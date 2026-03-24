"""Editing MCP tools for ClipCannon.

Provides tools for creating, modifying, and listing edit decision
lists (EDLs). Each edit represents a planned output clip with segments,
captions, crop, audio, and metadata specifications.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3 as _sqlite3
import time
from copy import deepcopy

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.change_classifier import RenderHint, classify_changes
from clipcannon.editing.edl import (
    CanvasSpec,
    ColorSpec,
    EditDecisionList,
    MotionSpec,
    OverlaySpec,
    RenderSettingsSpec,
    compute_total_duration,
    validate_edl,
)
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
    ensure_branch_columns,
    ensure_edit_versions_table,
    error_response,
    project_dir,
    save_edit_version,
    store_edit_segments,
    validate_project,
)

__all__ = [
    "EDITING_TOOL_DEFINITIONS",
    "dispatch_editing_tool",
]

logger = logging.getLogger(__name__)


# ============================================================
# DB MIGRATION HELPERS
# ============================================================
def _ensure_render_hint_column(conn: _sqlite3.Connection) -> None:
    """Ensure the render_hint_json column exists on the edits table.

    Handles migration for existing databases created before the
    change impact classification feature was added.

    Args:
        conn: SQLite connection.
    """
    try:
        conn.execute("SELECT render_hint_json FROM edits LIMIT 1")
    except _sqlite3.OperationalError:
        conn.execute(
            "ALTER TABLE edits ADD COLUMN render_hint_json TEXT"
        )
        logger.info("Added render_hint_json column to edits table (migration).")


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
    canvas: dict[str, object] | None = None,
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
        canvas: Optional canvas compositing configuration for full layout control.
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

    # Build canvas spec if provided (full AI compositing control)
    canvas_spec = CanvasSpec(**(canvas or {})) if canvas else CanvasSpec()

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
            canvas=canvas_spec,
            audio=audio_spec,
            overlays=[],
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

    response: dict[str, object] = {
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

    # ------------------------------------------------------------------
    # Auto-validate narrative coherence for non-contiguous segments
    # ------------------------------------------------------------------
    try:
        narrative_warnings: list[str] = []
        if len(segment_specs) > 1:
            nv_conn = get_connection(db, enable_vec=False, dict_rows=True)
            try:
                for i in range(len(segment_specs) - 1):
                    current_end = segment_specs[i].source_end_ms
                    next_start = segment_specs[i + 1].source_start_ms
                    gap_ms = next_start - current_end

                    if gap_ms > 1000:
                        # Query what words are being skipped in the gap
                        try:
                            gap_text_rows = fetch_all(
                                nv_conn,
                                "SELECT text FROM transcript_segments WHERE project_id = ? "
                                "AND start_ms >= ? AND end_ms <= ? ORDER BY start_ms",
                                (project_id, current_end, next_start),
                            )
                            gap_words = sum(
                                len(str(r["text"]).split()) for r in gap_text_rows
                            )
                            if gap_words > 20:
                                narrative_warnings.append(
                                    f"Gap between segments {i+1}-{i+2}: "
                                    f"{gap_ms/1000:.0f}s skipped ({gap_words} words)"
                                )
                        except Exception:
                            pass

                    # Check thought completion of current segment
                    try:
                        last_text_row = fetch_one(
                            nv_conn,
                            "SELECT text FROM transcript_segments WHERE project_id = ? "
                            "AND start_ms < ? AND end_ms > ? "
                            "ORDER BY start_ms DESC LIMIT 1",
                            (project_id, current_end, segment_specs[i].source_start_ms),
                        )
                        if last_text_row:
                            last_text = str(last_text_row["text"]).strip()
                            if last_text and not last_text.endswith((".", "!", "?")):
                                narrative_warnings.append(
                                    f"Segment {i+1}: may cut mid-thought "
                                    f"(last text: '...{last_text[-40:]}')"
                                )
                    except Exception:
                        pass
            finally:
                nv_conn.close()

        response["narrative_warnings"] = narrative_warnings if narrative_warnings else None
    except Exception:
        # Never let narrative validation break edit creation
        response["narrative_warnings"] = None

    return response


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

    if segments_changed and current_edl.captions.enabled:
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


# ============================================================
# TOOL 4: clipcannon_color_adjust
# ============================================================
async def clipcannon_color_adjust(
    project_id: str,
    edit_id: str,
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    gamma: float = 1.0,
    hue_shift: float = 0.0,
    segment_id: int | None = None,
) -> dict[str, object]:
    """Apply color grading to an edit globally or per-segment."""
    err = validate_project(project_id)
    if err is not None:
        return err

    try:
        color = ColorSpec(
            brightness=brightness, contrast=contrast,
            saturation=saturation, gamma=gamma, hue_shift=hue_shift,
        )
    except Exception as exc:
        return error_response("INVALID_PARAMETER", f"Invalid color values: {exc}")

    # Load existing EDL
    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if row is None:
            return error_response("EDIT_NOT_FOUND", f"Edit not found: {edit_id}")
        if row["status"] != "draft":
            return error_response("INVALID_STATE", f"Edit must be draft, is: {row['status']}")

        edl = EditDecisionList(**json.loads(row["edl_json"]))

        if segment_id is not None:
            # Apply to specific segment
            found = False
            for seg in edl.segments:
                if seg.segment_id == segment_id:
                    seg.color = color
                    found = True
                    break
            if not found:
                return error_response("SEGMENT_NOT_FOUND", f"Segment {segment_id} not found")
            scope = f"segment {segment_id}"
        else:
            # Apply globally
            edl.color = color
            scope = "global"

        # Save back
        execute(
            conn,
            "UPDATE edits SET edl_json = ?,"
            " updated_at = datetime('now') WHERE edit_id = ?",
            (edl.model_dump_json(), edit_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "edit_id": edit_id,
        "scope": scope,
        "color": color.model_dump(),
        "message": f"Color grading applied ({scope})",
    }


# ============================================================
# TOOL 5: clipcannon_add_motion
# ============================================================
async def clipcannon_add_motion(
    project_id: str,
    edit_id: str,
    segment_id: int,
    effect: str,
    start_scale: float = 1.0,
    end_scale: float = 1.3,
    easing: str = "linear",
) -> dict[str, object]:
    """Add motion effect to a segment."""
    err = validate_project(project_id)
    if err is not None:
        return err

    try:
        motion = MotionSpec(
            effect=effect,
            start_scale=start_scale,
            end_scale=end_scale,
            easing=easing,
        )
    except Exception as exc:
        return error_response("INVALID_PARAMETER", f"Invalid motion values: {exc}")

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if row is None:
            return error_response("EDIT_NOT_FOUND", f"Edit not found: {edit_id}")
        if row["status"] != "draft":
            return error_response("INVALID_STATE", f"Edit must be draft, is: {row['status']}")

        edl = EditDecisionList(**json.loads(row["edl_json"]))

        found = False
        for seg in edl.segments:
            if seg.segment_id == segment_id:
                seg.motion = motion
                found = True
                break
        if not found:
            return error_response("SEGMENT_NOT_FOUND", f"Segment {segment_id} not found")

        execute(
            conn,
            "UPDATE edits SET edl_json = ?,"
            " updated_at = datetime('now') WHERE edit_id = ?",
            (edl.model_dump_json(), edit_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "edit_id": edit_id,
        "segment_id": segment_id,
        "motion": motion.model_dump(),
        "message": f"Motion effect '{effect}' applied to segment {segment_id}",
    }


# ============================================================
# TOOL 6: clipcannon_add_overlay
# ============================================================
async def clipcannon_add_overlay(
    project_id: str,
    edit_id: str,
    overlay_type: str,
    text: str,
    start_ms: int,
    end_ms: int,
    subtitle: str = "",
    position: str = "bottom_left",
    opacity: float = 1.0,
    font_size: int = 36,
    text_color: str = "#FFFFFF",
    bg_color: str = "#000000",
    bg_opacity: float = 0.7,
    animation: str = "fade_in",
    animation_duration_ms: int = 500,
) -> dict[str, object]:
    """Add a visual overlay to an edit."""
    err = validate_project(project_id)
    if err is not None:
        return err

    try:
        overlay = OverlaySpec(
            overlay_type=overlay_type, text=text, subtitle=subtitle,
            position=position, start_ms=start_ms, end_ms=end_ms,
            opacity=opacity, font_size=font_size, text_color=text_color,
            bg_color=bg_color, bg_opacity=bg_opacity, animation=animation,
            animation_duration_ms=animation_duration_ms,
        )
    except Exception as exc:
        return error_response("INVALID_PARAMETER", f"Invalid overlay: {exc}")

    db = db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edl_json, status FROM edits "
            "WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if row is None:
            return error_response("EDIT_NOT_FOUND", f"Edit not found: {edit_id}")
        if row["status"] != "draft":
            return error_response("INVALID_STATE", f"Edit must be draft, is: {row['status']}")

        edl = EditDecisionList(**json.loads(row["edl_json"]))
        edl.overlays.append(overlay)

        execute(
            conn,
            "UPDATE edits SET edl_json = ?,"
            " updated_at = datetime('now') WHERE edit_id = ?",
            (edl.model_dump_json(), edit_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "edit_id": edit_id,
        "overlay_count": len(edl.overlays),
        "overlay": overlay.model_dump(),
        "message": f"Added {overlay_type} overlay to edit",
    }


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
    feedback: str,
) -> dict[str, object]:
    """Apply natural language feedback to an edit.

    Parses feedback text into a structured intent, converts to EDL
    changes, and applies via modify_edit. Returns the parsed intent
    and modification result.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.
        feedback: Natural language feedback about the video edit.

    Returns:
        Dict with parsed_intent, changes_applied, and modify_result.
    """
    from clipcannon.tools.feedback import (
        intent_to_changes,
        parse_feedback,
    )

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

    # Parse the feedback into a structured intent
    intent = parse_feedback(feedback, edl)

    intent_dump = intent.model_dump()

    # Check confidence threshold
    if intent.confidence < 0.3:
        return error_response(
            "LOW_CONFIDENCE",
            f"Could not confidently parse feedback: {feedback!r}",
            {
                "parsed_intent": intent_dump,
                "confidence": intent.confidence,
                "hint": "Try being more specific, e.g. 'the cut at 0:15 is too abrupt'",
            },
        )

    # Convert intent to changes dict
    changes = intent_to_changes(intent, edl)
    if not changes:
        return error_response(
            "NO_CHANGES",
            "Feedback was parsed but produced no applicable changes.",
            {"parsed_intent": intent_dump},
        )

    # Filter out internal-only keys (prefixed with _) for modify_edit
    modify_changes = {k: v for k, v in changes.items() if not k.startswith("_")}

    # Apply changes via modify_edit if there are standard changes
    modify_result: dict[str, object] = {}
    if modify_changes:
        modify_result = await clipcannon_modify_edit(
            project_id=project_id,
            edit_id=edit_id,
            changes=modify_changes,
        )

    # Collect any special actions that need separate tool calls
    special_actions: list[dict[str, object]] = []
    if "_color" in changes:
        special_actions.append({
            "action": "color_adjust",
            "parameters": changes["_color"],
        })
    if "_overlay" in changes:
        special_actions.append({
            "action": "add_overlay",
            "parameters": changes["_overlay"],
        })
    if "_motion_targets" in changes:
        special_actions.append({
            "action": "add_motion",
            "parameters": changes["_motion_targets"],
        })

    return {
        "parsed_intent": intent_dump,
        "changes_applied": changes,
        "modify_result": modify_result,
        "special_actions": special_actions if special_actions else None,
    }


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
            canvas=arguments.get("canvas"),  # type: ignore[arg-type]
            audio=arguments.get("audio"),  # type: ignore[arg-type]
            metadata=arguments.get("metadata"),  # type: ignore[arg-type]
        )
    if name == "clipcannon_modify_edit":
        return await clipcannon_modify_edit(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            changes=dict(arguments["changes"]),  # type: ignore[arg-type]
        )
    if name == "clipcannon_auto_trim":
        return await clipcannon_auto_trim(
            str(arguments["project_id"]),
            int(arguments.get("pause_threshold_ms", 800)),
            int(arguments.get("merge_gap_ms", 200)),
            int(arguments.get("min_segment_ms", 500)),
        )
    if name == "clipcannon_color_adjust":
        return await clipcannon_color_adjust(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            float(arguments.get("brightness", 0.0)),
            float(arguments.get("contrast", 1.0)),
            float(arguments.get("saturation", 1.0)),
            float(arguments.get("gamma", 1.0)),
            float(arguments.get("hue_shift", 0.0)),
            int(arguments["segment_id"]) if arguments.get("segment_id") is not None else None,
        )
    if name == "clipcannon_add_motion":
        return await clipcannon_add_motion(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            int(arguments["segment_id"]),
            str(arguments["effect"]),
            float(arguments.get("start_scale", 1.0)),
            float(arguments.get("end_scale", 1.3)),
            str(arguments.get("easing", "linear")),
        )
    if name == "clipcannon_add_overlay":
        return await clipcannon_add_overlay(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            str(arguments["overlay_type"]),
            str(arguments["text"]),
            int(arguments["start_ms"]),
            int(arguments["end_ms"]),
            str(arguments.get("subtitle", "")),
            str(arguments.get("position", "bottom_left")),
            float(arguments.get("opacity", 1.0)),
            int(arguments.get("font_size", 36)),
            str(arguments.get("text_color", "#FFFFFF")),
            str(arguments.get("bg_color", "#000000")),
            float(arguments.get("bg_opacity", 0.7)),
            str(arguments.get("animation", "fade_in")),
            int(arguments.get("animation_duration_ms", 500)),
        )
    if name == "clipcannon_edit_history":
        return await clipcannon_edit_history(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
        )
    if name == "clipcannon_revert_edit":
        return await clipcannon_revert_edit(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            int(arguments["version_number"]),
        )
    if name == "clipcannon_apply_feedback":
        return await clipcannon_apply_feedback(
            str(arguments["project_id"]),
            str(arguments["edit_id"]),
            str(arguments["feedback"]),
        )
    if name == "clipcannon_branch_edit":
        return await clipcannon_branch_edit(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            branch_name=str(arguments["branch_name"]),
            target_platform=str(arguments["target_platform"]),
        )
    if name == "clipcannon_list_branches":
        return await clipcannon_list_branches(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
        )

    return error_response("INTERNAL_ERROR", f"Unknown editing tool: {name}")
