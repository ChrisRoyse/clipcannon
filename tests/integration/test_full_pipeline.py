"""Full pipeline integration tests for ClipCannon.

Runs the complete pipeline on a real test video and verifies every output:
database tables, files on disk, provenance chain integrity.

Fixtures are defined in tests/integration/conftest.py. Expensive FFmpeg
operations run only once per module.

Requires: ffmpeg, numpy, scipy, Pillow, pydantic
Test video: testdata/2026-03-20 14-43-20.mp4 (209.9s, 2560x1440, 60fps)
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.db.schema import PIPELINE_STREAMS, init_project_directory
from clipcannon.pipeline.probe import run_probe
from clipcannon.provenance import verify_chain

TEST_VIDEO = Path(__file__).resolve().parent.parent.parent / "testdata" / "2026-03-20 14-43-20.mp4"

EXPECTED_DURATION_MS_MIN = 209000
EXPECTED_DURATION_MS_MAX = 210000
EXPECTED_RESOLUTION = "2560x1440"
EXPECTED_FPS = 60.0
EXPECTED_CODEC = "h264"


def _skip_if_no_video() -> None:
    """Skip test if test video is not available."""
    if not TEST_VIDEO.exists():
        pytest.skip(f"Test video not found: {TEST_VIDEO}")


# ============================================================
# INDIVIDUAL STAGE TESTS (verify shared results)
# ============================================================


class TestProbe:
    """Probe stage verification."""

    def test_probe_succeeds(self, probe_result) -> None:
        assert probe_result.success, f"Probe failed: {probe_result.error_message}"

    def test_probe_metadata(self, pipeline_project, probe_result) -> None:
        assert probe_result.success
        p = pipeline_project

        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT * FROM project WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert row is not None
        duration_ms = int(row["duration_ms"])
        assert EXPECTED_DURATION_MS_MIN <= duration_ms <= EXPECTED_DURATION_MS_MAX
        assert str(row["resolution"]) == EXPECTED_RESOLUTION
        assert float(row["fps"]) == EXPECTED_FPS
        assert str(row["codec"]) == EXPECTED_CODEC
        assert len(str(row["source_sha256"])) == 64


class TestAudioExtract:
    """Audio extraction verification."""

    def test_audio_extract_succeeds(self, audio_result) -> None:
        assert audio_result.success, f"Audio extract failed: {audio_result.error_message}"

    def test_audio_files_exist(self, pipeline_project, audio_result) -> None:
        assert audio_result.success
        stems_dir = pipeline_project["project_dir"] / "stems"
        for name in ("audio_16k.wav", "audio_original.wav"):
            f = stems_dir / name
            assert f.exists(), f"{name} not found"
            assert f.stat().st_size > 1_000_000, f"{name} too small"


class TestFrameExtract:
    """Frame extraction verification."""

    def test_frame_extract_succeeds(self, frame_result) -> None:
        assert frame_result.success, f"Frame extract failed: {frame_result.error_message}"

    def test_frame_count(self, pipeline_project, frame_result) -> None:
        assert frame_result.success
        frames = sorted((pipeline_project["project_dir"] / "frames").glob("frame_*.jpg"))
        assert 400 < len(frames) < 440


class TestFullPipeline:
    """Full pipeline verification (all stages run once)."""

    def test_all_stages_succeed(self, full_pipeline_results) -> None:
        for stage_name, result in full_pipeline_results.items():
            assert result.success, f"{stage_name} failed: {result.error_message}"

    def test_project_metadata(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            proj = fetch_one(conn, "SELECT * FROM project WHERE project_id = ?", (p["project_id"],))
        finally:
            conn.close()

        assert proj is not None
        assert EXPECTED_DURATION_MS_MIN <= int(proj["duration_ms"]) <= EXPECTED_DURATION_MS_MAX
        assert str(proj["status"]) == "ready"

    def test_audio_files_on_disk(self, pipeline_project, full_pipeline_results) -> None:
        stems_dir = pipeline_project["project_dir"] / "stems"
        for name in ("audio_16k.wav", "audio_original.wav"):
            assert (stems_dir / name).exists()
            assert (stems_dir / name).stat().st_size > 0

    def test_frames_on_disk(self, pipeline_project, full_pipeline_results) -> None:
        frames = sorted((pipeline_project["project_dir"] / "frames").glob("frame_*.jpg"))
        assert len(frames) > 400

    def test_storyboard_grids(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            grids = fetch_all(conn, "SELECT * FROM storyboard_grids WHERE project_id = ?", (p["project_id"],))
        finally:
            conn.close()

        assert len(grids) > 0
        from PIL import Image

        for grid in grids:
            grid_path = Path(str(grid["grid_path"]))
            assert grid_path.exists()
            assert Image.open(grid_path).size == (1044, 1044)

    def test_acoustic_data(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(conn, "SELECT * FROM acoustic WHERE project_id = ?", (p["project_id"],))
        finally:
            conn.close()
        assert len(rows) > 0
        assert rows[0]["avg_volume_db"] is not None

    def test_beats_data(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(conn, "SELECT * FROM beats WHERE project_id = ?", (p["project_id"],))
        finally:
            conn.close()
        assert len(rows) > 0

    def test_pacing_data(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(conn, "SELECT * FROM pacing WHERE project_id = ?", (p["project_id"],))
        finally:
            conn.close()
        assert len(rows) > 0
        for w in rows:
            assert w["words_per_minute"] is not None
            assert w["label"] is not None

    def test_content_safety(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(conn, "SELECT * FROM content_safety WHERE project_id = ?", (p["project_id"],))
        finally:
            conn.close()
        assert len(rows) > 0
        assert rows[0]["content_rating"] is not None

    def test_highlights(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(conn, "SELECT * FROM highlights WHERE project_id = ? ORDER BY score DESC", (p["project_id"],))
        finally:
            conn.close()
        assert len(rows) > 0
        for h in rows:
            assert float(h["score"]) >= 0
            assert h["reason"] is not None

    def test_stream_status(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(conn, "SELECT * FROM stream_status WHERE project_id = ?", (p["project_id"],))
        finally:
            conn.close()
        stream_map = {str(s["stream_name"]): str(s["status"]) for s in rows}
        for name in ("acoustic", "storyboards", "profanity", "highlights", "chronemic"):
            assert stream_map.get(name) == "completed", f"{name} not completed"

    def test_provenance_records(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(conn, "SELECT * FROM provenance WHERE project_id = ?", (p["project_id"],))
        finally:
            conn.close()
        assert len(rows) > 0
        for prov in rows:
            assert len(str(prov["chain_hash"])) == 64

    def test_provenance_chain_integrity(self, pipeline_project, full_pipeline_results) -> None:
        p = pipeline_project
        result = verify_chain(p["project_id"], p["db_path"])
        assert result.verified, f"Chain broken at {result.broken_at}: {result.issue}"


# ============================================================
# EDGE CASES (lightweight, no shared pipeline needed)
# ============================================================


class TestEdgeCases:
    """Edge case tests for pipeline error handling."""

    def setup_method(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.config = ClipCannonConfig.load()

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    async def test_nonexistent_video_errors_cleanly(self) -> None:
        from clipcannon.tools.project import clipcannon_project_create

        result = await clipcannon_project_create("test_bad", "/nonexistent/path/video.mp4")
        assert "error" in result
        assert result["error"]["code"] == "INVALID_PARAMETER"

    async def test_provenance_verify_fresh_project(self) -> None:
        project_id = "proj_fresh"
        init_project_directory(project_id, self.tmp_dir)
        db_path = self.tmp_dir / project_id / "analysis.db"

        result = verify_chain(project_id, db_path)
        assert result.verified is True
        assert result.total_records == 0

    async def test_provenance_tamper_detection(self) -> None:
        _skip_if_no_video()

        project_id = "proj_tamper"
        init_project_directory(project_id, self.tmp_dir)
        project_dir = self.tmp_dir / project_id
        db_path = project_dir / "analysis.db"

        source_video = project_dir / "source" / TEST_VIDEO.name
        shutil.copy2(str(TEST_VIDEO), str(source_video))

        conn = get_connection(db_path, enable_vec=False, dict_rows=False)
        try:
            conn.execute(
                """INSERT INTO project (
                    project_id, name, source_path, source_sha256,
                    duration_ms, resolution, fps, codec, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created')""",
                (project_id, "Tamper Test", str(source_video), "pending",
                 0, "unknown", 0, "unknown"),
            )
            for stream_name in PIPELINE_STREAMS:
                conn.execute(
                    "INSERT INTO stream_status (project_id, stream_name, status) "
                    "VALUES (?, ?, 'pending')",
                    (project_id, stream_name),
                )
            conn.commit()
        finally:
            conn.close()

        result = await run_probe(project_id, db_path, project_dir, self.config)
        assert result.success

        chain_before = verify_chain(project_id, db_path)
        assert chain_before.verified is True

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = conn.execute(
                "SELECT record_id FROM provenance WHERE project_id = ? "
                "ORDER BY timestamp_utc ASC",
                (project_id,),
            ).fetchone()
            record_id = row["record_id"] if isinstance(row, dict) else row[0]
            conn.execute(
                "UPDATE provenance SET output_sha256 = 'TAMPERED' WHERE record_id = ?",
                (record_id,),
            )
            conn.commit()
        finally:
            conn.close()

        chain_after = verify_chain(project_id, db_path)
        assert chain_after.verified is False, "Tamper should be detected"
