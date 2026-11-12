"""Editing helpers: platform profiles, errors, paths and project validation."""

from __future__ import annotations

from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_one
from clipcannon.exceptions import ClipCannonError

# ============================================================
# PLATFORM -> RENDER PROFILE MAPPING
# ============================================================
PLATFORM_PROFILES: dict[str, str] = {
    "tiktok": "tiktok_vertical",
    "instagram_reels": "instagram_reels",
    "youtube_shorts": "youtube_shorts",
    "youtube_standard": "youtube_standard",
    "youtube_4k": "youtube_4k",
    "facebook": "facebook",
    "linkedin": "linkedin",
}


# ============================================================
# SHARED UTILITIES
# ============================================================
def error_response(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Build standardized error response dict.

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        details: Optional additional context.

    Returns:
        Error response dictionary.
    """
    return {"error": {"code": code, "message": message, "details": details or {}}}


def projects_dir() -> Path:
    """Resolve projects base directory from config or default.

    Returns:
        Absolute path to the projects directory.
    """
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def db_path(project_id: str) -> Path:
    """Build database path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project's analysis.db.
    """
    return projects_dir() / project_id / "analysis.db"


def project_dir(project_id: str) -> Path:
    """Build project directory path.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project directory.
    """
    return projects_dir() / project_id


def validate_project(
    project_id: str, required_status: str | None = "ready"
) -> dict[str, object] | None:
    """Validate project exists and check status.

    Args:
        project_id: Project identifier.
        required_status: Expected status, or None to skip check.

    Returns:
        Error dict if validation fails, None on success.
    """
    db = db_path(project_id)
    if not db.exists():
        return error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")
    if required_status is not None:
        conn = get_connection(db, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT status FROM project WHERE project_id = ?",
                (project_id,),
            )
        finally:
            conn.close()
        if row is None:
            return error_response("PROJECT_NOT_FOUND", f"No project record: {project_id}")
        status = str(row.get("status", ""))
        if required_status == "ready" and status not in ("ready", "ready_degraded", "analyzing"):
            return error_response(
                "INVALID_STATE",
                f"Project not ready, current status: {status}",
            )
    return None
