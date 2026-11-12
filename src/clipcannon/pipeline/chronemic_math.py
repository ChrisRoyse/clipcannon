"""Pure pacing computations (WPM, pauses, speaker changes, labels)."""

from __future__ import annotations

WINDOW_MS = 60_000


def _count_words_in_window(
    words: list[dict[str, int | str]],
    win_start: int,
    win_end: int,
) -> int:
    """Count transcript words that fall within the time window.

    A word is counted if its midpoint is within [win_start, win_end).

    Args:
        words: Sorted list of word dicts.
        win_start: Window start in milliseconds.
        win_end: Window end in milliseconds.

    Returns:
        Number of words in the window.
    """
    count = 0
    for w in words:
        mid = (int(w["start_ms"]) + int(w["end_ms"])) // 2
        if mid >= win_end:
            break
        if mid >= win_start:
            count += 1
    return count


def _compute_pause_ratio(
    gaps: list[dict[str, int]],
    win_start: int,
    win_end: int,
) -> float:
    """Compute the ratio of silence gap duration to window duration.

    Args:
        gaps: Sorted list of silence gap dicts.
        win_start: Window start in milliseconds.
        win_end: Window end in milliseconds.

    Returns:
        Ratio of silence to window duration (0.0-1.0).
    """
    window_dur = win_end - win_start
    if window_dur <= 0:
        return 0.0

    silence_ms = 0
    for g in gaps:
        g_start = int(g["start_ms"])
        g_end = int(g["end_ms"])
        if g_start >= win_end:
            break
        if g_end <= win_start:
            continue
        # Overlap with window
        overlap_start = max(g_start, win_start)
        overlap_end = min(g_end, win_end)
        silence_ms += max(0, overlap_end - overlap_start)

    return round(silence_ms / window_dur, 4)


def _count_speaker_changes(
    segments: list[dict[str, int | str | None]],
    win_start: int,
    win_end: int,
) -> int:
    """Count distinct speaker transitions within the time window.

    A change is counted each time the speaker_id differs between
    consecutive segments that overlap the window.

    Args:
        segments: Sorted list of segment dicts with speaker_id.
        win_start: Window start in milliseconds.
        win_end: Window end in milliseconds.

    Returns:
        Number of speaker transitions.
    """
    in_window: list[int | str | None] = []
    for seg in segments:
        seg_start = int(seg["start_ms"])
        seg_end = int(seg["end_ms"])
        if seg_start >= win_end:
            break
        if seg_end <= win_start:
            continue
        in_window.append(seg.get("speaker_id"))

    changes = 0
    for i in range(1, len(in_window)):
        if in_window[i] != in_window[i - 1]:
            changes += 1

    return changes


def _classify_pacing(
    wpm: float,
    pause_ratio: float,
    speaker_changes: int,
) -> str:
    """Classify the pacing of a window.

    Labels:
        fast_dialogue:  WPM > 150
        normal:         100 <= WPM <= 150
        slow_monologue: WPM < 100 AND speaker_changes == 0
        dead_air:       pause_ratio > 0.5

    When multiple conditions are met, dead_air takes priority.

    Args:
        wpm: Words per minute in the window.
        pause_ratio: Ratio of silence to window duration.
        speaker_changes: Number of speaker transitions.

    Returns:
        Pacing label string.
    """
    if pause_ratio > 0.5:
        return "dead_air"
    if wpm > 150:
        return "fast_dialogue"
    if wpm >= 100:
        return "normal"
    if speaker_changes == 0:
        return "slow_monologue"
    return "normal"


def _compute_pacing_windows(
    duration_ms: int,
    words: list[dict[str, int | str]],
    gaps: list[dict[str, int]],
    segments: list[dict[str, int | str | None]],
) -> list[dict[str, int | float | str]]:
    """Compute pacing for each 60-second window.

    Args:
        duration_ms: Total video duration in milliseconds.
        words: Sorted transcript words.
        gaps: Sorted silence gaps.
        segments: Sorted transcript segments with speaker IDs.

    Returns:
        List of pacing window dicts.
    """
    windows: list[dict[str, int | float | str]] = []

    win_start = 0
    while win_start < duration_ms:
        win_end = min(win_start + WINDOW_MS, duration_ms)
        actual_dur_ms = win_end - win_start

        word_count = _count_words_in_window(words, win_start, win_end)
        wpm = word_count / (actual_dur_ms / 60_000.0) if actual_dur_ms > 0 else 0.0

        pause_ratio = _compute_pause_ratio(gaps, win_start, win_end)
        speaker_changes = _count_speaker_changes(segments, win_start, win_end)
        label = _classify_pacing(wpm, pause_ratio, speaker_changes)

        windows.append(
            {
                "start_ms": win_start,
                "end_ms": win_end,
                "words_per_minute": round(wpm, 2),
                "pause_ratio": pause_ratio,
                "speaker_changes": speaker_changes,
                "label": label,
            }
        )

        win_start = win_end

    return windows
