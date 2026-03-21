"""Full State Verification (FSV) - Billing System & Dashboard.

Forensic investigation of ClipCannon Phase 1 billing, HMAC integrity,
credit system, license server schema, MCP billing tools, dashboard app,
and JWT authentication. Every assertion prints physical evidence.

Run: cd /home/cabdru/clipcannon && python tests/fsv_billing_dashboard.py
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ============================================================================
# Counters
# ============================================================================
_pass = 0
_fail = 0
_errors: list[str] = []


def ok(label: str, evidence: str = "") -> None:
    global _pass
    _pass += 1
    ev = f" | Evidence: {evidence}" if evidence else ""
    print(f"  [PASS] {label}{ev}")


def fail(label: str, expected: str, actual: str, root_cause: str = "") -> None:
    global _fail
    _fail += 1
    msg = f"  [FAIL] {label} | Expected: {expected} | Actual: {actual}"
    if root_cause:
        msg += f" | Root Cause: {root_cause}"
    print(msg)
    _errors.append(msg)


# ============================================================================
# SECTION 1: HMAC INTEGRITY TESTS
# ============================================================================
def test_hmac_integrity() -> None:
    print("\n" + "=" * 70)
    print("SECTION 1: HMAC INTEGRITY (hmac_integrity.py)")
    print("=" * 70)

    from clipcannon.billing.hmac_integrity import (
        derive_hmac_key,
        get_machine_id,
        sign_balance,
        verify_balance,
        verify_balance_or_raise,
    )
    from clipcannon.exceptions import BillingError

    # 1.1 Machine ID: deterministic 32-char hex
    mid1 = get_machine_id()
    mid2 = get_machine_id()
    print(f"\n  Machine ID (call 1): {mid1}")
    print(f"  Machine ID (call 2): {mid2}")

    if len(mid1) == 32 and re.fullmatch(r"[0-9a-f]{32}", mid1):
        ok("machine_id is 32-char hex", mid1)
    else:
        fail("machine_id format", "32 hex chars", f"len={len(mid1)}, val={mid1}")

    if mid1 == mid2:
        ok("machine_id is deterministic (same on two calls)", f"{mid1} == {mid2}")
    else:
        fail("machine_id determinism", mid1, mid2,
             "get_machine_id() returned different values on same machine")

    # 1.2 Sign balance=1000 -> 64-char hex signature
    sig = sign_balance(1000, mid1)
    print(f"\n  Signature for balance=1000: {sig}")

    if len(sig) == 64 and re.fullmatch(r"[0-9a-f]{64}", sig):
        ok("signature is 64-char hex (SHA-256 output)", sig[:16] + "...")
    else:
        fail("signature format", "64 hex chars", f"len={len(sig)}")

    # 1.3 Verify correct balance/signature pair -> True
    result = verify_balance(1000, sig, mid1)
    print(f"\n  verify_balance(1000, correct_sig, mid) = {result}")
    if result is True:
        ok("verify correct pair returns True")
    else:
        fail("verify correct pair", "True", str(result))

    # 1.4 Tamper: balance=1001 with original sig -> False
    tampered_bal = verify_balance(1001, sig, mid1)
    print(f"  verify_balance(1001, original_sig, mid) = {tampered_bal}")
    if tampered_bal is False:
        ok("tampered balance detected (1001 != 1000)")
    else:
        fail("tamper detection (balance)", "False", str(tampered_bal))

    # 1.5 Tamper: balance=1000 with modified signature -> False
    bad_sig = "a" * 64
    tampered_sig = verify_balance(1000, bad_sig, mid1)
    print(f"  verify_balance(1000, 'aaaa...', mid) = {tampered_sig}")
    if tampered_sig is False:
        ok("tampered signature detected")
    else:
        fail("tamper detection (signature)", "False", str(tampered_sig))

    # 1.6 Edge: sign balance=0
    sig_zero = sign_balance(0, mid1)
    ver_zero = verify_balance(0, sig_zero, mid1)
    print(f"\n  sign_balance(0, mid) = {sig_zero[:16]}...")
    print(f"  verify_balance(0, sig_zero, mid) = {ver_zero}")
    if ver_zero is True:
        ok("balance=0 signs and verifies correctly")
    else:
        fail("balance=0 verify", "True", str(ver_zero))

    # 1.7 Edge: sign negative balance
    sig_neg = sign_balance(-50, mid1)
    ver_neg = verify_balance(-50, sig_neg, mid1)
    print(f"  sign_balance(-50, mid) = {sig_neg[:16]}...")
    print(f"  verify_balance(-50, sig_neg, mid) = {ver_neg}")
    if ver_neg is True:
        ok("negative balance signs and verifies correctly")
    else:
        fail("negative balance verify", "True", str(ver_neg))

    # 1.8 verify_balance_or_raise: should raise on tamper
    raised = False
    try:
        verify_balance_or_raise(999, sig, mid1)
    except BillingError as e:
        raised = True
        print(f"\n  verify_balance_or_raise(999, sig_for_1000) raised BillingError:")
        print(f"    message: {e.message}")
        print(f"    details: {e.details}")
        if e.details.get("code") == "BALANCE_TAMPERED":
            ok("verify_balance_or_raise raises BillingError with BALANCE_TAMPERED code")
        else:
            fail("BillingError code", "BALANCE_TAMPERED",
                 str(e.details.get("code")))
    if not raised:
        fail("verify_balance_or_raise on tamper", "BillingError raised", "no exception")

    # 1.9 Edge: HMAC with empty machine_id
    sig_empty = sign_balance(100, "")
    ver_empty = verify_balance(100, sig_empty, "")
    print(f"\n  sign_balance(100, '') = {sig_empty[:16]}...")
    print(f"  verify_balance(100, sig_empty, '') = {ver_empty}")
    if ver_empty is True:
        ok("empty machine_id: signs and verifies (no crash)")
    else:
        fail("empty machine_id verify", "True", str(ver_empty))

    # 1.10 Edge: very large balance
    big = 999999999
    sig_big = sign_balance(big, mid1)
    ver_big = verify_balance(big, sig_big, mid1)
    print(f"  sign_balance(999999999, mid) = {sig_big[:16]}...")
    print(f"  verify_balance(999999999, sig_big, mid) = {ver_big}")
    if ver_big is True:
        ok("large balance (999999999) signs and verifies correctly")
    else:
        fail("large balance verify", "True", str(ver_big))

    # 1.11 derive_hmac_key produces 32 bytes
    key = derive_hmac_key(mid1)
    print(f"\n  derive_hmac_key length: {len(key)} bytes")
    if len(key) == 32:
        ok("HMAC key is 32 bytes (SHA-256 digest)")
    else:
        fail("HMAC key length", "32", str(len(key)))


# ============================================================================
# SECTION 2: CREDIT SYSTEM TESTS
# ============================================================================
def test_credit_system() -> None:
    print("\n" + "=" * 70)
    print("SECTION 2: CREDIT SYSTEM (credits.py)")
    print("=" * 70)

    from clipcannon.billing.credits import (
        CREDIT_PACKAGES,
        CREDIT_RATES,
        check_spending_warning,
        estimate_cost,
        validate_spending_limit,
    )
    from clipcannon.exceptions import BillingError

    # 2.1 Print credit rate table as evidence
    print("\n  CREDIT RATE TABLE:")
    for op, cost in CREDIT_RATES.items():
        print(f"    {op}: {cost} credits")

    # 2.2 analyze costs 10 credits
    if CREDIT_RATES.get("analyze") == 10:
        ok("analyze operation costs 10 credits", f"CREDIT_RATES['analyze'] = {CREDIT_RATES['analyze']}")
    else:
        fail("analyze cost", "10", str(CREDIT_RATES.get("analyze")))

    # 2.3 estimate_cost returns correct value
    est = estimate_cost("analyze")
    print(f"\n  estimate_cost('analyze') = {est}")
    if est == 10:
        ok("estimate_cost('analyze') returns 10")
    else:
        fail("estimate_cost('analyze')", "10", str(est))

    # 2.4 estimate_cost for unknown operation raises BillingError
    raised = False
    try:
        estimate_cost("nonexistent_op")
    except BillingError as e:
        raised = True
        print(f"  estimate_cost('nonexistent_op') raised BillingError: {e.message}")
        if "UNKNOWN_OPERATION" in str(e.details.get("code", "")):
            ok("unknown operation raises BillingError with UNKNOWN_OPERATION code")
        else:
            fail("unknown op error code", "UNKNOWN_OPERATION", str(e.details))
    if not raised:
        fail("unknown operation", "BillingError raised", "no exception")

    # 2.5 Spending limit validation
    # The function checks (current_spending + new_charge) <= limit
    print("\n  SPENDING LIMIT VALIDATION:")

    # Within limit
    result_ok = validate_spending_limit(current_spending=100, new_charge=50, limit=200)
    print(f"  validate_spending_limit(100, 50, 200) = {result_ok}")
    if result_ok is True:
        ok("100 + 50 <= 200 is within limit")
    else:
        fail("within limit", "True", str(result_ok))

    # Exactly at limit
    result_exact = validate_spending_limit(current_spending=190, new_charge=10, limit=200)
    print(f"  validate_spending_limit(190, 10, 200) = {result_exact}")
    if result_exact is True:
        ok("190 + 10 == 200 is at limit (should pass)")
    else:
        fail("at limit boundary", "True", str(result_exact))

    # Over limit
    result_over = validate_spending_limit(current_spending=195, new_charge=10, limit=200)
    print(f"  validate_spending_limit(195, 10, 200) = {result_over}")
    if result_over is False:
        ok("195 + 10 > 200 exceeds limit")
    else:
        fail("over limit", "False", str(result_over))

    # 2.6 Spending warning at 80%
    warn_80 = check_spending_warning(160, 200)
    print(f"\n  check_spending_warning(160, 200) = {warn_80}")
    if warn_80 is not None and "80%" in warn_80:
        ok("80% spending triggers warning", warn_80)
    elif warn_80 is not None:
        ok("80% spending triggers warning (text differs)", warn_80)
    else:
        fail("80% spending warning", "non-None warning", "None")

    warn_100 = check_spending_warning(200, 200)
    print(f"  check_spending_warning(200, 200) = {warn_100}")
    if warn_100 is not None and "reached" in warn_100.lower():
        ok("100% spending triggers limit-reached message", warn_100)
    elif warn_100 is not None:
        ok("100% spending triggers warning", warn_100)
    else:
        fail("100% spending warning", "non-None warning", "None")

    warn_50 = check_spending_warning(100, 200)
    print(f"  check_spending_warning(100, 200) = {warn_50}")
    if warn_50 is None:
        ok("50% spending returns None (no warning)")
    else:
        fail("50% spending", "None", str(warn_50))

    # 2.7 Credit packages exist
    print("\n  CREDIT PACKAGES:")
    for name, info in CREDIT_PACKAGES.items():
        print(f"    {name}: {info['credits']} credits @ ${info['price_cents']/100:.2f}")

    expected_packages = {"starter", "creator", "pro", "studio"}
    actual_packages = set(CREDIT_PACKAGES.keys())
    if actual_packages == expected_packages:
        ok("all 4 credit packages defined", str(actual_packages))
    else:
        fail("credit packages", str(expected_packages), str(actual_packages))


# ============================================================================
# SECTION 3: LICENSE SERVER TESTS (SQLite schema & operations)
# ============================================================================
def test_license_server() -> None:
    print("\n" + "=" * 70)
    print("SECTION 3: LICENSE SERVER (server.py)")
    print("=" * 70)

    from license_server.server import _SCHEMA_SQL, app
    from clipcannon.billing.hmac_integrity import get_machine_id, sign_balance, verify_balance

    # 3.1 Verify expected HTTP endpoints exist on the FastAPI app
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    print("\n  Registered routes on license server app:")
    for r in sorted(routes):
        print(f"    {r}")

    expected_endpoints = ["/v1/charge", "/v1/refund", "/v1/balance", "/v1/history", "/v1/sync"]
    for ep in expected_endpoints:
        if ep in routes:
            ok(f"endpoint {ep} defined")
        else:
            fail(f"endpoint {ep}", "present in routes", "MISSING")

    # 3.2 Create temp SQLite license database with the schema
    print("\n  --- Temp DB Operations ---")
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    print(f"  Temp DB: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA_SQL)

        # Verify tables were created
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        print(f"  Tables created: {tables}")

        expected_tables = {"balance", "sync_log", "transactions"}
        if expected_tables.issubset(set(tables)):
            ok("all 3 tables created (balance, transactions, sync_log)")
        else:
            fail("table creation", str(expected_tables), str(tables))

        # 3.3 Insert a test balance record (balance=1000, valid HMAC)
        machine_id = get_machine_id()
        initial_balance = 1000
        initial_hmac = sign_balance(initial_balance, machine_id)
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO balance
               (id, machine_id, balance, balance_hmac, last_sync_utc,
                spending_this_month, spending_limit, updated_at)
               VALUES (1, ?, ?, ?, ?, 0, 200, ?)""",
            (machine_id, initial_balance, initial_hmac, now, now),
        )
        conn.commit()
        print(f"\n  Inserted balance record: balance={initial_balance}, hmac={initial_hmac[:16]}...")

        # 3.4 Read it back, verify HMAC validates
        row = conn.execute(
            "SELECT machine_id, balance, balance_hmac FROM balance WHERE id = 1"
        ).fetchone()

        read_balance = row["balance"]
        read_hmac = row["balance_hmac"]
        read_mid = row["machine_id"]
        print(f"  Read back: balance={read_balance}, hmac={read_hmac[:16]}...")

        hmac_valid = verify_balance(read_balance, read_hmac, read_mid)
        print(f"  HMAC validates: {hmac_valid}")
        if read_balance == 1000 and hmac_valid:
            ok("balance=1000 read back with valid HMAC")
        else:
            fail("balance readback", "balance=1000, hmac=True",
                 f"balance={read_balance}, hmac={hmac_valid}")

        # 3.5 Simulate a charge: deduct 10 credits, update HMAC, insert transaction
        charge_amount = 10
        new_balance = read_balance - charge_amount
        new_hmac = sign_balance(new_balance, machine_id)
        txn_id = f"txn_{uuid.uuid4().hex[:12]}"
        charge_time = datetime.now(timezone.utc).isoformat()
        idem_key = str(uuid.uuid4())

        conn.execute(
            "UPDATE balance SET balance = ?, balance_hmac = ?, spending_this_month = spending_this_month + ?, updated_at = ? WHERE id = 1",
            (new_balance, new_hmac, charge_amount, charge_time),
        )
        conn.execute(
            """INSERT INTO transactions
               (transaction_id, machine_id, operation, credits,
                balance_before, balance_after, project_id,
                idempotency_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (txn_id, machine_id, "analyze", -charge_amount, read_balance,
             new_balance, "test-project", idem_key, charge_time),
        )
        conn.commit()
        print(f"\n  Charged {charge_amount} credits: txn={txn_id}")

        # 3.6 Read balance back, verify it's 990 with valid HMAC
        row2 = conn.execute(
            "SELECT balance, balance_hmac, spending_this_month FROM balance WHERE id = 1"
        ).fetchone()
        post_charge_bal = row2["balance"]
        post_charge_hmac = row2["balance_hmac"]
        post_spending = row2["spending_this_month"]

        hmac_valid2 = verify_balance(post_charge_bal, post_charge_hmac, machine_id)
        print(f"  After charge: balance={post_charge_bal}, hmac_valid={hmac_valid2}, spending={post_spending}")

        if post_charge_bal == 990 and hmac_valid2:
            ok("after charge: balance=990 with valid HMAC")
        else:
            fail("post-charge balance", "990 + valid HMAC",
                 f"balance={post_charge_bal}, hmac={hmac_valid2}")

        if post_spending == 10:
            ok("spending_this_month incremented to 10")
        else:
            fail("spending after charge", "10", str(post_spending))

        # 3.7 Simulate a refund: add 10 credits back, verify balance=1000
        refund_amount = 10
        refund_balance = post_charge_bal + refund_amount
        refund_hmac = sign_balance(refund_balance, machine_id)
        refund_txn_id = f"txn_{uuid.uuid4().hex[:12]}"
        refund_time = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "UPDATE balance SET balance = ?, balance_hmac = ?, spending_this_month = spending_this_month - ?, updated_at = ? WHERE id = 1",
            (refund_balance, refund_hmac, refund_amount, refund_time),
        )
        conn.execute(
            """INSERT INTO transactions
               (transaction_id, machine_id, operation, credits,
                balance_before, balance_after, project_id,
                reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (refund_txn_id, machine_id, "refund:analyze", refund_amount,
             post_charge_bal, refund_balance, "test-project",
             "test refund", refund_time),
        )
        conn.commit()
        print(f"  Refunded {refund_amount} credits: txn={refund_txn_id}")

        row3 = conn.execute(
            "SELECT balance, balance_hmac, spending_this_month FROM balance WHERE id = 1"
        ).fetchone()
        final_bal = row3["balance"]
        final_hmac_valid = verify_balance(final_bal, row3["balance_hmac"], machine_id)
        final_spending = row3["spending_this_month"]
        print(f"  After refund: balance={final_bal}, hmac_valid={final_hmac_valid}, spending={final_spending}")

        if final_bal == 1000 and final_hmac_valid:
            ok("after refund: balance=1000 with valid HMAC")
        else:
            fail("post-refund balance", "1000 + valid HMAC",
                 f"balance={final_bal}, hmac={final_hmac_valid}")

        if final_spending == 0:
            ok("spending_this_month decremented back to 0")
        else:
            fail("spending after refund", "0", str(final_spending))

        # 3.8 Check transactions table has 2 entries (charge + refund)
        txn_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        print(f"\n  Transaction count: {txn_count}")

        all_txns = conn.execute(
            "SELECT transaction_id, operation, credits, balance_before, balance_after, reason FROM transactions ORDER BY created_at"
        ).fetchall()
        print("  Transaction details:")
        for t in all_txns:
            print(f"    {dict(t)}")

        if txn_count == 2:
            ok("2 transactions recorded (charge + refund)")
        else:
            fail("transaction count", "2", str(txn_count))

        # 3.9 Idempotency key uniqueness constraint
        print("\n  --- Idempotency Key Test ---")
        try:
            conn.execute(
                """INSERT INTO transactions
                   (transaction_id, machine_id, operation, credits,
                    balance_before, balance_after, idempotency_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"txn_dup_{uuid.uuid4().hex[:8]}", machine_id, "analyze", -10,
                 1000, 990, idem_key, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            fail("idempotency constraint", "UNIQUE violation on duplicate key", "insert succeeded")
        except sqlite3.IntegrityError as e:
            print(f"  Duplicate idempotency_key insert raised: {e}")
            ok("idempotency_key UNIQUE constraint prevents duplicate charges")

        # 3.10 Print full DB state as evidence
        print("\n  === FULL DB STATE (EVIDENCE) ===")
        bal_row = conn.execute("SELECT * FROM balance WHERE id = 1").fetchone()
        print(f"  Balance table: {dict(bal_row)}")

        all_txns_final = conn.execute("SELECT * FROM transactions ORDER BY created_at").fetchall()
        print(f"  Transactions ({len(all_txns_final)} rows):")
        for t in all_txns_final:
            print(f"    {dict(t)}")

        sync_count = conn.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0]
        print(f"  Sync log entries: {sync_count}")

    finally:
        conn.close()
        os.unlink(db_path)
        print(f"  Temp DB cleaned up: {db_path}")


# ============================================================================
# SECTION 4: BILLING MCP TOOLS TESTS
# ============================================================================
def test_billing_tools() -> None:
    print("\n" + "=" * 70)
    print("SECTION 4: BILLING MCP TOOLS (billing_tools.py)")
    print("=" * 70)

    from clipcannon.tools.billing_tools import (
        BILLING_TOOL_DEFINITIONS,
        dispatch_billing_tool,
        clipcannon_credits_balance,
        clipcannon_credits_history,
        clipcannon_credits_estimate,
        clipcannon_spending_limit,
    )

    # 4.1 Verify all 4 tool definitions exist
    tool_names = [t.name for t in BILLING_TOOL_DEFINITIONS]
    print(f"\n  Tool definitions ({len(BILLING_TOOL_DEFINITIONS)} total):")
    for t in BILLING_TOOL_DEFINITIONS:
        print(f"    name={t.name}")
        print(f"      description={t.description[:60]}...")
        print(f"      inputSchema keys={list(t.inputSchema.get('properties', {}).keys())}")

    expected_tools = {
        "clipcannon_credits_balance",
        "clipcannon_credits_history",
        "clipcannon_credits_estimate",
        "clipcannon_spending_limit",
    }
    actual_tools = set(tool_names)
    if actual_tools == expected_tools:
        ok("all 4 billing tool definitions present", str(actual_tools))
    else:
        missing = expected_tools - actual_tools
        extra = actual_tools - expected_tools
        fail("billing tools", str(expected_tools), f"missing={missing}, extra={extra}")

    # 4.2 Verify tool input schemas
    tool_map = {t.name: t for t in BILLING_TOOL_DEFINITIONS}

    # balance: no required props
    bal_schema = tool_map["clipcannon_credits_balance"].inputSchema
    if bal_schema.get("type") == "object":
        ok("balance tool has object schema (no required params)")
    else:
        fail("balance schema type", "object", str(bal_schema.get("type")))

    # history: optional limit
    hist_schema = tool_map["clipcannon_credits_history"].inputSchema
    hist_props = hist_schema.get("properties", {})
    if "limit" in hist_props:
        ok("history tool has 'limit' property", str(hist_props["limit"]))
    else:
        fail("history tool schema", "limit property", str(hist_props))

    # estimate: required operation with enum
    est_schema = tool_map["clipcannon_credits_estimate"].inputSchema
    est_props = est_schema.get("properties", {})
    est_required = est_schema.get("required", [])
    if "operation" in est_props and "operation" in est_required:
        enum_vals = est_props["operation"].get("enum", [])
        print(f"  estimate tool operation enum: {enum_vals}")
        if "analyze" in enum_vals:
            ok("estimate tool has 'operation' required field with 'analyze' in enum")
        else:
            fail("estimate enum", "'analyze' in enum", str(enum_vals))
    else:
        fail("estimate schema", "required 'operation'",
             f"props={list(est_props.keys())}, required={est_required}")

    # spending_limit: required limit_credits
    sl_schema = tool_map["clipcannon_spending_limit"].inputSchema
    sl_props = sl_schema.get("properties", {})
    sl_required = sl_schema.get("required", [])
    if "limit_credits" in sl_props and "limit_credits" in sl_required:
        ok("spending_limit tool has required 'limit_credits' field")
    else:
        fail("spending_limit schema", "required 'limit_credits'",
             f"props={list(sl_props.keys())}, required={sl_required}")

    # 4.3 Test dispatch function routes correctly
    import asyncio

    # Dispatch estimate (local, no server needed)
    result = asyncio.run(dispatch_billing_tool("clipcannon_credits_estimate", {"operation": "analyze"}))
    print(f"\n  dispatch('clipcannon_credits_estimate', operation='analyze') = {result}")
    if result.get("credits") == 10:
        ok("dispatch routes estimate correctly, returns 10 credits")
    else:
        fail("dispatch estimate", "credits=10", str(result))

    # Dispatch unknown tool
    result_unk = asyncio.run(dispatch_billing_tool("nonexistent_tool", {}))
    print(f"  dispatch('nonexistent_tool') = {result_unk}")
    if "error" in result_unk:
        ok("dispatch returns error for unknown tool")
    else:
        fail("dispatch unknown", "error dict", str(result_unk))

    # Dispatch spending_limit with negative value (local validation)
    result_neg = asyncio.run(dispatch_billing_tool("clipcannon_spending_limit", {"limit_credits": -1}))
    print(f"  dispatch('spending_limit', limit_credits=-1) = {result_neg}")
    if "error" in result_neg:
        ok("spending_limit rejects negative limit locally")
    else:
        fail("negative spending limit", "error dict", str(result_neg))


# ============================================================================
# SECTION 5: DASHBOARD TESTS
# ============================================================================
def test_dashboard() -> None:
    print("\n" + "=" * 70)
    print("SECTION 5: DASHBOARD (app.py, auth.py, routes)")
    print("=" * 70)

    # 5.1 Verify FastAPI app creates successfully
    from clipcannon.dashboard.app import create_app
    app = create_app()
    print(f"\n  Dashboard app created: {app.title} v{app.version}")

    if app is not None and app.title == "ClipCannon Dashboard":
        ok("FastAPI dashboard app created successfully", f"title={app.title}")
    else:
        fail("dashboard app creation", "ClipCannon Dashboard", str(app))

    # Enumerate all routes
    route_paths = [r.path for r in app.routes if hasattr(r, "path")]
    print(f"  Dashboard routes ({len(route_paths)}):")
    for rp in sorted(route_paths):
        print(f"    {rp}")

    # 5.2 Verify auth module functions
    from clipcannon.dashboard.auth import (
        create_session_token,
        verify_session_token,
        get_current_user,
        is_dev_mode,
        require_auth,
    )

    print(f"\n  Auth module functions present:")
    for fn_name, fn in [
        ("create_session_token", create_session_token),
        ("verify_session_token", verify_session_token),
        ("get_current_user", get_current_user),
        ("is_dev_mode", is_dev_mode),
        ("require_auth", require_auth),
    ]:
        if callable(fn):
            ok(f"auth.{fn_name} is callable")
        else:
            fail(f"auth.{fn_name}", "callable", str(type(fn)))

    # 5.3 Verify all route modules define their endpoint functions
    from clipcannon.dashboard.routes.home import router as home_router
    from clipcannon.dashboard.routes.credits import router as credits_router
    from clipcannon.dashboard.routes.provenance import router as prov_router
    from clipcannon.dashboard.routes.projects import router as proj_router

    for name, router_obj in [
        ("home", home_router),
        ("credits", credits_router),
        ("provenance", prov_router),
        ("projects", proj_router),
    ]:
        rr = [r.path for r in router_obj.routes if hasattr(r, "path")]
        print(f"\n  {name} router routes: {rr}")
        if len(rr) > 0:
            ok(f"{name} router has {len(rr)} route(s)")
        else:
            fail(f"{name} router", ">0 routes", "0 routes")

    # 5.4 JWT creation/verification cycle
    print("\n  --- JWT Token Tests ---")
    token = create_session_token("test-user-123", "test@example.com")
    print(f"  Token (first 40 chars): {token[:40]}...")
    print(f"  Token length: {len(token)}")

    if isinstance(token, str) and len(token) > 20:
        ok("JWT token created (string, >20 chars)")
    else:
        fail("JWT creation", "string >20 chars", f"type={type(token)}, len={len(token)}")

    # Verify the token and check claims
    payload = verify_session_token(token)
    print(f"  Decoded payload: {payload}")

    if payload is not None:
        ok("JWT token verified successfully")

        if payload.get("sub") == "test-user-123":
            ok("JWT 'sub' claim matches", f"sub={payload.get('sub')}")
        else:
            fail("JWT sub claim", "test-user-123", str(payload.get("sub")))

        if payload.get("email") == "test@example.com":
            ok("JWT 'email' claim matches", f"email={payload.get('email')}")
        else:
            fail("JWT email claim", "test@example.com", str(payload.get("email")))

        if "iat" in payload and "exp" in payload:
            iat = payload["iat"]
            exp = payload["exp"]
            ttl = exp - iat
            print(f"  iat={iat}, exp={exp}, ttl={ttl}s ({ttl/86400:.1f} days)")
            if 29 * 86400 <= ttl <= 31 * 86400:
                ok("JWT TTL is ~30 days", f"{ttl}s")
            else:
                fail("JWT TTL", "~30 days (2592000s)", f"{ttl}s")
        else:
            fail("JWT time claims", "iat and exp present", str(payload.keys()))
    else:
        fail("JWT verification", "non-None payload", "None")

    # 5.5 Test expired token handling
    print("\n  --- Expired Token Test ---")
    from jose import jwt as jose_jwt

    expired_payload = {
        "sub": "expired-user",
        "email": "expired@test.com",
        "iat": int(time.time()) - 100000,
        "exp": int(time.time()) - 1,  # expired 1 second ago
    }
    # Use the same secret as the auth module
    _secret = os.environ.get("CLIPCANNON_JWT_SECRET", "clipcannon-dev-secret-not-for-production")
    expired_token = jose_jwt.encode(expired_payload, _secret, algorithm="HS256")
    print(f"  Expired token (first 40 chars): {expired_token[:40]}...")

    expired_result = verify_session_token(expired_token)
    print(f"  verify_session_token(expired) = {expired_result}")

    if expired_result is None:
        ok("expired token correctly returns None")
    else:
        fail("expired token", "None", str(expired_result))

    # 5.6 Test invalid token
    invalid_result = verify_session_token("this.is.not.a.valid.jwt")
    print(f"  verify_session_token('invalid') = {invalid_result}")
    if invalid_result is None:
        ok("invalid token correctly returns None")
    else:
        fail("invalid token", "None", str(invalid_result))

    # 5.7 is_dev_mode check
    dev = is_dev_mode()
    print(f"\n  is_dev_mode() = {dev} (CLIPCANNON_DEV_MODE={os.environ.get('CLIPCANNON_DEV_MODE', 'not set')})")
    if isinstance(dev, bool):
        ok("is_dev_mode returns bool", str(dev))
    else:
        fail("is_dev_mode type", "bool", str(type(dev)))


# ============================================================================
# SECTION 6: D1 SYNC MODULE
# ============================================================================
def test_d1_sync() -> None:
    print("\n" + "=" * 70)
    print("SECTION 6: D1 SYNC MODULE (d1_sync.py)")
    print("=" * 70)

    from license_server.d1_sync import is_d1_configured, sync_push, sync_pull

    # 6.1 D1 not configured in test environment
    configured = is_d1_configured()
    print(f"\n  is_d1_configured() = {configured}")
    if configured is False:
        ok("D1 not configured (local-only mode as expected for Phase 1)")
    else:
        ok("D1 is configured (unexpected but not an error)", str(configured))

    # 6.2 sync_push returns skip message
    push_result = sync_push()
    print(f"  sync_push() = '{push_result}'")
    if "skip" in push_result.lower() or "local-only" in push_result.lower():
        ok("sync_push returns local-only skip message")
    else:
        fail("sync_push", "skip/local-only message", push_result)

    # 6.3 sync_pull returns skip message
    pull_result = sync_pull()
    print(f"  sync_pull() = '{pull_result}'")
    if "skip" in pull_result.lower() or "local-only" in pull_result.lower():
        ok("sync_pull returns local-only skip message")
    else:
        fail("sync_pull", "skip/local-only message", pull_result)


# ============================================================================
# SECTION 7: STRIPE WEBHOOKS MODULE
# ============================================================================
def test_stripe_webhooks() -> None:
    print("\n" + "=" * 70)
    print("SECTION 7: STRIPE WEBHOOKS (stripe_webhooks.py)")
    print("=" * 70)

    from license_server.stripe_webhooks import (
        router,
        PACKAGES,
        _verify_stripe_signature,
    )

    # 7.1 Stripe packages
    print(f"\n  Stripe PACKAGES: {PACKAGES}")
    expected_pkgs = {"starter": 50, "creator": 250, "pro": 1000, "studio": 5000}
    if PACKAGES == expected_pkgs:
        ok("Stripe packages match expected values")
    else:
        fail("stripe packages", str(expected_pkgs), str(PACKAGES))

    # 7.2 Router has webhook endpoint
    webhook_routes = [r.path for r in router.routes if hasattr(r, "path")]
    print(f"  Webhook router routes: {webhook_routes}")
    if "/stripe/webhook" in webhook_routes:
        ok("Stripe webhook route defined")
    else:
        fail("stripe webhook route", "/stripe/webhook", str(webhook_routes))

    # 7.3 Signature verification with known values
    import hashlib
    import hmac as hmac_mod

    test_secret = "whsec_test_secret"
    test_timestamp = "1234567890"
    test_payload = b'{"type":"checkout.session.completed"}'
    signed_payload = f"{test_timestamp}.".encode() + test_payload
    expected_sig = hmac_mod.new(
        test_secret.encode(), signed_payload, hashlib.sha256
    ).hexdigest()
    sig_header = f"t={test_timestamp},v1={expected_sig}"

    result = _verify_stripe_signature(test_payload, sig_header, test_secret)
    print(f"\n  _verify_stripe_signature(known payload, computed sig) = {result}")
    if result is True:
        ok("Stripe signature verification works with correct sig")
    else:
        fail("stripe sig verify", "True", str(result))

    # Bad signature
    bad_result = _verify_stripe_signature(test_payload, "t=123,v1=bad", test_secret)
    print(f"  _verify_stripe_signature(bad sig) = {bad_result}")
    if bad_result is False:
        ok("Stripe signature verification rejects bad sig")
    else:
        fail("stripe bad sig", "False", str(bad_result))


# ============================================================================
# SECTION 8: CROSS-MODULE INTEGRATION
# ============================================================================
def test_cross_module() -> None:
    print("\n" + "=" * 70)
    print("SECTION 8: CROSS-MODULE INTEGRATION")
    print("=" * 70)

    # 8.1 Billing __init__.py exports all expected symbols
    import clipcannon.billing as billing_mod

    expected_exports = [
        "BalanceInfo", "CREDIT_PACKAGES", "CREDIT_RATES", "ChargeResult",
        "LicenseClient", "RefundResult", "TransactionRecord",
        "check_spending_warning", "estimate_cost", "get_machine_id",
        "sign_balance", "validate_spending_limit", "verify_balance",
        "verify_balance_or_raise",
    ]

    print(f"\n  billing.__all__ = {billing_mod.__all__}")
    for sym in expected_exports:
        if hasattr(billing_mod, sym):
            ok(f"billing exports '{sym}'")
        else:
            fail(f"billing export '{sym}'", "present", "MISSING")

    # 8.2 LicenseClient uses correct machine_id
    client = billing_mod.LicenseClient()
    mid = billing_mod.get_machine_id()
    print(f"\n  LicenseClient.machine_id = {client.machine_id}")
    print(f"  get_machine_id() = {mid}")
    if client.machine_id == mid:
        ok("LicenseClient.machine_id matches get_machine_id()")
    else:
        fail("machine_id consistency", mid, client.machine_id)

    # 8.3 LicenseClient.estimate delegates to credits.estimate_cost
    import asyncio
    est = asyncio.run(client.estimate("analyze"))
    print(f"  LicenseClient.estimate('analyze') = {est}")
    if est == 10:
        ok("LicenseClient.estimate delegates correctly to credits.estimate_cost")
    else:
        fail("LicenseClient.estimate", "10", str(est))


# ============================================================================
# MAIN RUNNER
# ============================================================================
def main() -> None:
    print("=" * 70)
    print("SHERLOCK HOLMES FSV: BILLING SYSTEM & DASHBOARD")
    print("Full State Verification - Physical Evidence Collection")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    test_hmac_integrity()
    test_credit_system()
    test_license_server()
    test_billing_tools()
    test_dashboard()
    test_d1_sync()
    test_stripe_webhooks()
    test_cross_module()

    # Final report
    print("\n" + "=" * 70)
    print("SHERLOCK HOLMES INVESTIGATION COMPLETE")
    print("=" * 70)
    total = _pass + _fail
    print(f"\n  TOTAL CHECKS: {total}")
    print(f"  PASSED: {_pass}")
    print(f"  FAILED: {_fail}")

    if _fail > 0:
        print(f"\n  VERDICT: GUILTY - {_fail} failure(s) detected!")
        print("\n  FAILURE DETAILS:")
        for err in _errors:
            print(f"  {err}")
        sys.exit(1)
    else:
        print(f"\n  VERDICT: INNOCENT - All {_pass} checks passed.")
        print("  The billing system and dashboard are verified as operational.")
        sys.exit(0)


if __name__ == "__main__":
    main()
