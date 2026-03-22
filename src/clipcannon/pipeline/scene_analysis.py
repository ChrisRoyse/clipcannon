"""Scene analysis pipeline stage for automated video editing.

Analyzes every extracted frame to detect scene boundaries, face positions,
webcam overlay regions, and content areas. Pre-computes canvas regions for
all layout types so the AI never needs to manually measure coordinates.

Runs during ingest after frame_extract and transcribe stages.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

SCENE_THRESHOLD = 0.92  # SSIM threshold - sensitive to detect scrolling/navigation
MAX_SCENE_DURATION_MS = 8000  # Force scene break after 8 seconds
CHROME_TOP = 70  # Browser tab bar + bookmarks exclusion
CHROME_BOTTOM = 50  # OS taskbar exclusion
CANVAS_W, CANVAS_H = 1080, 1920  # 9:16 vertical output
LAYOUT_HEIGHTS = {"A": (576, 1344), "B": (768, 1152)}  # speaker, screen
PIP_SIZE, PIP_POS = 240, (24, 140)
EYE_LINE_PCT = 0.38  # Eye line position within face bbox

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scene_map (
    scene_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL, start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    face_x INTEGER, face_y INTEGER, face_w INTEGER, face_h INTEGER,
    face_confidence REAL,
    webcam_x INTEGER, webcam_y INTEGER, webcam_w INTEGER, webcam_h INTEGER,
    content_x INTEGER, content_y INTEGER, content_w INTEGER, content_h INTEGER,
    content_type TEXT DEFAULT 'unknown', visible_text TEXT DEFAULT '[]',
    layout_recommendation TEXT DEFAULT 'A',
    canvas_regions_json TEXT DEFAULT '{}', transcript_text TEXT DEFAULT '',
    FOREIGN KEY (project_id) REFERENCES project(project_id)
)"""

_INSERT_SQL = """INSERT INTO scene_map (
    project_id, start_ms, end_ms,
    face_x, face_y, face_w, face_h, face_confidence,
    webcam_x, webcam_y, webcam_w, webcam_h,
    content_x, content_y, content_w, content_h,
    content_type, visible_text,
    layout_recommendation, canvas_regions_json, transcript_text
) VALUES (?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?, ?,?,?)"""


def _compute_ssim(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    """Fast SSIM-like comparison via normalized cross-correlation (0.0-1.0)."""
    gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY)
    small_a = cv2.resize(gray_a, (320, 180))
    small_b = cv2.resize(gray_b, (320, 180))
    result = cv2.matchTemplate(small_a, small_b, cv2.TM_CCORR_NORMED)
    return float(result[0][0])


def _detect_face_mediapipe(frame_path: Path) -> dict[str, object] | None:
    """Detect the primary face using MediaPipe. Returns x/y/w/h/confidence."""
    from clipcannon.editing.smart_crop import detect_faces
    faces = detect_faces(frame_path)
    if not faces:
        return None
    f = faces[0]
    return {"x": f.x, "y": f.y, "w": f.width, "h": f.height,
            "confidence": round(f.confidence, 3)}


def _detect_webcam_region(
    face: dict[str, object], frame_w: int, frame_h: int,
) -> dict[str, int]:
    """Expand face bbox to webcam overlay (face + shoulders + mic)."""
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
    """Detect main content region using frame differencing."""
    cx, cy = 0, CHROME_TOP
    cw = frame_w
    ch = frame_h - CHROME_TOP - CHROME_BOTTOM

    if webcam is not None:
        if webcam["x"] > frame_w // 2:
            cw = min(cw, webcam["x"] - 40)
        else:
            cx = webcam["x"] + webcam["w"] + 40
            cw = frame_w - cx

    if frame_prev is not None:
        gray_c = cv2.cvtColor(frame_curr, cv2.COLOR_BGR2GRAY)
        gray_p = cv2.cvtColor(frame_prev, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray_c, gray_p)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        if webcam is not None:
            wx, wy = webcam["x"], webcam["y"]
            thresh[wy:wy + webcam["h"], wx:wx + webcam["w"]] = 0
        thresh[:CHROME_TOP, :] = 0
        thresh[frame_h - CHROME_BOTTOM:, :] = 0
        # Also mask out a wider area around the webcam to prevent
        # face movement from bleeding into the content bounding box
        if webcam is not None:
            margin = 60
            wx2 = max(0, webcam["x"] - margin)
            wy2 = max(0, webcam["y"] - margin)
            ww2 = min(frame_w - wx2, webcam["w"] + margin * 2)
            wh2 = min(frame_h - wy2, webcam["h"] + margin * 2)
            thresh[wy2:wy2 + wh2, wx2:wx2 + ww2] = 0

        coords = cv2.findNonZero(thresh)
        if coords is not None and len(coords) > 100:
            bx, by, bw, bh = cv2.boundingRect(coords)
            if bw > frame_w * 0.1 and bh > frame_h * 0.1:
                cx, cy = bx, max(by, CHROME_TOP)
                cw, ch = bw, min(bh, frame_h - CHROME_BOTTOM - cy)

    # CRITICAL: Clamp content width to not overlap webcam region
    if webcam is not None:
        wcam_right = webcam["x"] > frame_w // 2
        if wcam_right:
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
    crop_w = min(crop_w, frame_w)
    crop_h = min(crop_h, frame_h)
    return {"x": crop_x, "y": crop_y, "w": crop_w, "h": crop_h}


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


def _pick_screen_fit_mode(
    content_w: int, content_h: int,
    output_w: int, output_h: int,
) -> str:
    """Choose fit_mode for screen content based on aspect ratio.

    Wide horizontal content (dashboards, file lists) uses 'contain'
    to show everything readable with letterboxing. Vertical or
    square content (documents, code panels) uses 'cover' to fill.

    Args:
        content_w: Source content width.
        content_h: Source content height.
        output_w: Output region width.
        output_h: Output region height.

    Returns:
        'contain' for wide content, 'cover' for vertical/square.
    """
    content_aspect = content_w / max(content_h, 1)
    output_aspect = output_w / max(output_h, 1)

    # If the content is significantly wider than the output region,
    # use contain to avoid cropping important horizontal content
    if content_aspect > output_aspect * 1.3:
        return "contain"
    return "cover"


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

    # Layouts A and B: speaker + screen split
    for name, (spk_h, scr_h) in LAYOUT_HEIGHTS.items():
        sc = _compute_speaker_crop(face, CANVAS_W, spk_h, frame_w, frame_h)
        fm = _pick_screen_fit_mode(cw, ch, CANVAS_W, scr_h)
        result[name] = [
            _region("speaker", sc["x"], sc["y"], sc["w"], sc["h"],
                    0, 0, CANVAS_W, spk_h, 2),
            _region("screen", cx, cy, cw, ch,
                    0, spk_h, CANVAS_W, scr_h, 1, fm),
        ]

    # Layout C: PIP
    pc = _compute_speaker_crop(face, PIP_SIZE, PIP_SIZE, frame_w, frame_h)
    fm = _pick_screen_fit_mode(cw, ch, CANVAS_W, CANVAS_H)
    result["C"] = [
        _region("screen", cx, cy, cw, ch,
                0, 0, CANVAS_W, CANVAS_H, 1, fm),
        _region("pip_speaker", pc["x"], pc["y"], pc["w"], pc["h"],
                PIP_POS[0], PIP_POS[1], PIP_SIZE, PIP_SIZE, 2),
    ]

    # Layout D: full-screen face
    dc = _compute_speaker_crop(face, CANVAS_W, CANVAS_H, frame_w, frame_h)
    result["D"] = [
        _region("speaker_full", dc["x"], dc["y"], dc["w"], dc["h"],
                0, 0, CANVAS_W, CANVAS_H, 1),
    ]
    return result


def _ensure_scene_map_table(db_path: str) -> None:
    """Create scene_map table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scene_map_project "
            "ON scene_map(project_id, start_ms)")
        conn.commit()
    finally:
        conn.close()


def _parse_frame_number(frame_path: Path) -> int:
    """Extract numeric frame number from filename like frame_00042.jpg."""
    return int(frame_path.stem.split("_")[1])


def _get_transcript_segments(
    db_path: str, project_id: str,
) -> list[dict[str, object]]:
    """Load transcript segments for alignment with scenes."""
    segments: list[dict[str, object]] = []
    conn = sqlite3.connect(db_path)
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
        pass  # No transcript table yet
    finally:
        conn.close()
    return segments


def _detect_scene_boundaries(
    frame_files: list[Path], fps: float,
) -> list[dict[str, object]]:
    """Detect scene boundaries using SSIM on sequential frames."""
    scenes: list[dict[str, object]] = []
    scene_start = 0
    prev_data: np.ndarray | None = None
    total = len(frame_files)

    for i, fp in enumerate(frame_files):
        data = cv2.imread(str(fp))
        if data is None:
            continue
        # Check for scene boundary: SSIM change OR max duration exceeded
        is_scene_break = False
        if prev_data is not None:
            ssim = _compute_ssim(data, prev_data)
            if ssim < SCENE_THRESHOLD:
                is_scene_break = True

        # Force scene break if current scene exceeds max duration
        current_frame_num = _parse_frame_number(fp)
        start_frame_num = _parse_frame_number(frame_files[scene_start])
        current_ms = int((current_frame_num - 1) / fps * 1000)
        start_ms = int((start_frame_num - 1) / fps * 1000)
        if current_ms - start_ms > MAX_SCENE_DURATION_MS:
            is_scene_break = True

        if is_scene_break and i > scene_start:
            fn = _parse_frame_number(frame_files[scene_start])
            efn = _parse_frame_number(frame_files[i - 1])
            scenes.append({
                "start_frame": scene_start, "end_frame": i - 1,
                "start_ms": int((fn - 1) / fps * 1000),
                "end_ms": int((efn - 1) / fps * 1000),
                "mid_frame_path": frame_files[(scene_start + i - 1) // 2],
            })
            scene_start = i
        prev_data = data

    if scene_start < total:
        fn = _parse_frame_number(frame_files[scene_start])
        efn = _parse_frame_number(frame_files[-1])
        scenes.append({
            "start_frame": scene_start, "end_frame": total - 1,
            "start_ms": int((fn - 1) / fps * 1000),
            "end_ms": int((efn - 1) / fps * 1000),
            "mid_frame_path": frame_files[(scene_start + total - 1) // 2],
        })
    return scenes


def _store_scene_records(
    db_path: str, records: list[dict[str, object]],
) -> None:
    """Insert scene records into the scene_map table."""
    conn = sqlite3.connect(db_path)
    try:
        for rec in records:
            face, webcam, content = rec["face"], rec["webcam"], rec["content"]
            conn.execute(_INSERT_SQL, (
                rec["project_id"], rec["start_ms"], rec["end_ms"],
                face["x"] if face else None, face["y"] if face else None,
                face["w"] if face else None, face["h"] if face else None,
                face["confidence"] if face else None,
                webcam["x"] if webcam else None, webcam["y"] if webcam else None,
                webcam["w"] if webcam else None, webcam["h"] if webcam else None,
                content["x"], content["y"], content["w"], content["h"],
                "unknown", "[]",
                rec["layout"], json.dumps(rec["canvas"]), rec["transcript"],
            ))
        conn.commit()
    finally:
        conn.close()


async def run_scene_analysis(
    project_id: str, db_path: str, project_dir: str,
    config: object, **kwargs: object,
) -> dict[str, object]:
    """Run scene analysis on all extracted frames.

    Detects scene boundaries, faces, webcam regions, content areas,
    and pre-computes canvas regions for all layout types.

    Args:
        project_id: Project identifier.
        db_path: Path to project analysis.db.
        project_dir: Path to project directory.
        config: ClipCannon config.

    Returns:
        Dict with stage results including scene count and webcam info.
    """
    frames_dir = Path(project_dir) / "frames"
    if not frames_dir.exists():
        raise FileNotFoundError(f"Frames directory not found: {frames_dir}")

    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_files:
        raise ValueError("No frames found")

    fps = 2.0
    # Get source resolution
    conn = sqlite3.connect(db_path)
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
    logger.info("Scene analysis: %d frames, %dx%d, %.1f fps",
                len(frame_files), frame_w, frame_h, fps)

    _ensure_scene_map_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM scene_map WHERE project_id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()

    transcript_segments = _get_transcript_segments(db_path, project_id)

    # Phase 1: scene boundaries
    scenes = _detect_scene_boundaries(frame_files, fps)
    logger.info("Detected %d scenes", len(scenes))

    # Phase 2: face + webcam detection per scene
    webcam_detections: list[dict[str, int]] = []
    for scene in scenes:
        face = _detect_face_mediapipe(scene["mid_frame_path"])
        scene["face"] = face
        if face is not None:
            webcam_detections.append(
                _detect_webcam_region(face, frame_w, frame_h))

    stable_webcam: dict[str, int] | None = None
    if webcam_detections:
        stable_webcam = {
            k: int(np.median([w[k] for w in webcam_detections]))
            for k in ("x", "y", "w", "h")
        }

    # Phase 3: content regions + canvas + layout
    records: list[dict[str, object]] = []
    for scene in scenes:
        mid_idx = (scene["start_frame"] + scene["end_frame"]) // 2
        mid_frame = cv2.imread(str(frame_files[mid_idx]))
        start_frame = cv2.imread(str(frame_files[scene["start_frame"]]))
        content = _detect_content_region(
            mid_frame, start_frame, stable_webcam, frame_w, frame_h)
        face = scene.get("face")
        canvas = _build_canvas_regions(
            face, stable_webcam, content, frame_w, frame_h)

        if face is not None:
            pct = int(face["w"]) * int(face["h"]) / (frame_w * frame_h) * 100
            layout = "A" if pct > 5 else "C"
        else:
            layout = "A"

        parts = [str(s["text"]) for s in transcript_segments
                 if s["end_ms"] > scene["start_ms"]
                 and s["start_ms"] < scene["end_ms"]]
        records.append({
            "project_id": project_id,
            "start_ms": scene["start_ms"], "end_ms": scene["end_ms"],
            "face": face, "webcam": stable_webcam, "content": content,
            "layout": layout, "canvas": canvas,
            "transcript": " ".join(parts),
        })

    _store_scene_records(db_path, records)
    logger.info("Scene analysis complete: %d scenes stored", len(records))
    return {
        "scenes_detected": len(records),
        "webcam_detected": stable_webcam is not None,
        "webcam_region": stable_webcam,
    }
