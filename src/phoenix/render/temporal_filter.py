"""Temporal consistency filter for avatar rendering.

Applies Exponential Moving Average (EMA) smoothing on rendering
parameters (blendshapes, Gaussian params, expression) to prevent
frame-to-frame flickering. Smoothing is applied to PARAMETERS,
not to rendered pixels — this prevents ghosting artifacts.

The filter runs at frame rate (25fps) and maintains separate
smoothing states for different parameter groups with different
time constants:
  - Jaw/mouth: fast (alpha=0.6) — needs to track speech quickly
  - Brows/eyes: medium (alpha=0.4) — follows emotion with slight lag
  - Head pose: slow (alpha=0.2) — very smooth head movement
  - Gaze: fast (alpha=0.7) — eyes should be responsive
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SmoothingConfig:
    """EMA smoothing parameters for different body regions."""
    jaw_alpha: float = 0.6       # Fast — tracks speech
    mouth_alpha: float = 0.5     # Medium-fast — lip shapes
    brow_alpha: float = 0.35     # Medium — emotion tracking
    eye_alpha: float = 0.4       # Medium — blinks, squint
    gaze_alpha: float = 0.7      # Fast — eye direction
    head_pose_alpha: float = 0.2 # Slow — smooth head movement
    default_alpha: float = 0.4   # Fallback for unlisted params


# ARKit blendshape name → region mapping
_REGION_MAP: dict[str, str] = {}
_JAW_NAMES = {"jawOpen", "jawForward", "jawLeft", "jawRight"}
_MOUTH_NAMES = {
    "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthPressLeft", "mouthPressRight", "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthUpperUpLeft", "mouthUpperUpRight",
}
_BROW_NAMES = {
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
}
_EYE_NAMES = {
    "eyeBlinkLeft", "eyeBlinkRight", "eyeLookDownLeft", "eyeLookDownRight",
    "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft", "eyeLookOutRight",
    "eyeLookUpLeft", "eyeLookUpRight", "eyeSquintLeft", "eyeSquintRight",
    "eyeWideLeft", "eyeWideRight",
}
for n in _JAW_NAMES:
    _REGION_MAP[n] = "jaw"
for n in _MOUTH_NAMES:
    _REGION_MAP[n] = "mouth"
for n in _BROW_NAMES:
    _REGION_MAP[n] = "brow"
for n in _EYE_NAMES:
    _REGION_MAP[n] = "eye"


class TemporalFilter:
    """EMA smoother for blendshape and pose parameters.

    Maintains per-parameter smoothing state. Call update() at frame
    rate with new parameter values; returns smoothed values.

    Args:
        config: Smoothing parameters per region.
    """

    def __init__(self, config: SmoothingConfig | None = None) -> None:
        self._config = config or SmoothingConfig()
        self._state: dict[str, float] = {}
        self._initialized = False

    def update(self, params: dict[str, float]) -> dict[str, float]:
        """Smooth a dictionary of named parameters.

        On first call, initializes state to input values (no smoothing).
        Subsequent calls apply EMA per parameter.

        Args:
            params: Parameter name → value mapping.

        Returns:
            Smoothed parameter values.
        """
        if not self._initialized:
            self._state = dict(params)
            self._initialized = True
            return dict(params)

        smoothed = {}
        for name, value in params.items():
            alpha = self._get_alpha(name)
            prev = self._state.get(name, value)
            s = alpha * value + (1 - alpha) * prev
            self._state[name] = s
            smoothed[name] = s

        return smoothed

    def update_array(self, values: np.ndarray, alpha: float = 0.4) -> np.ndarray:
        """Smooth a numpy array of parameters with uniform alpha.

        Useful for FLAME coefficient vectors where per-name mapping
        isn't needed.

        Args:
            values: 1-D array of parameter values.
            alpha: EMA smoothing factor.

        Returns:
            Smoothed array.
        """
        if not hasattr(self, "_array_state") or self._array_state is None:
            self._array_state = values.copy()
            return values.copy()

        if len(values) != len(self._array_state):
            self._array_state = values.copy()
            return values.copy()

        self._array_state = alpha * values + (1 - alpha) * self._array_state
        return self._array_state.copy()

    def reset(self) -> None:
        """Clear all smoothing state."""
        self._state.clear()
        self._initialized = False
        self._array_state = None

    def _get_alpha(self, name: str) -> float:
        """Get the smoothing alpha for a named parameter."""
        region = _REGION_MAP.get(name)
        if region == "jaw":
            return self._config.jaw_alpha
        elif region == "mouth":
            return self._config.mouth_alpha
        elif region == "brow":
            return self._config.brow_alpha
        elif region == "eye":
            return self._config.eye_alpha
        elif name.startswith("gaze") or name.startswith("eye_look"):
            return self._config.gaze_alpha
        elif name.startswith("head"):
            return self._config.head_pose_alpha
        return self._config.default_alpha
