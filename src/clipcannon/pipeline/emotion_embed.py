"""Wav2Vec2 emotion and energy analysis pipeline stage for ClipCannon.

Segments audio into 5-second windows with 2.5-second stride and computes
energy, arousal, and valence from model hidden states. Falls back to
simple RMS-based energy computation if the model cannot be loaded.

Energy formula: normalized RMS of hidden states (0.0-1.0)
Arousal formula: variance of hidden states (normalized 0.0-1.0)
Valence formula: mean of hidden states (normalized 0.0-1.0, centered 0.5)
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from typing import TYPE_CHECKING

import numpy as np

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.source_resolution import resolve_audio_input
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

OPERATION = "emotion_analysis"
STAGE = "wav2vec2_emotion"
MODEL_ID = "facebook/wav2vec2-large-960h"
EMBEDDING_DIM = 1024
WINDOW_S = 5.0
STRIDE_S = 2.5
TARGET_SR = 16000


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load audio and resample to 16kHz mono.

    Args:
        audio_path: Path to the WAV file.

    Returns:
        Tuple of (mono audio as float32 array, sample rate).
    """
    try:
        import torchaudio

        waveform, sr = torchaudio.load(str(audio_path))
        # Convert to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        # Resample if needed
        if sr != TARGET_SR:
            resampler = torchaudio.transforms.Resample(sr, TARGET_SR)
            waveform = resampler(waveform)
        audio = waveform.squeeze(0).numpy()
        return audio, TARGET_SR
    except ImportError:
        pass

    # Fallback to scipy
    from scipy.io import wavfile
    from scipy.signal import resample

    sr, data = wavfile.read(str(audio_path))
    if data.dtype == np.int16:
        audio = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        audio = data.astype(np.float32) / 2147483648.0
    else:
        audio = data.astype(np.float32)

    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    if sr != TARGET_SR:
        num_samples = int(len(audio) * TARGET_SR / sr)
        audio = resample(audio, num_samples).astype(np.float32)

    return audio, TARGET_SR


def _segment_audio(
    audio: np.ndarray,
    sample_rate: int,
    window_s: float = WINDOW_S,
    stride_s: float = STRIDE_S,
) -> list[tuple[int, int, np.ndarray]]:
    """Segment audio into overlapping windows.

    Args:
        audio: Mono audio array.
        sample_rate: Audio sample rate.
        window_s: Window duration in seconds.
        stride_s: Stride between windows in seconds.

    Returns:
        List of (start_ms, end_ms, audio_chunk) tuples.
    """
    window_samples = int(window_s * sample_rate)
    stride_samples = int(stride_s * sample_rate)
    segments: list[tuple[int, int, np.ndarray]] = []

    pos = 0
    while pos + window_samples <= len(audio):
        chunk = audio[pos : pos + window_samples]
        start_ms = int(pos / sample_rate * 1000)
        end_ms = int((pos + window_samples) / sample_rate * 1000)
        segments.append((start_ms, end_ms, chunk))
        pos += stride_samples

    # Handle trailing chunk
    if pos < len(audio) and len(audio) - pos > sample_rate:
        chunk = audio[pos:]
        start_ms = int(pos / sample_rate * 1000)
        end_ms = int(len(audio) / sample_rate * 1000)
        segments.append((start_ms, end_ms, chunk))

    return segments


def _compute_emotion_model(
    segments: list[tuple[int, int, np.ndarray]],
    device: str,
) -> list[dict[str, object]]:
    """Compute emotion features from Wav2Vec2 hidden states.

    Energy: normalized RMS of hidden states (0.0-1.0).
    Arousal: variance of hidden states (normalized 0.0-1.0).
    Valence: mean of hidden states (normalized 0.0-1.0, centered at 0.5).

    Args:
        segments: List of (start_ms, end_ms, audio_chunk) tuples.
        device: Torch device string.

    Returns:
        List of dicts with start_ms, end_ms, energy, arousal, valence,
        embedding.
    """
    import gc

    import torch
    from transformers import AutoFeatureExtractor, AutoModel

    # Clear GPU memory from previous pipeline stages to prevent
    # VRAM exhaustion when loading Wav2Vec2 after other models.
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

    feature_extractor = AutoFeatureExtractor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID, torch_dtype=torch.float16)
    try:
        model = model.to(device)
    except NotImplementedError:
        logger.warning("Meta tensor detected, reloading Wav2Vec2 with device_map")
        del model
        torch.cuda.empty_cache()
        model = AutoModel.from_pretrained(
            MODEL_ID, torch_dtype=torch.float16, device_map={"": device},
        )
    model.eval()

    results: list[dict[str, object]] = []

    for start_ms, end_ms, chunk in segments:
        inputs = feature_extractor(
            chunk,
            sampling_rate=TARGET_SR,
            return_tensors="pt",
            padding=True,
        )
        input_values = inputs["input_values"].to(device)

        with torch.no_grad():
            outputs = model(input_values, output_hidden_states=True)

        # Use last hidden state
        hidden = outputs.last_hidden_state.squeeze(0).cpu().numpy()

        # Energy: normalized RMS of hidden states
        rms = float(np.sqrt(np.mean(hidden**2)))
        energy = float(np.clip(rms / (rms + 1.0), 0.0, 1.0))

        # Arousal: normalized variance of hidden states
        variance = float(np.var(hidden))
        arousal = float(np.clip(variance / (variance + 1.0), 0.0, 1.0))

        # Valence: shifted mean, centered at 0.5
        mean_val = float(np.mean(hidden))
        valence = float(np.clip(0.5 + mean_val / (abs(mean_val) + 2.0), 0.0, 1.0))

        # Mean-pool hidden states to get embedding
        embedding = np.mean(hidden, axis=0).astype(np.float32)

        results.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "energy": round(energy, 4),
                "arousal": round(arousal, 4),
                "valence": round(valence, 4),
                "embedding": embedding,
            }
        )

    # Clean up
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return results


def _compute_emotion_fallback(
    segments: list[tuple[int, int, np.ndarray]],
) -> list[dict[str, object]]:
    """Compute emotion features from raw audio RMS as fallback.

    Args:
        segments: List of (start_ms, end_ms, audio_chunk) tuples.

    Returns:
        List of dicts with start_ms, end_ms, energy, arousal, valence,
        embedding (zero-filled).
    """
    results: list[dict[str, object]] = []

    for start_ms, end_ms, chunk in segments:
        rms = float(np.sqrt(np.mean(chunk**2)))
        energy = float(np.clip(rms * 5.0, 0.0, 1.0))

        # Arousal from energy variance over sub-windows
        sub_size = max(1, len(chunk) // 10)
        sub_energies = []
        for i in range(0, len(chunk) - sub_size, sub_size):
            sub_rms = float(np.sqrt(np.mean(chunk[i : i + sub_size] ** 2)))
            sub_energies.append(sub_rms)

        arousal = float(np.clip(np.std(sub_energies) * 10, 0.0, 1.0)) if sub_energies else 0.0

        valence = 0.5  # Cannot determine from raw audio

        # Zero embedding as placeholder
        embedding = np.zeros(EMBEDDING_DIM, dtype=np.float32)

        results.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "energy": round(energy, 4),
                "arousal": round(arousal, 4),
                "valence": round(valence, 4),
                "embedding": embedding,
            }
        )

    return results


def _pack_embedding(embedding: np.ndarray) -> bytes:
    """Pack a float32 embedding into bytes for sqlite-vec.

    Args:
        embedding: 1-D float32 array.

    Returns:
        Packed bytes.
    """
    return struct.pack(f"{len(embedding)}f", *embedding.tolist())


def _insert_results(
    db_path: Path,
    project_id: str,
    results: list[dict[str, object]],
) -> dict[str, int]:
    """Insert emotion results into database tables.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        results: List of emotion result dicts.

    Returns:
        Dict with counts of inserted records per table.
    """
    counts: dict[str, int] = {}

    # Insert into emotion_curve (core table)
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        curve_rows: list[tuple[object, ...]] = [
            (
                project_id,
                int(r["start_ms"]),
                int(r["end_ms"]),
                float(r["arousal"]),
                float(r["valence"]),
                float(r["energy"]),
            )
            for r in results
        ]
        batch_insert(
            conn,
            "emotion_curve",
            ["project_id", "start_ms", "end_ms", "arousal", "valence", "energy"],
            curve_rows,
        )
        conn.commit()
        counts["emotion_curve"] = len(curve_rows)
    except Exception as exc:
        conn.rollback()
        raise PipelineError(
            f"Failed to insert emotion_curve: {exc}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
    finally:
        conn.close()

    # Insert into vec_emotion (vector table)
    vec_conn = get_connection(db_path, enable_vec=True, dict_rows=False)
    try:
        vec_inserted = 0
        for r in results:
            emb = r.get("embedding")
            if not isinstance(emb, np.ndarray):
                continue
            emb_bytes = _pack_embedding(emb)
            try:
                vec_conn.execute(
                    "INSERT INTO vec_emotion "
                    "(project_id, start_ms, end_ms, energy, arousal, "
                    "emotion_embedding) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        int(r["start_ms"]),
                        int(r["end_ms"]),
                        float(r["energy"]),
                        float(r["arousal"]),
                        emb_bytes,
                    ),
                )
                vec_inserted += 1
            except Exception as vec_err:
                if vec_inserted == 0:
                    logger.warning(
                        "vec_emotion insert failed (sqlite-vec may not be loaded): %s",
                        vec_err,
                    )
                    break
                raise
        vec_conn.commit()
        counts["vec_emotion"] = vec_inserted
    except Exception as exc:
        logger.warning("vec_emotion inserts failed: %s", exc)
        counts["vec_emotion"] = 0
    finally:
        vec_conn.close()

    return counts


async def run_emotion_embed(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the emotion/energy analysis pipeline stage.

    Segments audio into 5s windows with 2.5s stride and computes
    energy, arousal, and valence using Wav2Vec2 hidden states.
    Falls back to simple RMS energy if model loading fails.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    start_time = time.monotonic()

    try:
        audio_path = resolve_audio_input(project_dir)
        logger.info("Emotion analysis starting: %s", audio_path)

        # Load audio
        audio, sample_rate = await asyncio.to_thread(_load_audio, audio_path)
        logger.info(
            "Audio loaded: %d samples, %d Hz, %.1f seconds",
            len(audio),
            sample_rate,
            len(audio) / sample_rate,
        )

        # Segment audio
        segments = _segment_audio(audio, sample_rate)
        logger.info("Created %d audio segments for emotion analysis", len(segments))

        if not segments:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No audio segments created (audio too short)",
            )

        # Try model-based analysis, fall back to RMS
        gpu_device = str(config.get("gpu.device"))
        device = "cuda" if "cuda" in gpu_device else "cpu"
        backend_name = "wav2vec2"

        try:
            results = await asyncio.to_thread(
                _compute_emotion_model,
                segments,
                device,
            )
            logger.info("Wav2Vec2 emotion analysis succeeded")
        except (ImportError, OSError, RuntimeError) as model_err:
            logger.warning(
                "Wav2Vec2 model loading failed, using RMS fallback: %s",
                model_err,
            )
            backend_name = "rms_fallback"
            results = await asyncio.to_thread(
                _compute_emotion_fallback,
                segments,
            )

        # Insert results
        counts = await asyncio.to_thread(
            _insert_results,
            db_path,
            project_id,
            results,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Provenance
        input_sha = await asyncio.to_thread(sha256_file, audio_path)
        summary_data = json.dumps(
            [{"s": r["start_ms"], "e": r["energy"], "a": r["arousal"]} for r in results],
            sort_keys=True,
        )
        output_sha = sha256_string(summary_data)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(audio_path),
                sha256=input_sha,
                size_bytes=audio_path.stat().st_size,
            ),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=len(results),
            ),
            model_info=ModelInfo(
                name=backend_name,
                version=MODEL_ID if backend_name == "wav2vec2" else "rms",
                parameters={
                    "window_s": WINDOW_S,
                    "stride_s": STRIDE_S,
                    "embedding_dim": EMBEDDING_DIM,
                },
            ),
            execution_info=ExecutionInfo(
                duration_ms=elapsed_ms,
                gpu_device=device if device == "cuda" else None,
            ),
            parent_record_id=None,
            description=(
                f"Emotion analysis ({backend_name}): {len(results)} windows, "
                f"emotion_curve={counts.get('emotion_curve', 0)}, "
                f"vec_emotion={counts.get('vec_emotion', 0)}"
            ),
        )

        logger.info(
            "Emotion analysis complete in %d ms: %s",
            elapsed_ms,
            counts,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except PipelineError:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Emotion analysis failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
