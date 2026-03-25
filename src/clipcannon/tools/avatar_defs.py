"""Tool definitions for ClipCannon avatar/lip-sync MCP tools."""

from __future__ import annotations

from mcp.types import Tool

AVATAR_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_lip_sync",
        description=(
            "Generate a lip-synced talking-head video by mapping audio "
            "onto a driver video of a person's face. Uses LatentSync 1.6 "
            "(ByteDance) diffusion-based lip sync. Requires ~18GB VRAM. "
            "The driver video provides the face and head movements; "
            "the audio drives the lip movement. Output is a video where "
            "the person appears to speak the provided audio."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "audio_path": {
                    "type": "string",
                    "description": (
                        "Path to WAV audio file (from clipcannon_speak or any audio source)"
                    ),
                },
                "driver_video_path": {
                    "type": "string",
                    "description": (
                        "Path to driver video with visible face (webcam recording, "
                        "any length — will be looped to match audio duration)"
                    ),
                },
                "inference_steps": {
                    "type": "integer",
                    "default": 20,
                    "description": "Diffusion steps (20 = good quality, 10 = faster)",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducibility",
                },
            },
            "required": ["project_id", "audio_path", "driver_video_path"],
        },
    ),
]
