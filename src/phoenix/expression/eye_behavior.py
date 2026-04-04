"""Natural eye behavior model for avatar realism.

Generates realistic eye movements based on conversational state:
  - Microsaccades: tiny involuntary eye movements (2-3 per second)
  - Blinks: natural blink rate (15-20 per minute), faster when tired/stressed
  - Gaze direction: look at speaker, look away while thinking, return on response
  - Pupil dilation: slight changes with emotion/arousal (if rendering supports it)

All rule-based — no ML model needed. Runs on CPU at frame rate.

References:
  - Microsaccade rate: 1-3 Hz, amplitude 0.1-1.0 degrees
  - Blink duration: 100-400ms (avg 200ms)
  - Blink rate: 15-20/min relaxed, up to 26/min stressed
  - Saccade duration: 20-200ms depending on amplitude
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EyeState:
    """Current eye parameters for avatar rendering."""
    # Gaze direction (relative to center, in degrees)
    gaze_x: float = 0.0      # Left(-) / Right(+)
    gaze_y: float = 0.0      # Down(-) / Up(+)

    # Blink state (0 = fully open, 1 = fully closed)
    blink_left: float = 0.0
    blink_right: float = 0.0

    # Eyelid openness (0 = relaxed, 1 = wide)
    eye_wide_left: float = 0.0
    eye_wide_right: float = 0.0

    # Squint (0 = none, 1 = full squint)
    squint_left: float = 0.0
    squint_right: float = 0.0

    def to_arkit_dict(self) -> dict[str, float]:
        """Convert to ARKit blendshape names."""
        return {
            "eyeLookInLeft": max(0, self.gaze_x) * 0.3,
            "eyeLookOutLeft": max(0, -self.gaze_x) * 0.3,
            "eyeLookInRight": max(0, -self.gaze_x) * 0.3,
            "eyeLookOutRight": max(0, self.gaze_x) * 0.3,
            "eyeLookUpLeft": max(0, self.gaze_y) * 0.2,
            "eyeLookUpRight": max(0, self.gaze_y) * 0.2,
            "eyeLookDownLeft": max(0, -self.gaze_y) * 0.2,
            "eyeLookDownRight": max(0, -self.gaze_y) * 0.2,
            "eyeBlinkLeft": self.blink_left,
            "eyeBlinkRight": self.blink_right,
            "eyeWideLeft": self.eye_wide_left,
            "eyeWideRight": self.eye_wide_right,
            "eyeSquintLeft": self.squint_left,
            "eyeSquintRight": self.squint_right,
        }


class EyeBehavior:
    """Generate natural eye movements at frame rate.

    Call update() every frame (25fps = every 40ms). The model
    maintains internal state for blink timing, microsaccade
    patterns, and gaze direction.

    Args:
        fps: Frame rate (default 25).
        blink_rate_per_min: Average blinks per minute (default 17).
    """

    def __init__(self, fps: int = 25, blink_rate_per_min: float = 17.0) -> None:
        self._fps = fps
        self._dt = 1.0 / fps
        self._blink_rate = blink_rate_per_min / 60.0  # blinks per second
        self._state = EyeState()
        self._arousal = 0.5  # Must be set before _random_blink_interval()

        # Blink state machine
        self._blink_timer = 0.0
        self._next_blink = self._random_blink_interval()
        self._blink_phase = 0.0  # 0=open, progresses through close→open
        self._blink_duration = 0.2  # seconds
        self._in_blink = False

        # Microsaccade state
        self._saccade_timer = 0.0
        self._next_saccade = random.uniform(0.3, 0.8)
        self._saccade_target_x = 0.0
        self._saccade_target_y = 0.0

        # Gaze target (set externally based on speaker position)
        self._gaze_target_x = 0.0
        self._gaze_target_y = 0.0
        self._gaze_smooth = 0.1  # EMA alpha for gaze tracking

        # Arousal already set above (before _random_blink_interval)

    def set_gaze_target(self, x: float, y: float) -> None:
        """Set where the avatar should look (degrees from center)."""
        self._gaze_target_x = x
        self._gaze_target_y = y

    def set_arousal(self, arousal: float) -> None:
        """Set emotional arousal level (0-1). Affects blink rate and eye wideness."""
        self._arousal = max(0.0, min(1.0, arousal))

    def update(self) -> EyeState:
        """Advance one frame and return the eye state.

        Call at frame rate (25fps). Handles blinks, microsaccades,
        and gaze smoothing internally.
        """
        dt = self._dt

        # --- Blink logic ---
        self._blink_timer += dt
        if not self._in_blink and self._blink_timer >= self._next_blink:
            self._in_blink = True
            self._blink_phase = 0.0
            self._blink_duration = random.uniform(0.15, 0.3)

        if self._in_blink:
            self._blink_phase += dt / self._blink_duration
            if self._blink_phase >= 1.0:
                self._in_blink = False
                self._blink_timer = 0.0
                self._next_blink = self._random_blink_interval()
                self._state.blink_left = 0.0
                self._state.blink_right = 0.0
            else:
                # Smooth blink curve: fast close, slower open
                if self._blink_phase < 0.3:
                    # Closing phase (0 → 1)
                    blink_val = self._blink_phase / 0.3
                else:
                    # Opening phase (1 → 0)
                    blink_val = 1.0 - (self._blink_phase - 0.3) / 0.7
                # Slight asymmetry (one eye leads by ~10ms)
                self._state.blink_left = max(0, min(1, blink_val))
                self._state.blink_right = max(0, min(1, blink_val * 0.95))

        # --- Microsaccade logic ---
        self._saccade_timer += dt
        if self._saccade_timer >= self._next_saccade:
            self._saccade_timer = 0.0
            self._next_saccade = random.uniform(0.3, 0.7)
            # Tiny random displacement (0.1-0.5 degrees)
            amp = random.uniform(0.1, 0.5)
            angle = random.uniform(0, 2 * math.pi)
            self._saccade_target_x = math.cos(angle) * amp
            self._saccade_target_y = math.sin(angle) * amp

        # --- Gaze smoothing ---
        # Combine deliberate gaze target + microsaccade offset
        target_x = self._gaze_target_x + self._saccade_target_x
        target_y = self._gaze_target_y + self._saccade_target_y
        self._state.gaze_x += (target_x - self._state.gaze_x) * self._gaze_smooth
        self._state.gaze_y += (target_y - self._state.gaze_y) * self._gaze_smooth

        # Decay microsaccade offset back to zero
        self._saccade_target_x *= 0.9
        self._saccade_target_y *= 0.9

        # --- Arousal effects ---
        # High arousal → slightly wider eyes
        self._state.eye_wide_left = self._arousal * 0.3
        self._state.eye_wide_right = self._arousal * 0.3

        return self._state

    def force_blink(self) -> None:
        """Trigger an immediate blink (e.g., on surprise)."""
        self._in_blink = True
        self._blink_phase = 0.0
        self._blink_duration = 0.15  # Fast surprise blink

    def _random_blink_interval(self) -> float:
        """Random time until next blink (exponential distribution)."""
        # Arousal increases blink rate (stressed people blink more)
        rate = self._blink_rate * (1.0 + self._arousal * 0.5)
        mean_interval = 1.0 / max(rate, 0.1)
        return random.expovariate(1.0 / mean_interval)

    def reset(self) -> None:
        """Reset all eye state."""
        self._state = EyeState()
        self._blink_timer = 0.0
        self._in_blink = False
        self._saccade_timer = 0.0
