"""Audio cleanup MCP tool for ClipCannon.

Separated from audio.py to keep the main audio tools module under 500 lines.
"""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path

logger = logging.getLogger(__name__)


async def _extract_audio_from_source(
    proj_dir: Path, project_id: str,
) -> Path | None:
    """Extract audio from source video when stems are missing."""
    import asyncio

    source_dir = proj_dir / "source"
    if not source_dir.exists():
        return None
    videos = list(source_dir.glob("*.mp4")) + list(source_dir.glob("*.mkv"))
    if not videos:
        return None

    stems_dir = proj_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    output = stems_dir / "audio_original.wav"

    cmd = [
        "ffmpeg", "-y", "-i", str(videos[0]),
        "-vn", "-acodec", "pcm_s16le", str(output),
    ]
    logger.info("Stems missing for %s -- extracting audio from source", project_id)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("Audio extraction failed: %s", stderr.decode()[-500:])
            return None
    except FileNotFoundError:
        logger.error("ffmpeg not found -- cannot extract audio")
        return None

    if output.exists() and output.stat().st_size > 0:
        return output
    return None


async def run_audio_cleanup(
    project_id: str,
    edit_id: str,
    operations: list[str],
    hum_frequency: int,
    validate_project: object,
    validate_edit: object,
    project_dir_fn: object,
    store_asset_fn: object,
    error_fn: object,
) -> dict[str, object]:
    """Execute audio cleanup. Called from dispatch_audio_tool."""
    from clipcannon.audio.cleanup import SUPPORTED_CLEANUP_OPS, cleanup_audio

    err = validate_project(project_id)  # type: ignore[operator]
    if err is not None:
        return err
    err = validate_edit(project_id, edit_id)  # type: ignore[operator]
    if err is not None:
        return err

    invalid = [op for op in operations if op not in SUPPORTED_CLEANUP_OPS]
    if invalid:
        return error_fn("INVALID_PARAMETER", f"Unknown operations: {invalid}")  # type: ignore[operator]

    proj_dir: Path = project_dir_fn(project_id)  # type: ignore[operator]
    audio_dir = proj_dir / "edits" / edit_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    source_audio = proj_dir / "stems" / "vocals.wav"
    if not source_audio.exists():
        source_audio = proj_dir / "stems" / "audio_original.wav"
    if not source_audio.exists():
        source_audio = proj_dir / "stems" / "audio_16k.wav"
    if not source_audio.exists():
        wavs = (
            list((proj_dir / "stems").glob("*.wav"))
            if (proj_dir / "stems").exists()
            else []
        )
        if not wavs:
            wavs = list(proj_dir.glob("*.wav"))
        if wavs:
            source_audio = wavs[0]
        else:
            extracted = await _extract_audio_from_source(proj_dir, project_id)
            if extracted is None:
                return error_fn(  # type: ignore[operator]
                    "AUDIO_NOT_FOUND",
                    "No audio stems found and extraction failed.",
                )
            source_audio = extracted

    output_path = audio_dir / f"cleaned_{secrets.token_hex(4)}.wav"
    start = time.monotonic()

    try:
        result = await cleanup_audio(
            input_path=source_audio,
            output_path=output_path,
            operations=operations,
            hum_frequency=hum_frequency,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        return error_fn("CLEANUP_FAILED", str(exc))  # type: ignore[operator]

    elapsed_ms = int((time.monotonic() - start) * 1000)

    store_asset_fn(  # type: ignore[operator]
        project_id=project_id, edit_id=edit_id,
        asset_id=result.asset_id, asset_type="cleaned",
        file_path=str(result.file_path), duration_ms=result.duration_ms,
        sample_rate=result.sample_rate, model_used="ffmpeg",
        generation_params={"operations": operations, "hum_frequency": hum_frequency},
        seed=None, volume_db=0.0,
    )

    return {
        "asset_id": result.asset_id,
        "file_path": str(result.file_path),
        "duration_ms": result.duration_ms,
        "operations_applied": result.operations_applied,
        "elapsed_ms": elapsed_ms,
    }
