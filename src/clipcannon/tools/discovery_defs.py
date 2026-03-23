"""Tool definitions for ClipCannon discovery MCP tools.

Separates the JSON schema tool definitions from the implementation.
These tools help find the best moments, scenes, and cut points
in long-form video content.
"""

from __future__ import annotations

from mcp.types import Tool

DISCOVERY_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_find_best_moments",
        description=(
            "Find the best video segments for a specific purpose. "
            "Queries highlights, aligns to natural cut points (silence "
            "gaps), includes transcript text and canvas regions. "
            "Purpose-aware scoring: 'hook' prefers early segments "
            "with faces, 'cta' prefers late segments, 'tutorial_step' "
            "prefers text-change events. No credits charged."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "purpose": {
                    "type": "string",
                    "enum": ["hook", "highlight", "cta", "tutorial_step"],
                    "description": (
                        "Intended use: 'hook' (attention-grabbing opener), "
                        "'highlight' (best raw moments), 'cta' (call to action), "
                        "'tutorial_step' (instructional segment near slides)"
                    ),
                },
                "target_duration_s": {
                    "type": "integer",
                    "description": (
                        "Target clip duration in seconds (default 30, range 5-180)"
                    ),
                    "default": 30,
                    "minimum": 5,
                    "maximum": 180,
                },
                "count": {
                    "type": "integer",
                    "description": "Number of moments to return (default 5, max 10)",
                    "default": 5,
                    "maximum": 10,
                },
            },
            "required": ["project_id", "purpose"],
        },
    ),
    Tool(
        name="clipcannon_get_scene_at",
        description=(
            "Point query: get scene data for a single timestamp. "
            "Returns the scene covering the given time, or the "
            "closest scene if none matches exactly. Optionally "
            "includes previous and next scene summaries. Returns "
            "canvas regions for the requested layout. No credits charged."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "timestamp_ms": {
                    "type": "integer",
                    "description": "Target timestamp in milliseconds",
                },
                "layout": {
                    "type": "string",
                    "enum": ["A", "B", "C", "D"],
                    "description": (
                        "Layout to return canvas regions for. "
                        "Omit to use the scene's recommended layout."
                    ),
                },
                "include_neighbors": {
                    "type": "boolean",
                    "description": (
                        "Include previous and next scene summaries "
                        "(default false)"
                    ),
                    "default": False,
                },
            },
            "required": ["project_id", "timestamp_ms"],
        },
    ),
    Tool(
        name="clipcannon_find_cut_points",
        description=(
            "Find natural edit boundaries near a timestamp. "
            "Searches silence gaps, scene boundaries, and sentence "
            "endings within a configurable range. Returns cut points "
            "ranked by quality: silence_gap > scene_boundary > "
            "sentence_end. No credits charged."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "around_ms": {
                    "type": "integer",
                    "description": "Center timestamp to search around (ms)",
                },
                "search_range_ms": {
                    "type": "integer",
                    "description": (
                        "Search window radius in ms (default 5000). "
                        "Searches from around_ms - range to around_ms + range."
                    ),
                    "default": 5000,
                },
            },
            "required": ["project_id", "around_ms"],
        },
    ),
]
