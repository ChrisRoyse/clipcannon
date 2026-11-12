"""Editing MCP tool: clipcannon_create_edit (and render_hint column migration)."""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3 as _sqlite3
import time

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.edl import (
    CanvasSpec,
    EditDecisionList,
    RenderSettingsSpec,
    compute_total_duration,
    validate_edl,
)
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.editing_helpers import (
    PLATFORM_PROFILES,
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
