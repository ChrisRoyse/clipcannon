"""The run_visual_embed stage entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.frame_utils import frame_timestamp_ms
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.visual_embed_model import _run_embedding_pipeline
from clipcannon.pipeline.visual_embed_scenes import (
    EMBEDDING_DIM,
    OPERATION,
    STAGE,
    _detect_scenes,
    _get_sorted_frames,
    _serialize_embedding,
)
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)


async def run_visual_embed(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute SigLIP visual embedding and scene detection.

    Processes all extracted frames through SigLIP to produce 1152-dim
    embeddings, inserts them into vec_frames, detects scene boundaries,
    and inserts scene records.

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
        frames_dir = project_dir / "frames"
        frame_paths = _get_sorted_frames(frames_dir)
        extraction_fps = int(config.get("processing.frame_extraction_fps"))
        batch_size = int(config.get("processing.batch_size_visual"))
        threshold = float(config.get("processing.scene_change_threshold"))
        device = str(config.get("gpu.device"))
        # Models are pre-cached locally. No HF token needed at runtime.
        hf_token = os.environ.get("HF_TOKEN")

        logger.info(
            "Starting visual embedding: %d frames, batch_size=%d, device=%s",
            len(frame_paths),
            batch_size,
            device,
        )

        # Run model inference in thread pool
        embeddings = await asyncio.to_thread(
            _run_embedding_pipeline,
            frame_paths,
            batch_size,
            hf_token,
            device,
        )

        # Clear old data before inserting (idempotent re-runs).
        # vec0 virtual tables: DROP + recreate is the most reliable cleanup.
        conn = get_connection(db_path, enable_vec=True, dict_rows=True)
        try:
            conn.execute("DROP TABLE IF EXISTS vec_frames")
            conn.execute(
                "CREATE VIRTUAL TABLE vec_frames USING vec0("
                "frame_id INTEGER PRIMARY KEY, "
                "project_id TEXT, "
                "timestamp_ms INTEGER, "
                "frame_path TEXT, "
                "visual_embedding float[1152])"
            )
            conn.commit()
            logger.info("Cleared vec_frames table for re-ingest")
        except Exception as exc:
            logger.warning("vec_frames cleanup failed: %s", exc)
        finally:
            conn.close()

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            conn.execute(
                "DELETE FROM scenes WHERE project_id = ?",
                (project_id,),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("scenes cleanup skipped: %s", exc)
        finally:
            conn.close()

        # Insert embeddings into vec_frames
        conn = get_connection(db_path, enable_vec=True, dict_rows=True)
        try:
            vec_rows: list[tuple[object, ...]] = []
            for idx, (fp, emb) in enumerate(zip(frame_paths, embeddings, strict=False)):
                ts_ms = frame_timestamp_ms(fp, extraction_fps)
                vec_rows.append(
                    (
                        idx + 1,
                        project_id,
                        ts_ms,
                        str(fp),
                        _serialize_embedding(emb),
                    )
                )

            batch_insert(
                conn,
                "vec_frames",
                ["frame_id", "project_id", "timestamp_ms", "frame_path", "visual_embedding"],
                vec_rows,
            )
            conn.commit()
            logger.info("Inserted %d frame embeddings into vec_frames", len(vec_rows))
        finally:
            conn.close()

        # Detect scenes
        scenes = _detect_scenes(frame_paths, embeddings, extraction_fps, threshold)
        logger.info("Detected %d scenes (threshold=%.2f)", len(scenes), threshold)

        # Insert scenes
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            scene_rows: list[tuple[object, ...]] = [
                (
                    project_id,
                    scene["start_ms"],
                    scene["end_ms"],
                    scene["key_frame_path"],
                    scene["key_frame_timestamp_ms"],
                    scene["visual_similarity_avg"],
                    scene["dominant_colors"],
                )
                for scene in scenes
            ]

            batch_insert(
                conn,
                "scenes",
                [
                    "project_id",
                    "start_ms",
                    "end_ms",
                    "key_frame_path",
                    "key_frame_timestamp_ms",
                    "visual_similarity_avg",
                    "dominant_colors",
                ],
                scene_rows,
            )
            conn.commit()
            logger.info("Inserted %d scenes", len(scene_rows))
        finally:
            conn.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build content hash for provenance
        content_repr = f"frames:{len(frame_paths)},scenes:{len(scenes)}"
        content_hash = sha256_string(content_repr)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(frames_dir),
                sha256=sha256_string(
                    "\n".join(f.name for f in frame_paths),
                ),
            ),
            output_info=OutputInfo(
                sha256=content_hash,
                record_count=len(frame_paths),
            ),
            model_info=ModelInfo(
                name="siglip-so400m-patch14-384",
                version="google/siglip-so400m-patch14-384",
                parameters={
                    "embedding_dim": EMBEDDING_DIM,
                    "batch_size": batch_size,
                    "scene_threshold": threshold,
                },
            ),
            execution_info=ExecutionInfo(
                duration_ms=elapsed_ms,
                gpu_device=device,
            ),
            parent_record_id=None,
            description=(
                f"Computed {len(frame_paths)} SigLIP embeddings, detected {len(scenes)} scenes"
            ),
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
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Visual embedding failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
