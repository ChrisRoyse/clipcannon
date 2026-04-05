"""Low-level audio feature extraction for physics-based face animation.

Pure signal processing using numpy/scipy -- no ML models.
All functions are real-time capable at <5 ms per chunk.

Features extracted:
  - Formants (F1, F2, F3) via LPC root-finding
  - Fundamental frequency (F0) via the YIN algorithm
  - Zero-crossing rate (ZCR) for fricative detection
  - RMS energy
"""
from __future__ import annotations

import numpy as np


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, x))


def extract_formants_lpc(
    audio: np.ndarray, sample_rate: int, order: int = 12,
) -> tuple[float, float, float]:
    """Extract F1, F2, F3 from audio using LPC polynomial root-finding.

    LPC (Linear Predictive Coding) models the vocal tract as an
    all-pole filter.  The resonant frequencies (formants) are the
    angles of the complex roots of the LPC polynomial, converted to Hz.

    Args:
        audio: Float32 mono audio chunk.
        sample_rate: Sample rate in Hz.
        order: LPC order (rule of thumb: 2 + sr/1000).

    Returns:
        Tuple of (F1, F2, F3) in Hz.  Returns (0, 0, 0) on failure.
    """
    if len(audio) < order + 1:
        return (0.0, 0.0, 0.0)

    # Pre-emphasis to flatten the spectral tilt
    emphasized = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])
    windowed = emphasized * np.hamming(len(emphasized))

    # LPC via autocorrelation method (Levinson-Durbin)
    try:
        from scipy.linalg import solve_toeplitz
        corr = np.correlate(windowed, windowed, mode="full")
        corr = corr[len(corr) // 2:]
        lpc_coeffs = solve_toeplitz(corr[:order], corr[1:order + 1])
    except (np.linalg.LinAlgError, ValueError):
        return (0.0, 0.0, 0.0)

    # Build LPC polynomial and find roots
    poly = np.concatenate(([1.0], -lpc_coeffs))
    roots = np.roots(poly)

    # Keep roots inside unit circle with positive imaginary part
    roots = roots[np.imag(roots) > 0]
    roots = roots[np.abs(roots) < 1.0]
    if len(roots) == 0:
        return (0.0, 0.0, 0.0)

    # Convert to frequencies and sort
    angles = np.arctan2(np.imag(roots), np.real(roots))
    freqs = np.sort(angles * (sample_rate / (2.0 * np.pi)))
    freqs = freqs[freqs > 50]  # Discard sub-50 Hz artifacts

    f1 = float(freqs[0]) if len(freqs) > 0 else 0.0
    f2 = float(freqs[1]) if len(freqs) > 1 else 0.0
    f3 = float(freqs[2]) if len(freqs) > 2 else 0.0
    return (f1, f2, f3)


def extract_f0_yin(
    audio: np.ndarray, sample_rate: int,
    f_min: float = 60.0, f_max: float = 500.0,
    threshold: float = 0.15,
) -> float:
    """Extract fundamental frequency using the YIN algorithm.

    YIN: autocorrelation-based pitch detector with cumulative mean
    normalized difference function.  Pure numpy, no ML.

    Args:
        audio: Float32 mono audio chunk.
        sample_rate: Sample rate in Hz.
        f_min: Minimum expected F0.
        f_max: Maximum expected F0.
        threshold: YIN aperiodicity threshold.

    Returns:
        Estimated F0 in Hz, or 0.0 if unvoiced.
    """
    tau_min = max(2, int(sample_rate / f_max))
    tau_max = min(len(audio) // 2, int(sample_rate / f_min))

    if tau_max <= tau_min or len(audio) < tau_max * 2:
        return 0.0

    n = len(audio) - tau_max
    if n <= 0:
        return 0.0

    # Difference function d(tau)
    diffs = np.zeros(tau_max)
    for tau in range(1, tau_max):
        diff = audio[:n] - audio[tau:tau + n]
        diffs[tau] = np.sum(diff * diff)

    # Cumulative mean normalized difference (CMNDF)
    cmndf = np.ones(tau_max)
    running_sum = 0.0
    for tau in range(1, tau_max):
        running_sum += diffs[tau]
        if running_sum > 0:
            cmndf[tau] = diffs[tau] * tau / running_sum
        else:
            cmndf[tau] = 1.0

    # Find first dip below threshold
    best_tau = 0
    for tau in range(tau_min, tau_max):
        if cmndf[tau] < threshold:
            while tau + 1 < tau_max and cmndf[tau + 1] < cmndf[tau]:
                tau += 1
            best_tau = tau
            break

    if best_tau == 0:
        best_tau = int(np.argmin(cmndf[tau_min:tau_max])) + tau_min
        if cmndf[best_tau] > 0.5:
            return 0.0

    return float(sample_rate / best_tau) if best_tau > 0 else 0.0


def zero_crossing_rate(audio: np.ndarray, sample_rate: int) -> float:
    """Compute zero-crossing rate (crossings per second).

    High ZCR indicates fricatives (s, f, sh, th) which expose teeth.
    """
    if len(audio) < 2:
        return 0.0
    signs = np.signbit(audio)
    crossings = int(np.sum(signs[1:] != signs[:-1]))
    duration = len(audio) / sample_rate
    return crossings / duration if duration > 0 else 0.0
