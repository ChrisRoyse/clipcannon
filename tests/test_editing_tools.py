"""Tests for the MCP editing tools.

Tests cover:
- clipcannon_create_edit with valid segments
- Edit segments stored in DB
- Auto-captioning from transcript
- Non-existent project error
- Out-of-range segment validation error
- clipcannon_modify_edit changes name
- Modify non-draft edit rejected
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from clipcannon.tools.editing import (
    dispatch_editing_tool,
)


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture()
def project_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create a real project DB with schema v2 and VUD data.

    Returns the project_id.
    """
    project_id = "proj_edit_test"
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

        -- Phase 2 tables
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

        INSERT OR REPLACE INTO schema_version (version) VALUES (2);
    """)

    conn.execute(
        "INSERT INTO project (project_id, name, source_path, source_sha256, "
        "duration_ms, resolution, fps, codec, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            "Test Edit Project",
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
        (project_id, 0, 30000, "This is a test transcript for editing tools", 1, "en", 8),
    )
    seg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    words = [
        ("This", 0, 500),
        ("is", 600, 900),
        ("a", 1000, 1200),
        ("test", 1300, 1800),
        ("transcript", 2000, 3000),
        ("for", 3100, 3400),
        ("editing", 3500, 4200),
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
# TESTS
# ============================================================
class TestCreateEdit:
    """Test clipcannon_create_edit tool."""

    @pytest.mark.asyncio()
    async def test_create_edit_valid(self, project_setup: str, tmp_path: Path) -> None:
        """Create edit with valid segments stores in DB."""
        project_id = project_setup
        result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Test Clip 1",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in result, f"Got error: {result}"
        assert result["status"] == "draft"
        assert result["segment_count"] == 1
        assert result["total_duration_ms"] == 30000
        assert "edit_id" in result

    @pytest.mark.asyncio()
    async def test_create_edit_segments_in_db(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Created edit stores segment rows in edit_segments table."""
        project_id = project_setup
        result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Segments Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 10000},
                    {"source_start_ms": 15000, "source_end_ms": 25000},
                ],
            },
        )
        assert "error" not in result
        edit_id = result["edit_id"]

        projects_dir = tmp_path / "projects"
        db_path = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM edit_segments WHERE edit_id = ? ORDER BY segment_order",
            (edit_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0]["source_start_ms"] == 0
        assert rows[0]["source_end_ms"] == 10000
        assert rows[1]["source_start_ms"] == 15000
        assert rows[1]["source_end_ms"] == 25000

    @pytest.mark.asyncio()
    async def test_create_edit_with_captions(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Create edit with captions enabled auto-chunks from transcript."""
        project_id = project_setup
        result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Caption Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 10000},
                ],
                "captions": {"enabled": True, "style": "bold_centered"},
            },
        )
        assert "error" not in result
        assert result["captions_enabled"] is True
        assert result["caption_chunks"] >= 0

    @pytest.mark.asyncio()
    async def test_create_edit_nonexistent_project(
        self, project_setup: str
    ) -> None:
        """Non-existent project returns error."""
        result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": "nonexistent_project",
                "name": "Fail",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 10000},
                ],
            },
        )
        assert "error" in result

    @pytest.mark.asyncio()
    async def test_create_edit_out_of_range(
        self, project_setup: str
    ) -> None:
        """Segments beyond source duration trigger validation error."""
        project_id = project_setup
        result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Out of range",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 500000},
                ],
            },
        )
        assert "error" in result


class TestModifyEdit:
    """Test clipcannon_modify_edit tool."""

    @pytest.mark.asyncio()
    async def test_modify_name(
        self, project_setup: str
    ) -> None:
        """Modify edit name updates DB."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Original Name",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        edit_id = create_result["edit_id"]

        modify_result = await dispatch_editing_tool(
            "clipcannon_modify_edit",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "changes": {"name": "Updated Name"},
            },
        )
        assert "error" not in modify_result
        assert "name" in modify_result["updated_fields"]

    @pytest.mark.asyncio()
    async def test_modify_non_draft_rejected(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Cannot modify edit that is not in 'draft' status."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "To Approve",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        edit_id = create_result["edit_id"]

        projects_dir = tmp_path / "projects"
        db_path = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE edits SET status = 'rendered' WHERE edit_id = ?",
            (edit_id,),
        )
        conn.commit()
        conn.close()

        modify_result = await dispatch_editing_tool(
            "clipcannon_modify_edit",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "changes": {"name": "Should Fail"},
            },
        )
        assert "error" in modify_result
