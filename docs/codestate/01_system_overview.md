# ClipCannon System Overview

**Version**: 0.1.0 (Phase 1 + Phase 2 + Phase 3)
**Python**: >=3.12
**License**: MIT
**Build System**: Hatchling

## What ClipCannon Is

ClipCannon is an AI-powered video understanding, editing, rendering, and voice/avatar pipeline exposed as an MCP (Model Context Protocol) server. An AI assistant connects to ClipCannon over MCP, sends tool calls to analyze video files, create edits, render platform-optimized clips, generate audio, clone voices, and produce lip-synced talking-head videos. The pipeline ingests a source video, runs it through a 21-stage analysis DAG (transcription, scene detection, scene analysis, emotion analysis, beat tracking, and more), and stores all results in a per-project SQLite database. The assistant then queries that database through additional MCP tools to retrieve transcripts, analytics, frames, storyboards, scene maps, editing context, narrative analysis, and discovery data -- and uses the editing, rendering, audio, voice, and avatar tools to produce platform-ready video clips.

## Architecture

ClipCannon runs as three separate processes:

| Process | Port | Technology | Purpose |
|---------|------|------------|---------|
| MCP Server | stdio (or SSE on 3366) | `mcp` SDK + Python asyncio | Exposes 51 tools to AI assistants via MCP protocol |
| License Server | 3100 | FastAPI + Uvicorn | Credit billing, HMAC balance integrity, Stripe webhooks |
| Dashboard | 3200 | FastAPI + static HTML | Web UI for credits, projects, provenance, editing, review, and system health |

The MCP server uses stdio transport by default (the `clipcannon` console script). The license server and dashboard are separate FastAPI applications.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| MCP Protocol | `mcp>=1.0.0` (Server, stdio_server, Tool, TextContent) |
| Validation | `pydantic>=2.0` (config models, provenance records, billing models, EDL models) |
| HTTP Client | `httpx>=0.25.0` (license server communication) |
| Web Framework | `fastapi>=0.110.0` + `uvicorn>=0.30.0` (license server, dashboard) |
| Authentication | `python-jose[cryptography]>=3.3.0` (JWT-based dev auth) |
| Image Processing | `Pillow>=10.0.0` (frame grid composition, thumbnail generation, contact sheets) |
| Numerical | `numpy>=1.26.0`, `scipy>=1.12.0` |
| Billing | `stripe>=8.0.0` (webhook handling, credit packages) |
| Database | SQLite3 (stdlib) + `sqlite-vec>=0.1.0` (vector KNN search) |
| GPU (optional) | `torch>=2.3.0`, `faster-whisper>=1.0.0`, `transformers>=4.40.0`, `sentence-transformers>=3.0.0`, `demucs>=4.0.0`, `librosa>=0.10.0` |
| Audio (Phase 2) | `pydub` (audio mixing), `pedalboard` (effects processing), `midiutil` (MIDI composition), `pyfluidsynth` (MIDI rendering), `ace-step` (AI music generation) |
| Video (Phase 2) | `mediapipe` (face detection for smart cropping), `opencv-python` (scene analysis, frame processing), `rembg` (subject extraction) |
| Voice (Phase 3) | `speechbrain` (ECAPA-VOXCELEB speaker encoder), Qwen3-TTS (voice synthesis) |
| Avatar (Phase 3) | LatentSync 1.6 (ByteDance diffusion-based lip-sync) |

ML dependencies are in the `[ml]` optional extra and are not required for the MCP server to start. Phase 2 audio/video dependencies are in the `[phase2]` optional extra. Phase 3 voice/avatar reuses the `[ml]` group.

## MCP Tools (51 Total)

### Project Management (5 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_project_create` | Create a new project from a source video file. Validates format, runs ffprobe, computes SHA-256, initializes database. |
| `clipcannon_project_open` | Open an existing project and return its current state from the database. |
| `clipcannon_project_list` | List all projects, optionally filtered by status (created, analyzing, ready, error). |
| `clipcannon_project_status` | Get detailed status including pipeline stream progress, completion percentages, and disk usage. |
| `clipcannon_project_delete` | Delete a project directory. Can optionally preserve the original source video. |

### Understanding (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_ingest` | Run the full 21-stage analysis pipeline on a created project. Registers all stages, executes the DAG, returns results. |
| `clipcannon_get_transcript` | Get transcript with word-level timestamps. Paginated in 15-minute windows. Supports `text` and `words` detail levels. |
| `clipcannon_get_frame` | Get the nearest frame to a timestamp with moment context (transcript, speaker, emotion, topic, shot type, quality, pacing, OCR, profanity). Returns inline base64 image. Supports `render_id` for inspecting rendered output. |
| `clipcannon_search_content` | Search video content by semantic similarity (sqlite-vec + Nomic embeddings) or text match (SQL LIKE fallback). |

### Discovery (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_find_best_moments` | Find key moments with purpose-aware scoring (hook, highlight, cta, tutorial_step). Cross-stream convergence analysis. |
| `clipcannon_find_cut_points` | Find natural edit boundaries with cross-stream convergence scoring (silence, beat, scene, sentence). |
| `clipcannon_get_narrative_flow` | Analyze narrative coherence of proposed segments before creating an edit. |
| `clipcannon_find_safe_cuts` | Find audio-safe cut points across entire video using multiple analysis streams. |

### Disk Management (2 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_disk_status` | Show disk usage for a project classified by storage tier: sacred, regenerable, ephemeral. |
| `clipcannon_disk_cleanup` | Free disk space by deleting ephemeral files first, then regenerable (largest first). Sacred files are never touched. |

### Configuration (3 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_config_get` | Get a configuration value by dot-notation key (e.g., `processing.whisper_model`). |
| `clipcannon_config_set` | Set a configuration value, validate against the Pydantic schema, and persist to disk. |
| `clipcannon_config_list` | List all configuration values with their current settings. |

### Editing (11 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_create_edit` | Create a new edit from an EDL specification. Auto-generates captions from transcript words, validates segments against source. Supports canvas compositing. |
| `clipcannon_modify_edit` | Modify a draft edit via deep merge. Re-validates and regenerates captions if segments change. Auto-saves version history. |
| `clipcannon_auto_trim` | Analyze transcript to find filler words and long pauses, generate optimized segments that remove them. Returns segments ready for create_edit. |
| `clipcannon_color_adjust` | Apply color grading (brightness, contrast, saturation, gamma, hue shift) globally or per-segment. |
| `clipcannon_add_motion` | Add motion effects to segments: zoom_in, zoom_out, pan_left/right/up/down, ken_burns. Configurable easing. |
| `clipcannon_add_overlay` | Add visual overlays: lower_third, title_card, logo, watermark, cta. Includes position, timing, animation. |
| `clipcannon_edit_history` | List version history for an edit showing all saved versions. |
| `clipcannon_revert_edit` | Revert an edit to a previous version with automatic versioning. |
| `clipcannon_apply_feedback` | Apply natural language feedback to an edit (e.g., "make it shorter", "cut the intro"). |
| `clipcannon_branch_edit` | Fork an edit into a platform-specific variant (e.g., TikTok -> Instagram). |
| `clipcannon_list_branches` | List all branches of an edit. |

### Rendering (8 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_render` | Render a single edit to a platform-optimized video file. Charges 2 credits. Supports NVENC GPU acceleration with software fallback. |
| `clipcannon_get_editing_context` | Get ALL data needed for editing decisions in one call: transcript, highlights, silence gaps, pacing, scene boundaries, narrative analysis. |
| `clipcannon_analyze_frame` | Analyze a frame for content regions and webcam PIP overlay. Returns bounding boxes. ~125ms per frame. No credits. |
| `clipcannon_preview_clip` | Render a short (2-5 second) low-quality 540p preview of an edit. No credits charged. |
| `clipcannon_inspect_render` | Inspect rendered output: extracts frames at 5 key timestamps, probes metadata, runs quality checks. |
| `clipcannon_preview_layout` | Generate a single preview frame showing canvas layout at a timestamp. ~300ms. No credits. |
| `clipcannon_get_scene_map` | Get scene map with time-window pagination: scene boundaries, face positions, webcam region, content area, pre-computed canvas regions for layouts A/B/C/D, aligned transcript. |
| `clipcannon_preview_segment` | Low-quality preview of a specific segment. No credits. |

### Audio Generation (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_generate_music` | Generate AI music from a text prompt using ACE-Step v1.5 diffusion model (requires GPU). |
| `clipcannon_compose_midi` | Compose MIDI from 6 presets (ambient_pad, upbeat_pop, corporate, dramatic, minimal_piano, intro_jingle) and render to WAV via FluidSynth. |
| `clipcannon_generate_sfx` | Generate programmatic DSP sound effects (9 types: whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger). |
| `clipcannon_audio_cleanup` | Clean up source audio: noise reduction, normalization, silence trimming, EQ adjustment. |

### Voice (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_prepare_voice_data` | Extract vocal stems from ingested projects, split at silence boundaries, match with transcript, produce training manifests. |
| `clipcannon_voice_profiles` | Manage voice profiles: list, get, create, delete, update. Stores speaker embeddings and verification thresholds. |
| `clipcannon_speak` | Synthesize speech in a cloned voice via Qwen3-TTS with iterative multi-gate verification (sanity, intelligibility, identity). |
| `clipcannon_speak_optimized` | SECS-optimized synthesis: generate N candidates, score by speaker encoder cosine similarity, return best match. |

### Avatar (1 tool)

| Tool | Description |
|------|-------------|
| `clipcannon_lip_sync` | Generate lip-synced talking-head video using LatentSync 1.6 (ByteDance) diffusion pipeline. Takes audio + driver video, produces synced output. |

### Video Generation (1 tool)

| Tool | Description |
|------|-------------|
| `clipcannon_generate_video` | End-to-end video generation: voice synthesis (Qwen3-TTS) + lip-sync (LatentSync) from a text script and driver video. |

### Billing (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_credits_balance` | Get current credit balance, monthly spending, and spending limit. Shows warning at 80% of limit. |
| `clipcannon_credits_history` | Get transaction history showing charges, refunds, and purchases. Newest first. |
| `clipcannon_credits_estimate` | Estimate the credit cost for an operation: analyze (10), render (2), metadata (1), publish (1). |
| `clipcannon_spending_limit` | Set the monthly spending limit in credits. Operations exceeding this limit are blocked. |

## Pipeline Stages (21 Stages)

The analysis pipeline is a DAG of 21 stages. 16 analysis streams are tracked in the `stream_status` table:

`source_separation`, `visual`, `ocr`, `quality`, `shot_type`, `transcription`, `semantic`, `emotion`, `speaker`, `reactions`, `acoustic`, `beats`, `chronemic`, `storyboards`, `profanity`, `highlights`

Additional orchestration and analysis stages exist in the registry (`probe`, `vfr_normalize`, `audio_extract`, `frame_extract`, `scene_analysis`, `finalize`) that are part of the execution DAG. The `scene_analysis` stage runs after `frame_extract` and analyzes every frame for scene boundaries, face positions, webcam overlay regions, and content areas, storing results in the `scene_map` table.

## Project Directory Structure

Each project lives under `~/.clipcannon/projects/{project_id}/`:

```
~/.clipcannon/projects/proj_a1b2c3d4/
    analysis.db          # SQLite database (all analysis results + provenance + edits + renders + scene_map)
    source/              # Original source video (copied on project create)
    stems/               # Audio stems from source separation (vocal, music, etc.)
    frames/              # Extracted frames (frame_000001.jpg, frame_000002.jpg, ...)
    storyboards/         # Contact sheet images
    edits/               # Edit working directories (captions, metadata, audio)
    renders/             # Rendered output video files and thumbnails
```

### Storage Tier Classification

| Tier | Files | Policy |
|------|-------|--------|
| **Sacred** | `analysis.db`, `analysis.db-wal`, `analysis.db-shm`, everything in `source/` | Never auto-deleted |
| **Regenerable** | `source_cfr.mp4`, everything in `stems/`, `frames/`, `storyboards/` | Can be recreated by re-running pipeline stages |
| **Ephemeral** | Everything else (logs, temp files) | Safe to delete anytime |

## Database Schema

Each project's `analysis.db` uses schema version 3 and contains:

**Phase 1 tables (22)**: `schema_version`, `project`, `transcript_segments`, `transcript_words`, `scenes`, `speakers`, `emotion_curve`, `topics`, `highlights`, `reactions`, `silence_gaps`, `acoustic`, `music_sections`, `beats`, `beat_sections`, `on_screen_text`, `text_change_events`, `profanity_events`, `content_safety`, `pacing`, `storyboard_grids`, `stream_status`, `provenance`

**Phase 2 tables (6)**: `edits`, `edit_segments`, `renders`, `audio_assets`, `edit_versions`, `segment_cache`

**Scene analysis table (1)**: `scene_map` -- stores per-scene face positions, webcam regions, content areas, layout recommendations, and pre-computed canvas regions for layouts A/B/C/D

**Vector tables** (sqlite-vec `vec0`): `vec_frames` (float[1152]), `vec_semantic` (float[768]), `vec_emotion` (float[1024]), `vec_speakers` (float[512])

**Phase 3 table (1)**: `voice_profiles` -- stores voice profile metadata, speaker embeddings, verification thresholds. Located in `~/.clipcannon/voice_profiles.db` (separate from project databases).

Schema version: 3 (migrated from v1 -> v2 -> v3 via `migrate_to_v2()` and `migrate_to_v3()`). Connection pragmas: WAL journal mode, NORMAL synchronous, 64MB cache, foreign keys ON, temp store in memory.

## Exception Hierarchy

```
ClipCannonError (base)
    PipelineError     -- pipeline stage failures (includes stage_name, operation)
    BillingError      -- credit checks, charges, refunds, HMAC validation
    ProvenanceError   -- hash computation, chain verification, tamper detection
    DatabaseError     -- connections, schema, queries, sqlite-vec loading
    ConfigError       -- missing config, invalid values, validation failures
    GPUError          -- device detection, VRAM exhaustion, model loading
```

All exceptions carry a `message` string and a `details` dictionary.

## Entry Points

| Script | Module | Description |
|--------|--------|-------------|
| `clipcannon` | `clipcannon.server:main` | MCP server on stdio transport (defined in pyproject.toml `[project.scripts]`) |
| License server | `license_server.server:app` | Run via `uvicorn license_server.server:app --port 3100` |
| Dashboard | `clipcannon.dashboard.app:create_app` | Run via `uvicorn clipcannon.dashboard.app:app --port 3200` |

## Credit System

| Operation | Cost (credits) |
|-----------|---------------|
| analyze | 10 |
| render | 2 |
| metadata | 1 |
| publish | 1 |

Credit packages: Starter (50/$5), Creator (250/$20), Pro (1000/$60), Studio (5000/$200). Dev mode starts with 100 credits. Balances are HMAC-SHA256 signed using a machine-derived key to prevent tampering. The license server stores balances in `~/.clipcannon/license.db`.

## Supported Video Formats

mp4, mov, mkv, webm, avi, ts, mts

## GPU Precision Auto-Detection

| Compute Capability | Architecture | Precision |
|-------------------|-------------|-----------|
| 12.0 | Blackwell | nvfp4 |
| 8.9 | Ada Lovelace | int8 |
| 8.6 | Ampere | int8 |
| 7.5 | Turing | fp16 |
| No GPU | CPU fallback | fp32 |

The `ModelManager` in the GPU module uses an LRU eviction strategy. GPUs with >16 GB VRAM run models concurrently; smaller GPUs load models sequentially.

## Subsystems

### Editing Engine (`src/clipcannon/editing/`)

Declarative Edit Decision List (EDL) architecture supporting segment-based editing, adaptive caption generation, content-aware smart cropping (face tracking, split-screen, picture-in-picture, canvas compositing), automated filler/pause trimming, color grading, motion effects (zoom, pan, Ken Burns), visual overlays (lower thirds, title cards, logos, CTAs), iterative editing with version control (edit history, revert, branching, feedback application), and platform-specific metadata generation for 7 target platforms.

### Rendering Engine (`src/clipcannon/rendering/`)

Async FFmpeg-based rendering pipeline with 7 platform-optimized encoding profiles, GPU acceleration (NVENC/HEVC), transition effects (xfade), caption burn-in (ASS subtitles), per-segment canvas compositing with animated zoom, thumbnail generation, segment-level caching, render inspection, segment preview, and contact sheet storyboard generation.

### Audio Engine (`src/clipcannon/audio/`)

Three-tier audio generation: AI music via ACE-Step v1.5 diffusion model (GPU), MIDI composition from 6 presets with FluidSynth rendering, and 9 programmatic DSP sound effects. Includes speech-aware audio mixing with automatic ducking, peak normalization, audio cleanup (noise reduction, normalization, silence trimming, EQ), and effects processing.

### Discovery Engine (`src/clipcannon/tools/discovery.py`)

Cross-stream intelligence tools for finding optimal editing moments. Purpose-aware scoring (hook, highlight, CTA, tutorial step), natural cut-point detection using convergence of silence, beat, scene, and sentence boundaries. Narrative flow analysis validates segment sequences before rendering. Audio-safe cut-point detection across the entire video.

### Voice Engine (`src/clipcannon/voice/`)

Voice cloning pipeline with data preparation (silence-boundary splitting, transcript matching, phonemization, train/val manifests), voice profile management (SQLite CRUD with ECAPA-VOXCELEB 192-dim speaker embeddings), Qwen3-TTS voice synthesis with iterative multi-gate verification (sanity -> intelligibility -> identity), and SECS-optimized best-of-N candidate selection.

### Avatar Engine (`src/clipcannon/avatar/`)

Lip-sync video generation using LatentSync 1.6 (ByteDance) diffusion pipeline. Takes audio + driver video input, produces lip-synced talking-head output at 512x512 resolution with configurable inference steps. Integrated with voice synthesis for end-to-end video generation from text scripts.

### Scene Analysis (`src/clipcannon/pipeline/scene_analysis.py`)

Automated scene analysis that runs during ingest after frame extraction. Analyzes every extracted frame to detect scene boundaries (SSIM-based with 8s max scene duration), face positions, webcam overlay regions, and content areas. Pre-computes canvas regions for all layout types (A: 30/70 split, B: 40/60 split, C: PIP, D: full-screen face) so the AI never needs to manually measure coordinates. Results stored in the `scene_map` table.
