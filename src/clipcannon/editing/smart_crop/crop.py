"""Platform aspect ratios and face-aware crop region computation and smoothing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ============================================================
# PLATFORM ASPECT RATIOS
# ============================================================
PLATFORM_ASPECTS: dict[str, str] = {
    "tiktok": "9:16",
    "instagram_reels": "9:16",
    "youtube_shorts": "9:16",
    "youtube_standard": "16:9",
    "youtube_4k": "16:9",
    "facebook": "9:16",
    "linkedin": "1:1",
}


@dataclass
class CropRegion:
    """Calculated crop window for a scene."""

    x: int
    y: int
    width: int
    height: int


# ============================================================
# CROP CALCULATION
# ============================================================
def parse_aspect_ratio(aspect_str: str) -> float:
    """Convert an aspect ratio string like '9:16' to a float.

    Args:
        aspect_str: Aspect ratio in 'W:H' format.

    Returns:
        Aspect ratio as a float (width / height).

    Raises:
        ValueError: If the format is invalid.
    """
    parts = aspect_str.split(":")
    if len(parts) != 2:
        msg = f"Invalid aspect ratio format: {aspect_str!r}"
        raise ValueError(msg)
    w, h = int(parts[0]), int(parts[1])
    if w <= 0 or h <= 0:
        msg = f"Aspect ratio components must be positive: {aspect_str!r}"
        raise ValueError(msg)
    return w / h


def compute_crop_region(
    source_w: int,
    source_h: int,
    target_aspect: str,
    face_position_x: float = 0.5,
    face_position_y: float = 0.5,
    safe_area_pct: float = 0.85,
) -> CropRegion:
    """Calculate the crop window for a given target aspect ratio.

    Centers the crop on the face position (normalized 0-1) while
    ensuring the face stays within the safe area and the crop
    stays within frame bounds.

    Args:
        source_w: Source frame width in pixels.
        source_h: Source frame height in pixels.
        target_aspect: Target aspect ratio string (e.g., '9:16').
        face_position_x: Normalized face X position (0.0-1.0).
        face_position_y: Normalized face Y position (0.0-1.0).
        safe_area_pct: Fraction of crop that must contain the face.

    Returns:
        CropRegion with calculated position and dimensions.
    """
    target_ratio = parse_aspect_ratio(target_aspect)
    source_ratio = source_w / source_h

    # Calculate crop dimensions
    if target_ratio < source_ratio:
        # Target is taller/narrower (e.g., 9:16 from 16:9)
        crop_h = source_h
        crop_w = round(source_h * target_ratio)
    else:
        # Target is wider or same
        crop_w = source_w
        crop_h = round(source_w / target_ratio)

    # Clamp crop dimensions to source
    crop_w = min(crop_w, source_w)
    crop_h = min(crop_h, source_h)

    # Center on face position
    face_cx = face_position_x * source_w
    face_cy = face_position_y * source_h

    crop_x = int(face_cx - crop_w / 2)
    crop_y = int(face_cy - crop_h / 2)

    # Clamp to frame bounds
    crop_x = max(0, min(crop_x, source_w - crop_w))
    crop_y = max(0, min(crop_y, source_h - crop_h))

    # Enforce safe area
    if safe_area_pct > 0 and safe_area_pct < 1.0:
        safe_margin_x = crop_w * (1 - safe_area_pct) / 2
        safe_margin_y = crop_h * (1 - safe_area_pct) / 2

        face_in_crop_x = face_cx - crop_x
        face_in_crop_y = face_cy - crop_y

        # Adjust X if face is outside safe area
        if face_in_crop_x < safe_margin_x:
            crop_x = max(0, int(face_cx - safe_margin_x))
        elif face_in_crop_x > crop_w - safe_margin_x:
            crop_x = min(
                source_w - crop_w,
                int(face_cx - crop_w + safe_margin_x),
            )

        # Adjust Y if face is outside safe area
        if face_in_crop_y < safe_margin_y:
            crop_y = max(0, int(face_cy - safe_margin_y))
        elif face_in_crop_y > crop_h - safe_margin_y:
            crop_y = min(
                source_h - crop_h,
                int(face_cy - crop_h + safe_margin_y),
            )

    return CropRegion(x=crop_x, y=crop_y, width=crop_w, height=crop_h)


# ============================================================
# SCENE-BASED CROP STRATEGY
# ============================================================
def get_crop_for_scene(
    scene_data: dict[str, Any],
    source_w: int,
    source_h: int,
    target_aspect: str,
) -> CropRegion:
    """Determine crop strategy based on scene shot type.

    Uses the scene's shot_type and crop_recommendation from Phase 1
    to decide whether to use face detection or center crop.

    Args:
        scene_data: Scene dict with keys: shot_type, crop_recommendation,
            face_detected, face_position_x, face_position_y.
        source_w: Source frame width in pixels.
        source_h: Source frame height in pixels.
        target_aspect: Target aspect ratio string.

    Returns:
        CropRegion for this scene.
    """
    shot_type = str(scene_data.get("shot_type", "medium"))
    crop_rec = str(scene_data.get("crop_recommendation", "needs_reframe"))
    face_detected = bool(scene_data.get("face_detected", False))
    face_x = float(scene_data.get("face_position_x", 0.5))
    face_y = float(scene_data.get("face_position_y", 0.5))

    # Extreme closeup with safe framing: always center, ignore face
    if shot_type == "extreme_closeup" and crop_rec == "safe_for_vertical":
        return compute_crop_region(
            source_w, source_h, target_aspect,
            face_position_x=0.5, face_position_y=0.5,
        )

    # Wide shots with landscape framing get a wider safe area to
    # preserve more context around the subject
    if shot_type == "wide" and crop_rec == "keep_landscape" and face_detected:
        return compute_crop_region(
            source_w, source_h, target_aspect,
            face_position_x=face_x, face_position_y=face_y,
            safe_area_pct=0.9,
        )

    # All other cases: use face position if available, otherwise center
    pos_x = face_x if face_detected else 0.5
    pos_y = face_y if face_detected else 0.5
    return compute_crop_region(
        source_w, source_h, target_aspect,
        face_position_x=pos_x, face_position_y=pos_y,
    )


# ============================================================
# CROP SMOOTHING
# ============================================================
def smooth_crop_positions(
    crop_regions: list[CropRegion],
    alpha: float = 0.3,
) -> list[CropRegion]:
    """Smooth crop X positions across scenes using EMA.

    Applies exponential moving average to prevent jarring jumps
    in the crop position between consecutive scenes.

    Args:
        crop_regions: Ordered list of crop regions for consecutive
            scenes. Each region must have the same width and height.
        alpha: Smoothing factor (0-1). Lower = smoother. 0.3 default.

    Returns:
        New list of CropRegion with smoothed X positions.
    """
    if len(crop_regions) <= 1:
        return list(crop_regions)

    smoothed: list[CropRegion] = []
    prev_x = float(crop_regions[0].x)

    for i, region in enumerate(crop_regions):
        smooth_x = (
            float(region.x)
            if i == 0
            else alpha * region.x + (1 - alpha) * prev_x
        )

        prev_x = smooth_x

        smoothed.append(
            CropRegion(
                x=round(smooth_x),
                y=region.y,
                width=region.width,
                height=region.height,
            )
        )

    # Clamp smoothed positions to valid bounds
    for region in smoothed:
        if region.x < 0:
            region.x = 0

    return smoothed
