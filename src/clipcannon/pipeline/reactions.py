"""SenseVoice reaction detection pipeline stage for ClipCannon.

Detects audience reactions (laughter, applause) in audio using the
SenseVoice model. Falls back to energy-based detection if unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import numpy as np

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.source_resolution import resolve_audio_input
from clipcannon.provenance import (
    ExecutionInfo, InputInfo, ModelInfo, OutputInfo,
    record_provenance, sha256_file, sha256_string,
)

logger = logging.getLogger(__name__)
OPERATION = "reaction_detection"
STAGE = "sensevoice_reactions"
TARGET_SR = 16000
WINDOW_S = 3.0
STRIDE_S = 1.5
ENERGY_REACTION_THRESHOLD = 0.15


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load audio and resample to 16kHz mono.

    Args:
        audio_path: Path to the WAV file.

    Returns:
        Tuple of (mono float32 array, sample rate).
    """
    try:
        import torchaudio
        waveform, sr = torchaudio.load(str(audio_path))
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sr != TARGET_SR:
            resampler = torchaudio.transforms.Resample(sr, TARGET_SR)
            waveform = resampler(waveform)
        return waveform.squeeze(0).numpy(), TARGET_SR
    except ImportError:
        pass

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


def _check_sensevoice_funasr() -> bool:
    """Check if FunASR SenseVoice is available."""
    try:
        from funasr import AutoModel as FunASRModel  # noqa: F401
        return True
    except ImportError:
        return False


def _check_sensevoice_transformers() -> bool:
    """Check if SenseVoice via transformers is available."""
    try:
        from transformers import AutoModelForAudioClassification  # noqa: F401
        return True
    except ImportError:
        return False


def _detect_reactions_funasr(
    audio: np.ndarray,
    sample_rate: int,
) -> list[dict[str, object]]:
    """Detect reactions using FunASR SenseVoice model.

    Args:
        audio: Mono audio array.
        sample_rate: Audio sample rate.

    Returns:
        List of reaction dicts.
    """
    from funasr import AutoModel as FunASRModel

    model = FunASRModel(model="iic/SenseVoiceSmall", trust_remote_code=True)
    window_samples = int(WINDOW_S * sample_rate)
    stride_samples = int(STRIDE_S * sample_rate)

    reactions: list[dict[str, object]] = []

    pos = 0
    while pos + window_samples <= len(audio):
        chunk = audio[pos:pos + window_samples]
        start_ms = int(pos / sample_rate * 1000)
        end_ms = int((pos + window_samples) / sample_rate * 1000)

        result = model.generate(input=chunk, cache={})

        if result and isinstance(result, list):
            text = str(result[0].get("text", "")) if isinstance(result[0], dict) else str(result[0])
            text_lower = text.lower()

            if "<laughter>" in text_lower or "laugh" in text_lower:
                reactions.append({
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "type": "laughter",
                    "confidence": 0.8,
                    "duration_ms": end_ms - start_ms,
                    "intensity": "moderate",
                })
            if "<applause>" in text_lower or "applause" in text_lower:
                reactions.append({
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "type": "applause",
                    "confidence": 0.8,
                    "duration_ms": end_ms - start_ms,
                    "intensity": "moderate",
                })

        pos += stride_samples

    del model
    return reactions


def _detect_reactions_energy(
    audio: np.ndarray,
    sample_rate: int,
) -> list[dict[str, object]]:
    """Detect potential reactions from high-energy non-speech segments.

    Uses spectral characteristics to distinguish reactions from speech.
    High energy + high spectral spread = potential reaction.

    Args:
        audio: Mono audio array.
        sample_rate: Audio sample rate.

    Returns:
        List of reaction dicts.
    """
    window_samples = int(WINDOW_S * sample_rate)
    stride_samples = int(STRIDE_S * sample_rate)
    reactions: list[dict[str, object]] = []

    pos = 0
    while pos + window_samples <= len(audio):
        chunk = audio[pos:pos + window_samples]
        start_ms = int(pos / sample_rate * 1000)
        end_ms = int((pos + window_samples) / sample_rate * 1000)

        rms = float(np.sqrt(np.mean(chunk ** 2)))

        if rms > ENERGY_REACTION_THRESHOLD:
            # Compute spectral features to classify
            spectrum = np.abs(np.fft.rfft(chunk))
            if len(spectrum) > 0:
                # Spectral centroid (higher = more likely applause/laughter)
                freqs = np.fft.rfftfreq(len(chunk), 1.0 / sample_rate)
                centroid = float(
                    np.sum(freqs * spectrum) / (np.sum(spectrum) + 1e-10)
                )

                # Spectral spread
                spread = float(np.sqrt(
                    np.sum(((freqs - centroid) ** 2) * spectrum)
                    / (np.sum(spectrum) + 1e-10)
                ))

                # Zero crossing rate
                zcr = float(np.mean(np.abs(np.diff(np.sign(chunk)))) / 2)

                # Classify based on features
                reaction_type = None
                confidence = 0.0

                if centroid > 1000 and spread > 500 and zcr > 0.1:
                    # High centroid + high spread + high ZCR = applause-like
                    reaction_type = "applause"
                    confidence = min(0.6, rms * 3)
                elif centroid > 500 and zcr > 0.05 and rms > 0.2:
                    # Moderate features with high energy = laughter-like
                    reaction_type = "laughter"
                    confidence = min(0.5, rms * 2)

                if reaction_type and confidence > 0.3:
                    intensity = "weak"
                    if rms > 0.3:
                        intensity = "strong"
                    elif rms > 0.2:
                        intensity = "moderate"

                    reactions.append({
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "type": reaction_type,
                        "confidence": round(confidence, 3),
                        "duration_ms": end_ms - start_ms,
                        "intensity": intensity,
                    })

        pos += stride_samples

    return reactions


def _attach_context_transcripts(
    db_path: Path,
    project_id: str,
    reactions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach nearest transcript text as context for each reaction.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        reactions: List of reaction dicts.

    Returns:
        Updated reaction dicts with context_transcript field.
    """
    if not reactions:
        return reactions

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        segments = fetch_all(
            conn,
            "SELECT start_ms, end_ms, text FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
    finally:
        conn.close()

    if not segments:
        return reactions

    for reaction in reactions:
        r_mid = (int(reaction["start_ms"]) + int(reaction["end_ms"])) // 2
        best_text = ""
        best_dist = float("inf")

        for seg in segments:
            seg_mid = (int(seg["start_ms"]) + int(seg["end_ms"])) // 2
            dist = abs(r_mid - seg_mid)
            if dist < best_dist:
                best_dist = dist
                best_text = str(seg.get("text", ""))

        reaction["context_transcript"] = best_text[:200]

    return reactions


def _merge_overlapping_reactions(
    reactions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Merge overlapping reactions of the same type.

    Args:
        reactions: List of reaction dicts, possibly overlapping.

    Returns:
        Merged reactions list.
    """
    if not reactions:
        return reactions

    sorted_reactions = sorted(reactions, key=lambda r: (str(r["type"]), int(r["start_ms"])))
    merged: list[dict[str, object]] = []

    current = dict(sorted_reactions[0])
    for r in sorted_reactions[1:]:
        if (str(r["type"]) == str(current["type"])
                and int(r["start_ms"]) <= int(current["end_ms"])):
            current["end_ms"] = max(int(current["end_ms"]), int(r["end_ms"]))
            current["duration_ms"] = int(current["end_ms"]) - int(current["start_ms"])
            current["confidence"] = max(
                float(current.get("confidence", 0)),
                float(r.get("confidence", 0)),
            )
        else:
            merged.append(current)
            current = dict(r)

    merged.append(current)
    return merged


def _insert_reactions(
    db_path: Path,
    project_id: str,
    reactions: list[dict[str, object]],
) -> int:
    """Insert reactions into the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        reactions: List of reaction dicts.

    Returns:
        Number of reactions inserted.
    """
    if not reactions:
        return 0

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        rows: list[tuple[object, ...]] = [
            (
                project_id,
                int(r["start_ms"]),
                int(r["end_ms"]),
                str(r["type"]),
                float(r.get("confidence", 0.0)),
                int(r.get("duration_ms", 0)),
                str(r.get("intensity", "moderate")),
                str(r.get("context_transcript", ""))[:200],
            )
            for r in reactions
        ]
        batch_insert(
            conn, "reactions",
            ["project_id", "start_ms", "end_ms", "type",
             "confidence", "duration_ms", "intensity", "context_transcript"],
            rows,
        )
        conn.commit()
        return len(rows)
    except Exception as exc:
        conn.rollback()
        raise PipelineError(
            f"Failed to insert reactions: {exc}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
    finally:
        conn.close()


async def run_reactions(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the reaction detection pipeline stage.

    Tries SenseVoice (FunASR) first, then falls back to energy-based
    reaction detection for laughter and applause events.

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
        logger.info("Reaction detection starting: %s", audio_path)

        audio, sample_rate = await asyncio.to_thread(_load_audio, audio_path)
        logger.info(
            "Audio loaded: %.1f seconds",
            len(audio) / sample_rate,
        )

        backend_name = "energy_fallback"

        # Try FunASR SenseVoice
        if _check_sensevoice_funasr():
            try:
                reactions = await asyncio.to_thread(
                    _detect_reactions_funasr, audio, sample_rate,
                )
                backend_name = "sensevoice_funasr"
                logger.info("SenseVoice detected %d reactions", len(reactions))
            except Exception as sv_err:
                logger.warning(
                    "SenseVoice failed, using energy fallback: %s", sv_err,
                )
                reactions = await asyncio.to_thread(
                    _detect_reactions_energy, audio, sample_rate,
                )
        else:
            logger.info(
                "SenseVoice not available, using energy-based detection",
            )
            reactions = await asyncio.to_thread(
                _detect_reactions_energy, audio, sample_rate,
            )

        # Merge overlapping reactions
        reactions = _merge_overlapping_reactions(reactions)

        # Attach context transcripts
        reactions = await asyncio.to_thread(
            _attach_context_transcripts, db_path, project_id, reactions,
        )

        # Insert
        count = await asyncio.to_thread(
            _insert_reactions, db_path, project_id, reactions,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Provenance
        input_sha = await asyncio.to_thread(sha256_file, audio_path)
        reaction_summary = json.dumps(
            [{"t": r["type"], "s": r["start_ms"]} for r in reactions],
            sort_keys=True,
        )
        output_sha = sha256_string(reaction_summary)

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
                record_count=count,
            ),
            model_info=ModelInfo(
                name=backend_name,
                version="1.0",
                parameters={
                    "window_s": WINDOW_S,
                    "stride_s": STRIDE_S,
                    "energy_threshold": ENERGY_REACTION_THRESHOLD,
                },
            ),
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Reaction detection ({backend_name}): {count} reactions "
                f"({', '.join(str(r['type']) for r in reactions[:5])})"
            ),
        )

        logger.info(
            "Reaction detection complete in %d ms: %d reactions (%s)",
            elapsed_ms, count, backend_name,
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
        logger.error("Reaction detection failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
