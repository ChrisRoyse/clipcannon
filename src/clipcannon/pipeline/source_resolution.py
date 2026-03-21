"""Source file resolution for ClipCannon pipeline stages.

Determines which video file to use as the source for processing:
the original file or the VFR-normalized CFR version.

Convention:
    - If vfr_detected=True AND source_cfr_path is set, use source_cfr_path
    - Otherwise, use source_path (the original file)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_one
from clipcannon.exceptions import PipelineError

logger = logging.getLogger(__name__)


async def resolve_source_path(project_id: str, db_path: Path) -> Path:
    """Resolve the effective source file path for a project.

    If VFR was detected and normalization produced a CFR file,
    returns that path. Otherwise returns the original source path.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.

    Returns:
        Path to the video file that downstream stages should use.

    Raises:
        PipelineError: If the project is not found or the resolved
            file does not exist.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT source_path, source_cfr_path, vfr_detected "
            "FROM project WHERE project_id = ?",
            (project_id,),
        )
    finally:
        conn.close()

    if row is None:
        raise PipelineError(
            f"Project {project_id} not found in database",
            stage_name="source_resolution",
            operation="resolve",
        )

    vfr_detected = bool(row.get("vfr_detected", False))
    source_cfr_path = row.get("source_cfr_path")

    if vfr_detected and source_cfr_path:
        resolved = Path(str(source_cfr_path))
        if resolved.exists():
            logger.debug(
                "Using CFR-normalized source for %s: %s",
                project_id, resolved,
            )
            return resolved
        logger.warning(
            "CFR file %s not found for project %s, falling back to original",
            resolved, project_id,
        )

    source_path = Path(str(row["source_path"]))
    if not source_path.exists():
        raise PipelineError(
            f"Source file not found: {source_path}",
            stage_name="source_resolution",
            operation="resolve",
            details={"path": str(source_path)},
        )

    logger.debug("Using original source for %s: %s", project_id, source_path)
    return source_path


def resolve_audio_input(project_dir: Path) -> Path:
    """Resolve the best audio input file for speech processing stages.

    Prefers vocals.wav from source separation; falls back to audio_16k.wav.

    Args:
        project_dir: Path to the project directory.

    Returns:
        Path to the audio file to use for transcription/emotion/etc.
    """
    vocals_path = project_dir / "stems" / "vocals.wav"
    if vocals_path.exists() and vocals_path.stat().st_size > 0:
        logger.debug("Using separated vocals for speech processing: %s", vocals_path)
        return vocals_path

    audio_16k = project_dir / "stems" / "audio_16k.wav"
    if audio_16k.exists() and audio_16k.stat().st_size > 0:
        logger.debug("Using 16kHz audio for speech processing: %s", audio_16k)
        return audio_16k

    raise PipelineError(
        "No audio file available for speech processing",
        stage_name="source_resolution",
        operation="resolve_audio",
        details={"project_dir": str(project_dir)},
    )
