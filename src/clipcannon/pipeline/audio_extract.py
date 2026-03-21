"""Audio extraction pipeline stage for ClipCannon.

Extracts two WAV files from the source video:
  - audio_16k.wav: 16kHz mono for speech models (Whisper, etc.)
  - audio_original.wav: Native sample rate for source separation
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_one
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.source_resolution import resolve_source_path
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
    sha256_string,
)

logger = logging.getLogger(__name__)

OPERATION = "audio_extract"
STAGE = "ffmpeg_audio"


async def _run_ffmpeg_extract(
    source_path: Path,
    output_path: Path,
    sample_rate: int | None,
    mono: bool,
) -> tuple[bool, str]:
    """Run ffmpeg to extract audio from a video file.

    Args:
        source_path: Path to the source video.
        output_path: Path for the output WAV file.
        sample_rate: Target sample rate, or None for native.
        mono: Whether to downmix to mono.

    Returns:
        Tuple of (success, stderr_output).
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source_path),
        "-vn",
        "-acodec", "pcm_s16le",
    ]
    if sample_rate is not None:
        cmd.extend(["-ar", str(sample_rate)])
    if mono:
        cmd.extend(["-ac", "1"])
    cmd.append(str(output_path))

    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    return proc.returncode == 0, proc.stderr


async def run_audio_extract(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the audio extraction pipeline stage.

    Extracts two audio files from the source video:
      - stems/audio_16k.wav: 16kHz mono for speech processing
      - stems/audio_original.wav: Native rate for source separation

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    try:
        # Resolve which source file to use
        source_path = await resolve_source_path(project_id, db_path)

        stems_dir = project_dir / "stems"
        stems_dir.mkdir(parents=True, exist_ok=True)

        audio_16k_path = stems_dir / "audio_16k.wav"
        audio_original_path = stems_dir / "audio_original.wav"

        # Extract 16kHz mono
        logger.info("Extracting 16kHz mono audio for %s", project_id)
        success_16k, stderr_16k = await _run_ffmpeg_extract(
            source_path, audio_16k_path,
            sample_rate=16000, mono=True,
        )
        if not success_16k:
            raise PipelineError(
                f"Failed to extract 16kHz audio: {stderr_16k[-300:] if stderr_16k else 'unknown'}",
                stage_name=STAGE,
                operation=OPERATION,
            )

        # Extract original rate
        logger.info("Extracting original-rate audio for %s", project_id)
        success_orig, stderr_orig = await _run_ffmpeg_extract(
            source_path, audio_original_path,
            sample_rate=None, mono=False,
        )
        if not success_orig:
            raise PipelineError(
                f"Failed to extract original audio: {stderr_orig[-300:] if stderr_orig else 'unknown'}",
                stage_name=STAGE,
                operation=OPERATION,
            )

        # Verify outputs exist and have content
        for path, label in [
            (audio_16k_path, "audio_16k.wav"),
            (audio_original_path, "audio_original.wav"),
        ]:
            if not path.exists() or path.stat().st_size == 0:
                raise PipelineError(
                    f"Audio extraction produced empty or missing file: {label}",
                    stage_name=STAGE,
                    operation=OPERATION,
                )

        # Compute hashes
        hash_16k = await asyncio.to_thread(sha256_file, audio_16k_path)
        hash_orig = await asyncio.to_thread(sha256_file, audio_original_path)

        # Combined output hash for provenance
        combined_hash = sha256_string(f"{hash_16k}|{hash_orig}")

        source_sha256 = await asyncio.to_thread(sha256_file, source_path)

        # Write provenance record
        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(source_path),
                sha256=source_sha256,
                size_bytes=source_path.stat().st_size,
            ),
            output_info=OutputInfo(
                file_path=str(stems_dir),
                sha256=combined_hash,
                size_bytes=audio_16k_path.stat().st_size + audio_original_path.stat().st_size,
                record_count=2,
            ),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id="prov_001",
            description=(
                f"Audio extraction: audio_16k.wav ({audio_16k_path.stat().st_size} bytes), "
                f"audio_original.wav ({audio_original_path.stat().st_size} bytes)"
            ),
        )

        logger.info(
            "Audio extraction complete: 16k=%d bytes, original=%d bytes",
            audio_16k_path.stat().st_size,
            audio_original_path.stat().st_size,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            provenance_record_id=record_id,
        )

    except PipelineError:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Audio extraction failed: %s", error_msg)
        raise PipelineError(
            f"Audio extraction failed: {error_msg}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
