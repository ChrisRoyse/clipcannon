# Test Suite

## Pytest Configuration (`pyproject.toml`)

| Setting | Value |
|---|---|
| `testpaths` | `["tests"]` |
| `asyncio_mode` | `"auto"` |
| `pythonpath` | `["src"]` |

Dev deps: `pytest>=8.0`, `pytest-asyncio>=0.23.0`, `ruff>=0.4.0`

Ruff rules: E, F, W, I, N, UP, ANN, B, SIM, TCH. Python 3.12, line length 100, source root `src/`.

---

## Shared Fixtures

### `tests/conftest.py` (session-scoped)

| Fixture | Description |
|---|---|
| `clipcannon_config` | Single config load |
| `session_project_dir` | Shared temp project dir |
| `session_probed_project` | Runs probe once -> (project_id, db_path, project_dir, config, result) |
| `session_audio_extracted` | Audio extraction once (depends on probe) |
| `session_frames_extracted` | Frame extraction once (depends on probe) |

Test video: `testdata/2026-03-20 14-43-20.mp4` (209.9s, 2560x1440, 60fps h264).

### `tests/integration/conftest.py` (module-scoped)

`pipeline_project`, `probe_result`, `audio_result`, `frame_result`, `full_pipeline_results`

---

## Unit Tests (439 total across 24 files)

| File | Tests | Domain |
|---|---|---|
| `test_pipeline_stages.py` | 12 | Probe, audio/frame extract, DAG, orchestrator |
| `test_billing.py` | 40 | HMAC, credits, license server, D1, Stripe |
| `test_understanding_tools.py` | 11 | Transcript, search, frame tools |
| `test_provenance_integration.py` | 19 | Hash chain, tamper detection |
| `test_visual_pipeline.py` | 34 | Storyboard, quality, visual embed, OCR, shot type |
| `test_derived_stages.py` | 14 | Profanity, chronemic, highlights, finalize |
| `test_edl.py` | 19 | EDL models, validation, platform constraints |
| `test_captions.py` | 14 | Caption chunking, ASS generation |
| `test_smart_crop.py` | 15 | Crop regions, face tracking, aspect ratios |
| `test_editing_tools.py` | 19 | Create/modify/list edits, metadata, iterative editing |
| `test_rendering.py` | 14 | Encoding profiles, codec fallback |
| `test_audio_generation.py` | 15 | 9 SFX types, 6 MIDI presets |
| `dashboard/test_dashboard.py` | 18 | Dashboard endpoints |
| `test_dashboard_phase2.py` | 12 | Timeline, editing, review endpoints |
| `test_discovery_tools.py` | 28 | Best moments, cut points, narrative flow, safe cuts |
| `test_change_classifier.py` | 27 | Change classification for iterative editing |
| `test_feedback.py` | 30 | Natural language feedback application |
| `test_preview_segment.py` | 3 | Segment preview rendering |
| `test_segment_cache.py` | 17 | Segment-level render caching |
| `test_avatar.py` | 12 | Lip-sync engine (LatentSync) |
| `test_voice_verify.py` | 16 | Multi-gate voice verification (WER, SECS, sanity) |
| `test_voice_inference.py` | 5 | Qwen3-TTS voice synthesis |
| `test_voice_data_prep.py` | 11 | Voice data preparation, profile CRUD |
| `integration/test_full_pipeline.py` | 22 | Full pipeline with real video |

---

## FSV (Full State Verification) Scripts

Standalone forensic testing (`python tests/fsv_*.py`). Each script: imports every module, tests happy paths + 3+ edge cases, prints before/after state, verifies DB via direct SELECT, records PASS/FAIL with evidence.

| Script | Checks | Domain |
|---|---|---|
| `fsv_core_infrastructure.py` | ~154 | Exceptions, DB, schema, config, GPU, provenance |
| `fsv_pipeline_tools.py` | ~189 | DAG, stage registration, MCP tools |
| `fsv_billing_dashboard.py` | ~84 | HMAC, credits, license server, dashboard |
| `fsv_server_integration.py` | ~323 | Server integration, all tool dispatch |
| `manual_fsv_full.py` | ~1180 lines | Comprehensive system-wide verification |
| `manual_fsv_phase3.py` | ~787 lines | Editing, rendering, audio, new tools |
| `fsv_part1_pipeline.py` | ~435 lines | Pipeline-focused verification |
| `fsv_parts_3_to_7.py` | ~731 lines | Multi-domain verification |
| `integration/manual_verify.py` | ~429 lines | Integration verification |

---

## Running

```bash
pytest                              # Full suite (439 tests)
pytest tests/integration/           # Integration only
python tests/fsv_core_infrastructure.py  # Individual FSV script
ruff check src/                     # Lint
```
