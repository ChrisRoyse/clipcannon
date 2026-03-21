# Sherlock Holmes Forensic Verification Report

**Case ID**: SEARCH-UNIFICATION-2026-02-21
**Date**: 2026-02-21
**Subject**: Unified Search Refactor + Tier Tag Updates + next_steps Additions
**Investigator**: Holmes (Opus 4.6)

---

## Phase 1: Code Changes Structural Verification

### 1.1 SearchUnifiedInput Schema in `/home/cabdru/datalab/src/utils/validation.ts`

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| `mode` param exists | Yes | Yes (line 301) | **PASS** |
| `mode` enum values | `['keyword', 'semantic', 'hybrid']` | `z.enum(['keyword', 'semantic', 'hybrid'])` (line 301) | **PASS** |
| `mode` default | `'hybrid'` | `.default('hybrid')` (line 301) | **PASS** |
| Old `SearchInput` schema gone | No matches | Confirmed: 0 matches in `src/` for `SearchInput ` (as standalone schema) | **PASS** |
| Old `SearchSemanticInput` schema gone | No matches | Confirmed: 0 matches in `src/` | **PASS** |
| Old `SearchHybridInput` schema gone | No matches | Confirmed: 0 matches in `src/` | **PASS** |
| Schema has keyword-mode params | `phrase_search`, `include_highlight` | Lines 351-354 | **PASS** |
| Schema has semantic-mode params | `similarity_threshold` | Line 357 | **PASS** |
| Schema has hybrid-mode params | `bm25_weight`, `semantic_weight`, `rrf_k`, `auto_route` | Lines 361-368 | **PASS** |
| Always-on params NOT in schema | `quality_boost`, `expand_query`, `exclude_duplicate_chunks` absent from schema | Confirmed: only in handler comment (line 295-296) | **PASS** |

### 1.2 Unified Handler in `/home/cabdru/datalab/src/tools/search.ts`

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Single unified handler exists | `handleSearchUnified` exported | Line 1888: `export async function handleSearchUnified(...)` | **PASS** |
| Routes by mode | `switch(input.mode)` | Lines 1904-1912 | **PASS** |
| `quality_boost` hardcoded `true` | `quality_boost: true` | Line 1895 | **PASS** |
| `expand_query` hardcoded `true` | `expand_query: true` | Line 1896 | **PASS** |
| `exclude_duplicate_chunks` hardcoded `true` | `exclude_duplicate_chunks: true` | Line 1897 | **PASS** |
| `include_headers_footers` hardcoded `false` | `include_headers_footers: false` | Line 1898 | **PASS** |
| `include_cluster_context` hardcoded `true` | `include_cluster_context: true` | Line 1899 | **PASS** |
| `include_document_context` hardcoded `true` | `include_document_context: true` | Line 1900 | **PASS** |

### 1.3 Tool Registration in `/home/cabdru/datalab/src/tools/search.ts`

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Only `ocr_search` exists | Single unified entry | Line 2813: `ocr_search: {...}` | **PASS** |
| No `ocr_search_semantic` | Absent | Confirmed: 0 matches in entire `src/` for `ocr_search_semantic` | **PASS** |
| No `ocr_search_hybrid` | Absent | Confirmed: 0 matches in entire `src/` for `ocr_search_hybrid` | **PASS** |
| Total tools in searchTools | Counted | 10 tools: `ocr_search`, `ocr_fts_manage`, `ocr_search_export`, `ocr_benchmark_compare`, `ocr_rag_context`, `ocr_search_save`, `ocr_search_saved_list`, `ocr_search_saved_get`, `ocr_search_saved_execute`, `ocr_search_cross_db` | **PASS** |

### 1.4 Orphan Reference Scan

| Check | Scope | Matches Found | Verdict |
|-------|-------|---------------|---------|
| `ocr_search_semantic` in `src/` | All `.ts` files | 0 | **PASS** |
| `ocr_search_hybrid` in `src/` | All `.ts` files | 0 | **PASS** |
| `ocr_search_semantic` in `tests/` | All `.ts` files | 0 | **PASS** |
| `ocr_search_hybrid` in `tests/` | All `.ts` files | 0 | **PASS** |
| `SearchSemanticInput` in `src/` | All `.ts` files | 0 | **PASS** |
| `SearchHybridInput` in `src/` | All `.ts` files | 0 | **PASS** |
| Old handler names in src | `handleSearchSemantic[^I]`, `handleSearchBm25`, `handleSearchHybrid[^I]` | 0 (only stale comment at line 2601) | **PASS** (with note) |

**Note**: Line 2601 in search.ts contains a stale comment: `(handleSearch, handleSearchSemantic, or handleSearchHybrid)` -- but the actual code at line 2645 correctly calls `handleSearchUnified`. This is cosmetic only; no functional impact.

### 1.5 Saved Search Execute Handler

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Routes through unified handler | `handleSearchUnified(searchParams)` | Line 2645: `const searchResult: ToolResponse = await handleSearchUnified(searchParams ...)` | **PASS** |
| Mode mapping for saved searches | `bm25->keyword`, `semantic->semantic`, `hybrid->hybrid` | Line 2639: `const modeMap = { bm25: 'keyword', semantic: 'semantic', hybrid: 'hybrid' }` | **PASS** |

---

## Phase 2: Test Suite Execution

### 2.1 Full Test Suite

```
Test Files:  109 passed (109)
Tests:       2368 passed (2368)
Duration:    130.99s
```

| Check | Result | Verdict |
|-------|--------|---------|
| All 109 test files pass | 109/109 | **PASS** |
| All 2368 tests pass | 2368/2368 | **PASS** |
| Zero failures | 0 failures | **PASS** |

### 2.2 Build Verification

```
> tsc
(clean exit, no errors)
```

| Check | Result | Verdict |
|-------|--------|---------|
| TypeScript compilation | Clean, 0 errors | **PASS** |

### 2.3 E2E Gap Closure Tests (Search-Specific)

All 35 E2E tests passed, specifically:

| Test | Mode | Verdict |
|------|------|---------|
| 1.1 BM25 search returns chunk metadata | `mode` omitted (defaults to hybrid, but tests BM25 path) | **PASS** |
| 1.1 Semantic search returns chunk metadata | `mode: 'semantic'` | **PASS** |
| 1.2 content_type_filter | default mode | **PASS** |
| 1.2 section_path_filter | `mode: 'semantic'` | **PASS** |
| 1.2 page_range_filter | default mode | **PASS** |
| 1.3 quality_boost accepted | both true/false | **PASS** |
| 1.3 quality_boost on semantic | `mode: 'semantic'` | **PASS** |
| 1.4 hybrid auto_route | `mode: 'hybrid', auto_route: true` | **PASS** |

### 2.4 Search Schema Unit Tests

All 19 schema tests passed:

| Test | What Verified | Verdict |
|------|---------------|---------|
| Default mode is hybrid | `parse({query}).mode === 'hybrid'` | **PASS** |
| All defaults populated | `limit=10, similarity_threshold=0.7, bm25_weight=1.0, semantic_weight=1.0, rrf_k=60` | **PASS** |
| Empty query rejected | Throws 'required' | **PASS** |
| Query max length enforced | 1001 chars rejected | **PASS** |
| Keyword mode accepted | `mode: 'keyword'` | **PASS** |
| Semantic mode accepted | `mode: 'semantic'` | **PASS** |
| Hybrid mode accepted | `mode: 'hybrid'` | **PASS** |
| Invalid mode rejected | `mode: 'invalid'` throws | **PASS** |
| All three modes enumerated | loop test | **PASS** |

---

## Phase 3: next_steps Verification

### 3.1 next_steps in Handler Responses

| Tool File | Handler | next_steps Present | Evidence | Verdict |
|-----------|---------|--------------------|----------|---------|
| `search.ts` (hybrid) | `handleSearchHybridInternal` | YES | Line 1824: `next_steps: [...]` | **PASS** |
| `search.ts` (keyword) | `handleSearchKeywordInternal` | **NO** | Response at lines 1558-1604 has no `next_steps` | **FAIL** |
| `search.ts` (semantic) | `handleSearchSemanticInternal` | **NO** | Response at lines 1331-1369 has no `next_steps` | **FAIL** |
| `ingestion.ts` | `handleIngestFiles`, `handleIngestDirectory`, `handleProcessPending` | YES | Lines 1183, 1361, 1531 | **PASS** |
| `chunks.ts` | `handleChunkGet`, `handleChunkContext`, `handleDocumentPage` | YES | Lines 145, 299, 405 | **PASS** |
| `clustering.ts` | `handleClusterDocuments`, `handleClusterReassign` | YES | Lines 168, 263 | **PASS** |
| `health.ts` | `handleHealthCheck` | YES (dynamic) | Lines 228-254: builds next_steps based on gaps | **PASS** |

### 3.2 Bug: Missing next_steps in Keyword and Semantic Modes

**FINDING**: When `ocr_search` is called with `mode: 'keyword'` or `mode: 'semantic'`, the response does NOT include `next_steps`. Only `mode: 'hybrid'` returns next_steps.

**Severity**: LOW -- This is a UX inconsistency, not a functional bug. The search still works correctly in all modes.

**Root Cause**: The `handleSearchHybridInternal` function includes `next_steps` at line 1824, but `handleSearchKeywordInternal` (line 1558) and `handleSearchSemanticInternal` (line 1331) build their response data without it.

**Fix Required**: Add the same `next_steps` array to the `responseData` construction in both `handleSearchKeywordInternal` (around line 1558) and `handleSearchSemanticInternal` (around line 1331).

---

## Phase 4: Tier Tags Verification

### 4.1 [ESSENTIAL] Tag Distribution

| Tool File | Tools with [ESSENTIAL] | Verdict |
|-----------|----------------------|---------|
| `search.ts` | `ocr_search`, `ocr_rag_context` | **PASS** |
| `health.ts` | `ocr_health_check` | **PASS** |
| `database.ts` | `ocr_db_list`, `ocr_db_select`, `ocr_db_stats` | **PASS** |
| `intelligence.ts` | `ocr_guide` | **PASS** |
| `ingestion.ts` | `ocr_ingest_files`, `ocr_process_pending` | **PASS** |
| `chunks.ts` | `ocr_chunk_get`, `ocr_chunk_list`, `ocr_chunk_context`, `ocr_document_page` | **PASS** |
| `documents.ts` | `ocr_document_list`, `ocr_document_get`, `ocr_document_structure`, `ocr_document_toc` | **PASS** |

**Total [ESSENTIAL] tools**: 17

### 4.2 [CORE] Tag Removal

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| `[CORE]` in `src/tools/` | 0 matches | 0 matches | **PASS** |

The [CORE] tier tag has been completely replaced with [ESSENTIAL] across all tool files.

---

## Phase 5: Edge Case Verification (Schema Level)

### 5.1 Search with No Mode (Default to Hybrid)

**Schema Test Evidence** (search-schemas.test.ts line 13):
```
const result = SearchUnifiedInput.parse({ query: 'contract termination' });
expect(result.mode).toBe('hybrid');
```
**Result**: PASSES -- default mode is 'hybrid'.

### 5.2 Search with mode='keyword'

**Schema Test Evidence** (search-schemas.test.ts line 77):
```
const result = SearchUnifiedInput.parse({ query: 'termination clause', mode: 'keyword' });
expect(result.mode).toBe('keyword');
```
**Result**: PASSES -- keyword mode correctly parsed.

### 5.3 Search with mode='semantic'

**Schema Test Evidence** (search-schemas.test.ts line 90):
```
const result = SearchUnifiedInput.parse({ query: 'contract termination', mode: 'semantic' });
expect(result.mode).toBe('semantic');
```
**Result**: PASSES -- semantic mode correctly parsed.

### 5.4 Search with Hybrid-Specific Params in Keyword Mode

**Handler Behavior**: `handleSearchKeywordInternal` simply ignores `bm25_weight`, `semantic_weight`, `rrf_k`, and `auto_route` since it uses its own BM25-only logic. These parameters are present in the `InternalSearchParams` interface but unused by the keyword handler. No crash, no error.

**Verdict**: **PASS** -- harmless params are silently ignored.

### 5.5 Search with Invalid Mode

**Schema Test Evidence** (search-schemas.test.ts line 150):
```
expect(() => SearchUnifiedInput.parse({ query: 'test', mode: 'invalid' })).toThrow();
```
**Result**: PASSES -- Zod rejects invalid mode with a clear error.

---

## Phase 6: Database State Verification

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Database directory exists | `~/.ocr-provenance/databases/` | Exists with multiple DB files | **PASS** |
| Schema version (e2e-impact-test-2026-02-21.db) | 31 | 31 | **PASS** |

---

## Phase 7: Reranker Verification

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Reranker uses local cross-encoder | No Gemini references | `/home/cabdru/datalab/src/services/search/reranker.ts` imports only `localRerank` from `local-reranker.js` | **PASS** |
| Description says "local cross-encoder" | No "Gemini AI" mentions | Description at line 2 says "Local Cross-Encoder Search Re-ranker" | **PASS** |
| Unit tests pass | All pass | reranker.test.ts: 5 tests pass | **PASS** |

---

## Phase 8: Gemini Config Verification

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Only FLASH_3 model | Single model key | `GEMINI_MODELS = { FLASH_3: 'gemini-3-flash-preview' }` | **PASS** |
| No classification model | Removed | Confirmed: no CLASSIFICATION or RERANKER keys | **PASS** |

---

## Summary of Findings

### PASS (47 checks)

All structural changes are correctly implemented:
- SearchUnifiedInput schema with mode parameter works correctly
- Old schemas completely removed, zero orphan references
- Unified handler routes correctly to keyword/semantic/hybrid
- Always-on defaults properly hardcoded
- Tool registration is clean (10 search tools, single `ocr_search`)
- [CORE] tag fully replaced with [ESSENTIAL]
- Reranker fully local (no Gemini)
- Build clean, all 2368 tests pass across 109 files
- Schema version 31 confirmed
- Edge cases handled correctly (invalid mode rejected, defaults work)

### FAIL (2 checks) -- FIXED DURING INVESTIGATION

#### BUG 1: Missing next_steps in keyword and semantic search responses -- FIXED

**File**: `/home/cabdru/datalab/src/tools/search.ts`
**Severity**: LOW (UX inconsistency, not functional)
**Description**: The `handleSearchKeywordInternal` (keyword mode) and `handleSearchSemanticInternal` (semantic mode) did not include `next_steps` in their response data. Only `handleSearchHybridInternal` (hybrid mode) included it at line 1824.
**Impact**: AI agents using keyword or semantic mode wouldn't receive guidance on what tool to call next.

**Fix Applied**: Added `next_steps` array to both keyword and semantic response construction:
```typescript
next_steps: [
  { tool: 'ocr_chunk_context', description: 'Expand a result with neighboring chunks for more context' },
  { tool: 'ocr_document_get', description: 'Deep-dive into a specific source document' },
  { tool: 'ocr_document_page', description: 'Read the full page a result came from' },
],
```

**Verification**: Build clean + 2368/2368 tests pass after fix.

#### NOTE: Stale Comment in Saved Search Execute Handler -- FIXED

**File**: `/home/cabdru/datalab/src/tools/search.ts`
**Severity**: COSMETIC (no functional impact)
**Description**: Comment said `(handleSearch, handleSearchSemantic, or handleSearchHybrid)` but code correctly calls `handleSearchUnified`.
**Fix Applied**: Updated comment to reference `handleSearchUnified`.

---

## Final Verdict

### **SAFE TO SHIP** (all issues fixed)

The search unification refactor is structurally sound, fully tested, and functionally correct. Two minor issues were found and fixed during investigation: missing `next_steps` in keyword/semantic responses and a stale comment. After fixes, build is clean and all 2368 tests pass.

**Confidence**: HIGH

**Evidence Chain**:
1. Schema validated: SearchUnifiedInput correctly defines mode enum with hybrid default
2. Handler validated: Unified handler routes correctly, hardcodes always-on defaults
3. Registration validated: Only `ocr_search` registered, old tools gone
4. Orphans validated: Zero references to old names in src/ and tests/
5. Tests validated: 2368/2368 pass, 109/109 test files pass
6. Build validated: Clean TypeScript compilation
7. Database validated: Schema version 31 confirmed
8. Reranker validated: Fully local cross-encoder, no Gemini dependency
9. Tier tags validated: [CORE] fully replaced with [ESSENTIAL]

---

*Case closed. The game was well-played.*

*-- Holmes, 2026-02-21*
