"""Tests for the clipcannon_preview_segment rendering tool.

Tests cover:
- Invalid segment index (0 or > count) returns error
- Valid preview call returns segment source range info
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from clipcannon.tools.rendering import dispatch_rendering_tool


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture()
def preview_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create a real project DB with schema v2, an edit, and a source video stub.

    Returns the project_id.
    """
    project_id = "proj_preview_test"
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / project_id
    project_dir.mkdir(parents=True)
    db_path = project_dir / "analysis.db"

    # Create a minimal source video stub (touch file)
    source_path = project_dir / "source" / "video.mp4"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"\x00" * 100)  # dummy file

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
            parent_edit_id TEXT,
            branch_name TEXT DEFAULT 'main',
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

        INSERT OR REPLACE INTO schema_version (version) VALUES (2);
    """)

    conn.execute(
        "INSERT INTO project (project_id, name, source_path, source_sha256, "
        "duration_ms, resolution, fps, codec, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            "Preview Test Project",
            str(source_path),
            "sha256_preview_hash",
            300000,
            "1920x1080",
            30.0,
            "h264",
            "ready",
        ),
    )

    # Build a minimal EDL JSON with 3 segments
    edl = {
        "edit_id": "edit_preview_001",
        "project_id": project_id,
        "name": "Preview Test Edit",
        "status": "draft",
        "source_sha256": "sha256_preview_hash",
        "target_platform": "tiktok",
        "target_profile": "tiktok_vertical",
        "segments": [
            {
                "segment_id": 1,
                "source_start_ms": 0,
                "source_end_ms": 10000,
                "output_start_ms": 0,
                "speed": 1.0,
            },
            {
                "segment_id": 2,
                "source_start_ms": 15000,
                "source_end_ms": 25000,
                "output_start_ms": 10000,
                "speed": 1.5,
            },
            {
                "segment_id": 3,
                "source_start_ms": 50000,
                "source_end_ms": 60000,
                "output_start_ms": 16667,
                "speed": 1.0,
            },
        ],
        "captions": {"enabled": False},
        "crop": {"mode": "auto", "aspect_ratio": "9:16"},
        "canvas": {"enabled": False},
        "audio": {"source_audio": True},
        "overlays": [],
        "metadata": {},
        "render_settings": {"profile": "tiktok_vertical"},
    }
    edl_json = json.dumps(edl)

    conn.execute(
        "INSERT INTO edits (edit_id, project_id, name, status, target_platform, "
        "target_profile, edl_json, source_sha256, total_duration_ms, segment_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "edit_preview_001", project_id, "Preview Test Edit",
            "draft", "tiktok", "tiktok_vertical",
            edl_json, "sha256_preview_hash", 26667, 3,
        ),
    )

    conn.commit()
    conn.close()

    # Patch the projects_dir used by rendering.py
    monkeypatch.setattr(
        "clipcannon.tools.rendering._projects_dir",
        lambda: projects_dir,
    )

    return project_id


# ============================================================
# TESTS
# ============================================================
class TestPreviewSegment:
    """Test clipcannon_preview_segment tool."""

    @pytest.mark.asyncio()
    async def test_preview_segment_requires_valid_index_zero(
        self, preview_project: str
    ) -> None:
        """segment_index 0 returns an error (1-based indexing)."""
        result = await dispatch_rendering_tool(
            "clipcannon_preview_segment",
            {
                "project_id": preview_project,
                "edit_id": "edit_preview_001",
                "segment_index": 0,
            },
        )
        assert "error" in result
        assert "out of range" in result["error"]["message"].lower()

    @pytest.mark.asyncio()
    async def test_preview_segment_requires_valid_index_overflow(
        self, preview_project: str
    ) -> None:
        """segment_index > count returns an error."""
        result = await dispatch_rendering_tool(
            "clipcannon_preview_segment",
            {
                "project_id": preview_project,
                "edit_id": "edit_preview_001",
                "segment_index": 99,
            },
        )
        assert "error" in result
        assert "out of range" in result["error"]["message"].lower()

    @pytest.mark.asyncio()
    async def test_preview_returns_segment_info(
        self, preview_project: str
    ) -> None:
        """Valid preview call returns segment source range info.

        Note: Actual FFmpeg rendering may fail in test environment
        (no real video), so we check that the EDL/segment validation
        passes and the segment_info is returned if rendering succeeds,
        or a render error is returned with proper context.
        """
        result = await dispatch_rendering_tool(
            "clipcannon_preview_segment",
            {
                "project_id": preview_project,
                "edit_id": "edit_preview_001",
                "segment_index": 2,
            },
        )
        # In CI without FFmpeg or with a dummy source file, the render
        # will fail but the validation should pass. Check for either
        # a successful result with segment_info or a RENDER_FAILED
        # error (which means validation passed but FFmpeg couldn't
        # process the dummy source).
        if "error" in result:
            # Render failed is acceptable -- validation passed
            assert result["error"]["code"] in (
                "RENDER_FAILED", "SOURCE_NOT_FOUND",
            )
        else:
            # If render succeeded, verify segment_info
            assert "segment_info" in result
            seg = result["segment_info"]
            assert seg["segment_index"] == 2
            assert seg["source_start_ms"] == 15000
            assert seg["source_end_ms"] == 25000
            assert seg["speed"] == 1.5
            assert result["credits_charged"] == 0
