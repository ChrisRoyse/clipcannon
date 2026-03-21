# Agent 9: VLM Behavioral Tests (H-4)

## Date: 2026-02-23

## Issue Fixed

### H-4: Zero Behavioral Tests for VLM Tools
- **File created**: `tests/unit/tools/vlm-behavioral.test.ts` (69 tests)
- **Root cause**: The 4 VLM handlers (`handleVLMDescribe`, `handleVLMProcess`, `handleVLMAnalyzePDF`, `handleVLMStatus`) in `src/tools/vlm.ts` had only structural schema checks in the codebase. No tests verified actual behavior, error propagation, database interaction, or the `withDatabaseOperation` wrapper behavior.

## Tests Added (69 total)

### vlmTools exports (4 tests)
- Exports all 4 VLM tools with correct structure
- Tools map to correct handlers
- Descriptions contain category tags ([PROCESSING], [STATUS])

### handleVLMDescribe - without database (8 tests)
- VALIDATION_ERROR for missing/empty/non-string image_path
- PATH_NOT_FOUND for nonexistent files in allowed directories
- PATH_NOT_FOUND includes recovery hint (error propagation fix M-2)
- VALIDATION_ERROR for paths outside allowed directories (sanitizePath SEC-002)
- Boolean parameter coercion for use_thinking
- Optional context_text accepted
- Unknown params stripped by Zod

### handleVLMDescribe - with real database and image file (2 tests)
- Passes validation+file check+DB wrapper, fails only on Gemini API
- withDatabaseOperation cleans up operation counter even on VLM failure

### handleVLMProcess - without database (15 tests)
- DATABASE_NOT_SELECTED with and without document_id
- Recovery hint present on DB errors
- VALIDATION_ERROR for batch_size (out of range, zero, negative, non-integer, >20)
- VALIDATION_ERROR for limit (out of range, zero, non-integer, >500)
- Boundary values accepted (batch_size 1/20, limit 1/500)
- Unknown params stripped

### handleVLMProcess - with database selected (5 tests)
- DOCUMENT_NOT_FOUND for nonexistent document_id with recovery hint
- Pending mode on empty database (tests VLMPipeline init path)
- Document mode with valid document but no images
- withDatabaseOperation cleanup on failure

### handleVLMAnalyzePDF (10 tests)
- VALIDATION_ERROR for missing/empty/non-string pdf_path
- PATH_NOT_FOUND for nonexistent files in allowed dirs
- Does NOT require database selection (no DB needed)
- VALIDATION_ERROR for paths outside allowed directories
- Optional prompt parameter accepted
- File size >20MB rejected with clear message
- Small files pass size check (fail on Gemini API, not validation)

### handleVLMStatus (5 tests)
- Does NOT require database selection
- Accepts empty object input
- Unknown params stripped
- Correct MCP response structure
- Success response includes api_key_configured, rate_limiter, circuit_breaker

### Database interaction tests (2 tests)
- handleVLMProcess finds real documents in database
- Images table queried for VLM processing (inserts image row, verifies query)

### MCP response structure tests (3 tests)
- All handlers return `{content: [{type, text}]}` even on error
- Error responses have `isError` flag set
- Error responses include category, message, and recovery fields

### withDatabaseOperation wrapper tests (4 tests)
- handleVLMDescribe operation counter cleaned up on error
- handleVLMProcess operation counter cleaned up on error
- handleVLMAnalyzePDF does NOT use withDatabaseOperation (no DB needed)
- handleVLMStatus does NOT use withDatabaseOperation

### Type coercion edge cases (7 tests)
- Rejects non-string, null types for image_path, document_id, pdf_path
- Rejects string values for numeric params (batch_size, limit)

## Key Test Patterns Used

1. **sanitizePath compliance**: All test paths use `/tmp/` prefix (in allowed base directories) instead of `/nonexistent/` which gets rejected by SEC-002 path validation
2. **Nested describe isolation**: `without database` and `with database selected` sub-describes have independent `beforeEach`/`afterEach` to prevent database state leaking
3. **Conditional assertions**: For handlers that depend on Gemini API (which may or may not be configured in CI), tests verify the error is NOT a DB/validation error rather than asserting a specific API error
4. **Real database instances**: Uses `createDatabase`/`selectDatabase` from test helpers with temp directories

## Verification

- Build: `npm run build` -- 0 errors
- VLM tests: 69 passed, 0 failed
- Full test suite: **2543 passed, 0 failed** across **112 test files**
  - Previous: 2475 passed across 111 files
  - Delta: +68 tests, +1 test file
