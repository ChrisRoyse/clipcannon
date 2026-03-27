"""Tests for the EDL (Edit Decision List) module.

Tests cover:
- EDL model creation and validation
- Segment ordering and overlap detection
- Transition duration constraints
- Speed range validation
- CaptionSpec, CropSpec, MetadataSpec creation
- Total duration computation
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

from clipcannon.editing.edl import (
    CaptionSpec,
    CropSpec,
    EditDecisionList,
    MetadataSpec,
    SegmentSpec,
    TransitionSpec,
    compute_total_duration,
    validate_edl,
)


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture()
def project_db(tmp_path: Path) -> Path:
    """Create a real project database with schema v2 and project row."""
    db_path = tmp_path / "analysis.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS project ("
        "project_id TEXT PRIMARY KEY, name TEXT, source_path TEXT, "
        "source_sha256 TEXT, duration_ms INTEGER, resolution TEXT, "
        "fps REAL, codec TEXT, status TEXT DEFAULT 'ready', "
        "created_at TEXT DEFAULT (datetime('now')), "
        "updated_at TEXT DEFAULT (datetime('now')))"
    )
    conn.execute(
        "INSERT INTO project (project_id, name, source_path, source_sha256, "
        "duration_ms, resolution, fps, codec, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "proj_test01",
            "Test Project",
            "/tmp/source.mp4",
            "abc123def456",
            300000,
            "1920x1080",
            30.0,
            "h264",
            "ready",
        ),
    )
    conn.commit()
    conn.close()
    return db_path


def _make_edl(
    segments: list[SegmentSpec] | None = None,
    source_sha256: str = "abc123def456",
    target_platform: str = "tiktok",
) -> EditDecisionList:
    """Build a valid EDL for testing."""
    if segments is None:
        segments = [
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=30000,
                output_start_ms=0,
                speed=1.0,
            ),
        ]
    return EditDecisionList(
        edit_id="edit_test01",
        project_id="proj_test01",
        name="Test Edit",
        source_sha256=source_sha256,
        target_platform=target_platform,
        segments=segments,
    )


# ============================================================
# TESTS
# ============================================================
class TestEDLCreation:
    """Test EDL model creation with valid and invalid data."""

    def test_valid_edl_all_fields(self, project_db: Path) -> None:
        """Create a valid EDL with all fields and verify validation passes."""
        seg = SegmentSpec(
            segment_id=1,
            source_start_ms=10000,
            source_end_ms=40000,
            output_start_ms=0,
            speed=1.0,
            transition_in=TransitionSpec(type="fade", duration_ms=500),
            transition_out=TransitionSpec(type="dissolve", duration_ms=300),
        )
        edl = _make_edl(segments=[seg])
        errors = validate_edl(edl, project_db)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_invalid_source_sha256(self, project_db: Path) -> None:
        """EDL with mismatched source_sha256 triggers error."""
        edl = _make_edl(source_sha256="wrong_hash")
        errors = validate_edl(edl, project_db)
        assert any("source_sha256 mismatch" in e for e in errors)

    def test_segment_ordering_validation(self, project_db: Path) -> None:
        """Segments out of output_start_ms order trigger error."""
        seg1 = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=10000,
            output_start_ms=5000,
            speed=1.0,
        )
        seg2 = SegmentSpec(
            segment_id=2,
            source_start_ms=10000,
            source_end_ms=20000,
            output_start_ms=0,
            speed=1.0,
        )
        edl = _make_edl(segments=[seg1, seg2])
        errors = validate_edl(edl, project_db)
        assert any("not ordered" in e for e in errors)

    def test_segment_overlap_detection(self, project_db: Path) -> None:
        """Overlapping segments without transitions trigger error."""
        seg1 = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=20000,
            output_start_ms=0,
            speed=1.0,
        )
        seg2 = SegmentSpec(
            segment_id=2,
            source_start_ms=20000,
            source_end_ms=40000,
            output_start_ms=10000,
            speed=1.0,
        )
        edl = _make_edl(segments=[seg1, seg2])
        errors = validate_edl(edl, project_db)
        assert any("overlap" in e.lower() for e in errors)

    def test_transition_duration_too_long(self, project_db: Path) -> None:
        """Transition > 50% of shorter segment triggers error."""
        seg1 = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=10000,
            output_start_ms=0,
            speed=1.0,
            transition_out=TransitionSpec(type="fade", duration_ms=2000),
        )
        seg2 = SegmentSpec(
            segment_id=2,
            source_start_ms=20000,
            source_end_ms=23000,
            output_start_ms=10000,
            speed=1.0,
        )
        edl = _make_edl(segments=[seg1, seg2])
        errors = validate_edl(edl, project_db)
        assert any("exceeds 50%" in e for e in errors)

    def test_speed_range_validation_pydantic(self) -> None:
        """Speed outside 0.25-4.0 raises pydantic validation error."""
        with pytest.raises(ValidationError):
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=10000,
                output_start_ms=0,
                speed=5.0,
            )
        with pytest.raises(ValidationError):
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=10000,
                output_start_ms=0,
                speed=0.1,
            )


class TestDurationComputation:
    """Test compute_total_duration with various segment configs."""

    def test_single_segment(self) -> None:
        """Single segment at 1x speed returns exact source duration."""
        segs = [
            SegmentSpec(
                segment_id=1,
                source_start_ms=0,
                source_end_ms=10000,
                output_start_ms=0,
                speed=1.0,
            ),
        ]
        assert compute_total_duration(segs) == 10000

    def test_multiple_segments_different_speeds(self) -> None:
        """Multiple segments at different speeds compute correctly."""
        seg1 = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=10000,
            output_start_ms=0,
            speed=2.0,
        )
        seg2 = SegmentSpec(
            segment_id=2,
            source_start_ms=10000,
            source_end_ms=30000,
            output_start_ms=5000,
            speed=0.5,
        )
        total = compute_total_duration([seg1, seg2])
        # seg1: 10000/2.0 = 5000ms, seg2: 20000/0.5 = 40000ms
        # seg2 starts at 5000, so total = 5000 + 40000 = 45000
        assert total == 45000

    def test_empty_segments(self) -> None:
        """Empty segment list returns 0."""
        assert compute_total_duration([]) == 0


class TestTransitionTypes:
    """Test transition type validation."""

    def test_all_valid_transition_types(self) -> None:
        """All valid transition types are accepted by TransitionSpec."""
        valid_types = [
            "fade",
            "crossfade",
            "wipe_left",
            "wipe_right",
            "wipe_up",
            "wipe_down",
            "slide_left",
            "slide_right",
            "dissolve",
            "zoom_in",
            "cut",
        ]
        for t in valid_types:
            spec = TransitionSpec(type=t, duration_ms=500)
            assert spec.type == t

    def test_invalid_transition_type(self) -> None:
        """Invalid transition type raises validation error."""
        with pytest.raises(ValidationError):
            TransitionSpec(type="invalid_type", duration_ms=500)


class TestSubModels:
    """Test sub-model creation and validation."""

    def test_caption_spec_all_styles(self) -> None:
        """CaptionSpec with all 4 styles."""
        for style in ("bold_centered", "word_highlight", "subtitle_bar", "karaoke"):
            spec = CaptionSpec(style=style)
            assert spec.style == style

    def test_crop_spec_mode_validation(self) -> None:
        """CropSpec mode validation: auto, manual, none are valid."""
        for mode in ("auto", "manual", "none"):
            spec = CropSpec(mode=mode)
            assert spec.mode == mode

    def test_crop_spec_invalid_mode(self) -> None:
        """Invalid crop mode raises validation error."""
        with pytest.raises(ValidationError):
            CropSpec(mode="invalid_mode")

    def test_crop_spec_invalid_aspect_ratio(self) -> None:
        """Invalid aspect ratio format raises validation error."""
        with pytest.raises(ValidationError):
            CropSpec(aspect_ratio="16x9")

    def test_empty_segments_rejected(self) -> None:
        """EDL with empty segments list is rejected by pydantic."""
        with pytest.raises(ValidationError):
            EditDecisionList(
                edit_id="edit_test01",
                project_id="proj_test01",
                name="Empty",
                source_sha256="abc",
                target_platform="tiktok",
                segments=[],
            )

    def test_metadata_spec_creation(self) -> None:
        """MetadataSpec with all fields creates successfully."""
        meta = MetadataSpec(
            title="Test Title",
            description="Test Description",
            hashtags=["#test", "#clip"],
            thumbnail_timestamp_ms=5000,
        )
        assert meta.title == "Test Title"
        assert meta.description == "Test Description"
        assert len(meta.hashtags) == 2
        assert meta.thumbnail_timestamp_ms == 5000
