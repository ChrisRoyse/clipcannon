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
    Applies purpose-aware scoring adjustments.

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

            scored_highlights.append({
                **dict(h),
                "_adjusted_score": adjusted_score,
            })

        # Sort by adjusted score descending
        scored_highlights.sort(
            key=lambda x: float(x["_adjusted_score"]),  # type: ignore[arg-type]
            reverse=True,
        )

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

            moment: dict[str, object] = {
                "rank": rank_idx,
                "start_ms": h_start,
                "end_ms": h_end,
                "score": round(adjusted_score, 4),
                "reason": str(h.get("reason", "from highlights table")),
                "cut_points": {
                    "clean_start_ms": clean_start_ms,
                    "clean_end_ms": clean_end_ms,
                },
                "layout": layout_name,
                "canvas_regions": canvas_regions,
                "transcript": transcript_text,
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
    beat positions within the given range. Returns combined cut points
    sorted by quality: silence_gap > beat_hit > scene_boundary > sentence_end.

    Args:
        project_id: Project identifier.
        around_ms: Center timestamp to search around (ms).
        search_range_ms: Search window radius in ms (default 5000).

    Returns:
        Dictionary with ranked cut points.
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

    # Deduplicate by ms value, keeping the highest-priority entry
    # (silence_gap > beat_hit > scene_boundary > sentence_end)
    type_priority = {"silence_gap": 0, "beat_hit": 1, "scene_boundary": 2, "sentence_end": 3}
    quality_priority = {"excellent": 0, "good": 1}

    cut_points.sort(
        key=lambda cp: (
            quality_priority.get(str(cp["quality"]), 9),
            type_priority.get(str(cp["type"]), 9),
        )
    )

    seen_ms: set[int] = set()
    unique_points: list[dict[str, object]] = []
    for cp in cut_points:
        ms_val = int(cp["ms"])
        if ms_val not in seen_ms:
            seen_ms.add(ms_val)
            unique_points.append(cp)

    # Sort by quality tier, type priority, then proximity to around_ms
    unique_points.sort(
        key=lambda cp: (
            quality_priority.get(str(cp["quality"]), 9),
            type_priority.get(str(cp["type"]), 9),
            abs(int(cp["ms"]) - around_ms),
        )
    )

    return {
        "project_id": project_id,
        "timestamp_ms": around_ms,
        "search_range_ms": search_range_ms,
        "cut_points": unique_points,
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
    if name == "clipcannon_get_scene_at":
        layout_raw = arguments.get("layout")
        return await clipcannon_get_scene_at(
            project_id=str(arguments["project_id"]),
            timestamp_ms=int(arguments["timestamp_ms"]),  # type: ignore[arg-type]
            layout=str(layout_raw) if layout_raw is not None else None,
            include_neighbors=bool(arguments.get("include_neighbors", False)),
        )
    if name == "clipcannon_find_cut_points":
        return await clipcannon_find_cut_points(
            project_id=str(arguments["project_id"]),
            around_ms=int(arguments["around_ms"]),  # type: ignore[arg-type]
            search_range_ms=int(arguments.get("search_range_ms", 5000)),  # type: ignore[arg-type]
        )

    return _error(
        "INTERNAL_ERROR",
        f"Unknown discovery tool: {name}",
        {"tool": name},
    )
