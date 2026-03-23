"""Discovery MCP tools for ClipCannon.

Provides tools for finding the best moments, querying scenes at
specific timestamps, and locating natural cut points in long-form
video content. These are read-only analytical tools that do not
charge credits.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.discovery_defs import DISCOVERY_TOOL_DEFINITIONS

__all__ = [
    "DISCOVERY_TOOL_DEFINITIONS",
    "dispatch_discovery_tool",
]

logger = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================
def _error(
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
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


def _projects_dir() -> Path:
    """Resolve projects base directory from config or default.

    Returns:
        Absolute path to the projects directory.
    """
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def _db_path(project_id: str) -> Path:
    """Build database path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project's analysis.db.
    """
    return _projects_dir() / project_id / "analysis.db"


def _validate_project(
    project_id: str, required_status: str | None = "ready"
) -> dict[str, object] | None:
    """Validate project exists and check status.

    Args:
        project_id: Project identifier.
        required_status: Required project status, or None to skip check.

    Returns:
        Error dict if validation fails, None on success.
    """
    db = _db_path(project_id)
    if not db.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")
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
            return _error("PROJECT_NOT_FOUND", f"No project record: {project_id}")
        status = str(row.get("status", ""))
        if required_status == "ready" and status not in (
            "ready",
            "ready_degraded",
            "analyzing",
        ):
            return _error(
                "INVALID_STATE",
                f"Project not ready, current status: {status}",
            )
    return None


def _parse_canvas_regions(
    canvas_json_str: str, layout: str | None, recommended: str
) -> tuple[str, list[dict[str, object]]]:
    """Parse canvas_regions_json and extract regions for a layout.

    Args:
        canvas_json_str: Raw JSON string from the scene_map row.
        layout: Requested layout (A/B/C/D) or None for recommended.
        recommended: The scene's recommended layout.

    Returns:
        Tuple of (target_layout, regions list).
    """
    try:
        all_canvas = json.loads(canvas_json_str)
    except (json.JSONDecodeError, TypeError):
        all_canvas = {}

    target_layout = layout if layout is not None else recommended
    regions: list[dict[str, object]] = []
    if isinstance(all_canvas, dict) and target_layout in all_canvas:
        raw = all_canvas[target_layout]
        if isinstance(raw, list):
            regions = raw
        elif isinstance(raw, dict):
            regions = [raw]
    return target_layout, regions


def _score_cut_point(
    conn: object,
    project_id: str,
    ms: int,
    search_range: int = 500,
) -> tuple[str, list[str]]:
    """Score a cut point by checking signal convergence within range.

    Looks for silence gaps, sentence endings, and scene boundaries
    near the given timestamp and returns a quality label plus the
    list of converging signals.

    Args:
        conn: Database connection.
        project_id: Project identifier.
        ms: Timestamp in milliseconds to evaluate.
        search_range: Window (ms) to search for converging signals.

    Returns:
        Tuple of (quality_label, list_of_signal_names).
    """
    signals: list[str] = []

    # Check silence gaps
    try:
        sg = fetch_one(
            conn,
            "SELECT start_ms FROM silence_gaps "
            "WHERE project_id = ? AND ABS(start_ms - ?) <= ?",
            (project_id, ms, search_range),
        )
        if sg:
            signals.append("silence_gap")
    except Exception:
        pass

    # Check sentence endings
    try:
        se = fetch_one(
            conn,
            "SELECT end_ms FROM transcript_segments "
            "WHERE project_id = ? AND ABS(end_ms - ?) <= ?",
            (project_id, ms, search_range),
        )
        if se:
            signals.append("sentence_end")
    except Exception:
        pass

    # Check scene boundaries
    try:
        sb = fetch_one(
            conn,
            "SELECT start_ms FROM scene_map "
            "WHERE project_id = ? AND ABS(start_ms - ?) <= ?",
            (project_id, ms, search_range),
        )
        if sb:
            signals.append("scene_boundary")
    except Exception:
        pass

    if len(signals) >= 3:
        quality = "perfect"
    elif len(signals) >= 2:
        quality = "excellent"
    else:
        quality = "good"
    return quality, signals


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


# ============================================================
# TOOL 2: clipcannon_get_scene_at
# ============================================================
async def clipcannon_get_scene_at(
    project_id: str,
    timestamp_ms: int,
    layout: str | None = None,
    include_neighbors: bool = False,
) -> dict[str, object]:
    """Point query: get scene data for a single timestamp.

    Returns the scene covering the given timestamp, or the closest
    scene if none matches exactly. Optionally includes previous
    and next scene summaries.

    Args:
        project_id: Project identifier.
        timestamp_ms: Target timestamp in milliseconds.
        layout: Layout to return (A/B/C/D) or None for recommended.
        include_neighbors: Whether to include prev/next scene summaries.

    Returns:
        Dictionary with scene data and optional neighbors.
    """
    err = _validate_project(project_id)
    if err is not None:
        return err

    if layout is not None and layout not in ("A", "B", "C", "D"):
        return _error(
            "INVALID_PARAMETER",
            f"layout must be A, B, C, or D, got: {layout}",
        )

    db = _db_path(project_id)
    conn = get_connection(str(db), enable_vec=False, dict_rows=True)

    try:
        # Try exact match first
        scene_row = fetch_one(
            conn,
            "SELECT * FROM scene_map "
            "WHERE project_id = ? AND start_ms <= ? AND end_ms >= ? "
            "LIMIT 1",
            (project_id, timestamp_ms, timestamp_ms),
        )

        exact_match = scene_row is not None

        # If no exact match, get closest scene
        if scene_row is None:
            scene_row = fetch_one(
                conn,
                "SELECT * FROM scene_map "
                "WHERE project_id = ? "
                "ORDER BY ABS(start_ms - ?) LIMIT 1",
                (project_id, timestamp_ms),
            )

        if scene_row is None:
            return _error(
                "SCENE_NOT_FOUND",
                "No scenes found. Run ingest first.",
                {"project_id": project_id, "timestamp_ms": timestamp_ms},
            )

        # Build scene response
        scene_id = int(scene_row["scene_id"])
        scene_start = int(scene_row["start_ms"])
        scene_end = int(scene_row["end_ms"])
        rec_layout = str(scene_row.get("layout_recommendation", "A"))

        canvas_json = str(scene_row.get("canvas_regions_json", "{}"))
        target_layout, canvas_regions = _parse_canvas_regions(
            canvas_json, layout, rec_layout
        )

        scene: dict[str, object] = {
            "scene_id": scene_id,
            "start_ms": scene_start,
            "end_ms": scene_end,
            "exact_match": exact_match,
            "layout": target_layout,
            "recommended_layout": rec_layout,
            "canvas_regions": canvas_regions,
            "content_type": str(scene_row.get("content_type", "unknown")),
            "face_size_pct": float(scene_row.get("face_size_pct", 0) or 0),
            "transcript_text": str(
                scene_row.get("transcript_text", "")
            ),
        }

        # Face info
        if scene_row.get("face_x") is not None:
            scene["face"] = {
                "x": int(scene_row["face_x"]),
                "y": int(scene_row["face_y"]),
                "w": int(scene_row["face_w"]),
                "h": int(scene_row["face_h"]),
                "confidence": float(
                    scene_row.get("face_confidence", 0.0)
                ),
            }

        # Webcam info
        if scene_row.get("webcam_x") is not None:
            scene["webcam"] = {
                "x": int(scene_row["webcam_x"]),
                "y": int(scene_row["webcam_y"]),
                "w": int(scene_row["webcam_w"]),
                "h": int(scene_row["webcam_h"]),
            }

        # Content region
        if scene_row.get("content_x") is not None:
            scene["content"] = {
                "x": int(scene_row["content_x"]),
                "y": int(scene_row["content_y"]),
                "w": int(scene_row["content_w"]),
                "h": int(scene_row["content_h"]),
            }

        response: dict[str, object] = {
            "project_id": project_id,
            "timestamp_ms": timestamp_ms,
            "scene": scene,
        }

        # Include neighbor scenes if requested
        if include_neighbors:
            prev_row = fetch_one(
                conn,
                "SELECT scene_id, start_ms, end_ms, "
                "layout_recommendation FROM scene_map "
                "WHERE project_id = ? AND end_ms <= ? "
                "ORDER BY end_ms DESC LIMIT 1",
                (project_id, scene_start),
            )
            next_row = fetch_one(
                conn,
                "SELECT scene_id, start_ms, end_ms, "
                "layout_recommendation FROM scene_map "
                "WHERE project_id = ? AND start_ms >= ? "
                "ORDER BY start_ms ASC LIMIT 1",
                (project_id, scene_end),
            )

            neighbors: dict[str, object] = {}
            if prev_row is not None:
                neighbors["previous"] = {
                    "scene_id": int(prev_row["scene_id"]),
                    "start_ms": int(prev_row["start_ms"]),
                    "end_ms": int(prev_row["end_ms"]),
                    "layout": str(
                        prev_row.get("layout_recommendation", "A")
                    ),
                }
            if next_row is not None:
                neighbors["next"] = {
                    "scene_id": int(next_row["scene_id"]),
                    "start_ms": int(next_row["start_ms"]),
                    "end_ms": int(next_row["end_ms"]),
                    "layout": str(
                        next_row.get("layout_recommendation", "A")
                    ),
                }
            response["neighbors"] = neighbors

    except Exception as exc:
        logger.exception("get_scene_at failed for %s", project_id)
        return _error(
            "DISCOVERY_ERROR",
            f"Failed to get scene at timestamp: {exc}",
            {"project_id": project_id, "timestamp_ms": timestamp_ms},
        )
    finally:
        conn.close()

    return response


# ============================================================
# TOOL 3: clipcannon_find_cut_points
# ============================================================
async def clipcannon_find_cut_points(
    project_id: str,
    around_ms: int,
    search_range_ms: int = 5000,
) -> dict[str, object]:
    """Find natural edit boundaries near a timestamp.

    Searches silence gaps, scene boundaries, sentence endings, and
    beat positions within the given range. Applies cross-stream
    convergence scoring: signals within 500ms are clustered and
    scored by how many distinct signal types converge (3+ = perfect,
    2 = excellent, 1 = good). Convergence clusters are merged into
    a single point at the median timestamp.

    Args:
        project_id: Project identifier.
        around_ms: Center timestamp to search around (ms).
        search_range_ms: Search window radius in ms (default 5000).

    Returns:
        Dictionary with convergence-scored cut points.
    """
    err = _validate_project(project_id)
    if err is not None:
        return err

    search_range_ms = max(1000, min(30_000, search_range_ms))
    range_start = max(0, around_ms - search_range_ms)
    range_end = around_ms + search_range_ms

    db = _db_path(project_id)
    conn = get_connection(str(db), enable_vec=False, dict_rows=True)

    cut_points: list[dict[str, object]] = []

    try:
        # 1. Silence gaps in range
        silence_rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, duration_ms FROM silence_gaps "
            "WHERE project_id = ? AND start_ms >= ? AND end_ms <= ? "
            "ORDER BY duration_ms DESC",
            (project_id, range_start, range_end),
        )
        for sg in silence_rows:
            gap_duration = int(sg["duration_ms"])
            # Midpoint of silence gap is the best cut point
            cut_ms = (int(sg["start_ms"]) + int(sg["end_ms"])) // 2
            quality = "excellent" if gap_duration >= 500 else "good"
            cut_points.append({
                "ms": cut_ms,
                "type": "silence_gap",
                "gap_duration_ms": gap_duration,
                "quality": quality,
            })

        # 2. Scene boundaries in range
        scene_rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms FROM scene_map "
            "WHERE project_id = ? AND ("
            "  start_ms BETWEEN ? AND ? OR "
            "  end_ms BETWEEN ? AND ?"
            ")",
            (project_id, range_start, range_end, range_start, range_end),
        )
        # Collect unique boundary timestamps
        boundary_set: set[int] = set()
        for sr in scene_rows:
            s_start = int(sr["start_ms"])
            s_end = int(sr["end_ms"])
            if range_start <= s_start <= range_end:
                boundary_set.add(s_start)
            if range_start <= s_end <= range_end:
                boundary_set.add(s_end)

        for boundary_ms in sorted(boundary_set):
            cut_points.append({
                "ms": boundary_ms,
                "type": "scene_boundary",
                "quality": "good",
            })

        # 3. Sentence endings in range
        sentence_rows = fetch_all(
            conn,
            "SELECT end_ms, text FROM transcript_segments "
            "WHERE project_id = ? AND end_ms BETWEEN ? AND ? "
            "ORDER BY end_ms",
            (project_id, range_start, range_end),
        )
        for tr in sentence_rows:
            text = str(tr["text"]).strip()
            # Show last 60 chars as context
            text_before = text[-60:] if len(text) > 60 else text
            cut_points.append({
                "ms": int(tr["end_ms"]),
                "type": "sentence_end",
                "text_before": text_before,
                "quality": "good",
            })

        # 4. Beat positions (from beats table — stored as JSON array in beat_positions_ms)
        try:
            beats_row = fetch_one(
                conn,
                "SELECT beat_positions_ms FROM beats WHERE project_id = ? LIMIT 1",
                (project_id,),
            )
            if beats_row and beats_row.get("beat_positions_ms"):
                import json as json_mod
                beat_positions = json_mod.loads(str(beats_row["beat_positions_ms"]))
                for bp_ms in beat_positions:
                    bp_ms = int(bp_ms)
                    if range_start <= bp_ms <= range_end:
                        cut_points.append({
                            "ms": bp_ms,
                            "type": "beat_hit",
                            "quality": "good",
                        })
        except Exception as exc:
            logger.debug("Beat position lookup skipped: %s", exc)

    except Exception as exc:
        logger.exception("find_cut_points failed for %s", project_id)
        return _error(
            "DISCOVERY_ERROR",
            f"Failed to find cut points: {exc}",
            {"project_id": project_id, "around_ms": around_ms},
        )
    finally:
        conn.close()

    # --- Cross-stream convergence scoring ---
    CONVERGENCE_WINDOW_MS = 500

    # Group cut points into clusters by proximity
    cut_points.sort(key=lambda cp: cp["ms"])
    clusters: list[list[dict[str, object]]] = []
    current_cluster: list[dict[str, object]] = []

    for cp in cut_points:
        if not current_cluster:
            current_cluster = [cp]
        elif int(cp["ms"]) - int(current_cluster[0]["ms"]) <= CONVERGENCE_WINDOW_MS:
            current_cluster.append(cp)
        else:
            clusters.append(current_cluster)
            current_cluster = [cp]
    if current_cluster:
        clusters.append(current_cluster)

    # Score each cluster based on signal convergence
    scored_points: list[dict[str, object]] = []
    for cluster in clusters:
        signal_types = set(str(cp["type"]) for cp in cluster)
        n_signals = len(signal_types)

        if n_signals >= 3:
            quality = "perfect"
        elif n_signals >= 2:
            quality = "excellent"
        else:
            quality = "good"

        # Median timestamp
        ms_values = sorted(int(cp["ms"]) for cp in cluster)
        median_ms = ms_values[len(ms_values) // 2]

        # Build merged point
        merged: dict[str, object] = {
            "ms": median_ms,
            "quality": quality,
        }

        if n_signals > 1:
            merged["type"] = "convergence"
            merged["signals"] = sorted(signal_types)
        else:
            merged["type"] = cluster[0]["type"]

        # Carry forward metadata from constituent signals
        for cp in cluster:
            if cp.get("gap_duration_ms"):
                merged["gap_duration_ms"] = cp["gap_duration_ms"]
            if cp.get("text_before"):
                merged["text_before"] = cp["text_before"]

        scored_points.append(merged)

    # Sort by quality (perfect > excellent > good), then proximity
    quality_order = {"perfect": 0, "excellent": 1, "good": 2}
    scored_points.sort(
        key=lambda cp: (
            quality_order.get(str(cp["quality"]), 3),
            abs(int(cp["ms"]) - around_ms),
        )
    )

    return {
        "project_id": project_id,
        "timestamp_ms": around_ms,
        "search_range_ms": search_range_ms,
        "cut_points": scored_points,
    }


# ============================================================
# TOOL 4: clipcannon_get_narrative_flow
# ============================================================

# Keywords that signal the speaker is about to demonstrate something.
# If the gap after such a sentence is >5s, warn about a broken promise.
PROMISE_KEYWORDS: list[str] = [
    "let me show",
    "watch this",
    "here's what",
    "check this out",
    "you can see",
    "look at",
    "the reason is",
    "here's why",
    "so what happened",
    "the result",
    "and then",
    "so basically",
]

# Keywords that mark important content in gap summaries.
_KEY_PHRASE_MARKERS: list[str] = [
    "first",
    "never",
    "always",
    "better",
    "worse",
    "more",
    "less",
    "million",
    "billion",
    "percent",
    "compared",
]


def _extract_sentences(text: str) -> list[str]:
    """Split text into sentences on common terminators.

    Args:
        text: Raw transcript text.

    Returns:
        List of non-empty trimmed sentences.
    """
    import re

    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def _thought_complete(sentence: str) -> bool:
    """Check whether a sentence ends with a complete-thought punctuation.

    Args:
        sentence: The sentence text to check.

    Returns:
        True if the sentence ends with `.`, `!`, or `?`.
    """
    return sentence.rstrip().endswith((".", "!", "?"))


def _has_promise(text: str) -> str | None:
    """Return the first matching promise keyword found in *text*.

    Args:
        text: Lowercased text to scan.

    Returns:
        The matched keyword, or None.
    """
    lower = text.lower()
    for kw in PROMISE_KEYWORDS:
        if kw in lower:
            return kw
    return None


def _extract_key_phrases(text: str, max_chars: int = 200) -> str:
    """Build a truncated summary that preserves key phrases.

    For long gap transcripts, extract sentences containing numbers,
    product names, superlatives, or comparison words and truncate.

    Args:
        text: Full gap transcript text.
        max_chars: Maximum character length for the summary.

    Returns:
        Truncated text with key phrases preserved.
    """
    import re

    sentences = _extract_sentences(text)
    key_sentences: list[str] = []
    other_sentences: list[str] = []

    for sent in sentences:
        lower = sent.lower()
        has_number = bool(re.search(r"\d+", sent))
        has_marker = any(m in lower for m in _KEY_PHRASE_MARKERS)
        if has_number or has_marker:
            key_sentences.append(sent)
        else:
            other_sentences.append(sent)

    # Build output prioritising key sentences
    parts = key_sentences + other_sentences
    result = " ".join(parts)
    if len(result) <= max_chars:
        return result
    return result[: max_chars - len("[truncated]")] + "[truncated]"


async def clipcannon_get_narrative_flow(
    project_id: str,
    segments: list[dict[str, int]],
) -> dict[str, object]:
    """Analyze narrative coherence of proposed edit segments.

    Takes a list of proposed segment time ranges and returns what the
    speaker says at each boundary plus what's being skipped in each gap.
    Use this BEFORE creating an edit to verify the story makes sense.

    Args:
        project_id: Project identifier.
        segments: List of {"start_ms": int, "end_ms": int} dicts
                  representing proposed source time ranges.

    Returns:
        Narrative flow analysis with per-segment transcripts and gap
        warnings.
    """
    err = _validate_project(project_id)
    if err is not None:
        return err

    if not segments:
        return _error(
            "INVALID_PARAMETER",
            "segments must contain at least one entry",
        )

    # Validate and normalise segments
    parsed_segments: list[tuple[int, int]] = []
    for i, seg in enumerate(segments):
        s = seg.get("start_ms")
        e = seg.get("end_ms")
        if s is None or e is None:
            return _error(
                "INVALID_PARAMETER",
                f"Segment {i} missing start_ms or end_ms",
            )
        s_int, e_int = int(s), int(e)
        if e_int <= s_int:
            return _error(
                "INVALID_PARAMETER",
                f"Segment {i}: end_ms must be > start_ms",
            )
        parsed_segments.append((s_int, e_int))

    # Sort segments by start time
    parsed_segments.sort(key=lambda t: t[0])

    db = _db_path(project_id)
    conn = get_connection(str(db), enable_vec=False, dict_rows=True)

    flow: list[dict[str, object]] = []
    warnings: list[str] = []
    total_duration_ms = 0
    seg_index = 0
    gap_index = 0

    try:
        for idx, (seg_start, seg_end) in enumerate(parsed_segments):
            seg_index += 1
            seg_duration = seg_end - seg_start
            total_duration_ms += seg_duration

            # Fetch transcript rows overlapping this segment
            seg_rows = fetch_all(
                conn,
                "SELECT start_ms, end_ms, text FROM transcript_segments "
                "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
                "ORDER BY start_ms",
                (project_id, seg_end, seg_start),
            )

            full_text = " ".join(str(r["text"]) for r in seg_rows)
            sentences = _extract_sentences(full_text)
            first_sentence = sentences[0] if sentences else ""
            last_sentence = sentences[-1] if sentences else ""

            flow.append({
                "segment": seg_index,
                "source_range": f"{seg_start}-{seg_end}ms",
                "duration_ms": seg_duration,
                "first_sentence": first_sentence,
                "last_sentence": last_sentence,
                "thought_complete": _thought_complete(last_sentence)
                if last_sentence
                else True,
            })

            # Check for a gap to the NEXT segment
            if idx < len(parsed_segments) - 1:
                next_start = parsed_segments[idx + 1][0]
                gap_start = seg_end
                gap_end = next_start

                if gap_end <= gap_start:
                    # Segments overlap or are contiguous — no gap
                    continue

                gap_index += 1
                gap_duration = gap_end - gap_start

                # Fetch transcript in the gap
                gap_rows = fetch_all(
                    conn,
                    "SELECT start_ms, end_ms, text "
                    "FROM transcript_segments "
                    "WHERE project_id = ? "
                    "AND start_ms < ? AND end_ms > ? "
                    "ORDER BY start_ms",
                    (project_id, gap_end, gap_start),
                )

                gap_text = " ".join(str(r["text"]) for r in gap_rows)
                word_count = len(gap_text.split()) if gap_text.strip() else 0

                # --- Promise-payoff detection ---
                # Check last 2 sentences of the preceding segment
                warning: str | None = None
                check_text = " ".join(sentences[-2:]) if sentences else ""
                promise_kw = _has_promise(check_text)
                if promise_kw and gap_duration > 5000:
                    warning = (
                        f"BROKEN_PROMISE: speaker says '{promise_kw}' "
                        f"but the continuation is in this gap"
                    )
                    warnings.append(
                        f"Gap {gap_index}: Speaker says '{promise_kw}' "
                        f"at end of segment {seg_index} but the "
                        f"continuation happens in this gap."
                    )

                # --- Large gap detection ---
                if warning is None and gap_duration > 10_000:
                    gap_seconds = gap_duration // 1000
                    # Extract key phrases for summary
                    gap_sentences = _extract_sentences(gap_text)
                    key_bits: list[str] = []
                    import re as _re

                    for gs in gap_sentences:
                        lower = gs.lower()
                        has_num = bool(_re.search(r"\d+", gs))
                        has_marker = any(
                            m in lower for m in _KEY_PHRASE_MARKERS
                        )
                        if has_num or has_marker:
                            key_bits.append(gs)
                    key_str = (
                        ". Key phrases: " + ", ".join(
                            repr(k[:60]) for k in key_bits[:5]
                        )
                        if key_bits
                        else ""
                    )
                    warning = (
                        f"LARGE_GAP: {gap_seconds}s of content skipped "
                        f"({word_count} words){key_str}"
                    )
                    warnings.append(
                        f"Gap {gap_index}: {gap_seconds}s skipped "
                        f"between segments {seg_index}-{seg_index + 1}. "
                        f"Contains {word_count} words of content."
                    )

                # Build skipped_text (truncate for large gaps)
                skipped_text: str
                if gap_duration > 10_000 and len(gap_text) > 200:
                    skipped_text = _extract_key_phrases(gap_text, 200)
                else:
                    skipped_text = gap_text

                flow.append({
                    "gap": gap_index,
                    "source_range": f"{gap_start}-{gap_end}ms",
                    "duration_ms": gap_duration,
                    "skipped_text": skipped_text,
                    "word_count": word_count,
                    "warning": warning,
                })

    except Exception as exc:
        logger.exception(
            "get_narrative_flow failed for %s", project_id
        )
        return _error(
            "DISCOVERY_ERROR",
            f"Failed to analyze narrative flow: {exc}",
            {"project_id": project_id},
        )
    finally:
        conn.close()

    # Enrich with LLM narrative analysis if available
    llm_narrative: dict[str, object] | None = None
    try:
        conn2 = get_connection(str(db), enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn2,
                "SELECT analysis_json FROM narrative_analysis "
                "WHERE project_id = ? LIMIT 1",
                (project_id,),
            )
            if row and row.get("analysis_json"):
                llm_data = json.loads(str(row["analysis_json"]))
                llm_narrative = {
                    "story_beats": llm_data.get("story_beats", []),
                    "open_loops": llm_data.get("open_loops", []),
                    "chapter_boundaries": llm_data.get("chapter_boundaries", []),
                    "key_moments": llm_data.get("key_moments", []),
                    "narrative_summary": llm_data.get("narrative_summary"),
                }
        finally:
            conn2.close()
    except Exception:
        # Table may not exist yet; not a failure
        pass

    return {
        "project_id": project_id,
        "segment_count": len(parsed_segments),
        "total_duration_ms": total_duration_ms,
        "flow": flow,
        "warnings": warnings,
        "llm_narrative": llm_narrative,
    }


# ============================================================
# DISPATCH
# ============================================================
async def dispatch_discovery_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch a discovery tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_find_best_moments":
        return await clipcannon_find_best_moments(
            project_id=str(arguments["project_id"]),
            purpose=str(arguments["purpose"]),
            target_duration_s=int(arguments.get("target_duration_s", 30)),  # type: ignore[arg-type]
            count=int(arguments.get("count", 5)),  # type: ignore[arg-type]
        )
    if name == "clipcannon_find_cut_points":
        return await clipcannon_find_cut_points(
            project_id=str(arguments["project_id"]),
            around_ms=int(arguments["around_ms"]),  # type: ignore[arg-type]
            search_range_ms=int(arguments.get("search_range_ms", 5000)),  # type: ignore[arg-type]
        )
    if name == "clipcannon_get_narrative_flow":
        raw_segs = arguments.get("segments", [])
        segs: list[dict[str, int]] = [
            {
                "start_ms": int(s["start_ms"]),  # type: ignore[arg-type, index]
                "end_ms": int(s["end_ms"]),  # type: ignore[arg-type, index]
            }
            for s in raw_segs  # type: ignore[union-attr]
        ]
        return await clipcannon_get_narrative_flow(
            project_id=str(arguments["project_id"]),
            segments=segs,
        )

    return _error(
        "INTERNAL_ERROR",
        f"Unknown discovery tool: {name}",
        {"tool": name},
    )
