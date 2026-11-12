"""Discovery MCP tool: clipcannon_find_cut_points and cut-point scoring."""

from __future__ import annotations

import logging

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.discovery_common import _db_path, _error, _validate_project

logger = logging.getLogger(__name__)


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
# TOOL 2: clipcannon_find_cut_points
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
