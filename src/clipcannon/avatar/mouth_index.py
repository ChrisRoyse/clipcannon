"""Mouth frame extraction and indexing for MouthMemory.

Extracts face frames at 25fps from a video, detects landmarks,
labels each frame with its viseme (from transcript word timing),
and stores everything in the mouth_frames table.

Works on any ingested video -- uses transcript_words for timing
and scene_map for face region.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mouth_frames (
    frame_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    face_crop_path TEXT,
    mouth_crop_path TEXT,
    landmarks_json TEXT,
    head_yaw REAL DEFAULT 0,
    head_pitch REAL DEFAULT 0,
    head_roll REAL DEFAULT 0,
    viseme TEXT DEFAULT 'SIL',
    phoneme TEXT DEFAULT 'SIL',
    word TEXT DEFAULT '',
    word_position TEXT DEFAULT '',
    prev_viseme TEXT DEFAULT 'SIL',
    next_viseme TEXT DEFAULT 'SIL',
    mouth_openness REAL DEFAULT 0,
    mouth_width REAL DEFAULT 0.5,
    energy REAL DEFAULT 0,
    f0 REAL DEFAULT 0,
    emotion_label TEXT DEFAULT 'neutral',
    speaker_id INTEGER,
    quality_score REAL DEFAULT 0.5,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
)"""

_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_mouth_viseme
    ON mouth_frames(project_id, viseme, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_mouth_time
    ON mouth_frames(project_id, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_mouth_speaker
    ON mouth_frames(project_id, speaker_id, viseme);
"""

_INSERT_SQL = """INSERT INTO mouth_frames (
    project_id, timestamp_ms, face_crop_path, mouth_crop_path,
    landmarks_json, head_yaw, head_pitch, head_roll,
    viseme, phoneme, word, word_position, prev_viseme, next_viseme,
    mouth_openness, mouth_width, energy, f0, emotion_label,
    speaker_id, quality_score
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""

_face_analyzer: object | None = None


def _ensure_face_analyzer() -> object:
    """Lazy-load InsightFace for landmark detection."""
    global _face_analyzer
    if _face_analyzer is not None:
        return _face_analyzer

    from insightface.app import FaceAnalysis

    # Try multiple model root paths
    model_roots = [
        Path.home() / ".clipcannon" / "models" / "latentsync" / "checkpoints" / "auxiliary",
        Path.home() / ".clipcannon" / "models",
        Path.home() / ".insightface",
    ]
    root = str(model_roots[0])
    for p in model_roots:
        if (p / "models" / "buffalo_l").exists():
            root = str(p)
            break

    app = FaceAnalysis(
        name="buffalo_l", root=root,
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(512, 512))
    _face_analyzer = app
    logger.info("InsightFace loaded for mouth indexing")
    return app


def _compute_head_pose(landmarks_106: np.ndarray) -> tuple[float, float, float]:
    """Estimate head pose from 106-point landmarks.

    Simple approximation using eye and nose positions.
    Returns (yaw, pitch, roll) in degrees.
    """
    # Left eye center (points 33-42), right eye center (points 87-96)
    left_eye = landmarks_106[33:43].mean(axis=0)
    right_eye = landmarks_106[87:97].mean(axis=0)
    nose_tip = landmarks_106[86]

    # Yaw: horizontal offset of nose from eye center midpoint
    eye_center = (left_eye + right_eye) / 2
    eye_dist = np.linalg.norm(right_eye - left_eye)
    if eye_dist < 1:
        return (0.0, 0.0, 0.0)

    yaw = float(np.degrees(np.arctan2(
        nose_tip[0] - eye_center[0], eye_dist,
    )))

    # Pitch: vertical offset of nose from eye line
    pitch = float(np.degrees(np.arctan2(
        nose_tip[1] - eye_center[1], eye_dist,
    )))

    # Roll: angle of eye line
    dy = right_eye[1] - left_eye[1]
    dx = right_eye[0] - left_eye[0]
    roll = float(np.degrees(np.arctan2(dy, dx)))

    return (round(yaw, 1), round(pitch, 1), round(roll, 1))


def _compute_mouth_geometry(
    lip_landmarks: np.ndarray,
) -> tuple[float, float]:
    """Compute mouth openness and width from lip landmarks.

    Args:
        lip_landmarks: 20x2 array (InsightFace points 52-71).

    Returns:
        (openness, width) both normalized 0-1.
    """
    if len(lip_landmarks) < 14:
        return (0.0, 0.5)

    # Outer lip: top center ~ point 3, bottom center ~ point 9
    top = lip_landmarks[3]
    bottom = lip_landmarks[9]
    left = lip_landmarks[0]
    right = lip_landmarks[6]

    vertical = float(np.linalg.norm(bottom - top))
    horizontal = float(np.linalg.norm(right - left))

    if horizontal < 1:
        return (0.0, 0.5)

    # Normalize openness by mouth width (aspect ratio)
    openness = min(1.0, vertical / horizontal)
    # Normalize width relative to typical range
    width = min(1.0, horizontal / 80.0)  # 80px is typical mouth width at 512px face

    return (round(openness, 3), round(width, 3))


def _get_energy_at_time(
    audio: np.ndarray | None, sr: int, timestamp_ms: int,
    window_ms: int = 40,
) -> float:
    """Get RMS energy at a specific timestamp."""
    if audio is None:
        return 0.0
    start = int(timestamp_ms / 1000 * sr)
    end = int((timestamp_ms + window_ms) / 1000 * sr)
    start = max(0, min(start, len(audio)))
    end = max(start, min(end, len(audio)))
    if end <= start:
        return 0.0
    segment = audio[start:end]
    return float(np.sqrt(np.mean(segment ** 2)))


def ensure_mouth_tables(db_path: Path) -> None:
    """Create mouth_frames table if it doesn't exist."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.executescript(_INDEXES_SQL)
        conn.commit()
    finally:
        conn.close()


async def index_mouth_frames(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    video_path: Path | None = None,
    fps: int = 25,
) -> dict[str, object]:
    """Extract and index mouth frames from a video.

    Extracts frames at target fps, runs InsightFace on each,
    labels with viseme from transcript timing, stores in mouth_frames.

    Args:
        project_id: Project identifier.
        db_path: Path to analysis.db.
        project_dir: Project directory.
        video_path: Source video. If None, auto-discovers from project.
        fps: Extraction frame rate (default 25).

    Returns:
        Summary dict with counts.
    """
    start_time = time.monotonic()

    # Resolve video path
    if video_path is None:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT source_cfr_path, source_path FROM project WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return {"error": "Project not found in database"}
        video_path = Path(str(row["source_cfr_path"] or row["source_path"]))

    if not video_path.exists():
        return {"error": f"Video not found: {video_path}"}

    # Load transcript words for viseme labeling
    from clipcannon.avatar.viseme_map import build_viseme_timeline

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        word_rows = conn.execute(
            "SELECT w.word, w.start_ms, w.end_ms "
            "FROM transcript_words w "
            "JOIN transcript_segments s ON w.segment_id = s.segment_id "
            "WHERE s.project_id = ? ORDER BY w.start_ms",
            (project_id,),
        ).fetchall()
    finally:
        conn.close()

    words = [{"word": str(r["word"]), "start_ms": int(r["start_ms"]),
              "end_ms": int(r["end_ms"])} for r in word_rows]
    viseme_timeline = build_viseme_timeline(words, fps=fps)
    viseme_by_frame: dict[int, dict[str, object]] = {
        int(v["frame_idx"]): v for v in viseme_timeline
    }

    # Try loading vocal audio for energy
    audio = None
    sr = 24000
    vocals_path = project_dir / "stems" / "vocals.wav"
    if not vocals_path.exists():
        vocals_path = project_dir / "stems" / "audio_16k.wav"
        sr = 16000
    if vocals_path.exists():
        try:
            from scipy.io import wavfile
            sr_loaded, data = wavfile.read(str(vocals_path))
            sr = sr_loaded
            if data.dtype == np.int16:
                audio = data.astype(np.float64) / 32768.0
            else:
                audio = data.astype(np.float64)
            if audio.ndim == 2:
                audio = audio.mean(axis=1)
        except Exception as exc:
            logger.debug("Could not load audio for energy: %s", exc)

    # Extract frames using FFmpeg
    mouth_dir = project_dir / "mouth_frames"
    mouth_dir.mkdir(parents=True, exist_ok=True)

    frames_dir = mouth_dir / "raw"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-nostdin",
        "-i", str(video_path),
        "-vf", f"fps={fps}",
        "-q:v", "2",
        str(frames_dir / "frame_%06d.jpg"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": f"FFmpeg frame extraction failed: {proc.stderr[:300]}"}

    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_files:
        return {"error": "No frames extracted"}

    logger.info("Mouth indexing: %d frames extracted at %dfps", len(frame_files), fps)

    # Initialize face analyzer
    app = _ensure_face_analyzer()

    # Ensure table exists
    ensure_mouth_tables(db_path)

    # Clear old data for this project
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM mouth_frames WHERE project_id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()

    # Process frames
    frame_ms = 1000.0 / fps
    records: list[tuple] = []
    faces_dir = mouth_dir / "faces"
    mouths_dir = mouth_dir / "mouths"
    faces_dir.mkdir(parents=True, exist_ok=True)
    mouths_dir.mkdir(parents=True, exist_ok=True)

    for i, frame_path in enumerate(frame_files):
        timestamp_ms = int(i * frame_ms)

        frame = cv2.imread(str(frame_path))
        if frame is None:
            continue

        # Face detection
        faces = app.get(frame)
        if not faces:
            continue

        face = faces[0]
        if not hasattr(face, "landmark_2d_106") or face.landmark_2d_106 is None:
            continue

        landmarks_106 = face.landmark_2d_106
        confidence = float(face.det_score) if hasattr(face, "det_score") else 0.5

        if confidence < 0.3:
            continue

        # Head pose
        yaw, pitch, roll = _compute_head_pose(landmarks_106)

        # Lip landmarks (points 52-71)
        lip_lm = landmarks_106[52:72]
        openness, width = _compute_mouth_geometry(lip_lm)

        h, w_frame = frame.shape[:2]

        # Store raw frame path (for full-face warping in compositing)
        face_path = frame_path  # raw extracted frame at full resolution

        # Save mouth crop (for debugging/preview only)
        lip_min = lip_lm.min(axis=0).astype(int)
        lip_max = lip_lm.max(axis=0).astype(int)
        m_pad = 30
        mx1 = max(0, lip_min[0] - m_pad)
        my1 = max(0, lip_min[1] - m_pad)
        mx2 = min(w_frame, lip_max[0] + m_pad)
        my2 = min(h, lip_max[1] + m_pad)
        mouth_crop = frame[my1:my2, mx1:mx2]
        mouth_path = mouths_dir / f"mouth_{i:06d}.jpg"
        if mouth_crop.size > 0:
            cv2.imwrite(str(mouth_path), mouth_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        else:
            mouth_path = frame_path

        # Viseme from timeline
        vis_data = viseme_by_frame.get(i, {})
        viseme = str(vis_data.get("viseme", "SIL"))
        phoneme = str(vis_data.get("phoneme", "SIL"))
        word = str(vis_data.get("word", ""))
        word_pos = str(vis_data.get("word_position", ""))
        prev_vis = str(vis_data.get("prev_viseme", "SIL"))
        next_vis = str(vis_data.get("next_viseme", "SIL"))

        # Energy
        energy = _get_energy_at_time(audio, sr, timestamp_ms)

        # Blur-based quality (use mouth region for sharpness check)
        gray = cv2.cvtColor(mouth_crop, cv2.COLOR_BGR2GRAY) if mouth_crop.size > 0 else np.zeros((10, 10))
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        blur_score = min(1.0, lap_var / 500.0)
        quality = round(confidence * blur_score, 3)

        # Store full 106-point landmarks (for face-to-face warping)
        records.append((
            project_id, timestamp_ms, str(face_path), str(mouth_path),
            json.dumps(landmarks_106.tolist()),
            yaw, pitch, roll,
            viseme, phoneme, word, word_pos, prev_vis, next_vis,
            openness, width, round(energy, 6), 0.0, "neutral",
            None, quality,
        ))

        if (i + 1) % 200 == 0:
            logger.info("Mouth indexing: %d/%d frames processed", i + 1, len(frame_files))

    # Batch insert
    if records:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executemany(_INSERT_SQL, records)
            conn.commit()
        finally:
            conn.close()

    elapsed_s = time.monotonic() - start_time

    # Compute viseme coverage
    viseme_counts: dict[str, int] = {}
    for r in records:
        v = r[8]  # viseme field
        viseme_counts[v] = viseme_counts.get(v, 0) + 1

    logger.info(
        "Mouth indexing complete: %d frames indexed from %d extracted, %.1fs",
        len(records), len(frame_files), elapsed_s,
    )

    return {
        "project_id": project_id,
        "frames_extracted": len(frame_files),
        "frames_indexed": len(records),
        "fps": fps,
        "elapsed_s": round(elapsed_s, 2),
        "viseme_coverage": viseme_counts,
    }
