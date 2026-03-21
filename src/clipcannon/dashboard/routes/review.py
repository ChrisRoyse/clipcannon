"""Batch review workflow API routes for the ClipCannon dashboard.

Provides endpoints for batch review of rendered edits, including
a review queue, batch approve/reject operations, and review statistics.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Body

from clipcannon.db import execute, fetch_all, fetch_one, get_connection
from clipcannon.db.queries import table_exists

logger = logging.getLogger(__name__)

router = APIRouter(tags=["review"])

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


@router.get("/api/projects/{project_id}/review/queue")
async def get_review_queue(project_id: str) -> dict[str, object]:
    """Get all edits pending review (status='rendered').

    Returns edits that have been rendered and are ready for human review,
    including render info, metadata, and thumbnail path.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with review queue items.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "queue": [],
            "count": 0,
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "edits"):
            return {
                "project_id": project_id,
                "queue": [],
                "count": 0,
            }

        has_renders = table_exists(conn, "renders")

        if has_renders:
            queue = fetch_all(
                conn,
                """
                SELECT e.edit_id, e.name, e.status, e.target_platform,
                       e.target_profile, e.total_duration_ms, e.segment_count,
                       e.metadata_title, e.metadata_description,
                       e.metadata_hashtags, e.thumbnail_timestamp_ms,
                       e.created_at, e.updated_at,
                       r.render_id, r.status AS render_status,
                       r.output_path, r.file_size_bytes, r.duration_ms AS render_duration_ms,
                       r.resolution, r.codec, r.thumbnail_path,
                       r.completed_at AS render_completed_at
                FROM edits e
                LEFT JOIN renders r ON e.edit_id = r.edit_id AND e.project_id = r.project_id
                WHERE e.project_id = ? AND e.status = 'rendered'
                ORDER BY e.updated_at DESC
                """,
                (project_id,),
            )
        else:
            queue = fetch_all(
                conn,
                """
                SELECT edit_id, name, status, target_platform,
                       target_profile, total_duration_ms, segment_count,
                       metadata_title, metadata_description,
                       metadata_hashtags, thumbnail_timestamp_ms,
                       created_at, updated_at
                FROM edits
                WHERE project_id = ? AND status = 'rendered'
                ORDER BY updated_at DESC
                """,
                (project_id,),
            )

        return {
            "project_id": project_id,
            "queue": queue,
            "count": len(queue),
        }
    except Exception as exc:
        logger.error("Failed to get review queue for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "queue": [],
            "count": 0,
            "error": f"Query failed: {exc}",
        }
    finally:
        conn.close()


_DECISIONS_BODY: list[dict[str, str]] = Body(  # type: ignore[assignment]
    ...,
    description="Array of review decisions: {edit_id, action, feedback?}",
)


@router.post("/api/projects/{project_id}/review/batch")
async def batch_review(
    project_id: str,
    decisions: list[dict[str, str]] = _DECISIONS_BODY,
) -> dict[str, object]:
    """Batch approve or reject multiple edits.

    Accepts an array of review decisions, each containing an edit_id,
    an action ('approve' or 'reject'), and optional feedback text.

    Args:
        project_id: The project identifier.
        decisions: List of decision dicts with edit_id, action, and optional feedback.

    Returns:
        Dictionary with results for each decision.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "success": False,
            "results": [],
            "error": "Project not found",
        }

    if not decisions:
        return {
            "project_id": project_id,
            "success": False,
            "results": [],
            "error": "No decisions provided",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "edits"):
            return {
                "project_id": project_id,
                "success": False,
                "results": [],
                "error": "Edits table not found",
            }

        results: list[dict[str, object]] = []
        success_count = 0

        for decision in decisions:
            edit_id = decision.get("edit_id", "")
            action = decision.get("action", "")
            feedback = decision.get("feedback", "")

            if not edit_id:
                results.append({
                    "edit_id": edit_id,
                    "success": False,
                    "error": "Missing edit_id",
                })
                continue

            if action not in ("approve", "reject"):
                results.append({
                    "edit_id": edit_id,
                    "success": False,
                    "error": f"Invalid action: {action}. Must be 'approve' or 'reject'",
                })
                continue

            # Verify edit exists
            edit = fetch_one(
                conn,
                "SELECT edit_id, status FROM edits WHERE edit_id = ? AND project_id = ?",
                (edit_id, project_id),
            )

            if edit is None:
                results.append({
                    "edit_id": edit_id,
                    "success": False,
                    "error": "Edit not found",
                })
                continue

            if action == "approve":
                execute(
                    conn,
                    """
                    UPDATE edits
                    SET status = 'approved', updated_at = datetime('now')
                    WHERE edit_id = ? AND project_id = ?
                    """,
                    (edit_id, project_id),
                )
            else:
                execute(
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

            results.append({
                "edit_id": edit_id,
                "success": True,
                "action": action,
                "previous_status": edit.get("status"),
            })
            success_count += 1

        conn.commit()

        return {
            "project_id": project_id,
            "success": success_count > 0,
            "total": len(decisions),
            "succeeded": success_count,
            "failed": len(decisions) - success_count,
            "results": results,
        }
    except Exception as exc:
        logger.error("Batch review failed for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "success": False,
            "results": [],
            "error": f"Batch review failed: {exc}",
        }
    finally:
        conn.close()


@router.get("/api/projects/{project_id}/review/stats")
async def get_review_stats(project_id: str) -> dict[str, object]:
    """Get review statistics for a project.

    Returns counts of edits by status: total, approved, rejected,
    pending (draft), and rendered (awaiting review).

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with review statistics.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "stats": {
                "total": 0,
                "approved": 0,
                "rejected": 0,
                "pending": 0,
                "rendered": 0,
            },
            "error": "Project not found",
        }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "edits"):
            return {
                "project_id": project_id,
                "stats": {
                    "total": 0,
                    "approved": 0,
                    "rejected": 0,
                    "pending": 0,
                    "rendered": 0,
                },
            }

        rows = fetch_all(
            conn,
            """
            SELECT status, count(*) AS cnt
            FROM edits
            WHERE project_id = ?
            GROUP BY status
            """,
            (project_id,),
        )

        status_counts: dict[str, int] = {}
        total = 0
        for row in rows:
            status_str = str(row.get("status", "unknown"))
            count = int(row.get("cnt", 0))
            status_counts[status_str] = count
            total += count

        return {
            "project_id": project_id,
            "stats": {
                "total": total,
                "approved": status_counts.get("approved", 0),
                "rejected": status_counts.get("rejected", 0),
                "pending": status_counts.get("draft", 0),
                "rendered": status_counts.get("rendered", 0),
            },
        }
    except Exception as exc:
        logger.error("Failed to get review stats for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "stats": {
                "total": 0,
                "approved": 0,
                "rejected": 0,
                "pending": 0,
                "rendered": 0,
            },
            "error": f"Query failed: {exc}",
        }
    finally:
        conn.close()
