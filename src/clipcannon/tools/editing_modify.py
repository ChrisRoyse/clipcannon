"""Editing MCP tools: clipcannon_modify_edit and clipcannon_auto_trim."""

from __future__ import annotations

import json
import logging
from copy import deepcopy

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.editing.change_classifier import classify_changes
from clipcannon.editing.edl import EditDecisionList, compute_total_duration, validate_edl
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.editing_create import _ensure_render_hint_column
from clipcannon.tools.editing_helpers import (
    apply_changes,
    auto_generate_captions,
    db_path,
    error_response,
    save_edit_version,
    store_edit_segments,
    validate_project,
)

logger = logging.getLogger(__name__)


# ============================================================
# TOOL 2: clipcannon_modify_edit
# ============================================================
async def clipcannon_modify_edit(
    project_id: str,
    edit_id: str,
    changes: dict[str, object],
) -> dict[str, object]:
    """Modify an existing draft edit.

    Loads the current EDL, applies changes (deep merge), re-validates,
    and updates the database. Resets status to draft for re-rendering.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.
        changes: Partial update dict with any of: name, segments,
            captions, crop, audio, metadata, render_settings.

    Returns:
        Modification result dict or error response.
    """
    err = validate_project(project_id, required_status="ready")
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
    finally:
        conn.close()

    if edit_row is None:
        return error_response(
            "EDIT_NOT_FOUND", f"Edit not found: {edit_id}",
            {"edit_id": edit_id, "project_id": project_id},
        )

    current_status = str(edit_row.get("status", ""))
    # Allow modifications on draft and rendered edits — iterative
    # edit-review-fix workflows require modifying after render.
    # Only block if the edit is actively rendering.
    if current_status == "rendering":
        return error_response(
            "INVALID_STATE",
            f"Cannot modify edit while rendering is in progress.",
            {"edit_id": edit_id, "status": current_status},
        )

    try:
        edl_data = json.loads(str(edit_row["edl_json"]))
        current_edl = EditDecisionList(**edl_data)
    except Exception as exc:
        return error_response(
            "INTERNAL_ERROR", f"Failed to parse existing EDL: {exc}",
            {"edit_id": edit_id},
        )

    # Save the current state as a version before applying changes
    save_edit_version(
        db=db,
        edit_id=edit_id,
        edl_json=str(edit_row["edl_json"]),
        changes=changes,
        current_edl=current_edl,
    )

    # Snapshot the EDL before mutation for change classification
    old_edl_snapshot = deepcopy(current_edl)

    updated_fields, segments_changed, err = apply_changes(current_edl, changes)
    if err is not None:
        return err
    if not updated_fields:
        return error_response(
            "INVALID_PARAMETER", "No valid changes provided",
            {"changes_keys": list(changes.keys())},
        )

    validation_errors = validate_edl(current_edl, db)
    if validation_errors:
        return error_response(
            "VALIDATION_ERROR", "Modified EDL validation failed",
            {"errors": validation_errors},  # type: ignore[dict-item]
        )

    # Regenerate caption chunks when the timeline changed, or when a captions
    # update arrived without chunks (otherwise captions would silently vanish).
    if current_edl.captions.enabled and (segments_changed or not current_edl.captions.chunks):
        auto_generate_captions(current_edl, db, project_id, current_edl.segments, edit_id)

    # Classify changes to produce a render hint
    render_hint = classify_changes(old_edl_snapshot, current_edl)

    total_duration_ms = compute_total_duration(current_edl.segments)
    render_hint_json = render_hint.model_dump_json()

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        edl_json = current_edl.model_dump_json()

        # Ensure render_hint_json column exists (migration for existing DBs)
        _ensure_render_hint_column(conn)

        execute(
            conn,
            """UPDATE edits SET
                name = ?, edl_json = ?, total_duration_ms = ?,
                segment_count = ?, captions_enabled = ?, crop_mode = ?,
                thumbnail_timestamp_ms = ?, metadata_title = ?,
                metadata_description = ?, metadata_hashtags = ?,
                render_hint_json = ?,
                status = 'draft',
                updated_at = datetime('now')
            WHERE edit_id = ? AND project_id = ?""",
            (
                current_edl.name, edl_json, total_duration_ms,
                len(current_edl.segments), current_edl.captions.enabled,
                current_edl.crop.mode, current_edl.metadata.thumbnail_timestamp_ms,
                current_edl.metadata.title, current_edl.metadata.description,
                json.dumps(current_edl.metadata.hashtags),
                render_hint_json,
                edit_id, project_id,
            ),
        )
        if segments_changed:
            execute(conn, "DELETE FROM edit_segments WHERE edit_id = ?", (edit_id,))
            store_edit_segments(conn, edit_id, current_edl.segments)
        conn.commit()
    except ClipCannonError:
        raise
    except Exception as exc:
        logger.exception("Failed to update edit %s", edit_id)
        return error_response("INTERNAL_ERROR", f"Failed to update edit: {exc}")
    finally:
        conn.close()

    logger.info("Modified edit %s: updated %s", edit_id, updated_fields)

    return {
        "edit_id": edit_id,
        "status": "draft",
        "updated_fields": updated_fields,
        "segment_count": len(current_edl.segments),
        "total_duration_ms": total_duration_ms,
        "captions_enabled": current_edl.captions.enabled,
        "caption_chunks": len(current_edl.captions.chunks),
        "crop_mode": current_edl.crop.mode,
        "render_hint": render_hint.model_dump(),
    }


# ============================================================
# TOOL 3: clipcannon_auto_trim
# ============================================================
async def clipcannon_auto_trim(
    project_id: str,
    pause_threshold_ms: int = 800,
    merge_gap_ms: int = 200,
    min_segment_ms: int = 500,
) -> dict[str, object]:
    """Analyze transcript and generate trimmed segments removing fillers and pauses."""
    from clipcannon.editing.auto_trim import auto_trim

    err = validate_project(project_id)
    if err is not None:
        return err

    try:
        result = auto_trim(
            db_path=str(db_path(project_id)),
            project_id=project_id,
            pause_threshold_ms=pause_threshold_ms,
            merge_gap_ms=merge_gap_ms,
            min_segment_ms=min_segment_ms,
        )
        return result
    except ValueError as exc:
        return error_response("INVALID_PARAMETER", str(exc))
    except Exception as exc:
        logger.exception("auto_trim failed for %s", project_id)
        return error_response("INTERNAL_ERROR", f"Auto-trim failed: {exc}")
