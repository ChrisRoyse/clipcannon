"""Laplacian pyramid blending for seamless mouth compositing.

Multi-scale blending that avoids the color bleeding of Poisson blending
and the hard edges of simple alpha blending. Used by MouthMemory to
composite retrieved mouth frames into driver video frames.
"""

from __future__ import annotations

import cv2
import numpy as np


def _build_gaussian_pyramid(img: np.ndarray, levels: int) -> list[np.ndarray]:
    """Build Gaussian pyramid by successive downsampling."""
    pyramid = [img.astype(np.float32)]
    for _ in range(levels):
        img = cv2.pyrDown(pyramid[-1])
        pyramid.append(img)
    return pyramid


def _build_laplacian_pyramid(img: np.ndarray, levels: int) -> list[np.ndarray]:
    """Build Laplacian pyramid (band-pass decomposition)."""
    gauss = _build_gaussian_pyramid(img, levels)
    lap = []
    for i in range(levels):
        expanded = cv2.pyrUp(gauss[i + 1], dstsize=(gauss[i].shape[1], gauss[i].shape[0]))
        lap.append(gauss[i] - expanded)
    lap.append(gauss[-1])
    return lap


def _reconstruct_from_laplacian(pyramid: list[np.ndarray]) -> np.ndarray:
    """Reconstruct image from Laplacian pyramid."""
    img = pyramid[-1]
    for i in range(len(pyramid) - 2, -1, -1):
        expanded = cv2.pyrUp(img, dstsize=(pyramid[i].shape[1], pyramid[i].shape[0]))
        img = expanded + pyramid[i]
    return img


def laplacian_blend(
    foreground: np.ndarray,
    background: np.ndarray,
    mask: np.ndarray,
    levels: int = 4,
) -> np.ndarray:
    """Blend foreground onto background using Laplacian pyramid.

    This produces seamless edges at all spatial frequencies, avoiding
    both the hard edges of alpha blending and the color bleeding of
    Poisson blending.

    Args:
        foreground: BGR image (source mouth frame, warped to target).
        background: BGR image (driver frame).
        mask: Single-channel float mask (0-1), 1.0 where foreground
            should appear. Should have soft edges (Gaussian blurred).
        levels: Number of pyramid levels. 4 is good for mouth-sized regions.

    Returns:
        Blended BGR image, same size as background.
    """
    # Ensure same size
    h, w = background.shape[:2]
    foreground = cv2.resize(foreground, (w, h)) if foreground.shape[:2] != (h, w) else foreground
    mask = cv2.resize(mask, (w, h)) if mask.shape[:2] != (h, w) else mask

    # Ensure 3-channel mask
    if mask.ndim == 2:
        mask_3 = np.stack([mask] * 3, axis=-1)
    else:
        mask_3 = mask

    # Clamp levels to avoid too-small images
    min_dim = min(h, w)
    max_levels = max(1, int(np.log2(min_dim)) - 3)
    levels = min(levels, max_levels)

    # Build pyramids
    fg_lap = _build_laplacian_pyramid(foreground.astype(np.float32), levels)
    bg_lap = _build_laplacian_pyramid(background.astype(np.float32), levels)
    mask_gauss = _build_gaussian_pyramid(mask_3.astype(np.float32), levels)

    # Blend at each level
    blended_lap = []
    for fg_l, bg_l, m_l in zip(fg_lap, bg_lap, mask_gauss):
        # Resize mask to match level size if needed
        if m_l.shape[:2] != fg_l.shape[:2]:
            m_l = cv2.resize(m_l, (fg_l.shape[1], fg_l.shape[0]))
        if m_l.ndim == 2:
            m_l = np.stack([m_l] * 3, axis=-1)
        blended_lap.append(fg_l * m_l + bg_l * (1.0 - m_l))

    result = _reconstruct_from_laplacian(blended_lap)
    return np.clip(result, 0, 255).astype(np.uint8)


def create_soft_lip_mask(
    landmarks_20: np.ndarray,
    frame_shape: tuple[int, int],
    dilate_px: int = 10,
    blur_px: int = 9,
) -> np.ndarray:
    """Create a soft mask around the lip region from 20 lip landmarks.

    Args:
        landmarks_20: 20x2 array of lip landmark points (InsightFace 52-71).
        frame_shape: (height, width) of the target frame.
        dilate_px: Pixels to dilate outward.
        blur_px: Gaussian blur kernel size for soft edges.

    Returns:
        Float mask (0-1), same size as frame_shape[:2].
    """
    h, w = frame_shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    # Outer lip contour (first 14 points: indices 0-13)
    outer = landmarks_20[:14].astype(np.int32)
    cv2.fillPoly(mask, [outer], 255)

    if dilate_px > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (dilate_px * 2, dilate_px * 2),
        )
        mask = cv2.dilate(mask, kernel)

    if blur_px > 0:
        blur_size = blur_px * 2 + 1
        mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)

    return mask.astype(np.float32) / 255.0
