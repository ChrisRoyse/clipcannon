# Docker & Deployment Architecture

## Two-Image Architecture

| Image | Registry | Size | Rebuild Frequency |
|-------|----------|------|-------------------|
| **Models Base** | `leapable/ocr-provenance-models:v1` | ~24 GB | Rarely (model updates only) |
| **App** | `leapable/ocr-provenance-mcp:latest` | ~500 MB | Every release |

The app image uses `FROM leapable/ocr-provenance-models:v1` to inherit the Python venv and pre-cached models.

## Dockerfile — 4-Stage Build

```
Stage 1: node-build (TypeScript compilation)
  ├── Node 20-bookworm-slim
  ├── Compiles src/ → dist/
  ├── Validates native addons (better-sqlite3, sqlite-vec)
  └── Prunes devDependencies

Stage 2: license-server-build
  ├── Compiles packages/server/ → Hono + SQLite billing server
  └── Self-contained on port 3000

Stage 3: dashboard-build
  ├── External build context: ../ocrprovenance-cloud
  └── Next.js standalone build

Stage 4: runtime (FROM models image)
  ├── Installs Node.js 20
  ├── Installs LibreOffice (headless, for Office→PDF conversion in viewer)
  ├── Copies compiled outputs from stages 1, 2, 3
  ├── Copies Python worker scripts
  ├── Patches Python venv with requirements.txt (incl. openpyxl, xlrd for XLSX/XLS)
  ├── Verifies spreadsheet dependencies at build time
  ├── Overlays nomic model config (HuggingFace offline mode)
  ├── Creates /data/staged/ directory for HTTP upload staging
  └── Copies bundled data (AlexHormoziTranscripts demo)
```

## 3 Mandatory Services

All services must be running. If ANY dies, the container exits.

```
┌──────────────────────────────────────────────────┐
│  Docker Container                                 │
│                                                   │
│  1. License Server (port 3000) ← Started first    │
│     └── Hono + SQLite, billing/auth               │
│     └── Entrypoint waits for /health (10s)        │
│                                                   │
│  2. MCP HTTP Server (port 3366) ← Started second  │
│     └── 153 MCP tools, JSON-RPC over HTTP/SSE     │
│     └── REST API: POST /api/upload, DELETE /api/upload/staged │
│     └── REST API: GET/POST /api/viewer/* (document viewer) │
│     └── Multi-session state (per-session DB isolation) │
│     └── Entrypoint waits for /health (30s)        │
│                                                   │
│  3. Dashboard (port 3367) ← Started third          │
│     └── Next.js web UI                            │
│     └── Started with env whitelist (secret isolation)│
│     └── Entrypoint waits for HTTP 200 (15s)       │
└──────────────────────────────────────────────────┘
```

## Entrypoint Startup Flow (`docker-entrypoint.sh`)

```
Phase 1: Stable Machine ID
  └── Persist to /data/.machine_id (survives container recreation)

Phase 2: Secrets Generation
  ├── Primary: Fetch from Cloudflare Worker (/v1/secrets/bootstrap)
  ├── Fallback: Load from /data/.license_secrets (offline)
  └── Last resort: Generate locally (Ed25519 keypair)
  5 Required Secrets:
    SESSION_SECRET, LICENSE_SIGNING_KEY, LICENSE_PUBLIC_KEY,
    WORKER_AUTH_SECRET, WEBHOOK_SHARED_SECRET

Phase 3: GPU Detection
  └── Resolves TORCH_DEVICE=auto → cuda:0 / mps / cpu

Phase 4: Service Startup (strict order)
  ├── License Server → wait for /health
  ├── MCP Server → wait for /health
  └── Dashboard → wait for HTTP 200

Phase 5: Viewer Cache Reconciliation
  └── MCP server creates /data/viewer-cache/ at startup
  └── Cleans stale viewer-cache entries, sets timers for fresh
```

## Docker Compose

```yaml
services:
  ocr-provenance:
    image: leapable/ocr-provenance-mcp:latest
    ports:
      - "3366:3366"   # MCP HTTP
      - "3367:3367"   # Dashboard
      - "3000:3000"   # License Server
    volumes:
      - ocr-provenance-mcp-data:/data
    runtime: nvidia
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
              count: all
```

## Volume Mounts

| Mount | Container Path | Mode | Purpose |
|-------|---------------|------|---------|
| Named volume | `/data` | rw | SQLite databases, secrets, machine ID, staged uploads, viewer cache |
| Host home | `/host` | ro | User file access for ingestion |
| Windows drives (WSL) | `/host-windows/c` | ro | Windows file access (auto-detected) |
| Export dir | `/export` | rw | Database sharing/export |

## Environment Variables

### Core Services
| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_TRANSPORT` | `http` | Protocol mode |
| `MCP_HTTP_PORT` | `3366` | MCP server port |
| `LICENSE_PORT` | `3000` | License server port |
| `PORT` | `3367` | Dashboard port |

### GPU & Models
| Variable | Default | Purpose |
|----------|---------|---------|
| `TORCH_DEVICE` | `auto` | GPU device (auto/cuda/mps/cpu) |
| `EMBEDDING_DEVICE` | `auto` | Embedding model device |
| `MODEL_CHECKPOINT` | `/opt/models/chandra` | VLM model path |
| `RERANKER_MODEL_PATH` | `/opt/models/ms-marco-MiniLM-L-12-v2` | Cross-encoder reranker model path |
| `HF_HUB_OFFLINE` | `1` | Prevent HuggingFace network calls |
| `TRANSFORMERS_OFFLINE` | `1` | Prevent Transformers network calls |

### Processing
| Variable | Default | Purpose |
|----------|---------|---------|
| `OCR_MAX_CONCURRENT` | `2` | Parallel OCR tasks |
| `VLM_CONCURRENCY` | `2` | Parallel VLM image processing |
| `CHANDRA_METHOD` | `hf` | VLM inference method |

### File Access
| Variable | Default | Purpose |
|----------|---------|---------|
| `OCR_PROVENANCE_DATABASES_PATH` | `/data` | SQLite storage |
| `OCR_PROVENANCE_ALLOWED_DIRS` | `/host,/data,...` | Permitted directories |
| `OCR_PROVENANCE_HOST_HOME` | (set by wrapper) | Host home for path translation |
| `OCR_PROVENANCE_SHARE_DIR` | `/export` | Shared directory for database sharing |

## NPM Wrapper

The wrapper (`packages/wrapper/`) manages Docker from the host:

```bash
npx -y ocr-provenance-mcp install   # 5-step: Docker→models→app→license→register
npx -y ocr-provenance-mcp start     # Start container + sync keys
npx -y ocr-provenance-mcp stop      # Stop container
npx -y ocr-provenance-mcp status    # Show health + endpoints
npx -y ocr-provenance-mcp logs 100  # Tail container logs
npx -y ocr-provenance-mcp update    # Pull latest + restart
```

**Config persistence**: `~/.ocr-provenance-mcp/wrapper.json`
- Stores: licenseKey, machineId, accountEmail, imageTag, ports

**HTTP-to-Stdio Bridge**: The wrapper translates AI client stdin/stdout to HTTP POST `/mcp` with `X-License-Key` header and `Mcp-Session-Id` tracking.

**Ingest Intercept**: The wrapper HTTP bridge intercepts `ocr_ingest_files` and `ocr_ingest_directory` tool calls and automatically uploads host files via `POST /api/upload` before forwarding the request. This bypasses Docker bind mount permission issues — the file is staged inside the container at `/data/staged/` before ingestion proceeds.

**WSL Auto-Detection**: On WSL2, the wrapper auto-detects Windows mount paths (`/mnt/c/...`) and adds appropriate volume mounts (`/host-windows/c`) so Windows files are accessible inside the container.

**Stale Container Recreation**: If the container exists but is in a stopped/stale state, the wrapper automatically removes and recreates it.

**AI Client Auto-Registration**: Detects and registers with Claude Code, Claude Desktop, Cursor, and Windsurf.

## Healthcheck Script (`docker-healthcheck.sh`)

Verifies ALL 3 services unconditionally:
```bash
curl http://127.0.0.1:3366/health  # MCP → status: ok/operational
curl http://127.0.0.1:3000/health  # License server
curl http://127.0.0.1:3367/        # Dashboard → HTTP 200
```

## Cloud GPU Deployment

The system supports deployment on cloud GPU platforms (RunPod, Vast.ai) behind reverse proxies. The license server detects the public-facing URL from request headers so that Stripe callbacks, magic link emails, and cookie settings use the correct external URL instead of the internal localhost address.

**Public URL detection priority** (`packages/server/src/public-url.ts`):
1. `X-Forwarded-Proto` + `X-Forwarded-Host` headers (standard reverse proxy)
2. `Origin` header (browser POST/CORS requests)
3. `Referer` header (fallback)
4. `Host` header with protocol detection (external hosts assume HTTPS)
5. `DASHBOARD_URL` env var (internal localhost default)

**Environment detection**: The system auto-detects `RUNPOD_POD_ID` and similar cloud platform environment variables.

## Security Hardening

- Non-root user `mcp` (UID 999)
- `--cap-drop=ALL` + `--security-opt=no-new-privileges:true`
- Dashboard env isolation via `env -i` whitelist
- Database files: `chmod 600`
- All models offline-only (zero network calls in container)
- Viewer document IDs validated as UUIDs with path traversal rejection
