# 09 - Billing System

> Current-state documentation of ClipCannon's credit-based billing system, covering the three-layer trust model, HMAC integrity, license server HTTP API, local SQLite schema, credit rates and packages, spending limits, and Stripe webhook handling.

## Architecture Overview

The billing system has three layers:

1. **Cloudflare D1** (remote, cloud) -- intended as the source of truth for production. In Phase 1, this layer is a stub. No actual D1 connection is made.
2. **License Server** (local HTTP service, port 3100) -- FastAPI application that manages a local SQLite database (`~/.clipcannon/license.db`). All credit operations (charge, refund, balance, history) go through this server.
3. **HMAC Integrity** (cryptographic verification) -- every balance read and write is signed with an HMAC-SHA256 derived from the machine's hardware identity. Tampered balances are detected and rejected.

MCP billing tools and the dashboard both communicate with the license server via HTTP. The license server is the only process that reads/writes `license.db`.

```
MCP Tools / Dashboard
        |
        v  (HTTP on localhost:3100)
  License Server (FastAPI)
        |
        v  (SQLite)
  license.db (HMAC-signed balances)
        |
        v  (Phase 2+ only)
  Cloudflare D1 (remote source of truth)
```

---

## HMAC Integrity Layer

**Source:** `src/clipcannon/billing/hmac_integrity.py`

### Machine ID Derivation

The machine ID is a deterministic identifier derived from three hardware characteristics:

```
raw = "{platform.node()}|{uuid.getnode()}|{platform.machine()}"
machine_id = SHA256(raw)[:32]   # 32 hex characters
```

- `platform.node()` -- the hostname of the machine.
- `uuid.getnode()` -- the MAC address as a 48-bit integer.
- `platform.machine()` -- the CPU architecture string (e.g., `x86_64`).

The same physical machine always produces the same machine ID. This makes signed balances non-transferable between machines.

### HMAC Key Derivation

The HMAC signing key is derived from the machine ID using a versioned salt prefix:

```
hmac_key = SHA256("clipcannon-v1|{machine_id}")   # 32 bytes
```

The `clipcannon-v1` prefix allows key rotation in future versions without breaking existing installations.

### Balance Signing

To sign a balance:

```python
payload = f"balance:{balance}".encode()   # e.g., b"balance:100"
signature = HMAC-SHA256(hmac_key, payload).hexdigest()
```

The `sign_balance(balance, machine_id)` function returns the hex-encoded signature string.

### Balance Verification

To verify a balance:

1. Recompute the HMAC from the stored balance integer and the machine ID.
2. Compare the recomputed HMAC against the stored HMAC using `hmac.compare_digest` (constant-time comparison to prevent timing attacks).

### Tamper Detection

The `verify_balance_or_raise` function is called on every balance read. On mismatch:

1. Logs a `CRITICAL`-level message with the balance value, stored HMAC (truncated), expected HMAC (truncated), and machine ID (truncated).
2. Raises `BillingError` with code `BALANCE_TAMPERED`.
3. The license server converts this to an HTTP 403 response.

Tamper detection is fatal. There is no recovery path -- the balance file must be re-initialized or synced from D1.

---

## License Server HTTP API

**Source:** `src/license_server/server.py`

The license server is a FastAPI application running on port 3100. It initializes the SQLite database on startup via the `lifespan` context manager.

**Launch command:** `uvicorn license_server.server:app --port 3100`

### `GET /health`

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "service": "clipcannon-license-server"
}
```

---

### `POST /v1/charge`

Charges credits for an operation. Supports idempotency keys to prevent double charges.

**Request body (`ChargeRequest`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `machine_id` | `string` | Yes | Machine identifier |
| `operation` | `string` | Yes | Operation type (e.g., `analyze`) |
| `credits` | `integer` | Yes | Number of credits to charge |
| `project_id` | `string` | No | Project being charged for. Default: `""` |
| `idempotency_key` | `string` | No | UUID to prevent double charges. Auto-generated if omitted. |

**Success response:**
```json
{
  "success": true,
  "balance_before": 100,
  "balance_after": 90,
  "transaction_id": "txn_a1b2c3d4e5f6",
  "timestamp": "2026-03-21T..."
}
```

**Idempotent replay:** If the `idempotency_key` matches an existing transaction, the original result is returned with `"idempotent_replay": true`.

**Error cases:**
- `INSUFFICIENT_CREDITS` -- balance is less than the charge amount.
- `SPENDING_LIMIT_EXCEEDED` -- charge would push monthly spending over the limit.
- `BALANCE_TAMPERED` (HTTP 403) -- HMAC verification failed.

**Key behaviors:**
- Transaction ID format: `txn_{12 hex chars}` from `uuid.uuid4().hex[:12]`.
- Credits are stored as negative values in the `transactions` table for charges.
- The `spending_this_month` counter is incremented by the charge amount.
- HMAC is recomputed and stored after every balance change.

---

### `POST /v1/refund`

Refunds credits for a failed operation.

**Request body (`RefundRequest`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `machine_id` | `string` | Yes | Machine identifier |
| `transaction_id` | `string` | Yes | Original charge transaction ID |
| `reason` | `string` | No | Reason for the refund. Default: `""` |
| `project_id` | `string` | No | Project the refund is for. Default: `""` |

**Success response:**
```json
{
  "success": true,
  "balance_before": 90,
  "balance_after": 100,
  "transaction_id": "txn_...",
  "refunded_transaction": "txn_original",
  "credits_refunded": 10,
  "timestamp": "2026-03-21T..."
}
```

**Error cases:**
- HTTP 404 `TRANSACTION_NOT_FOUND` -- the original transaction ID does not exist.
- `BALANCE_TAMPERED` (HTTP 403) -- HMAC verification failed.

**Key behaviors:**
- Refund amount is the absolute value of the original transaction's `credits` field.
- The refund operation is recorded as `refund:{original_operation}`.
- `spending_this_month` is decremented by the refund amount (spending_delta is negative).

---

### `GET /v1/balance`

Returns the current credit balance with HMAC verification.

**Response:**
```json
{
  "balance": 100,
  "balance_hmac": "a1b2c3...",
  "last_sync_utc": "2026-03-21T...",
  "spending_this_month": 0,
  "spending_limit": 200
}
```

**Key behaviors:**
- Calls `_read_balance` which verifies the HMAC before returning data.
- Raises `BALANCE_TAMPERED` (HTTP 403) if verification fails.

---

### `GET /v1/history`

Returns transaction history, newest first.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | `integer` | `20` | Maximum number of records |
| `offset` | `integer` | `0` | Number of records to skip |

**Response:**
```json
{
  "transactions": [...],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

Each transaction includes: `transaction_id`, `operation`, `credits`, `balance_before`, `balance_after`, `project_id`, `reason`, `created_at`.

---

### `POST /v1/sync`

Forces a sync with Cloudflare D1.

**Response (Phase 1):**
```json
{
  "status": "ok",
  "message": "D1 sync skipped (local-only mode). Set CLIPCANNON_D1_API_URL and CLIPCANNON_D1_API_TOKEN to enable."
}
```

---

### `POST /v1/add_credits`

Manually adds credits. This endpoint is for development and testing only.

**Request body (`AddCreditsRequest`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `credits` | `integer` | Yes | Number of credits to add |
| `reason` | `string` | No | Reason for addition. Default: `"manual_add"` |

**Success response:**
```json
{
  "success": true,
  "balance_before": 100,
  "balance_after": 200,
  "credits_added": 100,
  "transaction_id": "txn_...",
  "timestamp": "2026-03-21T..."
}
```

**Key behaviors:**
- Does not increment `spending_this_month` (spending_delta is 0).
- Recorded as operation `credit_add`.

---

### `POST /v1/spending_limit`

Updates the monthly spending limit.

**Request body (`SpendingLimitRequest`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `limit` | `integer` | Yes | New monthly spending limit in credits |

**Success response:**
```json
{
  "success": true,
  "spending_limit": 500,
  "message": "Monthly spending limit set to 500 credits."
}
```

**Error:** HTTP 400 if limit is negative.

---

## Local SQLite Schema

**Database location:** `~/.clipcannon/license.db`

The database uses WAL journal mode and has foreign keys enabled.

### `balance` table

Single-row table (enforced by `CHECK (id = 1)`).

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER PRIMARY KEY` | Always 1 |
| `machine_id` | `TEXT NOT NULL` | 32-char hex machine identifier |
| `balance` | `INTEGER NOT NULL DEFAULT 0` | Current credit balance |
| `balance_hmac` | `TEXT NOT NULL` | HMAC-SHA256 signature of the balance |
| `last_sync_utc` | `TEXT` | ISO timestamp of last D1 sync |
| `spending_this_month` | `INTEGER DEFAULT 0` | Credits spent in current month |
| `spending_limit` | `INTEGER DEFAULT 200` | Monthly spending cap |
| `updated_at` | `TEXT NOT NULL` | ISO timestamp, defaults to `datetime('now')` |

### `transactions` table

| Column | Type | Description |
|--------|------|-------------|
| `transaction_id` | `TEXT PRIMARY KEY` | Format: `txn_{12 hex chars}` |
| `machine_id` | `TEXT NOT NULL` | Machine that initiated the transaction |
| `operation` | `TEXT NOT NULL` | Operation type (e.g., `analyze`, `refund:analyze`, `credit_add`, `stripe_purchase`) |
| `credits` | `INTEGER NOT NULL` | Negative for charges, positive for refunds/purchases |
| `balance_before` | `INTEGER NOT NULL` | Balance before the transaction |
| `balance_after` | `INTEGER NOT NULL` | Balance after the transaction |
| `project_id` | `TEXT` | Associated project (nullable) |
| `idempotency_key` | `TEXT UNIQUE` | UUID for charge deduplication |
| `reason` | `TEXT` | Human-readable reason |
| `synced_to_d1` | `BOOLEAN DEFAULT FALSE` | Whether this transaction has been synced to D1 |
| `created_at` | `TEXT NOT NULL` | ISO timestamp, defaults to `datetime('now')` |

**Indexes:**
- `idx_transactions_time` on `created_at DESC`
- `idx_transactions_project` on `project_id`

### `sync_log` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Auto-incrementing ID |
| `direction` | `TEXT NOT NULL` | `push` or `pull` |
| `d1_balance` | `INTEGER` | D1 balance at time of sync |
| `local_balance` | `INTEGER` | Local balance at time of sync |
| `status` | `TEXT` | `success`, `failed`, or `conflict` |
| `error_message` | `TEXT` | Error details if failed |
| `synced_at` | `TEXT NOT NULL` | ISO timestamp, defaults to `datetime('now')` |

---

## Dev Mode Initialization

On first startup, if no balance row exists, the server seeds the database with:
- **Balance:** 100 credits (`DEV_INITIAL_CREDITS`)
- **Spending limit:** 200 credits (`DEFAULT_SPENDING_LIMIT`)
- **Spending this month:** 0
- **HMAC:** Computed from the initial balance and machine ID

---

## Credit Rates

**Source:** `src/clipcannon/billing/credits.py`

| Operation | Credits | Status |
|-----------|---------|--------|
| `analyze` | 10 | Active (Phase 1) |
| `render` | 2 | Defined, not yet active |
| `metadata` | 1 | Defined, not yet active |
| `publish` | 1 | Defined, not yet active |

---

## Credit Packages

**Source:** `src/clipcannon/billing/credits.py`

| Package | Credits | Price (USD) | Per-Credit Cost |
|---------|---------|-------------|-----------------|
| `starter` | 50 | $5.00 | $0.10 |
| `creator` | 250 | $20.00 | $0.08 |
| `pro` | 1,000 | $60.00 | $0.06 |
| `studio` | 5,000 | $200.00 | $0.04 |

---

## Spending Limits and Warnings

**Source:** `src/clipcannon/billing/credits.py`

- The monthly spending limit defaults to 200 credits.
- Setting the limit to 0 means unlimited.
- The `validate_spending_limit` function returns `True` if `(current_spending + new_charge) <= limit`.
- The `check_spending_warning` function returns:
  - `None` if spending is below 80% of the limit (or limit is 0).
  - A warning string at 80-99% of the limit.
  - A limit-reached message at 100%+ of the limit.

---

## LicenseClient

**Source:** `src/clipcannon/billing/license_client.py`

An async HTTP client that wraps all license server API calls. Used by both MCP billing tools and the dashboard.

**Configuration:**
- Default base URL: `http://localhost:3100`
- HTTP timeout: 5 seconds
- Uses `httpx.AsyncClient` with lazy initialization

**Pydantic response models:**

| Model | Fields |
|-------|--------|
| `ChargeResult` | `success`, `balance_before`, `balance_after`, `transaction_id`, `timestamp`, `error`, `message` |
| `RefundResult` | `success`, `balance_before`, `balance_after`, `transaction_id`, `timestamp`, `error`, `message` |
| `BalanceInfo` | `balance`, `balance_hmac`, `last_sync_utc`, `spending_this_month`, `spending_limit` |
| `TransactionRecord` | `transaction_id`, `operation`, `credits`, `balance_before`, `balance_after`, `project_id`, `reason`, `created_at` |

**Methods:**

| Method | Server Endpoint | Description |
|--------|-----------------|-------------|
| `charge(operation, credits, project_id, idempotency_key)` | `POST /v1/charge` | Charges credits; auto-generates idempotency key if omitted |
| `refund(transaction_id, reason, project_id)` | `POST /v1/refund` | Refunds credits for a transaction |
| `get_balance()` | `GET /v1/balance` | Returns current balance info |
| `get_history(limit)` | `GET /v1/history` | Returns transaction history |
| `estimate(operation)` | (local lookup) | Returns credit cost from `CREDIT_RATES` without a server call |

**Error handling:** All methods catch `httpx.ConnectError` and return failure results (e.g., `ChargeResult(success=False, error="LICENSE_SERVER_UNREACHABLE")`) instead of raising. The `get_balance` method returns `BalanceInfo(balance=-1)` when unreachable. The `get_history` method returns an empty list when unreachable.

---

## Cloudflare D1 Sync

**Source:** `src/license_server/d1_sync.py`

Phase 1 operates in **local-only mode**. No D1 connection is made. The module provides three stub functions:

| Function | Behavior in Phase 1 |
|----------|---------------------|
| `sync_push()` | Logs "D1 sync skipped (local-only mode)" and returns. |
| `sync_pull()` | Logs "D1 sync skipped (local-only mode)" and returns. |
| `log_sync_event(direction, d1_balance, local_balance, status, error_message)` | Logs the event to the Python logger. |

**Configuration (for Phase 2+):**
- `CLIPCANNON_D1_API_URL` -- environment variable for the D1 API endpoint.
- `CLIPCANNON_D1_API_TOKEN` -- environment variable for the D1 API token.
- `is_d1_configured()` returns `True` only if both are set.

**Planned Phase 2 sync flow:**
- On charge/refund: local write, then async push to D1.
- On startup: pull from D1 to initialize local cache.
- Periodic: pull from D1 every 5 minutes for external changes (e.g., Stripe purchases).
- Conflict resolution: D1 is source of truth; replay unsynced local transactions.

---

## Stripe Webhook Handling

**Source:** `src/license_server/stripe_webhooks.py`

Handles Stripe `checkout.session.completed` events to add purchased credits. Registered as an `APIRouter` and mounted on the license server.

### Endpoint: `POST /stripe/webhook`

**Headers:**
- `Stripe-Signature` -- the Stripe webhook signature header. Required in production; skipped in dev mode.

**Signature verification:**
- Only performed when `STRIPE_WEBHOOK_SECRET` environment variable is set.
- Parses the `Stripe-Signature` header format: `t=timestamp,v1=signature`.
- Computes `HMAC-SHA256(secret, "{timestamp}.{raw_body}")` and compares with `v1` using constant-time comparison.
- Returns HTTP 400 if verification fails.

**Checkout handling:**
1. Extracts `metadata.package` and `metadata.machine_id` from the session object.
2. Looks up the credit amount from the `PACKAGES` dict (same values as `CREDIT_PACKAGES`).
3. Reads the current balance from `license.db`.
4. Adds credits: `new_balance = current_balance + credits_to_add`.
5. Recomputes the HMAC for the new balance.
6. Records a transaction with operation `stripe_purchase` and reason `package:{package_name}`.

**Package mapping (in `stripe_webhooks.py`):**

| Package | Credits |
|---------|---------|
| `starter` | 50 |
| `creator` | 250 |
| `pro` | 1,000 |
| `studio` | 5,000 |

**Error cases:**
- HTTP 400 if `package` or `machine_id` is missing from session metadata.
- HTTP 400 if the package name is not recognized.
- HTTP 500 if the balance record is not found in the database.

**Response:** `{"status": "ok"}` on success. All other Stripe event types are ignored.
