"""Signal weights and per-window highlight scoring."""

from __future__ import annotations

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

    starts_at_boundary = (first_text and first_text[0].isupper()) if first_text else False
    ends_at_boundary = (last_text and last_text[-1] in ".!?") if last_text else False

    if starts_at_boundary and ends_at_boundary:
        return 1.0
    if starts_at_boundary or ends_at_boundary:
        return 0.75
    return 0.5


def _visual_variety_score(
    scenes: list[dict[str, int | float | None]],
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
    scenes: list[dict[str, int | float | None]],
    win_start: int,
    win_end: int,
) -> float:
    """Average BRISQUE quality (0-1) of the window's scenes.

    Returns 0.0 when no scene in the window has a BRISQUE reading: the
    term contributes nothing rather than a placeholder (it was 0.5).
    """
    values: list[float] = []
    for s in scenes:
        if int(s["start_ms"]) >= win_end:
            break
        if int(s["end_ms"]) <= win_start or s["quality"] is None:
            continue
        values.append(float(s["quality"]))
    if not values:
        return 0.0
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
    return f"Highlight at {start_s:.1f}s-{end_s:.1f}s: " + ", ".join(reasons)


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
    scenes: list[dict[str, int | float | None]],
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

        candidates.append(
            {
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
            }
        )

        win_start = win_end

    # Sort by score descending and take top-N
    candidates.sort(key=lambda c: float(c["score"]), reverse=True)
    return candidates[:max_highlights]
