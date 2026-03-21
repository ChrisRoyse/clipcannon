# Phase 1: Foundation — Billing System Specification

**Version:** 1.0
**Date:** 2026-03-21

---

## 1. Overview

ClipCannon uses a credit-based billing system adapted from OCR Provenance's proven dual-layer architecture. Credits are the unit of consumption. Users purchase credit packages via Stripe checkout. The license server manages credit balances with HMAC-SHA256 integrity verification.

### Architecture

```
┌────────────────────┐     ┌────────────────────┐     ┌────────────────────┐
│  ClipCannon MCP    │     │  License Server     │     │  Cloudflare D1     │
│  Server (local)    │────▶│  (port 3100)        │────▶│  (source of truth) │
│                    │     │  SQLite local cache  │     │  Stripe webhooks   │
│  LicenseClient     │     │  HMAC integrity      │     │  Credit balances   │
└────────────────────┘     └────────────────────┘     └────────────────────┘
```

### Three-Layer Trust Model

1. **Cloudflare D1** — Source of truth. Stores canonical credit balances. Updated by Stripe webhooks on purchase.
2. **License Server (local SQLite)** — Cached copy for low-latency operations. Syncs with D1 periodically and on charge/refund.
3. **HMAC Integrity** — Every balance mutation is HMAC-SHA256 signed. Tampering detected = fatal exit.

---

## 2. Credit System

### 2.1 Phase 1 Credit Operations

| Operation | Credit Cost | When Charged | Refund Policy |
|:----------|:-----------|:-------------|:-------------|
| Video Analysis (full 12-stream pipeline) | 10 credits | On `clipcannon_ingest` call | Full refund if pipeline fails |

Phase 2+ adds: clip render (2 credits), metadata generation (1 credit), platform publish (1 credit).

### 2.2 Credit Packages (Stripe Checkout)

| Package | Credits | Price | Per-Credit |
|:--------|:--------|:------|:-----------|
| Starter | 50 | $5 | $0.10 |
| Creator | 250 | $20 | $0.08 |
| Pro | 1,000 | $60 | $0.06 |
| Studio | 5,000 | $200 | $0.04 |
| Unlimited | Unlimited | $99/month | -- |

### 2.3 Spending Controls

- Monthly spending cap: $5 - $500 (user-configurable)
- Warning at 80% of monthly limit
- Per-video cost estimate shown before processing begins
- Detailed cost breakdown in credit history

---

## 3. License Server

### 3.1 HTTP API

The license server runs on port 3100 and exposes these endpoints:

#### POST /v1/charge

Charge credits for an operation.

**Request:**
```json
{
  "machine_id": "hmac-derived-id",
  "operation": "analyze",
  "credits": 10,
  "project_id": "proj_a1b2c3d4",
  "idempotency_key": "uuid-v4"
}
```

**Response (success):**
```json
{
  "success": true,
  "balance_before": 852,
  "balance_after": 842,
  "transaction_id": "txn_001",
  "timestamp": "2026-03-21T10:00:00Z"
}
```

**Response (insufficient credits):**
```json
{
  "success": false,
  "error": "INSUFFICIENT_CREDITS",
  "balance": 5,
  "required": 10,
  "message": "Need 10 credits but only 5 available. Purchase more at the dashboard."
}
```

#### POST /v1/refund

Refund credits for a failed operation.

**Request:**
```json
{
  "machine_id": "hmac-derived-id",
  "transaction_id": "txn_001",
  "reason": "pipeline_failed",
  "project_id": "proj_a1b2c3d4"
}
```

#### GET /v1/balance

Get current credit balance.

**Response:**
```json
{
  "balance": 842,
  "balance_hmac": "a3f7...",
  "last_sync_utc": "2026-03-21T09:55:00Z",
  "spending_this_month": 58,
  "spending_limit": 200
}
```

#### GET /v1/history

Get transaction history.

**Query params:** `?limit=20&offset=0`

#### POST /v1/sync

Force sync with Cloudflare D1.

---

### 3.2 Local SQLite Schema (License Server)

```sql
CREATE TABLE balance (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Single row
    machine_id TEXT NOT NULL,
    balance INTEGER NOT NULL DEFAULT 0,
    balance_hmac TEXT NOT NULL,
    last_sync_utc TEXT,
    spending_this_month INTEGER DEFAULT 0,
    spending_limit INTEGER DEFAULT 200,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE transactions (
    transaction_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    credits INTEGER NOT NULL,          -- Negative for charge, positive for refund
    balance_before INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    project_id TEXT,
    idempotency_key TEXT UNIQUE,
    reason TEXT,
    synced_to_d1 BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_transactions_time ON transactions(created_at DESC);
CREATE INDEX idx_transactions_project ON transactions(project_id);

CREATE TABLE sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,           -- 'push' or 'pull'
    d1_balance INTEGER,
    local_balance INTEGER,
    status TEXT,                        -- 'success', 'failed', 'conflict'
    error_message TEXT,
    synced_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## 4. Machine ID & HMAC Integrity

### 4.1 Machine ID Derivation

```python
import hashlib
import platform
import uuid

def get_machine_id() -> str:
    """Deterministic machine ID from hardware characteristics.
    Same machine always produces the same ID.
    """
    raw = f"{platform.node()}|{uuid.getnode()}|{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```

### 4.2 HMAC Balance Signing

```python
import hmac
import hashlib

def derive_hmac_key(machine_id: str) -> bytes:
    """Deterministic HMAC key from machine ID."""
    return hashlib.sha256(f"clipcannon-v1|{machine_id}".encode()).digest()

def sign_balance(balance: int, machine_id: str) -> str:
    """Sign a balance value with machine-derived key."""
    key = derive_hmac_key(machine_id)
    payload = f"balance:{balance}".encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def verify_balance(balance: int, expected_hmac: str, machine_id: str) -> bool:
    """Verify balance hasn't been tampered with."""
    actual = sign_balance(balance, machine_id)
    return hmac.compare_digest(actual, expected_hmac)
```

### 4.3 Tamper Detection

On every balance read:
1. Read `balance` and `balance_hmac` from SQLite
2. Compute expected HMAC from balance + machine_id
3. If mismatch: **FATAL EXIT** — log tampering attempt, refuse to serve

On every balance write:
1. Compute new HMAC for new balance
2. UPDATE both `balance` and `balance_hmac` in single transaction

---

## 5. Cloudflare D1 Sync

### 5.1 Sync Strategy

- **On charge:** Local charge immediately → async push to D1
- **On refund:** Local refund immediately → async push to D1
- **Periodic:** Pull from D1 every 5 minutes to catch external changes (credit purchases via Stripe)
- **On startup:** Pull from D1 to initialize local cache

### 5.2 Conflict Resolution

If local balance differs from D1 balance:
- D1 is source of truth
- If D1 balance > local: user purchased credits (apply D1 balance)
- If D1 balance < local: local has unsynced charges (push charges to D1)
- If both differ in complex ways: use D1 balance, replay unsynced local transactions

### 5.3 D1 Schema

```sql
-- Cloudflare D1 (remote)
CREATE TABLE machines (
    machine_id TEXT PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    email TEXT,
    stripe_customer_id TEXT,
    spending_limit INTEGER DEFAULT 200,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE credit_purchases (
    purchase_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    stripe_session_id TEXT UNIQUE,
    package TEXT NOT NULL,
    credits_added INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT DEFAULT 'completed',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);

CREATE TABLE credit_transactions (
    transaction_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    credits INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    project_id TEXT,
    created_at TEXT,
    FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);
```

---

## 6. Stripe Integration

### 6.1 Checkout Flow

1. User clicks "Add Credits" on dashboard
2. Dashboard creates Stripe Checkout Session (server-side)
3. User redirected to Stripe-hosted payment page
4. On success: Stripe sends webhook to Cloudflare Worker
5. Worker updates D1 balance
6. License server pulls updated balance on next sync

### 6.2 Stripe Webhook Handler (Cloudflare Worker)

```
POST /stripe/webhook → Cloudflare Worker
  ├── Verify Stripe signature
  ├── Parse event: checkout.session.completed
  ├── Extract: customer_email, machine_id (from metadata), package
  ├── Look up credit amount for package
  ├── UPDATE machines SET balance = balance + credits WHERE machine_id = ?
  ├── INSERT INTO credit_purchases (...)
  └── Return 200 OK
```

### 6.3 Stripe Configuration

Environment variables (set in Cloudflare Worker):
- `STRIPE_SECRET_KEY` — Stripe API key (never on local machine)
- `STRIPE_WEBHOOK_SECRET` — Webhook signature verification

Dashboard environment variables:
- `STRIPE_PUBLISHABLE_KEY` — For checkout redirect

---

## 7. LicenseClient (MCP Server Side)

```python
class LicenseClient:
    """Client for the local license server. Used by MCP tools to charge/refund credits."""

    def __init__(self, base_url: str = "http://localhost:3100"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=5.0)

    async def charge(self, operation: str, credits: int, project_id: str) -> ChargeResult:
        """Charge credits. Returns ChargeResult with success/failure."""
        ...

    async def refund(self, transaction_id: str, reason: str) -> RefundResult:
        """Refund a previous charge."""
        ...

    async def get_balance(self) -> int:
        """Get current credit balance."""
        ...

    async def estimate(self, operation: str) -> int:
        """Estimate credit cost for an operation."""
        ...
```

### Integration with Pipeline

```python
async def clipcannon_ingest(project_id: str, options: dict = None):
    # 1. Charge credits BEFORE starting pipeline
    charge = await license_client.charge("analyze", 10, project_id)
    if not charge.success:
        return {"error": {"code": "INSUFFICIENT_CREDITS", "message": charge.error}}

    try:
        # 2. Run pipeline
        await pipeline.run(project_id, options)
        return {"status": "analyzing", "credits_charged": 10}
    except PipelineError as e:
        # 3. Refund on failure
        await license_client.refund(charge.transaction_id, f"pipeline_failed: {e}")
        raise
```

---

## 8. Dashboard Billing Pages (Phase 1)

### 8.1 Credit Balance Display

- Current balance (large number)
- Spending this month / monthly limit (progress bar)
- Warning banner at 80% of limit

### 8.2 Add Credits Page

- 4 preset buttons: $5 (50), $20 (250), $60 (1000), $200 (5000)
- Click → Stripe Checkout Session → redirect to Stripe
- Success → redirect back to dashboard with updated balance

### 8.3 Transaction History

- Table: date, operation, credits, project, balance after
- Filterable by date range and operation type

---

*End of Phase 1 Billing Spec*
