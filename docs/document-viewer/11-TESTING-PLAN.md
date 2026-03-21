# 11 — Testing Plan

## Principles

1. **Real data only** — No mocks, no stubs, no fake databases
2. **Real files** — Tests use actual files from the filesystem
3. **Real database queries** — Tests query real SQLite databases
4. **Verify outputs exist** — Check filesystem, database, HTTP responses
5. **Edge cases tested** — Missing files, corrupted paths, empty databases
6. **Fail when broken** — Tests must fail if the feature is broken

## Test Categories

### 11.1 MCP Server API Tests (TypeScript, Vitest)

**Location**: `tests/unit/viewer-api.test.ts`

**Setup**: Create a temporary database with real document records, create temporary files.

```typescript
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';

// Helper: create a temp database with a document record
function createTestDb(tempDir: string): { db: Database.Database; dbPath: string } {
  const dbPath = path.join(tempDir, 'test-viewer.db');
  const db = new Database(dbPath);
  // Run schema migration (use the real migration code)
  // Insert a real document record
  return { db, dbPath };
}
```

#### Test Cases

**Test 1: Prepare endpoint — file exists and gets cached**
```
Given: A document record with file_path pointing to a real file
When: GET /api/viewer/prepare/{doc_id}?db=test-viewer
Then:
  - Response status 200
  - Response body has ready=true
  - Response body has render_as matching file type
  - File exists at /data/viewer-cache/{doc_id}/{filename}
  - Verify: fs.existsSync(cachedPath) === true
```

**Test 2: Prepare endpoint — file not found**
```
Given: A document record with file_path pointing to a non-existent file
When: GET /api/viewer/prepare/{doc_id}?db=test-viewer
Then:
  - Response status 404
  - Response body has ready=false, error='FILE_NOT_FOUND'
  - Response body has paths_tried array with all attempted paths
  - Verify: /data/viewer-cache/{doc_id}/ does NOT exist
```

**Test 3: File endpoint — serves cached file with correct Content-Type**
```
Given: A cached PDF file at /data/viewer-cache/{doc_id}/file.pdf
When: GET /api/viewer/file/{doc_id}
Then:
  - Response status 200
  - Content-Type header is 'application/pdf'
  - Content-Length header matches file size
  - Response body matches file content (byte comparison)
```

**Test 4: File endpoint — not cached returns 404**
```
Given: No cached file for document
When: GET /api/viewer/file/{doc_id}
Then:
  - Response status 404
  - Response body has error='NOT_CACHED'
```

**Test 5: Close endpoint — starts cleanup timer**
```
Given: A cached file for document
When: POST /api/viewer/close/{doc_id}
Then:
  - Response status 200
  - Response body has cleanup_scheduled=true
  - File still exists (timer hasn't fired yet)
```

**Test 6: Document-detail endpoint — returns full metadata**
```
Given: A complete document with OCR results, chunks, embeddings, images, provenance
When: GET /api/databases/test/document-detail?document_id={id}
Then:
  - Response has document.file_name, file_path, file_type, file_hash
  - Response has ocr_result with quality score, duration
  - Response has counts.chunks > 0
  - Response has counts.embeddings > 0
  - Response has provenance.total_records > 0
  - Verify: each count matches actual COUNT(*) query
```

**Test 7: Chunk-text endpoint — returns full text**
```
Given: A chunk with id X in the database
When: GET /api/databases/test/chunk-text/{X}
Then:
  - Response has id matching X
  - Response has text field with full content
  - Response has char_count matching LENGTH(text)
  - Verify: text matches direct SELECT text FROM chunks WHERE id = ?
```

**Test 8: Prepare endpoint — Office file conversion**
```
Given: A DOCX file and a document record pointing to it
When: GET /api/viewer/prepare/{doc_id}?db=test
Then:
  - Response has ready=true
  - Response has render_as='pdf'
  - Cached file is a PDF (not DOCX)
  - Verify: file at cache path starts with %PDF header
```

**Test 9: Path resolution — absolute host path**
```
Given: document.file_path = '/home/user/docs/file.pdf'
  AND: OCR_PROVENANCE_HOST_HOME = '/home/user'
  AND: file exists at /host/docs/file.pdf
When: resolveDocumentPath('/home/user/docs/file.pdf')
Then: returns '/host/docs/file.pdf'
```

**Test 10: Path resolution — staged upload path**
```
Given: document.file_path = '/data/staged/batch-123/file.pdf'
  AND: file exists at /data/staged/batch-123/file.pdf
When: resolveDocumentPath('/data/staged/batch-123/file.pdf')
Then: returns '/data/staged/batch-123/file.pdf'
```

**Test 11: Path traversal prevention**
```
Given: document.file_path = '/host/../../../etc/passwd'
When: resolveDocumentPath(that path)
Then: returns null (path traversal blocked)
```

**Test 12: Render info mapping — all 18 types**
```
For each of: pdf, docx, doc, pptx, ppt, xlsx, xls, png, jpg, jpeg, tiff, tif, bmp, gif, webp, txt, csv, md
When: getViewerRenderInfo(type)
Then:
  - Returns a valid { renderAs, contentType }
  - renderAs is one of: 'pdf', 'image', 'text', 'markdown'
  - contentType is a valid MIME type
```

**Test 13: Cleanup timer — file deleted after timeout**
```
Given: A cached file with a SHORT cleanup delay (use 100ms for testing)
When: startCleanupTimer(doc_id) with SHORT delay
Then:
  - After 150ms: cached directory is deleted
  - Verify: fs.existsSync(cacheDir) === false
```

**Test 14: Cleanup timer — reset on access**
```
Given: A cleanup timer set for doc_id
When: resetCleanupTimer(doc_id)
Then: Timer is restarted from zero
  - After original timeout: file still exists
  - After new timeout: file is deleted
```

**Test 15: Startup reconciliation — stale caches cleaned**
```
Given: A cache directory with mtime > 24 hours ago
When: reconcileViewerCache()
Then: Directory is deleted
  - Verify: fs.existsSync(staleDir) === false
```

**Test 16: Startup reconciliation — fresh caches get timers**
```
Given: A cache directory with mtime < 24 hours ago
When: reconcileViewerCache()
Then: Timer is set for remaining time
  - Verify: viewerCleanupTimers.has(docId) === true
```

### 11.2 Dashboard Component Tests

**Location**: If the dashboard has a test setup (check for vitest/jest config), add tests there. Otherwise, manual testing.

**Manual Test Checklist**:

1. Click a PDF document → viewer opens, PDF renders in iframe
2. Click a .md document → viewer opens, Markdown renders as formatted HTML
3. Click a .txt document → viewer opens, plain text renders in monospace
4. Click a document with chunks → Chunks tab shows all chunks for that document
5. Expand a chunk → Full text loads and displays
6. Switch to Info tab → Metadata, OCR details, counts, provenance all display
7. Press Escape → Viewer closes
8. Click X button → Viewer closes
9. Re-open same document → Viewer opens instantly (cached)
10. Open document whose source file was deleted → Error state with clear message

### 11.3 Integration Tests

**Location**: `tests/integration/viewer-integration.test.ts`

**Test**: End-to-end flow using the real MCP server

```
1. Start MCP server with a real database (AlexHormoziTranscripts)
2. Pick a document ID from the database
3. Call GET /api/viewer/prepare/{doc_id}?db=AlexHormoziTranscripts
4. Verify response has ready=true
5. Call GET /api/viewer/file/{doc_id}
6. Verify file bytes match expected size
7. Call POST /api/viewer/close/{doc_id}
8. Verify cleanup_scheduled=true
9. Call GET /api/databases/AlexHormoziTranscripts/document-detail?document_id={doc_id}
10. Verify all sections present
11. Call GET /api/databases/AlexHormoziTranscripts/chunk-text/{chunk_id}
12. Verify text returned
```

### 11.4 Edge Case Tests

1. **Document with no OCR result (status=pending)**: Info tab shows document fields, ocr_result is null, counts are all 0
2. **Document with no chunks**: Chunks tab shows "No chunks found for this document"
3. **Document with 1000+ chunks**: Pagination works, first page loads quickly
4. **Empty database name**: Returns 400 error
5. **Special characters in filename**: URL encoding works correctly
6. **Very long file path**: Displays without breaking layout (truncation with tooltip)
7. **Concurrent prepare requests for same document**: Only one copy happens, second request gets cached result
8. **MIME type correctness**: Each file type gets the right Content-Type header

### 11.5 Manual Verification Checklist

After implementation, verify each step produces the expected output:

| Step | Action | Expected Output | How to Verify |
|------|--------|----------------|---------------|
| 1 | Navigate to database documents tab | Document table renders | Browser shows document list |
| 2 | Click a PDF document | Full-screen viewer opens | Visual confirmation |
| 3 | Check View tab | PDF renders in iframe | PDF content visible |
| 4 | Check Chunks tab | Chunk list with counts | Count matches database `SELECT COUNT(*) FROM chunks WHERE document_id = ?` |
| 5 | Expand a chunk | Full text appears | Text matches database `SELECT text FROM chunks WHERE id = ?` |
| 6 | Check Info tab | All metadata present | Values match database records |
| 7 | Close viewer | Viewer disappears | Body scroll restored |
| 8 | Check cache exists | File in viewer-cache | `ls /data/viewer-cache/{doc_id}/` |
| 9 | Wait >24 hours (or use short timer) | Cache cleaned | `ls /data/viewer-cache/{doc_id}/` returns empty |
| 10 | Delete source file, try to open | Error message | Clear error with original path shown |

## Test Data

### Using AlexHormoziTranscripts Database

The existing AlexHormoziTranscripts database (visible in the screenshot) contains:
- 1,150 documents (PDFs and .md files)
- PDFs have 184 pages, quality 5.0
- Markdown files have 1 page, quality 4.0

This is real production data that can be used for testing. No synthetic data needed.

**Test document**: `_OceanofPDF.com_00M_Money_Models_How_To_Make_Money_Alex_Hormozi.pdf`
- Type: PDF
- Pages: 184
- Quality: 5.0
- Status: complete
- Should have many chunks and embeddings
