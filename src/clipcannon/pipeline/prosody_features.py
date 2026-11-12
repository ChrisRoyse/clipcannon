"""Prosody feature extraction (F0, energy, rate) for prosody_analysis."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class ProsodyFeatures:
    """Prosodic features for a single segment."""

    f0_mean: float
    f0_std: float
    f0_min: float
    f0_max: float
    f0_range: float
    energy_mean: float
    energy_peak: float
    energy_std: float
    speaking_rate_wpm: float
    pitch_contour_type: str
    energy_level: str
    has_emphasis: bool
    has_breath: bool
    prosody_score: float


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load audio as mono float64."""
    from scipy.io import wavfile

    sr, data = wavfile.read(str(audio_path))
    if data.dtype == np.int16:
        audio = data.astype(np.float64) / 32768.0
    elif data.dtype == np.int32:
        audio = data.astype(np.float64) / 2147483648.0
    elif data.dtype in (np.float32, np.float64):
        audio = data.astype(np.float64)
    else:
        audio = data.astype(np.float64)

    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    return audio, sr


def _extract_prosody(audio: np.ndarray, sr: int, word_count: int,
                     duration_s: float) -> ProsodyFeatures:
    """Extract prosodic features from an audio segment."""
    import pyworld as pw

    # F0 extraction via WORLD vocoder
    f0, _timeaxis = pw.harvest(audio, sr, frame_period=5.0)
    voiced = f0[f0 > 0]

    if len(voiced) < 5:
        return ProsodyFeatures(
            f0_mean=0, f0_std=0, f0_min=0, f0_max=0, f0_range=0,
            energy_mean=0, energy_peak=0, energy_std=0,
            speaking_rate_wpm=0, pitch_contour_type="flat",
            energy_level="low", has_emphasis=False, has_breath=False,
            prosody_score=0,
        )

    f0_mean = float(np.mean(voiced))
    f0_std = float(np.std(voiced))
    f0_min = float(np.min(voiced))
    f0_max = float(np.max(voiced))
    f0_range = f0_max - f0_min

    # Energy (RMS in 50ms windows)
    hop = int(sr * 0.05)
    n_frames = max(1, len(audio) // hop)
    rms = np.array([
        np.sqrt(np.mean(audio[i * hop:(i + 1) * hop] ** 2))
        for i in range(n_frames)
    ])
    energy_mean = float(np.mean(rms))
    energy_peak = float(np.max(rms))
    energy_std = float(np.std(rms))

    # Speaking rate
    speaking_rate_wpm = (word_count / duration_s * 60) if duration_s > 0 else 0

    # Pitch contour classification
    if len(voiced) >= 10:
        first_quarter = np.mean(voiced[:len(voiced) // 4])
        last_quarter = np.mean(voiced[-len(voiced) // 4:])
        mid_half = np.mean(voiced[len(voiced) // 4: -len(voiced) // 4])

        if last_quarter > first_quarter * 1.1:
            pitch_contour_type = "rising"
        elif first_quarter > last_quarter * 1.1:
            pitch_contour_type = "falling"
        elif f0_std > f0_mean * 0.15:
            pitch_contour_type = "varied"
        else:
            pitch_contour_type = "flat"
    else:
        pitch_contour_type = "flat"

    # Energy level classification
    if energy_mean > 0.08:
        energy_level = "high"
    elif energy_mean > 0.03:
        energy_level = "medium"
    else:
        energy_level = "low"

    # Emphasis detection: large energy spikes relative to mean
    has_emphasis = bool(energy_peak > energy_mean * 2.5) if energy_mean > 0.01 else False

    # Breath detection: short low-energy dips between voiced regions
    has_breath = False
    if len(rms) > 10:
        low_energy = rms < energy_mean * 0.2
        dip_count = 0
        in_dip = False
        for val in low_energy:
            if val and not in_dip:
                dip_count += 1
                in_dip = True
            elif not val:
                in_dip = False
        has_breath = dip_count >= 2

    # Composite prosody score (0-100)
    # Higher = more expressive / better for voice cloning references
    score = 0.0
    # Pitch range contributes most (wide range = expressive)
    pitch_range_norm = min(f0_range / 100.0, 1.0)  # normalize: 100Hz range = max
    score += pitch_range_norm * 35

    # Pitch variation (std relative to mean)
    pitch_var_norm = min(f0_std / f0_mean, 0.3) / 0.3 if f0_mean > 0 else 0
    score += pitch_var_norm * 25

    # Energy variation (dynamic delivery)
    energy_var_norm = min(energy_std / energy_mean, 0.5) / 0.5 if energy_mean > 0.01 else 0
    score += energy_var_norm * 15

    # Speaking rate (natural conversational range scores highest)
    rate_score = 0
    if 120 <= speaking_rate_wpm <= 180:
        rate_score = 1.0
    elif 100 <= speaking_rate_wpm <= 200:
        rate_score = 0.7
    elif speaking_rate_wpm > 0:
        rate_score = 0.3
    score += rate_score * 10

    # Emphasis and breath add naturalness points
    if has_emphasis:
        score += 8
    if has_breath:
        score += 7

    return ProsodyFeatures(
        f0_mean=round(f0_mean, 2),
        f0_std=round(f0_std, 2),
        f0_min=round(f0_min, 2),
        f0_max=round(f0_max, 2),
        f0_range=round(f0_range, 2),
        energy_mean=round(energy_mean, 6),
        energy_peak=round(energy_peak, 6),
        energy_std=round(energy_std, 6),
        speaking_rate_wpm=round(speaking_rate_wpm, 1),
        pitch_contour_type=pitch_contour_type,
        energy_level=energy_level,
        has_emphasis=has_emphasis,
        has_breath=has_breath,
        prosody_score=round(min(score, 100.0), 1),
    )


def _extract_clip(
    vocal_path: Path, output_path: Path,
    start_ms: int, end_ms: int,
) -> bool:
    """Extract a WAV clip from the vocal stem using FFmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-nostdin",
        "-i", str(vocal_path),
        "-ss", f"{start_ms / 1000:.3f}",
        "-to", f"{end_ms / 1000:.3f}",
        "-ar", "24000", "-ac", "1",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0 and output_path.exists()
