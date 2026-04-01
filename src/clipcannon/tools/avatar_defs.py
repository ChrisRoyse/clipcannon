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
            "the audio drives the lip movement. Output preserves the "
            "original video resolution. The video is automatically "
            "looped (ping-pong) if the audio is longer."
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
                        "Path to audio file (from clipcannon_speak or any source). "
                        "Any format FFmpeg can decode (WAV recommended)."
                    ),
                },
                "driver_video_path": {
                    "type": "string",
                    "description": (
                        "Path to driver video with visible face. Use "
                        "clipcannon_extract_webcam to extract from an ingested video."
                    ),
                },
                "inference_steps": {
                    "type": "integer",
                    "default": 20,
                    "description": (
                        "Diffusion steps: 20 = good quality, 30-40 = better, 10 = faster"
                    ),
                },
                "guidance_scale": {
                    "type": "number",
                    "default": 1.5,
                    "description": (
                        "Classifier-free guidance: 1.5 = balanced, 2.0 = stronger lip sync"
                    ),
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed for reproducibility",
                },
            },
            "required": ["project_id", "audio_path", "driver_video_path"],
        },
    ),
    Tool(
        name="clipcannon_extract_webcam",
        description=(
            "Extract the webcam/face region from an ingested video as a "
            "standalone video file suitable for use as a lip-sync driver. "
            "Uses scene_map face detection data from ingest to locate the "
            "webcam PIP overlay or face region, then FFmpeg-crops it from "
            "the source video. The extracted video preserves the original "
            "frame rate. Run clipcannon_ingest first to populate scene_map."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier (must be ingested)",
                },
                "start_ms": {
                    "type": "integer",
                    "description": (
                        "Start time in ms (default: 0). Use to extract a "
                        "specific segment of the webcam."
                    ),
                },
                "end_ms": {
                    "type": "integer",
                    "description": (
                        "End time in ms (default: full duration). Use to "
                        "extract a specific segment."
                    ),
                },
                "padding_pct": {
                    "type": "number",
                    "default": 0.15,
                    "description": (
                        "Extra padding around the face region as a fraction "
                        "(0.15 = 15% padding on each side). Prevents tight crops."
                    ),
                },
            },
            "required": ["project_id"],
        },
    ),
]
