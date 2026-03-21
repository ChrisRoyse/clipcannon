"""Edit management API routes for the ClipCannon dashboard."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, JSONResponse

from clipcannon.db import execute, fetch_all, fetch_one, get_connection
from clipcannon.db.queries import table_exists

logger = logging.getLogger(__name__)

router = APIRouter(tags=["editing"])

PROJECTS_DIR = Path(
    os.environ.get(
        "CLIPCANNON_PROJECTS_DIR",
        str(Path.home() / ".clipcannon" / "projects"),
    )
)


def _get_db_path(project_id: str) -> Path:
    """Resolve the database path for a project.

    Args:
        project_id: The project identifier.

    Returns:
        Path to the project's analysis.db file.
    """
    return PROJECTS_DIR / project_id / "analysis.db"


@router.get("/api/projects/{project_id}/edits")
async def list_edits(
    project_id: str,
    status: str | None = Query(default=None, description="Filter by edit status"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results"),
) -> dict[str, object]:
    """List all edits for a project.

    Args:
        project_id: The project identifier.
        status: Optional status filter (draft, rendered, approved, rejected).
        limit: Maximum number of edits to return.

    Returns:
        Dictionary with edit list and count.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "edits": [],
            "count": 0,
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "edits"):
            return {
                "project_id": project_id,
                "edits": [],
                "count": 0,
            }

        sql = """
            SELECT edit_id, project_id, name, status, target_platform,
                   target_profile, total_duration_ms, segment_count,
                   captions_enabled, crop_mode, thumbnail_timestamp_ms,
                   metadata_title, metadata_description, metadata_hashtags,
                   render_id, created_at, updated_at
            FROM edits
            WHERE project_id = ?
        """
        params: list[object] = [project_id]

        if status is not None:
            sql += " AND status = ?"
            params.append(status)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        edits = fetch_all(conn, sql, tuple(params))

        return {
            "project_id": project_id,
            "edits": edits,
            "count": len(edits),
        }
    except Exception as exc:
        logger.error("Failed to list edits for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "edits": [],
            "count": 0,
            "error": f"Query failed: {exc}",
        }
    finally:
        conn.close()


@router.get("/api/projects/{project_id}/edits/{edit_id}")
async def get_edit_detail(project_id: str, edit_id: str) -> dict[str, object]:
    """Get edit detail including EDL, render status, and metadata.

    Joins the edits and renders tables to provide a complete view
    of an edit and its associated render job (if any).

    Args:
        project_id: The project identifier.
        edit_id: The edit identifier.

    Returns:
        Dictionary with full edit details and render info.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "edits"):
            return {
                "project_id": project_id,
                "edit_id": edit_id,
                "error": "Edits table not found",
            }

        edit = fetch_one(
            conn,
            "SELECT * FROM edits WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )

        if edit is None:
            return {
                "project_id": project_id,
                "edit_id": edit_id,
                "error": "Edit not found",
            }

        # Fetch render info if available
        render: dict[str, object] | None = None
        if table_exists(conn, "renders"):
            render = fetch_one(
                conn,
                """
                SELECT render_id, status, profile, output_path,
                       file_size_bytes, duration_ms, resolution,
                       codec, thumbnail_path, render_duration_ms,
                       error_message, created_at, completed_at
                FROM renders
                WHERE edit_id = ? AND project_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (edit_id, project_id),
            )

        # Fetch edit segments
        segments: list[dict[str, object]] = []
        if table_exists(conn, "edit_segments"):
            segments = fetch_all(
                conn,
                """
                SELECT id, segment_order, source_start_ms, source_end_ms,
                       output_start_ms, speed, transition_in_type,
                       transition_in_duration_ms, transition_out_type,
                       transition_out_duration_ms
                FROM edit_segments
                WHERE edit_id = ?
                ORDER BY segment_order
                """,
                (edit_id,),
            )

        return {
            "project_id": project_id,
            "edit": edit,
            "render": render,
            "segments": segments,
        }
    except Exception as exc:
        logger.error(
            "Failed to get edit detail for %s/%s: %s",
            project_id,
            edit_id,
            exc,
        )
        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "error": f"Query failed: {exc}",
        }
    finally:
        conn.close()


@router.post("/api/projects/{project_id}/edits/{edit_id}/approve")
async def approve_edit(project_id: str, edit_id: str) -> dict[str, object]:
    """Approve an edit by setting its status to 'approved'.

    Args:
        project_id: The project identifier.
        edit_id: The edit identifier.

    Returns:
        Dictionary confirming the approval action.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "success": False,
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "edits"):
            return {
                "project_id": project_id,
                "edit_id": edit_id,
                "success": False,
                "error": "Edits table not found",
            }

        # Verify edit exists
        edit = fetch_one(
            conn,
            "SELECT edit_id, status FROM edits WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )

        if edit is None:
            return {
                "project_id": project_id,
                "edit_id": edit_id,
                "success": False,
                "error": "Edit not found",
            }

        rows_affected = execute(
            conn,
            """
            UPDATE edits
            SET status = 'approved', updated_at = datetime('now')
            WHERE edit_id = ? AND project_id = ?
            """,
            (edit_id, project_id),
        )
        conn.commit()

        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "success": rows_affected > 0,
            "status": "approved",
            "previous_status": edit.get("status"),
        }
    except Exception as exc:
        logger.error(
            "Failed to approve edit %s/%s: %s",
            project_id,
            edit_id,
            exc,
        )
        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "success": False,
            "error": f"Approve failed: {exc}",
        }
    finally:
        conn.close()


@router.post("/api/projects/{project_id}/edits/{edit_id}/reject")
async def reject_edit(
    project_id: str,
    edit_id: str,
    feedback: str = Body(default="", embed=True),
) -> dict[str, object]:
    """Reject an edit with optional feedback text.

    Args:
        project_id: The project identifier.
        edit_id: The edit identifier.
        feedback: Rejection feedback text explaining why the edit was rejected.

    Returns:
        Dictionary confirming the rejection action.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "success": False,
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "edits"):
            return {
                "project_id": project_id,
                "edit_id": edit_id,
                "success": False,
                "error": "Edits table not found",
            }

        # Verify edit exists
        edit = fetch_one(
            conn,
            "SELECT edit_id, status FROM edits WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )

        if edit is None:
            return {
                "project_id": project_id,
                "edit_id": edit_id,
                "success": False,
                "error": "Edit not found",
            }

        rows_affected = execute(
            conn,
            """
            UPDATE edits
            SET status = 'rejected',
                rejection_feedback = ?,
                updated_at = datetime('now')
            WHERE edit_id = ? AND project_id = ?
            """,
            (feedback, edit_id, project_id),
        )
        conn.commit()

        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "success": rows_affected > 0,
            "status": "rejected",
            "feedback": feedback,
            "previous_status": edit.get("status"),
        }
    except Exception as exc:
        logger.error(
            "Failed to reject edit %s/%s: %s",
            project_id,
            edit_id,
            exc,
        )
        return {
            "project_id": project_id,
            "edit_id": edit_id,
            "success": False,
            "error": f"Reject failed: {exc}",
        }
    finally:
        conn.close()


@router.get("/api/projects/{project_id}/renders/{render_id}/video", response_model=None)
async def serve_video(
    project_id: str,
    render_id: str,
) -> FileResponse | JSONResponse:
    """Serve a rendered video file for in-browser playback.

    Looks up the render output_path from the database and returns the
    video file with the correct content-type for HTML5 video playback.

    Args:
        project_id: The project identifier.
        render_id: The render identifier.

    Returns:
        FileResponse with video/mp4 content type, or JSONResponse on error.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return JSONResponse(
            status_code=404,
            content={
                "project_id": project_id,
                "render_id": render_id,
                "error": "Project not found",
            },
        )

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "renders"):
            return JSONResponse(
                status_code=404,
                content={
                    "project_id": project_id,
                    "render_id": render_id,
                    "error": "Renders table not found",
                },
            )

        render = fetch_one(
            conn,
            """
            SELECT render_id, output_path, status, codec
            FROM renders
            WHERE render_id = ? AND project_id = ?
            """,
            (render_id, project_id),
        )

        if render is None:
            return JSONResponse(
                status_code=404,
                content={
                    "project_id": project_id,
                    "render_id": render_id,
                    "error": "Render not found",
                },
            )

        output_path = render.get("output_path")
        if not output_path:
            return JSONResponse(
                status_code=404,
                content={
                    "project_id": project_id,
                    "render_id": render_id,
                    "error": "Render has no output file",
                    "status": render.get("status"),
                },
            )

        video_path = Path(str(output_path))

        # Handle relative paths as relative to project directory
        if not video_path.is_absolute():
            video_path = PROJECTS_DIR / project_id / video_path

        if not video_path.exists():
            return JSONResponse(
                status_code=404,
                content={
                    "project_id": project_id,
                    "render_id": render_id,
                    "error": "Video file not found on disk",
                    "path": str(video_path),
                },
            )

        # Determine media type from codec or default to mp4
        media_type = "video/mp4"
        codec = render.get("codec", "")
        if codec and "webm" in str(codec).lower():
            media_type = "video/webm"

        return FileResponse(
            path=str(video_path),
            media_type=media_type,
            filename=video_path.name,
        )
    except Exception as exc:
        logger.error(
            "Failed to serve video for %s/%s: %s",
            project_id,
            render_id,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "project_id": project_id,
                "render_id": render_id,
                "error": f"Failed to serve video: {exc}",
            },
        )
    finally:
        conn.close()
