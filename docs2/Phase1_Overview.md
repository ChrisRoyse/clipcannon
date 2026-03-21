# Phase 1: Foundation — Overview & Plan

**Version:** 1.0
**Date:** 2026-03-21
**Phase Duration:** 8 weeks (Weeks 1-8)
**Prerequisite:** None (first phase)

---

## 1. Phase Goal

Deliver a working MCP server that can ingest a video file, run the full 12-stream understanding pipeline, produce a Video Understanding Document (VUD), serve that data to a multimodal AI through paginated MCP tools, track every transformation with a SHA-256 provenance hash chain, charge credits through a billing system, and display system status on a basic web dashboard.

At the end of Phase 1, an AI model connected via MCP can:
1. Ingest a source video
2. Receive a progressive, paginated understanding of the video (text map, storyboard overview, detail frames)
3. Search video content semantically
4. Verify the provenance chain of every transformation
5. All within credit-billing guardrails

Phase 1 does NOT include: editing/EDL creation, rendering, audio generation, animations, publishing, or the full review dashboard. Those are Phase 2-3.

---

## 2. Deliverables

| # | Deliverable | Description |
|:--|:-----------|:-----------|
| D1 | MCP Server Scaffold | FastMCP server with tool registry, stdio/SSE transport |
| D2 | Project Management | Create/open/list/delete projects with on-disk structure |
| D3 | Video Ingestion Pipeline | 19-stage DAG pipeline with graceful degradation |
| D4 | 12-Stream Understanding | All 12 analysis streams producing AI-readable data |
| D5 | VUD Delivery Tools | Paginated MCP tools delivering VUD under 25K tokens/response |
| D6 | Storyboard Generation | 80 adaptive storyboard grids per video |
| D7 | Frame Delivery Tools | Single frame + frame strip + storyboard delivery |
| D8 | Semantic Search | Content search via sqlite-vec vector similarity |
| D9 | Provenance Hash Chain | SHA-256 chain across all 19 pipeline stages + verify/query tools |
| D10 | Billing System | License server + credit charge/refund + HMAC integrity |
| D11 | Basic Dashboard | Web UI with credit balance, system health, provenance viewer |
| D12 | Docker Container | GPU-enabled container with all dependencies |

---

## 3. Success Criteria

| Criterion | Target | Measurement |
|:----------|:-------|:-----------|
| Ingestion speed (1hr 1080p, RTX 5090) | < 5 minutes | Wall clock time |
| Ingestion speed (1hr 1080p, RTX 4090) | < 8 minutes | Wall clock time |
| Transcript accuracy (English) | WER < 5% | Word Error Rate against ground truth |
| Word timestamp precision | < 50ms drift | Manual validation against waveform |
| Scene detection recall | > 90% | Manual count of visual transitions |
| MCP response size | < 25K tokens per response | Token count validation |
| VUD summary token count | ~8K tokens | Token count |
| Provenance chain records | 19 per full pipeline run | Count |
| Provenance chain integrity | 100% pass on verify | clipcannon_provenance_verify |
| File tamper detection | 100% detection rate | Modify file → verify → expect failure |
| Credit charge/refund | End-to-end working | Integration test |
| HMAC balance integrity | Tamper = fatal exit | Mutation test |
| VRAM peak (RTX 5090, NVFP4) | < 12 GB | nvidia-smi monitoring |
| VRAM peak (RTX 4090, INT8) | < 22 GB | nvidia-smi monitoring |
| sqlite-vec KNN search | < 15ms on 28K vectors | Benchmark |

---

## 4. Timeline

```
WEEK 1 ──────────────────────────────────────────────────────
  Project scaffold (pyproject.toml, Docker, config)
  GPU manager (detect, VRAM monitor, precision auto-select)
  SQLite connection manager (WAL, pragmas)
  Database schema (all tables + sqlite-vec virtual tables)

WEEK 2 ──────────────────────────────────────────────────────
  Provenance hasher (SHA-256 streaming)
  Provenance chain computation + verification
  Provenance recorder (write records to DB)
  MCP server scaffold (FastMCP, tool registry)
  Project management tools (CRUD)

WEEK 3 ──────────────────────────────────────────────────────
  Pipeline orchestrator (DAG runner, required/optional classification)
  Probe stage (FFprobe, VFR detection)
  VFR normalization stage
  Audio extraction stage
  HTDemucs source separation stage

WEEK 4 ──────────────────────────────────────────────────────
  Frame extraction stage (NVDEC 2fps)
  WhisperX transcription stage (forced alignment on vocal stem)
  Unit tests for all Week 3-4 stages
  Model download script

WEEK 5 ──────────────────────────────────────────────────────
  SigLIP visual embedding + scene detection
  PaddleOCR text detection
  BRISQUE + DOVER quality assessment
  ResNet-50 shot type classification

WEEK 6 ──────────────────────────────────────────────────────
  Nomic semantic embedding + topic clustering
  Wav2Vec2 emotion analysis
  WavLM speaker diarization
  SenseVoice reaction detection
  cuFFT acoustic + Beat This! beat detection

WEEK 7 ──────────────────────────────────────────────────────
  Profanity detection
  Chronemic computation
  Multi-signal highlight scoring
  Storyboard grid generation
  Finalize + chain verification stage
  All understanding MCP tools (9 tools)

WEEK 8 ──────────────────────────────────────────────────────
  License server (HTTP, SQLite cache)
  Cloudflare D1 sync + Stripe webhooks
  HMAC balance integrity
  Credit charge/refund from MCP server
  Basic dashboard (FastAPI, auth, home, credits, provenance)
  Integration testing + performance benchmarks
  Docker container finalization
```

---

## 5. Architecture Summary

### 5.1 Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│  Docker Container (NVIDIA Runtime, CUDA 13.2)           │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ ClipCannon  │  │License Server│  │  Dashboard   │  │
│  │ MCP Server  │  │  port 3100   │  │  port 3200   │  │
│  │ port 3366   │  │  Billing     │  │  Basic UI    │  │
│  └──────┬──────┘  └──────────────┘  └──────────────┘  │
│         │                                               │
│  ┌──────▼──────────────────────────────────────────┐   │
│  │  Pipeline Orchestrator (DAG Runner)              │   │
│  │                                                  │   │
│  │  REQUIRED STAGES:                                │   │
│  │  probe → vfr_norm → audio_extract → htdemucs →  │   │
│  │  frame_extract → whisperx                        │   │
│  │                                                  │   │
│  │  OPTIONAL STAGES (parallel after required):      │   │
│  │  siglip │ ocr │ quality │ shot_type │ nomic │   │   │
│  │  wav2vec2 │ wavlm │ sensevoice │ acoustic │     │   │
│  │  profanity │ chronemic │ highlights │ storyboard│   │
│  └─────────────────────────────────────────────────┘   │
│         │                                               │
│  ┌──────▼──────────────────────────────────────────┐   │
│  │  Storage                                         │   │
│  │  ~/.clipcannon/projects/{id}/                    │   │
│  │    analysis.db (SQLite + sqlite-vec)             │   │
│  │    source/ stems/ frames/ storyboards/           │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Data Flow

```
SOURCE VIDEO (mp4/mov/mkv/webm)
    │
    ▼
[1. PROBE] → metadata, VFR detection
    │
    ▼ (if VFR)
[1.5 VFR NORMALIZE] → CFR copy
    │
    ├────────────────┐
    ▼                ▼
[2. AUDIO]       [4. FRAMES]
    │             (2fps JPEGs)
    ▼                │
[3. HTDEMUCS]        ├──► [6. SIGLIP] → scenes, embeddings
 4 stems:            ├──► [7. OCR] → on-screen text
 vocals/music/       ├──► [8. QUALITY] → per-frame scores
 drums/other         └──► [9. SHOT TYPE] → camera framing
    │
    ├──► [5. WHISPERX on vocals] → transcript + words
    │         │
    │         └──► [10. NOMIC] → topics, semantic embeddings
    │         └──► [15. PROFANITY] → content safety
    │
    ├──► [11. WAV2VEC2 on vocals] → emotion curve
    ├──► [12. WAVLM on vocals] → speaker IDs
    ├──► [13. SENSEVOICE on vocals] → reactions
    ├──► [14. ACOUSTIC on mix+stems] → silence, beats
    │
    └──► DERIVED:
         [16. CHRONEMIC] → pacing
         [17. HIGHLIGHTS] → scored highlights
         [18. STORYBOARD] → 80 grids
         [19. FINALIZE] → verify chain
    │
    ▼
analysis.db (all structured data)
+ frames/ stems/ storyboards/ (binary files)
    │
    ▼
MCP TOOLS → AI reads progressively:
  get_vud_summary (~8K)
  get_analytics (~18K)
  get_transcript (paginated ~12K/page)
  get_segment_detail (~15K)
  get_storyboard (batched ~24K/batch)
  get_frame / get_frame_strip (on demand)
```

### 5.3 Key Constraints

| Constraint | Value | Reason |
|:-----------|:------|:-------|
| MCP response size | < 25K tokens | Claude Code truncates at ~25K |
| Frame extraction rate | 2 fps | Balance coverage vs storage |
| OCR extraction rate | 1 fps | Text changes less frequently |
| Storyboard grid count | 80 (fixed) | 80 grids × 9 frames = 720 frames |
| Storyboard grid size | 3×3 (1044×1044 px) | ~1,454 tokens per grid in Claude |
| SQLite journal mode | WAL | Concurrent reads during pipeline writes |
| sqlite-vec dimensions | 1152 (visual), 768 (semantic), 1024 (emotion), 512 (speaker) | Per-model embedding space |
| Provenance hash algorithm | SHA-256 | Industry standard, fast on CPU |
| Audio sample rate (pipeline input) | 16kHz mono | WhisperX requirement |
| Min GPU tier | RTX 2000 (Turing, FP16) | Minimum supported |
| Target GPU tier | RTX 5090 (Blackwell, NVFP4) | Optimal performance |

---

## 6. Dependencies (Python Packages)

### Core
```
fastmcp>=0.1.0          # MCP server framework
typed-ffmpeg>=3.0.0     # Type-safe FFmpeg (Phase 2, but install now)
sqlite-vec>=0.1.0       # Vector search in SQLite
pydantic>=2.0           # Data validation
httpx>=0.25.0           # HTTP client (license server)
uvicorn>=0.30.0         # ASGI server (dashboard)
fastapi>=0.110.0        # Dashboard web framework
python-jose>=3.3.0      # JWT for auth
```

### ML Models
```
torch>=2.3.0            # PyTorch with CUDA
faster-whisper>=1.0.0   # WhisperX transcription
whisperx>=3.1.0         # Forced alignment
transformers>=4.40.0    # SigLIP, Wav2Vec2, WavLM
sentence-transformers>=3.0.0  # Nomic Embed
demucs>=4.0.0           # HTDemucs source separation
paddleocr>=2.8.0        # PaddleOCR PP-OCRv5
pyiqa>=0.1.10           # BRISQUE quality assessment
funaudiollm>=0.1.0      # SenseVoice reaction detection
madmom>=0.17.0          # Beat This! (or beat_this package)
silero-vad>=5.0         # Voice activity detection
```

### Processing
```
numpy>=1.26.0
scipy>=1.12.0
cupy-cuda12x>=13.0.0    # GPU-accelerated computation
Pillow>=10.0.0          # Image processing (storyboard grids)
```

### Billing
```
stripe>=8.0.0           # Payment processing
```

---

## 7. Risk Register (Phase 1 Specific)

| Risk | Likelihood | Impact | Mitigation |
|:-----|:-----------|:-------|:-----------|
| WhisperX installation complexity (wav2vec2 aligner) | Medium | High | Pin versions, Docker layer caching, test on clean environment |
| HTDemucs VRAM spike during separation | Low | Medium | cpu_offload=True fallback, sequential model loading on <16GB GPUs |
| PaddleOCR dependency conflicts with PyTorch | Medium | Medium | Install in order: torch first, then paddlepaddle-gpu, then paddleocr |
| sqlite-vec not handling concurrent writes correctly | Low | High | WAL mode + single writer architecture. Pipeline stages write sequentially per table |
| 25K token limit exceeded for large videos | Medium | High | Test with 4-hour source. All tools have hard pagination |
| Beat This! model not available on PyPI | Medium | Low | Fallback to madmom for beat detection. Both are GPU-accelerated |
| Model weights exceed disk space | Low | Medium | download_models.py shows total size before download (~15GB). User confirms |
| Docker NVIDIA runtime not configured | Medium | High | validate_gpu.py checks before pipeline runs. Clear error messages |

---

## 8. Out of Scope (Phase 1)

These are explicitly NOT part of Phase 1:

- EDL format and edit creation
- Video rendering (FFmpeg filter graph building)
- Caption generation (ASS subtitles)
- Smart cropping (face detection)
- Audio generation (ACE-Step, MIDI, DSP SFX)
- Motion graphics (PyCairo, Lottie, WebM)
- Platform publishing (OAuth, API integration)
- Full dashboard (timeline, edit review, batch review)
- Metadata generation (titles, descriptions, hashtags)
- Thumbnail generation
- Multi-language support
- A/B testing
- Performance feedback loop

---

*End of Phase 1 Overview*
