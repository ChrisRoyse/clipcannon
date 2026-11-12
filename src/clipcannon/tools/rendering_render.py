"""Rendering MCP tools: clipcannon_render, inspect_render and analyze_frame."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.rendering.renderer import RenderEngine
from clipcannon.tools.rendering_common import (
    _db_path,
    _error,
    _extract_render_frame,
    _load_edl,
    _project_dir,
    _resolve_render_path,
    _validate_project,
)

logger = logging.getLogger(__name__)


# ============================================================
# TOOL 1: clipcannon_render
# ============================================================
async def clipcannon_render(
    project_id: str,
    edit_id: str,
    captions: bool = True,
) -> dict[str, object]:
    """Render an edit to a video file.

    Loads the EDL, executes the render pipeline,
    and returns the result with output path and metadata.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.
        captions: Whether to burn captions into the video. When
            False, disables caption burn-in even if the EDL has
            captions enabled.

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

    db = _db_path(project_id)
    # Requested speaker framing needs the speaker_tracking stage: refuse before
    # any state changes rather than render a centre crop in its place.
    from clipcannon.editing.speaker_framing import (
        SpeakerTrackingMissingError,
        require_speaker_tracking,
        wants_speaker_framing,
    )
    if wants_speaker_framing(edl):
        try:
            require_speaker_tracking(db, project_id)
        except SpeakerTrackingMissingError as exc:
            return _error(exc.code, str(exc), {"edit_id": edit_id, "project_id": project_id,
                                               "remediation": exc.remediation})

    # Update edit status to rendering
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

    # Execute render
    try:
        config = ClipCannonConfig.load()
        engine = RenderEngine(config)
        # When captions=False, disable caption burn-in entirely
        if not captions:
            edl.captions.enabled = False
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
        "elapsed_ms": elapsed_ms,
    }


# ============================================================
# TOOL 4: clipcannon_inspect_render
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
# TOOL 6: clipcannon_analyze_frame
# ============================================================
async def clipcannon_analyze_frame(
    project_id: str,
    timestamp_ms: int,
    render_id: str | None = None,
) -> dict[str, object]:
    """Analyze a frame for content regions and PIP overlay.

    Runs lightweight CV analysis (~125ms) to detect content
    regions, webcam PIP overlay position, and classify region
    types (text, ui_panel, image, empty).

    When ``render_id`` is provided, extracts the frame from the
    rendered output video instead of looking in the frames directory.

    Args:
        project_id: Project identifier.
        timestamp_ms: Source timestamp in milliseconds.
        render_id: Optional render ID to analyze instead of source.

    Returns:
        Dict with frame dimensions, content regions, and PIP info.
    """
    from clipcannon.pipeline.screen_layout import analyze_frame

    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err

    if render_id is not None:
        # Extract frame from rendered video on the fly
        render_path = _resolve_render_path(project_id, render_id)
        if render_path is None:
            return _error(
                "RENDER_NOT_FOUND",
                f"Render not found or output missing: {render_id}",
            )
        frame_path = await _extract_render_frame(render_path, timestamp_ms)
        if frame_path is None:
            return _error(
                "FRAME_EXTRACTION_FAILED",
                f"Could not extract frame at {timestamp_ms}ms from render {render_id}",
            )
    else:
        # Find the nearest frame from pre-extracted frames
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
