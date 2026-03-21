"""HTDemucs source separation pipeline stage for ClipCannon.

Separates the audio into four stems (vocals, drums, bass, other)
using Meta's HTDemucs model. This is an OPTIONAL stage -- if it
fails, downstream stages use audio_16k.wav instead of vocals.wav.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from typing import TYPE_CHECKING

from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "source_separation"
STAGE = "htdemucs"


def _check_demucs_available() -> bool:
    """Check if the demucs package is importable.

    Returns:
        True if demucs can be imported.
    """
    try:
        import demucs  # noqa: F401

        return True
    except ImportError:
        return False


async def _run_demucs_subprocess(
    audio_path: Path,
    output_dir: Path,
) -> tuple[bool, str]:
    """Run demucs via subprocess for better isolation.

    Uses the two-stems mode to separate vocals from accompaniment,
    which is faster and produces the primary output we need.

    Args:
        audio_path: Path to the input audio file.
        output_dir: Directory for demucs output.

    Returns:
        Tuple of (success, stderr_output).
    """
    cmd = [
        "python",
        "-m",
        "demucs",
        "--two-stems",
        "vocals",
        "-n",
        "htdemucs",
        "-o",
        str(output_dir),
        str(audio_path),
    ]
    logger.info("Running demucs: %s", " ".join(cmd))

    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    return proc.returncode == 0, proc.stderr


async def _run_demucs_api(
    audio_path: Path,
    output_dir: Path,
) -> bool:
    """Run demucs via the Python API.

    Args:
        audio_path: Path to the input audio file.
        output_dir: Directory for output stems.

    Returns:
        True if separation succeeded.
    """
    try:
        import torch
        import torchaudio
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        def _separate() -> bool:
            model = get_model("htdemucs")
            model.eval()

            wav, sr = torchaudio.load(str(audio_path))
            # Demucs expects (batch, channels, samples)
            if wav.dim() == 1:
                wav = wav.unsqueeze(0)
            ref = wav.mean(0)
            wav = (wav - ref.mean()) / ref.std()
            wav = wav.unsqueeze(0)

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = model.to(device)
            wav = wav.to(device)

            with torch.no_grad():
                sources = apply_model(model, wav, device=device)

            # sources shape: (batch, num_sources, channels, samples)
            source_names = model.sources
            output_dir.mkdir(parents=True, exist_ok=True)

            for idx, name in enumerate(source_names):
                stem = sources[0, idx].cpu()
                stem_path = output_dir / f"{name}.wav"
                torchaudio.save(str(stem_path), stem, sr)
                logger.info("Saved stem: %s (%d bytes)", stem_path, stem_path.stat().st_size)

            # Clean up GPU memory
            del model, wav, sources
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            return True

        return await asyncio.to_thread(_separate)

    except Exception as exc:
        logger.error("Demucs API separation failed: %s", exc)
        return False


async def run_source_separation(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the source separation pipeline stage.

    Separates audio into stems using HTDemucs. This is an optional
    stage; failure is logged but does not stop the pipeline.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    stems_dir = project_dir / "stems"
    audio_original = stems_dir / "audio_original.wav"

    if not audio_original.exists():
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message="audio_original.wav not found; cannot run source separation",
        )

    # Check demucs availability
    if not _check_demucs_available():
        logger.warning("demucs package not installed. Skipping source separation.")
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message="demucs package not installed. Install with: pip install demucs",
        )

    input_sha256 = await asyncio.to_thread(sha256_file, audio_original)

    # Try subprocess approach first (better isolation)
    demucs_output_dir = project_dir / "demucs_tmp"
    success, stderr = await _run_demucs_subprocess(audio_original, demucs_output_dir)

    if success:
        # Move stems to stems/ directory
        # Demucs outputs to: demucs_tmp/htdemucs/<filename_without_ext>/
        audio_stem = audio_original.stem
        demucs_result_dir = demucs_output_dir / "htdemucs" / audio_stem
        if demucs_result_dir.exists():
            for stem_file in demucs_result_dir.glob("*.wav"):
                dest = stems_dir / stem_file.name
                shutil.move(str(stem_file), str(dest))
                logger.info("Moved stem %s to %s", stem_file.name, dest)

            # Clean up temp directory
            shutil.rmtree(demucs_output_dir, ignore_errors=True)
        else:
            logger.warning(
                "Expected demucs output at %s not found, trying API",
                demucs_result_dir,
            )
            success = False

    if not success:
        # Fall back to API
        logger.info("Subprocess demucs failed, trying API approach")
        shutil.rmtree(demucs_output_dir, ignore_errors=True)
        success = await _run_demucs_api(audio_original, stems_dir)

    if not success:
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message="Both subprocess and API demucs approaches failed",
        )

    # Verify at least vocals.wav exists
    vocals_path = stems_dir / "vocals.wav"
    if not vocals_path.exists() or vocals_path.stat().st_size == 0:
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message="Source separation did not produce vocals.wav",
        )

    # Hash output stems
    stem_hashes: list[str] = []
    total_size = 0
    stem_count = 0
    for stem_name in ["vocals.wav", "no_vocals.wav", "drums.wav", "bass.wav", "other.wav"]:
        stem_path = stems_dir / stem_name
        if stem_path.exists() and stem_path.stat().st_size > 0:
            h = await asyncio.to_thread(sha256_file, stem_path)
            stem_hashes.append(f"{stem_name}:{h}")
            total_size += stem_path.stat().st_size
            stem_count += 1

    combined_hash = sha256_string("|".join(sorted(stem_hashes)))

    # Write provenance record
    record_id = record_provenance(
        db_path=db_path,
        project_id=project_id,
        operation=OPERATION,
        stage=STAGE,
        input_info=InputInfo(
            file_path=str(audio_original),
            sha256=input_sha256,
            size_bytes=audio_original.stat().st_size,
        ),
        output_info=OutputInfo(
            file_path=str(stems_dir),
            sha256=combined_hash,
            size_bytes=total_size,
            record_count=stem_count,
        ),
        model_info=ModelInfo(
            name="htdemucs",
            version="4.0",
        ),
        execution_info=ExecutionInfo(),
        parent_record_id="prov_001",
        description=f"Source separation: {stem_count} stems produced ({total_size} bytes total)",
    )

    logger.info("Source separation complete: %d stems, %d bytes", stem_count, total_size)

    return StageResult(
        success=True,
        operation=OPERATION,
        provenance_record_id=record_id,
    )
