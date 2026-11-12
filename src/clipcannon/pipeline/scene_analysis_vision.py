"""Frame-level vision helpers for scene analysis (faces, webcam, content)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import cv2

if TYPE_CHECKING:
    import numpy as np

# Content exclusion zones (pixels in SOURCE coordinates)
CHROME_TOP = 70
CHROME_BOTTOM = 50

# Analysis resolution - downsample to this before processing
ANALYSIS_W = 1280
ANALYSIS_H = 720


def _downsample(frame: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Downsample frame to analysis resolution. Returns (small, scale_x, scale_y)."""
    h, w = frame.shape[:2]
    if w <= ANALYSIS_W and h <= ANALYSIS_H:
        return frame, 1.0, 1.0
    scale_x = ANALYSIS_W / w
    scale_y = ANALYSIS_H / h
    scale = min(scale_x, scale_y)
    new_w = int(w * scale)
    new_h = int(h * scale)
    small = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return small, w / new_w, h / new_h


def _create_face_detector() -> object:
    """Create a reusable MediaPipe face detector."""
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (
        FaceDetector,
        FaceDetectorOptions,
    )

    model_path = Path.home() / ".clipcannon" / "models" / "blaze_face_short_range.tflite"
    if not model_path.exists():
        raise FileNotFoundError(
            f"BlazeFace model not found at {model_path}. "
            "Download it to enable face detection."
        )

    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        min_detection_confidence=0.4,
    )
    return FaceDetector.create_from_options(options)


def _detect_face_with_detector(
    detector: object,
    frame_path: Path,
    frame_w: int,
    frame_h: int,
) -> dict[str, object] | None:
    """Detect face using a pre-created detector. Scales coords to source resolution."""
    import tempfile

    import mediapipe as mp
    from PIL import Image as PILImage

    # Load and downsample for detection
    pil_img = PILImage.open(frame_path)
    img_w, img_h = pil_img.size
    half_w = img_w // 2

    # Try full image first (fast path for large faces)
    image = mp.Image.create_from_file(str(frame_path))
    result = detector.detect(image)

    if result.detections:
        d = result.detections[0]
        bbox = d.bounding_box
        return {
            "x": bbox.origin_x,
            "y": bbox.origin_y,
            "w": bbox.width,
            "h": bbox.height,
            "confidence": round(d.categories[0].score, 3),
        }

    # Quadrant search for small webcam faces
    quadrants = [
        (half_w, 0, img_w, img_h, half_w, 0),
        (0, 0, half_w, img_h, 0, 0),
        (half_w, img_h // 2, img_w, img_h, half_w, img_h // 2),
        (0, img_h // 2, half_w, img_h, 0, img_h // 2),
    ]

    for x1, y1, x2, y2, offset_x, offset_y in quadrants:
        crop = pil_img.crop((x1, y1, x2, y2))
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            crop.save(tmp.name, "JPEG", quality=85)
            crop_image = mp.Image.create_from_file(tmp.name)
            crop_result = detector.detect(crop_image)
            Path(tmp.name).unlink(missing_ok=True)

        if crop_result.detections:
            d = crop_result.detections[0]
            bbox = d.bounding_box
            return {
                "x": bbox.origin_x + offset_x,
                "y": bbox.origin_y + offset_y,
                "w": bbox.width,
                "h": bbox.height,
                "confidence": round(d.categories[0].score, 3),
            }

    return None


def _compute_ssim(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    """Fast SSIM-like comparison on 320x180 thumbnails."""
    gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
    small_a = cv2.resize(gray_a, (320, 180))
    small_b = cv2.resize(gray_b, (320, 180))
    result = cv2.matchTemplate(small_a, small_b, cv2.TM_CCORR_NORMED)
    return float(result[0][0])


def _detect_webcam_region(
    face: dict[str, object], frame_w: int, frame_h: int,
) -> dict[str, int]:
    """Expand face bbox to webcam overlay region."""
    fx, fy = int(face["x"]), int(face["y"])
    fw, fh = int(face["w"]), int(face["h"])
    expand_w, expand_h = int(fw * 1.8), int(fh * 2.5)
    wcam_x = max(0, fx - (expand_w - fw) // 2)
    wcam_y = max(0, fy - int(fh * 0.3))
    wcam_w = min(expand_w, frame_w - wcam_x)
    wcam_h = min(expand_h, frame_h - wcam_y)
    return {"x": wcam_x, "y": wcam_y, "w": wcam_w, "h": wcam_h}


def _detect_content_region(
    frame_curr: np.ndarray, frame_prev: np.ndarray | None,
    webcam: dict[str, int] | None, frame_w: int, frame_h: int,
) -> dict[str, int]:
    """Detect content region using frame differencing on downsampled frames."""
    cx, cy = 0, CHROME_TOP
    cw, ch = frame_w, frame_h - CHROME_TOP - CHROME_BOTTOM

    if webcam is not None:
        if webcam["x"] > frame_w // 2:
            cw = min(cw, webcam["x"] - 40)
        else:
            cx = webcam["x"] + webcam["w"] + 40
            cw = frame_w - cx

    if frame_prev is not None:
        # Downsample both frames for fast differencing
        small_curr, sx, sy = _downsample(frame_curr)
        small_prev, _, _ = _downsample(frame_prev)

        gray_c = cv2.cvtColor(small_curr, cv2.COLOR_BGR2GRAY)
        gray_p = cv2.cvtColor(small_prev, cv2.COLOR_BGR2GRAY)

        # Ensure same size
        if gray_c.shape != gray_p.shape:
            gray_p = cv2.resize(gray_p, (gray_c.shape[1], gray_c.shape[0]))

        diff = cv2.absdiff(gray_c, gray_p)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

        # Mask webcam and chrome (in downsampled coordinates)
        if webcam is not None:
            margin = 60
            wx2 = max(0, int(webcam["x"] / sx) - margin)
            wy2 = max(0, int(webcam["y"] / sy) - margin)
            ww2 = min(thresh.shape[1] - wx2, int(webcam["w"] / sx) + margin * 2)
            wh2 = min(thresh.shape[0] - wy2, int(webcam["h"] / sy) + margin * 2)
            thresh[wy2:wy2 + wh2, wx2:wx2 + ww2] = 0
        chrome_top_ds = int(CHROME_TOP / sy)
        chrome_bot_ds = int(CHROME_BOTTOM / sy)
        thresh[:chrome_top_ds, :] = 0
        if chrome_bot_ds > 0:
            thresh[-chrome_bot_ds:, :] = 0

        coords = cv2.findNonZero(thresh)
        if coords is not None and len(coords) > 100:
            bx, by, bw, bh = cv2.boundingRect(coords)
            # Scale back to source coordinates
            bx_src = int(bx * sx)
            by_src = int(by * sy)
            bw_src = int(bw * sx)
            bh_src = int(bh * sy)
            if bw_src > frame_w * 0.1 and bh_src > frame_h * 0.1:
                cx = bx_src
                cy = max(by_src, CHROME_TOP)
                cw = bw_src
                ch = min(bh_src, frame_h - CHROME_BOTTOM - cy)

    # Clamp content to not overlap webcam
    if webcam is not None:
        if webcam["x"] > frame_w // 2:
            max_right = webcam["x"] - 40
            if cx + cw > max_right:
                cw = max(100, max_right - cx)
        else:
            min_left = webcam["x"] + webcam["w"] + 40
            if cx < min_left:
                cw = max(100, cw - (min_left - cx))
                cx = min_left

    return {"x": max(0, cx), "y": max(0, cy),
            "w": max(100, cw), "h": max(100, ch)}
