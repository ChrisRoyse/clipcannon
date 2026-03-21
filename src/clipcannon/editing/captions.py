"""Caption generation for ClipCannon EDL rendering.

Converts WhisperX word-level timestamps into display-ready caption
chunks. Delegates ASS/drawtext rendering to caption_render module.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from clipcannon.editing.caption_render import (
    generate_ass_file,
    generate_drawtext_filters,
)
from clipcannon.editing.edl import CaptionChunk, CaptionWord, SegmentSpec

logger = logging.getLogger(__name__)

# Re-export rendering functions for public API
__all__ = [
    "WordRecord",
    "chunk_transcript_words",
    "fetch_words_for_segments",
    "generate_ass_file",
    "generate_drawtext_filters",
    "remap_timestamps",
]

# Punctuation that forces a chunk break
SENTENCE_ENDINGS = frozenset(".?!;:")
COMMA = ","

# Inter-chunk gap threshold
GAP_THRESHOLD_MS = 200

# Speech rate thresholds
FAST_SPEECH_WPM = 200
SLOW_SPEECH_WPM = 80


# ============================================================
# DATA CLASSES
# ============================================================
@dataclass
class WordRecord:
    """A word record from the transcript_words table."""

    word_id: int
    word: str
    start_ms: int
    end_ms: int
    confidence: float
    segment_id: int


# ============================================================
# CAPTION CHUNKING
# ============================================================
def chunk_transcript_words(
    words: list[CaptionWord],
    max_words: int = 3,
    min_display_ms: int = 500,
    max_display_ms: int = 3000,
) -> list[CaptionChunk]:
    """Convert a flat list of timed words into display-ready chunks.

    Applies chunking rules: max words, punctuation breaks, min/max
    duration, speech rate adaptation, and gap handling.

    Args:
        words: Ordered list of CaptionWord with timing.
        max_words: Maximum words per displayed chunk.
        min_display_ms: Minimum time a chunk stays on screen.
        max_display_ms: Maximum time before force-splitting.

    Returns:
        Ordered list of CaptionChunk ready for rendering.
    """
    if not words:
        return []

    # Compute effective max words based on speech rate
    effective_max = _adaptive_max_words(words, max_words)

    chunks: list[CaptionChunk] = []
    current_words: list[CaptionWord] = []
    chunk_counter = 0

    for word in words:
        current_words.append(word)

        should_break = False

        # Rule 1: max words per chunk
        if len(current_words) >= effective_max:
            should_break = True

        # Rule 2: sentence-ending punctuation
        if _ends_with_sentence_punct(word.word):
            should_break = True

        # Rule 3: comma after 2+ words
        if word.word.rstrip().endswith(COMMA) and len(current_words) >= 2:
            should_break = True

        if should_break:
            chunk_counter += 1
            chunk = _make_chunk(current_words, chunk_counter, min_display_ms)
            chunks.append(chunk)
            current_words = []

    # Flush remaining words
    if current_words:
        chunk_counter += 1
        chunk = _make_chunk(current_words, chunk_counter, min_display_ms)
        chunks.append(chunk)

    # Apply max duration splits
    chunks = _apply_max_duration_splits(chunks, max_display_ms, min_display_ms)

    # Apply inter-chunk gap handling
    _apply_gap_handling(chunks)

    # Re-number chunk IDs after splits
    for i, chunk in enumerate(chunks):
        chunk.chunk_id = i + 1

    return chunks


def _adaptive_max_words(
    words: list[CaptionWord],
    default_max: int,
) -> int:
    """Adjust max words per chunk based on speech rate.

    Args:
        words: All words to estimate speech rate from.
        default_max: Default max words per chunk.

    Returns:
        Adjusted max words value.
    """
    if len(words) < 2:
        return default_max

    total_duration_ms = words[-1].end_ms - words[0].start_ms
    if total_duration_ms <= 0:
        return default_max

    total_duration_min = total_duration_ms / 60000.0
    wpm = len(words) / total_duration_min

    if wpm > FAST_SPEECH_WPM:
        return max(default_max, min(5, default_max + 2))
    if wpm < SLOW_SPEECH_WPM:
        return max(2, default_max - 1)
    return default_max


def _ends_with_sentence_punct(word: str) -> bool:
    """Check if word ends with sentence-ending punctuation."""
    stripped = word.rstrip()
    return bool(stripped) and stripped[-1] in SENTENCE_ENDINGS


def _make_chunk(
    words: list[CaptionWord],
    chunk_id: int,
    min_display_ms: int,
) -> CaptionChunk:
    """Create a CaptionChunk from a list of words.

    Args:
        words: Words for this chunk.
        chunk_id: Sequential chunk identifier.
        min_display_ms: Minimum display duration.

    Returns:
        A new CaptionChunk with proper timing.
    """
    text = " ".join(w.word for w in words)
    start_ms = words[0].start_ms
    end_ms = words[-1].end_ms

    # Enforce minimum display duration
    if end_ms - start_ms < min_display_ms:
        end_ms = start_ms + min_display_ms

    return CaptionChunk(
        chunk_id=chunk_id,
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        words=list(words),
    )


def _apply_max_duration_splits(
    chunks: list[CaptionChunk],
    max_display_ms: int,
    min_display_ms: int,
) -> list[CaptionChunk]:
    """Force-split chunks that exceed max display duration.

    Args:
        chunks: Input chunks to check.
        max_display_ms: Maximum allowed display duration.
        min_display_ms: Minimum display duration for splits.

    Returns:
        New list with over-long chunks split.
    """
    result: list[CaptionChunk] = []
    counter = 0

    for chunk in chunks:
        duration = chunk.end_ms - chunk.start_ms
        if duration <= max_display_ms or len(chunk.words) <= 1:
            counter += 1
            chunk.chunk_id = counter
            result.append(chunk)
            continue

        # Split at midpoint of words
        words = chunk.words
        mid = len(words) // 2
        if mid == 0:
            mid = 1

        first_words = words[:mid]
        second_words = words[mid:]

        counter += 1
        first = _make_chunk(first_words, counter, min_display_ms)
        result.append(first)

        if second_words:
            counter += 1
            second = _make_chunk(second_words, counter, min_display_ms)
            result.append(second)

    return result


def _apply_gap_handling(chunks: list[CaptionChunk]) -> None:
    """Handle inter-chunk gaps in place.

    If gap < 200ms, hold previous chunk until next starts.
    If gap >= 200ms, leave the gap (no caption displayed).

    Args:
        chunks: Chunks to adjust (modified in place).
    """
    for i in range(len(chunks) - 1):
        gap = chunks[i + 1].start_ms - chunks[i].end_ms
        if 0 < gap < GAP_THRESHOLD_MS:
            chunks[i].end_ms = chunks[i + 1].start_ms


# ============================================================
# TIMESTAMP REMAPPING
# ============================================================
def remap_timestamps(
    chunks: list[CaptionChunk],
    segments: list[SegmentSpec],
) -> list[CaptionChunk]:
    """Re-map source-timeline chunk timestamps to output-timeline.

    For each chunk, finds which segment contains it and applies the
    time offset and speed adjustment to convert source timestamps
    to output timestamps.

    Args:
        chunks: Chunks with source-timeline timestamps.
        segments: EDL segments defining the source-to-output mapping.

    Returns:
        New list of chunks with output-timeline timestamps.
    """
    remapped: list[CaptionChunk] = []

    for chunk in chunks:
        mapped = _remap_single_chunk(chunk, segments)
        if mapped is not None:
            remapped.append(mapped)

    remapped.sort(key=lambda c: c.start_ms)

    # Re-number
    for i, c in enumerate(remapped):
        c.chunk_id = i + 1

    return remapped


def _remap_single_chunk(
    chunk: CaptionChunk,
    segments: list[SegmentSpec],
) -> CaptionChunk | None:
    """Remap a single chunk to the output timeline.

    Args:
        chunk: Chunk with source timestamps.
        segments: EDL segment list.

    Returns:
        Remapped chunk, or None if no matching segment found.
    """
    for seg in segments:
        # Check if chunk overlaps with this segment's source range
        if (
            chunk.start_ms >= seg.source_start_ms
            and chunk.start_ms < seg.source_end_ms
        ):
            # Compute the offset within the segment
            offset_in_source = chunk.start_ms - seg.source_start_ms
            offset_in_output = int(offset_in_source / seg.speed)

            output_start = seg.output_start_ms + offset_in_output

            chunk_source_dur = chunk.end_ms - chunk.start_ms
            output_dur = int(chunk_source_dur / seg.speed)
            output_end = output_start + output_dur

            # Remap individual words
            remapped_words: list[CaptionWord] = []
            for w in chunk.words:
                w_offset = w.start_ms - seg.source_start_ms
                w_out_start = seg.output_start_ms + int(w_offset / seg.speed)
                w_dur = w.end_ms - w.start_ms
                w_out_end = w_out_start + int(w_dur / seg.speed)
                remapped_words.append(
                    CaptionWord(
                        word=w.word,
                        start_ms=w_out_start,
                        end_ms=w_out_end,
                    )
                )

            return CaptionChunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                start_ms=output_start,
                end_ms=output_end,
                words=remapped_words,
            )

    logger.warning(
        "No matching segment for chunk at %d-%dms",
        chunk.start_ms,
        chunk.end_ms,
    )
    return None


# ============================================================
# FETCH WORDS FROM DB
# ============================================================
def fetch_words_for_segments(
    db_path: Path,
    project_id: str,
    segments: list[SegmentSpec],
) -> list[WordRecord]:
    """Query transcript_words for words overlapping with segments.

    Args:
        db_path: Path to the project SQLite database.
        project_id: Project identifier.
        segments: EDL segments defining source time ranges.

    Returns:
        Ordered list of WordRecord from the database.
    """
    if not segments:
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        all_words: list[WordRecord] = []

        for seg in segments:
            rows = conn.execute(
                "SELECT w.word_id, w.word, w.start_ms, w.end_ms, "
                "w.confidence, w.segment_id "
                "FROM transcript_words w "
                "JOIN transcript_segments s "
                "ON w.segment_id = s.segment_id "
                "WHERE s.project_id = ? "
                "AND w.start_ms >= ? AND w.end_ms <= ? "
                "ORDER BY w.start_ms",
                (project_id, seg.source_start_ms, seg.source_end_ms),
            ).fetchall()

            for row in rows:
                all_words.append(
                    WordRecord(
                        word_id=int(row["word_id"]),
                        word=str(row["word"]),
                        start_ms=int(row["start_ms"]),
                        end_ms=int(row["end_ms"]),
                        confidence=float(row["confidence"] or 1.0),
                        segment_id=int(row["segment_id"]),
                    )
                )

        return all_words

    finally:
        conn.close()
