"""Visual understanding MCP tool: clipcannon_get_segment_detail."""

from __future__ import annotations

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.db.schema_migrations import migrate_to_v5
from clipcannon.tools.understanding import _db_path, _error, _validate_project
from clipcannon.tools.understanding_frame import _safe_fetch_all


async def clipcannon_get_segment_detail(
    project_id: str,
    start_ms: int = 0,
    end_ms: int = 0,
    timestamp_ms: int | None = None,
    layout: str | None = None,
    include_ocr: bool = False,
) -> dict[str, object]:
    """Get ALL intelligence for a time range from every pipeline table.

    This is the master query tool. It pulls data from every embedder output
    table for the specified time window, giving the AI complete context
    about what is happening at any moment in the video.

    Queries 17 tables: transcript (segments + words), emotion curve,
    speakers, reactions, beat sections, on-screen text, text change events,
    pacing, scenes (quality + shot type), scene map (face/webcam/content/
    canvas), silence gaps, highlights, topics, profanity, music sections.

    When ``timestamp_ms`` is provided, returns a 10-second window centred on
    that timestamp plus the specific scene_map entry and canvas regions for
    the requested ``layout``.

    Args:
        project_id: Project identifier.
        start_ms: Start of time range in milliseconds.
        end_ms: End of time range in milliseconds.
        timestamp_ms: Optional point-query timestamp. Overrides start_ms/end_ms
            with a 10-second window (timestamp - 5000 to timestamp + 5000).
        layout: Optional layout name to filter canvas regions when using
            timestamp_ms mode.

    Returns:
        Dict with all pipeline data for the time range.
    """
    import json as json_mod

    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    # Point-query mode: 10s window centred on timestamp_ms
    if timestamp_ms is not None:
        start_ms = max(0, timestamp_ms - 5000)
        end_ms = timestamp_ms + 5000

    if end_ms <= start_ms:
        return _error("INVALID_PARAMETER", "end_ms must be greater than start_ms")

    db = _db_path(project_id)
    migrate_to_v5(db)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        # Time-range overlap condition used by most queries
        rq = "project_id = ? AND start_ms < ? AND end_ms > ?"
        rp = (project_id, end_ms, start_ms)

        # -- Transcript segments --
        transcript = fetch_all(
            conn,
            "SELECT segment_id, start_ms, end_ms, text, speaker_id,"
            " sentiment, sentiment_score"
            f" FROM transcript_segments WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Word-level timestamps for precise captions --
        seg_ids = [int(t["segment_id"]) for t in transcript]
        words: list[dict[str, object]] = []
        if seg_ids:
            placeholders = ",".join(["?"] * len(seg_ids))
            words_raw = fetch_all(
                conn,
                "SELECT word, start_ms, end_ms, confidence, speaker_id"
                f" FROM transcript_words WHERE segment_id IN ({placeholders})"
                " ORDER BY start_ms",
                tuple(seg_ids),
            )
            words = [dict(w) for w in words_raw]

        # -- Emotion curve (arousal, valence, energy) --
        emotion = fetch_all(
            conn,
            "SELECT start_ms, end_ms, arousal, valence, energy"
            f" FROM emotion_curve WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Speakers active in this range --
        speaker_ids = {int(t["speaker_id"]) for t in transcript if t.get("speaker_id") is not None}
        speakers: list[dict[str, object]] = []
        for sid in sorted(speaker_ids):
            row = fetch_one(
                conn,
                "SELECT speaker_id, label, total_speaking_ms,"
                " speaking_pct FROM speakers WHERE speaker_id = ?",
                (sid,),
            )
            if row:
                speakers.append(dict(row))

        # -- Reactions (laughter, applause, etc.) --
        reactions = fetch_all(
            conn,
            "SELECT start_ms, end_ms, type, confidence,"
            " intensity, context_transcript, instrument"
            f" FROM reactions WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Beat sections (tempo, time signature) --
        beat_sections = fetch_all(
            conn,
            "SELECT start_ms, end_ms, tempo_bpm, time_signature"
            f" FROM beat_sections WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- On-screen text (OCR detections) --
        # Only fetch raw OCR when explicitly requested (very large payload).
        # The cross-stream alignment logic below still needs the rows for
        # matching, so we always query but only include in the response when
        # include_ocr is True.
        on_screen = _safe_fetch_all(
            conn,
            "SELECT start_ms, end_ms, texts, type, change_from_previous"
            f" FROM on_screen_text WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        ) if include_ocr else _safe_fetch_all(
            conn,
            "SELECT start_ms, end_ms"
            f" FROM on_screen_text WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Text change events (slide transitions) --
        text_changes = _safe_fetch_all(
            conn,
            "SELECT timestamp_ms, type, new_title"
            " FROM text_change_events"
            " WHERE project_id = ? AND timestamp_ms >= ? AND timestamp_ms < ?"
            " ORDER BY timestamp_ms",
            (project_id, start_ms, end_ms),
        )

        # -- Pacing (speech rate, pauses) --
        pacing = fetch_all(
            conn,
            "SELECT start_ms, end_ms, words_per_minute,"
            " pause_ratio, speaker_changes, label"
            f" FROM pacing WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Scene quality + shot type --
        scenes = fetch_all(
            conn,
            "SELECT start_ms, end_ms, quality_avg, quality_min,"
            " quality_classification, quality_issues, quality_instrument,"
            " sharpness_avg, sharpness_min, shot_type,"
            " shot_type_confidence, crop_recommendation"
            f" FROM scenes WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Scene map (face/webcam/content/canvas regions) --
        scene_map_rows = _safe_fetch_all(
            conn,
            "SELECT start_ms, end_ms, face_x, face_y, face_w, face_h,"
            " face_confidence, face_size_pct,"
            " webcam_x, webcam_y, webcam_w, webcam_h,"
            " content_x, content_y, content_w, content_h,"
            " content_type, layout_recommendation,"
            " canvas_regions_json, transcript_text"
            " FROM scene_map"
            " WHERE project_id = ? AND start_ms < ? AND end_ms > ?"
            " ORDER BY start_ms",
            (project_id, end_ms, start_ms),
        )

        # Parse scene_map canvas regions
        scene_map: list[dict[str, object]] = []
        for row in scene_map_rows:
            sm: dict[str, object] = {
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
                "layout": str(row.get("layout_recommendation", "A")),
                "content_type": str(row.get("content_type", "unknown")),
                "face_size_pct": float(row.get("face_size_pct", 0) or 0),
            }
            if row.get("face_x") is not None:
                sm["face"] = {
                    "x": int(row["face_x"]), "y": int(row["face_y"]),
                    "w": int(row["face_w"]), "h": int(row["face_h"]),
                    "confidence": float(row.get("face_confidence") or 0),
                }
            if row.get("webcam_x") is not None:
                sm["webcam"] = {
                    "x": int(row["webcam_x"]), "y": int(row["webcam_y"]),
                    "w": int(row["webcam_w"]), "h": int(row["webcam_h"]),
                }
            if row.get("content_x") is not None:
                sm["content"] = {
                    "x": int(row["content_x"]), "y": int(row["content_y"]),
                    "w": int(row["content_w"]), "h": int(row["content_h"]),
                }
            canvas_json = str(row.get("canvas_regions_json", "{}"))
            try:
                sm["canvas"] = json_mod.loads(canvas_json)
            except (json_mod.JSONDecodeError, TypeError):
                sm["canvas"] = {}
            scene_map.append(sm)

        # -- Silence gaps (natural cut points) --
        silence = fetch_all(
            conn,
            "SELECT start_ms, end_ms, duration_ms, type"
            f" FROM silence_gaps WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Highlights in this range --
        highlights = _safe_fetch_all(
            conn,
            "SELECT start_ms, end_ms, type, score, reason,"
            " emotion_score, reaction_score, semantic_score,"
            " visual_score, quality_score"
            f" FROM highlights WHERE {rq}"
            " ORDER BY score DESC",
            rp,
        )

        # -- Topics overlapping this range --
        topics = _safe_fetch_all(
            conn,
            "SELECT start_ms, end_ms, label, keywords, coherence_score"
            f" FROM topics WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Profanity events --
        profanity = _safe_fetch_all(
            conn,
            "SELECT start_ms, end_ms, severity"
            " FROM profanity_events"
            " WHERE project_id = ? AND start_ms >= ? AND end_ms <= ?",
            (project_id, start_ms, end_ms),
        )

        # -- Music sections --
        music = _safe_fetch_all(
            conn,
            "SELECT start_ms, end_ms, type, confidence"
            f" FROM music_sections WHERE {rq}"
            " ORDER BY start_ms",
            rp,
        )

        # -- Narrative analysis from LLM --
        narrative = _safe_fetch_all(
            conn,
            "SELECT analysis_json FROM narrative_analysis"
            " WHERE project_id = ? LIMIT 1",
            (project_id,),
        )

    finally:
        conn.close()

    # -- Derived cross-stream intelligence (no new DB queries) --

    # Derive emphasis words from word-level timing gaps (pause > 300ms)
    emphasis_words: list[dict[str, object]] = []
    if len(words) >= 2:
        for i in range(1, len(words)):
            prev_end = int(words[i - 1].get("end_ms", 0))
            curr_start = int(words[i].get("start_ms", 0))
            gap_ms = curr_start - prev_end
            if gap_ms > 300:
                emphasis_words.append({
                    "word": str(words[i].get("word", "")),
                    "start_ms": curr_start,
                    "pause_before_ms": gap_ms,
                })

    # Detect speech-content alignment (speaker references screen content)
    speech_screen_alignment: list[dict[str, object]] = []
    visual_keywords = [
        "look at", "you can see", "right here", "this is", "let me show",
        "check this", "dashboard", "screen", "code", "file", "click",
        "open", "scroll", "tab", "window", "button",
    ]
    on_screen_dicts = [dict(o) for o in on_screen]
    for seg in transcript:
        seg_text = str(seg.get("text", "")).lower()
        matched_keywords = [kw for kw in visual_keywords if kw in seg_text]
        if matched_keywords:
            seg_start = int(seg.get("start_ms", 0))
            seg_end = int(seg.get("end_ms", 0))
            visible_ocr = [
                o for o in on_screen_dicts
                if int(o.get("start_ms", 0)) <= seg_end
                and int(o.get("end_ms", 0)) >= seg_start
            ]
            speech_screen_alignment.append({
                "transcript_ms": seg_start,
                "text": str(seg.get("text", "")),
                "keywords": matched_keywords,
                "screen_text_visible": len(visible_ocr) > 0,
            })

    # Find peak emotion moments in this range (top 3 by energy)
    emotion_peaks: list[dict[str, object]] = []
    if emotion:
        sorted_by_energy = sorted(
            emotion, key=lambda e: float(e.get("energy", 0)), reverse=True,
        )
        for e in sorted_by_energy[:3]:
            emotion_peaks.append({
                "start_ms": int(e["start_ms"]),
                "energy": round(float(e["energy"]), 4),
                "arousal": round(float(e["arousal"]), 4),
            })

    result: dict[str, object] = {
        "project_id": project_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "transcript": [dict(t) for t in transcript],
        "words": words,
        "emotion_curve": [dict(e) for e in emotion],
        "speakers": speakers,
        "reactions": [dict(r) for r in reactions],
        "beat_sections": [dict(b) for b in beat_sections],
        "text_change_events": [dict(tc) for tc in text_changes],
        "pacing": [dict(p) for p in pacing],
        "scenes_quality": [dict(s) for s in scenes],
        "scene_map": scene_map,
        "silence_gaps": [dict(sg) for sg in silence],
        "highlights": [dict(h) for h in highlights],
        "topics": [dict(t) for t in topics],
        "profanity": [dict(p) for p in profanity],
        "music_sections": [dict(m) for m in music],
        "emphasis_words": emphasis_words,
        "speech_screen_alignment": speech_screen_alignment,
        "emotion_peaks": emotion_peaks,
        "narrative_analysis": (
            json_mod.loads(narrative[0]["analysis_json"])
            if narrative
            else None
        ),
    }

    # Only include raw OCR data when explicitly requested
    if include_ocr:
        result["on_screen_text"] = on_screen_dicts

    # -- Point-query enrichment: scene_map entry + canvas regions for layout --
    if timestamp_ms is not None:
        result["timestamp_ms"] = timestamp_ms
        # Find the exact scene_map entry containing timestamp_ms
        point_scene: dict[str, object] | None = None
        for sm_entry in scene_map:
            sm_start = int(sm_entry.get("start_ms", 0))
            sm_end = int(sm_entry.get("end_ms", 0))
            if sm_start <= timestamp_ms < sm_end:
                point_scene = sm_entry
                break

        result["point_scene"] = point_scene
        if layout:
            canvas_data = point_scene.get("canvas", {}) if point_scene else {}
            result["requested_layout"] = layout
            result["layout_canvas_regions"] = (
                canvas_data.get(layout) if isinstance(canvas_data, dict) else None
            )

    return result
