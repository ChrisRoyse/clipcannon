"""Auto-trim: remove filler words and long pauses from video.

Analyzes transcript words and silence gaps to build optimized segments
that skip fillers (um, uh, like, you know) and dead air. Segments are
directly usable with ``clipcannon_create_edit``.
"""

from __future__ import annotations

import logging

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one, table_exists

logger = logging.getLogger(__name__)

FILLER_WORDS: frozenset[str] = frozenset({
    "um", "uh", "uhm", "uhh", "hmm", "hm",
    "like", "basically", "literally", "actually",
    "you know", "i mean", "right", "okay", "ok",
    "so", "well", "yeah", "yep", "erm",
})


def analyze_fillers(
    db_path: str,
    project_id: str,
    filler_words: frozenset[str] | None = None,
    min_confidence: float = 0.5,
) -> list[dict[str, object]]:
    """Find filler words in transcript_words table.

    Returns list of dicts with: word, start_ms, end_ms, confidence, word_id.
    Handles multi-word fillers (e.g. "you know") via consecutive-word matching.
    """
    effective = filler_words if filler_words is not None else FILLER_WORDS
    single = frozenset(w for w in effective if " " not in w)
    multi: dict[str, list[str]] = {
        p: p.split() for p in effective if " " in p
    }

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT word_id, word, start_ms, end_ms, confidence "
            "FROM transcript_words WHERE segment_id IN ("
            "SELECT segment_id FROM transcript_segments WHERE project_id = ?"
            ") ORDER BY start_ms",
            (project_id,),
        )
    finally:
        conn.close()

    if not rows:
        logger.warning("No transcript words for project %s", project_id)
        return []

    results: list[dict[str, object]] = []
    consumed: set[int] = set()

    # Multi-word filler detection (greedy, left-to-right)
    for phrase, tokens in multi.items():
        n = len(tokens)
        for i in range(len(rows) - n + 1):
            if i in consumed:
                continue
            ok = True
            for j, tok in enumerate(tokens):
                idx = i + j
                if idx in consumed:
                    ok = False
                    break
                w = str(rows[idx]["word"]).lower().strip(".,!?;:")
                c = float(rows[idx].get("confidence") or 0.0)
                if w != tok or c < min_confidence:
                    ok = False
                    break
            if ok:
                consumed.update(range(i, i + n))
                results.append({
                    "word": phrase,
                    "start_ms": rows[i]["start_ms"],
                    "end_ms": rows[i + n - 1]["end_ms"],
                    "confidence": min(
                        float(rows[i + k].get("confidence") or 0.0)
                        for k in range(n)
                    ),
                    "word_id": rows[i]["word_id"],
                })

    # Single-word filler detection
    for i, row in enumerate(rows):
        if i in consumed:
            continue
        w = str(row["word"]).lower().strip(".,!?;:")
        c = float(row.get("confidence") or 0.0)
        if w in single and c >= min_confidence:
            results.append({
                "word": w, "start_ms": row["start_ms"],
                "end_ms": row["end_ms"], "confidence": c,
                "word_id": row["word_id"],
            })

    results.sort(key=lambda d: int(d["start_ms"]))  # type: ignore[arg-type]
    logger.info("Found %d fillers in project %s", len(results), project_id)
    return results


def analyze_long_pauses(
    db_path: str,
    project_id: str,
    threshold_ms: int = 800,
) -> list[dict[str, object]]:
    """Find silence gaps exceeding threshold.

    Queries silence_gaps table. Returns list of dicts with:
    start_ms, end_ms, duration_ms. Returns empty if table missing.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        if not table_exists(conn, "silence_gaps"):
            logger.warning("silence_gaps table missing for %s", project_id)
            return []
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, (end_ms - start_ms) AS duration_ms "
            "FROM silence_gaps WHERE project_id = ? AND (end_ms - start_ms) >= ? "
            "ORDER BY start_ms",
            (project_id, threshold_ms),
        )
    finally:
        conn.close()

    logger.info("Found %d pauses (>=%dms) in %s", len(rows), threshold_ms, project_id)
    return rows  # type: ignore[return-value]


def build_trimmed_segments(
    source_duration_ms: int,
    fillers: list[dict[str, object]],
    pauses: list[dict[str, object]],
    merge_gap_ms: int = 200,
    min_segment_ms: int = 500,
) -> list[dict[str, object]]:
    """Build segments that skip filler words and long pauses.

    Algorithm:
    1. Collect all "dead zones" (filler + pause time ranges)
    2. Sort dead zones by start_ms
    3. Merge overlapping dead zones
    4. Build segments from gaps between dead zones
    5. Merge adjacent segments separated by < merge_gap_ms
    6. Drop segments shorter than min_segment_ms

    Returns list of dicts: {source_start_ms, source_end_ms, duration_ms}
    """
    if source_duration_ms <= 0:
        return []

    # 1. Collect dead zones
    dead: list[tuple[int, int]] = []
    for item in (*fillers, *pauses):
        s, e = int(item["start_ms"]), int(item["end_ms"])
        if s < e:
            dead.append((s, e))

    if not dead:
        return [{"source_start_ms": 0, "source_end_ms": source_duration_ms,
                 "duration_ms": source_duration_ms}]

    # 2-3. Sort and merge overlapping dead zones
    dead.sort()
    merged_dead: list[tuple[int, int]] = [dead[0]]
    for start, end in dead[1:]:
        ps, pe = merged_dead[-1]
        if start <= pe:
            merged_dead[-1] = (ps, max(pe, end))
        else:
            merged_dead.append((start, end))

    # 4. Build keep-segments from gaps
    keep: list[tuple[int, int]] = []
    cursor = 0
    for dz_start, dz_end in merged_dead:
        if cursor < dz_start:
            keep.append((cursor, dz_start))
        cursor = max(cursor, dz_end)
    if cursor < source_duration_ms:
        keep.append((cursor, source_duration_ms))
    if not keep:
        return []

    # 5. Merge adjacent keep-segments separated by < merge_gap_ms
    merged: list[tuple[int, int]] = [keep[0]]
    for ss, se in keep[1:]:
        ps, pe = merged[-1]
        if ss - pe < merge_gap_ms:
            merged[-1] = (ps, se)
        else:
            merged.append((ss, se))

    # 6. Drop short segments
    segments: list[dict[str, object]] = []
    for ss, se in merged:
        dur = se - ss
        if dur >= min_segment_ms:
            segments.append({"source_start_ms": ss, "source_end_ms": se,
                             "duration_ms": dur})

    logger.debug("Built %d segments from %d dead zones", len(segments), len(merged_dead))
    return segments


def auto_trim(
    db_path: str,
    project_id: str,
    filler_words: frozenset[str] | None = None,
    pause_threshold_ms: int = 800,
    merge_gap_ms: int = 200,
    min_segment_ms: int = 500,
) -> dict[str, object]:
    """Main entry point. Combines filler + pause analysis + segment building.

    Returns dict with: segments, removed_fillers, removed_pauses,
    original_duration_ms, trimmed_duration_ms, time_saved_ms,
    time_saved_pct, filler_details, pause_details.

    Raises ValueError if project not found.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn, "SELECT duration_ms FROM project WHERE project_id = ?",
            (project_id,),
        )
    finally:
        conn.close()

    if row is None:
        msg = f"Project {project_id!r} not found in database at {db_path}"
        raise ValueError(msg)

    source_duration_ms = int(row["duration_ms"])

    fillers = analyze_fillers(db_path, project_id, filler_words=filler_words)
    pauses = analyze_long_pauses(db_path, project_id, threshold_ms=pause_threshold_ms)
    segments = build_trimmed_segments(
        source_duration_ms, fillers, pauses,
        merge_gap_ms=merge_gap_ms, min_segment_ms=min_segment_ms,
    )

    trimmed_ms = sum(int(s["duration_ms"]) for s in segments)
    saved_ms = source_duration_ms - trimmed_ms
    saved_pct = (saved_ms / source_duration_ms * 100.0) if source_duration_ms > 0 else 0.0

    logger.info("Auto-trim %s: %d segs, saved %dms (%.1f%%)",
                project_id, len(segments), saved_ms, saved_pct)

    return {
        "segments": segments,
        "removed_fillers": len(fillers),
        "removed_pauses": len(pauses),
        "original_duration_ms": source_duration_ms,
        "trimmed_duration_ms": trimmed_ms,
        "time_saved_ms": saved_ms,
        "time_saved_pct": round(saved_pct, 2),
        "filler_details": fillers,
        "pause_details": pauses,
    }
