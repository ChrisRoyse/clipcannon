"""MCP tool definitions for ClipCannon.

Registers all tool modules and provides a unified registration function
for the MCP server. Each tool module exposes a list of tool definitions
and a dispatch function.
"""

from __future__ import annotations

from mcp.types import Tool

from clipcannon.tools.billing_tools import (
    BILLING_TOOL_DEFINITIONS,
    dispatch_billing_tool,
)
from clipcannon.tools.config_tools import (
    CONFIG_TOOL_DEFINITIONS,
    dispatch_config_tool,
)
from clipcannon.tools.disk import (
    DISK_TOOL_DEFINITIONS,
    dispatch_disk_tool,
)
from clipcannon.tools.project import (
    PROJECT_TOOL_DEFINITIONS,
    dispatch_project_tool,
)
from clipcannon.tools.provenance_tools import (
    PROVENANCE_TOOL_DEFINITIONS,
    dispatch_provenance_tool,
)
from clipcannon.tools.understanding import (
    clipcannon_get_analytics,
    clipcannon_get_transcript,
    clipcannon_get_vud_summary,
    clipcannon_ingest,
)
from clipcannon.tools.understanding_search import (
    clipcannon_search_content,
)
from clipcannon.tools.understanding_visual import (
    clipcannon_get_frame,
    clipcannon_get_frame_strip,
    clipcannon_get_segment_detail,
    clipcannon_get_storyboard,
)

# ---------------------------------------------------------------
# Understanding tool definitions (9 tools)
# ---------------------------------------------------------------
_PROJECT_ID_PROP = {
    "project_id": {"type": "string", "description": "Project identifier"},
}

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
        name="clipcannon_get_vud_summary",
        description=(
            "Get a compact Video Understanding Document summary (~8K tokens). "
            "Includes speakers, topics preview, top 5 highlights, reactions, "
            "beats, content safety, energy, and stream status."
        ),
        inputSchema={
            "type": "object",
            "properties": _PROJECT_ID_PROP,
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_get_analytics",
        description=(
            "Get detailed analytics for specific sections (~18K tokens). "
            "Sections: highlights, scenes, topics, reactions, beats, "
            "pacing, silence_gaps."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Sections to include. Default: all. "
                        "Options: highlights, scenes, topics, reactions, "
                        "beats, pacing, silence_gaps"
                    ),
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
            "Get ALL stream data for a time range (~15K tokens). "
            "Returns transcript, emotion curve, speakers, reactions, "
            "beats, on-screen text, pacing, quality, silence gaps."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "start_ms": {"type": "integer", "description": "Start time in ms"},
                "end_ms": {"type": "integer", "description": "End time in ms"},
            },
            "required": ["project_id", "start_ms", "end_ms"],
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
        name="clipcannon_get_frame_strip",
        description=(
            "Build a 3x3 composite grid of evenly-spaced frames from a range. "
            "Returns grid image path and per-cell metadata."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "start_ms": {"type": "integer", "description": "Start time in ms"},
                "end_ms": {"type": "integer", "description": "End time in ms"},
                "count": {
                    "type": "integer",
                    "description": "Number of frames (default: 9, max: 16)",
                    "default": 9,
                },
            },
            "required": ["project_id", "start_ms", "end_ms"],
        },
    ),
    Tool(
        name="clipcannon_get_storyboard",
        description=(
            "Get storyboard grids by batch number or time range. "
            "Each batch contains 12 grids. Specify start_ms/end_ms "
            "to get grids in a time range instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "batch": {
                    "type": "integer",
                    "description": "Batch number (1-indexed, 12 grids/batch)",
                    "default": 1,
                },
                "start_ms": {"type": "integer", "description": "Start time filter (ms)"},
                "end_ms": {"type": "integer", "description": "End time filter (ms)"},
            },
            "required": ["project_id"],
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
    elif name == "clipcannon_get_vud_summary":
        return await clipcannon_get_vud_summary(str(arguments["project_id"]))
    elif name == "clipcannon_get_analytics":
        sections = arguments.get("sections")
        return await clipcannon_get_analytics(
            str(arguments["project_id"]),
            list(sections) if sections is not None else None,  # type: ignore[arg-type]
        )
    elif name == "clipcannon_get_transcript":
        return await clipcannon_get_transcript(
            str(arguments["project_id"]),
            int(arguments.get("start_ms", 0)),  # type: ignore[arg-type]
            int(arguments["end_ms"]) if arguments.get("end_ms") is not None else None,
        )
    elif name == "clipcannon_get_segment_detail":
        return await clipcannon_get_segment_detail(
            str(arguments["project_id"]),
            int(arguments["start_ms"]),  # type: ignore[arg-type]
            int(arguments["end_ms"]),  # type: ignore[arg-type]
        )
    elif name == "clipcannon_get_frame":
        return await clipcannon_get_frame(
            str(arguments["project_id"]),
            int(arguments["timestamp_ms"]),  # type: ignore[arg-type]
        )
    elif name == "clipcannon_get_frame_strip":
        return await clipcannon_get_frame_strip(
            str(arguments["project_id"]),
            int(arguments["start_ms"]),  # type: ignore[arg-type]
            int(arguments["end_ms"]),  # type: ignore[arg-type]
            int(arguments.get("count", 9)),  # type: ignore[arg-type]
        )
    elif name == "clipcannon_get_storyboard":
        start = arguments.get("start_ms")
        end = arguments.get("end_ms")
        return await clipcannon_get_storyboard(
            str(arguments["project_id"]),
            int(arguments.get("batch", 1)),  # type: ignore[arg-type]
            int(start) if start is not None else None,
            int(end) if end is not None else None,
        )
    elif name == "clipcannon_search_content":
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
    (PROJECT_TOOL_DEFINITIONS, dispatch_project_tool),
    (PROVENANCE_TOOL_DEFINITIONS, dispatch_provenance_tool),
    (DISK_TOOL_DEFINITIONS, dispatch_disk_tool),
    (CONFIG_TOOL_DEFINITIONS, dispatch_config_tool),
    (UNDERSTANDING_TOOL_DEFINITIONS, dispatch_understanding_tool),
    (BILLING_TOOL_DEFINITIONS, dispatch_billing_tool),
]:
    for _tool_def in _defs:
        TOOL_DISPATCHERS[_tool_def.name] = _dispatch

ALL_TOOL_DEFINITIONS = (
    PROJECT_TOOL_DEFINITIONS
    + PROVENANCE_TOOL_DEFINITIONS
    + DISK_TOOL_DEFINITIONS
    + CONFIG_TOOL_DEFINITIONS
    + UNDERSTANDING_TOOL_DEFINITIONS
    + BILLING_TOOL_DEFINITIONS
)

__all__ = [
    "ALL_TOOL_DEFINITIONS",
    "BILLING_TOOL_DEFINITIONS",
    "TOOL_DISPATCHERS",
    "UNDERSTANDING_TOOL_DEFINITIONS",
    "dispatch_billing_tool",
    "dispatch_understanding_tool",
]
