# Agent 8: Dead Code Cleanup + Misc Fixes

## Issues Fixed

### L-8: Dead Exports Removed (3 items, 1 dead file)
1. **`parseGeminiJson`** in `src/tools/shared.ts` - Deleted entire function (lines 58-108). Zero importers confirmed by grep. Was used by removed Gemini non-VLM features.
2. **`src/services/chunking/chunk-deduplicator.ts`** - Deleted entire file. Zero importers in src/ or tests/. Only referenced in README.md.
3. **`batchedQuery`** in `src/services/storage/database/helpers.ts` - Deleted function + `DEFAULT_BATCH_SIZE` constant. Zero importers confirmed.

### L-9: Schema Definition Constants - NOT DELETED
`schema-definitions.ts` is imported by 4 files (operations.ts, schema-helpers.ts, verification.ts, bm25.ts). The `CREATE_*_TABLE` constants ARE used by TABLE_DEFINITIONS, schema-helpers createTables(), and operations.ts migrations. File is NOT dead code.

### L-11: Empty timeline.ts Module - DELETED
- Deleted `src/tools/timeline.ts` (empty stub with 0 tools)
- Removed `import { timelineTools }` from `src/index.ts`
- Removed `timelineTools` from `allToolModules` array in `src/index.ts`
- Updated `tests/unit/tools/timeline.test.ts`: removed timelineTools import and empty-check test
- Updated `tests/manual/guide-e2e-test.test.ts`: removed timelineTools import and usage
- Updated `tests/manual/gap-closure-manual.test.ts`: removed timelineTools import, migrated 3 test cases to use `reportTools.ocr_trends` with proper metric params

### L-3: VLM FTS Update Trigger WHEN Clause Gap - DOCUMENTED
The UPDATE trigger (`vlm_fts_au`) only fires on `original_text` changes when `new.image_id IS NOT NULL`. If `image_id` were set from non-null to null, the stale FTS entry remains. However, `image_id` is immutable after INSERT (never updated in any code path), so this is a theoretical gap only. Added explanatory comment to `schema-definitions.ts`.

### L-12: Search Analytics Silent Failure - Made Visible
In `src/tools/search.ts` `handleSearchSaved` execute action: when analytics UPDATE fails (pre-v30 databases missing `last_executed_at`/`execution_count` columns), now:
- Sets `analyticsWarning` string with error details
- Includes `warning` field in the response so callers know analytics tracking is unavailable
- Still logs via console.error (non-fatal)

### L-16: Coverage Thresholds Added to vitest.config.ts
Added thresholds under coverage config:
- lines: 70
- branches: 60
- functions: 70
- statements: 70

## Files Changed
- `src/tools/shared.ts` - Removed `parseGeminiJson` function
- `src/services/chunking/chunk-deduplicator.ts` - DELETED
- `src/services/storage/database/helpers.ts` - Removed `batchedQuery` function + `DEFAULT_BATCH_SIZE`
- `src/tools/timeline.ts` - DELETED
- `src/index.ts` - Removed timelineTools import and array entry
- `src/services/storage/migrations/schema-definitions.ts` - Added L-3 gap documentation comment
- `src/tools/search.ts` - Made analytics failure visible in response (L-12)
- `vitest.config.ts` - Added coverage thresholds (L-16)
- `tests/unit/tools/timeline.test.ts` - Removed timelineTools import and dead test
- `tests/manual/guide-e2e-test.test.ts` - Removed timelineTools references
- `tests/manual/gap-closure-manual.test.ts` - Migrated tests from timelineTools to reportTools

## Verification
- Build: `npm run build` - SUCCESS (0 errors)
- Tests: 111 files passed, 2474 tests passed, 0 failed
- Test count delta: -1 (removed timelineTools empty-check test)
