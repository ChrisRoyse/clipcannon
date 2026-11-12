"""FSV: persisted speaker-tracking state is consistent, the MCP tools report exactly
what is stored, labels write through, and speaker framing keeps the person who is
speaking inside the crop window.

Source of truth: the project's analysis.db (persons, face_tracks, face_detections,
speaker_segments, speaker_turns), read with sqlite3 independently of the tools.

Corpus: a project on which the speaker_tracking stage already ran on real footage
(default: the 61-minute NASA Artemis II press conference, proj_31a990b2). The
framing boundary uses a 40 s window with a reporter question, then two astronauts
answering across a cut: the smallest real span with a speaker change, a cut and an
off-camera voice. The whole-table checks are full-population because the claim is
integrity of the stored state, and they are cheap (one indexed scan each).

    python scripts/fsv/fsv_speaker_state.py [--project proj_x] [--window 1808000:1848000]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from kit import Run

from clipcannon.editing.speaker_framing import compute_tracked_framing
from clipcannon.tools.speakers import (
    clipcannon_get_speaker_timeline,
    clipcannon_get_speakers,
    clipcannon_label_person,
)

PROJECTS = Path.home() / ".clipcannon" / "projects"


def table_digest(con: sqlite3.Connection, table: str, pid: str) -> str:
    rows = con.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY 2", (pid,)).fetchall()
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


def one(con: sqlite3.Connection, sql: str, *args: object) -> object:
    return con.execute(sql, args).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="proj_31a990b2")
    ap.add_argument("--window", default="1808000:1848000")
    args, _ = ap.parse_known_args()
    pid = args.project
    w0, w1 = (int(x) for x in args.window.split(":"))
    db = PROJECTS / pid / "analysis.db"
    run = Run("speaker-state", issue=67, source_of_truth=str(db),
              claim="speaker-tracking state is consistent; tools return what is stored; "
                    "labels persist; framing keeps the active speaker in frame",
              corpus=f"{pid} (real footage, stage already run); framing window {w0}-{w1} ms",
              why_minimal="integrity is a whole-table claim; framing needs only one real "
                          "window with a speaker change, a cut and an off-camera voice")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    counts = {t: one(con, f"SELECT COUNT(*) FROM {t} WHERE project_id=?", pid) for t in
              ("face_shots", "face_tracks", "face_detections", "persons",
               "speaker_segments", "speaker_turns")}
    orphans = {
        "segment_person": one(con, "SELECT COUNT(*) FROM speaker_segments s WHERE project_id=? "
                              "AND person_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM persons p "
                              "WHERE p.project_id=s.project_id AND p.person_id=s.person_id)", pid),
        "track_shot": one(con, "SELECT COUNT(*) FROM face_tracks t WHERE project_id=? AND NOT "
                          "EXISTS (SELECT 1 FROM face_shots s WHERE s.project_id=t.project_id "
                          "AND s.shot_id=t.shot_id)", pid),
        "detection_track": one(con, "SELECT COUNT(*) FROM face_detections d WHERE project_id=? "
                               "AND NOT EXISTS (SELECT 1 FROM face_tracks t WHERE "
                               "t.project_id=d.project_id AND t.track_id=d.track_id)", pid),
    }
    turns = con.execute("SELECT start_ms, end_ms FROM speaker_turns WHERE project_id=? "
                        "ORDER BY start_ms", (pid,)).fetchall()
    overlaps = sum(1 for a, b in zip(turns, turns[1:], strict=False) if b[0] < a[1])
    run.check("stored_state_integrity", all(counts.values()) and not any(orphans.values())
              and overlaps == 0, after={"rows": counts, "orphans": orphans,
                                        "overlapping_turns": overlaps})

    tool = asyncio.run(clipcannon_get_speaker_timeline(pid, start_ms=w0, end_ms=w1))
    sql = con.execute("SELECT start_ms, end_ms, speaker_key FROM speaker_turns WHERE project_id=? "
                      "AND end_ms > ? AND start_ms < ? ORDER BY start_ms", (pid, w0, w1)).fetchall()
    labels = dict(con.execute("SELECT person_id, label FROM persons WHERE project_id=?", (pid,)))
    tool_rows = [(t["start_ms"], t["end_ms"], t["speaker"]) for t in tool.get("turns", [])]
    run.check("timeline_tool_equals_sql", tool_rows == [tuple(r) for r in sql] and tool_rows,
              after={"tool": tool_rows, "sql": sql,
                     "labels": [t["label"] for t in tool.get("turns", [])]})

    people = asyncio.run(clipcannon_get_speakers(pid))
    sql_people = [r[0] for r in con.execute("SELECT person_id FROM persons WHERE project_id=? "
                                            "ORDER BY speaking_ms DESC, frames DESC", (pid,))]
    run.check("speakers_tool_equals_sql",
              [p["person_id"] for p in people.get("people", [])] == sql_people,
              after={"tool_n": len(people.get("people", [])), "sql_n": len(sql_people)})

    # Label write-through: before -> set -> independent read -> restore -> read.
    target = sql_people[0]
    before = labels.get(target)
    asyncio.run(clipcannon_label_person(pid, target, "FSV probe label"))
    during = one(con, "SELECT label FROM persons WHERE project_id=? AND person_id=?", pid, target)
    asyncio.run(clipcannon_label_person(pid, target, before or f"P{target}"))
    after = one(con, "SELECT label FROM persons WHERE project_id=? AND person_id=?", pid, target)
    run.check("label_writes_through_and_restores", during == "FSV probe label" and after == before,
              before=before, during=during, after=after)

    digest_before = table_digest(con, "persons", pid)
    run.refuses("label_unknown_person", lambda: asyncio.run(
        clipcannon_label_person(pid, 999_999, "x")), "NOT_FOUND")
    run.refuses("label_empty", lambda: asyncio.run(
        clipcannon_label_person(pid, target, "  ")), "INVALID_PARAMETER")
    run.refuses("unknown_project", lambda: asyncio.run(
        clipcannon_get_speaker_timeline("proj_does_not_exist")), "PROJECT_NOT_FOUND")
    run.check("refusals_mutate_nothing", table_digest(con, "persons", pid) == digest_before,
              before=digest_before, after=table_digest(con, "persons", pid))

    framing = compute_tracked_framing(db, pid, w0, w1, source_size=(1920, 1080),
                                      canvas_size=(1080, 1920))
    inside = total = 0
    misses = []
    for piece in framing.pieces if framing else []:
        for t, x, _y in piece.keyframes:
            seg = con.execute("SELECT person_id FROM speaker_segments WHERE project_id=? AND "
                              "start_ms<=? AND end_ms>? AND person_id IS NOT NULL", (pid, t, t)
                              ).fetchone()
            if seg is None:
                continue
            face = con.execute(
                "SELECT (d.x1+d.x2)/2 FROM face_detections d JOIN face_tracks k ON "
                "k.project_id=d.project_id AND k.track_id=d.track_id WHERE d.project_id=? AND "
                "k.person_id=? AND d.t_ms BETWEEN ? AND ? ORDER BY ABS(d.t_ms-?) LIMIT 1",
                (pid, seg[0], t - 100, t + 100, t)).fetchone()
            if face is None:
                continue  # speaker not on screen at t (cutaway): nothing to keep in frame
            total += 1
            if x <= face[0] <= x + piece.width:
                inside += 1
            else:
                misses.append({"t_ms": t, "person": seg[0], "face_cx": face[0],
                               "window": [x, x + piece.width]})
    run.check("framing_keeps_on_screen_speaker", total >= 10 and inside / total >= 0.95,
              after={"keyframes_with_visible_speaker": total, "inside": inside,
                     "pieces": len(framing.pieces) if framing else 0, "misses": misses[:10]})
    con.close()
    return run.finish(limitations=[
        "attribution correctness itself (right person speaking) was checked by eye on 36 "
        "random moments in the original run; this probe checks consistency, not ground truth",
        "keyframes sampled as stored after simplification, not every rendered frame"])


if __name__ == "__main__":
    sys.exit(main())
