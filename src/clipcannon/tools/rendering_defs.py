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
    Tool(
        name="clipcannon_analyze_frame",
        description=(
            "Analyze a frame for content regions and webcam PIP "
            "overlay. Returns bounding boxes of detected content "
            "regions (text, UI panels, images) and PIP webcam "
            "position. Use before editing to understand frame "
            "layout. ~125ms per frame. No credits charged."
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
                    "description": (
                        "Source video timestamp to analyze (ms)"
                    ),
                },
            },
            "required": ["project_id", "timestamp_ms"],
        },
    ),
    Tool(
        name="clipcannon_preview_layout",
        description=(
            "Generate a single preview frame showing what a canvas "
            "layout looks like at a specific timestamp. Returns a "
            "JPEG image path in ~300ms. Use this to validate region "
            "coordinates before committing to a full video render. "
            "No credits charged."
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
                    "description": (
                        "Source video timestamp to preview (ms)"
                    ),
                },
                "canvas_width": {
                    "type": "integer",
                    "description": "Output canvas width",
                    "default": 1080,
                },
                "canvas_height": {
                    "type": "integer",
                    "description": "Output canvas height",
                    "default": 1920,
                },
                "background_color": {
                    "type": "string",
                    "description": "Canvas background hex color",
                    "default": "#000000",
                },
                "regions": {
                    "type": "array",
                    "description": (
                        "Canvas regions. Each: {region_id, "
                        "source_x, source_y, source_width, "
                        "source_height, output_x, output_y, "
                        "output_width, output_height, z_index, "
                        "fit_mode}"
                    ),
                    "items": {"type": "object"},
                    "minItems": 1,
                },
            },
            "required": [
                "project_id", "timestamp_ms", "regions",
            ],
        },
    ),
]
