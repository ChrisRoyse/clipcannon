# 12 — Implementation Order (Step-by-Step Sequence)

## Dependency Graph

```
Phase 1: MCP Server Backend
  Step 1.1: Helper functions (no dependencies)
  Step 1.2: Viewer prepare endpoint (depends on 1.1)
  Step 1.3: Viewer file endpoint (depends on 1.1)
  Step 1.4: Viewer close endpoint (depends on 1.1)
  Step 1.5: Document-detail endpoint (no dependencies)
  Step 1.6: Chunk-text endpoint (no dependencies)
  Step 1.7: Startup reconciliation (depends on 1.1)
  Step 1.8: LibreOffice in Dockerfile (independent)

Phase 2: Dashboard Frontend
  Step 2.1: Type definitions (no dependencies, but needs Phase 1 API shape)
  Step 2.2: API proxy update for binary responses (depends on 2.1)
  Step 2.3: ViewerTabContent component (depends on 2.1, 2.2)
  Step 2.4: ChunksTabContent component (depends on 2.1)
  Step 2.5: InfoTabContent component (depends on 2.1)
  Step 2.6: DocumentViewerModal component (depends on 2.3, 2.4, 2.5)
  Step 2.7: DocumentTable modification (depends on 2.6)
  Step 2.8: Add marked dependency (needed by 2.3)

Phase 3: Testing & Verification
  Step 3.1: Server API tests (depends on Phase 1)
  Step 3.2: Manual testing (depends on Phase 1 + 2)
  Step 3.3: Edge case testing (depends on Phase 1 + 2)
  Step 3.4: Code simplification pass
```

## Phase 1: MCP Server Backend (src/bin-http.ts + Dockerfile)

### Step 1.1: Add helper functions and constants

**File**: `src/bin-http.ts`
**What**: Add at module scope (near top of file, after imports):
- `VIEWER_CACHE_DIR` constant
- `MIME_TYPES` map
- `viewerCleanupTimers` Map
- `VIEWER_CLEANUP_DELAY_MS` constant
- `getViewerRenderInfo()` function
- `isOfficeType()` function
- `resolveDocumentPath()` function
- `getPathCandidates()` function
- `startCleanupTimer()` function
- `cancelCleanupTimer()` function
- `resetCleanupTimer()` function
- `cacheDocumentFile()` function
- `convertToPdf()` function
- `reconcileViewerCache()` function

**Dependencies**: None (these are pure utility functions)
**Test**: Build compiles without errors

### Step 1.2: Add viewer prepare endpoint

**File**: `src/bin-http.ts`
**What**: Add `GET /api/viewer/prepare/{document_id}?db={name}` handler
**Where**: Inside the `if (req.method === 'GET' && req.url?.startsWith('/api/'))` block, BEFORE `if (pathname === '/api/overview')`
**Dependencies**: Step 1.1
**Test**: `curl http://localhost:3366/api/viewer/prepare/{doc_id}?db=AlexHormoziTranscripts`

### Step 1.3: Add viewer file endpoint

**File**: `src/bin-http.ts`
**What**: Add `GET /api/viewer/file/{document_id}` handler
**Where**: Same block as 1.2, right after prepare handler
**Dependencies**: Step 1.1
**Test**: `curl -o /tmp/test.pdf http://localhost:3366/api/viewer/file/{doc_id}` — verify PDF bytes

### Step 1.4: Add viewer close endpoint

**File**: `src/bin-http.ts`
**What**: Add `POST /api/viewer/close/{document_id}` handler
**Where**: In the POST handler section, after the upload handlers
**Dependencies**: Step 1.1
**Test**: `curl -X POST http://localhost:3366/api/viewer/close/{doc_id}` — verify response

### Step 1.5: Add document-detail endpoint

**File**: `src/bin-http.ts`
**What**: Add `GET /api/databases/{name}/document-detail?document_id={id}` handler
**Where**: In the GET /api/ block, alongside existing database-scoped endpoints
**Dependencies**: None (uses existing database access patterns)
**Test**: `curl http://localhost:3366/api/databases/AlexHormoziTranscripts/document-detail?document_id={id}`

### Step 1.6: Add chunk-text endpoint

**File**: `src/bin-http.ts`
**What**: Add `GET /api/databases/{name}/chunk-text/{chunk_id}` handler
**Where**: Same location as 1.5
**Dependencies**: None
**Test**: `curl http://localhost:3366/api/databases/AlexHormoziTranscripts/chunk-text/{chunk_id}`

### Step 1.7: Add startup reconciliation

**File**: `src/bin-http.ts`
**What**: Call `reconcileViewerCache()` after the server starts listening
**Where**: After the `server.listen()` callback
**Dependencies**: Step 1.1
**Test**: Create stale cache dirs, restart server, verify they're cleaned up

### Step 1.8: Add LibreOffice to Dockerfile

**File**: `Dockerfile` (runtime stage)
**What**: Install `libreoffice-writer libreoffice-calc libreoffice-impress fonts-liberation fonts-dejavu-core`
**Dependencies**: Independent (can be done in parallel with other steps)
**Test**: `docker exec ocr-provenance-mcp libreoffice --version` returns a version

### Step 1.9: Build and test

**Commands**:
```bash
pkill -f "dist/bin.js"    # Kill existing server (separate command)
npm run build             # Build TypeScript
npm test                  # Run all tests
```

## Phase 2: Dashboard Frontend

### Step 2.1: Add type definitions

**File**: `packages/dashboard/lib/mcp-types.ts`
**What**: Add `ViewerPrepareResponse` and `DocumentDetail` interfaces
**Dependencies**: Phase 1 API shape (for correct type definitions)

### Step 2.2: Update API proxy for binary responses

**File**: `packages/dashboard/app/api/mcp/[...path]/route.ts`
**What**: Update the GET handler to detect binary responses (check Content-Type header) and stream them instead of parsing as JSON.

Alternative: Create a new route file `app/api/mcp-file/[...path]/route.ts` specifically for binary file proxying.

**Dependencies**: Step 2.1

### Step 2.3: Create ViewerTabContent component

**File**: `packages/dashboard/components/viewer-tab-content.tsx`
**What**: PdfViewer, ImageViewer, TextViewer, MarkdownViewer sub-components
**Dependencies**: Steps 2.1, 2.2

### Step 2.4: Create ChunksTabContent component

**File**: `packages/dashboard/components/chunks-tab-content.tsx`
**What**: Paginated chunk list with text expansion
**Dependencies**: Step 2.1

### Step 2.5: Create InfoTabContent component

**File**: `packages/dashboard/components/info-tab-content.tsx`
**What**: Document metadata, OCR details, counts, provenance display
**Dependencies**: Step 2.1

### Step 2.6: Create DocumentViewerModal component

**File**: `packages/dashboard/components/document-viewer-modal.tsx`
**What**: Full-screen modal with tab bar, lifecycle management (prepare/close calls)
**Dependencies**: Steps 2.3, 2.4, 2.5

### Step 2.7: Modify DocumentTable

**File**: `packages/dashboard/components/document-table.tsx`
**What**: Remove expandedId state and expand logic. Add viewerDoc state and viewer modal.
**Dependencies**: Step 2.6

### Step 2.8: Add marked dependency

**Command**: `cd packages/dashboard && npm install marked`
**What**: Markdown parser for the MarkdownViewer
**Dependencies**: None (can be done early)

### Step 2.9: Build and verify dashboard

**Commands**:
```bash
cd packages/dashboard
npm install
npm run build    # Next.js build
```

## Phase 3: Testing & Verification

### Step 3.1: Write and run server API tests

**File**: `tests/unit/viewer-api.test.ts`
**What**: All 16 test cases from Testing Plan
**Dependencies**: Phase 1 complete
**Command**: `npm test -- tests/unit/viewer-api.test.ts`

### Step 3.2: Manual testing

**What**: Follow the Manual Verification Checklist from Testing Plan
**Dependencies**: Phase 1 + 2 complete
**Verification**: Each step produces expected output, outputs verified against database

### Step 3.3: Edge case testing

**What**: Test all edge cases from Testing Plan
**Dependencies**: Phase 1 + 2 complete

### Step 3.4: Code simplification

**What**: Run code-simplifier agent to review all changes
**Dependencies**: All previous steps complete

## Time Estimates (Rough)

| Phase | Steps | Complexity |
|-------|-------|-----------|
| Phase 1 (Backend) | 9 steps | Medium — new endpoints in existing patterns |
| Phase 2 (Frontend) | 9 steps | Medium-High — new React components |
| Phase 3 (Testing) | 4 steps | Medium — real data testing |

## Critical Path

```
1.1 → 1.2 → 1.3 → 1.4 → 1.9 (build/test)
         ↘                ↗
          1.5, 1.6, 1.7

2.1 → 2.2 → 2.3 → 2.6 → 2.7 → 2.9 (build)
         ↘         ↗
          2.4, 2.5

3.1 → 3.2 → 3.3 → 3.4
```

Steps within the same phase that have no dependencies on each other can be done in parallel (e.g., 1.5 + 1.6, or 2.4 + 2.5).
