"""WavLM speaker diarization pipeline stage for ClipCannon.

Uses Silero VAD for speech segment detection, then extracts speaker
embeddings using WavLM (microsoft/wavlm-base-plus-sv) and clusters
them with AgglomerativeClustering. Falls back to speaker_0 on failure.
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
OPERATION = "speaker_diarization"
STAGE = "wavlm_speaker"
MODEL_ID = "microsoft/wavlm-base-plus-sv"
EMBEDDING_DIM = 512
TARGET_SR = 16000
MIN_SPEECH_DURATION_S = 0.5
CLUSTER_DISTANCE_THRESHOLD = 0.7


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load audio and resample to 16kHz mono."""
    try:
        import torchaudio

        waveform, sr = torchaudio.load(str(audio_path))
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sr != TARGET_SR:
            waveform = torchaudio.transforms.Resample(sr, TARGET_SR)(waveform)
        return waveform.squeeze(0).numpy(), TARGET_SR
    except ImportError:
        pass
    from scipy.io import wavfile
    from scipy.signal import resample

    sr, data = wavfile.read(str(audio_path))
    audio = data.astype(np.float32) / (
        32768.0 if data.dtype == np.int16 else 2147483648.0 if data.dtype == np.int32 else 1.0
    )
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    if sr != TARGET_SR:
        audio = resample(audio, int(len(audio) * TARGET_SR / sr)).astype(np.float32)
    return audio, TARGET_SR


def _detect_speech_vad(audio: np.ndarray, sample_rate: int) -> list[tuple[int, int]]:
    """Detect speech segments using Silero VAD."""
    import torch

    model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
    get_speech_timestamps = utils[0]
    audio_tensor = torch.from_numpy(audio).float()
    timestamps = get_speech_timestamps(
        audio_tensor,
        model,
        sampling_rate=sample_rate,
        min_speech_duration_ms=int(MIN_SPEECH_DURATION_S * 1000),
        return_seconds=False,
    )
    return [
        (int(ts["start"] / sample_rate * 1000), int(ts["end"] / sample_rate * 1000))
        for ts in timestamps
    ]


def _detect_speech_energy(audio: np.ndarray, sample_rate: int) -> list[tuple[int, int]]:
    """Fallback speech detection using energy thresholding."""
    ws = int(0.5 * sample_rate)
    segments: list[tuple[int, int]] = []
    in_speech = False
    start_ms = 0
    for i in range(0, len(audio) - ws, ws // 2):
        rms = float(np.sqrt(np.mean(audio[i : i + ws] ** 2)))
        t_ms = int(i / sample_rate * 1000)
        if rms > 0.01 and not in_speech:
            in_speech, start_ms = True, t_ms
        elif rms <= 0.01 and in_speech:
            in_speech = False
            if t_ms - start_ms >= int(MIN_SPEECH_DURATION_S * 1000):
                segments.append((start_ms, t_ms))
    if in_speech:
        end_ms = int(len(audio) / sample_rate * 1000)
        if end_ms - start_ms >= int(MIN_SPEECH_DURATION_S * 1000):
            segments.append((start_ms, end_ms))
    return segments


def _extract_wavlm_embeddings(
    audio: np.ndarray,
    sample_rate: int,
    speech_segments: list[tuple[int, int]],
    device: str,
) -> list[tuple[int, int, np.ndarray]]:
    """Extract WavLM 512-dim speaker embeddings for each speech segment."""
    import torch
    from transformers import AutoFeatureExtractor, AutoModel

    fe = AutoFeatureExtractor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(device)
    model.eval()
    results: list[tuple[int, int, np.ndarray]] = []
    for start_ms, end_ms in speech_segments:
        chunk = audio[int(start_ms / 1000 * sample_rate) : int(end_ms / 1000 * sample_rate)]
        if len(chunk) < sample_rate // 4:
            continue
        inputs = fe(chunk, sampling_rate=sample_rate, return_tensors="pt", padding=True)
        with torch.no_grad():
            hidden = (
                model(inputs["input_values"].to(device), output_hidden_states=True)
                .last_hidden_state.squeeze(0)
                .cpu()
                .numpy()
            )
        emb = np.mean(hidden, axis=0).astype(np.float32)
        if len(emb) > EMBEDDING_DIM:
            emb = emb[:EMBEDDING_DIM]
        elif len(emb) < EMBEDDING_DIM:
            padded = np.zeros(EMBEDDING_DIM, dtype=np.float32)
            padded[: len(emb)] = emb
            emb = padded
        norm = float(np.linalg.norm(emb))
        if norm > 1e-10:
            emb = emb / norm
        results.append((start_ms, end_ms, emb))
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return results


def _cluster_speakers(embeddings: list[tuple[int, int, np.ndarray]]) -> dict[int, list[int]]:
    """Cluster speaker embeddings. Auto-determines speaker count."""
    if len(embeddings) <= 1:
        return {0: list(range(len(embeddings)))}
    from sklearn.cluster import AgglomerativeClustering

    emb_matrix = np.array([e[2] for e in embeddings])
    labels = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=CLUSTER_DISTANCE_THRESHOLD,
        metric="cosine",
        linkage="average",
    ).fit_predict(emb_matrix)
    cluster_map: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        cluster_map.setdefault(int(label), []).append(idx)
    return cluster_map


def _insert_results(
    db_path: Path,
    project_id: str,
    embeddings: list[tuple[int, int, np.ndarray]],
    cluster_map: dict[int, list[int]],
    total_duration_ms: int,
) -> dict[str, int]:
    """Insert speaker diarization results into the database."""
    counts: dict[str, int] = {}
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        speaker_ids: dict[int, int] = {}
        for cid, indices in sorted(cluster_map.items()):
            total_speaking = sum(embeddings[i][1] - embeddings[i][0] for i in indices)
            pct = round(total_speaking / max(1, total_duration_ms) * 100, 2)
            cursor = conn.execute(
                "INSERT INTO speakers"
                " (project_id, label, total_speaking_ms, speaking_pct)"
                " VALUES (?, ?, ?, ?)",
                (project_id, f"speaker_{cid}", total_speaking, pct),
            )
            speaker_ids[cid] = cursor.lastrowid or 0
        counts["speakers"] = len(speaker_ids)
        seg_speaker: dict[int, int] = {}
        for cid, indices in cluster_map.items():
            for idx in indices:
                seg_speaker[idx] = speaker_ids[cid]
        segments = conn.execute(
            "SELECT segment_id, start_ms, end_ms"
            " FROM transcript_segments"
            " WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        ).fetchall()
        updated = 0
        for seg_row in segments:
            best_speaker = speaker_ids.get(0, 1)
            best_overlap = 0
            for idx, (es, ee, _) in enumerate(embeddings):
                overlap = max(0, min(seg_row[2], ee) - max(seg_row[1], es))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = seg_speaker.get(idx, best_speaker)
            conn.execute(
                "UPDATE transcript_segments SET speaker_id = ? WHERE segment_id = ?",
                (best_speaker, seg_row[0]),
            )
            updated += 1
        conn.execute(
            "UPDATE transcript_words SET speaker_id = ("
            "  SELECT ts.speaker_id"
            "  FROM transcript_segments ts"
            "  WHERE ts.segment_id = transcript_words.segment_id"
            ") WHERE segment_id IN ("
            "  SELECT segment_id"
            "  FROM transcript_segments WHERE project_id = ?"
            ")",
            (project_id,),
        )
        conn.commit()
        counts["updated_segments"] = updated
    except Exception as exc:
        conn.rollback()
        raise PipelineError(
            f"Failed to insert speaker results: {exc}", stage_name=STAGE, operation=OPERATION
        ) from exc
    finally:
        conn.close()
    # Insert vec_speakers
    vec_conn = get_connection(db_path, enable_vec=True, dict_rows=False)
    try:
        vec_inserted = 0
        for idx, (start_ms, _end_ms, emb) in enumerate(embeddings):
            sc = next((c for c, ii in cluster_map.items() if idx in ii), 0)
            emb_bytes = struct.pack(f"{len(emb)}f", *emb.tolist())
            try:
                vec_conn.execute(
                    "INSERT INTO vec_speakers"
                    " (project_id, segment_text,"
                    " timestamp_ms, speaker_id,"
                    " speaker_embedding)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        project_id,
                        "",
                        start_ms,
                        speaker_ids.get(sc, 1),
                        emb_bytes,
                    ),
                )
                vec_inserted += 1
            except Exception as ve:
                if vec_inserted == 0:
                    logger.warning("vec_speakers insert failed: %s", ve)
                    break
                raise
        vec_conn.commit()
        counts["vec_speakers"] = vec_inserted
    except Exception as exc:
        logger.warning("vec_speakers inserts failed: %s", exc)
        counts["vec_speakers"] = 0
    finally:
        vec_conn.close()
    return counts


def _insert_fallback_speaker(db_path: Path, project_id: str) -> dict[str, int]:
    """Assign all segments to speaker_0 as fallback."""
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        cursor = conn.execute(
            "INSERT INTO speakers"
            " (project_id, label, total_speaking_ms, speaking_pct)"
            " VALUES (?, ?, 0, 100.0)",
            (project_id, "speaker_0"),
        )
        sid = cursor.lastrowid
        conn.execute(
            "UPDATE transcript_segments SET speaker_id = ? WHERE project_id = ?", (sid, project_id)
        )
        conn.execute(
            "UPDATE transcript_words SET speaker_id = ? WHERE segment_id IN "
            "(SELECT segment_id FROM transcript_segments WHERE project_id = ?)",
            (sid, project_id),
        )
        conn.commit()
        return {"speakers": 1, "fallback": True}
    except Exception as exc:
        conn.rollback()
        logger.error("Fallback speaker insertion failed: %s", exc)
        return {"speakers": 0, "fallback": True}
    finally:
        conn.close()


async def run_speaker_embed(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the speaker diarization pipeline stage.

    Uses Silero VAD + WavLM for speaker embedding extraction and
    clustering. Falls back to assigning all segments to speaker_0.

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
        logger.info("Speaker diarization starting: %s", audio_path)
        audio, sample_rate = await asyncio.to_thread(_load_audio, audio_path)
        total_duration_ms = int(len(audio) / sample_rate * 1000)
        # Detect speech segments
        try:
            speech_segments = await asyncio.to_thread(_detect_speech_vad, audio, sample_rate)
            logger.info("VAD detected %d speech segments", len(speech_segments))
        except (ImportError, RuntimeError) as vad_err:
            logger.warning("Silero VAD failed, using energy fallback: %s", vad_err)
            speech_segments = await asyncio.to_thread(_detect_speech_energy, audio, sample_rate)
        if not speech_segments:
            logger.warning("No speech segments, using fallback speaker")
            await asyncio.to_thread(_insert_fallback_speaker, db_path, project_id)
            return StageResult(
                success=True,
                operation=OPERATION,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        # Extract speaker embeddings
        gpu_device = str(config.get("gpu.device"))
        device = "cuda" if "cuda" in gpu_device else "cpu"
        backend_name = "wavlm"
        try:
            embeddings = await asyncio.to_thread(
                _extract_wavlm_embeddings, audio, sample_rate, speech_segments, device
            )
            logger.info("Extracted %d speaker embeddings", len(embeddings))
        except (ImportError, OSError, RuntimeError) as model_err:
            logger.warning("WavLM failed, fallback to speaker_0: %s", model_err)
            backend_name = "fallback"
            await asyncio.to_thread(_insert_fallback_speaker, db_path, project_id)
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            input_sha = await asyncio.to_thread(sha256_file, audio_path)
            record_provenance(
                db_path=db_path,
                project_id=project_id,
                operation=OPERATION,
                stage=STAGE,
                input_info=InputInfo(
                    file_path=str(audio_path),
                    sha256=input_sha,
                    size_bytes=audio_path.stat().st_size,
                ),
                output_info=OutputInfo(sha256=sha256_string("fallback_speaker_0"), record_count=1),
                model_info=ModelInfo(name="fallback", version="1.0"),
                execution_info=ExecutionInfo(duration_ms=elapsed_ms),
                parent_record_id=None,
                description="Speaker diarization fallback: all segments -> speaker_0",
            )
            return StageResult(success=True, operation=OPERATION, duration_ms=elapsed_ms)
        if not embeddings:
            await asyncio.to_thread(_insert_fallback_speaker, db_path, project_id)
            return StageResult(
                success=True,
                operation=OPERATION,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        cluster_map = await asyncio.to_thread(_cluster_speakers, embeddings)
        num_speakers = len(cluster_map)
        logger.info("Clustered into %d speakers", num_speakers)
        await asyncio.to_thread(
            _insert_results, db_path, project_id, embeddings, cluster_map, total_duration_ms
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        input_sha = await asyncio.to_thread(sha256_file, audio_path)
        summary = json.dumps(
            {
                "speakers": num_speakers,
                "speech_segments": len(speech_segments),
                "embeddings": len(embeddings),
            },
            sort_keys=True,
        )
        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(audio_path), sha256=input_sha, size_bytes=audio_path.stat().st_size
            ),
            output_info=OutputInfo(sha256=sha256_string(summary), record_count=num_speakers),
            model_info=ModelInfo(
                name=backend_name,
                version=MODEL_ID,
                parameters={
                    "embedding_dim": EMBEDDING_DIM,
                    "cluster_threshold": CLUSTER_DISTANCE_THRESHOLD,
                },
            ),
            execution_info=ExecutionInfo(
                duration_ms=elapsed_ms, gpu_device=device if device == "cuda" else None
            ),
            parent_record_id=None,
            description=(
                f"Speaker diarization ({backend_name}): {num_speakers} speakers, "
                f"{len(speech_segments)} segments"
            ),
        )
        logger.info("Speaker diarization complete in %d ms: %d speakers", elapsed_ms, num_speakers)
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
        logger.error("Speaker diarization failed: %s", error_msg)
        return StageResult(success=False, operation=OPERATION, error_message=error_msg)
