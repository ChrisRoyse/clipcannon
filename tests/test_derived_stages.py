"""Integration tests for ClipCannon derived pipeline stages.

Tests profanity detection, chronemic analysis, highlight scoring,
and the finalize stage using mock data in a temporary database.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one, batch_insert
from clipcannon.db.schema import create_project_db
from clipcannon.pipeline.chronemic import run_chronemic
from clipcannon.pipeline.finalize import run_finalize
from clipcannon.pipeline.highlights import run_highlights
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.profanity import (
    _compute_content_rating,
    _load_wordlist,
    _resolve_wordlist_path,
    run_profanity,
)
from clipcannon.provenance import verify_chain


@pytest.fixture
def mock_project(tmp_path: Path):
    """Set up a project with mock transcript/acoustic data for testing."""
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    # Create subdirectories
    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    # Create database
    db_path = create_project_db(project_id, base_dir=tmp_path)

    # Insert project record with duration
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        execute(
            conn,
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, "Test Video", "/tmp/test.mp4",
                "abc123", 180000, "1920x1080", 30.0, "h264", "probed",
            ),
        )

        # Insert speakers
        execute(
            conn,
            "INSERT INTO speakers (project_id, label, total_speaking_ms, speaking_pct) "
            "VALUES (?, ?, ?, ?)",
            (project_id, "Speaker_1", 120000, 66.7),
        )
        execute(
            conn,
            "INSERT INTO speakers (project_id, label, total_speaking_ms, speaking_pct) "
            "VALUES (?, ?, ?, ?)",
            (project_id, "Speaker_2", 60000, 33.3),
        )

        # Insert transcript segments (3 minutes of content)
        segments_data = [
            (project_id, 0, 15000, "Hello everyone, welcome to the damn show.", 1, "en", 7),
            (project_id, 15000, 30000, "Today we are going to talk about some shit.", 1, "en", 9),
            (project_id, 30000, 50000, "Let me introduce our guest speaker.", 1, "en", 6),
            (project_id, 50000, 70000, "Thank you for having me, this is great.", 2, "en", 8),
            (project_id, 70000, 90000, "So the first topic is really interesting.", 2, "en", 7),
            (project_id, 90000, 110000, "I think that is a crap argument honestly.", 1, "en", 8),
            (project_id, 110000, 130000, "Well you might be right about that.", 2, "en", 7),
            (project_id, 130000, 150000, "Let me explain why this sucks so bad.", 1, "en", 8),
            (project_id, 150000, 170000, "That is a good point actually.", 2, "en", 6),
            (project_id, 170000, 180000, "Thanks for watching everyone!", 1, "en", 4),
        ]
        batch_insert(
            conn,
            "transcript_segments",
            ["project_id", "start_ms", "end_ms", "text", "speaker_id", "language", "word_count"],
            segments_data,
        )

        # Insert transcript words (including profanity)
        words_data = [
            # Segment 1 words
            (1, "Hello", 0, 500, 0.95, 1),
            (1, "everyone,", 500, 1200, 0.90, 1),
            (1, "welcome", 1200, 2000, 0.92, 1),
            (1, "to", 2000, 2300, 0.99, 1),
            (1, "the", 2300, 2600, 0.99, 1),
            (1, "damn", 2600, 3200, 0.88, 1),
            (1, "show.", 3200, 4000, 0.91, 1),
            # Segment 2 words
            (2, "Today", 15000, 15500, 0.95, 1),
            (2, "we", 15500, 15800, 0.99, 1),
            (2, "are", 15800, 16100, 0.99, 1),
            (2, "going", 16100, 16500, 0.97, 1),
            (2, "to", 16500, 16700, 0.99, 1),
            (2, "talk", 16700, 17100, 0.95, 1),
            (2, "about", 17100, 17500, 0.94, 1),
            (2, "some", 17500, 17900, 0.96, 1),
            (2, "shit.", 17900, 18500, 0.85, 1),
            # Segment 6 word
            (6, "I", 90000, 90200, 0.99, 1),
            (6, "think", 90200, 90600, 0.97, 1),
            (6, "that", 90600, 90900, 0.98, 1),
            (6, "is", 90900, 91100, 0.99, 1),
            (6, "a", 91100, 91200, 0.99, 1),
            (6, "crap", 91200, 91700, 0.87, 1),
            (6, "argument", 91700, 92300, 0.93, 1),
            (6, "honestly.", 92300, 93000, 0.91, 1),
            # Segment 8 word
            (8, "Let", 130000, 130300, 0.98, 1),
            (8, "me", 130300, 130500, 0.99, 1),
            (8, "explain", 130500, 131000, 0.95, 1),
            (8, "why", 131000, 131300, 0.97, 1),
            (8, "this", 131300, 131600, 0.98, 1),
            (8, "sucks", 131600, 132100, 0.84, 1),
            (8, "so", 132100, 132400, 0.96, 1),
            (8, "bad.", 132400, 132800, 0.94, 1),
        ]
        batch_insert(
            conn,
            "transcript_words",
            ["segment_id", "word", "start_ms", "end_ms", "confidence", "speaker_id"],
            words_data,
        )

        # Insert silence gaps
        gaps_data = [
            (project_id, 14500, 15000, 500, "silence"),
            (project_id, 49000, 50000, 1000, "silence"),
            (project_id, 89000, 90000, 1000, "silence"),
            (project_id, 129000, 130000, 1000, "silence"),
        ]
        batch_insert(
            conn,
            "silence_gaps",
            ["project_id", "start_ms", "end_ms", "duration_ms", "type"],
            gaps_data,
        )

        # Insert emotion curve
        emotion_data = [
            (project_id, 0, 30000, 0.6, 0.5, 0.65),
            (project_id, 30000, 60000, 0.4, 0.3, 0.45),
            (project_id, 60000, 90000, 0.7, 0.6, 0.75),
            (project_id, 90000, 120000, 0.8, 0.7, 0.85),
            (project_id, 120000, 150000, 0.5, 0.4, 0.55),
            (project_id, 150000, 180000, 0.3, 0.2, 0.35),
        ]
        batch_insert(
            conn,
            "emotion_curve",
            ["project_id", "start_ms", "end_ms", "arousal", "valence", "energy"],
            emotion_data,
        )

        # Insert reactions
        reactions_data = [
            (project_id, 25000, 28000, "laughter", 0.7, 3000, "moderate", "some shit"),
            (project_id, 90000, 93000, "applause", 0.8, 3000, "strong", "crap argument"),
        ]
        batch_insert(
            conn,
            "reactions",
            ["project_id", "start_ms", "end_ms", "type", "confidence",
             "duration_ms", "intensity", "context_transcript"],
            reactions_data,
        )

        # Insert topics
        topics_data = [
            (project_id, 0, 60000, "introduction", "welcome,show", 0.7, 0.6),
            (project_id, 60000, 120000, "main_discussion", "topic,argument", 0.8, 0.8),
            (project_id, 120000, 180000, "conclusion", "thanks,goodbye", 0.6, 0.5),
        ]
        batch_insert(
            conn,
            "topics",
            ["project_id", "start_ms", "end_ms", "label", "keywords",
             "coherence_score", "semantic_density"],
            topics_data,
        )

        # Insert scenes
        scenes_data = [
            (project_id, 0, 30000, "/tmp/f1.jpg", 15000, 0.9, None, False,
             None, None, "medium", 0.8, None, 0.7, 0.6, "good", None),
            (project_id, 30000, 70000, "/tmp/f2.jpg", 50000, 0.85, None, True,
             0.5, 0.5, "close_up", 0.9, None, 0.8, 0.7, "excellent", None),
            (project_id, 70000, 120000, "/tmp/f3.jpg", 95000, 0.88, None, True,
             0.4, 0.6, "medium", 0.85, None, 0.75, 0.65, "good", None),
            (project_id, 120000, 160000, "/tmp/f4.jpg", 140000, 0.92, None, False,
             None, None, "wide", 0.7, None, 0.65, 0.5, "fair", None),
            (project_id, 160000, 180000, "/tmp/f5.jpg", 170000, 0.87, None, True,
             0.5, 0.5, "close_up", 0.9, None, 0.8, 0.7, "good", None),
        ]
        batch_insert(
            conn,
            "scenes",
            ["project_id", "start_ms", "end_ms", "key_frame_path",
             "key_frame_timestamp_ms", "visual_similarity_avg", "dominant_colors",
             "face_detected", "face_position_x", "face_position_y",
             "shot_type", "shot_type_confidence", "crop_recommendation",
             "quality_avg", "quality_min", "quality_classification", "quality_issues"],
            scenes_data,
        )

        # Insert acoustic data
        execute(
            conn,
            "INSERT INTO acoustic (project_id, avg_volume_db, dynamic_range_db) "
            "VALUES (?, ?, ?)",
            (project_id, -18.5, 24.3),
        )

        # Insert beats
        execute(
            conn,
            "INSERT INTO beats (project_id, has_music, source, tempo_bpm, "
            "tempo_confidence, beat_positions_ms, downbeat_positions_ms, beat_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, False, "scipy_fallback", None, None, "[]", "[]", 0),
        )

        conn.commit()
    finally:
        conn.close()

    config = ClipCannonConfig.load()
    return project_id, db_path, project_dir, config


class TestWordlistLoading:
    """Tests for the profanity word list loader."""

    def test_wordlist_file_exists(self):
        """The bundled word list should exist and be loadable."""
        path = _resolve_wordlist_path()
        assert path.exists(), f"Word list not found at {path}"

    def test_wordlist_has_entries(self):
        """Word list should contain at least 100 words."""
        path = _resolve_wordlist_path()
        words = _load_wordlist(path)
        assert len(words) >= 100

    def test_wordlist_has_all_severities(self):
        """Word list should contain severe, moderate, and mild words."""
        path = _resolve_wordlist_path()
        words = _load_wordlist(path)
        severities = set(words.values())
        assert "severe" in severities
        assert "moderate" in severities
        assert "mild" in severities


class TestContentRating:
    """Tests for content rating thresholds."""

    def test_clean(self):
        """Zero matches should produce 'clean' rating."""
        assert _compute_content_rating(0) == "clean"

    def test_mild(self):
        """1-3 matches should produce 'mild' rating."""
        assert _compute_content_rating(1) == "mild"
        assert _compute_content_rating(3) == "mild"

    def test_moderate(self):
        """4-10 matches should produce 'moderate' rating."""
        assert _compute_content_rating(4) == "moderate"
        assert _compute_content_rating(10) == "moderate"

    def test_explicit(self):
        """More than 10 matches should produce 'explicit' rating."""
        assert _compute_content_rating(11) == "explicit"
        assert _compute_content_rating(100) == "explicit"


class TestProfanityStage:
    """Tests for the profanity detection pipeline stage."""

    def test_profanity_detection(self, mock_project):
        """Should detect profanity words and insert events."""
        project_id, db_path, project_dir, config = mock_project
        result = asyncio.run(
            run_profanity(project_id, db_path, project_dir, config),
        )

        assert result.success is True
        assert result.operation == "profanity_detection"
        assert result.provenance_record_id is not None

        # Check profanity_events
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            events = fetch_all(
                conn,
                "SELECT * FROM profanity_events WHERE project_id = ?",
                (project_id,),
            )
            # Should detect: damn (moderate), shit (moderate),
            # crap (mild), sucks (mild) = 4 matches
            assert len(events) >= 3
            words_found = [str(e["word"]).lower().strip(".,") for e in events]
            # At least some of these should be found
            assert any(w in words_found for w in ["damn", "shit", "crap", "sucks"])

            # Check content_safety
            safety = fetch_one(
                conn,
                "SELECT * FROM content_safety WHERE project_id = ?",
                (project_id,),
            )
            assert safety is not None
            assert int(safety["profanity_count"]) >= 3
            assert safety["content_rating"] in ("mild", "moderate", "explicit")
        finally:
            conn.close()


class TestChronemicStage:
    """Tests for the chronemic/pacing pipeline stage."""

    def test_chronemic_computation(self, mock_project):
        """Should compute pacing windows and insert records."""
        project_id, db_path, project_dir, config = mock_project
        result = asyncio.run(
            run_chronemic(project_id, db_path, project_dir, config),
        )

        assert result.success is True
        assert result.operation == "chronemic_analysis"
        assert result.provenance_record_id is not None

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            pacing = fetch_all(
                conn,
                "SELECT * FROM pacing WHERE project_id = ? ORDER BY start_ms",
                (project_id,),
            )
            # 180s / 60s = 3 windows
            assert len(pacing) == 3

            # Check first window has valid data
            w1 = pacing[0]
            assert int(w1["start_ms"]) == 0
            assert int(w1["end_ms"]) == 60000
            assert float(w1["words_per_minute"]) >= 0
            assert float(w1["pause_ratio"]) >= 0
            assert w1["label"] in (
                "fast_dialogue", "normal", "slow_monologue", "dead_air",
            )
        finally:
            conn.close()


class TestHighlightsStage:
    """Tests for the multi-signal highlight scoring stage."""

    def test_highlight_scoring(self, mock_project):
        """Should score candidate windows and insert top highlights."""
        project_id, db_path, project_dir, config = mock_project
        result = asyncio.run(
            run_highlights(project_id, db_path, project_dir, config),
        )

        assert result.success is True
        assert result.operation == "highlight_scoring"
        assert result.provenance_record_id is not None

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            highlights = fetch_all(
                conn,
                "SELECT * FROM highlights WHERE project_id = ? ORDER BY score DESC",
                (project_id,),
            )
            # 180s / 30s = 6 candidate windows, all should be stored
            # (less than max_highlights=20)
            assert len(highlights) >= 1

            top = highlights[0]
            assert float(top["score"]) > 0
            assert top["reason"] is not None
            assert len(str(top["reason"])) > 10
            assert top["type"] is not None

            # Check all component scores are populated
            assert float(top["emotion_score"]) >= 0
            assert float(top["reaction_score"]) >= 0
            assert float(top["semantic_score"]) >= 0
            assert float(top["narrative_score"]) >= 0
            assert float(top["visual_score"]) >= 0
            assert float(top["quality_score"]) >= 0
            assert float(top["speaker_score"]) >= 0
        finally:
            conn.close()


class TestFinalizeStage:
    """Tests for the finalize pipeline stage."""

    def test_finalize_sets_ready(self, mock_project):
        """Finalize should set project status to 'ready' after chain verification."""
        project_id, db_path, project_dir, config = mock_project

        # Run the derived stages first to produce provenance records
        asyncio.run(run_profanity(project_id, db_path, project_dir, config))
        asyncio.run(run_chronemic(project_id, db_path, project_dir, config))
        asyncio.run(run_highlights(project_id, db_path, project_dir, config))

        # Run finalize
        result = asyncio.run(
            run_finalize(project_id, db_path, project_dir, config),
        )

        assert result.success is True
        assert result.operation == "finalize"
        assert result.provenance_record_id is not None

        # Check project status
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            project = fetch_one(
                conn,
                "SELECT status FROM project WHERE project_id = ?",
                (project_id,),
            )
            assert project is not None
            assert project["status"] in ("ready", "ready_degraded")

            # Check stream_status has all streams
            statuses = fetch_all(
                conn,
                "SELECT stream_name, status FROM stream_status "
                "WHERE project_id = ?",
                (project_id,),
            )
            stream_names = {str(s["stream_name"]) for s in statuses}
            # All pipeline streams should be tracked
            from clipcannon.db.schema import PIPELINE_STREAMS
            for stream in PIPELINE_STREAMS:
                assert stream in stream_names, (
                    f"Stream '{stream}' missing from stream_status"
                )
        finally:
            conn.close()

    def test_finalize_verifies_provenance(self, mock_project):
        """Finalize should verify the provenance chain is intact."""
        project_id, db_path, project_dir, config = mock_project

        # Run one stage to create provenance
        asyncio.run(run_profanity(project_id, db_path, project_dir, config))

        # Verify chain manually before finalize
        chain_result = verify_chain(project_id, db_path)
        assert chain_result.verified is True

        # Run finalize
        result = asyncio.run(
            run_finalize(project_id, db_path, project_dir, config),
        )
        assert result.success is True

    def test_finalize_cleans_temp_files(self, mock_project):
        """Finalize should remove ephemeral temp files."""
        project_id, db_path, project_dir, config = mock_project

        # Create some temp files
        (project_dir / "temp_processing.tmp").write_text("temp data")
        (project_dir / "partial_output.part").write_text("partial")
        assert (project_dir / "temp_processing.tmp").exists()

        asyncio.run(run_finalize(project_id, db_path, project_dir, config))

        # Temp files should be gone
        assert not (project_dir / "temp_processing.tmp").exists()
        assert not (project_dir / "partial_output.part").exists()


class TestFullDerivedPipeline:
    """End-to-end test running all derived stages in sequence."""

    def test_full_pipeline(self, mock_project):
        """Run profanity -> chronemic -> highlights -> finalize."""
        project_id, db_path, project_dir, config = mock_project

        # Run all stages
        r1 = asyncio.run(run_profanity(project_id, db_path, project_dir, config))
        assert r1.success is True

        r2 = asyncio.run(run_chronemic(project_id, db_path, project_dir, config))
        assert r2.success is True

        r3 = asyncio.run(run_highlights(project_id, db_path, project_dir, config))
        assert r3.success is True

        r4 = asyncio.run(run_finalize(project_id, db_path, project_dir, config))
        assert r4.success is True

        # Comprehensive verification
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            # profanity_events has rows
            pe = fetch_all(
                conn,
                "SELECT * FROM profanity_events WHERE project_id = ?",
                (project_id,),
            )
            assert len(pe) >= 3

            # content_safety has a row
            cs = fetch_one(
                conn,
                "SELECT * FROM content_safety WHERE project_id = ?",
                (project_id,),
            )
            assert cs is not None
            assert cs["content_rating"] is not None

            # pacing has rows
            pacing = fetch_all(
                conn,
                "SELECT * FROM pacing WHERE project_id = ?",
                (project_id,),
            )
            assert len(pacing) == 3

            # highlights has rows
            highlights = fetch_all(
                conn,
                "SELECT * FROM highlights WHERE project_id = ?",
                (project_id,),
            )
            assert len(highlights) >= 1

            # stream_status has all streams
            from clipcannon.db.schema import PIPELINE_STREAMS
            statuses = fetch_all(
                conn,
                "SELECT stream_name, status FROM stream_status "
                "WHERE project_id = ?",
                (project_id,),
            )
            stream_names = {str(s["stream_name"]) for s in statuses}
            for stream in PIPELINE_STREAMS:
                assert stream in stream_names

            # Project status is 'ready'
            project = fetch_one(
                conn,
                "SELECT status FROM project WHERE project_id = ?",
                (project_id,),
            )
            assert project is not None
            assert project["status"] in ("ready", "ready_degraded")

            # Provenance chain is verified
            chain = verify_chain(project_id, db_path)
            assert chain.verified is True
            # 3 derived stages + finalize = 4 provenance records
            assert chain.total_records >= 4
        finally:
            conn.close()
