# Agent 3: Type Safety Fixes (M-7, M-8)

## Date: 2026-02-23

## Issues Fixed

### M-7: `as unknown as` Double Casts Hiding Type-Unsafe Fallback Objects
- **Root cause**: `parseLocation()` and `parseVLMStructuredData()` in converters.ts returned `{ _parse_error: true, _raw: raw }` cast via `as unknown as ProvenanceLocation`/`VLMStructuredData` on JSON.parse failure. No downstream consumer checks `_parse_error` (zero references). Accessing `.page_number` or `.imageType` on corrupt data silently returns `undefined` instead of failing fast.
- **Fix**: Changed both functions to return `null` on parse failure instead of the fake double-cast objects. Kept `console.error` logging for diagnostics.
- **Why null is safe**: `ProvenanceRecord.location` is already typed `ProvenanceLocation | null`. `ImageReference.vlm_structured_data` is already typed `VLMStructuredData | null`. All downstream consumers already guard with null checks (`if (record.location)`, `?.` optional chaining, ternary null checks). Verified all 11 consumer sites.

### M-8: Runtime Property Injection in Cross-DB Search
- **Root cause**: `normalized_score` was injected at runtime via `(r as Record<string, unknown>).normalized_score` and read back via the same cast. No type-level representation existed for this property.
- **Fix**: Created `CrossDBSearchResult` interface that includes all fields from the inline type literal plus `normalized_score: number`. Changed `allResults` to use `CrossDBSearchResult[]`. Initialized `normalized_score: 0` at push time. Removed all 3 `Record<string, unknown>` casts. Sort now uses direct property access: `b.normalized_score - a.normalized_score`.

## Files Changed

### `src/services/storage/database/converters.ts`
- `parseLocation()`: Return type changed from `ProvenanceLocation` to `ProvenanceLocation | null`. Catch block returns `null` instead of double-cast fake object.
- `parseVLMStructuredData()`: Return type changed from `VLMStructuredData` to `VLMStructuredData | null`. Catch block returns `null` instead of double-cast fake object.
- Comments updated to explain why null is safe (callers already handle it).

### `src/tools/search.ts`
- Added `CrossDBSearchResult` interface (8 fields including `normalized_score: number`) before `handleCrossDbSearch`.
- `allResults` typed as `CrossDBSearchResult[]` instead of inline `Array<{...}>` (7 fields, missing normalized_score).
- `allResults.push()` includes `normalized_score: 0` initialization.
- Normalization loop: `(r as Record<string, unknown>).normalized_score = ...` -> `r.normalized_score = ...`
- Sort: `((b as Record<string, unknown>).normalized_score as number)` -> `b.normalized_score`

## No Conflicts with Other Agents

- Agent 1 modified `src/server/state.ts` and `src/tools/ingestion.ts` -- no overlap.
- Agent 2 modified `src/services/storage/vector.ts` -- no overlap.

## Verification

- Build: `npm run build` -- 0 errors
- Tests: `npm test` -- 2475 passed, 0 failed across 111 test files
