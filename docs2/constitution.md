# ClipCannon Constitution

> **Level 1 Specification — Immutable Rules**
> All code, specs, tasks, and agent behavior MUST comply with this document.
> Violations require explicit exception approval and documentation in the decision log.

```xml
<constitution version="3.0">
<metadata>
  <project_name>ClipCannon</project_name>
  <spec_version>3.0.0</spec_version>
  <created>2026-03-26</created>
  <description>AI-native video editing, voice cloning, avatar pipeline, and real-time voice agent — local GPU, 22-stage multimodal analysis, platform-ready output, conversational AI assistant</description>
  <target_hardware>NVIDIA RTX 5090 (32GB GDDR7, CUDA 13.2) — degrades gracefully to RTX 2000+</target_hardware>
</metadata>

<!-- ============================================================ -->
<!-- TECH STACK                                                    -->
<!-- ============================================================ -->
<tech_stack>

  <!-- Runtime -->
  <language version="3.12+">Python</language>
  <framework version="1.0+">mcp library (Server class, stdio_server, Tool, TextContent)</framework>
  <database>SQLite 3.45+ (WAL mode, per-project analysis.db)</database>
  <vector_database version="0.1+">sqlite-vec (4 isolated vector tables)</vector_database>
  <video_engine version="7.x">FFmpeg (NVENC/NVDEC hardware acceleration)</video_engine>
  <gpu_framework version="2.3+">PyTorch (CUDA 13.2)</gpu_framework>
  <web_framework version="0.110+">FastAPI (license server on port 3100, dashboard on port 3200)</web_framework>
  <container>Docker (NVIDIA Container Toolkit, GPU passthrough)</container>

  <!-- ML Models — Understanding Pipeline (22 stages) -->
  <required_models>
    <model name="htdemucs" version="v4" vram_nvfp4="2.0GB" license="MIT">Source separation — 4 stems</model>
    <model name="whisperx" version="large-v3" vram_nvfp4="1.5GB" license="BSD-4-Clause">Transcription — mandatory wav2vec2 forced alignment</model>
    <model name="siglip" version="SO400M-patch14-384" vram_nvfp4="0.6GB" license="Apache-2.0">Visual embedding — 1152-dim</model>
    <model name="paddleocr" version="PP-OCRv5" vram_nvfp4="0.75GB" license="Apache-2.0">On-screen text detection</model>
    <model name="pyiqa-brisque" version="latest" vram_nvfp4="0.3GB" license="Public-Domain">Frame quality scoring (GPU)</model>
    <model name="dover-mobile" version="latest" vram_nvfp4="0.45GB" license="MIT">Aesthetic quality scoring (GPU)</model>
    <model name="resnet50-shottype" version="MovieShots" vram_nvfp4="0.2GB" license="MIT">Shot type classification</model>
    <model name="nomic-embed-text" version="v1.5" vram_nvfp4="0.25GB" license="Apache-2.0">Semantic embedding — 768-dim</model>
    <model name="wav2vec2-emotion" version="large" vram_nvfp4="0.75GB" license="MIT">Emotion/energy analysis — 1024-dim</model>
    <model name="wavlm-base-plus-sv" version="latest" vram_nvfp4="0.2GB" license="MIT">Speaker diarization — 512-dim</model>
    <model name="sensevoice-small" version="latest" vram_nvfp4="0.55GB" license="Apache-2.0">Reaction detection (laughter, applause)</model>
    <model name="beat-this" version="latest" vram_nvfp4="0.5GB" license="Open-Source">Beat/downbeat detection (GPU Transformer)</model>
    <model name="silero-vad" version="5.0" vram_nvfp4="0GB" license="MIT">Voice activity detection (CPU only)</model>
    <model name="Qwen3-8B" version="latest" vram_nvfp4="4.0GB" license="Apache-2.0">Narrative structure analysis — story beats, open loops, chapters, key moments (subprocess)</model>
  </required_models>

  <!-- ML Models — Audio Generation (loaded on demand) -->
  <optional_models>
    <model name="ace-step" version="v1.5-turbo-rl" vram_nvfp4="4.0GB" license="MIT">AI music generation</model>
  </optional_models>

  <!-- ML Models — Voice / Avatar (loaded on demand for ClipCannon video pipeline) -->
  <voice_avatar_models>
    <model name="Qwen3-TTS" version="1.7B" license="Apache-2.0">Voice synthesis with reference audio style transfer (high-quality, video generation)</model>
    <model name="Qwen3-Voice-Embedding-12Hz-1.7B" version="latest" license="Apache-2.0">2048-dim ECAPA-TDNN speaker encoder for identity verification</model>
    <model name="resemble-enhance" version="latest" license="MIT">Audio denoising + latent flow matching (24kHz → 44.1kHz)</model>
    <model name="faster-whisper-base" version="base" license="MIT">Transcription for WER verification gate (CPU, int8)</model>
    <model name="LatentSync" version="1.6" license="Apache-2.0">ByteDance diffusion-based lip-sync (512x512, DDIM)</model>
  </voice_avatar_models>

  <!-- ML Models — Voice Agent (real-time conversational AI, separate from ClipCannon) -->
  <voice_agent_models>
    <model name="Qwen3-14B-FP8" version="latest" vram_fp8="~14GB" license="Apache-2.0">Conversational LLM brain (vLLM, 0.45 GPU utilization)</model>
    <model name="faster-whisper-large-v3" version="large-v3" license="MIT">Streaming ASR with VAD endpointing</model>
    <model name="faster-qwen3-tts" version="0.6B" license="Apache-2.0">Low-latency TTS (~500ms TTFB) with CUDA graphs, Full ICL mode</model>
    <model name="silero-vad" version="5.0" vram_nvfp4="0GB" license="MIT">Voice activity detection for endpointing (CPU)</model>
  </voice_agent_models>

  <!-- Core Libraries -->
  <required_libraries>
    <library version="1.26+">numpy</library>
    <library version="1.12+">scipy</library>
    <library version="10.0+">Pillow</library>
    <library version="2.0+">pydantic</library>
    <library version="0.25+">httpx</library>
    <library version="8.0+">stripe</library>
    <library version="3.3+">python-jose (JWT)</library>
  </required_libraries>

  <!-- Audio Generation Libraries -->
  <required_libraries_audio>
    <library version="latest">pydub (audio mixing)</library>
    <library version="latest">pedalboard (audio effects, GPLv3)</library>
    <library version="latest">MIDIUtil (MIDI composition)</library>
    <library version="latest">pyfluidsynth (MIDI rendering)</library>
  </required_libraries_audio>

  <!-- Video / Editing Libraries -->
  <required_libraries_video>
    <library version="latest">mediapipe (face detection for smart cropping)</library>
    <library version="latest">opencv-python (scene analysis, frame processing)</library>
    <library version="latest">rembg (AI background removal)</library>
  </required_libraries_video>

  <!-- Voice / Avatar Libraries (ClipCannon) -->
  <required_libraries_voice>
    <library version="latest">torchaudio (audio I/O and resampling)</library>
    <library version="latest">transformers (Qwen3-TTS, speaker encoder)</library>
    <library version="latest">soundfile (audio metadata inspection)</library>
    <library version="latest">resemble-enhance (TTS post-processing)</library>
  </required_libraries_voice>

  <!-- Voice Agent Libraries -->
  <required_libraries_voice_agent>
    <library version="latest">vllm (Qwen3-14B-FP8 LLM serving)</library>
    <library version="latest">faster-whisper (streaming ASR)</library>
    <library version="latest">pyaudio (local audio capture/playback)</library>
    <library version="latest">websockets (WebSocket transport)</library>
    <library version="latest">numpy (audio buffer processing)</library>
  </required_libraries_voice_agent>

</tech_stack>

<!-- ============================================================ -->
<!-- DIRECTORY STRUCTURE                                            -->
<!-- ============================================================ -->
<directory_structure>
clipcannon/
├── src/
│   └── clipcannon/
│       ├── __init__.py
│       ├── server.py                  # MCP server entry (mcp library, Server class, stdio transport)
│       ├── config.py                  # Configuration management (dot-notation, Pydantic validation)
│       ├── exceptions.py              # ClipCannonError hierarchy (Pipeline, Billing, Provenance, Database, Config, GPU)
│       ├── tools/                     # MCP tool definitions (51 tools, 26 modules)
│       │   ├── __init__.py            # Tool registry + understanding tools (ingest, transcript, frame, search)
│       │   ├── project.py             # 5 project CRUD tools
│       │   ├── understanding.py       # Understanding tool handlers (ingest, transcript)
│       │   ├── understanding_search.py # Semantic/text content search
│       │   ├── understanding_visual.py # Frame extraction with moment context
│       │   ├── video_probe.py         # FFprobe wrapper and format validation
│       │   ├── editing.py             # 11 editing tools (create, modify, trim, color, motion, overlays, history, revert, feedback, branch)
│       │   ├── editing_defs.py        # JSON schema for editing tools
│       │   ├── editing_helpers.py     # EDL builder functions, DB storage helpers
│       │   ├── feedback.py            # Natural language feedback parsing
│       │   ├── rendering.py           # 8 rendering tools (render, context, analyze, preview, inspect, scene_map, segment)
│       │   ├── rendering_defs.py      # JSON schema for rendering tools
│       │   ├── storyboard.py          # Contact sheet generation
│       │   ├── audio.py               # 4 audio tools (music gen, MIDI, SFX, cleanup)
│       │   ├── discovery.py           # 4 discovery tools (best moments, cut points, narrative flow, safe cuts)
│       │   ├── discovery_defs.py      # JSON schema for discovery tools
│       │   ├── voice.py               # 4 voice tools (data prep, profiles, speak, speak_optimized)
│       │   ├── voice_defs.py          # JSON schema for voice tools
│       │   ├── avatar.py              # 1 avatar tool (lip_sync)
│       │   ├── avatar_defs.py         # JSON schema for avatar tool
│       │   ├── generate_video.py      # 1 video generation tool (voice + lip-sync end-to-end)
│       │   ├── generate_defs.py       # JSON schema for generate_video tool
│       │   ├── billing_tools.py       # 4 billing tools (balance, history, estimate, spending limit)
│       │   ├── provenance_tools.py    # Provenance tool definitions (currently empty; accessed via dashboard)
│       │   ├── disk.py                # 2 disk management tools (status, cleanup)
│       │   └── config_tools.py        # 3 configuration tools (get, set, list)
│       ├── pipeline/                  # Processing pipeline stages (22 stages, 29 modules)
│       │   ├── __init__.py
│       │   ├── orchestrator.py        # DAG-based pipeline runner
│       │   ├── dag.py                 # Topological sort (Kahn's algorithm)
│       │   ├── registry.py            # Stage registry with dependency graph
│       │   ├── source_resolution.py   # Source/audio path resolution helpers
│       │   ├── probe.py               # FFprobe metadata extraction
│       │   ├── vfr_normalize.py       # Variable → constant frame rate
│       │   ├── audio_extract.py       # Audio track extraction (16kHz mono + original)
│       │   ├── source_separation.py   # HTDemucs 4-stem separation
│       │   ├── frame_extract.py       # Frame extraction at configured FPS
│       │   ├── frame_utils.py         # Frame path resolution and shared frame helpers
│       │   ├── transcribe.py          # WhisperX + anti-hallucination filtering
│       │   ├── visual_embed.py        # SigLIP 1152-dim + scene detection
│       │   ├── ocr.py                 # PaddleOCR on-screen text
│       │   ├── screen_layout.py       # Webcam/content region detection
│       │   ├── scene_analysis.py      # Face detection, layout recommendations, canvas region pre-computation
│       │   ├── quality.py             # BRISQUE + DOVER quality scoring
│       │   ├── shot_type.py           # ResNet-50 shot classification
│       │   ├── semantic_embed.py      # Nomic 768-dim + topic extraction
│       │   ├── emotion_embed.py       # Wav2Vec2 1024-dim emotion
│       │   ├── speaker_embed.py       # WavLM 512-dim speaker diarization
│       │   ├── reactions.py           # SenseVoice reaction detection
│       │   ├── acoustic.py            # Volume, dynamic range, silence detection
│       │   ├── chronemic.py           # Pacing analysis (WPM, pause ratios)
│       │   ├── profanity.py           # Profanity detection and content safety
│       │   ├── highlights.py          # Multi-signal highlight scoring
│       │   ├── narrative_llm.py       # Qwen3-8B narrative analysis (story beats, open loops, chapters, key moments)
│       │   ├── storyboard.py          # Contact sheet grid generation
│       │   └── finalize.py            # Final status update
│       ├── editing/                   # Edit decision engine (12 modules)
│       │   ├── edl.py                 # EDL Pydantic models and validation
│       │   ├── captions.py            # Adaptive caption chunking
│       │   ├── caption_render.py      # ASS subtitle generation (4 styles)
│       │   ├── smart_crop.py          # Content-aware cropping (face tracking, split-screen, PIP)
│       │   ├── metadata_gen.py        # Platform-specific metadata generation
│       │   ├── auto_trim.py           # Filler word and pause removal
│       │   ├── motion.py              # Motion effects (zoom, pan, Ken Burns)
│       │   ├── overlays.py            # Visual overlays (lower third, title, logo, watermark, CTA)
│       │   ├── subject_extraction.py  # AI background removal via rembg
│       │   ├── measure_layout.py      # Face detection + canvas region computation
│       │   └── change_classifier.py   # Edit change classification for iterative editing
│       ├── rendering/                 # FFmpeg rendering engine (9 modules)
│       │   ├── renderer.py            # Async render pipeline (validation, caption, crop, FFmpeg, thumbnail, provenance)
│       │   ├── ffmpeg_cmd.py          # FFmpeg command builder (standard, split-screen, PIP, canvas compositing)
│       │   ├── profiles.py            # 7 encoding profiles (tiktok, instagram, youtube, facebook, linkedin)
│       │   ├── batch.py               # Batch rendering coordination
│       │   ├── thumbnail.py           # JPEG thumbnail extraction
│       │   ├── inspector.py           # Render inspection (frames, metadata, quality checks)
│       │   ├── preview.py             # Low-quality preview generation (clip, layout, segment)
│       │   └── segment_hash.py        # Segment-level cache hashing
│       ├── audio/                     # Audio generation engine (7 modules)
│       │   ├── music_gen.py           # ACE-Step v1.5 AI music (GPU)
│       │   ├── midi_compose.py        # MIDI from 6 presets
│       │   ├── midi_render.py         # FluidSynth MIDI → WAV
│       │   ├── sfx.py                 # 9 DSP sound effects
│       │   ├── mixer.py               # Speech-aware audio mixing with ducking
│       │   ├── effects.py             # Pedalboard audio effects chain
│       │   └── cleanup.py             # Noise reduction, normalization, silence trim, EQ
│       ├── voice/                     # Voice cloning engine (8 modules)
│       │   ├── data_prep.py           # Silence-boundary splitting, transcript matching, train/val manifests
│       │   ├── inference.py           # VoiceSynthesizer: Qwen3-TTS with iterative verification
│       │   ├── multi_voice.py         # Multi-voice synthesis for conversational scenarios (voice swapping mid-conversation)
│       │   ├── verify.py              # Multi-gate verification: sanity, intelligibility (WER), identity (SECS 2048-dim)
│       │   ├── optimize.py            # SECS-optimized best-of-N candidate selection
│       │   ├── profiles.py            # Voice profile SQLite CRUD (~/.clipcannon/voice_profiles.db)
│       │   └── enhance.py             # Resemble Enhance: denoise + latent flow matching (24kHz → 44.1kHz)
│       ├── avatar/                    # Avatar / lip-sync engine (2 modules)
│       │   └── lip_sync.py            # LatentSync 1.6 diffusion pipeline (512x512, DDIM)
│       ├── billing/                   # Credit system
│       │   ├── license_client.py      # Async HTTP client for license server
│       │   ├── credits.py             # Credit rates, packages, spending limits
│       │   └── hmac_integrity.py      # HMAC-SHA256 balance signing
│       ├── provenance/                # Hash chain system
│       │   ├── hasher.py              # SHA-256 utilities (file, bytes, string, table)
│       │   ├── chain.py               # Tamper-evident chain computation and verification
│       │   └── recorder.py            # Provenance record CRUD
│       ├── db/                        # Database layer
│       │   ├── schema.py              # DDL for 30 tables + 4 vector tables + indexes, migrations v1→v2→v3
│       │   ├── connection.py          # Connection factory with WAL pragmas, sqlite-vec loading
│       │   └── queries.py             # Parameterized query helpers, transaction manager
│       ├── gpu/                       # GPU management
│       │   ├── manager.py             # ModelManager with LRU eviction, concurrent/sequential mode
│       │   └── precision.py           # Precision auto-detection from CUDA compute capability
│       └── dashboard/                 # Web dashboard (port 3200)
│           ├── app.py                 # FastAPI app factory, CORS, route registration
│           ├── auth.py                # JWT dev-mode auth (HS256, 30-day TTL)
│           └── routes/                # 7 route modules (home, credits, projects, provenance, editing, review, timeline)
│   └── voiceagent/                    # Real-time voice agent (Jarvis) — separate from ClipCannon
│       ├── __init__.py
│       ├── __main__.py                # Entry point
│       ├── agent.py                   # VoiceAgent orchestrator — lifecycle, pipeline coordination
│       ├── cli.py                     # CLI entry (python -m voiceagent)
│       ├── config.py                  # Frozen dataclass config (LLM, ASR, TTS, Conversation, Transport)
│       ├── errors.py                  # VoiceAgentError hierarchy (ASR, TTS, LLM, Config, Transport)
│       ├── gpu_manager.py             # GPU memory management for voice agent models
│       ├── server.py                  # WebSocket server (FastAPI)
│       ├── activation/                # Wake word and hotkey activation
│       │   ├── wake_word.py           # Configurable wake word detection with audio feedback
│       │   └── hotkey.py              # Push-to-talk hotkey activation
│       ├── adapters/                  # TTS backend adapters
│       │   ├── clipcannon.py          # ClipCannon 1.7B Qwen3-TTS adapter (high-quality)
│       │   └── fast_tts.py            # faster-qwen3-tts 0.6B adapter (~500ms TTFB, CUDA graphs)
│       ├── asr/                       # Automatic speech recognition
│       │   ├── streaming.py           # Streaming ASR with faster-whisper
│       │   ├── endpointing.py         # Silence-based endpoint detection
│       │   ├── vad.py                 # Silero VAD integration
│       │   └── types.py               # ASR result types
│       ├── brain/                     # LLM reasoning
│       │   ├── llm.py                 # Qwen3-14B-FP8 via vLLM
│       │   ├── context.py             # Conversation context management
│       │   └── prompts.py             # System prompt templates
│       ├── conversation/              # Conversation state management
│       │   ├── manager.py             # Turn handling, interruption, history
│       │   └── state.py               # Conversation state machine
│       ├── transport/                 # Audio I/O transports
│       │   ├── local_audio.py         # Local microphone/speaker (PyAudio)
│       │   └── websocket.py           # WebSocket transport
│       ├── tts/                       # Text-to-speech
│       │   ├── streaming.py           # Streaming TTS synthesis
│       │   └── chunker.py             # Text chunking for streaming TTS
│       └── db/                        # Voice agent database
│           ├── connection.py          # SQLite connection factory
│           └── schema.py              # Conversation history schema
├── src/license_server/                # Standalone license server (port 3100)
│   ├── server.py                      # FastAPI app, SQLite-backed credits, HMAC integrity
│   ├── d1_sync.py                     # Cloudflare D1 sync stub (local-only)
│   └── stripe_webhooks.py             # Stripe checkout webhook handler
├── tests/                             # 42 pytest files (~686 tests), 10 FSV scripts
│   ├── conftest.py                    # Session-scoped shared fixtures
│   ├── test_pipeline_stages.py        # 12 tests — probe, audio/frame extract, DAG, orchestrator
│   ├── test_visual_pipeline.py        # 34 tests — storyboard, quality, visual embed, OCR, shot type
│   ├── test_derived_stages.py         # 14 tests — profanity, chronemic, highlights, finalize
│   ├── test_understanding_tools.py    # 11 tests — transcript, search, frame tools
│   ├── test_provenance_integration.py # 19 tests — hash chain, tamper detection
│   ├── test_billing.py                # 40 tests — HMAC, credits, license server, D1, Stripe
│   ├── test_edl.py                    # 19 tests — EDL models, validation, platform constraints
│   ├── test_captions.py               # 14 tests — caption chunking, ASS generation
│   ├── test_smart_crop.py             # 15 tests — crop regions, face tracking, aspect ratios
│   ├── test_editing_tools.py          # 19 tests — create/modify/list edits, metadata, iterative editing
│   ├── test_rendering.py              # 14 tests — encoding profiles, codec fallback
│   ├── test_audio_generation.py       # 15 tests — 9 SFX types, 6 MIDI presets
│   ├── test_discovery_tools.py        # 28 tests — best moments, cut points, narrative flow, safe cuts
│   ├── test_change_classifier.py      # 27 tests — change classification for iterative editing
│   ├── test_feedback.py               # 30 tests — natural language feedback application
│   ├── test_preview_segment.py        # 3 tests — segment preview rendering
│   ├── test_segment_cache.py          # 17 tests — segment-level render caching
│   ├── test_avatar.py                 # 12 tests — lip-sync engine (LatentSync)
│   ├── test_voice_verify.py           # 16 tests — multi-gate voice verification (WER, SECS, sanity)
│   ├── test_voice_inference.py        # 5 tests — Qwen3-TTS voice synthesis
│   ├── test_voice_data_prep.py        # 11 tests — voice data preparation, profile CRUD
│   ├── test_dashboard_phase2.py       # 12 tests — timeline, editing, review endpoints
│   ├── dashboard/test_dashboard.py    # 18 tests — dashboard endpoints
│   ├── integration/test_full_pipeline.py # 22 tests — full pipeline with real video
│   ├── voiceagent/                    # ~201 tests — voice agent subsystem
│   │   ├── conftest.py                # Voice agent test fixtures
│   │   ├── test_agent.py              # Agent orchestrator tests
│   │   ├── test_asr_types.py          # ASR result types
│   │   ├── test_chunker.py            # TTS text chunking
│   │   ├── test_cli.py                # CLI entry tests
│   │   ├── test_clipcannon_adapter.py # ClipCannon TTS adapter
│   │   ├── test_config.py             # Config loading, defaults
│   │   ├── test_context.py            # Conversation context
│   │   ├── test_conversation.py       # Turn handling, interruption
│   │   ├── test_db.py                 # Conversation DB
│   │   ├── test_hotkey.py             # Hotkey activation
│   │   ├── test_integration.py        # End-to-end voice pipeline
│   │   ├── test_llm.py                # LLM brain
│   │   ├── test_prompts.py            # System prompts
│   │   ├── test_server.py             # WebSocket server
│   │   ├── test_streaming_asr.py      # Streaming ASR
│   │   ├── test_streaming_tts.py      # Streaming TTS
│   │   ├── test_vad.py                # VAD tests
│   │   ├── test_wake_word.py          # Wake word detection
│   │   └── test_websocket.py          # WebSocket transport
│   ├── fsv_*.py                       # 6 FSV scripts (750+ checks total)
│   ├── manual_fsv_full.py             # Comprehensive system-wide verification
│   ├── manual_fsv_iterative.py        # Iterative editing verification
│   ├── manual_fsv_phase3.py           # Editing, rendering, audio, voice tools
│   └── integration/manual_verify.py   # Integration verification
├── config/
│   ├── default_config.json
│   └── docker-compose.yml
├── scripts/
│   ├── setup.sh
│   ├── download_models.py
│   ├── validate_gpu.py
│   ├── docker-entrypoint.sh           # Docker container entry point
│   └── jarvis-service.sh              # Systemd service script for voice agent
├── benchmarks/                        # Voice cloning benchmarks and evaluation
│   ├── results/                       # Benchmark result JSON files (SV-EER, Seed-TTS, WavLM)
│   ├── scripts/                       # Benchmark runners (seed-TTS eval, gradient optimization, WavLM)
│   ├── seedtts_eval/                  # Seed-TTS evaluation audio pairs
│   └── publish/                       # ArXiv report, HuggingFace model card, Gradio demo app
├── assets/
│   └── profanity/                     # Profanity word list
├── docs/codestate/                    # 15 codestate reference documents
├── docs2/                             # PRD, planning, and guide documents
├── Dockerfile
├── pyproject.toml
└── CLAUDE.md
</directory_structure>

<!-- ============================================================ -->
<!-- CODING STANDARDS                                              -->
<!-- ============================================================ -->
<coding_standards>

  <naming_conventions>
    <files>snake_case for all Python files (e.g., visual_embed.py, license_client.py)</files>
    <directories>snake_case for directories (e.g., pipeline/, license_server/)</directories>
    <classes>PascalCase for classes (e.g., ModelManager, PipelineOrchestrator, LicenseClient, VoiceSynthesizer)</classes>
    <functions>snake_case for functions and methods (e.g., compute_chain_hash, enhance_speech)</functions>
    <variables>snake_case for variables and parameters (e.g., project_id, frame_count)</variables>
    <constants>SCREAMING_SNAKE_CASE for constants (e.g., SCENE_THRESHOLD, SAMPLE_RATE, MAX_TOKEN_RESPONSE)</constants>
    <mcp_tools>snake_case prefixed with clipcannon_ (e.g., clipcannon_speak, clipcannon_ingest)</mcp_tools>
    <db_tables>snake_case for table names (e.g., transcript_segments, voice_profiles)</db_tables>
    <db_columns>snake_case for column names (e.g., start_ms, chain_hash, reference_embedding)</db_columns>
    <project_ids>Prefixed: proj_ + 8 hex chars (e.g., proj_a1b2c3d4)</project_ids>
    <provenance_ids>Prefixed: prov_ + 3-digit sequence (e.g., prov_001, prov_019)</provenance_ids>
    <voice_profile_ids>Prefixed: vp_ + hex (e.g., vp_abc123)</voice_profile_ids>
    <voice_agent_config>Frozen dataclasses with defaults (e.g., LLMConfig, ASRConfig, TTSConfig)</voice_agent_config>
  </naming_conventions>

  <type_annotations>
    <rule>ALL public functions MUST have full type annotations (parameters + return)</rule>
    <rule>Use pydantic BaseModel for all MCP tool parameters and responses</rule>
    <rule>Use dataclasses for internal data structures where pydantic is overkill</rule>
    <rule>Use TypedDict for simple dict shapes</rule>
    <rule>NEVER use Any — use Union, Optional, or a specific type</rule>
    <rule>Use Literal for string enums with fixed values (e.g., Literal["created", "analyzing", "ready", "error"])</rule>
  </type_annotations>

  <file_organization>
    <rule>One module per pipeline stage (e.g., transcribe.py contains only WhisperX logic)</rule>
    <rule>One file per MCP tool domain (e.g., tools/voice.py contains all voice tools)</rule>
    <rule>Maximum 500 lines per file — split into sub-modules if exceeded</rule>
    <rule>Shared utilities go in a utils/ module, not duplicated across files</rule>
    <rule>All imports at file top, stdlib first, then third-party, then local</rule>
    <rule>Circular imports are forbidden — restructure with dependency injection or interfaces</rule>
  </file_organization>

  <docstrings>
    <rule>All public classes and functions MUST have docstrings</rule>
    <rule>Use Google-style docstrings (Args, Returns, Raises sections)</rule>
    <rule>Pipeline stages must document: model used, VRAM requirement, input/output, fallback behavior</rule>
    <rule>MCP tools must document: parameter constraints, response token budget, error codes</rule>
  </docstrings>

  <error_handling>
    <rule>All pipeline stages MUST catch and handle exceptions — never let model inference crash the server</rule>
    <rule>Optional pipeline stages: catch Exception, log error, set stream_status="failed", insert fallback values</rule>
    <rule>Required pipeline stages: catch Exception, log error, set stream_status="failed", stop pipeline, refund credits</rule>
    <rule>MCP tools: return structured error JSON, never raise unhandled exceptions</rule>
    <rule>Log errors with full context (project_id, stage name, model name, stack trace) before handling</rule>
    <rule>Use custom exception hierarchy: ClipCannonError → PipelineError, BillingError, ProvenanceError, DatabaseError, ConfigError, GPUError</rule>
    <rule>NEVER silently swallow exceptions — always log at minimum</rule>
  </error_handling>

  <async_patterns>
    <rule>MCP tools are async (mcp library requirement)</rule>
    <rule>Pipeline orchestrator uses asyncio for parallel stage execution</rule>
    <rule>GPU model inference runs in thread executor to avoid blocking event loop</rule>
    <rule>License server HTTP calls are async via httpx</rule>
    <rule>Database writes are synchronous (SQLite limitation) — wrapped in run_in_executor if called from async</rule>
  </async_patterns>

</coding_standards>

<!-- ============================================================ -->
<!-- ARCHITECTURE RULES                                            -->
<!-- ============================================================ -->
<architecture_rules>

  <data_architecture>
    <rule id="ARCH-01">ONE SQLite database per project (analysis.db) — contains ALL structured data, embeddings, provenance</rule>
    <rule id="ARCH-02">Binary media (video, audio, frames, renders) stored as files on disk, referenced by path in DB</rule>
    <rule id="ARCH-03">sqlite-vec virtual tables for vector storage — 4 isolated tables, NEVER cross-space comparison</rule>
    <rule id="ARCH-04">WAL journal mode on every SQLite connection — enables concurrent reads during pipeline writes</rule>
    <rule id="ARCH-05">All timestamps in milliseconds (INTEGER) — unified timeline across all streams</rule>
    <rule id="ARCH-06">Embedding vectors NEVER sent to AI via MCP — only derived scalars (energy, quality, similarity)</rule>
    <rule id="ARCH-07">Voice profiles stored in a separate database (~/.clipcannon/voice_profiles.db) — not per-project</rule>
  </data_architecture>

  <pipeline_architecture>
    <rule id="ARCH-10">DAG-based execution — stages declare dependencies, orchestrator resolves execution order via topological sort</rule>
    <rule id="ARCH-11">Required stages (6) stop pipeline on failure; optional stages (16) degrade gracefully with fallback values</rule>
    <rule id="ARCH-12">HTDemucs source separation runs BEFORE all audio analysis — clean stems are force multiplier</rule>
    <rule id="ARCH-13">WhisperX with wav2vec2 forced alignment is MANDATORY — base Whisper timestamps drift 200-500ms</rule>
    <rule id="ARCH-14">Every pipeline stage writes a provenance record with SHA-256 hashes of input and output</rule>
    <rule id="ARCH-15">Scene analysis pre-computes canvas regions for all layout types (A/B/C/D) so AI never manually measures coordinates</rule>
  </pipeline_architecture>

  <mcp_architecture>
    <rule id="ARCH-20">Every MCP tool response MUST be under 25,000 tokens — Claude truncates beyond this</rule>
    <rule id="ARCH-21">Large data (transcript, scene map) delivered progressively through paginated tool calls</rule>
    <rule id="ARCH-22">Stateless tool calls, stateful project data — no in-memory state between tool calls</rule>
    <rule id="ARCH-23">All MCP responses are JSON with consistent error format: {error: {code, message, details}}</rule>
    <rule id="ARCH-24">Frame images delivered inline for multimodal AI consumption (JPEG via image content type)</rule>
  </mcp_architecture>

  <rendering_architecture>
    <rule id="ARCH-30">FFmpeg is the ONLY renderer — AI produces EDL JSON, ffmpeg_cmd.py builds FFmpeg filter_complex commands</rule>
    <rule id="ARCH-31">Immutable source reference: every EDL contains source_file_sha256, renderer verifies before executing</rule>
    <rule id="ARCH-32">Renderer REFUSES to open any file from renders/ directory as source input — prevents generation loss</rule>
    <rule id="ARCH-33">Single-pass rendering: multi-segment EDLs become ONE FFmpeg filter_complex, no intermediate re-encodes</rule>
    <rule id="ARCH-34">Re-render = new render from original source, never from previous render output</rule>
  </rendering_architecture>

  <voice_architecture>
    <rule id="ARCH-60">Voice synthesis uses Full ICL mode — real reference audio clip required for style transfer</rule>
    <rule id="ARCH-61">Speaker identity verified via 2048-dim Qwen3-TTS ECAPA-TDNN embeddings (not SpeechBrain 192-dim)</rule>
    <rule id="ARCH-62">Multi-gate verification pipeline: sanity (duration/clipping/SNR/silence) → intelligibility (WER) → identity (SECS)</rule>
    <rule id="ARCH-63">All TTS output auto-enhanced via Resemble Enhance (denoise + 44.1kHz upsample) unless explicitly disabled</rule>
    <rule id="ARCH-64">WER computation is case-insensitive and punctuation-stripped to avoid false failures</rule>
    <rule id="ARCH-65">SECS scoring uses the SAME encoder model for both reference embedding and candidate embedding — never mix encoder spaces</rule>
  </voice_architecture>

  <voice_agent_architecture>
    <rule id="ARCH-70">Voice agent (Jarvis) is a SEPARATE application from ClipCannon MCP — independent entry point, config, and model stack</rule>
    <rule id="ARCH-71">Voice agent uses faster-qwen3-tts 0.6B for low-latency TTS (~500ms TTFB); ClipCannon uses full 1.7B for video generation quality</rule>
    <rule id="ARCH-72">LLM brain runs Qwen3-14B-FP8 via vLLM with 0.45 GPU memory utilization, max 150 output tokens for conversational speed</rule>
    <rule id="ARCH-73">ASR uses faster-whisper-large-v3 with Silero VAD endpointing (600ms silence threshold)</rule>
    <rule id="ARCH-74">Conversation manager handles turn-taking, interruption detection, and history (max 50 turns)</rule>
    <rule id="ARCH-75">Transport layer supports both local audio (PyAudio) and WebSocket for remote clients</rule>
    <rule id="ARCH-76">Wake word engine supports configurable sensitivity, multi-keyword, and audio feedback</rule>
    <rule id="ARCH-77">Multi-voice synthesis enables voice swapping mid-conversation for scripted dialogue scenarios</rule>
    <rule id="ARCH-78">Voice agent config uses frozen dataclasses (immutable after creation), loaded from ~/.voiceagent/config.json</rule>
  </voice_agent_architecture>

  <billing_architecture>
    <rule id="ARCH-40">Two-layer trust: License Server (SQLite-backed, port 3100) → HMAC-SHA256 integrity (tamper detection). D1 remote sync stubs exist for future scale-out.</rule>
    <rule id="ARCH-41">Credits charged BEFORE operation begins, refunded on failure</rule>
    <rule id="ARCH-42">HMAC-SHA256 signs every balance mutation — tampered balance = fatal server exit</rule>
    <rule id="ARCH-43">Machine ID derived deterministically from hardware — same machine always gets same key</rule>
  </billing_architecture>

  <gpu_architecture>
    <rule id="ARCH-50">Precision auto-selection: NVFP4 (Blackwell CC 12.0), INT8 (Ada/Ampere CC 8.6+), FP16 (Turing CC 7.5)</rule>
    <rule id="ARCH-51">All understanding models fit in VRAM concurrently at NVFP4 (~10.6GB on RTX 5090)</rule>
    <rule id="ARCH-52">Audio generation and voice models loaded on demand AFTER understanding models unloaded</rule>
    <rule id="ARCH-53">On GPUs with less than 16GB VRAM: sequential model loading — load, infer, unload per stage</rule>
    <rule id="ARCH-54">NVENC operates on dedicated silicon — does not consume CUDA cores or interfere with inference</rule>
  </gpu_architecture>

</architecture_rules>

<!-- ============================================================ -->
<!-- ANTI-PATTERNS (FORBIDDEN)                                     -->
<!-- ============================================================ -->
<anti_patterns>
  <forbidden>
    <!-- Data & Embeddings -->
    <item reason="Mathematically meaningless">NEVER compare embeddings across different vector tables (e.g., SigLIP vs Nomic) — cross-stream correlation is done via timestamp JOINs only</item>
    <item reason="AI cannot process raw vectors">NEVER send raw embedding vectors to AI via MCP — send derived scalars and labels only</item>
    <item reason="Data corruption risk">NEVER modify the original source video file — it is read-only (Sacred tier)</item>
    <item reason="Generation loss">NEVER use a previously rendered output as source input for a new render — always render from original source</item>

    <!-- MCP -->
    <item reason="Truncation by Claude">NEVER return more than 25K tokens in a single MCP response — paginate large data</item>

    <!-- Pipeline -->
    <item reason="200-500ms timestamp drift">NEVER use base Whisper timestamps without wav2vec2 forced alignment — WhisperX is mandatory</item>
    <item reason="Dramatically worse audio analysis quality">NEVER feed mixed audio directly to emotion/speaker/reaction models if HTDemucs is available — always use clean vocal stem</item>
    <item reason="Data loss">NEVER skip provenance recording on any pipeline stage — every transformation must be hash-tracked</item>

    <!-- Voice -->
    <item reason="Encoder space mismatch">NEVER mix speaker encoder models — reference embedding and verification MUST use the same model (Qwen3-Voice-Embedding-12Hz-1.7B)</item>
    <item reason="Stale embeddings">NEVER use 192-dim SpeechBrain embeddings for verification — reject and require rebuild with 2048-dim encoder</item>
    <item reason="Raw vocoder artifacts">NEVER ship raw Qwen3-TTS output without Resemble Enhance post-processing unless user explicitly opts out</item>

    <!-- Voice Agent -->
    <item reason="Latency budget">NEVER use the 1.7B Qwen3-TTS model in the voice agent — use the 0.6B fast adapter for real-time conversation</item>
    <item reason="Model confusion">NEVER share TTS model instances between ClipCannon and voice agent — they use different model sizes and configurations</item>
    <item reason="Blocking">NEVER run synchronous model inference on the voice agent event loop — use async adapters</item>

    <!-- Security -->
    <item reason="Security">NEVER hardcode API keys, secrets, tokens, or credentials in source files — use environment variables</item>
    <item reason="Security">NEVER log sensitive data (tokens, passwords, credit card numbers)</item>
    <item reason="Security">NEVER commit .env files or files containing secrets to version control</item>

    <!-- Code Quality -->
    <item reason="Maintainability">NEVER use magic numbers — define named constants (SCENE_THRESHOLD = 0.75, SAMPLE_RATE = 44100)</item>
    <item reason="Type safety">NEVER use 'Any' type annotation — use specific types, Union, or Optional</item>
    <item reason="Architecture">NEVER call model inference directly from MCP tools — tools call pipeline stages or service functions</item>
    <item reason="Architecture">NEVER write raw SQL in MCP tools — use query helpers from db/queries.py</item>
    <item reason="Architecture">NEVER construct FFmpeg commands as raw strings — use the builder functions in ffmpeg_cmd.py</item>
    <item reason="Concurrency">NEVER run synchronous model inference on the async event loop — use run_in_executor</item>
    <item reason="File size">NEVER let a single file exceed 500 lines — split into sub-modules</item>
  </forbidden>
</anti_patterns>

<!-- ============================================================ -->
<!-- SECURITY REQUIREMENTS                                         -->
<!-- ============================================================ -->
<security_requirements>
  <rule id="SEC-01">ALL processing is local — no video data, transcripts, or embeddings leave the machine</rule>
  <rule id="SEC-02">Source video files are NEVER modified — read-only access enforced</rule>
  <rule id="SEC-03">Dashboard session tokens: HTTP-only cookies, 30-day TTL, JWT with HS256</rule>
  <rule id="SEC-04">HMAC-SHA256 balance integrity — tampered balance = immediate fatal exit with logged alert</rule>
  <rule id="SEC-05">Stripe webhook signature verification required — reject unsigned webhook calls</rule>
  <rule id="SEC-06">Profanity words are REDACTED in all MCP tool responses — stored in DB but shown as [REDACTED]</rule>
  <rule id="SEC-07">File path inputs validated and sanitized — prevent directory traversal in all MCP tools accepting paths</rule>
  <rule id="SEC-08">Machine ID derived from hardware characteristics — not user-configurable, not stored in plaintext</rule>
  <rule id="SEC-09">Provenance chain hashes detect any unauthorized modification of pipeline outputs</rule>
</security_requirements>

<!-- ============================================================ -->
<!-- PERFORMANCE BUDGETS                                           -->
<!-- ============================================================ -->
<performance_budgets>
  <!-- Pipeline Performance (RTX 5090 targets) -->
  <metric name="ingestion_1hr_1080p" target="< 5 minutes" gpu="RTX 5090">Full 22-stage pipeline for 1-hour 1080p source</metric>
  <metric name="ingestion_1hr_4090" target="< 8 minutes" gpu="RTX 4090">Same on RTX 4090 (INT8)</metric>
  <metric name="render_per_clip" target="< 30 seconds">Single clip render including audio + animations</metric>
  <metric name="music_gen_per_minute" target="< 5 seconds">ACE-Step music generation per minute of output</metric>
  <metric name="sfx_gen_per_effect" target="< 100 milliseconds">DSP sound effect generation</metric>
  <metric name="tts_per_sentence" target="< 10 seconds">Qwen3-TTS synthesis per sentence (including verification)</metric>
  <metric name="enhance_per_clip" target="< 15 seconds">Resemble Enhance post-processing per TTS clip</metric>

  <!-- Voice Agent Performance -->
  <metric name="voice_agent_ttfb" target="< 500 milliseconds">Time to first audio byte from faster-qwen3-tts 0.6B</metric>
  <metric name="voice_agent_llm_latency" target="< 2 seconds">Qwen3-14B-FP8 response generation (max 150 tokens)</metric>
  <metric name="voice_agent_asr_latency" target="< 300 milliseconds">Streaming ASR transcription latency</metric>
  <metric name="voice_agent_endpoint_silence" target="600 milliseconds">VAD silence threshold for turn-end detection</metric>

  <!-- Accuracy -->
  <metric name="transcript_wer" target="< 5%">Word Error Rate on English content</metric>
  <metric name="word_timestamp_precision" target="< 50ms drift">WhisperX wav2vec2 forced alignment precision</metric>
  <metric name="scene_detection_recall" target="> 90%">Scene boundary detection completeness</metric>
  <metric name="caption_sync" target="< 100ms drift">Caption display timing accuracy</metric>
  <metric name="voice_clone_secs" target="> 0.85">Speaker Embedding Cosine Similarity for cloned voice</metric>

  <!-- MCP Response -->
  <metric name="mcp_response_size" target="< 25,000 tokens">Every MCP tool response</metric>
  <metric name="editing_context_size" target="~20,000 tokens">clipcannon_get_editing_context response</metric>
  <metric name="transcript_page_size" target="~12,000 tokens">clipcannon_get_transcript per 15-min page</metric>

  <!-- Database -->
  <metric name="sqlite_vec_knn" target="< 15 milliseconds">KNN search on 28,000 vectors</metric>
  <metric name="db_query_p95" target="< 50 milliseconds">95th percentile for standard queries</metric>

  <!-- Resource -->
  <metric name="vram_peak_5090" target="< 12 GB">Peak VRAM during understanding pipeline (NVFP4)</metric>
  <metric name="vram_peak_4090" target="< 22 GB">Peak VRAM during understanding pipeline (INT8)</metric>
  <metric name="human_review_time" target="< 2 minutes">Per clip batch in dashboard</metric>
</performance_budgets>

<!-- ============================================================ -->
<!-- TESTING REQUIREMENTS                                          -->
<!-- ============================================================ -->
<testing_requirements>

  <coverage_minimum>80% line coverage for src/clipcannon/ and src/voiceagent/ (excluding dashboard templates)</coverage_minimum>

  <required_tests>
    <test_type scope="pipeline">Test for every pipeline stage — use real video for required stages, synthetic data for derived stages</test_type>
    <test_type scope="provenance">Test hash computation, chain verification, and tamper detection with real chain records</test_type>
    <test_type scope="billing">Test credit charge, refund, insufficient balance, HMAC sign/verify/tamper, idempotency keys</test_type>
    <test_type scope="mcp_tools">Test every MCP tool — verify response format, error handling, DB state after operation</test_type>
    <test_type scope="db">Test schema creation, query helpers, sqlite-vec vector operations (correct + wrong dimensions)</test_type>
    <test_type scope="editing">Test iterative editing: create, modify, version history, revert, branching, feedback application</test_type>
    <test_type scope="voice">Test multi-gate verification (sanity, WER, SECS), speaker encoder embedding dimensions, profile CRUD</test_type>
    <test_type scope="integration">Integration test: real video through full pipeline → verify every DB table + file on disk</test_type>
    <test_type scope="integration">Integration test: billing workflow — charge → process → verify OR charge → fail → refund</test_type>
    <test_type scope="voice_agent">Test voice agent subsystem: agent lifecycle, ASR streaming, TTS streaming, conversation state, wake word, transports</test_type>
    <test_type scope="voice_agent">Test adapters independently: fast_tts (0.6B) and clipcannon (1.7B) must not share state</test_type>
    <test_type scope="performance">Benchmark: pipeline time, VRAM peak, MCP response sizes, sqlite-vec search time</test_type>
  </required_tests>

  <test_data_policy>
    <rule>NO mock data — use real video files or synthetic data (PIL-generated frames, programmatic DB inserts)</rule>
    <rule>NO mock.patch on core logic — only mock external services (Stripe, Cloudflare D1) and unavailable ML models</rule>
    <rule>Tests must verify Sources of Truth directly — open the database with raw sqlite3 or check files with os.path.exists</rule>
    <rule>Do NOT rely solely on function return values — independently verify the side effects (DB rows, files, HMAC state)</rule>
    <rule>For edge cases, print BEFORE and AFTER state to prove the outcome</rule>
  </test_data_policy>

  <fixture_optimization>
    <rule id="TEST-OPT-01">NEVER re-run FFmpeg operations in function-scoped fixtures — use module scope for probe, audio extract, frame extract</rule>
    <rule id="TEST-OPT-02">NEVER reload ML models between tests — load once per module or session, share across tests</rule>
    <rule id="TEST-OPT-03">Use module-scoped fixtures for any operation taking more than 1 second</rule>
    <rule id="TEST-OPT-04">Use function-scoped fixtures only for lightweight setup (empty DB creation, synthetic data insertion)</rule>
    <rule id="TEST-OPT-05">Create PIL Images programmatically instead of extracting real frames when testing non-FFmpeg logic</rule>
    <rule id="TEST-OPT-06">Share DB state across tests in the same module when tests are read-only (assertions only, no mutations)</rule>
    <rule id="TEST-OPT-07">Use tmp_path_factory.mktemp() in module-scoped fixtures (not tmp_path which is function-scoped)</rule>
    <rule id="TEST-OPT-08">Chain expensive fixtures: probed_project → audio_extracted_project → frames_extracted_project — each runs once, downstream tests share the result</rule>
  </fixture_optimization>

  <fixture_scope_guide>
    <scope name="session">ML model loading, GPU initialization — load once for entire test run</scope>
    <scope name="module">FFmpeg operations (probe, audio extract, frame extract), full pipeline runs — shared by all tests in one file</scope>
    <scope name="function">Fresh databases, synthetic data, isolated mutation tests — each test gets its own</scope>
  </fixture_scope_guide>

  <test_patterns>
    <rule>Tests ship WITH implementation, not as separate tasks</rule>
    <rule>Use pytest as test runner with pytest-asyncio (asyncio_mode = "auto")</rule>
    <rule>MCP tool tests must assert response format matches spec (error codes, JSON structure)</rule>
    <rule>Provenance tests must include tamper-then-verify scenarios (modify field → verify_chain detects exact record)</rule>
    <rule>Billing tests must verify physical DB state after every charge/refund (not just API response)</rule>
    <rule>Pipeline stage tests must verify: StageResult.success, provenance record written, DB rows inserted, files created</rule>
    <rule>Voice tests must verify speaker embedding dimensions (2048) and SECS threshold behavior</rule>
    <rule>Break monolithic test methods into focused assertions — one test per verification concern</rule>
  </test_patterns>

</testing_requirements>

</constitution>
```
