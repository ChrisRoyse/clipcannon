"""Frame extraction pipeline stage for ClipCannon.

Extracts frames at 2fps from the source video using ffmpeg.
Attempts GPU-accelerated decoding (NVDEC) first, falls back
to software decoding.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_one
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.source_resolution import resolve_source_path
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
    sha256_string,
)

logger = logging.getLogger(__name__)

OPERATION = "frame_extract"
STAGE = "ffmpeg_frames"


def _build_frame_manifest(frames_dir: Path) -> str:
    """Build a sorted manifest of frame files for hashing.

    Args:
        frames_dir: Directory containing extracted frames.

    Returns:
        Newline-separated string of "filename:size" entries.
    """
    entries: list[str] = []
    for frame_file in sorted(frames_dir.glob("frame_*.jpg")):
        entries.append(f"{frame_file.name}:{frame_file.stat().st_size}")
    return "\n".join(entries)


async def _run_ffmpeg_frames_gpu(
    source_path: Path,
    frames_dir: Path,
    fps: int,
) -> tuple[bool, str]:
    """Extract frames with GPU-accelerated decoding.

    Args:
        source_path: Path to the source video.
        frames_dir: Output directory for frames.
        fps: Frames per second to extract.

    Returns:
        Tuple of (success, stderr_output).
    """
    cmd = [
        "ffmpeg", "-y",
        "-hwaccel", "cuda",
        "-i", str(source_path),
        "-vf", f"fps={fps}",
        "-q:v", "2",
        str(frames_dir / "frame_%06d.jpg"),
    ]
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    return proc.returncode == 0, proc.stderr


async def _run_ffmpeg_frames_sw(
    source_path: Path,
    frames_dir: Path,
    fps: int,
) -> tuple[bool, str]:
    """Extract frames with software decoding only.

    Args:
        source_path: Path to the source video.
        frames_dir: Output directory for frames.
        fps: Frames per second to extract.

    Returns:
        Tuple of (success, stderr_output).
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source_path),
        "-vf", f"fps={fps}",
        "-q:v", "2",
        str(frames_dir / "frame_%06d.jpg"),
    ]
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    return proc.returncode == 0, proc.stderr


async def run_frame_extract(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the frame extraction pipeline stage.

    Extracts frames at the configured fps (default 2fps) from the
    source video. Attempts GPU-accelerated decoding first.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    try:
        # Resolve source file
        source_path = await resolve_source_path(project_id, db_path)

        # Get duration for frame count validation
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT duration_ms FROM project WHERE project_id = ?",
                (project_id,),
            )
        finally:
            conn.close()

        if row is None:
            raise PipelineError(
                f"Project {project_id} not found in database",
                stage_name=STAGE,
                operation=OPERATION,
            )

        duration_ms = int(row.get("duration_ms", 0))
        extraction_fps = int(config.get("processing.frame_extraction_fps"))

        frames_dir = project_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        # Clear any existing frames
        for old_frame in frames_dir.glob("frame_*.jpg"):
            old_frame.unlink()

        # Try GPU-accelerated extraction first
        use_nvenc = bool(config.get("rendering.use_nvenc"))
        success = False
        stderr = ""

        if use_nvenc:
            logger.info("Attempting GPU-accelerated frame extraction at %dfps", extraction_fps)
            success, stderr = await _run_ffmpeg_frames_gpu(
                source_path, frames_dir, extraction_fps,
            )
            if not success:
                logger.warning(
                    "GPU frame extraction failed, falling back to software: %s",
                    stderr[-200:] if stderr else "",
                )

        if not success:
            logger.info("Running software frame extraction at %dfps", extraction_fps)
            success, stderr = await _run_ffmpeg_frames_sw(
                source_path, frames_dir, extraction_fps,
            )

        if not success:
            raise PipelineError(
                f"Frame extraction failed: {stderr[-300:] if stderr else 'unknown'}",
                stage_name=STAGE,
                operation=OPERATION,
            )

        # Count extracted frames
        frame_files = sorted(frames_dir.glob("frame_*.jpg"))
        frame_count = len(frame_files)

        if frame_count == 0:
            raise PipelineError(
                "Frame extraction produced no frames",
                stage_name=STAGE,
                operation=OPERATION,
            )

        # Validate frame count (expected = duration_s * fps, +/-5 tolerance)
        duration_s = duration_ms / 1000.0
        expected_count = int(duration_s * extraction_fps)
        tolerance = 5
        if abs(frame_count - expected_count) > tolerance:
            logger.warning(
                "Frame count mismatch: expected ~%d, got %d (tolerance=%d)",
                expected_count,
                frame_count,
                tolerance,
            )
        else:
            logger.info(
                "Frame count validated: %d frames (expected ~%d)",
                frame_count,
                expected_count,
            )

        # Build manifest and compute hash
        manifest = _build_frame_manifest(frames_dir)
        manifest_hash = sha256_string(manifest)

        # Total size of all frames
        total_size = sum(f.stat().st_size for f in frame_files)

        source_sha256 = await asyncio.to_thread(sha256_file, source_path)

        # Write provenance record
        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(source_path),
                sha256=source_sha256,
                size_bytes=source_path.stat().st_size,
            ),
            output_info=OutputInfo(
                file_path=str(frames_dir),
                sha256=manifest_hash,
                size_bytes=total_size,
                record_count=frame_count,
            ),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id="prov_001",
            description=f"Extracted {frame_count} frames at {extraction_fps}fps ({total_size} bytes)",
        )

        logger.info(
            "Frame extraction complete: %d frames, %d bytes total",
            frame_count,
            total_size,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            provenance_record_id=record_id,
        )

    except PipelineError:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Frame extraction failed: %s", error_msg)
        raise PipelineError(
            f"Frame extraction failed: {error_msg}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
