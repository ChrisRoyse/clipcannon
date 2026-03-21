"""FluidSynth MIDI-to-WAV rendering.

Renders MIDI files to high-quality WAV audio using FluidSynth with
SoundFont instrument samples. Requires the fluidsynth Python bindings
and a SoundFont file (e.g., GeneralUser_GS.sf2).

Example:
    wav_path = await render_midi_to_wav(
        midi_path=Path("/tmp/composition.mid"),
        output_path=Path("/tmp/composition.wav"),
    )
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default SoundFont search locations
_SOUNDFONT_SEARCH_PATHS: list[str] = [
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/soundfonts/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/GeneralUser_GS.sf2",
    "/usr/local/share/soundfonts/GeneralUser_GS.sf2",
    "~/.clipcannon/models/GeneralUser_GS.sf2",
]


def _find_default_soundfont() -> Path | None:
    """Search common locations for a SoundFont file.

    Returns:
        Path to first found SoundFont, or None if none found.
    """
    for sf_path_str in _SOUNDFONT_SEARCH_PATHS:
        sf_path = Path(sf_path_str).expanduser()
        if sf_path.exists():
            return sf_path
    return None


async def render_midi_to_wav(
    midi_path: Path,
    output_path: Path,
    soundfont_path: Path | None = None,
    sample_rate: int = 44100,
) -> Path:
    """Render a MIDI file to WAV audio using FluidSynth.

    Loads the specified SoundFont (or searches for a default), creates
    a FluidSynth synthesizer, renders the MIDI file, and saves the
    result as a WAV file.

    Args:
        midi_path: Path to the input MIDI file.
        output_path: Path for the output WAV file.
        soundfont_path: Path to SoundFont file. Searches defaults if None.
        sample_rate: Output sample rate in Hz.

    Returns:
        Path to the rendered WAV file.

    Raises:
        ImportError: If fluidsynth Python bindings are not installed.
        FileNotFoundError: If MIDI file or SoundFont cannot be found.
        RuntimeError: If rendering fails or output is empty.
    """
    try:
        import fluidsynth  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "FluidSynth Python bindings not installed. "
            "Install with: pip install pyfluidsynth"
        ) from exc

    # Validate MIDI file exists
    if not midi_path.exists():
        raise FileNotFoundError(f"MIDI file not found: {midi_path}")

    # Find SoundFont
    sf_path = soundfont_path
    if sf_path is None:
        sf_path = _find_default_soundfont()
    if sf_path is None:
        raise FileNotFoundError(
            "No SoundFont file found. Provide soundfont_path or install a "
            "SoundFont to one of: "
            + ", ".join(_SOUNDFONT_SEARCH_PATHS)
        )
    if not sf_path.exists():
        raise FileNotFoundError(f"SoundFont file not found: {sf_path}")

    logger.info(
        "Rendering MIDI to WAV: midi=%s, sf=%s, rate=%d",
        midi_path, sf_path, sample_rate,
    )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Create FluidSynth synthesizer and render
    fs = fluidsynth.Synth(samplerate=float(sample_rate))
    try:
        sfid = fs.sfload(str(sf_path))
        if sfid < 0:
            raise RuntimeError(
                f"Failed to load SoundFont: {sf_path}"
            )

        # Use FluidSynth's MIDI file player
        fs.midi_to_audio(str(midi_path), str(output_path))
    finally:
        fs.delete()

    # Validate output
    if not output_path.exists():
        raise RuntimeError(
            f"FluidSynth rendering failed: output not created at {output_path}"
        )
    if output_path.stat().st_size == 0:
        raise RuntimeError(
            f"FluidSynth rendering produced empty file at {output_path}"
        )

    logger.info("MIDI rendered to WAV: %s", output_path)

    return output_path
