# ClipCannon Implementation Plan

**Version:** 1.1
**Date:** 2026-03-21
**Based on:** ClipCannon PRD v5.0 (PRD1-PRD6)

---

## Phase 1 Status: COMPLETE

**Verified:** 2026-03-21
**Version:** 0.1.0

| Metric | Value |
|:-------|:------|
| FSV Checks | 750/750 passed |
| Pytest Tests | 181/181 passed |
| Lint Errors | 0 (ruff) |
| MCP Tools | 27 implemented |
| Pipeline Stages | 20 registered |
| DB Tables | 23 core + 4 vector |
| Source Lines | ~12,000 |

---

## 1. Implementation Overview

ClipCannon is an AI-native video editing MCP server that runs locally on consumer GPU hardware (target: RTX 5090). It decomposes video into parallel understanding streams, delivers frames + transcript + embedder analytics to a multimodal AI, and produces platform-ready outputs for 5 social media platforms.

### Delivery Phases

| Phase | Name | Focus | Status |
|:------|:-----|:------|:-------|
| 1 | Foundation | MCP server, ingestion, understanding pipeline, billing, provenance | **COMPLETE** (verified 2026-03-21) |
| 2 | Editing Engine | EDL, rendering, audio gen, captions, cropping, dashboard | NOT STARTED |
| 3 | Motion Graphics & Publishing | Animations, overlays, platform APIs, full dashboard | NOT STARTED |
| 4 | Intelligence & Growth | Analytics feedback loop, A/B testing, marketplace, agency tier | NOT STARTED |

---

## 2. Technology Stack

### Core Runtime

| Component | Technology | Version |
|:----------|:-----------|:--------|
| Language | Python 3.12+ | Latest stable |
| MCP Framework | `mcp` library (Server class, stdio_server, Tool, TextContent) | >=1.0.0 |
| Video Processing | FFmpeg 7.x | 7.x with NVENC/NVDEC |
| EDL Rendering | typed-ffmpeg v3.0 (Phase 2) | Type-safe FFmpeg command builder |
| Database | SQLite + sqlite-vec | Per-project .db file |
| GPU Framework | PyTorch 2.x + CUDA 13.2 | Latest |
| Containerization | Docker (NVIDIA Container Toolkit) | GPU passthrough |

### ML Models (Understanding Pipeline)

| Stream | Model | VRAM (NVFP4) | License |
|:-------|:------|:-------------|:--------|
| Source Separation | HTDemucs v4 | ~2.0 GB | MIT |
| Transcription | WhisperX (faster-whisper large-v3 + wav2vec2 alignment) | ~1.5 GB | BSD-4-Clause |
| Visual Embedding | SigLIP SO400M-patch14-384 | ~0.6 GB | Apache 2.0 |
| OCR | PaddleOCR PP-OCRv5 | ~0.75 GB | Apache 2.0 |
| Quality Assessment | pyiqa BRISQUE (GPU) + DOVER-Mobile | ~0.75 GB combined | Public domain / MIT |
| Shot Classification | ResNet-50 (MovieShots) | ~0.2 GB | MIT/Apache |
| Semantic Embedding | Nomic Embed Text v1.5 | ~0.25 GB | Apache 2.0 |
| Emotion/Energy | Wav2Vec2 Large (emotion) | ~0.75 GB | MIT |
| Speaker Diarization | WavLM Base Plus SV | ~0.2 GB | MIT |
| Reaction Detection | SenseVoice-Small | ~0.55 GB | Apache 2.0 |
| Beat Detection | Beat This! | ~0.5 GB | Open source |
| Content Safety | Word list + CLIP-NSFW (reuses SigLIP) | ~0 GB | N/A |
| VAD | Silero VAD | CPU only | MIT |

### Audio Generation Models (Phase 2)

| Component | Technology | License |
|:----------|:-----------|:--------|
| AI Music | ACE-Step v1.5 turbo-rl | MIT |
| MIDI Composition | MIDIUtil + music21 | MIT / LGPL |
| MIDI Rendering | FluidSynth + pyfluidsynth | LGPL |
| DSP/SFX | numpy + scipy.signal | BSD |
| Audio Mixing | pydub | MIT |
| Audio Effects | pedalboard (Spotify) | GPLv3 |

### Animation/Graphics (Phase 3)

| Component | Technology | License |
|:----------|:-----------|:--------|
| 2D Vector Graphics | PyCairo + Pango | LGPL |
| Lottie Rendering | rlottie-python | MIT |
| Transition Shaders | xfade-easing (GL Transitions port) | MIT |
| WebM Overlays | FFmpeg VP9 alpha compositing | LGPL |

---

## 3. Project Structure

The file tree below reflects the actual Phase 1 codebase. Directories and files that exist only in future phases are listed under their respective phase sections.

```
clipcannon/
├── src/
│   ├── clipcannon/
│   │   ├── __init__.py                 # Package root, exports __version__ = "0.1.0"
│   │   ├── server.py                   # MCP server entry point (mcp library, Server class, stdio transport)
│   │   ├── config.py                   # Configuration management (JSON config, Pydantic validation, dot-notation access)
│   │   ├── exceptions.py               # Exception hierarchy: ClipCannonError + 6 subclasses
│   │   │
│   │   ├── tools/                      # MCP tool definitions (27 tools across 8 modules)
│   │   │   ├── __init__.py             # Tool registry: ALL_TOOL_DEFINITIONS, TOOL_DISPATCHERS
│   │   │   ├── project.py              # 5 project tools: create, open, list, status, delete
│   │   │   ├── understanding.py        # 4 understanding tools: ingest, vud_summary, analytics, transcript
│   │   │   ├── understanding_visual.py # 4 visual tools: segment_detail, get_frame, frame_strip, storyboard
│   │   │   ├── understanding_search.py # 1 search tool: search_content (semantic + text fallback)
│   │   │   ├── provenance_tools.py     # 4 provenance tools: verify, query, chain, timeline
│   │   │   ├── disk.py                 # 2 disk tools: status, cleanup
│   │   │   ├── config_tools.py         # 3 config tools: get, set, list
│   │   │   ├── billing_tools.py        # 4 billing tools: balance, history, estimate, spending_limit
│   │   │   └── video_probe.py          # FFprobe wrapper: run_ffprobe, extract_video_metadata, detect_vfr
│   │   │
│   │   ├── pipeline/                   # Processing pipeline (20 stages)
│   │   │   ├── __init__.py             # Re-exports orchestrator, stages, run functions
│   │   │   ├── orchestrator.py         # DAG-based pipeline runner, StageResult, PipelineResult models
│   │   │   ├── dag.py                  # Topological sort (Kahn's algorithm), update_stream_status
│   │   │   ├── registry.py             # Builds pipeline DAG with all 20 stages, build_pipeline function
│   │   │   ├── source_resolution.py    # Helpers: resolve_source_path, resolve_audio_input
│   │   │   ├── probe.py                # Stage: FFprobe metadata + VFR detection
│   │   │   ├── vfr_normalize.py        # Stage: VFR -> CFR normalization via FFmpeg
│   │   │   ├── audio_extract.py        # Stage: Audio track extraction via FFmpeg
│   │   │   ├── source_separation.py    # Stage: HTDemucs stem separation (4 stems)
│   │   │   ├── frame_extract.py        # Stage: Frame extraction at configured FPS via FFmpeg
│   │   │   ├── visual_embed.py         # Stage: SigLIP visual embeddings (float[1152])
│   │   │   ├── ocr.py                  # Stage: PaddleOCR text detection
│   │   │   ├── quality.py              # Stage: Frame quality assessment (blur, exposure, noise)
│   │   │   ├── shot_type.py            # Stage: Shot type classification from scene key frames
│   │   │   ├── transcribe.py           # Stage: WhisperX transcription + forced alignment
│   │   │   ├── semantic_embed.py       # Stage: Nomic semantic embeddings (float[768])
│   │   │   ├── emotion_embed.py        # Stage: Wav2Vec2 emotion embeddings (float[1024])
│   │   │   ├── speaker_embed.py        # Stage: WavLM speaker embeddings (float[512])
│   │   │   ├── reactions.py            # Stage: SenseVoice reaction detection
│   │   │   ├── acoustic.py             # Stage: Acoustic analysis (volume, dynamic range, silence)
│   │   │   ├── chronemic.py            # Stage: Pacing/chronemic analysis
│   │   │   ├── profanity.py            # Stage: Profanity detection + content safety rating
│   │   │   ├── highlights.py           # Stage: Multi-signal highlight scoring
│   │   │   ├── storyboard.py           # Stage: Storyboard grid generation
│   │   │   └── finalize.py             # Stage: Final status update, marks project ready
│   │   │
│   │   ├── billing/                    # Credit billing system
│   │   │   ├── __init__.py             # Re-exports rates, packages, client, models, HMAC functions
│   │   │   ├── credits.py              # Credit rates, packages, estimate_cost, spending validation
│   │   │   ├── hmac_integrity.py       # HMAC-SHA256 balance signing via machine-derived key
│   │   │   └── license_client.py       # Async HTTP client for license server (httpx)
│   │   │
│   │   ├── provenance/                 # Provenance hash chain
│   │   │   ├── __init__.py             # Re-exports all public API
│   │   │   ├── hasher.py               # SHA-256 file/table hashing (streaming 8KB chunks)
│   │   │   ├── chain.py                # Chain hash computation + verification, GENESIS_HASH
│   │   │   └── recorder.py             # Provenance record CRUD, Pydantic models
│   │   │
│   │   ├── db/                         # Database layer
│   │   │   ├── __init__.py             # Re-exports connection, query, and schema functions
│   │   │   ├── connection.py           # SQLite connection factory (WAL mode, pragmas, sqlite-vec)
│   │   │   ├── schema.py               # DDL for 23 core tables + 4 vector tables + indexes
│   │   │   └── queries.py              # Parameterized query helpers, transaction context manager
│   │   │
│   │   ├── gpu/                        # GPU management
│   │   │   ├── __init__.py             # Re-exports GPUHealthReport, ModelManager, precision functions
│   │   │   ├── manager.py              # ModelManager: LRU model lifecycle, VRAM monitoring
│   │   │   └── precision.py            # NVFP4/INT8/FP16 auto-detection from CUDA compute capability
│   │   │
│   │   └── dashboard/                  # Web dashboard (port 3200)
│   │       ├── __init__.py             # Re-exports create_app
│   │       ├── app.py                  # FastAPI application factory, CORS, static files
│   │       ├── auth.py                 # JWT-based dev-mode authentication
│   │       └── routes/
│   │           ├── __init__.py         # Re-exports all 4 routers
│   │           ├── home.py             # Dashboard home + health check
│   │           ├── credits.py          # Credit balance + history API
│   │           ├── projects.py         # Project listing + status API
│   │           └── provenance.py       # Provenance chain + timeline API
│   │
│   └── license_server/                 # Standalone license server (port 3100)
│       ├── __init__.py
│       ├── server.py                   # FastAPI app, SQLite-backed credit balance with HMAC
│       ├── d1_sync.py                  # Cloudflare D1 sync stub (local-only in Phase 1)
│       └── stripe_webhooks.py          # Stripe checkout webhook handler
│
├── tests/                              # Flat test directory (no unit/integration hierarchy)
│   ├── test_pipeline_stages.py         # Pipeline stage tests (pytest)
│   ├── test_visual_pipeline.py         # Visual pipeline tests (pytest)
│   ├── test_derived_stages.py          # Derived stage tests (pytest)
│   ├── test_understanding_tools.py     # Understanding MCP tool tests (pytest)
│   ├── test_billing.py                 # Billing system tests (pytest)
│   ├── test_provenance_integration.py  # Provenance integration tests (pytest)
│   ├── dashboard/
│   │   ├── __init__.py
│   │   └── test_dashboard.py           # Dashboard tests (pytest)
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_full_pipeline.py       # Full pipeline integration tests (pytest)
│   │   └── manual_verify.py            # Manual verification script
│   ├── fsv_core_infrastructure.py      # FSV: 154 checks (exceptions, db, config, gpu, provenance)
│   ├── fsv_pipeline_tools.py           # FSV: 189 checks (DAG, stages, MCP tools, edge cases)
│   ├── fsv_billing_dashboard.py        # FSV: 84 checks (HMAC, credits, license server, dashboard)
│   ├── fsv_server_integration.py       # FSV: 323 checks (server, registry, pytest suite gate)
│   ├── fsv_part1_pipeline.py           # FSV: pipeline subset checks
│   └── fsv_parts_3_to_7.py            # FSV: multi-part checks
│
├── config/
│   ├── default_config.json             # Default configuration values
│   └── docker-compose.yml              # Docker Compose with NVIDIA runtime
│
├── scripts/
│   ├── setup.sh                        # Environment setup
│   ├── download_models.py              # Model weight downloader
│   ├── validate_gpu.py                 # GPU capability checker
│   └── docker-entrypoint.sh            # Docker entrypoint script
│
├── assets/
│   └── profanity/                      # Profanity word list (only asset present in Phase 1)
│
├── testdata/                           # Test fixture data
├── docs/                               # Codestate documentation
├── docs2/                              # PRD and planning documents
├── Dockerfile
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

**Directories NOT yet created (Phase 2-4):**
- `src/clipcannon/editing/` (Phase 2)
- `src/clipcannon/rendering/` (Phase 2)
- `src/clipcannon/audio/` (Phase 2)
- `src/clipcannon/animation/` (Phase 3)
- `src/clipcannon/publishing/` (Phase 3)
- `assets/lottie/`, `assets/webm/`, `assets/transitions/`, `assets/fonts/`, `assets/soundfonts/` (Phase 3)

---

## 4. Phase 1: Foundation -- COMPLETE

**Goal:** MCP server scaffold, video ingestion, understanding pipeline, billing, provenance chain, basic dashboard.

**Verified:** 2026-03-21 -- 750/750 FSV checks, 181/181 pytest tests, 0 lint errors.

### 4.1 Task Breakdown

#### 4.1.1 Project Scaffold & Infrastructure

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.1.1 | Initialize Python project with pyproject.toml, dependencies, linting | `pyproject.toml`, `src/clipcannon/__init__.py` | Done |
| 1.1.2 | Set up Docker container with NVIDIA runtime, FFmpeg 7.x, CUDA 13.2 | `Dockerfile`, `config/docker-compose.yml` | Done |
| 1.1.3 | Implement configuration management (load/save JSON config, defaults) | `src/clipcannon/config.py` | Done |
| 1.1.4 | Implement GPU manager (detect GPU, VRAM monitoring, precision auto-select) | `src/clipcannon/gpu/manager.py`, `precision.py` | Done |
| 1.1.5 | Create model weight downloader script | `scripts/download_models.py` | Done |
| 1.1.6 | Create GPU validation script | `scripts/validate_gpu.py` | Done |

#### 4.1.2 Database Layer

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.2.1 | Implement SQLite connection manager (WAL mode, pragmas, sqlite-vec) | `src/clipcannon/db/connection.py` | Done |
| 1.2.2 | Define full database schema with sqlite-vec virtual tables | `src/clipcannon/db/schema.py` | Done |
| 1.2.3 | Implement parameterized query helpers | `src/clipcannon/db/queries.py` | Done |
| 1.2.4 | Write schema migration system | `src/clipcannon/db/schema.py` | Done |

**Schema tables (23 core):** schema_version, project, transcript_segments, transcript_words, scenes, speakers, emotion_curve, topics, highlights, reactions, silence_gaps, acoustic, music_sections, beats, beat_sections, on_screen_text, text_change_events, profanity_events, content_safety, pacing, storyboard_grids, stream_status, provenance.

**Vector tables (4, sqlite-vec `vec0`):** vec_frames (float[1152]), vec_semantic (float[768]), vec_emotion (float[1024]), vec_speakers (float[512]).

Schema version: 1. Connection pragmas: WAL journal mode, NORMAL synchronous, 64MB cache, foreign keys ON, temp store in memory.

#### 4.1.3 Provenance Hash Chain

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.3.1 | Implement SHA-256 file hasher (streaming for large files) | `src/clipcannon/provenance/hasher.py` | Done |
| 1.3.2 | Implement chain hash computation (parent + input + output + operation) | `src/clipcannon/provenance/chain.py` | Done |
| 1.3.3 | Implement provenance recorder (write records to DB, chain verification) | `src/clipcannon/provenance/recorder.py` | Done |

#### 4.1.4 MCP Server + Project Management Tools

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.4.1 | Set up MCP server scaffold with tool registry (`mcp` library, Server class, stdio transport) | `src/clipcannon/server.py` | Done |
| 1.4.2 | Implement project management tools (create, open, list, status, delete) | `src/clipcannon/tools/project.py` | Done |
| 1.4.3 | Implement provenance query tools (verify, query, chain, timeline) | `src/clipcannon/tools/provenance_tools.py` | Done |
| 1.4.4 | Implement disk management tools (status, cleanup) | `src/clipcannon/tools/disk.py` | Done |
| 1.4.5 | Implement config tools (get, set, list) | `src/clipcannon/tools/config_tools.py` | Done |

#### 4.1.5 Pipeline Orchestrator

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.5.1 | Implement DAG-based pipeline orchestrator (topological sort, required/optional stages, graceful degradation) | `src/clipcannon/pipeline/orchestrator.py`, `dag.py`, `registry.py` | Done |

#### 4.1.6 Understanding Pipeline -- Required Stages

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.6.1 | Implement FFprobe stage (probe metadata, VFR detection) | `src/clipcannon/pipeline/probe.py` | Done |
| 1.6.2 | Implement VFR normalization (CFR re-encode via NVENC if VFR detected) | `src/clipcannon/pipeline/vfr_normalize.py` | Done |
| 1.6.3 | Implement audio extraction (PCM 16kHz mono + original rate) | `src/clipcannon/pipeline/audio_extract.py` | Done |
| 1.6.4 | Implement HTDemucs source separation (4 stems: vocals, music, drums, other) | `src/clipcannon/pipeline/source_separation.py` | Done |
| 1.6.5 | Implement frame extraction (NVDEC 2fps JPEGs) | `src/clipcannon/pipeline/frame_extract.py` | Done |
| 1.6.6 | Implement WhisperX transcription (forced alignment on vocal stem, word-level timestamps) | `src/clipcannon/pipeline/transcribe.py` | Done |

#### 4.1.7 Understanding Pipeline -- Visual Streams

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.7.1 | Implement SigLIP visual embedding + scene boundary detection | `src/clipcannon/pipeline/visual_embed.py` | Done |
| 1.7.2 | Implement PaddleOCR text detection (1fps, dedup, slide transitions) | `src/clipcannon/pipeline/ocr.py` | Done |
| 1.7.3 | Implement BRISQUE + DOVER quality assessment (GPU batch) | `src/clipcannon/pipeline/quality.py` | Done |
| 1.7.4 | Implement ResNet-50 shot type classification | `src/clipcannon/pipeline/shot_type.py` | Done |

#### 4.1.8 Understanding Pipeline -- Audio/Text Streams

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.8.1 | Implement Nomic semantic embedding + topic clustering | `src/clipcannon/pipeline/semantic_embed.py` | Done |
| 1.8.2 | Implement Wav2Vec2 emotion/energy analysis (on vocal stem) | `src/clipcannon/pipeline/emotion_embed.py` | Done |
| 1.8.3 | Implement WavLM speaker diarization (on vocal stem) | `src/clipcannon/pipeline/speaker_embed.py` | Done |
| 1.8.4 | Implement SenseVoice reaction detection (laughter, applause) | `src/clipcannon/pipeline/reactions.py` | Done |
| 1.8.5 | Implement acoustic analysis + beat detection | `src/clipcannon/pipeline/acoustic.py` | Done |

#### 4.1.9 Understanding Pipeline -- Derived Streams

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.9.1 | Implement profanity detection (word list + CLIP-NSFW) | `src/clipcannon/pipeline/profanity.py` | Done |
| 1.9.2 | Implement chronemic computation (WPM, pause ratios, pacing) | `src/clipcannon/pipeline/chronemic.py` | Done |
| 1.9.3 | Implement multi-signal highlight scoring | `src/clipcannon/pipeline/highlights.py` | Done |
| 1.9.4 | Implement storyboard grid generation (80 grids, adaptive interval) | `src/clipcannon/pipeline/storyboard.py` | Done |
| 1.9.5 | Implement finalize stage (chain verification, stream status) | `src/clipcannon/pipeline/finalize.py` | Done |

**Additional pipeline files (not in original plan but implemented):**
- `src/clipcannon/pipeline/source_resolution.py` -- Helpers for resolving source/audio paths (original vs CFR)

#### 4.1.10 Video Understanding MCP Tools

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.10.1 | Implement clipcannon_ingest (orchestrates full pipeline) | `src/clipcannon/tools/understanding.py` | Done |
| 1.10.2 | Implement clipcannon_get_vud_summary (~8K tokens) | `src/clipcannon/tools/understanding.py` | Done |
| 1.10.3 | Implement clipcannon_get_analytics (~18K tokens) | `src/clipcannon/tools/understanding.py` | Done |
| 1.10.4 | Implement clipcannon_get_transcript (paginated, ~12K/page) | `src/clipcannon/tools/understanding.py` | Done |
| 1.10.5 | Implement clipcannon_get_segment_detail (~15K tokens) | `src/clipcannon/tools/understanding_visual.py` | Done |
| 1.10.6 | Implement clipcannon_get_frame (single frame + temporal metadata) | `src/clipcannon/tools/understanding_visual.py` | Done |
| 1.10.7 | Implement clipcannon_get_frame_strip (3x3 grid for a time range) | `src/clipcannon/tools/understanding_visual.py` | Done |
| 1.10.8 | Implement clipcannon_get_storyboard (batched, 12 grids/batch) | `src/clipcannon/tools/understanding_visual.py` | Done |
| 1.10.9 | Implement clipcannon_search_content (semantic search via sqlite-vec) | `src/clipcannon/tools/understanding_search.py` | Done |

**Note:** The understanding tools are split across three files (`understanding.py`, `understanding_visual.py`, `understanding_search.py`) rather than a single file. Additionally, `video_probe.py` provides the FFprobe wrapper used by project tools.

**Critical constraint:** Every MCP tool response must be under 25K tokens.

#### 4.1.11 Billing System

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.11.1 | Implement license server (HTTP, port 3100, SQLite cache) | `src/license_server/server.py` | Done |
| 1.11.2 | Implement Cloudflare D1 sync (local-only stub in Phase 1) | `src/license_server/d1_sync.py` | Done |
| 1.11.3 | Implement Stripe webhook handler (credit purchase flow) | `src/license_server/stripe_webhooks.py` | Done |
| 1.11.4 | Implement HMAC-SHA256 balance integrity | `src/clipcannon/billing/hmac_integrity.py` | Done |
| 1.11.5 | Implement license client (charge/refund from MCP server) | `src/clipcannon/billing/license_client.py` | Done |
| 1.11.6 | Implement credit system (charge rates per operation, spending caps) | `src/clipcannon/billing/credits.py` | Done |

**Additional billing file (not in original plan):** `src/clipcannon/tools/billing_tools.py` -- 4 MCP billing tools (balance, history, estimate, spending_limit) that use the LicenseClient.

#### 4.1.12 Basic Dashboard

| Task | Description | Files | Status |
|:-----|:-----------|:------|:-------|
| 1.12.1 | Set up FastAPI dashboard app (port 3200) | `src/clipcannon/dashboard/app.py` | Done |
| 1.12.2 | Implement JWT-based dev-mode authentication | `src/clipcannon/dashboard/auth.py` | Done |
| 1.12.3 | Build home page (health, system status) | `src/clipcannon/dashboard/routes/home.py` | Done |
| 1.12.4 | Build credit balance and history endpoints | `src/clipcannon/dashboard/routes/credits.py` | Done |
| 1.12.5 | Build provenance chain and timeline endpoints | `src/clipcannon/dashboard/routes/provenance.py` | Done |

**Additional dashboard file:** `src/clipcannon/dashboard/routes/projects.py` -- Project listing and status API endpoints.

### 4.2 Phase 1 Success Criteria

- [x] Credit charge/refund flow works end-to-end
- [x] VUD contains AI-readable data (text labels, scores, timestamps) -- not raw embeddings
- [x] Provenance chain has valid chain hashes with `clipcannon_provenance_verify` passing
- [x] Any file modification after provenance recording is detected by hash mismatch
- [x] All MCP tool responses under 25K tokens
- [ ] Process a 1-hour video in under 5 minutes (RTX 5090) -- requires GPU hardware validation
- [ ] Word-level timestamps with WER < 5% on English content -- requires GPU hardware validation
- [ ] Scene detection captures 90%+ of visual transitions -- requires GPU hardware validation

### 4.3 Phase 1 Verification Summary

**Full State Verification (FSV)** -- 4 scripts, 750 total checks:

| Domain | Script | Checks | Result |
|:-------|:-------|:-------|:-------|
| Core Infrastructure | `fsv_core_infrastructure.py` | 154 | 154/154 passed |
| Pipeline + Tools | `fsv_pipeline_tools.py` | 189 | 189/189 passed |
| Billing + Dashboard | `fsv_billing_dashboard.py` | 84 | 84/84 passed |
| Server + Integration | `fsv_server_integration.py` | 323 | 323/323 passed |
| **Total** | **4 scripts** | **750** | **750/750 passed** |

**Pytest suite** -- 8 test files, 181 tests:

| File | Scope |
|:-----|:------|
| `test_pipeline_stages.py` | Pipeline stage unit tests |
| `test_visual_pipeline.py` | Visual pipeline stage tests |
| `test_derived_stages.py` | Derived stage tests |
| `test_understanding_tools.py` | Understanding MCP tool tests |
| `test_billing.py` | Billing system tests |
| `test_provenance_integration.py` | Provenance integration tests |
| `dashboard/test_dashboard.py` | Dashboard endpoint tests |
| `integration/test_full_pipeline.py` | Full pipeline integration tests |

**Lint** (ruff): 0 errors, 0 warnings. Rules: E, F, W, I, N, UP, ANN, B, SIM, TCH.

### 4.4 Phase 1 Architecture Notes

**MCP Server:** Uses the `mcp` Python library (Server class), NOT FastMCP. The server registers 27 tools via `list_tools()` and `call_tool()` handlers, runs on stdio transport by default (the `clipcannon` console script). Logging uses structured JSON to stderr.

**Pipeline stages:** 20 stages registered in `registry.py` (6 required, 14 optional). The 16 named analysis streams tracked in `stream_status` are: source_separation, visual, ocr, quality, shot_type, transcription, semantic, emotion, speaker, reactions, acoustic, beats, chronemic, storyboards, profanity, highlights. Additional orchestration stages (probe, vfr_normalize, audio_extract, frame_extract, finalize) are part of the DAG but not tracked as named streams.

**D1 sync:** Phase 1 is local-only. The `d1_sync.py` module provides stub functions that log "D1 sync skipped (local-only mode)". Interface designed for future D1 integration via `CLIPCANNON_D1_API_URL` and `CLIPCANNON_D1_API_TOKEN` environment variables.

**Exception hierarchy:**
```
ClipCannonError (base)
    PipelineError     -- pipeline stage failures (includes stage_name, operation)
    BillingError      -- credit checks, charges, refunds, HMAC validation
    ProvenanceError   -- hash computation, chain verification, tamper detection
    DatabaseError     -- connections, schema, queries, sqlite-vec loading
    ConfigError       -- missing config, invalid values, validation failures
    GPUError          -- device detection, VRAM exhaustion, model loading
```

---

## 5. Phase 2: Editing Engine + Audio + Dashboard -- NOT STARTED

**Goal:** EDL format, rendering pipeline, caption generation, smart cropping, AI audio generation, full dashboard with review workflow.

### 5.1 Task Breakdown

#### 5.1.1 EDL Format & Edit Creation

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 2.1.1 | Define EDL JSON schema (segments, transitions, captions, audio, overlays) | `src/clipcannon/editing/edl.py` | Phase 1 |
| 2.1.2 | Implement EDL validation (time range checks, profile compat) | `src/clipcannon/editing/edl.py` | 2.1.1 |
| 2.1.3 | Implement clipcannon_create_edit MCP tool | `src/clipcannon/tools/editing.py` | 2.1.1 |
| 2.1.4 | Implement clipcannon_modify_edit MCP tool | `src/clipcannon/tools/editing.py` | 2.1.3 |
| 2.1.5 | Implement clipcannon_list_edits MCP tool | `src/clipcannon/tools/editing.py` | 2.1.3 |

#### 5.1.2 Caption Generation

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 2.2.1 | Implement word-level caption chunking (min display duration, line breaks) | `src/clipcannon/editing/captions.py` | Phase 1 |
| 2.2.2 | Implement ASS subtitle generation (bold_centered, word_highlight, subtitle_bar styles) | `src/clipcannon/editing/captions.py` | 2.2.1 |
| 2.2.3 | Implement drawtext filter fallback for simple captions | `src/clipcannon/editing/captions.py` | 2.2.1 |

#### 5.1.3 Smart Cropping

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 2.3.1 | Integrate face detection (MediaPipe or InsightFace ONNX) | `src/clipcannon/editing/smart_crop.py` | Phase 1 |
| 2.3.2 | Implement face-aware crop calculation (center on face, safe area) | `src/clipcannon/editing/smart_crop.py` | 2.3.1 |
| 2.3.3 | Implement dynamic crop (pan-and-scan for mixed shot types) | `src/clipcannon/editing/smart_crop.py` | 2.3.2 |
| 2.3.4 | Implement per-platform crop profiles (9:16, 1:1, 16:9, 4:5) | `src/clipcannon/editing/smart_crop.py` | 2.3.2 |

#### 5.1.4 Rendering Pipeline

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 2.4.1 | Implement typed-ffmpeg filter graph builder (EDL -> FFmpeg command) | `src/clipcannon/rendering/renderer.py` | 2.1.1 |
| 2.4.2 | Implement platform encoding profiles (all 7 profiles from PRD) | `src/clipcannon/rendering/profiles.py` | 2.4.1 |
| 2.4.3 | Implement single-pass rendering (multi-segment EDL -> one FFmpeg command) | `src/clipcannon/rendering/renderer.py` | 2.4.1 |
| 2.4.4 | Implement generation loss prevention (source SHA-256 verification) | `src/clipcannon/rendering/renderer.py` | 2.4.1, 1.3.1 |
| 2.4.5 | Implement batch rendering (up to 3 parallel NVENC sessions) | `src/clipcannon/rendering/batch.py` | 2.4.3 |
| 2.4.6 | Implement thumbnail generation | `src/clipcannon/rendering/thumbnail.py` | 2.4.1 |
| 2.4.7 | Implement clipcannon_render MCP tool | `src/clipcannon/tools/rendering.py` | 2.4.3 |
| 2.4.8 | Implement clipcannon_render_status MCP tool | `src/clipcannon/tools/rendering.py` | 2.4.7 |
| 2.4.9 | Implement clipcannon_render_batch MCP tool | `src/clipcannon/tools/rendering.py` | 2.4.5 |

#### 5.1.5 AI Audio Generation Engine

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 2.5.1 | Implement ACE-Step v1.5 integration (text prompt -> music WAV) | `src/clipcannon/audio/music_gen.py` | Phase 1 |
| 2.5.2 | Implement MIDI composition pipeline (MIDIUtil + music21 progressions) | `src/clipcannon/audio/midi_compose.py` | Phase 1 |
| 2.5.3 | Implement FluidSynth MIDI -> WAV rendering | `src/clipcannon/audio/midi_render.py` | 2.5.2 |
| 2.5.4 | Implement DSP sound effects (whoosh, riser, impact, chime, etc.) | `src/clipcannon/audio/sfx.py` | Phase 1 |
| 2.5.5 | Implement audio mixing pipeline (ducking, crossfade, normalization) | `src/clipcannon/audio/mixer.py` | 2.5.1, 2.5.3, 2.5.4 |
| 2.5.6 | Implement pedalboard effects (reverb, compression, EQ, limiting) | `src/clipcannon/audio/effects.py` | 2.5.5 |
| 2.5.7 | Implement clipcannon_generate_music MCP tool | `src/clipcannon/tools/audio.py` | 2.5.1 |
| 2.5.8 | Implement clipcannon_compose_midi MCP tool | `src/clipcannon/tools/audio.py` | 2.5.2 |
| 2.5.9 | Implement clipcannon_generate_sfx MCP tool | `src/clipcannon/tools/audio.py` | 2.5.4 |

#### 5.1.6 Metadata Generation

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 2.6.1 | Implement per-platform metadata generation (title, description, hashtags) | `src/clipcannon/editing/metadata_gen.py` | Phase 1 |
| 2.6.2 | Implement clipcannon_generate_metadata MCP tool | `src/clipcannon/tools/editing.py` | 2.6.1 |

#### 5.1.7 Full Dashboard

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 2.7.1 | Build project view page (source video, analysis status, stream progress bars) | Dashboard routes | Phase 1 |
| 2.7.2 | Build timeline visualization (scene boundaries, speakers, emotion curve, topics, highlights) | Dashboard routes | Phase 1 |
| 2.7.3 | Build transcript panel (searchable, clickable timestamps, speaker labels) | Dashboard routes | Phase 1 |
| 2.7.4 | Build edit review page (clip preview player, platform mockups, metadata editor) | Dashboard routes | 2.4.7 |
| 2.7.5 | Build approve/reject/edit workflow (action buttons, feedback to AI) | Dashboard routes | 2.7.4 |
| 2.7.6 | Build batch review mode (swipe through clips, one-click approve/reject) | Dashboard routes | 2.7.5 |

### 5.2 Phase 2 Success Criteria

- [ ] AI can produce 10+ platform-ready clips from a single 1-hour source
- [ ] Render time < 30 seconds per clip (including audio + animations)
- [ ] Captions are word-accurate and properly timed (< 100ms drift)
- [ ] Output passes platform validation for all 5 target platforms
- [ ] Human can review and approve 20 clips in under 5 minutes via dashboard
- [ ] AI-generated music is coherent, mood-appropriate, and at least 30 seconds long
- [ ] DSP sound effects are clean (no clicks/pops) and properly timed
- [ ] Audio ducking correctly reduces music under speech within 200ms

### 5.3 Phase 2 Execution Order

```
Week 9-10: EDL + Captions + Cropping
  ├── 2.1.1-2.1.5 (EDL format)
  ├── 2.2.1-2.2.3 (captions)
  └── 2.3.1-2.3.4 (smart cropping)

Week 11-12: Rendering Pipeline
  ├── 2.4.1-2.4.9 (renderer, profiles, batch, thumbnails)
  └── 2.6.1-2.6.2 (metadata generation)

Week 13-14: Audio Generation Engine
  ├── 2.5.1-2.5.9 (ACE-Step, MIDI, DSP, mixer, MCP tools)
  └── Audio integration tests

Week 15-16: Dashboard + Integration
  ├── 2.7.1-2.7.6 (full dashboard)
  └── End-to-end editing workflow tests
```

---

## 6. Phase 3: Motion Graphics, Publishing & Full Dashboard -- NOT STARTED

**Goal:** 4-tier animation engine, platform API publishing, OAuth flows, publishing queue, complete dashboard.

### 6.1 Task Breakdown

#### 6.1.1 Animation Engine -- Tier 1: FFmpeg Native

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.1.1 | Implement FFmpeg native animations (drawtext fade/slide/typewriter, drawbox, progress bar) | `src/clipcannon/animation/ffmpeg_native.py` | Phase 2 |
| 3.1.2 | Implement 44+ xfade transitions | `src/clipcannon/animation/ffmpeg_native.py` | 3.1.1 |
| 3.1.3 | Port 60+ GL Transition shaders to FFmpeg xfade expressions | `assets/transitions/` | 3.1.2 |

#### 6.1.2 Animation Engine -- Tier 2: PyCairo

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.2.1 | Implement PyCairo frame renderer (RGBA PNG with transparency) | `src/clipcannon/animation/pycairo_renderer.py` | Phase 2 |
| 3.2.2 | Build 10 lower third templates (modern_bar, glass_panel, minimal_line, bold_stack, corner_tag, etc.) | `src/clipcannon/animation/templates.py` | 3.2.1 |
| 3.2.3 | Build title card renderer (fade_scale, slide_up, typewriter, kinetic_words) | `src/clipcannon/animation/pycairo_renderer.py` | 3.2.1 |
| 3.2.4 | Build callout/arrow renderer | `src/clipcannon/animation/pycairo_renderer.py` | 3.2.1 |
| 3.2.5 | Build social handle renderer (platform icons + username) | `src/clipcannon/animation/pycairo_renderer.py` | 3.2.1 |

#### 6.1.3 Animation Engine -- Tier 3: Lottie

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.3.1 | Implement rlottie-python rendering pipeline (JSON -> PNG frames) | `src/clipcannon/animation/lottie_renderer.py` | Phase 2 |
| 3.3.2 | Curate and ship 28 Lottie animations (CTAs, emojis, icons, decorative) | `assets/lottie/` | 3.3.1 |
| 3.3.3 | Implement optional LottieFiles.com API fetching + local cache | `src/clipcannon/animation/assets.py` | 3.3.1 |

#### 6.1.4 Animation Engine -- Tier 4: WebM Overlays

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.4.1 | Implement WebM VP9 alpha overlay compositing | `src/clipcannon/animation/webm_overlay.py` | Phase 2 |
| 3.4.2 | Create/curate 20 WebM assets (light leaks, bokeh, grain, glitch, particles, smoke, confetti) | `assets/webm/` | 3.4.1 |
| 3.4.3 | Implement custom asset import (user-provided WebM/Lottie) | `src/clipcannon/animation/assets.py` | 3.4.1 |

#### 6.1.5 Animation Compositing & MCP Tools

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.5.1 | Implement multi-layer overlay compositing (z-index ordering, enable windows) | `src/clipcannon/rendering/renderer.py` | 3.1.1-3.4.1 |
| 3.5.2 | Integrate animation rendering into render pipeline (parallel frame gen + FFmpeg composite) | `src/clipcannon/rendering/renderer.py` | 3.5.1 |
| 3.5.3 | Implement animation MCP tools (add_lower_third, add_animation, add_transition, list_animations, list_transitions) | `src/clipcannon/tools/animation.py` | 3.5.1 |

#### 6.1.6 Publishing -- OAuth & Platform Integration

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.6.1 | Implement OAuth 2.0 flow manager (token storage in OS keychain, refresh) | `src/clipcannon/publishing/oauth.py` | Phase 2 |
| 3.6.2 | Implement YouTube Data API v3 integration (resumable upload, metadata, #Shorts) | `src/clipcannon/publishing/youtube.py` | 3.6.1 |
| 3.6.3 | Implement Meta Graph API -- Instagram (Reels + Feed posting) | `src/clipcannon/publishing/instagram.py` | 3.6.1 |
| 3.6.4 | Implement TikTok Content Posting API (chunked upload + publish) | `src/clipcannon/publishing/tiktok.py` | 3.6.1 |
| 3.6.5 | Implement Meta Graph API -- Facebook (Reels + Feed posting) | `src/clipcannon/publishing/facebook.py` | 3.6.1 |
| 3.6.6 | Implement LinkedIn Marketing API (register upload + post) | `src/clipcannon/publishing/linkedin.py` | 3.6.1 |

#### 6.1.7 Publishing -- Queue & Workflow

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.7.1 | Implement publish queue (pending -> approved -> scheduled -> published -> rejected) | `src/clipcannon/publishing/queue.py` | Phase 2 |
| 3.7.2 | Implement scheduling (future publish times per platform) | `src/clipcannon/publishing/queue.py` | 3.7.1 |
| 3.7.3 | Implement post-publish status tracking | `src/clipcannon/publishing/queue.py` | 3.7.1, 3.6.2-3.6.6 |
| 3.7.4 | Implement publishing MCP tools (publish_review, publish_approve, publish_reject, publish_execute, publish_status, accounts_connect, accounts_disconnect) | `src/clipcannon/tools/publishing.py` | 3.7.1, 3.6.1 |

#### 6.1.8 Complete Dashboard

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.8.1 | Build publishing queue page (pending, approved, scheduled, published, rejected tabs) | Dashboard routes | 3.7.1 |
| 3.8.2 | Build platform connection page (OAuth flow triggers, status indicators) | Dashboard routes | 3.6.1 |
| 3.8.3 | Build account & billing page (credit history, spending limits, API key management) | Dashboard routes | 1.11.5 |
| 3.8.4 | Build settings page (processing defaults, platform profiles, GPU config) | Dashboard routes | 1.1.3 |
| 3.8.5 | Implement notification system (analysis complete, clips ready, publish success) | Dashboard routes | Phase 2 |

### 6.2 Phase 3 Success Criteria

- [ ] Lower thirds render at 1080p with smooth animation (no jank)
- [ ] Lottie animations render at correct frame rate with proper alpha transparency
- [ ] All 44+ FFmpeg native transitions work reliably
- [ ] 60+ GL Transition shader ports produce correct output
- [ ] Animation overlays do not degrade render speed by more than 20%
- [ ] OAuth flows work for all 5 platforms
- [ ] Successful automated posting with human approval gate
- [ ] Generated metadata is platform-appropriate and engaging
- [ ] Full audit trail of all publishing actions
- [ ] Credit billing accurate across all operations

### 6.3 Phase 3 Execution Order

```
Week 17-18: Animation Engine (All 4 Tiers)
  ├── 3.1.1-3.1.3 (FFmpeg native + transitions)
  ├── 3.2.1-3.2.5 (PyCairo lower thirds + title cards)
  ├── 3.3.1-3.3.3 (Lottie rendering + assets)
  └── 3.4.1-3.4.3 (WebM overlays + assets)

Week 19-20: Animation Integration + Publishing OAuth
  ├── 3.5.1-3.5.3 (compositing + MCP tools)
  └── 3.6.1-3.6.6 (OAuth + 5 platform APIs)

Week 21-22: Publishing Queue + Dashboard
  ├── 3.7.1-3.7.4 (publish queue + MCP tools)
  ├── 3.8.1-3.8.5 (complete dashboard)
  └── End-to-end publish workflow tests
```

---

## 7. Phase 4: Intelligence, Optimization & Growth -- NOT STARTED

**Goal:** Content performance feedback, A/B testing, template system, multi-language, marketplace, agency tier.

### 7.1 Task Breakdown

| Task | Description |
|:-----|:-----------|
| 4.1 | Content performance feedback loop (platform analytics API integration) |
| 4.2 | Improved highlight detection using performance data |
| 4.3 | A/B testing support (generate multiple versions of same clip) |
| 4.4 | Scheduling optimization (best time to post per platform) |
| 4.5 | Template system for recurring content types (save audio/animation presets) |
| 4.6 | Multi-language support (captions, metadata in multiple languages) |
| 4.7 | Advanced audio: ACE-Step LoRA fine-tuning, custom SoundFont import |
| 4.8 | Advanced animation: PyCairo template builder, brand kit system |
| 4.9 | Animation/template marketplace (community-contributed, credit-based) |
| 4.10 | Agency tier: multi-seat dashboard, team accounts, bulk pricing |
| 4.11 | Usage analytics dashboard: cost per video, ROI tracking |
| 4.12 | Unlimited subscription tier implementation |

Phase 4 is iterative and driven by user feedback from Phase 3 deployment.

---

## 8. Risk Mitigation

| Risk | Impact | Mitigation |
|:-----|:-------|:-----------|
| WhisperX timestamp drift on fast speech | High | Mandatory wav2vec2 forced alignment (20-50ms precision). Never use base Whisper timestamps. |
| HTDemucs fails on unusual audio | Medium | Fallback: skip separation, feed mixed audio to all streams. Graceful degradation. |
| VRAM exhaustion with all models loaded | High | NVFP4 precision keeps all models under 10.6 GB on RTX 5090. Fallback: sequential model loading on lower GPUs. |
| Smart cropping quality on complex scenes | Medium | Face-aware center crop as default. Fall back to center crop when no face detected. |
| Social media API rate limits | Low | Queue with rate limiting + exponential backoff. Batch scheduling. |
| Social media API deprecation/changes | Medium | Abstract platform adapters. Each platform is a separate module. |
| AI-generated music quality inconsistency | Medium | Seed-based generation for reproducibility. Fall back to MIDI composition. Human review. |
| Lottie rendering fidelity gaps | Low | Curate shipped assets for full rlottie compatibility. PyCairo fallback for custom overlays. |
| 25K token MCP response limit exceeded | High | All tools designed with pagination. Test response sizes with 4-hour source videos. |
| Generation loss (re-encoding rendered output) | High | Immutable source reference architecture. Renderer refuses to open files from renders/ dir. |

---

## 9. Testing Strategy

### Phase 1 Testing (Complete)

**Pytest suite** -- 181 tests across 8 files in a flat `tests/` directory:
- `test_pipeline_stages.py` -- Pipeline stage isolation with synthetic data
- `test_visual_pipeline.py` -- Visual stream stages
- `test_derived_stages.py` -- Derived stages (profanity, chronemic, highlights, storyboard, finalize)
- `test_understanding_tools.py` -- All 9 understanding MCP tools
- `test_billing.py` -- Credit charge, refund, HMAC, spending limits
- `test_provenance_integration.py` -- Hash chain computation, verification, tamper detection
- `dashboard/test_dashboard.py` -- Dashboard endpoint tests
- `integration/test_full_pipeline.py` -- Full pipeline integration

**FSV scripts** -- 750 checks across 4 standalone scripts:
- `fsv_core_infrastructure.py` -- 154 checks (exceptions, db, config, gpu, provenance)
- `fsv_pipeline_tools.py` -- 189 checks (DAG, stages, MCP tools, edge cases)
- `fsv_billing_dashboard.py` -- 84 checks (HMAC, credits, license server, dashboard)
- `fsv_server_integration.py` -- 323 checks (server, registry, full pytest gate)

### Future Phase Testing

**Integration Tests (Phase 2+):**
- Render workflow: EDL -> FFmpeg filter graph -> output validation (FFprobe)
- Audio workflow: ACE-Step -> mixer -> ducking -> final WAV
- Animation workflow: PyCairo frames + Lottie frames -> FFmpeg composite
- Publish workflow: mock platform APIs -> queue management

**End-to-End Tests (Phase 2+):**
- 1-hour source video -> full analysis -> 10+ clips -> render -> validate
- Dashboard: human-in-the-loop approve/reject cycle
- Billing: credit charge through full workflow, refund on failure

### Performance Benchmarks

- Ingestion speed: < 5 min for 1hr 1080p (RTX 5090)
- Render speed: < 30s per clip
- Music generation: < 5s per minute of audio
- SFX generation: < 100ms per effect
- VRAM peak: < 16GB during normal operation

---

## 10. Deployment Architecture

```
+----------------------------------------------------------+
|  Docker Container (NVIDIA Runtime, CUDA 13.2)            |
|                                                          |
|  +--------------+  +---------------+  +--------------+   |
|  | ClipCannon   |  | License       |  | Dashboard    |   |
|  | MCP Server   |  | Server        |  | Web UI       |   |
|  | stdio/SSE    |  | port 3100     |  | port 3200    |   |
|  | 27 tools     |  | (HTTP)        |  | (HTTP)       |   |
|  | (Phase 1)    |  | Billing/Auth  |  | Review/      |   |
|  |              |  | Credits       |  | Approve      |   |
|  +------+-------+  +---------------+  +--------------+   |
|         |                                                |
|  +------v--------------------------------------------+   |
|  |  GPU Processing Pipeline                          |   |
|  |  HTDemucs | WhisperX | SigLIP | Wav2Vec2 | WavLM |   |
|  |  SenseVoice | PaddleOCR | Nomic | Beat This!     |   |
|  +---------------------------------------------------+   |
|                                                          |
|  +---------------------------------------------------+   |
|  |  Storage: ~/.clipcannon/                          |   |
|  |  projects/{id}/analysis.db (SQLite + sqlite-vec)  |   |
|  |  projects/{id}/source/ frames/ stems/ storyboards/|   |
|  |  license.db (billing, HMAC-signed)                |   |
|  +---------------------------------------------------+   |
+----------------------------------------------------------+
         |
    MCP Protocol (stdio / SSE)
         |
+--------v---------+       +------------------+
|  AI Model         |       |  Cloudflare D1   |
|  (Claude Code)    |       |  (Phase 2+ only) |
|  1M context       |       |  Stripe webhooks |
+------------------+       +------------------+
```

---

## 11. Credit Cost Matrix

| Operation | Credit Cost | Rationale |
|:----------|:-----------|:----------|
| Video Analysis (full pipeline) | 10 credits | GPU-intensive: transcription + embeddings + frame extraction |
| Clip Render (per output clip, includes audio + animations) | 2 credits | NVENC encoding + caption burn + crop + audio mix + overlay |
| AI Music Generation (per track) | 0 credits | Included in clip render cost |
| Metadata Generation (per clip per platform) | 1 credit | AI-generated title + description + hashtags |
| Platform Publish (per post) | 1 credit | API call + upload + status tracking |

Phase 1 only uses the `analyze` operation (10 credits). Other operations are defined but not yet active.

---

## 12. MCP Tool Inventory

### Phase 1 -- Implemented (27 tools)

| Category | Count | Tools |
|:---------|:------|:------|
| Project Management | 5 | clipcannon_project_create, clipcannon_project_open, clipcannon_project_list, clipcannon_project_status, clipcannon_project_delete |
| Understanding -- Pipeline & Summary | 4 | clipcannon_ingest, clipcannon_get_vud_summary, clipcannon_get_analytics, clipcannon_get_transcript |
| Understanding -- Visual | 4 | clipcannon_get_segment_detail, clipcannon_get_frame, clipcannon_get_frame_strip, clipcannon_get_storyboard |
| Understanding -- Search | 1 | clipcannon_search_content |
| Provenance | 4 | clipcannon_provenance_verify, clipcannon_provenance_query, clipcannon_provenance_chain, clipcannon_provenance_timeline |
| Disk Management | 2 | clipcannon_disk_status, clipcannon_disk_cleanup |
| Configuration | 3 | clipcannon_config_get, clipcannon_config_set, clipcannon_config_list |
| Billing | 4 | clipcannon_credits_balance, clipcannon_credits_history, clipcannon_credits_estimate, clipcannon_spending_limit |

### Phase 2+ -- Planned (not yet implemented)

| Category | Count | Tools |
|:---------|:------|:------|
| Editing | 6 | clipcannon_create_edit, clipcannon_modify_edit, clipcannon_list_edits, clipcannon_get_edit, clipcannon_delete_edit, clipcannon_generate_metadata |
| Rendering | 5 | clipcannon_render, clipcannon_render_status, clipcannon_render_batch, clipcannon_render_preview, clipcannon_get_profiles |
| Audio | 5 | clipcannon_generate_music, clipcannon_compose_midi, clipcannon_generate_sfx, clipcannon_audio_status, clipcannon_list_soundfonts |
| Animation | 6 | clipcannon_add_lower_third, clipcannon_add_title_card, clipcannon_add_animation, clipcannon_add_transition, clipcannon_list_animations, clipcannon_list_transitions |
| Publishing | 8 | clipcannon_publish_review, clipcannon_publish_approve, clipcannon_publish_reject, clipcannon_publish_execute, clipcannon_publish_status, clipcannon_publish_schedule, clipcannon_accounts_connect, clipcannon_accounts_disconnect |

---

## 13. Key Design Decisions

1. **Single SQLite DB per project** -- All structured data (transcript, embeddings, provenance, EDLs) in one portable file. Binary media on disk referenced by path.

2. **sqlite-vec for vector search** -- KNN search in <15ms on 28K vectors. No external vector DB needed. Embedding space isolation enforced by separate virtual tables.

3. **typed-ffmpeg for rendering** -- Type-safe FFmpeg command building. AI writes EDL JSON; typed-ffmpeg builds the FFmpeg filter graph. No string concatenation of FFmpeg commands.

4. **WhisperX mandatory** -- Base Whisper timestamps drift 200-500ms. WhisperX with wav2vec2 forced alignment achieves 20-50ms precision. Non-negotiable for word-level captions.

5. **HTDemucs first in pipeline** -- Source separation before all audio analysis is a force multiplier. Every downstream audio model performs dramatically better on clean vocal stems.

6. **NVFP4 default on Blackwell** -- 87.5% VRAM savings. All models fit in 10.6 GB, leaving 21.4 GB free. Graceful fallback: INT8 -> FP16 on older GPUs.

7. **25K token MCP response limit** -- Every tool designed for progressive delivery. VUD is never sent as one blob. Pagination on transcript, storyboards, analytics.

8. **Immutable source reference** -- SHA-256 hash of original source video embedded in every EDL and render. Renderer refuses to use previously rendered output as input. Prevents generation loss.

9. **DAG-based graceful degradation** -- Required stages (probe, audio extract, frame extract, transcribe, vfr_normalize, finalize) stop pipeline on failure. Optional stages (14 total) provide fallback values and mark as failed in VUD.

10. **3-tier disk classification** -- Sacred (never delete), Regenerable (can recreate from sacred), Ephemeral (delete after use). Automatic cleanup of ephemeral files after pipeline completion.

11. **`mcp` library, not FastMCP** -- The MCP server uses the `mcp` Python library directly (Server class with `list_tools()` and `call_tool()` handlers), not the FastMCP wrapper. This provides full control over tool registration and dispatch.

---

*End of Implementation Plan*
