"""Integration test fixtures.

Extends session-level probe/audio/frame results with additional
pipeline stages (acoustic, storyboard, profanity, etc.) that
only run in integration tests.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.schema import PIPELINE_STREAMS, init_project_directory
from clipcannon.pipeline.acoustic import run_acoustic
from clipcannon.pipeline.audio_extract import run_audio_extract
from clipcannon.pipeline.chronemic import run_chronemic
from clipcannon.pipeline.finalize import run_finalize
from clipcannon.pipeline.frame_extract import run_frame_extract
from clipcannon.pipeline.highlights import run_highlights
from clipcannon.pipeline.probe import run_probe
from clipcannon.pipeline.profanity import run_profanity
from clipcannon.pipeline.storyboard import run_storyboard

TEST_VIDEO = Path(__file__).resolve().parent.parent.parent / "testdata" / "2026-03-20 14-43-20.mp4"


@pytest.fixture(scope="module")
def pipeline_project(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Set up project and run probe+audio+frame once for the module.

    This is a self-contained integration fixture. It does NOT
    reuse the session-scoped conftest fixtures because integration
    tests need their own project directory with stream_status rows,
    source video copy, and the full stage chain.
    """
    if not TEST_VIDEO.exists():
        pytest.skip(f"Test video not found: {TEST_VIDEO}")

    base_dir = tmp_path_factory.mktemp("full_pipeline")
    project_id = "proj_inttest"
    project_dir = base_dir / project_id
    config = ClipCannonConfig.load()

    init_project_directory(project_id, base_dir)
    db_path = project_dir / "analysis.db"

    # Copy test video to project source dir
    source_video = project_dir / "source" / TEST_VIDEO.name
    shutil.copy2(str(TEST_VIDEO), str(source_video))

    # Insert initial project record + stream_status
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        conn.execute(
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created')""",
            (project_id, "Integration Test", str(source_video),
             "pending", 0, "unknown", 0, "unknown"),
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
def probe_result(pipeline_project: dict) -> object:
    """Run probe once."""
    p = pipeline_project
    return asyncio.run(run_probe(
        p["project_id"], p["db_path"], p["project_dir"], p["config"],
    ))


@pytest.fixture(scope="module")
def audio_result(pipeline_project: dict, probe_result: object) -> object:
    """Run audio extract once (depends on probe)."""
    assert probe_result.success
    p = pipeline_project
    return asyncio.run(run_audio_extract(
        p["project_id"], p["db_path"], p["project_dir"], p["config"],
    ))


@pytest.fixture(scope="module")
def frame_result(pipeline_project: dict, probe_result: object) -> object:
    """Run frame extract once (depends on probe)."""
    assert probe_result.success
    p = pipeline_project
    return asyncio.run(run_frame_extract(
        p["project_id"], p["db_path"], p["project_dir"], p["config"],
    ))


@pytest.fixture(scope="module")
def full_pipeline_results(
    pipeline_project: dict,
    probe_result: object,
    audio_result: object,
    frame_result: object,
) -> dict[str, object]:
    """Run remaining non-model stages once, return all results."""
    assert probe_result.success
    assert audio_result.success
    assert frame_result.success

    p = pipeline_project
    pid = p["project_id"]
    db = p["db_path"]
    pdir = p["project_dir"]
    cfg = p["config"]

    return {
        "probe": probe_result,
        "audio": audio_result,
        "frame": frame_result,
        "acoustic": asyncio.run(run_acoustic(pid, db, pdir, cfg)),
        "storyboard": asyncio.run(run_storyboard(pid, db, pdir, cfg)),
        "profanity": asyncio.run(run_profanity(pid, db, pdir, cfg)),
        "chronemic": asyncio.run(run_chronemic(pid, db, pdir, cfg)),
        "highlights": asyncio.run(run_highlights(pid, db, pdir, cfg)),
        "finalize": asyncio.run(run_finalize(pid, db, pdir, cfg)),
    }
