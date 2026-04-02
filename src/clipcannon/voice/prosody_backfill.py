"""Backfill prosody analysis for existing voice training clips.

Runs prosody extraction on prepared voice data clips (in voice_data/<name>/wavs)
when the original ingest projects no longer exist. Stores results in a prosody.db
alongside the voice data so prosody_select can find them.

Usage (as module):
    from clipcannon.voice.prosody_backfill import backfill_voice_prosody
    await backfill_voice_prosody("boris")

Usage (CLI):
    python -m clipcannon.voice.prosody_backfill boris
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Re-use the same schema from prosody_analysis
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS prosody_segments (
    segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    clip_path TEXT,
    transcript_text TEXT NOT NULL DEFAULT '',
    word_count INTEGER DEFAULT 0,
    f0_mean REAL DEFAULT 0,
    f0_std REAL DEFAULT 0,
    f0_min REAL DEFAULT 0,
    f0_max REAL DEFAULT 0,
    f0_range REAL DEFAULT 0,
    energy_mean REAL DEFAULT 0,
    energy_peak REAL DEFAULT 0,
    energy_std REAL DEFAULT 0,
    speaking_rate_wpm REAL DEFAULT 0,
    pitch_contour_type TEXT DEFAULT 'flat',
    energy_level TEXT DEFAULT 'medium',
    has_emphasis INTEGER DEFAULT 0,
    has_breath INTEGER DEFAULT 0,
    prosody_score REAL DEFAULT 0,
    emotion_label TEXT DEFAULT 'neutral',
    metadata_json TEXT DEFAULT '{}'
)"""


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load audio as mono float64."""
    from scipy.io import wavfile

    sr, data = wavfile.read(str(audio_path))
    if data.dtype == np.int16:
        audio = data.astype(np.float64) / 32768.0
    elif data.dtype == np.int32:
        audio = data.astype(np.float64) / 2147483648.0
    elif data.dtype in (np.float32, np.float64):
        audio = data.astype(np.float64)
    else:
        audio = data.astype(np.float64)

    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    return audio, sr


def _extract_prosody(
    audio: np.ndarray, sr: int, word_count: int, duration_s: float,
) -> dict[str, object]:
    """Extract prosodic features from an audio clip."""
    import pyworld as pw

    f0, _timeaxis = pw.harvest(audio, sr, frame_period=5.0)
    voiced = f0[f0 > 0]

    if len(voiced) < 5:
        return {
            "f0_mean": 0, "f0_std": 0, "f0_min": 0, "f0_max": 0, "f0_range": 0,
            "energy_mean": 0, "energy_peak": 0, "energy_std": 0,
            "speaking_rate_wpm": 0, "pitch_contour_type": "flat",
            "energy_level": "low", "has_emphasis": False, "has_breath": False,
            "prosody_score": 0,
        }

    f0_mean = float(np.mean(voiced))
    f0_std = float(np.std(voiced))
    f0_min = float(np.min(voiced))
    f0_max = float(np.max(voiced))
    f0_range = f0_max - f0_min

    # Energy (RMS in 50ms windows)
    hop = int(sr * 0.05)
    n_frames = max(1, len(audio) // hop)
    rms = np.array([
        np.sqrt(np.mean(audio[i * hop:(i + 1) * hop] ** 2))
        for i in range(n_frames)
    ])
    energy_mean = float(np.mean(rms))
    energy_peak = float(np.max(rms))
    energy_std = float(np.std(rms))

    speaking_rate_wpm = (word_count / duration_s * 60) if duration_s > 0 else 0

    # Pitch contour classification
    if len(voiced) >= 10:
        first_quarter = np.mean(voiced[:len(voiced) // 4])
        last_quarter = np.mean(voiced[-len(voiced) // 4:])

        if last_quarter > first_quarter * 1.1:
            pitch_contour_type = "rising"
        elif first_quarter > last_quarter * 1.1:
            pitch_contour_type = "falling"
        elif f0_std > f0_mean * 0.15:
            pitch_contour_type = "varied"
        else:
            pitch_contour_type = "flat"
    else:
        pitch_contour_type = "flat"

    # Energy level
    if energy_mean > 0.08:
        energy_level = "high"
    elif energy_mean > 0.03:
        energy_level = "medium"
    else:
        energy_level = "low"

    # Emphasis detection
    has_emphasis = bool(energy_peak > energy_mean * 2.5) if energy_mean > 0.01 else False

    # Breath detection
    has_breath = False
    if len(rms) > 10:
        low_energy = rms < energy_mean * 0.2
        dip_count = 0
        in_dip = False
        for val in low_energy:
            if val and not in_dip:
                dip_count += 1
                in_dip = True
            elif not val:
                in_dip = False
        has_breath = dip_count >= 2

    # Composite prosody score (0-100)
    score = 0.0
    pitch_range_norm = min(f0_range / 100.0, 1.0)
    score += pitch_range_norm * 35

    pitch_var_norm = min(f0_std / f0_mean, 0.3) / 0.3 if f0_mean > 0 else 0
    score += pitch_var_norm * 25

    energy_var_norm = min(energy_std / energy_mean, 0.5) / 0.5 if energy_mean > 0.01 else 0
    score += energy_var_norm * 15

    rate_score = 0
    if 120 <= speaking_rate_wpm <= 180:
        rate_score = 1.0
    elif 100 <= speaking_rate_wpm <= 200:
        rate_score = 0.7
    elif speaking_rate_wpm > 0:
        rate_score = 0.3
    score += rate_score * 10

    if has_emphasis:
        score += 8
    if has_breath:
        score += 7

    return {
        "f0_mean": round(f0_mean, 2),
        "f0_std": round(f0_std, 2),
        "f0_min": round(f0_min, 2),
        "f0_max": round(f0_max, 2),
        "f0_range": round(f0_range, 2),
        "energy_mean": round(energy_mean, 6),
        "energy_peak": round(energy_peak, 6),
        "energy_std": round(energy_std, 6),
        "speaking_rate_wpm": round(speaking_rate_wpm, 1),
        "pitch_contour_type": pitch_contour_type,
        "energy_level": energy_level,
        "has_emphasis": has_emphasis,
        "has_breath": has_breath,
        "prosody_score": round(min(score, 100.0), 1),
    }


def _load_transcript_map(voice_dir: Path) -> dict[str, str]:
    """Load clip -> transcript text mapping from train.jsonl."""
    text_map: dict[str, str] = {}
    jsonl_path = voice_dir / "train.jsonl"
    if jsonl_path.exists():
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    audio_path = entry.get("audio", "")
                    text = entry.get("text", "")
                    if audio_path and text:
                        text_map[Path(audio_path).name] = text
                except json.JSONDecodeError:
                    continue
    return text_map


async def backfill_voice_prosody(
    voice_name: str,
    voice_data_base: Path | None = None,
) -> dict[str, object]:
    """Run prosody analysis on all existing voice training clips.

    Args:
        voice_name: Voice profile name (e.g. "boris").
        voice_data_base: Base voice data dir. Defaults to ~/.clipcannon/voice_data.

    Returns:
        Summary dict with counts and stats.
    """
    if voice_data_base is None:
        voice_data_base = Path.home() / ".clipcannon" / "voice_data"

    voice_dir = voice_data_base / voice_name
    wavs_dir = voice_dir / "wavs"

    if not wavs_dir.exists():
        return {"error": f"No voice data found at {wavs_dir}"}

    # Collect all WAV clips (exclude _trimmed variants)
    all_wavs = sorted([
        w for w in wavs_dir.glob("*.wav")
        if "_trimmed" not in w.name
    ])
    if not all_wavs:
        return {"error": "No WAV clips found"}

    # Load transcript text mapping
    text_map = _load_transcript_map(voice_dir)

    # Create/reset prosody DB
    db_path = voice_dir / "prosody.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_prosody_project "
            "ON prosody_segments(project_id, prosody_score DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_prosody_style "
            "ON prosody_segments(project_id, energy_level, pitch_contour_type)"
        )
        # Clear old data for this voice
        conn.execute(
            "DELETE FROM prosody_segments WHERE project_id = ?",
            (voice_name,),
        )
        conn.commit()
    finally:
        conn.close()

    start_time = time.monotonic()
    records: list[tuple] = []
    errors = 0

    logger.info("Prosody backfill: processing %d clips for voice '%s'", len(all_wavs), voice_name)

    for i, wav_path in enumerate(all_wavs):
        try:
            audio, sr = _load_audio(wav_path)
            duration_s = len(audio) / sr

            # Skip very short clips
            if duration_s < 0.8:
                continue

            text = text_map.get(wav_path.name, "")
            word_count = len(text.split()) if text else 0

            features = _extract_prosody(audio, sr, word_count, duration_s)

            start_ms = 0
            end_ms = int(duration_s * 1000)

            records.append((
                voice_name, start_ms, end_ms,
                str(wav_path),
                text, word_count,
                features["f0_mean"], features["f0_std"],
                features["f0_min"], features["f0_max"], features["f0_range"],
                features["energy_mean"], features["energy_peak"], features["energy_std"],
                features["speaking_rate_wpm"], features["pitch_contour_type"],
                features["energy_level"],
                1 if features["has_emphasis"] else 0,
                1 if features["has_breath"] else 0,
                features["prosody_score"], "neutral",
                json.dumps({
                    "duration_s": round(duration_s, 2),
                    "clip_index": i,
                    "source": "backfill",
                }),
            ))

            if (i + 1) % 50 == 0:
                logger.info("Prosody backfill: %d/%d clips processed", i + 1, len(all_wavs))

        except Exception as exc:
            errors += 1
            logger.warning("Prosody backfill: failed on %s: %s", wav_path.name, exc)

    # Batch insert
    if records:
        insert_sql = """INSERT INTO prosody_segments (
            project_id, start_ms, end_ms, clip_path, transcript_text, word_count,
            f0_mean, f0_std, f0_min, f0_max, f0_range,
            energy_mean, energy_peak, energy_std,
            speaking_rate_wpm, pitch_contour_type, energy_level,
            has_emphasis, has_breath, prosody_score, emotion_label, metadata_json
        ) VALUES (?,?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?)"""

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executemany(insert_sql, records)
            conn.commit()
        finally:
            conn.close()

    elapsed_s = time.monotonic() - start_time

    # Compute summary stats
    stats = _compute_stats(db_path, voice_name)

    logger.info(
        "Prosody backfill complete: %d segments, %d errors, %.1fs",
        len(records), errors, elapsed_s,
    )

    return {
        "voice_name": voice_name,
        "total_clips_scanned": len(all_wavs),
        "segments_stored": len(records),
        "errors": errors,
        "elapsed_s": round(elapsed_s, 2),
        "prosody_db": str(db_path),
        "stats": stats,
    }


def _compute_stats(db_path: Path, voice_name: str) -> dict[str, object]:
    """Compute summary stats from the prosody DB."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT "
            "  COUNT(*) as total, "
            "  AVG(prosody_score) as avg_score, "
            "  MAX(prosody_score) as max_score, "
            "  MIN(prosody_score) as min_score, "
            "  AVG(f0_mean) as avg_f0, "
            "  AVG(f0_range) as avg_pitch_range, "
            "  AVG(speaking_rate_wpm) as avg_rate "
            "FROM prosody_segments WHERE project_id = ?",
            (voice_name,),
        ).fetchone()

        by_energy = conn.execute(
            "SELECT energy_level, COUNT(*) as n "
            "FROM prosody_segments WHERE project_id = ? "
            "GROUP BY energy_level ORDER BY n DESC",
            (voice_name,),
        ).fetchall()

        by_contour = conn.execute(
            "SELECT pitch_contour_type, COUNT(*) as n "
            "FROM prosody_segments WHERE project_id = ? "
            "GROUP BY pitch_contour_type ORDER BY n DESC",
            (voice_name,),
        ).fetchall()

        top_clips = conn.execute(
            "SELECT clip_path, prosody_score, transcript_text, "
            "  pitch_contour_type, energy_level, speaking_rate_wpm "
            "FROM prosody_segments WHERE project_id = ? "
            "ORDER BY prosody_score DESC LIMIT 5",
            (voice_name,),
        ).fetchall()

        return {
            "total": int(row["total"]),
            "avg_prosody_score": round(float(row["avg_score"]), 1),
            "max_prosody_score": round(float(row["max_score"]), 1),
            "min_prosody_score": round(float(row["min_score"]), 1),
            "avg_f0_hz": round(float(row["avg_f0"]), 1),
            "avg_pitch_range_hz": round(float(row["avg_pitch_range"]), 1),
            "avg_speaking_rate_wpm": round(float(row["avg_rate"]), 1),
            "energy_distribution": {str(r["energy_level"]): int(r["n"]) for r in by_energy},
            "contour_distribution": {str(r["pitch_contour_type"]): int(r["n"]) for r in by_contour},
            "top_clips": [
                {
                    "clip": Path(str(r["clip_path"])).name,
                    "score": float(r["prosody_score"]),
                    "text": str(r["transcript_text"])[:60],
                    "contour": str(r["pitch_contour_type"]),
                    "energy": str(r["energy_level"]),
                    "wpm": float(r["speaking_rate_wpm"]),
                }
                for r in top_clips
            ],
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    name = sys.argv[1] if len(sys.argv) > 1 else "boris"
    result = asyncio.run(backfill_voice_prosody(name))
    print(json.dumps(result, indent=2))
