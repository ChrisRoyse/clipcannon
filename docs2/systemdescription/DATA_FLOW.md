# Data Flow & Processing Pipeline

## Document Lifecycle — End to End

```
  USER FILE (PDF/DOCX/PPTX/XLSX/XLS/HTML/EPUB/TXT/CSV/MD)
       │
       ├── (Option A: direct file path from host mount)
       ├── (Option B: HTTP upload via POST /api/upload → /data/staged/)
       ├── (Option C: wrapper ingest intercept — auto-uploads host files)
       │
       ▼
  ┌─────────────────────────────────────────────────┐
  │  1. INGESTION (ocr_ingest_files/directory)       │
  │     • Validate file type & path                  │
  │     • Compute SHA-256 file hash                  │
  │     • Duplicate detection (by hash)              │
  │     • Create Document record (status=pending)    │
  │     • Create DOCUMENT provenance (depth=0)       │
  │     • License charge (3¢/file)                   │
  │     • Text passthrough (txt/csv/md): skip OCR    │
  │     • Spreadsheets (xlsx/xls/csv): skip steps    │
  │       3b (images) and 4b (VLM) — tabular only   │
  └────────────────────┬────────────────────────────┘
                       │
                       ▼
  ┌─────────────────────────────────────────────────┐
  │  2. OCR PROCESSING (Marker-pdf v1.10.2)          │
  │     • Python daemon: ocr_worker_local.py         │
  │     • GPU: CUDA 8-10GB VRAM                      │
  │     • Output: Markdown + JSON blocks + metadata  │
  │     • Page offsets (exact char boundaries)        │
  │     • Create OCR_RESULT provenance (depth=1)     │
  │     • Document status → complete                 │
  └────────┬───────────────────────┬────────────────┘
           │                       │
           ▼                       ▼
  ┌────────────────┐    ┌──────────────────────────┐
  │ 3a. CHUNKING   │    │ 3b. IMAGE EXTRACTION     │
  │  Hybrid section│    │  Marker-extracted + file  │
  │  aware (2000ch)│    │  based (PyMuPDF/docx)    │
  │  10% overlap   │    │  SHA-256 content hash     │
  │  Max 8000 chars│    │  Context text from OCR    │
  │  CHUNK prov    │    │  IMAGE provenance         │
  │  (depth=2)     │    │  (depth=2)                │
  └───────┬────────┘    └──────────┬───────────────┘
          │                        │
          ▼                        ▼
  ┌────────────────┐    ┌──────────────────────────┐
  │ 4a. EMBEDDING  │    │ 4b. VLM ANALYSIS         │
  │  nomic-embed   │    │  Chandra v0.1.8          │
  │  768-dim float │    │  Structured JSON output   │
  │  CUDA 2-3GB    │    │  imageType, subjects,     │
  │  EMBEDDING     │    │  paragraphs, entities     │
  │  provenance    │    │  VLM_DESC provenance      │
  │  (depth=3)     │    │  (depth=3)                │
  └───────┬────────┘    └──────────┬───────────────┘
          │                        │
          │                        ▼
          │             ┌──────────────────────────┐
          │             │ 4c. VLM EMBEDDING        │
          │             │  nomic-embed on VLM text  │
          │             │  EMBEDDING provenance     │
          │             │  (depth=4)                │
          │             └──────────┬───────────────┘
          │                        │
          ▼                        ▼
  ┌─────────────────────────────────────────────────┐
  │  5. INDEXING                                     │
  │     • sqlite-vec HNSW index (768-dim vectors)    │
  │     • FTS5 full-text index (porter stemmer)      │
  │     • B-tree indexes (50+ SQL indexes)           │
  └────────────────────┬────────────────────────────┘
                       │
                       ▼
  ┌─────────────────────────────────────────────────┐
  │  6. SEARCH                                       │
  │     • BM25 keyword search (FTS5)                 │
  │     • Semantic vector search (sqlite-vec cosine)  │
  │     • Hybrid search (RRF, equal weights 1.0/1.0) │
  │     • Query expansion + classification            │
  │     • Cross-encoder reranking (enabled by default)│
  │     • Natural language query guidance + detection │
  │     • auto_route disabled (equal weight fusion)   │
  └─────────────────────────────────────────────────┘
```

## Provenance Chain Structure

Every transformation creates an immutable provenance record linked by parent-child relationships with SHA-256 hash chain integrity:

```
DOCUMENT (depth=0)                 ← Original file ingestion
  └── OCR_RESULT (depth=1)         ← Marker-pdf output
      ├── CHUNK (depth=2)          ← Text segments (2000 chars)
      │   └── EMBEDDING (depth=3)  ← 768-dim vector
      ├── IMAGE (depth=2)          ← Extracted images
      │   ├── VLM_DESC (depth=3)   ← Chandra analysis
      │   │   └── EMBEDDING (depth=4) ← VLM text vector
      │   └── (no direct embedding)
      └── EXTRACTION (depth=2)     ← Structured data extraction
          └── EMBEDDING (depth=3)  ← Extraction text vector
```

**Provenance Record Fields:**
- `id` (UUID), `type`, `chain_depth`, `chain_path`
- `source_type`, `source_id`, `parent_id`, `root_document_id`
- `content_hash` (SHA-256 of output)
- `chain_hash` (SHA-256 of content_hash + parent's chain_hash)
- `processor`, `processor_version`, `processing_duration_ms`
- `processing_quality_score`, `location` (page, character range)

## Python Worker Architecture

All three GPU workers run as **persistent daemon processes**, keeping models loaded in VRAM:

```
┌─────────────────────────────────────────────────────────────┐
│  TypeScript MCP Server                                       │
│                                                              │
│  NomicEmbeddingClient ──stdin/stdout──▶ embedding_worker.py  │
│  ChandraClient        ──stdin/stdout──▶ vlm_worker_local.py  │
│  MarkerClient         ──stdin/stdout──▶ ocr_worker_local.py  │
│                                                              │
│  Protocol: JSON lines (one JSON object per line)             │
│  Concurrency: Mutex lock per daemon (serialized requests)    │
└─────────────────────────────────────────────────────────────┘
```

**Daemon Lifecycle:**
1. First request triggers `spawn(python worker.py --daemon)`
2. Worker outputs ready signal: `{"status": "ready", "device": "cuda:0", ...}`
3. Subsequent requests reuse loaded model (no reload)
4. On batch completion: daemons killed to free GPU VRAM

| Worker | Model | VRAM | Daemon Protocol |
|--------|-------|------|----------------|
| OCR | Marker-pdf v1.10.2 | 8-10 GB | JSON lines on stdin/stdout |
| VLM | Chandra v0.1.8 | ~18 GB | JSON lines on stdin/stdout |
| Embedding | nomic-embed-text-v1.5 | 2-3 GB | JSON lines on stdin/stdout |

## Chunking Algorithm

**Hybrid Section-Aware Chunking:**
1. Parse Markdown structure (headings, tables, code blocks)
2. Build hierarchical section tree
3. Identify atomic regions (complete tables/figures)
4. Create chunks respecting section boundaries
5. Target size: 2000 chars, max: 8000, overlap: 10%

**Chunk Enrichment:**
- `heading_context` — nearest parent heading
- `section_path` — full breadcrumb (e.g., "Section 1 > 1.1 > Definitions")
- `page_number` — from exact page offsets
- `content_types` — array: [table, code, heading, text]
- `is_atomic` — complete table/figure (never split)

## Search Pipeline

```
QUERY (natural language recommended — keyword lists produce poor embeddings)
  │
  ├──▶ Keyword List Detection (warns if keyword-stuffing detected)
  ├──▶ Query Classification (table? factual? concept?)
  ├──▶ Query Expansion (synonyms, related terms)
  │
  ├──▶ BM25 Search (FTS5, porter stemmer)
  │     └── Ranked by TF-IDF relevance
  │
  ├──▶ Semantic Search (nomic embedding → sqlite-vec cosine)
  │     └── Quality-weighted scoring
  │
  └──▶ Hybrid Fusion (Reciprocal Rank Fusion)
        │   score = Σ(weight / (k + rank))
        │   weights: equal 1.0/1.0 (auto_route disabled)
        │
        ├──▶ Result Enrichment (context chunks, provenance)
        ├──▶ De-duplication
        └──▶ Cross-Encoder Reranking (enabled by default, CPU fallback)
```

**Embedding Search Detail:**
- Query prefixed: `"search_query: " + query_text`
- Document chunks prefixed: `"search_document: [Section: path] [Heading: ctx] text`
- Cosine similarity: `1 - vec_distance_cosine(query, doc)`
- Quality multiplier applied based on OCR quality score

**Search Defaults (v1.2.62+):**
- `rerank=true` — cross-encoder reranking enabled by default
- `auto_route=false` — disabled; equal weight BM25+semantic fusion
- Natural language queries strongly recommended; keyword lists produce poor embeddings and trigger a guidance warning

## Document State Machine

```
                    ┌──────────────┐
                    │              │
  ┌─────────┐      │  processing  │      ┌──────────┐
  │ pending  │─────▶│              │─────▶│ complete  │
  └─────────┘      └──────┬───────┘      └──────────┘
       ▲                   │
       │                   │ (permanent error)
       │                   ▼
       │           ┌──────────────┐
       └───────────│   failed     │
     (retry_failed)└──────────────┘
```

**Transient errors** (stay pending): timeout, GPU OOM, model errors (OCR_MODEL_ERROR is always transient), insufficient balance — classified via centralized `isTransientError()` function
**Permanent errors** (mark failed): file not found, invalid format, parse errors

## Billing Integration

```
  ocr_ingest_files
       │
       ▼
  getLicenseGate().charge(fileHash, metadata)
       │
       ├──▶ Local: POST /v1/charge (license server, SQLite)
       │     └── Deducts from local balance, signs HMAC
       │
       ├──▶ Central: POST /v1/charge/authorize (Cloudflare Worker, D1)
       │     └── Deducts from D1 balance (source of truth)
       │
       ├── Success ──▶ gate.confirm(chargeId) ──▶ Process document
       │
       └── 402 ──▶ gate.refund(chargeId) ──▶ InsufficientBalanceError
                    (document stays 'pending', not 'failed')
```

**Cost:** 3 cents per file (server-side pricing, not hardcoded in client)

## HTTP File Upload Path

An alternative to host mount file access, the HTTP upload endpoint stages files for ingestion:

```
POST /api/upload (multipart/form-data)
  │
  ├──▶ busboy streaming parser
  ├──▶ Magic-byte format detection (reads first 16 bytes)
  │     ├── Validates file content matches declared extension
  │     ├── Detects actual format from magic bytes (PDF, DOCX/ZIP, PNG, JPEG, TIFF, GIF, BMP, WebP, EPUB)
  │     └── On mismatch: rejects with detected-vs-declared format info
  ├──▶ SHA-256 content hashing
  ├──▶ Duplicate detection (by hash)
  ├──▶ sanitizeFilename() (preserves extension, 255 char limit)
  ├──▶ Stage to /data/staged/{batch_id}/{filename}
  │     └── raw_original_name tracked for provenance
  └──▶ Return staged file paths for ocr_ingest_files

DELETE /api/upload/staged
  └──▶ Cleanup staged files

Constraints:
  - 10 GB total staging quota
  - 48-hour auto-expiry of old batches
  - Rate limited (upload category)
```

The wrapper's HTTP bridge can also intercept `ocr_ingest_files`/`ocr_ingest_directory` tool calls to automatically upload host files via this endpoint, bypassing Docker bind mount permission issues.

## Document Viewer API

REST endpoints for in-browser document viewing with server-side conversion:

```
GET /api/viewer/prepare/{document_id}?db={database_name}
  │
  ├──▶ Look up document in database (file_path, file_type)
  ├──▶ Check viewer cache (/data/viewer-cache/{document_id}/)
  ├──▶ If cached: return immediately with render info
  ├──▶ If not cached, convert based on file type:
  │     ├── PDF: copy to cache (native browser rendering)
  │     ├── Office (DOCX/PPTX/XLSX/XLS/CSV): LibreOffice → PDF
  │     │     └── Spreadsheets: pre-process with spreadsheet_prepare.py
  │     │         (landscape orientation, fit-to-width page layout)
  │     ├── TIFF/TIF: Pillow → PNG (browsers cannot render TIFF)
  │     ├── Images (PNG/JPG/GIF/WebP/BMP): copy to cache
  │     ├── Markdown: serve as text/markdown
  │     └── Text: serve as text/plain
  └──▶ Return: { ready, document_id, filename, render_as, content_type, size_bytes }

GET /api/viewer/file/{document_id}
  └──▶ Stream cached file with correct Content-Type
       └── Resets 24-hour cleanup timer on access

POST /api/viewer/close/{document_id}
  └──▶ Start 24-hour cleanup timer for cache entry
```

**Cache Management:**
- Cache directory: `/data/viewer-cache/{document_id}/`
- 24-hour auto-cleanup after last access or explicit close
- Startup reconciliation: cleans stale entries, sets timers for fresh ones
- Path traversal hardening on document IDs (UUID validation, basename-only)

## Multi-Session State

Multiple MCP sessions (e.g., concurrent AI agents) get independent state:

```
Session A ──▶ SessionManager ──▶ { currentDb: "legal", operations: 2 }
Session B ──▶ SessionManager ──▶ { currentDb: "research", operations: 0 }

Shared: ConnectionCache (ref-counted SQLite connection pool)
Isolated: database selection, operation counters, vector service cache
```

Each session is tracked via `Mcp-Session-Id` header. `AsyncLocalStorage` propagates session context through the call stack. Sessions are automatically expired after TTL.

**ConnectionCache Details:**
- Ref-counted shared connections: multiple sessions on the same database share one SQLite connection
- Connections opened on first acquire, closed when refCount reaches zero
- Safe because: Node.js single-threaded + better-sqlite3 synchronous + WAL concurrent reads
- Metrics tracking: open connections, acquires, releases, hits, misses
