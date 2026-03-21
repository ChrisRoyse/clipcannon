# ClipCannon Test Suite

Current state of the testing infrastructure as of 2026-03-21.

## Pytest Configuration

Defined in `pyproject.toml` under `[tool.pytest.ini_options]`:

| Setting | Value | Purpose |
|---------|-------|---------|
| `testpaths` | `["tests"]` | Pytest discovers tests from the `tests/` directory |
| `asyncio_mode` | `"auto"` | All `async def test_*` functions run under pytest-asyncio automatically |
| `pythonpath` | `["src"]` | Adds `src/` to `sys.path` so `clipcannon.*` imports resolve without installation |

Dev dependencies (`[project.optional-dependencies] dev`):
- `pytest>=8.0`
- `pytest-asyncio>=0.23.0`
- `ruff>=0.4.0`

---

## Test Files

### Unit Tests

#### `tests/test_pipeline_stages.py` -- 12 tests

Tests probe, audio extraction, and frame extraction against a real test video. Uses module-scoped fixtures so expensive FFmpeg operations run only once.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestProbeStage` | 2 | Metadata extraction (duration, resolution, fps, codec, SHA-256); provenance record written |
| `TestAudioExtractStage` | 2 | Produces `audio_16k.wav` and `audio_original.wav`; provenance record written |
| `TestFrameExtractStage` | 2 | Produces ~420 JPEG frames at 2fps for 210s video; provenance record count matches |
| `TestSourceResolution` | 1 | Resolves to original file path when no VFR normalization is needed |
| `TestTopologicalSort` | 3 | Linear chain ordering; parallel stages at same level; diamond DAG resolution |
| `TestOrchestratorRegistration` | 2 | Register and list stages; duplicate registration raises `PipelineError` |

#### `tests/test_billing.py` -- 40 tests

Tests HMAC integrity, credit rates, spending limits, license server API, D1 sync, and Stripe webhooks.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestMachineId` | 2 | Deterministic machine ID; 32-char hex format |
| `TestHmacSigning` | 8 | Deterministic signature; different balance/machine produces different sigs; verify valid/tampered balance; verify-or-raise; HMAC key is 32 bytes |
| `TestCreditRates` | 3 | Known operation costs; unknown operation raises `BillingError`; `CREDIT_RATES` dict completeness |
| `TestSpendingLimit` | 4 | Within limit; at limit; over limit; zero spending |
| `TestSpendingWarning` | 4 | No warning below 80%; warning at 80%; warning at 100%; no warning when limit is zero |
| `TestLicenseServer` | 12 | Health check; initial balance (100 credits); charge; insufficient credits; idempotency prevents double-charge; refund; refund unknown transaction (404); transaction history; add credits (dev); set spending limit; spending limit enforcement; tamper detection (403); force sync |
| `TestD1Sync` | 3 | `sync_push` local-only; `sync_pull` local-only; `is_d1_configured` returns false without env vars |
| `TestStripeWebhooks` | 1 | PACKAGES dict contains starter (50), creator (250), pro (1000), studio (5000) |

All license server tests use a temporary SQLite database via `unittest.mock.patch` to avoid affecting real data.

#### `tests/test_understanding_tools.py` -- 22 tests

Tests VUD summary, analytics, transcript retrieval, segment detail, storyboard, search, and error handling. Uses a synthetic database populated with speakers, transcript segments, topics, highlights, reactions, emotion curve, beats, content safety, scenes, and storyboard grids.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestGetVudSummary` | 3 | Returns full summary structure (speakers, topics, highlights, reactions, stream status); response under 8K tokens (~32KB); nonexistent project returns `PROJECT_NOT_FOUND` |
| `TestGetAnalytics` | 4 | All sections returned by default; specific section filtering; invalid section returns `INVALID_PARAMETER`; scenes include pagination metadata |
| `TestGetTranscript` | 4 | Default 15-minute window returns all 5 segments; time range filter (0-12000ms returns 3 segments); word-level timestamps included; `has_more` flag and `next_start_ms` for pagination |
| `TestGetSegmentDetail` | 2 | Returns all streams (transcript, emotion curve, speakers, reactions, pacing, scenes/quality, silence gaps); invalid range (end <= start) returns error |
| `TestGetStoryboard` | 2 | Batch query returns correct grid count; time range query returns overlapping grids |
| `TestSearchContent` | 3 | Text search finds matching segments ("machine learning"); no-results query returns 0; invalid search type returns error |
| `TestErrorHandling` | 4 | `PROJECT_NOT_FOUND` for VUD summary, analytics, and transcript on nonexistent project; `INVALID_STATE` when project status is not "ready" |

#### `tests/test_provenance_integration.py` -- 19 tests

Tests the full provenance lifecycle: hash computation, chain integrity, tamper detection, and record retrieval.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestHasher` | 7 | SHA-256 file hashing; streaming hash for large files; bytes hashing (verified against known digest); string hashing; file hash verification (match and mismatch); nonexistent file raises `ProvenanceError`; table content hashing (deterministic) |
| `TestChain` | 4 | Deterministic chain hash computation; different parent hash produces different chain hash; record 3-entry chain and verify integrity; tampered chain detected at correct record |
| `TestRecorder` | 5 | Record ID format (`prov_NNN`); retrieve single record with all fields; missing record returns `None`; filter records by operation; timeline retrieval |
| (root) | 3 | `get_chain_from_genesis` walks chain correctly; empty chain verification succeeds with 0 records; (included in TestChain/TestRecorder) |

#### `tests/test_visual_pipeline.py` -- 34 tests

Tests storyboard generation, quality assessment, visual embedding helpers, OCR helpers, shot type constants, and module imports. Uses synthetic frames generated with Pillow.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestStoryboard` | 7 | Generates 3 grid files (20 frames / 9 per grid); grid dimensions are 1044x1044; DB records match (timestamps JSON, cell counts); provenance written; graceful failure with no frames; timestamp formatting; frame subsampling when over 720 limit |
| `TestQuality` | 6 | BRISQUE-to-quality conversion (0-100 scale, clamping); quality classification thresholds (good/acceptable/poor); blur detection; camera shake detection; clean footage (no issues); Laplacian fallback produces 0-100 scores; quality updates scene records |
| `TestVisualEmbedHelpers` | 5 | Cosine similarity of identical vectors is 1.0; orthogonal vectors is 0.0; frame timestamp calculation; dominant color extraction returns hex strings; scene detection from embeddings |
| `TestOCRHelpers` | 6 | Region classification (top, middle, bottom third); font size estimation (small, large); text change detection (added, removed, same, partial overlap) |
| `TestShotTypeHelpers` | 2 | All shot types have crop recommendations; expected labels in correct order |
| `TestModuleImports` | 6 | Imports for visual_embed, ocr, quality, shot_type, storyboard; pipeline `__init__` exports all visual stages |

#### `tests/test_derived_stages.py` -- 14 tests

Tests profanity detection, chronemic analysis, highlight scoring, finalize stage, and the full derived pipeline sequence.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestWordlistLoading` | 3 | Bundled word list file exists; contains 100+ words; contains severe, moderate, and mild severities |
| `TestContentRating` | 4 | Clean (0 matches); mild (1-3); moderate (4-10); explicit (11+) |
| `TestProfanityStage` | 1 | Detects profanity words (damn, shit, crap, sucks) and inserts profanity_events and content_safety records |
| `TestChronemicStage` | 1 | Computes 3 pacing windows (180s / 60s); valid WPM, pause ratio, and pacing labels |
| `TestHighlightsStage` | 1 | Scores candidate windows with all 7 component scores populated (emotion, reaction, semantic, narrative, visual, quality, speaker) |
| `TestFinalizeStage` | 3 | Sets project status to "ready"; verifies provenance chain; cleans temp files (.tmp, .part) |
| `TestFullDerivedPipeline` | 1 | Runs profanity -> chronemic -> highlights -> finalize in sequence; verifies all tables populated, all streams tracked, status is "ready", provenance chain verified with 4+ records |

### Dashboard Tests

#### `tests/dashboard/test_dashboard.py` -- 18 tests

Tests the FastAPI dashboard application endpoints, authentication, and API routes.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestHealth` | 1 | `/health` returns status "ok" with version and service name |
| `TestAuth` | 5 | Dev login sets session cookie; `/auth/me` returns authenticated user in dev mode; logout clears cookie; JWT token creation/verification roundtrip; invalid token returns `None` |
| `TestCredits` | 4 | Balance endpoint returns balance and spending_limit; history returns transaction list; packages endpoint returns packages with price/credit structure; add credits in dev mode |
| `TestProjects` | 3 | List projects returns array with count; project detail returns `found: false` for missing project; project status returns `not_found` for missing project |
| `TestProvenance` | 3 | Records endpoint handles missing project (count: 0); verify endpoint returns `verified: false` for missing project; timeline endpoint returns count: 0 for missing project |
| `TestHomePage` | 2 | `/` serves HTML containing "ClipCannon"; `/api/overview` returns version, GPU info, system health, and recent projects |

### Integration Tests

#### `tests/integration/test_full_pipeline.py` -- 22 tests

Runs the complete pipeline on a real test video (209.9s, 2560x1440, 60fps h264). Uses module-scoped fixtures so FFmpeg operations run only once. Requires: ffmpeg, numpy, scipy, Pillow, pydantic.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestProbe` | 2 | Probe succeeds; metadata matches expected values (duration 209-210s, 2560x1440, 60fps, h264, 64-char SHA-256) |
| `TestAudioExtract` | 2 | Audio extraction succeeds; both WAV files exist and are larger than 1MB |
| `TestFrameExtract` | 2 | Frame extraction succeeds; frame count is 400-440 (2fps for 210s) |
| `TestFullPipeline` | 14 | All 9 stages succeed; project metadata correct; audio files on disk; frames on disk; storyboard grids in DB and on disk (1044x1044); acoustic data; beats data; pacing data with required fields; content safety rating; highlights scored; all streams marked "completed"; provenance records with 64-char chain hashes; provenance chain integrity end-to-end |
| `TestEdgeCases` | 3 | Nonexistent video returns `INVALID_PARAMETER` error; fresh project provenance verification passes with 0 records; tampered provenance data is detected |

---

## FSV (Full State Verification) Tests

FSV scripts are standalone Python scripts (not collected by pytest) that perform forensic-grade verification with physical evidence printing. They import modules directly, create synthetic databases, and verify every assertion by inspecting source-of-truth data.

### `tests/fsv_core_infrastructure.py`

**Domain**: Database, Config, GPU, Provenance

10 test functions covering:
- Exceptions module (class hierarchy, message/details, stage_name/operation)
- Database connection manager (WAL mode, pragmas, dict_rows, auto-created parent dirs)
- Database schema (23 tables, schema_version, 9 indexes, idempotent creation)
- Query helpers (table_exists, batch_insert, fetch_all, fetch_one, count_rows, transactions, rollback)
- Configuration (dot-notation get, Pydantic validation, set/save/reload cycle)
- GPU manager (device detection, memory reporting)
- Provenance hasher (file hashing, bytes hashing, table content hashing)
- Provenance chain (deterministic hash, parent differentiation, 3-record chain verification, tamper detection)
- Provenance recorder (record ID format, retrieval, filtering, timeline)
- SHA-256 table content verification

### `tests/fsv_pipeline_tools.py`

**Domain**: 20 pipeline stages, 15 MCP tools, DAG resolution, graceful degradation

8 test sections covering:
- DAG dependency resolution (topological sort, cycle detection, empty list, real pipeline levels, probe at level 0, finalize at last level)
- Pipeline stage registration (20 stages defined, no duplicates, duplicate rejection)
- Required vs optional classification (6 required, 14 optional)
- Pipeline stage function signatures (all 20 are async, all accept project_id/db_path/project_dir/config)
- Graceful degradation (optional failure does not abort pipeline, required failure does)
- MCP tool tests with synthetic DB (project_list, project_status, get_vud_summary, get_analytics, get_transcript, get_segment_detail, get_frame, get_storyboard, search_content, provenance_verify, provenance_query, provenance_chain, provenance_timeline, disk_status, config_get/config_list)
- Edge case tests (nonexistent project, invalid parameters, empty search, out-of-range timestamps)
- Direct DB cross-verification (physical SELECT against every populated table)

### `tests/fsv_billing_dashboard.py`

**Domain**: HMAC, Credits, License Server, Dashboard Auth

8 test sections covering:
- HMAC integrity (machine ID format and determinism, sign/verify balance, tamper detection, edge cases: zero/negative/large balance, empty machine ID, verify_or_raise)
- Credit system (rate table, estimate_cost, unknown operation error, spending limit validation, spending warnings at 80%/100%, credit packages)
- License server (FastAPI routes, SQLite schema with 3 tables, HMAC-signed balance operations, charge/refund cycle, idempotency key constraint)
- Billing MCP tools (4 tool definitions, input schemas, dispatch routing, unknown tool error, negative limit rejection)
- Dashboard (FastAPI app creation, health endpoint, auth endpoints, credits API, projects API, provenance API, overview endpoint, static HTML)
- D1 sync module (sync_push/sync_pull local-only, is_d1_configured)
- Stripe webhooks (PACKAGES dict, price calculations)
- Cross-module integration (billing-to-dashboard flow, config-to-tools consistency)

### `tests/fsv_server_integration.py`

**Domain**: MCP server scaffold, 27 tools, dispatchers

6 test sections covering:
- Server creation (returns `Server` instance, name is "ClipCannon", version matches `__version__`)
- Tool registry completeness (27 tools registered, each expected tool present, no unexpected tools, category counts: 5 project, 9 understanding, 4 provenance, 2 disk, 3 config, 4 billing)
- Dispatcher completeness (27 dispatchers, each maps to a tool, all are callable)
- Unknown tool error handling (`UNKNOWN_TOOL` error code, tool name in message, available_tools list)
- Default configuration validation (config file exists, 6 required sections, specific value checks for whisper_model, frame_extraction_fps, scene_change_threshold)
- Tool definition schema integrity (every tool has name, description, inputSchema with type "object" and properties)

---

## Test Count Summary

| Category | File Count | Test Count |
|----------|-----------|------------|
| Unit tests | 6 | 141 |
| Dashboard tests | 1 | 18 |
| Integration tests | 1 | 22 |
| **Pytest total** | **8** | **181** |
| FSV: Core Infrastructure | 1 | ~154 checks |
| FSV: Pipeline + Tools | 1 | ~189 checks |
| FSV: Billing + Dashboard | 1 | ~84 checks |
| FSV: Server Integration | 1 | ~323 checks |
| **FSV total** | **4** | **~750 checks** |

---

## Running Tests

### Run the full pytest suite

```bash
cd /home/cabdru/clipcannon
pytest
```

### Run with verbose output

```bash
pytest -v
```

### Run a specific test file

```bash
pytest tests/test_billing.py
pytest tests/dashboard/test_dashboard.py
pytest tests/integration/test_full_pipeline.py
```

### Run a specific test class or function

```bash
pytest tests/test_billing.py::TestHmacSigning
pytest tests/test_billing.py::TestHmacSigning::test_sign_balance_returns_hex
```

### Run only fast tests (skip integration tests requiring test video)

```bash
pytest tests/test_billing.py tests/test_understanding_tools.py tests/test_provenance_integration.py tests/dashboard/test_dashboard.py
```

### Run FSV scripts (standalone, not via pytest)

```bash
python tests/fsv_core_infrastructure.py
python tests/fsv_pipeline_tools.py
python tests/fsv_billing_dashboard.py
python tests/fsv_server_integration.py
```

### Lint

```bash
ruff check src/
```

Ruff is configured in `pyproject.toml` with rules: E, F, W, I, N, UP, ANN, B, SIM, TCH. Target version is Python 3.12, line length 100, source root is `src/`.
