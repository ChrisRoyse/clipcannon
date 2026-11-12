"""Emotion result storage and the run_emotion_embed stage entry point."""

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
from clipcannon.pipeline.emotion_embed_audio import (
    EMBEDDING_DIM,
    MODEL_ID,
    OPERATION,
    STAGE,
    STRIDE_S,
    WINDOW_S,
    _load_audio,
    _segment_audio,
)
from clipcannon.pipeline.emotion_embed_model import _compute_emotion_model
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

    # Insert into vec_emotion (vector table). A failure here means the
    # embeddings are LOST — that is a broken state, so we RAISE rather than
    # swallow it and report a misleading count of 0.
    vec_conn = get_connection(db_path, enable_vec=True, dict_rows=False)
    try:
        vec_inserted = 0
        for r in results:
            emb = r.get("embedding")
            if not isinstance(emb, np.ndarray):
                raise PipelineError(
                    f"Missing/invalid emotion embedding for window "
                    f"{r.get('start_ms')}-{r.get('end_ms')} ms; refusing to "
                    "persist an incomplete emotion vector set.",
                    stage_name=STAGE,
                    operation=OPERATION,
                )
            emb_bytes = _pack_embedding(emb)
            vec_conn.execute(
                "INSERT INTO vec_emotion "
                "(project_id, start_ms, end_ms, emotion_embedding) "
                "VALUES (?, ?, ?, ?)",
                (project_id, int(r["start_ms"]), int(r["end_ms"]), emb_bytes),
            )
            vec_inserted += 1
        vec_conn.commit()
        counts["vec_emotion"] = vec_inserted
    except Exception as exc:
        vec_conn.rollback()
        raise PipelineError(
            f"vec_emotion insert FAILED — {len(results)} embeddings would be "
            f"LOST. sqlite-vec may not be loaded, or the embedding dim "
            f"({EMBEDDING_DIM}) does not match the vec0 table. Original error: "
            f"{type(exc).__name__}: {exc}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
    finally:
        vec_conn.close()

    if counts.get("vec_emotion", 0) != counts.get("emotion_curve", 0):
        raise PipelineError(
            f"Row-count mismatch: emotion_curve={counts.get('emotion_curve')} "
            f"vs vec_emotion={counts.get('vec_emotion')}. Every scalar row must "
            "have a matching embedding.",
            stage_name=STAGE,
            operation=OPERATION,
        )

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

        # Grounded dimensional-SER analysis. NO fallback: if the model cannot
        # be loaded or run, fail with full diagnostics so the operator can fix
        # the real problem (missing pre-cached model, OOM, etc.). A silent
        # placeholder would make this instrument contribute ~0 bits.
        gpu_device = str(config.get("gpu.device"))
        device = "cuda" if "cuda" in gpu_device else "cpu"
        backend_name = "wav2vec2_msp_dim"

        try:
            results = await asyncio.to_thread(
                _compute_emotion_model,
                segments,
                device,
            )
            logger.info("Dimensional SER emotion analysis succeeded")
        except PipelineError:
            raise
        except Exception as model_err:
            raise PipelineError(
                f"Emotion SER model '{MODEL_ID}' failed on device '{device}': "
                f"{type(model_err).__name__}: {model_err}. "
                "Ensure the model is pre-cached (no runtime downloads) and that "
                "VRAM is available. This stage has no fallback by design.",
                stage_name=STAGE,
                operation=OPERATION,
            ) from model_err

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
                version=MODEL_ID,
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
