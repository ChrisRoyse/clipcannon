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
        name="clipcannon_get_editing_context",
        description=(
            "Get ALL data needed for editing decisions in one call. "
            "Returns transcript, highlights (ranked), silence gaps "
            "(natural cut points), pacing, and scene boundaries. "
            "Use this FIRST before creating any edit."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
            },
            "required": ["project_id"],
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
        name="clipcannon_preview_clip",
        description=(
            "Render a short (2-5 second) low-quality preview of an edit at a specific time range. "
            "No credits charged. Uses 540p resolution and fast encoding for quick validation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "start_ms": {"type": "integer", "description": "Start time in source video (ms)"},
                "duration_ms": {
                    "type": "integer",
                    "description": "Preview duration (ms, max 5000)",
                    "default": 3000,
                },
            },
            "required": ["project_id", "start_ms"],
        },
    ),
    Tool(
        name="clipcannon_inspect_render",
        description=(
            "Inspect a rendered video output. Extracts frames at 5 key timestamps "
            "(start, 25%%, 50%%, 75%%, end), probes metadata, and runs quality checks. "
            "Returns inline frame images, metadata comparison, and pass/fail results."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "render_id": {"type": "string", "description": "Render identifier to inspect"},
            },
            "required": ["project_id", "render_id"],
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
