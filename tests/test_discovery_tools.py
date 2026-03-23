"""Tests for ClipCannon discovery MCP tools.

Tests narrative flow analysis, promise-payoff detection, gap
analysis, and error handling with synthetic data in a temp database.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, execute
from clipcannon.db.schema import create_project_db
from clipcannon.tools.discovery import (
    PROMISE_KEYWORDS,
    _extract_key_phrases,
    _extract_sentences,
    _has_promise,
    _thought_complete,
    clipcannon_get_narrative_flow,
    dispatch_discovery_tool,
)


@pytest.fixture
def ready_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a project in 'ready' status with synthetic transcript data."""
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    db_path = create_project_db(project_id, base_dir=tmp_path)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        # Project record - ready status
        execute(
            conn,
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, "Test Video", "/tmp/test.mp4",
                "abc123", 120000, "1920x1080", 30.0, "h264", "ready",
            ),
        )

        # Speakers (required FK for transcript_segments)
        batch_insert(
            conn, "speakers",
            ["project_id", "label", "total_speaking_ms", "speaking_pct"],
            [
                (project_id, "Speaker 1", 120000, 100.0),
            ],
        )

        # Transcript segments covering 0-120s
        batch_insert(
            conn, "transcript_segments",
            ["project_id", "start_ms", "end_ms", "text", "speaker_id", "word_count"],
            [
                (project_id, 0, 5000, "Hi, I spent the last day building this.", 1, 9),
                (project_id, 5000, 10000, "Cloud Code can now edit my videos.", 1, 7),
                (project_id, 10000, 15000, "Let me show you how it works.", 1, 7),
                (project_id, 15000, 25000, "First we open the dashboard.", 1, 6),
                (project_id, 25000, 35000, "Then we select the video file.", 1, 7),
                (project_id, 35000, 45000, "The system has 12 embedders running.", 1, 7),
                (project_id, 45000, 55000, "You get full control over the entire video.", 1, 9),
                (project_id, 55000, 65000, "It clips from 1 to 2 hour videos easily.", 1, 9),
                (project_id, 65000, 75000, "This is never boring to watch.", 1, 6),
                (project_id, 75000, 85000, "The quality is always better than before.", 1, 8),
                (project_id, 85000, 95000, "Check this out for the final result.", 1, 7),
                (project_id, 95000, 105000, "Here is the rendered output.", 1, 6),
                (project_id, 105000, 120000, "Thanks for watching everyone.", 1, 5),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    # Monkeypatch _projects_dir to point at tmp_path
    monkeypatch.setattr(
        "clipcannon.tools.discovery._projects_dir",
        lambda: tmp_path,
    )

    return project_id, db_path, tmp_path


# ------------------------------------------------------------------
# Helper function unit tests
# ------------------------------------------------------------------

class TestExtractSentences:
    def test_simple_split(self):
        result = _extract_sentences("Hello world. How are you? Fine!")
        assert result == ["Hello world.", "How are you?", "Fine!"]

    def test_single_sentence(self):
        result = _extract_sentences("Just one sentence.")
        assert result == ["Just one sentence."]

    def test_no_punctuation(self):
        result = _extract_sentences("no punctuation here")
        assert result == ["no punctuation here"]

    def test_empty_string(self):
        result = _extract_sentences("")
        assert result == []


class TestThoughtComplete:
    def test_period(self):
        assert _thought_complete("End of sentence.") is True

    def test_question(self):
        assert _thought_complete("Is this a question?") is True

    def test_exclamation(self):
        assert _thought_complete("Wow!") is True

    def test_incomplete(self):
        assert _thought_complete("and then") is False

    def test_trailing_space(self):
        assert _thought_complete("Done.  ") is True


class TestHasPromise:
    def test_match(self):
        assert _has_promise("Let me show you something") == "let me show"

    def test_no_match(self):
        assert _has_promise("Nothing special here") is None

    def test_case_insensitive(self):
        assert _has_promise("WATCH THIS carefully") == "watch this"

    def test_multiple_returns_first(self):
        kw = _has_promise("Let me show you, watch this")
        assert kw == "let me show"


class TestExtractKeyPhrases:
    def test_short_text(self):
        result = _extract_key_phrases("Short text.", 200)
        assert result == "Short text."

    def test_truncation(self):
        long_text = "Sentence one. " * 50
        result = _extract_key_phrases(long_text, 100)
        assert len(result) <= 100
        assert result.endswith("[truncated]")

    def test_key_phrases_prioritized(self):
        text = (
            "Normal sentence. There are 12 embedders. "
            "Another filler. The first step is important."
        )
        result = _extract_key_phrases(text, 200)
        # Key sentences (with numbers and "first") come first
        assert result.index("12 embedders") < result.index("Normal")


# ------------------------------------------------------------------
# Narrative flow tool tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_narrative_flow_basic(ready_project):
    """Basic two-segment flow with a gap returns correct structure."""
    project_id, _, _ = ready_project

    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[
            {"start_ms": 0, "end_ms": 10000},
            {"start_ms": 15000, "end_ms": 25000},
        ],
    )

    assert "error" not in result
    assert result["project_id"] == project_id
    assert result["segment_count"] == 2
    assert result["total_duration_ms"] == 20000

    flow = result["flow"]
    # Should have: segment 1, gap 1, segment 2
    assert len(flow) == 3
    assert flow[0]["segment"] == 1
    assert flow[1]["gap"] == 1
    assert flow[2]["segment"] == 2

    # Segment 1 boundaries
    assert "Hi" in flow[0]["first_sentence"]
    assert flow[0]["duration_ms"] == 10000

    # Gap between 10000-15000
    assert flow[1]["duration_ms"] == 5000
    assert flow[1]["word_count"] > 0


@pytest.mark.asyncio
async def test_narrative_flow_promise_detection(ready_project):
    """Detects broken promise when segment ends with 'let me show'."""
    project_id, _, _ = ready_project

    # Segment 1 ends at 15000 where text is "Let me show you how it works."
    # Gap is 15000-35000 (20s) - should trigger BROKEN_PROMISE
    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[
            {"start_ms": 0, "end_ms": 15000},
            {"start_ms": 35000, "end_ms": 55000},
        ],
    )

    assert "error" not in result
    warnings = result["warnings"]
    assert len(warnings) > 0
    assert any("let me show" in w.lower() for w in warnings)

    # The gap entry should have BROKEN_PROMISE warning
    gap_entries = [f for f in result["flow"] if "gap" in f]
    assert len(gap_entries) == 1
    assert gap_entries[0]["warning"] is not None
    assert "BROKEN_PROMISE" in gap_entries[0]["warning"]


@pytest.mark.asyncio
async def test_narrative_flow_large_gap(ready_project):
    """Large gaps (>10s) trigger LARGE_GAP warning with key phrases."""
    project_id, _, _ = ready_project

    # Segment 1: 0-5000, Segment 2: 75000-85000 (gap = 70s)
    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[
            {"start_ms": 0, "end_ms": 5000},
            {"start_ms": 75000, "end_ms": 85000},
        ],
    )

    assert "error" not in result
    gap_entries = [f for f in result["flow"] if "gap" in f]
    assert len(gap_entries) == 1
    gap = gap_entries[0]
    assert gap["duration_ms"] == 70000
    assert "LARGE_GAP" in gap["warning"]
    assert gap["word_count"] > 0


@pytest.mark.asyncio
async def test_narrative_flow_contiguous_segments(ready_project):
    """Contiguous segments produce no gap entries."""
    project_id, _, _ = ready_project

    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[
            {"start_ms": 0, "end_ms": 10000},
            {"start_ms": 10000, "end_ms": 25000},
        ],
    )

    assert "error" not in result
    gap_entries = [f for f in result["flow"] if "gap" in f]
    assert len(gap_entries) == 0
    assert result["segment_count"] == 2


@pytest.mark.asyncio
async def test_narrative_flow_single_segment(ready_project):
    """Single segment returns no gaps."""
    project_id, _, _ = ready_project

    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[{"start_ms": 0, "end_ms": 10000}],
    )

    assert "error" not in result
    assert result["segment_count"] == 1
    assert len(result["flow"]) == 1
    assert result["flow"][0]["segment"] == 1
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_narrative_flow_thought_complete(ready_project):
    """Thought-complete flag is set correctly."""
    project_id, _, _ = ready_project

    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[
            {"start_ms": 0, "end_ms": 10000},
        ],
    )

    assert "error" not in result
    seg = result["flow"][0]
    # Last sentence is "Cloud Code can now edit my videos." - ends with period
    assert seg["thought_complete"] is True


@pytest.mark.asyncio
async def test_narrative_flow_sorts_segments(ready_project):
    """Segments given out of order are sorted by start_ms."""
    project_id, _, _ = ready_project

    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[
            {"start_ms": 75000, "end_ms": 85000},
            {"start_ms": 0, "end_ms": 10000},
        ],
    )

    assert "error" not in result
    assert result["segment_count"] == 2
    # First flow entry should be the earlier segment
    assert result["flow"][0]["source_range"] == "0-10000ms"


# ------------------------------------------------------------------
# Validation / error tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_narrative_flow_invalid_project(ready_project):
    """Non-existent project returns error."""
    _, _, _ = ready_project

    result = await clipcannon_get_narrative_flow(
        project_id="nonexistent_project",
        segments=[{"start_ms": 0, "end_ms": 1000}],
    )
    assert "error" in result
    assert result["error"]["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_narrative_flow_empty_segments(ready_project):
    """Empty segments list returns error."""
    project_id, _, _ = ready_project

    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[],
    )
    assert "error" in result
    assert result["error"]["code"] == "INVALID_PARAMETER"


@pytest.mark.asyncio
async def test_narrative_flow_invalid_segment(ready_project):
    """Segment with end <= start returns error."""
    project_id, _, _ = ready_project

    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[{"start_ms": 5000, "end_ms": 1000}],
    )
    assert "error" in result
    assert result["error"]["code"] == "INVALID_PARAMETER"
    assert "end_ms must be > start_ms" in result["error"]["message"]


# ------------------------------------------------------------------
# Dispatch test
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_narrative_flow(ready_project):
    """Dispatcher routes to get_narrative_flow correctly."""
    project_id, _, _ = ready_project

    result = await dispatch_discovery_tool(
        name="clipcannon_get_narrative_flow",
        arguments={
            "project_id": project_id,
            "segments": [
                {"start_ms": 0, "end_ms": 10000},
                {"start_ms": 20000, "end_ms": 30000},
            ],
        },
    )

    assert "error" not in result
    assert result["segment_count"] == 2


@pytest.mark.asyncio
async def test_narrative_flow_small_gap_no_promise_warning(ready_project):
    """Gap <= 5s does not trigger broken promise even with keywords."""
    project_id, _, _ = ready_project

    # Segment ends at 15000 with "Let me show you" text,
    # but gap is only 15000-17000 (2s) - should NOT warn
    result = await clipcannon_get_narrative_flow(
        project_id=project_id,
        segments=[
            {"start_ms": 0, "end_ms": 15000},
            {"start_ms": 17000, "end_ms": 25000},
        ],
    )

    assert "error" not in result
    gap_entries = [f for f in result["flow"] if "gap" in f]
    assert len(gap_entries) == 1
    # Gap is 2s (2000ms) - less than 5s threshold, no BROKEN_PROMISE
    assert gap_entries[0]["warning"] is None
