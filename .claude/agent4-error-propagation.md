# Agent 4: Silent Error Propagation Fixes (M-2, M-3, M-4, L-13, L-14)

## Date: 2026-02-23

## Issues Fixed

### M-2: VLM Embedding Failure Silently Swallowed
- **File**: `src/tools/vlm.ts:266-270`
- **Root cause**: When VLM describes an image and embedding generation fails, the catch block logged a warning but the success response showed no indication of failure. Users/agents see success but the description is not semantically searchable.
- **Fix**: Added `warnings: string[]` array. On embedding failure, the warning message is pushed to the array and included in the success response via `...(warnings.length > 0 ? { warnings } : {})`. The VLM description is still reported as successful (it WAS stored), but the embedding failure is now visible.

### M-3: Tag Application Failure During Ingestion Swallowed
- **File**: `src/tools/ingestion.ts:761-767`
- **Root cause**: If auto-tagging of repeated headers/footers fails during document ingestion, the error was caught and logged but never surfaced to the user.
- **Fix**: Changed `processOneDocument` return type from `Promise<void>` to `Promise<string[]>` (warnings). On tag failure, warning is pushed to the array. Callers (`handleProcessPending`, `handleReprocess`) collect and include warnings in their responses.

### M-4: Metadata Enrichment Failure During Ingestion Swallowed
- **File**: `src/tools/ingestion.ts:862-868`
- **Root cause**: If metadata enrichment (block stats, links, structural fingerprint) fails, the document is marked complete but enrichment data is missing. Error was caught and logged but not surfaced.
- **Fix**: Same warnings pattern as M-3. Warning pushed to the `processOneDocument` warnings array, included in the final response.

### L-13: Image Relevance Analysis Fail-Open in VLM Pipeline
- **File**: `src/services/vlm/pipeline.ts:607-612`
- **Root cause**: When image relevance analysis threw an error, the pipeline defaulted to processing with VLM (fail-open), wasting Gemini API credits on potentially irrelevant images.
- **Fix**: Changed to fail-CLOSED. When relevance analysis throws, the image is NOT processed. Returns `{ process: false, reason: 'Relevance analysis failed: <error>. Skipping to avoid processing potentially irrelevant images.' }`. Error is logged clearly with console.error.

### L-14: Structured Extraction Embedding Failure Swallowed
- **File**: `src/tools/extraction-structured.ts:207-216`
- **Root cause**: Extraction succeeds but embedding for searchability fails silently. Users see success with `embedding_id: null` but no explanation of why.
- **Fix**: Added `warnings: string[]` array. On embedding failure, warning is pushed and included in the success response. Extraction is still reported as successful (it WAS stored), but the embedding failure is now visible.

## Additional Task: VLM Handlers Wrapped with withDatabaseOperation

### handleVLMDescribe
- **File**: `src/tools/vlm.ts`
- Wrapped with `withDatabaseOperation()` to prevent database switches during Gemini API calls and database writes.
- Import added: `withDatabaseOperation` from `../../server/state.js`

### handleVLMProcess
- **File**: `src/tools/vlm.ts`
- Wrapped with `withDatabaseOperation()` to protect long-running VLM pipeline processing.

### handleVLMAnalyzePDF - NOT wrapped
- Does not use the database at all (sends PDF directly to Gemini). Wrapping would cause it to fail when no database is selected, which would be a regression since it explicitly advertises "No database needed".

### handleVLMStatus - NOT wrapped (read-only, as specified)

## Files Changed

### `src/tools/vlm.ts`
- Added import of `withDatabaseOperation` from `../server/state.js`
- `handleVLMDescribe`: Wrapped body in `withDatabaseOperation()`, added `warnings: string[]` array, embedding catch block now pushes warning, success response includes `warnings` field when non-empty
- `handleVLMProcess`: Wrapped body in `withDatabaseOperation()`

### `src/tools/ingestion.ts`
- `processOneDocument`: Changed return type from `Promise<void>` to `Promise<string[]>`, added `warnings: string[]` accumulator, tag error (M-3) and enrichment error (M-4) catch blocks push to warnings, returns warnings at end
- `handleProcessPending`: Added `warnings` to results tracker, `processDocWithTracking` collects returned warnings from `processOneDocument`, response includes `warnings` field when non-empty
- `handleReprocess`: Collects `reprocessWarnings` from `processOneDocument`, includes in response when non-empty

### `src/services/vlm/pipeline.ts`
- `checkImageRelevance`: Changed fail-open to fail-closed in Layer 5 relevance analysis catch block. Now returns `{ process: false, reason: ... }` instead of falling through to process the image.

### `src/tools/extraction-structured.ts`
- `handleExtractStructured`: Added `warnings: string[]` array, embedding catch block pushes warning, success response includes `warnings` field when non-empty

## Design Decisions

1. **Warnings pattern over errors**: These are non-fatal failures where the primary operation succeeded. Using a `warnings` field on the success response makes failures visible without changing the success/error semantics. AI agents can inspect `warnings` and take corrective action (e.g., re-run embedding).

2. **Fail-closed for relevance analysis (L-13)**: Changed from fail-open because wasting Gemini API credits on irrelevant images (logos, icons) is worse than skipping a potentially relevant image. Skipped images can be retried; wasted API credits cannot be recovered.

3. **handleVLMAnalyzePDF not wrapped**: This handler explicitly does not use the database. Wrapping with `withDatabaseOperation()` would call `requireDatabase()` which throws if no DB is selected - a regression for a tool that advertises "No database needed".

## Verification

- Build: `npm run build` -- 0 errors
- Tests: `npm test` -- 2475 passed, 0 failed across 111 test files
