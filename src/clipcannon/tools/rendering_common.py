"""Shared helpers for the rendering MCP tools (errors, paths, sources, EDL loading)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from clipcannon.config import projects_dir as _cfg_projects_dir
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_one
from clipcannon.editing.edl import EditDecisionList


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
    """Resolve the configured projects directory (no fallback, see config.projects_dir).

    Returns:
        Absolute path to the projects directory.
    """
    return _cfg_projects_dir()


def _db_path(project_id: str) -> Path:
    """Build database path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project's analysis.db.
    """
    return _projects_dir() / project_id / "analysis.db"


def _project_dir(project_id: str) -> Path:
    """Build project directory path.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project directory.
    """
    return _projects_dir() / project_id


def _resolve_render_path(project_id: str, render_id: str) -> Path | None:
    """Resolve the output video path for a render.

    Args:
        project_id: Project identifier.
        render_id: Render identifier.

    Returns:
        Path to the rendered video, or None if not found.
    """
    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT output_path FROM renders "
            "WHERE render_id = ? AND project_id = ?",
            (render_id, project_id),
        )
    finally:
        conn.close()
    if row is None or not row.get("output_path"):
        return None
    path = Path(str(row["output_path"]))
    return path if path.exists() else None


async def _extract_render_frame(video_path: Path, timestamp_ms: int) -> Path | None:
    """Extract a single frame from a video at a given timestamp.

    Uses ffmpeg to seek to the timestamp and extract one JPEG frame.

    Args:
        video_path: Path to the video file.
        timestamp_ms: Timestamp in milliseconds to extract.

    Returns:
        Path to the extracted JPEG frame, or None on failure.
    """
    import tempfile

    output = Path(tempfile.mktemp(suffix=".jpg"))
    cmd = [
        "ffmpeg", "-y", "-ss", f"{timestamp_ms / 1000:.3f}",
        "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(output),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()
    return output if output.exists() and output.stat().st_size > 0 else None


def _resolve_source(project_id: str) -> Path | None:
    """Resolve the source video path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the source video, or None if not found.
    """
    db = _db_path(project_id)
    if not db.exists():
        return None

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT source_path, source_cfr_path FROM project "
            "WHERE project_id = ?",
            (project_id,),
        )
    finally:
        conn.close()

    if row is None:
        return None

    cfr = row.get("source_cfr_path")
    if cfr and Path(str(cfr)).exists():
        return Path(str(cfr))

    source = Path(str(row["source_path"]))
    return source if source.exists() else None


def _validate_project(project_id: str) -> dict[str, object] | None:
    """Validate that a project exists.

    Args:
        project_id: Project identifier.

    Returns:
        Error dict if validation fails, None on success.
    """
    db = _db_path(project_id)
    if not db.exists():
        return _error(
            "PROJECT_NOT_FOUND",
            f"Project not found: {project_id}",
        )
    return None


def _load_edl(
    project_id: str, edit_id: str
) -> tuple[EditDecisionList | None, dict[str, object] | None]:
    """Load an EDL from the database.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.

    Returns:
        Tuple of (EDL, None) on success or (None, error_dict) on failure.
    """
    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
    finally:
        conn.close()

    if row is None:
        return None, _error(
            "EDIT_NOT_FOUND",
            f"Edit not found: {edit_id}",
            {"edit_id": edit_id, "project_id": project_id},
        )

    status = str(row.get("status", ""))
    if status not in ("draft", "rendered", "approved"):
        return None, _error(
            "INVALID_STATE",
            f"Cannot render edit in '{status}' status",
            {"edit_id": edit_id, "status": status},
        )

    try:
        edl_data = json.loads(str(row["edl_json"]))
        edl = EditDecisionList(**edl_data)
    except Exception as exc:
        return None, _error(
            "INTERNAL_ERROR",
            f"Failed to parse EDL: {exc}",
            {"edit_id": edit_id},
        )

    return edl, None
