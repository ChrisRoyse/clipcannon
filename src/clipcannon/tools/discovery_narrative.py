"""Discovery MCP tool: clipcannon_get_narrative_flow and its text helpers."""

from __future__ import annotations

import json
import logging

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.discovery_common import _db_path, _error, _validate_project

logger = logging.getLogger(__name__)


# ============================================================
# TOOL 3: clipcannon_get_narrative_flow
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
