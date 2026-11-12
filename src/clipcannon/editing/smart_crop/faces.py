"""Face detection for smart cropping (MediaPipe with InsightFace fallback)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


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


_FACE_MODEL_PATH = Path.home() / ".clipcannon" / "models" / "blaze_face_short_range.tflite"


def _detect_faces_mediapipe(frame_path: Path) -> list[FaceDetection]:
    """Detect faces using MediaPipe Face Detection (Tasks API).

    Uses BlazeFace short-range model running locally. If no face is
    found in the full frame (common with small webcam overlays in
    large screen recordings), tries detection on each quadrant of
    the frame with coordinates mapped back to full-frame space.

    Args:
        frame_path: Path to the frame image.

    Returns:
        List of detected faces, or empty list on failure.

    Raises:
        FileNotFoundError: If the BlazeFace model file is missing.
    """
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (
        FaceDetector,
        FaceDetectorOptions,
    )

    if not _FACE_MODEL_PATH.exists():
        raise FileNotFoundError(
            f"BlazeFace model not found at {_FACE_MODEL_PATH}. "
            "Download from: https://storage.googleapis.com/mediapipe-models/"
            "face_detector/blaze_face_short_range/float16/1/"
            "blaze_face_short_range.tflite"
        )

    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(_FACE_MODEL_PATH)),
        min_detection_confidence=0.4,
    )
    detector = FaceDetector.create_from_options(options)

    try:
        # Try full frame first
        image = mp.Image.create_from_file(str(frame_path))
        result = detector.detect(image)

        if result.detections:
            return _parse_mediapipe_detections(result.detections, 0, 0)

        # No face in full frame - try quadrant crops for small webcam overlays
        # Common in screen recordings: webcam is 10-25% of frame in one corner
        from PIL import Image as PILImage

        pil_img = PILImage.open(frame_path)
        img_w, img_h = pil_img.size
        half_w, half_h = img_w // 2, img_h // 2

        quadrants = [
            (half_w, 0, img_w, img_h, half_w, 0),       # right half
            (0, 0, half_w, img_h, 0, 0),                 # left half
            (half_w, half_h, img_w, img_h, half_w, half_h),  # bottom-right
            (0, half_h, half_w, img_h, 0, half_h),       # bottom-left
            (half_w, 0, img_w, half_h, half_w, 0),       # top-right
            (0, 0, half_w, half_h, 0, 0),                # top-left
        ]

        import tempfile

        for x1, y1, x2, y2, offset_x, offset_y in quadrants:
            crop = pil_img.crop((x1, y1, x2, y2))
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                crop.save(tmp.name, "JPEG", quality=90)
                crop_image = mp.Image.create_from_file(tmp.name)
                crop_result = detector.detect(crop_image)
                Path(tmp.name).unlink(missing_ok=True)

            if crop_result.detections:
                faces = _parse_mediapipe_detections(
                    crop_result.detections, offset_x, offset_y,
                )
                if faces:
                    logger.info(
                        "Face found in quadrant crop (%d,%d)-(%d,%d)",
                        x1, y1, x2, y2,
                    )
                    return faces

        return []

    finally:
        detector.close()


def _parse_mediapipe_detections(
    detections: list[object],
    offset_x: int,
    offset_y: int,
) -> list[FaceDetection]:
    """Parse MediaPipe detection results into FaceDetection objects.

    Args:
        detections: MediaPipe detection results.
        offset_x: X offset to add (for quadrant-cropped detection).
        offset_y: Y offset to add (for quadrant-cropped detection).

    Returns:
        List of FaceDetection with coordinates in full-frame space.
    """
    faces: list[FaceDetection] = []
    for detection in detections:
        bbox = detection.bounding_box
        x = bbox.origin_x + offset_x
        y = bbox.origin_y + offset_y
        w = bbox.width
        h = bbox.height
        conf = float(detection.categories[0].score)
        faces.append(
            FaceDetection(x=x, y=y, width=w, height=h, confidence=conf)
        )
    return faces


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
        # "No faces" and "detector failed" are different facts (#68).
        raise RuntimeError(f"InsightFace face detection failed on {frame_path}: {exc}") from exc
