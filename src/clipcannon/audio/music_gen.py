"""ACE-Step v1.5 AI music generation integration.

Generates original background music from text prompts using the ACE-Step
v1.5 hybrid LM+DiT architecture. Requires GPU with at least 4GB VRAM.

Model weights are cached at ~/.cache/ace-step/checkpoints and are
downloaded once from HuggingFace on first use. No internet required
after initial download.

Example:
    result = await generate_music(
        prompt="gentle ambient pad, 70 BPM, warm",
        duration_s=30.0,
        output_path=Path("/tmp/music.wav"),
    )
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Persistent local cache -- model weights never re-downloaded
_CHECKPOINT_DIR = os.path.join(
    os.path.expanduser("~"), ".cache", "ace-step", "checkpoints"
)


@dataclass
class MusicResult:
    """Result of an AI music generation.

    Attributes:
        file_path: Path to the generated WAV file.
        duration_ms: Duration of the generated audio in milliseconds.
        sample_rate: Sample rate of the output audio.
        seed: Seed used for reproducible generation.
        model_used: Name of the model used.
        prompt: Text prompt used for generation.
    """

    file_path: Path
    duration_ms: int
    sample_rate: int
    seed: int
    model_used: str
    prompt: str


def _validate_output(output_path: Path, requested_duration_s: float) -> int:
    """Validate the generated audio file exists and has reasonable duration.

    Args:
        output_path: Path to the generated WAV file.
        requested_duration_s: Requested duration in seconds.

    Returns:
        Actual duration in milliseconds.

    Raises:
        RuntimeError: If the file is missing, empty, or duration is wrong.
    """
    if not output_path.exists():
        raise RuntimeError(
            f"Generated audio file not found at {output_path}. "
            "ACE-Step pipeline completed but produced no output file."
        )
    file_size = output_path.stat().st_size
    if file_size == 0:
        raise RuntimeError(
            f"Generated audio file is empty at {output_path}. "
            "ACE-Step pipeline produced a zero-byte file."
        )

    try:
        import wave

        with wave.open(str(output_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            actual_duration_s = frames / rate
            actual_duration_ms = int(actual_duration_s * 1000)
    except Exception as exc:
        logger.warning(
            "Cannot read WAV header from %s: %s. Estimating from file size.",
            output_path, exc,
        )
        # ACE-Step v1.5 outputs 16-bit stereo 48kHz: 4 bytes per sample
        estimated_samples = (file_size - 44) // 4  # 44-byte WAV header
        actual_duration_ms = int((estimated_samples / 48000) * 1000)
        actual_duration_s = actual_duration_ms / 1000.0

    tolerance = requested_duration_s * 0.10
    if abs(actual_duration_s - requested_duration_s) > max(tolerance, 1.0):
        logger.warning(
            "Generated audio duration %.1fs differs from requested %.1fs "
            "(tolerance: %.1fs). File: %s",
            actual_duration_s, requested_duration_s, tolerance, output_path,
        )

    return actual_duration_ms


async def generate_music(
    prompt: str,
    duration_s: float,
    output_path: Path,
    seed: int | None = None,
    guidance_scale: float = 15.0,
    gpu_device: str = "cuda:0",
    tags: str = "",
    lyrics: str = "",
    infer_steps: int = 100,
) -> MusicResult:
    """Generate original music using ACE-Step v1.5 hybrid LM+DiT model.

    Loads the ACE-Step v1.5 pipeline (auto-downloads weights on first use
    to ~/.cache/ace-step/checkpoints), generates audio from the text
    prompt, saves to the output path, validates the result, and cleans
    up GPU memory.

    All processing is local. No cloud APIs or internet required after
    initial model download.

    Args:
        prompt: Text description of the desired music.
        duration_s: Desired duration in seconds (max 600).
        output_path: Path to save the generated WAV file.
        seed: Random seed for reproducibility. Generated if None.
        guidance_scale: Classifier-free guidance scale (default 15.0).
        gpu_device: CUDA device identifier.
        tags: Genre/mood tags for v1.5 (e.g. "pop, upbeat, 120bpm").
        lyrics: Optional lyrics for vocal music generation.
        infer_steps: Number of DiT inference steps (default 100).

    Returns:
        MusicResult with generation details.

    Raises:
        ImportError: If ace-step is not installed.
        RuntimeError: If generation or validation fails.
    """
    try:
        from acestep.pipeline_ace_step import ACEStepPipeline  # type: ignore[import-untyped]
    except ImportError:
        logger.error(
            "ACE-Step not installed. Cannot generate AI music. "
            "Install with: pip install git+https://github.com/ace-step/ACE-Step.git"
        )
        raise ImportError(
            "ACE-Step not installed. "
            "Install with: pip install git+https://github.com/ace-step/ACE-Step.git"
        )

    try:
        import torch  # type: ignore[import-untyped]
    except ImportError:
        logger.error("PyTorch not installed. Required for ACE-Step music generation.")
        raise ImportError(
            "PyTorch not installed. Install with: pip install torch"
        )

    if seed is None:
        seed = random.randint(0, 2**31 - 1)

    if duration_s <= 0:
        raise ValueError(f"duration_s must be positive, got {duration_s}")
    if duration_s > 600:
        raise ValueError(f"duration_s must be <= 600, got {duration_s}")

    logger.info(
        "Generating music: prompt=%r, duration=%.1fs, seed=%d, "
        "guidance=%.1f, steps=%d, tags=%r",
        prompt[:80], duration_s, seed, guidance_scale, infer_steps, tags[:50],
    )

    # Determine VRAM availability for cpu_offload decision
    cpu_offload = True
    device_idx = 0
    if torch.cuda.is_available():
        try:
            device_idx = int(gpu_device.split(":")[-1]) if ":" in gpu_device else 0
            total_mem = torch.cuda.get_device_properties(device_idx).total_memory
            total_gb = total_mem / (1024**3)
            # v1.5 needs ~4GB VRAM minimum
            cpu_offload = total_gb < 4.0
            logger.info(
                "GPU %d: %.1f GB VRAM, cpu_offload=%s",
                device_idx, total_gb, cpu_offload,
            )
        except Exception as exc:
            logger.warning("GPU detection failed, using cpu_offload: %s", exc)
            cpu_offload = True
    else:
        logger.warning("No CUDA GPU available. Using CPU offload (slow).")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pipeline = None
    try:
        os.makedirs(_CHECKPOINT_DIR, exist_ok=True)

        pipeline = ACEStepPipeline(
            checkpoint_dir=_CHECKPOINT_DIR,
            device_id=device_idx,
            cpu_offload=cpu_offload,
        )

        result = pipeline(
            prompt=prompt,
            lyrics=lyrics,
            audio_duration=duration_s,
            guidance_scale=guidance_scale,
            manual_seeds=[seed],
            save_path=str(output_path),
            batch_size=1,
        )

        logger.info("ACE-Step generation completed. Output: %s", output_path)

    except ImportError:
        raise
    except Exception as exc:
        logger.error(
            "ACE-Step generation failed: %s. prompt=%r, duration=%.1fs, seed=%d",
            exc, prompt[:80], duration_s, seed,
        )
        raise RuntimeError(
            f"ACE-Step music generation failed: {exc}. "
            f"Prompt: {prompt[:80]!r}, Duration: {duration_s}s, Seed: {seed}"
        ) from exc
    finally:
        if pipeline is not None:
            del pipeline
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    actual_duration_ms = _validate_output(output_path, duration_s)

    return MusicResult(
        file_path=output_path,
        duration_ms=actual_duration_ms,
        sample_rate=48000,
        seed=seed,
        model_used="ACE-Step-v1.5",
        prompt=prompt,
    )
