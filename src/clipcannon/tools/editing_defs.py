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
        name="clipcannon_auto_trim",
        description=(
            "Analyze transcript to find filler words and long pauses, "
            "then generate optimized segments that remove them. "
            "Returns segments ready for clipcannon_create_edit. "
            "Filler words: um, uh, like, basically, literally, you know, I mean, etc. "
            "Pauses: silence gaps exceeding threshold (default 800ms)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "pause_threshold_ms": {
                    "type": "integer",
                    "description": "Minimum pause duration to remove (default: 800ms)",
                    "default": 800,
                },
                "merge_gap_ms": {
                    "type": "integer",
                    "description": "Merge segments separated by less than this (default: 200ms)",
                    "default": 200,
                },
                "min_segment_ms": {
                    "type": "integer",
                    "description": "Drop segments shorter than this (default: 500ms)",
                    "default": 500,
                },
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_color_adjust",
        description=(
            "Apply color grading to an edit. Adjusts brightness, contrast, "
            "saturation, gamma, and hue. Can be applied globally or per-segment. "
            "Values: brightness(-1 to 1), contrast(0-3), saturation(0-3), "
            "gamma(0.1-10), hue_shift(-180 to 180 degrees)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "edit_id": {"type": "string", "description": "Edit identifier"},
                "brightness": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Brightness (-1.0 to 1.0)",
                },
                "contrast": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Contrast (0.0 to 3.0)",
                },
                "saturation": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Saturation (0.0 to 3.0)",
                },
                "gamma": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Gamma (0.1 to 10.0)",
                },
                "hue_shift": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Hue shift (-180 to 180)",
                },
                "segment_id": {
                    "type": "integer",
                    "description": "Apply to specific segment (omit for global)",
                },
            },
            "required": ["project_id", "edit_id"],
        },
    ),
    Tool(
        name="clipcannon_add_motion",
        description=(
            "Add motion effect to an edit segment. Supports zoom_in, zoom_out, "
            "pan_left, pan_right, pan_up, pan_down, ken_burns. "
            "Ken Burns combines zoom with diagonal pan for cinematic movement."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "edit_id": {"type": "string", "description": "Edit identifier"},
                "segment_id": {"type": "integer", "description": "Segment to apply motion to"},
                "effect": {
                    "type": "string",
                    "enum": [
                        "zoom_in", "zoom_out",
                        "pan_left", "pan_right",
                        "pan_up", "pan_down",
                        "ken_burns",
                    ],
                    "description": "Motion effect type",
                },
                "start_scale": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Starting zoom scale (0.5-3.0)",
                },
                "end_scale": {
                    "type": "number",
                    "default": 1.3,
                    "description": "Ending zoom scale (0.5-3.0)",
                },
                "easing": {
                    "type": "string",
                    "enum": ["linear", "ease_in", "ease_out", "ease_in_out"],
                    "default": "linear",
                    "description": "Easing function",
                },
            },
            "required": ["project_id", "edit_id", "segment_id", "effect"],
        },
    ),
    Tool(
        name="clipcannon_add_overlay",
        description=(
            "Add a visual overlay to an edit. Supports lower_third (speaker name/title), "
            "title_card (full-screen text), logo, watermark, and cta (call-to-action). "
            "Each overlay has position, timing, font, colors, and optional animation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "edit_id": {"type": "string", "description": "Edit identifier"},
                "overlay_type": {
                    "type": "string",
                    "enum": ["lower_third", "title_card", "logo", "watermark", "cta"],
                    "description": "Overlay type",
                },
                "text": {"type": "string", "description": "Main text content"},
                "subtitle": {"type": "string", "description": "Subtitle text (lower_third only)"},
                "position": {
                    "type": "string",
                    "enum": [
                        "bottom_left", "bottom_center", "bottom_right",
                        "top_left", "top_center", "top_right", "center",
                    ],
                    "default": "bottom_left",
                },
                "start_ms": {"type": "integer", "description": "Overlay start time (ms)"},
                "end_ms": {"type": "integer", "description": "Overlay end time (ms)"},
                "opacity": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Overlay opacity (0-1)",
                },
                "font_size": {
                    "type": "integer",
                    "default": 36,
                    "description": "Font size (8-200)",
                },
                "text_color": {
                    "type": "string",
                    "default": "#FFFFFF",
                    "description": "Text color hex",
                },
                "bg_color": {
                    "type": "string",
                    "default": "#000000",
                    "description": "Background color hex",
                },
                "bg_opacity": {
                    "type": "number",
                    "default": 0.7,
                    "description": "Background opacity (0-1)",
                },
                "animation": {
                    "type": "string",
                    "enum": ["none", "fade_in", "fade_out", "slide_up", "slide_down"],
                    "default": "fade_in",
                },
                "animation_duration_ms": {
                    "type": "integer",
                    "default": 500,
                    "description": "Animation duration (ms)",
                },
            },
            "required": ["project_id", "edit_id", "overlay_type", "text", "start_ms", "end_ms"],
        },
    ),
]
