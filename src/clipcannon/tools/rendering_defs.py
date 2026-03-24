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
                "captions": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Burn captions into the video (default true). "
                        "Captions are burned in a post-render second "
                        "pass with automatic timestamp alignment to "
                        "the actual rendered output duration."
                    ),
                },
            },
            "required": ["project_id", "edit_id"],
        },
    ),
    Tool(
        name="clipcannon_get_editing_context",
        description=(
            "Get the enriched data manifest for a project. "
            "Returns a catalog of ALL available data (counts, ranges, "
            "scores), speaker breakdown (label + speaking_pct), "
            "narrative analysis from Qwen3-8B (story_beats, open_loops, "
            "chapter_boundaries, narrative_summary), transcript preview "
            "(first 500 words), and which tools to use to query each "
            "data type. One call gives you enough context to plan edits "
            "without needing get_vud_summary or get_transcript. "
            "Call this FIRST before any editing work."
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
            "layout. ~125ms per frame. No credits charged. "
            "Pass render_id to analyze a rendered output instead "
            "of the source video."
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
                "render_id": {
                    "type": "string",
                    "description": (
                        "Render ID to analyze (omit to use source video)"
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
            "No credits charged. Uses 540p resolution and fast encoding for quick validation. "
            "Pass render_id to preview a rendered output instead of the source video."
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
                "render_id": {
                    "type": "string",
                    "description": "Render ID to preview (omit to use source video)",
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
                "timestamp_ms": {
                    "type": "integer",
                    "description": (
                        "Specific timestamp to inspect (omit for 5 default positions)"
                    ),
                },
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
    Tool(
        name="clipcannon_get_scene_map",
        description=(
            "Get the scene map with time-window pagination and detail "
            "control. Summary mode (~40 tokens/scene): id, start/end, "
            "layout, has_face, transcript preview. Full mode (~120 "
            "tokens/scene): all fields including canvas_regions for "
            "a single layout only. Default window is 5 minutes from "
            "start_ms. Use has_more + next_start_ms to paginate. "
            "Requires ingest to have been run first."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "start_ms": {
                    "type": "integer",
                    "description": (
                        "Window start in milliseconds (default 0)"
                    ),
                    "default": 0,
                },
                "end_ms": {
                    "type": "integer",
                    "description": (
                        "Window end in milliseconds. "
                        "Default: start_ms + 300000 (5 minutes)"
                    ),
                },
                "detail": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "description": (
                        "Detail level. 'summary' = compact (~40 "
                        "tokens/scene). 'full' = canvas regions "
                        "included (~120 tokens/scene)."
                    ),
                    "default": "summary",
                },
                "layout": {
                    "type": "string",
                    "enum": ["A", "B", "C", "D"],
                    "description": (
                        "Layout to return canvas regions for "
                        "(full mode only). Omit to use each "
                        "scene's recommended layout."
                    ),
                },
            },
            "required": ["project_id"],
        },
    ),
]
