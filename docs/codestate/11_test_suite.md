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

### Shared Fixtures

#### `tests/conftest.py` -- Session-scoped fixtures (Phase 2)

Session-scoped fixtures that run expensive FFmpeg operations once and share results across all test modules.

| Fixture | Scope | Description |
|---------|-------|-------------|
| `clipcannon_config` | session | Single config load for entire session |
| `session_project_dir` | session | Shared temporary project directory |
| `session_probed_project` | session | Runs probe once, returns (project_id, db_path, project_dir, config, result) |
| `session_audio_extracted` | session | Runs audio extraction once (depends on probe) |
| `session_frames_extracted` | session | Runs frame extraction once (depends on probe) |

Test video: `testdata/2026-03-20 14-43-20.mp4` (209.9s, 2560x1440, 60fps h264).

#### `tests/integration/conftest.py` -- Module-scoped integration fixtures (Phase 2)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `pipeline_project` | module | Creates project directory with stream_status rows |
| `probe_result` | module | Runs probe once per module |
| `audio_result` | module | Audio extraction (depends on probe) |
| `frame_result` | module | Frame extraction (depends on probe) |
| `full_pipeline_results` | module | Full pipeline chain (probe -> finalize) |

### Phase 1 Unit Tests

#### `tests/test_pipeline_stages.py` -- 16 tests

Tests probe, audio extraction, frame extraction, DAG resolution, and orchestrator registration.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestProbeStage` | 2 | Metadata extraction; provenance record written |
| `TestAudioExtractStage` | 2 | Produces WAV files; provenance record written |
| `TestFrameExtractStage` | 2 | Produces ~420 JPEG frames; provenance count matches |
| `TestSourceResolution` | 1 | Resolves to original file path |
| `TestTopologicalSort` | 3 | Linear chain; parallel stages; diamond DAG |
| `TestOrchestratorRegistration` | 2 | Register/list stages; duplicate raises `PipelineError` |
| Additional tests | 4 | Config fixture, session fixture integration |

#### `tests/test_billing.py` -- 40 tests

*(Unchanged from Phase 1 -- HMAC integrity, credit rates, spending limits, license server API, D1 sync, Stripe webhooks)*

#### `tests/test_understanding_tools.py` -- 22 tests

*(Unchanged from Phase 1 -- VUD summary, analytics, transcript, segment detail, storyboard, search, error handling)*

#### `tests/test_provenance_integration.py` -- 19 tests

*(Unchanged from Phase 1 -- hash computation, chain integrity, tamper detection, record retrieval)*

#### `tests/test_visual_pipeline.py` -- 34 tests

*(Unchanged from Phase 1 -- storyboard generation, quality assessment, visual embedding, OCR, shot type)*

#### `tests/test_derived_stages.py` -- 14 tests

*(Unchanged from Phase 1 -- profanity detection, chronemic analysis, highlight scoring, finalize stage)*

### Phase 2 Unit Tests

#### `tests/test_edl.py` -- 26 tests

Tests EDL model creation, duration computation, platform constraints, transitions, and sub-models.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestEDLCreation` | 4 | Basic EDL instantiation, segment validation |
| `TestDurationComputation` | 4 | Total duration calculation, speed effects, transition overlap deduction |
| `TestPlatformDurationLimits` | 7 | Platform-specific limits for all 7 targets (tiktok 5-180s, instagram_reels 5-90s, etc.) |
| `TestTransitionTypes` | 5 | Transition model validation (fade, crossfade, wipe, slide) |
| `TestSubModels` | 6 | CropSpec, CaptionSpec, AudioSpec, SplitScreenSpec, PipSpec validation |

#### `tests/test_captions.py` -- 15 tests

Tests caption chunking, timestamp remapping, ASS generation, and drawtext filters.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestChunkTranscriptWords` | 4 | Word chunking with max_words, punctuation breaks, min/max display duration (500-3000ms) |
| `TestRemapTimestamps` | 3 | Speed-based timestamp adjustment (0.5x-2.0x) |
| `TestASSGeneration` | 3 | ASS subtitle format with bold_centered, subtitle_bar, karaoke styles |
| `TestDrawtextFilters` | 2 | FFmpeg drawtext filter creation |
| `TestFetchWordsFromDB` | 3 | DB word retrieval and timing validation |

#### `tests/test_smart_crop.py` -- 16 tests

Tests crop region computation, scene-based strategies, position smoothing, and aspect ratio parsing.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestComputeCropRegion` | 5 | Aspect ratio conversions (16:9->9:16, 16:9->1:1), face position clamping, safe area |
| `TestGetCropForScene` | 4 | Scene shot type strategies (extreme_closeup, medium, wide) |
| `TestSmoothCropPositions` | 3 | EMA smoothing of crop positions |
| `TestParseAspectRatio` | 4 | Aspect ratio parsing for all 7 platforms |

#### `tests/test_editing_tools.py` -- 11 tests (async)

Tests editing MCP tool functions with a complete Phase 2 database.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestCreateEdit` | 3 | Valid creation, segment DB persistence, auto caption chunking |
| `TestListEdits` | 2 | Listing edits, status filtering |
| `TestModifyEdit` | 3 | Draft modification, non-draft rejection |
| `TestGenerateMetadata` | 3 | Title/description/hashtags from VUD data |

#### `tests/test_rendering.py` -- 19 tests

Tests encoding profiles, software fallback, platform dimensions, and generation loss prevention.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestGetProfile` | 2 | Profile lookup by name |
| `TestListProfiles` | 2 | All 7 platform profiles enumeration |
| `TestSoftwareFallback` | 3 | Codec fallback (h264_nvenc->libx264, hevc_nvenc->libx265) |
| `TestEncodingProfileFields` | 3 | Profile field validation |
| `TestPlatformProfiles` | 7 | Resolution, fps, duration limits per platform |
| `TestGenerationLossPrevention` | 2 | Rejects renders from /renders/ paths |

#### `tests/test_audio_generation.py` -- 15 tests

Tests SFX generation and MIDI composition.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestGenerateSfx` | 9 | All 9 SFX types (whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger), WAV format, duration |
| `TestComposeMidi` | 6 | All 6 presets, tempo override, key override |

### Phase 2 Dashboard Tests

#### `tests/test_dashboard_phase2.py` -- 12 tests

Tests Phase 2 dashboard endpoints.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestTimelineEndpoints` | 3 | Timeline API, transcript search, enhanced view |
| `TestEditEndpoints` | 3 | Edit CRUD, listing, detail |
| `TestReviewEndpoints` | 3 | Review queue, batch operations, stats |
| `TestErrorHandling` | 3 | Missing project/edit errors, validation |

### Phase 1 Dashboard Tests

#### `tests/dashboard/test_dashboard.py` -- 18 tests

*(Unchanged from Phase 1)*

### Integration Tests

#### `tests/integration/test_full_pipeline.py` -- 19 tests

Full pipeline integration with real test video.

| Class | Tests | Scenarios |
|-------|-------|-----------|
| `TestProbe` | 2 | Metadata extraction, value validation |
| `TestAudioExtract` | 2 | WAV file generation, size validation |
| `TestFrameExtract` | 2 | Frame count (400-440 expected) |
| `TestFullPipeline` | 10 | All stages succeed, DB contents, provenance chain |
| `TestEdgeCases` | 3 | Nonexistent video, fresh project, tamper detection |

---

## FSV (Full State Verification) Tests

*(Unchanged from Phase 1 -- 4 FSV scripts with ~750 checks total)*

---

## Test Count Summary

| Category | File Count | Test Count |
|----------|-----------|------------|
| Phase 1 unit tests | 6 | 145 |
| Phase 2 unit tests | 6 | 102 |
| Phase 1 dashboard tests | 1 | 18 |
| Phase 2 dashboard tests | 1 | 12 |
| Integration tests | 1 | 19 |
| Shared fixtures | 2 | -- |
| **Pytest total** | **17** | **296** |
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
```

### Lint

```bash
ruff check src/
```

Ruff is configured in `pyproject.toml` with rules: E, F, W, I, N, UP, ANN, B, SIM, TCH. Target version is Python 3.12, line length 100, source root is `src/`.
