"""Tests for the segment render cache.

Tests cover:
- Deterministic hash computation
- Hash sensitivity to speed, color, canvas changes
- segment_cache table creation and migration
"""

from __future__ import annotations

import sqlite3

import pytest

from clipcannon.editing.edl import (
    CanvasRegion,
    CanvasSpec,
    ColorSpec,
    MotionSpec,
    SegmentCanvasSpec,
    SegmentSpec,
    TransitionSpec,
)
from clipcannon.rendering.segment_hash import compute_segment_hash


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture()
def base_segment() -> SegmentSpec:
    """A minimal SegmentSpec for hash testing."""
    return SegmentSpec(
        segment_id=1,
        source_start_ms=0,
        source_end_ms=5000,
        output_start_ms=0,
        speed=1.0,
    )


@pytest.fixture()
def source_sha256() -> str:
    """A deterministic source hash for testing."""
    return "abc123def456" * 5 + "ab"


@pytest.fixture()
def profile_name() -> str:
    """A deterministic profile name for testing."""
    return "tiktok_vertical"


# ============================================================
# HASH DETERMINISM
# ============================================================
class TestComputeSegmentHashDeterministic:
    """Same inputs produce the same hash."""

    def test_same_inputs_same_hash(
        self,
        base_segment: SegmentSpec,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Identical inputs produce identical hashes."""
        hash1 = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
        )
        hash2 = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
        )
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_hash_is_hex_string(
        self,
        base_segment: SegmentSpec,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Hash output is a valid hex string."""
        h = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
        )
        # Should only contain hex characters
        assert all(c in "0123456789abcdef" for c in h)


# ============================================================
# HASH SENSITIVITY — SPEED
# ============================================================
class TestComputeSegmentHashChangesOnSpeed:
    """Changing speed produces a different hash."""

    def test_different_speed_different_hash(
        self,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Speed 1.0 vs 1.5 produce different hashes."""
        seg_normal = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
            speed=1.0,
        )
        seg_fast = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
            speed=1.5,
        )

        hash_normal = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_normal,
            profile_name=profile_name,
        )
        hash_fast = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_fast,
            profile_name=profile_name,
        )
        assert hash_normal != hash_fast


# ============================================================
# HASH SENSITIVITY — COLOR
# ============================================================
class TestComputeSegmentHashChangesOnColor:
    """Changing color produces a different hash."""

    def test_global_color_changes_hash(
        self,
        base_segment: SegmentSpec,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Adding global color grading changes the hash."""
        hash_no_color = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
        )
        hash_with_color = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
            global_color=ColorSpec(brightness=0.2, contrast=1.5),
        )
        assert hash_no_color != hash_with_color

    def test_per_segment_color_changes_hash(
        self,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Per-segment color override changes the hash."""
        seg_plain = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
        )
        seg_colored = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
            color=ColorSpec(saturation=2.0),
        )

        hash_plain = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_plain,
            profile_name=profile_name,
        )
        hash_colored = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_colored,
            profile_name=profile_name,
        )
        assert hash_plain != hash_colored

    def test_different_color_values_different_hashes(
        self,
        base_segment: SegmentSpec,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Different color values produce different hashes."""
        hash_bright = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
            global_color=ColorSpec(brightness=0.5),
        )
        hash_contrast = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
            global_color=ColorSpec(contrast=2.0),
        )
        assert hash_bright != hash_contrast


# ============================================================
# HASH SENSITIVITY — CANVAS
# ============================================================
class TestComputeSegmentHashChangesOnCanvas:
    """Changing canvas produces a different hash."""

    def test_global_canvas_changes_hash(
        self,
        base_segment: SegmentSpec,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Adding a global canvas spec changes the hash."""
        hash_no_canvas = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
        )
        canvas = CanvasSpec(
            enabled=True,
            canvas_width=1080,
            canvas_height=1920,
            regions=[
                CanvasRegion(
                    region_id="speaker",
                    source_x=0,
                    source_y=0,
                    source_width=1920,
                    source_height=1080,
                    output_x=0,
                    output_y=0,
                    output_width=1080,
                    output_height=1920,
                ),
            ],
        )
        hash_with_canvas = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name=profile_name,
            canvas=canvas,
        )
        assert hash_no_canvas != hash_with_canvas

    def test_per_segment_canvas_changes_hash(
        self,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Per-segment canvas override changes the hash."""
        seg_plain = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
        )
        seg_canvas = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
            canvas=SegmentCanvasSpec(
                background_color="#FF0000",
                regions=[
                    CanvasRegion(
                        region_id="screen",
                        source_x=0,
                        source_y=0,
                        source_width=1920,
                        source_height=1080,
                        output_x=0,
                        output_y=0,
                        output_width=1080,
                        output_height=608,
                    ),
                ],
            ),
        )

        hash_plain = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_plain,
            profile_name=profile_name,
        )
        hash_canvas = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_canvas,
            profile_name=profile_name,
        )
        assert hash_plain != hash_canvas

    def test_motion_changes_hash(
        self,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Adding motion effect changes the hash."""
        seg_static = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
        )
        seg_motion = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
            motion=MotionSpec(effect="zoom_in", start_scale=1.0, end_scale=1.3),
        )

        hash_static = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_static,
            profile_name=profile_name,
        )
        hash_motion = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_motion,
            profile_name=profile_name,
        )
        assert hash_static != hash_motion

    def test_transition_changes_hash(
        self,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Adding a transition changes the hash."""
        seg_no_trans = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
        )
        seg_trans = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
            transition_in=TransitionSpec(type="fade", duration_ms=500),
        )

        hash_no = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_no_trans,
            profile_name=profile_name,
        )
        hash_trans = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_trans,
            profile_name=profile_name,
        )
        assert hash_no != hash_trans

    def test_different_profile_changes_hash(
        self,
        base_segment: SegmentSpec,
        source_sha256: str,
    ) -> None:
        """Different encoding profile changes the hash."""
        hash_tiktok = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name="tiktok_vertical",
        )
        hash_youtube = compute_segment_hash(
            source_sha256=source_sha256,
            segment=base_segment,
            profile_name="youtube_4k",
        )
        assert hash_tiktok != hash_youtube

    def test_different_source_changes_hash(
        self,
        base_segment: SegmentSpec,
        profile_name: str,
    ) -> None:
        """Different source SHA-256 changes the hash."""
        hash_a = compute_segment_hash(
            source_sha256="a" * 64,
            segment=base_segment,
            profile_name=profile_name,
        )
        hash_b = compute_segment_hash(
            source_sha256="b" * 64,
            segment=base_segment,
            profile_name=profile_name,
        )
        assert hash_a != hash_b

    def test_different_time_range_changes_hash(
        self,
        source_sha256: str,
        profile_name: str,
    ) -> None:
        """Different source time ranges produce different hashes."""
        seg_early = SegmentSpec(
            segment_id=1,
            source_start_ms=0,
            source_end_ms=5000,
            output_start_ms=0,
        )
        seg_late = SegmentSpec(
            segment_id=1,
            source_start_ms=5000,
            source_end_ms=10000,
            output_start_ms=0,
        )

        hash_early = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_early,
            profile_name=profile_name,
        )
        hash_late = compute_segment_hash(
            source_sha256=source_sha256,
            segment=seg_late,
            profile_name=profile_name,
        )
        assert hash_early != hash_late


# ============================================================
# TABLE CREATION
# ============================================================
class TestCacheTableCreation:
    """Verify segment_cache table creation and migration."""

    def test_ensure_creates_table(self) -> None:
        """ensure_segment_cache_table creates the table in a fresh DB."""
        from clipcannon.rendering.renderer import ensure_segment_cache_table

        conn = sqlite3.connect(":memory:")
        # Table should not exist yet
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("SELECT 1 FROM segment_cache LIMIT 1")

        ensure_segment_cache_table(conn)

        # Table should now exist
        conn.execute("SELECT 1 FROM segment_cache LIMIT 1")

    def test_ensure_is_idempotent(self) -> None:
        """Calling ensure twice does not error."""
        from clipcannon.rendering.renderer import ensure_segment_cache_table

        conn = sqlite3.connect(":memory:")
        ensure_segment_cache_table(conn)
        ensure_segment_cache_table(conn)  # Second call should not raise

        # Can insert and read
        conn.execute(
            "INSERT INTO segment_cache "
            "(cache_hash, project_id, file_path, source_hash, "
            "segment_spec_json) VALUES (?, ?, ?, ?, ?)",
            ("h1", "proj_test", "/tmp/test.mp4", "sha_test", "{}"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT cache_hash FROM segment_cache"
        ).fetchone()
        assert row[0] == "h1"

    def test_table_has_correct_columns(self) -> None:
        """segment_cache table has all expected columns."""
        from clipcannon.rendering.renderer import ensure_segment_cache_table

        conn = sqlite3.connect(":memory:")
        ensure_segment_cache_table(conn)

        cursor = conn.execute("PRAGMA table_info(segment_cache)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "cache_hash",
            "project_id",
            "file_path",
            "source_hash",
            "segment_spec_json",
            "file_size_bytes",
            "created_at",
            "last_used_at",
        }
        assert expected == columns

    def test_schema_v2_includes_segment_cache(
        self, tmp_path: pytest.TempPathFactory,
    ) -> None:
        """migrate_to_v2 includes segment_cache table."""
        from clipcannon.db.schema import (
            _CORE_TABLES_SQL,
            _PHASE2_TABLES_SQL,
        )

        conn = sqlite3.connect(":memory:")
        conn.executescript(_CORE_TABLES_SQL)
        conn.executescript(_PHASE2_TABLES_SQL)
        conn.commit()

        # segment_cache should exist
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='segment_cache'"
        ).fetchone()
        assert row is not None
        assert row[0] == "segment_cache"
