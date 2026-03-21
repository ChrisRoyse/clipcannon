# ClipCannon System Overview

**Version**: 0.1.0 (Phase 1)
**Python**: >=3.12
**License**: MIT
**Build System**: Hatchling

## What ClipCannon Is

ClipCannon is an AI-powered video understanding and editing pipeline exposed as an MCP (Model Context Protocol) server. An AI assistant connects to ClipCannon over MCP, sends tool calls to analyze video files, and receives structured JSON results. The pipeline ingests a source video, runs it through a 16-stream analysis DAG (transcription, scene detection, emotion analysis, beat tracking, and more), and stores all results in a per-project SQLite database. The assistant then queries that database through additional MCP tools to retrieve summaries, transcripts, analytics, frames, and storyboards.

## Architecture

ClipCannon runs as three separate processes:

| Process | Port | Technology | Purpose |
|---------|------|------------|---------|
| MCP Server | stdio (or SSE on 3366) | `mcp` SDK + Python asyncio | Exposes 27 tools to AI assistants via MCP protocol |
| License Server | 3100 | FastAPI + Uvicorn | Credit billing, HMAC balance integrity, Stripe webhooks |
| Dashboard | 3200 | FastAPI + static HTML | Web UI for credits, projects, provenance, and system health |

The MCP server uses stdio transport by default (the `clipcannon` console script). The license server and dashboard are separate FastAPI applications.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| MCP Protocol | `mcp>=1.0.0` (Server, stdio_server, Tool, TextContent) |
| Validation | `pydantic>=2.0` (config models, provenance records, billing models) |
| HTTP Client | `httpx>=0.25.0` (license server communication) |
| Web Framework | `fastapi>=0.110.0` + `uvicorn>=0.30.0` (license server, dashboard) |
| Authentication | `python-jose[cryptography]>=3.3.0` (JWT-based dev auth) |
| Image Processing | `Pillow>=10.0.0` (frame grid composition) |
| Numerical | `numpy>=1.26.0`, `scipy>=1.12.0` |
| Billing | `stripe>=8.0.0` (webhook handling, credit packages) |
| Database | SQLite3 (stdlib) + `sqlite-vec>=0.1.0` (vector KNN search) |
| GPU (optional) | `torch>=2.3.0`, `faster-whisper>=1.0.0`, `transformers>=4.40.0`, `sentence-transformers>=3.0.0`, `demucs>=4.0.0`, `librosa>=0.10.0` |

ML dependencies are in the `[ml]` optional extra and are not required for the MCP server to start.

## MCP Tools (27 Total)

### Project Management (5 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_project_create` | Create a new project from a source video file. Validates format, runs ffprobe, computes SHA-256, initializes database. |
| `clipcannon_project_open` | Open an existing project and return its current state from the database. |
| `clipcannon_project_list` | List all projects, optionally filtered by status (created, analyzing, ready, error). |
| `clipcannon_project_status` | Get detailed status including pipeline stream progress, completion percentages, and disk usage. |
| `clipcannon_project_delete` | Delete a project directory. Can optionally preserve the original source video. |

### Provenance (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_provenance_verify` | Verify the integrity of the provenance hash chain for a project. Detects tampering or broken links. |
| `clipcannon_provenance_query` | Query provenance records with optional filtering by operation or stage name. |
| `clipcannon_provenance_chain` | Walk the provenance chain from genesis to a specific record, showing full processing lineage. |
| `clipcannon_provenance_timeline` | Get a chronological timeline of all provenance events with durations and models used. |

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

### Understanding -- Pipeline & Summary (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_ingest` | Run the full 16-stream analysis pipeline on a created project. Registers all stages, executes the DAG, returns results. |
| `clipcannon_get_vud_summary` | Get a compact Video Understanding Document summary (~8K tokens). Includes speakers, topics, highlights, reactions, beats, content safety. |
| `clipcannon_get_analytics` | Get detailed analytics (~18K tokens) for specific sections: highlights, scenes, topics, reactions, beats, pacing, silence_gaps. |
| `clipcannon_get_transcript` | Get transcript with word-level timestamps. Paginated in 15-minute windows. |

### Understanding -- Visual (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_get_segment_detail` | Get ALL stream data for a time range (~15K tokens): transcript, emotion, speakers, reactions, beats, on-screen text, pacing, quality, silence gaps. |
| `clipcannon_get_frame` | Get the nearest frame to a timestamp with moment context (transcript, speaker, emotion, topic, shot type, quality, pacing, OCR, profanity). |
| `clipcannon_get_frame_strip` | Build a 3x3 composite grid of evenly-spaced frames from a time range. Returns grid image path and per-cell metadata. |
| `clipcannon_get_storyboard` | Get storyboard grids by batch number (12 grids per batch) or time range. |

### Understanding -- Search (1 tool)

| Tool | Description |
|------|-------------|
| `clipcannon_search_content` | Search video content by semantic similarity (sqlite-vec + Nomic embeddings) or text match (SQL LIKE fallback). |

### Billing (4 tools)

| Tool | Description |
|------|-------------|
| `clipcannon_credits_balance` | Get current credit balance, monthly spending, and spending limit. Shows warning at 80% of limit. |
| `clipcannon_credits_history` | Get transaction history showing charges, refunds, and purchases. Newest first. |
| `clipcannon_credits_estimate` | Estimate the credit cost for an operation: analyze (10), render (2), metadata (1), publish (1). |
| `clipcannon_spending_limit` | Set the monthly spending limit in credits. Operations exceeding this limit are blocked. |

## Pipeline Streams (16 Streams)

The analysis pipeline is a DAG of 16 streams tracked in the `stream_status` table:

`source_separation`, `visual`, `ocr`, `quality`, `shot_type`, `transcription`, `semantic`, `emotion`, `speaker`, `reactions`, `acoustic`, `beats`, `chronemic`, `storyboards`, `profanity`, `highlights`

Additional orchestration stages exist in the registry (`probe`, `vfr_normalize`, `audio_extract`, `frame_extract`, `finalize`) that are not tracked as named streams but are part of the execution DAG.

## Project Directory Structure

Each project lives under `~/.clipcannon/projects/{project_id}/`:

```
~/.clipcannon/projects/proj_a1b2c3d4/
    analysis.db          # SQLite database (all analysis results + provenance)
    source/              # Original source video (copied on project create)
    stems/               # Audio stems from source separation (vocal, music, etc.)
    frames/              # Extracted frames (frame_000001.jpg, frame_000002.jpg, ...)
    storyboards/         # Storyboard grid images and frame strips
```

### Storage Tier Classification

The disk management system classifies files into three tiers:

| Tier | Files | Policy |
|------|-------|--------|
| **Sacred** | `analysis.db`, `analysis.db-wal`, `analysis.db-shm`, everything in `source/` | Never auto-deleted |
| **Regenerable** | `source_cfr.mp4`, everything in `stems/`, `frames/`, `storyboards/` | Can be recreated by re-running pipeline stages |
| **Ephemeral** | Everything else (logs, temp files) | Safe to delete anytime |

## Database Schema

Each project's `analysis.db` contains 22 core tables and 4 vector virtual tables:

**Core tables**: `schema_version`, `project`, `transcript_segments`, `transcript_words`, `scenes`, `speakers`, `emotion_curve`, `topics`, `highlights`, `reactions`, `silence_gaps`, `acoustic`, `music_sections`, `beats`, `beat_sections`, `on_screen_text`, `text_change_events`, `profanity_events`, `content_safety`, `pacing`, `storyboard_grids`, `stream_status`, `provenance`

**Vector tables** (sqlite-vec `vec0`): `vec_frames` (float[1152]), `vec_semantic` (float[768]), `vec_emotion` (float[1024]), `vec_speakers` (float[512])

Schema version: 1. Connection pragmas: WAL journal mode, NORMAL synchronous, 64MB cache, foreign keys ON, temp store in memory.

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

Phase 1 only uses the `analyze` operation. Credit packages: Starter (50/$5), Creator (250/$20), Pro (1000/$60), Studio (5000/$200). Dev mode starts with 100 credits. Balances are HMAC-SHA256 signed using a machine-derived key to prevent tampering. The license server stores balances in `~/.clipcannon/license.db`.

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
