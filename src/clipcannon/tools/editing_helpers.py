"""Helper functions for editing tool parameter construction.

Provides builder functions that convert raw MCP tool parameter dicts
into validated Pydantic models (SegmentSpec, CaptionSpec, CropSpec,
AudioSpec, MetadataSpec). Also provides shared project/DB utilities.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.editing.captions import (
    chunk_transcript_words,
    fetch_words_for_segments,
    remap_timestamps,
)
from clipcannon.editing.edl import (
    AudioSpec,
    CaptionChunk,
    CaptionSpec,
    CaptionWord,
    CropSpec,
    EditDecisionList,
    MetadataSpec,
    RenderSettingsSpec,
    SegmentCanvasSpec,
    SegmentSpec,
    TransitionSpec,
)
from clipcannon.editing.smart_crop import PLATFORM_ASPECTS
from clipcannon.exceptions import ClipCannonError

logger = logging.getLogger(__name__)

# ============================================================
# PLATFORM -> RENDER PROFILE MAPPING
# ============================================================
PLATFORM_PROFILES: dict[str, str] = {
    "tiktok": "tiktok_vertical",
    "instagram_reels": "instagram_reels",
    "youtube_shorts": "youtube_shorts",
    "youtube_standard": "youtube_standard",
    "youtube_4k": "youtube_4k",
    "facebook": "facebook",
    "linkedin": "linkedin",
}


# ============================================================
# SHARED UTILITIES
# ============================================================
def error_response(
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
    return {"error": {"code": code, "message": message, "details": details or {}}}


def projects_dir() -> Path:
    """Resolve projects base directory from config or default.

    Returns:
        Absolute path to the projects directory.
    """
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def db_path(project_id: str) -> Path:
    """Build database path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project's analysis.db.
    """
    return projects_dir() / project_id / "analysis.db"


def project_dir(project_id: str) -> Path:
    """Build project directory path.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project directory.
    """
    return projects_dir() / project_id


def validate_project(
    project_id: str, required_status: str | None = "ready"
) -> dict[str, object] | None:
    """Validate project exists and check status.

    Args:
        project_id: Project identifier.
        required_status: Expected status, or None to skip check.

    Returns:
        Error dict if validation fails, None on success.
    """
    db = db_path(project_id)
    if not db.exists():
        return error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")
    if required_status is not None:
        conn = get_connection(db, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT status FROM project WHERE project_id = ?",
                (project_id,),
            )
        finally:
            conn.close()
        if row is None:
            return error_response("PROJECT_NOT_FOUND", f"No project record: {project_id}")
        status = str(row.get("status", ""))
        if required_status == "ready" and status not in ("ready", "ready_degraded", "analyzing"):
            return error_response(
                "INVALID_STATE",
                f"Project not ready, current status: {status}",
            )
    return None


# ============================================================
# SPEC BUILDERS
# ============================================================
def build_transition(raw: dict[str, object] | None) -> TransitionSpec | None:
    """Build a TransitionSpec from raw dict input.

    Args:
        raw: Raw transition dict with type and duration_ms, or None.

    Returns:
        TransitionSpec or None.
    """
    if raw is None:
        return None
    return TransitionSpec(
        type=str(raw.get("type", "cut")),  # type: ignore[arg-type]
        duration_ms=int(raw.get("duration_ms", 500)),  # type: ignore[arg-type]
    )


def build_segments(
    raw_segments: list[dict[str, object]],
) -> list[SegmentSpec]:
    """Build SegmentSpec list from raw input, auto-assigning IDs and offsets.

    Segments are ordered sequentially. Each segment's output_start_ms is
    computed based on the cumulative output duration of previous segments.

    Args:
        raw_segments: List of raw segment dicts.

    Returns:
        Ordered list of SegmentSpec.
    """
    specs: list[SegmentSpec] = []
    # Use float accumulator to avoid compounding int-truncation drift.
    # Each segment's output_start_ms is rounded from the precise float
    # sum, so errors stay < 0.5 ms instead of growing with each segment.
    output_cursor_f: float = 0.0

    for idx, raw in enumerate(raw_segments, start=1):
        source_start = int(raw["source_start_ms"])  # type: ignore[arg-type]
        source_end = int(raw["source_end_ms"])  # type: ignore[arg-type]
        speed = float(raw.get("speed", 1.0))  # type: ignore[arg-type]

        transition_in = build_transition(
            raw.get("transition_in")  # type: ignore[arg-type]
        )
        transition_out = build_transition(
            raw.get("transition_out")  # type: ignore[arg-type]
        )

        # Parse optional per-segment canvas override
        raw_canvas = raw.get("canvas")
        seg_canvas: SegmentCanvasSpec | None = None
        if isinstance(raw_canvas, dict):
            seg_canvas = SegmentCanvasSpec(**raw_canvas)

        # Clamp output_start_ms so it never overlaps with the previous
        # segment's computed end.  float→int rounding of the accumulator
        # and of output_duration_ms can differ by ±1ms; clamping keeps
        # the EDL validation happy while preserving float precision.
        output_start = round(output_cursor_f)
        if specs:
            prev_end = specs[-1].output_start_ms + specs[-1].output_duration_ms
            if output_start < prev_end:
                output_start = prev_end

        seg = SegmentSpec(
            segment_id=idx,
            source_start_ms=source_start,
            source_end_ms=source_end,
            output_start_ms=output_start,
            speed=speed,
            transition_in=transition_in,
            transition_out=transition_out,
            canvas=seg_canvas,
        )
        specs.append(seg)
        # Accumulate precise float duration (no truncation per-step)
        output_cursor_f += (source_end - source_start) / speed

    return specs


def build_caption_spec(
    raw: dict[str, object] | None,
) -> CaptionSpec:
    """Build CaptionSpec from raw input with defaults.

    Args:
        raw: Raw caption config dict or None.

    Returns:
        CaptionSpec with defaults applied.
    """
    if raw is None:
        return CaptionSpec()

    chunks_raw = raw.get("chunks", [])
    chunks: list[CaptionChunk] = []
    if isinstance(chunks_raw, list):
        for c in chunks_raw:
            if isinstance(c, dict):
                words_raw = c.get("words", [])
                words = [
                    CaptionWord(**w) if isinstance(w, dict) else w
                    for w in (words_raw if isinstance(words_raw, list) else [])
                ]
                chunks.append(
                    CaptionChunk(
                        chunk_id=int(c.get("chunk_id", 1)),  # type: ignore[arg-type]
                        text=str(c.get("text", "")),
                        start_ms=int(c.get("start_ms", 0)),  # type: ignore[arg-type]
                        end_ms=int(c.get("end_ms", 0)),  # type: ignore[arg-type]
                        words=words,
                    )
                )

    return CaptionSpec(
        enabled=bool(raw.get("enabled", True)),
        style=raw.get("style", "bold_centered"),  # type: ignore[arg-type]
        font=str(raw.get("font", "Montserrat-Bold")),
        font_size=int(raw.get("font_size", 48)),  # type: ignore[arg-type]
        color=str(raw.get("color", "#FFFFFF")),
        stroke_color=str(raw.get("stroke_color", "#000000")),
        stroke_width=int(raw.get("stroke_width", 3)),  # type: ignore[arg-type]
        position=raw.get("position", "center"),  # type: ignore[arg-type]
        animation=raw.get("animation", "word_by_word"),  # type: ignore[arg-type]
        chunks=chunks,
    )


def build_crop_spec(
    raw: dict[str, object] | None,
    target_platform: str,
) -> CropSpec:
    """Build CropSpec from raw input with platform defaults.

    Args:
        raw: Raw crop config dict or None.
        target_platform: Target platform for default aspect ratio.

    Returns:
        CropSpec with defaults applied.
    """
    default_aspect = PLATFORM_ASPECTS.get(target_platform, "9:16")

    if raw is None:
        return CropSpec(mode="auto", aspect_ratio=default_aspect)

    return CropSpec(
        mode=raw.get("mode", "auto"),  # type: ignore[arg-type]
        aspect_ratio=str(raw.get("aspect_ratio", default_aspect)),
        face_tracking=bool(raw.get("face_tracking", True)),
        safe_area_pct=float(raw.get("safe_area_pct", 0.85)),  # type: ignore[arg-type]
    )


def build_audio_spec(raw: dict[str, object] | None) -> AudioSpec:
    """Build AudioSpec from raw input with defaults.

    Args:
        raw: Raw audio config dict or None.

    Returns:
        AudioSpec with defaults applied.
    """
    if raw is None:
        return AudioSpec()

    return AudioSpec(
        source_audio=bool(raw.get("source_audio", True)),
        source_volume_db=float(raw.get("source_volume_db", 0.0)),  # type: ignore[arg-type]
        background_music=raw.get("background_music"),  # type: ignore[arg-type]
        sound_effects=raw.get("sound_effects", []),  # type: ignore[arg-type]
    )


def build_metadata_spec(raw: dict[str, object] | None) -> MetadataSpec:
    """Build MetadataSpec from raw input with defaults.

    Args:
        raw: Raw metadata config dict or None.

    Returns:
        MetadataSpec with defaults applied.
    """
    if raw is None:
        return MetadataSpec()

    return MetadataSpec(
        title=str(raw.get("title", "")),
        description=str(raw.get("description", "")),
        hashtags=list(raw.get("hashtags", [])),  # type: ignore[arg-type]
        thumbnail_timestamp_ms=raw.get("thumbnail_timestamp_ms"),  # type: ignore[arg-type]
    )


def build_render_settings(
    raw: dict[str, object],
    current: RenderSettingsSpec,
) -> RenderSettingsSpec:
    """Build RenderSettingsSpec from raw input with current as defaults.

    Args:
        raw: Raw render settings dict.
        current: Current render settings to use as defaults.

    Returns:
        RenderSettingsSpec with overrides applied.
    """
    return RenderSettingsSpec(
        profile=str(raw.get("profile", current.profile)),
        quality=raw.get("quality", current.quality),  # type: ignore[arg-type]
        use_nvenc=bool(raw.get("use_nvenc", current.use_nvenc)),
    )


def store_edit_segments(
    conn: sqlite3.Connection,
    edit_id: str,
    segments: list[SegmentSpec],
) -> None:
    """Store individual segment records in the edit_segments table.

    Args:
        conn: SQLite connection.
        edit_id: Edit identifier.
        segments: List of SegmentSpec to store.
    """
    for seg in segments:
        execute(
            conn,
            """INSERT INTO edit_segments (
                edit_id, segment_order, source_start_ms, source_end_ms,
                output_start_ms, speed,
                transition_in_type, transition_in_duration_ms,
                transition_out_type, transition_out_duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                edit_id,
                seg.segment_id,
                seg.source_start_ms,
                seg.source_end_ms,
                seg.output_start_ms,
                seg.speed,
                seg.transition_in.type if seg.transition_in else None,
                seg.transition_in.duration_ms if seg.transition_in else None,
                seg.transition_out.type if seg.transition_out else None,
                seg.transition_out.duration_ms if seg.transition_out else None,
            ),
        )


# ============================================================
# CAPTION AUTO-GENERATION
# ============================================================
def auto_generate_captions(
    edl: EditDecisionList,
    db: object,
    project_id: str,
    segment_specs: list[SegmentSpec],
    edit_id: str,
) -> None:
    """Auto-generate caption chunks from transcript words.

    Non-fatal: logs a warning and continues if generation fails.

    Args:
        edl: EDL to update with generated captions.
        db: Database path.
        project_id: Project identifier.
        segment_specs: List of segment specs.
        edit_id: Edit identifier for logging.
    """
    try:
        word_records = fetch_words_for_segments(db, project_id, segment_specs)  # type: ignore[arg-type]
        if word_records:
            caption_words = [
                CaptionWord(word=wr.word, start_ms=wr.start_ms, end_ms=wr.end_ms)
                for wr in word_records
            ]
            raw_chunks = chunk_transcript_words(caption_words)
            remapped_chunks = remap_timestamps(raw_chunks, segment_specs)
            edl.captions.chunks = remapped_chunks
            logger.info(
                "Auto-generated %d caption chunks for edit %s",
                len(remapped_chunks), edit_id,
            )
    except Exception as exc:
        logger.warning("Caption auto-generation failed for edit %s: %s", edit_id, exc)


# ============================================================
# CHANGE APPLICATION
# ============================================================
def apply_changes(
    edl: EditDecisionList,
    changes: dict[str, object],
) -> tuple[list[str], bool, dict[str, object] | None]:
    """Apply changes to an EDL and return tracking info.

    Args:
        edl: EDL to modify in place.
        changes: Dict of field name to new value.

    Returns:
        Tuple of (updated_field_names, segments_changed, error_or_none).
    """
    updated: list[str] = []
    segments_changed = False

    if "name" in changes:
        edl.name = str(changes["name"])
        updated.append("name")

    if "segments" in changes:
        raw_segs = changes["segments"]
        if isinstance(raw_segs, list):
            try:
                edl.segments = build_segments(raw_segs)  # type: ignore[arg-type]
                segments_changed = True
                updated.append("segments")
            except (ValueError, KeyError, TypeError) as exc:
                return [], False, error_response(
                    "INVALID_PARAMETER", f"Invalid segment data: {exc}",
                    {"error": str(exc)},
                )

    if "captions" in changes and isinstance(changes["captions"], dict):
        edl.captions = build_caption_spec(changes["captions"])  # type: ignore[arg-type]
        updated.append("captions")

    if "crop" in changes and isinstance(changes["crop"], dict):
        edl.crop = build_crop_spec(changes["crop"], edl.target_platform)  # type: ignore[arg-type]
        updated.append("crop")

    if "audio" in changes and isinstance(changes["audio"], dict):
        edl.audio = build_audio_spec(changes["audio"])  # type: ignore[arg-type]
        updated.append("audio")

    if "metadata" in changes and isinstance(changes["metadata"], dict):
        edl.metadata = build_metadata_spec(changes["metadata"])  # type: ignore[arg-type]
        updated.append("metadata")

    if "render_settings" in changes and isinstance(changes["render_settings"], dict):
        edl.render_settings = build_render_settings(
            changes["render_settings"], edl.render_settings,  # type: ignore[arg-type]
        )
        updated.append("render_settings")

    return updated, segments_changed, None
