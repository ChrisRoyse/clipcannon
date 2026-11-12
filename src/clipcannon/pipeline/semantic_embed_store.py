"""Segment loading, Nomic embedding computation and result storage."""

from __future__ import annotations

import logging
import struct
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.nomic_native import (
    DOC_PREFIX,
    EMBEDDING_DIM,
    IDENTITY,
    MODEL_ID,
    NomicEncoder,
)

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np

logger = logging.getLogger(__name__)

OPERATION = "semantic_embedding"
STAGE = "nomic_embed"
SEARCH_PREFIX = DOC_PREFIX

__all__ = [
    "EMBEDDING_DIM", "IDENTITY", "MODEL_ID", "OPERATION", "SEARCH_PREFIX", "STAGE",
    "_compute_embeddings", "_insert_results", "_load_segments_from_db", "_pack_embedding",
]


def _load_segments_from_db(
    db_path: Path,
    project_id: str,
) -> list[dict[str, object]]:
    """Load transcript segments (segment_id, start_ms, end_ms, text), ordered by time."""
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        return fetch_all(
            conn,
            "SELECT segment_id, start_ms, end_ms, text "
            "FROM transcript_segments WHERE project_id = ? "
            "ORDER BY start_ms",
            (project_id,),
        )
    finally:
        conn.close()


def _compute_embeddings(texts: list[str]) -> np.ndarray:
    """Embed already-prefixed texts with the pinned native Nomic instrument.

    Returns an (N, 768) float32 array of L2-normalised vectors. Raises
    ``SemanticInstrumentError`` (typed code + remediation) if the pinned
    instrument cannot be loaded; there is no substitute embedder.
    """
    import torch

    encoder = NomicEncoder()
    try:
        emb = encoder.encode(texts)
    finally:
        del encoder
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    logger.info("Computed %d semantic embeddings (%s)", len(emb), IDENTITY.runtime)
    return emb


def _pack_embedding(embedding: np.ndarray) -> bytes:
    """Pack a float32 embedding into bytes for sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding.tolist())


def _insert_results(
    db_path: Path,
    project_id: str,
    segments: list[dict[str, object]],
    embeddings: np.ndarray,
    topics: list[dict[str, object]],
) -> dict[str, int]:
    """Replace this project's semantic vectors and topics in one transaction.

    Any failure (including sqlite-vec not loading) rolls back and raises
    ``PipelineError``; nothing is half-written and nothing is reported as
    stored that was not.
    """
    if len(segments) != len(embeddings):
        raise PipelineError(
            f"{len(segments)} segments but {len(embeddings)} embeddings",
            stage_name=STAGE, operation=OPERATION,
        )
    conn = get_connection(db_path, enable_vec=True, dict_rows=False)
    try:
        conn.execute("DELETE FROM vec_semantic WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM topics WHERE project_id = ?", (project_id,))
        for i, seg in enumerate(segments):
            conn.execute(
                "INSERT INTO vec_semantic "
                "(segment_id, project_id, timestamp_ms, "
                "transcript_text, semantic_embedding) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    int(seg["segment_id"]),
                    project_id,
                    int(seg["start_ms"]),
                    str(seg["text"]),
                    _pack_embedding(embeddings[i]),
                ),
            )
        if topics:
            batch_insert(
                conn,
                "topics",
                ["project_id", "start_ms", "end_ms", "label", "keywords",
                 "coherence_score", "semantic_density"],
                [
                    (
                        project_id, int(t["start_ms"]), int(t["end_ms"]), str(t["label"]),
                        str(t.get("keywords", "[]")),
                        float(t.get("coherence_score", 0.0)),
                        float(t.get("semantic_density", 0.0)),
                    )
                    for t in topics
                ],
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise PipelineError(
            f"Failed to store semantic results: {exc}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
    finally:
        conn.close()
    return {"vec_semantic": len(segments), "topics": len(topics)}
