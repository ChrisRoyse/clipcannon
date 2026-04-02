"""Tool definitions for MouthMemory lip-sync v2 MCP tools."""

from __future__ import annotations

from mcp.types import Tool

MOUTHMEMORY_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_lip_sync_v2",
        description=(
            "Generate lip-synced video using MouthMemory retrieval engine. "
            "Uses REAL mouth frames instead of neural generation -- zero blur, "
            "full resolution. Works on ANY person in ANY ingested video. "
            "In self-source mode (no voice_name), the driver video's own "
            "mouth frames are used as the atlas. In atlas mode (with voice_name), "
            "uses a pre-built mouth atlas for richer viseme coverage."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier for output storage",
                },
                "audio_path": {
                    "type": "string",
                    "description": (
                        "Path to target speech audio "
                        "(from clipcannon_speak or any WAV file)"
                    ),
                },
                "driver_video_path": {
                    "type": "string",
                    "description": (
                        "Path to driver video with visible face. "
                        "If omitted, auto-extracts webcam from project."
                    ),
                },
                "voice_name": {
                    "type": "string",
                    "description": (
                        "Voice profile name for atlas mode. "
                        "If omitted, uses self-source mode "
                        "(driver video as its own atlas)."
                    ),
                },
                "fps": {
                    "type": "integer",
                    "default": 25,
                    "description": "Output frame rate (default: 25)",
                },
                "blend_mode": {
                    "type": "string",
                    "enum": ["laplacian", "gaussian", "alpha"],
                    "default": "laplacian",
                    "description": "Blending method for mouth composite",
                },
                "temporal_smooth": {
                    "type": "number",
                    "default": 0.5,
                    "description": (
                        "Temporal smoothing sigma "
                        "(0 = none, 1 = heavy, default: 0.5)"
                    ),
                },
            },
            "required": ["project_id", "audio_path"],
        },
    ),
    Tool(
        name="clipcannon_build_mouth_atlas",
        description=(
            "Build a mouth atlas for a voice profile from its training "
            "project videos. One-time offline operation. Indexes mouth "
            "frames from all training projects at 25fps, labels with "
            "visemes, and stores in a persistent atlas database. "
            "The atlas provides richer viseme coverage for lip_sync_v2."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "voice_name": {
                    "type": "string",
                    "description": "Voice profile name (e.g. 'boris')",
                },
                "project_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Specific project IDs to include. "
                        "If omitted, uses all training_projects from profile."
                    ),
                },
                "min_quality": {
                    "type": "number",
                    "default": 0.2,
                    "description": "Minimum quality score for included frames",
                },
            },
            "required": ["voice_name"],
        },
    ),
]
