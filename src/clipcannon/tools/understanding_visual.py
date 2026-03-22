"""Visual understanding MCP tools for ClipCannon.

Provides get_frame and get_segment_detail tools for retrieving
visual and temporal data.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.understanding import _db_path, _error, _project_dir, _validate_project

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

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
            " quality_avg, quality_classification"
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
        "quality_classification": (str(scene.get("quality_classification", "")) if scene else None),
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


async def clipcannon_get_frame(project_id: str, timestamp_ms: int) -> dict[str, object]:
    """Get nearest frame to timestamp with moment context."""
    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    frames_dir = _project_dir(project_id) / "frames"
    frame_path, actual_ms = _find_nearest_frame(frames_dir, timestamp_ms)
    if frame_path is None:
        return _error(
            "FRAME_NOT_FOUND", f"No frame near {timestamp_ms}ms", {"frames_dir": str(frames_dir)}
        )

    context = _get_moment_context(_db_path(project_id), project_id, actual_ms)

    # Encode frame as base64 for inline image viewing
    import base64

    try:
        image_b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
        image_payload = {"data": image_b64, "mimeType": "image/jpeg"}
    except Exception:
        image_payload = None

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



async def clipcannon_get_segment_detail(
    project_id: str,
    start_ms: int,
    end_ms: int,
) -> dict[str, object]:
    """Get ALL stream data for a time range: transcript, emotion, speakers,
    reactions, beats, on-screen text, pacing, quality, silence gaps."""
    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err
    if end_ms <= start_ms:
        return _error("INVALID_PARAMETER", "end_ms must be greater than start_ms")

    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        rq = "project_id = ? AND start_ms < ? AND end_ms > ?"
        rp = (project_id, end_ms, start_ms)

        transcript = fetch_all(
            conn,
            "SELECT segment_id, start_ms, end_ms, text, speaker_id"
            f" FROM transcript_segments WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )
        emotion = fetch_all(
            conn,
            "SELECT start_ms, end_ms, arousal, valence, energy"
            f" FROM emotion_curve WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        speaker_ids = {int(t["speaker_id"]) for t in transcript if t.get("speaker_id") is not None}
        speakers: list[dict[str, object]] = []
        for sid in sorted(speaker_ids):
            row = fetch_one(
                conn,
                "SELECT speaker_id, label, total_speaking_ms,"
                " speaking_pct FROM speakers"
                " WHERE speaker_id = ?",
                (sid,),
            )
            if row:
                speakers.append(dict(row))

        reactions = fetch_all(
            conn,
            "SELECT start_ms, end_ms, type, confidence,"
            " intensity, context_transcript"
            f" FROM reactions WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )
        beat_sections = fetch_all(
            conn,
            "SELECT start_ms, end_ms, tempo_bpm, time_signature"
            f" FROM beat_sections WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )
        on_screen = fetch_all(
            conn,
            "SELECT start_ms, end_ms, texts, type"
            f" FROM on_screen_text WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )
        pacing = fetch_all(
            conn,
            "SELECT start_ms, end_ms, words_per_minute,"
            " pause_ratio, speaker_changes, label"
            f" FROM pacing WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )
        scenes = fetch_all(
            conn,
            "SELECT start_ms, end_ms, quality_avg, quality_min,"
            " quality_classification, quality_issues, shot_type"
            f" FROM scenes WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )
        silence = fetch_all(
            conn,
            "SELECT start_ms, end_ms, duration_ms, type"
            f" FROM silence_gaps WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )
    finally:
        conn.close()

    return {
        "project_id": project_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "transcript": [dict(t) for t in transcript],
        "emotion_curve": [dict(e) for e in emotion],
        "speakers": speakers,
        "reactions": [dict(r) for r in reactions],
        "beat_sections": [dict(b) for b in beat_sections],
        "on_screen_text": [dict(o) for o in on_screen],
        "pacing": [dict(p) for p in pacing],
        "scenes_quality": [dict(s) for s in scenes],
        "silence_gaps": [dict(sg) for sg in silence],
    }
