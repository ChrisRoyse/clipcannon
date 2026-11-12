"""FSV (#70, #68): the semantic instrument runs in the main runtime, reproduces the
measured vectors, records its identity, and semantic search refuses instead of
substituting text search.

Source of truth: vec_semantic rows and the nomic_embed provenance row in the
project's analysis.db, read with sqlite3 + sqlite-vec independently of the
server; MCP replies over stdio for the search boundary.

Corpus: the 701 transcript segments of proj_31a990b2 (NASA Artemis II, 61 min).
Reference: the vectors of the measured transformers-4.57.6 remote-code run, kept
as evidence/fsv/70/reference_tf4.npz and pinned by the sha256 of the bytes that
run stored. The same segments re-embedded by the port must reproduce them. A
probe-owned re-keyed copy of the DB carries the missing-index state the real
project does not have.

    python scripts/fsv/fsv_semantic.py [--project proj_x]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
import sqlite_vec
from kit import REPO, Run
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECTS = Path.home() / ".clipcannon" / "projects"
QUERIES = ["heat shield", "splashdown and recovery", "the crew's families", "lunar flyby"]
REFERENCE = Path.home() / ".clipcannon" / "evidence" / "fsv" / "70" / "reference_tf4.npz"
# sha256 of the 701 packed vectors the tf4 remote-code run stored in vec_semantic
# (read from analysis.db before the first re-embedding, 2026-11-12).
REFERENCE_BLOB_SHA256 = "9f4900d004568df3faf979b8c48297da9e3cd8547b1fa6c0d62a8d1999b007ee"


def vec_state(db: Path, pid: str) -> dict:
    con = sqlite3.connect(db)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    try:
        rows = con.execute("SELECT segment_id, semantic_embedding FROM vec_semantic "
                           "WHERE project_id=? ORDER BY segment_id", (pid,)).fetchall()
        prov = con.execute("SELECT record_id, model_name, model_version, model_parameters "
                           "FROM provenance WHERE project_id=? AND stage='nomic_embed' "
                           "ORDER BY timestamp_utc DESC LIMIT 1", (pid,)).fetchone()
        topics = con.execute("SELECT COUNT(*) FROM topics WHERE project_id=?", (pid,)).fetchone()[0]
    finally:
        con.close()
    blob = b"".join(r[1] for r in rows)
    ids = [r[0] for r in rows]
    vecs = np.array([struct.unpack("768f", r[1]) for r in rows], np.float32)
    return {"ids": ids, "vecs": vecs, "sha256": hashlib.sha256(blob).hexdigest(),
            "n": len(rows), "topics": topics,
            "prov": {"record_id": prov[0], "model_name": prov[1], "model_version": prov[2],
                     "instrument": {k.removeprefix("instrument_"): v
                                    for k, v in json.loads(prov[3] or "{}").items()
                                    if k.startswith("instrument_")} or None}
            if prov else None}


def public(s: dict) -> dict:
    return {k: v for k, v in s.items() if k not in ("ids", "vecs")}


async def call(s: ClientSession, tool: str, args: dict) -> tuple[bool, dict]:
    res = await s.call_tool(tool, args, read_timeout_seconds=None)
    return bool(res.isError), json.loads("".join(c.text for c in res.content if c.type == "text"))


def server(env_extra: dict | None = None) -> StdioServerParameters:
    venv = REPO / ".venv" / "bin"
    env = dict(os.environ, PATH=f"{venv}{os.pathsep}{os.environ.get('PATH', '')}",
               **(env_extra or {}))
    return StdioServerParameters(command=str(REPO / "scripts" / "clipcannon-mcp"), env=env)


async def search_phase(run: Run, pid: str, db: Path, label: str, expect: str | None) -> dict:
    async with stdio_client(server()) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        before = vec_state(db, pid)["sha256"]
        err, body = await call(s, "clipcannon_search_content",
                               {"project_id": pid, "query": QUERIES[0], "limit": 5})
        after = vec_state(db, pid)["sha256"]
        e = body.get("error") or {}
        if expect:
            run.check(label, err and e.get("code") == expect and bool(e.get("remediation"))
                      and before == after and "results" not in body,
                      action={"search_type": "semantic"}, got=e, vec_unchanged=before == after)
        return body


async def main_async(run: Run, pid: str) -> None:
    import transformers

    from clipcannon.config import ClipCannonConfig
    from clipcannon.pipeline.nomic_native import IDENTITY, QUERY_PREFIX, NomicEncoder
    from clipcannon.pipeline.semantic_embed import run_semantic_embed

    db = PROJECTS / pid / "analysis.db"
    before_state = vec_state(db, pid)
    run.meta["db_before"] = public(before_state)
    # The measured reference: vectors of the transformers-4.57.6 remote-code run,
    # regenerated in that runtime; its packed bytes must equal the blob that run
    # stored (sha recorded before any re-embedding).
    npz = np.load(REFERENCE)
    blob = b"".join(struct.pack("768f", *v.tolist()) for v in npz["vecs"])
    ref = {"ids": npz["ids"].tolist(), "vecs": npz["vecs"], "n": len(npz["ids"]),
           "sha256": hashlib.sha256(blob).hexdigest(), "prov": before_state["prov"]}
    run.check("reference_is_the_measured_run", ref["sha256"] == REFERENCE_BLOB_SHA256,
              after={"npz": str(REFERENCE), "blob_sha256": ref["sha256"],
                     "expected": REFERENCE_BLOB_SHA256})

    # 2. Action: the real stage in the main runtime (transformers 5.x).
    res = await run_semantic_embed(pid, db, db.parent, ClipCannonConfig.load())
    got = vec_state(db, pid)
    same_ids = got["ids"] == ref["ids"]
    diff = float(np.abs(got["vecs"] - ref["vecs"]).max()) if same_ids else None
    cos = (got["vecs"] * ref["vecs"]).sum(1) if same_ids else np.zeros(1)
    run.check("stage_runs_in_main_runtime", res.success and transformers.__version__.startswith("5"),
              before={"transformers": transformers.__version__},
              after={"success": res.success, "error": res.error_message})
    run.check("vectors_reproduce_measured_instrument",
              same_ids and got["n"] == ref["n"] == 701 and diff is not None and diff < 1e-4,
              before={"n": ref["n"], "sha256": ref["sha256"]},
              after={"n": got["n"], "sha256": got["sha256"], "max_abs_diff": diff,
                     "min_cosine": float(cos.min())})
    run.check("instrument_identity_persisted",
              got["prov"] is not None and got["prov"]["instrument"] == IDENTITY.as_dict()
              and got["prov"]["model_version"] == IDENTITY.revision,
              before=ref["prov"], after=got["prov"])

    # 3. Boundary: semantic search answers from the index, independently recomputed.
    enc = NomicEncoder()
    async with stdio_client(server()) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        agree = []
        for q in QUERIES:
            err, body = await call(s, "clipcannon_search_content",
                                   {"project_id": pid, "query": q, "limit": 5})
            qv = enc.encode([QUERY_PREFIX + q])[0]
            mine = [got["ids"][i] for i in np.argsort(-(got["vecs"] @ qv))[:5]]
            theirs = [x["segment_id"] for x in body.get("results", [])]
            agree.append({"query": q, "mcp": theirs, "independent": mine,
                          "type": body.get("search_type"), "error": err})
        run.check("semantic_search_matches_independent_knn",
                  all(a["mcp"] == a["independent"] and a["type"] == "semantic" and not a["error"]
                      for a in agree), after=agree)
        err, body = await call(s, "clipcannon_search_content",
                               {"project_id": pid, "query": "x", "limit": 0})
        e = body.get("error") or {}
        run.check("schema_violation_typed", err and e.get("code") == "INVALID_ARGUMENTS"
                  and bool(e.get("remediation")) and e.get("details", {}).get("path") == "limit",
                  action={"limit": 0}, got=e)
        err, body = await call(s, "clipcannon_search_content",
                               {"project_id": pid, "query": "heat shield", "search_type": "text"})
        run.check("explicit_text_search_is_text", not err and body.get("search_type") == "text"
                  and all("heat shield" in x["text"].lower() for x in body["results"])
                  and all("similarity" not in x for x in body["results"]),
                  after={"n": body.get("result_count"), "type": body.get("search_type")})

    # 4. Boundaries on probe-owned re-keyed copies (the real project is current):
    #    vectors from an unidentified instrument -> STALE; no vectors -> MISSING.
    for cpid, label, code in (("proj_fsvstale", "stale_index_refused_not_substituted",
                               "SEMANTIC_INDEX_STALE"),
                              ("proj_fsvnosem", "missing_index_refused_not_substituted",
                               "SEMANTIC_INDEX_MISSING")):
        work = PROJECTS / cpid
        if work.exists():
            raise SystemExit(f"{work} exists; refusing to overwrite a project dir")
        work.mkdir()
        try:
            cdb = work / "analysis.db"
            shutil.copy2(db, cdb)
            con = sqlite3.connect(cdb)
            con.enable_load_extension(True)
            sqlite_vec.load(con)
            for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                        "AND sql NOT LIKE 'CREATE VIRTUAL TABLE%'").fetchall():
                if "project_id" in [c[1] for c in con.execute(f"PRAGMA table_info({table})")]:
                    con.execute(f"UPDATE {table} SET project_id=?", (cpid,))
            if code == "SEMANTIC_INDEX_STALE":
                # keep the vectors, re-key them, and drop the instrument identity
                con.execute("UPDATE vec_semantic SET project_id=?", (cpid,))
                con.execute("UPDATE provenance SET model_parameters=? WHERE stage='nomic_embed'",
                            ('{"embedding_dim": 768}',))
            else:
                con.execute("DELETE FROM vec_semantic")
            con.commit()
            con.close()
            await search_phase(run, cpid, cdb, label, code)
        finally:
            shutil.rmtree(work)
        run.check(f"copy_removed_{cpid}", not work.exists())

    # 5. Boundary: a broken config refuses; it does not fall back to the default tree.
    with tempfile.TemporaryDirectory() as home:
        cfg = Path(home) / ".clipcannon" / "config.json"
        cfg.parent.mkdir()
        cfg.write_text("{ not json")
        async with stdio_client(server({"HOME": home})) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            err, body = await call(s, "clipcannon_project_list", {})
        e = body.get("error") or {}
        run.check("broken_config_refused", err and e.get("code") == "CONFIG_INVALID"
                  and bool(e.get("remediation")) and "projects" not in body,
                  action={"config": "{ not json"}, got=e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="proj_31a990b2")
    args, _ = ap.parse_known_args()
    run = Run("semantic-instrument", issue=70, source_of_truth="vec_semantic + provenance rows",
              claim="the pinned native Nomic port runs under transformers 5, reproduces the "
                    "measured vectors, persists its identity; semantic search refuses rather "
                    "than substituting text; a broken config refuses",
              corpus=f"701 transcript segments of {args.project} + a re-keyed copy",
              why_minimal="the stored vectors of the measured run are the only reference "
                          "for 'same instrument'; the copy holds the missing-index state")
    asyncio.run(main_async(run, args.project))
    return run.finish(limitations=[
        "parity is against one 61-min English corpus; another language/domain is unmeasured",
        "GPU (RTX 5090) fp32; CPU parity not re-measured here"])


if __name__ == "__main__":
    sys.exit(main())
