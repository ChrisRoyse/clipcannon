"""Chronemic/pacing computation pipeline stage for ClipCannon.

Computes words-per-minute, pause ratios, speaker change density,
and pacing labels in 60-second sliding windows across the video.
This is an optional stage -- failure does not abort the pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all, fetch_one
from clipcannon.pipeline.orchestrator import StageResult
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

OPERATION = "chronemic_analysis"
STAGE = "chronemic"
WINDOW_MS = 60_000


def _get_duration_ms(db_path: Path, project_id: str) -> int:
    """Fetch project duration from the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        Duration in milliseconds, or 0 if not found.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT duration_ms FROM project WHERE project_id = ?",
            (project_id,),
        )
        if row and row.get("duration_ms") is not None:
            return int(row["duration_ms"])
        return 0
    finally:
        conn.close()


def _load_transcript_words(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | str]]:
    """Load all transcript words with timestamps.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of word dicts with start_ms, end_ms.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT tw.start_ms, tw.end_ms "
            "FROM transcript_words tw "
            "JOIN transcript_segments ts ON tw.segment_id = ts.segment_id "
            "WHERE ts.project_id = ? "
            "ORDER BY tw.start_ms",
            (project_id,),
        )
        return [{"start_ms": int(r["start_ms"]), "end_ms": int(r["end_ms"])} for r in rows]
    finally:
        conn.close()


def _load_silence_gaps(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int]]:
    """Load silence gaps with durations.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of gap dicts with start_ms, end_ms, duration_ms.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, duration_ms FROM silence_gaps "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "duration_ms": int(r["duration_ms"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_segments_with_speakers(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | str | None]]:
    """Load transcript segments with speaker IDs.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of segment dicts with start_ms, end_ms, speaker_id.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, speaker_id FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "speaker_id": r.get("speaker_id"),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _count_words_in_window(
    words: list[dict[str, int | str]],
    win_start: int,
    win_end: int,
) -> int:
    """Count transcript words that fall within the time window.

    A word is counted if its midpoint is within [win_start, win_end).

    Args:
        words: Sorted list of word dicts.
        win_start: Window start in milliseconds.
        win_end: Window end in milliseconds.

    Returns:
        Number of words in the window.
    """
    count = 0
    for w in words:
        mid = (int(w["start_ms"]) + int(w["end_ms"])) // 2
        if mid >= win_end:
            break
        if mid >= win_start:
            count += 1
    return count


def _compute_pause_ratio(
    gaps: list[dict[str, int]],
    win_start: int,
    win_end: int,
) -> float:
    """Compute the ratio of silence gap duration to window duration.

    Args:
        gaps: Sorted list of silence gap dicts.
        win_start: Window start in milliseconds.
        win_end: Window end in milliseconds.

    Returns:
        Ratio of silence to window duration (0.0-1.0).
    """
    window_dur = win_end - win_start
    if window_dur <= 0:
        return 0.0

    silence_ms = 0
    for g in gaps:
        g_start = int(g["start_ms"])
        g_end = int(g["end_ms"])
        if g_start >= win_end:
            break
        if g_end <= win_start:
            continue
        # Overlap with window
        overlap_start = max(g_start, win_start)
        overlap_end = min(g_end, win_end)
        silence_ms += max(0, overlap_end - overlap_start)

    return round(silence_ms / window_dur, 4)


def _count_speaker_changes(
    segments: list[dict[str, int | str | None]],
    win_start: int,
    win_end: int,
) -> int:
    """Count distinct speaker transitions within the time window.

    A change is counted each time the speaker_id differs between
    consecutive segments that overlap the window.

    Args:
        segments: Sorted list of segment dicts with speaker_id.
        win_start: Window start in milliseconds.
        win_end: Window end in milliseconds.

    Returns:
        Number of speaker transitions.
    """
    in_window: list[int | str | None] = []
    for seg in segments:
        seg_start = int(seg["start_ms"])
        seg_end = int(seg["end_ms"])
        if seg_start >= win_end:
            break
        if seg_end <= win_start:
            continue
        in_window.append(seg.get("speaker_id"))

    changes = 0
    for i in range(1, len(in_window)):
        if in_window[i] != in_window[i - 1]:
            changes += 1

    return changes


def _classify_pacing(
    wpm: float,
    pause_ratio: float,
    speaker_changes: int,
) -> str:
    """Classify the pacing of a window.

    Labels:
        fast_dialogue:  WPM > 150
        normal:         100 <= WPM <= 150
        slow_monologue: WPM < 100 AND speaker_changes == 0
        dead_air:       pause_ratio > 0.5

    When multiple conditions are met, dead_air takes priority.

    Args:
        wpm: Words per minute in the window.
        pause_ratio: Ratio of silence to window duration.
        speaker_changes: Number of speaker transitions.

    Returns:
        Pacing label string.
    """
    if pause_ratio > 0.5:
        return "dead_air"
    if wpm > 150:
        return "fast_dialogue"
    if wpm >= 100:
        return "normal"
    if speaker_changes == 0:
        return "slow_monologue"
    return "normal"


def _compute_pacing_windows(
    duration_ms: int,
    words: list[dict[str, int | str]],
    gaps: list[dict[str, int]],
    segments: list[dict[str, int | str | None]],
) -> list[dict[str, int | float | str]]:
    """Compute pacing for each 60-second window.

    Args:
        duration_ms: Total video duration in milliseconds.
        words: Sorted transcript words.
        gaps: Sorted silence gaps.
        segments: Sorted transcript segments with speaker IDs.

    Returns:
        List of pacing window dicts.
    """
    windows: list[dict[str, int | float | str]] = []

    win_start = 0
    while win_start < duration_ms:
        win_end = min(win_start + WINDOW_MS, duration_ms)
        actual_dur_ms = win_end - win_start

        word_count = _count_words_in_window(words, win_start, win_end)
        wpm = word_count / (actual_dur_ms / 60_000.0) if actual_dur_ms > 0 else 0.0

        pause_ratio = _compute_pause_ratio(gaps, win_start, win_end)
        speaker_changes = _count_speaker_changes(segments, win_start, win_end)
        label = _classify_pacing(wpm, pause_ratio, speaker_changes)

        windows.append(
            {
                "start_ms": win_start,
                "end_ms": win_end,
                "words_per_minute": round(wpm, 2),
                "pause_ratio": pause_ratio,
                "speaker_changes": speaker_changes,
                "label": label,
            }
        )

        win_start = win_end

    return windows


def _insert_pacing(
    db_path: Path,
    project_id: str,
    windows: list[dict[str, int | float | str]],
) -> int:
    """Insert pacing windows into the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        windows: Pacing window dicts.

    Returns:
        Number of rows inserted.
    """
    if not windows:
        return 0

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        rows: list[tuple[object, ...]] = [
            (
                project_id,
                int(w["start_ms"]),
                int(w["end_ms"]),
                float(w["words_per_minute"]),
                float(w["pause_ratio"]),
                int(w["speaker_changes"]),
                str(w["label"]),
            )
            for w in windows
        ]
        batch_insert(
            conn,
            "pacing",
            [
                "project_id",
                "start_ms",
                "end_ms",
                "words_per_minute",
                "pause_ratio",
                "speaker_changes",
                "label",
            ],
            rows,
        )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def run_chronemic(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the chronemic/pacing computation pipeline stage.

    Computes words-per-minute, pause ratio, speaker changes, and
    pacing labels for each 60-second window.

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
        duration_ms = await asyncio.to_thread(
            _get_duration_ms,
            db_path,
            project_id,
        )
        if duration_ms <= 0:
            logger.warning("No duration found, skipping chronemic analysis")
            return StageResult(
                success=True,
                operation=OPERATION,
                error_message="Skipped: no duration data",
            )

        words = await asyncio.to_thread(
            _load_transcript_words,
            db_path,
            project_id,
        )
        gaps = await asyncio.to_thread(
            _load_silence_gaps,
            db_path,
            project_id,
        )
        segments = await asyncio.to_thread(
            _load_segments_with_speakers,
            db_path,
            project_id,
        )

        windows = _compute_pacing_windows(duration_ms, words, gaps, segments)

        count = await asyncio.to_thread(
            _insert_pacing,
            db_path,
            project_id,
            windows,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Compute summary for provenance
        labels: dict[str, int] = {}
        for w in windows:
            lbl = str(w["label"])
            labels[lbl] = labels.get(lbl, 0) + 1

        summary = f"{count} windows: " + ", ".join(f"{k}={v}" for k, v in sorted(labels.items()))
        output_sha = sha256_string(summary)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                sha256=sha256_string(f"chronemic-{project_id}"),
            ),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=count,
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=f"Chronemic analysis: {summary}",
        )

        logger.info(
            "Chronemic analysis complete in %d ms: %s",
            elapsed_ms,
            summary,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Chronemic analysis failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
