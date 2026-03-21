"""Timeline and transcript API routes for the ClipCannon dashboard.

Provides endpoints for timeline visualization data (scenes, speakers,
emotion curves, topics, highlights), transcript search, and enhanced
project views with VUD summary statistics.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from clipcannon.db import fetch_all, fetch_one, get_connection
from clipcannon.db.queries import table_exists

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

router = APIRouter(tags=["timeline"])

PROJECTS_DIR = Path(
    os.environ.get(
        "CLIPCANNON_PROJECTS_DIR",
        str(Path.home() / ".clipcannon" / "projects"),
    )
)


def _get_db_path(project_id: str) -> Path:
    """Resolve the database path for a project.

    Args:
        project_id: The project identifier.

    Returns:
        Path to the project's analysis.db file.
    """
    return PROJECTS_DIR / project_id / "analysis.db"


def _safe_fetch_all(
    conn: sqlite3.Connection,
    table: str,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[dict[str, object]]:
    """Fetch all rows from a table, returning empty list if table missing.

    Args:
        conn: SQLite connection.
        table: Table name to check existence of.
        sql: Parameterized SQL query string.
        params: Query parameters.

    Returns:
        List of row dictionaries, or empty list if table does not exist.
    """
    if not table_exists(conn, table):
        return []
    try:
        return fetch_all(conn, sql, params)
    except Exception as exc:
        logger.debug("Query on table %s failed: %s", table, exc)
        return []


@router.get("/api/projects/{project_id}/timeline")
async def get_timeline(project_id: str) -> dict[str, object]:
    """Get timeline visualization data for a project.

    Returns scene boundaries, speaker segments, emotion curve, topics,
    and highlights as separate data series for timeline rendering.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with timeline data series.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        scenes = _safe_fetch_all(
            conn,
            "scenes",
            """
            SELECT scene_id, start_ms, end_ms, key_frame_path,
                   key_frame_timestamp_ms, visual_similarity_avg,
                   dominant_colors, shot_type, shot_type_confidence,
                   quality_avg
            FROM scenes
            WHERE project_id = ?
            ORDER BY start_ms
            """,
            (project_id,),
        )

        speakers = _safe_fetch_all(
            conn,
            "speakers",
            """
            SELECT s.speaker_id, s.label, s.total_speaking_ms,
                   s.speaking_pct
            FROM speakers s
            WHERE s.project_id = ?
            ORDER BY s.speaker_id
            """,
            (project_id,),
        )

        # Also get speaker segments from transcript for timeline positioning
        speaker_segments = _safe_fetch_all(
            conn,
            "transcript_segments",
            """
            SELECT ts.segment_id, ts.start_ms, ts.end_ms,
                   ts.speaker_id, s.label AS speaker_label, ts.text
            FROM transcript_segments ts
            LEFT JOIN speakers s ON ts.speaker_id = s.speaker_id
            WHERE ts.project_id = ?
            ORDER BY ts.start_ms
            """,
            (project_id,),
        )

        emotion_curve = _safe_fetch_all(
            conn,
            "emotion_curve",
            """
            SELECT start_ms, end_ms, arousal, valence, energy
            FROM emotion_curve
            WHERE project_id = ?
            ORDER BY start_ms
            """,
            (project_id,),
        )

        topics = _safe_fetch_all(
            conn,
            "topics",
            """
            SELECT topic_id, start_ms, end_ms, label, keywords,
                   coherence_score, semantic_density
            FROM topics
            WHERE project_id = ?
            ORDER BY start_ms
            """,
            (project_id,),
        )

        highlights = _safe_fetch_all(
            conn,
            "highlights",
            """
            SELECT highlight_id, start_ms, end_ms, type, score,
                   reason, emotion_score, reaction_score,
                   semantic_score, narrative_score, visual_score,
                   quality_score, speaker_score
            FROM highlights
            WHERE project_id = ?
            ORDER BY start_ms
            """,
            (project_id,),
        )

        return {
            "project_id": project_id,
            "scenes": scenes,
            "speakers": speakers,
            "speaker_segments": speaker_segments,
            "emotion_curve": emotion_curve,
            "topics": topics,
            "highlights": highlights,
        }
    except Exception as exc:
        logger.error("Timeline query failed for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "error": f"Timeline query failed: {exc}",
        }
    finally:
        conn.close()


@router.get("/api/projects/{project_id}/transcript-search")
async def search_transcript(
    project_id: str,
    q: str = Query(..., min_length=1, description="Search query text"),
    start_ms: int | None = Query(default=None, ge=0, description="Start time filter (ms)"),
    end_ms: int | None = Query(default=None, ge=0, description="End time filter (ms)"),
    limit: int = Query(default=100, ge=1, le=500, description="Max results"),
) -> dict[str, object]:
    """Search transcript segments by text with optional time range filter.

    Performs a case-insensitive LIKE search on transcript segment text.
    Results can be narrowed by start_ms and end_ms time boundaries.

    Args:
        project_id: The project identifier.
        q: Search query string.
        start_ms: Optional minimum start time in milliseconds.
        end_ms: Optional maximum end time in milliseconds.
        limit: Maximum number of results to return.

    Returns:
        Dictionary with matching transcript segments.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "query": q,
            "results": [],
            "count": 0,
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "transcript_segments"):
            return {
                "project_id": project_id,
                "query": q,
                "results": [],
                "count": 0,
            }

        sql = """
            SELECT ts.segment_id, ts.start_ms, ts.end_ms, ts.text,
                   ts.speaker_id, s.label AS speaker_label,
                   ts.language, ts.word_count
            FROM transcript_segments ts
            LEFT JOIN speakers s ON ts.speaker_id = s.speaker_id
            WHERE ts.project_id = ? AND ts.text LIKE ?
        """
        params: list[object] = [project_id, f"%{q}%"]

        if start_ms is not None:
            sql += " AND ts.start_ms >= ?"
            params.append(start_ms)

        if end_ms is not None:
            sql += " AND ts.end_ms <= ?"
            params.append(end_ms)

        sql += " ORDER BY ts.start_ms LIMIT ?"
        params.append(limit)

        results = fetch_all(conn, sql, tuple(params))

        return {
            "project_id": project_id,
            "query": q,
            "results": results,
            "count": len(results),
        }
    except Exception as exc:
        logger.error(
            "Transcript search failed for %s (q=%s): %s",
            project_id,
            q,
            exc,
        )
        return {
            "project_id": project_id,
            "query": q,
            "results": [],
            "count": 0,
            "error": f"Search failed: {exc}",
        }
    finally:
        conn.close()


@router.get("/api/projects/{project_id}/enhanced")
async def get_enhanced_project(project_id: str) -> dict[str, object]:
    """Get enhanced project view with VUD summary statistics.

    Returns aggregated stats including speaker count, topic count,
    highlight count, total scenes, content rating, and top 3 highlights.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with enhanced project data and VUD summary.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        # Speaker count
        speaker_count = 0
        if table_exists(conn, "speakers"):
            row = fetch_one(
                conn,
                "SELECT count(*) AS cnt FROM speakers WHERE project_id = ?",
                (project_id,),
            )
            speaker_count = int(row["cnt"]) if row else 0

        # Topic count
        topic_count = 0
        if table_exists(conn, "topics"):
            row = fetch_one(
                conn,
                "SELECT count(*) AS cnt FROM topics WHERE project_id = ?",
                (project_id,),
            )
            topic_count = int(row["cnt"]) if row else 0

        # Highlight count
        highlight_count = 0
        if table_exists(conn, "highlights"):
            row = fetch_one(
                conn,
                "SELECT count(*) AS cnt FROM highlights WHERE project_id = ?",
                (project_id,),
            )
            highlight_count = int(row["cnt"]) if row else 0

        # Total scenes
        scene_count = 0
        if table_exists(conn, "scenes"):
            row = fetch_one(
                conn,
                "SELECT count(*) AS cnt FROM scenes WHERE project_id = ?",
                (project_id,),
            )
            scene_count = int(row["cnt"]) if row else 0

        # Content rating
        content_rating = "unknown"
        if table_exists(conn, "content_safety"):
            row = fetch_one(
                conn,
                "SELECT content_rating FROM content_safety WHERE project_id = ?",
                (project_id,),
            )
            if row and row.get("content_rating"):
                content_rating = str(row["content_rating"])

        # Top 3 highlights by score
        top_highlights: list[dict[str, object]] = []
        if table_exists(conn, "highlights"):
            top_highlights = fetch_all(
                conn,
                """
                SELECT highlight_id, start_ms, end_ms, type, score, reason
                FROM highlights
                WHERE project_id = ?
                ORDER BY score DESC
                LIMIT 3
                """,
                (project_id,),
            )

        # Project metadata
        project_meta: dict[str, object] | None = None
        if table_exists(conn, "project"):
            project_meta = fetch_one(
                conn,
                "SELECT * FROM project WHERE project_id = ?",
                (project_id,),
            )

        return {
            "project_id": project_id,
            "metadata": project_meta,
            "vud_summary": {
                "speaker_count": speaker_count,
                "topic_count": topic_count,
                "highlight_count": highlight_count,
                "total_scenes": scene_count,
                "content_rating": content_rating,
                "top_highlights": top_highlights,
            },
        }
    except Exception as exc:
        logger.error("Enhanced project query failed for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "error": f"Enhanced query failed: {exc}",
        }
    finally:
        conn.close()
