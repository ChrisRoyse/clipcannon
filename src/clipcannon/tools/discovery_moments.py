"""Discovery MCP tool: clipcannon_find_best_moments."""

from __future__ import annotations

import logging

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.discovery_common import (
    _db_path,
    _error,
    _parse_canvas_regions,
    _validate_project,
)
from clipcannon.tools.discovery_cuts import _score_cut_point

logger = logging.getLogger(__name__)


# ============================================================
# TOOL 1: clipcannon_find_best_moments
# ============================================================
async def clipcannon_find_best_moments(
    project_id: str,
    purpose: str,
    target_duration_s: int = 30,
    count: int = 5,
) -> dict[str, object]:
    """Find the best video segments for a specific purpose.

    Queries highlights ranked by score, snaps to natural cut points
    via silence gaps, includes transcript text and canvas region data.
    Applies purpose-aware scoring adjustments with cross-stream
    intelligence boosts:
    - Emotion peak energy from Wav2Vec2 emotion_curve (up to +0.5)
    - Speech-content alignment when speaker references visuals (+0.3)
    - Emphasis pause detection for word gaps > 300ms (up to +0.3)

    Args:
        project_id: Project identifier.
        purpose: One of 'hook', 'highlight', 'cta', 'tutorial_step'.
        target_duration_s: Target clip duration in seconds (5-180).
        count: Number of moments to return (max 10).

    Returns:
        Dictionary with ranked moments and metadata.
    """
    # Validate inputs
    err = _validate_project(project_id)
    if err is not None:
        return err

    valid_purposes = ("hook", "highlight", "cta", "tutorial_step")
    if purpose not in valid_purposes:
        return _error(
            "INVALID_PARAMETER",
            f"purpose must be one of {valid_purposes}, got: {purpose}",
        )

    target_duration_s = max(5, min(180, target_duration_s))
    count = max(1, min(10, count))

    db = _db_path(project_id)
    conn = get_connection(str(db), enable_vec=False, dict_rows=True)

    try:
        # Get video duration for position-based scoring
        proj = fetch_one(
            conn,
            "SELECT duration_ms FROM project WHERE project_id = ?",
            (project_id,),
        )
        if proj is None:
            return _error(
                "PROJECT_NOT_FOUND",
                f"No project record: {project_id}",
            )
        total_duration_ms = int(proj["duration_ms"])

        # Fetch more highlights than needed so we can re-rank
        fetch_limit = count * 3
        highlights = fetch_all(
            conn,
            "SELECT * FROM highlights WHERE project_id = ? "
            "ORDER BY score DESC LIMIT ?",
            (project_id, fetch_limit),
        )

        if not highlights:
            return {
                "project_id": project_id,
                "purpose": purpose,
                "moments": [],
                "message": "No highlights found. Run ingest first.",
            }

        # For tutorial_step, fetch text_change_events timestamps
        text_change_timestamps: list[int] = []
        if purpose == "tutorial_step":
            try:
                tce_rows = fetch_all(
                    conn,
                    "SELECT timestamp_ms FROM text_change_events "
                    "WHERE project_id = ? ORDER BY timestamp_ms",
                    (project_id,),
                )
                text_change_timestamps = [
                    int(r["timestamp_ms"]) for r in tce_rows
                ]
            except Exception:
                # Table may not exist; proceed without
                pass

        # Apply purpose-based scoring adjustments
        scored_highlights: list[dict[str, object]] = []
        for h in highlights:
            raw_score = float(h["score"])
            h_start = int(h["start_ms"])
            h_end = int(h["end_ms"])
            h_mid = (h_start + h_end) // 2
            position_ratio = h_mid / max(total_duration_ms, 1)
            adjusted_score = raw_score

            if purpose == "hook":
                # Prefer highlights in first 25% of video
                if position_ratio <= 0.25:
                    adjusted_score *= 1.3
                elif position_ratio > 0.50:
                    adjusted_score *= 0.7
                # Face boost applied below after scene lookup

            elif purpose == "cta":
                # Prefer highlights in last 25% of video
                if position_ratio >= 0.75:
                    adjusted_score *= 1.3
                elif position_ratio < 0.50:
                    adjusted_score *= 0.7

            elif purpose == "tutorial_step":
                # Prefer highlights near text_change_events
                if text_change_timestamps:
                    min_dist = min(
                        abs(h_mid - tce) for tce in text_change_timestamps
                    )
                    if min_dist <= 10_000:
                        adjusted_score *= 1.3
                    elif min_dist > 30_000:
                        adjusted_score *= 0.7

            # purpose == "highlight" uses raw scores (no adjustment)

            # --- Cross-stream intelligence boosts ---
            # Enhancement 1: Emotion boost from emotion_curve data
            _emotion_peak_energy: float | None = None
            _emotion_peak_arousal: float | None = None
            try:
                emotion_row = fetch_one(
                    conn,
                    "SELECT MAX(energy) as peak_energy, "
                    "MAX(arousal) as peak_arousal "
                    "FROM emotion_curve WHERE project_id = ? "
                    "AND start_ms < ? AND end_ms > ?",
                    (project_id, int(h["end_ms"]), int(h["start_ms"])),
                )
                if emotion_row and emotion_row.get("peak_energy"):
                    _emotion_peak_energy = float(emotion_row["peak_energy"])
                    _emotion_peak_arousal = float(
                        emotion_row.get("peak_arousal") or 0.0
                    )
                    # Boost score by peak emotion (energy 0-1, add up to 0.5)
                    emotion_boost = _emotion_peak_energy * 0.5
                    adjusted_score += emotion_boost
            except Exception:
                pass  # emotion_curve may not be populated

            # Enhancement 2: Speech-content alignment detection
            _has_visual_reference = False
            try:
                visual_keywords = [
                    "look at", "you can see", "right here", "this is",
                    "let me show", "check this", "dashboard", "screen",
                    "code", "file", "click",
                ]
                trans_rows = fetch_all(
                    conn,
                    "SELECT text FROM transcript_segments "
                    "WHERE project_id = ? "
                    "AND start_ms < ? AND end_ms > ?",
                    (project_id, int(h["end_ms"]), int(h["start_ms"])),
                )
                full_text = " ".join(
                    str(r["text"]).lower() for r in trans_rows
                )
                _has_visual_reference = any(
                    kw in full_text for kw in visual_keywords
                )
                if _has_visual_reference:
                    adjusted_score += 0.3  # speech-content alignment boost
            except Exception:
                pass  # transcript_segments may not be populated

            # Enhancement 3: Emphasis pause detection (word gaps > 300ms)
            _emphasis_pauses = 0
            try:
                emphasis_count_row = fetch_one(
                    conn,
                    "SELECT COUNT(*) as cnt FROM ("
                    "  SELECT w1.end_ms, w2.start_ms "
                    "  FROM transcript_words w1 "
                    "  JOIN transcript_words w2 "
                    "    ON w2.word_id = w1.word_id + 1 "
                    "  JOIN transcript_segments ts "
                    "    ON w1.segment_id = ts.segment_id "
                    "  WHERE ts.project_id = ? "
                    "    AND w1.end_ms >= ? AND w1.end_ms <= ? "
                    "    AND (w2.start_ms - w1.end_ms) > 300"
                    ")",
                    (project_id, int(h["start_ms"]), int(h["end_ms"])),
                )
                if emphasis_count_row and int(emphasis_count_row["cnt"]) > 0:
                    _emphasis_pauses = int(emphasis_count_row["cnt"])
                    emphasis_boost = min(0.3, _emphasis_pauses * 0.1)
                    adjusted_score += emphasis_boost
            except Exception:
                pass  # transcript_words may not be joinable

            scored_highlights.append({
                **dict(h),
                "_adjusted_score": adjusted_score,
                "_emotion_peak_energy": _emotion_peak_energy,
                "_emotion_peak_arousal": _emotion_peak_arousal,
                "_has_visual_reference": _has_visual_reference,
                "_emphasis_pauses": _emphasis_pauses,
            })

        # Sort by adjusted score descending
        scored_highlights.sort(
            key=lambda x: float(x["_adjusted_score"]),  # type: ignore[arg-type]
            reverse=True,
        )

        # Pre-fetch narrative analysis for story beat matching
        story_beats: list[dict[str, object]] = []
        chapter_boundaries: list[dict[str, object]] = []
        try:
            na_row = fetch_one(
                conn,
                "SELECT analysis_json FROM narrative_analysis "
                "WHERE project_id = ? LIMIT 1",
                (project_id,),
            )
            if na_row:
                import json as json_mod
                na = json_mod.loads(str(na_row["analysis_json"]))
                story_beats = na.get("story_beats", [])
                chapter_boundaries = na.get("chapters", [])
        except Exception:
            pass  # narrative_analysis table may not exist

        # Build moments from top candidates
        moments: list[dict[str, object]] = []
        for rank_idx, h in enumerate(scored_highlights[:count], start=1):
            h_start = int(h["start_ms"])  # type: ignore[arg-type]
            h_end = int(h["end_ms"])  # type: ignore[arg-type]

            # Find nearest silence gap before the highlight start
            gap_before = fetch_one(
                conn,
                "SELECT start_ms FROM silence_gaps "
                "WHERE project_id = ? AND start_ms <= ? "
                "ORDER BY start_ms DESC LIMIT 1",
                (project_id, h_start),
            )
            clean_start_ms = (
                int(gap_before["start_ms"]) if gap_before else h_start
            )

            # Find nearest silence gap after the highlight end
            gap_after = fetch_one(
                conn,
                "SELECT end_ms FROM silence_gaps "
                "WHERE project_id = ? AND end_ms >= ? "
                "ORDER BY end_ms ASC LIMIT 1",
                (project_id, h_end),
            )
            clean_end_ms = (
                int(gap_after["end_ms"]) if gap_after else h_end
            )

            # Get transcript text for the time range
            transcript_rows = fetch_all(
                conn,
                "SELECT text FROM transcript_segments "
                "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
                "ORDER BY start_ms",
                (project_id, h_end, h_start),
            )
            transcript_text = " ".join(
                str(r["text"]) for r in transcript_rows
            )

            # Get scene_map data for canvas regions
            scene_row = fetch_one(
                conn,
                "SELECT * FROM scene_map "
                "WHERE project_id = ? AND start_ms <= ? AND end_ms >= ? "
                "LIMIT 1",
                (project_id, h_start, h_start),
            )

            layout_name = "A"
            canvas_regions: list[dict[str, object]] = []
            has_face = False
            if scene_row is not None:
                rec_layout = str(
                    scene_row.get("layout_recommendation", "A")
                )
                canvas_json = str(
                    scene_row.get("canvas_regions_json", "{}")
                )
                layout_name, canvas_regions = _parse_canvas_regions(
                    canvas_json, None, rec_layout
                )
                has_face = scene_row.get("face_x") is not None

            # For hook purpose: extra boost if face detected
            adjusted_score = float(h["_adjusted_score"])  # type: ignore[arg-type]
            if purpose == "hook" and has_face:
                adjusted_score *= 1.15

            # Extract cross-stream enrichment data from scoring pass
            _ep_energy = h.get("_emotion_peak_energy")
            _ep_arousal = h.get("_emotion_peak_arousal")

            # --- Enhancement 1: Convergence scoring on cut points ---
            start_quality, start_signals = _score_cut_point(
                conn, project_id, clean_start_ms,
            )
            end_quality, end_signals = _score_cut_point(
                conn, project_id, clean_end_ms,
            )

            # --- Enhancement 2: Story beat context ---
            moment_beat: dict[str, object] | None = None
            if story_beats and transcript_text:
                # Try text match first
                t_lower = transcript_text.lower()
                for beat in story_beats:
                    start_txt = str(beat.get("start_text", ""))[:30].lower()
                    if start_txt and start_txt in t_lower:
                        moment_beat = {
                            "type": beat.get("type", "unknown"),
                            "summary": beat.get("summary", ""),
                        }
                        break
            if moment_beat is None and chapter_boundaries:
                # Fallback: match by timestamp proximity to chapters
                h_mid = (h_start + h_end) // 2
                best_dist = float("inf")
                for ch in chapter_boundaries:
                    ch_ms = int(ch.get("start_ms", 0) or 0)
                    dist = abs(ch_ms - h_mid)
                    if dist < best_dist:
                        best_dist = dist
                        moment_beat = {
                            "type": ch.get("type", "chapter"),
                            "summary": ch.get("title", ch.get("summary", "")),
                        }

            # --- Enhancement 3: Moment character label ---
            _energy = float(_ep_energy) if _ep_energy is not None else 0.0
            _vis_ref = bool(h.get("_has_visual_reference", False))
            _emph = int(h.get("_emphasis_pauses", 0) or 0)

            if _energy > 0.35 and _emph > 2:
                moment_character = "passionate_claim"
            elif _energy > 0.35 and _vis_ref:
                moment_character = "excited_demo"
            elif _energy > 0.33:
                moment_character = "engaged_explanation"
            elif _vis_ref:
                moment_character = "screen_walkthrough"
            else:
                moment_character = "calm_narration"

            moment: dict[str, object] = {
                "rank": rank_idx,
                "start_ms": h_start,
                "end_ms": h_end,
                "score": round(adjusted_score, 4),
                "reason": str(h.get("reason", "from highlights table")),
                "cut_points": {
                    "clean_start_ms": clean_start_ms,
                    "clean_end_ms": clean_end_ms,
                    "start_quality": start_quality,
                    "start_signals": start_signals,
                    "end_quality": end_quality,
                    "end_signals": end_signals,
                },
                "layout": layout_name,
                "canvas_regions": canvas_regions,
                "transcript": transcript_text,
                "emotion_peak": {
                    "energy": (
                        float(_ep_energy) if _ep_energy is not None
                        else None
                    ),
                    "arousal": (
                        float(_ep_arousal) if _ep_arousal is not None
                        else None
                    ),
                },
                "has_visual_reference": _vis_ref,
                "emphasis_pauses": _emph,
                "story_beat": moment_beat,
                "moment_character": moment_character,
            }
            moments.append(moment)

        # Re-sort by final score after face boost
        moments.sort(key=lambda m: float(m["score"]), reverse=True)  # type: ignore[arg-type]
        for i, m in enumerate(moments, start=1):
            m["rank"] = i

    except Exception as exc:
        logger.exception("find_best_moments failed for %s", project_id)
        return _error(
            "DISCOVERY_ERROR",
            f"Failed to find best moments: {exc}",
            {"project_id": project_id},
        )
    finally:
        conn.close()

    return {
        "project_id": project_id,
        "purpose": purpose,
        "moments": moments,
    }
