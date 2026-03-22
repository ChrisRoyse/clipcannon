"""Rendering MCP tools for ClipCannon.

Provides tools for rendering edits to video files, checking render
status, and batch rendering multiple edits concurrently. Each render
charges 2 credits via the license server.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path

from clipcannon.billing.license_client import LicenseClient
from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
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


def _resolve_source(project_id: str) -> Path | None:
    """Resolve the source video path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the source video, or None if not found.
    """
    db = _db_path(project_id)
    if not db.exists():
        return None

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT source_path, source_cfr_path FROM project "
            "WHERE project_id = ?",
            (project_id,),
        )
    finally:
        conn.close()

    if row is None:
        return None

    cfr = row.get("source_cfr_path")
    if cfr and Path(str(cfr)).exists():
        return Path(str(cfr))

    source = Path(str(row["source_path"]))
    return source if source.exists() else None


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
# TOOL 4: clipcannon_preview_layout
# ============================================================
async def clipcannon_preview_layout(
    project_id: str,
    timestamp_ms: int,
    canvas_width: int,
    canvas_height: int,
    background_color: str,
    regions: list[dict[str, object]],
) -> dict[str, object]:
    """Generate a single preview frame of a canvas layout.

    Renders one composited JPEG at a specific timestamp to validate
    region coordinates before committing to a full video render.

    Args:
        project_id: Project identifier.
        timestamp_ms: Source timestamp in milliseconds.
        canvas_width: Output canvas width.
        canvas_height: Output canvas height.
        background_color: Canvas background hex color.
        regions: List of region dicts with source/output coordinates.

    Returns:
        Result dict with preview_path and elapsed_ms.
    """
    from clipcannon.editing.edl import CanvasRegion
    from clipcannon.rendering.ffmpeg_cmd import build_preview_cmd

    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err

    if not regions:
        return _error("INVALID_PARAMETER", "At least one region is required")

    if timestamp_ms < 0:
        return _error("INVALID_PARAMETER", "timestamp_ms must be >= 0")

    # Resolve source path
    source_path = _resolve_source(project_id)
    if source_path is None:
        return _error("PROJECT_NOT_FOUND", f"Source not found: {project_id}")

    # Build CanvasRegion objects from dicts
    try:
        canvas_regions = [CanvasRegion(**r) for r in regions]
    except Exception as exc:
        return _error(
            "INVALID_PARAMETER",
            f"Invalid region data: {exc}",
            {"error": str(exc)},
        )

    # Build preview output path
    project_dir = _project_dir(project_id)
    preview_dir = project_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_path = preview_dir / f"preview_{timestamp_ms}ms.jpg"

    # Build and execute FFmpeg command
    try:
        cmd = build_preview_cmd(
            source_path=source_path,
            output_path=preview_path,
            timestamp_ms=timestamp_ms,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            background_color=background_color,
            regions=canvas_regions,
        )
    except ValueError as exc:
        return _error("INVALID_PARAMETER", str(exc))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")
        return _error(
            "RENDER_ERROR",
            f"Preview generation failed (exit {proc.returncode})",
            {"stderr": stderr_text[:500]},
        )

    if not preview_path.exists():
        return _error(
            "RENDER_ERROR",
            "FFmpeg completed but preview file not found",
        )

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    # Encode preview as base64 for inline image viewing
    try:
        image_b64 = base64.b64encode(preview_path.read_bytes()).decode("ascii")
        image_payload: dict[str, str] | None = {
            "data": image_b64, "mimeType": "image/jpeg",
        }
    except Exception:
        image_payload = None

    result: dict[str, object] = {
        "project_id": project_id,
        "timestamp_ms": timestamp_ms,
        "preview_path": str(preview_path),
        "canvas_width": canvas_width,
        "canvas_height": canvas_height,
        "region_count": len(canvas_regions),
        "file_size_bytes": preview_path.stat().st_size,
        "elapsed_ms": elapsed_ms,
    }
    if image_payload is not None:
        result["_image"] = image_payload
    return result


# ============================================================
# TOOL 5: clipcannon_preview_clip
# ============================================================
async def clipcannon_preview_clip(
    project_id: str,
    start_ms: int,
    duration_ms: int = 3000,
) -> dict[str, object]:
    """Render a short low-quality preview clip."""
    from clipcannon.rendering.preview import render_preview

    proj_dir = _project_dir(project_id)
    if not proj_dir.exists():
        return _error(
            "PROJECT_NOT_FOUND",
            f"Project not found: {project_id}",
        )

    source = _resolve_source(project_id)
    if source is None:
        return _error(
            "SOURCE_NOT_FOUND",
            "No source video found",
        )

    preview_dir = proj_dir / "renders" / "previews"

    try:
        result = await render_preview(
            source_path=source,
            output_dir=preview_dir,
            start_ms=start_ms,
            duration_ms=duration_ms,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        return _error("PREVIEW_FAILED", str(exc))

    response: dict[str, object] = {
        "preview_path": str(result.preview_path),
        "duration_ms": result.duration_ms,
        "file_size_bytes": result.file_size_bytes,
        "elapsed_ms": result.elapsed_ms,
    }
    if result.thumbnail_base64:
        response["_image"] = {
            "data": result.thumbnail_base64,
            "mimeType": "image/jpeg",
        }

    return response


# ============================================================
# TOOL 6: clipcannon_inspect_render
# ============================================================
async def clipcannon_inspect_render(
    project_id: str,
    render_id: str,
) -> dict[str, object]:
    """Inspect a rendered video output with frame extraction and metadata checks."""
    from clipcannon.rendering.inspector import inspect_render

    db = _db_path(project_id)
    if not db.exists():
        return _error(
            "PROJECT_NOT_FOUND",
            f"Project not found: {project_id}",
        )

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT * FROM renders WHERE render_id = ? AND project_id = ?",
            (render_id, project_id),
        )
    finally:
        conn.close()

    if row is None:
        return _error(
            "RENDER_NOT_FOUND",
            f"Render not found: {render_id}",
        )

    output_path = row.get("output_path")
    if not output_path or not Path(output_path).exists():
        return _error(
            "OUTPUT_NOT_FOUND",
            "Rendered file not found on disk",
        )

    try:
        result = await inspect_render(
            render_output_path=Path(output_path),
            expected_duration_ms=row.get("duration_ms"),
            expected_width=row.get("resolution_width"),
            expected_height=row.get("resolution_height"),
            expected_codec=row.get("codec"),
        )
        result.render_id = render_id
    except (FileNotFoundError, RuntimeError) as exc:
        return _error("INSPECTION_FAILED", str(exc))

    return {
        "render_id": result.render_id,
        "output_path": result.output_path,
        "all_checks_passed": result.all_passed,
        "checks": result.checks,
        "metadata": result.metadata,
        "frames": [
            {
                "timestamp_ms": f["timestamp_ms"],
                "frame_path": f.get("frame_path", ""),
            }
            for f in result.frames
        ],
        "frame_count": len(result.frames),
        "elapsed_ms": result.elapsed_ms,
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
    if name == "clipcannon_get_editing_context":
        return await clipcannon_get_editing_context(
            project_id=str(arguments["project_id"]),
        )
    if name == "clipcannon_analyze_frame":
        return await clipcannon_analyze_frame(
            project_id=str(arguments["project_id"]),
            timestamp_ms=int(arguments["timestamp_ms"]),  # type: ignore[arg-type]
        )
    if name == "clipcannon_preview_clip":
        return await clipcannon_preview_clip(
            str(arguments["project_id"]),
            int(arguments["start_ms"]),
            int(arguments.get("duration_ms", 3000)),
        )
    if name == "clipcannon_inspect_render":
        return await clipcannon_inspect_render(
            str(arguments["project_id"]),
            str(arguments["render_id"]),
        )
    if name == "clipcannon_preview_layout":
        return await clipcannon_preview_layout(
            project_id=str(arguments["project_id"]),
            timestamp_ms=int(arguments["timestamp_ms"]),  # type: ignore[arg-type]
            canvas_width=int(arguments.get("canvas_width", 1080)),  # type: ignore[arg-type]
            canvas_height=int(arguments.get("canvas_height", 1920)),  # type: ignore[arg-type]
            background_color=str(arguments.get("background_color", "#000000")),
            regions=list(arguments["regions"]),  # type: ignore[arg-type]
        )

    return _error("INTERNAL_ERROR", f"Unknown rendering tool: {name}")


# ============================================================
# TOOL 7: clipcannon_analyze_frame
# ============================================================
async def clipcannon_analyze_frame(
    project_id: str,
    timestamp_ms: int,
) -> dict[str, object]:
    """Analyze a frame for content regions and PIP overlay.

    Runs lightweight CV analysis (~125ms) to detect content
    regions, webcam PIP overlay position, and classify region
    types (text, ui_panel, image, empty).

    Args:
        project_id: Project identifier.
        timestamp_ms: Source timestamp in milliseconds.

    Returns:
        Dict with frame dimensions, content regions, and PIP info.
    """
    from clipcannon.pipeline.screen_layout import analyze_frame

    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err

    # Find the nearest frame
    project_dir = _project_dir(project_id)
    frames_dir = project_dir / "frames"
    if not frames_dir.exists():
        return _error("NOT_FOUND", "Frames directory not found")

    # Calculate frame number from timestamp (2fps)
    frame_num = (timestamp_ms // 500) + 1
    frame_path = frames_dir / f"frame_{frame_num:06d}.jpg"

    # Search nearby if exact frame doesn't exist
    if not frame_path.exists():
        for offset in range(-5, 6):
            candidate = frames_dir / f"frame_{frame_num + offset:06d}.jpg"
            if candidate.exists():
                frame_path = candidate
                break
        else:
            return _error(
                "NOT_FOUND",
                f"No frame found near timestamp {timestamp_ms}ms",
            )

    result = analyze_frame(frame_path)
    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    return {
        "project_id": project_id,
        "timestamp_ms": timestamp_ms,
        "frame_path": str(frame_path),
        "frame_width": result["frame_width"],
        "frame_height": result["frame_height"],
        "content_regions": result["content_regions"],
        "pip_overlay": result["pip_overlay"],
        "region_count": result["region_count"],
        "elapsed_ms": elapsed_ms,
    }


# ============================================================
# TOOL 8: clipcannon_get_editing_context
# ============================================================
async def clipcannon_get_editing_context(
    project_id: str,
) -> dict[str, object]:
    """Get all data needed for AI editing decisions in one call.

    Consolidates transcript summary, highlights, silence gaps,
    pacing, scenes, and frame analysis into a single response.
    This replaces multiple separate tool calls.

    Args:
        project_id: Project identifier.

    Returns:
        Dict with all editing-relevant data.
    """
    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err

    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        # Project metadata
        proj = fetch_one(
            conn,
            "SELECT duration_ms, resolution, fps FROM project "
            "WHERE project_id = ?",
            (project_id,),
        )
        if proj is None:
            return _error("PROJECT_NOT_FOUND", f"No project: {project_id}")

        # Transcript segments (compact: just text + timing)
        segments = fetch_all(
            conn,
            "SELECT start_ms, end_ms, text FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )

        # Highlights (ranked by score)
        highlights = fetch_all(
            conn,
            "SELECT start_ms, end_ms, type, score, reason "
            "FROM highlights WHERE project_id = ? ORDER BY score DESC",
            (project_id,),
        )

        # Silence gaps (natural cut points)
        gaps = fetch_all(
            conn,
            "SELECT start_ms, end_ms, duration_ms "
            "FROM silence_gaps WHERE project_id = ? "
            "ORDER BY start_ms",
            (project_id,),
        )

        # Pacing windows
        pacing = fetch_all(
            conn,
            "SELECT start_ms, end_ms, words_per_minute, "
            "pause_ratio, label FROM pacing "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )

        # Scene boundaries
        scenes = fetch_all(
            conn,
            "SELECT scene_id, start_ms, end_ms, "
            "key_frame_path, dominant_colors "
            "FROM scenes WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )

    finally:
        conn.close()

    elapsed = int((time.monotonic() - start_time) * 1000)

    return {
        "project_id": project_id,
        "duration_ms": int(proj["duration_ms"]),
        "resolution": str(proj["resolution"]),
        "transcript": [
            {"start_ms": s["start_ms"], "end_ms": s["end_ms"],
             "text": s["text"]}
            for s in segments
        ],
        "highlights": [
            {"start_ms": h["start_ms"], "end_ms": h["end_ms"],
             "score": h["score"], "reason": h["reason"]}
            for h in highlights
        ],
        "silence_gaps": [
            {"start_ms": g["start_ms"], "end_ms": g["end_ms"],
             "duration_ms": g["duration_ms"]}
            for g in gaps
        ],
        "pacing": [
            {"start_ms": p["start_ms"], "end_ms": p["end_ms"],
             "wpm": p["words_per_minute"], "label": p["label"]}
            for p in pacing
        ],
        "scenes": [
            {"scene_id": s["scene_id"], "start_ms": s["start_ms"],
             "end_ms": s["end_ms"],
             "key_frame": s["key_frame_path"]}
            for s in scenes
        ],
        "segment_count": len(segments),
        "highlight_count": len(highlights),
        "scene_count": len(scenes),
        "silence_gap_count": len(gaps),
        "elapsed_ms": elapsed,
    }
