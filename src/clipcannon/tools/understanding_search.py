"""Content search MCP tool for ClipCannon.

Provides semantic (vector KNN) and text (SQL LIKE) search across
transcript segments in a project database.
"""
from __future__ import annotations

import logging
from pathlib import Path

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.understanding import _db_path, _error, _validate_project

logger = logging.getLogger(__name__)


async def clipcannon_search_content(
    project_id: str,
    query: str,
    limit: int = 10,
    search_type: str = "semantic",
) -> dict[str, object]:
    """Search video content by text or semantic similarity.

    Falls back to SQL LIKE search if vector search is unavailable.

    Args:
        project_id: Project identifier.
        query: Search query string.
        limit: Maximum results to return.
        search_type: "semantic" or "text".

    Returns:
        Search results with matching segments.
    """
    if search_type not in ("semantic", "text"):
        return _error(
            "INVALID_PARAMETER",
            f"search_type must be 'semantic' or 'text', got: {search_type}",
        )

    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    db = _db_path(project_id)
    results: list[dict[str, object]] = []
    actual_type = search_type

    if search_type == "semantic":
        try:
            results = await _semantic_search(db, project_id, query, limit)
        except Exception as vec_err:
            logger.warning("Semantic search unavailable, using text: %s", vec_err)
            actual_type = "text"
            results = await _text_search(db, project_id, query, limit)
    else:
        results = await _text_search(db, project_id, query, limit)

    return {
        "project_id": project_id,
        "query": query,
        "search_type": actual_type,
        "result_count": len(results),
        "results": results,
    }


async def _semantic_search(
    db_path: Path,
    project_id: str,
    query: str,
    limit: int,
) -> list[dict[str, object]]:
    """KNN semantic search via sqlite-vec and Nomic embeddings."""
    import struct
    import numpy as np
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        "nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True,
    )
    query_embedding = model.encode(
        [f"search_query: {query}"], show_progress_bar=False,
    )
    emb = np.array(query_embedding[0], dtype=np.float32)
    norm = np.linalg.norm(emb)
    if norm > 1e-10:
        emb = emb / norm
    query_bytes = struct.pack(f"{len(emb)}f", *emb.tolist())

    conn = get_connection(db_path, enable_vec=True, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT segment_id, timestamp_ms, transcript_text, distance "
            "FROM vec_semantic "
            "WHERE semantic_embedding MATCH ? AND k = ? "
            "ORDER BY distance",
            (query_bytes, limit),
        )
        results: list[dict[str, object]] = []
        for row in rows:
            seg_row = fetch_one(
                conn,
                "SELECT speaker_id FROM transcript_segments WHERE segment_id = ?",
                (int(row["segment_id"]),),
            )
            results.append({
                "segment_id": row["segment_id"],
                "timestamp_ms": row["timestamp_ms"],
                "text": row["transcript_text"],
                "similarity": round(1.0 - float(row["distance"]), 4),
                "speaker_id": seg_row.get("speaker_id") if seg_row else None,
            })
        return results
    finally:
        conn.close()
        del model


async def _text_search(
    db_path: Path,
    project_id: str,
    query: str,
    limit: int,
) -> list[dict[str, object]]:
    """Fallback text search using SQL LIKE."""
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        pattern = f"%{query}%"
        rows = fetch_all(
            conn,
            "SELECT segment_id, start_ms, end_ms, text, speaker_id "
            "FROM transcript_segments "
            "WHERE project_id = ? AND text LIKE ? "
            "ORDER BY start_ms LIMIT ?",
            (project_id, pattern, limit),
        )
        return [
            {
                "segment_id": r["segment_id"],
                "timestamp_ms": r["start_ms"],
                "text": r["text"],
                "similarity": 1.0,
                "speaker_id": r.get("speaker_id"),
            }
            for r in rows
        ]
    finally:
        conn.close()
