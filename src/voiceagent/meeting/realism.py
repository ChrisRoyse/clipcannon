"""Clone realism effects for human-like video output.

Lightweight numpy operations applied per-frame to avoid the "too perfect"
synthetic look. Real webcams have sensor noise, auto-exposure drift, and
humans have involuntary micro-movements.

All functions operate on uint8 RGB numpy arrays [H, W, 3].
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def add_film_grain(frame: np.ndarray, intensity: float = 0.015) -> np.ndarray:
    """Add temporal Gaussian noise simulating camera sensor grain.

    Args:
        frame: RGB uint8 array [H, W, 3].
        intensity: Noise strength (0.01-0.03 typical). 0.015 = 1.5%.

    Returns:
        New frame with grain added (clipped to [0, 255]).
    """
    noise = np.random.randn(*frame.shape).astype(np.float32) * intensity * 255
    return np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def apply_brightness_jitter(
    frame: np.ndarray, phase: float, amplitude: float = 0.01,
) -> np.ndarray:
    """Apply slow sinusoidal brightness variation simulating auto-exposure.

    Args:
        frame: RGB uint8 array.
        phase: Current phase in radians (incremented each call).
        amplitude: Brightness swing (0.01 = +/-1%).

    Returns:
        Brightness-adjusted frame.
    """
    factor = 1.0 + amplitude * np.sin(phase)
    return np.clip(frame.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def generate_micro_saccade(
    frame_index: int, frequency_hz: float = 2.5,
) -> tuple[int, int]:
    """Generate micro-saccade eye jitter offset.

    Returns (dx, dy) pixel offset to apply to eye region. 1-2px range.
    Deterministic given frame_index for reproducibility in tests.
    """
    # Use sin/cos with different frequencies for natural-looking 2D jitter
    t = frame_index / 30.0  # assuming 30fps
    dx = int(round(np.sin(t * frequency_hz * 2 * np.pi) * 1.5))
    dy = int(round(np.cos(t * frequency_hz * 1.7 * 2 * np.pi) * 1.0))
    return dx, dy


class BlinkGenerator:
    """Generate natural blink timing and overlay frames.

    Blinks occur at random intervals with gaussian distribution centered
    around mean_interval_s. Each blink lasts ~150ms (5 frames at 30fps).
    """

    def __init__(self, mean_interval_s: float = 4.5, std_s: float = 1.0):
        self._mean = mean_interval_s
        self._std = std_s
        self._next_blink_frame: int = self._sample_next()
        self._blink_phase: int = -1  # -1 = not blinking, 0-4 = blink frame
        self._blink_duration_frames: int = 5  # ~167ms at 30fps

    def _sample_next(self) -> int:
        """Sample next blink time in frames (30fps)."""
        interval = max(1.0, np.random.normal(self._mean, self._std))
        return int(interval * 30)

    def get_blink_alpha(self, frame_index: int) -> float:
        """Get eyelid closure alpha for current frame.

        Returns 0.0 (eyes open) to 1.0 (eyes fully closed).
        Call once per frame, advancing frame_index sequentially.
        """
        if frame_index >= self._next_blink_frame and self._blink_phase < 0:
            self._blink_phase = 0

        if self._blink_phase < 0:
            return 0.0

        # Blink curve: close then open (sinusoidal)
        progress = self._blink_phase / self._blink_duration_frames
        alpha = np.sin(progress * np.pi)  # 0 -> 1 -> 0 over duration

        self._blink_phase += 1
        if self._blink_phase > self._blink_duration_frames:
            self._blink_phase = -1
            self._next_blink_frame = frame_index + self._sample_next()

        return float(alpha)

    def apply_blink(
        self,
        frame: np.ndarray,
        alpha: float,
        eye_region: tuple[int, int, int, int],
    ) -> np.ndarray:
        """Apply blink darkening to eye region.

        Args:
            frame: RGB uint8 array.
            alpha: Eyelid closure (0=open, 1=closed).
            eye_region: (x, y, w, h) of both eyes region.

        Returns:
            Frame with blink applied.
        """
        if alpha < 0.05:
            return frame
        x, y, w, h = eye_region
        result = frame.copy()
        region = result[y : y + h, x : x + w].astype(np.float32)
        # Darken proportionally (simulates eyelid covering iris)
        skin_tone = np.mean(region, axis=(0, 1)) * 0.7  # approximate eyelid color
        region = region * (1 - alpha) + skin_tone * alpha
        result[y : y + h, x : x + w] = np.clip(region, 0, 255).astype(np.uint8)
        return result
