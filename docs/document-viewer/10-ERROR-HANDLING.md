# 10 — Error Handling Strategy

## Core Principle: Fail Fast, Never Silent

Per the constitution's fail-fast doctrine:
- Every error must surface immediately with full context
- No silent fallbacks, no degradation, no empty defaults
- Error messages include: what failed, why, what input caused it, and how to fix it

## Error Categories

### Category 1: File Not Found

**When**: Source file no longer exists at the stored path.

**Error response from `/api/viewer/prepare`**:
```json
{
  "ready": false,
  "error": "FILE_NOT_FOUND",
  "message": "Source file not found. The original file may have been moved or deleted from the host filesystem.",
  "document_id": "abc-123",
  "original_file_path": "/host/Documents/contracts/old-contract.pdf",
  "paths_tried": [
    "/host/Documents/contracts/old-contract.pdf",
    "/data/staged/batch-2026-03-15/old-contract.pdf"
  ],
  "suggestion": "Ensure the file exists at the original path, or re-ingest the document."
}
```

**Dashboard display**: Full-screen error state in the viewer showing the error message, original path, and paths tried.

### Category 2: Office Conversion Failed

**When**: LibreOffice fails to convert an Office file to PDF.

**Error response**:
```json
{
  "ready": false,
  "error": "CONVERSION_FAILED",
  "message": "Failed to convert DOCX to PDF. LibreOffice returned an error.",
  "document_id": "abc-123",
  "original_file_path": "/host/Documents/report.docx",
  "conversion_error": "LibreOffice process exited with code 1: Error loading font 'Calibri'",
  "suggestion": "The file may be corrupted or use unsupported fonts. Try opening it in LibreOffice on your host machine."
}
```

### Category 3: Database Not Found / Not OCR Database

**When**: The database name in the URL doesn't exist or isn't a valid OCR database.

**Error response**: Standard 404/422 from `openVerifiedOcrDb()` — same as all existing endpoints.

### Category 4: Document ID Not Found

**When**: The document ID doesn't exist in the database.

**Error response**:
```json
{
  "error": "Document 'nonexistent-id' not found in database 'AlexHormoziTranscripts'",
  "document_id": "nonexistent-id",
  "database": "AlexHormoziTranscripts"
}
```

### Category 5: Cache Read Error

**When**: Cached file exists but can't be read (permissions, disk error).

**Error response from `/api/viewer/file`**:
```json
{
  "error": "CACHE_READ_ERROR",
  "message": "Failed to read cached file: EACCES: permission denied",
  "document_id": "abc-123"
}
```

### Category 6: Cache Not Found (Not Prepared)

**When**: Client requests `/api/viewer/file/{id}` without first calling `/api/viewer/prepare/{id}`.

**Error response**:
```json
{
  "error": "NOT_CACHED",
  "message": "No cached file for document abc-123. Call /api/viewer/prepare/ first.",
  "document_id": "abc-123"
}
```

### Category 7: Network/Proxy Error

**When**: Dashboard can't reach MCP server.

**Dashboard display**: Standard error state: "MCP server unreachable: [error details]"

### Category 8: Unsupported File Type

**When**: A document has a file_type not in the supported list.

**Error from `getViewerRenderInfo()`**:
```
Error: Unsupported file type for viewer: xyz
```

**This should never happen** because the ingestion system validates file types. But if it does, it surfaces as a clear error in the viewer.

## Error Logging (Server Side)

All viewer errors are logged via `console.error()` (not `console.log()`, per IMM-02):

```typescript
// Pattern for all viewer error logging
console.error(`[viewer] ${operation} failed for document ${documentId}: ${errorMessage}`, {
  document_id: documentId,
  operation: 'prepare' | 'serve' | 'cleanup' | 'convert',
  file_path: originalFilePath,
  error: errorMessage,
  stack: error.stack,
});
```

### Log Format Examples

```
[viewer] prepare failed for document abc-123: Source file not found at /host/Documents/old.pdf
[viewer] convert failed for document def-456: LibreOffice exited with code 1
[viewer] serve failed for document ghi-789: EACCES: permission denied /data/viewer-cache/ghi-789/file.pdf
[viewer] cleanup failed for document jkl-012: ENOENT: directory not found
[viewer] Startup reconciliation: cleaned 3 expired, set 2 timers
```

## Error Display (Dashboard)

### ViewerErrorState Component

```tsx
function ViewerErrorState({
  error,
  document,
  detail,
}: {
  error: string;
  document?: McpDocument;
  detail?: {
    paths_tried?: string[];
    suggestion?: string;
    original_file_path?: string;
  };
}) {
  return (
    <div className="flex items-center justify-center h-full p-8">
      <div className="max-w-lg w-full text-center">
        <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center mx-auto mb-4">
          <span className="text-red-400 text-2xl">!</span>
        </div>

        <h3 className="text-lg font-medium text-red-400 mb-2">
          Unable to display document
        </h3>

        {document && (
          <p className="text-slate-400 text-sm mb-3">{document.file_name}</p>
        )}

        <div className="bg-slate-800 rounded-lg p-4 text-left mb-4">
          <p className="text-sm text-slate-300 font-mono break-all">{error}</p>
        </div>

        {detail?.original_file_path && (
          <div className="text-left mb-3">
            <p className="text-xs text-slate-500 mb-1">Original file path:</p>
            <p className="text-xs text-slate-400 font-mono bg-slate-800 rounded px-2 py-1 break-all">
              {detail.original_file_path}
            </p>
          </div>
        )}

        {detail?.paths_tried && detail.paths_tried.length > 0 && (
          <div className="text-left mb-3">
            <p className="text-xs text-slate-500 mb-1">Paths searched:</p>
            <ul className="text-xs text-slate-500 font-mono space-y-0.5">
              {detail.paths_tried.map((p, i) => (
                <li key={i} className="bg-slate-800 rounded px-2 py-0.5 break-all">✕ {p}</li>
              ))}
            </ul>
          </div>
        )}

        {detail?.suggestion && (
          <p className="text-sm text-slate-400 mt-3 bg-blue-500/10 border border-blue-500/20 rounded-lg p-3">
            {detail.suggestion}
          </p>
        )}
      </div>
    </div>
  );
}
```

## No Fallbacks, No Workarounds

The following patterns are explicitly **prohibited**:

1. ~~If file not found, show the OCR text instead~~ → Error out. The View tab shows the file. The Chunks tab shows the text.
2. ~~If conversion fails, show raw Office XML~~ → Error out. Unreadable XML helps no one.
3. ~~If browser doesn't support TIFF, convert server-side~~ → Error out. User can convert externally.
4. ~~If viewer prepare fails, fall back to the old expand view~~ → Error out. Old expand view is deleted.
5. ~~If chunk text fails to load, show preview~~ → Show preview in the list, show error on expand attempt.
6. ~~Catch all errors and show generic "Something went wrong"~~ → Every error shows specific, actionable details.
