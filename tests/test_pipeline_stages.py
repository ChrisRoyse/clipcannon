"""Integration tests for ClipCannon pipeline stages.

Tests probe, audio extraction, and frame extraction against the
real test video file. Does NOT test model inference stages
(source_separation, transcribe) as those require model downloads.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.db.schema import create_project_db, init_project_directory
from clipcannon.pipeline.orchestrator import (
    PipelineOrchestrator,
    PipelineStage,
    StageResult,
    _topological_sort,
)
from clipcannon.pipeline.probe import run_probe
from clipcannon.pipeline.audio_extract import run_audio_extract
from clipcannon.pipeline.frame_extract import run_frame_extract
from clipcannon.pipeline.source_resolution import resolve_source_path

TEST_VIDEO = Path("/home/cabdru/clipcannon/testdata/2026-03-20 14-43-20.mp4")


@pytest.fixture
def project_setup(tmp_path: Path):
    """Set up a temporary project for testing."""
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    # Create project database
    db_path = create_project_db(project_id, base_dir=tmp_path)

    # Create subdirectories
    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    # Insert initial project row
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        execute(
            conn,
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                "Test Project",
                str(TEST_VIDEO),
                "pending",
                0,
                "0x0",
                0.0,
                "unknown",
                "created",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    config = ClipCannonConfig.load()

    return project_id, db_path, project_dir, config


@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestProbeStage:
    """Tests for the probe pipeline stage."""

    def test_probe_extracts_metadata(self, project_setup):
        """Probe should extract correct metadata from the test video."""
        project_id, db_path, project_dir, config = project_setup
        result = asyncio.run(run_probe(project_id, db_path, project_dir, config))

        assert result.success is True
        assert result.operation == "probe"
        assert result.provenance_record_id is not None

        # Verify project table was updated
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT * FROM project WHERE project_id = ?",
                (project_id,),
            )
        finally:
            conn.close()

        assert row is not None
        assert int(row["duration_ms"]) > 200000  # ~210s video
        assert row["resolution"] == "2560x1440"
        assert float(row["fps"]) == 60.0
        assert row["codec"] == "h264"
        assert row["source_sha256"] != "pending"
        assert row["status"] == "probed"

    def test_probe_writes_provenance(self, project_setup):
        """Probe should write a provenance record."""
        project_id, db_path, project_dir, config = project_setup
        result = asyncio.run(run_probe(project_id, db_path, project_dir, config))

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT * FROM provenance WHERE project_id = ?",
                (project_id,),
            )
        finally:
            conn.close()

        assert len(rows) >= 1
        prov = rows[0]
        assert prov["operation"] == "probe"
        assert prov["input_sha256"] is not None
        assert prov["chain_hash"] is not None


@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestAudioExtractStage:
    """Tests for the audio extraction pipeline stage."""

    def test_audio_extract_produces_files(self, project_setup):
        """Audio extract should produce 16k and original WAV files."""
        project_id, db_path, project_dir, config = project_setup

        # Must probe first
        asyncio.run(run_probe(project_id, db_path, project_dir, config))

        result = asyncio.run(run_audio_extract(project_id, db_path, project_dir, config))

        assert result.success is True
        assert result.operation == "audio_extract"

        stems_dir = project_dir / "stems"
        audio_16k = stems_dir / "audio_16k.wav"
        audio_orig = stems_dir / "audio_original.wav"

        assert audio_16k.exists()
        assert audio_orig.exists()
        assert audio_16k.stat().st_size > 0
        assert audio_orig.stat().st_size > 0

    def test_audio_extract_writes_provenance(self, project_setup):
        """Audio extract should write a provenance record."""
        project_id, db_path, project_dir, config = project_setup
        asyncio.run(run_probe(project_id, db_path, project_dir, config))
        result = asyncio.run(run_audio_extract(project_id, db_path, project_dir, config))

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT * FROM provenance WHERE project_id = ? AND operation = 'audio_extract'",
                (project_id,),
            )
        finally:
            conn.close()

        assert len(rows) == 1
        assert rows[0]["output_sha256"] is not None


@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestFrameExtractStage:
    """Tests for the frame extraction pipeline stage."""

    def test_frame_extract_produces_frames(self, project_setup):
        """Frame extract should produce approximately duration*2 frames."""
        project_id, db_path, project_dir, config = project_setup

        # Must probe first
        asyncio.run(run_probe(project_id, db_path, project_dir, config))

        result = asyncio.run(run_frame_extract(project_id, db_path, project_dir, config))

        assert result.success is True
        assert result.operation == "frame_extract"

        frames_dir = project_dir / "frames"
        frame_count = len(list(frames_dir.glob("frame_*.jpg")))

        # ~210s video at 2fps = ~420 frames, +/-5 tolerance
        assert frame_count > 400
        assert frame_count < 440

    def test_frame_extract_writes_provenance(self, project_setup):
        """Frame extract should write a provenance record."""
        project_id, db_path, project_dir, config = project_setup
        asyncio.run(run_probe(project_id, db_path, project_dir, config))
        result = asyncio.run(run_frame_extract(project_id, db_path, project_dir, config))

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT * FROM provenance WHERE project_id = ? AND operation = 'frame_extract'",
                (project_id,),
            )
        finally:
            conn.close()

        assert len(rows) == 1
        assert int(rows[0]["output_record_count"]) > 400


class TestTopologicalSort:
    """Tests for DAG resolution."""

    def test_linear_dependency(self):
        """Linear chain should produce one stage per level."""
        stages = [
            PipelineStage(name="a", operation="op_a", required=True, depends_on=[]),
            PipelineStage(name="b", operation="op_b", required=True, depends_on=["a"]),
            PipelineStage(name="c", operation="op_c", required=True, depends_on=["b"]),
        ]
        levels = _topological_sort(stages)
        assert len(levels) == 3
        assert levels[0][0].name == "a"
        assert levels[1][0].name == "b"
        assert levels[2][0].name == "c"

    def test_parallel_stages(self):
        """Independent stages at same level should be in the same level."""
        stages = [
            PipelineStage(name="root", operation="op_root", required=True, depends_on=[]),
            PipelineStage(name="a", operation="op_a", required=True, depends_on=["root"]),
            PipelineStage(name="b", operation="op_b", required=True, depends_on=["root"]),
            PipelineStage(name="c", operation="op_c", required=True, depends_on=["root"]),
        ]
        levels = _topological_sort(stages)
        assert len(levels) == 2
        level_1_names = {s.name for s in levels[1]}
        assert level_1_names == {"a", "b", "c"}

    def test_diamond_dependency(self):
        """Diamond DAG should produce correct levels."""
        stages = [
            PipelineStage(name="root", operation="op", required=True, depends_on=[]),
            PipelineStage(name="left", operation="op", required=True, depends_on=["root"]),
            PipelineStage(name="right", operation="op", required=True, depends_on=["root"]),
            PipelineStage(name="join", operation="op", required=True, depends_on=["left", "right"]),
        ]
        levels = _topological_sort(stages)
        assert len(levels) == 3
        assert levels[0][0].name == "root"
        mid_names = {s.name for s in levels[1]}
        assert mid_names == {"left", "right"}
        assert levels[2][0].name == "join"


class TestOrchestratorRegistration:
    """Tests for PipelineOrchestrator stage registration."""

    def test_register_and_list(self):
        """Should register stages and maintain order."""
        config = ClipCannonConfig.load()
        orch = PipelineOrchestrator(config)

        orch.register_stage(PipelineStage(
            name="stage_a", operation="op_a", required=True,
        ))
        orch.register_stage(PipelineStage(
            name="stage_b", operation="op_b", required=False,
        ))

        assert len(orch.stages) == 2
        assert orch.stages[0].name == "stage_a"
        assert orch.stages[1].name == "stage_b"

    def test_duplicate_registration_raises(self):
        """Duplicate stage name should raise PipelineError."""
        from clipcannon.exceptions import PipelineError as PE
        config = ClipCannonConfig.load()
        orch = PipelineOrchestrator(config)

        orch.register_stage(PipelineStage(
            name="stage_a", operation="op_a", required=True,
        ))
        with pytest.raises(PE, match="already registered"):
            orch.register_stage(PipelineStage(
                name="stage_a", operation="op_a2", required=True,
            ))


@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestSourceResolution:
    """Tests for source file resolution."""

    def test_resolves_to_original(self, project_setup):
        """Should resolve to original when no VFR normalization."""
        project_id, db_path, project_dir, config = project_setup
        asyncio.run(run_probe(project_id, db_path, project_dir, config))

        resolved = asyncio.run(resolve_source_path(project_id, db_path))
        assert resolved == TEST_VIDEO
