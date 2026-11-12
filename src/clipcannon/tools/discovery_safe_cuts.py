"""Discovery MCP tool: clipcannon_find_safe_cuts."""

from __future__ import annotations

import json
import logging

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.discovery_common import _db_path, _error, _validate_project
from clipcannon.tools.discovery_narrative import PROMISE_KEYWORDS

logger = logging.getLogger(__name__)


# ============================================================
# TOOL 4: clipcannon_find_safe_cuts
# ============================================================
async def clipcannon_find_safe_cuts(
    project_id: str,
    min_silence_ms: int = 400,
) -> dict[str, object]:
    """Find audio-safe cut points across the entire video.

    Cross-references silence gaps, sentence endings, beat positions,
    scene boundaries, text change events, and emotion energy to produce
    scored cut points with recommended padding.

    Args:
        project_id: Project identifier.
        min_silence_ms: Minimum silence gap duration in ms (default 400).

    Returns:
        Dictionary with scored safe-cut points.
    """
    err = _validate_project(project_id)
    if err is not None:
        return err

    min_silence_ms = max(50, min_silence_ms)

    db = _db_path(project_id)
    conn = get_connection(str(db), enable_vec=False, dict_rows=True)

    try:
        # Video duration
        proj = fetch_one(
            conn,
            "SELECT duration_ms FROM project WHERE project_id = ?",
            (project_id,),
        )
        if proj is None:
            return _error("PROJECT_NOT_FOUND", f"No project record: {project_id}")
        video_duration = int(proj["duration_ms"])

        # 1. Fetch silence gaps above threshold
        gaps = fetch_all(
            conn,
            "SELECT start_ms, end_ms, duration_ms FROM silence_gaps "
            "WHERE project_id = ? AND duration_ms >= ? "
            "ORDER BY start_ms",
            (project_id, min_silence_ms),
        )
        if not gaps:
            return {
                "project_id": project_id,
                "total_safe_cuts": 0,
                "video_duration_ms": video_duration,
                "cuts": [],
                "message": "No silence gaps found above threshold.",
            }

        # 2. Pre-fetch beat positions
        beat_positions: list[int] = []
        try:
            beats_row = fetch_one(
                conn,
                "SELECT beat_positions_ms FROM beats "
                "WHERE project_id = ? LIMIT 1",
                (project_id,),
            )
            if beats_row and beats_row.get("beat_positions_ms"):
                beat_positions = [
                    int(b) for b in json.loads(
                        str(beats_row["beat_positions_ms"])
                    )
                ]
        except Exception:
            pass

        # 3. Pre-fetch scene boundaries
        scene_boundaries: list[int] = []
        try:
            scene_rows = fetch_all(
                conn,
                "SELECT start_ms, end_ms FROM scene_map "
                "WHERE project_id = ?",
                (project_id,),
            )
            sb_set: set[int] = set()
            for sr in scene_rows:
                sb_set.add(int(sr["start_ms"]))
                sb_set.add(int(sr["end_ms"]))
            scene_boundaries = sorted(sb_set)
        except Exception:
            pass

        # 4. Pre-fetch text change events (no project_id column)
        text_change_timestamps: list[int] = []
        try:
            tce_rows = fetch_all(
                conn,
                "SELECT timestamp_ms FROM text_change_events "
                "ORDER BY timestamp_ms",
                (),
            )
            text_change_timestamps = [int(r["timestamp_ms"]) for r in tce_rows]
        except Exception:
            pass

        # 5. Process each silence gap
        cuts: list[dict[str, object]] = []

        for gap in gaps:
            gap_start = int(gap["start_ms"])
            gap_end = int(gap["end_ms"])
            gap_duration = int(gap["duration_ms"])
            gap_mid = (gap_start + gap_end) // 2

            # --- Words before the gap ---
            words_before_rows: list[dict[str, object]] = []
            try:
                words_before_rows = fetch_all(
                    conn,
                    "SELECT word, end_ms, confidence FROM transcript_words "
                    "WHERE end_ms <= ? ORDER BY end_ms DESC LIMIT 3",
                    (gap_start + 100,),
                )
            except Exception:
                pass

            # --- Words after the gap ---
            words_after_rows: list[dict[str, object]] = []
            try:
                words_after_rows = fetch_all(
                    conn,
                    "SELECT word, start_ms, confidence FROM transcript_words "
                    "WHERE start_ms >= ? ORDER BY start_ms ASC LIMIT 3",
                    (gap_end - 100,),
                )
            except Exception:
                pass

            words_before_text = " ".join(
                str(w["word"]) for w in reversed(words_before_rows)
            )
            words_after_text = " ".join(
                str(w["word"]) for w in words_after_rows
            )

            # --- Sentence ending check ---
            thought_complete = False
            sentence_end = False
            try:
                seg_row = fetch_one(
                    conn,
                    "SELECT text FROM transcript_segments "
                    "WHERE project_id = ? AND end_ms >= ? AND start_ms <= ? "
                    "ORDER BY ABS(end_ms - ?) ASC LIMIT 1",
                    (project_id, gap_start - 500, gap_start + 100, gap_start),
                )
                if seg_row:
                    seg_text = str(seg_row["text"]).rstrip()
                    if seg_text.endswith((".", "!", "?")):
                        sentence_end = True
                        thought_complete = True
                    elif seg_text.lower().endswith("right"):
                        thought_complete = True
            except Exception:
                pass

            # --- Beat alignment ---
            beat_aligned = False
            nearest_beat: int | None = None
            if beat_positions:
                closest = min(beat_positions, key=lambda b: abs(b - gap_mid))
                if abs(closest - gap_mid) <= 500:
                    beat_aligned = True
                    nearest_beat = closest

            # --- Scene boundary ---
            scene_boundary = False
            if scene_boundaries:
                closest_sb = min(
                    scene_boundaries, key=lambda s: abs(s - gap_mid)
                )
                if abs(closest_sb - gap_mid) <= 500:
                    scene_boundary = True

            # --- Text change event ---
            text_change = False
            if text_change_timestamps:
                closest_tc = min(
                    text_change_timestamps, key=lambda t: abs(t - gap_mid)
                )
                if abs(closest_tc - gap_mid) <= 1000:
                    text_change = True

            # --- Emotion energy ---
            energy: float | None = None
            try:
                emo_row = fetch_one(
                    conn,
                    "SELECT energy FROM emotion_curve "
                    "WHERE project_id = ? AND start_ms <= ? AND end_ms >= ? "
                    "LIMIT 1",
                    (project_id, gap_mid, gap_mid),
                )
                if emo_row and emo_row.get("energy") is not None:
                    energy = round(float(emo_row["energy"]), 3)
            except Exception:
                pass

            # --- Safety score ---
            score = 40  # base: silence gap exists
            if thought_complete:
                score += 20
            if beat_aligned:
                score += 15
            if scene_boundary:
                score += 10
            if text_change:
                score += 10
            if gap_duration >= 800:
                score += 5

            # Penalty: low confidence on last word (mid-word clip)
            if words_before_rows:
                last_conf = float(words_before_rows[0].get("confidence", 1.0))
                if last_conf < 0.5:
                    score -= 20

            # Penalty: promise keyword in last 2 words before gap
            warning: str | None = None
            if words_before_rows:
                last_2_words = " ".join(
                    str(w["word"]).lower()
                    for w in reversed(words_before_rows[:2])
                )
                for kw in PROMISE_KEYWORDS:
                    if kw in last_2_words:
                        score -= 30
                        warning = f"PROMISE_OPEN: speaker says '{kw}'"
                        break

            score = max(0, min(100, score))

            # --- Recommended padding ---
            cut_before_ms = gap_start - 50
            cut_after_ms = gap_end + 50

            # Snap cut_before to nearest beat if aligned
            if beat_aligned and nearest_beat is not None:
                if nearest_beat <= gap_start:
                    cut_before_ms = nearest_beat

            # --- Build signals list ---
            signals: list[str] = ["silence_gap"]
            if sentence_end:
                signals.append("sentence_end")
            if thought_complete and not sentence_end:
                signals.append("thought_complete")
            if beat_aligned:
                signals.append("beat_hit")
            if scene_boundary:
                signals.append("scene_boundary")
            if text_change:
                signals.append("text_change")

            cuts.append({
                "cut_ms": gap_mid,
                "cut_before_ms": max(0, cut_before_ms),
                "cut_after_ms": min(video_duration, cut_after_ms),
                "safety_score": score,
                "silence_gap_ms": gap_duration,
                "words_before": words_before_text,
                "words_after": words_after_text,
                "thought_complete": thought_complete,
                "sentence_end": sentence_end,
                "beat_aligned": beat_aligned,
                "scene_boundary": scene_boundary,
                "text_change": text_change,
                "energy": energy,
                "signals": signals,
                "warning": warning,
            })

        # Sort by safety_score DESC, then timestamp ASC
        cuts.sort(key=lambda c: (-c["safety_score"], c["cut_ms"]))

    except Exception as exc:
        logger.exception("find_safe_cuts failed for %s", project_id)
        return _error(
            "DISCOVERY_ERROR",
            f"Failed to find safe cuts: {exc}",
            {"project_id": project_id},
        )
    finally:
        conn.close()

    return {
        "project_id": project_id,
        "total_safe_cuts": len(cuts),
        "video_duration_ms": video_duration,
        "cuts": cuts,
    }
