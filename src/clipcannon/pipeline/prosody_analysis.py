"""Prosody analysis pipeline stage for ClipCannon.

Extracts prosodic features (F0 contour, energy, speaking rate, pitch
variation) from the vocal stem per sentence. Stores tagged clips with
their prosody metadata for use as voice cloning references.

Runs after source_separation + transcription. CPU-only (pyworld/numpy).
Each sentence-aligned clip is tagged with energy level, pitch range,
speaking rate, and a composite expressiveness score.

The prosody_segments table enables automatic reference clip selection
during voice synthesis -- pick the clip whose prosody matches the
target style (energetic, calm, emphatic, etc).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "prosody_analysis"
STAGE = "prosody"

# Minimum clip duration to analyze (ms)
MIN_CLIP_MS = 800
# Maximum clip duration (ms)
MAX_CLIP_MS = 15000

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
    metadata_json TEXT DEFAULT '{}',
    FOREIGN KEY (project_id) REFERENCES project(project_id)
)"""

_INSERT_SQL = """INSERT INTO prosody_segments (
    project_id, start_ms, end_ms, clip_path, transcript_text, word_count,
    f0_mean, f0_std, f0_min, f0_max, f0_range,
    energy_mean, energy_peak, energy_std,
    speaking_rate_wpm, pitch_contour_type, energy_level,
    has_emphasis, has_breath, prosody_score, emotion_label, metadata_json
) VALUES (?,?,?,?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?,?)"""


@dataclass
class ProsodyFeatures:
    """Prosodic features for a single segment."""

    f0_mean: float
    f0_std: float
    f0_min: float
    f0_max: float
    f0_range: float
    energy_mean: float
    energy_peak: float
    energy_std: float
    speaking_rate_wpm: float
    pitch_contour_type: str
    energy_level: str
    has_emphasis: bool
    has_breath: bool
    prosody_score: float


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


def _extract_prosody(audio: np.ndarray, sr: int, word_count: int,
                     duration_s: float) -> ProsodyFeatures:
    """Extract prosodic features from an audio segment."""
    import pyworld as pw

    # F0 extraction via WORLD vocoder
    f0, _timeaxis = pw.harvest(audio, sr, frame_period=5.0)
    voiced = f0[f0 > 0]

    if len(voiced) < 5:
        return ProsodyFeatures(
            f0_mean=0, f0_std=0, f0_min=0, f0_max=0, f0_range=0,
            energy_mean=0, energy_peak=0, energy_std=0,
            speaking_rate_wpm=0, pitch_contour_type="flat",
            energy_level="low", has_emphasis=False, has_breath=False,
            prosody_score=0,
        )

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

    # Speaking rate
    speaking_rate_wpm = (word_count / duration_s * 60) if duration_s > 0 else 0

    # Pitch contour classification
    if len(voiced) >= 10:
        first_quarter = np.mean(voiced[:len(voiced) // 4])
        last_quarter = np.mean(voiced[-len(voiced) // 4:])
        mid_half = np.mean(voiced[len(voiced) // 4: -len(voiced) // 4])

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

    # Energy level classification
    if energy_mean > 0.08:
        energy_level = "high"
    elif energy_mean > 0.03:
        energy_level = "medium"
    else:
        energy_level = "low"

    # Emphasis detection: large energy spikes relative to mean
    has_emphasis = bool(energy_peak > energy_mean * 2.5) if energy_mean > 0.01 else False

    # Breath detection: short low-energy dips between voiced regions
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
    # Higher = more expressive / better for voice cloning references
    score = 0.0
    # Pitch range contributes most (wide range = expressive)
    pitch_range_norm = min(f0_range / 100.0, 1.0)  # normalize: 100Hz range = max
    score += pitch_range_norm * 35

    # Pitch variation (std relative to mean)
    pitch_var_norm = min(f0_std / f0_mean, 0.3) / 0.3 if f0_mean > 0 else 0
    score += pitch_var_norm * 25

    # Energy variation (dynamic delivery)
    energy_var_norm = min(energy_std / energy_mean, 0.5) / 0.5 if energy_mean > 0.01 else 0
    score += energy_var_norm * 15

    # Speaking rate (natural conversational range scores highest)
    rate_score = 0
    if 120 <= speaking_rate_wpm <= 180:
        rate_score = 1.0
    elif 100 <= speaking_rate_wpm <= 200:
        rate_score = 0.7
    elif speaking_rate_wpm > 0:
        rate_score = 0.3
    score += rate_score * 10

    # Emphasis and breath add naturalness points
    if has_emphasis:
        score += 8
    if has_breath:
        score += 7

    return ProsodyFeatures(
        f0_mean=round(f0_mean, 2),
        f0_std=round(f0_std, 2),
        f0_min=round(f0_min, 2),
        f0_max=round(f0_max, 2),
        f0_range=round(f0_range, 2),
        energy_mean=round(energy_mean, 6),
        energy_peak=round(energy_peak, 6),
        energy_std=round(energy_std, 6),
        speaking_rate_wpm=round(speaking_rate_wpm, 1),
        pitch_contour_type=pitch_contour_type,
        energy_level=energy_level,
        has_emphasis=has_emphasis,
        has_breath=has_breath,
        prosody_score=round(min(score, 100.0), 1),
    )


def _extract_clip(
    vocal_path: Path, output_path: Path,
    start_ms: int, end_ms: int,
) -> bool:
    """Extract a WAV clip from the vocal stem using FFmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-nostdin",
        "-i", str(vocal_path),
        "-ss", f"{start_ms / 1000:.3f}",
        "-to", f"{end_ms / 1000:.3f}",
        "-ar", "24000", "-ac", "1",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0 and output_path.exists()


def _get_transcript_sentences(
    db_path: Path, project_id: str,
) -> list[dict[str, object]]:
    """Get sentence-aligned segments from transcript."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT start_ms, end_ms, text, word_count "
            "FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        ).fetchall()
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "text": str(r["text"]),
                "word_count": int(r["word_count"] or len(str(r["text"]).split())),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _get_emotion_for_time(
    db_path: Path, project_id: str, start_ms: int, end_ms: int,
) -> str:
    """Get the dominant emotion label for a time range."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT label FROM emotion_curve "
            "WHERE project_id = ? AND start_ms >= ? AND start_ms < ? "
            "ORDER BY score DESC LIMIT 1",
            (project_id, start_ms, end_ms),
        ).fetchall()
        if rows:
            return str(rows[0]["label"])
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return "neutral"


def _ensure_table(db_path: Path) -> None:
    """Create prosody_segments table if it doesn't exist."""
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
        conn.commit()
    finally:
        conn.close()


async def run_prosody_analysis(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Analyze prosodic features of vocal stem per sentence.

    Extracts F0 contour, energy, speaking rate from the vocal stem
    for each transcript sentence. Stores tagged clips with prosody
    metadata in the prosody_segments table.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    start_time = time.monotonic()

    try:
        # Find vocal stem
        vocal_path = project_dir / "stems" / "vocals.wav"
        if not vocal_path.exists():
            # Fallback to extracted audio
            vocal_path = project_dir / "audio.wav"
        if not vocal_path.exists():
            # Try any WAV in project root
            wavs = list(project_dir.glob("*.wav"))
            if wavs:
                vocal_path = wavs[0]
            else:
                return StageResult(
                    success=True, operation=OPERATION,
                    duration_ms=0,
                    provenance_record_id=None,
                )

        # Get transcript sentences
        sentences = _get_transcript_sentences(db_path, project_id)
        if not sentences:
            logger.info("Prosody analysis: no transcript segments, skipping")
            return StageResult(
                success=True, operation=OPERATION,
                duration_ms=int((time.monotonic() - start_time) * 1000),
                provenance_record_id=None,
            )

        # Load full vocal audio
        audio, sr = _load_audio(vocal_path)
        total_samples = len(audio)

        _ensure_table(db_path)

        # Clear old data
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "DELETE FROM prosody_segments WHERE project_id = ?",
                (project_id,),
            )
            conn.commit()
        finally:
            conn.close()

        # Create prosody clips directory
        prosody_dir = project_dir / "prosody_clips"
        prosody_dir.mkdir(parents=True, exist_ok=True)

        records: list[tuple] = []
        clip_count = 0

        for i, sent in enumerate(sentences):
            start_ms = int(sent["start_ms"])
            end_ms = int(sent["end_ms"])
            duration_ms = end_ms - start_ms

            if duration_ms < MIN_CLIP_MS or duration_ms > MAX_CLIP_MS:
                continue

            text = str(sent["text"]).strip()
            word_count = int(sent["word_count"])
            if word_count < 3:
                continue

            # Extract audio segment
            start_sample = int(start_ms / 1000 * sr)
            end_sample = int(end_ms / 1000 * sr)
            start_sample = max(0, min(start_sample, total_samples))
            end_sample = max(start_sample, min(end_sample, total_samples))

            segment_audio = audio[start_sample:end_sample]
            if len(segment_audio) < sr * 0.5:
                continue

            duration_s = len(segment_audio) / sr

            # Extract prosodic features
            features = _extract_prosody(segment_audio, sr, word_count, duration_s)

            # Extract clip file
            clip_name = f"prosody_{i:04d}.wav"
            clip_path = prosody_dir / clip_name
            clip_extracted = _extract_clip(vocal_path, clip_path, start_ms, end_ms)

            # Get emotion label from emotion_curve
            emotion = _get_emotion_for_time(db_path, project_id, start_ms, end_ms)

            records.append((
                project_id, start_ms, end_ms,
                str(clip_path) if clip_extracted else None,
                text, word_count,
                features.f0_mean, features.f0_std,
                features.f0_min, features.f0_max, features.f0_range,
                features.energy_mean, features.energy_peak, features.energy_std,
                features.speaking_rate_wpm, features.pitch_contour_type,
                features.energy_level,
                1 if features.has_emphasis else 0,
                1 if features.has_breath else 0,
                features.prosody_score, emotion,
                json.dumps({
                    "duration_s": round(duration_s, 2),
                    "sentence_index": i,
                }),
            ))

            if clip_extracted:
                clip_count += 1

        # Batch insert
        if records:
            conn = sqlite3.connect(str(db_path))
            try:
                conn.executemany(_INSERT_SQL, records)
                conn.commit()
            finally:
                conn.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        logger.info(
            "Prosody analysis: %d segments analyzed, %d clips extracted, took %dms",
            len(records), clip_count, elapsed_ms,
        )

        content_hash = sha256_string(
            f"prosody:{len(records)},clips:{clip_count}",
        )

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(vocal_path),
                sha256=sha256_string(str(vocal_path)),
            ),
            output_info=OutputInfo(
                sha256=content_hash,
                record_count=len(records),
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Prosody analysis: {len(records)} segments, "
                f"{clip_count} clips extracted"
            ),
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Prosody analysis failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
