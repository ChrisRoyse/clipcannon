"""Tool definitions for ClipCannon voice cloning MCP tools.

Separates the JSON schema tool definitions from the implementation.
"""

from __future__ import annotations

from mcp.types import Tool

_PID = {"type": "string", "description": "Project identifier"}

VOICE_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_prepare_voice_data",
        description=(
            "Prepare voice training data from one or more ingested projects. "
            "Splits vocal stems at silence boundaries, matches transcript text, "
            "normalizes volume, phonemizes, and writes train/val split files. "
            "Requires projects to have been ingested with vocals.wav and "
            "transcript_words populated."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "List of project identifiers to extract voice data from",
                },
                "speaker_label": {
                    "type": "string",
                    "description": "Speaker label for the training data (e.g. 'host')",
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "Output directory for clips and manifests. "
                        "Defaults to ~/.clipcannon/voice_data/<speaker_label>/"
                    ),
                },
                "min_clip_duration_ms": {
                    "type": "integer",
                    "default": 1000,
                    "description": "Minimum clip duration in milliseconds",
                },
                "max_clip_duration_ms": {
                    "type": "integer",
                    "default": 12000,
                    "description": "Maximum clip duration in milliseconds",
                },
            },
            "required": ["project_ids", "speaker_label"],
        },
    ),
    Tool(
        name="clipcannon_voice_profiles",
        description=(
            "Manage voice profiles for voice cloning. "
            "Actions: 'list' (all profiles), 'get' (by name), "
            "'create' (new profile), 'delete' (by name), "
            "'update' (modify fields). Profiles track model path, "
            "training status, and verification threshold."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "delete", "update"],
                    "description": "Action to perform on voice profiles",
                },
                "name": {
                    "type": "string",
                    "description": "Profile name (required for get/create/delete/update)",
                },
                "model_path": {
                    "type": "string",
                    "description": "Path to voice model directory (required for create)",
                },
                "training_status": {
                    "type": "string",
                    "enum": ["pending", "preparing", "training", "ready", "failed"],
                    "description": "Training status (for update)",
                },
                "training_hours": {
                    "type": "number",
                    "description": "Training hours completed (for update)",
                },
                "sample_rate": {
                    "type": "integer",
                    "default": 24000,
                    "description": "Audio sample rate in Hz",
                },
            },
            "required": ["action"],
        },
    ),
    Tool(
        name="clipcannon_speak",
        description=(
            "Generate speech in a cloned voice using Qwen3-TTS. "
            "Takes text and a voice profile name, synthesizes audio "
            "with iterative verification: compares output against "
            "the speaker's voice fingerprint and retries if needed. "
            "Uses SDPA attention on RTX 5090 Blackwell with BF16. "
            "Without a voice profile, uses the model's default voice."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "text": {
                    "type": "string",
                    "description": "Text to synthesize as speech",
                },
                "voice_name": {
                    "type": "string",
                    "description": "Voice profile name (omit for default voice)",
                },
                "speed": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Speaking rate multiplier (0.5-2.0)",
                },
                "max_attempts": {
                    "type": "integer",
                    "default": 5,
                    "description": "Max verification retry attempts (best-of-N)",
                },
                "enhance": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Post-process with Resemble Enhance to remove metallic "
                        "vocoder artifacts and upsample to 44.1kHz broadcast quality. "
                        "Adds ~10s processing time. Set false for raw TTS output."
                    ),
                },
                "prosody_style": {
                    "type": "string",
                    "enum": [
                        "energetic", "calm", "emphatic", "varied",
                        "fast", "slow", "rising", "question", "best",
                    ],
                    "description": (
                        "Auto-select a reference clip whose prosody matches "
                        "this style. Uses prosody_segments data from ingest. "
                        "Overrides the default reference clip. Requires the "
                        "voice profile's training projects to have been ingested."
                    ),
                },
                "temperature": {
                    "type": "number",
                    "default": 0.7,
                    "description": (
                        "Sampling temperature (0.3-0.9). Higher = more "
                        "expressive prosody but slightly lower identity "
                        "match. 0.7 = balanced for video, 0.5 = conservative."
                    ),
                },
            },
            "required": ["project_id", "text"],
        },
    ),
    Tool(
        name="clipcannon_speak_optimized",
        description=(
            "SECS-optimized voice synthesis using Qwen3-TTS. Generates "
            "N candidates, scores each against your voice fingerprint "
            "using a speaker encoder, and returns the one that sounds "
            "most like you. Selects the best reference clip automatically. "
            "Slower but higher quality than clipcannon_speak."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "text": {
                    "type": "string",
                    "description": "Text to synthesize",
                },
                "voice_name": {
                    "type": "string",
                    "description": "Voice profile name (must have trained model)",
                },
                "n_candidates": {
                    "type": "integer",
                    "default": 8,
                    "description": "Candidates to generate and rank (8 = good tradeoff)",
                },
                "enhance": {
                    "type": "boolean",
                    "default": True,
                    "description": (
                        "Post-process with Resemble Enhance to remove metallic "
                        "vocoder artifacts and upsample to 44.1kHz broadcast quality."
                    ),
                },
            },
            "required": ["project_id", "text", "voice_name"],
        },
    ),
]
