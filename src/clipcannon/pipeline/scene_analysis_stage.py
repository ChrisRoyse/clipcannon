"""The run_scene_analysis stage entry point."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.scene_analysis_boundaries import (
    _detect_scene_boundaries,
    _ensure_scene_map_table,
    _fetch_silence_gaps,
    _fetch_word_boundaries,
    _get_transcript_segments,
    _store_scene_records,
)
from clipcannon.pipeline.scene_analysis_canvas import _build_canvas_regions, _classify_content_type
from clipcannon.pipeline.scene_analysis_vision import (
    ANALYSIS_H,
    ANALYSIS_W,
    _create_face_detector,
    _detect_content_region,
    _detect_face_with_detector,
    _detect_webcam_region,
)
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)


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
            raise RuntimeError(f"BlazeFace detector failed to initialise: {exc}") from exc

        webcam_detections: list[dict[str, int]] = []
        for scene in scenes:
            mid_idx = scene["mid_frame_idx"]
            mid_path = frame_files[mid_idx]

            face = None
            if detector is not None:
                # A detector error is not "no face" (#68): let it fail the stage.
                face = _detect_face_with_detector(
                    detector, mid_path, frame_w, frame_h,
                )

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
