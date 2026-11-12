"""Editing MCP tools: branch_edit and list_branches."""

from __future__ import annotations

import json
import logging
import secrets
from copy import deepcopy

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.edl import EditDecisionList, RenderSettingsSpec
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.editing_helpers import (
    PLATFORM_PROFILES,
    db_path,
    ensure_branch_columns,
    error_response,
    project_dir,
    store_edit_segments,
    validate_project,
)

logger = logging.getLogger(__name__)


def _project_source_size(project_id: str) -> tuple[int, int]:
    """Source video (width, height) from the project row; 1920x1080 if unknown."""
    conn = get_connection(db_path(project_id), enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn, "SELECT resolution FROM project WHERE project_id = ?", (project_id,),
        )
    finally:
        conn.close()
    try:
        w, h = str((row or {}).get("resolution", "")).lower().split("x")
        return int(w), int(h)
    except ValueError:
        return 1920, 1080


# ============================================================
# TOOL 10: clipcannon_branch_edit
# ============================================================
async def clipcannon_branch_edit(
    project_id: str,
    edit_id: str,
    branch_name: str,
    target_platform: str,
) -> dict[str, object]:
    """Fork an edit into a platform-specific variant.

    Deep-copies the source edit's EDL, creates a new edit with
    a different target platform, and links it via parent_edit_id.
    All segments, captions, effects, overlays are copied.

    Args:
        project_id: Project identifier.
        edit_id: Source edit identifier to branch from.
        branch_name: Name for this branch (e.g., 'instagram').
        target_platform: Target platform for the branched edit.

    Returns:
        Branch result dict with new edit_id and branch_name, or error.
    """
    err = validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    valid_platforms = {
        "tiktok", "instagram_reels", "youtube_shorts",
        "youtube_standard", "youtube_4k", "facebook", "linkedin",
    }
    if target_platform not in valid_platforms:
        return error_response(
            "INVALID_PARAMETER",
            f"Invalid target_platform: {target_platform}. "
            f"Valid: {', '.join(sorted(valid_platforms))}",
            {"target_platform": target_platform},
        )

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        edit_row = fetch_one(
            conn,
            "SELECT * FROM edits WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
    finally:
        conn.close()

    if edit_row is None:
        return error_response(
            "EDIT_NOT_FOUND",
            f"Edit not found: {edit_id}",
            {"edit_id": edit_id, "project_id": project_id},
        )

    # Parse the source EDL and deep-copy it
    try:
        edl_data = json.loads(str(edit_row["edl_json"]))
        source_edl = EditDecisionList(**edl_data)
    except Exception as exc:
        return error_response(
            "INTERNAL_ERROR",
            f"Failed to parse source EDL: {exc}",
            {"edit_id": edit_id},
        )

    # Deep-copy the EDL for the branch
    branched_edl = deepcopy(source_edl)

    # Assign new identity
    new_edit_id = f"edit_{secrets.token_hex(6)}"
    new_profile = PLATFORM_PROFILES.get(target_platform, "tiktok_vertical")

    branched_edl.edit_id = new_edit_id
    branched_edl.target_platform = target_platform  # type: ignore[assignment]
    branched_edl.target_profile = new_profile
    branched_edl.render_settings = RenderSettingsSpec(profile=new_profile)
    branched_edl.status = "draft"  # type: ignore[assignment]

    # Store the branched edit
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        ensure_branch_columns(conn)

        edl_json_str = branched_edl.model_dump_json()
        total_duration_ms = int(edit_row.get("total_duration_ms", 0) or 0)

        execute(
            conn,
            """INSERT INTO edits (
                edit_id, project_id, name, status, target_platform,
                target_profile, edl_json, source_sha256,
                total_duration_ms, segment_count, captions_enabled,
                crop_mode, thumbnail_timestamp_ms,
                metadata_title, metadata_description, metadata_hashtags,
                parent_edit_id, branch_name
            ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_edit_id, project_id,
                f"{edit_row['name']} ({branch_name})",
                target_platform, new_profile,
                edl_json_str, str(edit_row["source_sha256"]),
                total_duration_ms,
                int(edit_row.get("segment_count", 0) or 0),
                bool(edit_row.get("captions_enabled", True)),
                str(edit_row.get("crop_mode", "auto")),
                edit_row.get("thumbnail_timestamp_ms"),
                edit_row.get("metadata_title"),
                edit_row.get("metadata_description"),
                edit_row.get("metadata_hashtags"),
                edit_id,
                branch_name,
            ),
        )

        # Copy segment rows
        store_edit_segments(conn, new_edit_id, branched_edl.segments)

        # Ensure the root edit has branch_name='main' if not set
        execute(
            conn,
            "UPDATE edits SET branch_name = 'main' "
            "WHERE edit_id = ? AND (branch_name IS NULL OR branch_name = '')",
            (edit_id,),
        )

        conn.commit()
    except ClipCannonError:
        raise
    except Exception as exc:
        logger.exception("Failed to store branched edit %s", new_edit_id)
        return error_response("INTERNAL_ERROR", f"Failed to store branch: {exc}")
    finally:
        conn.close()

    # Create edit directory
    edit_dir = project_dir(project_id) / "edits" / new_edit_id
    edit_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Branched edit %s -> %s (branch=%s, platform=%s)",
        edit_id, new_edit_id, branch_name, target_platform,
    )

    return {
        "edit_id": new_edit_id,
        "parent_edit_id": edit_id,
        "branch_name": branch_name,
        "target_platform": target_platform,
        "target_profile": new_profile,
        "segment_count": len(branched_edl.segments),
        "total_duration_ms": total_duration_ms,
        "status": "draft",
    }


# ============================================================
# TOOL 11: clipcannon_list_branches
# ============================================================
async def clipcannon_list_branches(
    project_id: str,
    edit_id: str,
) -> dict[str, object]:
    """List all branches of an edit.

    Finds all edits where parent_edit_id matches OR the edit_id
    itself matches. Returns the root edit and all branches.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier (root or any branch).

    Returns:
        Dict with branches list, or error.
    """
    err = validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        ensure_branch_columns(conn)

        # First, find the root edit_id. If the given edit_id has a
        # parent_edit_id, use that as the root. Otherwise, it IS the root.
        row = fetch_one(
            conn,
            "SELECT edit_id, parent_edit_id FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
    finally:
        conn.close()

    if row is None:
        return error_response(
            "EDIT_NOT_FOUND",
            f"Edit not found: {edit_id}",
            {"edit_id": edit_id, "project_id": project_id},
        )

    parent = row.get("parent_edit_id")
    root_id = str(parent) if parent else str(row["edit_id"])

    # Fetch the root and all branches
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        branches = fetch_all(
            conn,
            "SELECT edit_id, branch_name, target_platform, status, created_at "
            "FROM edits WHERE project_id = ? "
            "AND (edit_id = ? OR parent_edit_id = ?) "
            "ORDER BY created_at",
            (project_id, root_id, root_id),
        )
    finally:
        conn.close()

    branch_list: list[dict[str, object]] = []
    for b in branches:
        branch_list.append({
            "edit_id": str(b["edit_id"]),
            "branch_name": str(b.get("branch_name") or "main"),
            "target_platform": str(b["target_platform"]),
            "status": str(b["status"]),
            "created_at": str(b["created_at"]),
        })

    return {
        "root_edit_id": root_id,
        "branch_count": len(branch_list),
        "branches": branch_list,
    }
