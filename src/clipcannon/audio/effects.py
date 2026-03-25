"""Audio effects processing using pedalboard.

Applies professional-grade audio effects chains to audio files
using Spotify's pedalboard library. Supports reverb, compression,
EQ filtering, and limiting with sensible defaults.

Example:
    output = apply_effects(
        audio_path=Path("/tmp/input.wav"),
        output_path=Path("/tmp/processed.wav"),
        effects=["reverb", "compression", "limiter"],
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Default parameters for each effect type
_EFFECT_DEFAULTS: dict[str, dict[str, float]] = {
    "reverb": {
        "room_size": 0.5,
        "damping": 0.5,
        "wet_level": 0.3,
        "dry_level": 0.7,
        "width": 1.0,
    },
    "compression": {
        "threshold_db": -20.0,
        "ratio": 4.0,
        "attack_ms": 10.0,
        "release_ms": 100.0,
    },
    "eq_low_cut": {
        "cutoff_hz": 80.0,
    },
    "eq_high_cut": {
        "cutoff_hz": 16000.0,
    },
    "limiter": {
        "threshold_db": -1.0,
        "release_ms": 100.0,
    },
}

SUPPORTED_EFFECTS = frozenset(_EFFECT_DEFAULTS.keys())


def apply_effects(
    audio_path: Path,
    output_path: Path,
    effects: list[str],
    params: dict[str, object] | None = None,
) -> Path:
    """Apply an audio effects chain to an audio file.

    Loads the audio, constructs a pedalboard from the requested effects
    in order, processes the audio through the chain, and saves the
    result.

    Args:
        audio_path: Path to the input audio file.
        output_path: Path for the processed output file.
        effects: Ordered list of effect names to apply.
            Supported: reverb, compression, eq_low_cut, eq_high_cut,
            limiter.
        params: Optional parameter overrides keyed by effect name.
            Example: {"reverb": {"room_size": 0.8, "wet_level": 0.4}}

    Returns:
        Path to the processed output file.

    Raises:
        ImportError: If pedalboard is not installed.
        FileNotFoundError: If input audio file is not found.
        ValueError: If an unsupported effect is requested.
    """
    try:
        import pedalboard  # type: ignore[import-untyped]
        from pedalboard.io import AudioFile  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "pedalboard not installed. Install with: pip install pedalboard"
        ) from exc

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Validate effect names
    for effect_name in effects:
        if effect_name not in SUPPORTED_EFFECTS:
            valid = ", ".join(sorted(SUPPORTED_EFFECTS))
            raise ValueError(
                f"Unsupported effect: {effect_name}. Supported: {valid}"
            )

    effective_params = params or {}

    logger.info(
        "Applying effects chain %s to %s",
        effects, audio_path,
    )

    # Build the effects chain
    effect_instances: list[object] = []

    for effect_name in effects:
        # Merge defaults with user overrides
        defaults = dict(_EFFECT_DEFAULTS[effect_name])
        overrides = effective_params.get(effect_name, {})
        if isinstance(overrides, dict):
            defaults.update(overrides)

        if effect_name == "reverb":
            effect_instances.append(
                pedalboard.Reverb(
                    room_size=float(defaults["room_size"]),
                    damping=float(defaults["damping"]),
                    wet_level=float(defaults["wet_level"]),
                    dry_level=float(defaults["dry_level"]),
                    width=float(defaults["width"]),
                )
            )
        elif effect_name == "compression":
            effect_instances.append(
                pedalboard.Compressor(
                    threshold_db=float(defaults["threshold_db"]),
                    ratio=float(defaults["ratio"]),
                    attack_ms=float(defaults["attack_ms"]),
                    release_ms=float(defaults["release_ms"]),
                )
            )
        elif effect_name == "eq_low_cut":
            effect_instances.append(
                pedalboard.HighpassFilter(
                    cutoff_frequency_hz=float(defaults["cutoff_hz"]),
                )
            )
        elif effect_name == "eq_high_cut":
            effect_instances.append(
                pedalboard.LowpassFilter(
                    cutoff_frequency_hz=float(defaults["cutoff_hz"]),
                )
            )
        elif effect_name == "limiter":
            effect_instances.append(
                pedalboard.Limiter(
                    threshold_db=float(defaults["threshold_db"]),
                    release_ms=float(defaults["release_ms"]),
                )
            )

    board = pedalboard.Pedalboard(effect_instances)

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Process audio
    with AudioFile(str(audio_path)) as f:
        sample_rate = f.samplerate
        audio = f.read(f.frames)

    processed = board(audio, sample_rate)

    with AudioFile(
        str(output_path), "w",
        samplerate=sample_rate,
        num_channels=processed.shape[0],
    ) as f:
        f.write(processed)

    logger.info("Effects applied: %s -> %s", audio_path, output_path)

    return output_path
