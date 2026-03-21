# ClipCannon Implementation Plan

**Version:** 1.0
**Date:** 2026-03-21
**Based on:** ClipCannon PRD v5.0 (PRD1-PRD6)

---

## 1. Implementation Overview

ClipCannon is an AI-native video editing MCP server that runs locally on consumer GPU hardware (target: RTX 5090). It decomposes video into 12 parallel understanding streams, delivers frames + transcript + embedder analytics to a multimodal AI, and produces platform-ready outputs for 5 social media platforms.

### Delivery Phases

| Phase | Name | Focus | Dependencies |
|:------|:-----|:------|:-------------|
| 1 | Foundation | MCP server, ingestion, understanding pipeline, billing, provenance | None |
| 2 | Editing Engine | EDL, rendering, audio gen, captions, cropping, dashboard | Phase 1 |
| 3 | Motion Graphics & Publishing | Animations, overlays, platform APIs, full dashboard | Phase 2 |
| 4 | Intelligence & Growth | Analytics feedback loop, A/B testing, marketplace, agency tier | Phase 3 |

---

## 2. Technology Stack

### Core Runtime

| Component | Technology | Version |
|:----------|:-----------|:--------|
| Language | Python 3.12+ | Latest stable |
| MCP Framework | FastMCP / mcp-python-sdk | Latest |
| Video Processing | FFmpeg 7.x | 7.x with NVENC/NVDEC |
| EDL Rendering | typed-ffmpeg v3.0 | Type-safe FFmpeg command builder |
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

### Audio Generation Models

| Component | Technology | License |
|:----------|:-----------|:--------|
| AI Music | ACE-Step v1.5 turbo-rl | MIT |
| MIDI Composition | MIDIUtil + music21 | MIT / LGPL |
| MIDI Rendering | FluidSynth + pyfluidsynth | LGPL |
| DSP/SFX | numpy + scipy.signal | BSD |
| Audio Mixing | pydub | MIT |
| Audio Effects | pedalboard (Spotify) | GPLv3 |

### Animation/Graphics

| Component | Technology | License |
|:----------|:-----------|:--------|
| 2D Vector Graphics | PyCairo + Pango | LGPL |
| Lottie Rendering | rlottie-python | MIT |
| Transition Shaders | xfade-easing (GL Transitions port) | MIT |
| WebM Overlays | FFmpeg VP9 alpha compositing | LGPL |

---

## 3. Project Structure

```
clipcannon/
├── src/
│   ├── clipcannon/
│   │   ├── __init__.py
│   │   ├── server.py                 # MCP server entry point (FastMCP)
│   │   ├── config.py                 # Configuration management
│   │   │
│   │   ├── tools/                    # MCP tool definitions (60+ tools)
│   │   │   ├── __init__.py
│   │   │   ├── project.py            # Project CRUD tools
│   │   │   ├── understanding.py      # Ingest, analyze, VUD tools
│   │   │   ├── editing.py            # EDL, edit creation tools
│   │   │   ├── rendering.py          # Render, batch render tools
│   │   │   ├── audio.py              # Music gen, SFX, MIDI tools
│   │   │   ├── animation.py          # Lower third, Lottie, WebM tools
│   │   │   ├── publishing.py         # Platform publish tools
│   │   │   ├── provenance.py         # Provenance query/verify tools
│   │   │   ├── disk.py               # Disk management tools
│   │   │   └── config_tools.py       # Configuration tools
│   │   │
│   │   ├── pipeline/                 # Processing pipeline stages
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py       # DAG-based pipeline runner
│   │   │   ├── probe.py              # FFprobe + VFR detection
│   │   │   ├── vfr_normalize.py      # VFR → CFR normalization
│   │   │   ├── audio_extract.py      # Audio demux
│   │   │   ├── source_separation.py  # HTDemucs stem separation
│   │   │   ├── frame_extract.py      # NVDEC frame extraction
│   │   │   ├── transcribe.py         # WhisperX transcription
│   │   │   ├── visual_embed.py       # SigLIP embedding + scene detection
│   │   │   ├── ocr.py                # PaddleOCR text detection
│   │   │   ├── quality.py            # BRISQUE + DOVER quality assessment
│   │   │   ├── shot_type.py          # ResNet-50 shot classification
│   │   │   ├── semantic_embed.py     # Nomic embedding + topic clustering
│   │   │   ├── emotion_embed.py      # Wav2Vec2 emotion analysis
│   │   │   ├── speaker_embed.py      # WavLM speaker diarization
│   │   │   ├── reactions.py          # SenseVoice reaction detection
│   │   │   ├── acoustic.py           # cuFFT spectral + Beat This!
│   │   │   ├── profanity.py          # Word list + NSFW detection
│   │   │   ├── chronemic.py          # Pacing computation
│   │   │   ├── highlights.py         # Multi-signal highlight scoring
│   │   │   ├── storyboard.py         # Storyboard grid generation
│   │   │   └── finalize.py           # Chain verification + status
│   │   │
│   │   ├── editing/                  # Edit decision engine
│   │   │   ├── __init__.py
│   │   │   ├── edl.py                # EDL schema + validation
│   │   │   ├── captions.py           # ASS subtitle generation
│   │   │   ├── smart_crop.py         # Face-aware cropping
│   │   │   └── metadata_gen.py       # AI metadata generation
│   │   │
│   │   ├── rendering/                # FFmpeg rendering
│   │   │   ├── __init__.py
│   │   │   ├── renderer.py           # typed-ffmpeg filter graph builder
│   │   │   ├── profiles.py           # Platform encoding profiles
│   │   │   ├── batch.py              # Batch render orchestration
│   │   │   └── thumbnail.py          # Thumbnail generation
│   │   │
│   │   ├── audio/                    # Audio generation engine
│   │   │   ├── __init__.py
│   │   │   ├── music_gen.py          # ACE-Step integration
│   │   │   ├── midi_compose.py       # MIDIUtil + music21 composition
│   │   │   ├── midi_render.py        # FluidSynth WAV rendering
│   │   │   ├── sfx.py                # DSP sound effects (numpy/scipy)
│   │   │   ├── mixer.py              # pydub audio mixing + ducking
│   │   │   └── effects.py            # pedalboard audio effects
│   │   │
│   │   ├── animation/                # Motion graphics engine
│   │   │   ├── __init__.py
│   │   │   ├── pycairo_renderer.py   # Lower thirds, title cards
│   │   │   ├── lottie_renderer.py    # rlottie-python rendering
│   │   │   ├── webm_overlay.py       # WebM alpha compositing
│   │   │   ├── ffmpeg_native.py      # FFmpeg drawtext/drawbox
│   │   │   ├── templates.py          # Animation template registry
│   │   │   └── assets.py             # Asset management + LottieFiles API
│   │   │
│   │   ├── publishing/               # Platform publishing
│   │   │   ├── __init__.py
│   │   │   ├── oauth.py              # OAuth 2.0 flow management
│   │   │   ├── youtube.py            # YouTube Data API v3
│   │   │   ├── instagram.py          # Meta Graph API (Reels/Feed)
│   │   │   ├── tiktok.py             # TikTok Content Posting API
│   │   │   ├── facebook.py           # Meta Graph API (Reels/Feed)
│   │   │   ├── linkedin.py           # LinkedIn Marketing API
│   │   │   └── queue.py              # Publish queue + scheduling
│   │   │
│   │   ├── billing/                  # Credit billing system
│   │   │   ├── __init__.py
│   │   │   ├── license_client.py     # Local license server client
│   │   │   ├── credits.py            # Credit charge/refund logic
│   │   │   └── hmac_integrity.py     # HMAC-SHA256 balance integrity
│   │   │
│   │   ├── provenance/               # Provenance hash chain
│   │   │   ├── __init__.py
│   │   │   ├── hasher.py             # SHA-256 file/table hashing
│   │   │   ├── chain.py              # Chain hash computation + verification
│   │   │   └── recorder.py           # Provenance record creation
│   │   │
│   │   ├── db/                       # Database layer
│   │   │   ├── __init__.py
│   │   │   ├── schema.py             # DDL + migrations
│   │   │   ├── connection.py         # WAL mode, pragmas, connection pool
│   │   │   └── queries.py            # Parameterized query helpers
│   │   │
│   │   ├── gpu/                      # GPU management
│   │   │   ├── __init__.py
│   │   │   ├── manager.py            # VRAM monitoring, model lifecycle
│   │   │   ├── green_contexts.py     # SM partitioning (Blackwell)
│   │   │   └── precision.py          # NVFP4/INT8/FP16 auto-selection
│   │   │
│   │   └── dashboard/                # Web dashboard
│   │       ├── __init__.py
│   │       ├── app.py                # FastAPI/Starlette app
│   │       ├── auth.py               # Magic link authentication
│   │       ├── routes/               # API routes
│   │       ├── static/               # Frontend assets
│   │       └── templates/            # HTML templates
│   │
│   └── license_server/               # Standalone license server
│       ├── __init__.py
│       ├── server.py                 # HTTP server (port 3100)
│       ├── d1_sync.py                # Cloudflare D1 sync
│       └── stripe_webhooks.py        # Stripe webhook handler
│
├── tests/
│   ├── unit/
│   │   ├── test_pipeline/
│   │   ├── test_editing/
│   │   ├── test_rendering/
│   │   ├── test_audio/
│   │   ├── test_animation/
│   │   ├── test_provenance/
│   │   └── test_billing/
│   ├── integration/
│   │   ├── test_full_pipeline.py
│   │   ├── test_render_workflow.py
│   │   └── test_publish_workflow.py
│   └── fixtures/
│       ├── sample_video_10s.mp4
│       └── sample_audio_10s.wav
│
├── config/
│   ├── default_config.json
│   ├── platform_profiles.json
│   └── docker-compose.yml
│
├── scripts/
│   ├── setup.sh                      # Environment setup
│   ├── download_models.py            # Model weight downloader
│   └── validate_gpu.py               # GPU capability checker
│
├── assets/
│   ├── lottie/                       # 28 shipped Lottie animations
│   ├── webm/                         # 20 pre-rendered WebM effects
│   ├── transitions/                  # 60+ GL Transition expressions
│   ├── fonts/                        # Bundled fonts
│   ├── soundfonts/                   # GeneralUser_GS.sf2
│   └── profanity/                    # Profanity word list
│
├── docs2/                            # PRD and planning documents
├── Dockerfile
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

---

## 4. Phase 1: Foundation

**Goal:** MCP server scaffold, video ingestion, 12-stream understanding pipeline, billing, provenance chain, basic dashboard.

### 4.1 Task Breakdown

#### 4.1.1 Project Scaffold & Infrastructure

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.1.1 | Initialize Python project with pyproject.toml, dependencies, linting | `pyproject.toml`, `src/clipcannon/__init__.py` | None |
| 1.1.2 | Set up Docker container with NVIDIA runtime, FFmpeg 7.x, CUDA 13.2 | `Dockerfile`, `config/docker-compose.yml` | None |
| 1.1.3 | Implement configuration management (load/save JSON config, defaults) | `src/clipcannon/config.py` | 1.1.1 |
| 1.1.4 | Implement GPU manager (detect GPU, VRAM monitoring, precision auto-select) | `src/clipcannon/gpu/manager.py`, `precision.py` | 1.1.1 |
| 1.1.5 | Create model weight downloader script | `scripts/download_models.py` | 1.1.1 |
| 1.1.6 | Create GPU validation script | `scripts/validate_gpu.py` | 1.1.4 |

#### 4.1.2 Database Layer

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.2.1 | Implement SQLite connection manager (WAL mode, pragmas, pool) | `src/clipcannon/db/connection.py` | 1.1.1 |
| 1.2.2 | Define full database schema with sqlite-vec virtual tables | `src/clipcannon/db/schema.py` | 1.2.1 |
| 1.2.3 | Implement parameterized query helpers | `src/clipcannon/db/queries.py` | 1.2.1 |
| 1.2.4 | Write schema migration system | `src/clipcannon/db/schema.py` | 1.2.2 |

**Schema tables:** project, transcript_segments, transcript_words, scenes, speakers, emotion_curve, topics, highlights, reactions, silence_gaps, acoustic, beats, beat_sections, music_sections, pacing, on_screen_text, text_change_events, profanity_events, content_safety, storyboard_grids, stream_status, provenance, edits, renders, publish_queue, session_state. **Vector tables (sqlite-vec):** vec_frames (1152-dim), vec_semantic (768-dim), vec_emotion (1024-dim), vec_speakers (512-dim).

#### 4.1.3 Provenance Hash Chain

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.3.1 | Implement SHA-256 file hasher (streaming for large files) | `src/clipcannon/provenance/hasher.py` | 1.1.1 |
| 1.3.2 | Implement chain hash computation (parent + input + output + operation) | `src/clipcannon/provenance/chain.py` | 1.3.1 |
| 1.3.3 | Implement provenance recorder (write records to DB, chain verification) | `src/clipcannon/provenance/recorder.py` | 1.3.2, 1.2.2 |

#### 4.1.4 MCP Server + Project Management Tools

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.4.1 | Set up FastMCP server scaffold with tool registry | `src/clipcannon/server.py` | 1.1.1 |
| 1.4.2 | Implement project management tools (create, open, list, status, delete) | `src/clipcannon/tools/project.py` | 1.4.1, 1.2.2 |
| 1.4.3 | Implement provenance query tools (verify, query, chain, timeline) | `src/clipcannon/tools/provenance.py` | 1.4.1, 1.3.3 |
| 1.4.4 | Implement disk management tools (status, cleanup) | `src/clipcannon/tools/disk.py` | 1.4.1 |
| 1.4.5 | Implement config tools (get, set, list) | `src/clipcannon/tools/config_tools.py` | 1.4.1, 1.1.3 |

#### 4.1.5 Pipeline Orchestrator

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.5.1 | Implement DAG-based pipeline orchestrator (required/optional task classification, graceful degradation) | `src/clipcannon/pipeline/orchestrator.py` | 1.2.2, 1.3.3 |

#### 4.1.6 Understanding Pipeline — Required Stages

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.6.1 | Implement FFprobe stage (probe metadata, VFR detection) | `src/clipcannon/pipeline/probe.py` | 1.5.1 |
| 1.6.2 | Implement VFR normalization (CFR re-encode via NVENC if VFR detected) | `src/clipcannon/pipeline/vfr_normalize.py` | 1.6.1 |
| 1.6.3 | Implement audio extraction (PCM 16kHz mono + original rate) | `src/clipcannon/pipeline/audio_extract.py` | 1.6.1 |
| 1.6.4 | Implement HTDemucs source separation (4 stems: vocals, music, drums, other) | `src/clipcannon/pipeline/source_separation.py` | 1.6.3 |
| 1.6.5 | Implement frame extraction (NVDEC 2fps JPEGs) | `src/clipcannon/pipeline/frame_extract.py` | 1.6.2 |
| 1.6.6 | Implement WhisperX transcription (forced alignment on vocal stem, word-level timestamps) | `src/clipcannon/pipeline/transcribe.py` | 1.6.4 |

#### 4.1.7 Understanding Pipeline — Visual Streams

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.7.1 | Implement SigLIP visual embedding + scene boundary detection | `src/clipcannon/pipeline/visual_embed.py` | 1.6.5 |
| 1.7.2 | Implement PaddleOCR text detection (1fps, dedup, slide transitions) | `src/clipcannon/pipeline/ocr.py` | 1.6.5 |
| 1.7.3 | Implement BRISQUE + DOVER quality assessment (GPU batch) | `src/clipcannon/pipeline/quality.py` | 1.6.5 |
| 1.7.4 | Implement ResNet-50 shot type classification | `src/clipcannon/pipeline/shot_type.py` | 1.7.1 |

#### 4.1.8 Understanding Pipeline — Audio/Text Streams

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.8.1 | Implement Nomic semantic embedding + topic clustering | `src/clipcannon/pipeline/semantic_embed.py` | 1.6.6 |
| 1.8.2 | Implement Wav2Vec2 emotion/energy analysis (on vocal stem) | `src/clipcannon/pipeline/emotion_embed.py` | 1.6.4 |
| 1.8.3 | Implement WavLM speaker diarization (on vocal stem) | `src/clipcannon/pipeline/speaker_embed.py` | 1.6.4 |
| 1.8.4 | Implement SenseVoice reaction detection (laughter, applause) | `src/clipcannon/pipeline/reactions.py` | 1.6.4 |
| 1.8.5 | Implement cuFFT acoustic analysis + Beat This! beat detection | `src/clipcannon/pipeline/acoustic.py` | 1.6.4 |

#### 4.1.9 Understanding Pipeline — Derived Streams

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.9.1 | Implement profanity detection (word list + CLIP-NSFW) | `src/clipcannon/pipeline/profanity.py` | 1.6.6, 1.7.1 |
| 1.9.2 | Implement chronemic computation (WPM, pause ratios, pacing) | `src/clipcannon/pipeline/chronemic.py` | 1.6.6, 1.8.3, 1.8.5 |
| 1.9.3 | Implement multi-signal highlight scoring | `src/clipcannon/pipeline/highlights.py` | 1.8.1, 1.8.2, 1.8.4, 1.7.3 |
| 1.9.4 | Implement storyboard grid generation (80 grids, adaptive interval) | `src/clipcannon/pipeline/storyboard.py` | 1.6.5 |
| 1.9.5 | Implement finalize stage (chain verification, stream status) | `src/clipcannon/pipeline/finalize.py` | All 1.6-1.9 |

#### 4.1.10 Video Understanding MCP Tools

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.10.1 | Implement clipcannon_ingest (orchestrates full pipeline) | `src/clipcannon/tools/understanding.py` | 1.5.1 |
| 1.10.2 | Implement clipcannon_get_vud_summary (~8K tokens) | `src/clipcannon/tools/understanding.py` | 1.2.3 |
| 1.10.3 | Implement clipcannon_get_analytics (~18K tokens) | `src/clipcannon/tools/understanding.py` | 1.2.3 |
| 1.10.4 | Implement clipcannon_get_transcript (paginated, ~12K/page) | `src/clipcannon/tools/understanding.py` | 1.2.3 |
| 1.10.5 | Implement clipcannon_get_segment_detail (~15K tokens) | `src/clipcannon/tools/understanding.py` | 1.2.3 |
| 1.10.6 | Implement clipcannon_get_frame (single frame + temporal metadata) | `src/clipcannon/tools/understanding.py` | 1.2.3 |
| 1.10.7 | Implement clipcannon_get_frame_strip (3x3 grid for a time range) | `src/clipcannon/tools/understanding.py` | 1.2.3 |
| 1.10.8 | Implement clipcannon_get_storyboard (batched, 12 grids/batch) | `src/clipcannon/tools/understanding.py` | 1.2.3 |
| 1.10.9 | Implement clipcannon_search_content (semantic search via sqlite-vec) | `src/clipcannon/tools/understanding.py` | 1.2.3 |

**Critical constraint:** Every MCP tool response must be under 25K tokens.

#### 4.1.11 Billing System

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.11.1 | Implement license server (HTTP, port 3100, SQLite cache) | `src/license_server/server.py` | 1.1.1 |
| 1.11.2 | Implement Cloudflare D1 sync (source of truth) | `src/license_server/d1_sync.py` | 1.11.1 |
| 1.11.3 | Implement Stripe webhook handler (credit purchase flow) | `src/license_server/stripe_webhooks.py` | 1.11.1 |
| 1.11.4 | Implement HMAC-SHA256 balance integrity | `src/clipcannon/billing/hmac_integrity.py` | 1.11.1 |
| 1.11.5 | Implement license client (charge/refund from MCP server) | `src/clipcannon/billing/license_client.py` | 1.11.1 |
| 1.11.6 | Implement credit system (charge rates per operation, spending caps) | `src/clipcannon/billing/credits.py` | 1.11.5 |

#### 4.1.12 Basic Dashboard

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 1.12.1 | Set up FastAPI dashboard app (port 3200) | `src/clipcannon/dashboard/app.py` | 1.1.1 |
| 1.12.2 | Implement magic link authentication (JWT, Resend email) | `src/clipcannon/dashboard/auth.py` | 1.12.1 |
| 1.12.3 | Build home page (credit balance, system health, GPU status) | `src/clipcannon/dashboard/routes/` | 1.12.1, 1.11.5 |
| 1.12.4 | Build credit purchase page (Stripe checkout integration) | `src/clipcannon/dashboard/routes/` | 1.12.1, 1.11.3 |
| 1.12.5 | Build provenance chain viewer page | `src/clipcannon/dashboard/routes/` | 1.12.1, 1.3.3 |

### 4.2 Phase 1 Success Criteria

- [ ] Process a 1-hour video in under 5 minutes (RTX 5090)
- [ ] Word-level timestamps with WER < 5% on English content
- [ ] Scene detection captures 90%+ of visual transitions
- [ ] Credit charge/refund flow works end-to-end
- [ ] VUD contains AI-readable data (text labels, scores, timestamps) — not raw embeddings
- [ ] Provenance chain has 19 records with valid chain hashes
- [ ] clipcannon_provenance_verify passes on every completed project
- [ ] Any file modification after provenance recording is detected by hash mismatch
- [ ] All MCP tool responses under 25K tokens

### 4.3 Phase 1 Execution Order

```
Week 1-2: Scaffold + DB + Provenance
  ├── 1.1.1-1.1.6 (project setup, Docker, GPU manager)
  ├── 1.2.1-1.2.4 (database layer + schema)
  ├── 1.3.1-1.3.3 (provenance chain)
  └── 1.4.1-1.4.5 (MCP server + project tools)

Week 3-4: Core Pipeline (Required Stages)
  ├── 1.5.1 (pipeline orchestrator)
  ├── 1.6.1-1.6.6 (probe, VFR, audio, HTDemucs, frames, WhisperX)
  └── Tests for each stage

Week 5-6: Full Understanding Pipeline
  ├── 1.7.1-1.7.4 (visual streams)
  ├── 1.8.1-1.8.5 (audio/text streams)
  ├── 1.9.1-1.9.5 (derived streams + finalize)
  └── Integration tests

Week 7-8: MCP Tools + Billing + Dashboard
  ├── 1.10.1-1.10.9 (understanding MCP tools)
  ├── 1.11.1-1.11.6 (billing system)
  ├── 1.12.1-1.12.5 (basic dashboard)
  └── End-to-end testing
```

---

## 5. Phase 2: Editing Engine + Audio + Dashboard

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
| 2.4.1 | Implement typed-ffmpeg filter graph builder (EDL → FFmpeg command) | `src/clipcannon/rendering/renderer.py` | 2.1.1 |
| 2.4.2 | Implement platform encoding profiles (all 7 profiles from PRD) | `src/clipcannon/rendering/profiles.py` | 2.4.1 |
| 2.4.3 | Implement single-pass rendering (multi-segment EDL → one FFmpeg command) | `src/clipcannon/rendering/renderer.py` | 2.4.1 |
| 2.4.4 | Implement generation loss prevention (source SHA-256 verification) | `src/clipcannon/rendering/renderer.py` | 2.4.1, 1.3.1 |
| 2.4.5 | Implement batch rendering (up to 3 parallel NVENC sessions) | `src/clipcannon/rendering/batch.py` | 2.4.3 |
| 2.4.6 | Implement thumbnail generation | `src/clipcannon/rendering/thumbnail.py` | 2.4.1 |
| 2.4.7 | Implement clipcannon_render MCP tool | `src/clipcannon/tools/rendering.py` | 2.4.3 |
| 2.4.8 | Implement clipcannon_render_status MCP tool | `src/clipcannon/tools/rendering.py` | 2.4.7 |
| 2.4.9 | Implement clipcannon_render_batch MCP tool | `src/clipcannon/tools/rendering.py` | 2.4.5 |

#### 5.1.5 AI Audio Generation Engine

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 2.5.1 | Implement ACE-Step v1.5 integration (text prompt → music WAV) | `src/clipcannon/audio/music_gen.py` | Phase 1 |
| 2.5.2 | Implement MIDI composition pipeline (MIDIUtil + music21 progressions) | `src/clipcannon/audio/midi_compose.py` | Phase 1 |
| 2.5.3 | Implement FluidSynth MIDI → WAV rendering | `src/clipcannon/audio/midi_render.py` | 2.5.2 |
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
| 2.7.1 | Build project view page (source video, analysis status, 12-stream progress bars) | Dashboard routes | Phase 1 |
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

## 6. Phase 3: Motion Graphics, Publishing & Full Dashboard

**Goal:** 4-tier animation engine, platform API publishing, OAuth flows, publishing queue, complete dashboard.

### 6.1 Task Breakdown

#### 6.1.1 Animation Engine — Tier 1: FFmpeg Native

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.1.1 | Implement FFmpeg native animations (drawtext fade/slide/typewriter, drawbox, progress bar) | `src/clipcannon/animation/ffmpeg_native.py` | Phase 2 |
| 3.1.2 | Implement 44+ xfade transitions | `src/clipcannon/animation/ffmpeg_native.py` | 3.1.1 |
| 3.1.3 | Port 60+ GL Transition shaders to FFmpeg xfade expressions | `assets/transitions/` | 3.1.2 |

#### 6.1.2 Animation Engine — Tier 2: PyCairo

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.2.1 | Implement PyCairo frame renderer (RGBA PNG with transparency) | `src/clipcannon/animation/pycairo_renderer.py` | Phase 2 |
| 3.2.2 | Build 10 lower third templates (modern_bar, glass_panel, minimal_line, bold_stack, corner_tag, etc.) | `src/clipcannon/animation/templates.py` | 3.2.1 |
| 3.2.3 | Build title card renderer (fade_scale, slide_up, typewriter, kinetic_words) | `src/clipcannon/animation/pycairo_renderer.py` | 3.2.1 |
| 3.2.4 | Build callout/arrow renderer | `src/clipcannon/animation/pycairo_renderer.py` | 3.2.1 |
| 3.2.5 | Build social handle renderer (platform icons + username) | `src/clipcannon/animation/pycairo_renderer.py` | 3.2.1 |

#### 6.1.3 Animation Engine — Tier 3: Lottie

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.3.1 | Implement rlottie-python rendering pipeline (JSON → PNG frames) | `src/clipcannon/animation/lottie_renderer.py` | Phase 2 |
| 3.3.2 | Curate and ship 28 Lottie animations (CTAs, emojis, icons, decorative) | `assets/lottie/` | 3.3.1 |
| 3.3.3 | Implement optional LottieFiles.com API fetching + local cache | `src/clipcannon/animation/assets.py` | 3.3.1 |

#### 6.1.4 Animation Engine — Tier 4: WebM Overlays

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

#### 6.1.6 Publishing — OAuth & Platform Integration

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.6.1 | Implement OAuth 2.0 flow manager (token storage in OS keychain, refresh) | `src/clipcannon/publishing/oauth.py` | Phase 2 |
| 3.6.2 | Implement YouTube Data API v3 integration (resumable upload, metadata, #Shorts) | `src/clipcannon/publishing/youtube.py` | 3.6.1 |
| 3.6.3 | Implement Meta Graph API — Instagram (Reels + Feed posting) | `src/clipcannon/publishing/instagram.py` | 3.6.1 |
| 3.6.4 | Implement TikTok Content Posting API (chunked upload + publish) | `src/clipcannon/publishing/tiktok.py` | 3.6.1 |
| 3.6.5 | Implement Meta Graph API — Facebook (Reels + Feed posting) | `src/clipcannon/publishing/facebook.py` | 3.6.1 |
| 3.6.6 | Implement LinkedIn Marketing API (register upload + post) | `src/clipcannon/publishing/linkedin.py` | 3.6.1 |

#### 6.1.7 Publishing — Queue & Workflow

| Task | Description | Files | Deps |
|:-----|:-----------|:------|:-----|
| 3.7.1 | Implement publish queue (pending → approved → scheduled → published → rejected) | `src/clipcannon/publishing/queue.py` | Phase 2 |
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

## 7. Phase 4: Intelligence, Optimization & Growth

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

### Unit Tests (per module)
- Pipeline stage isolation: each stage tested with fixture inputs
- EDL validation: valid/invalid EDL schemas
- Provenance chain: hash computation, chain verification, tamper detection
- Credit billing: charge, refund, insufficient balance, HMAC verification
- Caption generation: chunking, timing, ASS format correctness
- Smart crop: face position → crop calculation for all aspect ratios

### Integration Tests
- Full pipeline: 10-second fixture video through all 12 streams
- Render workflow: EDL → FFmpeg filter graph → output validation (FFprobe)
- Audio workflow: ACE-Step → mixer → ducking → final WAV
- Animation workflow: PyCairo frames + Lottie frames → FFmpeg composite
- Publish workflow: mock platform APIs → queue management

### End-to-End Tests
- 1-hour source video → full analysis → 10+ clips → render → validate
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
┌──────────────────────────────────────────────────────────┐
│  Docker Container (NVIDIA Runtime, CUDA 13.2)            │
│                                                          │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐ │
│  │ ClipCannon   │  │ License       │  │ Dashboard    │ │
│  │ MCP Server   │  │ Server        │  │ Web UI       │ │
│  │ port 3366    │  │ port 3100     │  │ port 3200    │ │
│  │ (stdio/SSE)  │  │ (HTTP)        │  │ (HTTP)       │ │
│  │ 60+ tools    │  │ Billing/Auth  │  │ Review/      │ │
│  │              │  │ Credits       │  │ Approve      │ │
│  └──────┬───────┘  └───────────────┘  └──────────────┘ │
│         │                                                │
│  ┌──────▼────────────────────────────────────────────┐  │
│  │  GPU Processing Pipeline                           │  │
│  │  HTDemucs │ WhisperX │ SigLIP │ Wav2Vec2 │ WavLM │  │
│  │  SenseVoice │ PaddleOCR │ Nomic │ Beat This!     │  │
│  │  ACE-Step │ NVENC ×3 │ NVDEC ×2 │ cuFFT         │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Storage: ~/.clipcannon/                           │  │
│  │  projects/{id}/analysis.db (SQLite + sqlite-vec)  │  │
│  │  projects/{id}/source/ frames/ stems/ renders/    │  │
│  │  models/ assets/ soundfonts/                      │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
         │
    MCP Protocol (stdio / SSE)
         │
┌────────▼─────────┐       ┌──────────────────┐
│  AI Model         │       │  Cloudflare D1   │
│  (Claude Code)    │       │  (billing truth) │
│  1M context       │       │  Stripe webhooks │
└──────────────────┘       └──────────────────┘
```

---

## 11. Credit Cost Matrix

| Operation | Credit Cost | Rationale |
|:----------|:-----------|:----------|
| Video Analysis (full 12-stream pipeline) | 10 credits | GPU-intensive: transcription + embeddings + frame extraction |
| Clip Render (per output clip, includes audio + animations) | 2 credits | NVENC encoding + caption burn + crop + audio mix + overlay |
| AI Music Generation (per track) | 0 credits | Included in clip render cost |
| Metadata Generation (per clip per platform) | 1 credit | AI-generated title + description + hashtags |
| Platform Publish (per post) | 1 credit | API call + upload + status tracking |

---

## 12. MCP Tool Inventory (60+ tools)

### Project Management (5)
clipcannon_project_create, clipcannon_project_open, clipcannon_project_list, clipcannon_project_status, clipcannon_project_delete

### Video Understanding (12)
clipcannon_ingest, clipcannon_transcribe, clipcannon_analyze_frames, clipcannon_analyze_audio, clipcannon_analyze_scenes, clipcannon_get_vud_summary, clipcannon_get_analytics, clipcannon_get_transcript, clipcannon_get_segment_detail, clipcannon_get_frame, clipcannon_get_frame_strip, clipcannon_get_storyboard, clipcannon_search_content

### Editing (6)
clipcannon_create_edit, clipcannon_modify_edit, clipcannon_list_edits, clipcannon_get_edit, clipcannon_delete_edit, clipcannon_generate_metadata

### Rendering (5)
clipcannon_render, clipcannon_render_status, clipcannon_render_batch, clipcannon_render_preview, clipcannon_get_profiles

### Audio (5)
clipcannon_generate_music, clipcannon_compose_midi, clipcannon_generate_sfx, clipcannon_audio_status, clipcannon_list_soundfonts

### Animation (6)
clipcannon_add_lower_third, clipcannon_add_title_card, clipcannon_add_animation, clipcannon_add_transition, clipcannon_list_animations, clipcannon_list_transitions

### Publishing (8)
clipcannon_publish_review, clipcannon_publish_approve, clipcannon_publish_reject, clipcannon_publish_execute, clipcannon_publish_status, clipcannon_publish_schedule, clipcannon_accounts_connect, clipcannon_accounts_disconnect

### Provenance (4)
clipcannon_provenance_verify, clipcannon_provenance_query, clipcannon_provenance_chain, clipcannon_provenance_timeline

### Billing (4)
clipcannon_credits_balance, clipcannon_credits_history, clipcannon_credits_estimate, clipcannon_spending_limit

### Disk Management (2)
clipcannon_disk_status, clipcannon_disk_cleanup

### Configuration (3)
clipcannon_config_get, clipcannon_config_set, clipcannon_config_list

---

## 13. Key Design Decisions

1. **Single SQLite DB per project** — All structured data (transcript, embeddings, provenance, EDLs) in one portable file. Binary media on disk referenced by path.

2. **sqlite-vec for vector search** — KNN search in <15ms on 28K vectors. No external vector DB needed. Embedding space isolation enforced by separate virtual tables.

3. **typed-ffmpeg for rendering** — Type-safe FFmpeg command building. AI writes EDL JSON; typed-ffmpeg builds the FFmpeg filter graph. No string concatenation of FFmpeg commands.

4. **WhisperX mandatory** — Base Whisper timestamps drift 200-500ms. WhisperX with wav2vec2 forced alignment achieves 20-50ms precision. Non-negotiable for word-level captions.

5. **HTDemucs first in pipeline** — Source separation before all audio analysis is a force multiplier. Every downstream audio model performs dramatically better on clean vocal stems.

6. **NVFP4 default on Blackwell** — 87.5% VRAM savings. All models fit in 10.6 GB, leaving 21.4 GB free. Graceful fallback: INT8 → FP16 on older GPUs.

7. **25K token MCP response limit** — Every tool designed for progressive delivery. VUD is never sent as one blob. Pagination on transcript, storyboards, analytics.

8. **Immutable source reference** — SHA-256 hash of original source video embedded in every EDL and render. Renderer refuses to use previously rendered output as input. Prevents generation loss.

9. **DAG-based graceful degradation** — Required tasks (probe, audio extract, transcribe) stop pipeline on failure. Optional tasks (OCR, emotion, beat detection) provide fallback values and mark as failed in VUD.

10. **3-tier disk classification** — Sacred (never delete), Regenerable (can recreate from sacred), Ephemeral (delete after use). Automatic cleanup of ephemeral files after pipeline completion.

---

*End of Implementation Plan*
