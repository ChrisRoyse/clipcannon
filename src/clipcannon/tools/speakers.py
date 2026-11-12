"""MCP tools: who is in the video, who is speaking when, and about what.

Backed by the speaker_tracking stage (face tracks + Light-ASD active speaker +
ECAPA voice clusters + transcript). Persons are anonymous identity clusters
(P0, P1, ...) until labelled with clipcannon_label_person.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from mcp.types import Tool

from clipcannon.tools.understanding import _db_path, _error, _validate_project

SPEAKER_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_get_speakers",
        description=(
            "List the people detected in the video (face identity clusters), with "
            "how long each one speaks, whether their voice was bound to their face, "
            "and an optional thumbnail image of a person. Requires the "
            "speaker_tracking stage."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "min_speaking_ms": {"type": "integer", "default": 0,
                                    "description": "Only people who speak at least this long"},
                "thumbnail_person_id": {"type": "integer",
                                        "description": "Return this person's face as an image"},
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_get_speaker_timeline",
        description=(
            "Who is speaking, when, whether they are on screen, and what they are "
            "talking about: speaker turns with text, salient keywords and whether "
            "the turn is a question, for a time range. Speakers are P<n> (a face "
            "identity, possibly also bound to a voice) or V<n> (an off-screen voice "
            "never seen speaking, e.g. a moderator or phone caller)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "start_ms": {"type": "integer", "default": 0},
                "end_ms": {"type": "integer", "description": "Default: start_ms + 600000"},
                "speaker": {"type": "string",
                            "description": "Filter to one speaker key, e.g. 'P3' or 'V1'"},
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_label_person",
        description="Give a detected person a human-readable name (e.g. 'Reid Wiseman').",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "person_id": {"type": "integer"},
                "label": {"type": "string", "minLength": 1},
            },
            "required": ["project_id", "person_id", "label"],
        },
    ),
]


def _connect(project_id: str) -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path(project_id)))
    con.row_factory = sqlite3.Row
    return con


def _has_tables(con: sqlite3.Connection) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE name='speaker_turns'").fetchone() is not None


_NOT_RUN = ("NOT_ANALYZED", "Speaker tracking has not run for this project "
            "(pipeline stage 'speaker_tracking').")


def _labels(con: sqlite3.Connection, project_id: str) -> dict[int, str]:
    return {r["person_id"]: r["label"] for r in con.execute(
        "SELECT person_id, label FROM persons WHERE project_id=? AND label IS NOT NULL",
        (project_id,))}


def _thumbnail(project_id: str, row: sqlite3.Row) -> dict[str, str] | None:
    import base64
    import subprocess

    con = _connect(project_id)
    try:
        src = con.execute("SELECT source_path FROM project WHERE project_id=?",
                          (project_id,)).fetchone()["source_path"]
    finally:
        con.close()
    x1, y1, x2, y2 = (row["thumb_x1"], row["thumb_y1"], row["thumb_x2"], row["thumb_y2"])
    pad = (y2 - y1) * 0.35
    x, y = max(0, int(x1 - pad)), max(0, int(y1 - pad))
    w, h = int(x2 - x1 + 2 * pad), int(y2 - y1 + 2 * pad)
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{row['thumb_t_ms'] / 1000:.3f}", "-i", str(src),
         "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y},scale=256:-2", "-f", "image2",
         "-c:v", "mjpeg", "-"], capture_output=True, timeout=30)
    if out.returncode != 0 or not out.stdout:
        return None
    return {"data": base64.b64encode(out.stdout).decode(), "mimeType": "image/jpeg"}


async def clipcannon_get_speakers(project_id: str, min_speaking_ms: int = 0,
                                  thumbnail_person_id: int | None = None) -> dict[str, Any]:
    err = _validate_project(project_id)
    if err is not None:
        return err
    con = _connect(project_id)
    try:
        if not _has_tables(con):
            return _error(*_NOT_RUN)
        rows = con.execute(
            "SELECT * FROM persons WHERE project_id=? AND speaking_ms >= ? "
            "ORDER BY speaking_ms DESC, frames DESC", (project_id, min_speaking_ms)).fetchall()
        voices = con.execute(
            "SELECT voice_cluster, SUM(end_ms-start_ms) AS ms, COUNT(*) AS n FROM speaker_turns "
            "WHERE project_id=? AND person_id IS NULL AND voice_cluster IS NOT NULL "
            "GROUP BY voice_cluster ORDER BY ms DESC", (project_id,)).fetchall()
    finally:
        con.close()
    people = [{
        "person_id": r["person_id"], "key": f"P{r['person_id']}", "label": r["label"],
        "speaking_ms": r["speaking_ms"], "on_screen_frames": r["frames"],
        "voice_cluster": r["voice_cluster"], "seen_at_ms": r["thumb_t_ms"],
    } for r in rows]
    result: dict[str, Any] = {
        "project_id": project_id,
        "people": people,
        "off_screen_voices": [{"key": f"V{v['voice_cluster']}", "speaking_ms": v["ms"],
                               "turns": v["n"]} for v in voices],
    }
    if thumbnail_person_id is not None:
        match = [r for r in rows if r["person_id"] == thumbnail_person_id]
        img = _thumbnail(project_id, match[0]) if match else None
        if img is None:
            return _error("NOT_FOUND", f"No thumbnail for person {thumbnail_person_id}")
        result["_image"] = img
    return result


async def clipcannon_get_speaker_timeline(project_id: str, start_ms: int = 0,
                                          end_ms: int | None = None,
                                          speaker: str | None = None) -> dict[str, Any]:
    err = _validate_project(project_id)
    if err is not None:
        return err
    end = end_ms if end_ms is not None else start_ms + 600_000
    con = _connect(project_id)
    try:
        if not _has_tables(con):
            return _error(*_NOT_RUN)
        labels = _labels(con, project_id)
        q = ("SELECT * FROM speaker_turns WHERE project_id=? AND end_ms > ? AND start_ms < ?"
             + (" AND speaker_key = ?" if speaker else "") + " ORDER BY start_ms")
        args: tuple[Any, ...] = (project_id, start_ms, end) + ((speaker,) if speaker else ())
        rows = con.execute(q, args).fetchall()
    finally:
        con.close()
    turns = []
    for r in rows:
        dur = r["end_ms"] - r["start_ms"]
        turns.append({
            "start_ms": r["start_ms"], "end_ms": r["end_ms"], "speaker": r["speaker_key"],
            "label": labels.get(r["person_id"]) if r["person_id"] is not None else None,
            "on_screen": round(r["on_screen_ms"] / dur, 2) if dur > 0 else 0.0,
            "is_question": bool(r["is_question"]),
            "about": json.loads(r["keywords"] or "[]"),
            "text": r["text"] if len(r["text"]) <= 400 else r["text"][:400] + "...",
        })
    return {"project_id": project_id, "start_ms": start_ms, "end_ms": end,
            "turn_count": len(turns), "turns": turns}


async def clipcannon_label_person(project_id: str, person_id: int, label: str) -> dict[str, Any]:
    err = _validate_project(project_id)
    if err is not None:
        return err
    if not label.strip():
        return _error("INVALID_PARAMETER", "label must not be empty")
    con = _connect(project_id)
    try:
        if not _has_tables(con):
            return _error(*_NOT_RUN)
        cur = con.execute("UPDATE persons SET label=? WHERE project_id=? AND person_id=?",
                          (label.strip(), project_id, person_id))
        con.commit()
    finally:
        con.close()
    if cur.rowcount == 0:
        return _error("NOT_FOUND", f"No person {person_id} in project {project_id}")
    return {"project_id": project_id, "person_id": person_id, "label": label.strip()}


async def dispatch_speaker_tool(name: str, arguments: dict[str, object]) -> dict[str, Any]:
    a = arguments
    pid = str(a.get("project_id", ""))
    if name == "clipcannon_get_speakers":
        tp = a.get("thumbnail_person_id")
        return await clipcannon_get_speakers(
            pid, int(a.get("min_speaking_ms", 0) or 0),  # type: ignore[arg-type]
            int(tp) if tp is not None else None)  # type: ignore[arg-type]
    if name == "clipcannon_get_speaker_timeline":
        e = a.get("end_ms")
        return await clipcannon_get_speaker_timeline(
            pid, int(a.get("start_ms", 0) or 0),  # type: ignore[arg-type]
            int(e) if e is not None else None,  # type: ignore[arg-type]
            str(a["speaker"]) if a.get("speaker") else None)
    if name == "clipcannon_label_person":
        return await clipcannon_label_person(
            pid, int(a["person_id"]), str(a["label"]))  # type: ignore[arg-type]
    return _error("UNKNOWN_TOOL", f"Unknown speaker tool: {name}")


__all__ = ["SPEAKER_TOOL_DEFINITIONS", "dispatch_speaker_tool"]
