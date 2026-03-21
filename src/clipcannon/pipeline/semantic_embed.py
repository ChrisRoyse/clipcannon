"""Nomic semantic embedding and topic clustering pipeline stage.

Loads nomic-ai/nomic-embed-text-v1.5 via sentence-transformers to compute
768-dim semantic embeddings for each transcript segment, then clusters
segments into topics using agglomerative clustering with TF-IDF-based
topic label generation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from collections import Counter
from pathlib import Path

import numpy as np

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)

OPERATION = "semantic_embedding"
STAGE = "nomic_embed"
MODEL_ID = "nomic-ai/nomic-embed-text-v1.5"
EMBEDDING_DIM = 768
SEARCH_PREFIX = "search_document: "

# Clustering parameters
DISTANCE_THRESHOLD = 1.2
MIN_CLUSTER_SIZE = 1

# Stop words for keyword extraction
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "because", "but", "and", "or", "if", "while", "that", "this", "these",
    "those", "it", "its", "i", "me", "my", "we", "our", "you", "your",
    "he", "him", "his", "she", "her", "they", "them", "their", "what",
    "which", "who", "whom", "about", "up", "like", "also", "well",
    "really", "right", "going", "know", "think", "get", "got", "go",
    "yeah", "okay", "um", "uh", "oh",
})


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
    """Compute Nomic embeddings for texts.

    Args:
        texts: List of texts to embed (already prefixed).

    Returns:
        Array of shape (len(texts), 768) with L2-normalized embeddings.
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_ID, trust_remote_code=True)
    embeddings = model.encode(texts, show_progress_bar=False)
    emb_array = np.array(embeddings, dtype=np.float32)

    # L2 normalize
    norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-10)
    emb_array = emb_array / norms

    del model
    return emb_array


def _extract_keywords(
    texts: list[str],
    top_k: int = 5,
) -> list[str]:
    """Extract top keywords from a list of texts using word frequency.

    Args:
        texts: List of segment texts.
        top_k: Number of top keywords to return.

    Returns:
        List of top keywords.
    """
    word_counts: Counter[str] = Counter()
    for text in texts:
        words = text.lower().split()
        for word in words:
            cleaned = word.strip(".,!?;:\"'()-")
            if len(cleaned) > 2 and cleaned not in _STOP_WORDS:
                word_counts[cleaned] += 1

    return [word for word, _ in word_counts.most_common(top_k)]


def _cluster_segments(
    embeddings: np.ndarray,
    segments: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Cluster segments into topics using agglomerative clustering.

    Args:
        embeddings: L2-normalized embeddings array (N, 768).
        segments: List of segment dicts.

    Returns:
        List of topic dicts with label, start_ms, end_ms, etc.
    """
    from sklearn.cluster import AgglomerativeClustering

    if len(segments) <= 1:
        # Single segment = single topic
        seg = segments[0]
        text = str(seg.get("text", ""))
        keywords = _extract_keywords([text], top_k=3)
        return [{
            "start_ms": int(seg.get("start_ms", 0)),
            "end_ms": int(seg.get("end_ms", 0)),
            "label": ", ".join(keywords) if keywords else "topic_0",
            "keywords": json.dumps(keywords),
            "coherence_score": 1.0,
            "semantic_density": 1.0,
        }]

    # Determine number of clusters
    n_segments = len(segments)
    max_clusters = max(1, min(n_segments, n_segments // 3 + 1))

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=DISTANCE_THRESHOLD,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)

    # Group segments by cluster
    cluster_map: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        cluster_map.setdefault(int(label), []).append(idx)

    topics: list[dict[str, object]] = []
    for cluster_id, indices in sorted(cluster_map.items()):
        cluster_segments = [segments[i] for i in indices]
        cluster_embeddings = embeddings[indices]
        cluster_texts = [str(s.get("text", "")) for s in cluster_segments]

        # Time range
        start_ms = min(int(s.get("start_ms", 0)) for s in cluster_segments)
        end_ms = max(int(s.get("end_ms", 0)) for s in cluster_segments)

        # Keywords
        keywords = _extract_keywords(cluster_texts, top_k=5)
        label = ", ".join(keywords[:3]) if keywords else f"topic_{cluster_id}"

        # Coherence: average pairwise cosine similarity within cluster
        if len(cluster_embeddings) > 1:
            sim_matrix = cluster_embeddings @ cluster_embeddings.T
            n = len(cluster_embeddings)
            mask = np.ones((n, n), dtype=bool)
            np.fill_diagonal(mask, False)
            coherence = float(np.mean(sim_matrix[mask]))
        else:
            coherence = 1.0

        # Semantic density: mean distance from centroid
        centroid = np.mean(cluster_embeddings, axis=0)
        distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
        density = float(1.0 / (1.0 + np.mean(distances)))

        topics.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "label": label,
            "keywords": json.dumps(keywords),
            "coherence_score": round(coherence, 4),
            "semantic_density": round(density, 4),
        })

    return topics


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
                conn, "topics",
                ["project_id", "start_ms", "end_ms", "label",
                 "keywords", "coherence_score", "semantic_density"],
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
            _load_segments_from_db, db_path, project_id,
        )

        if not segments:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No transcript segments found for semantic embedding",
            )

        logger.info(
            "Semantic embedding: processing %d segments", len(segments),
        )

        # Prepare texts with search prefix
        texts = [
            SEARCH_PREFIX + str(seg.get("text", ""))
            for seg in segments
        ]

        # Compute embeddings
        try:
            embeddings = await asyncio.to_thread(_compute_embeddings, texts)
        except ImportError as imp_err:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message=f"sentence-transformers not available: {imp_err}",
            )

        # Cluster into topics
        topics = await asyncio.to_thread(
            _cluster_segments, embeddings, segments,
        )

        # Insert results
        counts = await asyncio.to_thread(
            _insert_results, db_path, project_id,
            segments, embeddings, topics,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Provenance
        segment_texts = json.dumps(
            [str(s.get("text", "")) for s in segments], sort_keys=True,
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
                name="nomic-embed-text",
                version="v1.5",
                parameters={
                    "embedding_dim": EMBEDDING_DIM,
                    "distance_threshold": DISTANCE_THRESHOLD,
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
            "Semantic embedding complete in %d ms: %s", elapsed_ms, counts,
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
