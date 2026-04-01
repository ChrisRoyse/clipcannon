"""Programmatic DSP sound effects using numpy and scipy.

Generates mathematical sound effects through digital signal processing.
All effects are synthesized from scratch -- no samples or external
audio files required. Output is 16-bit WAV at 44100 Hz.

Example:
    result = generate_sfx(
        sfx_type="whoosh",
        output_path=Path("/tmp/whoosh.wav"),
        duration_ms=500,
    )
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100

# Supported SFX types
SUPPORTED_SFX_TYPES = frozenset({
    "whoosh", "riser", "downer", "impact", "chime",
    "tick", "bass_drop", "shimmer", "stinger",
    "ambient_drone", "ambient_texture", "pad_swell", "nature_bed",
})


@dataclass
class SfxResult:
    """Result of sound effect generation.

    Attributes:
        file_path: Path to the generated WAV file.
        duration_ms: Actual duration in milliseconds.
        sample_rate: Sample rate of the output.
        sfx_type: Type of sound effect generated.
    """

    file_path: Path
    duration_ms: int
    sample_rate: int
    sfx_type: str


def _time_array(duration_ms: int) -> np.ndarray:
    """Create a time array for the given duration.

    Args:
        duration_ms: Duration in milliseconds.

    Returns:
        numpy array of time values in seconds.
    """
    num_samples = int(SAMPLE_RATE * duration_ms / 1000)
    return np.linspace(0, duration_ms / 1000, num_samples, endpoint=False)


def _apply_fade(signal: np.ndarray, fade_samples: int = 50) -> np.ndarray:
    """Apply zero-crossing fade-in and fade-out to prevent clicks.

    Args:
        signal: Audio signal array.
        fade_samples: Number of samples for fade-in/fade-out.

    Returns:
        Signal with fades applied.
    """
    if len(signal) < fade_samples * 2:
        fade_samples = len(signal) // 4

    if fade_samples > 0:
        fade_in = np.linspace(0.0, 1.0, fade_samples)
        fade_out = np.linspace(1.0, 0.0, fade_samples)
        signal[:fade_samples] *= fade_in
        signal[-fade_samples:] *= fade_out

    return signal


def _normalize(signal: np.ndarray, target: float = 0.8) -> np.ndarray:
    """Normalize signal to target fraction of max amplitude.

    Args:
        signal: Audio signal array.
        target: Target amplitude as fraction of maximum (0.0-1.0).

    Returns:
        Normalized signal.
    """
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal * (target / peak)
    return signal


def _to_int16(signal: np.ndarray) -> np.ndarray:
    """Convert float signal to 16-bit integer for WAV output.

    Args:
        signal: Float audio signal (range -1.0 to 1.0).

    Returns:
        int16 numpy array.
    """
    return np.clip(signal * 32767, -32768, 32767).astype(np.int16)


def _save_wav(signal: np.ndarray, output_path: Path) -> None:
    """Save signal as 16-bit WAV file.

    Args:
        signal: Float audio signal.
        output_path: Path to save the WAV file.
    """
    from scipy.io import wavfile  # type: ignore[import-untyped]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    int16_signal = _to_int16(signal)
    wavfile.write(str(output_path), SAMPLE_RATE, int16_signal)


def _gen_whoosh(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Logarithmic frequency chirp (200-8000 Hz) with exponential decay."""
    from scipy.signal import chirp  # type: ignore[import-untyped]

    t = _time_array(duration_ms)
    duration_s = duration_ms / 1000.0
    signal = chirp(t, f0=200, f1=8000, t1=duration_s, method="logarithmic")
    # Exponential decay envelope
    envelope = np.exp(-3.0 * t / duration_s)
    return signal * envelope


def _gen_riser(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Ascending chirp (100-4000 Hz) with crescendo envelope."""
    from scipy.signal import chirp  # type: ignore[import-untyped]

    t = _time_array(duration_ms)
    duration_s = duration_ms / 1000.0
    signal = chirp(t, f0=100, f1=4000, t1=duration_s, method="linear")
    # Crescendo envelope (increasing amplitude)
    envelope = np.linspace(0.2, 1.0, len(t))
    return signal * envelope


def _gen_downer(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Descending chirp (4000-100 Hz) with decrescendo envelope."""
    from scipy.signal import chirp  # type: ignore[import-untyped]

    t = _time_array(duration_ms)
    duration_s = duration_ms / 1000.0
    signal = chirp(t, f0=4000, f1=100, t1=duration_s, method="linear")
    # Decrescendo envelope
    envelope = np.linspace(1.0, 0.1, len(t))
    return signal * envelope


def _gen_impact(duration_ms: int, params: dict[str, object]) -> np.ndarray:
    """White noise burst with fast exponential decay."""
    t = _time_array(duration_ms)
    duration_s = duration_ms / 1000.0
    decay_rate = float(params.get("decay_rate", 20))
    noise = np.random.default_rng(42).standard_normal(len(t))
    envelope = np.exp(-decay_rate * t / duration_s)
    return noise * envelope


def _gen_chime(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Harmonically-related sine tones (880 Hz base) with independent decay."""
    t = _time_array(duration_ms)
    duration_s = duration_ms / 1000.0

    base_freq = 880.0
    signal = np.zeros(len(t))

    for harmonic, amplitude, decay in [(1, 1.0, 3.0), (2, 0.5, 5.0), (3, 0.3, 7.0)]:
        freq = base_freq * harmonic
        tone = amplitude * np.sin(2 * np.pi * freq * t)
        envelope = np.exp(-decay * t / duration_s)
        signal += tone * envelope

    return signal


def _gen_tick(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Short 1000 Hz click with very sharp exponential decay."""
    t = _time_array(duration_ms)
    duration_s = duration_ms / 1000.0
    freq = 1000.0
    signal = np.sin(2 * np.pi * freq * t)
    # Very sharp attack and decay
    envelope = np.exp(-50.0 * t / duration_s)
    return signal * envelope


def _gen_bass_drop(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Low-frequency sine sweep (200-40 Hz) with sub-harmonic resonance."""
    t = _time_array(duration_ms)
    duration_s = duration_ms / 1000.0

    # Frequency sweep from 200 to 40 Hz
    freq = 200.0 - (160.0 * t / duration_s)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    signal = np.sin(phase)

    # Add resonance via second harmonic
    signal += 0.3 * np.sin(phase * 0.5)

    # Sustain envelope with slight decay
    envelope = np.exp(-1.0 * t / duration_s)
    return signal * envelope


def _gen_shimmer(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """High-frequency filtered noise with slow attack and decay envelope."""
    t = _time_array(duration_ms)

    # Generate white noise
    rng = np.random.default_rng(123)
    noise = rng.standard_normal(len(t))

    # Simple high-pass filter: subtract smoothed version
    kernel_size = int(SAMPLE_RATE * 0.002)  # 2ms smoothing
    if kernel_size > 1:
        kernel = np.ones(kernel_size) / kernel_size
        smoothed = np.convolve(noise, kernel, mode="same")
        noise = noise - smoothed

    # Slow attack and decay envelope
    attack_samples = int(len(t) * 0.3)
    decay_samples = len(t) - attack_samples
    attack = np.linspace(0.0, 1.0, attack_samples)
    decay = np.exp(-2.0 * np.linspace(0, 1, decay_samples))
    envelope = np.concatenate([attack, decay])

    return noise * envelope


def _gen_stinger(duration_ms: int, params: dict[str, object]) -> np.ndarray:
    """Combined impact burst + rising sweep for dramatic transitions."""
    half_ms = duration_ms // 2
    impact = _gen_impact(half_ms, params)
    riser = _gen_riser(half_ms, params)

    # Crossfade at junction
    overlap = min(50, len(impact) // 4, len(riser) // 4)
    if overlap > 0:
        fade_out = np.linspace(1.0, 0.0, overlap)
        fade_in = np.linspace(0.0, 1.0, overlap)
        impact[-overlap:] *= fade_out
        riser[:overlap] *= fade_in

    return np.concatenate([impact, riser])


def _gen_ambient_drone(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Layered sine waves (110/165/220 Hz) with 0.1 Hz LFO and decay."""
    t = _time_array(duration_ms)
    duration_s = duration_ms / 1000.0
    signal = (np.sin(2 * np.pi * 110.0 * t)
              + 0.7 * np.sin(2 * np.pi * 165.0 * t)
              + 0.5 * np.sin(2 * np.pi * 220.0 * t))
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.1 * t)
    envelope = np.exp(-1.0 * t / max(duration_s, 0.001))
    return signal * lfo * envelope


def _gen_ambient_texture(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Filtered pink noise with ~4 Hz granular amplitude gates."""
    t = _time_array(duration_ms)
    n = len(t)
    rng = np.random.default_rng(77)
    pink = np.cumsum(rng.standard_normal(n))
    # High-pass: subtract running mean to remove DC drift
    ks = min(int(SAMPLE_RATE * 0.05), n // 2) or 1
    pink -= np.convolve(pink, np.ones(ks) / ks, mode="same")
    # Granular gates at ~4 Hz with soft attack/decay
    gate = (0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)) ** 0.5
    signal = pink * gate
    # Attack/decay envelope
    env = np.ones(n)
    a_len, d_len = min(int(n * 0.15), n), min(int(n * 0.2), n)
    if a_len > 0:
        env[:a_len] = np.linspace(0.0, 1.0, a_len)
    if d_len > 0:
        env[-d_len:] = np.linspace(1.0, 0.0, d_len)
    return signal * env


def _gen_pad_swell(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Harmonic series (220 Hz) with slow ADSR (30/40/30) envelope."""
    t = _time_array(duration_ms)
    n = len(t)
    signal = np.zeros(n)
    for h, amp in [(1, 1.0), (2, 0.6), (3, 0.35), (4, 0.2)]:
        signal += amp * np.sin(2 * np.pi * 220.0 * h * t)
    # ADSR: 30% attack, 40% sustain at 0.8, 30% release
    a = max(int(n * 0.3), 1)
    s = max(int(n * 0.4), 1)
    r = max(n - a - s, 1)
    env = np.concatenate([
        np.linspace(0.0, 1.0, a),
        np.full(s, 0.8),
        np.linspace(0.8, 0.0, r),
    ])
    env = env[:n] if len(env) > n else np.pad(env, (0, n - len(env)))
    return signal * env


def _gen_nature_bed(duration_ms: int, _params: dict[str, object]) -> np.ndarray:
    """Pink noise (octave bands) plus bandpass (200-2000 Hz) layer with fades."""
    from scipy.signal import butter, sosfilt  # type: ignore[import-untyped]

    t = _time_array(duration_ms)
    n = len(t)
    rng = np.random.default_rng(99)
    # Pink noise via weighted octave bands
    pink = np.zeros(n)
    for i in range(8):
        step = 2 ** i
        band = rng.standard_normal((n + step - 1) // step) / np.sqrt(2.0 ** i)
        pink += np.repeat(band, step)[:n]
    # Bandpass-filtered white noise layer
    nyq = SAMPLE_RATE / 2.0
    lo, hi = 200.0 / nyq, min(2000.0 / nyq, 0.99)
    white = rng.standard_normal(n)
    if lo < hi:
        filtered = sosfilt(butter(4, [lo, hi], btype="band", output="sos"), white)
    else:
        filtered = white
    signal = pink + 0.3 * filtered
    # Gentle 10% fade in/out
    fl = max(int(n * 0.1), 1)
    env = np.ones(n)
    env[:fl] = np.linspace(0.0, 1.0, fl)
    env[-fl:] = np.linspace(1.0, 0.0, fl)
    return signal * env


# Generator dispatch table
_SfxGenerator = Callable[[int, dict[str, object]], np.ndarray]

_GENERATORS: dict[str, _SfxGenerator] = {
    "whoosh": _gen_whoosh,
    "riser": _gen_riser,
    "downer": _gen_downer,
    "impact": _gen_impact,
    "chime": _gen_chime,
    "tick": _gen_tick,
    "bass_drop": _gen_bass_drop,
    "shimmer": _gen_shimmer,
    "stinger": _gen_stinger,
    "ambient_drone": _gen_ambient_drone,
    "ambient_texture": _gen_ambient_texture,
    "pad_swell": _gen_pad_swell,
    "nature_bed": _gen_nature_bed,
}


def generate_sfx(
    sfx_type: str,
    output_path: Path,
    duration_ms: int = 500,
    params: dict[str, object] | None = None,
) -> SfxResult:
    """Generate a programmatic sound effect.

    Synthesizes audio using mathematical DSP functions, applies
    fade-in/fade-out to prevent clicks, normalizes to 80% amplitude,
    and saves as a 16-bit WAV file at 44100 Hz.

    Args:
        sfx_type: Type of effect (whoosh, riser, downer, impact, chime,
            tick, bass_drop, shimmer, stinger, ambient_drone,
            ambient_texture, pad_swell, nature_bed).
        output_path: Path to save the generated WAV file.
        duration_ms: Duration in milliseconds (default 500).
        params: Optional parameters for the specific effect type.

    Returns:
        SfxResult with generation details.

    Raises:
        ValueError: If sfx_type is unknown.
    """
    if sfx_type not in _GENERATORS:
        valid = ", ".join(sorted(SUPPORTED_SFX_TYPES))
        raise ValueError(
            f"Unknown sfx_type: {sfx_type}. Supported types: {valid}"
        )

    effective_params = params or {}

    logger.info(
        "Generating SFX: type=%s, duration=%dms, path=%s",
        sfx_type, duration_ms, output_path,
    )

    # Generate the raw signal
    generator = _GENERATORS[sfx_type]
    signal = generator(duration_ms, effective_params)

    # Apply zero-crossing fade to prevent clicks/pops
    signal = _apply_fade(signal, fade_samples=50)

    # Normalize to 80% of max amplitude
    signal = _normalize(signal, target=0.8)

    # Save as WAV
    _save_wav(signal, output_path)

    # Validate output
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"Failed to generate SFX at {output_path}"
        )

    actual_duration_ms = int(len(signal) / SAMPLE_RATE * 1000)

    logger.info("SFX generated: %s (%dms)", sfx_type, actual_duration_ms)

    return SfxResult(
        file_path=output_path,
        duration_ms=actual_duration_ms,
        sample_rate=SAMPLE_RATE,
        sfx_type=sfx_type,
    )
