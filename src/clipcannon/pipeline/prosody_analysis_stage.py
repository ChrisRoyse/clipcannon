"""Prosody storage, transcript lookups and the run_prosody_analysis entry point."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import TYPE_CHECKING

from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.prosody_features import _extract_clip, _extract_prosody, _load_audio
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

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
