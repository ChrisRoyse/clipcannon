"""Dispatch for the editing MCP tools."""

from __future__ import annotations

from clipcannon.tools.editing_branches import clipcannon_branch_edit, clipcannon_list_branches
from clipcannon.tools.editing_create import clipcannon_create_edit
from clipcannon.tools.editing_effects import (
    clipcannon_add_motion,
    clipcannon_add_overlay,
    clipcannon_color_adjust,
)
from clipcannon.tools.editing_helpers import error_response
from clipcannon.tools.editing_history import (
    clipcannon_apply_feedback,
    clipcannon_edit_history,
    clipcannon_revert_edit,
)
from clipcannon.tools.editing_modify import clipcannon_auto_trim, clipcannon_modify_edit


# ============================================================
# DISPATCH
# ============================================================
async def dispatch_editing_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch an editing tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_create_edit":
        return await clipcannon_create_edit(
            project_id=str(arguments["project_id"]),
            name=str(arguments["name"]),
            target_platform=str(arguments["target_platform"]),
            segments=list(arguments["segments"]),  # type: ignore[arg-type]
            captions=arguments.get("captions"),  # type: ignore[arg-type]
            crop=arguments.get("crop"),  # type: ignore[arg-type]
            canvas=arguments.get("canvas"),  # type: ignore[arg-type]
            audio=arguments.get("audio"),  # type: ignore[arg-type]
            metadata=arguments.get("metadata"),  # type: ignore[arg-type]
        )
    if name == "clipcannon_modify_edit":
        return await clipcannon_modify_edit(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            changes=dict(arguments["changes"]),  # type: ignore[arg-type]
        )
    if name == "clipcannon_auto_trim":
        return await clipcannon_auto_trim(
            str(arguments["project_id"]),
            int(arguments.get("pause_threshold_ms", 800)),
            int(arguments.get("merge_gap_ms", 200)),
            int(arguments.get("min_segment_ms", 500)),
        )
    if name == "clipcannon_color_adjust":
        return await clipcannon_color_adjust(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            float(arguments.get("brightness", 0.0)),
            float(arguments.get("contrast", 1.0)),
            float(arguments.get("saturation", 1.0)),
            float(arguments.get("gamma", 1.0)),
            float(arguments.get("hue_shift", 0.0)),
            int(arguments["segment_id"]) if arguments.get("segment_id") is not None else None,
        )
    if name == "clipcannon_add_motion":
        return await clipcannon_add_motion(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            int(arguments["segment_id"]),
            str(arguments["effect"]),
            float(arguments.get("start_scale", 1.0)),
            float(arguments.get("end_scale", 1.3)),
            str(arguments.get("easing", "linear")),
        )
    if name == "clipcannon_add_overlay":
        return await clipcannon_add_overlay(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            str(arguments["overlay_type"]),
            str(arguments["text"]),
            int(arguments["start_ms"]),
            int(arguments["end_ms"]),
            str(arguments.get("subtitle", "")),
            str(arguments.get("position", "bottom_left")),
            float(arguments.get("opacity", 1.0)),
            int(arguments.get("font_size", 36)),
            str(arguments.get("text_color", "#FFFFFF")),
            str(arguments.get("bg_color", "#000000")),
            float(arguments.get("bg_opacity", 0.7)),
            str(arguments.get("animation", "fade_in")),
            int(arguments.get("animation_duration_ms", 500)),
        )
    if name == "clipcannon_edit_history":
        return await clipcannon_edit_history(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
        )
    if name == "clipcannon_revert_edit":
        return await clipcannon_revert_edit(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            int(arguments["version_number"]),
        )
    if name == "clipcannon_apply_feedback":
        ops = arguments.get("operations")
        fb = arguments.get("feedback")
        return await clipcannon_apply_feedback(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            feedback=str(fb) if fb is not None else None,
            operations=ops if isinstance(ops, list) else None,
        )
    if name == "clipcannon_branch_edit":
        return await clipcannon_branch_edit(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            branch_name=str(arguments["branch_name"]),
            target_platform=str(arguments["target_platform"]),
        )
    if name == "clipcannon_list_branches":
        return await clipcannon_list_branches(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
        )

    return error_response("INTERNAL_ERROR", f"Unknown editing tool: {name}")
