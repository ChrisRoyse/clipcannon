"""Understanding MCP tools for ClipCannon.

Provides ingest, VUD summary, analytics, and transcript tools. Shared
helpers (_error, _db_path, etc.) are used by understanding_visual.py
and understanding_search.py.
"""

from __future__ import annotations

import logging
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.exceptions import ClipCannonError

logger = logging.getLogger(__name__)

_TRANSCRIPT_PAGE_MS = 900_000  # 15-minute transcript pages


def _error(code: str, message: str, details: dict[str, object] | None = None) -> dict[str, object]:
    """Build standardized error response dict."""
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _projects_dir() -> Path:
    """Resolve projects base directory from config or default."""
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def _db_path(project_id: str) -> Path:
    """Build database path for a project."""
    return _projects_dir() / project_id / "analysis.db"


def _project_dir(project_id: str) -> Path:
    """Build project directory path."""
    return _projects_dir() / project_id


def _validate_project(
    project_id: str, required_status: str | None = "ready"
) -> dict[str, object] | None:
    """Validate project exists and check status. Returns error dict or None."""
    db = _db_path(project_id)
    if not db.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")
    if required_status is not None:
        conn = get_connection(db, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(conn, "SELECT status FROM project WHERE project_id = ?", (project_id,))
        finally:
            conn.close()
        if row is None:
            return _error("PROJECT_NOT_FOUND", f"No project record: {project_id}")
        status = str(row.get("status", ""))
        if required_status == "created" and status != "created":
            return _error(
                "INVALID_STATE", f"Project must be 'created' to ingest, current: {status}"
            )
        if required_status == "ready" and status not in ("ready", "ready_degraded", "analyzing"):
            return _error("INVALID_STATE", f"Project not ready, current status: {status}")
    return None


async def clipcannon_ingest(
    project_id: str, options: dict[str, object] | None = None
) -> dict[str, object]:
    """Run the full analysis pipeline on a created project."""
    err = _validate_project(project_id, required_status="created")
    if err is not None:
        return err

    db = _db_path(project_id)
    proj_dir = _project_dir(project_id)

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        execute(
            conn,
            "UPDATE project SET status = 'analyzing',"
            " updated_at = datetime('now')"
            " WHERE project_id = ?",
            (project_id,),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        config = ClipCannonConfig.load()
    except ClipCannonError:
        return _error("CONFIG_ERROR", "Failed to load ClipCannon configuration")

    from clipcannon.pipeline.registry import build_pipeline

    orchestrator = build_pipeline(config)

    try:
        result = await orchestrator.run(project_id, db, proj_dir)
    except Exception as exc:
        logger.exception("Pipeline failed for project %s", project_id)
        err_conn = get_connection(db, enable_vec=False, dict_rows=False)
        try:
            execute(
                err_conn,
                "UPDATE project SET status = 'error',"
                " updated_at = datetime('now')"
                " WHERE project_id = ?",
                (project_id,),
            )
            err_conn.commit()
        finally:
            err_conn.close()
        return _error("PIPELINE_ERROR", f"Pipeline failed: {exc}")

    # Update project status based on pipeline result
    final_status = "ready" if result.success else "ready_degraded"
    if result.failed_required:
        final_status = "error"

    status_conn = get_connection(db, enable_vec=False, dict_rows=False)
    try:
        execute(
            status_conn,
            "UPDATE project SET status = ?, updated_at = datetime('now') "
            "WHERE project_id = ?",
            (final_status, project_id),
        )
        status_conn.commit()
    finally:
        status_conn.close()

    return {
        "project_id": project_id,
        "status": final_status,
        "pipeline_success": result.success,
        "total_duration_ms": result.total_duration_ms,
        "stages_completed": sum(1 for s in result.stage_results.values() if s.success),
        "stages_failed": len(result.failed_required) + len(result.failed_optional),
        "failed_required": result.failed_required,
        "failed_optional": result.failed_optional,
    }


async def clipcannon_get_transcript(
    project_id: str,
    start_ms: int = 0,
    end_ms: int | None = None,
    detail: str = "text",
) -> dict[str, object]:
    """Get transcript with optional word-level timestamps. 15-min pages with pagination.

    Args:
        project_id: Project identifier.
        start_ms: Start time in milliseconds (default 0).
        end_ms: End time in ms (default start_ms + 900000).
        detail: Detail level — ``"text"`` (compact, segments only) or
            ``"words"`` (includes word-level timestamps). Default ``"text"``.

    Returns:
        Dict with transcript segments and pagination info.
    """
    if detail not in ("text", "words"):
        return _error(
            "INVALID_PARAMETER",
            f"detail must be 'text' or 'words', got '{detail}'",
        )

    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err
    if end_ms is None:
        end_ms = start_ms + _TRANSCRIPT_PAGE_MS

    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        segments = fetch_all(
            conn,
            "SELECT segment_id, start_ms, end_ms, text,"
            " speaker_id, language, word_count"
            " FROM transcript_segments"
            " WHERE project_id = ?"
            " AND start_ms < ? AND end_ms > ?"
            " ORDER BY start_ms",
            (project_id, end_ms, start_ms),
        )

        enriched: list[dict[str, object]] = []
        for seg in segments:
            sd = dict(seg)
            if detail == "words":
                words = fetch_all(
                    conn,
                    "SELECT word, start_ms, end_ms,"
                    " confidence, speaker_id"
                    " FROM transcript_words"
                    " WHERE segment_id = ?"
                    " ORDER BY start_ms",
                    (int(seg["segment_id"]),),
                )
                sd["words"] = [dict(w) for w in words]
            enriched.append(sd)

        hm_row = fetch_one(
            conn,
            "SELECT count(*) as cnt"
            " FROM transcript_segments"
            " WHERE project_id = ? AND start_ms >= ?",
            (project_id, end_ms),
        )
        has_more = int(hm_row["cnt"]) > 0 if hm_row else False

        dur_row = fetch_one(
            conn, "SELECT duration_ms FROM project WHERE project_id = ?", (project_id,)
        )
        total_dur = int(dur_row["duration_ms"]) if dur_row else 0
    finally:
        conn.close()

    return {
        "project_id": project_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "total_duration_ms": total_dur,
        "segment_count": len(enriched),
        "segments": enriched,
        "has_more": has_more,
        "next_start_ms": end_ms if has_more else None,
    }
