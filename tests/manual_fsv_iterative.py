"""Manual FSV (Full State Verification) for Iterative Editing Architecture.

Exercises ALL P0-P5 features end-to-end with synthetic data, then
physically verifies DB state at each step using direct SQLite queries.

Run: python tests/manual_fsv_iterative.py
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure src is importable when running standalone
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

# ---------------------------------------------------------------------------
# Results tracking
# ---------------------------------------------------------------------------
_PASS = 0
_FAIL = 0
_TOTAL = 0


def check(
    number: int,
    description: str,
    input_desc: str,
    expected: str,
    actual: str,
    db_state: str,
    passed: bool,
) -> None:
    """Print a single check result and update counters."""
    global _PASS, _FAIL, _TOTAL
    _TOTAL += 1
    status = "PASS" if passed else "FAIL"
    if passed:
        _PASS += 1
    else:
        _FAIL += 1

    print(
        f"\n[CHECK {number:02d}] {description}\n"
        f"  INPUT:    {input_desc}\n"
        f"  EXPECTED: {expected}\n"
        f"  ACTUAL:   {actual}\n"
        f"  DB STATE: {db_state}\n"
        f"  RESULT:   {status}"
    )


def summary() -> None:
    """Print final summary."""
    print(
        f"\n{'=' * 55}\n"
        f"FSV SUMMARY: {_PASS}/{_TOTAL} checks passed"
        f"\n{'=' * 55}"
    )
    if _FAIL:
        print(f"  ** {_FAIL} FAILURES **")


# ---------------------------------------------------------------------------
# DB helper -- direct raw SQLite access (NOT through ClipCannon)
# ---------------------------------------------------------------------------
def raw_conn(db_path: Path) -> sqlite3.Connection:
    """Open a raw sqlite3 connection with dict rows."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def raw_fetch_one(db_path: Path, sql: str, params: tuple = ()) -> dict | None:
    conn = raw_conn(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def raw_fetch_all(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    conn = raw_conn(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def raw_count(db_path: Path, sql: str, params: tuple = ()) -> int:
    row = raw_fetch_one(db_path, sql, params)
    if row is None:
        return 0
    return list(row.values())[0] or 0


# ---------------------------------------------------------------------------
# Setup: create a synthetic project from scratch
# ---------------------------------------------------------------------------
def setup_test_project(tmp_dir: Path) -> tuple[str, Path]:
    """Create a test project with synthetic data.

    Returns (project_id, db_path).
    """
    from clipcannon.db.schema import create_project_db

    project_id = "fsv_iterative_test"
    db_path = create_project_db(project_id, base_dir=tmp_dir)

    conn = sqlite3.connect(str(db_path))
    try:
        # Insert project row (status=ready so editing tools work)
        conn.execute(
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                "FSV Iterative Test",
                "/fake/source.mp4",
                "abc123deadbeef",
                120000,  # 2 minutes
                "1920x1080",
                30.0,
                "h264",
                "ready",
            ),
        )

        # Insert transcript_segments spanning the full duration
        segments_data = [
            (project_id, 0, 10000, "Hello everyone welcome to this video"),
            (project_id, 10000, 25000, "Today we are going to talk about testing"),
            (project_id, 25000, 40000, "Let me show you how the system works"),
            (project_id, 40000, 55000, "This is really important for quality"),
            (project_id, 55000, 70000, "And that wraps up the first section"),
            (project_id, 70000, 85000, "Moving on to the next topic now"),
            (project_id, 85000, 100000, "Here are some final thoughts"),
            (project_id, 100000, 120000, "Thanks for watching see you next time"),
        ]
        for pid, start, end, text in segments_data:
            conn.execute(
                "INSERT INTO transcript_segments (project_id, start_ms, end_ms, text, word_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (pid, start, end, text, len(text.split())),
            )

        # Insert transcript_words for caption generation
        word_id = 0
        for seg_idx, (_, start, end, text) in enumerate(segments_data, start=1):
            words = text.split()
            word_dur = (end - start) // max(len(words), 1)
            for w_idx, word in enumerate(words):
                w_start = start + w_idx * word_dur
                w_end = w_start + word_dur
                word_id += 1
                conn.execute(
                    "INSERT INTO transcript_words (segment_id, word, start_ms, end_ms, confidence) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (seg_idx, word, w_start, w_end, 0.95),
                )

        conn.commit()
    finally:
        conn.close()

    # Create required project subdirectories
    project_dir = tmp_dir / project_id
    for subdir in ("source", "stems", "frames", "storyboards", "edits", "renders"):
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    return project_id, db_path


# ---------------------------------------------------------------------------
# Monkey-patch the helpers so they point to our temp directory
# ---------------------------------------------------------------------------
def patch_paths(tmp_dir: Path) -> None:
    """Override projects_dir so all tools resolve to our temp dir."""
    import clipcannon.tools.editing_helpers as eh
    import clipcannon.tools.rendering as rn

    eh.projects_dir = lambda: tmp_dir  # type: ignore[assignment]
    rn._projects_dir = lambda: tmp_dir  # type: ignore[assignment]


# ===================================================================
# MAIN FSV ASYNC TEST SEQUENCE
# ===================================================================
async def run_fsv(tmp_dir: Path) -> None:
    from clipcannon.tools.editing import dispatch_editing_tool
    from clipcannon.tools.rendering import dispatch_rendering_tool
    from clipcannon.rendering.segment_hash import compute_segment_hash
    from clipcannon.editing.edl import SegmentSpec

    project_id, db_path = setup_test_project(tmp_dir)

    # ==========================================================
    # Phase 1: Setup verification
    # ==========================================================
    print("\n" + "=" * 55)
    print("PHASE 1: SETUP VERIFICATION")
    print("=" * 55)

    row = raw_fetch_one(db_path, "SELECT * FROM project WHERE project_id = ?", (project_id,))
    check(
        0, "Project exists in DB",
        f"project_id={project_id}",
        "project row with status=ready",
        f"status={row['status']}" if row else "None",
        f"project table: {row is not None}",
        row is not None and row["status"] == "ready",
    )

    # ==========================================================
    # Phase 2: P0 -- Version History
    # ==========================================================
    print("\n" + "=" * 55)
    print("PHASE 2: P0 -- VERSION HISTORY")
    print("=" * 55)

    # CHECK 1: Create an edit
    ORIG_NAME = "Highlight Reel V1"
    create_result = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": ORIG_NAME,
        "target_platform": "tiktok",
        "segments": [
            {"source_start_ms": 0, "source_end_ms": 15000},
            {"source_start_ms": 25000, "source_end_ms": 45000},
            {"source_start_ms": 70000, "source_end_ms": 90000},
        ],
    })
    edit_id = str(create_result.get("edit_id", ""))
    has_error = "error" in create_result

    check(
        1, "Create edit succeeds",
        f"create_edit(name={ORIG_NAME!r}, platform=tiktok, 3 segments)",
        "edit_id returned, no error",
        f"edit_id={edit_id}, error={has_error}",
        f"create_result keys: {list(create_result.keys())}",
        bool(edit_id) and not has_error,
    )

    # CHECK 2: Verify edits table
    edit_row = raw_fetch_one(db_path, "SELECT * FROM edits WHERE edit_id = ?", (edit_id,))
    check(
        2, "Edit row in DB with status=draft",
        f"SELECT from edits WHERE edit_id={edit_id}",
        "1 row, status=draft",
        f"row exists={edit_row is not None}, status={edit_row['status'] if edit_row else 'N/A'}",
        f"edits table: name={edit_row['name'] if edit_row else 'N/A'}",
        edit_row is not None and edit_row["status"] == "draft",
    )

    # CHECK 3: Modify edit -- change name to "Modified V1"
    mod1_result = await dispatch_editing_tool("clipcannon_modify_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "changes": {"name": "Modified V1"},
    })
    mod1_error = "error" in mod1_result
    check(
        3, "Modify edit (name change) succeeds",
        f"modify_edit(changes={{name: 'Modified V1'}})",
        "no error, updated_fields includes 'name'",
        f"error={mod1_error}, updated={mod1_result.get('updated_fields', [])}",
        f"modify result keys: {list(mod1_result.keys())}",
        not mod1_error and "name" in (mod1_result.get("updated_fields") or []),
    )

    # CHECK 4: edit_versions has 1 row with version_number=1
    ver_count = raw_count(
        db_path,
        "SELECT COUNT(*) FROM edit_versions WHERE edit_id = ?",
        (edit_id,),
    )
    check(
        4, "edit_versions has 1 row after first modify",
        f"COUNT from edit_versions WHERE edit_id={edit_id}",
        "1",
        str(ver_count),
        f"edit_versions count: {ver_count}",
        ver_count == 1,
    )

    # CHECK 5: Version 1 edl_json contains ORIGINAL name, not "Modified V1"
    ver1_row = raw_fetch_one(
        db_path,
        "SELECT * FROM edit_versions WHERE edit_id = ? AND version_number = 1",
        (edit_id,),
    )
    ver1_edl = json.loads(ver1_row["edl_json"]) if ver1_row else {}
    ver1_name = ver1_edl.get("name", "")
    check(
        5, "Version 1 edl_json has ORIGINAL name (snapshot before modify)",
        f"edit_versions row version_number=1, edl_json->name",
        f"name={ORIG_NAME!r}",
        f"name={ver1_name!r}",
        f"version_id={ver1_row['version_id'] if ver1_row else 'N/A'}",
        ver1_name == ORIG_NAME,
    )

    # CHECK 6: Modify again -- change segments (2 segments instead of 3)
    mod2_result = await dispatch_editing_tool("clipcannon_modify_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "changes": {
            "segments": [
                {"source_start_ms": 0, "source_end_ms": 20000},
                {"source_start_ms": 55000, "source_end_ms": 80000},
            ],
        },
    })
    mod2_error = "error" in mod2_result
    check(
        6, "Modify edit (segment change) succeeds",
        f"modify_edit(changes={{segments: [2 segments]}})",
        "no error, updated_fields includes 'segments'",
        f"error={mod2_error}, updated={mod2_result.get('updated_fields', [])}",
        f"segment_count={mod2_result.get('segment_count', '?')}",
        not mod2_error and "segments" in (mod2_result.get("updated_fields") or []),
    )

    # CHECK 7: edit_versions now has 2 rows
    ver_count2 = raw_count(
        db_path,
        "SELECT COUNT(*) FROM edit_versions WHERE edit_id = ?",
        (edit_id,),
    )
    ver_rows = raw_fetch_all(
        db_path,
        "SELECT version_number FROM edit_versions WHERE edit_id = ? ORDER BY version_number",
        (edit_id,),
    )
    ver_nums = [r["version_number"] for r in ver_rows]
    check(
        7, "edit_versions has 2 rows after second modify",
        f"COUNT + version_numbers from edit_versions WHERE edit_id={edit_id}",
        "count=2, version_numbers=[1, 2]",
        f"count={ver_count2}, version_numbers={ver_nums}",
        f"edit_versions: {ver_rows}",
        ver_count2 == 2 and ver_nums == [1, 2],
    )

    # CHECK 8: Version 2 change_description mentions "segment"
    ver2_row = raw_fetch_one(
        db_path,
        "SELECT change_description FROM edit_versions WHERE edit_id = ? AND version_number = 2",
        (edit_id,),
    )
    ver2_desc = str(ver2_row["change_description"]).lower() if ver2_row else ""
    check(
        8, "Version 2 change_description mentions segment",
        "edit_versions version_number=2 change_description",
        "contains 'segment'",
        f"description={ver2_row['change_description'] if ver2_row else 'N/A'}",
        f"edit_versions v2: desc={ver2_desc[:80]}",
        "segment" in ver2_desc,
    )

    # CHECK 9: Call edit_history tool
    history_result = await dispatch_editing_tool("clipcannon_edit_history", {
        "project_id": project_id,
        "edit_id": edit_id,
    })
    hist_error = "error" in history_result
    check(
        9, "edit_history tool returns data",
        f"edit_history(project_id={project_id}, edit_id={edit_id})",
        "no error, version_count=2",
        f"error={hist_error}, version_count={history_result.get('version_count', '?')}",
        f"history keys: {list(history_result.keys())}",
        not hist_error and history_result.get("version_count") == 2,
    )

    # CHECK 10: versions array has 3 entries (current + 2 versions)
    versions_arr = history_result.get("versions", [])
    check(
        10, "edit_history versions array has 3 entries",
        "history_result['versions'] length",
        "3 (current + v1 + v2)",
        f"{len(versions_arr)}",
        f"version entries: {[v.get('version_number') for v in versions_arr]}",
        len(versions_arr) == 3,
    )

    # CHECK 11: Revert to version 1
    revert_result = await dispatch_editing_tool("clipcannon_revert_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "version_number": 1,
    })
    revert_error = "error" in revert_result
    check(
        11, "Revert to version 1 succeeds",
        f"revert_edit(version_number=1)",
        "no error, reverted_to_version=1",
        f"error={revert_error}, reverted_to={revert_result.get('reverted_to_version', '?')}",
        f"revert result keys: {list(revert_result.keys())}",
        not revert_error and revert_result.get("reverted_to_version") == 1,
    )

    # CHECK 12: DB name is back to original
    edit_after_revert = raw_fetch_one(
        db_path, "SELECT name FROM edits WHERE edit_id = ?", (edit_id,),
    )
    reverted_name = edit_after_revert["name"] if edit_after_revert else ""
    check(
        12, "After revert, edit name is back to original",
        f"edits.name after revert to v1",
        f"name={ORIG_NAME!r}",
        f"name={reverted_name!r}",
        f"edits row: name={reverted_name!r}",
        reverted_name == ORIG_NAME,
    )

    # CHECK 13: edit_versions now has 3 rows
    ver_count3 = raw_count(
        db_path,
        "SELECT COUNT(*) FROM edit_versions WHERE edit_id = ?",
        (edit_id,),
    )
    check(
        13, "edit_versions has 3 rows after revert (revert created version 3)",
        f"COUNT from edit_versions WHERE edit_id={edit_id}",
        "3",
        str(ver_count3),
        f"edit_versions count: {ver_count3}",
        ver_count3 == 3,
    )

    # CHECK 14: Version 3 change_description contains "revert"
    ver3_row = raw_fetch_one(
        db_path,
        "SELECT change_description FROM edit_versions WHERE edit_id = ? AND version_number = 3",
        (edit_id,),
    )
    ver3_desc = str(ver3_row["change_description"]).lower() if ver3_row else ""
    check(
        14, "Version 3 change_description contains 'revert'",
        "edit_versions version_number=3 change_description",
        "contains 'revert'",
        f"description={ver3_row['change_description'] if ver3_row else 'N/A'}",
        f"edit_versions v3: desc={ver3_desc[:80]}",
        "revert" in ver3_desc,
    )

    # ==========================================================
    # Phase 3: P2 -- Change Classification (render_hint)
    # ==========================================================
    print("\n" + "=" * 55)
    print("PHASE 3: P2 -- CHANGE CLASSIFICATION (RENDER_HINT)")
    print("=" * 55)

    # CHECK 15: Modify name only -- nothing should be invalidated
    mod_name = await dispatch_editing_tool("clipcannon_modify_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "changes": {"name": "Renamed Edit"},
    })
    hint15 = mod_name.get("render_hint", {})
    check(
        15, "Name-only change: no invalidation",
        "modify_edit(changes={name: 'Renamed Edit'})",
        "segments_invalidated=[], captions=false, audio=false",
        (
            f"segments_invalidated={hint15.get('segments_invalidated', '?')}, "
            f"captions={hint15.get('captions_invalidated', '?')}, "
            f"audio={hint15.get('audio_invalidated', '?')}"
        ),
        f"render_hint: {hint15}",
        (
            hint15.get("segments_invalidated") == []
            and hint15.get("captions_invalidated") is False
            and hint15.get("audio_invalidated") is False
            and hint15.get("all_segments_invalidated") is False
        ),
    )

    # CHECK 16: Modify caption style -- only captions_invalidated
    mod_cap = await dispatch_editing_tool("clipcannon_modify_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "changes": {"captions": {"font_size": 72, "style": "subtitle_bar"}},
    })
    hint16 = mod_cap.get("render_hint", {})
    check(
        16, "Caption style change: captions_invalidated only",
        "modify_edit(changes={captions: {font_size: 72, style: subtitle_bar}})",
        "captions_invalidated=true, segments_invalidated=[], audio=false",
        (
            f"captions={hint16.get('captions_invalidated', '?')}, "
            f"segments_invalidated={hint16.get('segments_invalidated', '?')}, "
            f"audio={hint16.get('audio_invalidated', '?')}"
        ),
        f"render_hint: {hint16}",
        (
            hint16.get("captions_invalidated") is True
            and hint16.get("audio_invalidated") is False
        ),
    )

    # CHECK 17: Modify segments -- captions + audio invalidated, segments tracked
    # When segment count stays the same (IDs match 1:1), the classifier
    # does per-segment comparison and puts changed IDs in segments_invalidated
    # rather than all_segments_invalidated (more efficient). When segment
    # count differs, all_segments_invalidated is set. We test BOTH cases.
    #
    # Case A: same count, different timings -> per-segment invalidation
    mod_seg = await dispatch_editing_tool("clipcannon_modify_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "changes": {
            "segments": [
                {"source_start_ms": 5000, "source_end_ms": 25000},
                {"source_start_ms": 40000, "source_end_ms": 60000},
                {"source_start_ms": 80000, "source_end_ms": 100000},
            ],
        },
    })
    hint17 = mod_seg.get("render_hint", {})
    segs_inv = hint17.get("segments_invalidated", [])
    all_inv = hint17.get("all_segments_invalidated", False)
    # Either all_segments_invalidated OR all segment IDs in segments_invalidated
    all_affected = all_inv or (set(segs_inv) == {1, 2, 3})
    check(
        17, "Segment timing change: all segments + captions + audio invalidated",
        "modify_edit(changes={segments: [3 new segments, same count]})",
        "all segments affected (via all_segments or per-id), captions=true, audio=true",
        (
            f"all_segments={all_inv}, segments_invalidated={segs_inv}, "
            f"captions={hint17.get('captions_invalidated', '?')}, "
            f"audio={hint17.get('audio_invalidated', '?')}"
        ),
        f"render_hint: {hint17}",
        (
            all_affected
            and hint17.get("captions_invalidated") is True
            and hint17.get("audio_invalidated") is True
        ),
    )

    # Case B: different segment count -> all_segments_invalidated
    mod_seg_b = await dispatch_editing_tool("clipcannon_modify_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "changes": {
            "segments": [
                {"source_start_ms": 5000, "source_end_ms": 25000},
                {"source_start_ms": 40000, "source_end_ms": 60000},
            ],
        },
    })
    hint17b = mod_seg_b.get("render_hint", {})
    check(
        37, "Segment count change: all_segments_invalidated=true",
        "modify_edit(changes={segments: [2 segments from 3]})",
        "all_segments_invalidated=true, captions=true, audio=true",
        (
            f"all_segments={hint17b.get('all_segments_invalidated', '?')}, "
            f"captions={hint17b.get('captions_invalidated', '?')}, "
            f"audio={hint17b.get('audio_invalidated', '?')}"
        ),
        f"render_hint: {hint17b}",
        (
            hint17b.get("all_segments_invalidated") is True
            and hint17b.get("captions_invalidated") is True
            and hint17b.get("audio_invalidated") is True
        ),
    )

    # ==========================================================
    # Phase 4: P3 -- Feedback Parser
    # ==========================================================
    print("\n" + "=" * 55)
    print("PHASE 4: P3 -- FEEDBACK INTENT PARSER")
    print("=" * 55)

    # Create a fresh edit for feedback testing
    fb_edit = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "Feedback Test Edit",
        "target_platform": "tiktok",
        "segments": [
            {"source_start_ms": 0, "source_end_ms": 20000},
            {"source_start_ms": 30000, "source_end_ms": 50000},
            {"source_start_ms": 60000, "source_end_ms": 80000},
        ],
    })
    fb_edit_id = str(fb_edit.get("edit_id", ""))

    # CHECK 18: "the music is too loud" -> audio_adjust
    fb1 = await dispatch_editing_tool("clipcannon_apply_feedback", {
        "project_id": project_id,
        "edit_id": fb_edit_id,
        "feedback": "the music is too loud",
    })
    fb1_intent = fb1.get("parsed_intent", {})
    fb1_error = "error" in fb1
    check(
        18, "Feedback 'music is too loud' -> audio_adjust",
        "apply_feedback('the music is too loud')",
        "intent_type=audio_adjust",
        f"intent_type={fb1_intent.get('intent_type', 'N/A')}, error={fb1_error}",
        f"parsed_intent: {fb1_intent}",
        fb1_intent.get("intent_type") == "audio_adjust" and not fb1_error,
    )

    # CHECK 19: "make the text bigger" -> caption_resize
    fb2 = await dispatch_editing_tool("clipcannon_apply_feedback", {
        "project_id": project_id,
        "edit_id": fb_edit_id,
        "feedback": "make the text bigger",
    })
    fb2_intent = fb2.get("parsed_intent", {})
    fb2_error = "error" in fb2
    check(
        19, "Feedback 'make the text bigger' -> caption_resize",
        "apply_feedback('make the text bigger')",
        "intent_type=caption_resize",
        f"intent_type={fb2_intent.get('intent_type', 'N/A')}, error={fb2_error}",
        f"parsed_intent: {fb2_intent}",
        fb2_intent.get("intent_type") == "caption_resize" and not fb2_error,
    )

    # CHECK 20: gibberish "asdfghjkl" -> error (low confidence)
    fb3 = await dispatch_editing_tool("clipcannon_apply_feedback", {
        "project_id": project_id,
        "edit_id": fb_edit_id,
        "feedback": "asdfghjkl",
    })
    fb3_error = "error" in fb3
    fb3_code = fb3.get("error", {}).get("code", "") if fb3_error else ""
    check(
        20, "Feedback gibberish 'asdfghjkl' -> error or low confidence",
        "apply_feedback('asdfghjkl')",
        "error with LOW_CONFIDENCE code",
        f"error={fb3_error}, code={fb3_code}",
        f"response keys: {list(fb3.keys())}",
        fb3_error and fb3_code == "LOW_CONFIDENCE",
    )

    # ==========================================================
    # Phase 5: P4 -- Edit Branching
    # ==========================================================
    print("\n" + "=" * 55)
    print("PHASE 5: P4 -- EDIT BRANCHING")
    print("=" * 55)

    # Create a new edit for branching
    branch_src = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "Branch Source",
        "target_platform": "tiktok",
        "segments": [
            {"source_start_ms": 0, "source_end_ms": 30000},
            {"source_start_ms": 40000, "source_end_ms": 70000},
        ],
    })
    branch_src_id = str(branch_src.get("edit_id", ""))
    branch_src_seg_count = branch_src.get("segment_count", 0)

    # CHECK 21: Branch to "instagram"
    branch_result = await dispatch_editing_tool("clipcannon_branch_edit", {
        "project_id": project_id,
        "edit_id": branch_src_id,
        "branch_name": "instagram",
        "target_platform": "instagram_reels",
    })
    branch_error = "error" in branch_result
    new_branch_id = str(branch_result.get("edit_id", ""))
    check(
        21, "Branch edit to instagram succeeds",
        f"branch_edit(edit_id={branch_src_id}, branch=instagram, platform=instagram_reels)",
        "new edit_id, no error, branch_name=instagram",
        f"error={branch_error}, new_id={new_branch_id}, branch={branch_result.get('branch_name', '?')}",
        f"branch result keys: {list(branch_result.keys())}",
        not branch_error and bool(new_branch_id) and branch_result.get("branch_name") == "instagram",
    )

    # CHECK 22: DB has new edit with parent_edit_id set
    branch_db_row = raw_fetch_one(
        db_path,
        "SELECT * FROM edits WHERE edit_id = ?",
        (new_branch_id,),
    )
    check(
        22, "Branched edit in DB has parent_edit_id and branch_name",
        f"SELECT from edits WHERE edit_id={new_branch_id}",
        f"parent_edit_id={branch_src_id}, branch_name=instagram",
        (
            f"parent={branch_db_row['parent_edit_id'] if branch_db_row else 'N/A'}, "
            f"branch={branch_db_row['branch_name'] if branch_db_row else 'N/A'}"
        ),
        f"edits row: {branch_db_row is not None}",
        (
            branch_db_row is not None
            and branch_db_row["parent_edit_id"] == branch_src_id
            and branch_db_row["branch_name"] == "instagram"
        ),
    )

    # CHECK 23: Segment count matches
    branch_seg_count = int(branch_db_row["segment_count"]) if branch_db_row else 0
    check(
        23, "Branched edit segment count matches source",
        f"branched edit segment_count vs source ({branch_src_seg_count})",
        f"segment_count={branch_src_seg_count}",
        f"segment_count={branch_seg_count}",
        f"DB segment_count: {branch_seg_count}",
        branch_seg_count == branch_src_seg_count,
    )

    # CHECK 24: list_branches returns both root and instagram
    branches_result = await dispatch_editing_tool("clipcannon_list_branches", {
        "project_id": project_id,
        "edit_id": branch_src_id,
    })
    br_error = "error" in branches_result
    branch_list = branches_result.get("branches", [])
    branch_names = [b.get("branch_name") for b in branch_list]
    check(
        24, "list_branches returns root (main) and branch (instagram)",
        f"list_branches(edit_id={branch_src_id})",
        "branches include 'main' and 'instagram'",
        f"error={br_error}, branch_names={branch_names}",
        f"branch_count={branches_result.get('branch_count', '?')}",
        not br_error and "main" in branch_names and "instagram" in branch_names,
    )

    # ==========================================================
    # Phase 6: P1 -- Segment Hash Verification
    # ==========================================================
    print("\n" + "=" * 55)
    print("PHASE 6: P1 -- SEGMENT HASH VERIFICATION")
    print("=" * 55)

    seg_a = SegmentSpec(
        segment_id=1,
        source_start_ms=0,
        source_end_ms=10000,
        output_start_ms=0,
        speed=1.0,
    )
    # CHECK 25: Identical segment -> identical hash
    hash1 = compute_segment_hash("abc123", seg_a, "tiktok_vertical")
    hash2 = compute_segment_hash("abc123", seg_a, "tiktok_vertical")
    check(
        25, "Identical SegmentSpec produces identical hash",
        f"compute_segment_hash(same inputs) x2",
        "hashes match",
        f"h1={hash1[:16]}..., h2={hash2[:16]}...",
        f"hash1==hash2: {hash1 == hash2}",
        hash1 == hash2,
    )

    # CHECK 26: Different speed -> different hash
    seg_b = SegmentSpec(
        segment_id=1,
        source_start_ms=0,
        source_end_ms=10000,
        output_start_ms=0,
        speed=1.5,
    )
    hash3 = compute_segment_hash("abc123", seg_b, "tiktok_vertical")
    check(
        26, "Different speed produces different hash",
        f"compute_segment_hash(speed=1.0) vs compute_segment_hash(speed=1.5)",
        "hashes differ",
        f"h1={hash1[:16]}..., h3={hash3[:16]}...",
        f"hash1!=hash3: {hash1 != hash3}",
        hash1 != hash3,
    )

    # ==========================================================
    # Phase 7: Edge Cases
    # ==========================================================
    print("\n" + "=" * 55)
    print("PHASE 7: EDGE CASES")
    print("=" * 55)

    # CHECK 27: edit_history with non-existent edit_id
    hist_bad = await dispatch_editing_tool("clipcannon_edit_history", {
        "project_id": project_id,
        "edit_id": "nonexistent_edit_999",
    })
    check(
        27, "edit_history with non-existent edit_id returns error",
        "edit_history(edit_id='nonexistent_edit_999')",
        "error response",
        f"has_error={'error' in hist_bad}, code={hist_bad.get('error', {}).get('code', '')}",
        f"response: {list(hist_bad.keys())}",
        "error" in hist_bad,
    )

    # CHECK 28: revert_edit with non-existent version_number
    revert_bad = await dispatch_editing_tool("clipcannon_revert_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "version_number": 999,
    })
    check(
        28, "revert_edit with non-existent version_number returns error",
        "revert_edit(version_number=999)",
        "error response with VERSION_NOT_FOUND",
        f"has_error={'error' in revert_bad}, code={revert_bad.get('error', {}).get('code', '')}",
        f"response: {list(revert_bad.keys())}",
        "error" in revert_bad and revert_bad.get("error", {}).get("code") == "VERSION_NOT_FOUND",
    )

    # CHECK 29: branch_edit with non-existent edit_id
    branch_bad = await dispatch_editing_tool("clipcannon_branch_edit", {
        "project_id": project_id,
        "edit_id": "nonexistent_edit_999",
        "branch_name": "bad_branch",
        "target_platform": "tiktok",
    })
    check(
        29, "branch_edit with non-existent edit_id returns error",
        "branch_edit(edit_id='nonexistent_edit_999')",
        "error response",
        f"has_error={'error' in branch_bad}, code={branch_bad.get('error', {}).get('code', '')}",
        f"response: {list(branch_bad.keys())}",
        "error" in branch_bad,
    )

    # CHECK 30: apply_feedback with empty feedback string
    fb_empty = await dispatch_editing_tool("clipcannon_apply_feedback", {
        "project_id": project_id,
        "edit_id": fb_edit_id,
        "feedback": "",
    })
    fb_empty_error = "error" in fb_empty
    check(
        30, "apply_feedback with empty string returns error or low confidence",
        "apply_feedback(feedback='')",
        "error response (low confidence)",
        f"has_error={fb_empty_error}, code={fb_empty.get('error', {}).get('code', '')}",
        f"response keys: {list(fb_empty.keys())}",
        fb_empty_error,
    )

    # CHECK 31: preview_segment with segment_index=0 (out of range)
    preview_0 = await dispatch_rendering_tool("clipcannon_preview_segment", {
        "project_id": project_id,
        "edit_id": fb_edit_id,
        "segment_index": 0,
    })
    check(
        31, "preview_segment with index 0 returns error",
        "preview_segment(segment_index=0)",
        "error response (INVALID_PARAMETER)",
        f"has_error={'error' in preview_0}, code={preview_0.get('error', {}).get('code', '')}",
        f"response: {list(preview_0.keys())}",
        "error" in preview_0 and preview_0.get("error", {}).get("code") == "INVALID_PARAMETER",
    )

    # CHECK 32: preview_segment with index > segment_count
    preview_high = await dispatch_rendering_tool("clipcannon_preview_segment", {
        "project_id": project_id,
        "edit_id": fb_edit_id,
        "segment_index": 999,
    })
    check(
        32, "preview_segment with index > segment_count returns error",
        "preview_segment(segment_index=999)",
        "error response (INVALID_PARAMETER)",
        f"has_error={'error' in preview_high}, code={preview_high.get('error', {}).get('code', '')}",
        f"response: {list(preview_high.keys())}",
        "error" in preview_high and preview_high.get("error", {}).get("code") == "INVALID_PARAMETER",
    )

    # ==========================================================
    # Bonus: Additional cross-feature verification
    # ==========================================================
    print("\n" + "=" * 55)
    print("BONUS: CROSS-FEATURE VERIFICATION")
    print("=" * 55)

    # CHECK 33: render_hint_json stored in DB after modify
    hint_row = raw_fetch_one(
        db_path,
        "SELECT render_hint_json FROM edits WHERE edit_id = ?",
        (edit_id,),
    )
    hint_json = hint_row.get("render_hint_json") if hint_row else None
    hint_valid = False
    if hint_json:
        try:
            parsed = json.loads(hint_json)
            hint_valid = "segments_invalidated" in parsed or "all_segments_invalidated" in parsed
        except Exception:
            pass
    check(
        33, "render_hint_json stored in edits table is valid JSON",
        f"edits.render_hint_json for edit_id={edit_id}",
        "valid JSON with segments_invalidated or all_segments_invalidated",
        f"has_json={hint_json is not None}, valid={hint_valid}",
        f"DB: render_hint_json={str(hint_json)[:80] if hint_json else 'NULL'}",
        hint_valid,
    )

    # CHECK 34: edit_segments table has correct entries for current edit
    edit_segs = raw_fetch_all(
        db_path,
        "SELECT * FROM edit_segments WHERE edit_id = ? ORDER BY segment_order",
        (edit_id,),
    )
    current_edit_row = raw_fetch_one(
        db_path,
        "SELECT segment_count FROM edits WHERE edit_id = ?",
        (edit_id,),
    )
    expected_count = int(current_edit_row["segment_count"]) if current_edit_row else 0
    check(
        34, "edit_segments table matches current segment_count",
        f"edit_segments rows for edit_id={edit_id}",
        f"count={expected_count}",
        f"count={len(edit_segs)}",
        f"DB: segment_orders={[s['segment_order'] for s in edit_segs]}",
        len(edit_segs) == expected_count,
    )

    # CHECK 35: Feedback audio adjust actually modifies the EDL audio settings
    pre_fb_row = raw_fetch_one(
        db_path,
        "SELECT edl_json FROM edits WHERE edit_id = ?",
        (fb_edit_id,),
    )
    pre_audio = json.loads(pre_fb_row["edl_json"])["audio"] if pre_fb_row else {}
    pre_vol = pre_audio.get("source_volume_db", 0.0)
    fb_audio = await dispatch_editing_tool("clipcannon_apply_feedback", {
        "project_id": project_id,
        "edit_id": fb_edit_id,
        "feedback": "the background music is too loud, turn it down",
    })
    post_fb_row = raw_fetch_one(
        db_path,
        "SELECT edl_json FROM edits WHERE edit_id = ?",
        (fb_edit_id,),
    )
    post_audio = json.loads(post_fb_row["edl_json"])["audio"] if post_fb_row else {}
    post_vol = post_audio.get("source_volume_db", 0.0)
    # Feedback should lower volume (negative delta)
    vol_changed = post_vol != pre_vol
    check(
        35, "Feedback 'music too loud' actually changes audio volume in DB",
        f"apply_feedback then check edits.edl_json->audio->source_volume_db",
        f"volume changed from {pre_vol}",
        f"pre={pre_vol}, post={post_vol}, changed={vol_changed}",
        f"DB: edl_json->audio->source_volume_db",
        vol_changed,
    )

    # CHECK 36: Branched edit has its own edl_json (not shared reference)
    src_edl_row = raw_fetch_one(
        db_path,
        "SELECT edl_json FROM edits WHERE edit_id = ?",
        (branch_src_id,),
    )
    branch_edl_row = raw_fetch_one(
        db_path,
        "SELECT edl_json FROM edits WHERE edit_id = ?",
        (new_branch_id,),
    )
    src_edl = json.loads(src_edl_row["edl_json"]) if src_edl_row else {}
    br_edl = json.loads(branch_edl_row["edl_json"]) if branch_edl_row else {}
    # They should have different edit_ids but same segments
    check(
        36, "Branched edit has independent EDL (different edit_id, same segments)",
        f"Compare edl_json between source and branch",
        "different edit_id, same segment count",
        (
            f"src_edit_id={src_edl.get('edit_id', '?')}, "
            f"br_edit_id={br_edl.get('edit_id', '?')}, "
            f"src_segs={len(src_edl.get('segments', []))}, "
            f"br_segs={len(br_edl.get('segments', []))}"
        ),
        f"DB: two separate edl_json blobs",
        (
            src_edl.get("edit_id") != br_edl.get("edit_id")
            and len(src_edl.get("segments", [])) == len(br_edl.get("segments", []))
        ),
    )


# ===================================================================
# ENTRY POINT
# ===================================================================
def main() -> None:
    print("=" * 55)
    print("ClipCannon FSV: Iterative Editing Architecture")
    print("P0-P5 Full State Verification")
    print("=" * 55)

    with tempfile.TemporaryDirectory(prefix="fsv_iter_") as tmpdir:
        tmp_path = Path(tmpdir)
        patch_paths(tmp_path)
        asyncio.run(run_fsv(tmp_path))

    summary()
    sys.exit(1 if _FAIL > 0 else 0)


if __name__ == "__main__":
    main()
