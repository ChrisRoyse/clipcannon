"""Audio generation engine for ClipCannon.

Provides AI music generation, MIDI composition, programmatic sound
effects, audio mixing with speech-aware ducking, and effects
processing. Four tiers of audio generation:

- Tier 1A: ACE-Step v1.5 AI music generation (GPU, 48kHz stereo)
- Tier 1B: MusicGen (Meta AudioCraft) music generation (GPU, 44.1kHz mono)
- Tier 2: AI-enhanced MIDI composition + FluidSynth rendering (CPU)
- Tier 3: Programmatic DSP sound effects + ambient textures (CPU)

All tiers feed into a shared mixing pipeline that combines sources
with speech-aware ducking and loudness normalization. A video-aware
MusicPlanner reads analysis data to auto-generate matching music.
"""

from __future__ import annotations

from clipcannon.audio.cleanup import (
    SUPPORTED_CLEANUP_OPS,
    CleanupResult,
    cleanup_audio,
)
from clipcannon.audio.effects import SUPPORTED_EFFECTS, apply_effects
from clipcannon.audio.midi_ai import (
    MidiPlan,
    MidiSection,
    plan_midi_from_keywords,
    plan_midi_from_prompt,
)
from clipcannon.audio.midi_compose import (
    PRESETS,
    MidiResult,
    compose_midi,
    compose_midi_sectioned,
)
from clipcannon.audio.midi_render import render_midi_to_wav
from clipcannon.audio.mixer import MixResult, mix_audio
from clipcannon.audio.music_gen import MusicResult, generate_music
from clipcannon.audio.music_planner import MusicBrief, MusicPlanner
from clipcannon.audio.musicgen import generate_music_musicgen
from clipcannon.audio.sfx import (
    SAMPLE_RATE,
    SUPPORTED_SFX_TYPES,
    SfxResult,
    generate_sfx,
)

__all__ = [
    "CleanupResult",
    "MidiPlan",
    "MidiResult",
    "MidiSection",
    "MixResult",
    "MusicBrief",
    "MusicPlanner",
    "MusicResult",
    "PRESETS",
    "SAMPLE_RATE",
    "SUPPORTED_CLEANUP_OPS",
    "SUPPORTED_EFFECTS",
    "SUPPORTED_SFX_TYPES",
    "SfxResult",
    "apply_effects",
    "cleanup_audio",
    "compose_midi",
    "compose_midi_sectioned",
    "generate_music",
    "generate_music_musicgen",
    "generate_sfx",
    "mix_audio",
    "plan_midi_from_keywords",
    "plan_midi_from_prompt",
    "render_midi_to_wav",
]
