"""Phoenix error hierarchy.

All Phoenix subsystems raise typed exceptions from this module.
Each error captures full context for debugging GPU pipeline failures.
"""

from __future__ import annotations


class PhoenixError(Exception):
    """Base exception for all Phoenix subsystems.

    Args:
        message: Human-readable error description.
        context: Optional dict of debug context (shapes, dtypes, devices).
    """

    def __init__(self, message: str, context: dict | None = None) -> None:
        self.context = context or {}
        super().__init__(self._format(message))

    def _format(self, message: str) -> str:
        if not self.context:
            return message
        ctx = ", ".join(f"{k}={v}" for k, v in self.context.items())
        return f"{message} [{ctx}]"


class CompositorError(PhoenixError):
    """Raised when a GPU compositor kernel fails.

    Covers alpha blending, resizing, color conversion, face pasting,
    film grain, and brightness jitter operations.
    """


class RenderError(PhoenixError):
    """Raised when the 3D Gaussian Splat renderer fails.

    Covers rasterization, deformation, and NVENC encoding errors.
    """


class ExpressionError(PhoenixError):
    """Raised when the expression engine fails.

    Covers Audio2Expression inference, FLAME blendshape computation,
    and gaze/blink parameter generation.
    """


class BehaviorError(PhoenixError):
    """Raised when the embedding-driven behavior system fails.

    Covers emotion fusion, gesture selection, prosody matching,
    speaker tracking, and cross-modal detection.
    """
