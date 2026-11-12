"""Editing MCP tools: color_adjust, add_motion and add_overlay."""

from __future__ import annotations

import json

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.editing.edl import ColorSpec, EditDecisionList, MotionSpec, OverlaySpec
from clipcannon.tools.editing_helpers import db_path, error_response, validate_project


# ============================================================
# TOOL 4: clipcannon_color_adjust
# ============================================================
async def clipcannon_color_adjust(
    project_id: str,
    edit_id: str,
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    gamma: float = 1.0,
    hue_shift: float = 0.0,
    segment_id: int | None = None,
) -> dict[str, object]:
    """Apply color grading to an edit globally or per-segment."""
    err = validate_project(project_id)
    if err is not None:
        return err

    try:
        color = ColorSpec(
            brightness=brightness, contrast=contrast,
            saturation=saturation, gamma=gamma, hue_shift=hue_shift,
        )
    except Exception as exc:
        return error_response("INVALID_PARAMETER", f"Invalid color values: {exc}")

    # Load existing EDL
    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if row is None:
            return error_response("EDIT_NOT_FOUND", f"Edit not found: {edit_id}")
        if row["status"] != "draft":
            return error_response("INVALID_STATE", f"Edit must be draft, is: {row['status']}")

        edl = EditDecisionList(**json.loads(row["edl_json"]))

        if segment_id is not None:
            # Apply to specific segment
            found = False
            for seg in edl.segments:
                if seg.segment_id == segment_id:
                    seg.color = color
                    found = True
                    break
            if not found:
                return error_response("SEGMENT_NOT_FOUND", f"Segment {segment_id} not found")
            scope = f"segment {segment_id}"
        else:
            # Apply globally
            edl.color = color
            scope = "global"

        # Save back
        execute(
            conn,
            "UPDATE edits SET edl_json = ?,"
            " updated_at = datetime('now') WHERE edit_id = ?",
            (edl.model_dump_json(), edit_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "edit_id": edit_id,
        "scope": scope,
        "color": color.model_dump(),
        "message": f"Color grading applied ({scope})",
    }


# ============================================================
# TOOL 5: clipcannon_add_motion
# ============================================================
async def clipcannon_add_motion(
    project_id: str,
    edit_id: str,
    segment_id: int,
    effect: str,
    start_scale: float = 1.0,
    end_scale: float = 1.3,
    easing: str = "linear",
) -> dict[str, object]:
    """Add motion effect to a segment."""
    err = validate_project(project_id)
    if err is not None:
        return err

    try:
        motion = MotionSpec(
            effect=effect,
            start_scale=start_scale,
            end_scale=end_scale,
            easing=easing,
        )
    except Exception as exc:
        return error_response("INVALID_PARAMETER", f"Invalid motion values: {exc}")

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if row is None:
            return error_response("EDIT_NOT_FOUND", f"Edit not found: {edit_id}")
        if row["status"] != "draft":
            return error_response("INVALID_STATE", f"Edit must be draft, is: {row['status']}")

        edl = EditDecisionList(**json.loads(row["edl_json"]))

        found = False
        for seg in edl.segments:
            if seg.segment_id == segment_id:
                seg.motion = motion
                found = True
                break
        if not found:
            return error_response("SEGMENT_NOT_FOUND", f"Segment {segment_id} not found")

        execute(
            conn,
            "UPDATE edits SET edl_json = ?,"
            " updated_at = datetime('now') WHERE edit_id = ?",
            (edl.model_dump_json(), edit_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "edit_id": edit_id,
        "segment_id": segment_id,
        "motion": motion.model_dump(),
        "message": f"Motion effect '{effect}' applied to segment {segment_id}",
    }


# ============================================================
# TOOL 6: clipcannon_add_overlay
# ============================================================
async def clipcannon_add_overlay(
    project_id: str,
    edit_id: str,
    overlay_type: str,
    text: str,
    start_ms: int,
    end_ms: int,
    subtitle: str = "",
    position: str = "bottom_left",
    opacity: float = 1.0,
    font_size: int = 36,
    text_color: str = "#FFFFFF",
    bg_color: str = "#000000",
    bg_opacity: float = 0.7,
    animation: str = "fade_in",
    animation_duration_ms: int = 500,
) -> dict[str, object]:
    """Add a visual overlay to an edit."""
    err = validate_project(project_id)
    if err is not None:
        return err

    try:
        overlay = OverlaySpec(
            overlay_type=overlay_type, text=text, subtitle=subtitle,
            position=position, start_ms=start_ms, end_ms=end_ms,
            opacity=opacity, font_size=font_size, text_color=text_color,
            bg_color=bg_color, bg_opacity=bg_opacity, animation=animation,
            animation_duration_ms=animation_duration_ms,
        )
    except Exception as exc:
        return error_response("INVALID_PARAMETER", f"Invalid overlay: {exc}")

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if row is None:
            return error_response("EDIT_NOT_FOUND", f"Edit not found: {edit_id}")
        if row["status"] != "draft":
            return error_response("INVALID_STATE", f"Edit must be draft, is: {row['status']}")

        edl = EditDecisionList(**json.loads(row["edl_json"]))
        edl.overlays.append(overlay)

        execute(
            conn,
            "UPDATE edits SET edl_json = ?,"
            " updated_at = datetime('now') WHERE edit_id = ?",
            (edl.model_dump_json(), edit_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "edit_id": edit_id,
        "overlay_count": len(edl.overlays),
        "overlay": overlay.model_dump(),
        "message": f"Added {overlay_type} overlay to edit",
    }
