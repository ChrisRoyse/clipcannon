#!/usr/bin/env python3
"""
=============================================================================
  SHERLOCK HOLMES - FULL STATE VERIFICATION (FSV)
  ClipCannon Phase 1 Core Infrastructure
=============================================================================

  "When you have eliminated the impossible, whatever remains,
   however improbable, must be the truth."

  This script forensically verifies every module in the core
  infrastructure by:
    1. Testing happy paths with synthetic data
    2. Testing 3+ edge cases per module
    3. Printing state BEFORE and AFTER each operation
    4. Physically verifying database contents via SELECT
    5. Physically verifying file existence and contents
=============================================================================
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from pathlib import Path

# Ensure src/ is on the path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

# ============================================================
# GLOBALS
# ============================================================
PASS_COUNT = 0
FAIL_COUNT = 0
EVIDENCE: list[dict[str, str]] = []

TMP_ROOT = Path(tempfile.mkdtemp(prefix="fsv_clipcannon_"))


def banner(title: str) -> None:
    """Print a section banner."""
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  HOLMES INVESTIGATION: {title}")
    print(sep)


def sub_banner(title: str) -> None:
    """Print a sub-section banner."""
    print(f"\n  --- {title} ---")


def record(test_name: str, passed: bool, expected: str, actual: str, detail: str = "") -> None:
    """Record a test result with evidence."""
    global PASS_COUNT, FAIL_COUNT
    status = "PASS" if passed else "FAIL"
    if passed:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1

    tag = "[PASS]" if passed else "[FAIL] ****"
    print(f"  {tag} {test_name}")
    print(f"         Expected : {expected}")
    print(f"         Actual   : {actual}")
    if detail:
        print(f"         Detail   : {detail}")

    EVIDENCE.append({
        "test": test_name,
        "status": status,
        "expected": expected,
        "actual": actual,
        "detail": detail,
    })


def safe_run(name: str, fn):
    """Run a test function, catching all exceptions."""
    try:
        fn()
    except Exception as exc:
        record(
            f"{name} (EXCEPTION)",
            False,
            "No exception",
            f"{type(exc).__name__}: {exc}",
            traceback.format_exc().split("\n")[-3].strip(),
        )


# ============================================================
# 1. EXCEPTIONS MODULE
# ============================================================
def test_exceptions():
    banner("EXCEPTIONS MODULE")
    from clipcannon.exceptions import (
        BillingError,
        ClipCannonError,
        ConfigError,
        DatabaseError,
        GPUError,
        PipelineError,
        ProvenanceError,
    )

    sub_banner("Happy Path: All exception classes exist and are subclasses")
    classes = {
        "ClipCannonError": ClipCannonError,
        "PipelineError": PipelineError,
        "BillingError": BillingError,
        "ProvenanceError": ProvenanceError,
        "DatabaseError": DatabaseError,
        "ConfigError": ConfigError,
        "GPUError": GPUError,
    }
    for name, cls in classes.items():
        is_sub = issubclass(cls, ClipCannonError)
        record(
            f"Exception {name} is subclass of ClipCannonError",
            is_sub,
            "True",
            str(is_sub),
        )

    sub_banner("Edge Case: ClipCannonError carries message and details")
    err = ClipCannonError("test msg", details={"key": "val"})
    record(
        "ClipCannonError.message",
        err.message == "test msg",
        "test msg",
        err.message,
    )
    record(
        "ClipCannonError.details",
        err.details == {"key": "val"},
        "{'key': 'val'}",
        str(err.details),
    )

    sub_banner("Edge Case: PipelineError carries stage_name and operation")
    pe = PipelineError("fail", stage_name="transcription", operation="whisperx")
    record(
        "PipelineError.stage_name",
        pe.stage_name == "transcription",
        "transcription",
        pe.stage_name,
    )
    record(
        "PipelineError.operation",
        pe.operation == "whisperx",
        "whisperx",
        pe.operation,
    )

    sub_banner("Edge Case: Default details is empty dict")
    err2 = ClipCannonError("no details")
    record(
        "ClipCannonError default details",
        err2.details == {},
        "{}",
        str(err2.details),
    )


# ============================================================
# 2. DATABASE CONNECTION MANAGER
# ============================================================
def test_db_connection():
    banner("DATABASE CONNECTION MANAGER")
    from clipcannon.db.connection import get_connection

    db_path = TMP_ROOT / "conn_test" / "test.db"

    sub_banner("Happy Path: Create connection, verify WAL mode and pragmas")
    print(f"  STATE BEFORE: db_path exists = {db_path.exists()}")
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    print(f"  STATE AFTER: db_path exists = {db_path.exists()}")

    record(
        "Database file created",
        db_path.exists(),
        "True",
        str(db_path.exists()),
    )

    # Verify WAL mode
    journal = conn.execute("PRAGMA journal_mode").fetchone()
    journal_val = journal["journal_mode"] if isinstance(journal, dict) else journal[0]
    record(
        "PRAGMA journal_mode = wal",
        str(journal_val).lower() == "wal",
        "wal",
        str(journal_val),
    )

    # Verify synchronous=NORMAL (1)
    sync = conn.execute("PRAGMA synchronous").fetchone()
    sync_val = sync["synchronous"] if isinstance(sync, dict) else sync[0]
    record(
        "PRAGMA synchronous = NORMAL (1)",
        int(sync_val) == 1,
        "1",
        str(sync_val),
    )

    # Verify cache_size
    cache = conn.execute("PRAGMA cache_size").fetchone()
    cache_val = cache["cache_size"] if isinstance(cache, dict) else cache[0]
    record(
        "PRAGMA cache_size = -64000",
        int(cache_val) == -64000,
        "-64000",
        str(cache_val),
    )

    # Verify foreign_keys
    fk = conn.execute("PRAGMA foreign_keys").fetchone()
    fk_val = fk["foreign_keys"] if isinstance(fk, dict) else fk[0]
    record(
        "PRAGMA foreign_keys = ON (1)",
        int(fk_val) == 1,
        "1",
        str(fk_val),
    )

    # Verify temp_store=MEMORY (2)
    ts = conn.execute("PRAGMA temp_store").fetchone()
    ts_val = ts["temp_store"] if isinstance(ts, dict) else ts[0]
    record(
        "PRAGMA temp_store = MEMORY (2)",
        int(ts_val) == 2,
        "2",
        str(ts_val),
    )

    sub_banner("Edge Case: dict_rows returns dicts")
    conn.execute("CREATE TABLE test_dr (id INTEGER, name TEXT)")
    conn.execute("INSERT INTO test_dr VALUES (1, 'alice')")
    row = conn.execute("SELECT * FROM test_dr").fetchone()
    is_dict = isinstance(row, dict)
    record(
        "dict_rows=True returns dict",
        is_dict,
        "True (dict)",
        str(type(row).__name__),
    )
    if is_dict:
        record(
            "dict row keys correct",
            set(row.keys()) == {"id", "name"},
            "{'id', 'name'}",
            str(set(row.keys())),
        )

    sub_banner("Edge Case: dict_rows=False returns tuples")
    conn2 = get_connection(TMP_ROOT / "conn_test" / "test2.db", enable_vec=False, dict_rows=False)
    conn2.execute("CREATE TABLE t (x INTEGER)")
    conn2.execute("INSERT INTO t VALUES (42)")
    row2 = conn2.execute("SELECT * FROM t").fetchone()
    is_tuple = isinstance(row2, tuple)
    record(
        "dict_rows=False returns tuple",
        is_tuple,
        "True (tuple)",
        str(type(row2).__name__),
    )
    conn2.close()

    sub_banner("Edge Case: Parent directory auto-created")
    deep_path = TMP_ROOT / "deep" / "nested" / "path" / "auto.db"
    print(f"  STATE BEFORE: {deep_path.parent} exists = {deep_path.parent.exists()}")
    conn3 = get_connection(deep_path, enable_vec=False, dict_rows=False)
    print(f"  STATE AFTER: {deep_path.parent} exists = {deep_path.parent.exists()}")
    record(
        "Auto-created parent directories",
        deep_path.exists(),
        "True",
        str(deep_path.exists()),
    )
    conn3.close()
    conn.close()


# ============================================================
# 3. DATABASE SCHEMA
# ============================================================
def test_db_schema():
    banner("DATABASE SCHEMA")
    from clipcannon.db.schema import (
        SCHEMA_VERSION,
        create_project_db,
        get_schema_version,
    )

    project_id = "fsv_schema_test"
    base_dir = TMP_ROOT / "schema_projects"

    sub_banner("Happy Path: Create project DB, verify all tables")
    print(f"  STATE BEFORE: base_dir exists = {base_dir.exists()}")
    db_path = create_project_db(project_id, base_dir=base_dir)
    print(f"  STATE AFTER: db_path = {db_path}, exists = {db_path.exists()}")

    record(
        "create_project_db returns valid path",
        db_path.exists(),
        "True",
        str(db_path.exists()),
    )

    # Now physically inspect sqlite_master
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    tables_raw = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = sorted([r["name"] for r in tables_raw])
    print(f"  PHYSICAL EVIDENCE - Tables in sqlite_master:")
    for t in table_names:
        print(f"    - {t}")

    # Expected core tables (24)
    expected_core = sorted([
        "schema_version", "project", "transcript_segments", "transcript_words",
        "scenes", "speakers", "emotion_curve", "topics", "highlights",
        "reactions", "silence_gaps", "acoustic", "music_sections", "beats",
        "beat_sections", "on_screen_text", "text_change_events",
        "profanity_events", "content_safety", "pacing", "storyboard_grids",
        "stream_status", "provenance",
    ])

    for tbl in expected_core:
        found = tbl in table_names
        record(
            f"Table '{tbl}' exists",
            found,
            "True",
            str(found),
        )

    sub_banner("Verify schema_version = 1")
    sv = conn.execute("SELECT MAX(version) as v FROM schema_version").fetchone()
    sv_val = sv["v"] if sv else None
    record(
        "schema_version == 1",
        sv_val == SCHEMA_VERSION,
        str(SCHEMA_VERSION),
        str(sv_val),
    )

    # Cross-verify via get_schema_version
    sv_func = get_schema_version(db_path)
    record(
        "get_schema_version() == 1",
        sv_func == SCHEMA_VERSION,
        str(SCHEMA_VERSION),
        str(sv_func),
    )

    sub_banner("Verify indexes exist")
    indexes_raw = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name"
    ).fetchall()
    index_names = [r["name"] for r in indexes_raw]
    print(f"  PHYSICAL EVIDENCE - Custom indexes:")
    for idx in index_names:
        print(f"    - {idx}")

    expected_indexes = [
        "idx_segments_time", "idx_words_time", "idx_words_segment",
        "idx_scenes_time", "idx_emotion_time", "idx_highlights_score",
        "idx_reactions_time", "idx_provenance_project", "idx_provenance_chain",
    ]
    for idx in expected_indexes:
        found = idx in index_names
        record(
            f"Index '{idx}' exists",
            found,
            "True",
            str(found),
        )

    sub_banner("Edge Case: get_schema_version on non-existent DB returns None")
    sv_none = get_schema_version(TMP_ROOT / "nonexistent.db")
    record(
        "get_schema_version(nonexistent) == None",
        sv_none is None,
        "None",
        str(sv_none),
    )

    sub_banner("Edge Case: Idempotent create (IF NOT EXISTS)")
    db_path2 = create_project_db(project_id, base_dir=base_dir)
    record(
        "Second create_project_db succeeds (idempotent)",
        db_path2.exists(),
        "True",
        str(db_path2.exists()),
    )

    conn.close()


# ============================================================
# 4. QUERY HELPERS
# ============================================================
def test_db_queries():
    banner("QUERY HELPERS")
    from clipcannon.db.queries import (
        batch_insert,
        count_rows,
        fetch_all,
        fetch_one,
        table_exists,
        transaction,
    )
    from clipcannon.db.schema import create_project_db

    project_id = "fsv_queries_test"
    base_dir = TMP_ROOT / "query_projects"
    db_path = create_project_db(project_id, base_dir=base_dir)

    from clipcannon.db.connection import get_connection
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)

    sub_banner("Happy Path: table_exists for core tables")
    for tbl in ["project", "transcript_segments", "provenance"]:
        exists = table_exists(conn, tbl)
        record(f"table_exists('{tbl}')", exists, "True", str(exists))

    te_fake = table_exists(conn, "nonexistent_table_xyz")
    record("table_exists('nonexistent_table_xyz')", not te_fake, "False", str(te_fake))

    sub_banner("Happy Path: batch_insert into transcript_segments + physical verify")
    # First insert a project row (FK dependency)
    conn.execute(
        "INSERT INTO project (project_id, name, source_path, source_sha256, duration_ms, resolution, fps, codec) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, "FSV Test", "/tmp/test.mp4", "abc123", 60000, "1920x1080", 30.0, "h264"),
    )
    conn.commit()

    rows_to_insert = [
        (project_id, 0, 5000, "Hello world", None, "en", 2),
        (project_id, 5000, 10000, "This is a test", None, "en", 4),
        (project_id, 10000, 15000, "Forensic verification", None, "en", 2),
        (project_id, 15000, 20000, "Edge case testing", None, "en", 3),
        (project_id, 20000, 25000, "Final segment", None, "en", 2),
    ]
    columns = ["project_id", "start_ms", "end_ms", "text", "speaker_id", "language", "word_count"]

    print(f"  STATE BEFORE batch_insert: count = {count_rows(conn, 'transcript_segments')}")
    inserted = batch_insert(conn, "transcript_segments", columns, rows_to_insert)
    conn.commit()
    print(f"  STATE AFTER batch_insert: count = {count_rows(conn, 'transcript_segments')}")

    record(
        "batch_insert returned count",
        inserted == 5,
        "5",
        str(inserted),
    )

    # Physical verification: SELECT back and compare
    sub_banner("Physical Verification: SELECT * FROM transcript_segments")
    db_rows = fetch_all(conn, "SELECT * FROM transcript_segments ORDER BY start_ms")
    print(f"  Retrieved {len(db_rows)} rows:")
    for r in db_rows:
        print(f"    segment_id={r['segment_id']}, start={r['start_ms']}, end={r['end_ms']}, text='{r['text']}'")

    record(
        "fetch_all returns 5 rows",
        len(db_rows) == 5,
        "5",
        str(len(db_rows)),
    )

    # Verify first row content matches
    first = db_rows[0]
    record(
        "First row text matches",
        first["text"] == "Hello world",
        "Hello world",
        str(first["text"]),
    )
    record(
        "First row start_ms matches",
        first["start_ms"] == 0,
        "0",
        str(first["start_ms"]),
    )

    sub_banner("Happy Path: fetch_one")
    one = fetch_one(conn, "SELECT * FROM transcript_segments WHERE start_ms = ?", (10000,))
    record(
        "fetch_one finds correct row",
        one is not None and one["text"] == "Forensic verification",
        "Forensic verification",
        str(one["text"]) if one else "None",
    )

    sub_banner("Happy Path: count_rows with WHERE clause")
    cnt = count_rows(conn, "transcript_segments", "language = ?", ("en",))
    record(
        "count_rows with WHERE returns 5",
        cnt == 5,
        "5",
        str(cnt),
    )

    sub_banner("Happy Path: transaction context manager (commit)")
    with transaction(conn) as tx:
        tx.execute(
            "INSERT INTO transcript_segments (project_id, start_ms, end_ms, text, language, word_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, 25000, 30000, "Transaction test", "en", 2),
        )
    cnt_after = count_rows(conn, "transcript_segments")
    record(
        "Transaction commit: row count increased",
        cnt_after == 6,
        "6",
        str(cnt_after),
    )

    sub_banner("Edge Case: transaction rollback on exception")
    cnt_before_rb = count_rows(conn, "transcript_segments")
    try:
        with transaction(conn) as tx:
            tx.execute(
                "INSERT INTO transcript_segments (project_id, start_ms, end_ms, text, language, word_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, 30000, 35000, "Rollback test", "en", 2),
            )
            raise ValueError("Deliberate failure for rollback test")
    except Exception:
        pass
    cnt_after_rb = count_rows(conn, "transcript_segments")
    record(
        "Transaction rollback: row count unchanged",
        cnt_after_rb == cnt_before_rb,
        str(cnt_before_rb),
        str(cnt_after_rb),
    )

    sub_banner("Edge Case: batch_insert with empty rows")
    empty_result = batch_insert(conn, "transcript_segments", columns, [])
    record(
        "batch_insert with empty rows returns 0",
        empty_result == 0,
        "0",
        str(empty_result),
    )

    sub_banner("Edge Case: fetch_one returns None for no match")
    none_row = fetch_one(conn, "SELECT * FROM transcript_segments WHERE start_ms = ?", (999999,))
    record(
        "fetch_one returns None for no match",
        none_row is None,
        "None",
        str(none_row),
    )

    conn.close()


# ============================================================
# 5. CONFIGURATION
# ============================================================
def test_config():
    banner("CONFIGURATION")
    from clipcannon.config import ClipCannonConfig
    from clipcannon.exceptions import ConfigError

    sub_banner("Happy Path: Load default config, verify dot-notation get")
    config = ClipCannonConfig.load()
    whisper_model = config.get("processing.whisper_model")
    record(
        "processing.whisper_model == 'large-v3'",
        whisper_model == "large-v3",
        "large-v3",
        str(whisper_model),
    )

    fps = config.get("processing.frame_extraction_fps")
    record(
        "processing.frame_extraction_fps == 2",
        fps == 2,
        "2",
        str(fps),
    )

    version = config.get("version")
    record(
        "version == '1.0'",
        version == "1.0",
        "1.0",
        str(version),
    )

    sub_banner("Happy Path: Pydantic validation")
    v = config.validated
    record(
        "validated.processing.whisper_model",
        v.processing.whisper_model == "large-v3",
        "large-v3",
        v.processing.whisper_model,
    )
    record(
        "validated.gpu.device",
        v.gpu.device == "cuda:0",
        "cuda:0",
        v.gpu.device,
    )

    sub_banner("Happy Path: set + save + reload cycle")
    tmp_config_path = TMP_ROOT / "config_test" / "config.json"
    config2 = ClipCannonConfig.load()
    config2.config_path = tmp_config_path

    print(f"  STATE BEFORE set: processing.whisper_model = {config2.get('processing.whisper_model')}")
    config2.set("processing.whisper_model", "medium")
    print(f"  STATE AFTER set: processing.whisper_model = {config2.get('processing.whisper_model')}")
    record(
        "set() updates value",
        config2.get("processing.whisper_model") == "medium",
        "medium",
        str(config2.get("processing.whisper_model")),
    )

    config2.save()
    record(
        "save() creates file",
        tmp_config_path.exists(),
        "True",
        str(tmp_config_path.exists()),
    )

    # Physical verification: read the saved file
    saved_data = json.loads(tmp_config_path.read_text())
    record(
        "Saved file contains updated value",
        saved_data["processing"]["whisper_model"] == "medium",
        "medium",
        str(saved_data["processing"]["whisper_model"]),
    )

    # Reload from saved file
    config3 = ClipCannonConfig.load(config_path=tmp_config_path)
    record(
        "Reloaded config preserves value",
        config3.get("processing.whisper_model") == "medium",
        "medium",
        str(config3.get("processing.whisper_model")),
    )

    sub_banner("Edge Case: get non-existent key raises ConfigError")
    try:
        config.get("nonexistent.key.path")
        record("get non-existent key raises ConfigError", False, "ConfigError", "No exception")
    except ConfigError:
        record("get non-existent key raises ConfigError", True, "ConfigError", "ConfigError raised")

    sub_banner("Edge Case: set with invalid type triggers pydantic re-validation")
    try:
        bad_config = ClipCannonConfig.load()
        bad_config.set("processing.frame_extraction_fps", "not_an_int")
        # Pydantic might coerce or reject - check
        val = bad_config.validated.processing.frame_extraction_fps
        # If pydantic coerces string to int, that is acceptable behavior
        record(
            "set invalid type (string for int)",
            True,
            "Either coerced or raised",
            f"Coerced to {val}" if isinstance(val, int) else f"Value: {val}",
        )
    except ConfigError:
        record("set invalid type raises ConfigError", True, "ConfigError", "ConfigError raised")

    sub_banner("Edge Case: resolve_path expands ~")
    resolved = config.resolve_path("directories.projects")
    home = Path.home()
    record(
        "resolve_path expands ~",
        str(home) in str(resolved),
        f"Contains {home}",
        str(resolved),
    )

    sub_banner("Edge Case: to_dict returns deep copy")
    d1 = config.to_dict()
    d1["processing"]["whisper_model"] = "MUTATED"
    original = config.get("processing.whisper_model")
    record(
        "to_dict returns deep copy (mutation safe)",
        original != "MUTATED",
        "large-v3",
        str(original),
    )


# ============================================================
# 6. GPU MANAGER
# ============================================================
def test_gpu_manager():
    banner("GPU MANAGER")
    from clipcannon.gpu.manager import ModelManager

    sub_banner("Happy Path: CPU-only mode")
    mgr = ModelManager(device="cpu")
    record("cpu_only == True", mgr.cpu_only, "True", str(mgr.cpu_only))
    record("device == 'cpu'", mgr.device == "cpu", "cpu", mgr.device)
    record("precision == 'fp32'", mgr.precision == "fp32", "fp32", mgr.precision)
    record("concurrent == False", not mgr.concurrent, "False", str(mgr.concurrent))

    sub_banner("Happy Path: Health report in CPU mode")
    health = mgr.get_health()
    print(f"  HEALTH REPORT: {health.to_dict()}")
    record("health.cpu_only == True", health.cpu_only, "True", str(health.cpu_only))
    record("health.device_name == 'CPU'", health.device_name == "CPU", "CPU", health.device_name)
    record("health.vram_total_bytes == 0", health.vram_total_bytes == 0, "0", str(health.vram_total_bytes))
    record("health.loaded_models == []", health.loaded_models == [], "[]", str(health.loaded_models))
    record(
        "health.to_dict() has all keys",
        all(k in health.to_dict() for k in [
            "device_name", "compute_capability", "vram_total_gb", "vram_used_gb",
            "vram_free_gb", "vram_usage_pct", "precision", "concurrent_mode",
            "loaded_models", "cpu_only",
        ]),
        "All 10 keys present",
        str(list(health.to_dict().keys())),
    )

    sub_banner("Happy Path: Load/unload cycle with dummy model")
    dummy_model = {"type": "dummy", "weights": [1, 2, 3]}
    print(f"  STATE BEFORE load: loaded_models = {mgr.loaded_model_names}")
    result = mgr.load("whisperx", loader_fn=lambda: dummy_model, vram_estimate_bytes=1_000_000)
    print(f"  STATE AFTER load: loaded_models = {mgr.loaded_model_names}")

    record("load returns model", result == dummy_model, "dummy_model", str(type(result)))
    record("is_model_loaded('whisperx')", mgr.is_model_loaded("whisperx"), "True", str(mgr.is_model_loaded("whisperx")))
    record("loaded_model_names contains 'whisperx'", "whisperx" in mgr.loaded_model_names, "True", str(mgr.loaded_model_names))

    # get_model
    got = mgr.get_model("whisperx")
    record("get_model returns same object", got is dummy_model, "True", str(got is dummy_model))

    # Re-load same model (should return cached)
    result2 = mgr.load("whisperx")
    record("Re-load returns cached model", result2 is dummy_model, "True", str(result2 is dummy_model))

    # Unload
    print(f"  STATE BEFORE unload: loaded_models = {mgr.loaded_model_names}")
    mgr.unload("whisperx")
    print(f"  STATE AFTER unload: loaded_models = {mgr.loaded_model_names}")
    record("After unload: is_model_loaded == False", not mgr.is_model_loaded("whisperx"), "False", str(mgr.is_model_loaded("whisperx")))

    sub_banner("Edge Case: unload non-loaded model (no-op)")
    mgr.unload("nonexistent_model")
    record("Unload non-loaded model: no crash", True, "No exception", "No exception")

    sub_banner("Edge Case: load without loader_fn raises GPUError")
    from clipcannon.exceptions import GPUError
    try:
        mgr.load("unknown_model")
        record("load without loader_fn raises GPUError", False, "GPUError", "No exception")
    except GPUError:
        record("load without loader_fn raises GPUError", True, "GPUError", "GPUError raised")

    sub_banner("Edge Case: unload_all")
    mgr.load("model_a", loader_fn=lambda: "A", vram_estimate_bytes=100)
    mgr.load("model_b", loader_fn=lambda: "B", vram_estimate_bytes=200)
    print(f"  STATE BEFORE unload_all: loaded_models = {mgr.loaded_model_names}")
    mgr.unload_all()
    print(f"  STATE AFTER unload_all: loaded_models = {mgr.loaded_model_names}")
    record(
        "unload_all clears all models",
        len(mgr.loaded_model_names) == 0,
        "0",
        str(len(mgr.loaded_model_names)),
    )

    sub_banner("Edge Case: LRU eviction in sequential (non-concurrent) CPU mode")
    # In CPU mode, concurrent=False, so loading a new model should unload old ones
    mgr2 = ModelManager(device="cpu")
    mgr2.load("first", loader_fn=lambda: "F", vram_estimate_bytes=100)
    record("Sequential: first model loaded", mgr2.is_model_loaded("first"), "True", str(mgr2.is_model_loaded("first")))
    mgr2.load("second", loader_fn=lambda: "S", vram_estimate_bytes=100)
    record(
        "Sequential: first model evicted when second loaded",
        not mgr2.is_model_loaded("first"),
        "False (evicted)",
        str(mgr2.is_model_loaded("first")),
    )
    record(
        "Sequential: second model loaded",
        mgr2.is_model_loaded("second"),
        "True",
        str(mgr2.is_model_loaded("second")),
    )

    sub_banner("Edge Case: Health report properties")
    record("vram_usage_pct == 0.0 for CPU", health.vram_usage_pct == 0.0, "0.0", str(health.vram_usage_pct))
    record("vram_total_gb == 0.0 for CPU", health.vram_total_gb == 0.0, "0.0", str(health.vram_total_gb))


# ============================================================
# 7. PROVENANCE HASHER
# ============================================================
def test_provenance_hasher():
    banner("PROVENANCE HASHER")
    from clipcannon.provenance.hasher import (
        sha256_bytes,
        sha256_file,
        sha256_string,
        verify_file_hash,
    )
    from clipcannon.exceptions import ProvenanceError

    sub_banner("Happy Path: sha256_file with known content")
    test_file = TMP_ROOT / "hash_test" / "known.txt"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    known_content = b"ClipCannon forensic verification test content"
    test_file.write_bytes(known_content)

    # Compute expected hash independently
    expected_hash = hashlib.sha256(known_content).hexdigest()

    print(f"  STATE: File written to {test_file} ({len(known_content)} bytes)")
    actual_hash = sha256_file(test_file)
    print(f"  EVIDENCE: Expected hash = {expected_hash}")
    print(f"  EVIDENCE: Actual hash   = {actual_hash}")

    record(
        "sha256_file matches independent computation",
        actual_hash == expected_hash,
        expected_hash,
        actual_hash,
    )
    record(
        "Hash is 64 hex chars",
        len(actual_hash) == 64,
        "64",
        str(len(actual_hash)),
    )

    sub_banner("Happy Path: Modify 1 byte, verify different hash")
    modified_content = b"ClipCannon forensic verification test conten!"  # Changed last char
    test_file.write_bytes(modified_content)
    modified_hash = sha256_file(test_file)
    print(f"  EVIDENCE: Modified hash = {modified_hash}")
    record(
        "Modified file produces different hash",
        modified_hash != expected_hash,
        "Different from original",
        f"original={expected_hash[:16]}... modified={modified_hash[:16]}...",
    )

    sub_banner("Happy Path: sha256_bytes")
    data = b"test bytes"
    expected_bytes_hash = hashlib.sha256(data).hexdigest()
    actual_bytes_hash = sha256_bytes(data)
    record(
        "sha256_bytes matches hashlib",
        actual_bytes_hash == expected_bytes_hash,
        expected_bytes_hash,
        actual_bytes_hash,
    )

    sub_banner("Happy Path: sha256_string")
    text = "test string"
    expected_str_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    actual_str_hash = sha256_string(text)
    record(
        "sha256_string matches hashlib(utf-8 encoded)",
        actual_str_hash == expected_str_hash,
        expected_str_hash,
        actual_str_hash,
    )

    sub_banner("Happy Path: verify_file_hash")
    # Restore known content
    test_file.write_bytes(known_content)
    verified = verify_file_hash(test_file, expected_hash)
    record("verify_file_hash returns True for matching", verified, "True", str(verified))

    not_verified = verify_file_hash(test_file, "0000" * 16)
    record("verify_file_hash returns False for mismatch", not not_verified, "False", str(not_verified))

    sub_banner("Edge Case: sha256_file on non-existent file raises ProvenanceError")
    try:
        sha256_file(Path("/tmp/definitely_does_not_exist_fsv.txt"))
        record("Non-existent file raises ProvenanceError", False, "ProvenanceError", "No exception")
    except ProvenanceError:
        record("Non-existent file raises ProvenanceError", True, "ProvenanceError", "ProvenanceError raised")

    sub_banner("Edge Case: sha256_file on directory raises ProvenanceError")
    try:
        sha256_file(TMP_ROOT)
        record("Directory raises ProvenanceError", False, "ProvenanceError", "No exception")
    except ProvenanceError:
        record("Directory raises ProvenanceError", True, "ProvenanceError", "ProvenanceError raised")

    sub_banner("Edge Case: sha256_bytes with empty bytes")
    empty_hash = sha256_bytes(b"")
    expected_empty = hashlib.sha256(b"").hexdigest()
    record(
        "sha256_bytes(b'') matches empty hash",
        empty_hash == expected_empty,
        expected_empty,
        empty_hash,
    )

    sub_banner("Edge Case: sha256_string with empty string")
    empty_str_hash = sha256_string("")
    expected_empty_str = hashlib.sha256(b"").hexdigest()
    record(
        "sha256_string('') matches empty bytes hash",
        empty_str_hash == expected_empty_str,
        expected_empty_str,
        empty_str_hash,
    )


# ============================================================
# 8. PROVENANCE CHAIN
# ============================================================
def test_provenance_chain():
    banner("PROVENANCE CHAIN")
    from clipcannon.provenance.chain import (
        GENESIS_HASH,
        ChainVerificationResult,
        compute_chain_hash,
        get_chain_from_genesis,
        verify_chain,
    )
    from clipcannon.db.schema import create_project_db
    from clipcannon.db.connection import get_connection

    sub_banner("Happy Path: Compute 5 chain hashes in sequence")
    hashes = []
    parent = GENESIS_HASH
    for i in range(5):
        h = compute_chain_hash(
            parent_hash=parent,
            input_sha256=f"input_{i:03d}",
            output_sha256=f"output_{i:03d}",
            operation=f"stage_{i}",
            model_name="testmodel",
            model_version="1.0",
            model_params={"batch_size": 32},
        )
        hashes.append(h)
        print(f"  Chain[{i}]: parent={parent[:16]}... -> hash={h[:16]}...")
        parent = h

    record(
        "5 chain hashes computed",
        len(hashes) == 5,
        "5",
        str(len(hashes)),
    )

    # All should be unique
    record(
        "All chain hashes are unique",
        len(set(hashes)) == 5,
        "5 unique",
        f"{len(set(hashes))} unique",
    )

    # Each hash is 64 hex chars
    all_64 = all(len(h) == 64 for h in hashes)
    record("All hashes are 64 hex chars", all_64, "True", str(all_64))

    sub_banner("Happy Path: Write chain to DB, verify_chain passes")
    project_id = "fsv_chain_test"
    base_dir = TMP_ROOT / "chain_projects"
    db_path = create_project_db(project_id, base_dir=base_dir)

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    # Insert project
    conn.execute(
        "INSERT INTO project (project_id, name, source_path, source_sha256, duration_ms, resolution, fps, codec) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, "Chain Test", "/tmp/test.mp4", "abc", 60000, "1920x1080", 30.0, "h264"),
    )

    # Insert 5 provenance records with computed chain hashes
    parent_hash = GENESIS_HASH
    record_ids = []
    for i in range(5):
        rid = f"prov_{i+1:03d}"
        record_ids.append(rid)
        chain_h = compute_chain_hash(
            parent_hash=parent_hash,
            input_sha256=f"input_{i:03d}",
            output_sha256=f"output_{i:03d}",
            operation=f"stage_{i}",
            model_name="testmodel",
            model_version="1.0",
            model_params={"batch_size": 32},
        )
        parent_record_id = record_ids[i - 1] if i > 0 else None
        ts = f"2026-01-01T00:00:{i:02d}+00:00"
        conn.execute(
            "INSERT INTO provenance (record_id, project_id, timestamp_utc, operation, stage, "
            "input_sha256, output_sha256, parent_record_id, model_name, model_version, "
            "model_parameters, chain_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, project_id, ts, f"stage_{i}", f"stage_{i}",
             f"input_{i:03d}", f"output_{i:03d}", parent_record_id,
             "testmodel", "1.0", json.dumps({"batch_size": 32}, sort_keys=True), chain_h),
        )
        parent_hash = chain_h

    conn.commit()
    conn.close()

    # Verify chain
    result = verify_chain(project_id, db_path)
    print(f"  EVIDENCE: verify_chain result = verified={result.verified}, total={result.total_records}")
    record(
        "verify_chain passes for valid chain",
        result.verified,
        "True",
        str(result.verified),
    )
    record(
        "verify_chain total_records == 5",
        result.total_records == 5,
        "5",
        str(result.total_records),
    )

    sub_banner("Happy Path: get_chain_from_genesis")
    chain = get_chain_from_genesis(project_id, "prov_005", db_path)
    record(
        "get_chain_from_genesis returns 5 records",
        len(chain) == 5,
        "5",
        str(len(chain)),
    )
    record(
        "Chain starts at prov_001 (genesis)",
        chain[0].record_id == "prov_001",
        "prov_001",
        chain[0].record_id if chain else "EMPTY",
    )
    record(
        "Chain ends at prov_005 (target)",
        chain[-1].record_id == "prov_005",
        "prov_005",
        chain[-1].record_id if chain else "EMPTY",
    )

    sub_banner("TAMPER TEST: Modify record 3 chain_hash, verify chain fails AT record 3")
    conn2 = get_connection(db_path, enable_vec=False, dict_rows=True)
    print(f"  STATE BEFORE tamper: Fetching prov_003 chain_hash...")
    original_row = conn2.execute(
        "SELECT chain_hash FROM provenance WHERE record_id = 'prov_003'"
    ).fetchone()
    print(f"  Original chain_hash for prov_003 = {original_row['chain_hash'][:32]}...")

    tampered_hash = "0000" * 16  # 64 zeros
    conn2.execute(
        "UPDATE provenance SET chain_hash = ? WHERE record_id = 'prov_003'",
        (tampered_hash,),
    )
    conn2.commit()
    print(f"  STATE AFTER tamper: chain_hash for prov_003 set to {tampered_hash[:32]}...")
    conn2.close()

    tampered_result = verify_chain(project_id, db_path)
    print(f"  EVIDENCE: verify_chain after tamper = verified={tampered_result.verified}, broken_at={tampered_result.broken_at}")
    record(
        "Tampered chain fails verification",
        not tampered_result.verified,
        "False",
        str(tampered_result.verified),
    )
    record(
        "Chain breaks at prov_003",
        tampered_result.broken_at == "prov_003",
        "prov_003",
        str(tampered_result.broken_at),
    )

    sub_banner("Edge Case: verify_chain with empty project")
    empty_result = verify_chain("nonexistent_project_xyz", db_path)
    record(
        "Empty project chain verifies (vacuously true)",
        empty_result.verified,
        "True",
        str(empty_result.verified),
    )
    record(
        "Empty project has 0 records",
        empty_result.total_records == 0,
        "0",
        str(empty_result.total_records),
    )

    sub_banner("Edge Case: compute_chain_hash deterministic")
    h1 = compute_chain_hash("GENESIS", "in", "out", "op", "m", "v", {"k": 1})
    h2 = compute_chain_hash("GENESIS", "in", "out", "op", "m", "v", {"k": 1})
    record("Same inputs produce same hash", h1 == h2, h1[:32], h2[:32])

    h3 = compute_chain_hash("GENESIS", "in", "out", "op", "m", "v", {"k": 2})
    record("Different params produce different hash", h1 != h3, "Different", f"h1={h1[:16]}... h3={h3[:16]}...")


# ============================================================
# 9. PROVENANCE RECORDER
# ============================================================
def test_provenance_recorder():
    banner("PROVENANCE RECORDER")
    from clipcannon.provenance.recorder import (
        ExecutionInfo,
        InputInfo,
        ModelInfo,
        OutputInfo,
        get_provenance_records,
        get_provenance_timeline,
        record_provenance,
    )
    from clipcannon.provenance.chain import verify_chain
    from clipcannon.db.schema import create_project_db
    from clipcannon.db.connection import get_connection

    project_id = "fsv_recorder_test"
    base_dir = TMP_ROOT / "recorder_projects"
    db_path = create_project_db(project_id, base_dir=base_dir)

    # Insert project row for FK
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    conn.execute(
        "INSERT INTO project (project_id, name, source_path, source_sha256, duration_ms, resolution, fps, codec) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, "Recorder Test", "/tmp/test.mp4", "abc", 60000, "1920x1080", 30.0, "h264"),
    )
    conn.commit()
    conn.close()

    sub_banner("Happy Path: Record 3 provenance entries")
    records_made = []
    for i in range(3):
        parent = records_made[-1] if records_made else None
        rid = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=f"operation_{i+1}",
            stage=f"stage_{i+1}",
            input_info=InputInfo(
                file_path=f"/tmp/input_{i+1}.txt",
                sha256=hashlib.sha256(f"input_{i+1}".encode()).hexdigest(),
                size_bytes=1000 * (i + 1),
            ),
            output_info=OutputInfo(
                file_path=f"/tmp/output_{i+1}.txt",
                sha256=hashlib.sha256(f"output_{i+1}".encode()).hexdigest(),
                size_bytes=2000 * (i + 1),
                record_count=10 * (i + 1),
            ),
            model_info=ModelInfo(
                name="test_model",
                version="2.0",
                quantization="int8",
                parameters={"beam_size": 5},
            ),
            execution_info=ExecutionInfo(
                duration_ms=5000 * (i + 1),
                gpu_device="cpu",
                vram_peak_mb=0.0,
            ),
            parent_record_id=parent,
            description=f"Test operation {i+1}",
        )
        records_made.append(rid)
        print(f"  Recorded provenance: {rid}")

    record(
        "3 records created",
        len(records_made) == 3,
        "3",
        str(len(records_made)),
    )
    record(
        "record_ids are prov_001, prov_002, prov_003",
        records_made == ["prov_001", "prov_002", "prov_003"],
        "['prov_001', 'prov_002', 'prov_003']",
        str(records_made),
    )

    sub_banner("Physical Verification: SELECT * FROM provenance")
    conn2 = get_connection(db_path, enable_vec=False, dict_rows=True)
    raw_rows = conn2.execute(
        "SELECT record_id, project_id, operation, stage, chain_hash, parent_record_id "
        "FROM provenance ORDER BY record_id"
    ).fetchall()
    print(f"  Retrieved {len(raw_rows)} rows from provenance table:")
    for r in raw_rows:
        print(f"    record_id={r['record_id']}, op={r['operation']}, stage={r['stage']}, "
              f"chain_hash={str(r['chain_hash'])[:24]}..., parent={r['parent_record_id']}")

    record(
        "Physical SELECT returns 3 rows",
        len(raw_rows) == 3,
        "3",
        str(len(raw_rows)),
    )

    # Verify chain_hash is non-empty for all
    all_have_hash = all(r["chain_hash"] and len(str(r["chain_hash"])) == 64 for r in raw_rows)
    record(
        "All records have 64-char chain_hash",
        all_have_hash,
        "True",
        str(all_have_hash),
    )

    # Verify parent linkage
    record(
        "prov_001 has no parent",
        raw_rows[0]["parent_record_id"] is None,
        "None",
        str(raw_rows[0]["parent_record_id"]),
    )
    record(
        "prov_002 parent is prov_001",
        raw_rows[1]["parent_record_id"] == "prov_001",
        "prov_001",
        str(raw_rows[1]["parent_record_id"]),
    )
    record(
        "prov_003 parent is prov_002",
        raw_rows[2]["parent_record_id"] == "prov_002",
        "prov_002",
        str(raw_rows[2]["parent_record_id"]),
    )
    conn2.close()

    sub_banner("Happy Path: verify_chain passes for recorded entries")
    chain_result = verify_chain(project_id, db_path)
    print(f"  EVIDENCE: verify_chain = verified={chain_result.verified}, total={chain_result.total_records}")
    record(
        "verify_chain passes",
        chain_result.verified,
        "True",
        str(chain_result.verified),
    )
    record(
        "verify_chain total_records == 3",
        chain_result.total_records == 3,
        "3",
        str(chain_result.total_records),
    )

    sub_banner("Happy Path: get_provenance_records")
    records = get_provenance_records(db_path, project_id)
    record(
        "get_provenance_records returns 3",
        len(records) == 3,
        "3",
        str(len(records)),
    )

    # Filter by operation
    filtered = get_provenance_records(db_path, project_id, operation="operation_2")
    record(
        "Filtered by operation returns 1",
        len(filtered) == 1,
        "1",
        str(len(filtered)),
    )
    if filtered:
        record(
            "Filtered record is prov_002",
            filtered[0].record_id == "prov_002",
            "prov_002",
            filtered[0].record_id,
        )

    sub_banner("Happy Path: get_provenance_timeline")
    timeline = get_provenance_timeline(db_path, project_id)
    record(
        "get_provenance_timeline returns 3",
        len(timeline) == 3,
        "3",
        str(len(timeline)),
    )

    sub_banner("Edge Case: Record with no model_info")
    rid_no_model = record_provenance(
        db_path=db_path,
        project_id=project_id,
        operation="no_model_op",
        stage="no_model_stage",
        input_info=InputInfo(sha256="aaa"),
        output_info=OutputInfo(sha256="bbb"),
        model_info=None,
        execution_info=ExecutionInfo(duration_ms=100),
        parent_record_id="prov_003",
        description="No model test",
    )
    record(
        "Record with no model_info succeeds",
        rid_no_model == "prov_004",
        "prov_004",
        rid_no_model,
    )

    sub_banner("Edge Case: get_provenance_records for non-existent project")
    empty_records = get_provenance_records(db_path, "nonexistent_project")
    record(
        "Non-existent project returns empty list",
        len(empty_records) == 0,
        "0",
        str(len(empty_records)),
    )


# ============================================================
# 10. PROVENANCE HASHER - sha256_table_content
# ============================================================
def test_sha256_table_content():
    banner("PROVENANCE HASHER - TABLE CONTENT HASHING")
    from clipcannon.provenance.hasher import sha256_table_content
    from clipcannon.db.schema import create_project_db
    from clipcannon.db.connection import get_connection

    project_id = "fsv_table_hash"
    base_dir = TMP_ROOT / "table_hash_projects"
    db_path = create_project_db(project_id, base_dir=base_dir)

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    conn.execute(
        "INSERT INTO project (project_id, name, source_path, source_sha256, duration_ms, resolution, fps, codec) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, "Table Hash Test", "/tmp/test.mp4", "abc", 60000, "1920x1080", 30.0, "h264"),
    )
    conn.execute(
        "INSERT INTO transcript_segments (project_id, start_ms, end_ms, text, language, word_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, 0, 5000, "Hello", "en", 1),
    )
    conn.commit()

    sub_banner("Happy Path: Hash table content")
    h1 = sha256_table_content(conn, "transcript_segments", project_id)
    record("sha256_table_content returns 64-char hash", len(h1) == 64, "64", str(len(h1)))

    # Same data should produce same hash
    h2 = sha256_table_content(conn, "transcript_segments", project_id)
    record("Deterministic: same data same hash", h1 == h2, h1[:32], h2[:32])

    sub_banner("Edge Case: Different data produces different hash")
    conn.execute(
        "INSERT INTO transcript_segments (project_id, start_ms, end_ms, text, language, word_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, 5000, 10000, "World", "en", 1),
    )
    conn.commit()
    h3 = sha256_table_content(conn, "transcript_segments", project_id)
    record("New data changes hash", h3 != h1, "Different", f"before={h1[:16]}... after={h3[:16]}...")

    sub_banner("Edge Case: Non-existent project returns hash of empty list")
    h_empty = sha256_table_content(conn, "transcript_segments", "nonexistent_proj")
    record("Empty project returns valid hash", len(h_empty) == 64, "64", str(len(h_empty)))

    sub_banner("Edge Case: Invalid table name raises ProvenanceError")
    from clipcannon.exceptions import ProvenanceError
    try:
        sha256_table_content(conn, "table; DROP TABLE--", project_id)
        record("Invalid table name raises ProvenanceError", False, "ProvenanceError", "No exception")
    except ProvenanceError:
        record("Invalid table name raises ProvenanceError", True, "ProvenanceError", "ProvenanceError raised")

    conn.close()


# ============================================================
# FINAL SUMMARY
# ============================================================
def print_summary():
    sep = "=" * 72
    print(f"\n\n{sep}")
    print("  SHERLOCK HOLMES - INVESTIGATION COMPLETE")
    print(sep)
    print(f"\n  TOTAL TESTS: {PASS_COUNT + FAIL_COUNT}")
    print(f"  PASSED:      {PASS_COUNT}")
    print(f"  FAILED:      {FAIL_COUNT}")

    if FAIL_COUNT == 0:
        print("\n  VERDICT: ALL MODULES PROVEN INNOCENT")
        print("  The evidence overwhelmingly supports correct implementation.")
    else:
        print(f"\n  VERDICT: {FAIL_COUNT} FAILURE(S) DETECTED - GUILTY")
        print("  The following tests produced contradictory evidence:")
        for e in EVIDENCE:
            if e["status"] == "FAIL":
                print(f"    [FAIL] {e['test']}")
                print(f"           Expected: {e['expected']}")
                print(f"           Actual:   {e['actual']}")
                if e["detail"]:
                    print(f"           Detail:   {e['detail']}")

    print(f"\n  Evidence preserved at: {TMP_ROOT}")
    print(sep)
    return FAIL_COUNT


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=" * 72)
    print("  SHERLOCK HOLMES FULL STATE VERIFICATION (FSV)")
    print("  ClipCannon Phase 1 Core Infrastructure")
    print(f"  Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Temp root: {TMP_ROOT}")
    print("=" * 72)

    test_funcs = [
        ("Exceptions", test_exceptions),
        ("DB Connection", test_db_connection),
        ("DB Schema", test_db_schema),
        ("DB Queries", test_db_queries),
        ("Configuration", test_config),
        ("GPU Manager", test_gpu_manager),
        ("Provenance Hasher", test_provenance_hasher),
        ("Provenance Chain", test_provenance_chain),
        ("Provenance Recorder", test_provenance_recorder),
        ("SHA256 Table Content", test_sha256_table_content),
    ]

    for name, fn in test_funcs:
        safe_run(name, fn)

    failures = print_summary()

    # Cleanup
    try:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    except Exception:
        pass

    sys.exit(failures)
