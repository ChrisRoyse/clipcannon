"""FFprobe + VFR detection pipeline stage for ClipCannon.

Validates the source video file, extracts metadata via ffprobe,
detects variable frame rate, computes the source SHA-256, inserts
project metadata into the database, and writes a provenance record.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

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
    sha256_string,
)
from clipcannon.tools.video_probe import (
    SUPPORTED_FORMATS,
    detect_vfr,
    extract_video_metadata,
    run_ffprobe,
)

if TYPE_CHECKING:
    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "probe"
STAGE = "ffprobe_vfr"


def _validate_source_file(source_path: Path) -> None:
    """Validate that the source video file exists and is supported.

    Args:
        source_path: Path to the source video file.

    Raises:
        PipelineError: If the file is missing, not a file, or unsupported.
    """
    if not source_path.exists():
        raise PipelineError(
            f"Source file not found: {source_path}",
            stage_name=STAGE,
            operation=OPERATION,
            details={"path": str(source_path)},
        )
    if not source_path.is_file():
        raise PipelineError(
            f"Source path is not a file: {source_path}",
            stage_name=STAGE,
            operation=OPERATION,
            details={"path": str(source_path)},
        )

    suffix = source_path.suffix.lstrip(".").lower()
    if suffix not in SUPPORTED_FORMATS:
        raise PipelineError(
            f"Unsupported video format: .{suffix}. Supported: {SUPPORTED_FORMATS}",
            stage_name=STAGE,
            operation=OPERATION,
            details={"format": suffix},
        )


async def run_probe(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the probe pipeline stage.

    Steps:
        1. Resolve source file path from the project database.
        2. Validate the file exists and is a supported format.
        3. Run ffprobe to extract metadata.
        4. Detect VFR using the vfrdet filter.
        5. Compute SHA-256 of the source file.
        6. Update the project table with all metadata.
        7. Write a provenance record.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    try:
        # 1. Look up source path from project table
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT source_path FROM project WHERE project_id = ?",
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

        source_path = Path(str(row["source_path"]))

        # 2. Validate source file
        _validate_source_file(source_path)

        # 3. Run ffprobe (blocking - run in executor)
        probe_data = await asyncio.to_thread(run_ffprobe, str(source_path))
        metadata = extract_video_metadata(probe_data)

        # Validate minimum requirements
        duration_ms = int(metadata["duration_ms"])
        if duration_ms <= 0:
            raise PipelineError(
                "Video has zero or negative duration",
                stage_name=STAGE,
                operation=OPERATION,
                details={"duration_ms": duration_ms},
            )

        # 4. Detect VFR (blocking - run in executor)
        vfr_detected = await asyncio.to_thread(detect_vfr, str(source_path))
        logger.info(
            "VFR detection for %s: %s",
            source_path.name,
            "VFR detected" if vfr_detected else "CFR",
        )

        # 5. Compute SHA-256 (blocking - run in executor)
        source_sha256 = await asyncio.to_thread(sha256_file, source_path)

        file_size = source_path.stat().st_size

        # 6. Update project table
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            execute(
                conn,
                """UPDATE project SET
                    source_sha256 = ?,
                    duration_ms = ?,
                    resolution = ?,
                    fps = ?,
                    codec = ?,
                    audio_codec = ?,
                    audio_channels = ?,
                    file_size_bytes = ?,
                    vfr_detected = ?,
                    status = 'probed',
                    updated_at = datetime('now')
                WHERE project_id = ?""",
                (
                    source_sha256,
                    duration_ms,
                    str(metadata["resolution"]),
                    float(metadata["fps"]),
                    str(metadata["codec"]),
                    metadata.get("audio_codec"),
                    metadata.get("audio_channels"),
                    file_size,
                    vfr_detected,
                    project_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # 7. Write provenance record
        output_hash = sha256_string(
            f"{source_sha256}|{duration_ms}|{metadata['resolution']}|"
            f"{metadata['fps']}|{metadata['codec']}|{vfr_detected}"
        )

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(source_path),
                sha256=source_sha256,
                size_bytes=file_size,
            ),
            output_info=OutputInfo(
                sha256=output_hash,
                record_count=1,
            ),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id=None,
            description=(
                f"Probed video: {metadata['resolution']} @ {metadata['fps']}fps, "
                f"{duration_ms}ms, codec={metadata['codec']}, vfr={vfr_detected}"
            ),
        )

        logger.info(
            "Probe complete for %s: %s @ %sfps, %dms, vfr=%s",
            project_id,
            metadata["resolution"],
            metadata["fps"],
            duration_ms,
            vfr_detected,
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
        logger.error("Probe stage failed: %s", error_msg)
        raise PipelineError(
            f"Probe stage failed: {error_msg}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
