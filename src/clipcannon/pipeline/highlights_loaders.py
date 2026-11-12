"""Database loaders feeding highlight scoring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one

if TYPE_CHECKING:
    from pathlib import Path


def _get_duration_ms(db_path: Path, project_id: str) -> int:
    """Fetch project duration.

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


def _load_emotion_curve(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | float]]:
    """Load emotion curve data.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of emotion dicts with start_ms, end_ms, energy.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, energy FROM emotion_curve "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "energy": float(r["energy"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_reactions(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int]]:
    """Load reaction events.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of reaction dicts with start_ms, end_ms.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms FROM reactions WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [{"start_ms": int(r["start_ms"]), "end_ms": int(r["end_ms"])} for r in rows]
    finally:
        conn.close()


def _load_topics(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | float]]:
    """Load topic segments with semantic density.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of topic dicts with start_ms, end_ms, semantic_density.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, semantic_density FROM topics "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "semantic_density": float(r["semantic_density"])
                if r.get("semantic_density") is not None
                else 0.5,
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_scenes(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | float]]:
    """Load scene data with quality.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of scene dicts with start_ms, end_ms, quality_avg.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, quality_avg FROM scenes "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "quality_avg": float(r["quality_avg"]) if r.get("quality_avg") is not None else 0.5,
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_segments_with_speakers(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | str | None]]:
    """Load transcript segments with speaker info.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of segment dicts with start_ms, end_ms, speaker_id, text.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, speaker_id, text "
            "FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "speaker_id": r.get("speaker_id"),
                "text": str(r.get("text", "")),
            }
            for r in rows
        ]
    finally:
        conn.close()
