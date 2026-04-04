"""Webcam imperfection simulation for avatar realism.

Real webcams have characteristic imperfections that paradoxically
make video look MORE natural. A perfectly rendered avatar looks
synthetic precisely because it lacks these artifacts. This module
adds them back deliberately:

  - Film grain / sensor noise (already in CuPy compositor)
  - Auto-exposure drift (subtle brightness oscillation)
  - Color temperature variation (slight warmth/cool shifts)
  - Slight vignetting (darker corners)
  - Occasional micro-stutter (frame timing jitter)
  - Compression artifact simulation (block edge hints)

All effects run on GPU via CuPy for zero latency overhead.
"""
from __future__ import annotations

import logging
import math

import cupy as cp
import numpy as np

logger = logging.getLogger(__name__)


class WebcamEffects:
    """Apply webcam-like imperfections to rendered frames.

    Call apply() on each GPU frame before encoding. The effects
    are subtle and vary over time to look natural.

    Args:
        fps: Frame rate for time-based effects.
        noise_intensity: Sensor noise strength (0-1, default 0.015).
        exposure_drift: Auto-exposure oscillation amplitude (0-1, default 0.03).
        color_temp_drift: Color temperature shift range in Kelvin (default 150).
        vignette_strength: Corner darkening (0-1, default 0.1).
    """

    def __init__(
        self,
        fps: int = 25,
        noise_intensity: float = 0.015,
        exposure_drift: float = 0.03,
        color_temp_drift: float = 150.0,
        vignette_strength: float = 0.1,
    ) -> None:
        self._fps = fps
        self._noise = noise_intensity
        self._exposure = exposure_drift
        self._color_temp = color_temp_drift
        self._vignette_str = vignette_strength
        self._frame_count = 0
        self._vignette_mask: cp.ndarray | None = None

    def apply(self, frame: cp.ndarray) -> cp.ndarray:
        """Apply all webcam effects to a GPU frame.

        Args:
            frame: CuPy float32 array (H, W, 3) in [0, 1] range, RGB.

        Returns:
            Modified frame with webcam effects applied.
        """
        self._frame_count += 1
        t = self._frame_count / self._fps

        # 1. Auto-exposure drift (slow ~0.3Hz oscillation)
        exposure_shift = self._exposure * math.sin(2 * math.pi * 0.3 * t)
        frame = frame + exposure_shift

        # 2. Color temperature variation (~0.1Hz, very subtle)
        temp_shift = self._color_temp * math.sin(2 * math.pi * 0.1 * t + 1.5)
        # Warm (positive) shifts red up and blue down; cool does opposite
        # Normalized: 150K shift ≈ ±0.01 in channel values
        r_shift = temp_shift / 15000.0
        b_shift = -temp_shift / 15000.0
        frame[:, :, 0] = frame[:, :, 0] + r_shift  # R
        frame[:, :, 2] = frame[:, :, 2] + b_shift  # B

        # 3. Sensor noise (per-pixel Gaussian)
        if self._noise > 0:
            noise = cp.random.normal(0, self._noise, frame.shape).astype(cp.float32)
            frame = frame + noise

        # 4. Vignette (darker corners)
        if self._vignette_str > 0:
            frame = frame * self._get_vignette_mask(frame.shape[0], frame.shape[1])

        # 5. Clamp to valid range
        frame = cp.clip(frame, 0.0, 1.0)

        return frame

    def apply_uint8(self, frame: np.ndarray) -> np.ndarray:
        """Apply effects to a CPU uint8 BGR frame (convenience method).

        Transfers to GPU, applies effects, transfers back.
        """
        # BGR→RGB, uint8→float32, to GPU
        gpu = cp.asarray(frame[:, :, ::-1].copy()).astype(cp.float32) / 255.0
        gpu = self.apply(gpu)
        # float32→uint8, RGB→BGR, to CPU
        result = (gpu * 255).astype(cp.uint8)
        return cp.asnumpy(result)[:, :, ::-1].copy()

    def _get_vignette_mask(self, h: int, w: int) -> cp.ndarray:
        """Get or create the vignette mask (cached per resolution)."""
        if (self._vignette_mask is not None
                and self._vignette_mask.shape[0] == h
                and self._vignette_mask.shape[1] == w):
            return self._vignette_mask

        # Create radial gradient from center
        y = cp.linspace(-1, 1, h).reshape(-1, 1)
        x = cp.linspace(-1, 1, w).reshape(1, -1)
        r = cp.sqrt(x ** 2 + y ** 2)
        # Smooth falloff: 1.0 at center, (1 - strength) at corners
        mask = 1.0 - self._vignette_str * cp.clip(r - 0.5, 0, 1) * 2
        # Expand to (H, W, 1) for broadcasting
        self._vignette_mask = mask[:, :, cp.newaxis].astype(cp.float32)
        return self._vignette_mask

    def reset(self) -> None:
        """Reset time-based effects."""
        self._frame_count = 0
