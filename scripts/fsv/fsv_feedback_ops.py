"""FSV: edit feedback through the real MCP server changes the stored EDL exactly as
the typed operations declare, and every refusal changes nothing.

Source of truth: the `edits` row (edl_json) in the project's analysis.db, read
with sqlite3 independently of the server. The real path is the MCP server over
stdio (scripts/clipcannon-mcp), called by an MCP client exactly as an agent does.
This client does not advertise sampling, which is the boundary for free text.

Corpus: one new two-segment edit on a real ingested project (default: the NASA
Artemis II press conference). Two segments are the fewest that show a per-segment
op touching one segment and not the other; one edit is enough because the ops are
pure EDL transforms.

    python scripts/fsv/fsv_feedback_ops.py [--project proj_x]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

from kit import REPO, Run
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DB_ROOT = Path.home() / ".clipcannon" / "projects"


def edl_row(db: Path, edit_id: str) -> tuple[dict, str] | tuple[None, None]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT edl_json FROM edits WHERE edit_id=?", (edit_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        return None, None
    return json.loads(row[0]), hashlib.sha256(row[0].encode()).hexdigest()


async def call(s: ClientSession, tool: str, args: dict) -> tuple[bool, dict]:
    res = await s.call_tool(tool, args, read_timeout_seconds=None)
    text = "".join(c.text for c in res.content if c.type == "text")
    try:
        return bool(res.isError), json.loads(text)
    except json.JSONDecodeError:
        # The MCP SDK validates arguments against the tool's input schema before
        # the handler runs and replies with plain text; record it as that layer.
        return bool(res.isError), {"error": {"code": "MCP_INPUT_SCHEMA", "message": text}}


async def probe(run: Run, pid: str) -> None:
    db = DB_ROOT / pid / "analysis.db"
    venv = REPO / ".venv" / "bin"
    env = dict(os.environ, PATH=f"{venv}{os.pathsep}{os.environ.get('PATH', '')}")
    params = StdioServerParameters(command=str(REPO / "scripts" / "clipcannon-mcp"), env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        err, made = await call(s, "clipcannon_create_edit", {
            "project_id": pid, "name": "FSV feedback ops", "target_platform": "youtube_shorts",
            "segments": [{"source_start_ms": 1711100, "source_end_ms": 1730000},
                         {"source_start_ms": 1730000, "source_end_ms": 1756300}],
            "captions": {"enabled": True, "style": "word_highlight", "position": "bottom",
                         "font_size": 64}})
        edit_id = made.get("edit_id")
        before, digest0 = edl_row(db, edit_id) if edit_id else (None, None)
        run.check("edit_created_and_stored", not err and before is not None
                  and len(before["segments"]) == 2, after={"edit_id": edit_id, "response": made})
        if before is None:
            return

        ops = [{"op": "captions", "font_size_delta": 16, "position": "center"},
               {"op": "speed", "segment_ids": [2], "speed": 1.25}]
        err, res = await call(s, "clipcannon_apply_feedback",
                              {"project_id": pid, "edit_id": edit_id, "operations": ops})
        after, digest1 = edl_row(db, edit_id)
        seg = {x["segment_id"]: x for x in after["segments"]}
        run.check("typed_ops_persist_exactly", not err
                  and after["captions"]["font_size"] == before["captions"]["font_size"] + 16
                  and after["captions"]["position"] == "center"
                  and seg[2]["speed"] == 1.25 and seg[1]["speed"] == before["segments"][0]["speed"]
                  and len(after["captions"].get("chunks") or []) > 0,
                  before={"font_size": before["captions"]["font_size"],
                          "position": before["captions"]["position"],
                          "speeds": [x["speed"] for x in before["segments"]]},
                  action=ops,
                  after={"font_size": after["captions"]["font_size"],
                         "position": after["captions"]["position"],
                         "speeds": [x["speed"] for x in after["segments"]],
                         "chunks": len(after["captions"].get("chunks") or []),
                         "planner": res.get("parser"), "row_sha256": digest1})

        async def refused(name: str, args: dict, code: str) -> None:
            e, body = await call(s, "clipcannon_apply_feedback",
                                 {"project_id": pid, "edit_id": edit_id, **args})
            _, digest = edl_row(db, edit_id)
            got = (body.get("error") or {}).get("code")
            run.check(name, e and got == code and digest == digest1,
                      action=args, expected_code=code, got_code=got, is_error=e,
                      row_unchanged=digest == digest1, remediation=(body.get("error") or {})
                      .get("details", {}).get("remediation"))

        await refused("out_of_range_op_refused",
                      {"operations": [{"op": "speed", "segment_ids": [2], "speed": 9}]},
                      "MCP_INPUT_SCHEMA")
        await refused("nonexistent_segment_refused",
                      {"operations": [{"op": "speed", "segment_ids": [99], "speed": 2}]},
                      "INVALID_OPERATION")
        await refused("free_text_without_planner_refused",
                      {"feedback": "make the captions bigger"}, "FEEDBACK_PLANNER_UNAVAILABLE")
        await refused("empty_request_refused", {}, "INVALID_PARAMETER")
        e, body = await call(s, "clipcannon_apply_feedback", {
            "project_id": pid, "edit_id": "edit_does_not_exist", "operations": ops})
        run.check("unknown_edit_refused", e and isinstance(body.get("error"), dict),
                  got=body.get("error"))
        run.meta["edit_id"] = edit_id
        run.meta["row_sha256_created"] = digest0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="proj_31a990b2")
    args, _ = ap.parse_known_args()
    run = Run("feedback-ops", issue=67, source_of_truth="edits.edl_json in analysis.db",
              claim="typed feedback ops through the real MCP server change the stored EDL "
                    "exactly as declared; refusals carry a code and change nothing",
              corpus=f"one new two-segment edit on {args.project}",
              why_minimal="two segments are the fewest that show a per-segment op leaving "
                          "the other segment alone; ops are pure EDL transforms")
    asyncio.run(probe(run, args.project))
    return run.finish(limitations=[
        "the sampling planner path needs a client with sampling; this client has none, so "
        "only its refusal is proven here",
        "the edit is left in the project as evidence (edit_id in report.json)"])


if __name__ == "__main__":
    sys.exit(main())
