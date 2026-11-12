"""Dispatch for the rendering MCP tools."""

from __future__ import annotations

from clipcannon.tools.rendering_common import _error
from clipcannon.tools.rendering_context import clipcannon_get_editing_context
from clipcannon.tools.rendering_preview import (
    clipcannon_preview_clip,
    clipcannon_preview_layout,
    clipcannon_preview_segment,
)
from clipcannon.tools.rendering_render import (
    clipcannon_analyze_frame,
    clipcannon_inspect_render,
    clipcannon_render,
)
from clipcannon.tools.rendering_scene_map import clipcannon_get_scene_map


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
            captions=bool(arguments.get("captions", True)),
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
    if name == "clipcannon_preview_segment":
        return await clipcannon_preview_segment(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            segment_index=int(arguments["segment_index"]),
        )

    return _error("INTERNAL_ERROR", f"Unknown rendering tool: {name}")
