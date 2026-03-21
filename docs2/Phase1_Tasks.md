# Phase 1: Foundation — Atomic Task Breakdown

**Version:** 1.0
**Date:** 2026-03-21

Each task has: ID, title, description, acceptance criteria, dependencies, estimated effort, files to create/modify.

Legend: **S** = Small (< 2 hours), **M** = Medium (2-4 hours), **L** = Large (4-8 hours), **XL** = Extra Large (> 8 hours)

---

## Week 1-2: Scaffold + Database + Provenance + MCP Server

### T-001: Initialize Python project
**Size:** M
**Deps:** None
**Files:** `pyproject.toml`, `src/clipcannon/__init__.py`, `.gitignore`, `scripts/setup.sh`
**Acceptance Criteria:**
- [ ] `pyproject.toml` with all dependencies listed (core, ML, processing, billing)
- [ ] Package installable with `pip install -e .`
- [ ] Linting configured (ruff)
- [ ] Type checking configured (pyright or mypy)
- [ ] `scripts/setup.sh` creates virtualenv and installs deps

---

### T-002: Docker container with NVIDIA runtime
**Size:** L
**Deps:** T-001
**Files:** `Dockerfile`, `config/docker-compose.yml`
**Acceptance Criteria:**
- [ ] Container builds with NVIDIA base image (CUDA 13.2 if available, else 12.x)
- [ ] FFmpeg 7.x installed with NVENC/NVDEC support
- [ ] Python 3.12+ with all ML dependencies
- [ ] `docker compose up` starts all 3 services (MCP, license, dashboard)
- [ ] `nvidia-smi` works inside container
- [ ] GPU passthrough verified

---

### T-003: Configuration management
**Size:** S
**Deps:** T-001
**Files:** `src/clipcannon/config.py`, `config/default_config.json`
**Acceptance Criteria:**
- [ ] Load config from `~/.clipcannon/config.json`
- [ ] Fall back to `default_config.json` if no user config
- [ ] Dot-notation access: `config.get("processing.whisper_model")`
- [ ] Type-safe config updates: `config.set("gpu.max_vram_usage_gb", 24)`
- [ ] Default config matches PRD Section 14.1

---

### T-004: GPU manager
**Size:** M
**Deps:** T-001
**Files:** `src/clipcannon/gpu/manager.py`, `src/clipcannon/gpu/precision.py`
**Acceptance Criteria:**
- [ ] Auto-detect GPU via `torch.cuda.get_device_capability()`
- [ ] Auto-select precision: NVFP4 (Blackwell), INT8 (Ada/Ampere), FP16 (Turing)
- [ ] Monitor VRAM usage via `torch.cuda.memory_allocated()`
- [ ] Report GPU health (name, VRAM total/used/free, temperature)
- [ ] Determine concurrent vs sequential model loading based on VRAM
- [ ] Graceful fallback when no GPU detected (CPU-only mode with warning)

---

### T-005: GPU validation script
**Size:** S
**Deps:** T-004
**Files:** `scripts/validate_gpu.py`
**Acceptance Criteria:**
- [ ] Reports GPU name, VRAM, compute capability, CUDA version
- [ ] Reports selected precision tier
- [ ] Reports estimated model loading strategy (concurrent/sequential)
- [ ] Warns if VRAM < 8GB
- [ ] Errors if no CUDA GPU detected

---

### T-006: Model weight downloader
**Size:** M
**Deps:** T-001
**Files:** `scripts/download_models.py`
**Acceptance Criteria:**
- [ ] Downloads all 12+ model weights to `~/.clipcannon/models/`
- [ ] Shows total download size before starting (~15GB)
- [ ] Progress bar per model
- [ ] Resume on interruption (partial downloads)
- [ ] Verify checksums after download
- [ ] Skip already-downloaded models

---

### T-007: SQLite connection manager
**Size:** S
**Deps:** T-001
**Files:** `src/clipcannon/db/connection.py`
**Acceptance Criteria:**
- [ ] Set WAL journal mode on every connection
- [ ] Set pragmas: synchronous=NORMAL, cache_size=-64000, foreign_keys=ON, temp_store=MEMORY
- [ ] Connection pooling (or reuse single connection per project)
- [ ] Context manager for transactions
- [ ] Load sqlite-vec extension on connection

---

### T-008: Database schema
**Size:** L
**Deps:** T-007
**Files:** `src/clipcannon/db/schema.py`
**Acceptance Criteria:**
- [ ] All tables from Phase1_Architecture.md Section 2.2 created
- [ ] All 4 sqlite-vec virtual tables created (vec_frames, vec_semantic, vec_emotion, vec_speakers)
- [ ] All indexes created
- [ ] Schema version tracking for future migrations
- [ ] `create_project_db(project_id)` function creates fresh DB with schema
- [ ] Unit test: create DB, verify all tables exist

---

### T-009: Query helpers
**Size:** S
**Deps:** T-007
**Files:** `src/clipcannon/db/queries.py`
**Acceptance Criteria:**
- [ ] Parameterized query execution (prevent SQL injection)
- [ ] Row factory for dict-like access
- [ ] Batch insert helper (for transcript words, embeddings)
- [ ] Transaction wrapper

---

### T-010: SHA-256 file hasher
**Size:** S
**Deps:** T-001
**Files:** `src/clipcannon/provenance/hasher.py`
**Acceptance Criteria:**
- [ ] Stream-based hashing (8KB chunks) for large files (>1GB)
- [ ] Hash verification: `verify_file_hash(path, expected_hash) → bool`
- [ ] Table content hasher: hash serialized query results
- [ ] Unit test: hash a file, modify 1 byte, verify mismatch

---

### T-011: Provenance chain computation
**Size:** M
**Deps:** T-010
**Files:** `src/clipcannon/provenance/chain.py`
**Acceptance Criteria:**
- [ ] `compute_chain_hash(parent_hash, input_sha256, output_sha256, operation, model_name, model_version, model_params) → str`
- [ ] Genesis hash (no parent) handled correctly
- [ ] Chain verification: verify all records in sequence
- [ ] Unit test: create 5-record chain, verify passes. Tamper record 3, verify fails at record 3

---

### T-012: Provenance recorder
**Size:** M
**Deps:** T-011, T-008
**Files:** `src/clipcannon/provenance/recorder.py`
**Acceptance Criteria:**
- [ ] `record_provenance(project_id, operation, stage, input_info, output_info, model_info, execution_info) → record_id`
- [ ] Auto-computes chain hash from parent
- [ ] Stores in provenance table in analysis.db
- [ ] `verify_project_chain(project_id) → (bool, list[issues])`
- [ ] Integration test: record 3 provenance entries, verify chain

---

### T-013: MCP server scaffold
**Size:** M
**Deps:** T-001
**Files:** `src/clipcannon/server.py`
**Acceptance Criteria:**
- [ ] FastMCP server starts and accepts connections (stdio and SSE)
- [ ] Tool registry loads tools from `tools/` package
- [ ] Server info returns name, version, tool count
- [ ] Error handling: tool exceptions → proper MCP error responses
- [ ] Logging configured (structured JSON logs)

---

### T-014: Project management tools
**Size:** M
**Deps:** T-013, T-008, T-010
**Files:** `src/clipcannon/tools/project.py`
**Acceptance Criteria:**
- [ ] `clipcannon_project_create`: creates project dir, runs probe, computes SHA-256
- [ ] `clipcannon_project_open`: returns project state from DB
- [ ] `clipcannon_project_list`: returns all projects, filterable by status
- [ ] `clipcannon_project_status`: returns pipeline progress + disk usage
- [ ] `clipcannon_project_delete`: removes project dir (optionally keeps source)
- [ ] All responses match spec in Phase1_MCP_Tools_Spec.md

---

### T-015: Provenance MCP tools
**Size:** S
**Deps:** T-013, T-012
**Files:** `src/clipcannon/tools/provenance.py`
**Acceptance Criteria:**
- [ ] `clipcannon_provenance_verify`: verifies chain, returns integrity status
- [ ] `clipcannon_provenance_query`: returns filtered provenance records
- [ ] `clipcannon_provenance_chain`: returns chain from genesis to target
- [ ] `clipcannon_provenance_timeline`: returns chronological summary

---

### T-016: Disk management tools
**Size:** S
**Deps:** T-013
**Files:** `src/clipcannon/tools/disk.py`
**Acceptance Criteria:**
- [ ] `clipcannon_disk_status`: returns usage by tier (sacred/regenerable/ephemeral)
- [ ] `clipcannon_disk_cleanup`: deletes ephemeral first, then regenerable (largest first)

---

### T-017: Config MCP tools
**Size:** S
**Deps:** T-013, T-003
**Files:** `src/clipcannon/tools/config_tools.py`
**Acceptance Criteria:**
- [ ] `clipcannon_config_get`, `clipcannon_config_set`, `clipcannon_config_list`

---

## Week 3-4: Pipeline Orchestrator + Required Stages

### T-018: Pipeline orchestrator
**Size:** L
**Deps:** T-008, T-012
**Files:** `src/clipcannon/pipeline/orchestrator.py`
**Acceptance Criteria:**
- [ ] DAG-based stage execution with dependency resolution
- [ ] Required vs optional stage classification
- [ ] Parallel execution of independent stages (when VRAM permits)
- [ ] Graceful degradation: optional stage failure → fallback values + status update
- [ ] Required stage failure → pipeline stops, error reported
- [ ] Progress tracking: update stream_status table for each stage
- [ ] Provenance recording at each stage
- [ ] Ephemeral file cleanup after each stage completes

---

### T-019: Probe stage
**Size:** M
**Deps:** T-018
**Files:** `src/clipcannon/pipeline/probe.py`
**Acceptance Criteria:**
- [ ] FFprobe extracts: duration, resolution, fps, codec, audio codec, channels, file size
- [ ] VFR detection via `vfrdet` filter
- [ ] SHA-256 of source file computed
- [ ] INSERT into project table
- [ ] Provenance record written
- [ ] Validation: file exists, has video stream, supported format
- [ ] Unit test with 10s fixture video

---

### T-020: VFR normalization stage
**Size:** M
**Deps:** T-019
**Files:** `src/clipcannon/pipeline/vfr_normalize.py`
**Acceptance Criteria:**
- [ ] Skips if source is already CFR
- [ ] Selects nearest standard frame rate
- [ ] NVENC re-encode at CRF 18 (near-lossless)
- [ ] Output SHA-256 computed
- [ ] Provenance record written
- [ ] All subsequent stages use CFR copy

---

### T-021: Audio extraction stage
**Size:** S
**Deps:** T-019
**Files:** `src/clipcannon/pipeline/audio_extract.py`
**Acceptance Criteria:**
- [ ] Extracts 16kHz mono WAV (for WhisperX)
- [ ] Extracts original sample rate WAV (for HTDemucs)
- [ ] SHA-256 of both outputs computed
- [ ] Provenance record written

---

### T-022: HTDemucs source separation stage
**Size:** L
**Deps:** T-021, T-004
**Files:** `src/clipcannon/pipeline/source_separation.py`
**Acceptance Criteria:**
- [ ] Loads HTDemucs model (GPU preferred, CPU fallback)
- [ ] Produces 4 stems: vocals, music, drums, other
- [ ] Saves stems as WAV at source sample rate
- [ ] Unloads model after completion
- [ ] SHA-256 of all 4 stems computed
- [ ] Provenance record written
- [ ] Fallback: if fails, downstream stages use mixed audio
- [ ] Unit test with 10s audio fixture

---

### T-023: Frame extraction stage
**Size:** M
**Deps:** T-020
**Files:** `src/clipcannon/pipeline/frame_extract.py`
**Acceptance Criteria:**
- [ ] NVDEC-accelerated extraction at 2fps
- [ ] Output as numbered JPEGs: frame_000000.jpg, frame_000001.jpg, ...
- [ ] Frame count validation (expected ±1)
- [ ] Frame manifest SHA-256 computed
- [ ] Provenance record written

---

### T-024: WhisperX transcription stage
**Size:** XL
**Deps:** T-022, T-004
**Files:** `src/clipcannon/pipeline/transcribe.py`
**Acceptance Criteria:**
- [ ] Loads WhisperX with wav2vec2 forced alignment
- [ ] Transcribes vocal stem (or mixed audio if separation failed)
- [ ] Word-level timestamps with 20-50ms precision
- [ ] Auto language detection
- [ ] Segments inserted into transcript_segments
- [ ] Words inserted into transcript_words
- [ ] Provenance record written
- [ ] WER < 5% on English test content
- [ ] Integration test with 10s fixture

---

## Week 5-6: Full Understanding Pipeline

### T-025: SigLIP visual embedding + scene detection
**Size:** L
**Deps:** T-023, T-004
**Files:** `src/clipcannon/pipeline/visual_embed.py`
**Acceptance Criteria:**
- [ ] Batch inference (batch=64) through SigLIP
- [ ] 1152-dim embeddings stored in vec_frames
- [ ] Scene boundaries detected via cosine similarity < 0.75
- [ ] Scenes with key frame, face detection, dominant colors stored
- [ ] Provenance record written
- [ ] > 90% scene detection recall on test video

---

### T-026: PaddleOCR text detection
**Size:** M
**Deps:** T-023
**Files:** `src/clipcannon/pipeline/ocr.py`
**Acceptance Criteria:**
- [ ] 1fps sampling (every other extracted frame)
- [ ] Deduplication of consecutive identical text
- [ ] Region classification, font size estimation
- [ ] Text change events detected (slide transitions)
- [ ] Provenance record written

---

### T-027: Quality assessment
**Size:** M
**Deps:** T-023
**Files:** `src/clipcannon/pipeline/quality.py`
**Acceptance Criteria:**
- [ ] BRISQUE batch inference on all frames
- [ ] DOVER-Mobile inference for aesthetic quality
- [ ] Per-scene aggregation: avg, min, blur_pct, classification, issues
- [ ] Provenance record written

---

### T-028: Shot type classification
**Size:** M
**Deps:** T-025
**Files:** `src/clipcannon/pipeline/shot_type.py`
**Acceptance Criteria:**
- [ ] ResNet-50 classifies 1 key frame per scene
- [ ] Labels: extreme_closeup, closeup, medium, wide, establishing
- [ ] Crop recommendation computed
- [ ] Provenance record written

---

### T-029: Nomic semantic embedding + topics
**Size:** M
**Deps:** T-024
**Files:** `src/clipcannon/pipeline/semantic_embed.py`
**Acceptance Criteria:**
- [ ] `search_document:` prefix prepended to segments
- [ ] 768-dim embeddings stored in vec_semantic
- [ ] K-means clustering → topic detection
- [ ] Topic labels generated from top keywords
- [ ] Provenance record written

---

### T-030: Wav2Vec2 emotion analysis
**Size:** M
**Deps:** T-022
**Files:** `src/clipcannon/pipeline/emotion_embed.py`
**Acceptance Criteria:**
- [ ] 5s windows, 2.5s stride on vocal stem
- [ ] 1024-dim embeddings in vec_emotion
- [ ] arousal/valence/energy scalars in emotion_curve
- [ ] Provenance record written

---

### T-031: WavLM speaker diarization
**Size:** L
**Deps:** T-022
**Files:** `src/clipcannon/pipeline/speaker_embed.py`
**Acceptance Criteria:**
- [ ] Silero VAD for speech segments
- [ ] 512-dim X-vectors in vec_speakers
- [ ] Agglomerative clustering → unique speakers
- [ ] Speakers table populated
- [ ] transcript_segments + transcript_words updated with speaker_id
- [ ] Provenance record written

---

### T-032: SenseVoice reaction detection
**Size:** M
**Deps:** T-022
**Files:** `src/clipcannon/pipeline/reactions.py`
**Acceptance Criteria:**
- [ ] Detects laughter, applause events with timestamps
- [ ] Confidence, duration, intensity computed
- [ ] Context transcript attached
- [ ] Provenance record written

---

### T-033: Acoustic analysis + Beat This!
**Size:** L
**Deps:** T-022
**Files:** `src/clipcannon/pipeline/acoustic.py`
**Acceptance Criteria:**
- [ ] cuFFT spectral analysis: RMS, silence detection, music classification
- [ ] Beat This! on music stem: beat positions, downbeats, BPM
- [ ] silence_gaps, acoustic, music_sections, beats, beat_sections populated
- [ ] Provenance record written

---

### T-034: Profanity detection
**Size:** S
**Deps:** T-024, T-025
**Files:** `src/clipcannon/pipeline/profanity.py`
**Acceptance Criteria:**
- [ ] Word list matching on transcript_words
- [ ] Profanity events with severity levels
- [ ] Content rating computed
- [ ] Provenance record written

---

### T-035: Chronemic computation
**Size:** S
**Deps:** T-024, T-031, T-033
**Files:** `src/clipcannon/pipeline/chronemic.py`
**Acceptance Criteria:**
- [ ] WPM, pause_ratio, speaker_changes per 60s window
- [ ] Labels: fast_dialogue, normal, slow_monologue, dead_air
- [ ] Provenance record written

---

### T-036: Highlight scoring
**Size:** M
**Deps:** T-030, T-032, T-029, T-027
**Files:** `src/clipcannon/pipeline/highlights.py`
**Acceptance Criteria:**
- [ ] 7-component scoring formula implemented
- [ ] Natural language reason generated for each highlight
- [ ] Top-N selection (configurable, default 20)
- [ ] All component scores stored
- [ ] Provenance record written

---

### T-037: Storyboard grid generation
**Size:** M
**Deps:** T-023
**Files:** `src/clipcannon/pipeline/storyboard.py`
**Acceptance Criteria:**
- [ ] Adaptive interval: `max(duration_s / 720, 0.5)`
- [ ] 80 grids of 3x3 (1044x1044px, 348x348 per cell)
- [ ] Timestamp overlay on each cell (Montserrat-Bold 14px)
- [ ] Grid paths + cell metadata stored in DB
- [ ] Provenance record written

---

### T-038: Finalize stage
**Size:** S
**Deps:** All T-025 through T-037
**Files:** `src/clipcannon/pipeline/finalize.py`
**Acceptance Criteria:**
- [ ] stream_status updated for all streams
- [ ] Degradation note computed from failed streams
- [ ] Full provenance chain verified
- [ ] Project status set to "ready" or "error"
- [ ] Ephemeral temp files cleaned up
- [ ] Final provenance record written

---

## Week 7: Understanding MCP Tools

### T-039: clipcannon_ingest tool
**Size:** M
**Deps:** T-018, T-013
**Files:** `src/clipcannon/tools/understanding.py`
**Acceptance Criteria:**
- [ ] Charges credits via LicenseClient
- [ ] Starts pipeline asynchronously
- [ ] Returns immediately with status
- [ ] Refunds on pipeline failure

---

### T-040: VUD delivery tools (get_vud_summary, get_analytics, get_transcript, get_segment_detail)
**Size:** L
**Deps:** T-013, T-009
**Files:** `src/clipcannon/tools/understanding.py`
**Acceptance Criteria:**
- [ ] get_vud_summary: ~8K tokens, compact overview
- [ ] get_analytics: ~18K tokens, all scenes/topics/highlights/reactions
- [ ] get_transcript: paginated ~12K/page, time-range filtered
- [ ] get_segment_detail: ~15K tokens, full-resolution for a time range
- [ ] ALL responses verified < 25K tokens with 4-hour test data

---

### T-041: Frame/storyboard delivery tools
**Size:** M
**Deps:** T-013
**Files:** `src/clipcannon/tools/understanding.py`
**Acceptance Criteria:**
- [ ] get_frame: single JPEG + at_this_moment metadata
- [ ] get_frame_strip: 3x3 composite grid from time range
- [ ] get_storyboard: batched (12 grids/batch), 7 batches for 80 grids
- [ ] All responses < 25K tokens

---

### T-042: Semantic search tool
**Size:** M
**Deps:** T-013, T-029
**Files:** `src/clipcannon/tools/understanding.py`
**Acceptance Criteria:**
- [ ] Embeds query via Nomic, searches vec_semantic
- [ ] Returns top-K results with transcript text, timestamps, scores
- [ ] Search time < 15ms on 28K vectors
- [ ] Optional: visual search via SigLIP (search vec_frames)

---

## Week 8: Billing + Dashboard + Integration

### T-043: License server
**Size:** L
**Deps:** T-001
**Files:** `src/license_server/server.py`
**Acceptance Criteria:**
- [ ] HTTP server on port 3100
- [ ] POST /v1/charge, POST /v1/refund, GET /v1/balance, GET /v1/history, POST /v1/sync
- [ ] Local SQLite cache with balance + transactions
- [ ] Idempotency key support (prevent double charges)
- [ ] Request logging

---

### T-044: Cloudflare D1 sync
**Size:** M
**Deps:** T-043
**Files:** `src/license_server/d1_sync.py`
**Acceptance Criteria:**
- [ ] Pull balance from D1 on startup
- [ ] Periodic sync every 5 minutes
- [ ] Push charges/refunds to D1 asynchronously
- [ ] Conflict resolution (D1 is source of truth)

---

### T-045: Stripe webhook handler
**Size:** M
**Deps:** T-043
**Files:** `src/license_server/stripe_webhooks.py`
**Acceptance Criteria:**
- [ ] Verify Stripe signature
- [ ] Handle checkout.session.completed event
- [ ] Update D1 balance with purchased credits
- [ ] Idempotent (replay-safe)

---

### T-046: HMAC balance integrity
**Size:** M
**Deps:** T-043
**Files:** `src/clipcannon/billing/hmac_integrity.py`
**Acceptance Criteria:**
- [ ] Machine ID derivation (deterministic from hardware)
- [ ] HMAC-SHA256 signing of balance values
- [ ] Verify on every balance read
- [ ] Fatal exit on tamper detection
- [ ] Unit test: sign, verify, tamper, verify fails

---

### T-047: License client + credit system
**Size:** M
**Deps:** T-043
**Files:** `src/clipcannon/billing/license_client.py`, `src/clipcannon/billing/credits.py`
**Acceptance Criteria:**
- [ ] LicenseClient: charge, refund, get_balance, estimate
- [ ] Credit rates: analyze=10 credits
- [ ] Spending limit enforcement
- [ ] Billing MCP tools: balance, history, estimate, spending_limit

---

### T-048: Dashboard app scaffold
**Size:** M
**Deps:** T-001
**Files:** `src/clipcannon/dashboard/app.py`, `src/clipcannon/dashboard/auth.py`
**Acceptance Criteria:**
- [ ] FastAPI app on port 3200
- [ ] Magic link authentication (JWT, 10-min expiry, 30-day session)
- [ ] Dev mode: returns token in console (no email)
- [ ] HTTP-only session cookie
- [ ] Environment isolation (whitelisted env vars only)

---

### T-049: Dashboard pages (home, credits, provenance)
**Size:** L
**Deps:** T-048, T-047, T-015
**Files:** `src/clipcannon/dashboard/routes/`, `src/clipcannon/dashboard/templates/`
**Acceptance Criteria:**
- [ ] Home page: credit balance, GPU status, VRAM usage, recent activity
- [ ] Credits page: balance display, add credits (Stripe checkout), transaction history
- [ ] Provenance page: chain viewer per project (timeline, record details, integrity status)
- [ ] Responsive layout (works on desktop and tablet)

---

### T-050: Integration tests
**Size:** L
**Deps:** All above
**Files:** `tests/integration/test_full_pipeline.py`
**Acceptance Criteria:**
- [ ] 10-second fixture video through full pipeline → all 19 stages complete
- [ ] Provenance chain verifies (19 records)
- [ ] VUD summary < 8K tokens
- [ ] All MCP tools return valid responses
- [ ] Credit charge + refund flow works
- [ ] Tamper detection works (modify file → verify fails)

---

### T-051: Performance benchmarks
**Size:** M
**Deps:** T-050
**Files:** `tests/integration/test_performance.py`
**Acceptance Criteria:**
- [ ] Benchmark: pipeline time for 10s, 1min, 10min fixture videos
- [ ] Benchmark: VRAM peak during pipeline
- [ ] Benchmark: sqlite-vec KNN search time
- [ ] Benchmark: MCP response token counts
- [ ] Results logged to `tests/benchmark_results.json`

---

## Task Summary

| Week | Tasks | Count |
|:-----|:------|:------|
| 1-2 | T-001 through T-017 | 17 |
| 3-4 | T-018 through T-024 | 7 |
| 5-6 | T-025 through T-038 | 14 |
| 7 | T-039 through T-042 | 4 |
| 8 | T-043 through T-051 | 9 |
| **Total** | | **51 tasks** |

| Size | Count |
|:-----|:------|
| S (< 2 hours) | 14 |
| M (2-4 hours) | 26 |
| L (4-8 hours) | 9 |
| XL (> 8 hours) | 2 |

---

*End of Phase 1 Task Breakdown*
