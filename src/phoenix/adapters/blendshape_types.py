"""Blendshape types, constants, and ARKit-to-FLAME conversion.

Defines the 52 ARKit blendshape names, the BlendshapeFrame dataclass,
the abstract Audio2FaceAdapter base, and BlendshapeToFLAME mapping.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

import numpy as np

from phoenix.errors import ExpressionError

# ---------------------------------------------------------------------------
# 52 ARKit blendshape names in canonical order
# ---------------------------------------------------------------------------

ARKIT_BLENDSHAPE_NAMES: list[str] = [
    "eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft",
    "eyeLookOutLeft", "eyeLookUpLeft", "eyeSquintLeft",
    "eyeWideLeft", "eyeBlinkRight", "eyeLookDownRight",
    "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight",
    "eyeSquintRight", "eyeWideRight", "jawForward",
    "jawLeft", "jawRight", "jawOpen",
    "mouthClose", "mouthFunnel", "mouthPucker",
    "mouthLeft", "mouthRight", "mouthSmileLeft",
    "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft",
    "mouthStretchRight", "mouthRollLower", "mouthRollUpper",
    "mouthShrugLower", "mouthShrugUpper", "mouthPressLeft",
    "mouthPressRight", "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthUpperUpLeft", "mouthUpperUpRight", "browDownLeft",
    "browDownRight", "browInnerUp", "browOuterUpLeft",
    "browOuterUpRight", "cheekPuff", "cheekSquintLeft",
    "cheekSquintRight", "noseSneerLeft", "noseSneerRight",
    "tongueOut",
]

BLENDSHAPE_INDEX: dict[str, int] = {
    name: i for i, name in enumerate(ARKIT_BLENDSHAPE_NAMES)
}

NUM_ARKIT_BLENDSHAPES = 52
NUM_FLAME_EXPRESSIONS = 53


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a scalar to [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# BlendshapeFrame dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BlendshapeFrame:
    """52 ARKit blendshape coefficients for a single frame.

    Attributes:
        coefficients: Array of shape (52,) with values in [0, 1].
        timestamp: Timestamp in seconds (monotonic or audio-relative).
        duration_ms: Time taken to compute this frame, in milliseconds.
    """

    coefficients: np.ndarray
    timestamp: float = 0.0
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.coefficients.shape != (NUM_ARKIT_BLENDSHAPES,):
            raise ExpressionError(
                f"BlendshapeFrame requires ({NUM_ARKIT_BLENDSHAPES},) "
                f"array, got {self.coefficients.shape}",
                {"shape": self.coefficients.shape},
            )
        if np.any(np.isnan(self.coefficients)):
            raise ExpressionError(
                "BlendshapeFrame coefficients contain NaN values", {},
            )

    def get(self, name: str) -> float:
        """Get a blendshape coefficient by ARKit name.

        Args:
            name: ARKit blendshape name (e.g., 'jawOpen').

        Returns:
            Coefficient value in [0, 1].

        Raises:
            ExpressionError: If name is not a valid ARKit blendshape.
        """
        idx = BLENDSHAPE_INDEX.get(name)
        if idx is None:
            raise ExpressionError(
                f"Unknown blendshape: {name}",
                {"valid": list(BLENDSHAPE_INDEX.keys())[:5]},
            )
        return float(self.coefficients[idx])


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class Audio2FaceAdapter(abc.ABC):
    """Abstract base for audio-to-blendshape adapters."""

    @abc.abstractmethod
    def process_audio_chunk(
        self, audio: np.ndarray, sr: int,
    ) -> BlendshapeFrame:
        """Convert an audio chunk to a BlendshapeFrame.

        Args:
            audio: 1-D float32 audio array (mono).
            sr: Sample rate in Hz.

        Returns:
            BlendshapeFrame with 52 ARKit blendshape coefficients.
        """

    @abc.abstractmethod
    def reset(self) -> None:
        """Reset internal state (EMA buffers, connection state, etc.)."""


# ---------------------------------------------------------------------------
# BlendshapeToFLAME: ARKit -> FLAME mapping
# ---------------------------------------------------------------------------

class BlendshapeToFLAME:
    """Maps 52 ARKit blendshapes to FLAME's 53 expression coefficients.

    Uses a linear mapping matrix calibrated from known correspondences
    between ARKit and FLAME expression spaces.

    FLAME expression dimensions:
        0-9: Jaw and mouth, 10-19: Lips, 20-29: Cheeks and nose,
        30-39: Brows, 40-49: Eyes, 50-52: Tongue and misc.
    """

    def __init__(self) -> None:
        self._matrix = self._build_mapping_matrix()

    def convert(self, frame: BlendshapeFrame) -> np.ndarray:
        """Convert ARKit blendshapes to FLAME expression coefficients.

        Args:
            frame: BlendshapeFrame with 52 ARKit coefficients.

        Returns:
            Array of shape (53,) with values clipped to [-2, 2].
        """
        flame = self._matrix @ frame.coefficients
        return np.clip(flame, -2.0, 2.0).astype(np.float32)

    @staticmethod
    def _build_mapping_matrix() -> np.ndarray:
        """Build the 53x52 ARKit-to-FLAME linear mapping matrix."""
        m = np.zeros(
            (NUM_FLAME_EXPRESSIONS, NUM_ARKIT_BLENDSHAPES),
            dtype=np.float32,
        )
        idx = BLENDSHAPE_INDEX

        def _s(fi: int, name: str, w: float) -> None:
            m[fi, idx[name]] = w

        # Jaw and mouth (FLAME 0-9)
        _s(0, "jawOpen", 1.8);       _s(1, "jawForward", 1.2)
        _s(2, "jawLeft", 1.0);       _s(3, "jawRight", 1.0)
        _s(4, "mouthClose", -1.0);   _s(5, "mouthFunnel", 1.5)
        _s(6, "mouthPucker", 1.5);   _s(7, "mouthLeft", 1.0)
        _s(8, "mouthRight", 1.0);    _s(9, "mouthRollLower", 1.2)
        # Lips (FLAME 10-19)
        _s(10, "mouthRollUpper", 1.2); _s(11, "mouthShrugLower", 1.0)
        _s(12, "mouthShrugUpper", 1.0); _s(13, "mouthSmileLeft", 1.5)
        _s(14, "mouthSmileRight", 1.5); _s(15, "mouthFrownLeft", 1.5)
        _s(16, "mouthFrownRight", 1.5); _s(17, "mouthStretchLeft", 1.0)
        _s(18, "mouthStretchRight", 1.0); _s(19, "mouthPressLeft", 0.8)
        # Cheeks and nose (FLAME 20-29)
        _s(20, "mouthPressRight", 0.8)
        _s(21, "mouthLowerDownLeft", 1.2)
        _s(22, "mouthLowerDownRight", 1.2)
        _s(23, "mouthUpperUpLeft", 1.2)
        _s(24, "mouthUpperUpRight", 1.2)
        _s(25, "cheekPuff", 1.5)
        _s(26, "cheekSquintLeft", 1.0); _s(27, "cheekSquintRight", 1.0)
        _s(28, "noseSneerLeft", 1.0);   _s(29, "noseSneerRight", 1.0)
        # Brows (FLAME 30-39)
        _s(30, "browDownLeft", 1.5);  _s(31, "browDownRight", 1.5)
        _s(32, "browInnerUp", 1.5);   _s(33, "browOuterUpLeft", 1.2)
        _s(34, "browOuterUpRight", 1.2)
        _s(35, "mouthDimpleLeft", 0.8); _s(36, "mouthDimpleRight", 0.8)
        # Composite brow expressions
        m[37, idx["browInnerUp"]] = 0.5
        m[37, idx["browOuterUpLeft"]] = 0.5
        m[38, idx["browInnerUp"]] = 0.5
        m[38, idx["browOuterUpRight"]] = 0.5
        m[39, idx["browInnerUp"]] = 0.4
        m[39, idx["browOuterUpLeft"]] = 0.3
        m[39, idx["browOuterUpRight"]] = 0.3
        # Eyes (FLAME 40-49)
        _s(40, "eyeBlinkLeft", 1.5);  _s(41, "eyeBlinkRight", 1.5)
        _s(42, "eyeWideLeft", 1.2);   _s(43, "eyeWideRight", 1.2)
        _s(44, "eyeSquintLeft", 1.0); _s(45, "eyeSquintRight", 1.0)
        _s(46, "eyeLookUpLeft", 0.8); _s(47, "eyeLookUpRight", 0.8)
        _s(48, "eyeLookDownLeft", 0.8); _s(49, "eyeLookDownRight", 0.8)
        # Tongue and misc (FLAME 50-52)
        _s(50, "tongueOut", 1.5)
        m[51, idx["eyeLookInLeft"]] = 0.5
        m[51, idx["eyeLookInRight"]] = 0.5
        m[52, idx["eyeLookOutLeft"]] = 0.5
        m[52, idx["eyeLookOutRight"]] = 0.5

        return m
