"""Tests for ClipCannon understanding MCP tools.

Tests transcript retrieval, segment detail, search, and error
handling with synthetic data in a temp database.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, execute
from clipcannon.db.schema import create_project_db
from clipcannon.tools.understanding import (
    clipcannon_get_transcript,
)
from clipcannon.tools.understanding_search import (
    clipcannon_search_content,
)
from clipcannon.tools.understanding_visual import (
    clipcannon_get_segment_detail,
)


@pytest.fixture
def ready_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a project in 'ready' status with synthetic analysis data."""
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    # Create a synthetic frame file
    frame_path = project_dir / "frames" / "frame_000001.jpg"
    frame_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

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

        # Speakers
        batch_insert(
            conn, "speakers",
            ["project_id", "label", "total_speaking_ms", "speaking_pct"],
            [
                (project_id, "Speaker 1", 80000, 66.7),
                (project_id, "Speaker 2", 40000, 33.3),
            ],
        )

        # Transcript segments
        batch_insert(
            conn, "transcript_segments",
            ["project_id", "start_ms", "end_ms", "text", "speaker_id", "word_count"],
            [
                (project_id, 0, 5000, "Hello and welcome to the show.", 1, 7),
                (project_id, 5000, 10000, "Today we discuss machine learning.", 1, 6),
                (project_id, 10000, 15000, "That is a great topic.", 2, 6),
                (project_id, 60000, 65000, "Let me explain further.", 1, 4),
                (project_id, 65000, 70000, "Deep learning is fascinating.", 2, 5),
            ],
        )

        # Transcript words for first segment
        batch_insert(
            conn, "transcript_words",
            ["segment_id", "word", "start_ms", "end_ms", "confidence"],
            [
                (1, "Hello", 0, 500, 0.99),
                (1, "and", 500, 700, 0.98),
                (1, "welcome", 700, 1200, 0.97),
                (1, "to", 1200, 1400, 0.99),
                (1, "the", 1400, 1600, 0.98),
                (1, "show", 1600, 2000, 0.99),
            ],
        )

        # Topics
        batch_insert(
            conn, "topics",
            ["project_id", "start_ms", "end_ms", "label", "keywords",
             "coherence_score", "semantic_density"],
            [
                (project_id, 0, 15000, "introduction", '["hello","welcome","show"]',
                 0.85, 0.72),
                (project_id, 60000, 70000, "deep learning", '["learning","deep","neural"]',
                 0.90, 0.80),
            ],
        )

        # Highlights
        batch_insert(
            conn, "highlights",
            ["project_id", "start_ms", "end_ms", "type", "score", "reason",
             "emotion_score", "reaction_score", "semantic_score",
             "narrative_score", "visual_score", "quality_score", "speaker_score"],
            [
                (project_id, 0, 30000, "key_topic", 0.85,
                 "High semantic density", 0.7, 0.5, 0.9, 0.8, 0.6, 0.7, 0.9),
                (project_id, 60000, 90000, "emotional_peak", 0.72,
                 "High energy", 0.9, 0.3, 0.6, 0.7, 0.5, 0.6, 0.8),
            ],
        )

        # Reactions
        batch_insert(
            conn, "reactions",
            ["project_id", "start_ms", "end_ms", "type", "confidence",
             "intensity", "context_transcript"],
            [
                (project_id, 5000, 6000, "laughter", 0.85, "medium",
                 "Today we discuss machine learning."),
            ],
        )

        # Emotion curve
        batch_insert(
            conn, "emotion_curve",
            ["project_id", "start_ms", "end_ms", "arousal", "valence", "energy"],
            [
                (project_id, 0, 5000, 0.4, 0.6, 0.5),
                (project_id, 5000, 10000, 0.6, 0.7, 0.65),
                (project_id, 10000, 15000, 0.5, 0.5, 0.55),
            ],
        )

        # Beats
        execute(
            conn,
            """INSERT INTO beats (project_id, has_music, source, tempo_bpm,
               tempo_confidence, beat_count) VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, False, "speech", 0.0, 0.0, 0),
        )

        # Content safety
        execute(
            conn,
            """INSERT INTO content_safety (project_id, profanity_count,
               profanity_density, content_rating) VALUES (?, ?, ?, ?)""",
            (project_id, 0, 0.0, "G"),
        )

        # Stream status
        streams = [
            "source_separation", "visual", "ocr", "quality", "shot_type",
            "transcription", "semantic", "emotion", "speaker", "reactions",
            "acoustic", "beats", "chronemic", "storyboards", "profanity",
            "highlights",
        ]
        for stream in streams:
            execute(
                conn,
                "INSERT INTO stream_status (project_id, stream_name, status) "
                "VALUES (?, ?, 'completed')",
                (project_id, stream),
            )

        # Pacing
        batch_insert(
            conn, "pacing",
            ["project_id", "start_ms", "end_ms", "words_per_minute",
             "pause_ratio", "speaker_changes", "label"],
            [
                (project_id, 0, 60000, 120.0, 0.15, 2, "moderate"),
            ],
        )

        # Silence gaps
        batch_insert(
            conn, "silence_gaps",
            ["project_id", "start_ms", "end_ms", "duration_ms", "type"],
            [
                (project_id, 15000, 60000, 45000, "extended_pause"),
            ],
        )

        # Scenes
        batch_insert(
            conn, "scenes",
            ["project_id", "start_ms", "end_ms", "key_frame_path",
             "key_frame_timestamp_ms", "shot_type", "quality_avg",
             "quality_min", "quality_classification"],
            [
                (project_id, 0, 60000, str(frame_path), 0,
                 "medium_shot", 0.75, 0.60, "good"),
                (project_id, 60000, 120000, str(frame_path), 60000,
                 "close_up", 0.80, 0.65, "good"),
            ],
        )

        # Storyboard grids
        grid_path = project_dir / "storyboards" / "grid_001.jpg"
        grid_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
        batch_insert(
            conn, "storyboard_grids",
            ["project_id", "grid_number", "grid_path",
             "cell_timestamps_ms", "cell_metadata"],
            [
                (project_id, 1, str(grid_path),
                 json.dumps([0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000]),
                 json.dumps({"cells": [{"ts": i * 500} for i in range(9)]})),
            ],
        )

        # Provenance (minimal for count)
        execute(
            conn,
            """INSERT INTO provenance (
                record_id, project_id, timestamp_utc, operation,
                stage, chain_hash
            ) VALUES (?, ?, datetime('now'), 'probe', 'ffprobe', 'hash1')""",
            (f"prov_{uuid.uuid4().hex[:8]}", project_id),
        )

        conn.commit()
    finally:
        conn.close()

    # Monkeypatch _projects_dir to use tmp_path
    import clipcannon.tools.understanding as und_mod
    monkeypatch.setattr(und_mod, "_projects_dir", lambda: tmp_path)

    return {
        "project_id": project_id,
        "db_path": db_path,
        "project_dir": project_dir,
        "tmp_path": tmp_path,
    }


class TestGetTranscript:
    """Tests for clipcannon_get_transcript."""

    @pytest.mark.asyncio
    async def test_default_range(self, ready_project: dict[str, object]) -> None:
        """Returns all segments in default 15-minute window."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_get_transcript(pid)

        assert "error" not in result
        assert result["start_ms"] == 0
        assert result["end_ms"] == 900_000
        assert result["segment_count"] == 5
        assert result["has_more"] is False

    @pytest.mark.asyncio
    async def test_time_range_filter(self, ready_project: dict[str, object]) -> None:
        """Returns only segments in the specified range."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_get_transcript(pid, start_ms=0, end_ms=12000)

        # Should include segments overlapping 0-12000
        assert result["segment_count"] == 3

    @pytest.mark.asyncio
    async def test_word_level_timestamps(self, ready_project: dict[str, object]) -> None:
        """Segments include word-level timestamps."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_get_transcript(pid, start_ms=0, end_ms=6000, detail="words")

        # First segment should have words when detail="words"
        seg = result["segments"][0]
        assert "words" in seg
        assert len(seg["words"]) == 6

    @pytest.mark.asyncio
    async def test_pagination_flag(self, ready_project: dict[str, object]) -> None:
        """Has_more is True when more segments exist after the range."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_get_transcript(pid, start_ms=0, end_ms=20000)

        assert result["has_more"] is True
        assert result["next_start_ms"] == 20000


class TestGetSegmentDetail:
    """Tests for clipcannon_get_segment_detail."""

    @pytest.mark.asyncio
    async def test_returns_all_streams(self, ready_project: dict[str, object]) -> None:
        """Segment detail includes all data streams for the range."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_get_segment_detail(pid, start_ms=0, end_ms=15000)

        assert "error" not in result
        assert "transcript" in result
        assert "emotion_curve" in result
        assert "speakers" in result
        assert "reactions" in result
        assert "pacing" in result
        assert "scenes_quality" in result
        assert "silence_gaps" in result

        # Transcript should have 3 segments in 0-15000
        assert len(result["transcript"]) == 3
        # Emotion curve should have 3 entries
        assert len(result["emotion_curve"]) == 3

    @pytest.mark.asyncio
    async def test_invalid_range(self, ready_project: dict[str, object]) -> None:
        """Returns error when end_ms <= start_ms."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_get_segment_detail(pid, start_ms=10000, end_ms=5000)
        assert "error" in result


class TestSearchContent:
    """Tests for clipcannon_search_content."""

    @pytest.mark.asyncio
    async def test_text_search(self, ready_project: dict[str, object]) -> None:
        """Text search finds matching transcript segments."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_search_content(
            pid, query="machine learning", search_type="text",
        )

        assert "error" not in result
        assert result["result_count"] >= 1
        assert "machine learning" in result["results"][0]["text"].lower()

    @pytest.mark.asyncio
    async def test_text_search_no_results(self, ready_project: dict[str, object]) -> None:
        """Text search returns empty results for non-matching query."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_search_content(
            pid, query="xyzzy_nonexistent_term", search_type="text",
        )
        assert result["result_count"] == 0

    @pytest.mark.asyncio
    async def test_invalid_search_type(self, ready_project: dict[str, object]) -> None:
        """Returns error for invalid search type."""
        pid = str(ready_project["project_id"])
        result = await clipcannon_search_content(
            pid, query="test", search_type="invalid",
        )
        assert "error" in result


class TestErrorHandling:
    """Tests for error handling across understanding tools."""

    @pytest.mark.asyncio
    async def test_transcript_not_found(self, ready_project: dict[str, object]) -> None:
        """Returns error for missing project."""
        result = await clipcannon_get_transcript("proj_does_not_exist")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_wrong_status(
        self, ready_project: dict[str, object],
    ) -> None:
        """Returns INVALID_STATE when project is not ready."""
        pid = str(ready_project["project_id"])
        db = Path(str(ready_project["db_path"]))
        # Change status to 'created'
        conn = get_connection(db, enable_vec=False, dict_rows=False)
        try:
            execute(
                conn,
                "UPDATE project SET status = 'created' WHERE project_id = ?",
                (pid,),
            )
            conn.commit()
        finally:
            conn.close()

        result = await clipcannon_get_transcript(pid)
        assert "error" in result
        assert result["error"]["code"] == "INVALID_STATE"
