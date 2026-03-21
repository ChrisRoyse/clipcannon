"""Project management MCP tools for ClipCannon.

Provides tools for creating, opening, listing, inspecting, and deleting
video analysis projects. Each project gets its own directory structure
and SQLite database under ~/.clipcannon/projects/.
"""

from __future__ import annotations

import logging
import secrets
import shutil
import time
from pathlib import Path

from mcp.types import Tool

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
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
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


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


async def clipcannon_project_list(status_filter: str = "all") -> dict[str, object]:
    """List all projects, optionally filtered by status.

    Args:
        status_filter: Status to filter by, or "all" for everything.

    Returns:
        Dictionary with projects list.
    """
    projects_dir = _get_projects_dir()
    if not projects_dir.exists():
        return {"projects": [], "total": 0}

    projects: list[dict[str, object]] = []

    try:
        for entry in sorted(projects_dir.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("proj_"):
                continue

            db_file = entry / "analysis.db"
            if not db_file.exists():
                continue

            try:
                conn = get_connection(db_file, enable_vec=False, dict_rows=True)
                try:
                    row = fetch_one(
                        conn,
                        "SELECT project_id, name, status, duration_ms,"
                        " resolution, created_at FROM project LIMIT 1",
                    )
                finally:
                    conn.close()

                if row is not None and (
                    status_filter == "all" or row.get("status") == status_filter
                ):
                    projects.append(dict(row))
            except ClipCannonError:
                logger.warning("Failed to read project %s", entry.name)
                continue

        return {"projects": projects, "total": len(projects)}

    except Exception as exc:
        logger.exception("Error listing projects")
        return _error_response("INTERNAL_ERROR", f"Error listing projects: {exc}")


async def clipcannon_project_status(project_id: str) -> dict[str, object]:
    """Get detailed project status including pipeline progress.

    Args:
        project_id: Project identifier.

    Returns:
        Detailed status dict or error response.
    """
    db_path = _get_db_path(project_id)
    if not db_path.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            project_row = fetch_one(
                conn,
                "SELECT * FROM project WHERE project_id = ?",
                (project_id,),
            )
            if project_row is None:
                return _error_response("PROJECT_NOT_FOUND", f"No project record: {project_id}")

            # Pipeline progress
            streams = fetch_all(
                conn,
                "SELECT stream_name, status, started_at, completed_at, duration_ms, error_message "
                "FROM stream_status WHERE project_id = ? ORDER BY stream_name",
                (project_id,),
            )
        finally:
            conn.close()

        # Compute pipeline summary
        total = len(streams)
        completed = sum(1 for s in streams if s.get("status") == "completed")
        failed = sum(1 for s in streams if s.get("status") == "failed")
        running = sum(1 for s in streams if s.get("status") == "running")
        pending = sum(1 for s in streams if s.get("status") == "pending")

        # Compute disk usage by tier
        project_dir = _get_projects_dir() / project_id
        disk_usage = _compute_disk_usage(project_dir)

        return {
            "project": dict(project_row),
            "pipeline": {
                "total_streams": total,
                "completed": completed,
                "failed": failed,
                "running": running,
                "pending": pending,
                "progress_pct": round(completed / total * 100, 1) if total > 0 else 0,
                "streams": [dict(s) for s in streams],
            },
            "disk_usage": disk_usage,
        }

    except ClipCannonError as exc:
        return _error_response("INTERNAL_ERROR", str(exc), exc.details)


def _compute_disk_usage(project_dir: Path) -> dict[str, object]:
    """Compute disk usage for a project directory.

    Args:
        project_dir: Path to the project directory.

    Returns:
        Dictionary with total_bytes and per-subdirectory breakdown.
    """
    if not project_dir.exists():
        return {"total_bytes": 0, "subdirs": {}}

    subdirs: dict[str, int] = {}
    total = 0

    for item in project_dir.iterdir():
        if item.is_dir():
            dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            subdirs[item.name] = dir_size
            total += dir_size
        elif item.is_file():
            size = item.stat().st_size
            subdirs[item.name] = size
            total += size

    return {"total_bytes": total, "subdirs": subdirs}


async def clipcannon_project_delete(
    project_id: str,
    keep_source: bool = True,
) -> dict[str, object]:
    """Delete a project directory and optionally preserve the source video.

    Args:
        project_id: Project identifier.
        keep_source: If True, do not delete the original source video.

    Returns:
        Deletion result or error response.
    """
    project_dir = _get_projects_dir() / project_id
    if not project_dir.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        # Measure size before deletion
        total_size = sum(f.stat().st_size for f in project_dir.rglob("*") if f.is_file())

        if keep_source:
            # Delete everything except source/
            source_dir = project_dir / "source"
            source_size = (
                sum(f.stat().st_size for f in source_dir.rglob("*") if f.is_file())
                if source_dir.exists()
                else 0
            )

            for item in project_dir.iterdir():
                if item.name == "source":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            freed = total_size - source_size
        else:
            shutil.rmtree(project_dir)
            freed = total_size

        freed_mb = round(freed / (1024 * 1024), 2)

        return {
            "project_id": project_id,
            "deleted": True,
            "keep_source": keep_source,
            "freed_bytes": freed,
            "freed_mb": freed_mb,
        }

    except Exception as exc:
        logger.exception("Error deleting project %s", project_id)
        return _error_response("INTERNAL_ERROR", f"Deletion failed: {exc}")


_PROJECT_ID_SCHEMA = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string", "description": "Project identifier"},
    },
    "required": ["project_id"],
}

PROJECT_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_project_create",
        description=(
            "Create a new project from a source video. Validates format,"
            " extracts metadata via ffprobe, computes SHA-256,"
            " and initializes the project database."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable project name"},
                "source_video_path": {
                    "type": "string",
                    "description": "Absolute path to source video (mp4/mov/mkv/webm/avi/ts/mts)",
                },
            },
            "required": ["name", "source_video_path"],
        },
    ),
    Tool(
        name="clipcannon_project_open",
        description="Open an existing project and return its current state.",
        inputSchema=_PROJECT_ID_SCHEMA,
    ),
    Tool(
        name="clipcannon_project_list",
        description="List all projects, optionally filtered by status.",
        inputSchema={
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Filter: all, created, analyzing, ready, error",
                    "default": "all",
                },
            },
        },
    ),
    Tool(
        name="clipcannon_project_status",
        description="Get detailed status with pipeline progress and disk usage.",
        inputSchema=_PROJECT_ID_SCHEMA,
    ),
    Tool(
        name="clipcannon_project_delete",
        description="Delete a project. Can optionally preserve the original source video.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "keep_source": {
                    "type": "boolean",
                    "description": "Preserve source video",
                    "default": True,
                },
            },
            "required": ["project_id"],
        },
    ),
]


async def dispatch_project_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    """Dispatch a project tool call by name."""
    if name == "clipcannon_project_create":
        return await clipcannon_project_create(
            str(arguments["name"]), str(arguments["source_video_path"])
        )
    elif name == "clipcannon_project_open":
        return await clipcannon_project_open(str(arguments["project_id"]))
    elif name == "clipcannon_project_list":
        return await clipcannon_project_list(str(arguments.get("status_filter", "all")))
    elif name == "clipcannon_project_status":
        return await clipcannon_project_status(str(arguments["project_id"]))
    elif name == "clipcannon_project_delete":
        return await clipcannon_project_delete(
            str(arguments["project_id"]), bool(arguments.get("keep_source", True))
        )
    return _error_response("INTERNAL_ERROR", f"Unknown project tool: {name}")
