"""Rendering MCP tool: clipcannon_get_editing_context."""

from __future__ import annotations

import json
import time

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.rendering_common import _db_path, _error, _validate_project


# ============================================================
# TOOL 7: clipcannon_get_editing_context
# ============================================================
async def clipcannon_get_editing_context(
    project_id: str,
) -> dict[str, object]:
    """Get bounded editing-context data for AI decisions.

    Returns a data manifest (~500 tokens) describing what data is
    available for this project and which tools to use to query it.
    This is a catalog/registry — it tells the AI WHAT exists, not
    the data itself. The AI then uses targeted tools to pull
    exactly what it needs on demand.

    Args:
        project_id: Project identifier.

    Returns:
        Data manifest with counts, ranges, and tool references.
    """
    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err

    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        proj = fetch_one(
            conn,
            "SELECT duration_ms, resolution, fps, status FROM project "
            "WHERE project_id = ?",
            (project_id,),
        )
        if proj is None:
            return _error("PROJECT_NOT_FOUND", f"No project: {project_id}")

        # Count queries — fast aggregate stats from each table
        counts: dict[str, int] = {}
        for table, col in [
            ("transcript_segments", "project_id"),
            ("highlights", "project_id"),
            ("silence_gaps", "project_id"),
            ("scenes", "project_id"),
            ("scene_map", "project_id"),
            ("speakers", "project_id"),
            ("topics", "project_id"),
            ("emotion_curve", "project_id"),
            ("pacing", "project_id"),
            ("on_screen_text", "project_id"),
            ("reactions", "project_id"),
            ("provenance", "project_id"),
        ]:
            try:
                row = fetch_one(
                    conn,
                    f"SELECT COUNT(*) AS cnt FROM {table} WHERE {col} = ?",  # noqa: S608
                    (project_id,),
                )
                counts[table] = int(row["cnt"]) if row else 0
            except Exception:
                counts[table] = 0

        # Top highlight score
        top_hl = fetch_one(
            conn,
            "SELECT MAX(score) AS top FROM highlights WHERE project_id = ?",
            (project_id,),
        )
        top_highlight_score = round(float(top_hl["top"]), 2) if top_hl and top_hl["top"] else 0.0

        # Dominant speaker
        speaker_row = fetch_one(
            conn,
            "SELECT label, speaking_pct FROM speakers "
            "WHERE project_id = ? ORDER BY speaking_pct DESC LIMIT 1",
            (project_id,),
        )

        # Dominant pacing label
        pacing_row = fetch_one(
            conn,
            "SELECT label, SUM(end_ms - start_ms) AS total_ms "
            "FROM pacing WHERE project_id = ? "
            "GROUP BY label ORDER BY total_ms DESC LIMIT 1",
            (project_id,),
        )

        # WPM range
        wpm_row = fetch_one(
            conn,
            "SELECT MIN(words_per_minute) AS min_wpm, "
            "MAX(words_per_minute) AS max_wpm "
            "FROM pacing WHERE project_id = ?",
            (project_id,),
        )

        # Avg energy
        energy_row = fetch_one(
            conn,
            "SELECT AVG(energy) AS avg_e FROM emotion_curve WHERE project_id = ?",
            (project_id,),
        )

        # Beats summary
        beats_row = fetch_one(
            conn,
            "SELECT has_music, tempo_bpm FROM beats WHERE project_id = ? LIMIT 1",
            (project_id,),
        )

        # Content safety
        safety_row = fetch_one(
            conn,
            "SELECT content_rating FROM content_safety WHERE project_id = ? LIMIT 1",
            (project_id,),
        )

        # Webcam detection (from scene_map)
        webcam_row = fetch_one(
            conn,
            "SELECT webcam_x, webcam_y, webcam_w, webcam_h FROM scene_map "
            "WHERE project_id = ? AND webcam_x IS NOT NULL LIMIT 1",
            (project_id,),
        )

        # Topic labels
        topic_rows = fetch_all(
            conn,
            "SELECT label FROM topics WHERE project_id = ? ORDER BY start_ms LIMIT 5",
            (project_id,),
        )

        # All speakers with label + speaking_pct
        try:
            all_speakers = fetch_all(
                conn,
                "SELECT label, speaking_pct FROM speakers "
                "WHERE project_id = ? ORDER BY speaking_pct DESC",
                (project_id,),
            )
        except Exception:
            all_speakers = []

        # Narrative analysis (from Qwen3-8B) — table may not exist
        narrative_data: dict[str, object] | None = None
        try:
            narr_row = fetch_one(
                conn,
                "SELECT analysis_json FROM narrative_analysis "
                "WHERE project_id = ? LIMIT 1",
                (project_id,),
            )
            if narr_row and narr_row.get("analysis_json"):
                raw = json.loads(str(narr_row["analysis_json"]))
                narrative_data = {
                    "story_beats": raw.get("story_beats", []),
                    "open_loops": raw.get("open_loops", []),
                    "chapter_boundaries": raw.get("chapter_boundaries", []),
                    "narrative_summary": raw.get("narrative_summary", ""),
                }
        except Exception:
            narrative_data = None

        # Transcript preview — first 500 words
        transcript_preview: str = ""
        try:
            ts_rows = fetch_all(
                conn,
                "SELECT text FROM transcript_segments "
                "WHERE project_id = ? ORDER BY start_ms",
                (project_id,),
            )
            if ts_rows:
                full_text = " ".join(
                    str(r["text"]).strip() for r in ts_rows if r.get("text")
                )
                words = full_text.split()
                transcript_preview = " ".join(words[:500])
        except Exception:
            transcript_preview = ""

    finally:
        conn.close()

    elapsed = int((time.monotonic() - start_time) * 1000)

    return {
        "project_id": project_id,
        "video": {
            "duration_ms": int(proj["duration_ms"]),
            "resolution": str(proj["resolution"]),
            "fps": float(proj["fps"]),
            "status": str(proj["status"]),
        },
        "data_manifest": {
            "transcript": {
                "segments": counts["transcript_segments"],
                "query": "get_transcript(project_id, start_ms, end_ms)",
            },
            "scenes": {
                "visual_scenes": counts["scene_map"],
                "scene_boundaries": counts["scenes"],
                "query": "get_scene_map(project_id, start_ms, end_ms, detail, layout)",
            },
            "highlights": {
                "count": counts["highlights"],
                "top_score": top_highlight_score,
                "query": "find_best_moments(project_id, purpose, count)",
            },
            "silence_gaps": {
                "count": counts["silence_gaps"],
                "query": "find_cut_points(project_id, around_ms, search_range_ms)",
            },
            "speakers": {
                "count": counts["speakers"],
                "dominant": (
                    f"{speaker_row['label']} ({speaker_row['speaking_pct']}%)"
                    if speaker_row else "unknown"
                ),
            },
            "topics": {
                "count": counts["topics"],
                "labels": [str(t["label"]) for t in topic_rows],
            },
            "emotion": {
                "data_points": counts["emotion_curve"],
                "avg_energy": (
                    round(float(energy_row["avg_e"]), 2)
                    if energy_row and energy_row["avg_e"] else None
                ),
            },
            "pacing": {
                "dominant": str(pacing_row["label"]) if pacing_row else "unknown",
                "wpm_range": (
                    f"{int(wpm_row['min_wpm'])}-{int(wpm_row['max_wpm'])}"
                    if wpm_row and wpm_row["min_wpm"] else "unknown"
                ),
            },
            "webcam": {
                "detected": webcam_row is not None,
            },
            "beats": {
                "detected": bool(beats_row and beats_row["has_music"]),
                "bpm": int(beats_row["tempo_bpm"]) if beats_row and beats_row["tempo_bpm"] else None,
            },
            "ocr_text": {
                "detected": counts["on_screen_text"] > 0,
                "regions": counts["on_screen_text"],
            },
            "reactions": {
                "count": counts["reactions"],
            },
            "content_rating": (
                str(safety_row["content_rating"]) if safety_row else "unknown"
            ),
            "provenance_records": counts["provenance"],
        },
        "speakers": [
            {"label": str(s["label"]), "speaking_pct": round(float(s["speaking_pct"]), 1)}
            for s in all_speakers
            if s.get("speaking_pct") is not None
        ],
        "narrative": narrative_data,
        "transcript_preview": transcript_preview,
        "query_tools": {
            "find_best_moments": "Find scored clip candidates for hook/highlight/cta/tutorial_step",
            "get_scene_map": "Browse scenes in paginated time windows (summary or full detail)",
            "find_cut_points": "Find natural edit boundaries (silence gaps, scene breaks, sentences)",
            "get_transcript": "Get word-level transcript for any time range",
            "search_content": "Search transcript by keywords",
            "analyze_frame": "Detect content regions and webcam in any frame",
            "get_frame": "Get any frame as an image for visual inspection",
            "preview_layout": "Preview a canvas layout composition as JPEG",
        },
        "elapsed_ms": elapsed,
    }
