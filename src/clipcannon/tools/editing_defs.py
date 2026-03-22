"""Tool definitions for ClipCannon editing MCP tools.

Separates the JSON schema tool definitions from the implementation
to keep both files under the 500-line limit.
"""

from __future__ import annotations

from mcp.types import Tool

EDITING_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_create_edit",
        description=(
            "Create a new edit from an EDL specification. "
            "Defines segments from the source video, with optional "
            "captions, smart crop, audio mixing, and metadata. "
            "Auto-generates caption chunks from transcript if enabled."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "name": {"type": "string", "description": "Human-readable edit name"},
                "target_platform": {
                    "type": "string",
                    "description": "Target platform for the output clip",
                    "enum": [
                        "tiktok", "instagram_reels", "youtube_shorts",
                        "youtube_standard", "youtube_4k", "facebook", "linkedin",
                    ],
                },
                "segments": {
                    "type": "array",
                    "description": (
                        "Array of segment objects defining source time ranges. "
                        "Each segment: {source_start_ms, source_end_ms, "
                        "speed (default 1.0), transition_in, transition_out}"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_start_ms": {
                                "type": "integer",
                                "description": "Start time (ms)",
                            },
                            "source_end_ms": {
                                "type": "integer",
                                "description": "End time (ms)",
                            },
                            "speed": {
                                "type": "number",
                                "description": "Playback speed",
                                "default": 1.0,
                            },
                            "transition_in": {
                                "type": "object",
                                "description": "Transition at start",
                            },
                            "transition_out": {
                                "type": "object",
                                "description": "Transition at end",
                            },
                            "canvas": {
                                "type": "object",
                                "description": (
                                    "Per-segment canvas override. "
                                    "Use regions[] for compositing, "
                                    "zoom{} for animated crop"
                                ),
                            },
                        },
                        "required": ["source_start_ms", "source_end_ms"],
                    },
                    "minItems": 1,
                },
                "captions": {
                    "type": "object",
                    "description": "Caption config",
                },
                "crop": {
                    "type": "object",
                    "description": "Crop config",
                },
                "canvas": {
                    "type": "object",
                    "description": (
                        "Canvas compositing for full AI layout control. "
                        "Keys: enabled, canvas_width, canvas_height, "
                        "background_color, regions[]"
                    ),
                },
                "audio": {
                    "type": "object",
                    "description": "Audio config",
                },
                "metadata": {
                    "type": "object",
                    "description": "Clip metadata",
                },
            },
            "required": ["project_id", "name", "target_platform", "segments"],
        },
    ),
    Tool(
        name="clipcannon_modify_edit",
        description=(
            "Modify an existing draft edit. Applies partial updates "
            "to the EDL, re-validates, and updates the database. "
            "Only draft edits can be modified."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "edit_id": {"type": "string", "description": "Edit identifier"},
                "changes": {
                    "type": "object",
                    "description": (
                        "Partial update: name, segments, captions, "
                        "crop, audio, metadata, render_settings"
                    ),
                },
            },
            "required": ["project_id", "edit_id", "changes"],
        },
    ),
    Tool(
        name="clipcannon_list_edits",
        description=(
            "List edits for a project. Returns compact summaries "
            "with edit_id, name, status, platform, duration, and "
            "segment count. Filter by status optionally."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status",
                    "default": "all",
                    "enum": [
                        "all", "draft", "rendering", "rendered",
                        "approved", "rejected", "failed",
                    ],
                },
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_generate_metadata",
        description=(
            "Generate platform-specific metadata for an edit. "
            "Uses VUD data to create title, description, hashtags, "
            "and thumbnail timestamp."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "edit_id": {"type": "string", "description": "Edit identifier"},
                "target_platform": {
                    "type": "string",
                    "description": "Override target platform",
                    "enum": [
                        "tiktok", "instagram_reels", "youtube_shorts",
                        "youtube_standard", "youtube_4k", "facebook", "linkedin",
                    ],
                },
            },
            "required": ["project_id", "edit_id"],
        },
    ),
]
