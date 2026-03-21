# Document Viewer API

## Overview

The document viewer provides REST endpoints for in-browser viewing of ingested documents. It handles server-side conversion (Office→PDF, TIFF→PNG) and manages a per-document cache with automatic 24-hour cleanup. Added in v1.2.64.

**Location**: Implemented in `src/bin-http.ts` as part of the MCP HTTP server (port 3366).

## Supported File Types

| File Type | Render As | Conversion | Content-Type |
|-----------|-----------|------------|--------------|
| PDF | `pdf` | None (native) | `application/pdf` |
| DOCX, DOC, PPTX, PPT | `pdf` | LibreOffice → PDF | `application/pdf` |
| XLSX, XLS, CSV | `pdf` | Spreadsheet prep → LibreOffice → PDF | `application/pdf` |
| TIFF, TIF | `image` | Pillow → PNG | `image/png` |
| PNG, JPG, JPEG, GIF, WebP, BMP | `image` | None (native) | `image/*` |
| Markdown (MD) | `markdown` | None | `text/markdown; charset=utf-8` |
| Text (TXT) | `text` | None | `text/plain; charset=utf-8` |

## REST Endpoints

### Prepare Document for Viewing

```
GET /api/viewer/prepare/{document_id}?db={database_name}
```

**Parameters:**
- `document_id` — UUID of the document (path parameter)
- `db` — Database name (query parameter, required)

**Flow:**
1. Look up document in database → get `file_path`, `file_type`
2. Check viewer cache (`/data/viewer-cache/{document_id}/`)
3. If cached: return immediately with render info
4. If not cached, convert based on file type:
   - **PDF**: Copy to cache
   - **Office files**: LibreOffice headless → PDF conversion
   - **Spreadsheets**: Pre-process with `spreadsheet_prepare.py` (landscape + fit-to-width), then LibreOffice → PDF
   - **TIFF**: Pillow → PNG (browsers cannot render TIFF in `<img>` tags)
   - **Images**: Copy to cache
   - **Text/Markdown**: Copy to cache

**Response (200):**
```json
{
  "ready": true,
  "document_id": "abc123",
  "filename": "report.pdf",
  "original_filename": "report.docx",
  "render_as": "pdf",
  "content_type": "application/pdf",
  "size_bytes": 1048576
}
```

### Serve Cached File

```
GET /api/viewer/file/{document_id}
```

Streams the cached file with correct `Content-Type` header. Sets `Content-Disposition: inline` for in-browser rendering. Resets the 24-hour cleanup timer on every access.

**Headers:**
- `Content-Type`: Based on file extension
- `Content-Length`: File size
- `Content-Disposition`: `inline; filename="..."` (URL-encoded)
- `Cache-Control`: `private, max-age=3600`

### Close Document

```
POST /api/viewer/close/{document_id}
```

Starts the 24-hour cleanup timer for the document's cache entry. Call this when the user navigates away from the viewer.

**Response (200):**
```json
{
  "started_cleanup_timer": true,
  "document_id": "abc123",
  "cleanup_at": "2026-03-21T12:00:00.000Z"
}
```

## Cache Management

### Directory Structure

```
/data/viewer-cache/
├── {document_id_1}/
│   ├── report.pdf          # Converted or copied file
│   └── (original may be deleted after conversion)
├── {document_id_2}/
│   └── photo.png
└── ...
```

### Lifecycle

1. **Prepare**: Creates cache directory, converts/copies file
2. **Access**: Serves file, resets cleanup timer
3. **Close**: Starts 24-hour countdown to deletion
4. **Auto-cleanup**: Timer fires → removes cache directory
5. **Startup reconciliation**: On server start, cleans stale entries (>24h old), sets timers for fresh ones

### Concurrency

- Cache preparation uses `flock` to prevent duplicate conversions of the same document
- Timer map (`viewerCleanupTimers`) tracks active cleanup timers
- Timer reset on every file access prevents premature cleanup during active viewing

## Security

### Path Traversal Hardening

- Document IDs are sanitized via `sanitizeDocumentId()`: must not contain path separators or traversal sequences
- `path.basename()` applied to all IDs
- File paths resolved within the cache directory only
- Original file access goes through the existing `OCR_PROVENANCE_ALLOWED_DIRS` validation

### Spreadsheet Conversion Security

- LibreOffice runs in headless mode with `--norestore`
- Spreadsheet pre-processing creates temporary copies (never modifies originals)
- Temporary files cleaned up after conversion

## Spreadsheet Handling

Spreadsheet files (XLSX, XLS, CSV) get special preprocessing before LibreOffice conversion:

1. `spreadsheet_prepare.py` creates a copy with:
   - Landscape page orientation on all sheets
   - Fit-to-width page scaling (1 page wide, auto pages tall)
   - This ensures wide columns are not cut off in the PDF
2. The preprocessed copy is fed to LibreOffice with `calc_pdf_Export` filter
3. LibreOffice produces a PDF with all data visible

Without preprocessing, LibreOffice defaults to A4 portrait which truncates wide spreadsheets.

## TIFF Handling

Browsers cannot render TIFF images in `<img>` tags, so the viewer converts TIFF to PNG:

1. Uses Pillow (already installed for Marker/VLM workers)
2. For multi-page TIFFs, frame 0 (first page) is converted
3. Original TIFF is deleted from cache after successful conversion
4. Returned as `render_as: "image"` with `content_type: "image/png"`

## Error Handling

| Error | HTTP Status | Error Code |
|-------|-------------|------------|
| Invalid document ID | 400 | `INVALID_ID` |
| Document not found in database | 404 | `NOT_FOUND` |
| File not found on disk | 404 | `FILE_NOT_FOUND` |
| No cached file (call prepare first) | 404 | `NOT_CACHED` |
| Conversion failed | 500 | `PREPARE_FAILED` |
| File streaming error | 500 | `STREAM_ERROR` |

## Dependencies

- **LibreOffice**: Installed in Docker image for Office→PDF conversion
- **Pillow**: Already present for image processing workers; used for TIFF→PNG
- **openpyxl/xlrd**: Already present for spreadsheet OCR; used by `spreadsheet_prepare.py`
