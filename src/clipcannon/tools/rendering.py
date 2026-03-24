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


def _resolve_render_path(project_id: str, render_id: str) -> Path | None:
    """Resolve the output video path for a render.

    Args:
        project_id: Project identifier.
        render_id: Render identifier.

    Returns:
        Path to the rendered video, or None if not found.
    """
    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT output_path FROM renders "
            "WHERE render_id = ? AND project_id = ?",
            (render_id, project_id),
        )
    finally:
        conn.close()
    if row is None or not row.get("output_path"):
        return None
    path = Path(str(row["output_path"]))
    return path if path.exists() else None


async def _extract_render_frame(video_path: Path, timestamp_ms: int) -> Path | None:
    """Extract a single frame from a video at a given timestamp.

    Uses ffmpeg to seek to the timestamp and extract one JPEG frame.

    Args:
        video_path: Path to the video file.
        timestamp_ms: Timestamp in milliseconds to extract.

    Returns:
        Path to the extracted JPEG frame, or None on failure.
    """
    import tempfile

    output = Path(tempfile.mktemp(suffix=".jpg"))
    cmd = [
        "ffmpeg", "-y", "-ss", f"{timestamp_ms / 1000:.3f}",
        "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(output),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()
    return output if output.exists() and output.stat().st_size > 0 else None


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
# TOOL 5: clipcannon_get_scene_map
# ============================================================
async def clipcannon_get_scene_map(
    project_id: str,
    start_ms: int = 0,
    end_ms: int | None = None,
    detail: str = "summary",
    layout: str | None = None,
) -> dict[str, object]:
    """Get the scene map with pagination and detail control.

    Supports two detail modes for bounded token output:
    - **summary** (~40 tokens/scene): id, start/end, layout,
      has_face, transcript preview (first 80 chars).
    - **full** (~120 tokens/scene): all fields including
      canvas_regions, but only for the requested layout.

    Time-window pagination keeps each response bounded. Default
    window is 5 minutes from *start_ms*.

    Args:
        project_id: Project identifier.
        start_ms: Window start in milliseconds (default 0).
        end_ms: Window end in milliseconds (default start_ms + 300000).
        detail: ``"summary"`` or ``"full"`` (default ``"summary"``).
        layout: Layout to return — ``"A"``, ``"B"``, ``"C"``, ``"D"``,
            or ``None`` for the scene's recommended layout only.
    """
    # ---- validate detail param ----
    if detail not in ("summary", "full"):
        return _error(
            "INVALID_PARAMETER",
            f"detail must be 'summary' or 'full', got '{detail}'",
        )

    # ---- validate layout param ----
    valid_layouts = {"A", "B", "C", "D"}
    if layout is not None and layout not in valid_layouts:
        return _error(
            "INVALID_PARAMETER",
            f"layout must be one of A/B/C/D or null, got '{layout}'",
        )

    # ---- compute window ----
    if end_ms is None:
        end_ms = start_ms + 300_000  # 5-minute default window

    if end_ms <= start_ms:
        return _error(
            "INVALID_PARAMETER",
            f"end_ms ({end_ms}) must be greater than start_ms ({start_ms})",
        )

    proj_dir = _project_dir(project_id)
    if not proj_dir.exists():
        return _error(
            "PROJECT_NOT_FOUND",
            f"Project not found: {project_id}",
        )

    db = _db_path(project_id)
    if not db.exists():
        return _error("DB_NOT_FOUND", "Project database not found")

    conn = get_connection(str(db), enable_vec=False, dict_rows=True)
    try:
        # Get project info
        proj = fetch_one(
            conn,
            "SELECT resolution, duration_ms, fps FROM project "
            "WHERE project_id = ?",
            (project_id,),
        )
        if proj is None:
            return _error(
                "PROJECT_NOT_FOUND",
                f"No project record: {project_id}",
            )

        # Total scene count (whole project)
        total_row = fetch_one(
            conn,
            "SELECT COUNT(*) AS cnt FROM scene_map "
            "WHERE project_id = ?",
            (project_id,),
        )
        total_scenes_in_project = int(total_row["cnt"]) if total_row else 0

        # Windowed scene query
        scenes_raw = fetch_all(
            conn,
            "SELECT * FROM scene_map WHERE project_id = ? "
            "AND start_ms >= ? AND start_ms < ? ORDER BY start_ms",
            (project_id, start_ms, end_ms),
        )

        # Check if more scenes exist beyond window
        next_row = fetch_one(
            conn,
            "SELECT MIN(start_ms) AS next_ms FROM scene_map "
            "WHERE project_id = ? AND start_ms >= ?",
            (project_id, end_ms),
        )

        # Batch-fetch text_change_events and emotion_curve for summary enrichment
        _text_changes: list[dict[str, object]] = []
        _emotion_entries: list[dict[str, object]] = []
        if detail == "summary" and scenes_raw:
            try:
                _text_changes = [
                    dict(r)
                    for r in fetch_all(
                        conn,
                        "SELECT timestamp_ms, new_title FROM text_change_events "
                        "WHERE project_id = ? AND timestamp_ms >= ? AND timestamp_ms < ? "
                        "ORDER BY timestamp_ms",
                        (project_id, start_ms, end_ms),
                    )
                ]
            except Exception:
                _text_changes = []
            try:
                _emotion_entries = [
                    dict(r)
                    for r in fetch_all(
                        conn,
                        "SELECT start_ms, end_ms, energy FROM emotion_curve "
                        "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
                        "ORDER BY start_ms",
                        (project_id, end_ms, start_ms),
                    )
                ]
            except Exception:
                _emotion_entries = []
    except Exception as exc:
        return _error(
            "SCENE_MAP_NOT_FOUND",
            f"Scene map not available. Run ingest first. Error: {exc}",
        )
    finally:
        conn.close()

    if not scenes_raw and total_scenes_in_project == 0:
        return _error(
            "SCENE_MAP_EMPTY",
            "No scenes in scene map. Run ingest first.",
        )

    has_more = next_row is not None and next_row["next_ms"] is not None
    next_start_ms = int(next_row["next_ms"]) if has_more else None

    # ---- Build response scenes ----
    scenes: list[dict[str, object]] = []
    webcam_info: dict[str, object] | None = None

    for row in scenes_raw:
        rec_layout = str(row.get("layout_recommendation", "A"))

        if detail == "summary":
            # ~120 tokens per scene: compact with storyboard context
            transcript_raw = str(row.get("transcript_text", ""))
            preview = transcript_raw[:80]
            if len(transcript_raw) > 80:
                preview += "..."

            scene_start = int(row["start_ms"])
            scene_end = int(row["end_ms"])
            scene_mid = (scene_start + scene_end) // 2

            # screen_content: most recent text_change_event at or before scene start
            screen_content = ""
            for tc in reversed(_text_changes):
                if int(tc.get("timestamp_ms", 0)) <= scene_start:
                    raw_title = str(tc.get("new_title", "") or "")
                    screen_content = raw_title[:60]
                    break

            # speaker_activity: classify from transcript text
            text_lower = transcript_raw.lower()
            screen_ref_phrases = ("you can see", "look at", "this shows", "here")
            direct_addr_words = (" i ", " you ", " we ", "let me", " i'")
            if any(p in text_lower for p in screen_ref_phrases):
                speaker_activity = "screen_reference"
            elif any(w in f" {text_lower} " for w in direct_addr_words):
                speaker_activity = "direct_address"
            else:
                speaker_activity = "narrating"

            # energy: nearest emotion_curve entry to scene midpoint
            energy: float | None = None
            best_dist = float("inf")
            for em in _emotion_entries:
                em_mid = (int(em.get("start_ms", 0)) + int(em.get("end_ms", 0))) // 2
                dist = abs(em_mid - scene_mid)
                if dist < best_dist:
                    best_dist = dist
                    energy = round(float(em.get("energy", 0)), 4)

            scene: dict[str, object] = {
                "id": int(row["scene_id"]),
                "start_ms": scene_start,
                "end_ms": scene_end,
                "layout": rec_layout,
                "has_face": row.get("face_x") is not None,
                "transcript_preview": preview,
                "screen_content": screen_content,
                "speaker_activity": speaker_activity,
                "energy": energy,
            }
        else:
            # full mode (~120 tokens per scene)
            scene = {
                "id": int(row["scene_id"]),
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
                "duration_ms": int(row["end_ms"]) - int(row["start_ms"]),
                "transcript": str(row.get("transcript_text", "")),
                "layout": rec_layout,
            }

            # Face
            if row.get("face_x") is not None:
                scene["face"] = {
                    "x": int(row["face_x"]),
                    "y": int(row["face_y"]),
                    "w": int(row["face_w"]),
                    "h": int(row["face_h"]),
                    "conf": float(row.get("face_confidence") or 0),
                }

            # Content region
            if row.get("content_x") is not None:
                scene["content"] = {
                    "x": int(row["content_x"]),
                    "y": int(row["content_y"]),
                    "w": int(row["content_w"]),
                    "h": int(row["content_h"]),
                }

            # Canvas regions — only the requested layout
            canvas_json = str(row.get("canvas_regions_json", "{}"))
            try:
                all_canvas = json.loads(canvas_json)
            except (json.JSONDecodeError, TypeError):
                all_canvas = {}

            target_layout = layout if layout is not None else rec_layout
            if isinstance(all_canvas, dict) and target_layout in all_canvas:
                scene["canvas"] = {target_layout: all_canvas[target_layout]}
            else:
                scene["canvas"] = {}

        scenes.append(scene)

        # Extract webcam info from first scene that has it
        if webcam_info is None and row.get("webcam_x") is not None:
            webcam_info = {
                "detected": True,
                "x": int(row["webcam_x"]),
                "y": int(row["webcam_y"]),
                "w": int(row["webcam_w"]),
                "h": int(row["webcam_h"]),
            }

    response: dict[str, object] = {
        "project_id": project_id,
        "source": {
            "resolution": str(proj["resolution"]),
            "duration_ms": int(proj["duration_ms"]),
            "fps": float(proj["fps"]),
        },
        "webcam": webcam_info or {"detected": False},
        "window": {
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
        "total_scenes_in_window": len(scenes),
        "total_scenes_in_project": total_scenes_in_project,
        "has_more": has_more,
        "scenes": scenes,
    }
    if next_start_ms is not None:
        response["next_start_ms"] = next_start_ms

    return response


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
    if name == "clipcannon_get_editing_context":
        return await clipcannon_get_editing_context(
            project_id=str(arguments["project_id"]),
        )
    if name == "clipcannon_analyze_frame":
        return await clipcannon_analyze_frame(
            project_id=str(arguments["project_id"]),
            timestamp_ms=int(arguments["timestamp_ms"]),  # type: ignore[arg-type]
            render_id=str(arguments["render_id"]) if arguments.get("render_id") else None,
        )
    if name == "clipcannon_preview_clip":
        return await clipcannon_preview_clip(
            str(arguments["project_id"]),
            int(arguments["start_ms"]),
            int(arguments.get("duration_ms", 3000)),
            render_id=str(arguments["render_id"]) if arguments.get("render_id") else None,
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

    if name == "clipcannon_get_scene_map":
        return await clipcannon_get_scene_map(
            str(arguments["project_id"]),
            start_ms=int(arguments.get("start_ms", 0)),
            end_ms=int(arguments["end_ms"]) if arguments.get("end_ms") is not None else None,
            detail=str(arguments.get("detail", "summary")),
            layout=str(arguments["layout"]) if arguments.get("layout") is not None else None,
        )

    return _error("INTERNAL_ERROR", f"Unknown rendering tool: {name}")


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


# ============================================================
# TOOL 7: clipcannon_get_editing_context
# ============================================================
async def clipcannon_get_editing_context(
    project_id: str,
) -> dict[str, object]:
    """Get bounded editing-context data for AI decisions.

    Returns a data manifest (~500 tokens) describing what data is
    available for this project and which tools to use to query it.
    This is a catalog/registry — it tells the AI WHAT exists, not
    the data itself. The AI then uses targeted tools to pull
    exactly what it needs on demand.

    Args:
        project_id: Project identifier.

    Returns:
        Data manifest with counts, ranges, and tool references.
    """
    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err

    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        proj = fetch_one(
            conn,
            "SELECT duration_ms, resolution, fps, status FROM project "
            "WHERE project_id = ?",
            (project_id,),
        )
        if proj is None:
            return _error("PROJECT_NOT_FOUND", f"No project: {project_id}")

        # Count queries — fast aggregate stats from each table
        counts: dict[str, int] = {}
        for table, col in [
            ("transcript_segments", "project_id"),
            ("highlights", "project_id"),
            ("silence_gaps", "project_id"),
            ("scenes", "project_id"),
            ("scene_map", "project_id"),
            ("speakers", "project_id"),
            ("topics", "project_id"),
            ("emotion_curve", "project_id"),
            ("pacing", "project_id"),
            ("on_screen_text", "project_id"),
            ("reactions", "project_id"),
            ("provenance", "project_id"),
        ]:
            try:
                row = fetch_one(
                    conn,
                    f"SELECT COUNT(*) AS cnt FROM {table} WHERE {col} = ?",  # noqa: S608
                    (project_id,),
                )
                counts[table] = int(row["cnt"]) if row else 0
            except Exception:
                counts[table] = 0

        # Top highlight score
        top_hl = fetch_one(
            conn,
            "SELECT MAX(score) AS top FROM highlights WHERE project_id = ?",
            (project_id,),
        )
        top_highlight_score = round(float(top_hl["top"]), 2) if top_hl and top_hl["top"] else 0.0

        # Dominant speaker
        speaker_row = fetch_one(
            conn,
            "SELECT label, speaking_pct FROM speakers "
            "WHERE project_id = ? ORDER BY speaking_pct DESC LIMIT 1",
            (project_id,),
        )

        # Dominant pacing label
        pacing_row = fetch_one(
            conn,
            "SELECT label, SUM(end_ms - start_ms) AS total_ms "
            "FROM pacing WHERE project_id = ? "
            "GROUP BY label ORDER BY total_ms DESC LIMIT 1",
            (project_id,),
        )

        # WPM range
        wpm_row = fetch_one(
            conn,
            "SELECT MIN(words_per_minute) AS min_wpm, "
            "MAX(words_per_minute) AS max_wpm "
            "FROM pacing WHERE project_id = ?",
            (project_id,),
        )

        # Avg energy
        energy_row = fetch_one(
            conn,
            "SELECT AVG(energy) AS avg_e FROM emotion_curve WHERE project_id = ?",
            (project_id,),
        )

        # Beats summary
        beats_row = fetch_one(
            conn,
            "SELECT has_music, tempo_bpm FROM beats WHERE project_id = ? LIMIT 1",
            (project_id,),
        )

        # Content safety
        safety_row = fetch_one(
            conn,
            "SELECT content_rating FROM content_safety WHERE project_id = ? LIMIT 1",
            (project_id,),
        )

        # Webcam detection (from scene_map)
        webcam_row = fetch_one(
            conn,
            "SELECT webcam_x, webcam_y, webcam_w, webcam_h FROM scene_map "
            "WHERE project_id = ? AND webcam_x IS NOT NULL LIMIT 1",
            (project_id,),
        )

        # Topic labels
        topic_rows = fetch_all(
            conn,
            "SELECT label FROM topics WHERE project_id = ? ORDER BY start_ms LIMIT 5",
            (project_id,),
        )

        # All speakers with label + speaking_pct
        try:
            all_speakers = fetch_all(
                conn,
                "SELECT label, speaking_pct FROM speakers "
                "WHERE project_id = ? ORDER BY speaking_pct DESC",
                (project_id,),
            )
        except Exception:
            all_speakers = []

        # Narrative analysis (from Qwen3-8B) — table may not exist
        narrative_data: dict[str, object] | None = None
        try:
            narr_row = fetch_one(
                conn,
                "SELECT analysis_json FROM narrative_analysis "
                "WHERE project_id = ? LIMIT 1",
                (project_id,),
            )
            if narr_row and narr_row.get("analysis_json"):
                raw = json.loads(str(narr_row["analysis_json"]))
                narrative_data = {
                    "story_beats": raw.get("story_beats", []),
                    "open_loops": raw.get("open_loops", []),
                    "chapter_boundaries": raw.get("chapter_boundaries", []),
                    "narrative_summary": raw.get("narrative_summary", ""),
                }
        except Exception:
            narrative_data = None

        # Transcript preview — first 500 words
        transcript_preview: str = ""
        try:
            ts_rows = fetch_all(
                conn,
                "SELECT text FROM transcript_segments "
                "WHERE project_id = ? ORDER BY start_ms",
                (project_id,),
            )
            if ts_rows:
                full_text = " ".join(
                    str(r["text"]).strip() for r in ts_rows if r.get("text")
                )
                words = full_text.split()
                transcript_preview = " ".join(words[:500])
        except Exception:
            transcript_preview = ""

    finally:
        conn.close()

    elapsed = int((time.monotonic() - start_time) * 1000)

    return {
        "project_id": project_id,
        "video": {
            "duration_ms": int(proj["duration_ms"]),
            "resolution": str(proj["resolution"]),
            "fps": float(proj["fps"]),
            "status": str(proj["status"]),
        },
        "data_manifest": {
            "transcript": {
                "segments": counts["transcript_segments"],
                "query": "get_transcript(project_id, start_ms, end_ms)",
            },
            "scenes": {
                "visual_scenes": counts["scene_map"],
                "scene_boundaries": counts["scenes"],
                "query": "get_scene_map(project_id, start_ms, end_ms, detail, layout)",
            },
            "highlights": {
                "count": counts["highlights"],
                "top_score": top_highlight_score,
                "query": "find_best_moments(project_id, purpose, count)",
            },
            "silence_gaps": {
                "count": counts["silence_gaps"],
                "query": "find_cut_points(project_id, around_ms, search_range_ms)",
            },
            "speakers": {
                "count": counts["speakers"],
                "dominant": (
                    f"{speaker_row['label']} ({speaker_row['speaking_pct']}%)"
                    if speaker_row else "unknown"
                ),
            },
            "topics": {
                "count": counts["topics"],
                "labels": [str(t["label"]) for t in topic_rows],
            },
            "emotion": {
                "data_points": counts["emotion_curve"],
                "avg_energy": (
                    round(float(energy_row["avg_e"]), 2)
                    if energy_row and energy_row["avg_e"] else None
                ),
            },
            "pacing": {
                "dominant": str(pacing_row["label"]) if pacing_row else "unknown",
                "wpm_range": (
                    f"{int(wpm_row['min_wpm'])}-{int(wpm_row['max_wpm'])}"
                    if wpm_row and wpm_row["min_wpm"] else "unknown"
                ),
            },
            "webcam": {
                "detected": webcam_row is not None,
            },
            "beats": {
                "detected": bool(beats_row and beats_row["has_music"]),
                "bpm": int(beats_row["tempo_bpm"]) if beats_row and beats_row["tempo_bpm"] else None,
            },
            "ocr_text": {
                "detected": counts["on_screen_text"] > 0,
                "regions": counts["on_screen_text"],
            },
            "reactions": {
                "count": counts["reactions"],
            },
            "content_rating": (
                str(safety_row["content_rating"]) if safety_row else "unknown"
            ),
            "provenance_records": counts["provenance"],
        },
        "speakers": [
            {"label": str(s["label"]), "speaking_pct": round(float(s["speaking_pct"]), 1)}
            for s in all_speakers
            if s.get("speaking_pct") is not None
        ],
        "narrative": narrative_data,
        "transcript_preview": transcript_preview,
        "query_tools": {
            "find_best_moments": "Find scored clip candidates for hook/highlight/cta/tutorial_step",
            "get_scene_map": "Browse scenes in paginated time windows (summary or full detail)",
            "find_cut_points": "Find natural edit boundaries (silence gaps, scene breaks, sentences)",
            "get_transcript": "Get word-level transcript for any time range",
            "search_content": "Search transcript by keywords",
            "analyze_frame": "Detect content regions and webcam in any frame",
            "get_frame": "Get any frame as an image for visual inspection",
            "preview_layout": "Preview a canvas layout composition as JPEG",
        },
        "elapsed_ms": elapsed,
    }
