"""Layout measurement via face detection for mathematically precise compositing.

Uses face detection to calculate exact source crop coordinates and output
placement for all standard layouts (A, B, C, D). Eliminates guesswork
by computing positions from detected face bounding boxes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from clipcannon.editing.smart_crop import FaceDetection, detect_faces

logger = logging.getLogger(__name__)

# Standard vertical canvas dimensions
CANVAS_W = 1080
CANVAS_H = 1920

# Eye line position within a face bounding box (fraction from top)
EYE_LINE_IN_FACE = 0.38

# Layout definitions: (speaker_height, screen_height)
LAYOUT_HEIGHTS: dict[str, tuple[int, int]] = {
    "A": (576, 1344),   # 30/70 split
    "B": (768, 1152),   # 40/60 split
    "C_circle": (240, 1920),   # PIP circle
    "C_rect": (350, 1920),     # PIP rectangle
    "D": (1920, 0),     # Full-screen face
}

# PIP positions: (x, y) for top-left corner of PIP window
PIP_POSITIONS: dict[str, tuple[int, int]] = {
    "top_left": (24, 140),
    "top_right_circle": (816, 140),
    "top_right_rect": (776, 140),
}


@dataclass
class LayoutMeasurement:
    """Mathematically computed layout coordinates from face detection."""

    layout: str
    face_detected: bool
    face_bbox: dict[str, int] = field(default_factory=dict)
    speaker_region: dict[str, int] = field(default_factory=dict)
    screen_region: dict[str, int] = field(default_factory=dict)
    canvas_regions: list[dict[str, object]] = field(default_factory=list)
    eye_line_y: int = 0
    headroom_px: int = 0
    face_width_pct: float = 0.0


def _compute_speaker_crop(
    face: FaceDetection,
    frame_w: int,
    frame_h: int,
    output_w: int,
    output_h: int,
) -> dict[str, int]:
    """Compute source crop coordinates to center face in output region.

    Uses cover-mode math: the crop is sized so that when scaled to
    fill output_w x output_h, the face ends up centered with proper
    headroom and eye-line placement.

    Args:
        face: Detected face bounding box in source frame.
        frame_w: Source frame width.
        frame_h: Source frame height.
        output_w: Target output region width.
        output_h: Target output region height.

    Returns:
        Dict with source_x, source_y, source_w, source_h.
    """
    output_aspect = output_w / output_h

    # Face center in source
    face_cx = face.center_x

    # Eye position in source (eyes are ~38% from top of face bbox)
    eye_y = face.y + face.height * EYE_LINE_IN_FACE

    # Size the crop based on the FACE, not the frame.
    # For wide outputs (Layout A/B speaker region), size based on
    # showing face + upper body at ~60-80% face width.
    # For tall outputs (Layout D full face), size based on tight face crop.

    if output_aspect >= 1.0:
        # Wide output (speaker region in split layout)
        # Crop height = face height * 2.5 (face + upper shoulders)
        crop_h = int(face.height * 2.5)
        crop_w = int(crop_h * output_aspect)
    else:
        # Tall output (full-screen face, PIP)
        # Face should be 60-70% of output width
        target_face_pct = 0.65
        crop_w = int(face.width / target_face_pct)
        crop_h = int(crop_w / output_aspect)

    # Clamp to frame dimensions
    crop_w = min(crop_w, frame_w)
    crop_h = min(crop_h, frame_h)

    # Position the crop so the eye line lands at upper third of output.
    # After cover-scaling, the crop maps 1:1 to output (same aspect ratio).
    # Eye should be at 1/3 of crop height from top.
    desired_eye_in_crop = crop_h / 3.0
    crop_y = int(eye_y - desired_eye_in_crop)

    # Center horizontally on face
    crop_x = int(face_cx - crop_w / 2)

    # Clamp to frame bounds
    crop_x = max(0, min(crop_x, frame_w - crop_w))
    crop_y = max(0, min(crop_y, frame_h - crop_h))

    return {
        "source_x": crop_x,
        "source_y": crop_y,
        "source_w": crop_w,
        "source_h": crop_h,
    }


def _compute_screen_crop(
    frame_w: int,
    frame_h: int,
    face: FaceDetection | None,
    output_w: int,
    output_h: int,
) -> dict[str, int]:
    """Compute source crop for screen content, excluding the webcam area.

    Crops the screen content region (everything except the webcam
    overlay area). Uses the face detection to identify and exclude
    the webcam corner.

    Args:
        frame_w: Source frame width.
        frame_h: Source frame height.
        face: Detected face (to identify webcam corner to exclude).
        output_w: Target output width.
        output_h: Target output height.

    Returns:
        Dict with source_x, source_y, source_w, source_h.
    """
    if face is None:
        # No face detected - use full frame
        return {
            "source_x": 0,
            "source_y": 0,
            "source_w": frame_w,
            "source_h": frame_h,
        }

    # Determine which corner the webcam is in
    webcam_right = face.center_x > frame_w / 2
    webcam_bottom = face.center_y > frame_h / 2

    # Exclude the webcam quadrant from the screen content
    # Add margin around the webcam area
    margin = 40

    if webcam_right and webcam_bottom:
        # Webcam in bottom-right: screen is everything left of webcam
        screen_w = max(face.x - margin, frame_w // 2)
        screen_h = frame_h
        screen_x = 0
        screen_y = 0
    elif webcam_right and not webcam_bottom:
        # Webcam in top-right
        screen_w = max(face.x - margin, frame_w // 2)
        screen_h = frame_h
        screen_x = 0
        screen_y = 0
    elif not webcam_right and webcam_bottom:
        # Webcam in bottom-left
        screen_x = face.x + face.width + margin
        screen_w = frame_w - screen_x
        screen_h = frame_h
        screen_y = 0
    else:
        # Webcam in top-left
        screen_x = face.x + face.width + margin
        screen_w = frame_w - screen_x
        screen_h = frame_h
        screen_y = 0

    # Crop out browser chrome (top ~70px) and taskbar (bottom ~50px)
    chrome_top = 70
    taskbar_bottom = 50
    screen_y = max(screen_y, chrome_top)
    screen_h = min(screen_h, frame_h - taskbar_bottom) - screen_y

    return {
        "source_x": max(0, screen_x),
        "source_y": max(0, screen_y),
        "source_w": min(screen_w, frame_w),
        "source_h": max(100, screen_h),
    }


def measure_layout(
    frame_path: str,
    frame_w: int,
    frame_h: int,
    layout: str = "A",
) -> LayoutMeasurement:
    """Compute exact layout coordinates from face detection.

    Runs face detection on the given frame and calculates
    mathematically precise source crop and output placement
    coordinates for the requested layout type.

    Args:
        frame_path: Path to the frame image.
        frame_w: Source frame width in pixels.
        frame_h: Source frame height in pixels.
        layout: Layout type - A (30/70), B (40/60), C (PIP), D (full face).

    Returns:
        LayoutMeasurement with exact coordinates for canvas regions.

    Raises:
        ValueError: If layout type is not recognized.
    """
    if layout not in ("A", "B", "C", "D"):
        raise ValueError(
            f"Unknown layout: {layout!r}. Valid: A, B, C, D"
        )

    path = Path(frame_path)
    faces = detect_faces(path) if path.exists() else []

    if not faces:
        logger.warning("No face detected in %s", frame_path)
        return LayoutMeasurement(
            layout=layout,
            face_detected=False,
        )

    face = faces[0]  # Largest face (primary speaker)

    # Face metrics
    eye_y_source = int(face.y + face.height * EYE_LINE_IN_FACE)

    if layout == "D":
        # Full-screen face
        speaker_h = CANVAS_H
        speaker_crop = _compute_speaker_crop(
            face, frame_w, frame_h, CANVAS_W, speaker_h,
        )

        # Calculate where the eye line will land in output
        scale = speaker_h / speaker_crop["source_h"]
        eye_in_output = int((eye_y_source - speaker_crop["source_y"]) * scale)

        result = LayoutMeasurement(
            layout="D",
            face_detected=True,
            face_bbox={
                "x": face.x, "y": face.y,
                "width": face.width, "height": face.height,
                "confidence": round(face.confidence, 3),
            },
            speaker_region=speaker_crop,
            eye_line_y=eye_in_output,
            headroom_px=int((eye_y_source - face.y * 0.6 - speaker_crop["source_y"]) * scale),
            face_width_pct=round(face.width / speaker_crop["source_w"] * 100, 1),
            canvas_regions=[
                {
                    "region_id": "speaker",
                    "source_x": speaker_crop["source_x"],
                    "source_y": speaker_crop["source_y"],
                    "source_width": speaker_crop["source_w"],
                    "source_height": speaker_crop["source_h"],
                    "output_x": 0,
                    "output_y": 0,
                    "output_width": CANVAS_W,
                    "output_height": CANVAS_H,
                    "z_index": 1,
                    "fit_mode": "cover",
                },
            ],
        )
        return result

    if layout in ("A", "B"):
        speaker_h, screen_h = LAYOUT_HEIGHTS[layout]
        speaker_crop = _compute_speaker_crop(
            face, frame_w, frame_h, CANVAS_W, speaker_h,
        )
        screen_crop = _compute_screen_crop(
            frame_w, frame_h, face, CANVAS_W, screen_h,
        )

        scale = speaker_h / speaker_crop["source_h"]
        eye_in_output = int((eye_y_source - speaker_crop["source_y"]) * scale)

        return LayoutMeasurement(
            layout=layout,
            face_detected=True,
            face_bbox={
                "x": face.x, "y": face.y,
                "width": face.width, "height": face.height,
                "confidence": round(face.confidence, 3),
            },
            speaker_region=speaker_crop,
            screen_region=screen_crop,
            eye_line_y=eye_in_output,
            headroom_px=max(0, int((face.y - speaker_crop["source_y"]) * scale)),
            face_width_pct=round(face.width / speaker_crop["source_w"] * 100, 1),
            canvas_regions=[
                {
                    "region_id": "speaker",
                    "source_x": speaker_crop["source_x"],
                    "source_y": speaker_crop["source_y"],
                    "source_width": speaker_crop["source_w"],
                    "source_height": speaker_crop["source_h"],
                    "output_x": 0,
                    "output_y": 0,
                    "output_width": CANVAS_W,
                    "output_height": speaker_h,
                    "z_index": 2,
                    "fit_mode": "cover",
                },
                {
                    "region_id": "screen",
                    "source_x": screen_crop["source_x"],
                    "source_y": screen_crop["source_y"],
                    "source_width": screen_crop["source_w"],
                    "source_height": screen_crop["source_h"],
                    "output_x": 0,
                    "output_y": speaker_h,
                    "output_width": CANVAS_W,
                    "output_height": screen_h,
                    "z_index": 1,
                    "fit_mode": "cover",
                },
            ],
        )

    # Layout C: PIP
    pip_size = 240
    screen_crop = _compute_screen_crop(
        frame_w, frame_h, face, CANVAS_W, CANVAS_H,
    )
    speaker_crop = _compute_speaker_crop(
        face, frame_w, frame_h, pip_size, pip_size,
    )

    return LayoutMeasurement(
        layout="C",
        face_detected=True,
        face_bbox={
            "x": face.x, "y": face.y,
            "width": face.width, "height": face.height,
            "confidence": round(face.confidence, 3),
        },
        speaker_region=speaker_crop,
        screen_region=screen_crop,
        face_width_pct=round(face.width / speaker_crop["source_w"] * 100, 1),
        canvas_regions=[
            {
                "region_id": "screen",
                "source_x": screen_crop["source_x"],
                "source_y": screen_crop["source_y"],
                "source_width": screen_crop["source_w"],
                "source_height": screen_crop["source_h"],
                "output_x": 0,
                "output_y": 0,
                "output_width": CANVAS_W,
                "output_height": CANVAS_H,
                "z_index": 1,
                "fit_mode": "cover",
            },
            {
                "region_id": "pip_speaker",
                "source_x": speaker_crop["source_x"],
                "source_y": speaker_crop["source_y"],
                "source_width": speaker_crop["source_w"],
                "source_height": speaker_crop["source_h"],
                "output_x": 24,
                "output_y": 140,
                "output_width": pip_size,
                "output_height": pip_size,
                "z_index": 2,
                "fit_mode": "cover",
            },
        ],
    )
