"""Understanding MCP tools for ClipCannon.

Provides ingest, VUD summary, analytics, and transcript tools. Shared
helpers (_error, _db_path, etc.) are used by understanding_visual.py
and understanding_search.py.
"""

from __future__ import annotations

import logging
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.exceptions import ClipCannonError

logger = logging.getLogger(__name__)

_TRANSCRIPT_PAGE_MS = 900_000  # 15-minute transcript pages
_MAX_SCENES_PER_PAGE = 100


def _error(code: str, message: str, details: dict[str, object] | None = None) -> dict[str, object]:
    """Build standardized error response dict."""
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _projects_dir() -> Path:
    """Resolve projects base directory from config or default."""
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def _db_path(project_id: str) -> Path:
    """Build database path for a project."""
    return _projects_dir() / project_id / "analysis.db"


def _project_dir(project_id: str) -> Path:
    """Build project directory path."""
    return _projects_dir() / project_id


def _validate_project(
    project_id: str, required_status: str | None = "ready"
) -> dict[str, object] | None:
    """Validate project exists and check status. Returns error dict or None."""
    db = _db_path(project_id)
    if not db.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")
    if required_status is not None:
        conn = get_connection(db, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(conn, "SELECT status FROM project WHERE project_id = ?", (project_id,))
        finally:
            conn.close()
        if row is None:
            return _error("PROJECT_NOT_FOUND", f"No project record: {project_id}")
        status = str(row.get("status", ""))
        if required_status == "created" and status != "created":
            return _error(
                "INVALID_STATE", f"Project must be 'created' to ingest, current: {status}"
            )
        if required_status == "ready" and status not in ("ready", "ready_degraded", "analyzing"):
            return _error("INVALID_STATE", f"Project not ready, current status: {status}")
    return None


async def clipcannon_ingest(
    project_id: str, options: dict[str, object] | None = None
) -> dict[str, object]:
    """Run the full analysis pipeline on a created project."""
    err = _validate_project(project_id, required_status="created")
    if err is not None:
        return err

    db = _db_path(project_id)
    proj_dir = _project_dir(project_id)

    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        execute(
            conn,
            "UPDATE project SET status = 'analyzing',"
            " updated_at = datetime('now')"
            " WHERE project_id = ?",
            (project_id,),
        )
        fetch_one(
            conn,
            "SELECT duration_ms FROM project WHERE project_id = ?",
            (project_id,),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        config = ClipCannonConfig.load()
    except ClipCannonError:
        return _error("CONFIG_ERROR", "Failed to load ClipCannon configuration")

    from clipcannon.pipeline.registry import build_pipeline

    orchestrator = build_pipeline(config)

    try:
        result = await orchestrator.run(project_id, db, proj_dir)
    except Exception as exc:
        logger.exception("Pipeline failed for project %s", project_id)
        err_conn = get_connection(db, enable_vec=False, dict_rows=False)
        try:
            execute(
                err_conn,
                "UPDATE project SET status = 'error',"
                " updated_at = datetime('now')"
                " WHERE project_id = ?",
                (project_id,),
            )
            err_conn.commit()
        finally:
            err_conn.close()
        return _error("PIPELINE_ERROR", f"Pipeline failed: {exc}")

    return {
        "project_id": project_id,
        "status": "ready" if result.success else "error",
        "pipeline_success": result.success,
        "total_duration_ms": result.total_duration_ms,
        "stages_completed": len([s for s in result.stage_results.values() if s.success]),
        "stages_failed": len(result.failed_required) + len(result.failed_optional),
        "failed_required": result.failed_required,
        "failed_optional": result.failed_optional,
    }


async def clipcannon_get_vud_summary(project_id: str) -> dict[str, object]:
    """Get compact Video Understanding Document summary (~8K tokens).

    Includes speakers, topics preview, top 5 highlights, reactions,
    beats, content safety, energy, and stream status.
    """
    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        project = fetch_one(conn, "SELECT * FROM project WHERE project_id = ?", (project_id,))
        if project is None:
            return _error("PROJECT_NOT_FOUND", f"No project record: {project_id}")

        speakers = fetch_all(
            conn,
            "SELECT label, total_speaking_ms, speaking_pct"
            " FROM speakers WHERE project_id = ?"
            " ORDER BY speaking_pct DESC",
            (project_id,),
        )

        tc_row = fetch_one(
            conn, "SELECT count(*) as cnt FROM topics WHERE project_id = ?", (project_id,)
        )
        topic_count = int(tc_row["cnt"]) if tc_row else 0
        topic_preview = fetch_all(
            conn,
            "SELECT label, start_ms, end_ms, coherence_score"
            " FROM topics WHERE project_id = ?"
            " ORDER BY start_ms LIMIT 5",
            (project_id,),
        )

        top_highlights = fetch_all(
            conn,
            "SELECT start_ms, end_ms, type, score, reason"
            " FROM highlights WHERE project_id = ?"
            " ORDER BY score DESC LIMIT 5",
            (project_id,),
        )

        reaction_counts = fetch_all(
            conn,
            "SELECT type, count(*) as cnt FROM reactions WHERE project_id = ? GROUP BY type",
            (project_id,),
        )

        beats_row = fetch_one(
            conn,
            "SELECT has_music, source, tempo_bpm,"
            " tempo_confidence, beat_count"
            " FROM beats WHERE project_id = ? LIMIT 1",
            (project_id,),
        )

        safety_row = fetch_one(
            conn,
            "SELECT profanity_count, profanity_density,"
            " content_rating FROM content_safety"
            " WHERE project_id = ? LIMIT 1",
            (project_id,),
        )

        energy_row = fetch_one(
            conn,
            "SELECT avg(energy) as avg_energy FROM emotion_curve WHERE project_id = ?",
            (project_id,),
        )
        avg_energy = (
            round(float(energy_row["avg_energy"]), 4)
            if (energy_row and energy_row.get("avg_energy") is not None)
            else None
        )

        streams = fetch_all(
            conn,
            "SELECT stream_name, status, error_message"
            " FROM stream_status WHERE project_id = ?"
            " ORDER BY stream_name",
            (project_id,),
        )
        failed_streams = [
            {"stream": str(s["stream_name"]), "error": str(s.get("error_message", ""))}
            for s in streams
            if str(s.get("status")) == "failed"
        ]
        stream_summary = {
            "total": len(streams),
            "completed": sum(1 for s in streams if s.get("status") == "completed"),
            "failed": len(failed_streams),
            "skipped": sum(1 for s in streams if s.get("status") == "skipped"),
        }

        prov_row = fetch_one(
            conn, "SELECT count(*) as cnt FROM provenance WHERE project_id = ?", (project_id,)
        )
        prov_count = int(prov_row["cnt"]) if prov_row else 0
    finally:
        conn.close()

    return {
        "project_id": project_id,
        "name": project.get("name"),
        "duration_ms": project.get("duration_ms"),
        "resolution": project.get("resolution"),
        "fps": project.get("fps"),
        "status": project.get("status"),
        "speakers": {"count": len(speakers), "details": [dict(s) for s in speakers]},
        "topics": {"count": topic_count, "preview": [dict(t) for t in topic_preview]},
        "top_highlights": [dict(h) for h in top_highlights],
        "reactions": {str(r["type"]): int(r["cnt"]) for r in reaction_counts},
        "beats": dict(beats_row) if beats_row else None,
        "content_safety": dict(safety_row) if safety_row else None,
        "avg_energy": avg_energy,
        "stream_status": stream_summary,
        "failed_streams": failed_streams if failed_streams else None,
        "provenance_records": prov_count,
    }


async def clipcannon_get_analytics(
    project_id: str, sections: list[str] | None = None
) -> dict[str, object]:
    """Get detailed analytics (~18K tokens). Sections: highlights, scenes,
    topics, reactions, beats, pacing, silence_gaps. Scenes paginated at 100."""
    valid = {"highlights", "scenes", "topics", "reactions", "beats", "pacing", "silence_gaps"}
    if sections is None:
        sections = list(valid)
    else:
        invalid = set(sections) - valid
        if invalid:
            return _error("INVALID_PARAMETER", f"Invalid sections: {invalid}. Valid: {valid}")

    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err

    db = _db_path(project_id)
    result: dict[str, object] = {"project_id": project_id, "sections": sections}
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        if "highlights" in sections:
            rows = fetch_all(
                conn,
                "SELECT * FROM highlights WHERE project_id = ? ORDER BY score DESC",
                (project_id,),
            )
            result["highlights"] = [dict(r) for r in rows]

        if "scenes" in sections:
            tr = fetch_one(
                conn, "SELECT count(*) as cnt FROM scenes WHERE project_id = ?", (project_id,)
            )
            total = int(tr["cnt"]) if tr else 0
            rows = fetch_all(
                conn,
                "SELECT * FROM scenes WHERE project_id = ? ORDER BY start_ms LIMIT ?",
                (project_id, _MAX_SCENES_PER_PAGE),
            )
            result["scenes"] = {
                "total": total,
                "page_size": _MAX_SCENES_PER_PAGE,
                "data": [dict(r) for r in rows],
                "has_more": total > _MAX_SCENES_PER_PAGE,
            }

        if "topics" in sections:
            rows = fetch_all(
                conn, "SELECT * FROM topics WHERE project_id = ? ORDER BY start_ms", (project_id,)
            )
            result["topics"] = [dict(r) for r in rows]

        if "reactions" in sections:
            rows = fetch_all(
                conn,
                "SELECT * FROM reactions WHERE project_id = ? ORDER BY start_ms",
                (project_id,),
            )
            result["reactions"] = [dict(r) for r in rows]

        if "beats" in sections:
            br = fetch_one(conn, "SELECT * FROM beats WHERE project_id = ? LIMIT 1", (project_id,))
            bs = fetch_all(
                conn,
                "SELECT * FROM beat_sections WHERE project_id = ? ORDER BY start_ms",
                (project_id,),
            )
            result["beats"] = {
                "summary": dict(br) if br else None,
                "sections": [dict(r) for r in bs],
            }

        if "pacing" in sections:
            rows = fetch_all(
                conn, "SELECT * FROM pacing WHERE project_id = ? ORDER BY start_ms", (project_id,)
            )
            result["pacing"] = [dict(r) for r in rows]

        if "silence_gaps" in sections:
            rows = fetch_all(
                conn,
                "SELECT * FROM silence_gaps WHERE project_id = ? ORDER BY start_ms",
                (project_id,),
            )
            result["silence_gaps"] = [dict(r) for r in rows]
    finally:
        conn.close()
    return result


async def clipcannon_get_transcript(
    project_id: str, start_ms: int = 0, end_ms: int | None = None
) -> dict[str, object]:
    """Get transcript with word-level timestamps. 15-min pages with pagination."""
    err = _validate_project(project_id, required_status="ready")
    if err is not None:
        return err
    if end_ms is None:
        end_ms = start_ms + _TRANSCRIPT_PAGE_MS

    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        segments = fetch_all(
            conn,
            "SELECT segment_id, start_ms, end_ms, text,"
            " speaker_id, language, word_count"
            " FROM transcript_segments"
            " WHERE project_id = ?"
            " AND start_ms < ? AND end_ms > ?"
            " ORDER BY start_ms",
            (project_id, end_ms, start_ms),
        )

        enriched: list[dict[str, object]] = []
        for seg in segments:
            sd = dict(seg)
            words = fetch_all(
                conn,
                "SELECT word, start_ms, end_ms,"
                " confidence, speaker_id"
                " FROM transcript_words"
                " WHERE segment_id = ?"
                " ORDER BY start_ms",
                (int(seg["segment_id"]),),
            )
            sd["words"] = [dict(w) for w in words]
            enriched.append(sd)

        hm_row = fetch_one(
            conn,
            "SELECT count(*) as cnt"
            " FROM transcript_segments"
            " WHERE project_id = ? AND start_ms >= ?",
            (project_id, end_ms),
        )
        has_more = int(hm_row["cnt"]) > 0 if hm_row else False

        dur_row = fetch_one(
            conn, "SELECT duration_ms FROM project WHERE project_id = ?", (project_id,)
        )
        total_dur = int(dur_row["duration_ms"]) if dur_row else 0
    finally:
        conn.close()

    return {
        "project_id": project_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "total_duration_ms": total_dur,
        "segment_count": len(enriched),
        "segments": enriched,
        "has_more": has_more,
        "next_start_ms": end_ms if has_more else None,
    }
