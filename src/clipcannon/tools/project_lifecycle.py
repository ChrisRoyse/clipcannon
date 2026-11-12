"""Project MCP tools: shared helpers, project create and open."""

from __future__ import annotations

import logging
import secrets
import shutil
import time
from pathlib import Path

from clipcannon.config import projects_dir as _cfg_projects_dir
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.db.schema import PIPELINE_STREAMS, init_project_directory
from clipcannon.exceptions import ClipCannonError
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
)
from clipcannon.tools.video_probe import (
    SUPPORTED_FORMATS,
    detect_vfr,
    extract_video_metadata,
    run_ffprobe,
)

logger = logging.getLogger(__name__)


def _error_response(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Build a standardized error response dict.

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        details: Optional additional context.

    Returns:
        Error response dictionary.
    """
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _get_projects_dir() -> Path:
    """Resolve the projects base directory from config.

    Returns:
        Absolute path to the projects directory.
    """
    return _cfg_projects_dir()


def _get_db_path(project_id: str) -> Path:
    """Build the database path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project's analysis.db.
    """
    return _get_projects_dir() / project_id / "analysis.db"


async def clipcannon_project_create(
    name: str,
    source_video_path: str,
) -> dict[str, object]:
    """Create a new ClipCannon project from a source video.

    Validates the source file, extracts metadata via ffprobe, computes
    a SHA-256 hash, creates the project directory and database, and
    records an initial provenance entry.

    Args:
        name: Human-readable project name.
        source_video_path: Absolute path to the source video file.

    Returns:
        Project info dict or error response.
    """
    # Validate source file
    source_path = Path(source_video_path).resolve()
    if not source_path.exists():
        return _error_response(
            "INVALID_PARAMETER",
            f"Source video not found: {source_video_path}",
            {"path": str(source_path)},
        )

    suffix = source_path.suffix.lstrip(".").lower()
    if suffix not in SUPPORTED_FORMATS:
        return _error_response(
            "INVALID_PARAMETER",
            f"Unsupported format: .{suffix}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}",
            {"format": suffix, "supported": sorted(SUPPORTED_FORMATS)},
        )

    # Generate project ID
    project_id = f"proj_{secrets.token_hex(4)}"

    try:
        # Run ffprobe
        start_time = time.monotonic()
        probe_data = run_ffprobe(str(source_path))
        metadata = extract_video_metadata(probe_data)
        probe_duration_ms = int((time.monotonic() - start_time) * 1000)

        # Compute SHA-256
        source_sha256 = sha256_file(source_path)

        # Detect VFR
        vfr_detected = detect_vfr(str(source_path))

        # Create project directory structure and DB
        projects_dir = _get_projects_dir()
        project_dir = init_project_directory(project_id, projects_dir)
        db_path = projects_dir / project_id / "analysis.db"

        # Copy source to project source/ dir
        dest_source = project_dir / "source" / source_path.name
        shutil.copy2(str(source_path), str(dest_source))

        # Insert project record
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            execute(
                conn,
                """INSERT INTO project (
                    project_id, name, source_path, source_sha256,
                    duration_ms, resolution, fps, codec,
                    audio_codec, audio_channels, file_size_bytes,
                    vfr_detected, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created')""",
                (
                    project_id,
                    name,
                    str(dest_source),
                    source_sha256,
                    metadata["duration_ms"],
                    metadata["resolution"],
                    metadata["fps"],
                    metadata["codec"],
                    metadata.get("audio_codec"),
                    metadata.get("audio_channels"),
                    metadata.get("file_size_bytes"),
                    vfr_detected,
                ),
            )

            # Initialize stream_status rows
            for stream_name in PIPELINE_STREAMS:
                execute(
                    conn,
                    "INSERT INTO stream_status (project_id, stream_name, status)"
                    " VALUES (?, ?, 'pending')",
                    (project_id, stream_name),
                )

            conn.commit()
        finally:
            conn.close()

        # Record provenance for the probe operation
        record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation="probe",
            stage="ffprobe",
            input_info=InputInfo(
                file_path=str(dest_source),
                sha256=source_sha256,
                size_bytes=metadata.get("file_size_bytes", 0),
            ),
            output_info=OutputInfo(
                sha256="",
                record_count=1,
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=probe_duration_ms),
            parent_record_id=None,
            description=f"Initial probe of source video: {source_path.name}",
        )

        return {
            "project_id": project_id,
            "name": name,
            "source_path": str(dest_source),
            "source_sha256": source_sha256,
            "duration_ms": metadata["duration_ms"],
            "resolution": metadata["resolution"],
            "fps": metadata["fps"],
            "codec": metadata["codec"],
            "audio_codec": metadata.get("audio_codec"),
            "audio_channels": metadata.get("audio_channels"),
            "file_size_bytes": metadata.get("file_size_bytes"),
            "vfr_detected": vfr_detected,
            "status": "created",
            "project_dir": str(project_dir),
        }

    except ClipCannonError as exc:
        return _error_response("INTERNAL_ERROR", str(exc), exc.details)
    except Exception as exc:
        logger.exception("Unexpected error creating project")
        return _error_response("INTERNAL_ERROR", f"Unexpected error: {exc}")


async def clipcannon_project_open(project_id: str) -> dict[str, object]:
    """Open an existing project and return its current state.

    Args:
        project_id: Project identifier.

    Returns:
        Project state dict or error response.
    """
    db_path = _get_db_path(project_id)
    if not db_path.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(conn, "SELECT * FROM project WHERE project_id = ?", (project_id,))
        finally:
            conn.close()

        if row is None:
            return _error_response("PROJECT_NOT_FOUND", f"Project record not found: {project_id}")

        return dict(row)
    except ClipCannonError as exc:
        return _error_response("INTERNAL_ERROR", str(exc), exc.details)
