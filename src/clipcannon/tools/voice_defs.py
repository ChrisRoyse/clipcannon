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
            "normalizes volume, phonemizes, and writes train/val split files "
            "in StyleTTS2-compatible format. Requires projects to have been "
            "ingested with vocals.wav and transcript_words populated."
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
            "Generate speech in a cloned voice using StyleTTS 2. "
            "Takes text and a voice profile name, synthesizes audio "
            "with iterative verification: compares output against "
            "the speaker's voice fingerprint and retries if needed. "
            "Returns an audio asset attached to the project. "
            "Without a trained voice profile, uses the default model voice."
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
                    "description": "Max verification retry attempts",
                },
            },
            "required": ["project_id", "text"],
        },
    ),
    Tool(
        name="clipcannon_train_voice",
        description=(
            "Fine-tune StyleTTS 2 on voice training data to create "
            "a custom voice profile. Requires voice data prepared "
            "via clipcannon_prepare_voice_data. Training takes 8-12 "
            "hours on RTX 5090 and produces a permanent voice model."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "voice_name": {
                    "type": "string",
                    "description": "Name for the voice profile",
                },
                "data_dir": {
                    "type": "string",
                    "description": "Path to prepared training data directory",
                },
                "epochs": {
                    "type": "integer",
                    "default": 50,
                    "description": "Training epochs",
                },
                "batch_size": {
                    "type": "integer",
                    "default": 4,
                    "description": "Training batch size",
                },
            },
            "required": ["voice_name", "data_dir"],
        },
    ),
]
