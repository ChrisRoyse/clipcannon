# ClipCannon Verification Report

Full State Verification (FSV) results and pytest coverage.

## FSV Methodology

Full State Verification (FSV) is a forensic testing approach that goes beyond standard unit testing. Each FSV script:

1. **Imports every module under test directly** -- verifying that all exports exist and are importable.
2. **Tests happy paths with synthetic data** -- creating temporary databases, populating them with known values, and running operations against them.
3. **Tests 3+ edge cases per module** -- including empty inputs, boundary values, error conditions, and tamper detection.
4. **Prints state BEFORE and AFTER each operation** -- providing a physical evidence trail of what changed.
5. **Physically verifies results via direct database SELECT** -- not trusting return values alone, but inspecting SQLite tables to confirm data was actually written.
6. **Records every check as PASS or FAIL** -- with expected value, actual value, and detail for failures.

FSV scripts run as standalone Python programs (`python tests/fsv_*.py`), not through pytest. They produce human-readable output with evidence for each assertion.

---

## Verification Domains

### Domain 1: Core Infrastructure -- 154 checks

**Script**: `tests/fsv_core_infrastructure.py`

| Module | Checks | What Was Verified |
|--------|--------|-------------------|
| Exceptions | 11 | All 7 exception classes exist and subclass `ClipCannonError` |
| Database Connection | 12 | WAL mode, pragmas, dict_rows, auto-created parent dirs |
| Database Schema | 26 | Core tables, schema_version, indexes, idempotent creation |
| Query Helpers | 20 | table_exists, batch_insert, fetch_all, fetch_one, count_rows, transactions |
| Configuration | 18 | Dot-notation get, Pydantic validation, set/save/reload |
| GPU Manager | 15 | Device detection, memory reporting |
| Provenance Hasher | 18 | File hashing, bytes hashing, table content hashing |
| Provenance Chain | 16 | Deterministic hash, parent differentiation, chain verification, tamper detection |
| Provenance Recorder | 14 | Record ID format, retrieval, filtering, timeline |
| SHA-256 Table Content | 4 | Determinism, cross-table verification |

**Result**: 154/154 passed

### Domain 2: Pipeline + Tools -- 189 checks

**Script**: `tests/fsv_pipeline_tools.py`

DAG resolution, stage registration, graceful degradation, MCP tools, edge cases, DB cross-verification.

**Result**: 189/189 passed

### Domain 3: Billing + Dashboard -- 84 checks

**Script**: `tests/fsv_billing_dashboard.py`

HMAC integrity, credit system, license server, billing MCP tools, dashboard, D1 sync, Stripe webhooks.

**Result**: 84/84 passed

### Domain 4: Server + Integration -- 323 checks

**Script**: `tests/fsv_server_integration.py`

Server integration, tool dispatch, all tool modules.

**Result**: 323/323 passed

### Domain 5: Full System Verification

**Script**: `tests/manual_fsv_full.py` (1180 lines)

Comprehensive system-wide verification covering all modules end-to-end.

### Domain 6: Phase 2+ Features

**Script**: `tests/manual_fsv_phase3.py` (787 lines)

Verification of Phase 2 features: editing engine (EDL, captions, smart crop), rendering engine (profiles, FFmpeg, canvas compositing), audio engine (music, MIDI, SFX, cleanup), new MCP tools (auto_trim, color_adjust, motion, overlays, subject extraction, preview, inspect, measure_layout, storyboard, scene_map).

---

## Pytest Coverage

278 tests across 17 files:

| Test File | Tests | Coverage Domain |
|-----------|-------|-----------------|
| `test_pipeline_stages.py` | 12 | Probe, audio, frame, DAG, orchestrator |
| `test_billing.py` | 40 | HMAC, credits, license server, webhooks |
| `test_understanding_tools.py` | 20 | VUD, analytics, transcript, search |
| `test_provenance_integration.py` | 19 | Hash chain, tamper detection |
| `test_visual_pipeline.py` | 34 | Storyboard, quality, visual, OCR, shot type |
| `test_derived_stages.py` | 14 | Profanity, chronemic, highlights, finalize |
| `test_edl.py` | 19 | EDL models, validation, platform constraints |
| `test_captions.py` | 14 | Caption chunking, ASS generation |
| `test_smart_crop.py` | 15 | Crop regions, face tracking, aspect ratios |
| `test_editing_tools.py` | 10 | Create/modify/list edits, metadata |
| `test_rendering.py` | 14 | Encoding profiles, codec fallback |
| `test_audio_generation.py` | 15 | 9 SFX types, 6 MIDI presets |
| `test_dashboard.py` | 18 | Phase 1 dashboard endpoints |
| `test_dashboard_phase2.py` | 12 | Timeline, editing, review endpoints |
| `test_full_pipeline.py` | 22 | Full pipeline integration |

---

## Summary

| Domain | Script/Source | Checks | Result |
|--------|--------|--------|--------|
| Core Infrastructure | `fsv_core_infrastructure.py` | 154 | 154/154 passed |
| Pipeline + Tools | `fsv_pipeline_tools.py` | 189 | 189/189 passed |
| Billing + Dashboard | `fsv_billing_dashboard.py` | 84 | 84/84 passed |
| Server + Integration | `fsv_server_integration.py` | 323 | 323/323 passed |
| Full System | `manual_fsv_full.py` | ~1180 lines | Extended verification |
| Phase 2+ Features | `manual_fsv_phase3.py` | ~787 lines | Feature verification |
| **FSV Total** | **6 scripts** | **750+** | **All passing** |
| **Pytest Total** | **17 files** | **278** | **All passing** |

---

## Lint Status

Linter: `ruff` (configured in `pyproject.toml`)

| Setting | Value |
|---------|-------|
| Target version | Python 3.12 |
| Line length | 100 |
| Source root | `src/` |
| Selected rules | E, F, W, I, N, UP, ANN, B, SIM, TCH |

---

## Codebase Metrics

- **Source files**: `src/clipcannon/` and `src/license_server/`
- **Test files**: 17 pytest files + 6 FSV scripts
- **Pipeline stages**: 21
- **MCP tools**: 51
- **Database tables**: 27 core + 4 vector
- **Encoding profiles**: 7
- **Target platforms**: 7
