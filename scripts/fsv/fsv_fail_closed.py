"""FSV (#68): converted cover-ups now refuse instead of returning a substitute.

Source of truth: the bytes each path would have written (grid JPEG, quality
scores, DB rows) and the exception or typed error it raises, read back
independently (file existence/sha, sqlite3).

Corpus: probe-owned temp files: one real frame from proj_31a990b2 plus one
truncated JPEG, one non-WAV "audio" file, one SQLite DB with a real table and
one file that is not a database. Each pair (good input vs broken input) is the
minimum that separates "no data" from "instrument failed", which is the claim.

    python scripts/fsv/fsv_fail_closed.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from kit import Run, sha256_file

from clipcannon.audio.music_gen import _validate_output
from clipcannon.dashboard.routes.projects import _query_project_metadata
from clipcannon.db.optional import require_missing_table
from clipcannon.pipeline.quality import _run_laplacian_scoring
from clipcannon.pipeline.storyboard import _generate_grid

FRAMES = Path.home() / ".clipcannon" / "projects" / "proj_31a990b2" / "frames"


def raises(fn) -> str | None:  # noqa: ANN001
    try:
        fn()
    except Exception as exc:  # the probe records which exception, if any
        return f"{type(exc).__name__}: {str(exc)[:160]}"
    return None


def main() -> int:
    run = Run("fail-closed", issue=68, source_of_truth="written artifacts + raised errors",
              claim="converted cover-ups refuse on broken input and still work on good input; "
                    "only an absent optional table is tolerated",
              corpus="1 real NASA frame + 1 truncated JPEG, 1 non-WAV, 1 SQLite DB + 1 non-DB",
              why_minimal="one good/broken pair per path separates 'no data' from "
                          "'instrument failed'; more inputs add no proof")
    work = Path(tempfile.mkdtemp(prefix="fsv68_"))
    try:
        good = work / "frame_000001.jpg"
        shutil.copy2(sorted(FRAMES.glob("*.jpg"))[100], good)
        bad = work / "frame_000002.jpg"
        bad.write_bytes(good.read_bytes()[:200])  # truncated JPEG

        # 1. Quality: good frame scores; broken frame refuses (was: 50.0 placeholder).
        scores = _run_laplacian_scoring([good])
        err = raises(lambda: _run_laplacian_scoring([good, bad]))
        run.check("quality_refuses_unreadable_frame", len(scores) == 1 and err is not None,
                  before={"old_behaviour": "score 50.0 for the broken frame"},
                  after={"good_score": scores, "broken_error": err})

        # 2. Storyboard: broken frame refuses and writes no grid (was: grey cell).
        grid_ok, grid_bad = work / "grid_ok.jpg", work / "grid_bad.jpg"
        _generate_grid([good] * 9, [i * 1000 for i in range(9)], grid_ok)
        err = raises(lambda: _generate_grid([good] * 8 + [bad], [i * 1000 for i in range(9)],
                                            grid_bad))
        run.check("storyboard_refuses_unreadable_frame",
                  grid_ok.exists() and err is not None and not grid_bad.exists(),
                  after={"good_grid_sha256": sha256_file(grid_ok) if grid_ok.exists() else None,
                         "broken_error": err, "broken_grid_written": grid_bad.exists()})

        # 3. Music output: non-WAV refuses (was: duration estimated from file size).
        fake = work / "music.wav"
        fake.write_bytes(b"\x00" * 48044)
        err = raises(lambda: _validate_output(fake, 1.0))
        run.check("music_non_wav_refused", err is not None and "WAV header" in err,
                  before={"old_behaviour": "estimate 0.25 s from 48044 bytes"},
                  after={"error": err})

        # 4. Optional tables: absent table tolerated, any other DB error propagates.
        db = work / "a.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE present (x)")
        absent = raises(lambda: _tolerate(con, "SELECT * FROM no_such_stage_table"))
        syntax = raises(lambda: _tolerate(con, "SELEC broken"))
        con.close()
        notdb = work / "not.db"
        notdb.write_bytes(b"this is not a database" * 100)
        c2 = sqlite3.connect(notdb)
        corrupt = raises(lambda: _tolerate(c2, "SELECT * FROM present"))
        c2.close()
        run.check("absent_table_tolerated_others_raise",
                  absent is None and syntax is not None and corrupt is not None,
                  after={"absent_table": absent, "syntax_error": syntax, "not_a_db": corrupt})

        # 5. Dashboard: unreadable project DB is reported, not hidden (was: None).
        meta = _query_project_metadata(notdb, "proj_x")
        run.check("dashboard_reports_unreadable_project",
                  isinstance(meta, dict) and meta.get("status") == "error" and meta.get("error"),
                  after={"returned": meta})
    finally:
        shutil.rmtree(work)
    run.check("temp_removed", not work.exists())
    return run.finish(limitations=[
        "function-level calls on probe-owned inputs; the stage/tool boundaries that wrap "
        "them return typed failures (StageResult / MCP error), shown in fsv_semantic.py",
        "GPU-only paths (BRISQUE, SenseVoice, WavLM, InsightFace) not forced to fail here"])


def _tolerate(con: sqlite3.Connection, sql: str) -> None:
    try:
        con.execute(sql).fetchall()
    except sqlite3.OperationalError as exc:
        require_missing_table(exc)


if __name__ == "__main__":
    sys.exit(main())
