# Forensic Audit Fix Coordination

## Status: IN PROGRESS
## Date: 2026-02-23

## Agent Sequence (Synchronous - Each waits for previous)

### Agent 1: State Race Condition (H-1, H-2, M-9)
- **Files**: `src/server/state.ts`
- **Fix**: Add operation tracking (beginDatabaseOperation/endDatabaseOperation). selectDatabase() rejects if operations in-flight. Async handlers use try/finally.
- **Status**: PENDING
- **Memory**: agent1-state-fix.md

### Agent 2: VLM Page Range Filter (M-1)
- **Files**: `src/services/storage/vector.ts`
- **Fix**: mapAndFilterResults currently ignores _options param. Rename to options, apply pageRangeFilter to VLM results (chunk_id === null). Filter by e.page_number against min_page/max_page.
- **Status**: PENDING
- **Memory**: agent2-vlm-filter.md

### Agent 3: Type Safety (M-7, M-8)
- **Files**: `src/services/storage/database/converters.ts`, `src/tools/search.ts`
- **Fix M-7**: parseLocation/parseVLMStructuredData return null on parse failure instead of fake `{_parse_error}` objects. Update rowToProvenance/rowToImage to propagate null.
- **Fix M-8**: Add typed interface CrossDBResult with normalized_score field. Replace Record<string, unknown> casts.
- **Status**: PENDING
- **Memory**: agent3-type-safety.md

### Agent 4: Silent Failures → Visible Errors (M-2, M-3, M-4, L-13, L-14)
- **Files**: `src/tools/vlm.ts`, `src/tools/ingestion.ts`, `src/services/vlm/pipeline.ts`, `src/tools/extraction-structured.ts`
- **Fix M-2**: VLM embedding failure → include warning in response, don't silently swallow
- **Fix M-3**: Tag failure → include warning in response
- **Fix M-4**: Metadata enrichment failure → include warning in response
- **Fix L-13**: VLM relevance analysis fail → fail-closed (skip VLM), not fail-open
- **Fix L-14**: Structured extraction embedding failure → include warning in response
- **Status**: PENDING
- **Memory**: agent4-error-propagation.md

### Agent 5: Math Overflow + SIGKILL (M-10, M-11)
- **Files**: `src/tools/search.ts`, `src/tools/reports.ts`, `src/tools/chunks.ts`, `src/services/images/extractor.ts`
- **Fix M-10**: Replace Math.min(...array)/Math.max(...array) with iterative reduce() at 6 locations
- **Fix M-11**: Add SIGKILL escalation to runCommand() in extractor.ts
- **Status**: PENDING
- **Memory**: agent5-math-sigkill.md

### Agent 6: Migration Atomicity (M-5, M-6, L-5, L-15)
- **Files**: `src/services/storage/migrations/operations.ts`, `src/services/storage/vector.ts`
- **Fix M-5**: Wrap v19→v20 in transaction, PRAGMA foreign_keys in try/finally
- **Fix M-6**: Wrap v20→v21 in transaction
- **Fix L-5**: Wrap v27→v29 in transactions
- **Fix L-15**: Wrap VLM FTS rebuild delete-all+insert in transaction
- **Status**: PENDING
- **Memory**: agent6-migrations.md

### Agent 7: Search Scoring (L-1, L-2)
- **Files**: `src/services/search/fusion.ts`, `src/tools/search.ts`
- **Fix L-1**: Remove quality multiplier from fusion.ts (BM25 and semantic already apply it)
- **Fix L-2**: Single-result normalization → use 0.5 instead of 1.0, or use raw score
- **Status**: PENDING
- **Memory**: agent7-search-scoring.md

### Agent 8: Dead Code + Misc Cleanup (L-8, L-9, L-11, L-3, L-6, L-12, L-16)
- **Fix L-8**: Delete parseGeminiJson (dead - zero importers), chunk-deduplicator.ts, batchedQuery
- **Fix L-9**: Delete dead schema-definitions constants
- **Fix L-11**: Delete empty timeline.ts (update any imports)
- **Fix L-3**: Add VLM FTS trigger for image_id update NULL→non-NULL edge
- **Fix L-6**: Add safeJsonParse utility with runtime validation at system boundaries
- **Fix L-12**: Search analytics on pre-v29 DB should throw, not silently fail
- **Fix L-16**: Add coverage thresholds to vitest.config.ts
- **Status**: PENDING
- **Memory**: agent8-cleanup.md

### Agent 9: Test Coverage (H-4 - VLM behavioral tests + full suite validation)
- **Files**: `tests/`
- **Fix H-4**: Add behavioral tests for VLM handlers (handleVLMDescribe, handleVLMProcess, handleVLMAnalyzePDF, handleVLMStatus)
- **Run full test suite**: Ensure all 2475+ tests still pass after all fixes
- **Status**: PENDING
- **Memory**: agent9-tests.md

### Agent 10: Code Simplifier Review
- **Status**: PENDING
- **Memory**: agent10-review.md

## Key Files Modified
(Updated by each agent as they work)

## Notes
- NO backwards compatibility hacks
- NO mock data in tests
- Fail fast on errors, robust logging
- Every change must be verified by building and running tests
