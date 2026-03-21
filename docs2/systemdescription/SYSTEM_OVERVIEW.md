# OCR Provenance MCP Server — System Overview

## What Is It?

OCR Provenance MCP Server is a **production-grade document intelligence platform** that runs entirely on local GPU hardware. It provides 153 MCP (Model Context Protocol) tools for document ingestion, OCR processing, semantic search, image analysis, and compliance tracking — all with complete provenance chain auditing. Supports concurrent multi-agent access via per-session database isolation.

**Key differentiator**: 100% local processing — no cloud APIs, no data leaves your machine.

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Document OCR** | Marker-pdf v1.10.2 converts PDF/DOCX/PPTX/XLSX/XLS/HTML/EPUB/TXT/CSV/MD to structured Markdown |
| **Semantic Search** | 768-dim nomic-embed-text-v1.5 embeddings with sqlite-vec HNSW index, cross-encoder reranking enabled by default |
| **Image Analysis** | Chandra v0.1.8 VLM generates structured descriptions of extracted images |
| **Document Viewer** | REST API for in-browser document viewing with PDF/Office/TIFF/image conversion and 24h cache management |
| **Provenance Tracking** | SHA-256 hash chains track every transformation from file to embedding |
| **Hybrid Search** | BM25 full-text + semantic vector search fused via Reciprocal Rank Fusion with cross-encoder reranking |
| **HTTP File Upload** | Multipart streaming upload via POST /api/upload with staging, dedup, and provenance |
| **Multi-Session** | Per-session database isolation for concurrent multi-agent access via SessionManager + ConnectionCache |
| **Multi-Database** | User-isolated SQLite databases with full lifecycle management |
| **Cloud Deployment** | Supports cloud GPU platforms (RunPod, Vast.ai) with automatic public URL detection via reverse proxy headers |
| **Billing & Licensing** | Ed25519-signed licenses, Stripe payments, HMAC-protected balances |
| **Compliance** | HIPAA, SOC 2, SOX audit trail exports |
| **Collaboration** | Annotations, document locks, approval workflows |
| **Contract Management** | Obligation tracking, playbook comparison, structured extraction |

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Protocol** | Model Context Protocol (MCP) — JSON-RPC over stdio or HTTP/SSE |
| **Server** | TypeScript 5.5 (ES2022), Node.js 20 |
| **Database** | SQLite 3 + sqlite-vec (HNSW vector search) + FTS5 (full-text) |
| **OCR Engine** | Marker-pdf v1.10.2 (Python, CUDA-accelerated) |
| **VLM Engine** | Chandra v0.1.8 (Python, ~18GB VRAM) |
| **Embeddings** | nomic-embed-text-v1.5 (Python, 768-dim, ~2-3GB VRAM) |
| **Reranking** | cross-encoder/ms-marco-MiniLM-L-12-v2 (GPU with CPU fallback, ~1GB) |
| **License Server** | Hono.js + SQLite (port 3000) |
| **Dashboard** | Next.js (port 3367) |
| **Billing** | Cloudflare Workers + D1 + Stripe |
| **Container** | Docker (two-image: models ~24GB + app ~500MB) |
| **Document Viewer** | LibreOffice (Office→PDF), Pillow (TIFF→PNG), native PDF/image passthrough |
| **Testing** | Vitest 4.1 (3700+ tests, 161 files) |

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────┐
│                    AI Client (Claude Code, Cursor, etc.) │
│                         stdio / HTTP                     │
└────────────────────────────┬────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────┐
│              NPM Wrapper (packages/wrapper/)             │
│   Docker lifecycle · HTTP-to-stdio bridge · Config       │
│   Ingest intercept (auto-upload host files)              │
│   WSL auto-detection · AI client registration            │
└────────────────────────────┬────────────────────────────┘
                             │ HTTP POST /mcp
┌────────────────────────────▼────────────────────────────┐
│                 Docker Container (3 Services)            │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  MCP Server   │  │License Server│  │  Dashboard   │  │
│  │  port 3366    │  │  port 3000   │  │  port 3367   │  │
│  │  153 tools    │  │  Billing/Auth│  │  Web UI      │  │
│  │  Viewer API   │  │              │  │              │  │
│  └──────┬───────┘  └──────────────┘  └──────────────┘  │
│         │                                                │
│  ┌──────▼──────────────────────────────────────────┐    │
│  │           Python GPU Workers (Daemons)           │    │
│  │                                                  │    │
│  │  ┌─────────┐  ┌─────────┐  ┌──────────────┐    │    │
│  │  │Marker   │  │Chandra  │  │nomic-embed   │    │    │
│  │  │OCR      │  │VLM      │  │Embeddings    │    │    │
│  │  │8-10GB   │  │~18GB    │  │2-3GB VRAM    │    │    │
│  │  └─────────┘  └─────────┘  └──────────────┘    │    │
│  │  ┌─────────────────┐  ┌──────────────────┐     │    │
│  │  │Cross-Encoder    │  │Spreadsheet Prep  │     │    │
│  │  │Reranker ~1GB    │  │(openpyxl/xlrd)   │     │    │
│  │  └─────────────────┘  └──────────────────┘     │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │        SQLite + sqlite-vec + FTS5                 │   │
│  │   /data/*.db (user databases)                     │   │
│  │   /data/_license_server.db (billing)              │   │
│  │   /data/viewer-cache/ (document viewer)           │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# One-command install
npx -y ocr-provenance-mcp install

# Manual Docker usage
docker-compose up -d
```

## Project Structure Summary

```
/home/cabdru/datalab/
├── src/              # TypeScript source (MCP server + tools + services)
│   ├── tools/        # 31 tool modules (153 MCP tools)
│   ├── services/     # Business logic (OCR, search, embedding, storage, upload, reranker)
│   ├── models/       # Data type definitions
│   ├── server/       # MCP infrastructure, tool registration, multi-session state
│   │   ├── session-state.ts   # SessionManager — per-session database isolation
│   │   ├── connection-cache.ts # ConnectionCache — ref-counted shared SQLite connections
│   │   └── register-tools.ts  # Tool registration with rate limiting
│   └── wrapper/      # Docker lifecycle management
├── python/           # 11 Python workers (OCR, VLM, embedding, clustering, spreadsheet prep)
├── packages/
│   ├── server/       # License billing server (Hono + SQLite)
│   ├── wrapper/      # NPM CLI wrapper (published to npm)
│   └── checkout-worker/  # Cloudflare Worker (Stripe integration)
├── tests/            # 161 test files (unit, integration, GPU, E2E)
├── scripts/          # Docker build/release, entrypoint, healthcheck
└── docs2/            # This documentation
```

## Key Design Principles

1. **100% Local GPU Processing** — No cloud APIs, no data exfiltration
2. **Complete Provenance** — Every transformation tracked with SHA-256 hash chains
3. **Fail-Fast** — No graceful degradation; all 3 services mandatory
4. **HMAC Balance Integrity** — Tamper-proof billing via cryptographic signing
5. **Zero-Config Install** — Single `npx` command handles everything
6. **Multi-Database Isolation** — Each database is a separate SQLite file
7. **Multi-Session Isolation** — Concurrent MCP sessions get independent state via SessionManager + ConnectionCache
8. **Denormalized Search** — Embedding records always include original text (self-contained results)
9. **Natural Language Queries** — Search optimized for natural language; keyword lists produce poor embeddings
10. **Document Viewer** — In-browser document viewing with server-side conversion and 24h cache lifecycle
11. **Cloud Proxy Support** — Automatic public URL detection for cloud GPU platforms via reverse proxy headers
