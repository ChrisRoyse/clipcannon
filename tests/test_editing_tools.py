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

        -- Edit version history
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
    async def test_modify_rendering_rejected(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Cannot modify edit that is actively rendering."""
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
            "UPDATE edits SET status = 'rendering' WHERE edit_id = ?",
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

    async def test_modify_rendered_allowed(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Can modify a rendered edit — resets to draft."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Rendered Edit",
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
                "changes": {"name": "Modified After Render"},
            },
        )
        assert "error" not in modify_result


class TestEditVersionHistory:
    """Tests for edit version history (P0 iterative editing)."""

    @pytest.mark.asyncio()
    async def test_modify_creates_version(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Modifying an edit saves the previous state as a version."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Version Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        edit_id = str(create_result["edit_id"])

        modify_result = await dispatch_editing_tool(
            "clipcannon_modify_edit",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "changes": {"name": "Version Test Modified"},
            },
        )
        assert "error" not in modify_result

        # Verify version exists in DB
        projects_dir = tmp_path / "projects"
        db_file = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM edit_versions WHERE edit_id = ?",
            (edit_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["version_number"] == 1
        assert rows[0]["edit_id"] == edit_id
        assert rows[0]["edl_json"] is not None

    @pytest.mark.asyncio()
    async def test_version_number_increments(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Multiple modifications produce incrementing version numbers."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Increment Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        edit_id = str(create_result["edit_id"])

        for i in range(3):
            result = await dispatch_editing_tool(
                "clipcannon_modify_edit",
                {
                    "project_id": project_id,
                    "edit_id": edit_id,
                    "changes": {"name": f"Version {i + 1}"},
                },
            )
            assert "error" not in result

        projects_dir = tmp_path / "projects"
        db_file = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT version_number FROM edit_versions WHERE edit_id = ? "
            "ORDER BY version_number",
            (edit_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == 3
        assert [r["version_number"] for r in rows] == [1, 2, 3]

    @pytest.mark.asyncio()
    async def test_change_description_generated(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Version change description mentions what was modified."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Desc Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        edit_id = str(create_result["edit_id"])

        # Modify segments
        await dispatch_editing_tool(
            "clipcannon_modify_edit",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "changes": {
                    "segments": [
                        {"source_start_ms": 0, "source_end_ms": 15000},
                        {"source_start_ms": 20000, "source_end_ms": 30000},
                    ],
                },
            },
        )

        projects_dir = tmp_path / "projects"
        db_file = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT change_description FROM edit_versions WHERE edit_id = ? "
            "ORDER BY version_number DESC LIMIT 1",
            (edit_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        desc = row["change_description"].lower()
        assert "segment" in desc

    @pytest.mark.asyncio()
    async def test_edit_history_returns_versions(
        self, project_setup: str,
    ) -> None:
        """edit_history returns all versions including current."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "History Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        edit_id = str(create_result["edit_id"])

        # Modify twice
        for i in range(2):
            await dispatch_editing_tool(
                "clipcannon_modify_edit",
                {
                    "project_id": project_id,
                    "edit_id": edit_id,
                    "changes": {"name": f"History v{i + 1}"},
                },
            )

        history_result = await dispatch_editing_tool(
            "clipcannon_edit_history",
            {"project_id": project_id, "edit_id": edit_id},
        )
        assert "error" not in history_result
        assert history_result["version_count"] == 2

        versions = history_result["versions"]
        # First entry is current (version 0)
        assert versions[0]["version_number"] == 0
        assert versions[0]["change_description"] == "Current state"
        # Then versions in descending order
        assert versions[1]["version_number"] == 2
        assert versions[2]["version_number"] == 1

    @pytest.mark.asyncio()
    async def test_revert_edit_restores_state(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Reverting to version 1 restores the original name."""
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
        assert "error" not in create_result
        edit_id = str(create_result["edit_id"])

        # Modify name
        await dispatch_editing_tool(
            "clipcannon_modify_edit",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "changes": {"name": "Changed Name"},
            },
        )

        # Revert to version 1 (the original state)
        revert_result = await dispatch_editing_tool(
            "clipcannon_revert_edit",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "version_number": 1,
            },
        )
        assert "error" not in revert_result
        assert revert_result["reverted_to_version"] == 1
        assert revert_result["name"] == "Original Name"

        # Verify in DB
        projects_dir = tmp_path / "projects"
        db_file = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT name, status FROM edits WHERE edit_id = ?",
            (edit_id,),
        ).fetchone()
        conn.close()

        assert row["name"] == "Original Name"
        assert row["status"] == "draft"

    @pytest.mark.asyncio()
    async def test_revert_creates_version(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Reverting creates a new version preserving the pre-revert state."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Revert Version Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        edit_id = str(create_result["edit_id"])

        # Modify to create version 1
        await dispatch_editing_tool(
            "clipcannon_modify_edit",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "changes": {"name": "After Modify"},
            },
        )

        # Revert to version 1 -- should create version 2
        revert_result = await dispatch_editing_tool(
            "clipcannon_revert_edit",
            {
                "project_id": project_id,
                "edit_id": edit_id,
                "version_number": 1,
            },
        )
        assert "error" not in revert_result
        assert revert_result["saved_current_as_version"] == 2

        # Verify version 2 exists and has the pre-revert state
        projects_dir = tmp_path / "projects"
        db_file = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT version_number, change_description FROM edit_versions "
            "WHERE edit_id = ? ORDER BY version_number",
            (edit_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0]["version_number"] == 1
        assert rows[1]["version_number"] == 2
        assert "revert" in rows[1]["change_description"].lower()


class TestEditBranching:
    """Tests for edit branching (P4 iterative editing)."""

    @pytest.mark.asyncio()
    async def test_branch_creates_new_edit(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Branching creates a new edit with parent_edit_id set."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Branch Source",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        source_edit_id = str(create_result["edit_id"])

        branch_result = await dispatch_editing_tool(
            "clipcannon_branch_edit",
            {
                "project_id": project_id,
                "edit_id": source_edit_id,
                "branch_name": "instagram",
                "target_platform": "instagram_reels",
            },
        )
        assert "error" not in branch_result, f"Got error: {branch_result}"
        assert branch_result["parent_edit_id"] == source_edit_id
        assert branch_result["edit_id"] != source_edit_id

        # Verify in DB
        projects_dir = tmp_path / "projects"
        db_file = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT parent_edit_id, branch_name FROM edits WHERE edit_id = ?",
            (str(branch_result["edit_id"]),),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["parent_edit_id"] == source_edit_id
        assert row["branch_name"] == "instagram"

    @pytest.mark.asyncio()
    async def test_branch_copies_segments(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Branched edit copies all segments from the source."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Multi-Segment",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 10000},
                    {"source_start_ms": 15000, "source_end_ms": 25000},
                ],
            },
        )
        assert "error" not in create_result
        source_edit_id = str(create_result["edit_id"])

        branch_result = await dispatch_editing_tool(
            "clipcannon_branch_edit",
            {
                "project_id": project_id,
                "edit_id": source_edit_id,
                "branch_name": "youtube",
                "target_platform": "youtube_shorts",
            },
        )
        assert "error" not in branch_result
        assert branch_result["segment_count"] == 2

        # Verify segment rows exist in DB
        projects_dir = tmp_path / "projects"
        db_file = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM edit_segments WHERE edit_id = ? ORDER BY segment_order",
            (str(branch_result["edit_id"]),),
        ).fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0]["source_start_ms"] == 0
        assert rows[0]["source_end_ms"] == 10000
        assert rows[1]["source_start_ms"] == 15000
        assert rows[1]["source_end_ms"] == 25000

    @pytest.mark.asyncio()
    async def test_branch_has_new_platform(
        self, project_setup: str
    ) -> None:
        """Branched edit has the new target platform."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Platform Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        source_edit_id = str(create_result["edit_id"])

        branch_result = await dispatch_editing_tool(
            "clipcannon_branch_edit",
            {
                "project_id": project_id,
                "edit_id": source_edit_id,
                "branch_name": "reels",
                "target_platform": "instagram_reels",
            },
        )
        assert "error" not in branch_result
        assert branch_result["target_platform"] == "instagram_reels"
        assert branch_result["target_profile"] == "instagram_reels"

    @pytest.mark.asyncio()
    async def test_list_branches_includes_root_and_branch(
        self, project_setup: str
    ) -> None:
        """list_branches returns both root and branched edits."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "List Branch Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        root_id = str(create_result["edit_id"])

        # Create a branch
        branch_result = await dispatch_editing_tool(
            "clipcannon_branch_edit",
            {
                "project_id": project_id,
                "edit_id": root_id,
                "branch_name": "facebook_variant",
                "target_platform": "facebook",
            },
        )
        assert "error" not in branch_result

        # List branches
        list_result = await dispatch_editing_tool(
            "clipcannon_list_branches",
            {"project_id": project_id, "edit_id": root_id},
        )
        assert "error" not in list_result
        assert list_result["branch_count"] == 2
        assert list_result["root_edit_id"] == root_id

        branch_ids = [b["edit_id"] for b in list_result["branches"]]
        assert root_id in branch_ids
        assert str(branch_result["edit_id"]) in branch_ids

    @pytest.mark.asyncio()
    async def test_branch_name_stored(
        self, project_setup: str, tmp_path: Path
    ) -> None:
        """Branch name is correctly stored in the database."""
        project_id = project_setup
        create_result = await dispatch_editing_tool(
            "clipcannon_create_edit",
            {
                "project_id": project_id,
                "name": "Branch Name Test",
                "target_platform": "tiktok",
                "segments": [
                    {"source_start_ms": 0, "source_end_ms": 30000},
                ],
            },
        )
        assert "error" not in create_result
        source_edit_id = str(create_result["edit_id"])

        branch_result = await dispatch_editing_tool(
            "clipcannon_branch_edit",
            {
                "project_id": project_id,
                "edit_id": source_edit_id,
                "branch_name": "shorts_variant",
                "target_platform": "youtube_shorts",
            },
        )
        assert "error" not in branch_result

        # Check DB directly
        projects_dir = tmp_path / "projects"
        db_file = projects_dir / project_id / "analysis.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT branch_name FROM edits WHERE edit_id = ?",
            (str(branch_result["edit_id"]),),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["branch_name"] == "shorts_variant"
