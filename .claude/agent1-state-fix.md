# Agent 1: Database State Race Condition Fix (H-1, H-2, M-9)

## Date: 2026-02-23

## Issues Fixed

### H-1: validateGeneration() Only Used in ONE Place
- **Root cause**: Generation counter mechanism existed but was only called at step 6 of the ingestion pipeline.
- **Fix**: Created `withDatabaseOperation()` wrapper that automatically calls `beginDatabaseOperation()` before and `endDatabaseOperation()` + `validateGeneration()` after. Applied to `handleProcessPending` and `handleReprocess` -- the two long-running async handlers. Removed the manual `validateGeneration()` call in `processOneDocument()` since the caller now handles it.

### H-2: Global Mutable State Without Async Synchronization
- **Root cause**: `state.currentDatabase`, `state.currentDatabaseName`, and `_cachedVectorService` are global mutable variables. Async handlers yield the event loop at every `await`, allowing interleaved MCP messages to mutate shared state.
- **Fix**: Added `_activeOperations` counter. `selectDatabase()` and `clearDatabase()` throw immediately if `_activeOperations > 0`. `beginDatabaseOperation()` increments the counter, `endDatabaseOperation()` decrements it (never below 0). `withDatabaseOperation()` provides try/finally guarantee.

### M-9: Non-Atomic selectDatabase() Window
- **Root cause**: Between closing the old database (step 2) and opening the new one (step 3), `state.currentDatabase` was null. Any concurrent async handler calling `requireDatabase()` during this window would get a "DATABASE_NOT_SELECTED" error.
- **Fix**: Atomic swap pattern -- open new DB first, swap state variables (single tick, no await), then close old DB. No null window.

## Files Changed

### `src/server/state.ts`
- Added `_activeOperations` counter variable
- Added `beginDatabaseOperation()` -- increments counter, returns generation, throws if no DB
- Added `endDatabaseOperation()` -- decrements counter (floor at 0)
- Added `getActiveOperationCount()` -- diagnostic/test helper
- Added `withDatabaseOperation<T>(fn)` -- async wrapper with try/finally + generation validation
- Modified `selectDatabase()` -- added operation guard (throws if ops in-flight), atomic swap (open new, swap state, close old)
- Modified `clearDatabase(forceClose?)` -- added operation guard (throws if ops in-flight unless forceClose=true)
- Modified `resetState()` -- resets `_activeOperations` to 0, uses `forceClose=true` for clearDatabase

### `src/tools/ingestion.ts`
- Changed import: replaced `validateGeneration` with `withDatabaseOperation`
- `handleProcessPending`: wrapped body in `withDatabaseOperation()` callback
- `handleReprocess`: wrapped body in `withDatabaseOperation()` callback
- `processOneDocument`: removed manual `validateGeneration(generation)` call, removed `generation` from destructuring (no longer needed locally)

## Design Decisions

1. **forceClose on clearDatabase**: Tests call `resetState()` unconditionally between test cases. Without `forceClose`, this would throw if a test left operations tracked. Process exit cleanup also needs to bypass the guard.

2. **Not wrapping every handler**: Only `handleProcessPending` and `handleReprocess` need `withDatabaseOperation()` because they are the only handlers that do significant async work (OCR, embedding, VLM) across many await points. Read-only or synchronous handlers don't yield the event loop, so they're safe with plain `requireDatabase()`.

3. **generation field kept in ProcessOneDocumentParams**: The interface still has `generation` even though `processOneDocument` no longer uses it directly. Callers pass it through, and removing it from the interface would be a larger refactor. The TS compiler is fine with unused object properties.

## Verification

- Build: `npm run build` -- 0 errors
- Tests: `npm test` -- 2475 passed, 0 failed across 111 test files
- State tests: 45 passed (existing tests cover selectDatabase, clearDatabase, resetState)
- Ingestion handler tests: 22 passed (covers handleProcessPending, handleReprocess error paths)
