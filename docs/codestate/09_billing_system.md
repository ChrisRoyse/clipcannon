# Billing System

## Architecture

Three-layer trust model:

```
MCP Tools / Dashboard
    |  HTTP localhost:3100
License Server (FastAPI)
    |  SQLite
license.db (HMAC-signed balances)
    |  (future)
Cloudflare D1 (remote source of truth)
```

---

## HMAC Integrity (`billing/hmac_integrity.py`)

**Machine ID**: `SHA256("{hostname}|{mac_addr}|{cpu_arch}")[:32]` -- deterministic per machine, non-transferable.

**HMAC key**: `SHA256("clipcannon-v1|{machine_id}")` -- versioned salt for future key rotation.

**Signing**: `HMAC-SHA256(key, "balance:{balance}")` hex digest.

**Verification**: Constant-time comparison via `hmac.compare_digest`. On mismatch: `CRITICAL` log, raises `BillingError(BALANCE_TAMPERED)`, HTTP 403. Fatal -- no recovery path.

---

## License Server API (`license_server/server.py`)

FastAPI on port 3100. Launch: `uvicorn license_server.server:app --port 3100`

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (`status`, `version`, `service`) |
| POST | `/v1/charge` | Charge credits (idempotent via `idempotency_key`) |
| POST | `/v1/refund` | Refund credits for a `transaction_id` |
| GET | `/v1/balance` | Current balance with HMAC verification |
| GET | `/v1/history` | Transaction history (newest first, `limit`/`offset` params) |
| POST | `/v1/sync` | Force D1 sync (currently local-only stub) |
| POST | `/v1/add_credits` | Dev/test: manually add credits |
| POST | `/v1/spending_limit` | Update monthly spending limit |

**Charge request**: `machine_id`, `operation`, `credits`, optional `project_id`, `idempotency_key`. Returns `balance_before`, `balance_after`, `transaction_id`. Errors: `INSUFFICIENT_CREDITS`, `SPENDING_LIMIT_EXCEEDED`, `BALANCE_TAMPERED`.

**Refund request**: `machine_id`, `transaction_id`, optional `reason`, `project_id`. Refund amount = abs(original charge). Decrements `spending_this_month`.

**Transaction ID format**: `txn_{uuid4.hex[:12]}`. Credits stored negative for charges, positive for refunds/purchases.

---

## SQLite Schema (`~/.clipcannon/license.db`)

WAL journal mode, foreign keys enabled.

### balance table (single row, `CHECK(id=1)`)

`id`, `machine_id`, `balance`, `balance_hmac`, `last_sync_utc`, `spending_this_month` (default 0), `spending_limit` (default 200), `updated_at`

### transactions table

`transaction_id` (PK), `machine_id`, `operation`, `credits`, `balance_before`, `balance_after`, `project_id`, `idempotency_key` (UNIQUE), `reason`, `synced_to_d1`, `created_at`. Indexes: `created_at DESC`, `project_id`.

### sync_log table

`id`, `direction` (push/pull), `d1_balance`, `local_balance`, `status`, `error_message`, `synced_at`

---

## Dev Mode Init

First startup seeds: 100 credits (`DEV_INITIAL_CREDITS`), 200 spending limit (`DEFAULT_SPENDING_LIMIT`), HMAC computed from initial balance.

## Credit Rates (`billing/credits.py`)

| Operation | Credits | Status |
|---|---|---|
| analyze | 10 | Active |
| render | 2 | Active |
| metadata | 1 | Defined |
| publish | 1 | Defined |

## Credit Packages

| Package | Credits | Price | Per-Credit |
|---|---|---|---|
| starter | 50 | $5 | $0.10 |
| creator | 250 | $20 | $0.08 |
| pro | 1,000 | $60 | $0.06 |
| studio | 5,000 | $200 | $0.04 |

## Spending Limits

Default limit: 200 credits/month. Limit 0 = unlimited. Warning at 80%, limit-reached at 100%.

## LicenseClient (`billing/license_client.py`)

Async HTTP client wrapping all license server calls. Base URL `http://localhost:3100`, 5s timeout, lazy `httpx.AsyncClient`. Methods: `charge()`, `refund()`, `get_balance()`, `get_history()`, `estimate()` (local lookup). All methods catch `ConnectError` and return failure results instead of raising.

## D1 Sync (`license_server/d1_sync.py`)

Currently local-only stubs. Env vars `CLIPCANNON_D1_API_URL` and `CLIPCANNON_D1_API_TOKEN` for future activation. Planned: push on charge/refund, pull on startup + every 5 min, D1 as source of truth with local transaction replay.

## Stripe Webhooks (`license_server/stripe_webhooks.py`)

Handles `checkout.session.completed`. Signature verification via `STRIPE_WEBHOOK_SECRET` env var (skipped in dev). Extracts `metadata.package` and `metadata.machine_id` from session, adds credits to balance, records `stripe_purchase` transaction. Package mapping mirrors `CREDIT_PACKAGES`.
