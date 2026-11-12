"""Post-transcription hallucination filtering (phrases, loops, confidence)."""

from __future__ import annotations

import logging
import zlib

from clipcannon.pipeline.transcribe_config import (
    _HALLUCINATION_EXACT,
    _HALLUCINATION_PHRASES,
    _MAX_COMPRESSION_RATIO,
    _MIN_SEGMENT_CONFIDENCE,
    _MIN_WORD_CONFIDENCE,
)

logger = logging.getLogger(__name__)


# ============================================================
# POST-TRANSCRIPTION HALLUCINATION FILTERING
# ============================================================
def _is_hallucination_phrase(text: str) -> bool:
    """Check if text matches a known hallucination phrase.

    Uses two-tier matching:
    - Substring match for multi-word phrases (catches them anywhere)
    - Exact match for single-word/short phrases (avoids false positives
      when the word appears naturally in real speech)

    Args:
        text: Segment text to check.

    Returns:
        True if the text is a known hallucination.
    """
    normalized = text.strip().lower()
    if not normalized:
        return True

    # Tier 1: Substring match for multi-word phrases
    if any(phrase in normalized for phrase in _HALLUCINATION_PHRASES):
        return True

    # Tier 2: Exact match for short/ambiguous phrases
    # Strip trailing punctuation for comparison
    cleaned = normalized.rstrip(".,!?;:")
    return cleaned in _HALLUCINATION_EXACT


def _detect_repetition(text: str, min_ngram: int = 2) -> bool:
    """Detect repeated n-grams indicating hallucination loops.

    When Whisper hallucinates, it often gets stuck in a loop
    repeating the same phrase over and over. Catches both
    single-word stutters ("the the the") and multi-word loops
    ("hello world hello world").

    Args:
        text: Text to check for repetition.
        min_ngram: Minimum n-gram size to check.

    Returns:
        True if repetition is detected.
    """
    words = text.lower().split()
    if len(words) < min_ngram * 2:
        return False

    max_n = min(len(words) // 2, 20)
    for n in range(min_ngram, max_n + 1):
        for i in range(len(words) - 2 * n + 1):
            ngram = tuple(words[i : i + n])
            next_ngram = tuple(words[i + n : i + 2 * n])
            if ngram == next_ngram:
                return True
    return False


def _deloop_text(text: str, min_ngram: int = 2) -> str:
    """Collapse repeated phrases to single occurrence.

    Args:
        text: Text with potential repetitions.
        min_ngram: Minimum n-gram size for delooping.

    Returns:
        Text with repeated phrases collapsed.
    """
    words = text.split()
    result: list[str] = []
    i = 0
    while i < len(words):
        matched = False
        max_n = min(len(words) - i, 20)
        for n in range(max_n, min_ngram - 1, -1):
            if i + 2 * n > len(words):
                continue
            phrase = words[i : i + n]
            next_phrase = words[i + n : i + 2 * n]
            if phrase == next_phrase:
                result.extend(phrase)
                # Skip all consecutive repetitions
                j = i + n
                while j + n <= len(words) and words[j : j + n] == phrase:
                    j += n
                i = j
                matched = True
                break
        if not matched:
            result.append(words[i])
            i += 1
    return " ".join(result)


def _compression_ratio(text: str) -> float:
    """Compute compression ratio of text.

    High ratio = repetitive/compressible = likely hallucinated.

    Args:
        text: Text to analyze.

    Returns:
        Compression ratio (uncompressed / compressed size).
    """
    text_bytes = text.encode("utf-8")
    if not text_bytes:
        return 0.0
    compressed = zlib.compress(text_bytes)
    return len(text_bytes) / len(compressed)


def _word_confidence(word: dict[str, object]) -> float | None:
    """Extract confidence score from a word dict.

    WhisperX uses 'score', faster-whisper uses 'confidence'.
    Returns None if neither key is present.

    Args:
        word: Word dict from transcript segment.

    Returns:
        Confidence score as float, or None.
    """
    score = word.get("score") or word.get("confidence")
    if score is None:
        return None
    return float(score)


def _filter_hallucinations(
    segments: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    """Apply multi-layer hallucination filtering to transcript segments.

    Filtering layers:
    1. Known hallucination phrase detection
    2. Repetition/looping detection and delooping
    3. Compression ratio filtering (repetitive text)
    4. Confidence-based word filtering
    5. Confidence-based segment filtering

    Args:
        segments: Raw transcript segments from Whisper/WhisperX.

    Returns:
        Tuple of (filtered_segments, removed_count).
    """
    filtered: list[dict[str, object]] = []
    removed = 0

    for seg in segments:
        text = str(seg.get("text", "")).strip()

        # Layer 1: Known hallucination phrases
        if _is_hallucination_phrase(text):
            logger.debug(
                "Filtered hallucination phrase: %r at %.1f-%.1fs",
                text[:50],
                float(seg.get("start", 0)),
                float(seg.get("end", 0)),
            )
            removed += 1
            continue

        # Layer 2: Repetition detection
        if _detect_repetition(text):
            delooped = _deloop_text(text)
            if _is_hallucination_phrase(delooped):
                logger.debug("Filtered repeated hallucination: %r", text[:50])
                removed += 1
                continue
            seg["text"] = delooped
            logger.debug("Delooped repetition: %r -> %r", text[:50], delooped[:50])

        # Layer 3: Compression ratio (catches subtle repetition)
        text = str(seg.get("text", ""))
        if len(text) > 20:
            ratio = _compression_ratio(text)
            if ratio > _MAX_COMPRESSION_RATIO:
                delooped = _deloop_text(text)
                if len(delooped.split()) < 3:
                    logger.debug(
                        "Filtered high-compression segment: %r (ratio=%.2f)",
                        text[:50],
                        ratio,
                    )
                    removed += 1
                    continue
                seg["text"] = delooped

        # Layer 4: Word-level confidence filtering
        words = seg.get("words", [])
        if isinstance(words, list) and words:
            good_words = []
            for w in words:
                if not isinstance(w, dict):
                    continue
                conf = _word_confidence(w)
                if conf is not None and conf < _MIN_WORD_CONFIDENCE:
                    continue
                good_words.append(w)

            if not good_words:
                logger.debug(
                    "Filtered all-low-confidence segment: %r",
                    text[:50],
                )
                removed += 1
                continue

            # Layer 5: Segment-level confidence check
            scores = [c for w in good_words if (c := _word_confidence(w)) is not None]
            if scores:
                avg_conf = sum(scores) / len(scores)
                if avg_conf < _MIN_SEGMENT_CONFIDENCE:
                    logger.debug(
                        "Filtered low-confidence segment: %r (avg=%.3f)",
                        text[:50],
                        avg_conf,
                    )
                    removed += 1
                    continue

            seg["words"] = good_words
            seg["text"] = " ".join(
                str(w.get("word", "")).strip()
                for w in good_words
                if str(w.get("word", "")).strip()
            )

        # Keep the segment
        final_text = str(seg.get("text", "")).strip()
        if final_text:
            filtered.append(seg)
        else:
            removed += 1

    return filtered, removed
