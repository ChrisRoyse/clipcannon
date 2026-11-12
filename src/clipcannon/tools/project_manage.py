"""Project MCP tools: project list, status and delete."""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.project_lifecycle import _error_response, _get_db_path, _get_projects_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


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
