"""VFR-to-CFR normalization pipeline stage for ClipCannon.

Detects if the source video has variable frame rate and converts
it to constant frame rate using ffmpeg. Selects the nearest standard
frame rate and attempts GPU-accelerated encoding first.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
)

logger = logging.getLogger(__name__)

OPERATION = "vfr_normalize"
STAGE = "ffmpeg_cfr"

# Standard frame rates to snap to
STANDARD_FRAME_RATES: list[float] = [
    23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0,
]


def _select_nearest_frame_rate(source_fps: float) -> float:
    """Select the nearest standard frame rate to the source.

    Args:
        source_fps: Detected source frame rate.

    Returns:
        Nearest standard frame rate value.
    """
    return min(STANDARD_FRAME_RATES, key=lambda r: abs(r - source_fps))


async def _run_ffmpeg_normalize(
    source_path: Path,
    output_path: Path,
    target_fps: float,
    try_nvenc: bool,
) -> tuple[bool, str]:
    """Run ffmpeg to normalize VFR to CFR.

    Attempts GPU-accelerated encoding first, falls back to libx264.

    Args:
        source_path: Path to the VFR source video.
        output_path: Path for the CFR output.
        target_fps: Target constant frame rate.
        try_nvenc: Whether to attempt NVENC first.

    Returns:
        Tuple of (success, stderr_output).
    """
    fps_str = f"{target_fps:.3f}" if target_fps != int(target_fps) else str(int(target_fps))

    if try_nvenc:
        cmd_nvenc = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-i", str(source_path),
            "-vf", f"fps={fps_str}",
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-cq", "18",
            "-c:a", "copy",
            str(output_path),
        ]
        logger.info("Attempting VFR normalization with NVENC: fps=%s", fps_str)
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd_nvenc,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if proc.returncode == 0:
            return True, proc.stderr

        logger.warning(
            "NVENC failed (code %d), falling back to libx264: %s",
            proc.returncode,
            proc.stderr[-200:] if proc.stderr else "",
        )

    cmd_sw = [
        "ffmpeg", "-y",
        "-i", str(source_path),
        "-vf", f"fps={fps_str}",
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "medium",
        "-c:a", "copy",
        str(output_path),
    ]
    logger.info("Running VFR normalization with libx264: fps=%s", fps_str)
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd_sw,
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    if proc.returncode != 0:
        return False, proc.stderr

    return True, proc.stderr


async def run_vfr_normalize(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the VFR normalization pipeline stage.

    If the source is already CFR (vfr_detected=False), this stage
    is a no-op and returns success immediately.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT source_path, vfr_detected, fps, source_sha256 "
                "FROM project WHERE project_id = ?",
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

        vfr_detected = bool(row.get("vfr_detected", False))

        if not vfr_detected:
            logger.info("Source is CFR, skipping VFR normalization for %s", project_id)
            return StageResult(
                success=True,
                operation=OPERATION,
            )

        source_path = Path(str(row["source_path"]))
        source_fps = float(row.get("fps", 30.0))
        source_sha256 = str(row.get("source_sha256", ""))

        # Select target frame rate
        target_fps = _select_nearest_frame_rate(source_fps)
        logger.info(
            "VFR normalization: %s fps -> %s fps",
            source_fps,
            target_fps,
        )

        # Output path
        output_path = project_dir / "source" / "source_cfr.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Run ffmpeg
        use_nvenc = bool(config.get("rendering.use_nvenc"))
        success, stderr = await _run_ffmpeg_normalize(
            source_path, output_path, target_fps, try_nvenc=use_nvenc,
        )

        if not success:
            raise PipelineError(
                f"VFR normalization failed: {stderr[-300:] if stderr else 'unknown error'}",
                stage_name=STAGE,
                operation=OPERATION,
            )

        if not output_path.exists():
            raise PipelineError(
                f"VFR normalization output missing: {output_path}",
                stage_name=STAGE,
                operation=OPERATION,
            )

        # Compute output hash
        output_sha256 = await asyncio.to_thread(sha256_file, output_path)
        output_size = output_path.stat().st_size

        # Update project table
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            execute(
                conn,
                """UPDATE project SET
                    source_cfr_path = ?,
                    vfr_normalized = 1,
                    fps = ?,
                    updated_at = datetime('now')
                WHERE project_id = ?""",
                (str(output_path), target_fps, project_id),
            )
            conn.commit()
        finally:
            conn.close()

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
                file_path=str(output_path),
                sha256=output_sha256,
                size_bytes=output_size,
            ),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id="prov_001",
            description=f"VFR normalization: {source_fps}fps -> {target_fps}fps CFR",
        )

        logger.info("VFR normalization complete: %s", output_path)

        return StageResult(
            success=True,
            operation=OPERATION,
            provenance_record_id=record_id,
        )

    except PipelineError:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("VFR normalization failed: %s", error_msg)
        raise PipelineError(
            f"VFR normalization failed: {error_msg}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
