"""Scene boundary detection, audio snapping and scene_map storage."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import cv2

from clipcannon.pipeline.scene_analysis_vision import _compute_ssim, _downsample

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np

# Scene detection parameters
SCENE_THRESHOLD = 0.92

# Audio-aware boundary snapping: when a visual scene boundary falls
# during speech, snap it to the nearest silence gap or word boundary
# within this search radius (ms).
AUDIO_SNAP_RADIUS_MS = 2000

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
