"""Editing MCP tools for ClipCannon.

Provides tools for creating, modifying, and listing edit decision
lists (EDLs). Each edit represents a planned output clip with segments,
captions, crop, audio, and metadata specifications.
"""

from __future__ import annotations

import json
import logging
import secrets
import time

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.edl import (
    EditDecisionList,
    OverlaySpec,
    RenderSettingsSpec,
    compute_total_duration,
    validate_edl,
)
from clipcannon.editing.metadata_gen import generate_metadata
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.editing_defs import EDITING_TOOL_DEFINITIONS
from clipcannon.tools.editing_helpers import (
    PLATFORM_PROFILES,
    apply_changes,
    auto_generate_captions,
    build_audio_spec,
    build_caption_spec,
    build_crop_spec,
    build_metadata_spec,
    build_segments,
    db_path,
    error_response,
    project_dir,
    store_edit_segments,
    validate_project,
)

__all__ = [
    "EDITING_TOOL_DEFINITIONS",
    "dispatch_editing_tool",
]

logger = logging.getLogger(__name__)


# ============================================================
# TOOL 1: clipcannon_create_edit
# ============================================================
async def clipcannon_create_edit(
    project_id: str,
    name: str,
    target_platform: str,
    segments: list[dict[str, object]],
    captions: dict[str, object] | None = None,
    crop: dict[str, object] | None = None,
    audio: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Create a new edit from an EDL specification.

    Validates the project, builds the EDL from parameters, auto-generates
    caption chunks if needed, and stores the edit in the database.

    Args:
        project_id: Project identifier.
        name: Human-readable edit name.
        target_platform: Target platform (tiktok, instagram_reels, etc.).
        segments: Array of segment dicts with source_start_ms, source_end_ms, etc.
        captions: Optional caption configuration.
        crop: Optional crop configuration.
        audio: Optional audio configuration.
        metadata: Optional metadata (title, description, hashtags).

    Returns:
        Edit creation result dict or error response.
    """
    start_time = time.monotonic()

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

    if not segments:
        return error_response(
            "INVALID_PARAMETER",
            "At least one segment is required",
            {"segments_count": 0},
        )

    db = db_path(project_id)

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        project_row = fetch_one(
            conn,
            "SELECT source_sha256 FROM project WHERE project_id = ?",
            (project_id,),
        )
    finally:
        conn.close()

    if project_row is None:
        return error_response("PROJECT_NOT_FOUND", f"No project record: {project_id}")

    source_sha256 = str(project_row["source_sha256"])
    edit_id = f"edit_{secrets.token_hex(6)}"

    try:
        segment_specs = build_segments(segments)
    except (ValueError, KeyError, TypeError) as exc:
        return error_response(
            "INVALID_PARAMETER",
            f"Invalid segment data: {exc}",
            {"error": str(exc)},
        )

    caption_spec = build_caption_spec(captions)
    crop_spec = build_crop_spec(crop, target_platform)
    audio_spec = build_audio_spec(audio)
    metadata_spec = build_metadata_spec(metadata)
    target_profile = PLATFORM_PROFILES.get(target_platform, "tiktok_vertical")

    try:
        edl = EditDecisionList(
            edit_id=edit_id,
            project_id=project_id,
            name=name,
            status="draft",
            source_sha256=source_sha256,
            target_platform=target_platform,  # type: ignore[arg-type]
            target_profile=target_profile,
            segments=segment_specs,
            captions=caption_spec,
            crop=crop_spec,
            audio=audio_spec,
            overlays=OverlaySpec(),
            metadata=metadata_spec,
            render_settings=RenderSettingsSpec(profile=target_profile),
        )
    except Exception as exc:
        return error_response(
            "INVALID_PARAMETER",
            f"Failed to build EDL: {exc}",
            {"error": str(exc)},
        )

    validation_errors = validate_edl(edl, db)
    if validation_errors:
        return error_response(
            "VALIDATION_ERROR",
            "EDL validation failed",
            {"errors": validation_errors},  # type: ignore[dict-item]
        )

    # Auto-generate captions if enabled and no chunks provided
    if caption_spec.enabled and not caption_spec.chunks:
        auto_generate_captions(edl, db, project_id, segment_specs, edit_id)

    total_duration_ms = compute_total_duration(segment_specs)

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        edl_json = edl.model_dump_json()
        execute(
            conn,
            """INSERT INTO edits (
                edit_id, project_id, name, status, target_platform,
                target_profile, edl_json, source_sha256,
                total_duration_ms, segment_count, captions_enabled,
                crop_mode, thumbnail_timestamp_ms,
                metadata_title, metadata_description, metadata_hashtags
            ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                edit_id, project_id, name, target_platform, target_profile,
                edl_json, source_sha256, total_duration_ms,
                len(segment_specs), caption_spec.enabled, crop_spec.mode,
                metadata_spec.thumbnail_timestamp_ms,
                metadata_spec.title, metadata_spec.description,
                json.dumps(metadata_spec.hashtags),
            ),
        )
        store_edit_segments(conn, edit_id, segment_specs)
        conn.commit()
    except ClipCannonError:
        raise
    except Exception as exc:
        logger.exception("Failed to store edit %s", edit_id)
        return error_response("INTERNAL_ERROR", f"Failed to store edit: {exc}")
    finally:
        conn.close()

    edit_dir = project_dir(project_id) / "edits" / edit_id
    edit_dir.mkdir(parents=True, exist_ok=True)

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    logger.info("Created edit %s for project %s in %dms", edit_id, project_id, elapsed_ms)

    return {
        "edit_id": edit_id,
        "status": "draft",
        "name": name,
        "target_platform": target_platform,
        "target_profile": target_profile,
        "segment_count": len(segment_specs),
        "total_duration_ms": total_duration_ms,
        "captions_enabled": caption_spec.enabled,
        "caption_chunks": len(edl.captions.chunks),
        "crop_mode": crop_spec.mode,
        "elapsed_ms": elapsed_ms,
    }


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
    and updates the database. Only draft edits can be modified.

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
    if current_status != "draft":
        return error_response(
            "INVALID_STATE",
            f"Cannot modify edit in '{current_status}' status. Only 'draft' edits can be modified.",
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

    if segments_changed and current_edl.captions.enabled:
        auto_generate_captions(current_edl, db, project_id, current_edl.segments, edit_id)

    total_duration_ms = compute_total_duration(current_edl.segments)

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        edl_json = current_edl.model_dump_json()
        execute(
            conn,
            """UPDATE edits SET
                name = ?, edl_json = ?, total_duration_ms = ?,
                segment_count = ?, captions_enabled = ?, crop_mode = ?,
                thumbnail_timestamp_ms = ?, metadata_title = ?,
                metadata_description = ?, metadata_hashtags = ?,
                updated_at = datetime('now')
            WHERE edit_id = ? AND project_id = ?""",
            (
                current_edl.name, edl_json, total_duration_ms,
                len(current_edl.segments), current_edl.captions.enabled,
                current_edl.crop.mode, current_edl.metadata.thumbnail_timestamp_ms,
                current_edl.metadata.title, current_edl.metadata.description,
                json.dumps(current_edl.metadata.hashtags),
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
    }


# ============================================================
# TOOL 3: clipcannon_list_edits
# ============================================================
async def clipcannon_list_edits(
    project_id: str,
    status_filter: str = "all",
) -> dict[str, object]:
    """List edits for a project with optional status filtering.

    Args:
        project_id: Project identifier.
        status_filter: Filter by status (all, draft, rendering, rendered,
            approved, rejected). Default: all.

    Returns:
        List of edit summaries or error response.
    """
    err = validate_project(project_id, required_status=None)
    if err is not None:
        return err

    valid_statuses = {"all", "draft", "rendering", "rendered", "approved", "rejected", "failed"}
    if status_filter not in valid_statuses:
        return error_response(
            "INVALID_PARAMETER",
            f"Invalid status_filter: {status_filter}. "
            f"Valid: {', '.join(sorted(valid_statuses))}",
            {"status_filter": status_filter},
        )

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        base_sql = """SELECT edit_id, name, status, target_platform,
                target_profile, total_duration_ms, segment_count,
                captions_enabled, crop_mode,
                metadata_title, created_at, updated_at
            FROM edits WHERE project_id = ?"""

        if status_filter == "all":
            rows = fetch_all(conn, base_sql + " ORDER BY created_at DESC", (project_id,))
        else:
            rows = fetch_all(
                conn, base_sql + " AND status = ? ORDER BY created_at DESC",
                (project_id, status_filter),
            )
    finally:
        conn.close()

    edits = [dict(row) for row in rows]

    return {
        "project_id": project_id,
        "status_filter": status_filter,
        "edits": edits,
        "total": len(edits),
    }


# ============================================================
# TOOL 4: clipcannon_generate_metadata
# ============================================================
async def clipcannon_generate_metadata(
    project_id: str,
    edit_id: str,
    target_platform: str | None = None,
) -> dict[str, object]:
    """Generate platform-specific metadata for an edit.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.
        target_platform: Override platform (defaults to edit's target_platform).

    Returns:
        Generated metadata dict or error response.
    """
    start_time = time.monotonic()

    err = validate_project(project_id, required_status=None)
    if err is not None:
        return err

    db = db_path(project_id)

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        edit_row = fetch_one(
            conn,
            "SELECT edit_id, target_platform, edl_json FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
    finally:
        conn.close()

    if edit_row is None:
        return error_response(
            "EDIT_NOT_FOUND", f"Edit not found: {edit_id}",
            {"edit_id": edit_id, "project_id": project_id},
        )

    platform = target_platform or str(edit_row.get("target_platform", "tiktok"))

    try:
        edl_data = json.loads(str(edit_row["edl_json"]))
    except (json.JSONDecodeError, TypeError) as exc:
        return error_response(
            "INTERNAL_ERROR", f"Failed to parse EDL JSON: {exc}",
            {"edit_id": edit_id},
        )

    try:
        result = generate_metadata(
            project_id=project_id, edit_id=edit_id,
            target_platform=platform, db_path=db, edl_json=edl_data,
        )
    except Exception as exc:
        logger.exception("Metadata generation failed for edit %s", edit_id)
        return error_response(
            "GENERATION_FAILED", f"Metadata generation failed: {exc}",
            {"edit_id": edit_id},
        )

    conn = get_connection(db, enable_vec=False, dict_rows=False)
    try:
        execute(
            conn,
            """UPDATE edits SET
                metadata_title = ?, metadata_description = ?,
                metadata_hashtags = ?, thumbnail_timestamp_ms = ?,
                updated_at = datetime('now')
            WHERE edit_id = ? AND project_id = ?""",
            (result.title, result.description,
             json.dumps(result.hashtags), result.thumbnail_timestamp_ms,
             edit_id, project_id),
        )
        conn.commit()
    except Exception as exc:
        logger.exception("Failed to update metadata for edit %s", edit_id)
        return error_response("INTERNAL_ERROR", f"Failed to store metadata: {exc}")
    finally:
        conn.close()

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    logger.info("Generated metadata for edit %s in %dms", edit_id, elapsed_ms)

    return {
        "edit_id": edit_id,
        "target_platform": platform,
        "title": result.title,
        "description": result.description,
        "hashtags": result.hashtags,
        "thumbnail_timestamp_ms": result.thumbnail_timestamp_ms,
        "elapsed_ms": elapsed_ms,
    }


# ============================================================
# DISPATCH
# ============================================================
async def dispatch_editing_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch an editing tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_create_edit":
        return await clipcannon_create_edit(
            project_id=str(arguments["project_id"]),
            name=str(arguments["name"]),
            target_platform=str(arguments["target_platform"]),
            segments=list(arguments["segments"]),  # type: ignore[arg-type]
            captions=arguments.get("captions"),  # type: ignore[arg-type]
            crop=arguments.get("crop"),  # type: ignore[arg-type]
            audio=arguments.get("audio"),  # type: ignore[arg-type]
            metadata=arguments.get("metadata"),  # type: ignore[arg-type]
        )
    if name == "clipcannon_modify_edit":
        return await clipcannon_modify_edit(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            changes=dict(arguments["changes"]),  # type: ignore[arg-type]
        )
    if name == "clipcannon_list_edits":
        return await clipcannon_list_edits(
            project_id=str(arguments["project_id"]),
            status_filter=str(arguments.get("status_filter", "all")),
        )
    if name == "clipcannon_generate_metadata":
        platform_raw = arguments.get("target_platform")
        return await clipcannon_generate_metadata(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            target_platform=str(platform_raw) if platform_raw is not None else None,
        )

    return error_response("INTERNAL_ERROR", f"Unknown editing tool: {name}")
