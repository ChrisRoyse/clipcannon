"""Scene analysis pipeline stage for automated video editing.

Analyzes extracted frames to detect scene boundaries, face positions,
webcam overlay regions, and content areas. Pre-computes canvas regions
for all layout types so the AI never needs to manually measure coordinates.

Performance optimizations:
- Frames are downsampled to 1280x720 before analysis (7.5x fewer pixels)
- MediaPipe face detector is created once and reused across all scenes
- SSIM comparison uses 320x180 thumbnails
- Face detection runs only on scene representative frames (not every frame)

Runs during ingest after frame_extract.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

# Scene detection parameters
SCENE_THRESHOLD = 0.92

# Audio-aware boundary snapping: when a visual scene boundary falls
# during speech, snap it to the nearest silence gap or word boundary
# within this search radius (ms).
AUDIO_SNAP_RADIUS_MS = 2000

# Content exclusion zones (pixels in SOURCE coordinates)
CHROME_TOP = 70
CHROME_BOTTOM = 50

# Analysis resolution - downsample to this before processing
ANALYSIS_W = 1280
ANALYSIS_H = 720

# Output canvas (9:16 vertical)
CANVAS_W, CANVAS_H = 1080, 1920
LAYOUT_HEIGHTS = {"A": (576, 1344), "B": (768, 1152)}
PIP_SIZE, PIP_POS = 240, (24, 140)
EYE_LINE_PCT = 0.38

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scene_map (
    scene_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL, start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    face_x INTEGER, face_y INTEGER, face_w INTEGER, face_h INTEGER,
    face_confidence REAL, face_size_pct REAL DEFAULT 0,
    webcam_x INTEGER, webcam_y INTEGER, webcam_w INTEGER, webcam_h INTEGER,
    content_x INTEGER, content_y INTEGER, content_w INTEGER, content_h INTEGER,
    content_type TEXT DEFAULT 'unknown', visible_text TEXT DEFAULT '[]',
    layout_recommendation TEXT DEFAULT 'A',
    canvas_regions_json TEXT DEFAULT '{}', transcript_text TEXT DEFAULT '',
    FOREIGN KEY (project_id) REFERENCES project(project_id)
)"""

_INSERT_SQL = """INSERT INTO scene_map (
    project_id, start_ms, end_ms,
    face_x, face_y, face_w, face_h, face_confidence, face_size_pct,
    webcam_x, webcam_y, webcam_w, webcam_h,
    content_x, content_y, content_w, content_h,
    content_type, visible_text,
    layout_recommendation, canvas_regions_json, transcript_text
) VALUES (?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?, ?,?,?)"""


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


def _region(
    rid: str, sx: int, sy: int, sw: int, sh: int,
    ox: int, oy: int, ow: int, oh: int, z: int,
    fit: str = "cover",
) -> dict[str, object]:
    """Build a canvas region dict."""
    return {
        "region_id": rid,
        "source_x": sx, "source_y": sy,
        "source_width": sw, "source_height": sh,
        "output_x": ox, "output_y": oy,
        "output_width": ow, "output_height": oh,
        "z_index": z, "fit_mode": fit,
    }


def _pick_screen_fit_mode(cw: int, ch: int, ow: int, oh: int) -> str:
    """Choose fit_mode: contain for wide content, cover for vertical."""
    content_aspect = cw / max(ch, 1)
    output_aspect = ow / max(oh, 1)
    return "contain" if content_aspect > output_aspect * 1.3 else "cover"


def _compute_speaker_crop(
    face: dict[str, object], out_w: int, out_h: int,
    frame_w: int, frame_h: int,
) -> dict[str, int]:
    """Compute source crop for speaker region centered on face."""
    fx, fy = int(face["x"]), int(face["y"])
    fw, fh = int(face["w"]), int(face["h"])
    aspect = out_w / out_h
    if aspect >= 1.0:
        crop_h = int(fh * 2.5)
        crop_w = int(crop_h * aspect)
    else:
        crop_w = int(fw / 0.65)
        crop_h = int(crop_w / aspect)
    eye_y = fy + fh * EYE_LINE_PCT
    face_cx = fx + fw / 2.0
    crop_y = int(eye_y - crop_h / 3.0)
    crop_x = int(face_cx - crop_w / 2)
    crop_x = max(0, min(crop_x, frame_w - crop_w))
    crop_y = max(0, min(crop_y, frame_h - crop_h))
    return {"x": crop_x, "y": crop_y,
            "w": min(crop_w, frame_w), "h": min(crop_h, frame_h)}


def _build_canvas_regions(
    face: dict[str, object] | None, webcam: dict[str, int] | None,
    content: dict[str, int], frame_w: int, frame_h: int,
) -> dict[str, list[dict[str, object]]]:
    """Pre-compute canvas regions for all layout types."""
    result: dict[str, list[dict[str, object]]] = {}
    cx, cy, cw, ch = content["x"], content["y"], content["w"], content["h"]

    if face is None:
        fm = _pick_screen_fit_mode(cw, ch, CANVAS_W, CANVAS_H)
        scr = _region("screen", cx, cy, cw, ch,
                       0, 0, CANVAS_W, CANVAS_H, 1, fm)
        for layout in ("A", "B", "C", "D"):
            result[layout] = [scr]
        return result

    # Use webcam region for speaker (stable, shows full person)
    if webcam is not None:
        wx, wy, ww, wh = webcam["x"], webcam["y"], webcam["w"], webcam["h"]
    else:
        sc = _compute_speaker_crop(face, CANVAS_W, 576, frame_w, frame_h)
        wx, wy, ww, wh = sc["x"], sc["y"], sc["w"], sc["h"]

    for name, (spk_h, scr_h) in LAYOUT_HEIGHTS.items():
        fm = _pick_screen_fit_mode(cw, ch, CANVAS_W, scr_h)
        result[name] = [
            _region("speaker", wx, wy, ww, wh,
                    0, 0, CANVAS_W, spk_h, 2, "contain"),
            _region("screen", cx, cy, cw, ch,
                    0, spk_h, CANVAS_W, scr_h, 1, fm),
        ]

    pc = _compute_speaker_crop(face, PIP_SIZE, PIP_SIZE, frame_w, frame_h)
    fm = _pick_screen_fit_mode(cw, ch, CANVAS_W, CANVAS_H)
    result["C"] = [
        _region("screen", cx, cy, cw, ch,
                0, 0, CANVAS_W, CANVAS_H, 1, fm),
        _region("pip_speaker", pc["x"], pc["y"], pc["w"], pc["h"],
                PIP_POS[0], PIP_POS[1], PIP_SIZE, PIP_SIZE, 2),
    ]

    result["D"] = [
        _region("speaker_full", wx, wy, ww, wh,
                0, 0, CANVAS_W, CANVAS_H, 1, "contain"),
    ]
    return result


def _classify_content_type(
    face: dict[str, object] | None,
    webcam: dict[str, int] | None,
    content: dict[str, int],
    frame_w: int,
    frame_h: int,
) -> str:
    """Classify the content type of a scene based on detected regions.

    Uses heuristics from face area percentage, webcam presence, and
    content region size to determine the dominant content type.

    Returns one of: 'talking_head', 'screen_with_webcam', 'screen_only',
    'presentation', 'split_content', 'unknown'.
    """
    face_area_pct = 0.0
    if face is not None:
        face_area = int(face["w"]) * int(face["h"])
        face_area_pct = face_area / (frame_w * frame_h) * 100

    has_webcam = webcam is not None
    content_area_pct = (content["w"] * content["h"]) / (frame_w * frame_h) * 100

    # Face takes up >30% of frame = talking head
    if face_area_pct > 30:
        return "talking_head"

    # Webcam detected with content area = screen recording with webcam
    if has_webcam and content_area_pct > 40:
        return "screen_with_webcam"

    # Face detected but small, with large content area
    if face is not None and face_area_pct > 1 and content_area_pct > 50:
        return "screen_with_webcam"

    # No face, large content area = pure screen content
    if face is None and content_area_pct > 60:
        return "screen_only"

    # Small content area with face = presentation/slide
    if face is not None and content_area_pct < 40:
        return "presentation"

    return "screen_only"


def _ensure_scene_map_table(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scene_map_project "
            "ON scene_map(project_id, start_ms)")
        # Migrate: add face_size_pct column if missing on existing tables
        try:
            conn.execute(
                "ALTER TABLE scene_map ADD COLUMN face_size_pct REAL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.commit()
    finally:
        conn.close()


def _parse_frame_number(frame_path: Path) -> int:
    return int(frame_path.stem.split("_")[1])


def _get_transcript_segments(db_path: Path, project_id: str) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT start_ms, end_ms, text FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        ).fetchall()
        for r in rows:
            segments.append({"start_ms": int(r["start_ms"]),
                             "end_ms": int(r["end_ms"]),
                             "text": str(r["text"])})
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return segments


def _fetch_silence_gaps(
    db_path: Path, project_id: str,
) -> list[dict[str, int]]:
    """Fetch silence gaps from the acoustic analysis."""
    gaps: list[dict[str, int]] = []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT start_ms, end_ms, duration_ms FROM silence_gaps "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        ).fetchall()
        for r in rows:
            gaps.append({
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "mid_ms": (int(r["start_ms"]) + int(r["end_ms"])) // 2,
            })
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return gaps


def _fetch_word_boundaries(
    db_path: Path, project_id: str,
) -> list[int]:
    """Fetch word end timestamps as potential safe snap points."""
    boundaries: list[int] = []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT end_ms FROM transcript_words "
            "WHERE project_id = ? ORDER BY end_ms",
            (project_id,),
        ).fetchall()
        boundaries = [int(r["end_ms"]) for r in rows]
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()
    return boundaries


def _snap_boundary_to_audio(
    visual_ms: int,
    silence_gaps: list[dict[str, int]],
    word_boundaries: list[int],
    radius_ms: int = AUDIO_SNAP_RADIUS_MS,
) -> int:
    """Snap a visual scene boundary to the nearest audio-safe point.

    Priority: silence gap midpoint > word boundary > original.
    Only snaps if a candidate exists within radius_ms.
    """
    best_ms = visual_ms
    best_dist = radius_ms + 1  # Start beyond radius so original wins if nothing found

    # Priority 1: Silence gap midpoints (safest — guaranteed no speech)
    for gap in silence_gaps:
        dist = abs(gap["mid_ms"] - visual_ms)
        if dist < best_dist:
            best_dist = dist
            best_ms = gap["mid_ms"]

    # Priority 2: Word boundaries (safe — speech pauses between words)
    # Only use if no silence gap was found within radius
    if best_dist > radius_ms:
        import bisect
        idx = bisect.bisect_left(word_boundaries, visual_ms)
        for candidate_idx in (idx - 1, idx):
            if 0 <= candidate_idx < len(word_boundaries):
                dist = abs(word_boundaries[candidate_idx] - visual_ms)
                if dist < best_dist:
                    best_dist = dist
                    best_ms = word_boundaries[candidate_idx]

    return best_ms


def _detect_scene_boundaries(
    frame_files: list[Path],
    fps: float,
    silence_gaps: list[dict[str, int]] | None = None,
    word_boundaries: list[int] | None = None,
) -> list[dict[str, object]]:
    """Detect scenes using SSIM, snapping boundaries to audio-safe points.

    No artificial max duration — scenes are as long as the visual
    content remains stable. When a visual change IS detected, the
    boundary is snapped to the nearest silence gap or word boundary
    to avoid cutting mid-speech.
    """
    scenes: list[dict[str, object]] = []
    scene_start = 0
    prev_data: np.ndarray | None = None

    for i, fp in enumerate(frame_files):
        data = cv2.imread(str(fp))
        if data is None:
            continue

        # Downsample for SSIM comparison
        small, _, _ = _downsample(data)

        is_scene_break = False
        if prev_data is not None:
            ssim = _compute_ssim(small, prev_data)
            if ssim < SCENE_THRESHOLD:
                is_scene_break = True

        if is_scene_break and i > scene_start:
            fn = _parse_frame_number(frame_files[scene_start])
            efn = _parse_frame_number(frame_files[i - 1])
            raw_end_ms = int((efn - 1) / fps * 1000)

            # Snap boundary to audio-safe point
            if silence_gaps or word_boundaries:
                raw_end_ms = _snap_boundary_to_audio(
                    raw_end_ms,
                    silence_gaps or [],
                    word_boundaries or [],
                )

            scenes.append({
                "start_frame": scene_start, "end_frame": i - 1,
                "start_ms": int((fn - 1) / fps * 1000),
                "end_ms": raw_end_ms,
                "mid_frame_idx": (scene_start + i - 1) // 2,
            })
            scene_start = i

        prev_data = small  # Store downsampled for next comparison

    total = len(frame_files)
    if scene_start < total:
        fn = _parse_frame_number(frame_files[scene_start])
        efn = _parse_frame_number(frame_files[-1])
        scenes.append({
            "start_frame": scene_start, "end_frame": total - 1,
            "start_ms": int((fn - 1) / fps * 1000),
            "end_ms": int((efn - 1) / fps * 1000),
            "mid_frame_idx": (scene_start + total - 1) // 2,
        })
    return scenes


def _store_scene_records(db_path: Path, records: list[dict[str, object]]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        for rec in records:
            face, webcam, content = rec["face"], rec["webcam"], rec["content"]
            conn.execute(_INSERT_SQL, (
                rec["project_id"], rec["start_ms"], rec["end_ms"],
                face["x"] if face else None, face["y"] if face else None,
                face["w"] if face else None, face["h"] if face else None,
                face["confidence"] if face else None,
                rec.get("face_size_pct", 0.0),
                webcam["x"] if webcam else None, webcam["y"] if webcam else None,
                webcam["w"] if webcam else None, webcam["h"] if webcam else None,
                content["x"], content["y"], content["w"], content["h"],
                rec.get("content_type", "unknown"), "[]",
                rec["layout"], json.dumps(rec["canvas"]), rec["transcript"],
            ))
        conn.commit()
    finally:
        conn.close()


async def run_scene_analysis(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Run scene analysis on all extracted frames.

    Performance-optimized: downsamples frames to 720p for analysis,
    reuses MediaPipe detector across all scenes, and only runs
    face detection on scene representative frames.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    start_time = time.monotonic()
    operation = "scene_analysis"

    try:
        frames_dir = project_dir / "frames"
        if not frames_dir.exists():
            raise FileNotFoundError(f"Frames directory not found: {frames_dir}")

        frame_files = sorted(frames_dir.glob("frame_*.jpg"))
        if not frame_files:
            raise ValueError("No frames found")

        fps = 2.0

        # Get source resolution from DB
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT resolution FROM project WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            raise ValueError(f"Project not found: {project_id}")

        res = str(row["resolution"]).split("x")
        frame_w, frame_h = int(res[0]), int(res[1])

        logger.info(
            "Scene analysis: %d frames, %dx%d source, downsampling to %dx%d",
            len(frame_files), frame_w, frame_h, ANALYSIS_W, ANALYSIS_H,
        )

        _ensure_scene_map_table(db_path)

        # Clear old data
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("DELETE FROM scene_map WHERE project_id = ?", (project_id,))
            conn.commit()
        finally:
            conn.close()

        transcript_segments = _get_transcript_segments(db_path, project_id)

        # Fetch audio intelligence for boundary snapping
        silence_gaps = _fetch_silence_gaps(db_path, project_id)
        word_boundaries = _fetch_word_boundaries(db_path, project_id)
        logger.info(
            "Scene analysis: loaded %d silence gaps, %d word boundaries for audio snapping",
            len(silence_gaps), len(word_boundaries),
        )

        # Phase 1: Scene boundary detection (SSIM + audio-aware snapping)
        scenes = _detect_scene_boundaries(
            frame_files, fps,
            silence_gaps=silence_gaps,
            word_boundaries=word_boundaries,
        )
        logger.info("Detected %d scenes from %d frames", len(scenes), len(frame_files))

        # Phase 2: Face detection (reuse detector, one call per scene)
        detector = None
        try:
            detector = _create_face_detector()
        except FileNotFoundError:
            logger.warning("BlazeFace model not found - skipping face detection")
        except Exception as exc:
            logger.warning("Face detector creation failed: %s", exc)

        webcam_detections: list[dict[str, int]] = []
        for scene in scenes:
            mid_idx = scene["mid_frame_idx"]
            mid_path = frame_files[mid_idx]

            face = None
            if detector is not None:
                try:
                    face = _detect_face_with_detector(
                        detector, mid_path, frame_w, frame_h,
                    )
                except Exception as exc:
                    logger.debug("Face detection failed for scene: %s", exc)

            scene["face"] = face
            if face is not None:
                webcam = _detect_webcam_region(face, frame_w, frame_h)
                webcam_detections.append(webcam)

        # Close detector
        if detector is not None:
            import contextlib
            with contextlib.suppress(Exception):
                detector.close()

        # Stable webcam region (median of detections)
        stable_webcam: dict[str, int] | None = None
        if webcam_detections:
            stable_webcam = {
                "x": int(np.median([w["x"] for w in webcam_detections])),
                "y": int(np.median([w["y"] for w in webcam_detections])),
                "w": int(np.median([w["w"] for w in webcam_detections])),
                "h": int(np.median([w["h"] for w in webcam_detections])),
            }

        # Phase 3: Content detection + canvas pre-computation
        scene_records: list[dict[str, object]] = []

        for scene in scenes:
            mid_idx = scene["mid_frame_idx"]
            start_idx = scene["start_frame"]

            mid_frame = cv2.imread(str(frame_files[mid_idx]))
            start_frame = cv2.imread(str(frame_files[start_idx]))

            content = _detect_content_region(
                mid_frame, start_frame, stable_webcam, frame_w, frame_h,
            )

            face = scene.get("face")
            canvas = _build_canvas_regions(
                face, stable_webcam, content, frame_w, frame_h,
            )

            # Classify content type from detected regions
            content_type = _classify_content_type(
                face, stable_webcam, content, frame_w, frame_h,
            )

            # Compute face size as percentage of frame
            face_size_pct = 0.0
            if face is not None:
                face_size_pct = round(
                    (int(face["w"]) * int(face["h"])) / (frame_w * frame_h) * 100, 2
                )

            # Layout recommendation
            layout = "A"
            if face is not None:
                layout = "A" if face_size_pct > 5 else "C"

            # Transcript alignment
            scene_text_parts: list[str] = []
            for seg in transcript_segments:
                if int(seg["end_ms"]) > scene["start_ms"] and int(seg["start_ms"]) < scene["end_ms"]:
                    scene_text_parts.append(str(seg["text"]))

            scene_records.append({
                "project_id": project_id,
                "start_ms": scene["start_ms"],
                "end_ms": scene["end_ms"],
                "face": face,
                "webcam": stable_webcam,
                "content": content,
                "content_type": content_type,
                "face_size_pct": face_size_pct,
                "layout": layout,
                "canvas": canvas,
                "transcript": " ".join(scene_text_parts),
            })

        _store_scene_records(db_path, scene_records)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        logger.info(
            "Scene analysis complete: %d scenes, webcam=%s, took %d ms",
            len(scene_records),
            "detected" if stable_webcam else "not found",
            elapsed_ms,
        )

        content_hash = sha256_string(
            f"scenes:{len(scene_records)},webcam:{stable_webcam is not None}",
        )

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=operation,
            stage="scene_detector",
            input_info=InputInfo(
                file_path=str(frames_dir),
                sha256=sha256_string(
                    "\n".join(f.name for f in frame_files),
                ),
            ),
            output_info=OutputInfo(
                sha256=content_hash,
                record_count=len(scene_records),
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Scene analysis detected {len(scene_records)} scenes, "
                f"webcam={'detected' if stable_webcam else 'not found'}"
            ),
        )

        return StageResult(
            success=True,
            operation=operation,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Scene analysis failed after %d ms: %s", elapsed_ms, error_msg)
        return StageResult(
            success=False,
            operation=operation,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
