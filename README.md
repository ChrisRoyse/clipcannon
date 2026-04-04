<div align="center">

# ClipCannon

**AI-powered video understanding, editing, and voice synthesis -- all running locally on your GPU.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![License: BSL 1.1](https://img.shields.io/badge/license-BSL_1.1-orange.svg?style=flat-square)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-compatible-purple.svg?style=flat-square)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-994_passing-brightgreen.svg?style=flat-square)](#testing)
[![Tools](https://img.shields.io/badge/MCP_tools-55-orange.svg?style=flat-square)](#mcp-tools)

---

ClipCannon ingests a video, runs it through a **22-stage AI analysis pipeline**, and gives your AI assistant (Claude, etc.) the tools to edit, render, and publish platform-optimized clips -- with voice cloning, lip-sync avatars, real-time meeting bots, and AI-generated audio. No cloud APIs. Everything runs on your machine.

[Quick Start](#quick-start-5-minutes) &#8226; [Full Setup Guide](#full-setup-guide) &#8226; [Using ClipCannon](#using-clipcannon-with-claude) &#8226; [Features](#features) &#8226; [MCP Tools](#mcp-tools) &#8226; [Architecture](#architecture)

<br>

<a href="https://paypal.me/ChrisRoyseAI" target="_blank">
  <img src="https://img.shields.io/badge/SUPPORT_THIS_PROJECT-00457C?style=for-the-badge&logo=paypal&logoColor=white" alt="Support This Project" width="300"/>
</a>

</div>

---

## What is ClipCannon?

ClipCannon is an MCP server that turns any AI assistant into a professional video editor + voice clone + meeting avatar. You give it a video file; it analyzes every frame, every word, every emotion, every speaker, every scene -- then exposes **55 tools** that let an AI assistant create edits, render platform-ready clips, generate music, clone voices, and even join Google Meet as a talking AI avatar.

**The core idea**: instead of scrubbing through hours of footage manually, let an AI understand the content through neural embeddings and structured analysis, then have a conversation about what to create.

www.clipcannon.com

---

## Quick Start (5 Minutes)

If you're using **Claude Code**, the fastest way to get started:

```bash
# 1. Clone the repo
git clone https://github.com/ChrisRoyse/clipcannon.git
cd clipcannon

# 2. Tell Claude Code to set everything up
claude
```

Then paste this prompt into Claude Code:

```
Here is my Hugging Face token: hf_xxxxx
Here is my PulseAudio password (if on WSL2): xxxxx

Please:
1. Install ClipCannon with all ML dependencies (pip install -e ".[ml,phase2]")
2. Set my HF token as an environment variable
3. Install Ollama and pull qwen3:8b-nothink
4. Add ClipCannon as an MCP server
5. Verify the GPU is detected and all models can load
6. Run the test suite to confirm everything works
```

Claude will handle the entire installation process, download models, and verify your setup.

---

## Full Setup Guide

### Prerequisites

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| **Python** | 3.12 | 3.13+ |
| **GPU** | NVIDIA 8GB VRAM (RTX 3060) | 24-32GB VRAM (RTX 4090/5090) |
| **CUDA** | 12.1+ | 13.0+ |
| **FFmpeg** | 6.0+ | With NVENC support |
| **RAM** | 16GB | 64GB+ |
| **Disk** | 20GB (models) | 50GB+ (models + projects) |
| **OS** | Linux / WSL2 | Ubuntu 22.04+ or WSL2 on Windows 11 |

### Step-by-Step Installation

#### 1. Clone and Install

```bash
git clone https://github.com/ChrisRoyse/clipcannon.git
cd clipcannon

# Core package (tools + editing + rendering)
pip install -e .

# ML models (analysis pipeline, embeddings, voice)
pip install -e ".[ml]"

# Phase 2 extras (AI audio, advanced voice, avatar)
pip install -e ".[phase2]"

# Development tools (testing, linting)
pip install -e ".[dev]"
```

#### 2. Install Ollama (Local LLM)

ClipCannon uses Ollama for local LLM inference (narrative analysis, meeting bot intelligence):

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull the recommended models
ollama pull qwen3:8b-nothink    # Fast responses for real-time conversation
ollama pull qwen3:14b-nothink   # Better quality for analysis tasks
```

#### 3. Set Environment Variables

```bash
# Hugging Face token (needed to download gated models like Whisper, Wav2Vec2)
export HUGGINGFACE_TOKEN=hf_your_token_here

# Optional: Set GPU device
export CUDA_VISIBLE_DEVICES=0
```

Add these to your `~/.bashrc` or `~/.zshrc` to persist across sessions.

#### 4. Connect to Claude

**Claude Code (CLI):**
```bash
claude mcp add clipcannon -- clipcannon
```

**Claude Desktop:**

Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "clipcannon": {
      "command": "clipcannon",
      "args": []
    }
  }
}
```

#### 5. Verify Installation

Tell Claude:
```
Run clipcannon_config_list and tell me if the GPU is detected correctly.
Then run clipcannon_project_list to verify the MCP connection works.
```

### WSL2 Setup (Windows Users)

If you're running on Windows via WSL2, additional setup is needed for audio:

```
I'm on WSL2. Please set up PulseAudio TCP bridge for audio capture.
I need:
1. PulseAudio installed on Windows with TCP module enabled on port 4713
2. WSL2 PULSE_SERVER pointing to the Windows host
3. Output and clone_audio sinks configured
4. Firewall rule for port 4713
```

### Docker Setup

```bash
cd config
docker compose up -d

# Dashboard: http://localhost:3200
# License server: http://localhost:3100
```

---

## Using ClipCannon with Claude

### Getting Started Prompts

Once ClipCannon is connected, here are prompts to learn the system:

#### Learn What's Available
```
What ClipCannon tools do you have access to? Give me a categorized overview.
```

```
Explain the ClipCannon video analysis pipeline. What happens when I ingest a video?
```

#### Analyze Your First Video
```
Create a project from /path/to/my/video.mp4 and run the full analysis pipeline.
Show me the results when it's done.
```

```
Show me the transcript of the video we just analyzed. Who are the speakers?
```

```
What are the best highlight moments in this video? Show me the top 5.
```

#### Create Edits
```
Create a 60-second TikTok highlight reel from the best moments.
Use adaptive captions and face-tracking crop.
```

```
Find all the moments where the speaker talks about [topic] and create a
compilation clip for YouTube Shorts.
```

```
Create a split-screen edit showing two speakers side by side during
their debate. Add lower-third captions.
```

#### Voice Cloning
```
Create a voice profile from this video's speaker. I want to clone their voice.
```

```
Using the voice profile we just created, generate speech saying:
"Welcome to our channel! Don't forget to subscribe."
```

```
Generate a lip-synced talking-head video of the speaker saying a new script.
```

#### AI Audio
```
Generate background music for this clip. I want something upbeat and energetic,
around 120 BPM, that fits the mood of the highlights.
```

```
Create a cinematic intro sound effect for the beginning of this video.
```

```
Clean up the audio in this clip - reduce background noise and normalize levels.
```

### Workflow Examples

#### Content Creator Workflow
```
I have a 2-hour podcast recording. I need:
1. Analyze the full video
2. Find the 10 best moments (most engaging, emotional, or funny)
3. Create 5 separate 60-second TikTok clips from those moments
4. Each clip should have captions, face-tracking crop, and be 1080x1920
5. Render all 5 clips

Start with the analysis and show me what you find.
```

#### Meeting Recap Workflow
```
Analyze this meeting recording. I need:
1. Full transcript with speaker identification
2. Summary of key topics discussed
3. Action items and decisions made
4. A 3-minute highlight clip of the most important moments
```

#### Voice Clone Workflow
```
I want to create a voice clone from this interview video:
1. Analyze the video to find the best voice samples
2. Create a voice profile (aim for SECS > 0.95)
3. Test the clone by generating a sample sentence
4. If quality is good, generate a full intro script with the cloned voice
```

### Power User Prompts

```
Show me the scene map for this project. I want to understand the visual layout
of each scene so I can plan my edit.
```

```
Search the video content for any mention of "product launch" or "quarterly results".
Show me timestamps and context.
```

```
Compare the editing context between scene 3 and scene 7.
Which would work better as an opening shot?
```

```
Find safe cut points near the 2-minute mark. I need a clean transition
that doesn't interrupt mid-sentence.
```

```
Create a branch of my current edit. I want to try a different opening
without losing my original version.
```

### Voice Agent ("Jarvis")

ClipCannon includes a standalone real-time voice assistant:

```bash
# Start the voice agent
python -m voiceagent talk --voice boris

# WebSocket server for remote clients
python -m voiceagent serve --port 8765
```

Ask Claude to set it up:
```
Set up the Jarvis voice agent with wake word detection.
I want it to listen for "Hey Jarvis" and respond using my voice clone.
Use Ollama with qwen3:8b for fast responses.
```

### Meeting Bot (Santa/Avatar)

Join Google Meet as an AI-powered avatar:

```
Launch the Santa meeting bot on this Google Meet link: [URL]
It should:
1. Load all models into VRAM before joining
2. Listen continuously and respond when addressed
3. Use the Santa voice clone with full prosody
4. Respond within 2 seconds of being asked a question
```

---

## Features

- **22-Stage Analysis Pipeline** -- Transcription, scene detection, emotion analysis, speaker diarization, narrative structure, beat tracking, OCR, quality scoring, and more. All running as a parallelized DAG.
- **5 Embedding Spaces** -- Visual (SigLIP 1152-dim), semantic (Nomic 768-dim), emotion (Wav2Vec2 1024-dim), speaker (WavLM 512-dim), and voice identity (ECAPA-TDNN 2048-dim) stored in sqlite-vec for KNN search.
- **Smart Editing** -- Declarative EDL architecture with adaptive captions, face-tracking crop, split-screen, PIP, canvas compositing, motion effects, overlays, and iterative version control.
- **7 Platform Profiles** -- One-click rendering for TikTok, Instagram Reels, YouTube Shorts, YouTube Standard, YouTube 4K, Facebook, and LinkedIn with NVENC GPU acceleration.
- **AI Audio** -- Text-to-music via ACE-Step diffusion, 6 MIDI presets with FluidSynth, 9 DSP sound effects, speech-aware mixing with automatic ducking.
- **Voice Cloning** -- Qwen3-TTS 1.7B with multi-gate verification (sanity, intelligibility, identity via SECS), best-of-N optimization, and Resemble Enhance post-processing to 44.1kHz broadcast quality.
- **Lip-Sync Avatars** -- LatentSync 1.6 (ByteDance) diffusion pipeline for talking-head video generation from text scripts.
- **Meeting Bot** -- AI avatar that joins Google Meet, listens to conversation, and responds with voice-cloned speech via real-time ASR + LLM + TTS pipeline.
- **Phoenix Avatar Engine** -- Custom GPU-native avatar rendering with CuPy CUDA kernels (0.2ms compositing), insightface landmark detection, emotion-driven blend shapes, and prosody-matched voice selection.
- **Voice Agent ("Jarvis")** -- Real-time conversational AI with wake-word activation, streaming ASR, local LLM (Qwen3-8B/14B), and voice-cloned TTS. All local, zero cloud.
- **OCR Provenance RAG** -- Meeting transcripts stored in OCR Provenance for AI-searchable history across sessions.
- **Tamper-Evident Provenance** -- SHA-256 hash chain linking every pipeline operation.
- **Credit Billing** -- HMAC-signed balance with Stripe integration, spending limits, and transaction history.
- **100% Local** -- No data leaves your machine. All models run on your GPU. All storage is SQLite on disk.

---

## MCP Tools

55 tools organized into 12 categories:

| Category | Count | Key Tools |
|----------|-------|-----------|
| **Project** | 5 | `create`, `open`, `list`, `status`, `delete` |
| **Understanding** | 4 | `ingest`, `get_transcript`, `get_frame`, `search_content` |
| **Discovery** | 5 | `find_best_moments`, `find_cut_points`, `get_narrative_flow`, `find_safe_cuts`, `get_scene_map` |
| **Editing** | 11 | `create_edit`, `modify_edit`, `auto_trim`, `color_adjust`, `add_motion`, `add_overlay`, `apply_feedback`, `branch_edit`, `edit_history`, `revert_edit`, `list_branches` |
| **Rendering** | 6 | `render`, `preview_clip`, `preview_segment`, `preview_layout`, `inspect_render`, `analyze_frame` |
| **Context** | 2 | `get_editing_context`, `get_scene_map` |
| **Audio** | 5 | `generate_music`, `compose_music`, `compose_midi`, `generate_sfx`, `audio_cleanup`, `auto_music` |
| **Voice** | 4 | `prepare_voice_data`, `voice_profiles`, `speak`, `speak_optimized` |
| **Avatar** | 3 | `lip_sync`, `extract_webcam`, `generate_video` |
| **Billing** | 4 | `credits_balance`, `credits_history`, `credits_estimate`, `spending_limit` |
| **Disk** | 2 | `disk_status`, `disk_cleanup` |
| **Config** | 3 | `config_get`, `config_set`, `config_list` |

---

## Architecture

```
                    +-----------------+
                    |  AI Assistant   |  (Claude Code, Claude Desktop)
                    |  (MCP Client)   |
                    +--------+--------+
                             | MCP Protocol (stdio)
                    +--------v--------+
                    |  ClipCannon     |
                    |  MCP Server     |  55 tools
                    +--------+--------+
                             |
          +------------------+------------------+
          |                  |                  |
  +-------v------+  +-------v------+  +-------v-------+
  | Analysis     |  | Editing      |  | Voice/Avatar  |
  | Pipeline     |  | + Rendering  |  | Engine        |
  | (22 stages)  |  | Engine       |  |               |
  |              |  | (FFmpeg +    |  | Qwen3-TTS     |
  | SigLIP       |  |  NVENC)      |  | LatentSync    |
  | Nomic Embed  |  |              |  | Phoenix CuPy  |
  | Wav2Vec2     |  | 7 profiles   |  | insightface   |
  | WavLM        |  | ASS captions |  | ECAPA-TDNN    |
  | Qwen3-8B     |  | Smart crop   |  | Silero VAD    |
  | WhisperX     |  | Canvas comp  |  | Resemble Enh  |
  +-------+------+  +-------+------+  +-------+-------+
          |                  |                  |
          +------------------+------------------+
                             |
                    +--------v--------+
                    | SQLite + vec    |  Per-project DB
                    | (analysis.db)   |  4 vector tables
                    +-----------------+  31 core tables
```

### ML Models

| Model | Purpose | VRAM | Auto-Downloaded |
|-------|---------|------|-----------------|
| SigLIP-SO400M | Visual embeddings | ~2 GB | Yes (HF) |
| Nomic Embed v1.5 | Semantic embeddings | ~1 GB | Yes (HF) |
| Wav2Vec2-large | Emotion analysis | ~2 GB | Yes (HF) |
| WavLM-base-plus-sv | Speaker diarization | ~1 GB | Yes (HF) |
| WhisperX Large v3 | Speech-to-text | ~3 GB | Yes (HF) |
| faster-whisper large-v3-turbo | Real-time ASR | ~2 GB | Yes (HF) |
| HTDemucs v4 | Audio source separation | ~2 GB | Yes (HF) |
| Qwen3-8B/14B | LLM (via Ollama) | 5-10 GB | Via `ollama pull` |
| Qwen3-TTS 1.7B | Voice cloning (video) | ~4 GB | Yes (HF) |
| faster-qwen3-tts 0.6B | Real-time TTS | ~2 GB | Yes (HF) |
| LatentSync 1.6 | Lip-sync avatars | ~4 GB | Yes (HF) |
| ACE-Step v1.5 | AI music generation | ~4 GB | Yes (HF) |
| insightface buffalo_l | Face detection/landmarks | ~1 GB | Yes |
| Silero VAD v5 | Voice activity detection | CPU | Yes (torch.hub) |
| PaddleOCR v5 | On-screen text detection | ~1 GB | Yes |

Models are loaded on-demand with LRU eviction. GPUs with 24+ GB run models concurrently; smaller GPUs load sequentially.

---

## Frequently Asked Questions

### "How much VRAM do I need?"

- **8GB** -- Can run core analysis (one model at a time). Slower but functional.
- **16GB** -- Comfortable for analysis + editing + basic voice work.
- **24GB (RTX 4090)** -- Full pipeline including voice cloning and avatar generation.
- **32GB (RTX 5090)** -- Everything concurrent, real-time meeting bot with TTS + ASR + LLM simultaneously.

### "Can I run this without a GPU?"

The analysis pipeline requires CUDA. Editing and rendering work on CPU but are much slower without NVENC. The voice agent requires a GPU.

### "What about Mac/Apple Silicon?"

Not currently supported. The pipeline depends heavily on CUDA, PyTorch CUDA, and NVENC. MPS support is planned for a future release.

### "How long does analysis take?"

Depends on video length and GPU:
- 5-minute video on RTX 4090: ~2-3 minutes
- 1-hour video on RTX 4090: ~15-20 minutes
- The 22-stage DAG runs in parallel, so more GPU = faster

### "Is my data sent anywhere?"

No. Everything runs locally. All models run on your GPU. All data stays in SQLite on disk. No cloud APIs are called. The only network calls are model downloads from Hugging Face (first run only) and optional Ollama API (which also runs locally).

---

## Configuration

Config stored at `~/.clipcannon/config.json`:

```bash
# Key settings (via MCP tools)
processing.whisper_model = "large-v3"       # Whisper model size
processing.frame_extraction_fps = 2         # Frames per second to extract
rendering.use_nvenc = true                  # GPU-accelerated rendering
gpu.device = "cuda:0"                       # GPU device
gpu.max_vram_usage_gb = 24                  # VRAM limit
```

Auto-detects GPU precision: Blackwell (nvfp4), Ada Lovelace (int8), Ampere (int8), Turing (fp16), CPU (fp32).

---

## Project Structure

```
src/
  clipcannon/           # Core video editing package
    pipeline/           # 22-stage analysis DAG
    editing/            # EDL engine, captions, smart crop
    rendering/          # FFmpeg rendering, 7 profiles
    audio/              # AI music, MIDI, SFX, mixing
    voice/              # Voice cloning + verification
    avatar/             # LatentSync lip-sync
    tools/              # 55 MCP tool definitions
    db/                 # SQLite + sqlite-vec
    gpu/                # Precision detection, model manager
    provenance/         # SHA-256 hash chain
    billing/            # HMAC credits, license client
    dashboard/          # FastAPI web UI
  license_server/       # Credit billing service
  voiceagent/           # Real-time voice assistant
    asr/                # Whisper streaming, Silero VAD, endpointing
    tts/                # Streaming TTS, sentence chunker
    meeting/            # Meeting bot, MCP client, transcript store
    adapters/           # FastTTSAdapter (0.6B with CUDA graphs)
  phoenix/              # GPU-native avatar engine
    render/             # CuPy CUDA kernels, face warper, lip sync
    expression/         # Emotion fusion, speaker tracking, gesture library
    behavior/           # Prosody matcher, emotion mirror, cross-modal detection
scripts/
  santa_meet_bot.py     # Google Meet avatar bot
tests/                  # 994 tests across 50+ files
config/                 # Docker Compose, default config
docs/                   # White paper, architecture docs, codestate
```

---

## Testing

```bash
# Run full test suite (994 tests)
pytest

# Core ClipCannon tests
pytest tests/clipcannon/

# Voice agent tests
pytest tests/voiceagent/

# Phoenix avatar engine tests (GPU required)
pytest tests/phoenix/

# Integration tests (requires GPU + test video)
pytest tests/integration/

# Lint
ruff check src/
```

---

## Supported Formats

**Input**: mp4, mov, mkv, webm, avi, ts, mts

**Output**: Platform-optimized mp4 (h264/h265) at 7 resolution/bitrate profiles

---

## Documentation

- [White Paper](docs/clipcannon_whitepaper.md) -- Full technical paper
- [System Overview](docs/codestate/01_system_overview.md) -- High-level architecture
- [Source Code Map](docs/codestate/02_source_code_map.md) -- Complete file tree
- [Pipeline Stages](docs/codestate/06_pipeline_stages.md) -- All 22 stages
- [Database Schema](docs/codestate/04_database_schema.md) -- Full table definitions
- [Editing Engine](docs/codestate/13_editing_engine.md) -- EDL models, captions
- [Rendering Engine](docs/codestate/14_rendering_engine.md) -- FFmpeg pipeline
- [Audio Engine](docs/codestate/15_audio_engine.md) -- AI music, MIDI, SFX
- [Voice Agent](docs/codestate/16_voice_agent.md) -- Conversational AI architecture
- [Phoenix Implementation Plan](docs/project_phoenix_implementation_plan.md) -- Avatar engine roadmap

---

## Contributing

Contributions are welcome. Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for new functionality
4. Ensure all tests pass (`pytest`) and lint is clean (`ruff check src/`)
5. Submit a pull request

---

## License

[Business Source License 1.1](LICENSE) -- Chris Royse, 2026

You can use, modify, and self-host ClipCannon freely. The one restriction: you cannot use it to offer a competing commercial Video Production Service to third parties. On **2030-03-31** (or 4 years after each version's release), the license automatically converts to **Apache 2.0**.

---

<div align="center">

<a href="https://paypal.me/ChrisRoyseAI" target="_blank">
  <img src="https://img.shields.io/badge/SUPPORT_THIS_PROJECT-00457C?style=for-the-badge&logo=paypal&logoColor=white" alt="Support This Project" width="300"/>
</a>

<br><br>

Built with PyTorch, FFmpeg, sqlite-vec, CuPy, and the MCP protocol.

</div>
