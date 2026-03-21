# Database Sharing

## Overview

Four sharing tools enable database transfer between users and systems. Implemented in `src/tools/sharing.ts`. Uses the `/export` mount (mapped to `~/ocr-provenance-exports` on host via `OCR_PROVENANCE_SHARE_DIR` env var).

## Tools

| Tool | Purpose |
|------|---------|
| `ocr_db_share` | Export database to the shared folder (`/export`) with host-side path output |
| `ocr_db_import_shared` | List available bundles in the shared folder and import one |
| `ocr_db_transfer` | Package a database into a transfer bundle (`.db` + `manifest.json`) at a specified path |
| `ocr_db_receive` | Import a transfer bundle from a path, register in the registry with metadata |

## Transfer Bundle Format

A transfer bundle is a directory containing:

```json
// manifest.json
{
  "version": 1,
  "database_name": "legal-contracts-2024",
  "created_at": "2026-03-16T20:00:00.000Z",
  "document_count": 250,
  "chunk_count": 5400,
  "embedding_count": 5400,
  "size_bytes": 47185920,
  "tags": ["legal", "contracts"],
  "metadata": { "author": "Chris Royse", "project": "Q1 Review" },
  "description": "Legal contracts processed with OCR Provenance MCP"
}
```

Plus the `.db` SQLite file.

## User Workflow

**Exporting (sender):**
```
ocr_db_share { database_name: "legal-contracts-2024" }
→ "Bundle created at ~/ocr-provenance-exports/legal-contracts-2024-bundle/
   Contains: legal-contracts-2024.db (45 MB), manifest.json
   Share this folder with others. They can import it with ocr_db_import_shared."
```

**Importing (receiver):**
1. Place received bundle in `~/ocr-provenance-exports/`
2. Import:
```
ocr_db_import_shared { bundle_name: "legal-contracts-2024-bundle" }
→ "Imported 'legal-contracts-2024': 250 documents, 5,400 chunks, 5,400 embeddings.
   All provenance records preserved. Ready to search."
```

**Listing available bundles:**
```
ocr_db_import_shared { list: true }
→ "Available bundles in shared folder:
   1. legal-contracts-2024-bundle/ — 250 docs, 45 MB
   2. research-papers-bundle/ — 50 docs, 12 MB"
```

## Tool Schemas

```typescript
const DbShareInput = z.object({
  database_name: z.string().min(1).optional()
    .describe('Database to share (uses current if not specified)'),
});

const DbImportSharedInput = z.object({
  bundle_name: z.string().min(1).optional()
    .describe('Name of the bundle directory in the shared folder to import'),
  new_name: z.string().min(1).max(64).regex(/^[a-zA-Z0-9_-]+$/).optional()
    .describe('Override the database name during import'),
  list: z.boolean().default(false)
    .describe('List available bundles instead of importing'),
  auto_select: z.boolean().default(false)
    .describe('Select the imported database after import'),
});
```

## Edge Cases

- **Name collision**: If a database with the same name exists, returns an error suggesting `new_name`
- **Bare `.db` file without manifest**: Supported — name derived from filename, counts queried from the database
- **Corrupted database**: `ocr_db_receive` runs `PRAGMA integrity_check` before importing
- **Empty shared folder**: Returns a clear message directing the user to place bundles in `~/ocr-provenance-exports/`
- **Schema version mismatch**: Warns but allows import (read-only context — migration is the sender's responsibility)

## Infrastructure

No Docker or wrapper changes are required. The `/export` mount exists in all installations, and `OCR_PROVENANCE_ALLOWED_DIRS` includes `/export` when the wrapper sets it up.
