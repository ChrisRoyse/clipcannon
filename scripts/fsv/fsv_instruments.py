"""FSV (#68 follow-up): quality and reaction readings from different instruments
never share a column, every row names its instrument, and readers only trust
the instrument they understand.

Source of truth: the scenes / reactions / provenance rows of a probe-owned
re-keyed copy of proj_31a990b2, read back with plain sqlite3; Laplacian
variance recomputed independently (scipy.ndimage) from the frame files.

Corpus: the NASA Artemis II project (226 scenes, 61 min audio). Its frames and
audio are linked read-only into the copy; only the copied analysis.db is
written. pyiqa is not installed on this host, so the BRISQUE column routing is
exercised with synthetic scores through the real writer (stated below).

    python scripts/fsv/fsv_instruments.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np
import sqlite_vec
from kit import Run
from PIL import Image
from scipy import ndimage

from clipcannon.config import ClipCannonConfig
from clipcannon.db.schema_migrations import get_schema_version, migrate_to_v5
from clipcannon.pipeline import reactions_stage
from clipcannon.pipeline.highlights_loaders import _load_scenes
from clipcannon.pipeline.highlights_scoring import _avg_visual_quality
from clipcannon.pipeline.quality import _write_scene_scores, run_quality

PROJECTS = Path.home() / ".clipcannon" / "projects"
SRC, PID = "proj_31a990b2", "proj_fsvinst"


def q(db: Path, sql: str, params: tuple = ()) -> list[tuple]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def cols(db: Path, table: str) -> set[str]:
    return {r[1] for r in q(db, f"PRAGMA table_info({table})")}


def make_copy(work: Path) -> Path:
    src = PROJECTS / SRC
    work.mkdir()
    for child in src.iterdir():
        if child.name != "analysis.db" and not child.name.startswith("analysis.db-"):
            (work / child.name).symlink_to(child)
    db = work / "analysis.db"
    shutil.copy2(src / "analysis.db", db)
    con = sqlite3.connect(db)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND sql NOT LIKE 'CREATE VIRTUAL TABLE%'").fetchall():
        if "project_id" in [c[1] for c in con.execute(f"PRAGMA table_info({table})")]:
            con.execute(f"UPDATE {table} SET project_id=?", (PID,))
    # Legacy state as an old run left it: an untagged quality value and
    # SenseVoice-style rows with the constant 0.8 confidence.
    con.execute("UPDATE scenes SET quality_avg = 77.0, quality_classification = 'good'")
    con.execute("DELETE FROM reactions")
    for s in (1000, 5000, 9000):
        con.execute("INSERT INTO reactions (project_id, start_ms, end_ms, type, confidence,"
                    " duration_ms, intensity) VALUES (?,?,?,?,?,?,?)",
                    (PID, s, s + 3000, "laughter", 0.8, 3000, "moderate"))
    con.commit()
    con.close()
    return db


def laplacian_var(path: Path) -> float:
    img = Image.open(path).convert("L")
    if max(img.size) > 512:
        r = 512 / max(img.size)
        img = img.resize((int(img.width * r), int(img.height * r)), Image.LANCZOS)
    a = np.asarray(img, dtype=np.float64)
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    return float(np.var(ndimage.convolve(a, k, mode="nearest")))


async def main_async(run: Run) -> None:
    cfg = ClipCannonConfig.load()
    fps = int(cfg.get("processing.frame_extraction_fps"))
    work = PROJECTS / PID
    if work.exists():
        raise SystemExit(f"{work} exists; refusing to overwrite a project dir")
    db = make_copy(work)
    try:
        # 1. Migration: v4 -> v5 adds the columns, keeps data, is idempotent.
        before = {"version": get_schema_version(db), "scenes_has_sharpness":
                  "sharpness_avg" in cols(db, "scenes"),
                  "reactions_has_instrument": "instrument" in cols(db, "reactions")}
        first, second = migrate_to_v5(db), migrate_to_v5(db)
        after = {"version": get_schema_version(db),
                 "scenes_new": sorted({"quality_instrument", "sharpness_avg", "sharpness_min"}
                                      & cols(db, "scenes")),
                 "reactions_instrument": "instrument" in cols(db, "reactions"),
                 "legacy_quality_kept": q(db, "SELECT COUNT(*) FROM scenes WHERE quality_avg=77")[0][0]}
        run.check("migration_v5_adds_columns_idempotent",
                  before["version"] == 4 and not before["scenes_has_sharpness"] and first
                  and not second and after["version"] == 5 and len(after["scenes_new"]) == 3
                  and after["reactions_instrument"] and after["legacy_quality_kept"] > 0,
                  before=before, after={**after, "first": first, "second": second})

        # 2. Untagged legacy quality is not trusted by the highlight reader.
        legacy = _load_scenes(db, PID)
        run.check("legacy_untagged_quality_not_used",
                  legacy and all(s["quality"] is None for s in legacy),
                  before={"quality_avg_77_rows": after["legacy_quality_kept"]},
                  after={"loader_quality_values": sorted({str(s["quality"]) for s in legacy})})

        # 3. Real quality stage on this host (pyiqa absent -> Laplacian).
        res = await run_quality(PID, db, work, cfg)
        rows = q(db, "SELECT start_ms, end_ms, quality_avg, quality_min, quality_classification,"
                     " quality_instrument, sharpness_avg, sharpness_min FROM scenes"
                     " WHERE project_id=? ORDER BY start_ms", (PID,))
        prov = q(db, "SELECT model_name, model_version, model_parameters FROM provenance"
                     " WHERE project_id=? AND operation='quality_assessment'"
                     " ORDER BY timestamp_utc DESC LIMIT 1", (PID,))[0]
        params = json.loads(prov[2])
        tagged = [r for r in rows if r[5] == "laplacian_variance"]
        run.check("laplacian_writes_sharpness_only",
                  res.success and tagged and all(r[6] is not None for r in tagged)
                  and all(r[2] is None and r[3] is None and r[4] is None for r in rows)
                  and all(r[5] is None and r[6] is None for r in rows if r not in tagged)
                  and prov[0] == "laplacian_variance" and params.get("columns") == "sharpness_*"
                  and params.get("scenes_scored") == len(tagged),
                  action="run_quality (real stage)",
                  after={"success": res.success, "error": res.error_message,
                         "scenes": len(rows), "tagged_laplacian": len(tagged),
                         "quality_avg_non_null": sum(r[2] is not None for r in rows),
                         "sharpness_range": [min((r[6] for r in tagged), default=None),
                                             max((r[6] for r in tagged), default=None)],
                         "provenance": [prov[0], prov[1], params]})

        # 4. Independent recompute of 3 scenes' sharpness from the frame files.
        frames = sorted((work / "frames").glob("frame_*.jpg"))
        ts = {f: (int(f.stem.split("_")[1]) - 1) * 1000 // fps for f in frames}
        picks = [tagged[0], tagged[len(tagged) // 2], tagged[-1]] if tagged else []
        recomputed = []
        for r in picks:
            vals = [laplacian_var(f) for f, t in ts.items() if r[0] <= t <= r[1]]
            recomputed.append({"scene": [r[0], r[1]], "stored_avg": r[6],
                               "recomputed_avg": round(sum(vals) / len(vals), 2),
                               "stored_min": r[7], "recomputed_min": round(min(vals), 2)})
        run.check("sharpness_matches_independent_recompute",
                  picks and all(abs(x["stored_avg"] - x["recomputed_avg"]) <= 0.011
                                and abs(x["stored_min"] - x["recomputed_min"]) <= 0.011
                                for x in recomputed), after=recomputed)

        # 5. Highlight reader: Laplacian is not BRISQUE -> no quality term (was 0.5).
        hs = _load_scenes(db, PID)
        win = _avg_visual_quality(hs, 0, 600_000)
        run.check("highlights_ignore_sharpness", all(s["quality"] is None for s in hs)
                  and win == 0.0, after={"window_0_600s_quality": win})

        # 6. BRISQUE routing through the real writer (synthetic 70.0 scores).
        brisque_scores = {t: 70.0 for t in ts.values()}
        n_b = _write_scene_scores(db, PID, "brisque", brisque_scores)
        b_rows = q(db, "SELECT quality_avg, quality_classification, quality_instrument,"
                       " sharpness_avg FROM scenes WHERE project_id=? AND quality_instrument"
                       " IS NOT NULL", (PID,))
        hs_b = _load_scenes(db, PID)
        run.check("brisque_writes_quality_only_and_clears_sharpness",
                  n_b == len(tagged) and all(r == (70.0, "good", "brisque", None) for r in b_rows)
                  and all(s["quality"] in (None, 0.7) for s in hs_b)
                  and _avg_visual_quality(hs_b, 0, 600_000) == 0.7,
                  action="_write_scene_scores(brisque, 70.0 per frame)",
                  after={"scenes": n_b, "distinct_rows": sorted(set(map(str, b_rows))),
                         "loader_window_quality": _avg_visual_quality(hs_b, 0, 600_000)})
        lap_scores = {ts[f]: laplacian_var(f) for f in frames[:400]}
        _write_scene_scores(db, PID, "laplacian_variance", lap_scores)
        mixed = q(db, "SELECT COUNT(*) FROM scenes WHERE project_id=? AND quality_avg IS NOT NULL"
                      " AND sharpness_avg IS NOT NULL", (PID,))[0][0]
        left_b = q(db, "SELECT COUNT(*) FROM scenes WHERE quality_instrument='brisque'")[0][0]
        run.check("rerun_never_leaves_two_instruments", mixed == 0 and left_b == 0,
                  after={"rows_with_both": mixed, "brisque_rows_left": left_b})

        # 7. Reactions, real SenseVoice (installed here): replaces legacy rows.
        res = await reactions_stage.run_reactions(PID, db, work, cfg)
        r_rows = q(db, "SELECT instrument, confidence, intensity FROM reactions WHERE project_id=?",
                   (PID,))
        rprov = q(db, "SELECT model_name, model_parameters, output_record_count FROM provenance"
                      " WHERE project_id=? AND operation='reaction_detection'"
                      " ORDER BY timestamp_utc DESC LIMIT 1", (PID,))[0]
        run.check("sensevoice_rows_tagged_no_fabricated_confidence",
                  res.success and all(r == ("sensevoice_funasr", None, None) for r in r_rows)
                  and rprov[0] == "sensevoice_funasr" and rprov[2] == len(r_rows),
                  before={"legacy_rows": 3, "legacy_confidence": 0.8},
                  after={"success": res.success, "error": res.error_message,
                         "rows": len(r_rows), "distinct": sorted(set(map(str, r_rows))),
                         "provenance": [rprov[0], json.loads(rprov[1]), rprov[2]]})

        # 8. AST instrument (FunASR reported not installed), real stage on the
        # full mix: rows tagged, confidence = model probability >= its pinned
        # threshold, replaces the SenseVoice rows, a re-run does not append.
        orig = reactions_stage._check_sensevoice_funasr
        reactions_stage._check_sensevoice_funasr = lambda: False
        try:
            res1 = await reactions_stage.run_reactions(PID, db, work, cfg)
            n1 = q(db, "SELECT COUNT(*) FROM reactions WHERE project_id=?", (PID,))[0][0]
            res2 = await reactions_stage.run_reactions(PID, db, work, cfg)
        finally:
            reactions_stage._check_sensevoice_funasr = orig
        a_rows = q(db, "SELECT instrument, type, confidence, start_ms, end_ms, context_transcript"
                       " FROM reactions WHERE project_id=? ORDER BY start_ms", (PID,))
        aprov = q(db, "SELECT model_name, model_version, model_parameters, input_file_path"
                      " FROM provenance WHERE project_id=? AND operation='reaction_detection'"
                      " ORDER BY timestamp_utc DESC LIMIT 1", (PID,))[0]
        ap = json.loads(aprov[2])
        thr = {"laughter": ap.get("instrument_laughter_threshold"),
               "applause": ap.get("instrument_applause_threshold")}
        run.check("ast_rows_tagged_with_model_probability",
                  res1.success and res2.success and a_rows and len(a_rows) == n1
                  and all(r[0] == "ast_audioset" and thr[r[1]] is not None
                          and thr[r[1]] <= r[2] <= 1.0 for r in a_rows)
                  and aprov[0] == "ast_audioset"
                  and aprov[1] == "f826b80d28226b62986cc218e5cec390b1096902",
                  action="run_reactions twice with FunASR reported absent (real mix audio)",
                  before={"sensevoice_rows": len(r_rows)},
                  after={"success": [res1.success, res2.success],
                         "error": res1.error_message or res2.error_message,
                         "rows_run1": n1, "rows_run2": len(a_rows),
                         "rows": [[r[1], r[2], r[3], r[4], (r[5] or "")[:60]] for r in a_rows],
                         "provenance": [aprov[0], aprov[1], ap]})
        run.check("reactions_read_full_mix_not_vocals",
                  str(aprov[3]).endswith("stems/audio_16k.wav"),
                  before={"old_input": "stems/vocals.wav (speech resolver)"},
                  after={"input_file_path": aprov[3]})

        # 9. Readers expose the instrument (MCP tool fn + dashboard route).
        from clipcannon.dashboard.routes.timeline import get_timeline
        from clipcannon.tools.understanding_segment import clipcannon_get_segment_detail
        seg = await clipcannon_get_segment_detail(PID, 0, 3_700_000)
        tl = await get_timeline(PID)
        sc = (seg.get("scenes_quality") or [{}])[0]
        tsc = (tl.get("scenes") or [{}])[0]
        rc = seg.get("reactions") or []
        run.check("readers_expose_instrument",
                  "quality_instrument" in sc and "sharpness_avg" in sc
                  and "quality_instrument" in tsc and "sharpness_avg" in tsc
                  and (not rc or all(r.get("instrument") == "ast_audioset" for r in rc)),
                  after={"segment_scene": {k: sc.get(k) for k in ("quality_avg", "quality_instrument",
                                                                   "sharpness_avg")},
                         "timeline_scene": {k: tsc.get(k) for k in ("quality_instrument",
                                                                    "sharpness_avg")},
                         "segment_reactions": len(rc), "error": seg.get("error")})
    finally:
        shutil.rmtree(work)
    run.check("copy_removed", not work.exists())


def main() -> int:
    run = Run("instrument-columns", issue=68, source_of_truth="scenes/reactions/provenance rows",
              claim="quality and reaction readings are stored per instrument (BRISQUE->quality_*, "
                    "Laplacian->sharpness_*, reactions.instrument), re-runs replace rather than mix, "
                    "and readers use only the instrument they understand",
              corpus=f"re-keyed copy of {SRC} (226 scenes, 61-min audio)",
              why_minimal="one real project exercises both installed instruments end to end; "
                          "the legacy seed is the minimum that shows mixing is cleared")
    asyncio.run(main_async(run))
    return run.finish(limitations=[
        "pyiqa is not installed here: BRISQUE column routing uses synthetic 70.0 scores "
        "through the real writer; BRISQUE numbers themselves are not measured",
        "the AST instrument ran on the stage with FunASR reported absent (monkeypatched "
        "check); the NASA audio has no reaction labels, so this probe checks storage, "
        "not accuracy (accuracy: fsv_reactions_bench.py on labelled ESC-50)",
        "the recompute shares PIL resizing with the stage; only the convolution is independent"])


if __name__ == "__main__":
    sys.exit(main())
