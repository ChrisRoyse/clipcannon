"""Audio mixing pipeline with speech-aware ducking.

Combines source audio, background music, and sound effects into a
single mixed output with automatic ducking that reduces music volume
during speech segments. Uses pydub for audio manipulation.

Example:
    result = await mix_audio(
        source_audio_path=Path("/tmp/speech.wav"),
        output_path=Path("/tmp/final_mix.wav"),
        background_music_path=Path("/tmp/music.wav"),
        duck_under_speech=True,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MixResult:
    """Result of audio mixing.

    Attributes:
        file_path: Path to the mixed audio file.
        duration_ms: Duration of the mix in milliseconds.
        sample_rate: Sample rate of the output.
        layers_mixed: Number of audio layers combined.
    """

    file_path: Path
    duration_ms: int
    sample_rate: int
    layers_mixed: int


def _detect_speech_regions(
    audio_segment: object,
    window_ms: int = 50,
    threshold_rms: float = 300.0,
) -> list[tuple[int, int]]:
    """Detect speech regions using RMS energy analysis.

    Analyzes audio in small windows and marks regions where RMS energy
    exceeds the threshold as speech. Adjacent speech windows are merged
    into contiguous regions.

    Args:
        audio_segment: pydub AudioSegment of the source speech.
        window_ms: Analysis window size in milliseconds.
        threshold_rms: RMS energy threshold for speech detection.

    Returns:
        List of (start_ms, end_ms) tuples marking speech regions.
    """
    duration_ms = len(audio_segment)  # type: ignore[arg-type]
    speech_windows: list[bool] = []

    for start in range(0, duration_ms, window_ms):
        end = min(start + window_ms, duration_ms)
        chunk = audio_segment[start:end]  # type: ignore[index]
        rms = chunk.rms  # type: ignore[attr-defined]
        speech_windows.append(rms > threshold_rms)

    # Merge adjacent speech windows into regions
    regions: list[tuple[int, int]] = []
    in_speech = False
    region_start = 0

    for i, is_speech in enumerate(speech_windows):
        pos_ms = i * window_ms
        if is_speech and not in_speech:
            region_start = pos_ms
            in_speech = True
        elif not is_speech and in_speech:
            regions.append((region_start, pos_ms))
            in_speech = False

    if in_speech:
        regions.append((region_start, len(speech_windows) * window_ms))

    return regions


def _apply_ducking(
    music_segment: object,
    speech_regions: list[tuple[int, int]],
    duck_level_db: float,
    attack_ms: int,
    release_ms: int,
) -> object:
    """Apply volume ducking to music during speech regions.

    Reduces music volume by duck_level_db during speech with smooth
    attack and release ramps.

    Args:
        music_segment: pydub AudioSegment of the background music.
        speech_regions: List of (start_ms, end_ms) speech regions.
        duck_level_db: Volume reduction in dB (negative value).
        attack_ms: Ramp-down time before speech in milliseconds.
        release_ms: Ramp-up time after speech in milliseconds.

    Returns:
        Modified pydub AudioSegment with ducking applied.
    """
    try:
        import pydub  # type: ignore[import-untyped]  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "pydub not installed. Install with: pip install pydub"
        ) from exc

    music_duration = len(music_segment)  # type: ignore[arg-type]
    result = music_segment  # type: ignore[assignment]

    for start_ms, end_ms in speech_regions:
        # Calculate ducking region with attack/release ramps
        duck_start = max(0, start_ms - attack_ms)
        duck_end = min(music_duration, end_ms + release_ms)

        if duck_start >= music_duration:
            continue

        # Split music into: before-duck | duck-region | after-duck
        before = result[:duck_start]  # type: ignore[index]
        duck_region = result[duck_start:duck_end]  # type: ignore[index]
        after = result[duck_end:]  # type: ignore[index]

        # Apply volume reduction to the duck region
        ducked = duck_region + duck_level_db  # type: ignore[operator]

        # Reassemble
        result = before + ducked + after  # type: ignore[operator]

    return result


async def mix_audio(
    source_audio_path: Path,
    output_path: Path,
    background_music_path: Path | None = None,
    sfx_entries: list[dict[str, object]] | None = None,
    music_volume_db: float = -18.0,
    duck_under_speech: bool = True,
    duck_level_db: float = -6.0,
    duck_attack_ms: int = 200,
    duck_release_ms: int = 300,
    normalize: bool = True,
    sample_rate: int = 44100,
) -> MixResult:
    """Mix multiple audio sources into a single output file.

    Combines source audio (speech), optional background music with
    speech-aware ducking, and optional sound effects at specified
    offsets. Layers are mixed bottom to top: music -> speech -> SFX.

    Args:
        source_audio_path: Path to the source audio (speech) file.
        output_path: Path to save the mixed output WAV file.
        background_music_path: Optional path to background music file.
        sfx_entries: Optional list of SFX dicts with keys:
            path (str), offset_ms (int), volume_db (float).
        music_volume_db: Volume adjustment for background music in dB.
        duck_under_speech: Whether to duck music during speech.
        duck_level_db: Additional volume reduction during speech in dB.
        duck_attack_ms: Ducking ramp-down time in milliseconds.
        duck_release_ms: Ducking ramp-up time in milliseconds.
        normalize: Whether to apply peak normalization.
        sample_rate: Output sample rate in Hz.

    Returns:
        MixResult with mixing details.

    Raises:
        ImportError: If pydub is not installed.
        FileNotFoundError: If source audio file is not found.
    """
    try:
        from pydub import AudioSegment  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "pydub not installed. Install with: pip install pydub"
        ) from exc

    if not source_audio_path.exists():
        raise FileNotFoundError(
            f"Source audio file not found: {source_audio_path}"
        )

    logger.info(
        "Mixing audio: source=%s, music=%s, sfx_count=%d",
        source_audio_path,
        background_music_path,
        len(sfx_entries) if sfx_entries else 0,
    )

    # Load source audio
    source = AudioSegment.from_file(str(source_audio_path))
    source = source.set_frame_rate(sample_rate)
    layers_mixed = 1

    # Start with the source as the base mix
    mix = source

    # Layer 1 (bottom): Background music
    if background_music_path is not None and background_music_path.exists():
        music = AudioSegment.from_file(str(background_music_path))
        music = music.set_frame_rate(sample_rate)

        # Adjust music volume
        music = music + music_volume_db

        # Loop or trim music to match source duration
        source_duration = len(source)
        if len(music) < source_duration:
            # Loop music to fill duration
            loops_needed = (source_duration // len(music)) + 1
            music = music * loops_needed
        music = music[:source_duration]

        # Apply ducking if requested
        if duck_under_speech:
            speech_regions = _detect_speech_regions(source)
            if speech_regions:
                music = _apply_ducking(
                    music,
                    speech_regions,
                    duck_level_db=duck_level_db,
                    attack_ms=duck_attack_ms,
                    release_ms=duck_release_ms,
                )

        # Overlay music under source
        mix = music.overlay(source)
        layers_mixed += 1

    # Layer 2 (top): Sound effects at specified offsets
    if sfx_entries:
        for entry in sfx_entries:
            sfx_path = Path(str(entry["path"]))
            offset_ms = int(entry.get("offset_ms", 0))  # type: ignore[arg-type]
            volume_db = float(entry.get("volume_db", 0.0))  # type: ignore[arg-type]

            if not sfx_path.exists():
                logger.warning("SFX file not found, skipping: %s", sfx_path)
                continue

            sfx = AudioSegment.from_file(str(sfx_path))
            sfx = sfx.set_frame_rate(sample_rate)
            sfx = sfx + volume_db

            mix = mix.overlay(sfx, position=offset_ms)
            layers_mixed += 1

    # Normalize if requested
    if normalize:
        # Simple peak normalization to -1 dBFS
        target_dbfs = -1.0
        change_db = target_dbfs - mix.max_dBFS
        mix = mix + change_db

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Export
    mix.export(str(output_path), format="wav")

    duration_ms = len(mix)

    logger.info(
        "Audio mixed: %d layers, duration=%dms, path=%s",
        layers_mixed, duration_ms, output_path,
    )

    return MixResult(
        file_path=output_path,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        layers_mixed=layers_mixed,
    )
