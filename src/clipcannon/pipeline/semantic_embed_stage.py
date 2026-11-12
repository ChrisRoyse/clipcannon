"""The run_semantic_embed stage entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.nomic_native import IDENTITY, SemanticInstrumentError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.semantic_embed_store import (
    EMBEDDING_DIM,
    OPERATION,
    SEARCH_PREFIX,
    STAGE,
    _compute_embeddings,
    _insert_results,
    _load_segments_from_db,
)
from clipcannon.pipeline.semantic_embed_topics import (
    DISTANCE_THRESHOLD,
    _cluster_segments,
    _compute_sentiment,
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


async def run_semantic_embed(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the semantic embedding pipeline stage.

    Loads transcript segments, computes Nomic embeddings, clusters
    into topics, and stores results in the database.

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
        # Load segments from DB
        segments = await asyncio.to_thread(
            _load_segments_from_db,
            db_path,
            project_id,
        )

        if not segments:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No transcript segments found for semantic embedding",
            )

        logger.info(
            "Semantic embedding: processing %d segments",
            len(segments),
        )

        # Compute sentiment per segment
        segment_texts = [str(s["text"]) for s in segments]
        sentiments = await asyncio.to_thread(_compute_sentiment, segment_texts)

        # Update transcript_segments with sentiment
        conn2 = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            # Add sentiment columns on pre-existing DBs (checked, not swallowed)
            cols = {r["name"] for r in conn2.execute(
                "PRAGMA table_info(transcript_segments)").fetchall()}
            if "sentiment" not in cols:
                conn2.execute("ALTER TABLE transcript_segments ADD COLUMN sentiment TEXT")
            if "sentiment_score" not in cols:
                conn2.execute(
                    "ALTER TABLE transcript_segments ADD COLUMN sentiment_score REAL")
            for seg, sent in zip(segments, sentiments, strict=True):
                execute(
                    conn2,
                    "UPDATE transcript_segments SET sentiment = ?, sentiment_score = ? "
                    "WHERE segment_id = ?",
                    (sent["label"], sent["score"], int(seg["segment_id"])),
                )
            conn2.commit()
        finally:
            conn2.close()

        texts = [SEARCH_PREFIX + str(seg.get("text", "")) for seg in segments]
        try:
            embeddings = await asyncio.to_thread(_compute_embeddings, texts)
        except SemanticInstrumentError as exc:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message=f"{exc.code}: {exc} Remediation: {exc.remediation}",
            )

        # Cluster into topics
        topics = await asyncio.to_thread(
            _cluster_segments,
            embeddings,
            segments,
        )

        # Insert results
        counts = await asyncio.to_thread(
            _insert_results,
            db_path,
            project_id,
            segments,
            embeddings,
            topics,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Provenance
        segment_texts = json.dumps(
            [str(s.get("text", "")) for s in segments],
            sort_keys=True,
        )
        input_sha = sha256_string(segment_texts)
        topic_json = json.dumps(topics, sort_keys=True, default=str)
        output_sha = sha256_string(topic_json)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(sha256=input_sha),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=len(segments),
            ),
            model_info=ModelInfo(
                name=IDENTITY.model_id,
                version=IDENTITY.revision,
                parameters={
                    "embedding_dim": EMBEDDING_DIM,
                    "distance_threshold": DISTANCE_THRESHOLD,
                    **IDENTITY.as_params(),
                },
            ),
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Semantic embedding: {len(segments)} segments, "
                f"{len(topics)} topics, "
                f"vec_semantic={counts.get('vec_semantic', 0)}"
            ),
        )

        logger.info(
            "Semantic embedding complete in %d ms: %s",
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
        logger.error("Semantic embedding failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
