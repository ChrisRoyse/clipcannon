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
    CanvasSpec,
    ColorSpec,
    EditDecisionList,
    MotionSpec,
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
# TOOL 5: clipcannon_auto_trim
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
# TOOL 6: clipcannon_color_adjust
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
# TOOL 7: clipcannon_add_motion
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
# TOOL 8: clipcannon_add_overlay
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
# TOOL 9: clipcannon_extract_subject
# ============================================================
async def clipcannon_extract_subject(
    project_id: str,
    model: str = "u2net_human_seg",
) -> dict[str, object]:
    """Extract subject masks from video frames using rembg."""
    from clipcannon.editing.subject_extraction import extract_subject_masks

    err = validate_project(project_id)
    if err is not None:
        return err

    proj_dir = project_dir(project_id)
    frames_dir = proj_dir / "frames"
    if not frames_dir.exists():
        return error_response("FRAMES_NOT_FOUND", "No frames directory")

    processing_dir = proj_dir / "processing"

    try:
        result = await extract_subject_masks(
            frames_dir=frames_dir,
            output_dir=processing_dir,
            model_name=model,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.exception("Subject extraction failed for %s", project_id)
        return error_response("EXTRACTION_FAILED", str(exc))

    return {
        "project_id": project_id,
        "mask_video_path": str(result.mask_video_path),
        "frame_count": result.frame_count,
        "duration_ms": result.duration_ms,
        "model_used": result.model_used,
        "elapsed_ms": result.elapsed_ms,
        "message": (
            f"Extracted {result.frame_count} masks using {model}. "
            f"Mask video at {result.mask_video_path}"
        ),
    }


# ============================================================
# TOOL 10: clipcannon_replace_background
# ============================================================
async def clipcannon_replace_background(
    project_id: str,
    edit_id: str,
    background_type: str,
    background_value: str = "40",
) -> dict[str, object]:
    """Replace video background using extracted subject masks."""
    import asyncio as aio
    import time as time_mod

    from clipcannon.editing.subject_extraction import (
        build_background_replace_filters,
    )

    err = validate_project(project_id)
    if err is not None:
        return err

    proj_dir = project_dir(project_id)
    processing_dir = proj_dir / "processing"
    masks_dir = processing_dir / "masks"

    if not masks_dir.exists() or not any(masks_dir.glob("mask_*.png")):
        return error_response(
            "NO_MASKS",
            "No subject masks found. Run clipcannon_extract_subject first.",
        )

    # Find the mask video
    mask_videos = sorted(processing_dir.glob("mask_*.mp4"))
    if not mask_videos:
        return error_response(
            "NO_MASK_VIDEO",
            "No mask video found. Run clipcannon_extract_subject first.",
        )
    mask_video = mask_videos[-1]  # Latest

    # Find source video
    source_dir = proj_dir / "source"
    source_files = list(source_dir.glob("*"))
    if not source_files:
        return error_response("SOURCE_NOT_FOUND", "No source video")
    source_path = source_files[0]

    output_dir = proj_dir / "processing" / "bg_replaced"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"bg_{background_type}_{secrets.token_hex(4)}.mp4"

    # Default resolution
    w, h = 2560, 1440

    # Get actual source resolution
    conn = get_connection(str(db_path(project_id)), enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT resolution FROM project WHERE project_id = ?",
            (project_id,),
        )
    finally:
        conn.close()

    if row and row.get("resolution"):
        res = str(row["resolution"]).split("x")
        w, h = int(res[0]), int(res[1])

    filters = build_background_replace_filters(
        mask_video_input_idx=1,
        background_type=background_type,
        background_value=background_value,
        output_w=w,
        output_h=h,
    )

    filter_complex = ";".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(source_path),
        "-i", str(mask_video),
        "-filter_complex", filter_complex,
        "-map", "[composed]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]

    t0 = time_mod.monotonic()
    proc = await aio.create_subprocess_exec(
        *cmd,
        stdout=aio.subprocess.PIPE,
        stderr=aio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    elapsed_ms = int((time_mod.monotonic() - t0) * 1000)

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")[-500:]
        return error_response(
            "BG_REPLACE_FAILED",
            f"Background replacement failed: {error_msg}",
        )

    if not output_path.exists():
        return error_response(
            "BG_REPLACE_FAILED",
            "Output file not created",
        )

    return {
        "project_id": project_id,
        "edit_id": edit_id,
        "output_path": str(output_path),
        "background_type": background_type,
        "file_size_bytes": output_path.stat().st_size,
        "elapsed_ms": elapsed_ms,
        "message": (
            f"Background replaced with {background_type}. "
            f"Output at {output_path}"
        ),
    }


# ============================================================
# TOOL 11: clipcannon_remove_region
# ============================================================
async def clipcannon_remove_region(
    project_id: str,
    edit_id: str,
    x: int,
    y: int,
    width: int,
    height: int,
    description: str = "",
) -> dict[str, object]:
    """Remove a rectangular region from the source video."""
    from clipcannon.editing.edl import RemovalSpec

    err = validate_project(project_id)
    if err is not None:
        return err

    try:
        removal = RemovalSpec(x=x, y=y, width=width, height=height, description=description)
    except Exception as exc:
        return error_response("INVALID_PARAMETER", f"Invalid removal spec: {exc}")

    conn = get_connection(str(db_path(project_id)), enable_vec=False, dict_rows=True)
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
        edl.removals.append(removal)

        execute(
            conn,
            "UPDATE edits SET edl_json = ?, updated_at = datetime('now') "
            "WHERE edit_id = ?",
            (edl.model_dump_json(), edit_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "edit_id": edit_id,
        "removal_count": len(edl.removals),
        "removal": removal.model_dump(),
        "message": f"Region removed: {width}x{height} at ({x},{y})",
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

    return error_response("INTERNAL_ERROR", f"Unknown editing tool: {name}")
