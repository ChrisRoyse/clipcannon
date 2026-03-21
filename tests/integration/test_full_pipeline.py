"""Full pipeline integration tests for ClipCannon.

Runs the complete pipeline on a real test video and verifies every output:
database tables, files on disk, provenance chain integrity.

Uses module-scoped fixtures so that expensive FFmpeg operations
(probe, audio extract, frame extract, acoustic, storyboard, etc.)
run only once. All test methods verify the shared output.

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
from clipcannon.db.schema import init_project_directory, PIPELINE_STREAMS
from clipcannon.pipeline.acoustic import run_acoustic
from clipcannon.pipeline.chronemic import run_chronemic
from clipcannon.pipeline.finalize import run_finalize
from clipcannon.pipeline.frame_extract import run_frame_extract
from clipcannon.pipeline.highlights import run_highlights
from clipcannon.pipeline.audio_extract import run_audio_extract
from clipcannon.pipeline.probe import run_probe
from clipcannon.pipeline.profanity import run_profanity
from clipcannon.pipeline.storyboard import run_storyboard
from clipcannon.provenance import verify_chain

# Path to the real test video
TEST_VIDEO = Path(__file__).resolve().parent.parent.parent / "testdata" / "2026-03-20 14-43-20.mp4"

# Expected metadata ranges
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
# MODULE-SCOPED FIXTURES: run the pipeline once, share results
# ============================================================


@pytest.fixture(scope="module")
def pipeline_project(tmp_path_factory):
    """Set up project, run probe + audio + frame extract once for the module.

    Returns a dict with project_id, db_path, project_dir, config, and
    the StageResult for each pipeline stage.
    """
    _skip_if_no_video()

    base_dir = tmp_path_factory.mktemp("full_pipeline")
    project_id = "proj_inttest"
    project_dir = base_dir / project_id
    config = ClipCannonConfig.load()

    init_project_directory(project_id, base_dir)
    db_path = project_dir / "analysis.db"

    # Copy test video to project source dir
    source_dir = project_dir / "source"
    source_video = source_dir / TEST_VIDEO.name
    shutil.copy2(str(TEST_VIDEO), str(source_video))

    # Insert initial project record
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        conn.execute(
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created')""",
            (
                project_id, "Integration Test",
                str(source_video), "pending",
                0, "unknown", 0, "unknown",
            ),
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

    return {
        "project_id": project_id,
        "db_path": db_path,
        "project_dir": project_dir,
        "config": config,
    }


@pytest.fixture(scope="module")
def probe_result(pipeline_project):
    """Run probe once for the module."""
    import asyncio
    p = pipeline_project
    result = asyncio.run(run_probe(
        p["project_id"], p["db_path"], p["project_dir"], p["config"],
    ))
    return result


@pytest.fixture(scope="module")
def audio_result(pipeline_project, probe_result):
    """Run audio extract once (depends on probe)."""
    import asyncio
    assert probe_result.success, f"Probe failed: {probe_result.error_message}"
    p = pipeline_project
    return asyncio.run(run_audio_extract(
        p["project_id"], p["db_path"], p["project_dir"], p["config"],
    ))


@pytest.fixture(scope="module")
def frame_result(pipeline_project, probe_result):
    """Run frame extract once (depends on probe)."""
    import asyncio
    assert probe_result.success, f"Probe failed: {probe_result.error_message}"
    p = pipeline_project
    return asyncio.run(run_frame_extract(
        p["project_id"], p["db_path"], p["project_dir"], p["config"],
    ))


@pytest.fixture(scope="module")
def full_pipeline_results(pipeline_project, probe_result, audio_result, frame_result):
    """Run the remaining non-model stages once, return all results."""
    import asyncio
    assert probe_result.success
    assert audio_result.success
    assert frame_result.success

    p = pipeline_project
    pid, db, pdir, cfg = p["project_id"], p["db_path"], p["project_dir"], p["config"]

    acoustic_r = asyncio.run(run_acoustic(pid, db, pdir, cfg))
    storyboard_r = asyncio.run(run_storyboard(pid, db, pdir, cfg))
    profanity_r = asyncio.run(run_profanity(pid, db, pdir, cfg))
    chronemic_r = asyncio.run(run_chronemic(pid, db, pdir, cfg))
    highlights_r = asyncio.run(run_highlights(pid, db, pdir, cfg))
    finalize_r = asyncio.run(run_finalize(pid, db, pdir, cfg))

    return {
        "probe": probe_result,
        "audio": audio_result,
        "frame": frame_result,
        "acoustic": acoustic_r,
        "storyboard": storyboard_r,
        "profanity": profanity_r,
        "chronemic": chronemic_r,
        "highlights": highlights_r,
        "finalize": finalize_r,
    }


# ============================================================
# INDIVIDUAL STAGE TESTS (verify shared results)
# ============================================================


class TestProbe:
    """Probe stage verification."""

    def test_probe_succeeds(self, probe_result) -> None:
        """Probe stage extracts correct metadata from the test video."""
        assert probe_result.success, f"Probe failed: {probe_result.error_message}"

    def test_probe_metadata(self, pipeline_project, probe_result) -> None:
        """Probe populates project table with correct values."""
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
        assert EXPECTED_DURATION_MS_MIN <= duration_ms <= EXPECTED_DURATION_MS_MAX, (
            f"Duration {duration_ms}ms outside expected range"
        )
        assert str(row["resolution"]) == EXPECTED_RESOLUTION
        assert float(row["fps"]) == EXPECTED_FPS
        assert str(row["codec"]) == EXPECTED_CODEC
        assert row["source_sha256"] is not None
        assert len(str(row["source_sha256"])) == 64


class TestAudioExtract:
    """Audio extraction verification."""

    def test_audio_extract_succeeds(self, audio_result) -> None:
        """Audio extraction produces both WAV files."""
        assert audio_result.success, f"Audio extract failed: {audio_result.error_message}"

    def test_audio_files_exist(self, pipeline_project, audio_result) -> None:
        """WAV files are present and have content."""
        assert audio_result.success
        stems_dir = pipeline_project["project_dir"] / "stems"
        audio_16k = stems_dir / "audio_16k.wav"
        audio_orig = stems_dir / "audio_original.wav"

        assert audio_16k.exists(), "audio_16k.wav not found"
        assert audio_orig.exists(), "audio_original.wav not found"
        assert audio_16k.stat().st_size > 1_000_000, "audio_16k.wav too small"
        assert audio_orig.stat().st_size > 1_000_000, "audio_original.wav too small"


class TestFrameExtract:
    """Frame extraction verification."""

    def test_frame_extract_succeeds(self, frame_result) -> None:
        """Frame extraction produces expected number of JPEG frames."""
        assert frame_result.success, f"Frame extract failed: {frame_result.error_message}"

    def test_frame_count(self, pipeline_project, frame_result) -> None:
        """Frame count is in expected range for 210s video at 2fps."""
        assert frame_result.success
        frames_dir = pipeline_project["project_dir"] / "frames"
        frames = sorted(frames_dir.glob("frame_*.jpg"))

        assert len(frames) > 400, f"Too few frames: {len(frames)}"
        assert len(frames) < 440, f"Too many frames: {len(frames)}"
        assert frames[0].stat().st_size > 0
        assert frames[-1].stat().st_size > 0


class TestFullPipeline:
    """Full pipeline verification (all stages run once)."""

    def test_all_stages_succeed(self, full_pipeline_results) -> None:
        """Every stage in the pipeline completes successfully."""
        for stage_name, result in full_pipeline_results.items():
            assert result.success, f"{stage_name} failed: {result.error_message}"

    def test_project_metadata(self, pipeline_project, full_pipeline_results) -> None:
        """Project table has correct metadata after full pipeline."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            proj = fetch_one(
                conn,
                "SELECT * FROM project WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert proj is not None
        assert EXPECTED_DURATION_MS_MIN <= int(proj["duration_ms"]) <= EXPECTED_DURATION_MS_MAX
        assert str(proj["resolution"]) == EXPECTED_RESOLUTION
        assert float(proj["fps"]) == EXPECTED_FPS
        assert str(proj["status"]) == "ready"

    def test_audio_files_on_disk(self, pipeline_project, full_pipeline_results) -> None:
        """Audio WAV files exist on disk after pipeline."""
        stems_dir = pipeline_project["project_dir"] / "stems"
        assert (stems_dir / "audio_16k.wav").exists()
        assert (stems_dir / "audio_original.wav").exists()
        assert (stems_dir / "audio_16k.wav").stat().st_size > 0
        assert (stems_dir / "audio_original.wav").stat().st_size > 0

    def test_frames_on_disk(self, pipeline_project, full_pipeline_results) -> None:
        """Extracted JPEG frames exist on disk."""
        frames = sorted((pipeline_project["project_dir"] / "frames").glob("frame_*.jpg"))
        assert len(frames) > 400

    def test_storyboard_grids(self, pipeline_project, full_pipeline_results) -> None:
        """Storyboard grids are present in DB and on disk with correct dimensions."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            grids = fetch_all(
                conn,
                "SELECT * FROM storyboard_grids WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert len(grids) > 0, "No storyboard grids in database"
        for grid in grids:
            grid_path = Path(str(grid["grid_path"]))
            assert grid_path.exists(), f"Grid file missing: {grid_path}"
            from PIL import Image
            img = Image.open(grid_path)
            assert img.size == (1044, 1044), f"Grid size wrong: {img.size}"

    def test_acoustic_data(self, pipeline_project, full_pipeline_results) -> None:
        """Acoustic analysis data is stored in the database."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            acoustic = fetch_all(
                conn,
                "SELECT * FROM acoustic WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert len(acoustic) > 0, "No acoustic data"
        assert acoustic[0]["avg_volume_db"] is not None
        assert acoustic[0]["dynamic_range_db"] is not None

    def test_beats_data(self, pipeline_project, full_pipeline_results) -> None:
        """Beats data is stored in the database."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            beats = fetch_all(
                conn,
                "SELECT * FROM beats WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()
        assert len(beats) > 0, "No beats data"

    def test_pacing_data(self, pipeline_project, full_pipeline_results) -> None:
        """Pacing data has required fields."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            pacing = fetch_all(
                conn,
                "SELECT * FROM pacing WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert len(pacing) > 0, "No pacing data"
        for window in pacing:
            assert window["start_ms"] is not None
            assert window["end_ms"] is not None
            assert window["words_per_minute"] is not None
            assert window["label"] is not None

    def test_content_safety(self, pipeline_project, full_pipeline_results) -> None:
        """Content safety rating is computed."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            safety = fetch_all(
                conn,
                "SELECT * FROM content_safety WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert len(safety) > 0, "No content safety data"
        assert safety[0]["content_rating"] is not None

    def test_highlights(self, pipeline_project, full_pipeline_results) -> None:
        """Highlights are scored and stored."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            highlights = fetch_all(
                conn,
                "SELECT * FROM highlights WHERE project_id = ? ORDER BY score DESC",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert len(highlights) > 0, "No highlights"
        for h in highlights:
            assert float(h["score"]) >= 0
            assert h["type"] is not None
            assert h["reason"] is not None

    def test_stream_status(self, pipeline_project, full_pipeline_results) -> None:
        """All expected streams are marked completed."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            streams = fetch_all(
                conn,
                "SELECT * FROM stream_status WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert len(streams) > 0, "No stream status entries"
        stream_map = {str(s["stream_name"]): str(s["status"]) for s in streams}
        assert stream_map.get("acoustic") == "completed"
        assert stream_map.get("storyboards") == "completed"
        assert stream_map.get("profanity") == "completed"
        assert stream_map.get("highlights") == "completed"
        assert stream_map.get("chronemic") == "completed"

    def test_provenance_records(self, pipeline_project, full_pipeline_results) -> None:
        """Provenance records have valid chain hashes."""
        p = pipeline_project
        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            provenance = fetch_all(
                conn,
                "SELECT * FROM provenance WHERE project_id = ? ORDER BY timestamp_utc",
                (p["project_id"],),
            )
        finally:
            conn.close()

        assert len(provenance) > 0, "No provenance records"
        for prov in provenance:
            assert prov["chain_hash"] is not None
            assert len(str(prov["chain_hash"])) == 64

    def test_provenance_chain_integrity(self, pipeline_project, full_pipeline_results) -> None:
        """Provenance chain verifies end-to-end."""
        p = pipeline_project
        chain_result = verify_chain(p["project_id"], p["db_path"])
        assert chain_result.verified, (
            f"Provenance chain broken at {chain_result.broken_at}: "
            f"{chain_result.issue}"
        )

        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            provenance = fetch_all(
                conn,
                "SELECT * FROM provenance WHERE project_id = ?",
                (p["project_id"],),
            )
        finally:
            conn.close()
        assert chain_result.total_records == len(provenance)


# ============================================================
# EDGE CASES (these are lightweight, no shared pipeline needed)
# ============================================================


class TestEdgeCases:
    """Edge case tests for pipeline error handling."""

    def setup_method(self) -> None:
        """Set up temp directory for edge case tests."""
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.config = ClipCannonConfig.load()

    def teardown_method(self) -> None:
        """Clean up temp directory."""
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    async def test_nonexistent_video_errors_cleanly(self) -> None:
        """Creating a project with nonexistent video returns error."""
        from clipcannon.tools.project import clipcannon_project_create

        result = await clipcannon_project_create(
            "test_bad", "/nonexistent/path/video.mp4",
        )
        assert "error" in result
        assert result["error"]["code"] == "INVALID_PARAMETER"

    async def test_provenance_verify_fresh_project(self) -> None:
        """Provenance verification on a fresh project passes with 0 records."""
        project_id = "proj_fresh"
        init_project_directory(project_id, self.tmp_dir)
        db_path = self.tmp_dir / project_id / "analysis.db"

        chain_result = verify_chain(project_id, db_path)
        assert chain_result.verified is True
        assert chain_result.total_records == 0

    async def test_provenance_tamper_detection(self) -> None:
        """Tampering with provenance data is detected by chain verification."""
        _skip_if_no_video()

        project_id = "proj_tamper"
        project_dir = self.tmp_dir / project_id
        init_project_directory(project_id, self.tmp_dir)
        db_path = self.tmp_dir / project_id / "analysis.db"

        # Set up project with source video
        source_dir = project_dir / "source"
        source_video = source_dir / TEST_VIDEO.name
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

        # Run probe to create provenance records
        result = await run_probe(project_id, db_path, project_dir, self.config)
        assert result.success

        # Verify chain passes before tampering
        chain_before = verify_chain(project_id, db_path)
        assert chain_before.verified is True
        assert chain_before.total_records > 0

        # Tamper with provenance: modify a field used in chain_hash computation
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = conn.execute(
                "SELECT record_id FROM provenance WHERE project_id = ? "
                "ORDER BY timestamp_utc ASC",
                (project_id,),
            ).fetchone()
            record_id = row["record_id"] if isinstance(row, dict) else row[0]
            conn.execute(
                "UPDATE provenance SET output_sha256 = 'TAMPERED' "
                "WHERE record_id = ?",
                (record_id,),
            )
            conn.commit()
        finally:
            conn.close()

        # Verify chain now fails
        chain_after = verify_chain(project_id, db_path)
        assert chain_after.verified is False, "Tamper should be detected"
