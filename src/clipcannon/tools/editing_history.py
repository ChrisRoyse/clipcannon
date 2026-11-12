"""Editing MCP tools: edit_history, revert_edit and apply_feedback."""

from __future__ import annotations

import json
import logging
import secrets

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.edl import EditDecisionList, compute_total_duration
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.editing_branches import _project_source_size
from clipcannon.tools.editing_helpers import (
    auto_generate_captions,
    db_path,
    ensure_edit_versions_table,
    error_response,
    store_edit_segments,
    validate_project,
)
from clipcannon.tools.editing_modify import clipcannon_modify_edit

logger = logging.getLogger(__name__)


# ============================================================
# TOOL 7: clipcannon_edit_history
# ============================================================
async def clipcannon_edit_history(
    project_id: str,
    edit_id: str,
) -> dict[str, object]:
    """List version history for an edit.

    Returns all saved versions ordered by version_number descending,
    plus the current state as version 0.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.

    Returns:
        Dict with versions list or error response.
    """
    err = validate_project(project_id)
    if err is not None:
        return err

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        edit_row = fetch_one(
            conn,
            "SELECT edit_id, name, status, updated_at FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if edit_row is None:
            return error_response(
                "EDIT_NOT_FOUND", f"Edit not found: {edit_id}",
                {"edit_id": edit_id, "project_id": project_id},
            )

        ensure_edit_versions_table(conn)

        version_rows = fetch_all(
            conn,
            "SELECT version_id, version_number, change_description, created_at "
            "FROM edit_versions WHERE edit_id = ? "
            "ORDER BY version_number DESC",
            (edit_id,),
        )
    finally:
        conn.close()

    versions: list[dict[str, object]] = [
        {
            "version_id": "current",
            "version_number": 0,
            "change_description": "Current state",
            "created_at": str(edit_row.get("updated_at", "")),
        },
    ]
    for row in version_rows:
        versions.append({
            "version_id": str(row["version_id"]),
            "version_number": int(row["version_number"]),
            "change_description": str(row["change_description"] or ""),
            "created_at": str(row["created_at"]),
        })

    return {
        "edit_id": edit_id,
        "name": str(edit_row.get("name", "")),
        "status": str(edit_row.get("status", "")),
        "version_count": len(version_rows),
        "versions": versions,
    }


# ============================================================
# TOOL 8: clipcannon_revert_edit
# ============================================================
async def clipcannon_revert_edit(
    project_id: str,
    edit_id: str,
    version_number: int,
) -> dict[str, object]:
    """Revert an edit to a previous version.

    Saves the current state as a new version (so the revert itself
    is versioned), then replaces the current EDL with the target
    version's EDL. Resets status to draft and regenerates captions
    if segments changed.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.
        version_number: The version number to revert to.

    Returns:
        Revert result dict or error response.
    """
    err = validate_project(project_id)
    if err is not None:
        return err

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        edit_row = fetch_one(
            conn,
            "SELECT * FROM edits WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if edit_row is None:
            return error_response(
                "EDIT_NOT_FOUND", f"Edit not found: {edit_id}",
                {"edit_id": edit_id, "project_id": project_id},
            )

        current_status = str(edit_row.get("status", ""))
        if current_status == "rendering":
            return error_response(
                "INVALID_STATE",
                "Cannot revert edit while rendering is in progress.",
                {"edit_id": edit_id, "status": current_status},
            )

        ensure_edit_versions_table(conn)

        target_row = fetch_one(
            conn,
            "SELECT version_id, edl_json FROM edit_versions "
            "WHERE edit_id = ? AND version_number = ?",
            (edit_id, version_number),
        )
        if target_row is None:
            return error_response(
                "VERSION_NOT_FOUND",
                f"Version {version_number} not found for edit {edit_id}",
                {"edit_id": edit_id, "version_number": version_number},
            )

        # Save current state as a new version before reverting
        current_edl_json = str(edit_row["edl_json"])
        max_row = fetch_one(
            conn,
            "SELECT MAX(version_number) as max_ver FROM edit_versions "
            "WHERE edit_id = ?",
            (edit_id,),
        )
        next_ver = (int(max_row["max_ver"]) + 1) if max_row and max_row["max_ver"] is not None else 1
        revert_version_id = f"ver_{secrets.token_hex(6)}"

        execute(
            conn,
            """INSERT INTO edit_versions (
                version_id, edit_id, parent_version_id, version_number,
                edl_json, change_description
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                revert_version_id, edit_id, None, next_ver,
                current_edl_json,
                f"State before revert to version {version_number}",
            ),
        )

        # Restore the target version's EDL
        target_edl_json = str(target_row["edl_json"])
        target_edl = EditDecisionList(**json.loads(target_edl_json))

        # Regenerate captions if segments exist and captions enabled
        if target_edl.captions.enabled and target_edl.segments:
            auto_generate_captions(
                target_edl, db, project_id, target_edl.segments, edit_id,
            )

        total_duration_ms = compute_total_duration(target_edl.segments)
        restored_edl_json = target_edl.model_dump_json()

        execute(
            conn,
            """UPDATE edits SET
                name = ?, edl_json = ?, total_duration_ms = ?,
                segment_count = ?, captions_enabled = ?, crop_mode = ?,
                thumbnail_timestamp_ms = ?, metadata_title = ?,
                metadata_description = ?, metadata_hashtags = ?,
                status = 'draft',
                updated_at = datetime('now')
            WHERE edit_id = ? AND project_id = ?""",
            (
                target_edl.name, restored_edl_json, total_duration_ms,
                len(target_edl.segments), target_edl.captions.enabled,
                target_edl.crop.mode, target_edl.metadata.thumbnail_timestamp_ms,
                target_edl.metadata.title, target_edl.metadata.description,
                json.dumps(target_edl.metadata.hashtags),
                edit_id, project_id,
            ),
        )

        # Rebuild edit_segments
        execute(conn, "DELETE FROM edit_segments WHERE edit_id = ?", (edit_id,))
        store_edit_segments(conn, edit_id, target_edl.segments)
        conn.commit()
    except ClipCannonError:
        raise
    except Exception as exc:
        logger.exception("Failed to revert edit %s to version %d", edit_id, version_number)
        return error_response("INTERNAL_ERROR", f"Failed to revert edit: {exc}")
    finally:
        conn.close()

    logger.info(
        "Reverted edit %s to version %d (saved current as version %d)",
        edit_id, version_number, next_ver,
    )

    return {
        "edit_id": edit_id,
        "reverted_to_version": version_number,
        "saved_current_as_version": next_ver,
        "status": "draft",
        "name": target_edl.name,
        "segment_count": len(target_edl.segments),
        "total_duration_ms": total_duration_ms,
    }


# ============================================================
# TOOL 9: clipcannon_apply_feedback
# ============================================================
async def clipcannon_apply_feedback(
    project_id: str,
    edit_id: str,
    feedback: str | None = None,
    operations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Apply feedback to an edit as typed, validated operations.

    The plan comes from ``operations`` when given; otherwise ``feedback`` is
    planned by the client's model (MCP sampling); without a planner the call
    fails closed and nothing changes. The plan is converted to merged EDL
    changes and applied via modify_edit.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.
        feedback: Free-text feedback about the edit.
        operations: Typed operations (see FeedbackPlan) to apply directly.

    Returns:
        Dict with parser, plan, changes_applied, modify_result and
        special_actions (follow-up tool calls for color/overlay/motion).
    """
    from clipcannon.editing.feedback_ops import OpError, ops_to_changes
    from clipcannon.rendering.profiles import get_profile
    from clipcannon.tools.feedback_apply import PlanError, resolve_plan

    err = validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    db = db_path(project_id)

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        edit_row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
    finally:
        conn.close()

    if edit_row is None:
        return error_response(
            "EDIT_NOT_FOUND", f"Edit not found: {edit_id}",
            {"edit_id": edit_id, "project_id": project_id},
        )

    current_status = str(edit_row.get("status", ""))
    if current_status == "rendering":
        return error_response(
            "INVALID_STATE",
            "Cannot apply feedback while rendering is in progress.",
            {"edit_id": edit_id, "status": current_status},
        )

    try:
        edl_data = json.loads(str(edit_row["edl_json"]))
        edl = EditDecisionList(**edl_data)
    except Exception as exc:
        return error_response(
            "INTERNAL_ERROR", f"Failed to parse existing EDL: {exc}",
            {"edit_id": edit_id},
        )

    try:
        plan, parser, diagnostics = await resolve_plan(edl, feedback, operations)
    except PlanError as exc:
        return error_response(exc.code, str(exc), exc.details)

    source_size = _project_source_size(project_id)
    profile = get_profile(edl.render_settings.profile)
    try:
        changes, special_actions = ops_to_changes(
            plan, edl, source_size=source_size,
            canvas_size=(profile.width, profile.height),
        )
    except OpError as exc:
        return error_response(
            "INVALID_OPERATION", str(exc),
            {"parser": parser, "plan": plan.model_dump(),
             "remediation": "use segment ids and ranges from get_edit; nothing was changed"},
        )

    modify_result: dict[str, object] = {}
    if changes:
        modify_result = await clipcannon_modify_edit(
            project_id=project_id, edit_id=edit_id, changes=changes,
        )
        if isinstance(modify_result, dict) and "error" in modify_result:
            return modify_result
    elif not special_actions:
        return error_response(
            "NO_CHANGES", "Feedback was parsed but produced no applicable changes.",
            {"parser": parser, "plan": plan.model_dump()},
        )

    for action in special_actions:
        action["parameters"] = {"project_id": project_id, "edit_id": edit_id,
                                **action["parameters"]}

    return {
        "parser": parser,
        "plan": plan.model_dump(),
        "changed_fields": sorted(changes),
        "modify_result": modify_result,
        "special_actions": special_actions or None,
        **({"diagnostics": diagnostics} if diagnostics else {}),
    }
