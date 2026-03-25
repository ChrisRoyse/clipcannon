"""Tests for Phase 2 dashboard endpoints.

Tests cover:
- GET /api/projects/{project_id}/timeline
- GET /api/projects/{project_id}/transcript-search
- GET /api/projects/{project_id}/enhanced
- GET /api/projects/{project_id}/edits
- GET /api/projects/{project_id}/edits/{edit_id}
- POST /api/projects/{project_id}/edits/{edit_id}/approve
- POST /api/projects/{project_id}/edits/{edit_id}/reject
- GET /api/projects/{project_id}/review/queue
- POST /api/projects/{project_id}/review/batch
- GET /api/projects/{project_id}/review/stats
- Missing project error handling
- Missing edit error handling
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from fastapi.testclient import TestClient

from clipcannon.dashboard.app import create_app


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture()
def dashboard_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create a real project DB with all required tables and data.

    Returns project_id.
    """
    project_id = "proj_dash_test"
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / project_id
    project_dir.mkdir(parents=True)
    db_path = project_dir / "analysis.db"

    # Set env var for dashboard routes
    monkeypatch.setenv("CLIPCANNON_PROJECTS_DIR", str(projects_dir))

    # Also patch the module-level PROJECTS_DIR in each route module
    from clipcannon.dashboard.routes import editing, review, timeline

    monkeypatch.setattr(timeline, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(editing, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(review, "PROJECTS_DIR", projects_dir)

    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS project (
            project_id TEXT PRIMARY KEY,
            name TEXT, source_path TEXT, source_sha256 TEXT,
            duration_ms INTEGER, resolution TEXT, fps REAL,
            codec TEXT, status TEXT DEFAULT 'ready',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS scenes (
            scene_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT, start_ms INTEGER, end_ms INTEGER,
            key_frame_path TEXT, key_frame_timestamp_ms INTEGER,
            visual_similarity_avg REAL, dominant_colors TEXT,
            shot_type TEXT, shot_type_confidence REAL, quality_avg REAL
        );

        CREATE TABLE IF NOT EXISTS speakers (
            speaker_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT, label TEXT, total_speaking_ms INTEGER,
            speaking_pct REAL
        );

        CREATE TABLE IF NOT EXISTS transcript_segments (
            segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT, start_ms INTEGER, end_ms INTEGER,
            text TEXT, speaker_id INTEGER, language TEXT,
            word_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS emotion_curve (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT, start_ms INTEGER, end_ms INTEGER,
            arousal REAL, valence REAL, energy REAL
        );

        CREATE TABLE IF NOT EXISTS topics (
            topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT, start_ms INTEGER, end_ms INTEGER,
            label TEXT, keywords TEXT, coherence_score REAL,
            semantic_density REAL
        );

        CREATE TABLE IF NOT EXISTS highlights (
            highlight_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT, start_ms INTEGER, end_ms INTEGER,
            type TEXT, score REAL, reason TEXT,
            emotion_score REAL, reaction_score REAL,
            semantic_score REAL, narrative_score REAL,
            visual_score REAL, quality_score REAL, speaker_score REAL
        );

        CREATE TABLE IF NOT EXISTS edits (
            edit_id TEXT PRIMARY KEY,
            project_id TEXT, name TEXT,
            status TEXT DEFAULT 'draft',
            target_platform TEXT, target_profile TEXT,
            edl_json TEXT, source_sha256 TEXT,
            total_duration_ms INTEGER, segment_count INTEGER,
            captions_enabled BOOLEAN DEFAULT TRUE,
            crop_mode TEXT DEFAULT 'auto',
            thumbnail_timestamp_ms INTEGER,
            metadata_title TEXT, metadata_description TEXT,
            metadata_hashtags TEXT, rejection_feedback TEXT,
            render_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS edit_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edit_id TEXT, segment_order INTEGER,
            source_start_ms INTEGER, source_end_ms INTEGER,
            output_start_ms INTEGER, speed REAL DEFAULT 1.0,
            transition_in_type TEXT, transition_in_duration_ms INTEGER,
            transition_out_type TEXT, transition_out_duration_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS renders (
            render_id TEXT PRIMARY KEY,
            edit_id TEXT, project_id TEXT,
            status TEXT DEFAULT 'pending', profile TEXT,
            output_path TEXT, output_sha256 TEXT,
            file_size_bytes INTEGER, duration_ms INTEGER,
            resolution TEXT, codec TEXT, thumbnail_path TEXT,
            render_duration_ms INTEGER, error_message TEXT,
            provenance_record_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );

        INSERT OR REPLACE INTO schema_version (version) VALUES (2);
    """)

    # Insert project
    conn.execute(
        "INSERT INTO project VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (project_id, "Dashboard Test", "/tmp/source.mp4", "hash123",
         300000, "1920x1080", 30.0, "h264", "ready"),
    )

    # Insert VUD data
    conn.execute(
        "INSERT INTO scenes (project_id, start_ms, end_ms, key_frame_path, "
        "key_frame_timestamp_ms, visual_similarity_avg, shot_type, quality_avg) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, 0, 10000, "/tmp/frame.jpg", 5000, 0.85, "medium", 0.9),
    )
    conn.execute(
        "INSERT INTO speakers (project_id, label, total_speaking_ms, speaking_pct) "
        "VALUES (?, ?, ?, ?)",
        (project_id, "Speaker A", 25000, 0.83),
    )
    conn.execute(
        "INSERT INTO transcript_segments "
        "(project_id, start_ms, end_ms, text, speaker_id, language, word_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, 0, 10000, "Hello world testing dashboard", 1, "en", 4),
    )
    conn.execute(
        "INSERT INTO highlights (project_id, start_ms, end_ms, type, score, reason) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, 5000, 15000, "insight", 0.9, "Great insight"),
    )

    # Insert edits
    edl_json = json.dumps({
        "segments": [{"source_start_ms": 0, "source_end_ms": 30000}],
    })
    conn.execute(
        "INSERT INTO edits (edit_id, project_id, name, status, target_platform, "
        "target_profile, edl_json, source_sha256, total_duration_ms, segment_count, "
        "metadata_title, metadata_description, metadata_hashtags) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("edit_dash_01", project_id, "Test Edit 1", "draft", "tiktok",
         "tiktok_vertical", edl_json, "hash123", 30000, 1,
         "Test Title", "Test Desc", '["#test"]'),
    )
    conn.execute(
        "INSERT INTO edits (edit_id, project_id, name, status, target_platform, "
        "target_profile, edl_json, source_sha256, total_duration_ms, segment_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("edit_dash_02", project_id, "Rendered Edit", "rendered", "tiktok",
         "tiktok_vertical", edl_json, "hash123", 30000, 1),
    )

    # Insert edit segments
    conn.execute(
        "INSERT INTO edit_segments (edit_id, segment_order, source_start_ms, "
        "source_end_ms, output_start_ms, speed) VALUES (?, ?, ?, ?, ?, ?)",
        ("edit_dash_01", 1, 0, 30000, 0, 1.0),
    )

    conn.commit()
    conn.close()

    return project_id


@pytest.fixture()
def client(dashboard_project: str) -> TestClient:
    """Create FastAPI TestClient."""
    app = create_app()
    return TestClient(app)


# ============================================================
# TESTS
# ============================================================
class TestTimelineEndpoints:
    """Test timeline and enhanced project endpoints."""

    def test_get_timeline(self, client: TestClient, dashboard_project: str) -> None:
        """GET /api/projects/{id}/timeline returns scene/speaker/emotion data."""
        resp = client.get(f"/api/projects/{dashboard_project}/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == dashboard_project
        assert "scenes" in data
        assert "speakers" in data
        assert "highlights" in data

    def test_transcript_search(self, client: TestClient, dashboard_project: str) -> None:
        """GET /api/projects/{id}/transcript-search with query."""
        resp = client.get(
            f"/api/projects/{dashboard_project}/transcript-search",
            params={"q": "Hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "Hello"
        assert "results" in data

    def test_enhanced_project(self, client: TestClient, dashboard_project: str) -> None:
        """GET /api/projects/{id}/enhanced returns VUD stats."""
        resp = client.get(f"/api/projects/{dashboard_project}/enhanced")
        assert resp.status_code == 200
        data = resp.json()
        assert "vud_summary" in data
        summary = data["vud_summary"]
        assert summary["speaker_count"] >= 1
        assert summary["total_scenes"] >= 1


class TestEditEndpoints:
    """Test edit CRUD endpoints."""

    def test_list_edits(self, client: TestClient, dashboard_project: str) -> None:
        """GET /api/projects/{id}/edits returns edit list."""
        resp = client.get(f"/api/projects/{dashboard_project}/edits")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 2

    def test_get_edit_detail(self, client: TestClient, dashboard_project: str) -> None:
        """GET /api/projects/{id}/edits/{edit_id} returns edit detail."""
        resp = client.get(
            f"/api/projects/{dashboard_project}/edits/edit_dash_01"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "edit" in data
        assert data["edit"]["edit_id"] == "edit_dash_01"
        assert "segments" in data

    def test_approve_edit(self, client: TestClient, dashboard_project: str) -> None:
        """POST /api/projects/{id}/edits/{edit_id}/approve changes status."""
        resp = client.post(
            f"/api/projects/{dashboard_project}/edits/edit_dash_01/approve"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "approved"

    def test_reject_edit_with_feedback(
        self, client: TestClient, dashboard_project: str
    ) -> None:
        """POST /api/projects/{id}/edits/{edit_id}/reject with feedback."""
        resp = client.post(
            f"/api/projects/{dashboard_project}/edits/edit_dash_02/reject",
            json={"feedback": "Needs better pacing"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "rejected"
        assert data["feedback"] == "Needs better pacing"


class TestReviewEndpoints:
    """Test review workflow endpoints."""

    def test_review_queue(self, client: TestClient, dashboard_project: str) -> None:
        """GET /api/projects/{id}/review/queue returns pending edits."""
        resp = client.get(f"/api/projects/{dashboard_project}/review/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "queue" in data
        assert "count" in data

    def test_batch_review(self, client: TestClient, dashboard_project: str) -> None:
        """POST /api/projects/{id}/review/batch processes multiple decisions."""
        resp = client.post(
            f"/api/projects/{dashboard_project}/review/batch",
            json=[
                {"edit_id": "edit_dash_01", "action": "approve"},
            ],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_review_stats(self, client: TestClient, dashboard_project: str) -> None:
        """GET /api/projects/{id}/review/stats returns counts."""
        resp = client.get(f"/api/projects/{dashboard_project}/review/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        stats = data["stats"]
        assert "total" in stats
        assert "approved" in stats
        assert "rejected" in stats
        assert "pending" in stats
        assert "rendered" in stats


class TestErrorHandling:
    """Test error handling for missing resources."""

    def test_missing_project_timeline(self, client: TestClient) -> None:
        """Missing project returns error, not 500."""
        resp = client.get("/api/projects/nonexistent_proj/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_missing_edit_detail(
        self, client: TestClient, dashboard_project: str
    ) -> None:
        """Missing edit returns error, not 500."""
        resp = client.get(
            f"/api/projects/{dashboard_project}/edits/nonexistent_edit"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
