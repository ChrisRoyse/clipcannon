# 02 — System Architecture

## Component Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  BROWSER (Dashboard — Next.js at port 3367)                              │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  DocumentTable (modified)                                          │  │
│  │  - onClick → opens DocumentViewerModal instead of expanding row    │  │
│  │  - passes: doc.id, doc.file_name, doc.file_type, dbName           │  │
│  └────────────────────┬───────────────────────────────────────────────┘  │
│                       │ opens                                            │
│  ┌────────────────────▼───────────────────────────────────────────────┐  │
│  │  DocumentViewerModal (NEW — full screen overlay)                    │  │
│  │  ┌─────────────────────────────────────────────────────────────┐   │  │
│  │  │  Tab Bar: [View] [Chunks] [Info]                             │   │  │
│  │  └─────────────────────────────────────────────────────────────┘   │  │
│  │                                                                    │  │
│  │  ┌─────────────┐ ┌───────────────┐ ┌───────────────────────────┐  │  │
│  │  │ ViewerTab    │ │ ChunksTab     │ │ InfoTab                   │  │  │
│  │  │             │ │               │ │                           │  │  │
│  │  │ PDF: iframe │ │ Paginated     │ │ Metadata grid             │  │  │
│  │  │ IMG: <img>  │ │ chunk list    │ │ Provenance chain          │  │  │
│  │  │ TXT: <pre>  │ │ with expand   │ │ Quality scores            │  │  │
│  │  │ Office: PDF │ │ and search    │ │ Processing timeline       │  │  │
│  │  └──────┬──────┘ └───────┬───────┘ └─────────────┬─────────────┘  │  │
│  │         │                │                       │                 │  │
│  └─────────┼────────────────┼───────────────────────┼─────────────────┘  │
│            │                │                       │                    │
└────────────┼────────────────┼───────────────────────┼────────────────────┘
             │                │                       │
    ┌────────▼────────┐  ┌───▼────────────┐  ┌──────▼─────────────────┐
    │ Dashboard API    │  │ Dashboard API   │  │ Dashboard API           │
    │ Route (proxy)    │  │ Route (proxy)   │  │ Route (proxy)           │
    │ GET /api/mcp/    │  │ GET /api/mcp/   │  │ GET /api/mcp/           │
    │ viewer/file/     │  │ databases/      │  │ databases/              │
    │ {doc_id}         │  │ {name}/chunks   │  │ {name}/document-detail  │
    └────────┬─────────┘  └───┬────────────┘  └──────┬─────────────────┘
             │                │                       │
    ┌────────▼────────────────▼───────────────────────▼─────────────────┐
    │ MCP Server (port 3366)                                            │
    │                                                                    │
    │ NEW ENDPOINTS:                                                     │
    │ ┌──────────────────────────────────────────────────────────────┐   │
    │ │ GET /api/viewer/prepare/{doc_id}                              │   │
    │ │  1. Query documents table for file_path                       │   │
    │ │  2. Check /data/viewer-cache/{doc_id}/ exists                 │   │
    │ │  3. If not: copy from /host/ or /data/staged/ to cache       │   │
    │ │  4. For Office files: convert to PDF via LibreOffice          │   │
    │ │  5. Return: { ready: true, content_type, filename, size }    │   │
    │ └──────────────────────────────────────────────────────────────┘   │
    │ ┌──────────────────────────────────────────────────────────────┐   │
    │ │ GET /api/viewer/file/{doc_id}                                 │   │
    │ │  1. Read from /data/viewer-cache/{doc_id}/                    │   │
    │ │  2. Stream file bytes with correct Content-Type               │   │
    │ │  3. Reset 24-hour cleanup timer                               │   │
    │ └──────────────────────────────────────────────────────────────┘   │
    │ ┌──────────────────────────────────────────────────────────────┐   │
    │ │ DELETE /api/viewer/file/{doc_id}                              │   │
    │ │  1. Delete cached file from /data/viewer-cache/{doc_id}/      │   │
    │ │  2. Cancel cleanup timer                                      │   │
    │ └──────────────────────────────────────────────────────────────┘   │
    │ ┌──────────────────────────────────────────────────────────────┐   │
    │ │ GET /api/databases/{name}/document-detail?document_id={id}    │   │
    │ │  1. Full document record from documents table                 │   │
    │ │  2. OCR result metadata                                       │   │
    │ │  3. Provenance chain (depth 0 + children summary)             │   │
    │ │  4. Image count, chunk count, embedding count                 │   │
    │ │  5. Processing timeline                                       │   │
    │ └──────────────────────────────────────────────────────────────┘   │
    │                                                                    │
    │ EXISTING ENDPOINTS (used as-is):                                   │
    │  GET /api/databases/{name}/chunks?document_id={id}                 │
    │  GET /api/databases/{name}/provenance-tree?document_id={id}        │
    │  GET /api/databases/{name}/quality-heatmap?document_id={id}        │
    │                                                                    │
    └────────────────────────────────────────────────────────────────────┘
```

## Data Flow: Opening a Document

```
Step 1: User clicks document row
  └─► DocumentTable.onClick(doc) → setViewerDoc(doc) → renders DocumentViewerModal

Step 2: DocumentViewerModal mounts
  └─► Calls POST /api/mcp/viewer/prepare/{doc.id}?db={dbName}
      └─► MCP server:
          a. SELECT file_path, file_name, file_type FROM documents WHERE id = ?
          b. Check if /data/viewer-cache/{doc.id}/{filename} exists
          c. If not exists:
             - Resolve host path: file_path → /host/{relative_path}
             - Verify file exists at resolved path
             - mkdir -p /data/viewer-cache/{doc.id}/
             - cp /host/{relative_path} /data/viewer-cache/{doc.id}/{filename}
             - For Office files (.docx,.doc,.pptx,.ppt,.xlsx,.xls):
               Run: libreoffice --headless --convert-to pdf --outdir /data/viewer-cache/{doc.id}/ <file>
          d. Return { ready: true, filename, content_type, size_bytes, render_as }

Step 3: Browser loads file
  └─► ViewerTab renders based on render_as:
      - "pdf" → <iframe src="/api/mcp/viewer/file/{doc.id}?db={dbName}" />
      - "image" → <img src="/api/mcp/viewer/file/{doc.id}?db={dbName}" />
      - "text" → fetch() content as text, render in <pre>
      - "markdown" → fetch() content as text, render as HTML

Step 4: User switches to Chunks tab
  └─► Calls GET /api/mcp/databases/{dbName}/chunks?document_id={doc.id}
      └─► Returns paginated chunks with text previews

Step 5: User switches to Info tab
  └─► Calls GET /api/mcp/databases/{dbName}/document-detail?document_id={doc.id}
      └─► Returns full document metadata + provenance summary

Step 6: User closes viewer (X or Escape)
  └─► Calls POST /api/mcp/viewer/close/{doc.id}
      └─► MCP server starts 24-hour cleanup timer for /data/viewer-cache/{doc.id}/
```

## Data Flow: 24-Hour Cleanup

```
Timer Start: POST /api/viewer/close/{doc.id}
  └─► Server stores in-memory Map: viewerCleanupTimers.set(doc.id, setTimeout(..., 24*60*60*1000))

Timer Reset: GET /api/viewer/file/{doc.id} (any access resets the timer)
  └─► clearTimeout(viewerCleanupTimers.get(doc.id))
  └─► viewerCleanupTimers.set(doc.id, setTimeout(..., 24*60*60*1000))

Timer Fire: After 24 hours of no access
  └─► rm -rf /data/viewer-cache/{doc.id}/
  └─► viewerCleanupTimers.delete(doc.id)

Server Restart: On MCP server startup
  └─► Scan /data/viewer-cache/*/
  └─► For each directory, check mtime of files
  └─► If oldest file mtime > 24 hours ago: delete directory
  └─► If within 24 hours: set new timer for remaining time
```

## File Path Resolution

The `documents.file_path` column stores the original path as seen by the ingestion tool. This path could be:

1. **Host path via `/host` mount**: `/host/Documents/contracts/agreement.pdf`
   - The wrapper mounts `$HOME → /host:ro`
   - `file_path` was set during ingestion as `/host/...`

2. **Staged upload path**: `/data/staged/{batch_id}/{filename}`
   - File was uploaded via POST /api/upload
   - Still exists in `/data/staged/` (unless auto-expired after 48h)

3. **Windows path via WSL**: `/host-windows/c/Users/.../document.pdf`
   - Mounted by wrapper for Windows file access

4. **Direct container path**: `/data/bundled/{filename}`
   - For demo/bundled data shipped with the Docker image

**Resolution algorithm** (in order):
```
1. Try file_path directly (it may be an absolute container path)
2. If file_path starts with /host or /host-windows: try as-is (host mount)
3. If file_path does NOT start with / (relative): prepend /host/
4. If not found at any path: return error with details
```

## Database Impact

### New directory
- `/data/viewer-cache/` — created on first viewer prepare request
- Structure: `/data/viewer-cache/{document_id}/{filename}`

### No schema changes
- No new database tables
- No migration needed
- Uses existing `documents.file_path`, `documents.file_name`, `documents.file_type`

### Existing endpoints used
- `GET /api/databases/{name}/chunks?document_id={id}` — already exists, already supports document_id filter
- `GET /api/databases/{name}/provenance-tree?document_id={id}` — already exists
- `GET /api/databases/{name}/quality-heatmap?document_id={id}` — already exists
