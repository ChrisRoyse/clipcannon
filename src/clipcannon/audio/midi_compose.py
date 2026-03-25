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

logger = logging.getLogger(__name__)

# ============================================================
# MIDI NOTE CONSTANTS
# ============================================================
# MIDI note numbers for C4 octave (middle C = 60)
_C4, _D4, _E4, _F4, _G4, _A4, _B4 = 60, 62, 64, 65, 67, 69, 71
_C5, _D5, _E5 = 72, 74, 76
_C3, _D3, _E3, _F3, _G3, _A3, _B3 = 48, 50, 52, 53, 55, 57, 59

# ============================================================
# CHORD DEFINITIONS (root-relative semitones)
# ============================================================
_MAJOR = (0, 4, 7)
_MINOR = (0, 3, 7)
_MAJ7 = (0, 4, 7, 11)
_MIN7 = (0, 3, 7, 10)
_DOM7 = (0, 4, 7, 10)

# Key note mappings (C major / C minor roots)
_KEY_ROOTS: dict[str, int] = {
    "C": 60, "D": 62, "E": 64, "F": 65, "G": 67, "A": 69, "B": 71,
    "Db": 61, "Eb": 63, "Gb": 66, "Ab": 68, "Bb": 70,
}

# ============================================================
# CHORD PROGRESSIONS (as MIDI note lists per chord)
# ============================================================
# I-vi-IV-V in C major with 7ths
_PROG_C_MAJ7_CYCLE: list[list[int]] = [
    [60, 64, 67, 71],  # Cmaj7
    [57, 60, 64, 67],  # Am7
    [53, 57, 60, 64],  # Fmaj7 (voiced)
    [55, 59, 62, 65],  # G7
]

# I-V-vi-IV pop canon in C major
_PROG_POP_CANON: list[list[int]] = [
    [60, 64, 67],  # C
    [55, 59, 62],  # G
    [57, 60, 64],  # Am
    [53, 57, 60],  # F
]

# I-vi-IV-V in C major
_PROG_C_STANDARD: list[list[int]] = [
    [60, 64, 67],  # C
    [57, 60, 64],  # Am
    [53, 57, 60],  # F
    [55, 59, 62],  # G
]

# I-IV-vi-V corporate feel
_PROG_CORPORATE: list[list[int]] = [
    [60, 64, 67],  # C
    [53, 57, 60],  # F
    [57, 60, 64],  # Am
    [55, 59, 62],  # G
]

# i-VI-III-VII in C minor (dramatic)
_PROG_DRAMATIC: list[list[int]] = [
    [60, 63, 67],  # Cm
    [56, 60, 63],  # Ab
    [51, 55, 58],  # Eb
    [58, 62, 65],  # Bb
]

# Simple I-V-vi-IV for minimal piano
_PROG_MINIMAL: list[list[int]] = [
    [60, 64, 67],  # C
    [55, 59, 62],  # G
    [57, 60, 64],  # Am
    [53, 57, 60],  # F
]

# Jingle: I-IV-V-I bright
_PROG_JINGLE: list[list[int]] = [
    [60, 64, 67],  # C
    [53, 57, 60],  # F
    [55, 59, 62],  # G
    [60, 64, 67],  # C
]

# Melody patterns (scale degree offsets from root, in semitones)
_MELODY_PATTERNS: dict[str, list[int]] = {
    "ambient_pad": [0, 4, 7, 12, 7, 4],
    "upbeat_pop": [0, 2, 4, 7, 4, 2, 0, -1],
    "corporate": [0, 4, 7, 4, 0, 2, 4, 2],
    "dramatic": [0, 3, 7, 12, 15, 12, 7, 3],
    "minimal_piano": [0, 4, 7, 12, 7, 4, 0, -5],
    "intro_jingle": [0, 4, 7, 12, 7, 4, 7, 12],
}

# MIDI program numbers for instruments
_PROG_PIANO = 0
_PROG_STRINGS = 48
_PROG_PAD = 89  # Warm Pad
_PROG_BASS = 33  # Electric Bass (finger)
_PROG_BRASS = 61  # Brass Section

# Drum channel constants (MIDI channel 9)
_KICK = 36
_SNARE = 38
_HIHAT_CLOSED = 42
_HIHAT_OPEN = 46


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
# PRESET REGISTRY
# ============================================================
PRESETS: dict[str, PresetConfig] = {
    "ambient_pad": PresetConfig(
        tempo_bpm=70,
        key="C",
        progression=_PROG_C_MAJ7_CYCLE,
        instruments=[_PROG_PAD, _PROG_STRINGS],
        has_drums=False,
        dynamics=(40, 70),
        melody_pattern=_MELODY_PATTERNS["ambient_pad"],
    ),
    "upbeat_pop": PresetConfig(
        tempo_bpm=128,
        key="C",
        progression=_PROG_POP_CANON,
        instruments=[_PROG_PIANO, _PROG_BASS],
        has_drums=True,
        dynamics=(70, 100),
        melody_pattern=_MELODY_PATTERNS["upbeat_pop"],
    ),
    "corporate": PresetConfig(
        tempo_bpm=100,
        key="C",
        progression=_PROG_CORPORATE,
        instruments=[_PROG_PIANO, _PROG_STRINGS],
        has_drums=False,
        dynamics=(55, 80),
        melody_pattern=_MELODY_PATTERNS["corporate"],
    ),
    "dramatic": PresetConfig(
        tempo_bpm=90,
        key="C",
        progression=_PROG_DRAMATIC,
        instruments=[_PROG_STRINGS, _PROG_BRASS],
        has_drums=True,
        dynamics=(60, 110),
        melody_pattern=_MELODY_PATTERNS["dramatic"],
    ),
    "minimal_piano": PresetConfig(
        tempo_bpm=80,
        key="C",
        progression=_PROG_MINIMAL,
        instruments=[_PROG_PIANO],
        has_drums=False,
        dynamics=(45, 75),
        melody_pattern=_MELODY_PATTERNS["minimal_piano"],
    ),
    "intro_jingle": PresetConfig(
        tempo_bpm=120,
        key="C",
        progression=_PROG_JINGLE,
        instruments=[_PROG_PIANO, _PROG_STRINGS, _PROG_BASS],
        has_drums=True,
        dynamics=(70, 100),
        melody_pattern=_MELODY_PATTERNS["intro_jingle"],
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


def _add_chord_track(
    midi: object,
    track: int,
    channel: int,
    program: int,
    progression: list[list[int]],
    beats_per_chord: float,
    total_beats: float,
    velocity_min: int,
    velocity_max: int,
) -> None:
    """Add a chord track to the MIDI file."""
    midi.addProgramChange(track, channel, 0, program)  # type: ignore[attr-defined]
    velocity = (velocity_min + velocity_max) // 2
    beat = 0.0
    chord_idx = 0

    while beat < total_beats:
        chord = progression[chord_idx % len(progression)]
        dur = min(beats_per_chord, total_beats - beat)
        for note in chord:
            midi.addNote(track, channel, note, beat, dur, velocity)  # type: ignore[attr-defined]
        beat += beats_per_chord
        chord_idx += 1


def _add_melody_track(
    midi: object,
    track: int,
    channel: int,
    program: int,
    progression: list[list[int]],
    melody_pattern: list[int],
    beats_per_chord: float,
    total_beats: float,
    velocity_min: int,
    velocity_max: int,
) -> None:
    """Add a melody track derived from chord roots and scale degree offsets."""
    midi.addProgramChange(track, channel, 0, program)  # type: ignore[attr-defined]

    beat = 0.0
    chord_idx = 0
    note_duration = 0.5  # eighth note

    while beat < total_beats:
        chord = progression[chord_idx % len(progression)]
        root = chord[0]

        for pat_idx, offset in enumerate(melody_pattern):
            note_beat = beat + pat_idx * note_duration
            if note_beat >= total_beats:
                break
            if note_beat >= beat + beats_per_chord:
                break
            note = root + 12 + offset  # Melody one octave above root
            # Vary velocity slightly for expression
            vel = velocity_min + ((pat_idx * 7) % (velocity_max - velocity_min))
            midi.addNote(  # type: ignore[attr-defined]
                track, channel, note, note_beat,
                note_duration * 0.9, vel,
            )

        beat += beats_per_chord
        chord_idx += 1


def _add_bass_track(
    midi: object,
    track: int,
    channel: int,
    progression: list[list[int]],
    beats_per_chord: float,
    total_beats: float,
    velocity: int,
) -> None:
    """Add a bass track following chord roots one octave below."""
    midi.addProgramChange(track, channel, 0, _PROG_BASS)  # type: ignore[attr-defined]

    beat = 0.0
    chord_idx = 0

    while beat < total_beats:
        chord = progression[chord_idx % len(progression)]
        root = chord[0] - 12  # Bass one octave below
        dur = min(beats_per_chord, total_beats - beat)
        midi.addNote(track, channel, root, beat, dur, velocity)  # type: ignore[attr-defined]
        beat += beats_per_chord
        chord_idx += 1


def _add_drum_track(
    midi: object,
    track: int,
    total_beats: float,
    velocity: int,
) -> None:
    """Add drum pattern: kick on 1/3, snare on 2/4, hihat on eighths."""
    channel = 9  # Standard MIDI drum channel

    beat = 0.0
    while beat < total_beats:
        bar_pos = beat % 4.0

        # Kick on beats 1 and 3
        if bar_pos in (0.0, 2.0):
            midi.addNote(track, channel, _KICK, beat, 0.5, velocity)  # type: ignore[attr-defined]

        # Snare on beats 2 and 4
        if bar_pos in (1.0, 3.0):
            midi.addNote(track, channel, _SNARE, beat, 0.5, velocity - 10)  # type: ignore[attr-defined]

        # Hihat on every eighth note
        midi.addNote(track, channel, _HIHAT_CLOSED, beat, 0.25, velocity - 20)  # type: ignore[attr-defined]

        beat += 0.5  # Advance by eighth note


def compose_midi(
    preset: str,
    duration_s: float,
    output_path: Path,
    tempo_bpm: int | None = None,
    key: str | None = None,
) -> MidiResult:
    """Compose a MIDI file from a preset configuration.

    Creates a multi-track MIDI file with chords, melody, optional bass
    and drums based on the selected preset. Saves the MIDI file to
    the specified output path.

    Args:
        preset: Preset name (ambient_pad, upbeat_pop, corporate,
            dramatic, minimal_piano, intro_jingle).
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
    try:
        from midiutil import MIDIFile  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "MIDIUtil not installed. Install with: pip install MIDIUtil"
        ) from exc

    if preset not in PRESETS:
        valid = ", ".join(sorted(PRESETS.keys()))
        raise ValueError(
            f"Unknown preset: {preset}. Valid presets: {valid}"
        )

    config = PRESETS[preset]
    tempo = tempo_bpm if tempo_bpm is not None else config.tempo_bpm
    used_key = key if key is not None else config.key

    # Calculate total beats from duration and tempo
    beats_per_second = tempo / 60.0
    total_beats = duration_s * beats_per_second
    beats_per_chord = 4.0  # One chord per bar (4/4 time)

    # Determine number of tracks
    num_tracks = 2  # chord + melody minimum
    if config.has_drums:
        num_tracks += 1
    if len(config.instruments) > 1:
        num_tracks += 1  # bass track

    midi = MIDIFile(num_tracks)
    midi.addTempo(0, 0, tempo)

    vel_min, vel_max = config.dynamics

    # Track 0: Chords (first instrument)
    _add_chord_track(
        midi, track=0, channel=0,
        program=config.instruments[0],
        progression=config.progression,
        beats_per_chord=beats_per_chord,
        total_beats=total_beats,
        velocity_min=vel_min,
        velocity_max=vel_max,
    )

    # Track 1: Melody (first instrument, different channel)
    _add_melody_track(
        midi, track=1, channel=1,
        program=config.instruments[0],
        progression=config.progression,
        melody_pattern=config.melody_pattern,
        beats_per_chord=beats_per_chord,
        total_beats=total_beats,
        velocity_min=vel_min,
        velocity_max=vel_max,
    )

    current_track = 2

    # Bass track (if multiple instruments)
    if len(config.instruments) > 1:
        _add_bass_track(
            midi, track=current_track, channel=2,
            progression=config.progression,
            beats_per_chord=beats_per_chord,
            total_beats=total_beats,
            velocity=(vel_min + vel_max) // 2,
        )
        current_track += 1

    # Drum track
    if config.has_drums:
        _add_drum_track(
            midi, track=current_track,
            total_beats=total_beats,
            velocity=(vel_min + vel_max) // 2,
        )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write MIDI file
    with open(output_path, "wb") as f:
        midi.writeFile(f)

    duration_ms = int(duration_s * 1000)

    logger.info(
        "MIDI composed: preset=%s, tempo=%d BPM, key=%s, duration=%.1fs, path=%s",
        preset, tempo, used_key, duration_s, output_path,
    )

    return MidiResult(
        midi_path=output_path,
        duration_ms=duration_ms,
        tempo_bpm=tempo,
        key=used_key,
        preset=preset,
    )
