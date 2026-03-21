# Database Schema & Data Model

## Overview

The system uses SQLite with three extensions:
- **sqlite-vec** — HNSW vector index for 768-dim cosine similarity search
- **FTS5** — Full-text search with porter stemming
- **WAL mode** — Write-Ahead Logging for concurrent read/write

Current schema version: **33** (forward-only migrations with pre-backup safety)

> Schema version unchanged since v1.2.26. All recent features (viewer, multi-session, upload) operate at the HTTP/REST layer without schema changes.

## Database Types

| Database | Location | Purpose |
|----------|----------|---------|
| User databases | `/data/{name}.db` | Document storage, search, provenance |
| Registry | `/data/_databases.db` | Tracks all databases, tags, workspaces |
| License server | `/data/_license_server.db` | Billing, charges, payments, users |
| License cache | `/data/_license.db` | Pending charges, cached balance |

Internal databases (prefixed with `_`) are hidden from user-facing tools.

## Connection Pragmas

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;        -- 64 MB
PRAGMA wal_autocheckpoint = 1000;
PRAGMA mmap_size = 268435456;      -- 256 MB
PRAGMA busy_timeout = 30000;       -- 30 seconds
```

---

## Core Tables (Provenance Hierarchy)

### documents (Depth 0 — Root)

```
documents
├── id TEXT PRIMARY KEY (UUID)
├── file_path TEXT NOT NULL
├── file_name TEXT NOT NULL
├── file_hash TEXT NOT NULL (SHA-256)
├── file_size INTEGER
├── file_type TEXT
├── status TEXT (pending|processing|complete|failed)
├── error_message TEXT
├── page_count INTEGER
├── provenance_id TEXT UNIQUE → provenance(id)
├── datalab_file_id TEXT
├── doc_title TEXT
├── doc_author TEXT
├── doc_subject TEXT
├── created_at TEXT
├── modified_at TEXT
└── ocr_completed_at TEXT
```

### ocr_results (Depth 1)

```
ocr_results
├── id TEXT PRIMARY KEY (UUID)
├── document_id TEXT NOT NULL → documents(id)
├── extracted_text TEXT NOT NULL
├── text_length INTEGER
├── page_count INTEGER
├── parse_quality_score REAL
├── datalab_request_id TEXT
├── datalab_mode TEXT (fast|balanced|accurate)
├── json_blocks TEXT (JSON array of block-level data)
├── extras_json TEXT (charts, links, tracked_changes)
├── cost_cents INTEGER
├── provenance_id TEXT → provenance(id)
├── processing_started_at TEXT
├── processing_completed_at TEXT
└── processing_duration_ms INTEGER
```

### chunks (Depth 2)

```
chunks
├── id TEXT PRIMARY KEY (UUID)
├── document_id TEXT NOT NULL → documents(id)
├── ocr_result_id TEXT → ocr_results(id)
├── chunk_index INTEGER NOT NULL
├── text TEXT NOT NULL (CHECK: length > 0)
├── text_hash TEXT NOT NULL (SHA-256)
├── character_start INTEGER
├── character_end INTEGER
├── page_number INTEGER
├── page_range TEXT
├── overlap_previous INTEGER
├── overlap_next INTEGER
├── heading_context TEXT
├── heading_level INTEGER
├── section_path TEXT
├── content_types TEXT (JSON array: code, table, image, equation)
├── is_atomic INTEGER (0|1, complete table/figure)
├── embedding_status TEXT (pending|complete|failed)
├── embedded_at TEXT
├── ocr_quality_score REAL
├── provenance_id TEXT → provenance(id)
└── created_at TEXT
```

### images (Depth 2)

```
images
├── id TEXT PRIMARY KEY (UUID)
├── document_id TEXT NOT NULL → documents(id)
├── ocr_result_id TEXT → ocr_results(id)
├── image_index INTEGER
├── page_number INTEGER
├── extracted_path TEXT (filesystem reference)
├── format TEXT (png|jpg|...)
├── width INTEGER, height INTEGER
├── file_size INTEGER
├── bbox_x REAL, bbox_y REAL, bbox_width REAL, bbox_height REAL
├── page_width REAL, page_height REAL
├── context_text TEXT (surrounding OCR text)
├── block_type TEXT
├── is_header_footer INTEGER (0|1)
├── vlm_status TEXT (pending|processing|complete|failed)
├── vlm_description TEXT
├── vlm_structured_data TEXT (JSON)
├── vlm_embedding_id TEXT → embeddings(id)
├── vlm_model TEXT
├── vlm_confidence REAL (0-1)
├── vlm_processed_at TEXT
├── vlm_tokens_used INTEGER
├── error_message TEXT
├── provenance_id TEXT → provenance(id)
└── created_at TEXT
```

### embeddings (Depth 3/4)

```
embeddings
├── id TEXT PRIMARY KEY (UUID)
├── chunk_id TEXT → chunks(id)         ┐
├── image_id TEXT → images(id)         ├── mutually exclusive
├── extraction_id TEXT → extractions(id)┘
├── document_id TEXT NOT NULL → documents(id)
├── original_text TEXT NOT NULL  ← ALWAYS included (CP-002)
├── source_file_path TEXT
├── source_file_name TEXT
├── source_file_hash TEXT
├── page_number INTEGER
├── page_range TEXT
├── character_start INTEGER
├── character_end INTEGER
├── chunk_index INTEGER
├── total_chunks INTEGER
├── model_name TEXT (nomic-embed-text-v1.5)
├── model_version TEXT
├── task_type TEXT (search_document|search_query)
├── inference_mode TEXT (local)
├── gpu_device TEXT
├── content_hash TEXT (SHA-256)
├── generation_duration_ms INTEGER
├── provenance_id TEXT → provenance(id)
└── created_at TEXT
```

### provenance (Meta — All Depths)

```
provenance
├── id TEXT PRIMARY KEY (UUID)
├── type TEXT NOT NULL (DOCUMENT|OCR_RESULT|CHUNK|IMAGE|VLM_DESCRIPTION|EMBEDDING|EXTRACTION|...)
├── source_type TEXT (FILE|OCR|CHUNKING|IMAGE_EXTRACTION|VLM|EMBEDDING|...)
├── source_id TEXT
├── source_path TEXT
├── parent_id TEXT → provenance(id)
├── parent_ids TEXT (serialized array)
├── root_document_id TEXT
├── chain_depth INTEGER
├── chain_path TEXT
├── chain_hash TEXT (SHA-256 chain integrity)
├── content_hash TEXT (SHA-256)
├── input_hash TEXT
├── file_hash TEXT
├── processor TEXT
├── processor_version TEXT
├── processing_params TEXT (JSON)
├── processing_duration_ms INTEGER
├── processing_quality_score REAL
├── location TEXT (JSON: page_number, character_start/end, bounding_box)
├── source_file_created_at TEXT
├── source_file_modified_at TEXT
├── user_id TEXT
├── agent_id TEXT
├── agent_metadata_json TEXT
├── created_at TEXT
└── processed_at TEXT
```

---

## Vector Search Table

```sql
CREATE VIRTUAL TABLE vec_embeddings USING vec0(
  embedding_id TEXT PRIMARY KEY,
  vector FLOAT[768]
);
```

- **768-dimensional** float32 vectors (nomic-embed-text-v1.5)
- **Cosine similarity**: `1 - vec_distance_cosine(v.vector, ?)`
- Joined with `embeddings` table for metadata enrichment
- Supports document filters, chunk filters, page range filters

---

## Full-Text Search Tables

| FTS5 Index | Source Table | Columns | Purpose |
|-----------|-------------|---------|---------|
| `chunks_fts` | chunks | text | Keyword search on chunk text |
| `vlm_fts` | embeddings (WHERE image_id NOT NULL) | original_text | VLM description search |
| `documents_fts` | documents | doc_title, doc_author, doc_subject | Document metadata search |
| `extractions_fts` | extractions | extraction_json | Structured data search |
| `databases_fts` | registry databases | name, description | Cross-database search |

All use external content mode (no duplication) with INSERT/DELETE/UPDATE triggers.

---

## Governance Tables

### annotations
- Types: comment, correction, question, highlight, flag, approval
- Status: open, resolved, dismissed
- Threading via `parent_id`

### document_locks
- Types: exclusive, shared
- Expiration-based with reason field

### workflow_states
- States: draft → submitted → in_review → changes_requested → approved/rejected → executed → archived
- Assignment tracking: assigned_to, assigned_by, due_date

### approval_chains / approval_steps
- Template chains with ordered steps
- Per-document step progress tracking

### audit_log
- Action tracking with user, session, IP, entity details

---

## Contract Management Tables

### obligations
- Types: payment, delivery, notification, renewal, termination, compliance, reporting, approval
- Status: active, fulfilled, overdue, waived, expired
- Source: chunk reference, page, confidence score

### playbooks
- Preferred contract terms as reusable templates
- JSON clause definitions

---

## Other Tables

| Table | Purpose |
|-------|---------|
| `extractions` | Structured data extracted from pages (JSON schema → JSON result) |
| `form_fills` | Form field processing results |
| `comparisons` | Document diff results (similarity_ratio, text_diff, structural_diff) |
| `clusters` | Document grouping (HDBSCAN/agglomerative/k-means) |
| `document_clusters` | Many-to-many cluster assignment with similarity scores |
| `tags` / `entity_tags` | User-defined tagging system |
| `users` | Identity with roles (viewer/reviewer/editor/admin) |
| `saved_searches` | Persisted queries with alert capability |
| `webhooks` | Outbound event notification URLs |
| `schema_version` | Migration tracking |
| `database_metadata` | Per-database counts and version |
| `fts_index_metadata` | FTS5 index health tracking |

---

## Registry Database Schema

```
_databases.db
├── databases (name PK, description, file_path, counts, timestamps)
├── database_tags (name, tag — composite PK)
├── database_metadata_kv (name, key — composite PK)
├── workspaces (name PK, description)
├── workspace_members (workspace_name, database_name)
├── access_log (database_name, action, accessed_at)
└── databases_fts (FTS5 for search)
```

---

## License Server Database Schema

```
_license_server.db
├── users (id, email, real_email, stripe_customer_id)
├── license_keys (id, user_id, key_hash, balance_cents, balance_hmac, tier, status)
├── sessions (token, user_id, expires_at)
├── charges (id, license_key_id, amount_cents, status, document_hash)
├── payments (id, user_id, amount_cents, stripe_payment_intent_id)
└── (indexes on key_hash, user_id, status)
```

---

## Index Summary

50+ B-tree indexes covering:
- Foreign keys (document_id, chunk_id, etc.)
- Search optimization (section_path, heading_level, content_types)
- Temporal queries (created_at DESC)
- Unique constraints (provenance_id, key_hash)
- Status filtering (embedding_status, vlm_status)
