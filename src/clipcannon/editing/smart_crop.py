"""Smart cropping and layout for ClipCannon EDL rendering.

Supports three layout modes for vertical video:
- crop: Single face-centered crop (default). Good for talking-head.
- split_screen: Speaker top + screen content bottom. For tutorials,
  screen shares, demos where center-crop loses the screen content.
- pip: Picture-in-picture. Small speaker overlay on full screen.

Uses face detection to anchor the crop window on the primary
speaker when converting landscape (16:9) source video to vertical
(9:16) or square (1:1) target aspect ratios.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

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


# ============================================================
# DATA CLASSES
# ============================================================
@dataclass
class FaceDetection:
    """A detected face bounding box."""

    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center_x(self) -> float:
        """Horizontal center of the face in pixels."""
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        """Vertical center of the face in pixels."""
        return self.y + self.height / 2.0

    @property
    def area(self) -> int:
        """Area of the bounding box in pixels."""
        return self.width * self.height


@dataclass
class CropRegion:
    """Calculated crop window for a scene."""

    x: int
    y: int
    width: int
    height: int


# ============================================================
# FACE DETECTION
# ============================================================
def detect_faces(frame_path: Path) -> list[FaceDetection]:
    """Detect faces in a frame image.

    Tries MediaPipe Face Detection first, then InsightFace ONNX
    as fallback. Returns empty list if neither model is available.

    Args:
        frame_path: Path to the frame image file.

    Returns:
        List of FaceDetection instances sorted by area (largest first).
        Empty list if no faces found or models unavailable.
    """
    if not frame_path.exists():
        logger.warning("Frame file not found: %s", frame_path)
        return []

    # Try MediaPipe first
    faces = _detect_faces_mediapipe(frame_path)
    if faces:
        return sorted(faces, key=lambda f: f.area, reverse=True)

    # Fallback to InsightFace
    faces = _detect_faces_insightface(frame_path)
    if faces:
        return sorted(faces, key=lambda f: f.area, reverse=True)

    logger.info("No faces detected in %s", frame_path)
    return []


def _detect_faces_mediapipe(frame_path: Path) -> list[FaceDetection]:
    """Detect faces using MediaPipe Face Detection.

    Args:
        frame_path: Path to the frame image.

    Returns:
        List of detected faces, or empty list on failure.
    """
    try:
        import mediapipe as mp
        import numpy as np
        from PIL import Image
    except ImportError:
        logger.debug("MediaPipe not available for face detection")
        return []

    try:
        image = Image.open(frame_path).convert("RGB")
        img_array = np.array(image)
        img_h, img_w = img_array.shape[:2]

        mp_face = mp.solutions.face_detection
        with mp_face.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.5,
        ) as face_detection:
            results = face_detection.process(img_array)

            if not results.detections:
                return []

            faces: list[FaceDetection] = []
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                x = max(0, int(bbox.xmin * img_w))
                y = max(0, int(bbox.ymin * img_h))
                w = min(int(bbox.width * img_w), img_w - x)
                h = min(int(bbox.height * img_h), img_h - y)
                conf = float(detection.score[0])
                faces.append(FaceDetection(x=x, y=y, width=w, height=h, confidence=conf))

            return faces

    except Exception as exc:
        logger.warning("MediaPipe face detection failed: %s", exc)
        return []


def _detect_faces_insightface(frame_path: Path) -> list[FaceDetection]:
    """Detect faces using InsightFace ONNX as fallback.

    Args:
        frame_path: Path to the frame image.

    Returns:
        List of detected faces, or empty list on failure.
    """
    try:
        import numpy as np
        from insightface.app import FaceAnalysis
        from PIL import Image
    except ImportError:
        logger.debug("InsightFace not available for face detection")
        return []

    try:
        image = Image.open(frame_path).convert("RGB")
        img_array = np.array(image)

        app = FaceAnalysis(
            name="buffalo_sc",
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=0, det_size=(640, 640))
        det_faces = app.get(img_array)

        faces: list[FaceDetection] = []
        for face in det_faces:
            bbox = face.bbox.astype(int)
            x, y = int(bbox[0]), int(bbox[1])
            w = int(bbox[2] - bbox[0])
            h = int(bbox[3] - bbox[1])
            conf = float(face.det_score)
            faces.append(FaceDetection(x=x, y=y, width=w, height=h, confidence=conf))

        return faces

    except Exception as exc:
        logger.warning("InsightFace face detection failed: %s", exc)
        return []


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


# ============================================================
# SPLIT-SCREEN LAYOUT
# ============================================================
@dataclass
class SplitScreenLayout:
    """Computed split-screen regions for FFmpeg vstack."""

    # Region in the SOURCE frame to use as screen content
    screen_src_x: int
    screen_src_y: int
    screen_src_w: int
    screen_src_h: int

    # Region in the SOURCE frame to use as speaker
    speaker_src_x: int
    speaker_src_y: int
    speaker_src_w: int
    speaker_src_h: int

    # Dimensions in the OUTPUT frame
    output_w: int
    output_h: int
    screen_out_h: int
    speaker_out_h: int
    separator_px: int
    separator_color: str
    speaker_position: str  # "top" or "bottom"


def detect_speaker_region(
    source_w: int,
    source_h: int,
    faces: list[FaceDetection],
) -> tuple[int, int, int, int] | None:
    """Detect the webcam/speaker region in a composited frame.

    Heuristic: the speaker webcam overlay is typically in a corner
    of the source frame. Look for a face and estimate the webcam
    region as a bounding box around it with padding.

    If no faces detected, returns None (can't auto-detect).

    Args:
        source_w: Source frame width.
        source_h: Source frame height.
        faces: Detected faces from detect_faces().

    Returns:
        (x, y, width, height) of the speaker region, or None.
    """
    if not faces:
        return None

    # Use the largest face (closest to camera)
    face = faces[0]

    # Estimate webcam region: expand face bbox by 2x in each direction
    # and snap to the nearest corner quadrant
    pad_x = face.width
    pad_y = int(face.height * 1.5)

    cam_x = max(0, face.x - pad_x)
    cam_y = max(0, face.y - pad_y)
    cam_w = min(face.width + 2 * pad_x, source_w - cam_x)
    cam_h = min(face.height + 2 * pad_y, source_h - cam_y)

    # Determine which quadrant the face is in
    cx = face.center_x
    cy = face.center_y

    # If face is in the bottom-right quadrant, likely a PIP overlay
    in_right_half = cx > source_w * 0.5
    in_bottom_half = cy > source_h * 0.5

    if in_right_half and in_bottom_half:
        # Bottom-right PIP — common in OBS/screen recordings
        cam_w = min(cam_w, source_w // 3)
        cam_h = min(cam_h, source_h // 3)
        cam_x = max(source_w - cam_w, face.x - pad_x)
        cam_y = max(source_h - cam_h, face.y - pad_y)
    elif not in_right_half and in_bottom_half:
        # Bottom-left PIP
        cam_w = min(cam_w, source_w // 3)
        cam_h = min(cam_h, source_h // 3)
        cam_x = 0
        cam_y = max(source_h - cam_h, face.y - pad_y)
    else:
        # Face is prominently placed — likely half the frame is speaker
        # Use the half of the frame containing the face
        if in_right_half:
            cam_x = source_w // 2
            cam_w = source_w // 2
            cam_y = 0
            cam_h = source_h
        else:
            cam_x = 0
            cam_w = source_w // 2
            cam_y = 0
            cam_h = source_h

    return (cam_x, cam_y, cam_w, cam_h)


def compute_screen_region(
    source_w: int,
    source_h: int,
    speaker_region: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int]:
    """Compute the screen content region (everything NOT the speaker).

    If no speaker region is known, returns the full frame.

    Args:
        source_w: Source frame width.
        source_h: Source frame height.
        speaker_region: (x, y, w, h) of the speaker region, or None.

    Returns:
        (x, y, width, height) of the screen content region.
    """
    if speaker_region is None:
        return (0, 0, source_w, source_h)

    sp_x, sp_y, sp_w, sp_h = speaker_region

    # If the speaker is in a small corner overlay, the screen is the full frame
    sp_area = sp_w * sp_h
    frame_area = source_w * source_h
    if sp_area < frame_area * 0.2:
        # Speaker is a small PIP — screen is the full frame
        return (0, 0, source_w, source_h)

    # If the speaker takes a significant portion, use the OTHER half
    if sp_x > source_w * 0.4:
        # Speaker is on the right — screen is on the left
        return (0, 0, sp_x, source_h)
    # Speaker is on the left — screen is on the right
    return (sp_x + sp_w, 0, source_w - sp_x - sp_w, source_h)


def compute_split_screen_layout(
    source_w: int,
    source_h: int,
    output_w: int,
    output_h: int,
    faces: list[FaceDetection],
    speaker_position: str = "top",
    split_ratio: float = 0.35,
    separator_px: int = 4,
    separator_color: str = "#FFFFFF",
    manual_speaker_region: dict[str, int] | None = None,
    manual_screen_region: dict[str, int] | None = None,
) -> SplitScreenLayout:
    """Compute split-screen layout for vertical video.

    Divides the output into two stacked regions:
    - Speaker region (from webcam/face area of source)
    - Screen content region (the rest of the source)

    Args:
        source_w: Source frame width in pixels.
        source_h: Source frame height in pixels.
        output_w: Output frame width (e.g., 1080).
        output_h: Output frame height (e.g., 1920).
        faces: Detected faces for auto speaker region detection.
        speaker_position: "top" or "bottom".
        split_ratio: Speaker region as fraction of output height.
        separator_px: Height of separator bar between regions.
        separator_color: Separator bar color hex.
        manual_speaker_region: Manual {x, y, width, height} override.
        manual_screen_region: Manual {x, y, width, height} override.

    Returns:
        SplitScreenLayout with computed source and output regions.
    """
    # Resolve speaker region
    if manual_speaker_region is not None:
        sp_region = (
            manual_speaker_region["x"],
            manual_speaker_region["y"],
            manual_speaker_region["width"],
            manual_speaker_region["height"],
        )
    else:
        sp_region = detect_speaker_region(source_w, source_h, faces)

    # If no speaker found, fall back to bottom-right quadrant guess
    if sp_region is None:
        sp_region = (
            source_w * 2 // 3,
            source_h * 2 // 3,
            source_w // 3,
            source_h // 3,
        )

    # Resolve screen region
    if manual_screen_region is not None:
        scr_region = (
            manual_screen_region["x"],
            manual_screen_region["y"],
            manual_screen_region["width"],
            manual_screen_region["height"],
        )
    else:
        scr_region = compute_screen_region(source_w, source_h, sp_region)

    # Compute output dimensions
    speaker_out_h = int(output_h * split_ratio) - separator_px // 2
    screen_out_h = output_h - speaker_out_h - separator_px

    return SplitScreenLayout(
        screen_src_x=scr_region[0],
        screen_src_y=scr_region[1],
        screen_src_w=scr_region[2],
        screen_src_h=scr_region[3],
        speaker_src_x=sp_region[0],
        speaker_src_y=sp_region[1],
        speaker_src_w=sp_region[2],
        speaker_src_h=sp_region[3],
        output_w=output_w,
        output_h=output_h,
        screen_out_h=screen_out_h,
        speaker_out_h=speaker_out_h,
        separator_px=separator_px,
        separator_color=separator_color,
        speaker_position=speaker_position,
    )


# ============================================================
# PIP (PICTURE-IN-PICTURE) LAYOUT
# ============================================================
@dataclass
class PipLayout:
    """Computed picture-in-picture layout for FFmpeg overlay."""

    # Full-screen background (screen content, scaled to output)
    bg_src_x: int
    bg_src_y: int
    bg_src_w: int
    bg_src_h: int

    # PIP window (speaker, cropped from source)
    pip_src_x: int
    pip_src_y: int
    pip_src_w: int
    pip_src_h: int

    # Output dimensions
    output_w: int
    output_h: int
    pip_out_w: int
    pip_out_h: int
    pip_x: int  # PIP position in output frame
    pip_y: int
    pip_border_px: int
    pip_border_color: str


def compute_pip_layout(
    source_w: int,
    source_h: int,
    output_w: int,
    output_h: int,
    faces: list[FaceDetection],
    pip_size: float = 0.25,
    pip_position: str = "bottom_right",
    pip_margin_px: int = 20,
    pip_border_px: int = 3,
    pip_border_color: str = "#FFFFFF",
    manual_speaker_region: dict[str, int] | None = None,
) -> PipLayout:
    """Compute picture-in-picture layout.

    Full screen shows the screen content. A small PIP window
    shows the speaker, positioned in a corner.

    Args:
        source_w: Source frame width.
        source_h: Source frame height.
        output_w: Output width (e.g., 1080).
        output_h: Output height (e.g., 1920).
        faces: Detected faces for speaker region.
        pip_size: PIP window as fraction of output width.
        pip_position: Corner placement.
        pip_margin_px: Margin from edges.
        pip_border_px: Border width around PIP.
        pip_border_color: Border color hex.
        manual_speaker_region: Manual override for speaker region.

    Returns:
        PipLayout with computed positions.
    """
    # Speaker region
    if manual_speaker_region is not None:
        sp = (
            manual_speaker_region["x"],
            manual_speaker_region["y"],
            manual_speaker_region["width"],
            manual_speaker_region["height"],
        )
    else:
        sp = detect_speaker_region(source_w, source_h, faces)
        if sp is None:
            sp = (
                source_w * 2 // 3,
                source_h * 2 // 3,
                source_w // 3,
                source_h // 3,
            )

    # PIP output dimensions
    pip_out_w = int(output_w * pip_size)
    pip_out_h = int(pip_out_w * sp[3] / max(sp[2], 1))

    # PIP position in output frame
    margin = pip_margin_px + pip_border_px
    if pip_position == "top_left":
        pip_x = margin
        pip_y = margin
    elif pip_position == "top_right":
        pip_x = output_w - pip_out_w - margin
        pip_y = margin
    elif pip_position == "bottom_left":
        pip_x = margin
        pip_y = output_h - pip_out_h - margin
    else:  # bottom_right
        pip_x = output_w - pip_out_w - margin
        pip_y = output_h - pip_out_h - margin

    return PipLayout(
        bg_src_x=0,
        bg_src_y=0,
        bg_src_w=source_w,
        bg_src_h=source_h,
        pip_src_x=sp[0],
        pip_src_y=sp[1],
        pip_src_w=sp[2],
        pip_src_h=sp[3],
        output_w=output_w,
        output_h=output_h,
        pip_out_w=pip_out_w,
        pip_out_h=pip_out_h,
        pip_x=pip_x,
        pip_y=pip_y,
        pip_border_px=pip_border_px,
        pip_border_color=pip_border_color,
    )
