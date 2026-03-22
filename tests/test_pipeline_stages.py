"""Integration tests for ClipCannon pipeline stages.

Tests probe, audio extraction, and frame extraction against the
real test video file. Does NOT test model inference stages
(source_separation, transcribe) as those require model downloads.

Uses session-scoped fixtures from conftest.py so that expensive
FFmpeg operations run only ONCE across all test modules.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.pipeline.orchestrator import (
    PipelineOrchestrator,
    PipelineStage,
    _topological_sort,
)
from clipcannon.pipeline.source_resolution import resolve_source_path

TEST_VIDEO = Path("/home/cabdru/clipcannon/testdata/2026-03-20 14-43-20.mp4")


# ============================================================
# PROBE TESTS (use session_probed_project from conftest)
# ============================================================


@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestProbeStage:
    """Tests for the probe pipeline stage."""

    def test_probe_extracts_metadata(self, session_probed_project):
        """Probe should extract correct metadata from the test video."""
        assert session_probed_project is not None
        project_id, db_path, project_dir, config, result = session_probed_project

        assert result.success is True
        assert result.operation == "probe"
        assert result.provenance_record_id is not None

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

    def test_probe_writes_provenance(self, session_probed_project):
        """Probe should write a provenance record."""
        assert session_probed_project is not None
        project_id, db_path, *_ = session_probed_project

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT * FROM provenance WHERE project_id = ? AND operation = 'probe'",
                (project_id,),
            )
        finally:
            conn.close()

        assert len(rows) >= 1
        prov = rows[0]
        assert prov["operation"] == "probe"
        assert prov["input_sha256"] is not None
        assert prov["chain_hash"] is not None


# ============================================================
# AUDIO EXTRACT TESTS (use session_audio_extracted from conftest)
# ============================================================


@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestAudioExtractStage:
    """Tests for the audio extraction pipeline stage."""

    def test_audio_extract_produces_files(self, session_audio_extracted):
        """Audio extract should produce 16k and original WAV files."""
        assert session_audio_extracted is not None
        project_id, db_path, project_dir, config, result = session_audio_extracted

        assert result.success is True
        assert result.operation == "audio_extract"

        stems_dir = project_dir / "stems"
        audio_16k = stems_dir / "audio_16k.wav"
        audio_orig = stems_dir / "audio_original.wav"

        assert audio_16k.exists()
        assert audio_orig.exists()
        assert audio_16k.stat().st_size > 0
        assert audio_orig.stat().st_size > 0

    def test_audio_extract_writes_provenance(self, session_audio_extracted):
        """Audio extract should write a provenance record."""
        assert session_audio_extracted is not None
        project_id, db_path, *_ = session_audio_extracted

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


# ============================================================
# FRAME EXTRACT TESTS (use session_frames_extracted from conftest)
# ============================================================


@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestFrameExtractStage:
    """Tests for the frame extraction pipeline stage."""

    def test_frame_extract_produces_frames(self, session_frames_extracted):
        """Frame extract should produce approximately duration*2 frames."""
        assert session_frames_extracted is not None
        project_id, db_path, project_dir, config, result = session_frames_extracted

        assert result.success is True
        assert result.operation == "frame_extract"

        frames_dir = project_dir / "frames"
        frame_count = len(list(frames_dir.glob("frame_*.jpg")))

        # ~210s video at 2fps = ~420 frames, +/-5 tolerance
        assert frame_count > 400
        assert frame_count < 440

    def test_frame_extract_writes_provenance(self, session_frames_extracted):
        """Frame extract should write a provenance record."""
        assert session_frames_extracted is not None
        project_id, db_path, *_ = session_frames_extracted

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


# ============================================================
# SOURCE RESOLUTION (uses session_probed_project)
# ============================================================


@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestSourceResolution:
    """Tests for source file resolution."""

    def test_resolves_to_original(self, session_probed_project):
        """Should resolve to original when no VFR normalization."""
        assert session_probed_project is not None
        project_id, db_path, project_dir, config, result = session_probed_project
        assert result.success is True

        resolved = asyncio.run(resolve_source_path(project_id, db_path))
        assert resolved == TEST_VIDEO


# ============================================================
# PURE UNIT TESTS (no FFmpeg, no shared fixtures needed)
# ============================================================


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

    def test_register_and_list(self, clipcannon_config):
        """Should register stages and maintain order."""
        orch = PipelineOrchestrator(clipcannon_config)

        orch.register_stage(PipelineStage(
            name="stage_a", operation="op_a", required=True,
        ))
        orch.register_stage(PipelineStage(
            name="stage_b", operation="op_b", required=False,
        ))

        assert len(orch.stages) == 2
        assert orch.stages[0].name == "stage_a"
        assert orch.stages[1].name == "stage_b"

    def test_duplicate_registration_raises(self, clipcannon_config):
        """Duplicate stage name should raise PipelineError."""
        from clipcannon.exceptions import PipelineError as PE

        orch = PipelineOrchestrator(clipcannon_config)

        orch.register_stage(PipelineStage(
            name="stage_a", operation="op_a", required=True,
        ))
        with pytest.raises(PE, match="already registered"):
            orch.register_stage(PipelineStage(
                name="stage_a", operation="op_a2", required=True,
            ))
