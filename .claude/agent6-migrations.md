# Agent 6: Migration Atomicity Fixes (M-5, M-6, L-5, L-15)

## Date: 2026-02-23

## Issues Fixed

### M-5: Migration v19→v20 Non-Atomic with Foreign Keys Risk
**File**: `src/services/storage/migrations/operations.ts` (migrateV19ToV20)

**Problem**: 5 ALTER TABLE statements and CREATE TABLE operations without a transaction. `PRAGMA foreign_keys = OFF` was not wrapped in try-finally, so a crash could leave foreign keys disabled.

**Fix**:
- Moved `PRAGMA foreign_keys = OFF` before try block, `PRAGMA foreign_keys = ON` into a `finally` block so it ALWAYS re-enables even on crash.
- Wrapped all regular DDL (ALTER TABLE, CREATE TABLE, CREATE INDEX) in an explicit `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK` block.
- Moved virtual table creation (`CREATE VIRTUAL TABLE ... USING vec0`) outside the transaction since vec0 may not support transactional DDL.
- FK integrity check runs after transaction commit.

### M-6: Migration v20→v21 Non-Atomic
**File**: `src/services/storage/migrations/operations.ts` (migrateV20ToV21)

**Problem**: DROP TABLE + CREATE TABLE + CREATE VIRTUAL TABLE without a transaction.

**Fix**:
- Same pattern as M-5: `PRAGMA foreign_keys = OFF/ON` in try-finally.
- DROP TABLE + CREATE TABLE + CREATE INDEX wrapped in `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK`.
- Virtual table operations (vec0 DROP + CREATE) placed outside transaction.
- FK integrity check after all DDL.

### L-5: Migrations v27→v29 Not Wrapped in Transactions
**File**: `src/services/storage/migrations/operations.ts` (migrateV27ToV28, migrateV28ToV29)

**Problem**: CREATE TABLE + CREATE INDEX without transaction wrapper.

**Fix**:
- Both migrations now use `db.transaction(() => { ... })()` to wrap all DDL atomically.
- v27→v28: saved_searches table + 3 indexes in one transaction.
- v28→v29: tags + entity_tags tables + 2 indexes in one transaction.

### Bonus: v29→v30 Also Not Wrapped
**File**: `src/services/storage/migrations/operations.ts` (migrateV29ToV30)

**Problem**: FTS5 virtual table creation, triggers, FTS population, ALTER TABLE, and CREATE INDEX all without transaction.

**Fix**:
- FTS5 virtual table creation and triggers remain outside transaction (virtual table DDL limitations).
- FTS population (delete-all + INSERT), ALTER TABLE columns, and CREATE INDEX wrapped in `db.transaction()`.

### L-15: VLM FTS Rebuild Not in Transaction
**File**: `src/services/search/bm25.ts` (rebuildVLMIndex)

**Problem**: `delete-all` then `INSERT INTO vlm_fts` as two separate statements. A crash between them leaves an empty VLM FTS index.

**Fix**:
- Wrapped the entire rebuild (delete-all + INSERT + COUNT + fts_index_metadata upsert) in `this.db.transaction(() => { ... })()`.
- The transaction returns the count, which is used for the return value.

## Files Changed
- `src/services/storage/migrations/operations.ts` - migrateV19ToV20, migrateV20ToV21, migrateV27ToV28, migrateV28ToV29, migrateV29ToV30
- `src/services/search/bm25.ts` - rebuildVLMIndex

## Verification
- Build: PASS (tsc clean)
- Tests: 2475 passed, 0 failed across 111 test files

## Design Notes
- Virtual table operations (vec0, FTS5 CREATE VIRTUAL TABLE) are placed outside transactions because they manage their own shadow tables and may not support transactional DDL rollback in all SQLite builds.
- FTS5 DML operations (delete-all, INSERT INTO fts) DO work within transactions and are wrapped accordingly.
- `PRAGMA foreign_keys` uses try-finally pattern (not transaction) because PRAGMA statements are not transactional in SQLite.
