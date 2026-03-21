"""Multi-signal highlight scoring pipeline stage for ClipCannon.

Computes highlight scores for candidate time windows using a weighted
combination of seven signals: emotion energy, reaction presence,
semantic density, narrative completeness, visual variety, visual
quality, and speaker confidence. This is an optional stage.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all, fetch_one
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)

OPERATION = "highlight_scoring"
STAGE = "highlights"

# Scoring weights from the PRD
W_EMOTION = 0.25
W_REACTION = 0.20
W_SEMANTIC = 0.20
W_NARRATIVE = 0.15
W_VISUAL_VARIETY = 0.10
W_QUALITY = 0.05
W_SPEAKER = 0.05

# Default window size for candidate generation (30-60s)
CANDIDATE_WINDOW_MS = 30_000


def _get_duration_ms(db_path: Path, project_id: str) -> int:
    """Fetch project duration.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        Duration in milliseconds, or 0 if not found.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT duration_ms FROM project WHERE project_id = ?",
            (project_id,),
        )
        if row and row.get("duration_ms") is not None:
            return int(row["duration_ms"])
        return 0
    finally:
        conn.close()


def _load_emotion_curve(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | float]]:
    """Load emotion curve data.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of emotion dicts with start_ms, end_ms, energy.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, energy FROM emotion_curve "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "energy": float(r["energy"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_reactions(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int]]:
    """Load reaction events.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of reaction dicts with start_ms, end_ms.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms FROM reactions "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {"start_ms": int(r["start_ms"]), "end_ms": int(r["end_ms"])}
            for r in rows
        ]
    finally:
        conn.close()


def _load_topics(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | float]]:
    """Load topic segments with semantic density.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of topic dicts with start_ms, end_ms, semantic_density.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, semantic_density FROM topics "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "semantic_density": float(r["semantic_density"])
                if r.get("semantic_density") is not None
                else 0.5,
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_scenes(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | float]]:
    """Load scene data with quality.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of scene dicts with start_ms, end_ms, quality_avg.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, quality_avg FROM scenes "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "quality_avg": float(r["quality_avg"])
                if r.get("quality_avg") is not None
                else 0.5,
            }
            for r in rows
        ]
    finally:
        conn.close()


def _load_segments_with_speakers(
    db_path: Path,
    project_id: str,
) -> list[dict[str, int | str | None]]:
    """Load transcript segments with speaker info.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of segment dicts with start_ms, end_ms, speaker_id, text.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, speaker_id, text "
            "FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        return [
            {
                "start_ms": int(r["start_ms"]),
                "end_ms": int(r["end_ms"]),
                "speaker_id": r.get("speaker_id"),
                "text": str(r.get("text", "")),
            }
            for r in rows
        ]
    finally:
        conn.close()


def _avg_emotion_energy(
    emotions: list[dict[str, int | float]],
    win_start: int,
    win_end: int,
) -> float:
    """Average emotion energy in the window.

    Args:
        emotions: Emotion curve data.
        win_start: Window start ms.
        win_end: Window end ms.

    Returns:
        Average energy or 0.5 default.
    """
    values: list[float] = []
    for e in emotions:
        if int(e["start_ms"]) >= win_end:
            break
        if int(e["end_ms"]) <= win_start:
            continue
        values.append(float(e["energy"]))
    if not values:
        return 0.5
    return sum(values) / len(values)


def _has_reaction(
    reactions: list[dict[str, int]],
    win_start: int,
    win_end: int,
) -> float:
    """Check if any reaction event overlaps the window.

    Args:
        reactions: Reaction events.
        win_start: Window start ms.
        win_end: Window end ms.

    Returns:
        1.0 if any reaction overlaps, 0.0 otherwise.
    """
    for r in reactions:
        if int(r["start_ms"]) >= win_end:
            break
        if int(r["end_ms"]) <= win_start:
            continue
        return 1.0
    return 0.0


def _avg_semantic_density(
    topics: list[dict[str, int | float]],
    win_start: int,
    win_end: int,
) -> float:
    """Average semantic density from topics in the window.

    Args:
        topics: Topic data.
        win_start: Window start ms.
        win_end: Window end ms.

    Returns:
        Average semantic density or 0.5 default.
    """
    values: list[float] = []
    for t in topics:
        if int(t["start_ms"]) >= win_end:
            break
        if int(t["end_ms"]) <= win_start:
            continue
        values.append(float(t["semantic_density"]))
    if not values:
        return 0.5
    return sum(values) / len(values)


def _narrative_completeness(
    segments: list[dict[str, int | str | None]],
    win_start: int,
    win_end: int,
) -> float:
    """Assess narrative completeness of the window.

    A window has high narrative completeness if it starts and ends
    at sentence boundaries (text ends with punctuation).

    Args:
        segments: Transcript segments.
        win_start: Window start ms.
        win_end: Window end ms.

    Returns:
        1.0 if starts/ends at sentence boundary, 0.5 otherwise.
    """
    in_window: list[dict[str, int | str | None]] = []
    for seg in segments:
        if int(seg["start_ms"]) >= win_end:
            break
        if int(seg["end_ms"]) <= win_start:
            continue
        in_window.append(seg)

    if not in_window:
        return 0.5

    first_text = str(in_window[0].get("text", "")).strip()
    last_text = str(in_window[-1].get("text", "")).strip()

    starts_at_boundary = (
        first_text and first_text[0].isupper()
    ) if first_text else False
    ends_at_boundary = (
        last_text and last_text[-1] in ".!?"
    ) if last_text else False

    if starts_at_boundary and ends_at_boundary:
        return 1.0
    if starts_at_boundary or ends_at_boundary:
        return 0.75
    return 0.5


def _visual_variety_score(
    scenes: list[dict[str, int | float]],
    win_start: int,
    win_end: int,
) -> float:
    """Count scene boundary changes within the window.

    Normalized by expected boundaries (1 per 10s).

    Args:
        scenes: Scene data.
        win_start: Window start ms.
        win_end: Window end ms.

    Returns:
        Visual variety score (0.0-1.0).
    """
    boundaries = 0
    for scene in scenes:
        scene_start = int(scene["start_ms"])
        if win_start < scene_start < win_end:
            boundaries += 1

    window_dur_s = (win_end - win_start) / 1000.0
    expected = max(1.0, window_dur_s / 10.0)
    return min(1.0, boundaries / expected)


def _avg_visual_quality(
    scenes: list[dict[str, int | float]],
    win_start: int,
    win_end: int,
) -> float:
    """Average visual quality from scenes in the window.

    Args:
        scenes: Scene data.
        win_start: Window start ms.
        win_end: Window end ms.

    Returns:
        Average quality or 0.5 default.
    """
    values: list[float] = []
    for s in scenes:
        if int(s["start_ms"]) >= win_end:
            break
        if int(s["end_ms"]) <= win_start:
            continue
        values.append(float(s["quality_avg"]))
    if not values:
        return 0.5
    return sum(values) / len(values)


def _speaker_confidence_score(
    segments: list[dict[str, int | str | None]],
    win_start: int,
    win_end: int,
) -> float:
    """Compute speaker confidence for the window.

    1.0 if a single speaker dominates >80% of segments, else 0.5.

    Args:
        segments: Transcript segments with speaker_id.
        win_start: Window start ms.
        win_end: Window end ms.

    Returns:
        Speaker confidence score.
    """
    speaker_counts: dict[str, int] = {}
    total = 0
    for seg in segments:
        if int(seg["start_ms"]) >= win_end:
            break
        if int(seg["end_ms"]) <= win_start:
            continue
        sid = str(seg.get("speaker_id", "unknown"))
        speaker_counts[sid] = speaker_counts.get(sid, 0) + 1
        total += 1

    if total == 0:
        return 0.5

    max_count = max(speaker_counts.values())
    if max_count / total > 0.8:
        return 1.0
    return 0.5


def _generate_reason(
    scores: dict[str, float],
    win_start: int,
    win_end: int,
) -> str:
    """Generate a natural-language reason for why this is a highlight.

    Args:
        scores: Component score dict.
        win_start: Window start ms.
        win_end: Window end ms.

    Returns:
        Human-readable reason string.
    """
    reasons: list[str] = []

    if scores["emotion"] > 0.7:
        reasons.append("high emotional energy")
    if scores["reaction"] > 0.5:
        reasons.append("audience reaction detected")
    if scores["semantic"] > 0.7:
        reasons.append("dense semantic content")
    if scores["narrative"] > 0.8:
        reasons.append("complete narrative arc")
    if scores["visual_variety"] > 0.6:
        reasons.append("dynamic visual changes")
    if scores["quality"] > 0.7:
        reasons.append("high visual quality")
    if scores["speaker"] > 0.8:
        reasons.append("clear single speaker")

    if not reasons:
        reasons.append("balanced multi-signal score")

    start_s = win_start / 1000.0
    end_s = win_end / 1000.0
    return (
        f"Highlight at {start_s:.1f}s-{end_s:.1f}s: "
        + ", ".join(reasons)
    )


def _classify_highlight_type(scores: dict[str, float]) -> str:
    """Classify the highlight type based on dominant signal.

    Args:
        scores: Component score dict.

    Returns:
        Highlight type string.
    """
    dominant = max(scores, key=scores.get)  # type: ignore[arg-type]
    type_map = {
        "emotion": "emotional_peak",
        "reaction": "audience_reaction",
        "semantic": "key_topic",
        "narrative": "story_arc",
        "visual_variety": "visual_montage",
        "quality": "visual_showcase",
        "speaker": "key_speaker_moment",
    }
    return type_map.get(dominant, "multi_signal")


def _score_candidates(
    duration_ms: int,
    emotions: list[dict[str, int | float]],
    reactions: list[dict[str, int]],
    topics: list[dict[str, int | float]],
    scenes: list[dict[str, int | float]],
    segments: list[dict[str, int | str | None]],
    max_highlights: int,
) -> list[dict[str, int | float | str]]:
    """Score all candidate windows and return top-N highlights.

    Args:
        duration_ms: Total video duration.
        emotions: Emotion curve data.
        reactions: Reaction events.
        topics: Topic data.
        scenes: Scene data.
        segments: Transcript segments.
        max_highlights: Maximum number of highlights to return.

    Returns:
        Top-N highlight dicts sorted by score descending.
    """
    candidates: list[dict[str, int | float | str]] = []

    win_start = 0
    while win_start < duration_ms:
        win_end = min(win_start + CANDIDATE_WINDOW_MS, duration_ms)

        scores = {
            "emotion": _avg_emotion_energy(emotions, win_start, win_end),
            "reaction": _has_reaction(reactions, win_start, win_end),
            "semantic": _avg_semantic_density(topics, win_start, win_end),
            "narrative": _narrative_completeness(segments, win_start, win_end),
            "visual_variety": _visual_variety_score(scenes, win_start, win_end),
            "quality": _avg_visual_quality(scenes, win_start, win_end),
            "speaker": _speaker_confidence_score(segments, win_start, win_end),
        }

        total_score = (
            W_EMOTION * scores["emotion"]
            + W_REACTION * scores["reaction"]
            + W_SEMANTIC * scores["semantic"]
            + W_NARRATIVE * scores["narrative"]
            + W_VISUAL_VARIETY * scores["visual_variety"]
            + W_QUALITY * scores["quality"]
            + W_SPEAKER * scores["speaker"]
        )

        highlight_type = _classify_highlight_type(scores)
        reason = _generate_reason(scores, win_start, win_end)

        candidates.append({
            "start_ms": win_start,
            "end_ms": win_end,
            "type": highlight_type,
            "score": round(total_score, 4),
            "reason": reason,
            "emotion_score": round(scores["emotion"], 4),
            "reaction_score": round(scores["reaction"], 4),
            "semantic_score": round(scores["semantic"], 4),
            "narrative_score": round(scores["narrative"], 4),
            "visual_score": round(scores["visual_variety"], 4),
            "quality_score": round(scores["quality"], 4),
            "speaker_score": round(scores["speaker"], 4),
        })

        win_start = win_end

    # Sort by score descending and take top-N
    candidates.sort(key=lambda c: float(c["score"]), reverse=True)
    return candidates[:max_highlights]


def _insert_highlights(
    db_path: Path,
    project_id: str,
    highlights: list[dict[str, int | float | str]],
) -> int:
    """Insert highlight records into the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        highlights: Highlight dicts to insert.

    Returns:
        Number of highlights inserted.
    """
    if not highlights:
        return 0

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        rows: list[tuple[object, ...]] = [
            (
                project_id,
                int(h["start_ms"]),
                int(h["end_ms"]),
                str(h["type"]),
                float(h["score"]),
                str(h["reason"]),
                float(h["emotion_score"]),
                float(h["reaction_score"]),
                float(h["semantic_score"]),
                float(h["narrative_score"]),
                float(h["visual_score"]),
                float(h["quality_score"]),
                float(h["speaker_score"]),
            )
            for h in highlights
        ]
        batch_insert(
            conn,
            "highlights",
            [
                "project_id", "start_ms", "end_ms", "type", "score",
                "reason", "emotion_score", "reaction_score",
                "semantic_score", "narrative_score", "visual_score",
                "quality_score", "speaker_score",
            ],
            rows,
        )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def run_highlights(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the multi-signal highlight scoring pipeline stage.

    Scores candidate windows using seven weighted signals and selects
    the top-N highlights.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    start_time = time.monotonic()

    try:
        duration_ms = await asyncio.to_thread(
            _get_duration_ms, db_path, project_id,
        )
        if duration_ms <= 0:
            logger.warning("No duration found, skipping highlight scoring")
            return StageResult(
                success=True,
                operation=OPERATION,
                error_message="Skipped: no duration data",
            )

        # Determine max highlights from config
        try:
            max_highlights = int(
                config.get("processing.highlight_count_default"),
            )
        except Exception:
            max_highlights = 20

        # Load all signal data in parallel
        emotions, reactions, topics, scenes, segments = await asyncio.gather(
            asyncio.to_thread(_load_emotion_curve, db_path, project_id),
            asyncio.to_thread(_load_reactions, db_path, project_id),
            asyncio.to_thread(_load_topics, db_path, project_id),
            asyncio.to_thread(_load_scenes, db_path, project_id),
            asyncio.to_thread(
                _load_segments_with_speakers, db_path, project_id,
            ),
        )

        # Score candidates
        highlights = _score_candidates(
            duration_ms, emotions, reactions, topics,
            scenes, segments, max_highlights,
        )

        # Insert
        count = await asyncio.to_thread(
            _insert_highlights, db_path, project_id, highlights,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build provenance
        top_score = highlights[0]["score"] if highlights else 0.0
        summary = (
            f"{count} highlights selected (top score={top_score}), "
            f"max_requested={max_highlights}"
        )
        output_sha = sha256_string(summary)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                sha256=sha256_string(f"highlights-{project_id}"),
            ),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=count,
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=f"Highlight scoring: {summary}",
        )

        logger.info(
            "Highlight scoring complete in %d ms: %s",
            elapsed_ms, summary,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Highlight scoring failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
