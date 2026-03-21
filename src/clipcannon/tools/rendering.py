"""Rendering MCP tools for ClipCannon.

Provides tools for rendering edits to video files, checking render
status, and batch rendering multiple edits concurrently. Each render
charges 2 credits via the license server.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from clipcannon.billing.license_client import LicenseClient
from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.editing.edl import EditDecisionList
from clipcannon.exceptions import ClipCannonError
from clipcannon.rendering.batch import render_batch
from clipcannon.rendering.renderer import RenderEngine
from clipcannon.tools.rendering_defs import RENDERING_TOOL_DEFINITIONS

__all__ = [
    "RENDERING_TOOL_DEFINITIONS",
    "dispatch_rendering_tool",
]

logger = logging.getLogger(__name__)

# Credits charged per render operation
_RENDER_CREDITS = 2


# ============================================================
# HELPERS
# ============================================================
def _error(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Build standardized error response dict.

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        details: Optional additional context.

    Returns:
        Error response dictionary.
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


def _projects_dir() -> Path:
    """Resolve projects base directory from config or default.

    Returns:
        Absolute path to the projects directory.
    """
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def _db_path(project_id: str) -> Path:
    """Build database path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project's analysis.db.
    """
    return _projects_dir() / project_id / "analysis.db"


def _project_dir(project_id: str) -> Path:
    """Build project directory path.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project directory.
    """
    return _projects_dir() / project_id


def _validate_project(project_id: str) -> dict[str, object] | None:
    """Validate that a project exists.

    Args:
        project_id: Project identifier.

    Returns:
        Error dict if validation fails, None on success.
    """
    db = _db_path(project_id)
    if not db.exists():
        return _error(
            "PROJECT_NOT_FOUND",
            f"Project not found: {project_id}",
        )
    return None


def _load_edl(
    project_id: str, edit_id: str
) -> tuple[EditDecisionList | None, dict[str, object] | None]:
    """Load an EDL from the database.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.

    Returns:
        Tuple of (EDL, None) on success or (None, error_dict) on failure.
    """
    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
    finally:
        conn.close()

    if row is None:
        return None, _error(
            "EDIT_NOT_FOUND",
            f"Edit not found: {edit_id}",
            {"edit_id": edit_id, "project_id": project_id},
        )

    status = str(row.get("status", ""))
    if status not in ("draft", "rendered", "approved"):
        return None, _error(
            "INVALID_STATE",
            f"Cannot render edit in '{status}' status",
            {"edit_id": edit_id, "status": status},
        )

    try:
        edl_data = json.loads(str(row["edl_json"]))
        edl = EditDecisionList(**edl_data)
    except Exception as exc:
        return None, _error(
            "INTERNAL_ERROR",
            f"Failed to parse EDL: {exc}",
            {"edit_id": edit_id},
        )

    return edl, None


# ============================================================
# TOOL 1: clipcannon_render
# ============================================================
async def clipcannon_render(
    project_id: str,
    edit_id: str,
) -> dict[str, object]:
    """Render an edit to a video file.

    Loads the EDL, charges credits, executes the render pipeline,
    and returns the result with output path and metadata.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.

    Returns:
        Render result dict or error response.
    """
    start_time = time.monotonic()

    # Validate project
    err = _validate_project(project_id)
    if err is not None:
        return err

    # Load EDL
    edl, err = _load_edl(project_id, edit_id)
    if err is not None:
        return err
    assert edl is not None  # noqa: S101

    # Update edit status to rendering
    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=False)
    try:
        execute(
            conn,
            "UPDATE edits SET status = 'rendering', "
            "updated_at = datetime('now') "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Charge credits
    license_client = LicenseClient()
    try:
        charge_result = await license_client.charge(
            operation="render",
            credits=_RENDER_CREDITS,
            project_id=project_id,
        )
        if not charge_result.success:
            logger.warning(
                "Credit charge failed for render %s/%s: %s",
                project_id,
                edit_id,
                charge_result.error,
            )
    except Exception as exc:
        logger.warning(
            "License server unavailable for render %s/%s: %s",
            project_id,
            edit_id,
            exc,
        )
    finally:
        await license_client.close()

    # Execute render
    try:
        config = ClipCannonConfig.load()
        engine = RenderEngine(config)
        result = await engine.render(
            edl=edl,
            project_dir=_project_dir(project_id),
            db_path=db,
        )
    except Exception as exc:
        # Update edit status back to draft on failure
        conn = get_connection(db, enable_vec=False, dict_rows=False)
        try:
            execute(
                conn,
                "UPDATE edits SET status = 'failed', "
                "updated_at = datetime('now') "
                "WHERE edit_id = ? AND project_id = ?",
                (edit_id, project_id),
            )
            conn.commit()
        finally:
            conn.close()

        logger.exception(
            "Render failed for %s/%s",
            project_id,
            edit_id,
        )
        return _error(
            "RENDER_FAILED",
            f"Render failed: {exc}",
            {"edit_id": edit_id, "project_id": project_id},
        )

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    if not result.success:
        return _error(
            "RENDER_FAILED",
            result.error_message or "Render failed",
            {
                "render_id": result.render_id,
                "edit_id": edit_id,
                "project_id": project_id,
            },
        )

    logger.info(
        "Render completed: %s/%s -> %s (%dms)",
        project_id,
        edit_id,
        result.render_id,
        elapsed_ms,
    )

    return {
        "render_id": result.render_id,
        "status": "completed",
        "output_path": str(result.output_path) if result.output_path else None,
        "file_size_bytes": result.file_size_bytes,
        "duration_ms": result.duration_ms,
        "render_duration_ms": result.render_duration_ms,
        "thumbnail_path": str(result.thumbnail_path) if result.thumbnail_path else None,
        "output_sha256": result.output_sha256,
        "credits_charged": _RENDER_CREDITS,
        "elapsed_ms": elapsed_ms,
    }


# ============================================================
# TOOL 2: clipcannon_render_status
# ============================================================
async def clipcannon_render_status(
    project_id: str,
    render_id: str,
) -> dict[str, object]:
    """Check the status of a render job.

    Args:
        project_id: Project identifier.
        render_id: Render identifier.

    Returns:
        Render status dict or error response.
    """
    err = _validate_project(project_id)
    if err is not None:
        return err

    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT * FROM renders "
            "WHERE render_id = ? AND project_id = ?",
            (render_id, project_id),
        )
    finally:
        conn.close()

    if row is None:
        return _error(
            "RENDER_NOT_FOUND",
            f"Render not found: {render_id}",
            {"render_id": render_id, "project_id": project_id},
        )

    return {
        "render_id": str(row["render_id"]),
        "edit_id": str(row["edit_id"]),
        "status": str(row["status"]),
        "profile": str(row.get("profile", "")),
        "output_path": str(row["output_path"]) if row.get("output_path") else None,
        "output_sha256": str(row["output_sha256"]) if row.get("output_sha256") else None,
        "file_size_bytes": int(row["file_size_bytes"]) if row.get("file_size_bytes") else 0,
        "duration_ms": int(row["duration_ms"]) if row.get("duration_ms") else 0,
        "resolution": str(row.get("resolution", "")),
        "codec": str(row.get("codec", "")),
        "thumbnail_path": str(row["thumbnail_path"]) if row.get("thumbnail_path") else None,
        "render_duration_ms": (
            int(row["render_duration_ms"]) if row.get("render_duration_ms") else 0
        ),
        "error_message": str(row["error_message"]) if row.get("error_message") else None,
        "created_at": str(row.get("created_at", "")),
        "completed_at": str(row["completed_at"]) if row.get("completed_at") else None,
    }


# ============================================================
# TOOL 3: clipcannon_render_batch
# ============================================================
async def clipcannon_render_batch(
    project_id: str,
    edit_ids: list[str],
) -> dict[str, object]:
    """Render multiple edits concurrently.

    Loads all EDLs, charges credits for each, and renders them
    with concurrency limited by config.rendering.max_parallel_renders.

    Args:
        project_id: Project identifier.
        edit_ids: List of edit identifiers to render.

    Returns:
        Batch render results dict or error response.
    """
    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err

    if not edit_ids:
        return _error(
            "INVALID_PARAMETER",
            "At least one edit_id is required",
            {"edit_ids_count": 0},
        )

    # Load all EDLs
    edl_list: list[EditDecisionList] = []
    errors: list[dict[str, object]] = []

    for eid in edit_ids:
        edl, load_err = _load_edl(project_id, eid)
        if load_err is not None:
            errors.append({"edit_id": eid, "error": load_err})
        elif edl is not None:
            edl_list.append(edl)

    if not edl_list:
        return _error(
            "NO_VALID_EDITS",
            "No valid edits found for batch rendering",
            {"errors": errors},  # type: ignore[dict-item]
        )

    # Charge credits for all renders
    total_credits = _RENDER_CREDITS * len(edl_list)
    license_client = LicenseClient()
    try:
        charge_result = await license_client.charge(
            operation="render_batch",
            credits=total_credits,
            project_id=project_id,
        )
        if not charge_result.success:
            logger.warning(
                "Batch credit charge failed for %s: %s",
                project_id,
                charge_result.error,
            )
    except Exception as exc:
        logger.warning(
            "License server unavailable for batch render %s: %s",
            project_id,
            exc,
        )
    finally:
        await license_client.close()

    # Update all edits to rendering status
    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=False)
    try:
        for edl in edl_list:
            execute(
                conn,
                "UPDATE edits SET status = 'rendering', "
                "updated_at = datetime('now') "
                "WHERE edit_id = ? AND project_id = ?",
                (edl.edit_id, project_id),
            )
        conn.commit()
    finally:
        conn.close()

    # Execute batch render
    try:
        config = ClipCannonConfig.load()
        results = await render_batch(
            edl_list=edl_list,
            project_dir=_project_dir(project_id),
            db_path=db,
            config=config,
        )
    except Exception as exc:
        logger.exception(
            "Batch render failed for %s",
            project_id,
        )
        return _error(
            "BATCH_RENDER_FAILED",
            f"Batch render failed: {exc}",
            {"project_id": project_id},
        )

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    # Build per-edit results
    renders: list[dict[str, object]] = []
    for i, result in enumerate(results):
        edit_id = edl_list[i].edit_id if i < len(edl_list) else "unknown"
        renders.append({
            "edit_id": edit_id,
            "render_id": result.render_id,
            "status": "completed" if result.success else "failed",
            "output_path": str(result.output_path) if result.output_path else None,
            "file_size_bytes": result.file_size_bytes,
            "duration_ms": result.duration_ms,
            "error_message": result.error_message,
        })

    succeeded = sum(1 for r in results if r.success)
    failed_count = len(results) - succeeded

    logger.info(
        "Batch render for %s: %d succeeded, %d failed (%dms)",
        project_id,
        succeeded,
        failed_count,
        elapsed_ms,
    )

    return {
        "project_id": project_id,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed_count,
        "credits_charged": total_credits,
        "renders": renders,
        "load_errors": errors if errors else None,
        "elapsed_ms": elapsed_ms,
    }


# ============================================================
# DISPATCH
# ============================================================
async def dispatch_rendering_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch a rendering tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_render":
        return await clipcannon_render(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
        )
    if name == "clipcannon_render_status":
        return await clipcannon_render_status(
            project_id=str(arguments["project_id"]),
            render_id=str(arguments["render_id"]),
        )
    if name == "clipcannon_render_batch":
        return await clipcannon_render_batch(
            project_id=str(arguments["project_id"]),
            edit_ids=[str(e) for e in list(arguments["edit_ids"])],  # type: ignore[union-attr]
        )

    return _error("INTERNAL_ERROR", f"Unknown rendering tool: {name}")
