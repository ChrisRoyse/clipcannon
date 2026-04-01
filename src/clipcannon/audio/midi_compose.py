"""MIDI composition engine using MIDIUtil.

Generates theory-correct MIDI compositions from preset configurations.
Each preset defines a chord progression, instrumentation, tempo, and
dynamics profile. Uses hardcoded note arrays based on music theory --
no heavyweight music21 dependency required.

Example:
    result = compose_midi(
        preset="ambient_pad",
        duration_s=60.0,
        output_path=Path("/tmp/composition.mid"),
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.audio.midi_ai import MidiPlan

logger = logging.getLogger(__name__)

# MIDI program numbers for instruments
_PROG_PIANO = 0
_PROG_STRINGS = 48
_PROG_PAD = 89  # Warm Pad
_PROG_BASS = 33  # Electric Bass (finger)
_PROG_BRASS = 61  # Brass Section

# Drum channel constants (MIDI channel 9)
_KICK, _SNARE, _HIHAT_CLOSED = 36, 38, 42

# ============================================================
# CHORD PROGRESSIONS (as MIDI note lists per chord)
# ============================================================
_PROGRESSIONS: dict[str, list[list[int]]] = {
    "c_maj7_cycle": [[60, 64, 67, 71], [57, 60, 64, 67], [53, 57, 60, 64], [55, 59, 62, 65]],
    "pop_canon": [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60]],
    "corporate": [[60, 64, 67], [53, 57, 60], [57, 60, 64], [55, 59, 62]],
    "dramatic": [[60, 63, 67], [56, 60, 63], [51, 55, 58], [58, 62, 65]],
    "minimal": [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60]],
    "jingle": [[60, 64, 67], [53, 57, 60], [55, 59, 62], [60, 64, 67]],
    "lofi_chill": [[60, 64, 67, 71], [57, 60, 64, 67], [50, 53, 57, 60], [55, 59, 62, 65]],
    "cinematic_epic": [[57, 60, 64], [53, 57, 60], [60, 64, 67], [55, 59, 62]],
    "tech_corporate": [[60, 64, 67], [52, 55, 59], [57, 60, 64], [53, 57, 60]],
    "acoustic_folk": [[55, 59, 62], [52, 55, 59], [60, 64, 67], [50, 54, 57]],
    "synth_wave": [[53, 56, 60], [48, 51, 55], [56, 60, 63], [51, 55, 58]],
    "jazz_smooth": [[60, 64, 67, 71], [50, 53, 57, 60], [55, 59, 62, 65], [60, 64, 67, 71]],
}

# Melody patterns (scale degree offsets from root, in semitones)
_MELODY_PATTERNS: dict[str, list[int]] = {
    "ambient_pad": [0, 4, 7, 12, 7, 4],
    "upbeat_pop": [0, 2, 4, 7, 4, 2, 0, -1],
    "corporate": [0, 4, 7, 4, 0, 2, 4, 2],
    "dramatic": [0, 3, 7, 12, 15, 12, 7, 3],
    "minimal_piano": [0, 4, 7, 12, 7, 4, 0, -5],
    "intro_jingle": [0, 4, 7, 12, 7, 4, 7, 12],
    "lofi_chill": [0, 4, 7, 11, 7, 4, 0, -1],
    "cinematic_epic": [0, 3, 7, 12, 15, 12, 10, 7],
    "tech_corporate": [0, 4, 7, 4, 2, 4, 7, 4],
    "acoustic_folk": [0, 2, 4, 7, 4, 2, 0, 2],
    "synth_wave": [0, 3, 7, 10, 12, 10, 7, 3],
    "jazz_smooth": [0, 4, 7, 11, 12, 11, 7, 4],
}


@dataclass
class PresetConfig:
    """Configuration for a composition preset."""

    tempo_bpm: int
    key: str
    progression: list[list[int]]
    instruments: list[int]
    has_drums: bool
    dynamics: tuple[int, int]
    melody_pattern: list[int]


# ============================================================
# PRESET REGISTRY (12 presets)
# ============================================================
PRESETS: dict[str, PresetConfig] = {
    "ambient_pad": PresetConfig(
        70, "C", _PROGRESSIONS["c_maj7_cycle"], [_PROG_PAD, _PROG_STRINGS],
        False, (40, 70), _MELODY_PATTERNS["ambient_pad"],
    ),
    "upbeat_pop": PresetConfig(
        128, "C", _PROGRESSIONS["pop_canon"], [_PROG_PIANO, _PROG_BASS],
        True, (70, 100), _MELODY_PATTERNS["upbeat_pop"],
    ),
    "corporate": PresetConfig(
        100, "C", _PROGRESSIONS["corporate"], [_PROG_PIANO, _PROG_STRINGS],
        False, (55, 80), _MELODY_PATTERNS["corporate"],
    ),
    "dramatic": PresetConfig(
        90, "C", _PROGRESSIONS["dramatic"], [_PROG_STRINGS, _PROG_BRASS],
        True, (60, 110), _MELODY_PATTERNS["dramatic"],
    ),
    "minimal_piano": PresetConfig(
        80, "C", _PROGRESSIONS["minimal"], [_PROG_PIANO],
        False, (45, 75), _MELODY_PATTERNS["minimal_piano"],
    ),
    "intro_jingle": PresetConfig(
        120, "C", _PROGRESSIONS["jingle"], [_PROG_PIANO, _PROG_STRINGS, _PROG_BASS],
        True, (70, 100), _MELODY_PATTERNS["intro_jingle"],
    ),
    "lofi_chill": PresetConfig(
        75, "C", _PROGRESSIONS["lofi_chill"], [_PROG_PIANO, _PROG_PAD],
        False, (35, 60), _MELODY_PATTERNS["lofi_chill"],
    ),
    "cinematic_epic": PresetConfig(
        95, "A", _PROGRESSIONS["cinematic_epic"], [_PROG_STRINGS, _PROG_BRASS],
        True, (50, 120), _MELODY_PATTERNS["cinematic_epic"],
    ),
    "tech_corporate": PresetConfig(
        110, "C", _PROGRESSIONS["tech_corporate"], [_PROG_PIANO, _PROG_STRINGS],
        False, (60, 85), _MELODY_PATTERNS["tech_corporate"],
    ),
    "acoustic_folk": PresetConfig(
        105, "G", _PROGRESSIONS["acoustic_folk"], [_PROG_PIANO],
        False, (50, 80), _MELODY_PATTERNS["acoustic_folk"],
    ),
    "synth_wave": PresetConfig(
        118, "F", _PROGRESSIONS["synth_wave"], [_PROG_PAD, _PROG_BASS],
        True, (65, 95), _MELODY_PATTERNS["synth_wave"],
    ),
    "jazz_smooth": PresetConfig(
        112, "C", _PROGRESSIONS["jazz_smooth"], [_PROG_PIANO],
        False, (55, 85), _MELODY_PATTERNS["jazz_smooth"],
    ),
}


@dataclass
class MidiResult:
    """Result of MIDI composition."""

    midi_path: Path
    duration_ms: int
    tempo_bpm: int
    key: str
    preset: str


# ============================================================
# Track-building helpers
# ============================================================


def _add_chord_track(
    midi: object, track: int, channel: int, program: int,
    progression: list[list[int]], beats_per_chord: float,
    total_beats: float, velocity_min: int, velocity_max: int,
) -> None:
    """Add a chord track to the MIDI file."""
    midi.addProgramChange(track, channel, 0, program)  # type: ignore[attr-defined]
    velocity = (velocity_min + velocity_max) // 2
    beat, chord_idx = 0.0, 0
    while beat < total_beats:
        chord = progression[chord_idx % len(progression)]
        dur = min(beats_per_chord, total_beats - beat)
        for note in chord:
            midi.addNote(track, channel, note, beat, dur, velocity)  # type: ignore[attr-defined]
        beat += beats_per_chord
        chord_idx += 1


def _add_melody_track(
    midi: object, track: int, channel: int, program: int,
    progression: list[list[int]], melody_pattern: list[int],
    beats_per_chord: float, total_beats: float,
    velocity_min: int, velocity_max: int,
) -> None:
    """Add a melody track derived from chord roots and scale degree offsets."""
    midi.addProgramChange(track, channel, 0, program)  # type: ignore[attr-defined]
    beat, chord_idx = 0.0, 0
    note_duration = 0.5  # eighth note
    while beat < total_beats:
        root = progression[chord_idx % len(progression)][0]
        for pat_idx, offset in enumerate(melody_pattern):
            note_beat = beat + pat_idx * note_duration
            if note_beat >= total_beats or note_beat >= beat + beats_per_chord:
                break
            note = root + 12 + offset
            vel = velocity_min + ((pat_idx * 7) % (velocity_max - velocity_min))
            midi.addNote(track, channel, note, note_beat, note_duration * 0.9, vel)  # type: ignore[attr-defined]
        beat += beats_per_chord
        chord_idx += 1


def _add_bass_track(
    midi: object, track: int, channel: int,
    progression: list[list[int]], beats_per_chord: float,
    total_beats: float, velocity: int,
) -> None:
    """Add a bass track following chord roots one octave below."""
    midi.addProgramChange(track, channel, 0, _PROG_BASS)  # type: ignore[attr-defined]
    beat, chord_idx = 0.0, 0
    while beat < total_beats:
        root = progression[chord_idx % len(progression)][0] - 12
        dur = min(beats_per_chord, total_beats - beat)
        midi.addNote(track, channel, root, beat, dur, velocity)  # type: ignore[attr-defined]
        beat += beats_per_chord
        chord_idx += 1


def _add_drum_track(
    midi: object, track: int, total_beats: float, velocity: int,
) -> None:
    """Add drum pattern: kick on 1/3, snare on 2/4, hihat on eighths."""
    channel = 9
    beat = 0.0
    while beat < total_beats:
        bar_pos = beat % 4.0
        if bar_pos in (0.0, 2.0):
            midi.addNote(track, channel, _KICK, beat, 0.5, velocity)  # type: ignore[attr-defined]
        if bar_pos in (1.0, 3.0):
            midi.addNote(track, channel, _SNARE, beat, 0.5, velocity - 10)  # type: ignore[attr-defined]
        midi.addNote(track, channel, _HIHAT_CLOSED, beat, 0.25, velocity - 20)  # type: ignore[attr-defined]
        beat += 0.5


# ============================================================
# Shared MIDI setup helper
# ============================================================


def _setup_midi(config: PresetConfig, tempo: int) -> tuple[object, int]:
    """Create a MIDIFile and return (midi, num_tracks).

    Raises:
        ImportError: If midiutil is not installed.
    """
    try:
        from midiutil import MIDIFile  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "MIDIUtil not installed. Install with: pip install MIDIUtil"
        ) from exc

    num_tracks = 2
    if config.has_drums:
        num_tracks += 1
    if len(config.instruments) > 1:
        num_tracks += 1
    midi = MIDIFile(num_tracks)
    midi.addTempo(0, 0, tempo)
    return midi, num_tracks


def _write_tracks(
    midi: object, config: PresetConfig,
    beats_per_chord: float, total_beats: float,
    vel_min: int, vel_max: int,
) -> None:
    """Write chord, melody, bass, and drum tracks to the MIDI file."""
    _add_chord_track(
        midi, 0, 0, config.instruments[0], config.progression,
        beats_per_chord, total_beats, vel_min, vel_max,
    )
    _add_melody_track(
        midi, 1, 1, config.instruments[0], config.progression,
        config.melody_pattern, beats_per_chord, total_beats, vel_min, vel_max,
    )
    current_track = 2
    if len(config.instruments) > 1:
        _add_bass_track(
            midi, current_track, 2, config.progression,
            beats_per_chord, total_beats, (vel_min + vel_max) // 2,
        )
        current_track += 1
    if config.has_drums:
        _add_drum_track(midi, current_track, total_beats, (vel_min + vel_max) // 2)


def _save_midi(midi: object, output_path: Path) -> None:
    """Ensure parent directory exists and write MIDI file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        midi.writeFile(f)  # type: ignore[attr-defined]


# ============================================================
# Public API
# ============================================================


def compose_midi(
    preset: str,
    duration_s: float,
    output_path: Path,
    tempo_bpm: int | None = None,
    key: str | None = None,
) -> MidiResult:
    """Compose a MIDI file from a preset configuration.

    Args:
        preset: Preset name from ``PRESETS``.
        duration_s: Desired duration in seconds.
        output_path: Path to save the MIDI file.
        tempo_bpm: Override tempo (uses preset default if None).
        key: Override key (uses preset default if None).

    Returns:
        MidiResult with composition details.

    Raises:
        ImportError: If midiutil is not installed.
        ValueError: If preset name is unknown.
    """
    if preset not in PRESETS:
        raise ValueError(
            f"Unknown preset: {preset}. Valid: {', '.join(sorted(PRESETS))}"
        )

    config = PRESETS[preset]
    tempo = tempo_bpm if tempo_bpm is not None else config.tempo_bpm
    used_key = key if key is not None else config.key
    total_beats = duration_s * (tempo / 60.0)

    midi, _ = _setup_midi(config, tempo)
    _write_tracks(midi, config, 4.0, total_beats, *config.dynamics)
    _save_midi(midi, output_path)

    duration_ms = int(duration_s * 1000)
    logger.info(
        "MIDI composed: preset=%s, tempo=%d BPM, key=%s, duration=%.1fs, path=%s",
        preset, tempo, used_key, duration_s, output_path,
    )
    return MidiResult(
        midi_path=output_path, duration_ms=duration_ms,
        tempo_bpm=tempo, key=used_key, preset=preset,
    )


def compose_midi_sectioned(
    plan: MidiPlan,
    output_path: Path,
) -> MidiResult:
    """Compose a multi-section MIDI file from a MidiPlan.

    Each section (intro, verse, chorus, bridge, outro) uses different
    dynamics as specified in the plan. The preset determines chord
    progression, instrumentation, and melody pattern.

    Args:
        plan: A ``MidiPlan`` with sections, preset, tempo, and key.
        output_path: Path to save the MIDI file.

    Returns:
        MidiResult with composition details.

    Raises:
        ImportError: If midiutil is not installed.
        ValueError: If preset is unknown or plan has no sections.
    """
    if plan.preset not in PRESETS:
        raise ValueError(
            f"Unknown preset: {plan.preset}. Valid: {', '.join(sorted(PRESETS))}"
        )
    if not plan.sections:
        raise ValueError("MidiPlan must have at least one section")

    config = PRESETS[plan.preset]
    tempo = plan.tempo_bpm
    beats_per_bar = float(plan.time_sig[0])

    total_bars = sum(s.bars for s in plan.sections)
    total_beats = float(total_bars * beats_per_bar)

    midi, _ = _setup_midi(config, tempo)

    for section in plan.sections:
        section_beats = float(section.bars * beats_per_bar)
        vel_min, vel_max = section.dynamics
        _write_tracks(midi, config, beats_per_bar, section_beats, vel_min, vel_max)
        logger.debug(
            "Section '%s': %d bars, dynamics=(%d,%d)",
            section.name, section.bars, vel_min, vel_max,
        )

    _save_midi(midi, output_path)

    duration_s = total_beats / (tempo / 60.0)
    duration_ms = int(duration_s * 1000)
    logger.info(
        "Sectioned MIDI composed: preset=%s, tempo=%d BPM, key=%s, "
        "sections=%d, duration=%.1fs, path=%s",
        plan.preset, tempo, plan.key, len(plan.sections), duration_s, output_path,
    )
    return MidiResult(
        midi_path=output_path, duration_ms=duration_ms,
        tempo_bpm=tempo, key=plan.key, preset=plan.preset,
    )
