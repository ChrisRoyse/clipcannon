"""Segment loading, Nomic embedding computation and result storage."""

from __future__ import annotations

import json
import logging
import struct
from typing import TYPE_CHECKING

import numpy as np

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all
from clipcannon.exceptions import PipelineError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

OPERATION = "semantic_embedding"
STAGE = "nomic_embed"
MODEL_ID = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIM = 768
SEARCH_PREFIX = "search_document: "


def _load_segments_from_db(
    db_path: Path,
    project_id: str,
) -> list[dict[str, object]]:
    """Load transcript segments from the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of segment dicts with segment_id, start_ms, end_ms, text.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT segment_id, start_ms, end_ms, text "
            "FROM transcript_segments WHERE project_id = ? "
            "ORDER BY start_ms",
            (project_id,),
        )
        return rows
    finally:
        conn.close()


def _compute_embeddings(
    texts: list[str],
) -> np.ndarray:
    """Compute Nomic embeddings for texts via subprocess.

    Runs SentenceTransformer in a fresh process to avoid state corruption
    (tuple assignment errors) in long-running MCP server processes.

    Args:
        texts: List of texts to embed (already prefixed).

    Returns:
        Array of shape (len(texts), 768) with L2-normalized embeddings.
    """
    import subprocess
    import tempfile

    worker_script = r'''
import json, sys
import numpy as np

with open(sys.argv[1], "r") as f:
    texts = json.load(f)
model_id = sys.argv[2]

import torch
from sentence_transformers import SentenceTransformer

device = "cuda:0" if torch.cuda.is_available() else "cpu"
model = SentenceTransformer(model_id, trust_remote_code=True, device=device)
embeddings = model.encode(texts, show_progress_bar=False, device=device)
emb_array = np.array(embeddings, dtype=np.float32)

# L2 normalize
norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
norms = np.maximum(norms, 1e-10)
emb_array = (emb_array / norms).tolist()

json.dump(emb_array, sys.stdout)
'''

    tmp_texts = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="nomic_texts_", delete=False,
    )
    try:
        json.dump(texts, tmp_texts)
        tmp_texts.close()

        proc = subprocess.run(
            ["python3", "-c", worker_script, tmp_texts.name, MODEL_ID],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"Nomic subprocess failed (rc={proc.returncode}): "
                f"{proc.stderr[-300:] if proc.stderr else 'no stderr'}"
            )

        emb_list = json.loads(proc.stdout)
        emb_array = np.array(emb_list, dtype=np.float32)
        logger.info("Computed %d semantic embeddings via subprocess", len(emb_array))

    finally:
        import os
        os.unlink(tmp_texts.name)

    return emb_array


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
    segments: list[dict[str, object]],
    embeddings: np.ndarray,
    topics: list[dict[str, object]],
) -> dict[str, int]:
    """Insert semantic embeddings and topics into the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        segments: Transcript segment dicts.
        embeddings: Embedding array (N, 768).
        topics: Topic dicts.

    Returns:
        Dict with counts of inserted records per table.
    """
    counts: dict[str, int] = {}

    # Insert into vec_semantic (needs vec extension)
    vec_conn = get_connection(db_path, enable_vec=True, dict_rows=False)
    try:
        vec_inserted = 0
        for i, seg in enumerate(segments):
            emb_bytes = _pack_embedding(embeddings[i])
            try:
                vec_conn.execute(
                    "INSERT INTO vec_semantic "
                    "(segment_id, project_id, timestamp_ms, "
                    "transcript_text, semantic_embedding) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        int(seg.get("segment_id", i)),
                        project_id,
                        int(seg.get("start_ms", 0)),
                        str(seg.get("text", "")),
                        emb_bytes,
                    ),
                )
                vec_inserted += 1
            except Exception as vec_err:
                if vec_inserted == 0:
                    logger.warning(
                        "vec_semantic insert failed (sqlite-vec may not be loaded): %s",
                        vec_err,
                    )
                    break
                raise
        vec_conn.commit()
        counts["vec_semantic"] = vec_inserted
    except Exception as exc:
        logger.warning("vec_semantic inserts failed: %s", exc)
        counts["vec_semantic"] = 0
    finally:
        vec_conn.close()

    # Insert topics into core table
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        if topics:
            topic_rows: list[tuple[object, ...]] = [
                (
                    project_id,
                    int(t["start_ms"]),
                    int(t["end_ms"]),
                    str(t["label"]),
                    str(t.get("keywords", "[]")),
                    float(t.get("coherence_score", 0.0)),
                    float(t.get("semantic_density", 0.0)),
                )
                for t in topics
            ]
            batch_insert(
                conn,
                "topics",
                [
                    "project_id",
                    "start_ms",
                    "end_ms",
                    "label",
                    "keywords",
                    "coherence_score",
                    "semantic_density",
                ],
                topic_rows,
            )
        counts["topics"] = len(topics)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise PipelineError(
            f"Failed to insert semantic results: {exc}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
    finally:
        conn.close()

    return counts
