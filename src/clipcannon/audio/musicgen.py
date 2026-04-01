"""MusicGen (Meta AudioCraft) AI music generation integration.

Generates background music from text prompts using Meta's MusicGen
model. Supports small/medium/large sizes. For durations >30s, uses
windowed generation with 5s overlap and linear crossfade at seams.
Output is resampled from MusicGen's native 32kHz to 44100Hz.

Example:
    result = await generate_music_musicgen(
        prompt="gentle ambient pad, 70 BPM, warm synths",
        duration_s=60.0,
        output_path=Path("/tmp/music.wav"),
    )
"""

from __future__ import annotations

import logging
import random
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

_MUSICGEN_SR = 32000  # MusicGen native sample rate
_OUTPUT_SR = 44100  # ClipCannon pipeline standard
_MAX_CHUNK_S = 30.0  # Max single-pass duration
_OVERLAP_S = 5.0  # Overlap between chunks for crossfade
_VALID_SIZES = frozenset({"small", "medium", "large"})


def _validate_inputs(prompt: str, duration_s: float, model_size: str) -> None:
    """Validate generation parameters before loading models."""
    if not prompt or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if duration_s <= 0:
        raise ValueError(f"duration_s must be positive, got {duration_s}")
    if duration_s > 120:
        raise ValueError(f"duration_s must be <= 120, got {duration_s}")
    if model_size not in _VALID_SIZES:
        raise ValueError(
            f"Unknown model_size: {model_size!r}. "
            f"Valid: {', '.join(sorted(_VALID_SIZES))}"
        )


def _crossfade_chunks(chunks: list, overlap_samples: int) -> "np.ndarray":  # noqa: F821
    """Crossfade adjacent audio chunks with linear ramp at seams."""
    import numpy as np

    if len(chunks) == 1:
        return chunks[0]

    fade_out = np.linspace(1.0, 0.0, overlap_samples, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, overlap_samples, dtype=np.float32)
    result = chunks[0].copy()

    for chunk in chunks[1:]:
        result[-overlap_samples:] *= fade_out
        chunk[:overlap_samples] *= fade_in
        overlap_mix = result[-overlap_samples:] + chunk[:overlap_samples]
        result = np.concatenate([
            result[:-overlap_samples], overlap_mix, chunk[overlap_samples:],
        ])

    return result


def _resample_to_44100(audio: "np.ndarray", src_sr: int) -> "np.ndarray":  # noqa: F821
    """Resample audio from src_sr to 44100Hz via linear interpolation."""
    import numpy as np

    if src_sr == _OUTPUT_SR:
        return audio

    output_len = int(len(audio) * (_OUTPUT_SR / src_sr))
    src_indices = np.linspace(0, len(audio) - 1, output_len, dtype=np.float64)
    idx_floor = np.floor(src_indices).astype(np.int64)
    idx_ceil = np.minimum(idx_floor + 1, len(audio) - 1)
    frac = (src_indices - idx_floor).astype(np.float32)
    return audio[idx_floor] * (1.0 - frac) + audio[idx_ceil] * frac


def _save_wav_mono(audio: "np.ndarray", path: Path, sample_rate: int) -> None:  # noqa: F821
    """Save mono float32 audio as 16-bit WAV."""
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    int16_audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int16_audio.tobytes())


def _validate_output(output_path: Path, requested_s: float) -> int:
    """Validate generated WAV exists and return actual duration in ms."""
    if not output_path.exists():
        raise RuntimeError(
            f"Generated audio not found at {output_path}. "
            "MusicGen completed but produced no output."
        )
    if output_path.stat().st_size == 0:
        raise RuntimeError(f"Generated audio is empty at {output_path}.")

    with wave.open(str(output_path), "rb") as wf:
        actual_s = wf.getnframes() / wf.getframerate()
        actual_ms = int(actual_s * 1000)

    tolerance = requested_s * 0.15
    if abs(actual_s - requested_s) > max(tolerance, 2.0):
        logger.warning(
            "Duration %.1fs differs from requested %.1fs. File: %s",
            actual_s, requested_s, output_path,
        )
    return actual_ms


def _compute_chunk_durations(duration_s: float) -> list[float]:
    """Compute per-chunk durations for windowed generation."""
    if duration_s <= _MAX_CHUNK_S:
        return [duration_s]

    stride = _MAX_CHUNK_S - _OVERLAP_S  # 25s effective stride
    durations: list[float] = []
    remaining = duration_s

    while remaining > 0:
        if remaining <= _MAX_CHUNK_S:
            chunk_len = remaining
            if durations:
                chunk_len += _OVERLAP_S
            durations.append(min(chunk_len, _MAX_CHUNK_S))
            break
        durations.append(_MAX_CHUNK_S)
        remaining -= stride

    logger.info(
        "Windowed generation: %d chunks, durations=%s",
        len(durations), [f"{d:.1f}s" for d in durations],
    )
    return durations


async def generate_music_musicgen(
    prompt: str,
    duration_s: float,
    output_path: Path,
    model_size: str = "medium",
    seed: int | None = None,
    gpu_device: str = "cuda:0",
) -> "MusicResult":
    """Generate music using Meta's MusicGen model.

    Loads MusicGen (auto-downloads weights on first use via HuggingFace),
    generates audio from the text prompt, saves as 44100Hz mono WAV,
    validates the result, and cleans up GPU memory.

    For durations >30s, generates 30s chunks with 5s overlap and
    crossfades at seams for seamless long-form audio.

    Args:
        prompt: Text description of the desired music.
        duration_s: Desired duration in seconds (max 120).
        output_path: Path to save the generated WAV file.
        model_size: Model size -- "small", "medium", or "large".
        seed: Random seed for reproducibility. Generated if None.
        gpu_device: CUDA device identifier (e.g. "cuda:0").

    Returns:
        MusicResult with generation details.

    Raises:
        ImportError: If audiocraft or torch is not installed.
        ValueError: If parameters are invalid.
        RuntimeError: If generation or validation fails.
    """
    from clipcannon.audio.music_gen import MusicResult

    _validate_inputs(prompt, duration_s, model_size)

    try:
        from audiocraft.models import MusicGen  # type: ignore[import-untyped]
    except ImportError:
        logger.error(
            "audiocraft not installed. Install with: pip install audiocraft"
        )
        raise ImportError(
            "audiocraft not installed. Install with: pip install audiocraft"
        )

    try:
        import torch  # type: ignore[import-untyped]
    except ImportError:
        logger.error("PyTorch not installed. Required for MusicGen.")
        raise ImportError("PyTorch not installed. Install with: pip install torch")

    import numpy as np

    if seed is None:
        seed = random.randint(0, 2**31 - 1)

    model_name = f"facebook/musicgen-{model_size}"
    logger.info(
        "MusicGen: prompt=%r, duration=%.1fs, model=%s, seed=%d, device=%s",
        prompt[:80], duration_s, model_name, seed, gpu_device,
    )

    chunk_durations = _compute_chunk_durations(duration_s)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model = None
    try:
        logger.info("Loading MusicGen model: %s", model_name)
        model = MusicGen.get_pretrained(model_name, device=gpu_device)
        logger.info("MusicGen model loaded.")

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)

        # Generate each chunk
        raw_chunks: list[np.ndarray] = []
        for i, chunk_dur in enumerate(chunk_durations):
            logger.info("Generating chunk %d/%d (%.1fs)", i + 1, len(chunk_durations), chunk_dur)
            model.set_generation_params(duration=chunk_dur)
            wav_tensor = model.generate([prompt])

            # Shape: (batch=1, channels, samples) -> mono float32
            chunk_audio = wav_tensor[0, 0].cpu().numpy().astype(np.float32)
            peak = np.max(np.abs(chunk_audio))
            if peak > 0:
                chunk_audio = chunk_audio / peak * 0.9
            raw_chunks.append(chunk_audio)
            logger.info(
                "Chunk %d: %d samples (%.1fs at %dHz)",
                i + 1, len(chunk_audio), len(chunk_audio) / _MUSICGEN_SR, _MUSICGEN_SR,
            )

        # Crossfade if windowed
        if len(raw_chunks) > 1:
            overlap_samples = int(_OVERLAP_S * _MUSICGEN_SR)
            merged = _crossfade_chunks(raw_chunks, overlap_samples)
            logger.info("Crossfaded %d chunks: %.1fs", len(raw_chunks), len(merged) / _MUSICGEN_SR)
        else:
            merged = raw_chunks[0]

        # Resample 32kHz -> 44100Hz and save
        resampled = _resample_to_44100(merged, _MUSICGEN_SR)
        logger.info("Resampled %d -> %d samples (%dHz -> %dHz)",
                     len(merged), len(resampled), _MUSICGEN_SR, _OUTPUT_SR)
        _save_wav_mono(resampled, output_path, _OUTPUT_SR)
        logger.info("MusicGen output saved: %s", output_path)

    except ImportError:
        raise
    except Exception as exc:
        logger.error(
            "MusicGen failed: %s. prompt=%r, duration=%.1fs, model=%s, seed=%d",
            exc, prompt[:80], duration_s, model_name, seed,
        )
        raise RuntimeError(
            f"MusicGen generation failed: {exc}. "
            f"Prompt: {prompt[:80]!r}, Duration: {duration_s}s, "
            f"Model: {model_name}, Seed: {seed}"
        ) from exc
    finally:
        if model is not None:
            del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("GPU memory cleaned up.")

    actual_duration_ms = _validate_output(output_path, duration_s)

    return MusicResult(
        file_path=output_path,
        duration_ms=actual_duration_ms,
        sample_rate=_OUTPUT_SR,
        seed=seed,
        model_used=model_name,
        prompt=prompt,
    )
