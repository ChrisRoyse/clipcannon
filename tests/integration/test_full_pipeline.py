"""Full pipeline integration tests for ClipCannon.

Runs the complete pipeline on a real test video and verifies every output:
database tables, files on disk, provenance chain integrity.

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


class TestFullPipeline:
    """Full pipeline integration test suite using real video."""

    @pytest.fixture(autouse=True)
    def setup_project(self, tmp_path: Path) -> None:
        """Set up a project directory with the real test video."""
        _skip_if_no_video()

        self.project_id = "proj_inttest"
        self.base_dir = tmp_path / "projects"
        self.project_dir = self.base_dir / self.project_id
        self.config = ClipCannonConfig.load()

        # Initialize project directory and database
        init_project_directory(self.project_id, self.base_dir)
        self.db_path = self.project_dir / "analysis.db"

        # Copy test video to project source dir
        source_dir = self.project_dir / "source"
        self.source_video = source_dir / TEST_VIDEO.name
        shutil.copy2(str(TEST_VIDEO), str(self.source_video))

        # Insert initial project record
        conn = get_connection(self.db_path, enable_vec=False, dict_rows=False)
        try:
            conn.execute(
                """INSERT INTO project (
                    project_id, name, source_path, source_sha256,
                    duration_ms, resolution, fps, codec, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created')""",
                (
                    self.project_id, "Integration Test",
                    str(self.source_video), "pending",
                    0, "unknown", 0, "unknown",
                ),
            )
            # Initialize stream_status rows
            for stream_name in PIPELINE_STREAMS:
                conn.execute(
                    "INSERT INTO stream_status (project_id, stream_name, status) "
                    "VALUES (?, ?, 'pending')",
                    (self.project_id, stream_name),
                )
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------
    # Stage 1: Probe
    # ---------------------------------------------------------------
    async def test_01_probe(self) -> None:
        """Probe stage extracts correct metadata from the test video."""
        result = await run_probe(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert result.success, f"Probe failed: {result.error_message}"

        # Verify project table was updated
        conn = get_connection(self.db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT * FROM project WHERE project_id = ?",
                (self.project_id,),
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
        assert len(str(row["source_sha256"])) == 64  # SHA-256 hex

    # ---------------------------------------------------------------
    # Stage 2: Audio Extract
    # ---------------------------------------------------------------
    async def test_02_audio_extract(self) -> None:
        """Audio extraction produces both WAV files."""
        # Must probe first
        await run_probe(
            self.project_id, self.db_path, self.project_dir, self.config,
        )

        result = await run_audio_extract(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert result.success, f"Audio extract failed: {result.error_message}"

        stems_dir = self.project_dir / "stems"
        audio_16k = stems_dir / "audio_16k.wav"
        audio_orig = stems_dir / "audio_original.wav"

        assert audio_16k.exists(), "audio_16k.wav not found"
        assert audio_orig.exists(), "audio_original.wav not found"
        assert audio_16k.stat().st_size > 1_000_000, "audio_16k.wav too small"
        assert audio_orig.stat().st_size > 1_000_000, "audio_original.wav too small"

    # ---------------------------------------------------------------
    # Stage 3: Frame Extract
    # ---------------------------------------------------------------
    async def test_03_frame_extract(self) -> None:
        """Frame extraction produces expected number of JPEG frames."""
        await run_probe(
            self.project_id, self.db_path, self.project_dir, self.config,
        )

        result = await run_frame_extract(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert result.success, f"Frame extract failed: {result.error_message}"

        frames_dir = self.project_dir / "frames"
        frames = sorted(frames_dir.glob("frame_*.jpg"))

        # At 2fps for ~210s, expect ~420 frames (tolerance of 5)
        assert len(frames) > 400, f"Too few frames: {len(frames)}"
        assert len(frames) < 440, f"Too many frames: {len(frames)}"

        # Verify first and last frame exist and have content
        assert frames[0].stat().st_size > 0
        assert frames[-1].stat().st_size > 0

    # ---------------------------------------------------------------
    # Full pipeline test (all stages in sequence)
    # ---------------------------------------------------------------
    async def test_full_pipeline_all_stages(self) -> None:
        """Run all non-model stages and verify every output."""
        # -- Required stages --
        probe_result = await run_probe(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert probe_result.success, f"Probe failed: {probe_result.error_message}"

        audio_result = await run_audio_extract(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert audio_result.success, f"Audio extract failed: {audio_result.error_message}"

        frame_result = await run_frame_extract(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert frame_result.success, f"Frame extract failed: {frame_result.error_message}"

        # -- Non-model stages --
        acoustic_result = await run_acoustic(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert acoustic_result.success, f"Acoustic failed: {acoustic_result.error_message}"

        storyboard_result = await run_storyboard(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert storyboard_result.success, f"Storyboard failed: {storyboard_result.error_message}"

        profanity_result = await run_profanity(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert profanity_result.success, f"Profanity failed: {profanity_result.error_message}"

        chronemic_result = await run_chronemic(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert chronemic_result.success, f"Chronemic failed: {chronemic_result.error_message}"

        highlights_result = await run_highlights(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert highlights_result.success, f"Highlights failed: {highlights_result.error_message}"

        finalize_result = await run_finalize(
            self.project_id, self.db_path, self.project_dir, self.config,
        )
        assert finalize_result.success, f"Finalize failed: {finalize_result.error_message}"

        # ========== VERIFY ALL OUTPUTS ==========
        conn = get_connection(self.db_path, enable_vec=False, dict_rows=True)
        try:
            # -- Project metadata --
            proj = fetch_one(
                conn,
                "SELECT * FROM project WHERE project_id = ?",
                (self.project_id,),
            )
            assert proj is not None
            assert EXPECTED_DURATION_MS_MIN <= int(proj["duration_ms"]) <= EXPECTED_DURATION_MS_MAX
            assert str(proj["resolution"]) == EXPECTED_RESOLUTION
            assert float(proj["fps"]) == EXPECTED_FPS
            assert str(proj["status"]) == "ready"

            # -- Audio files on disk --
            stems_dir = self.project_dir / "stems"
            assert (stems_dir / "audio_16k.wav").exists()
            assert (stems_dir / "audio_original.wav").exists()
            assert (stems_dir / "audio_16k.wav").stat().st_size > 0
            assert (stems_dir / "audio_original.wav").stat().st_size > 0

            # -- Frames on disk --
            frames = sorted((self.project_dir / "frames").glob("frame_*.jpg"))
            assert len(frames) > 400

            # -- Storyboard grids --
            grids = fetch_all(
                conn,
                "SELECT * FROM storyboard_grids WHERE project_id = ?",
                (self.project_id,),
            )
            assert len(grids) > 0, "No storyboard grids in database"
            # Check grid files exist on disk
            for grid in grids:
                grid_path = Path(str(grid["grid_path"]))
                assert grid_path.exists(), f"Grid file missing: {grid_path}"
                # Check grid image dimensions
                from PIL import Image
                img = Image.open(grid_path)
                assert img.size == (1044, 1044), f"Grid size wrong: {img.size}"

            # -- Silence gaps --
            gaps = fetch_all(
                conn,
                "SELECT * FROM silence_gaps WHERE project_id = ?",
                (self.project_id,),
            )
            # May or may not have gaps depending on audio content
            assert isinstance(gaps, list)

            # -- Acoustic --
            acoustic = fetch_all(
                conn,
                "SELECT * FROM acoustic WHERE project_id = ?",
                (self.project_id,),
            )
            assert len(acoustic) > 0, "No acoustic data"
            assert acoustic[0]["avg_volume_db"] is not None
            assert acoustic[0]["dynamic_range_db"] is not None

            # -- Beats --
            beats = fetch_all(
                conn,
                "SELECT * FROM beats WHERE project_id = ?",
                (self.project_id,),
            )
            assert len(beats) > 0, "No beats data"

            # -- Pacing --
            pacing = fetch_all(
                conn,
                "SELECT * FROM pacing WHERE project_id = ?",
                (self.project_id,),
            )
            assert len(pacing) > 0, "No pacing data"
            # Verify each window has required fields
            for p in pacing:
                assert p["start_ms"] is not None
                assert p["end_ms"] is not None
                assert p["words_per_minute"] is not None
                assert p["label"] is not None

            # -- Content safety --
            safety = fetch_all(
                conn,
                "SELECT * FROM content_safety WHERE project_id = ?",
                (self.project_id,),
            )
            assert len(safety) > 0, "No content safety data"
            assert safety[0]["content_rating"] is not None

            # -- Highlights --
            highlights = fetch_all(
                conn,
                "SELECT * FROM highlights WHERE project_id = ? ORDER BY score DESC",
                (self.project_id,),
            )
            assert len(highlights) > 0, "No highlights"
            # Verify score fields
            for h in highlights:
                assert float(h["score"]) >= 0
                assert h["type"] is not None
                assert h["reason"] is not None

            # -- Stream status --
            streams = fetch_all(
                conn,
                "SELECT * FROM stream_status WHERE project_id = ?",
                (self.project_id,),
            )
            assert len(streams) > 0, "No stream status entries"
            stream_map = {str(s["stream_name"]): str(s["status"]) for s in streams}
            # The streams that we ran should be completed
            assert stream_map.get("acoustic") == "completed"
            assert stream_map.get("storyboards") == "completed"
            assert stream_map.get("profanity") == "completed"
            assert stream_map.get("highlights") == "completed"
            assert stream_map.get("chronemic") == "completed"

            # -- Provenance --
            provenance = fetch_all(
                conn,
                "SELECT * FROM provenance WHERE project_id = ? ORDER BY timestamp_utc",
                (self.project_id,),
            )
            assert len(provenance) > 0, "No provenance records"
            # Each record should have a chain_hash
            for prov in provenance:
                assert prov["chain_hash"] is not None
                assert len(str(prov["chain_hash"])) == 64

            # -- Provenance chain verification --
            chain_result = verify_chain(self.project_id, self.db_path)
            assert chain_result.verified, (
                f"Provenance chain broken at {chain_result.broken_at}: "
                f"{chain_result.issue}"
            )
            assert chain_result.total_records == len(provenance)

        finally:
            conn.close()


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
            # Get the first record_id to target
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
