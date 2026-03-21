# OCR Provenance MCP Server — Documentation Index

> **Version**: 1.2.66 | **Tools**: 153 | **Tests**: 3700+ | **Schema**: v33

## Documentation Files

| Document | Description |
|----------|-------------|
| [SYSTEM_OVERVIEW.md](./SYSTEM_OVERVIEW.md) | Architecture overview, tech stack, capabilities, project structure |
| [DATA_FLOW.md](./DATA_FLOW.md) | Complete document lifecycle, provenance chains, search pipeline, billing integration |
| [MCP_TOOLS_REFERENCE.md](./MCP_TOOLS_REFERENCE.md) | All 153 MCP tools organized by category with descriptions |
| [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) | Complete SQLite schema — 30+ tables, 50+ indexes, FTS5, sqlite-vec |
| [DOCKER_DEPLOYMENT.md](./DOCKER_DEPLOYMENT.md) | Two-image architecture, 3-service startup, entrypoint, wrapper CLI |
| [BILLING_AND_LICENSING.md](./BILLING_AND_LICENSING.md) | License keys, HMAC balances, Stripe, Ed25519, spending limits |
| [SECURITY_ARCHITECTURE.md](./SECURITY_ARCHITECTURE.md) | 7-layer security, auth, crypto integrity, rate limiting, compliance |
| [GPU_PROCESSING.md](./GPU_PROCESSING.md) | Python workers, daemon protocol, VRAM management, model specs |
| [DASHBOARD.md](./DASHBOARD.md) | Web UI routes, authentication, environment isolation |
| [DOCUMENT_VIEWER.md](./DOCUMENT_VIEWER.md) | REST API for document viewing with PDF/Office/TIFF/image conversion and cache management |

## Quick Reference

### What does this system do?
A **100% local GPU-powered document intelligence platform** that ingests documents, performs OCR, generates embeddings, analyzes images with a VLM, and provides hybrid search — all with complete provenance chain tracking and compliance audit trails. Exposes 153 tools via the Model Context Protocol (MCP).

### How does data flow?
```
File → Ingest → OCR (Marker) → Chunk → Embed (nomic) → Index → Search (rerank)
                    └→ Images → VLM (Chandra) → Embed → Index → Search (rerank)
```
Every step creates a provenance record with SHA-256 hash chain integrity.

### What's in the Docker container?
Three mandatory services:
1. **MCP Server** (port 3366) — 153 tools via HTTP/SSE + Document Viewer REST API
2. **License Server** (port 3000) — Billing, auth, Stripe
3. **Dashboard** (port 3367) — Web UI for account management

### How is it secured?
- Ed25519 signed licenses, HMAC-protected balances
- Rate limiting on all tools (5-100 calls/min by category)
- Zod schema validation, path sanitization (viewer + upload + ingest), SQL parameterization
- Non-root Docker, `--cap-drop=ALL`, secret isolation
- Complete audit logging, HIPAA/SOC 2/SOX compliance exports

### Key file locations
```
src/tools/         — 31 modules defining 153 MCP tools
src/services/      — Business logic (OCR, search, embedding, storage, upload, reranker)
src/server/        — MCP infrastructure, tool registration, multi-session state, connection cache
python/            — 11 Python worker scripts (incl. spreadsheet_prepare.py)
packages/server/   — License billing server (Hono + SQLite)
packages/wrapper/  — NPM CLI wrapper (Docker management, ingest intercept)
packages/checkout-worker/ — Cloudflare Worker (Stripe)
scripts/           — Docker entrypoint, healthcheck, release
tests/             — 161 test files (unit, integration, GPU, E2E)
```
