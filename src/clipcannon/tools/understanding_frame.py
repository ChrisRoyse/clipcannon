"""Visual understanding MCP tool: clipcannon_get_frame and frame lookup helpers."""

from __future__ import annotations

import base64
import sqlite3
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.optional import require_missing_table
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.db.schema_migrations import migrate_to_v5
from clipcannon.tools.understanding import _db_path, _error, _project_dir, _validate_project

if TYPE_CHECKING:
    from pathlib import Path


def _safe_fetch_all(
    conn: object,
    sql: str,
    params: tuple[object, ...],
) -> list[dict[str, object]]:
    """Fetch all rows, returning empty list if the table doesn't exist."""
    try:
        return [dict(r) for r in fetch_all(conn, sql, params)]  # type: ignore[arg-type]
    except sqlite3.OperationalError as _exc:  # absent table only (#68)
        require_missing_table(_exc)
        return []

_FRAME_INTERVAL_MS = 500  # 2fps => one frame every 500ms


def _find_nearest_frame(frames_dir: Path, timestamp_ms: int) -> tuple[Path | None, int]:
    """Find frame file nearest to timestamp. Returns (path, actual_ms)."""
    if not frames_dir.exists():
        return None, 0
    target = int(timestamp_ms / _FRAME_INTERVAL_MS) + 1
    for offset in range(10):
        for num in (target + offset, target - offset):
            if num < 1:
                continue
            candidate = frames_dir / f"frame_{num:06d}.jpg"
            if candidate.exists():
                return candidate, (num - 1) * _FRAME_INTERVAL_MS
    return None, 0


def _get_moment_context(db: Path, project_id: str, ts: int) -> dict[str, object]:
    """Get transcript/emotion/topic/shot/quality/pacing/OCR/profanity at a moment."""
    migrate_to_v5(db)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        _at = "project_id = ? AND start_ms <= ? AND end_ms >= ?"
        _p = (project_id, ts, ts)

        seg = fetch_one(
            conn, f"SELECT text, speaker_id FROM transcript_segments WHERE {_at} LIMIT 1", _p
        )
        speaker_label = None
        if seg and seg.get("speaker_id") is not None:
            spk = fetch_one(
                conn, "SELECT label FROM speakers WHERE speaker_id = ?", (int(seg["speaker_id"]),)
            )
            speaker_label = str(spk.get("label", "")) if spk else None

        emo = fetch_one(
            conn, f"SELECT arousal, valence, energy FROM emotion_curve WHERE {_at} LIMIT 1", _p
        )
        topic = fetch_one(conn, f"SELECT label FROM topics WHERE {_at} LIMIT 1", _p)
        scene = fetch_one(
            conn,
            "SELECT shot_type, shot_type_confidence,"
            " quality_avg, quality_classification, quality_instrument,"
            " sharpness_avg"
            f" FROM scenes WHERE {_at} LIMIT 1",
            _p,
        )
        pace = fetch_one(
            conn,
            f"SELECT words_per_minute, pause_ratio, label FROM pacing WHERE {_at} LIMIT 1",
            _p,
        )
        ost = fetch_one(conn, f"SELECT texts, type FROM on_screen_text WHERE {_at} LIMIT 1", _p)
        prof = fetch_one(
            conn,
            "SELECT word, severity FROM profanity_events"
            " WHERE project_id = ? AND start_ms <= ?"
            " AND end_ms >= ? LIMIT 1",
            (project_id, ts + 500, ts),
        )
    finally:
        conn.close()

    return {
        "transcript": str(seg.get("text", "")) if seg else None,
        "speaker_id": seg.get("speaker_id") if seg else None,
        "speaker_label": speaker_label,
        "emotion": dict(emo) if emo else None,
        "topic": str(topic.get("label", "")) if topic else None,
        "shot_type": str(scene.get("shot_type", "")) if scene else None,
        "shot_type_confidence": scene.get("shot_type_confidence") if scene else None,
        "quality": scene.get("quality_avg") if scene else None,
        "quality_classification": scene.get("quality_classification") if scene else None,
        # Which instrument filled the scene: brisque -> quality*, laplacian_variance
        # -> sharpness (raw Laplacian variance, not a 0-100 score).
        "quality_instrument": scene.get("quality_instrument") if scene else None,
        "sharpness": scene.get("sharpness_avg") if scene else None,
        "pacing": dict(pace) if pace else None,
        "on_screen_text": str(ost.get("texts", "")) if ost else None,
        "profanity": (
            {
                "word": str(prof.get("word", "")),
                "severity": str(prof.get("severity", "")),
            }
            if prof
            else None
        ),
    }


async def clipcannon_get_frame(
    project_id: str,
    timestamp_ms: int,
    render_id: str | None = None,
) -> dict[str, object]:
    """Get nearest frame to timestamp with moment context.

    When ``render_id`` is provided, extracts the frame from the rendered
    output video instead of looking in the pre-extracted frames directory.
    Moment context (transcript, emotion, etc.) is not available for renders
    and will be returned as ``null``.

    Args:
        project_id: Project identifier.
        timestamp_ms: Target timestamp in milliseconds.
        render_id: Optional render ID to get frame from rendered output.

    Returns:
        Dict with frame image and moment context.
    """
    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    if render_id is not None:
        from clipcannon.tools.rendering import _extract_render_frame, _resolve_render_path

        render_path = _resolve_render_path(project_id, render_id)
        if render_path is None:
            return _error(
                "RENDER_NOT_FOUND",
                f"Render not found or output missing: {render_id}",
            )
        frame_path = await _extract_render_frame(render_path, timestamp_ms)
        if frame_path is None:
            return _error(
                "FRAME_EXTRACTION_FAILED",
                f"Could not extract frame at {timestamp_ms}ms from render {render_id}",
            )
        actual_ms = timestamp_ms
        context = None
    else:
        frames_dir = _project_dir(project_id) / "frames"
        frame_path, actual_ms = _find_nearest_frame(frames_dir, timestamp_ms)
        if frame_path is None:
            return _error(
                "FRAME_NOT_FOUND", f"No frame near {timestamp_ms}ms",
                {"frames_dir": str(frames_dir)},
            )
        context = _get_moment_context(_db_path(project_id), project_id, actual_ms)

    # Encode frame as base64 for inline image viewing
    try:
        image_b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
        image_payload = {"data": image_b64, "mimeType": "image/jpeg"}
    except OSError as exc:
        return _error("FRAME_UNREADABLE", f"Frame {frame_path} cannot be read: {exc}")

    result: dict[str, object] = {
        "project_id": project_id,
        "requested_ms": timestamp_ms,
        "actual_ms": actual_ms,
        "frame_path": str(frame_path),
        "at_this_moment": context,
    }
    if image_payload is not None:
        result["_image"] = image_payload
    return result
