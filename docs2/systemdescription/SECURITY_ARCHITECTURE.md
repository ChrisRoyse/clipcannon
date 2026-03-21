# Security Architecture

## Security Layers

```
Layer 1: Network          ← 127.0.0.1 binding, Docker isolation
Layer 2: Authentication   ← X-License-Key header, session cookies
Layer 3: Authorization    ← Rate limiting, spending limits, admin roles
Layer 4: Data Integrity   ← HMAC balances, Ed25519 signatures, SHA-256 chains
Layer 5: Secret Isolation ← Dashboard env whitelist, no secrets in workers
Layer 6: Input Validation ← Zod schemas, path sanitization, SQL parameterization
Layer 7: Audit Trail      ← Complete audit log with user/action/entity tracking
```

## Authentication

### MCP Server Authentication
- **Header**: `X-License-Key: lk_XXXXXXXX...`
- Key hashed with SHA-256, compared against `license_keys.key_hash`
- **Localhost exemption**: Requests from `127.0.0.1` / `::1` skip auth (trusted container boundary)
- MCP server binds `127.0.0.1` locally, `0.0.0.0` in Docker

### Dashboard Authentication
- **Magic link email** → signed JWT token (10-min expiry)
- Session stored in SQLite `sessions` table (30-day TTL)
- HTTP-only, SameSite=Lax cookies
- Session token verified via `SESSION_SECRET` HMAC

### License Server Middleware
| Auth Type | Header | Usage |
|-----------|--------|-------|
| License Key | `X-License-Key` | Charge, balance, checkout |
| Session | `Authorization: Bearer {token}` | Dashboard routes, email recovery |
| Admin | Session + email in `ADMIN_EMAILS` | Revoke, adjust, keys, usage |
| Webhook | `X-Webhook-Secret` | Stripe webhook callback |

## Cryptographic Integrity

### HMAC Balance Protection
```
signBalance(keyId, balanceCents) = HMAC-SHA256(LICENSE_SIGNING_KEY, "balance:{keyId}:{balanceCents}")
```
- Verified at EVERY balance mutation (charge, refund, credit, sync, admin adjust, stale refund)
- Constant-time comparison via `timingSafeEqual()` (prevents timing attacks)
- Missing or invalid HMAC → FATAL exit
- On startup: re-signs all records with current secrets (migration support)

### Ed25519 License Signing
- Private key seed: 32 bytes (64 hex chars)
- Used for: session tokens, signed data payloads
- Public key: distributed for offline verification
- DER format with ASN.1 prefixes

### SHA-256 Provenance Chains
```
chain_hash = SHA-256(content_hash + ":" + parent.chain_hash)
```
- Every provenance record has `content_hash` (output hash) and `chain_hash` (cumulative)
- Verification: walk chain from leaf to root, recompute all hashes
- Tampering at any point breaks the chain

### Balance Token (Worker-side)
```
signBalanceToken(keyHash, balanceCents, WORKER_AUTH_SECRET)
  = HMAC-SHA256(secret, "balance-token:{keyHash}:{balanceCents}:{timestamp}")
  expires: 1 hour
```
- Issued by Cloudflare Worker only
- Unverifiable by client (requires WORKER_AUTH_SECRET)
- Prevents local balance forgery

## Secret Management

### 5 Required Secrets
| Secret | Purpose | Risk if Leaked |
|--------|---------|---------------|
| `SESSION_SECRET` | Session HMAC | Session forgery |
| `LICENSE_SIGNING_KEY` | Ed25519 seed + HMAC balance | Balance tampering, key forgery |
| `LICENSE_PUBLIC_KEY` | Ed25519 public | Low (verification only) |
| `WORKER_AUTH_SECRET` | Cloudflare auth | Unauthorized charges |
| `WEBHOOK_SHARED_SECRET` | Stripe webhooks | Fake payment credits |

### Secret Isolation
- **Dashboard** started with `env -i` whitelist — receives ONLY:
  - `SESSION_SECRET`, `OCR_LICENSE_KEY`, `MCP_SERVER_URL`, `OCR_LICENSE_SERVER`
- **Dashboard does NOT receive**: LICENSE_SIGNING_KEY, LICENSE_PUBLIC_KEY, WORKER_AUTH_SECRET, WEBHOOK_SHARED_SECRET
- **Python workers** receive NO secrets (GPU processing only)
- **Secrets file**: In-memory only when Cloudflare available; `/data/.license_secrets` (chmod 600) only in offline/air-gapped mode

### Secret Sourcing (3-Tier)
1. Cloudflare Worker: `/v1/secrets/bootstrap` (deterministic per machine_id) — **secrets stay in memory only, no disk persistence**
2. Disk cache: `/data/.license_secrets` (offline/air-gapped fallback only — deleted when Cloudflare becomes available)
3. Local generation: Ed25519 keypair + random hex (first boot only, persisted for offline restart)

## Rate Limiting

### MCP Tool Rate Limits
| Category | Limit | Window | Tools |
|----------|-------|--------|-------|
| search | 50/min | 60s | ocr_search, ocr_search_cross_db, ocr_rag_context |
| ingestion | 10/min | 60s | ocr_ingest_files, ocr_ingest_directory, ocr_process_pending |
| destructive | 5/min | 60s | ocr_db_delete, ocr_document_delete, ocr_tag_delete |
| upload | rate limited | 60s | POST /api/upload |
| default | 100/min | 60s | All other tools |

### License Provisioning Rate Limits
| Limit | Window | Key |
|-------|--------|-----|
| 3 requests | 1 minute | Per IP address |
| 2 requests | 5 minutes | Per machine_id |

## Input Validation

- **Zod schemas** on all 153 MCP tools — strict type checking, coercion, rejection
- **Path sanitization** — prevents `../../../etc/passwd` directory traversal
  - Ingestion: validated against `OCR_PROVENANCE_ALLOWED_DIRS`
  - Upload: filename sanitization (255 char limit, extension preserved)
  - Viewer: document IDs validated as UUIDs, `path.basename()` applied, path separator rejection
- **Database name validation** — alphanumeric, underscore, hyphen only
- **SQL parameterization** — all queries use prepared statements (no string concatenation)
- **File existence checks** — validated before processing
- **Response truncation** — 700 KB max to prevent client disk spill
- **Upload validation** — magic byte verification, SHA-256 hashing, 10 GB staging quota, 48-hour auto-expiry, duplicate detection by content hash

## Network Security

- **MCP server**: binds `127.0.0.1` (localhost only) except in Docker (`0.0.0.0`)
- **Docker**: `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`
- **Non-root user**: `mcp` (UID 999)
- **No outbound from workers**: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`
- **Read-only host mount**: `-v $HOME:/host:ro`
- **Database permissions**: `chmod 600` on all sensitive files
- **Viewer cache isolation**: document IDs validated before filesystem access

## Compliance Features

### Audit Logging
- Every tool call logged: action, entity_type, entity_id, user_id, details_json, ip_address
- Queryable via `ocr_audit_query` tool
- Exportable via `ocr_export_audit_log` (CSV/JSON)

### Compliance Reports
| Tool | Standard |
|------|----------|
| `ocr_compliance_report` | General compliance overview |
| `ocr_compliance_hipaa` | HIPAA-specific report |
| `ocr_compliance_export` | SOC 2, HIPAA, SOX format exports |

### Provenance Verification
- `ocr_provenance_verify` — validates SHA-256 hash chains
- `ocr_provenance_export` — W3C PROV format export
- Complete chain: file → OCR → chunk → embedding (every step auditable)

## No Offline Grace

**Critical design decision**: The license server MUST be reachable for every charge.
- No cached balance processing
- No offline grace period
- No `chargeOffline()` function exists
- Network failure → refund local charge → FATAL error
- This prevents balance manipulation via network disconnection
