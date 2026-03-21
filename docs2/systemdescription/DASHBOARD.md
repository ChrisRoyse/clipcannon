# Dashboard & Web UI

## Overview

The dashboard is a **Next.js server-rendered web application** on port 3367, providing user authentication, account management, and Stripe payment integration. It is one of the 3 mandatory services in the Docker container.

**Source**: External repo (`../ocrprovenance-cloud`), built as Stage 3 of Dockerfile.
**Routes**: Server-rendered HTML via Hono (no SPA).

## Routes

### Public
| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Landing page with features, pricing ($0.03/file) |
| `/login` | GET/POST | Email entry → magic link |
| `/login/sent` | GET | "Check your email" confirmation |
| `/auth/verify` | GET | Magic link verification → session cookie |

### Authenticated (Session Cookie)
| Route | Method | Purpose |
|-------|--------|---------|
| `/dashboard` | GET | Main dashboard — stats, balance, charges, payments |
| `/dashboard` | POST | Handle Stripe checkout callback |
| `/dashboard/checkout` | POST | Create Stripe checkout session |
| `/dashboard/account` | GET | Profile, spending limit, API key |
| `/dashboard/account/spending-limit` | POST | Set/update monthly limit |
| `/dashboard/account/spending-limit/reset` | POST | Reset monthly counter |
| `/dashboard/account/regenerate-key` | POST | Revoke + generate new key |
| `/dashboard/logout` | POST | Delete session, clear cookie |

## Features

### Main Dashboard
- **Balance**: Current account balance (e.g., "$5.00")
- **Files Remaining**: Calculated as balance / $0.03
- **Files Processed**: Total confirmed charges
- **This Month**: Spending vs. monthly limit
- **Recent Charges** table (last 20): date, file type, amount, status
- **Recent Payments** table (last 20): date, amount, Stripe payment ID

### Add Funds
- Preset buttons: $5, $10, $25, $50
- Custom amount input
- Redirects to Stripe hosted checkout
- Success callback syncs balance

### Account Page
- Profile: email, member since, Stripe customer ID
- Spending limit management ($10/$25/$50/$100/No Limit)
- API key display (prefix only) with regeneration option

## Authentication Flow

```
1. User enters email → POST /login
2. Server generates signed JWT (10-min expiry)
3. Email sent via Resend API (or dev mode returns token)
4. User clicks magic link → GET /auth/verify?token=...
5. Token verified → session created (30-day TTL)
6. HTTP-only cookie set → redirect to /dashboard
```

## Environment Isolation

Dashboard runs with **whitelisted environment variables only**:

| Receives | Does NOT Receive |
|----------|-----------------|
| SESSION_SECRET | LICENSE_SIGNING_KEY |
| OCR_LICENSE_KEY | LICENSE_PUBLIC_KEY |
| MCP_SERVER_URL | WORKER_AUTH_SECRET |
| OCR_LICENSE_SERVER | WEBHOOK_SHARED_SECRET |
| CHECKOUT_API_URL | |

Even if the dashboard is compromised, it cannot forge license tokens or Stripe webhooks.

## Communication

```
Dashboard (3367) ──HTTP──▶ License Server (3000)
                           └── Balance, charges, sessions, auth

Dashboard (3367) ──HTTP──▶ MCP Server (3366)
                           └── /health, /api/checkout, /api/checkout/callback
                           └── X-License-Key header for auth
                           └── Localhost (127.0.0.1) exempted from auth
```

## Cloud Proxy Support

The dashboard works behind cloud reverse proxies (RunPod, Vast.ai). The license server's `getPublicBaseUrl()` function detects the external URL from `X-Forwarded-Host` and `X-Forwarded-Proto` headers, ensuring Stripe checkout callbacks and magic link emails use the correct public URL instead of the internal localhost address.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `ocr_dashboard_open` | Open dashboard in default browser (supports WSL/Mac/Linux) |
| `ocr_dashboard_status` | Check health of all 3 services |
