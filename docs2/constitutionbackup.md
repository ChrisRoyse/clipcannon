# Constitution: OCR Provenance MCP System

## Identity

| Field | Value |
|-------|-------|
| Project | OCR Provenance MCP — AI Context Engineering Platform |
| Version | 1.2.4 |
| Updated | 2026-03-14 |
| Schema | v33 (per-database) + Registry v1 (`_registry.db`) |
| Stack | TypeScript 5.x + Python 3.10+ / MCP SDK / SQLite + sqlite-vec |
| Processing | 100% local GPU — Marker-pdf (OCR), Chandra (VLM), nomic-embed-text-v1.5 (embeddings), ms-marco-MiniLM-L-12-v2 (reranking) |
| Stats | 151 MCP tools, 30 tool modules, 28 per-db tables + 7 registry tables, 10 Python files, 144 test files |
| Transport | **HTTP/SSE (primary, always-on)** — all 3 services run concurrently; stdio available but deprecated |

MCP server + context engineering platform for document OCR, VLM image analysis, clustering, comparison, hybrid search, and multi-database management with complete provenance tracking. Every piece of data chains back to its exact source file, page, and character offset. All processing runs locally on GPU — zero cloud APIs. A centralized registry enables sub-millisecond database discovery, filtering, tagging, archiving, and workspace grouping.

---

## Critical Rules (IMMUTABLE)

1. **NEVER store data without a provenance record** — core invariant; data without lineage is unusable
2. **NEVER use `console.log()` in TypeScript** — use `console.error()` — stdout is JSON-RPC in stdio mode; console.log corrupts MCP protocol
3. **NEVER use cloud APIs for OCR, VLM, or embeddings** — local GPU only; no document content leaves the machine
4. **NEVER commit secrets, credentials, or `.env` files**
5. **NEVER use `flash-attn`** — incompatible with Blackwell/sm_120, MPS, and CPU; use standard PyTorch attention
6. **NEVER modify per-database schema for registry features** — registry is a separate database; per-db stays at v33
7. **ALWAYS include `original_text` in search results** — users must never need a follow-up query
8. **ALWAYS validate tool inputs with Zod via `validateInput()`** — MCP tools accept untrusted input
9. **ALWAYS read a file before editing it**
10. **ALWAYS kill stale server before rebuild**: `pkill -f "dist/bin.js"` (separate command), then `npm run build && npm test`
11. **NEVER serve HTML from the MCP server** — REST API only in `bin-http.ts`; dashboard is a separate app

---

## Fail-Fast Doctrine (IMMUTABLE)

Silent failures are highest-severity bugs. If something is broken, fail immediately with clear error info.

**Prohibited patterns:**
- `try { X } catch { fallbackY }` that silently degrades
- Returning default/empty data when real operation fails — throw instead
- `try { newWay } catch { oldWay }` backwards-compat hacks — if it fails, throw and exit
- Swallowing errors in catch blocks — every catch MUST: re-throw, throw with context, OR `console.error()` + `handleError()` (tool boundary only)
- `|| defaultValue` to mask undefined from failed operations

**Required error context:** what failed, why, what input caused it. Include file paths, IDs, operation names. Preserve stack traces. `MCPError.fromUnknown()` preserves `.details` and `.code`.

**Boundary:** MCP tool handlers are where errors become structured responses: `try { ... } catch { return handleError(error); }`. The prohibition is on catch blocks that silently succeed or fall back.

**No backwards compatibility:** No shims, re-exports, `_deprecated` wrappers, `_var` renames, or `// removed` comments. Git is the record. If a migration changes a table, update ALL code touching that table.

---

## Build & Verify

```bash
pkill -f "dist/bin.js"   # Kill stale server FIRST (separate command)
npm run build             # tsc — must succeed with 0 errors
npm test                  # vitest run — must pass with 0 failures
npm run lint              # eslint
```

After ANY code change: kill → build → test. If tests fail, fix root cause — never skip.

---

## Architecture

### 3-Service Topology (Always-On)

```
┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│   MCP Server     │       │  License Server   │       │    Dashboard     │
│   :3366 (HTTP)   │──────▶│  :3000 (Hono)     │◀──────│  :3367 (Next.js) │
│                  │       │                   │       │                   │
│  151 MCP tools   │       │  SQLite + Stripe  │       │  Context Eng. UI  │
│  REST API /api/* │       │  Ed25519 licenses │       │  Dark/Light mode  │
│  SQLite + vec    │       │  Session auth     │       │  Tailwind CSS     │
└──────────────────┘       └──────────────────┘       └──────────────────┘
```

All 3 services are **mandatory** — no fallbacks, no skipping. Docker entrypoint starts all 3 and monitors them.

- **MCP → License Server**: `X-License-Key` header
- **Dashboard → License Server**: `Authorization: Bearer` session token
- **Dashboard → MCP**: Next.js proxy routes `/api/mcp/[...path]` → `localhost:3366/api/*`

### Transport: HTTP Primary

The MCP server runs via HTTP/SSE (`bin-http.ts`) as the primary transport. Each HTTP session gets its own `McpServer` + `StreamableHTTPServerTransport`. Sessions have TTL, cleanup runs every 60s. CORS restricted to localhost by default.

**Why not stdio:** stdio blocks when multiple services need the same process. HTTP allows the MCP server, license server, and dashboard to all run simultaneously and communicate via HTTP.

stdio entry point (`index.ts` / `bin.js`) still exists for backwards compatibility but is not the recommended path.

### MCP Server Layout

```
src/
├── index.ts              # stdio entry point (deprecated)
├── bin-http.ts           # HTTP/SSE entry point (primary) + REST API endpoints
├── server/               # State, config, MCPError, register-tools, startup
├── tools/                # 30 tool modules + shared.ts
│   └── shared.ts         # formatResponse, handleError, ToolDefinition, successResult
├── services/
│   ├── ocr/              # Marker-pdf daemon bridge
│   ├── vlm/              # Chandra daemon bridge
│   ├── embedding/        # nomic-embed-text-v1.5 bridge
│   ├── storage/
│   │   ├── database/     # Per-database ops (CRUD, helpers, types)
│   │   ├── registry/     # Registry singleton (_registry.db)
│   │   ├── migrations/   # Per-database schema v1-v33
│   │   └── vector.ts     # sqlite-vec operations
│   ├── search/           # BM25 + vector + RRF + rerank
│   ├── chunking/         # Text chunking with offset tracking
│   ├── clustering/       # HDBSCAN, agglomerative, k-means
│   ├── comparison/       # Document diff and similarity
│   ├── images/           # Image extraction and optimization
│   ├── provenance/       # Chain management and verification
│   ├── license/          # License gate (charge/confirm/refund, NO offline grace)
│   ├── clm/              # Contract lifecycle management
│   ├── audit.ts          # Audit logging
│   ├── python-pool.ts    # Python worker pool
│   └── webhook-delivery.ts
├── models/               # TypeScript interfaces
└── utils/                # hash.ts (SHA-256), validation.ts (Zod)
python/                   # 10 files (9 workers + __init__.py)
tests/                    # 144 test files
```

### License System

| Component | Location | Purpose |
|-----------|----------|---------|
| License Gate | `src/services/license/` | $0.03/file, auto-provisioned key, NO offline grace — server MUST be reachable |
| License Server | `packages/server` | Hono + SQLite, Stripe, Ed25519-signed licenses |
| Dashboard | separate repo | Next.js 15, magic link login, balance, Stripe checkout |

**Auto-provisioning**: `POST /v1/provision` → deterministic `HMAC(LICENSE_SIGNING_KEY, "provision:" + machine_id)`. Same machine = same key. Ed25519-signed license_token for offline verification. $0 balance until Stripe payment.

**Billing**: `gate.charge(hash)` → process → `gate.confirm(id)` or `gate.refund(id)`. $0 balance = 402 error. Server determines pricing via `cost_per_file_cents`.

**Auth**: Two non-overlapping middlewares — License Key Auth (SHA256 hash) for MCP endpoints, Session Auth (Bearer) for dashboard.

**Secrets**: SESSION_SECRET, LICENSE_SIGNING_KEY (Ed25519 private), LICENSE_PUBLIC_KEY (Ed25519 public).

---

## Local Model Stack

| Component | Model | VRAM | Daemon |
|-----------|-------|------|--------|
| OCR | Marker-pdf v1.10.2 | ~4GB | Yes — `ocr_worker_local.py --daemon` |
| VLM | Chandra v0.1.8 | ~18GB | Yes — `vlm_worker_local.py --daemon` |
| Embeddings | nomic-embed-text-v1.5 | ~1GB | No — per-call |
| Reranking | ms-marco-MiniLM-L-12-v2 | ~1GB | No — per-call |

**Daemon pattern**: Spawn on first request → models loaded once → requests serialized via promise lock → auto-respawn on crash → `destroy()` frees GPU before next model loads → kill on shutdown.

**GPU**: RTX 5090 (32GB) or equivalent. `getMarkerClient().destroy()` before VLM to free ~4GB.

### Model Cache Locations

Models MUST be pre-cached. No runtime downloads — fail fast if missing.

| Model | Location | Size | Env Override |
|-------|----------|------|-------------|
| Marker/Surya OCR | `~/.cache/datalab/models/` | 3.3GB | `MODEL_CACHE_DIR` |
| Nomic embeddings | `./models/nomic-embed-text-v1.5/` | 523MB | `EMBEDDING_MODEL_PATH` |
| Chandra VLM | `~/.cache/huggingface/hub/models--datalab-to--chandra/` | 17.6GB | `CHANDRA_MODEL_PATH` |
| MS-Marco reranker | `~/.cache/huggingface/hub/` | 260MB | (HuggingFace default) |

---

## Data Model

### Provenance Chain (Core Invariant)

```
DOCUMENT(0) → OCR_RESULT(1) → CHUNK(2)/IMAGE(2) → EMBEDDING(3)/VLM_DESC(3) → EMBEDDING(4)
```

Each record: SHA-256 content hash, chain-hash (Merkle parent linking), processor name, timestamps, quality scores.

### Per-Database Schema (v33, 28 physical + 5 virtual)

- **Core**: documents, ocr_results, chunks, embeddings, images, provenance
- **Features**: extractions, form_fills, comparisons, clusters, document_clusters, tags, entity_tags
- **Infra**: schema_version, database_metadata, fts_index_metadata, uploaded_files, saved_searches
- **Collab**: users, audit_log, annotations, document_locks
- **Workflow**: workflow_states, approval_chains, approval_steps
- **CLM**: obligations, playbooks
- **Events**: webhooks
- **Virtual**: vec_embeddings (sqlite-vec), chunks_fts, vlm_fts, extractions_fts, documents_fts (FTS5)

**FK cascade delete order**: vec_embeddings → NULL vlm_embedding_id → embeddings → images → clusters → document_clusters → comparisons → chunks → extractions → ocr_results → FTS → document → provenance

### Registry (`_registry.db`)

Location: `~/.ocr-provenance/_registry.db` (alongside `databases/`, not inside it). 6 physical + 1 FTS5 virtual table. Startup reconciliation syncs filesystem ↔ registry. Write-through on all CRUD. ON DELETE/UPDATE CASCADE on all FKs.

### Storage Layout

```
~/.ocr-provenance/
├── _registry.db          # Central catalog
├── _license.db           # Balance cache, pending charges
├── databases/*.db        # Independent RAG databases
└── images/<doc-id>/      # Extracted images
```

---

## REST API (HTTP mode)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (probes all 3 services in Docker mode) |
| GET | `/api/overview` | Database overview |
| GET | `/api/databases` | List databases |
| GET | `/api/databases/:name/stats` | Database stats |
| GET | `/api/databases/:name/documents` | Paginated documents |
| GET | `/api/databases/:name/health` | Health gaps |
| GET | `/api/databases/:name/provenance-tree` | Provenance chain |
| GET | `/api/databases/:name/quality-heatmap` | Quality heatmap |
| GET | `/api/databases/:name/embedding-coverage` | Embedding coverage |
| GET | `/api/databases/:name/search-readiness` | Search readiness |
| GET | `/api/databases/:name/context-composition` | Context breakdown |
| GET | `/api/databases/:name/trends` | Processing trends |
| GET | `/api/databases/:name/chunks` | Chunk list |
| GET | `/api/databases/:name/clusters` | Cluster list |
| GET | `/api/databases/:name/images` | Image list |
| GET | `/api/activity` | Recent activity |
| GET | `/api/status` | System status |
| GET | `/api/context-summary` | Cross-database context |
| GET | `/api/recommendations` | AI recommendations |
| GET | `/api/license` | Billing & license status |
| POST | `/api/checkout` | Stripe checkout (proxied) |
| POST | `/mcp` | MCP protocol endpoint (SSE) |

---

## Conventions

| Scope | Convention |
|-------|-----------|
| TS files | kebab-case |
| Variables | camelCase, SCREAMING_SNAKE for constants |
| Functions | camelCase, verb-first |
| Types | PascalCase |
| MCP tools | snake_case, `ocr_` prefix |
| Python | snake_case, type hints required |
| REST paths | kebab-case under `/api/` |

**Tool handler pattern**: `validateInput(Schema, params)` → logic → `formatResponse(successResult({...next_steps}))` or `handleError(error)`. Every `successResult()` MUST include `next_steps: {tool, description}[]`.

**Python bridge**: stdout = JSON data, stderr = logs. Never hardcode `python3` — use platform detection. `resolve_device('auto')` → CUDA > MPS > CPU.

---

## Anti-Patterns (FORBIDDEN)

| Don't | Do Instead |
|-------|-----------|
| Store data without provenance | Create provenance record for every transformation |
| Use cloud APIs for processing | Local Marker/Chandra/nomic models only |
| Add fallback/degradation logic | Throw with full context |
| Catch and swallow errors | Re-throw or log + propagate failure |
| Return empty data on failure | Throw with operation, input, cause |
| `try { new } catch { old }` | Remove old paths entirely |
| Mock data in tests | Real databases, real operations, real verification |
| Generate embeddings one-at-a-time | Batch with `batch_size=64` (max 100) |
| Process logos/icons with VLM | Filter with image relevance heuristics first |
| Open every `.db` to list databases | Query `_registry.db` |
| Leave FK ON during migration | `PRAGMA foreign_keys = OFF` during table recreation |
| Set VLM concurrency >2 | Daemon is single-threaded; >2 just queues |
| `\|\| defaultValue` to mask failures | Check explicitly, throw if unexpected |

---

## Security

- **Secrets**: No API keys for processing. `OCR_LICENSE_KEY` auto-provisioned (Ed25519-signed). Env secrets: SESSION_SECRET, LICENSE_SIGNING_KEY, LICENSE_PUBLIC_KEY.
- **Input**: Zod validation on all MCP tool inputs. SQL injection protection.
- **Paths**: `sanitizePath()` resolves absolute, rejects `..`, validates against allowed dirs. Docker: `OCR_PROVENANCE_ALLOWED_DIRS`.
- **Network**: HTTP/SSE primary transport. CORS restricted to localhost. All inference local-only.
- **Database**: File mode 600. WAL mode. `PRAGMA foreign_keys = ON` (except migrations).
- **Integrity**: SHA-256 hashes on all content. `ocr_provenance_verify` for tamper detection.

---

## Performance Budgets

| Component | Target |
|-----------|--------|
| OCR (Marker) | ~2s/page, ~340s for 160pg PDF, ~120s model startup (first call) |
| VLM (Chandra) | 3-8s/image, ~120s model startup (first call) |
| Embedding | 60-120 chunks/s (CUDA), ~20 (CPU) |
| Vector search | <20ms for 100K vectors |
| BM25 search | <10ms |
| Hybrid search | <500ms (BM25 + vector + RRF + rerank) |
| Provenance verify | <100ms/chain |
| Registry listing | <1ms, FTS <5ms, reconciliation <100ms for 100 DBs |

---

## Testing

**Rules**: No mocks — real databases, real operations, real verification. Tests MUST fail when functionality breaks. Clean up temp artifacts. After code changes: kill → build → test.

| Category | Focus |
|----------|-------|
| Unit (80% target) | Chunking, hashing, provenance, CRUD, registry, Zod validation |
| Integration | OCR, VLM, GPU embedding, pipeline, search, registry reconciliation |
| Device-specific | CUDA/MPS/CPU detection, throughput benchmarks |

---

## Tool Groups (151 tools, 30 modules)

| Group | Module | Count |
|-------|--------|-------|
| Database (core) | database.ts | 5 |
| Database Management | database-management.ts | 8 |
| Portability | portability.ts | 7 |
| Sharing | sharing.ts | 2 |
| Ingestion | ingestion.ts | 7 |
| Search | search.ts | 7 |
| Documents | documents.ts | 10 |
| Provenance | provenance.ts | 6 |
| VLM (Local) | vlm-local.ts | 3 |
| Images | images.ts | 8 |
| Extraction | extraction.ts | 1 |
| Structured Extraction | extraction-structured.ts | 3 |
| Reports | reports.ts | 8 |
| Comparison | comparison.ts | 6 |
| Clustering | clustering.ts | 7 |
| Chunks | chunks.ts | 4 |
| Embeddings | embeddings.ts | 4 |
| Tags | tags.ts | 6 |
| Intelligence | intelligence.ts | 5 |
| Health | health.ts | 1 |
| Maintenance | maintenance.ts | 1 |
| Users | users.ts | 2 |
| Collaboration | collaboration.ts | 11 |
| Workflow | workflow.ts | 8 |
| CLM | clm.ts | 9 |
| Compliance | compliance.ts | 3 |
| Events | events.ts | 6 |
| Config | config.ts | 2 |
| Dashboard | dashboard.ts | 2 |
| License | license.ts | 1 |

Supported file types: PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, PNG, JPG, JPEG, TIFF, TIF, BMP, GIF, WEBP, TXT, CSV, MD (18)

---

## Python Workers

| Worker | File | Daemon |
|--------|------|--------|
| OCR | `ocr_worker_local.py` | Yes |
| VLM | `vlm_worker_local.py` | Yes |
| Embedding | `embedding_worker.py` | No |
| Image Extractor | `image_extractor.py` | No |
| DOCX Images | `docx_image_extractor.py` | No |
| Image Optimizer | `image_optimizer.py` | No |
| Clustering | `clustering_worker.py` | No |
| Reranker | `reranker_worker.py` | No |
| GPU Utils | `gpu_utils.py` | No |

---

## Known Gotchas

| Gotcha | Resolution |
|--------|------------|
| MCP server process is `dist/bin.js` not `dist/index.js` | `pkill -f "dist/bin.js"` |
| `pkill` + build in one command kills build | Run pkill separately first |
| Circular FK: `embeddings.image_id` ↔ `images.vlm_embedding_id` | NULL vlm_embedding_id first |
| FTS5 external content join | `c.rowid = chunks_fts.rowid` (NOT `c.id` UUID) |
| FTS5 rebuild ghost rows | `delete-all` + re-insert (NOT `rebuild`) |
| Windows: `python3` not found | Auto-detect: `python` (Win) vs `python3` (Unix) |
| MCP client caches tool list | New tools need server restart |
| `getMarkerClient().destroy()` before VLM | Frees GPU for Chandra (~18GB) |
| `max_pages` vs `page_range` | TS `max_pages` → Python `page_range` conversion |
| Registry name collision | Registry uses `_` prefix, lives outside `databases/` |
| `dirname('/data')` = `/` | When env var IS the directory, use it directly |
| `dotenv.config()` prints to stdout in v17 | Use `{ quiet: true }` |

---

## Ingestion Pipeline

```
1. ocr_ingest_files / ocr_ingest_directory → validate → store docs (status='pending')
2. ocr_process_pending [max_pages, mode, include_images] →
   License charge → Marker OCR → provenance → images → chunks → embeddings → (VLM) → confirm/refund
3. Return: {processed: N, failed: M, details: [...]}
```

Cost: $0 for inference. $0.03/file billing via auto-provisioned license key.

---

## AI Agent Navigation

Every tool response includes `next_steps: {tool, description}[]`. Tool descriptions start with a category tag:

| Tag | Meaning |
|-----|---------|
| `[ESSENTIAL]` | Core workflow, use freely |
| `[CRITICAL]` | Database discovery/navigation |
| `[PROCESSING]` | Triggers computation, may be slow |
| `[STATUS]` | Read-only, no side effects |
| `[ANALYSIS]` | Deep inspection |
| `[SEARCH]` | Search tools |
| `[SETUP]` | One-time config |
| `[MANAGE]` | Non-destructive modifications |
| `[DESTRUCTIVE]` | Permanent deletion, confirm first |

Compact mode: `compact=true` = 77% token reduction. Context-aware next_steps: empty → suggest creation; populated → suggest analysis.

---

## Configuration

| Setting | Default | Notes |
|---------|---------|-------|
| `MCP_TRANSPORT` | http | **http** (primary) or stdio |
| `MCP_HTTP_PORT` | 3366 | HTTP mode port |
| `MCP_SESSION_TTL` | 3600 | Session TTL seconds |
| `TORCH_DEVICE` | auto | auto/cuda/mps/cpu |
| `EMBEDDING_DEVICE` | auto | auto/cuda/mps/cpu |
| `OCR_MAX_CONCURRENT` | 2 | 1-10 |
| `OCR_TIMEOUT` | 1800000 | 30 min ms |
| `CHANDRA_METHOD` | hf | hf or vllm |
| `VLM_CONCURRENCY` | 2 | Max 2 (daemon single-threaded) |
| `MODEL_CACHE_DIR` | ~/.cache/datalab/models | OCR models |
| `CHANDRA_MODEL_PATH` | (HF default) | VLM model override |
| `EMBEDDING_MODEL_PATH` | ./models/nomic-embed-text-v1.5 | Embedding model |
| `OCR_LICENSE_KEY` | (auto-provisioned) | HMAC + Ed25519 |
| `OCR_LICENSE_SERVER` | https://license.ocrprovenance.com | License server |
| ~~`OCR_LICENSE_OFFLINE_GRACE_HOURS`~~ | ~~24~~ | REMOVED — no offline grace, server must be reachable |
| `OCR_PROVENANCE_ALLOWED_DIRS` | (none) | Extra allowed dirs |
| `OCR_SPENDING_LIMIT_CENTS` | (none) | Monthly limit (server-enforced) |

No required env vars — all defaults are sensible. License auto-provisions on first run.

---

## Workflow State Machine

```
(none) → draft → submitted → in_review → approved → executed → archived
                                        → rejected
                                        → changes_requested → submitted (loop)
```

---

## Error Classes

| Class | Use |
|-------|-----|
| `MCPError` | Tool-level errors → MCP clients |
| `VectorError` | sqlite-vec failures |
| `EmbeddingError` | Embedding generation failures |
| `OCRError` | Marker-pdf failures |
| `VLMError` | Chandra failures |

Rules: Every catch re-throws or adds context. Use `MCPError.fromUnknown()`. Use `withDatabaseOperation()` for race protection. Parse Python stderr with worker name + input.
