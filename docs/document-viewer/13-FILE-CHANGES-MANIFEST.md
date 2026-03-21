# 13 — File Changes Manifest

## Every file that will be created or modified.

### Files Modified

| # | File Path | Change Description |
|---|-----------|-------------------|
| 1 | `src/bin-http.ts` | Add 4 new REST endpoints (viewer/prepare, viewer/file, viewer/close, document-detail, chunk-text) + helper functions + startup reconciliation + cleanup timer management. ~300 lines added. |
| 2 | `packages/dashboard/components/document-table.tsx` | Remove expandedId state and expand-on-click logic. Add viewerDoc state and DocumentViewerModal rendering. Net ~-20 lines (remove expand) + ~10 lines (add viewer). |
| 3 | `packages/dashboard/lib/mcp-types.ts` | Add `ViewerPrepareResponse` and `DocumentDetail` interfaces. ~60 lines added. |
| 4 | `packages/dashboard/app/api/mcp/[...path]/route.ts` | Update GET handler to detect non-JSON responses and stream binary data instead of parsing as JSON. ~20 lines modified. |
| 5 | `Dockerfile` | Add LibreOffice installation in runtime stage. ~5 lines added. |
| 6 | `packages/dashboard/package.json` | Add `marked` dependency. 1 line. |

### Files Created

| # | File Path | Description | Approx. Lines |
|---|-----------|-------------|---------------|
| 1 | `packages/dashboard/components/document-viewer-modal.tsx` | Full-screen modal component with tab bar, lifecycle management (prepare/close API calls), Escape key handling, body scroll lock. | ~150 |
| 2 | `packages/dashboard/components/viewer-tab-content.tsx` | Document content viewer with 4 renderers: PdfViewer (iframe), ImageViewer (img + zoom), TextViewer (pre), MarkdownViewer (marked + prose). Error and loading states. | ~250 |
| 3 | `packages/dashboard/components/chunks-tab-content.tsx` | Paginated chunk list for a specific document, with search, text expansion, and client-side text caching. | ~200 |
| 4 | `packages/dashboard/components/info-tab-content.tsx` | Document metadata display: file info, OCR processing details, content counts, provenance chain summary. | ~200 |
| 5 | `tests/unit/viewer-api.test.ts` | Server-side API tests for all viewer endpoints + helper functions. 16 test cases. | ~400 |

### Files NOT Modified (Explicitly)

These files are **not changed** by this feature:

| File | Reason |
|------|--------|
| `src/tools/*.ts` | No new MCP tools. Viewer is REST API only. |
| `src/services/storage/migrations/*.ts` | No schema changes. No new tables. |
| `src/models/document.ts` | No changes to document model. |
| `src/server/register-tools.ts` | No new tools registered. |
| `src/server/state.ts` | No state changes. |
| `packages/server/*` | License server is unaffected. |
| `packages/wrapper/*` | NPM wrapper is unaffected. |
| `packages/checkout-worker/*` | Billing worker is unaffected. |
| `python/*` | No Python worker changes. |
| `scripts/docker-entrypoint.sh` | No entrypoint changes. |
| `scripts/docker-healthcheck.sh` | No healthcheck changes. |

### Directories Created at Runtime

| Directory | Created By | Cleaned Up By |
|-----------|-----------|---------------|
| `/data/viewer-cache/` | First `viewer/prepare` request | Never (directory persists, contents cleaned) |
| `/data/viewer-cache/{document_id}/` | `viewer/prepare` request | 24-hour cleanup timer or startup reconciliation |

### Dependencies Added

| Package | Location | Version | Purpose |
|---------|----------|---------|---------|
| `marked` | `packages/dashboard/package.json` | `^15.0.0` | Markdown-to-HTML parsing for .md file viewer |
| `libreoffice-writer` | `Dockerfile` (apt) | System package | DOCX/DOC to PDF conversion |
| `libreoffice-calc` | `Dockerfile` (apt) | System package | XLSX/XLS to PDF conversion |
| `libreoffice-impress` | `Dockerfile` (apt) | System package | PPTX/PPT to PDF conversion |
| `fonts-liberation` | `Dockerfile` (apt) | System package | Standard fonts for Office rendering |
| `fonts-dejavu-core` | `Dockerfile` (apt) | System package | Fallback fonts |

### Optionally Added Dependencies

| Package | Location | Version | Purpose | Needed? |
|---------|----------|---------|---------|---------|
| `@tailwindcss/typography` | `packages/dashboard/package.json` | `^0.5.0` | `prose` class for Markdown rendering | Check if already installed first |

## Impact Assessment

### Docker Image Size
- LibreOffice packages: +150-200MB
- `marked` npm package: +50KB (negligible)
- Total image size increase: ~200MB (from ~500MB to ~700MB for app image)

### Runtime Memory
- `viewerCleanupTimers` Map: Negligible (one timer per open document)
- Cached files: Size of original documents (temporary, 24-hour expiry)

### Performance Impact
- File copy: Milliseconds for most documents
- LibreOffice conversion: 2-20 seconds depending on file size
- No impact on existing OCR, search, or ingestion performance

### Security Impact
- No new auth mechanisms (uses existing X-License-Key)
- Path traversal prevention in `resolveDocumentPath()`
- Read-only access to host mount (no writes to /host)
- Cached files have restrictive permissions (600)

### Backwards Compatibility
- **NONE** — the old expand-on-click behavior is deleted
- If the dashboard is updated without the MCP server being updated: viewer prepare calls will 404 (clear error)
- If the MCP server is updated without the dashboard: document table still works (old expand code is removed but viewer won't open)
- **Both must be updated together** for the feature to work
