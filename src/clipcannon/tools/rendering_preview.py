"""Rendering MCP tools: preview_layout, preview_clip and preview_segment."""

from __future__ import annotations

import asyncio
import base64
import logging
import time

from clipcannon.tools.rendering_common import (
    _error,
    _extract_render_frame,
    _load_edl,
    _project_dir,
    _resolve_render_path,
    _resolve_source,
    _validate_project,
)

logger = logging.getLogger(__name__)


# ============================================================
# TOOL 2: clipcannon_preview_layout
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
# TOOL 3: clipcannon_preview_clip
# ============================================================
async def clipcannon_preview_clip(
    project_id: str,
    start_ms: int,
    duration_ms: int = 3000,
    render_id: str | None = None,
) -> dict[str, object]:
    """Render a short low-quality preview clip."""
    from clipcannon.rendering.preview import render_preview

    proj_dir = _project_dir(project_id)
    if not proj_dir.exists():
        return _error(
            "PROJECT_NOT_FOUND",
            f"Project not found: {project_id}",
        )

    if render_id is not None:
        source = _resolve_render_path(project_id, render_id)
        if source is None:
            return _error(
                "RENDER_NOT_FOUND",
                f"Render not found or output missing: {render_id}",
            )
    else:
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
# TOOL 8: clipcannon_preview_segment
# ============================================================
async def clipcannon_preview_segment(
    project_id: str,
    edit_id: str,
    segment_index: int,
) -> dict[str, object]:
    """Preview a single segment from an edit at low quality.

    Renders ONE segment at 540p using fast software encoding for
    quick validation. Extracts a midpoint frame for visual inspection.
    No credits charged.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.
        segment_index: 1-based segment index to preview.

    Returns:
        Dict with preview_path, frame_path, and segment_info, or error.
    """
    from clipcannon.rendering.ffmpeg_cmd import build_encoding_args, build_ffmpeg_cmd
    from clipcannon.rendering.profiles import EncodingProfile

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

    # Validate segment_index (1-based)
    segment_count = len(edl.segments)
    if segment_index < 1 or segment_index > segment_count:
        return _error(
            "INVALID_PARAMETER",
            f"segment_index {segment_index} out of range. "
            f"Valid range: 1 to {segment_count}.",
            {
                "segment_index": segment_index,
                "segment_count": segment_count,
            },
        )

    segment = edl.segments[segment_index - 1]

    # Resolve source video
    source_path = _resolve_source(project_id)
    if source_path is None:
        return _error(
            "SOURCE_NOT_FOUND",
            f"Source video not found for project {project_id}",
        )

    # Create preview directory
    preview_dir = _project_dir(project_id) / "renders" / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    preview_filename = f"preview_{edit_id}_seg{segment_index}.mp4"
    preview_path = preview_dir / preview_filename

    # 540p preview profile (software encoding, fast)
    preview_profile = EncodingProfile(
        name="preview_540p",
        width=540,
        height=960,
        aspect_ratio="9:16",
        fps=30,
        video_codec="libx264",
        video_bitrate="1000k",
        max_bitrate="1500k",
        bufsize="3M",
        audio_codec="aac",
        audio_bitrate="128k",
        audio_sample_rate=44100,
        movflags="+faststart",
    )

    encoding_args = build_encoding_args(preview_profile)

    # Build FFmpeg command for just this one segment
    cmd = build_ffmpeg_cmd(
        source_path=source_path,
        output_path=preview_path,
        segments=[segment],
        profile=preview_profile,
        crop_region=None,
        ass_path=None,
        encoding_args=encoding_args,
    )

    # Execute FFmpeg
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")[:500]
            return _error(
                "RENDER_FAILED",
                f"Preview render failed (exit {proc.returncode})",
                {"stderr": stderr_text},
            )
    except Exception as exc:
        return _error(
            "RENDER_FAILED",
            f"Preview render error: {exc}",
        )

    if not preview_path.exists() or preview_path.stat().st_size == 0:
        return _error(
            "RENDER_FAILED",
            "Preview render produced no output",
        )

    # Extract midpoint frame for visual inspection
    segment_duration_ms = int(
        (segment.source_end_ms - segment.source_start_ms) / segment.speed
    )
    midpoint_ms = segment_duration_ms // 2
    frame_path = await _extract_render_frame(preview_path, midpoint_ms)

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    result: dict[str, object] = {
        "preview_path": str(preview_path),
        "frame_path": str(frame_path) if frame_path else None,
        "segment_info": {
            "segment_index": segment_index,
            "source_start_ms": segment.source_start_ms,
            "source_end_ms": segment.source_end_ms,
            "speed": segment.speed,
            "output_duration_ms": segment_duration_ms,
        },
        "resolution": f"{preview_profile.width}x{preview_profile.height}",
        "credits_charged": 0,
        "elapsed_ms": elapsed_ms,
    }

    logger.info(
        "Preview segment %d of edit %s rendered in %dms",
        segment_index, edit_id, elapsed_ms,
    )

    return result
