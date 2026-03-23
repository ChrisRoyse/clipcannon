"""MCP tool definitions for ClipCannon.

Registers all tool modules and provides a unified registration function
for the MCP server. Each tool module exposes a list of tool definitions
and a dispatch function.
"""

from __future__ import annotations

from mcp.types import Tool

from clipcannon.tools.audio import (
    AUDIO_TOOL_DEFINITIONS,
    dispatch_audio_tool,
)
from clipcannon.tools.billing_tools import (
    BILLING_TOOL_DEFINITIONS,
    dispatch_billing_tool,
)
from clipcannon.tools.config_tools import (
    CONFIG_TOOL_DEFINITIONS,
    dispatch_config_tool,
)
from clipcannon.tools.discovery import (
    DISCOVERY_TOOL_DEFINITIONS,
    dispatch_discovery_tool,
)
from clipcannon.tools.disk import (
    DISK_TOOL_DEFINITIONS,
    dispatch_disk_tool,
)
from clipcannon.tools.editing import (
    EDITING_TOOL_DEFINITIONS,
    dispatch_editing_tool,
)
from clipcannon.tools.project import (
    PROJECT_TOOL_DEFINITIONS,
    dispatch_project_tool,
)
from clipcannon.tools.provenance_tools import (
    PROVENANCE_TOOL_DEFINITIONS,
    dispatch_provenance_tool,
)
from clipcannon.tools.rendering import (
    RENDERING_TOOL_DEFINITIONS,
    dispatch_rendering_tool,
)
from clipcannon.tools.understanding import (
    clipcannon_get_transcript,
    clipcannon_ingest,
)
from clipcannon.tools.understanding_search import (
    clipcannon_search_content,
)
from clipcannon.tools.understanding_visual import (
    clipcannon_get_frame,
    clipcannon_get_segment_detail,
)

# ---------------------------------------------------------------
# Understanding tool definitions (5 tools)
# ---------------------------------------------------------------
UNDERSTANDING_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_ingest",
        description=(
            "Run the full analysis pipeline on a created project. "
            "Registers all stages, executes the DAG, and returns results."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "options": {
                    "type": "object",
                    "description": "Optional pipeline overrides (reserved for future use)",
                },
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_get_transcript",
        description=(
            "Get transcript with word-level timestamps. "
            "Paginated in 15-minute windows. Use start_ms/end_ms "
            "to navigate. Returns has_more and next_start_ms."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "start_ms": {
                    "type": "integer",
                    "description": "Start time in milliseconds (default: 0)",
                    "default": 0,
                },
                "end_ms": {
                    "type": "integer",
                    "description": "End time in ms (default: start_ms + 900000)",
                },
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_get_segment_detail",
        description=(
            "Master query: get ALL intelligence from every embedder "
            "for a time range. Returns 17 data streams: transcript "
            "(segments + words), emotion curve (arousal/valence/energy), "
            "speakers, reactions, beats, on-screen text (OCR), text "
            "change events (slide transitions), pacing, scene quality, "
            "scene map (face/webcam/content/canvas regions), silence "
            "gaps, highlights (scored), topics, profanity, music sections. "
            "Use get_editing_context first to see what data exists, "
            "then call this tool for specific time ranges. "
            "Alternatively, pass timestamp_ms for a 10-second point query "
            "centred on that timestamp (replaces get_scene_at). "
            "Optionally pass layout to get canvas regions for that layout."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "start_ms": {
                    "type": "integer",
                    "description": "Start time in ms (not needed when using timestamp_ms)",
                    "default": 0,
                },
                "end_ms": {
                    "type": "integer",
                    "description": "End time in ms (not needed when using timestamp_ms)",
                    "default": 0,
                },
                "timestamp_ms": {
                    "type": "integer",
                    "description": (
                        "Point-query mode: returns a 10s window "
                        "(timestamp - 5000 to timestamp + 5000) "
                        "with scene_map entry and canvas regions. "
                        "Overrides start_ms/end_ms."
                    ),
                },
                "layout": {
                    "type": "string",
                    "description": (
                        "Layout name to filter canvas regions "
                        "(e.g. 'tiktok_vertical', 'youtube_standard'). "
                        "Only used with timestamp_ms."
                    ),
                },
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_get_frame",
        description=(
            "Get the nearest frame to a timestamp with moment context. "
            "Returns frame path + transcript, speaker, emotion, topic, "
            "shot type, quality, pacing, on-screen text, profanity."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "timestamp_ms": {"type": "integer", "description": "Target timestamp in ms"},
            },
            "required": ["project_id", "timestamp_ms"],
        },
    ),
    Tool(
        name="clipcannon_search_content",
        description=(
            "Search video content by semantic similarity or text match. "
            "Returns matching segments with timestamps and scores. "
            "Falls back to text search if vector model unavailable."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "query": {"type": "string", "description": "Search query"},
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 10)",
                    "default": 10,
                },
                "search_type": {
                    "type": "string",
                    "description": "Search type: semantic or text (default: semantic)",
                    "default": "semantic",
                    "enum": ["semantic", "text"],
                },
            },
            "required": ["project_id", "query"],
        },
    ),
]


async def dispatch_understanding_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch an understanding tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_ingest":
        return await clipcannon_ingest(
            str(arguments["project_id"]),
            arguments.get("options"),  # type: ignore[arg-type]
        )
    if name == "clipcannon_get_transcript":
        return await clipcannon_get_transcript(
            str(arguments["project_id"]),
            int(arguments.get("start_ms", 0)),  # type: ignore[arg-type]
            int(arguments["end_ms"]) if arguments.get("end_ms") is not None else None,
        )
    if name == "clipcannon_get_segment_detail":
        ts_raw = arguments.get("timestamp_ms")
        layout_raw = arguments.get("layout")
        return await clipcannon_get_segment_detail(
            str(arguments["project_id"]),
            int(arguments.get("start_ms", 0)),  # type: ignore[arg-type]
            int(arguments.get("end_ms", 0)),  # type: ignore[arg-type]
            timestamp_ms=int(ts_raw) if ts_raw is not None else None,  # type: ignore[arg-type]
            layout=str(layout_raw) if layout_raw is not None else None,
        )
    if name == "clipcannon_get_frame":
        return await clipcannon_get_frame(
            str(arguments["project_id"]),
            int(arguments["timestamp_ms"]),  # type: ignore[arg-type]
        )
    if name == "clipcannon_search_content":
        return await clipcannon_search_content(
            str(arguments["project_id"]),
            str(arguments["query"]),
            int(arguments.get("limit", 10)),  # type: ignore[arg-type]
            str(arguments.get("search_type", "semantic")),
        )

    return {"error": {"code": "INTERNAL_ERROR", "message": f"Unknown tool: {name}", "details": {}}}


# Combined mapping of tool name -> dispatch function
TOOL_DISPATCHERS: dict[str, object] = {}

# Build dispatcher map from all modules
for _defs, _dispatch in [
    # Phase 1 modules
    (PROJECT_TOOL_DEFINITIONS, dispatch_project_tool),
    (PROVENANCE_TOOL_DEFINITIONS, dispatch_provenance_tool),
    (DISK_TOOL_DEFINITIONS, dispatch_disk_tool),
    (CONFIG_TOOL_DEFINITIONS, dispatch_config_tool),
    (UNDERSTANDING_TOOL_DEFINITIONS, dispatch_understanding_tool),
    (BILLING_TOOL_DEFINITIONS, dispatch_billing_tool),
    # Phase 2 modules
    (EDITING_TOOL_DEFINITIONS, dispatch_editing_tool),
    (RENDERING_TOOL_DEFINITIONS, dispatch_rendering_tool),
    (AUDIO_TOOL_DEFINITIONS, dispatch_audio_tool),
    (DISCOVERY_TOOL_DEFINITIONS, dispatch_discovery_tool),
]:
    for _tool_def in _defs:
        TOOL_DISPATCHERS[_tool_def.name] = _dispatch

ALL_TOOL_DEFINITIONS = (
    # Phase 1
    PROJECT_TOOL_DEFINITIONS
    + PROVENANCE_TOOL_DEFINITIONS
    + DISK_TOOL_DEFINITIONS
    + CONFIG_TOOL_DEFINITIONS
    + UNDERSTANDING_TOOL_DEFINITIONS
    + BILLING_TOOL_DEFINITIONS
    # Phase 2
    + EDITING_TOOL_DEFINITIONS
    + RENDERING_TOOL_DEFINITIONS
    + AUDIO_TOOL_DEFINITIONS
    + DISCOVERY_TOOL_DEFINITIONS
)

__all__ = [
    "ALL_TOOL_DEFINITIONS",
    "AUDIO_TOOL_DEFINITIONS",
    "BILLING_TOOL_DEFINITIONS",
    "DISCOVERY_TOOL_DEFINITIONS",
    "EDITING_TOOL_DEFINITIONS",
    "RENDERING_TOOL_DEFINITIONS",
    "TOOL_DISPATCHERS",
    "UNDERSTANDING_TOOL_DEFINITIONS",
    "dispatch_audio_tool",
    "dispatch_billing_tool",
    "dispatch_discovery_tool",
    "dispatch_editing_tool",
    "dispatch_rendering_tool",
    "dispatch_understanding_tool",
]
