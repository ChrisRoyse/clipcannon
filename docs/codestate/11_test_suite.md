# ClipCannon Test Suite

Current state of the testing infrastructure.

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

### Shared Fixtures

#### `tests/conftest.py` -- Session-scoped fixtures

Session-scoped fixtures that run expensive FFmpeg operations once and share results across all test modules.

| Fixture | Scope | Description |
|---------|-------|-------------|
| `clipcannon_config` | session | Single config load for entire session |
| `session_project_dir` | session | Shared temporary project directory |
| `session_probed_project` | session | Runs probe once, returns (project_id, db_path, project_dir, config, result) |
| `session_audio_extracted` | session | Runs audio extraction once (depends on probe) |
| `session_frames_extracted` | session | Runs frame extraction once (depends on probe) |

Test video: `testdata/2026-03-20 14-43-20.mp4` (209.9s, 2560x1440, 60fps h264).

#### `tests/integration/conftest.py` -- Module-scoped integration fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `pipeline_project` | module | Creates project directory with stream_status rows |
| `probe_result` | module | Runs probe once per module |
| `audio_result` | module | Audio extraction (depends on probe) |
| `frame_result` | module | Frame extraction (depends on probe) |
| `full_pipeline_results` | module | Full pipeline chain (probe -> finalize) |

### Phase 1 Unit Tests

#### `tests/test_pipeline_stages.py` -- 12 tests

Tests probe, audio extraction, frame extraction, DAG resolution, and orchestrator registration.

#### `tests/test_billing.py` -- 40 tests

HMAC integrity, credit rates, spending limits, license server API, D1 sync, Stripe webhooks.

#### `tests/test_understanding_tools.py` -- 20 tests

VUD summary, analytics, transcript, segment detail, search, error handling.

#### `tests/test_provenance_integration.py` -- 19 tests

Hash computation, chain integrity, tamper detection, record retrieval.

#### `tests/test_visual_pipeline.py` -- 34 tests

Storyboard generation, quality assessment, visual embedding, OCR, shot type.

#### `tests/test_derived_stages.py` -- 14 tests

Profanity detection, chronemic analysis, highlight scoring, finalize stage.

### Phase 2 Unit Tests

#### `tests/test_edl.py` -- 19 tests

EDL model creation, duration computation, platform constraints, transitions, and sub-models.

#### `tests/test_captions.py` -- 14 tests

Caption chunking, timestamp remapping, ASS generation, and drawtext filters.

#### `tests/test_smart_crop.py` -- 15 tests

Crop region computation, scene-based strategies, position smoothing, and aspect ratio parsing.

#### `tests/test_editing_tools.py` -- 10 tests (async)

Create/modify/list edits, metadata generation with a complete Phase 2 database.

#### `tests/test_rendering.py` -- 14 tests

Encoding profiles, software fallback, platform dimensions, and generation loss prevention.

#### `tests/test_audio_generation.py` -- 15 tests

All 9 SFX types (whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger), all 6 MIDI presets.

### Dashboard Tests

#### `tests/dashboard/test_dashboard.py` -- 18 tests

Phase 1 dashboard endpoints.

#### `tests/test_dashboard_phase2.py` -- 12 tests

Timeline, editing, review API endpoints.

### Integration Tests

#### `tests/integration/test_full_pipeline.py` -- 22 tests

Full pipeline integration with real test video.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestProbe` | 2 | Metadata extraction, value validation |
| `TestAudioExtract` | 2 | WAV file generation, size validation |
| `TestFrameExtract` | 2 | Frame count validation |
| `TestFullPipeline` | 10+ | All stages succeed, DB contents, provenance chain |
| `TestEdgeCases` | 3+ | Nonexistent video, fresh project, tamper detection |

---

## FSV (Full State Verification) Tests

### Phase 1 FSV Scripts (4 scripts)

| Script | Checks | Domain |
|--------|--------|--------|
| `tests/fsv_core_infrastructure.py` | ~154 | Exceptions, DB, schema, config, GPU, provenance |
| `tests/fsv_pipeline_tools.py` | ~189 | DAG resolution, stage registration, MCP tools |
| `tests/fsv_billing_dashboard.py` | ~84 | HMAC, credits, license server, dashboard |
| `tests/fsv_server_integration.py` | ~323 | Server integration, tool dispatch |

### Extended FSV Scripts (2 scripts)

| Script | Lines | Domain |
|--------|-------|--------|
| `tests/manual_fsv_full.py` | 1180 | Comprehensive full-system verification |
| `tests/manual_fsv_phase3.py` | 787 | Phase 2+ feature verification: editing, rendering, audio, new tools |

---

## Test Count Summary

| Category | File Count | Test Count |
|----------|-----------|------------|
| Phase 1 unit tests | 6 | 139 |
| Phase 2 unit tests | 6 | 87 |
| Phase 1 dashboard tests | 1 | 18 |
| Phase 2 dashboard tests | 1 | 12 |
| Integration tests | 1 | 22 |
| Shared fixtures | 2 | -- |
| **Pytest total** | **17** | **278** |
| FSV: Core Infrastructure | 1 | ~154 checks |
| FSV: Pipeline + Tools | 1 | ~189 checks |
| FSV: Billing + Dashboard | 1 | ~84 checks |
| FSV: Server Integration | 1 | ~323 checks |
| FSV: Full System | 1 | ~1180 lines |
| FSV: Phase 3 Features | 1 | ~787 lines |
| **FSV total** | **6** | **~750+ checks** |

---

## Running Tests

### Run the full pytest suite

```bash
cd /home/cabdru/clipcannon
pytest
```

### Run Phase 2 tests only

```bash
pytest tests/test_edl.py tests/test_captions.py tests/test_smart_crop.py tests/test_editing_tools.py tests/test_rendering.py tests/test_audio_generation.py tests/test_dashboard_phase2.py
```

### Run integration tests

```bash
pytest tests/integration/test_full_pipeline.py
```

### Run FSV scripts

```bash
python tests/fsv_core_infrastructure.py
python tests/fsv_pipeline_tools.py
python tests/fsv_billing_dashboard.py
python tests/fsv_server_integration.py
python tests/manual_fsv_full.py
python tests/manual_fsv_phase3.py
```

### Lint

```bash
ruff check src/
```

Ruff is configured in `pyproject.toml` with rules: E, F, W, I, N, UP, ANN, B, SIM, TCH. Target version is Python 3.12, line length 100, source root is `src/`.
