"""Tests for the feedback intent parser.

Tests cover:
- Parsing various feedback patterns into FeedbackIntent
- Timestamp parsing across multiple formats
- Intent-to-changes conversion for speed and color
- Full end-to-end apply_feedback tool integration
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from clipcannon.editing.edl import (
    AudioSpec,
    CaptionSpec,
    ColorSpec,
    CropSpec,
    EditDecisionList,
    MetadataSpec,
    RenderSettingsSpec,
    SegmentSpec,
)
from clipcannon.tools.feedback import (
    FeedbackIntent,
    find_segment_at_timestamp,
    intent_to_changes,
    parse_feedback,
    parse_timestamp_ms,
)


# ============================================================
# HELPERS
# ============================================================
def _make_edl(
    segments: list[SegmentSpec] | None = None,
    captions: CaptionSpec | None = None,
    audio: AudioSpec | None = None,
    color: ColorSpec | None = None,
) -> EditDecisionList:
    """Build a minimal EDL for testing."""
    if segments is None:
        segments = [
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=10000,
                output_start_ms=0,
                speed=1.0,
            ),
            SegmentSpec(
                segment_id=2,
                source_start_ms=15000,
                source_end_ms=30000,
                output_start_ms=10000,
                speed=1.0,
            ),
            SegmentSpec(
                segment_id=3,
                source_start_ms=35000,
                source_end_ms=50000,
                output_start_ms=25000,
                speed=1.0,
            ),
        ]
    return EditDecisionList(
        edit_id="edit_test",
        project_id="proj_test",
        name="Test Edit",
        target_platform="tiktok",
        segments=segments,
        captions=captions or CaptionSpec(font_size=48),
        audio=audio or AudioSpec(),
        color=color,
    )


# ============================================================
# PARSE TESTS
# ============================================================
class TestParseFeedback:
    """Tests for parse_feedback pattern matching."""

    def test_parse_cut_too_abrupt(self) -> None:
        """'the cut at 0:15 is too abrupt' -> transition_fix intent."""
        edl = _make_edl()
        intent = parse_feedback("the cut at 0:15 is too abrupt", edl)
        assert intent.intent_type == "transition_fix"
        assert intent.confidence >= 0.8
        assert intent.parameters.get("transition_type") == "crossfade"
        assert intent.target_timestamp_ms == 15000

    def test_parse_too_fast(self) -> None:
        """'too fast in the middle' -> speed_adjust intent."""
        edl = _make_edl()
        intent = parse_feedback("too fast in the middle", edl)
        assert intent.intent_type == "speed_adjust"
        assert intent.confidence >= 0.7
        assert intent.parameters.get("direction") == "slower"

    def test_parse_music_too_loud(self) -> None:
        """'the music is too loud' -> audio_adjust intent."""
        edl = _make_edl()
        intent = parse_feedback("the music is too loud", edl)
        assert intent.intent_type == "audio_adjust"
        assert intent.confidence >= 0.8
        assert intent.parameters.get("direction") == "quieter"

    def test_parse_make_warmer(self) -> None:
        """'make it warmer' -> color_adjust intent."""
        edl = _make_edl()
        intent = parse_feedback("make it warmer", edl)
        assert intent.intent_type == "color_adjust"
        assert intent.confidence >= 0.7
        assert intent.parameters.get("parameter") == "saturation"
        assert intent.parameters.get("direction") == "increase"

    def test_parse_text_bigger(self) -> None:
        """'make the text bigger' -> caption_resize intent."""
        edl = _make_edl()
        intent = parse_feedback("make the text bigger", edl)
        assert intent.intent_type == "caption_resize"
        assert intent.confidence >= 0.8
        assert intent.parameters.get("direction") == "bigger"

    def test_parse_zoom_in(self) -> None:
        """'zoom in on the dashboard' -> motion_add intent."""
        edl = _make_edl()
        intent = parse_feedback("zoom in on the dashboard", edl)
        assert intent.intent_type == "motion_add"
        assert intent.confidence >= 0.7
        assert intent.parameters.get("effect") == "zoom_in"
        assert intent.parameters.get("search_text") == "the dashboard"

    def test_parse_unknown(self) -> None:
        """Unparseable feedback returns unknown with confidence 0."""
        edl = _make_edl()
        intent = parse_feedback("I really like this video", edl)
        assert intent.intent_type == "unknown"
        assert intent.confidence == 0.0

    def test_parse_empty(self) -> None:
        """Empty feedback returns unknown."""
        edl = _make_edl()
        intent = parse_feedback("", edl)
        assert intent.intent_type == "unknown"
        assert intent.confidence == 0.0

    def test_parse_case_insensitive(self) -> None:
        """Pattern matching is case-insensitive."""
        edl = _make_edl()
        intent = parse_feedback("TOO FAST in the middle", edl)
        assert intent.intent_type == "speed_adjust"

    def test_parse_segment_targeting(self) -> None:
        """Timestamp in feedback targets the correct segment."""
        edl = _make_edl()
        # 0:05 = 5000ms, falls in segment 1 (0-10000ms)
        intent = parse_feedback("the cut at 0:05 is too abrupt", edl)
        assert intent.target_segment_ids == [1]

    def test_parse_brighter(self) -> None:
        """'brighter' -> color_adjust with brightness increase."""
        edl = _make_edl()
        intent = parse_feedback("make it brighter", edl)
        assert intent.intent_type == "color_adjust"
        assert intent.parameters.get("parameter") == "brightness"
        assert intent.parameters.get("direction") == "increase"


# ============================================================
# TIMESTAMP PARSING TESTS
# ============================================================
class TestTimestampParsing:
    """Tests for parse_timestamp_ms."""

    def test_mm_ss_format(self) -> None:
        """'0:15' -> 15000ms."""
        assert parse_timestamp_ms("at 0:15 the cut") == 15000

    def test_mm_ss_with_minutes(self) -> None:
        """'1:30' -> 90000ms."""
        assert parse_timestamp_ms("around 1:30") == 90000

    def test_seconds_format(self) -> None:
        """'at 15 seconds' -> 15000ms."""
        assert parse_timestamp_ms("at 15 seconds the music") == 15000

    def test_seconds_abbreviated(self) -> None:
        """'15s' -> 15000ms."""
        assert parse_timestamp_ms("around 15s mark") == 15000

    def test_minute_mark(self) -> None:
        """'at the 1 minute mark' -> 60000ms."""
        assert parse_timestamp_ms("at the 1 minute mark") == 60000

    def test_no_timestamp(self) -> None:
        """No timestamp returns None."""
        assert parse_timestamp_ms("make it faster") is None

    def test_fractional_seconds(self) -> None:
        """'0:15.5' -> 15500ms."""
        assert parse_timestamp_ms("at 0:15.5") == 15500


# ============================================================
# SEGMENT TARGETING TESTS
# ============================================================
class TestSegmentTargeting:
    """Tests for find_segment_at_timestamp."""

    def test_first_segment(self) -> None:
        edl = _make_edl()
        seg = find_segment_at_timestamp(edl, 5000)
        assert seg is not None
        assert seg.segment_id == 1

    def test_second_segment(self) -> None:
        edl = _make_edl()
        seg = find_segment_at_timestamp(edl, 15000)
        assert seg is not None
        assert seg.segment_id == 2

    def test_out_of_range(self) -> None:
        edl = _make_edl()
        seg = find_segment_at_timestamp(edl, 999999)
        assert seg is None


# ============================================================
# INTENT TO CHANGES TESTS
# ============================================================
class TestIntentToChanges:
    """Tests for intent_to_changes conversion."""

    def test_intent_to_changes_speed(self) -> None:
        """speed_adjust intent produces correct changes dict."""
        edl = _make_edl()
        intent = FeedbackIntent(
            intent_type="speed_adjust",
            target_segment_ids=[],
            parameters={"direction": "slower", "magnitude": 0.15},
            confidence=0.8,
            raw_feedback="too fast",
        )
        changes = intent_to_changes(intent, edl)
        assert "segments" in changes
        segments = changes["segments"]
        # All segments should have reduced speed
        for seg in segments:
            assert seg["speed"] == pytest.approx(0.85)

    def test_intent_to_changes_speed_targeted(self) -> None:
        """speed_adjust on specific segment only changes that segment."""
        edl = _make_edl()
        intent = FeedbackIntent(
            intent_type="speed_adjust",
            target_segment_ids=[2],
            parameters={"direction": "slower", "magnitude": 0.15},
            confidence=0.85,
            raw_feedback="too fast at 0:12",
        )
        changes = intent_to_changes(intent, edl)
        assert "segments" in changes
        segments = changes["segments"]
        # Only segment index 1 (id=2) should be slower
        assert segments[0]["speed"] == 1.0  # unchanged
        assert segments[1]["speed"] == pytest.approx(0.85)  # changed
        assert segments[2]["speed"] == 1.0  # unchanged

    def test_intent_to_changes_color_warmer(self) -> None:
        """color_adjust 'warmer' -> increased saturation."""
        edl = _make_edl()
        intent = FeedbackIntent(
            intent_type="color_adjust",
            parameters={
                "parameter": "saturation",
                "direction": "increase",
                "magnitude": 0.2,
            },
            confidence=0.8,
            raw_feedback="make it warmer",
        )
        changes = intent_to_changes(intent, edl)
        assert "_color" in changes
        assert changes["_color"]["saturation"] == pytest.approx(1.2)

    def test_intent_to_changes_caption_bigger(self) -> None:
        """caption_resize 'bigger' -> font_size increased by 8."""
        edl = _make_edl()
        intent = FeedbackIntent(
            intent_type="caption_resize",
            parameters={"direction": "bigger"},
            confidence=0.9,
            raw_feedback="make the text bigger",
        )
        changes = intent_to_changes(intent, edl)
        assert "captions" in changes
        assert changes["captions"]["font_size"] == 56  # 48 + 8

    def test_intent_to_changes_audio_quieter(self) -> None:
        """audio_adjust 'quieter' -> volume reduced by 3dB."""
        edl = _make_edl()
        intent = FeedbackIntent(
            intent_type="audio_adjust",
            parameters={"direction": "quieter", "magnitude_db": -3.0},
            confidence=0.85,
            raw_feedback="the music is too loud",
        )
        changes = intent_to_changes(intent, edl)
        assert "audio" in changes
        assert changes["audio"]["source_volume_db"] == -3.0

    def test_intent_to_changes_unknown(self) -> None:
        """Unknown intent returns empty changes."""
        edl = _make_edl()
        intent = FeedbackIntent(
            intent_type="unknown",
            confidence=0.0,
            raw_feedback="nice video",
        )
        changes = intent_to_changes(intent, edl)
        assert changes == {}


# ============================================================
# INTEGRATION FIXTURE (reused from test_editing_tools pattern)
# ============================================================
@pytest.fixture()
def project_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create a real project DB with schema and transcript data.

    Returns the project_id.
    """
    project_id = "proj_feedback_test"
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / project_id
    project_dir.mkdir(parents=True)
    db_path = project_dir / "analysis.db"

    conn = sqlite3.connect(str(db_path))

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS project (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_cfr_path TEXT,
            duration_ms INTEGER NOT NULL,
            resolution TEXT NOT NULL,
            fps REAL NOT NULL,
            codec TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ready',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transcript_segments (
            segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            text TEXT NOT NULL,
            speaker_id INTEGER,
            language TEXT DEFAULT 'en',
            word_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS transcript_words (
            word_id INTEGER PRIMARY KEY AUTOINCREMENT,
            segment_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            confidence REAL,
            speaker_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS topics (
            topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            label TEXT NOT NULL,
            keywords TEXT,
            coherence_score REAL,
            semantic_density REAL
        );

        CREATE TABLE IF NOT EXISTS highlights (
            highlight_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            type TEXT NOT NULL,
            score REAL NOT NULL,
            reason TEXT NOT NULL,
            emotion_score REAL,
            reaction_score REAL,
            semantic_score REAL,
            narrative_score REAL,
            visual_score REAL,
            quality_score REAL,
            speaker_score REAL
        );

        CREATE TABLE IF NOT EXISTS edits (
            edit_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            target_platform TEXT NOT NULL,
            target_profile TEXT NOT NULL,
            edl_json TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            total_duration_ms INTEGER,
            segment_count INTEGER,
            captions_enabled BOOLEAN DEFAULT TRUE,
            crop_mode TEXT DEFAULT 'auto',
            thumbnail_timestamp_ms INTEGER,
            metadata_title TEXT,
            metadata_description TEXT,
            metadata_hashtags TEXT,
            rejection_feedback TEXT,
            render_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS edit_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edit_id TEXT NOT NULL,
            segment_order INTEGER NOT NULL,
            source_start_ms INTEGER NOT NULL,
            source_end_ms INTEGER NOT NULL,
            output_start_ms INTEGER NOT NULL,
            speed REAL DEFAULT 1.0,
            transition_in_type TEXT,
            transition_in_duration_ms INTEGER,
            transition_out_type TEXT,
            transition_out_duration_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS renders (
            render_id TEXT PRIMARY KEY,
            edit_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            profile TEXT NOT NULL,
            output_path TEXT,
            output_sha256 TEXT,
            file_size_bytes INTEGER,
            duration_ms INTEGER,
            resolution TEXT,
            codec TEXT,
            thumbnail_path TEXT,
            render_duration_ms INTEGER,
            error_message TEXT,
            provenance_record_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS audio_assets (
            asset_id TEXT PRIMARY KEY,
            edit_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            sample_rate INTEGER DEFAULT 44100,
            model_used TEXT,
            generation_params TEXT,
            seed INTEGER,
            volume_db REAL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS edit_versions (
            version_id TEXT PRIMARY KEY,
            edit_id TEXT NOT NULL,
            parent_version_id TEXT,
            version_number INTEGER NOT NULL,
            edl_json TEXT NOT NULL,
            change_description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (edit_id) REFERENCES edits(edit_id)
        );
        CREATE INDEX IF NOT EXISTS idx_edit_versions_edit
            ON edit_versions(edit_id, version_number);

        INSERT OR REPLACE INTO schema_version (version) VALUES (2);
    """)

    conn.execute(
        "INSERT INTO project (project_id, name, source_path, source_sha256, "
        "duration_ms, resolution, fps, codec, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            "Feedback Test Project",
            "/tmp/source.mp4",
            "sha256_test_hash",
            300000,
            "1920x1080",
            30.0,
            "h264",
            "ready",
        ),
    )

    conn.execute(
        "INSERT INTO transcript_segments "
        "(project_id, start_ms, end_ms, text, speaker_id, language, word_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, 0, 30000, "This is a test transcript for feedback tools", 1, "en", 8),
    )
    seg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    words = [
        ("This", 0, 500),
        ("is", 600, 900),
        ("a", 1000, 1200),
        ("test", 1300, 1800),
        ("transcript", 2000, 3000),
        ("for", 3100, 3400),
        ("feedback", 3500, 4200),
        ("tools", 4300, 5000),
    ]
    for word, start, end in words:
        conn.execute(
            "INSERT INTO transcript_words "
            "(segment_id, word, start_ms, end_ms, confidence, speaker_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (seg_id, word, start, end, 0.95, 1),
        )

    conn.execute(
        "INSERT INTO topics (project_id, start_ms, end_ms, label, keywords, "
        "coherence_score, semantic_density) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, 0, 30000, "Testing workflow", '["testing", "workflow"]', 0.85, 0.7),
    )
    conn.execute(
        "INSERT INTO highlights (project_id, start_ms, end_ms, type, score, "
        "reason) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, 5000, 15000, "insight", 0.9, "Key testing insight revealed"),
    )

    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "clipcannon.tools.editing_helpers.projects_dir",
        lambda: projects_dir,
    )

    return project_id


# ============================================================
# INTEGRATION TEST
# ============================================================
class TestApplyFeedbackIntegration:
    """Full end-to-end integration test."""

    @pytest.mark.asyncio()
    async def test_apply_feedback_too_fast(
        self, project_setup: str, tmp_path: Path,
    ) -> None:
        """Create edit, apply 'too fast' feedback, verify speed changed."""
        from clipcannon.tools.editing import dispatch_editing_tool

        project_id = project_setup

        # Step 1: Create an edit with 2 segments
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Feedback Test Edit",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                    {"source_start_ms": 60000, "source_end_ms": 90000},
                ],
            },
        )
        assert "error" not in create_result, f"Create failed: {create_result}"
        edit_id = str(create_result["edit_id"])

        # Step 2: Apply "too fast" feedback
        feedback_result = await dispatch_editing_tool(
            "clipcannon_apply_feedback",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "feedback": "it's too fast, slow it down",
            },
        )
        assert "error" not in feedback_result, f"Feedback failed: {feedback_result}"
        assert feedback_result["parsed_intent"]["intent_type"] == "speed_adjust"
        assert feedback_result["parsed_intent"]["confidence"] >= 0.7

        # Step 3: Verify the speed was actually changed in the EDL
        modify_result = feedback_result["modify_result"]
        assert "error" not in modify_result, f"Modify failed: {modify_result}"
        assert "segments" in modify_result.get("updated_fields", [])

        # Reload EDL from DB and check speeds
        projects_dir = tmp_path / "projects"
        db_path = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT edl_json FROM edits WHERE edit_id = ?", (edit_id,),
        ).fetchone()
        conn.close()

        import json
        edl_data = json.loads(row["edl_json"])
        for seg in edl_data["segments"]:
            # Speed should have decreased from 1.0
            assert seg["speed"] < 1.0

    @pytest.mark.asyncio()
    async def test_apply_feedback_low_confidence(
        self, project_setup: str,
    ) -> None:
        """Unparseable feedback returns LOW_CONFIDENCE error."""
        from clipcannon.tools.editing import dispatch_editing_tool

        project_id = project_setup

        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Low Confidence Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        edit_id = str(create_result["edit_id"])

        feedback_result = await dispatch_editing_tool(
            "clipcannon_apply_feedback",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "feedback": "I really like this video a lot",
            },
        )
        assert "error" in feedback_result
        assert feedback_result["error"]["code"] == "LOW_CONFIDENCE"

    @pytest.mark.asyncio()
    async def test_apply_feedback_caption_resize(
        self, project_setup: str, tmp_path: Path,
    ) -> None:
        """Apply 'make text bigger' feedback, verify font_size changed."""
        from clipcannon.tools.editing import dispatch_editing_tool

        project_id = project_setup

        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Caption Resize Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
                "captions": {"enabled": True, "font_size": 48},
            },
        )
        assert "error" not in create_result
        edit_id = str(create_result["edit_id"])

        feedback_result = await dispatch_editing_tool(
            "clipcannon_apply_feedback",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "feedback": "make the text bigger please",
            },
        )
        assert "error" not in feedback_result, f"Feedback failed: {feedback_result}"
        assert feedback_result["parsed_intent"]["intent_type"] == "caption_resize"

        # Verify font size increased
        projects_dir = tmp_path / "projects"
        db_path = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT edl_json FROM edits WHERE edit_id = ?", (edit_id,),
        ).fetchone()
        conn.close()

        import json
        edl_data = json.loads(row["edl_json"])
        assert edl_data["captions"]["font_size"] == 56  # 48 + 8
