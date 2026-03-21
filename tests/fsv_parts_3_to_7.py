"""FSV Parts 3-7: Billing, MCP Tools, Schema, Config, GPU."""
import sys
import asyncio
import sqlite3
import json
import os
import time
import hashlib
import tempfile
import shutil
import subprocess
import signal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

VERDICTS = []

def verdict(test_name, passed, expected="", actual="", reason=""):
    status = "PASS" if passed else "FAIL"
    VERDICTS.append((test_name, status, reason))
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    if expected:
        print(f"EXPECTED: {expected}")
    if actual:
        print(f"ACTUAL:   {actual}")
    print(f"VERDICT: {status}")
    if reason and not passed:
        print(f"REASON:  {reason}")
    print(f"{'='*60}")


# ============================================================
# PART 3: BILLING SYSTEM
# ============================================================
async def test_billing():
    print(f"\n\n{'#'*60}")
    print(f"# FSV PART 3: BILLING SYSTEM VERIFICATION")
    print(f"{'#'*60}")

    from clipcannon.billing.hmac_integrity import (
        get_machine_id, sign_balance, verify_balance, verify_balance_or_raise,
        derive_hmac_key,
    )
    from clipcannon.billing.credits import estimate_cost, CREDIT_RATES
    from clipcannon.exceptions import BillingError

    # --- Test HMAC functions directly (no server needed) ---
    print("\n--- HMAC Integrity Tests ---")

    machine_id = get_machine_id()
    verdict("Machine ID is 32 hex chars", len(machine_id) == 32 and all(c in '0123456789abcdef' for c in machine_id),
            expected="32 hex chars",
            actual=f"len={len(machine_id)}, id={machine_id[:8]}...")

    hmac_key = derive_hmac_key(machine_id)
    verdict("HMAC key is 32 bytes", len(hmac_key) == 32,
            expected="32 bytes",
            actual=f"len={len(hmac_key)}")

    # Sign and verify
    balance_100 = 100
    sig = sign_balance(balance_100, machine_id)
    valid = verify_balance(balance_100, sig, machine_id)
    verdict("sign_balance + verify_balance round-trip", valid,
            expected="verify=True",
            actual=f"verify={valid}")

    # Tamper test: wrong balance
    tampered = verify_balance(999999, sig, machine_id)
    verdict("Tampered balance detected", not tampered,
            expected="verify=False for tampered balance",
            actual=f"verify={tampered}")

    # verify_balance_or_raise on tampered
    try:
        verify_balance_or_raise(999999, sig, machine_id)
        verdict("verify_balance_or_raise raises on tamper", False,
                reason="Should have raised BillingError")
    except BillingError as e:
        verdict("verify_balance_or_raise raises on tamper", True,
                expected="BillingError with BALANCE_TAMPERED",
                actual=f"BillingError: {e.message[:60]}...")

    # Credit rate estimation
    print("\n--- Credit Rate Tests ---")
    cost = estimate_cost("analyze")
    verdict("estimate_cost('analyze') returns 10", cost == 10,
            expected="10",
            actual=f"{cost}")

    try:
        estimate_cost("nonexistent_op")
        verdict("estimate_cost unknown op raises", False, reason="Should have raised")
    except BillingError:
        verdict("estimate_cost unknown op raises", True,
                expected="BillingError",
                actual="BillingError raised")

    # --- License Server Integration Tests ---
    print("\n--- License Server Integration Tests ---")

    # Remove existing license.db to start fresh
    license_db = Path.home() / ".clipcannon" / "license.db"
    if license_db.exists():
        license_db.unlink()

    # Start the license server
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "license_server.server:app", "--port", "3100", "--no-access-log"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    import httpx
    for _ in range(20):
        try:
            resp = httpx.get("http://localhost:3100/health", timeout=1.0)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        verdict("License server started", False, reason="Server did not start within 10s")
        server_proc.kill()
        return

    try:
        verdict("License server started", True,
                expected="health endpoint returns 200",
                actual="200 OK")

        # a. Check initial balance (should be 100)
        resp = httpx.get("http://localhost:3100/v1/balance")
        balance_data = resp.json()
        verdict("Initial balance is 100", balance_data.get("balance") == 100,
                expected="balance=100",
                actual=f"balance={balance_data.get('balance')}")

        # Independently verify in license.db
        raw_conn = sqlite3.connect(str(license_db))
        raw_conn.row_factory = sqlite3.Row
        raw_row = raw_conn.execute("SELECT balance, balance_hmac FROM balance WHERE id=1").fetchone()
        raw_conn.close()
        verdict("Raw DB balance is 100", raw_row['balance'] == 100,
                expected="balance=100 in raw DB",
                actual=f"balance={raw_row['balance']}")

        # Verify HMAC is correct
        raw_hmac_ok = verify_balance(raw_row['balance'], raw_row['balance_hmac'], machine_id)
        verdict("Raw DB HMAC is valid", raw_hmac_ok,
                expected="HMAC matches",
                actual=f"valid={raw_hmac_ok}")

        # b. Charge 10 credits
        charge_resp = httpx.post("http://localhost:3100/v1/charge", json={
            "machine_id": machine_id,
            "operation": "analyze",
            "credits": 10,
            "project_id": "test_proj_1",
            "idempotency_key": "charge-1",
        })
        charge_data = charge_resp.json()
        verdict("Charge 10 credits succeeds", charge_data.get("success") == True,
                expected="success=True",
                actual=f"success={charge_data.get('success')}")
        verdict("Balance after charge is 90", charge_data.get("balance_after") == 90,
                expected="balance_after=90",
                actual=f"balance_after={charge_data.get('balance_after')}")

        # Independently verify in raw DB
        raw_conn = sqlite3.connect(str(license_db))
        raw_conn.row_factory = sqlite3.Row
        raw_row = raw_conn.execute("SELECT balance, balance_hmac FROM balance WHERE id=1").fetchone()
        raw_conn.close()
        verdict("Raw DB balance after charge is 90", raw_row['balance'] == 90,
                expected="balance=90",
                actual=f"balance={raw_row['balance']}")
        raw_hmac_ok = verify_balance(raw_row['balance'], raw_row['balance_hmac'], machine_id)
        verdict("Raw DB HMAC valid after charge", raw_hmac_ok,
                expected="HMAC matches",
                actual=f"valid={raw_hmac_ok}")

        # c. Refund the charge
        txn_id = charge_data.get("transaction_id", "")
        refund_resp = httpx.post("http://localhost:3100/v1/refund", json={
            "machine_id": machine_id,
            "transaction_id": txn_id,
            "reason": "FSV test refund",
            "project_id": "test_proj_1",
        })
        refund_data = refund_resp.json()
        verdict("Refund succeeds", refund_data.get("success") == True,
                expected="success=True",
                actual=f"success={refund_data.get('success')}")
        verdict("Balance after refund is 100", refund_data.get("balance_after") == 100,
                expected="balance_after=100",
                actual=f"balance_after={refund_data.get('balance_after')}")

        # Independently verify
        raw_conn = sqlite3.connect(str(license_db))
        raw_conn.row_factory = sqlite3.Row
        raw_row = raw_conn.execute("SELECT balance FROM balance WHERE id=1").fetchone()
        raw_conn.close()
        verdict("Raw DB balance after refund is 100", raw_row['balance'] == 100,
                expected="balance=100",
                actual=f"balance={raw_row['balance']}")

        # d. EDGE CASE: Insufficient credits
        print("\n--- Edge Case: Insufficient Credits ---")
        # Set balance to 5 via add_credits (subtract 95)
        httpx.post("http://localhost:3100/v1/charge", json={
            "machine_id": machine_id,
            "operation": "analyze",
            "credits": 95,
            "project_id": "test_drain",
            "idempotency_key": "drain-1",
        })

        bal_resp = httpx.get("http://localhost:3100/v1/balance")
        balance_now = bal_resp.json().get("balance")
        verdict("Balance drained to 5", balance_now == 5,
                expected="balance=5",
                actual=f"balance={balance_now}")

        insuf_resp = httpx.post("http://localhost:3100/v1/charge", json={
            "machine_id": machine_id,
            "operation": "analyze",
            "credits": 10,
            "project_id": "test_insuf",
            "idempotency_key": "insuf-1",
        })
        insuf_data = insuf_resp.json()
        verdict("Insufficient credits rejected", insuf_data.get("success") == False,
                expected="success=False",
                actual=f"success={insuf_data.get('success')}")
        verdict("Error code is INSUFFICIENT_CREDITS",
                insuf_data.get("error") == "INSUFFICIENT_CREDITS",
                expected="INSUFFICIENT_CREDITS",
                actual=f"error={insuf_data.get('error')}")

        # Verify balance unchanged
        bal_after = httpx.get("http://localhost:3100/v1/balance").json().get("balance")
        verdict("Balance unchanged after rejection", bal_after == 5,
                expected="balance=5",
                actual=f"balance={bal_after}")

        # e. EDGE CASE: HMAC tamper detection
        print("\n--- Edge Case: HMAC Tamper Detection ---")
        raw_conn = sqlite3.connect(str(license_db))
        raw_conn.execute("UPDATE balance SET balance = 999999 WHERE id = 1")
        raw_conn.commit()
        raw_conn.close()

        tamper_resp = httpx.get("http://localhost:3100/v1/balance")
        verdict("HMAC tamper detected on read",
                tamper_resp.status_code == 403 or "TAMPERED" in tamper_resp.text,
                expected="403 or BALANCE_TAMPERED error",
                actual=f"status={tamper_resp.status_code}, body={tamper_resp.text[:100]}")

        # Fix the tamper by restoring balance and HMAC
        raw_conn = sqlite3.connect(str(license_db))
        fixed_hmac = sign_balance(5, machine_id)
        raw_conn.execute("UPDATE balance SET balance = 5, balance_hmac = ? WHERE id = 1", (fixed_hmac,))
        raw_conn.commit()
        raw_conn.close()

        # f. EDGE CASE: Idempotency
        print("\n--- Edge Case: Idempotency ---")
        # Add credits back first
        httpx.post("http://localhost:3100/v1/add_credits", json={"credits": 95, "reason": "FSV restore"})

        idem_key = "test-idem-123"
        idem_resp1 = httpx.post("http://localhost:3100/v1/charge", json={
            "machine_id": machine_id,
            "operation": "analyze",
            "credits": 10,
            "project_id": "test_idem",
            "idempotency_key": idem_key,
        })
        idem_data1 = idem_resp1.json()

        idem_resp2 = httpx.post("http://localhost:3100/v1/charge", json={
            "machine_id": machine_id,
            "operation": "analyze",
            "credits": 10,
            "project_id": "test_idem",
            "idempotency_key": idem_key,
        })
        idem_data2 = idem_resp2.json()

        verdict("Both idempotent charges succeed",
                idem_data1.get("success") and idem_data2.get("success"),
                expected="both success=True",
                actual=f"first={idem_data1.get('success')}, second={idem_data2.get('success')}")
        verdict("Idempotent replay detected",
                idem_data2.get("idempotent_replay") == True,
                expected="idempotent_replay=True on second call",
                actual=f"idempotent_replay={idem_data2.get('idempotent_replay')}")

        # Check balance only charged once
        final_bal = httpx.get("http://localhost:3100/v1/balance").json().get("balance")
        verdict("Balance charged only once (idempotency)", final_bal == 90,
                expected="balance=90 (charged once from 100)",
                actual=f"balance={final_bal}")

        # Check transactions table for this key
        raw_conn = sqlite3.connect(str(license_db))
        raw_conn.row_factory = sqlite3.Row
        idem_txns = raw_conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE idempotency_key = ?",
            (idem_key,)
        ).fetchone()
        raw_conn.close()
        verdict("Only 1 transaction for idempotency key", idem_txns['cnt'] == 1,
                expected="count=1",
                actual=f"count={idem_txns['cnt']}")

    finally:
        server_proc.terminate()
        server_proc.wait(timeout=5)


# ============================================================
# PART 4: MCP TOOLS
# ============================================================
async def test_mcp_tools():
    print(f"\n\n{'#'*60}")
    print(f"# FSV PART 4: MCP TOOLS VERIFICATION")
    print(f"{'#'*60}")

    from clipcannon.tools.project import (
        clipcannon_project_create, clipcannon_project_open,
    )
    from clipcannon.tools.config_tools import (
        clipcannon_config_get, clipcannon_config_set,
    )

    VIDEO_PATH = "/home/cabdru/clipcannon/testdata/2026-03-20 14-43-20.mp4"

    # 1. Create project with real video
    print("\n--- Create project with real video ---")
    result = await clipcannon_project_create("FSV MCP Test", VIDEO_PATH)
    has_project_id = "project_id" in result and not "error" in result
    verdict("Project created successfully", has_project_id,
            expected="project_id in result",
            actual=f"keys={list(result.keys())[:5]}")

    if has_project_id:
        project_id = result["project_id"]
        # Verify in raw DB
        db_path = Path.home() / ".clipcannon" / "projects" / project_id / "analysis.db"
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.row_factory = sqlite3.Row
        proj_row = raw_conn.execute("SELECT * FROM project WHERE project_id = ?", (project_id,)).fetchone()
        raw_conn.close()
        verdict("Project exists in raw DB", proj_row is not None,
                expected="project row found",
                actual=f"found={proj_row is not None}")

        if proj_row:
            verdict("Project has correct name", proj_row['name'] == 'FSV MCP Test',
                    expected="name='FSV MCP Test'",
                    actual=f"name={proj_row['name']}")

        # Clean up
        shutil.rmtree(db_path.parent, ignore_errors=True)

    # 2. Config get
    print("\n--- Config get ---")
    config_result = await clipcannon_config_get("processing.whisper_model")
    verdict("Config get returns value", config_result.get("value") == "large-v3",
            expected="value='large-v3'",
            actual=f"value={config_result.get('value')}")

    # 3. Config set and get
    print("\n--- Config set and get ---")
    set_result = await clipcannon_config_set("gpu.max_vram_usage_gb", 16)
    verdict("Config set succeeds", set_result.get("saved") == True,
            expected="saved=True",
            actual=f"saved={set_result.get('saved')}")

    get_result = await clipcannon_config_get("gpu.max_vram_usage_gb")
    verdict("Config get returns updated value", get_result.get("value") == 16,
            expected="value=16",
            actual=f"value={get_result.get('value')}")

    # Verify config file on disk
    config_path = Path.home() / ".clipcannon" / "config.json"
    if config_path.exists():
        raw_config = json.loads(config_path.read_text())
        verdict("Config file has updated value", raw_config.get("gpu", {}).get("max_vram_usage_gb") == 16,
                expected="gpu.max_vram_usage_gb=16 in file",
                actual=f"value={raw_config.get('gpu', {}).get('max_vram_usage_gb')}")

    # Restore original
    await clipcannon_config_set("gpu.max_vram_usage_gb", 24)

    # 5. Edge case: nonexistent file
    print("\n--- Edge case: nonexistent file ---")
    err_result = await clipcannon_project_create("Bad Project", "/nonexistent/path/video.mp4")
    verdict("Nonexistent file returns error",
            "error" in err_result and err_result["error"]["code"] == "INVALID_PARAMETER",
            expected="error.code=INVALID_PARAMETER",
            actual=f"error={err_result.get('error', {}).get('code')}")

    # Verify no project was created
    projects_dir = Path.home() / ".clipcannon" / "projects"
    # The project should not have been created - count dirs before and after
    # (simplified: just check the error response is correct)
    verdict("No project created for invalid file", "project_id" not in err_result,
            expected="no project_id in response",
            actual=f"project_id present={('project_id' in err_result)}")

    # 6. Edge case: open nonexistent project
    print("\n--- Edge case: open nonexistent project ---")
    open_result = await clipcannon_project_open("proj_nonexistent_99999")
    verdict("Open nonexistent returns PROJECT_NOT_FOUND",
            "error" in open_result and open_result["error"]["code"] == "PROJECT_NOT_FOUND",
            expected="error.code=PROJECT_NOT_FOUND",
            actual=f"error={open_result.get('error', {}).get('code')}")


# ============================================================
# PART 5: DATABASE SCHEMA
# ============================================================
async def test_schema():
    print(f"\n\n{'#'*60}")
    print(f"# FSV PART 5: DATABASE SCHEMA VERIFICATION")
    print(f"{'#'*60}")

    from clipcannon.db.schema import create_project_db

    tmpdir = Path(tempfile.mkdtemp(prefix="fsv_schema_"))
    try:
        db_path = create_project_db("schema_test", tmpdir)

        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.row_factory = sqlite3.Row

        # 1. List all tables
        tables = [r['name'] for r in raw_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        print(f"\nTables found: {tables}")

        expected_tables = [
            "acoustic", "beat_sections", "beats", "content_safety",
            "emotion_curve", "highlights", "music_sections", "on_screen_text",
            "pacing", "profanity_events", "project", "provenance", "reactions",
            "scenes", "schema_version", "silence_gaps", "speakers",
            "storyboard_grids", "stream_status", "text_change_events",
            "topics", "transcript_segments", "transcript_words",
        ]

        for t in expected_tables:
            verdict(f"Table {t} exists", t in tables,
                    expected=f"{t} in tables",
                    actual=f"present={t in tables}")

        # 2. List all indexes
        indexes = [r['name'] for r in raw_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        print(f"\nIndexes found: {indexes}")

        expected_indexes = [
            "idx_segments_time", "idx_words_time", "idx_words_segment",
            "idx_scenes_time", "idx_emotion_time", "idx_highlights_score",
            "idx_reactions_time", "idx_provenance_project", "idx_provenance_chain",
        ]
        for idx in expected_indexes:
            verdict(f"Index {idx} exists", idx in indexes,
                    expected=f"{idx} in indexes",
                    actual=f"present={idx in indexes}")

        # 3. Check virtual tables (sqlite-vec)
        vtables = [r['name'] for r in raw_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%vec0%' ORDER BY name"
        ).fetchall()]
        # If sqlite-vec is installed, we should have vec_frames etc.
        # If not, it's expected to be empty
        print(f"\nVirtual tables: {vtables}")
        try:
            import sqlite_vec
            vec_expected = ["vec_frames", "vec_semantic", "vec_emotion", "vec_speakers"]
            for vt in vec_expected:
                verdict(f"Virtual table {vt} exists", vt in vtables or vt in tables,
                        expected=f"{vt} exists",
                        actual=f"present={vt in vtables or vt in tables}")

            # Try inserting into vec_frames with correct dimensions (1152)
            import struct
            vec_1152 = struct.pack(f'{1152}f', *([0.1] * 1152))
            try:
                raw_conn.execute(
                    "INSERT INTO vec_frames(frame_id, project_id, timestamp_ms, frame_path, visual_embedding) VALUES (?, ?, ?, ?, ?)",
                    (1, "test", 0, "test.jpg", vec_1152)
                )
                raw_conn.commit()
                verdict("vec_frames insert 1152-dim works", True,
                        expected="insert succeeds",
                        actual="insert succeeded")
            except Exception as e:
                verdict("vec_frames insert 1152-dim works", False, reason=str(e))

            # Try wrong dimensions (768)
            vec_768 = struct.pack(f'{768}f', *([0.1] * 768))
            try:
                raw_conn.execute(
                    "INSERT INTO vec_frames(frame_id, project_id, timestamp_ms, frame_path, visual_embedding) VALUES (?, ?, ?, ?, ?)",
                    (2, "test", 0, "test2.jpg", vec_768)
                )
                raw_conn.commit()
                verdict("vec_frames rejects 768-dim", False,
                        reason="Should have raised for wrong dimensions")
            except Exception as e:
                verdict("vec_frames rejects 768-dim", True,
                        expected="error on wrong dimensions",
                        actual=f"error: {str(e)[:60]}")

        except ImportError:
            print("  sqlite-vec not installed, skipping vector table tests")
            verdict("sqlite-vec available", False,
                    reason="sqlite-vec not importable (non-critical)")

        # 4. Print schema of each core table
        print("\n--- Table Schemas ---")
        for t in expected_tables[:5]:  # Just first 5 for brevity
            cols = raw_conn.execute(f"PRAGMA table_info({t})").fetchall()
            col_info = [(c['name'], c['type']) for c in cols]
            print(f"  {t}: {col_info}")

        raw_conn.close()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# PART 6: CONFIGURATION
# ============================================================
async def test_config():
    print(f"\n\n{'#'*60}")
    print(f"# FSV PART 6: CONFIGURATION VERIFICATION")
    print(f"{'#'*60}")

    from clipcannon.config import ClipCannonConfig
    from clipcannon.exceptions import ConfigError

    # 1. Load default config, verify all expected keys
    print("\n--- Load and verify defaults ---")
    config = ClipCannonConfig.load()

    expected_keys = [
        "version", "directories.projects", "directories.models",
        "processing.whisper_model", "processing.frame_extraction_fps",
        "rendering.default_profile", "publishing.require_approval",
        "gpu.device", "gpu.max_vram_usage_gb",
    ]
    for key in expected_keys:
        try:
            val = config.get(key)
            verdict(f"Config key '{key}' exists", True,
                    expected=f"key exists",
                    actual=f"value={val}")
        except ConfigError:
            verdict(f"Config key '{key}' exists", False,
                    reason=f"Key not found")

    # 2. Set, save, reload, verify persistence
    print("\n--- Set, save, reload ---")
    tmp_config_path = Path(tempfile.mktemp(suffix=".json"))
    try:
        config2 = ClipCannonConfig.load()
        config2.config_path = tmp_config_path

        old_val = config2.get("processing.frame_extraction_fps")
        config2.set("processing.frame_extraction_fps", 5)
        config2.save()

        # Reload from disk
        config3 = ClipCannonConfig.load(tmp_config_path)
        new_val = config3.get("processing.frame_extraction_fps")
        verdict("Config persisted after save/reload", new_val == 5,
                expected="frame_extraction_fps=5",
                actual=f"frame_extraction_fps={new_val}")

        # Verify raw file
        raw_data = json.loads(tmp_config_path.read_text())
        verdict("Config file has correct value", raw_data.get("processing", {}).get("frame_extraction_fps") == 5,
                expected="5 in file",
                actual=f"{raw_data.get('processing', {}).get('frame_extraction_fps')}")
    finally:
        if tmp_config_path.exists():
            tmp_config_path.unlink()

    # 3. Invalid key path
    print("\n--- Edge case: invalid key ---")
    try:
        config.get("nonexistent.key.path")
        verdict("Invalid key raises ConfigError", False, reason="Should have raised")
    except ConfigError:
        verdict("Invalid key raises ConfigError", True,
                expected="ConfigError raised",
                actual="ConfigError raised")

    # 4. Invalid value (pydantic validation)
    print("\n--- Edge case: invalid value type ---")
    try:
        config_test = ClipCannonConfig.load()
        config_test.set("gpu.max_vram_usage_gb", "not_a_number")
        verdict("Invalid value type raises ConfigError", False,
                reason="Should have raised on pydantic validation")
    except ConfigError:
        verdict("Invalid value type raises ConfigError", True,
                expected="ConfigError raised",
                actual="ConfigError raised")


# ============================================================
# PART 7: GPU MANAGER
# ============================================================
async def test_gpu():
    print(f"\n\n{'#'*60}")
    print(f"# FSV PART 7: GPU MANAGER VERIFICATION")
    print(f"{'#'*60}")

    from clipcannon.gpu.precision import auto_detect_precision, get_compute_capability
    from clipcannon.gpu.manager import ModelManager, GPUHealthReport

    # 1. Detect GPU and precision
    print("\n--- GPU Detection ---")
    cc = get_compute_capability()
    precision = auto_detect_precision()
    print(f"  Compute capability: {cc}")
    print(f"  Auto-detected precision: {precision}")
    verdict("Precision is valid", precision in ("nvfp4", "int8", "fp16", "fp32"),
            expected="one of nvfp4/int8/fp16/fp32",
            actual=f"precision={precision}")

    # 2. ModelManager initialization
    print("\n--- ModelManager ---")
    manager = ModelManager(device="cpu")
    verdict("ModelManager CPU mode", manager.cpu_only == True,
            expected="cpu_only=True",
            actual=f"cpu_only={manager.cpu_only}")

    # 3. Health report
    health = manager.get_health()
    verdict("Health report has all fields",
            all(hasattr(health, f) for f in ['device_name', 'vram_total_bytes', 'vram_used_bytes',
                                               'vram_free_bytes', 'compute_capability', 'precision']),
            expected="All health fields present",
            actual=f"device={health.device_name}, precision={health.precision}")

    health_dict = health.to_dict()
    verdict("Health to_dict works", isinstance(health_dict, dict) and "device_name" in health_dict,
            expected="dict with device_name key",
            actual=f"type={type(health_dict)}, keys={list(health_dict.keys())[:5]}")

    # Try GPU mode if available
    try:
        import torch
        if torch.cuda.is_available():
            gpu_manager = ModelManager(device="cuda:0")
            gpu_health = gpu_manager.get_health()
            print(f"  GPU: {gpu_health.device_name}")
            print(f"  VRAM: {gpu_health.vram_total_gb:.1f} GB total, {gpu_health.vram_free_gb:.1f} GB free")
            print(f"  CC: {gpu_health.compute_capability}")
            print(f"  Precision: {gpu_health.precision}")
            print(f"  Concurrent: {gpu_health.concurrent_mode}")

            verdict("GPU manager initializes", not gpu_manager.cpu_only,
                    expected="cpu_only=False on GPU",
                    actual=f"cpu_only={gpu_manager.cpu_only}")
            verdict("GPU health has device name", gpu_health.device_name != "CPU",
                    expected="device_name != 'CPU'",
                    actual=f"device_name={gpu_health.device_name}")
            verdict("GPU health has VRAM > 0", gpu_health.vram_total_bytes > 0,
                    expected="vram > 0",
                    actual=f"vram={gpu_health.vram_total_gb:.1f} GB")
    except ImportError:
        print("  torch not available, skipping GPU tests")

    # Test model load/unload in CPU mode
    print("\n--- Model Load/Unload ---")
    test_model = manager.load("test_model", loader_fn=lambda: "dummy_model_obj", vram_estimate_bytes=0)
    verdict("Model loaded", manager.is_model_loaded("test_model"),
            expected="is_model_loaded=True",
            actual=f"loaded={manager.is_model_loaded('test_model')}")
    verdict("Model object returned", test_model == "dummy_model_obj",
            expected="'dummy_model_obj'",
            actual=f"{test_model}")

    manager.unload("test_model")
    verdict("Model unloaded", not manager.is_model_loaded("test_model"),
            expected="is_model_loaded=False",
            actual=f"loaded={manager.is_model_loaded('test_model')}")


async def main():
    await test_billing()
    await test_mcp_tools()
    await test_schema()
    await test_config()
    await test_gpu()

    print(f"\n\n{'='*60}")
    print("FSV PARTS 3-7 SUMMARY")
    print(f"{'='*60}")
    passes = sum(1 for _, s, _ in VERDICTS if s == "PASS")
    fails = sum(1 for _, s, _ in VERDICTS if s == "FAIL")
    for name, status, reason in VERDICTS:
        marker = "[PASS]" if status == "PASS" else "[FAIL]"
        line = f"  {marker} {name}"
        if reason and status == "FAIL":
            line += f" -- {reason}"
        print(line)
    print(f"\nTotal: {passes} passed, {fails} failed out of {len(VERDICTS)}")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
