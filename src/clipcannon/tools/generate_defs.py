"""Tool definitions for ClipCannon video generation orchestrator."""

from __future__ import annotations

from mcp.types import Tool

GENERATE_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_generate_video",
        description=(
            "Generate a complete video from a text script. "
            "End-to-end pipeline: (1) StyleTTS 2 synthesizes speech "
            "in the target voice with verification loop, (2) LatentSync "
            "maps the audio onto a driver video for lip sync. "
            "Every step is verified. Returns paths to the generated "
            "audio and lip-synced video. Requires a driver video "
            "of the target person's face."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier (for output storage)",
                },
                "script": {
                    "type": "string",
                    "description": "The text script for the person to say",
                },
                "driver_video_path": {
                    "type": "string",
                    "description": (
                        "Path to a webcam video of the target person. "
                        "Face must be clearly visible. Will be looped to match audio length."
                    ),
                },
                "voice_name": {
                    "type": "string",
                    "description": "Voice profile name (omit for default voice)",
                },
                "speed": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Speaking rate (0.5-2.0)",
                },
                "max_voice_attempts": {
                    "type": "integer",
                    "default": 5,
                    "description": "Max voice verification retry attempts",
                },
                "lip_sync_steps": {
                    "type": "integer",
                    "default": 20,
                    "description": "LatentSync diffusion steps (20=quality, 10=fast)",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducibility",
                },
            },
            "required": ["project_id", "script", "driver_video_path"],
        },
    ),
]
