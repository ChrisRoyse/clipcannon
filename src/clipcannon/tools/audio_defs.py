"""Audio tool definitions for ClipCannon MCP server.

Separated from audio.py to keep the implementation module under 500 lines.
Contains AUDIO_TOOL_DEFINITIONS used by the MCP tool registry.
"""

from __future__ import annotations

from mcp.types import Tool

_PID = {"type": "string", "description": "Project identifier"}
_EID = {"type": "string", "description": "Edit identifier to attach audio to"}

AUDIO_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_generate_music",
        description=(
            "Generate original AI background music from a text prompt. "
            "Supports ACE-Step v1.5 (GPU, 4+ GB VRAM) and Meta MusicGen "
            "(GPU, medium model). Use 'model' to select."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "prompt": {"type": "string", "description": "Music description"},
                "duration_s": {"type": "number", "description": "Duration in seconds"},
                "seed": {"type": "integer", "description": "Seed for reproducibility"},
                "volume_db": {"type": "number", "description": "Volume in dB", "default": -18},
                "model": {
                    "type": "string",
                    "description": "Model to use: ace-step (default) or musicgen",
                    "enum": ["ace-step", "musicgen"],
                    "default": "ace-step",
                },
            },
            "required": ["project_id", "edit_id", "prompt", "duration_s"],
        },
    ),
    Tool(
        name="clipcannon_compose_midi",
        description=(
            "Compose a MIDI track from preset and render to WAV. "
            "CPU-only. 12 presets: ambient_pad, upbeat_pop, corporate, "
            "dramatic, minimal_piano, intro_jingle, lofi_chill, "
            "cinematic_epic, tech_corporate, acoustic_folk, synth_wave, "
            "jazz_smooth."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "preset": {
                    "type": "string", "description": "Composition preset",
                    "enum": [
                        "ambient_pad", "upbeat_pop", "corporate",
                        "dramatic", "minimal_piano", "intro_jingle",
                        "lofi_chill", "cinematic_epic", "tech_corporate",
                        "acoustic_folk", "synth_wave", "jazz_smooth",
                    ],
                },
                "duration_s": {"type": "number", "description": "Duration in seconds"},
                "tempo_bpm": {"type": "integer", "description": "Override tempo in BPM"},
                "key": {"type": "string", "description": "Override musical key"},
            },
            "required": ["project_id", "edit_id", "preset", "duration_s"],
        },
    ),
    Tool(
        name="clipcannon_generate_sfx",
        description=(
            "Generate a DSP sound effect. CPU-only, instant. Types: "
            "whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger, "
            "ambient_drone, ambient_texture, pad_swell, nature_bed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "sfx_type": {
                    "type": "string", "description": "Sound effect type",
                    "enum": [
                        "whoosh", "riser", "downer", "impact", "chime",
                        "tick", "bass_drop", "shimmer", "stinger",
                        "ambient_drone", "ambient_texture", "pad_swell",
                        "nature_bed",
                    ],
                },
                "duration_ms": {
                    "type": "integer", "description": "Duration in ms",
                    "default": 500,
                },
                "params": {"type": "object", "description": "Effect-specific params"},
            },
            "required": ["project_id", "edit_id", "sfx_type"],
        },
    ),
    Tool(
        name="clipcannon_audio_cleanup",
        description=(
            "Clean up audio by removing noise, hum, sibilance, or normalizing loudness. "
            "Operations: noise_reduction, de_hum, de_ess, normalize_loudness."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "noise_reduction", "de_hum",
                            "de_ess", "normalize_loudness",
                        ],
                    },
                    "minItems": 1,
                    "description": "Cleanup operations to apply",
                },
                "hum_frequency": {
                    "type": "integer",
                    "default": 50,
                    "description": "Hum frequency: 50 (EU) or 60 (US) Hz",
                },
            },
            "required": ["project_id", "edit_id", "operations"],
        },
    ),
    Tool(
        name="clipcannon_auto_music",
        description=(
            "Automatically analyze a video edit and generate matching "
            "background music. Reads emotion, pacing, and beat data "
            "to choose mood, tempo, and style. Supports tier selection: "
            "'ai' (ACE-Step GPU), 'midi' (CPU MIDI), or 'auto' (tries "
            "AI first, falls back to MIDI)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "style_override": {
                    "type": "string",
                    "description": (
                        "Override detected mood with a style keyword "
                        "(e.g. 'calm', 'upbeat', 'dramatic')"
                    ),
                },
                "tier": {
                    "type": "string",
                    "description": "Generation tier: ai, midi, or auto",
                    "enum": ["ai", "midi", "auto"],
                    "default": "auto",
                },
                "duration_override_s": {
                    "type": "number",
                    "description": "Override duration in seconds (uses edit duration if omitted)",
                },
            },
            "required": ["project_id", "edit_id"],
        },
    ),
    Tool(
        name="clipcannon_compose_music",
        description=(
            "Compose background music from a natural language description. "
            "Uses AI keyword analysis to select MIDI preset, tempo, and key, "
            "then composes and renders to WAV. CPU-only."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "description": {
                    "type": "string",
                    "description": "Natural language music description",
                },
                "duration_s": {
                    "type": "number",
                    "description": "Duration in seconds",
                },
                "tempo_bpm": {
                    "type": "integer",
                    "description": "Override tempo in BPM",
                },
                "key": {
                    "type": "string",
                    "description": "Override musical key (e.g. C, Am, F)",
                },
                "energy": {
                    "type": "string",
                    "description": "Override energy level",
                    "enum": ["low", "medium", "high"],
                },
            },
            "required": ["project_id", "edit_id", "description", "duration_s"],
        },
    ),
]
