"""Shared test fixtures for ClipCannon.

Session-scoped fixtures run expensive FFmpeg operations (probe,
audio extract, frame extract) ONCE for the entire test session.
All test modules share the same probed/extracted project data.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute
from clipcannon.db.schema import create_project_db

TEST_VIDEO = Path("/home/cabdru/clipcannon/testdata/2026-03-20 14-43-20.mp4")


@pytest.fixture(scope="session")
def clipcannon_config() -> ClipCannonConfig:
    """Load config once for the entire test session."""
    return ClipCannonConfig.load()


@pytest.fixture(scope="session")
def session_project_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a single temp directory for session-scoped pipeline tests."""
    return tmp_path_factory.mktemp("session_pipeline")


@pytest.fixture(scope="session")
def session_probed_project(
    session_project_dir: Path,
    clipcannon_config: ClipCannonConfig,
) -> tuple[str, Path, Path, ClipCannonConfig, object] | None:
    """Run probe ONCE for the entire session. Shared by all test files.

    Returns:
        Tuple of (project_id, db_path, project_dir, config, probe_result)
        or None if test video is missing.
    """
    if not TEST_VIDEO.exists():
        return None

    from clipcannon.pipeline.probe import run_probe

    project_id = "session_probe"
    project_dir = session_project_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    db_path = create_project_db(project_id, base_dir=session_project_dir)

    for subdir in ("source", "stems", "frames", "storyboards"):
        (project_dir / subdir).mkdir(exist_ok=True)

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
                "Session Test",
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

    result = asyncio.run(
        run_probe(project_id, db_path, project_dir, clipcannon_config)
    )
    return project_id, db_path, project_dir, clipcannon_config, result


@pytest.fixture(scope="session")
def session_audio_extracted(
    session_probed_project: tuple | None,
) -> tuple[str, Path, Path, ClipCannonConfig, object] | None:
    """Run audio extraction ONCE for the session (depends on probe).

    Returns:
        Same tuple shape as session_probed_project with audio result.
    """
    if session_probed_project is None:
        return None

    from clipcannon.pipeline.audio_extract import run_audio_extract

    project_id, db_path, project_dir, config, probe_result = session_probed_project
    if not probe_result.success:
        return None

    result = asyncio.run(
        run_audio_extract(project_id, db_path, project_dir, config)
    )
    return project_id, db_path, project_dir, config, result


@pytest.fixture(scope="session")
def session_frames_extracted(
    session_probed_project: tuple | None,
) -> tuple[str, Path, Path, ClipCannonConfig, object] | None:
    """Run frame extraction ONCE for the session (depends on probe).

    Returns:
        Same tuple shape as session_probed_project with frame result.
    """
    if session_probed_project is None:
        return None

    from clipcannon.pipeline.frame_extract import run_frame_extract

    project_id, db_path, project_dir, config, probe_result = session_probed_project
    if not probe_result.success:
        return None

    result = asyncio.run(
        run_frame_extract(project_id, db_path, project_dir, config)
    )
    return project_id, db_path, project_dir, config, result
