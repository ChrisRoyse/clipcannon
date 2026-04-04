"""GPU compositor kernels using CuPy.

Every operation runs entirely on GPU. ZERO CPU copies. If CuPy fails,
CompositorError is raised with full context -- no silent fallbacks.

All inputs and outputs are CuPy ndarrays in float32 [0, 1] range
with shape (H, W, 3) unless otherwise noted.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

import cupy as cp

from phoenix.errors import CompositorError
from phoenix.render._gpu_kernels import (
    ALPHA_BLEND_KERNEL,
    BILINEAR_RESIZE_KERNEL,
    rgb_to_yuv420,
    validate_gpu_array,
    yuv420_to_rgb,
)

logger = logging.getLogger(__name__)

ColorSpace = Literal["rgb", "bgr", "yuv420"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def alpha_blend_gpu(
    foreground: cp.ndarray,
    background: cp.ndarray,
    alpha: cp.ndarray,
) -> cp.ndarray:
    """Blend foreground onto background using an alpha mask on GPU.

    Handles mismatched sizes by resizing foreground and alpha to match
    background dimensions. All computation stays on GPU.

    Args:
        foreground: GPU array, float32, shape (H, W, 3) or (H, W, 4).
        background: GPU array, float32, shape (H, W, 3).
        alpha: GPU array, float32, shape (H, W), (H, W, 1), or (H, W, 3).
            Values in [0, 1].

    Returns:
        Blended GPU array, float32, shape (H, W, 3).

    Raises:
        CompositorError: If inputs have wrong dtype or CuPy kernel fails.
    """
    t0 = time.perf_counter()
    try:
        validate_gpu_array(foreground, "foreground")
        validate_gpu_array(background, "background")
        validate_gpu_array(alpha, "alpha")

        bg_h, bg_w = background.shape[:2]

        # Strip alpha channel from foreground if (H, W, 4)
        if foreground.ndim == 3 and foreground.shape[2] == 4:
            foreground = foreground[:, :, :3]

        # Resize foreground to match background if needed
        fg_h, fg_w = foreground.shape[:2]
        if fg_h != bg_h or fg_w != bg_w:
            foreground = resize_gpu(foreground, bg_h, bg_w)

        # Resize alpha to match background if needed
        a_h, a_w = alpha.shape[:2]
        if a_h != bg_h or a_w != bg_w:
            if alpha.ndim == 2:
                alpha = alpha[:, :, cp.newaxis]
            alpha = resize_gpu(alpha, bg_h, bg_w)

        # Normalize alpha shape for kernel
        if alpha.ndim == 2 or (alpha.ndim == 3 and alpha.shape[2] == 1):
            alpha_flat = alpha.ravel()
            alpha_channels = 1
        else:
            alpha_flat = alpha.ravel()
            alpha_channels = alpha.shape[2]

        channels = 3
        out = cp.empty_like(background)
        total = bg_h * bg_w * channels
        block = 256
        grid = (total + block - 1) // block

        ALPHA_BLEND_KERNEL(
            (grid,),
            (block,),
            (
                foreground.ravel(),
                background.ravel(),
                alpha_flat,
                out.ravel(),
                bg_h,
                bg_w,
                channels,
                alpha_channels,
            ),
        )
        cp.cuda.Device().synchronize()
    except CompositorError:
        raise
    except Exception as exc:
        raise CompositorError(
            f"alpha_blend_gpu failed: {exc}",
            context={
                "fg_shape": getattr(foreground, "shape", None),
                "bg_shape": getattr(background, "shape", None),
                "alpha_shape": getattr(alpha, "shape", None),
            },
        ) from exc

    elapsed = time.perf_counter() - t0
    logger.debug("alpha_blend_gpu: %.3fms", elapsed * 1000)
    return out


def resize_gpu(
    image: cp.ndarray,
    target_h: int,
    target_w: int,
) -> cp.ndarray:
    """Bilinear interpolation resize entirely on GPU.

    No cv2.resize, no CPU transfer. Uses a custom CUDA kernel for
    bilinear sampling.

    Args:
        image: GPU array, float32, shape (H, W, C).
        target_h: Target height in pixels.
        target_w: Target width in pixels.

    Returns:
        Resized GPU array, float32, shape (target_h, target_w, C).

    Raises:
        CompositorError: If input has wrong dtype or kernel fails.
    """
    t0 = time.perf_counter()
    try:
        validate_gpu_array(image, "image")
        if image.ndim == 2:
            image = image[:, :, cp.newaxis]

        src_h, src_w, channels = image.shape
        if src_h == target_h and src_w == target_w:
            return image.copy()

        out = cp.empty((target_h, target_w, channels), dtype=cp.float32)
        total = target_h * target_w * channels
        block = 256
        grid = (total + block - 1) // block

        BILINEAR_RESIZE_KERNEL(
            (grid,),
            (block,),
            (
                image.ravel(),
                out.ravel(),
                src_h,
                src_w,
                target_h,
                target_w,
                channels,
            ),
        )
        cp.cuda.Device().synchronize()
    except CompositorError:
        raise
    except Exception as exc:
        raise CompositorError(
            f"resize_gpu failed: {exc}",
            context={
                "image_shape": getattr(image, "shape", None),
                "target": (target_h, target_w),
            },
        ) from exc

    elapsed = time.perf_counter() - t0
    logger.debug("resize_gpu: %.3fms", elapsed * 1000)
    return out


def color_convert_gpu(
    image: cp.ndarray,
    src: ColorSpace,
    dst: ColorSpace,
) -> cp.ndarray:
    """Convert color space entirely on GPU using CuPy math.

    Supports: rgb <-> bgr, rgb -> yuv420, yuv420 -> rgb.
    No OpenCV, no CPU transfer.

    Args:
        image: GPU array, float32. Shape (H, W, 3) for rgb/bgr,
            or (H * 3 // 2, W) for yuv420 (NV12-like planar).
        src: Source color space string.
        dst: Destination color space string.

    Returns:
        Converted GPU array, float32.

    Raises:
        CompositorError: If conversion is unsupported or input is invalid.
    """
    t0 = time.perf_counter()
    try:
        validate_gpu_array(image, "image")

        if src == dst:
            return image.copy()

        if {src, dst} == {"rgb", "bgr"}:
            result = image[:, :, ::-1].copy()
        elif src == "rgb" and dst == "yuv420":
            result = rgb_to_yuv420(image)
        elif src == "yuv420" and dst == "rgb":
            result = yuv420_to_rgb(image)
        else:
            raise CompositorError(
                f"Unsupported color conversion: {src} -> {dst}",
                context={"src": src, "dst": dst},
            )
    except CompositorError:
        raise
    except Exception as exc:
        raise CompositorError(
            f"color_convert_gpu failed: {exc}",
            context={
                "image_shape": getattr(image, "shape", None),
                "src": src,
                "dst": dst,
            },
        ) from exc

    elapsed = time.perf_counter() - t0
    logger.debug("color_convert_gpu %s->%s: %.3fms", src, dst, elapsed * 1000)
    return result


def paste_face_region_gpu(
    frame: cp.ndarray,
    face: cp.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    alpha: float = 1.0,
) -> cp.ndarray:
    """Paste a face region onto a frame at (x, y) with boundary clipping.

    Handles the case where the face region extends beyond the frame edge
    by clipping to valid bounds. All operations on GPU.

    Args:
        frame: GPU array, float32, shape (H, W, 3).
        face: GPU array, float32, shape (face_h, face_w, 3).
        x: Left coordinate in frame where face top-left is placed.
        y: Top coordinate in frame where face top-left is placed.
        w: Target width to resize face to before pasting.
        h: Target height to resize face to before pasting.
        alpha: Blending alpha in [0, 1]. Default 1.0 (fully opaque).

    Returns:
        New GPU array with face pasted, float32, shape (H, W, 3).

    Raises:
        CompositorError: If inputs are invalid or kernel fails.
    """
    t0 = time.perf_counter()
    try:
        validate_gpu_array(frame, "frame")
        validate_gpu_array(face, "face")

        result = frame.copy()
        frame_h, frame_w = result.shape[:2]

        # Resize face to target (w, h)
        resized_face = resize_gpu(face, h, w)

        # Compute clipping bounds
        src_y0 = max(0, -y)
        src_x0 = max(0, -x)
        dst_y0 = max(0, y)
        dst_x0 = max(0, x)
        dst_y1 = min(frame_h, y + h)
        dst_x1 = min(frame_w, x + w)
        src_y1 = src_y0 + (dst_y1 - dst_y0)
        src_x1 = src_x0 + (dst_x1 - dst_x0)

        if dst_y0 >= dst_y1 or dst_x0 >= dst_x1:
            logger.debug("paste_face_region_gpu: no overlap, returning frame")
            return result

        face_region = resized_face[src_y0:src_y1, src_x0:src_x1, :]
        frame_region = result[dst_y0:dst_y1, dst_x0:dst_x1, :]
        blended = face_region * alpha + frame_region * (1.0 - alpha)
        result[dst_y0:dst_y1, dst_x0:dst_x1, :] = blended

    except CompositorError:
        raise
    except Exception as exc:
        raise CompositorError(
            f"paste_face_region_gpu failed: {exc}",
            context={
                "frame_shape": getattr(frame, "shape", None),
                "face_shape": getattr(face, "shape", None),
                "pos": (x, y, w, h),
            },
        ) from exc

    elapsed = time.perf_counter() - t0
    logger.debug("paste_face_region_gpu: %.3fms", elapsed * 1000)
    return result


def film_grain_gpu(
    frame: cp.ndarray,
    intensity: float = 0.02,
) -> cp.ndarray:
    """Add film grain noise to a frame entirely on GPU.

    Uses CuPy random number generation (GPU-native). Additive noise,
    result clipped to [0, 1].

    Args:
        frame: GPU array, float32, shape (H, W, 3). Values in [0, 1].
        intensity: Noise strength. 0.02 is subtle, 0.1 is heavy.

    Returns:
        Grained GPU array, float32, shape (H, W, 3), clipped to [0, 1].

    Raises:
        CompositorError: If input is invalid.
    """
    t0 = time.perf_counter()
    try:
        validate_gpu_array(frame, "frame")
        noise = cp.random.normal(
            loc=0.0, scale=intensity, size=frame.shape, dtype=cp.float32
        )
        result = cp.clip(frame + noise, 0.0, 1.0)
    except CompositorError:
        raise
    except Exception as exc:
        raise CompositorError(
            f"film_grain_gpu failed: {exc}",
            context={
                "frame_shape": getattr(frame, "shape", None),
                "intensity": intensity,
            },
        ) from exc

    elapsed = time.perf_counter() - t0
    logger.debug("film_grain_gpu: %.3fms", elapsed * 1000)
    return result


def brightness_jitter_gpu(
    frame: cp.ndarray,
    amount: float = 0.01,
) -> cp.ndarray:
    """Apply uniform brightness shift to a frame on GPU.

    Generates a single random offset in [-amount, +amount] and adds it
    to all pixels. Result clipped to [0, 1].

    Args:
        frame: GPU array, float32, shape (H, W, 3). Values in [0, 1].
        amount: Maximum brightness shift magnitude.

    Returns:
        Jittered GPU array, float32, shape (H, W, 3), clipped to [0, 1].

    Raises:
        CompositorError: If input is invalid.
    """
    t0 = time.perf_counter()
    try:
        validate_gpu_array(frame, "frame")
        offset = cp.random.uniform(-amount, amount, size=(), dtype=cp.float32)
        result = cp.clip(frame + offset, 0.0, 1.0)
    except CompositorError:
        raise
    except Exception as exc:
        raise CompositorError(
            f"brightness_jitter_gpu failed: {exc}",
            context={
                "frame_shape": getattr(frame, "shape", None),
                "amount": amount,
            },
        ) from exc

    elapsed = time.perf_counter() - t0
    logger.debug("brightness_jitter_gpu: %.3fms", elapsed * 1000)
    return result
