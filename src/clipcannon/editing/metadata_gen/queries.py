"""Database queries feeding metadata generation for an edit's time range."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all

if TYPE_CHECKING:
    from pathlib import Path


# ============================================================
# Data extraction helpers
# ============================================================
def _fetch_topics_for_range(
    db_path: Path,
    project_id: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, object]]:
    """Fetch topics overlapping the given time range.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        start_ms: Range start in milliseconds.
        end_ms: Range end in milliseconds.

    Returns:
        List of topic rows as dicts.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT label, keywords, coherence_score "
            "FROM topics "
            "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
            "ORDER BY coherence_score DESC",
            (project_id, end_ms, start_ms),
        )
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _fetch_highlights_for_range(
    db_path: Path,
    project_id: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, object]]:
    """Fetch highlights overlapping the given time range, sorted by score.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        start_ms: Range start in milliseconds.
        end_ms: Range end in milliseconds.

    Returns:
        List of highlight rows as dicts.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, type, score, reason "
            "FROM highlights "
            "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
            "ORDER BY score DESC",
            (project_id, end_ms, start_ms),
        )
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _fetch_transcript_for_range(
    db_path: Path,
    project_id: str,
    start_ms: int,
    end_ms: int,
    max_chars: int = 2000,
) -> str:
    """Fetch transcript text for the given time range.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        start_ms: Range start in milliseconds.
        end_ms: Range end in milliseconds.
        max_chars: Maximum characters to return.

    Returns:
        Concatenated transcript text.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT text FROM transcript_segments "
            "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
            "ORDER BY start_ms",
            (project_id, end_ms, start_ms),
        )
    finally:
        conn.close()

    parts: list[str] = []
    total = 0
    for row in rows:
        text = str(row.get("text", ""))
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining > 0:
                parts.append(text[:remaining])
            break
        parts.append(text)
        total += len(text)

    return " ".join(parts).strip()


def _get_edit_time_range(
    edl_json: dict[str, object],
) -> tuple[int, int]:
    """Extract the min start and max end from an EDL's segments.

    Args:
        edl_json: Parsed EDL JSON dict.

    Returns:
        Tuple of (min_source_start_ms, max_source_end_ms).
    """
    segments = edl_json.get("segments", [])
    if not segments:
        return (0, 0)

    starts = [int(s.get("source_start_ms", 0)) for s in segments]  # type: ignore[union-attr]
    ends = [int(s.get("source_end_ms", 0)) for s in segments]  # type: ignore[union-attr]
    return (min(starts), max(ends))
