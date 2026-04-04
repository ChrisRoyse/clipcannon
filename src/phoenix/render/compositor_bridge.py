"""Bridge between numpy uint8 frames and CuPy GPU compositor.

Converts numpy uint8 [0,255] frames to CuPy float32 [0,1] on GPU,
runs compositor operations, and converts back. This bridge is used
during Phase 0-1 when frames still originate from cv2.VideoCapture
(CPU) but we want GPU-accelerated compositing.

In Phase 3 (Gaussian renderer), frames originate on GPU and this
bridge is no longer needed — operations use CuPy directly.
"""
from __future__ import annotations

import logging
import time

import cupy as cp
import numpy as np

from phoenix.errors import CompositorError
from phoenix.render.cupy_compositor import (
    alpha_blend_gpu,
    brightness_jitter_gpu,
    film_grain_gpu,
    paste_face_region_gpu,
    resize_gpu,
)

logger = logging.getLogger(__name__)


def _to_gpu(frame: np.ndarray) -> cp.ndarray:
    """Convert numpy uint8 [0,255] frame to CuPy float32 [0,1] on GPU."""
    if frame.dtype != np.uint8:
        raise CompositorError(
            f"Expected uint8 frame, got {frame.dtype}",
            context={"dtype": str(frame.dtype), "shape": frame.shape},
        )
    return cp.asarray(frame, dtype=cp.float32) / 255.0


def _to_cpu(frame: cp.ndarray) -> np.ndarray:
    """Convert CuPy float32 [0,1] frame to numpy uint8 [0,255]."""
    return (cp.clip(frame, 0.0, 1.0) * 255.0).astype(cp.uint8).get()


def gpu_composite_face(
    base_frame: np.ndarray,
    face_frame: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    blend_alpha: float = 1.0,
) -> np.ndarray:
    """Composite a face frame onto a base frame using GPU.

    Replaces cv2.resize + numpy array slicing with GPU operations.

    Args:
        base_frame: Full resolution RGB uint8 frame.
        face_frame: Face region RGB uint8 frame (any size).
        x: X position in base frame.
        y: Y position in base frame.
        w: Target width for face region.
        h: Target height for face region.
        blend_alpha: 0.0-1.0 blend factor (1.0 = full replace).

    Returns:
        Composited full-resolution RGB uint8 frame.

    Raises:
        CompositorError: If GPU operations fail.
    """
    t0 = time.perf_counter()

    base_gpu = _to_gpu(base_frame)
    face_gpu = _to_gpu(face_frame)

    # Resize face to target dimensions on GPU
    face_resized = resize_gpu(face_gpu, h, w)

    # Paste onto base frame
    result_gpu = paste_face_region_gpu(
        base_gpu, face_resized, x, y, w, h, alpha=blend_alpha,
    )

    result = _to_cpu(result_gpu)

    elapsed = (time.perf_counter() - t0) * 1000
    logger.debug("gpu_composite_face: %.1fms", elapsed)
    return result


def gpu_film_grain(
    frame: np.ndarray,
    intensity: float = 0.015,
) -> np.ndarray:
    """Apply film grain on GPU.

    Args:
        frame: RGB uint8 frame.
        intensity: Grain intensity (0.0-1.0).

    Returns:
        Frame with film grain applied, RGB uint8.

    Raises:
        CompositorError: If GPU operations fail.
    """
    gpu_frame = _to_gpu(frame)
    result = film_grain_gpu(gpu_frame, intensity=intensity)
    return _to_cpu(result)


def gpu_brightness_jitter(
    frame: np.ndarray,
    amount: float = 0.01,
) -> np.ndarray:
    """Apply deterministic brightness shift on GPU.

    Unlike the underlying brightness_jitter_gpu (which adds a random
    offset in [-amount, +amount]), this function applies a fixed shift.
    Positive amount brightens, negative darkens.

    Args:
        frame: RGB uint8 frame.
        amount: Brightness shift (-1.0 to 1.0). Positive = brighter.

    Returns:
        Frame with brightness shifted, RGB uint8.

    Raises:
        CompositorError: If GPU operations fail.
    """
    gpu_frame = _to_gpu(frame)
    result = cp.clip(gpu_frame + float(amount), 0.0, 1.0)
    return _to_cpu(result)


def gpu_alpha_blend(
    foreground: np.ndarray,
    background: np.ndarray,
    alpha: np.ndarray | float,
) -> np.ndarray:
    """Alpha blend foreground onto background using GPU.

    Args:
        foreground: RGB uint8 frame.
        background: RGB uint8 frame.
        alpha: Either a float (uniform alpha) or a uint8/float32 mask.

    Returns:
        Blended RGB uint8 frame.

    Raises:
        CompositorError: If GPU operations fail.
    """
    fg_gpu = _to_gpu(foreground)
    bg_gpu = _to_gpu(background)

    if isinstance(alpha, (int, float)):
        alpha_gpu = cp.full(
            (foreground.shape[0], foreground.shape[1]),
            float(alpha),
            dtype=cp.float32,
        )
    elif isinstance(alpha, np.ndarray):
        if alpha.dtype == np.uint8:
            alpha_gpu = cp.asarray(alpha, dtype=cp.float32) / 255.0
        else:
            alpha_gpu = cp.asarray(alpha, dtype=cp.float32)
    else:
        raise CompositorError(
            f"Unsupported alpha type: {type(alpha)}",
            context={"type": str(type(alpha))},
        )

    result = alpha_blend_gpu(fg_gpu, bg_gpu, alpha_gpu)
    return _to_cpu(result)
