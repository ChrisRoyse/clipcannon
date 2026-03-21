# Billing & Licensing System

## Architecture Overview

Dual-layer billing with local cache and central source of truth:

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  MCP Server      │     │  License Server   │     │  Cloudflare D1   │
│  (client-side)   │────▶│  (port 3000)      │────▶│  (source of truth)│
│                  │     │  SQLite cache      │     │  Stripe webhooks  │
│  LicenseClient   │     │  HMAC integrity    │     │  Balance tokens   │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

## License Key Provisioning

**Deterministic HMAC keys** — same machine always gets same key:

```
key = "lk_" + HMAC-SHA256(LICENSE_SIGNING_KEY, "provision:{machine_id}").slice(0, 32)
```

- Machine ID persisted to `/data/.machine_id` (survives container recreation)
- Machine email pattern: `auto-{machine_id.slice(0,16)}@machine.ocrprovenance.com`
- Initial balance: $0.00 (no free tier)
- Rate limited: 3/min/IP + 2/5min/machine_id

## Ed25519 License Signing

```
5 Required Secrets (generated at startup):
├── SESSION_SECRET         — 64 hex chars, HMAC for session tokens
├── LICENSE_SIGNING_KEY    — Ed25519 private key seed, 64 hex chars
├── LICENSE_PUBLIC_KEY     — Ed25519 public key, 64 hex chars
├── WORKER_AUTH_SECRET     — Cloudflare worker auth, 64 hex chars
└── WEBHOOK_SHARED_SECRET  — Stripe webhook HMAC, 64 hex chars

Secret sourcing (3-tier fallback):
1. Cloudflare Worker /v1/secrets/bootstrap (primary, deterministic per machine)
2. Disk cache at /data/.license_secrets (offline fallback)
3. Local Ed25519 generation (first boot only)
```

## HMAC Balance Integrity

Every balance mutation is HMAC-verified:

```
signBalance(keyId, balanceCents) = HMAC-SHA256(LICENSE_SIGNING_KEY, "balance:{keyId}:{balanceCents}")
```

Checked at: charge, refund, credit, admin adjust, sync, stale refund, startup migration.
**Tampered balances → FATAL exit.**

## Charge Flow

```
1. MCP calls POST /v1/charge (license server)
   └── Deducts from local balance, signs new HMAC
   └── Returns: { charge_id, balance_cents, cost_cents }

2. License server calls POST /v1/charge/authorize (Cloudflare Worker)
   └── Deducts from D1 balance (source of truth)
   └── Returns: { authorized, balance_cents, balance_token }

3. On OCR success: POST /v1/confirm → marks charge 'confirmed'
   On OCR failure: POST /v1/refund → restores balance + signs HMAC

Failure modes:
- Central 402 → refund local → InsufficientBalanceError (doc stays 'pending')
- Network error → refund local → FATAL (no offline grace)
```

**Cost:** 3 cents per file (server-side pricing)

## Stripe Integration

```
Payment flow:
1. User clicks "Add $10" on dashboard
2. POST /dashboard/checkout → license server → Cloudflare Worker
3. Worker creates Stripe checkout session
4. User redirects to Stripe hosted page
5. Payment completes → Stripe webhook → Worker
6. Worker: upsert D1 balance + customers table
7. Dashboard syncs balance from license server

Webhook events:
- checkout.session.completed → credit balance
- charge.refunded → deduct balance
```

**Cloudflare D1 Schema:**
- `balances` (key_hash PK, balance_cents)
- `charges` (id PK, key_hash, amount_cents, status)
- `payments` (id PK, key_hash, stripe_payment_intent_id)
- `customers` (key_hash PK, real_email, stripe_customer_id)
- `refunds` (id PK, stripe_refund_id UNIQUE)
- `machine_secrets` (machine_id PK, secrets)

## License Server Routes

| Route | Auth | Purpose |
|-------|------|---------|
| `POST /v1/provision` | None (rate limited) | Auto-provision key from machine_id |
| `POST /v1/charge` | X-License-Key | Reserve charge |
| `POST /v1/confirm` | X-License-Key | Confirm charge |
| `POST /v1/refund` | X-License-Key | Refund charge |
| `POST /v1/sync` | X-License-Key | Sync offline charges |
| `GET /v1/balance` | X-License-Key | Get balance + cost |
| `PUT /v1/spending-limit` | X-License-Key | Set monthly limit |
| `POST /v1/auth/send-link` | None | Magic link email |
| `POST /v1/auth/verify` | Token | Create session |
| `POST /v1/checkout/by-key` | X-License-Key | Stripe session |
| `POST /v1/checkout/internal/credit` | X-Webhook-Secret | Webhook callback |
| `POST /v1/account/recover-by-email` | Session | Balance recovery |
| `POST /v1/admin/*` | Admin session | Revoke, adjust, keys, usage |

## Spending Limits

- Monthly spending caps: min $1, max $1,000
- Enforcement: charge blocked if monthly spend + cost > limit
- Reset: manual or automatic at month boundary
- Dashboard shows warning at 80% of limit

## Email Recovery

1. User pays via Stripe → real email captured in D1
2. Machine dies → new machine, new key, $0 balance
3. User sends magic link to original email
4. System calls `POST /v1/balance/consolidate-by-email`
5. All old keys' balances consolidated to new key
6. Balance restored

## Cloud Proxy URL Detection

When running behind a reverse proxy on cloud GPU platforms (RunPod, Vast.ai), the license server detects the public-facing URL from request headers. This ensures Stripe checkout `success_url` callbacks and magic link emails use the correct external URL.

**Detection** (`packages/server/src/public-url.ts`):
1. `X-Forwarded-Proto` + `X-Forwarded-Host` (standard reverse proxy headers)
2. `Origin` header (browser POST/CORS)
3. `Referer` header (fallback)
4. `Host` header with protocol detection
5. `DASHBOARD_URL` env var (internal localhost default)

## Machine ID Persistence

```
Primary: /data/.machine_id (in Docker volume)
Backup:  ~/.ocr-provenance-mcp/wrapper.json (on host)
Flow:    Host wrapper passes MACHINE_ID env → container uses it
         Same machine_id → same secrets → same key → same balance
```
