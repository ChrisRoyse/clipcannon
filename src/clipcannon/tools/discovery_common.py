"""Shared helpers for the discovery MCP tools (errors, paths, validation)."""

from __future__ import annotations

import json
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_one
from clipcannon.exceptions import ClipCannonError


# ============================================================
# HELPERS
# ============================================================
def _error(
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
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


def _projects_dir() -> Path:
    """Resolve projects base directory from config or default.

    Returns:
        Absolute path to the projects directory.
    """
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def _db_path(project_id: str) -> Path:
    """Build database path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project's analysis.db.
    """
    return _projects_dir() / project_id / "analysis.db"


def _validate_project(
    project_id: str, required_status: str | None = "ready"
) -> dict[str, object] | None:
    """Validate project exists and check status.

    Args:
        project_id: Project identifier.
        required_status: Required project status, or None to skip check.

    Returns:
        Error dict if validation fails, None on success.
    """
    db = _db_path(project_id)
    if not db.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")
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
            return _error("PROJECT_NOT_FOUND", f"No project record: {project_id}")
        status = str(row.get("status", ""))
        if required_status == "ready" and status not in (
            "ready",
            "ready_degraded",
            "analyzing",
        ):
            return _error(
                "INVALID_STATE",
                f"Project not ready, current status: {status}",
            )
    return None


def _parse_canvas_regions(
    canvas_json_str: str, layout: str | None, recommended: str
) -> tuple[str, list[dict[str, object]]]:
    """Parse canvas_regions_json and extract regions for a layout.

    Args:
        canvas_json_str: Raw JSON string from the scene_map row.
        layout: Requested layout (A/B/C/D) or None for recommended.
        recommended: The scene's recommended layout.

    Returns:
        Tuple of (target_layout, regions list).
    """
    try:
        all_canvas = json.loads(canvas_json_str)
    except (json.JSONDecodeError, TypeError):
        all_canvas = {}

    target_layout = layout if layout is not None else recommended
    regions: list[dict[str, object]] = []
    if isinstance(all_canvas, dict) and target_layout in all_canvas:
        raw = all_canvas[target_layout]
        if isinstance(raw, list):
            regions = raw
        elif isinstance(raw, dict):
            regions = [raw]
    return target_layout, regions
