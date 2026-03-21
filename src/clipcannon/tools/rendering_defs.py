"""Tool definitions for ClipCannon rendering MCP tools.

Separates the JSON schema tool definitions from the implementation.
"""

from __future__ import annotations

from mcp.types import Tool

RENDERING_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_render",
        description=(
            "Render an edit to a platform-ready video file. "
            "Executes the full rendering pipeline: source validation, "
            "caption burn-in, smart crop, FFmpeg encoding, thumbnail "
            "generation, and provenance recording. Charges 2 credits."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "edit_id": {"type": "string", "description": "Edit identifier to render"},
            },
            "required": ["project_id", "edit_id"],
        },
    ),
    Tool(
        name="clipcannon_render_status",
        description=(
            "Check the status of a render job. Returns render "
            "metadata including status, output path, file size, "
            "duration, codec, resolution, and any error message."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "render_id": {"type": "string", "description": "Render identifier"},
            },
            "required": ["project_id", "render_id"],
        },
    ),
    Tool(
        name="clipcannon_render_batch",
        description=(
            "Render multiple edits concurrently. Processes all "
            "specified edits with concurrency limited by "
            "max_parallel_renders config. Charges 2 credits per edit."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "edit_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of edit identifiers to render",
                    "minItems": 1,
                },
            },
            "required": ["project_id", "edit_ids"],
        },
    ),
]
