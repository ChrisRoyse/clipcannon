# 03 — MCP Server Changes (bin-http.ts)

## Overview

Four new REST API endpoints are added to `src/bin-http.ts`. Zero new MCP tools. Zero schema changes.

All endpoints follow the existing pattern in bin-http.ts: raw `req`/`res` handling inside the `if (req.method === 'GET' && req.url?.startsWith('/api/'))` block.

## New Endpoints

### 3.1 GET /api/viewer/prepare/{document_id}?db={database_name}

**Purpose**: Ensure a document file is cached and ready for viewing. Copies from host mount if needed. Converts Office files to PDF.

**Location in bin-http.ts**: Add BEFORE the existing `if (pathname === '/api/overview')` block, inside the GET /api/ handler.

**Request**:
```
GET /api/viewer/prepare/{document_id}?db=AlexHormoziTranscripts
```

**Response (success)**:
```json
{
  "ready": true,
  "document_id": "abc-123",
  "filename": "contract.pdf",
  "original_filename": "contract.pdf",
  "render_as": "pdf",
  "content_type": "application/pdf",
  "size_bytes": 2457600,
  "cached_at": "2026-03-19T21:30:00.000Z",
  "source_path": "/host/Documents/contract.pdf"
}
```

**Response (file not found)**:
```json
{
  "ready": false,
  "error": "FILE_NOT_FOUND",
  "message": "Source file not found at any resolved path",
  "document_id": "abc-123",
  "original_file_path": "/host/Documents/old-file.pdf",
  "paths_tried": [
    "/host/Documents/old-file.pdf",
    "/data/staged/batch-xyz/old-file.pdf"
  ]
}
```

**Implementation pseudocode**:
```typescript
const viewerPrepareMatch = pathname.match(/^\/api\/viewer\/prepare\/([^/]+)$/);
if (viewerPrepareMatch) {
  const documentId = decodeURIComponent(viewerPrepareMatch[1]);
  const dbName = parsedUrl.searchParams.get('db');
  if (!dbName) {
    res.writeHead(400, JSON_CT);
    res.end(JSON.stringify({ error: 'Missing required query parameter: db' }));
    return;
  }

  const verified = openVerifiedOcrDb(dbName);
  if (!verified) return; // 404/422 already sent
  const conn = verified.conn;

  try {
    // 1. Get document record
    const doc = conn.prepare(
      'SELECT id, file_path, file_name, file_type FROM documents WHERE id = ?'
    ).get(documentId) as { id: string; file_path: string; file_name: string; file_type: string } | undefined;

    if (!doc) {
      res.writeHead(404, JSON_CT);
      res.end(JSON.stringify({ error: `Document '${documentId}' not found` }));
      return;
    }

    // 2. Determine render_as and content_type
    const { renderAs, contentType } = getViewerRenderInfo(doc.file_type);

    // 3. Check cache
    const cacheDir = path.join(VIEWER_CACHE_DIR, documentId);
    const viewerFilename = renderAs === 'pdf' && isOfficeType(doc.file_type)
      ? doc.file_name.replace(/\.[^.]+$/, '.pdf')
      : doc.file_name;
    const cachedPath = path.join(cacheDir, viewerFilename);

    if (fs.existsSync(cachedPath)) {
      const stat = fs.statSync(cachedPath);
      resetCleanupTimer(documentId);
      res.writeHead(200, JSON_CT);
      res.end(JSON.stringify({
        ready: true,
        document_id: documentId,
        filename: viewerFilename,
        original_filename: doc.file_name,
        render_as: renderAs,
        content_type: contentType,
        size_bytes: stat.size,
        cached_at: stat.mtime.toISOString(),
        source_path: doc.file_path,
      }));
      return;
    }

    // 4. Resolve source file path
    const resolvedPath = resolveDocumentPath(doc.file_path);
    if (!resolvedPath) {
      res.writeHead(404, JSON_CT);
      res.end(JSON.stringify({
        ready: false,
        error: 'FILE_NOT_FOUND',
        message: 'Source file not found at any resolved path',
        document_id: documentId,
        original_file_path: doc.file_path,
        paths_tried: getPathCandidates(doc.file_path),
      }));
      return;
    }

    // 5. Copy to cache
    fs.mkdirSync(cacheDir, { recursive: true });
    const srcPath = resolvedPath;
    const destPath = path.join(cacheDir, doc.file_name);
    fs.copyFileSync(srcPath, destPath);

    // 6. Convert Office to PDF if needed
    let finalPath = destPath;
    if (isOfficeType(doc.file_type)) {
      finalPath = await convertToPdf(destPath, cacheDir);
      // Delete original Office file after conversion
      if (finalPath !== destPath) {
        fs.unlinkSync(destPath);
      }
    }

    const stat = fs.statSync(finalPath);
    startCleanupTimer(documentId);

    res.writeHead(200, JSON_CT);
    res.end(JSON.stringify({
      ready: true,
      document_id: documentId,
      filename: path.basename(finalPath),
      original_filename: doc.file_name,
      render_as: renderAs,
      content_type: contentType,
      size_bytes: stat.size,
      cached_at: stat.mtime.toISOString(),
      source_path: doc.file_path,
    }));
  } finally {
    conn.close();
  }
}
```

### 3.2 GET /api/viewer/file/{document_id}?db={database_name}

**Purpose**: Stream the cached file bytes to the browser with the correct Content-Type.

**Request**:
```
GET /api/viewer/file/abc-123?db=AlexHormoziTranscripts
```

**Response**: Raw file bytes with appropriate headers:
```
Content-Type: application/pdf
Content-Length: 2457600
Content-Disposition: inline; filename="contract.pdf"
Cache-Control: private, max-age=3600
```

**Implementation pseudocode**:
```typescript
const viewerFileMatch = pathname.match(/^\/api\/viewer\/file\/([^/]+)$/);
if (viewerFileMatch) {
  const documentId = decodeURIComponent(viewerFileMatch[1]);
  const cacheDir = path.join(VIEWER_CACHE_DIR, documentId);

  if (!fs.existsSync(cacheDir)) {
    res.writeHead(404, JSON_CT);
    res.end(JSON.stringify({
      error: 'NOT_CACHED',
      message: `No cached file for document ${documentId}. Call /api/viewer/prepare/ first.`,
    }));
    return;
  }

  // Find the file in the cache directory (there should be exactly one)
  const files = fs.readdirSync(cacheDir);
  if (files.length === 0) {
    res.writeHead(404, JSON_CT);
    res.end(JSON.stringify({ error: 'CACHE_EMPTY', message: 'Cache directory exists but is empty' }));
    return;
  }

  const filename = files[0];
  const filePath = path.join(cacheDir, filename);
  const stat = fs.statSync(filePath);
  const ext = path.extname(filename).toLowerCase();
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  // Reset 24-hour cleanup timer on every access
  resetCleanupTimer(documentId);

  res.writeHead(200, {
    'Content-Type': contentType,
    'Content-Length': String(stat.size),
    'Content-Disposition': `inline; filename="${encodeURIComponent(filename)}"`,
    'Cache-Control': 'private, max-age=3600',
  });

  // Stream the file
  const stream = fs.createReadStream(filePath);
  stream.pipe(res);
  stream.on('error', (err) => {
    console.error(`[viewer] Stream error for ${documentId}: ${err.message}`);
    if (!res.headersSent) {
      res.writeHead(500, JSON_CT);
      res.end(JSON.stringify({ error: 'STREAM_ERROR', message: err.message }));
    }
  });
  return; // Important: don't fall through to other handlers
}
```

### 3.3 POST /api/viewer/close/{document_id}

**Purpose**: Signal that the viewer has been closed. Starts the 24-hour cleanup timer.

**Request**:
```
POST /api/viewer/close/abc-123
```

**Response**:
```json
{
  "document_id": "abc-123",
  "cleanup_scheduled": true,
  "cleanup_at": "2026-03-20T21:30:00.000Z"
}
```

**Implementation**: Must be added in a new `if (req.method === 'POST')` block, similar to how the upload handler works. Placed after the upload handlers.

### 3.4 GET /api/databases/{name}/document-detail?document_id={id}

**Purpose**: Return full document metadata, OCR results, and provenance summary for the Info tab.

**Response**:
```json
{
  "document": {
    "id": "abc-123",
    "file_name": "contract.pdf",
    "file_path": "/host/Documents/contract.pdf",
    "file_type": "pdf",
    "file_hash": "sha256:abcdef...",
    "file_size": 2457600,
    "status": "complete",
    "page_count": 184,
    "doc_title": null,
    "doc_author": null,
    "doc_subject": null,
    "created_at": "2026-03-17T18:06:39.000Z",
    "modified_at": null,
    "ocr_completed_at": "2026-03-17T18:08:15.000Z"
  },
  "ocr_result": {
    "id": "ocr-456",
    "text_length": 450000,
    "page_count": 184,
    "parse_quality_score": 5.0,
    "processing_duration_ms": 95000,
    "processing_started_at": "2026-03-17T18:06:42.000Z",
    "processing_completed_at": "2026-03-17T18:08:15.000Z"
  },
  "counts": {
    "chunks": 225,
    "embeddings": 225,
    "images": 42,
    "vlm_complete": 38,
    "vlm_pending": 4
  },
  "provenance": {
    "root_id": "prov-root",
    "chain_depth": 4,
    "total_records": 493,
    "verified": true
  }
}
```

**SQL queries**:
```sql
-- Document record
SELECT * FROM documents WHERE id = ?

-- OCR result
SELECT id, text_length, page_count, parse_quality_score,
       processing_duration_ms, processing_started_at, processing_completed_at
FROM ocr_results WHERE document_id = ?

-- Counts
SELECT
  (SELECT COUNT(*) FROM chunks WHERE document_id = ?) as chunk_count,
  (SELECT COUNT(*) FROM embeddings WHERE document_id = ?) as embedding_count,
  (SELECT COUNT(*) FROM images WHERE document_id = ?) as image_count,
  (SELECT COUNT(*) FROM images WHERE document_id = ? AND vlm_status = 'complete') as vlm_complete,
  (SELECT COUNT(*) FROM images WHERE document_id = ? AND vlm_status = 'pending') as vlm_pending

-- Provenance summary
SELECT id, chain_depth FROM provenance
WHERE root_document_id = ? ORDER BY chain_depth DESC LIMIT 1

SELECT COUNT(*) as total FROM provenance WHERE root_document_id = ?
```

## Helper Functions (new, added to bin-http.ts)

### VIEWER_CACHE_DIR constant
```typescript
const VIEWER_CACHE_DIR = path.join(
  process.env.OCR_PROVENANCE_DATABASES_PATH ?? '/data',
  'viewer-cache'
);
```

### MIME_TYPES map
```typescript
const MIME_TYPES: Record<string, string> = {
  '.pdf': 'application/pdf',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.bmp': 'image/bmp',
  '.tiff': 'image/tiff',
  '.tif': 'image/tiff',
  '.txt': 'text/plain; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.docx': 'application/pdf', // converted
  '.doc': 'application/pdf',
  '.pptx': 'application/pdf',
  '.ppt': 'application/pdf',
  '.xlsx': 'application/pdf',
  '.xls': 'application/pdf',
};
```

### getViewerRenderInfo(fileType)
```typescript
function getViewerRenderInfo(fileType: string): { renderAs: string; contentType: string } {
  const ft = fileType.toLowerCase().replace(/^\./, '');
  if (ft === 'pdf') return { renderAs: 'pdf', contentType: 'application/pdf' };
  if (['docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls'].includes(ft))
    return { renderAs: 'pdf', contentType: 'application/pdf' };
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif'].includes(ft))
    return { renderAs: 'image', contentType: MIME_TYPES[`.${ft}`] || 'image/png' };
  if (ft === 'md') return { renderAs: 'markdown', contentType: 'text/markdown; charset=utf-8' };
  if (['txt', 'csv'].includes(ft)) return { renderAs: 'text', contentType: 'text/plain; charset=utf-8' };
  throw new Error(`Unsupported file type for viewer: ${ft}`);
}
```

### isOfficeType(fileType)
```typescript
function isOfficeType(fileType: string): boolean {
  return ['docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls'].includes(
    fileType.toLowerCase().replace(/^\./, '')
  );
}
```

### resolveDocumentPath(filePath)
```typescript
function resolveDocumentPath(filePath: string): string | null {
  // Try each candidate path in order
  for (const candidate of getPathCandidates(filePath)) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}
```

### getPathCandidates(filePath)
```typescript
function getPathCandidates(filePath: string): string[] {
  const candidates: string[] = [];

  // 1. Direct path (as stored in database)
  candidates.push(filePath);

  // 2. If path includes /host/ prefix, try as-is (already resolved)
  if (filePath.startsWith('/host/') || filePath.startsWith('/host-windows/')) {
    // Already tried above
  } else if (filePath.startsWith('/data/')) {
    // Container internal path — already tried
  } else if (filePath.startsWith('/')) {
    // Absolute host path → prepend /host
    // E.g., /home/user/Documents/file.pdf → /host/Documents/file.pdf
    const hostHome = process.env.OCR_PROVENANCE_HOST_HOME;
    if (hostHome) {
      const relative = filePath.startsWith(hostHome)
        ? filePath.slice(hostHome.length)
        : filePath;
      candidates.push(`/host${relative}`);
    }
    candidates.push(`/host${filePath}`);
  } else {
    // Relative path → try under /host/
    candidates.push(`/host/${filePath}`);
  }

  // 3. Check staged uploads
  const stagedBase = path.join(
    process.env.OCR_PROVENANCE_DATABASES_PATH ?? '/data',
    'staged'
  );
  if (fs.existsSync(stagedBase)) {
    const fileName = path.basename(filePath);
    // Search staged directories for the file
    try {
      const batches = fs.readdirSync(stagedBase);
      for (const batch of batches) {
        const stagedPath = path.join(stagedBase, batch, fileName);
        candidates.push(stagedPath);
      }
    } catch { /* staged dir scan failed, skip */ }
  }

  return candidates;
}
```

### convertToPdf(filePath, outDir) — Office to PDF conversion
```typescript
async function convertToPdf(filePath: string, outDir: string): Promise<string> {
  const { execSync } = require('child_process');
  const basename = path.basename(filePath, path.extname(filePath));
  const expectedOutput = path.join(outDir, `${basename}.pdf`);

  try {
    execSync(
      `libreoffice --headless --norestore --convert-to pdf --outdir "${outDir}" "${filePath}"`,
      { timeout: 120_000, stdio: 'pipe' }
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Office-to-PDF conversion failed for ${path.basename(filePath)}: ${msg}. ` +
      `Ensure LibreOffice is installed in the Docker image.`
    );
  }

  if (!fs.existsSync(expectedOutput)) {
    throw new Error(
      `Office-to-PDF conversion produced no output. Expected: ${expectedOutput}`
    );
  }

  return expectedOutput;
}
```

### Cleanup timer management
```typescript
const viewerCleanupTimers = new Map<string, ReturnType<typeof setTimeout>>();
const CLEANUP_DELAY_MS = 24 * 60 * 60 * 1000; // 24 hours

function startCleanupTimer(documentId: string): void {
  clearCleanupTimer(documentId);
  const timer = setTimeout(() => {
    const cacheDir = path.join(VIEWER_CACHE_DIR, documentId);
    try {
      if (fs.existsSync(cacheDir)) {
        fs.rmSync(cacheDir, { recursive: true, force: true });
        console.error(`[viewer] Cleaned up cache for document ${documentId}`);
      }
    } catch (err) {
      console.error(`[viewer] Cleanup failed for ${documentId}: ${err instanceof Error ? err.message : err}`);
    }
    viewerCleanupTimers.delete(documentId);
  }, CLEANUP_DELAY_MS);
  viewerCleanupTimers.set(documentId, timer);
}

function resetCleanupTimer(documentId: string): void {
  if (viewerCleanupTimers.has(documentId)) {
    startCleanupTimer(documentId); // restart the 24h timer
  }
}

function clearCleanupTimer(documentId: string): void {
  const existing = viewerCleanupTimers.get(documentId);
  if (existing) {
    clearTimeout(existing);
    viewerCleanupTimers.delete(documentId);
  }
}
```

### Startup cleanup (added to server initialization)
```typescript
function cleanupStaleViewerCache(): void {
  if (!fs.existsSync(VIEWER_CACHE_DIR)) return;
  const now = Date.now();
  try {
    const entries = fs.readdirSync(VIEWER_CACHE_DIR, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const dirPath = path.join(VIEWER_CACHE_DIR, entry.name);
      const files = fs.readdirSync(dirPath);
      if (files.length === 0) {
        fs.rmdirSync(dirPath);
        continue;
      }
      // Check newest file mtime
      let newest = 0;
      for (const f of files) {
        const st = fs.statSync(path.join(dirPath, f));
        if (st.mtimeMs > newest) newest = st.mtimeMs;
      }
      const ageMs = now - newest;
      if (ageMs > CLEANUP_DELAY_MS) {
        fs.rmSync(dirPath, { recursive: true, force: true });
        console.error(`[viewer] Startup cleanup: removed stale cache ${entry.name}`);
      } else {
        // Set timer for remaining time
        const remainingMs = CLEANUP_DELAY_MS - ageMs;
        startCleanupTimer(entry.name);
        console.error(`[viewer] Startup: timer set for ${entry.name} (${Math.round(remainingMs / 60000)}min remaining)`);
      }
    }
  } catch (err) {
    console.error(`[viewer] Startup cleanup error: ${err instanceof Error ? err.message : err}`);
  }
}
```

## LibreOffice Dependency

For Office file conversion, LibreOffice must be installed in the Docker container.

**Dockerfile change** (in the runtime stage):
```dockerfile
# Install LibreOffice for document viewer Office-to-PDF conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer libreoffice-calc libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*
```

This adds ~150MB to the image. Only the writer/calc/impress components are needed (no GUI, no Java).

## Auth Exemption

The viewer endpoints MUST NOT be exempt from license key auth. They follow the same auth pattern as all other `/api/` endpoints.

## Summary of Changes to bin-http.ts

1. Add `VIEWER_CACHE_DIR`, `MIME_TYPES`, helper functions at module scope
2. Add `cleanupStaleViewerCache()` call after server starts listening
3. Add viewer prepare/file/close handlers in the request routing section
4. Add document-detail handler alongside existing database-scoped endpoints
