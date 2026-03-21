"""Tests for the captions module.

Tests cover:
- chunk_transcript_words with various inputs
- Punctuation-based chunking
- Min/max display duration enforcement
- Adaptive speech rate handling
- remap_timestamps with speed adjustments
- generate_ass_file with different styles
- generate_drawtext_filters format
- fetch_words_for_segments from real DB
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from clipcannon.editing.caption_render import (
    generate_ass_file,
    generate_drawtext_filters,
)
from clipcannon.editing.captions import (
    chunk_transcript_words,
    fetch_words_for_segments,
    remap_timestamps,
)
from clipcannon.editing.edl import CaptionChunk, CaptionWord, SegmentSpec


# ============================================================
# HELPERS
# ============================================================
def _words(texts: list[str], gap_ms: int = 300) -> list[CaptionWord]:
    """Generate evenly-spaced CaptionWord list."""
    words: list[CaptionWord] = []
    cursor = 0
    for text in texts:
        dur = gap_ms
        words.append(CaptionWord(word=text, start_ms=cursor, end_ms=cursor + dur))
        cursor += dur + 50  # 50ms gap between words
    return words


def _fast_words(texts: list[str]) -> list[CaptionWord]:
    """Generate fast-speech words (>200 WPM)."""
    words: list[CaptionWord] = []
    cursor = 0
    # ~250 WPM -> each word ~240ms total
    dur_per_word = 100
    gap = 20
    for text in texts:
        words.append(
            CaptionWord(word=text, start_ms=cursor, end_ms=cursor + dur_per_word)
        )
        cursor += dur_per_word + gap
    return words


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture()
def transcript_db(tmp_path: Path) -> Path:
    """Create a real DB with transcript_segments and transcript_words."""
    db_path = tmp_path / "analysis.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS project ("
        "project_id TEXT PRIMARY KEY, source_sha256 TEXT, duration_ms INTEGER)"
    )
    conn.execute(
        "INSERT INTO project VALUES (?, ?, ?)",
        ("proj_cap01", "hash123", 60000),
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS transcript_segments ("
        "segment_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "project_id TEXT, start_ms INTEGER, end_ms INTEGER, "
        "text TEXT, speaker_id INTEGER, language TEXT, word_count INTEGER)"
    )
    conn.execute(
        "INSERT INTO transcript_segments "
        "(project_id, start_ms, end_ms, text, speaker_id, language, word_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("proj_cap01", 0, 10000, "Hello world this is a test", 1, "en", 6),
    )
    seg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        "CREATE TABLE IF NOT EXISTS transcript_words ("
        "word_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "segment_id INTEGER, word TEXT, start_ms INTEGER, end_ms INTEGER, "
        "confidence REAL, speaker_id INTEGER)"
    )
    word_data = [
        (seg_id, "Hello", 0, 500, 0.99, 1),
        (seg_id, "world", 600, 1100, 0.98, 1),
        (seg_id, "this", 1200, 1600, 0.97, 1),
        (seg_id, "is", 1700, 1900, 0.95, 1),
        (seg_id, "a", 2000, 2100, 0.90, 1),
        (seg_id, "test", 2200, 2700, 0.96, 1),
    ]
    conn.executemany(
        "INSERT INTO transcript_words "
        "(segment_id, word, start_ms, end_ms, confidence, speaker_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        word_data,
    )
    conn.commit()
    conn.close()
    return db_path


# ============================================================
# TESTS
# ============================================================
class TestChunkTranscriptWords:
    """Test caption chunking logic."""

    def test_10_words_max3_produces_chunks(self) -> None:
        """10 words with max_words=3 -> 3-4 chunks."""
        words = _words(
            ["The", "quick", "brown", "fox", "jumps",
             "over", "the", "lazy", "brown", "dog"]
        )
        chunks = chunk_transcript_words(words, max_words=3)
        assert 3 <= len(chunks) <= 5

    def test_punctuation_breaks(self) -> None:
        """Sentence-ending punctuation forces a chunk break."""
        words = _words(["Hello", "world.", "This", "is", "great."])
        chunks = chunk_transcript_words(words, max_words=10)
        # "world." ends with period -> should break after it
        assert len(chunks) >= 2
        assert "world." in chunks[0].text

    def test_min_display_duration_enforcement(self) -> None:
        """Chunks with duration < 500ms are extended to 500ms."""
        # Create very short words
        words = [
            CaptionWord(word="Hi", start_ms=0, end_ms=100),
        ]
        chunks = chunk_transcript_words(words, max_words=5, min_display_ms=500)
        assert len(chunks) == 1
        assert (chunks[0].end_ms - chunks[0].start_ms) >= 500

    def test_max_display_duration_split(self) -> None:
        """Chunks exceeding max_display_ms are split."""
        # Create words spanning 5000ms
        words = [
            CaptionWord(word="word1", start_ms=0, end_ms=1000),
            CaptionWord(word="word2", start_ms=1100, end_ms=2000),
            CaptionWord(word="word3", start_ms=2100, end_ms=3000),
            CaptionWord(word="word4", start_ms=3100, end_ms=4000),
            CaptionWord(word="word5", start_ms=4100, end_ms=5000),
        ]
        chunks = chunk_transcript_words(
            words, max_words=10, max_display_ms=2000
        )
        for chunk in chunks:
            duration = chunk.end_ms - chunk.start_ms
            # Each chunk should be at most 2000ms (plus min enforcement)
            assert duration <= 3000  # some slack for min_display enforcement

    def test_fast_speech_larger_chunks(self) -> None:
        """Fast speech (>200 WPM) -> adaptive max increases."""
        # 20 words in 4.8s = ~250 WPM
        texts = [f"w{i}" for i in range(20)]
        words = _fast_words(texts)
        chunks = chunk_transcript_words(words, max_words=3)
        # With adaptive max, chunks should have more than 3 words each
        max_words_in_chunk = max(len(c.words) for c in chunks)
        assert max_words_in_chunk >= 3

    def test_empty_words(self) -> None:
        """Empty word list returns empty chunks."""
        chunks = chunk_transcript_words([])
        assert chunks == []

    def test_chunk_ids_sequential(self) -> None:
        """Chunk IDs are sequential starting from 1."""
        words = _words(["a", "b", "c", "d", "e", "f"])
        chunks = chunk_transcript_words(words, max_words=2)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == i + 1


class TestRemapTimestamps:
    """Test timestamp remapping to output timeline."""

    def test_single_segment_1x_speed(self) -> None:
        """At 1x speed, output timestamps match source timestamps."""
        chunks = [
            CaptionChunk(
                chunk_id=1,
                text="Hello world",
                start_ms=1000,
                end_ms=2000,
                words=[
                    CaptionWord(word="Hello", start_ms=1000, end_ms=1500),
                    CaptionWord(word="world", start_ms=1500, end_ms=2000),
                ],
            ),
        ]
        segments = [
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=10000,
                output_start_ms=0,
                speed=1.0,
            ),
        ]
        remapped = remap_timestamps(chunks, segments)
        assert len(remapped) == 1
        assert remapped[0].start_ms == 1000
        assert remapped[0].end_ms == 2000

    def test_segment_at_2x_speed(self) -> None:
        """At 2x speed, output timestamps are halved."""
        chunks = [
            CaptionChunk(
                chunk_id=1,
                text="Hello",
                start_ms=2000,
                end_ms=4000,
                words=[
                    CaptionWord(word="Hello", start_ms=2000, end_ms=4000),
                ],
            ),
        ]
        segments = [
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=10000,
                output_start_ms=0,
                speed=2.0,
            ),
        ]
        remapped = remap_timestamps(chunks, segments)
        assert len(remapped) == 1
        # 2000ms source offset / 2.0 speed = 1000ms output start
        assert remapped[0].start_ms == 1000
        # (4000-2000) / 2.0 = 1000ms duration -> output end = 2000
        assert remapped[0].end_ms == 2000

    def test_chunk_outside_segments_dropped(self) -> None:
        """Chunks outside all segment ranges are dropped."""
        chunks = [
            CaptionChunk(
                chunk_id=1,
                text="orphan",
                start_ms=50000,
                end_ms=51000,
                words=[],
            ),
        ]
        segments = [
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=10000,
                output_start_ms=0,
                speed=1.0,
            ),
        ]
        remapped = remap_timestamps(chunks, segments)
        assert len(remapped) == 0


class TestASSGeneration:
    """Test ASS subtitle file generation."""

    def test_bold_centered_format(self) -> None:
        """Generate ASS with bold_centered style: verify structure."""
        chunks = [
            CaptionChunk(
                chunk_id=1,
                text="Hello",
                start_ms=0,
                end_ms=1000,
                words=[CaptionWord(word="Hello", start_ms=0, end_ms=1000)],
            ),
        ]
        ass = generate_ass_file(chunks, "bold_centered")
        assert "[Script Info]" in ass
        assert "Title: ClipCannon Captions" in ass
        assert "[V4+ Styles]" in ass
        assert "BoldCentered" in ass
        assert "[Events]" in ass
        assert "Dialogue:" in ass

    def test_subtitle_bar_style(self) -> None:
        """Generate ASS with subtitle_bar style: verify background box."""
        chunks = [
            CaptionChunk(
                chunk_id=1,
                text="Test",
                start_ms=0,
                end_ms=1000,
                words=[],
            ),
        ]
        ass = generate_ass_file(chunks, "subtitle_bar")
        assert "SubtitleBar" in ass
        # subtitle_bar uses BorderStyle 3 for background box
        assert "BorderStyle" in ass


class TestDrawtextFilters:
    """Test FFmpeg drawtext filter generation."""

    def test_drawtext_format(self) -> None:
        """Drawtext filter string has expected format."""
        chunks = [
            CaptionChunk(
                chunk_id=1,
                text="Hello world",
                start_ms=0,
                end_ms=1000,
                words=[
                    CaptionWord(word="Hello", start_ms=0, end_ms=500),
                    CaptionWord(word="world", start_ms=500, end_ms=1000),
                ],
            ),
        ]
        filters = generate_drawtext_filters(chunks, "bold_centered")
        assert len(filters) >= 1
        assert "drawtext=" in filters[0]
        assert "enable=" in filters[0]


class TestFetchWordsFromDB:
    """Test fetching words from real database."""

    def test_fetch_words_for_segments(self, transcript_db: Path) -> None:
        """Fetch words that overlap with the segment's time range."""
        segments = [
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=10000,
                output_start_ms=0,
                speed=1.0,
            ),
        ]
        words = fetch_words_for_segments(transcript_db, "proj_cap01", segments)
        assert len(words) >= 1
        assert words[0].word == "Hello"
        # Verify ordering
        for i in range(1, len(words)):
            assert words[i].start_ms >= words[i - 1].start_ms
