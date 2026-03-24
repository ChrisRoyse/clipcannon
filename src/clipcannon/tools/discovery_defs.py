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
            "gaps) with convergence quality scoring (silence_gap, "
            "sentence_end, scene_boundary signals). Includes transcript, "
            "canvas regions, story_beat (from narrative analysis), and "
            "moment_character label (passionate_claim / excited_demo / "
            "engaged_explanation / screen_walkthrough / calm_narration). "
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
        name="clipcannon_find_cut_points",
        description=(
            "Find natural edit boundaries near a timestamp with "
            "cross-stream convergence scoring. Searches silence gaps, "
            "beat hits, scene boundaries, and sentence endings within "
            "a configurable range. Returns cut points scored by signal "
            "convergence: 'perfect' when 3+ signals align (silence + "
            "beat + sentence), 'excellent' for 2 signals, 'good' for "
            "single signals. Convergence points include all contributing "
            "signal types. No credits charged."
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
    Tool(
        name="clipcannon_get_narrative_flow",
        description=(
            "Analyze narrative coherence of proposed edit segments "
            "BEFORE creating an edit. Takes proposed source time ranges "
            "and shows what the speaker says at each segment boundary, "
            "what content is being skipped in gaps between segments, "
            "and warns about broken promise-payoff patterns. ALWAYS "
            "call this before create_edit when using non-contiguous "
            "segments. No credits charged."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_ms": {"type": "integer"},
                            "end_ms": {"type": "integer"},
                        },
                        "required": ["start_ms", "end_ms"],
                    },
                    "minItems": 1,
                    "description": (
                        "Proposed segment time ranges from the source "
                        "video, each with start_ms and end_ms"
                    ),
                },
            },
            "required": ["project_id", "segments"],
        },
    ),
    Tool(
        name="clipcannon_find_safe_cuts",
        description=(
            "Find audio-safe cut points across the ENTIRE video by "
            "cross-referencing ALL analysis streams: silence gaps, "
            "sentence endings (word-level), beat positions, scene "
            "boundaries, text change events, and emotion energy. "
            "Each cut point includes the exact words before and after "
            "the gap, whether the thought is complete, recommended "
            "padding in ms, and a safety rating. Returns cuts sorted "
            "by safety score (safest first). Use these timestamps "
            "directly as segment boundaries in create_edit — the "
            "padding is already calculated. ALWAYS use this tool "
            "instead of manually picking timestamps. No credits charged."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "min_silence_ms": {
                    "type": "integer",
                    "description": (
                        "Minimum silence gap duration to consider (default 400ms). "
                        "Lower values find more cuts but may clip audio."
                    ),
                    "default": 400,
                },
            },
            "required": ["project_id"],
        },
    ),
]
