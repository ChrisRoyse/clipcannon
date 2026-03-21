"""Project management routes for the ClipCannon dashboard.

Provides endpoints to list projects, get project details, and
check pipeline processing status.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

PROJECTS_DIR = Path(
    os.environ.get(
        "CLIPCANNON_PROJECTS_DIR",
        str(Path.home() / ".clipcannon" / "projects"),
    )
)

# Pipeline stages in execution order
PIPELINE_STAGES = [
    "ingest",
    "frame_extraction",
    "scene_detection",
    "transcription",
    "diarization",
    "emotion_analysis",
    "visual_embedding",
    "topic_segmentation",
    "highlight_detection",
]


def _get_db_path(project_id: str) -> Path:
    """Resolve the database path for a project.

    Args:
        project_id: The project identifier.

    Returns:
        Path to the project's analysis.db file.
    """
    return PROJECTS_DIR / project_id / "analysis.db"


def _query_project_metadata(db_path: Path, project_id: str) -> dict[str, object] | None:
    """Query project metadata from the database.

    Args:
        db_path: Path to the project database.
        project_id: The project identifier.

    Returns:
        Project metadata dictionary or None if not found.
    """
    try:
        from clipcannon.db import fetch_one, get_connection

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT * FROM project WHERE project_id = ?",
                (project_id,),
            )
            if row is None:
                return None
            return {str(k): v for k, v in row.items()}
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Failed to query project %s: %s", project_id, exc)
        return None


def _query_pipeline_status(db_path: Path, project_id: str) -> dict[str, object]:
    """Query pipeline processing status from provenance records.

    Args:
        db_path: Path to the project database.
        project_id: The project identifier.

    Returns:
        Dictionary with completed stages and overall progress.
    """
    completed_stages: list[str] = []

    try:
        from clipcannon.db import fetch_all, get_connection

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT DISTINCT stage FROM provenance WHERE project_id = ?",
                (project_id,),
            )
            completed_stages = [str(row["stage"]) for row in rows]
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("Failed to query pipeline status for %s: %s", project_id, exc)

    progress = len(completed_stages) / len(PIPELINE_STAGES) * 100 if PIPELINE_STAGES else 0

    return {
        "completed_stages": completed_stages,
        "total_stages": len(PIPELINE_STAGES),
        "progress_pct": round(progress, 1),
        "all_stages": PIPELINE_STAGES,
    }


@router.get("")
async def list_projects() -> dict[str, object]:
    """List all projects with basic metadata.

    Returns:
        Dictionary with project list and count.
    """
    projects: list[dict[str, object]] = []

    if not PROJECTS_DIR.exists():
        return {"projects": projects, "count": 0}

    try:
        project_dirs = sorted(
            [d for d in PROJECTS_DIR.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )

        for proj_dir in project_dirs:
            db_path = proj_dir / "analysis.db"
            stat = proj_dir.stat()

            project_info: dict[str, object] = {
                "project_id": proj_dir.name,
                "name": proj_dir.name,
                "has_database": db_path.exists(),
                "created_at": datetime.fromtimestamp(
                    stat.st_ctime,
                    tz=UTC,
                ).isoformat(),
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime,
                    tz=UTC,
                ).isoformat(),
            }

            # Get status from DB if available
            if db_path.exists():
                metadata = _query_project_metadata(db_path, proj_dir.name)
                if metadata:
                    project_info["status"] = metadata.get("status", "unknown")
                    project_info["source_path"] = metadata.get("source_path")
                    project_info["duration_ms"] = metadata.get("duration_ms")
                    project_info["resolution"] = metadata.get("resolution")
                else:
                    project_info["status"] = "created"
            else:
                project_info["status"] = "created"

            projects.append(project_info)

    except OSError as exc:
        logger.warning("Failed to list projects: %s", exc)

    return {"projects": projects, "count": len(projects)}


@router.get("/{project_id}")
async def get_project_detail(project_id: str) -> dict[str, object]:
    """Get detailed information about a project.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with full project metadata and pipeline status.
    """
    proj_dir = PROJECTS_DIR / project_id

    if not proj_dir.exists():
        return {
            "project_id": project_id,
            "found": False,
            "error": f"Project not found: {project_id}",
        }

    db_path = proj_dir / "analysis.db"
    stat = proj_dir.stat()

    result: dict[str, object] = {
        "project_id": project_id,
        "found": True,
        "has_database": db_path.exists(),
        "created_at": datetime.fromtimestamp(
            stat.st_ctime,
            tz=UTC,
        ).isoformat(),
        "modified_at": datetime.fromtimestamp(
            stat.st_mtime,
            tz=UTC,
        ).isoformat(),
    }

    if db_path.exists():
        metadata = _query_project_metadata(db_path, project_id)
        if metadata:
            result["metadata"] = metadata

        pipeline = _query_pipeline_status(db_path, project_id)
        result["pipeline"] = pipeline
    else:
        result["metadata"] = None
        result["pipeline"] = {
            "completed_stages": [],
            "total_stages": len(PIPELINE_STAGES),
            "progress_pct": 0,
            "all_stages": PIPELINE_STAGES,
        }

    # List files in project directory
    try:
        files = []
        for f in proj_dir.iterdir():
            if f.is_file():
                files.append(
                    {
                        "name": f.name,
                        "size_bytes": f.stat().st_size,
                    }
                )
        result["files"] = files
    except OSError:
        result["files"] = []

    return result


@router.get("/{project_id}/status")
async def get_project_status(project_id: str) -> dict[str, object]:
    """Get the pipeline processing status for a project.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with pipeline progress and stage completion.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "status": "not_found",
            "pipeline": {
                "completed_stages": [],
                "total_stages": len(PIPELINE_STAGES),
                "progress_pct": 0,
                "all_stages": PIPELINE_STAGES,
            },
        }

    # Get project status from metadata
    metadata = _query_project_metadata(db_path, project_id)
    status = "unknown"
    if metadata:
        status = str(metadata.get("status", "unknown"))

    pipeline = _query_pipeline_status(db_path, project_id)

    return {
        "project_id": project_id,
        "status": status,
        "pipeline": pipeline,
    }
