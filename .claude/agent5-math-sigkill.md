# Agent 5: Math Overflow + SIGKILL Escalation Fixes (M-10, M-11)

## Date: 2026-02-23

## M-10: Math.min/max(...scores) Stack Overflow Risk

### Problem
`Math.min(...array)` / `Math.max(...array)` spreads every element as a function argument. V8 has a hard limit of ~65,536 arguments; exceeding it throws `RangeError: Maximum call stack size exceeded`.

### Fix
Created `src/utils/math.ts` with iterative `safeMin()` and `safeMax()` helpers that return `undefined` for empty arrays (callers use `?? fallback`).

### Locations Fixed (10 occurrences across 3 files)

1. **`src/tools/chunks.ts:260-261`** - Chunk context page range calculation
   - `Math.min(...allPages)` -> `safeMin(allPages) ?? null`
   - `Math.max(...allPages)` -> `safeMax(allPages) ?? null`

2. **`src/tools/reports.ts:188-189`** - VLM confidence min/max (per-document stats)
   - `Math.min(...confidences)` -> `safeMin(confidences) ?? 0`
   - `Math.max(...confidences)` -> `safeMax(confidences) ?? 0`

3. **`src/tools/reports.ts:381-382`** - VLM confidence min/max (document detail)
   - `Math.min(...confidences)` -> `safeMin(confidences) ?? null`
   - `Math.max(...confidences)` -> `safeMax(confidences) ?? null`

4. **`src/tools/search.ts:424-425`** - RAG context page range calculation
   - `Math.min(...allIndices)` -> `(safeMin(allIndices) ?? 0)`
   - `Math.max(...allIndices)` -> `(safeMax(allIndices) ?? 0)`

5. **`src/tools/search.ts:2988-2989`** - Cross-DB BM25 score normalization
   - `Math.min(...scores)` -> `safeMin(scores) ?? 0`
   - `Math.max(...scores)` -> `safeMax(scores) ?? 0`

## M-11: runCommand SIGKILL Escalation

### Problem
`ImageExtractor.runCommand()` spawned child processes with a 10s SIGTERM timeout but no SIGKILL escalation. If Python ignores SIGTERM, zombie processes accumulate.

### Fix
Replicated the SIGKILL escalation pattern from `runPythonExtractorScript()`:
- Added `settled` flag and `sigkillTimer` for proper lifecycle management
- Added `cleanup()` helper to clear timers
- After `timeout + 5000ms`: check if process still alive, send SIGKILL
- If `close` event hasn't fired, settle the promise to prevent zombie hangs
- Handle SIGTERM/SIGKILL signals in the `close` handler

### File Changed
`src/services/images/extractor.ts` - `runCommand()` method (lines 385-403 -> expanded)

## Files Changed
- `src/utils/math.ts` (NEW) - `safeMin()` and `safeMax()` iterative helpers
- `src/tools/chunks.ts` - Added import, replaced 2 spread patterns
- `src/tools/reports.ts` - Added import, replaced 4 spread patterns
- `src/tools/search.ts` - Added import, replaced 4 spread patterns
- `src/services/images/extractor.ts` - SIGKILL escalation in `runCommand()`

## Verification
- Build: `npm run build` passed (0 errors)
- Tests: 2475 passed, 0 failed across 111 test files
- Grep verification: No remaining `Math.min(...` / `Math.max(...` spread patterns in src/
