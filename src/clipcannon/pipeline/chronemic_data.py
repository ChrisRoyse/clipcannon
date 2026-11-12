"""Database loaders and pacing storage for the chronemic stage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all, fetch_one

if TYPE_CHECKING:
    from pathlib import Path


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
