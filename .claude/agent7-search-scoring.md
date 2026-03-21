# Agent 7: Search Scoring Fixes (L-1, L-2)

## Date: 2026-02-23

## Issue L-1: Quality Multiplier Applied Twice in Hybrid Search

**Problem**: In hybrid search mode, `computeQualityMultiplier` was applied three times:
1. In BM25 handler (`bm25.ts` via `applyQualityAndRerank`)
2. In semantic handler (`vector.ts` via `computeQualityMultiplier`)
3. In RRF fusion (`fusion.ts` line 227)

A document with quality score 0 got 0.64x effective multiplier (0.8 * 0.8) in hybrid mode instead of the intended 0.8x in standalone modes.

**Fix**: Removed the quality multiplier application from `fusion.ts` (lines 225-228) and removed the unused `computeQualityMultiplier` import. BM25 and semantic handlers already apply quality weighting to their individual scores before fusion. Added a comment explaining why fusion does not re-apply quality.

**Files changed**:
- `src/services/search/fusion.ts` - Removed quality multiplier block and import
- `tests/unit/services/search/vlm-search-integration.test.ts` - Updated test expectation (line 871-875) to expect raw RRF score without quality multiplier

## Issue L-2: Cross-DB Single-Result Databases Get Inflated Score of 1.0

**Problem**: In `ocr_search_cross_db`, when a database returns only 1 result (or all results have the same BM25 score), min-max normalization produces `range = 0`, and the fallback was `normalized_score = 1.0`. This meant a single low-quality result would get the maximum normalized score, potentially outranking genuinely good results from larger databases.

**Fix**: Changed the fallback from `1.0` to `0.5` (neutral midpoint). This prevents single-result databases from artificially outranking multi-result databases while not penalizing them unfairly either.

**File changed**:
- `src/tools/search.ts` - Line 2993-2995: Changed `1.0` to `0.5` in normalized_score fallback

## Verification
- Build: Clean (0 errors)
- Tests: 2475 passed, 0 failed across 111 test files
