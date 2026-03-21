# Agent 2: VLM Page Range Filter Fix (M-1)

## Date: 2026-02-23

## Issue Fixed

### M-1: Vector Search pageRangeFilter NEVER Applied to VLM Results
- **Root cause**: `mapAndFilterResults()` in `vector.ts` accepted `_options` (underscore-prefixed = unused parameter). The `pageRangeFilter` was defined in `VectorSearchOptions` and passed by callers (`searchWithFilter`, `searchAll`) but never actually applied to results. VLM/extraction results were silently returned even when they fell outside the requested page range.
- **Impact**: Users searching with `page_range_filter` in semantic or hybrid mode would silently miss or include wrong VLM image descriptions. BM25 path was not affected (applies filter correctly in SQL at bm25.ts:307-316).

## Fix Applied

### `src/services/storage/vector.ts`
1. **Renamed `_options` to `options`** in `mapAndFilterResults()` signature (line 581) -- parameter is now used.
2. **Added pageRangeFilter post-query filtering** (lines 627-638): After mapping rows to results but before slicing to limit, VLM/extraction results (where `chunk_id === null`) are filtered by `page_number` against `min_page`/`max_page`. Chunk results pass through since they are already filtered by SQL chunk filter conditions.
3. **Moved `.slice(0, limit)` after VLM filtering** (line 642): Previously, limit was applied before any VLM filtering, meaning filtered-out VLM results would reduce the final count below the requested limit even when valid results existed. Now the limit is applied after all filtering, using the `limit * 2` over-fetch from the SQL queries as headroom.
4. **Updated comment in `buildChunkFilterSQL()`** (lines 389-391): Clarified that VLM page range filtering is now actually applied in `mapAndFilterResults`, not just claimed to be.

## Design Decisions

1. **Post-query filtering (not SQL)**: VLM/extraction results and chunk results are mixed in vector search queries. Chunk results use `ch.page_number` (from chunks table JOIN), while VLM results use `e.page_number` (from embeddings table). Adding SQL conditions for VLM page filtering would require complex CASE/OR logic that complicates the query. Post-query filtering is simple, correct, and consistent with the existing architecture comment.

2. **Exclude null page_number when filtering**: If a VLM result has no `page_number` and the user explicitly requests a page range, we exclude it. This is the fail-safe behavior -- returning results with unknown page location when the user asked for a specific range is incorrect.

3. **Filter before limit, not after**: The original code did `.filter(distance).slice(limit).map()`. The fix changes this to `.filter(distance).map().filter(pageRange).slice(limit)`. This ensures the user gets up to `limit` results even when some VLM results are filtered out, since the SQL queries already fetch `limit * 2` rows.

## Files Changed

- `src/services/storage/vector.ts` -- Fixed `mapAndFilterResults()` to apply pageRangeFilter to VLM/extraction results; updated comment in `buildChunkFilterSQL()`

## Verification

- Build: `npm run build` -- 0 errors
- Tests: `npm test` -- 2475 passed, 0 failed across 111 test files
- No conflicts with Agent 1 changes (Agent 1 modified `src/server/state.ts` and `src/tools/ingestion.ts`)
