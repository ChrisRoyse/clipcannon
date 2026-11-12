"""FSV: a render that asks for speaker framing on a project where speaker tracking
never ran is refused with SPEAKER_TRACKING_MISSING before any state changes,
instead of quietly rendering a centre crop.

Source of truth: the edits row (status, render_id) and the renders table in the
project's analysis.db, plus the project's renders/ directory listing.

Corpus: a probe-owned copy of a real project's analysis.db (default
proj_31a990b2) re-keyed to a new project id, with the speaker_tracking tables
dropped. A copy is the minimum: the claim is about a project state (stage never
ran) that the real project no longer has, and the real project must not be
mutated. The copy is deleted at the end; its digests stay in the report.

    python scripts/fsv/fsv_framing_refusal.py [--project proj_x]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from kit import Run, sha256_file

from clipcannon.tools.rendering_render import clipcannon_render

PROJECTS = Path.home() / ".clipcannon" / "projects"
TRACKING = ("face_shots", "face_tracks", "face_detections", "persons",
            "speaker_segments", "speaker_turns")


def state(db: Path, pid: str, edit_id: str) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        status, render_id = con.execute(
            "SELECT status, render_id FROM edits WHERE edit_id=?", (edit_id,)).fetchone()
        renders = con.execute("SELECT COUNT(*) FROM renders WHERE project_id=?",
                              (pid,)).fetchone()[0]
    finally:
        con.close()
    rdir = db.parent / "renders"
    return {"status": status, "render_id": render_id, "renders_rows": renders,
            "render_dirs": sorted(p.name for p in rdir.iterdir()) if rdir.exists() else []}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="proj_31a990b2")
    args, _ = ap.parse_known_args()
    src_db = PROJECTS / args.project / "analysis.db"
    pid = "proj_fsvnospk"
    work = PROJECTS / pid
    run = Run("framing-refusal", issue=67, source_of_truth="edits/renders rows of the copy",
              claim="speaker framing on a project without speaker tracking is refused "
                    "before any state change",
              corpus=f"re-keyed copy of {args.project}/analysis.db without tracking tables",
              why_minimal="the claimed state (stage never ran) does not exist in the real "
                          "project and the real project must not be mutated")
    if work.exists():
        raise SystemExit(f"{work} exists; refusing to overwrite a project dir")
    work.mkdir()
    try:
        db = work / "analysis.db"
        shutil.copy2(src_db, db)
        con = sqlite3.connect(db)
        for t in TRACKING:
            con.execute(f"DROP TABLE IF EXISTS {t}")
        for (table,) in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND sql NOT LIKE 'CREATE VIRTUAL TABLE%'").fetchall():  # vec0 needs sqlite-vec
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({table})")]
            if "project_id" in cols:
                con.execute(f"UPDATE {table} SET project_id=?", (pid,))
        edits = con.execute("SELECT edit_id, edl_json FROM edits").fetchall()
        con.commit()
        con.close()
        tracked = next(e for e, j in edits
                       if (c := json.loads(j).get("crop", {})).get("face_tracking")
                       and c.get("mode") == "auto" and c.get("layout", "crop") == "crop")
        run.meta["copy_sha256_before"] = sha256_file(db)

        before = state(db, pid, tracked)
        res = asyncio.run(clipcannon_render(pid, tracked))
        after = state(db, pid, tracked)
        code = (res.get("error") or {}).get("code")
        run.check("tracking_missing_refused", code == "SPEAKER_TRACKING_MISSING",
                  action={"render": tracked}, got=res.get("error"))
        run.check("refusal_changed_no_state", before == after, before=before, after=after)
        run.check("refusal_names_remediation",
                  bool((res.get("error") or {}).get("details", {}).get("remediation")),
                  remediation=(res.get("error") or {}).get("details", {}).get("remediation"))
        real = state(src_db, args.project, tracked)
        run.check("real_project_untouched", real["status"] != "rendering",
                  after={"real_project_edit": real})
    finally:
        shutil.rmtree(work)
    run.check("copy_removed", not work.exists())
    return run.finish(limitations=[
        "proves the refusal path only; a render on the real project with tracking data "
        "is covered by the speaker framing boundary in fsv_speaker_state.py"])


if __name__ == "__main__":
    sys.exit(main())
