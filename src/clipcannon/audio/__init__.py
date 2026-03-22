"""Audio generation engine for ClipCannon.

Provides AI music generation, MIDI composition, programmatic sound
effects, audio mixing with speech-aware ducking, and effects
processing. Three tiers of audio generation are supported:

- Tier 1: ACE-Step v1.5 AI music generation (GPU required)
- Tier 2: MIDI composition + FluidSynth rendering (CPU only)
- Tier 3: Programmatic DSP sound effects (CPU only)

All tiers feed into a shared mixing pipeline that combines sources
with speech-aware ducking and loudness normalization.
"""

from __future__ import annotations

from clipcannon.audio.cleanup import (
    SUPPORTED_CLEANUP_OPS,
    CleanupResult,
    cleanup_audio,
)
from clipcannon.audio.effects import SUPPORTED_EFFECTS, apply_effects
from clipcannon.audio.midi_compose import (
    PRESETS,
    MidiResult,
    compose_midi,
)
from clipcannon.audio.midi_render import render_midi_to_wav
from clipcannon.audio.mixer import MixResult, mix_audio
from clipcannon.audio.music_gen import MusicResult, generate_music
from clipcannon.audio.sfx import (
    SAMPLE_RATE,
    SUPPORTED_SFX_TYPES,
    SfxResult,
    generate_sfx,
)

__all__ = [
    "CleanupResult",
    "MidiResult",
    "MixResult",
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
    "generate_music",
    "generate_sfx",
    "mix_audio",
    "render_midi_to_wav",
]
