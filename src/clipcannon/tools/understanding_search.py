"""Content search MCP tool for ClipCannon.

Semantic (vector KNN over the pinned Nomic instrument) and text (SQL LIKE)
search across transcript segments. The two are different instruments: a
semantic request is never answered with text matches (#68). If the semantic
index or instrument is missing, the call is refused with a typed error.
"""

from __future__ import annotations

import json
import logging
import struct
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.pipeline.nomic_native import (
    IDENTITY,
    QUERY_PREFIX,
    SemanticInstrumentError,
    get_encoder,
)
from clipcannon.tools.understanding import _db_path, _error, _validate_project

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_REINDEX = (
    "Re-run the semantic_embed stage for this project (clipcannon_ingest), which "
    "embeds every transcript segment with the pinned instrument; or call again "
    "with search_type='text' if a literal text match is what you want."
)


def _refuse(code: str, message: str, remediation: str, **details: object) -> dict[str, object]:
    err = _error(code, message, dict(details))
    err["error"]["remediation"] = remediation  # type: ignore[index]
    return err


async def clipcannon_search_content(
    project_id: str,
    query: str,
    limit: int = 10,
    search_type: str = "semantic",
) -> dict[str, object]:
    """Search video content by semantic similarity or literal text."""
    if search_type not in ("semantic", "text"):
        return _error(
            "INVALID_PARAMETER",
            f"search_type must be 'semantic' or 'text', got: {search_type}",
        )

    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    db = _db_path(project_id)
    if search_type == "semantic":
        refusal = _check_index(db, project_id)
        if refusal is not None:
            return refusal
        try:
            results = _semantic_search(db, query, limit)
        except SemanticInstrumentError as exc:
            return _refuse(exc.code, str(exc), exc.remediation)
    else:
        results = _text_search(db, project_id, query, limit)

    return {
        "project_id": project_id,
        "query": query,
        "search_type": search_type,
        "result_count": len(results),
        "results": results,
        **({"instrument": IDENTITY.as_dict()} if search_type == "semantic" else {}),
    }


def _check_index(db_path: Path, project_id: str) -> dict[str, object] | None:
    """Refuse unless the stored vectors exist and came from the pinned instrument."""
    conn = get_connection(db_path, enable_vec=True, dict_rows=True)
    try:
        row = fetch_one(conn, "SELECT COUNT(*) AS n FROM vec_semantic WHERE project_id = ?",
                        (project_id,))
        prov = fetch_one(
            conn,
            "SELECT model_parameters FROM provenance WHERE project_id = ? "
            "AND stage = 'nomic_embed' ORDER BY timestamp_utc DESC LIMIT 1",
            (project_id,),
        )
    finally:
        conn.close()
    if not row or int(row["n"]) == 0:
        return _refuse("SEMANTIC_INDEX_MISSING",
                       f"Project {project_id} has no semantic vectors (vec_semantic is empty).",
                       _REINDEX)
    params = json.loads(prov["model_parameters"]) if prov and prov["model_parameters"] else {}
    stored = IDENTITY.from_params(params) if isinstance(params, dict) else None
    if stored != IDENTITY.as_dict():
        return _refuse(
            "SEMANTIC_INDEX_STALE",
            "The stored vectors were not produced by the pinned semantic instrument; "
            "comparing a query against them would mix two instruments.",
            _REINDEX,
            stored_instrument=stored, pinned_instrument=IDENTITY.as_dict(),
        )
    return None


def _semantic_search(db_path: Path, query: str, limit: int) -> list[dict[str, object]]:
    """KNN semantic search via sqlite-vec and the pinned Nomic encoder."""
    emb = get_encoder().encode([QUERY_PREFIX + query])[0]
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
            results.append(
                {
                    "segment_id": row["segment_id"],
                    "timestamp_ms": row["timestamp_ms"],
                    "text": row["transcript_text"],
                    "similarity": round(1.0 - float(row["distance"]), 4),
                    "speaker_id": seg_row.get("speaker_id") if seg_row else None,
                }
            )
        return results
    finally:
        conn.close()


def _text_search(
    db_path: Path,
    project_id: str,
    query: str,
    limit: int,
) -> list[dict[str, object]]:
    """Literal text search using SQL LIKE (only when search_type='text')."""
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT segment_id, start_ms, end_ms, text, speaker_id "
            "FROM transcript_segments "
            "WHERE project_id = ? AND text LIKE ? "
            "ORDER BY start_ms LIMIT ?",
            (project_id, f"%{query}%", limit),
        )
        return [
            {
                "segment_id": r["segment_id"],
                "timestamp_ms": r["start_ms"],
                "text": r["text"],
                "speaker_id": r.get("speaker_id"),
            }
            for r in rows
        ]
    finally:
        conn.close()
