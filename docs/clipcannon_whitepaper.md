# ClipCannon: A Multi-Modal Embedding Architecture for AI-Driven Video Understanding, Editing, and Voice Synthesis

**Version 0.1.0 -- Technical White Paper**
**March 2026**

---

## Abstract

ClipCannon is an AI-powered video understanding, editing, rendering, and voice synthesis pipeline that ingests raw video footage and transforms it into platform-optimized clips through a 22-stage directed acyclic graph (DAG) analysis pipeline. The system employs eight distinct embedding models across four perceptual modalities -- visual, linguistic, acoustic, and speaker identity -- to construct a dense, queryable representation of video content. These embeddings are stored in a per-project SQLite database augmented with the `sqlite-vec` extension for sub-linear nearest-neighbor search, enabling an AI assistant to discover semantically meaningful moments, detect natural edit boundaries, and compose edits with cross-stream intelligence. A separate real-time Voice Agent subsystem extends the architecture with a ninth embedding model for speaker verification during voice cloning. This paper describes the complete system architecture, details each embedding model and its role in the pipeline, explains how embeddings interact during discovery and editing, and documents the provenance, billing, and rendering subsystems that make ClipCannon a production-grade tool for AI-assisted video production.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Architecture](#2-system-architecture)
3. [The 22-Stage Analysis Pipeline](#3-the-22-stage-analysis-pipeline)
4. [Multi-Modal Embedding Architecture](#4-multi-modal-embedding-architecture)
   - 4.1 Visual Embeddings (SigLIP)
   - 4.2 Semantic Embeddings (Nomic Embed)
   - 4.3 Emotion Embeddings (Wav2Vec2)
   - 4.4 Speaker Embeddings (WavLM)
   - 4.5 Voice Identity Embeddings (Qwen3-TTS ECAPA-TDNN)
5. [Vector Storage and Retrieval](#5-vector-storage-and-retrieval)
6. [Cross-Stream Intelligence](#6-cross-stream-intelligence)
7. [Narrative Analysis via Large Language Model](#7-narrative-analysis-via-large-language-model)
8. [Scene Analysis and Layout Computation](#8-scene-analysis-and-layout-computation)
9. [The Editing Engine](#9-the-editing-engine)
10. [The Rendering Engine](#10-the-rendering-engine)
11. [The Audio Engine](#11-the-audio-engine)
12. [The Voice Engine](#12-the-voice-engine)
13. [The Avatar Engine](#13-the-avatar-engine)
14. [The Voice Agent](#14-the-voice-agent)
15. [Provenance and Data Integrity](#15-provenance-and-data-integrity)
16. [Billing and Credit System](#16-billing-and-credit-system)
17. [GPU Management and Resource Optimization](#17-gpu-management-and-resource-optimization)
18. [MCP Protocol Integration](#18-mcp-protocol-integration)
19. [Database Architecture](#19-database-architecture)
20. [Testing and Verification](#20-testing-and-verification)
21. [Graceful Degradation](#21-graceful-degradation)
22. [Conclusion](#22-conclusion)
23. [Appendix A: Model Summary Table](#appendix-a-model-summary-table)
24. [Appendix B: Embedding Dimension Reference](#appendix-b-embedding-dimension-reference)

---

## 1. Introduction

The explosion of short-form video content across platforms such as TikTok, Instagram Reels, YouTube Shorts, and LinkedIn has created an acute demand for tools that can rapidly analyze long-form source footage and extract platform-optimized clips. Traditional video editing requires manual scrubbing, subjective judgment about "interesting moments," and significant technical skill in encoding, aspect ratio management, and caption placement. ClipCannon addresses these challenges by constructing a rich, multi-modal understanding of video content through neural embeddings and then exposing that understanding to AI assistants via the Model Context Protocol (MCP).

The central insight behind ClipCannon is that video is inherently multi-modal: a single frame carries visual semantics, the audio track conveys emotion and speaker identity, the transcript carries linguistic meaning, and the temporal structure of these signals reveals narrative flow. By embedding each modality into a separate vector space and storing these embeddings alongside structured metadata in a per-project database, ClipCannon enables an AI assistant to perform cross-modal queries -- for example, finding moments where emotional intensity peaks coincide with topic transitions and natural audio boundaries.

ClipCannon operates as three coordinated processes -- an MCP server exposing 51 tools, a license server managing credit-based billing, and a web dashboard for project oversight -- plus an optional real-time Voice Agent for conversational interaction. The entire system runs locally, with no cloud API dependencies for core functionality. All ML models execute on the user's GPU, and all data remains on-premises in SQLite databases.

---

## 2. System Architecture

ClipCannon is composed of four independent processes:

| Process | Port / Transport | Technology | Purpose |
|---------|-----------------|------------|---------|
| MCP Server | stdio (or SSE 3366) | `mcp` SDK + Python asyncio | 51 tools for AI assistants |
| License Server | 3100 | FastAPI + Uvicorn | Credit billing with HMAC integrity |
| Dashboard | 3200 | FastAPI + static HTML | Web UI for projects, credits, provenance |
| Voice Agent | 8765 (WS) or local mic | Pipecat + PyAudio | Real-time conversational AI |

The MCP server is the primary interface. An AI assistant (such as Claude) connects via stdio transport and invokes tools to create projects, analyze video, discover moments, compose edits, render clips, synthesize voice, and generate lip-synced avatars. The server is stateless; all persistent state lives in per-project SQLite databases under `~/.clipcannon/projects/{project_id}/analysis.db`.

### 2.1 Source Code Organization

```
src/
  clipcannon/          # Core package (included in wheel)
    pipeline/          # 22-stage analysis DAG
    editing/           # EDL engine, captions, smart crop, motion, overlays
    rendering/         # FFmpeg-based async rendering with 7 platform profiles
    audio/             # AI music, MIDI, DSP SFX, mixing, cleanup
    voice/             # Voice cloning: data prep, synthesis, verification, enhancement
    avatar/            # LatentSync lip-sync diffusion
    tools/             # 51 MCP tool definitions and dispatchers
    db/                # SQLite connection factory, schema, queries
    gpu/               # Precision detection, LRU model manager
    provenance/        # SHA-256 hash chain, tamper detection
    billing/           # HMAC-signed credits, license client
    dashboard/         # FastAPI web UI with 7 route groups
  license_server/      # Credit billing FastAPI service
  voiceagent/          # Standalone real-time voice assistant
```

### 2.2 Technology Stack

The system is built on Python >= 3.12 with Pydantic >= 2.0 for data validation, SQLite for storage (with `sqlite-vec` for vector KNN), and PyTorch >= 2.3.0 for GPU inference. Video processing uses FFmpeg via async subprocess invocations, with NVENC hardware acceleration where available and automatic software fallback.

---

## 3. The 22-Stage Analysis Pipeline

When a user invokes `clipcannon_ingest`, ClipCannon executes a directed acyclic graph (DAG) of 22 pipeline stages. The DAG is topologically sorted using Kahn's algorithm, producing execution levels where stages within a level share no mutual dependencies and execute concurrently via `asyncio.gather()`.

### 3.1 DAG Topology

```
Level 0: probe
Level 1: vfr_normalize                              -> probe
Level 2: audio_extract, frame_extract               -> vfr_normalize
Level 3: source_separation, visual_embed, ocr,      -> audio_extract / frame_extract
         quality, storyboard, transcribe, acoustic
Level 4: shot_type, scene_analysis, semantic_embed,  -> frame_extract, visual_embed,
         narrative_llm, speaker_embed,                  transcribe, audio_extract
         emotion_embed, reactions, profanity
Level 5: chronemic                                   -> transcribe, speaker_embed
Level 6: highlights                                  -> 7 upstream stages
Level 7: finalize                                    -> 15 upstream stages
```

### 3.2 Required vs. Optional Stages

Six stages are required -- failure of any required stage aborts the pipeline:

1. **probe** -- FFprobe metadata extraction, VFR detection, SHA-256 hashing
2. **vfr_normalize** -- Variable-to-constant frame rate conversion via FFmpeg
3. **audio_extract** -- Extracts 16kHz mono (for speech models) and native-rate audio
4. **frame_extract** -- Extracts JPEG frames at configurable FPS (default 2)
5. **transcribe** -- Speech-to-text with word-level timestamps
6. **finalize** -- Status reconciliation, provenance verification, cleanup

The remaining 16 stages are optional. They employ graceful degradation: if an optional stage fails, downstream stages check the dependency status and either use fallback data or skip gracefully. The project is still marked as "ready" provided the provenance chain verifies.

### 3.3 Audio Source Resolution

A shared utility, `resolve_audio_input()`, provides cascading audio path selection. If source separation produced a `vocals.wav` stem (isolating speech from background music), downstream audio stages prefer it. If source separation failed or was not run, stages fall back to `audio_16k.wav`. This ensures the pipeline completes even without GPU-intensive source separation.

---

## 4. Multi-Modal Embedding Architecture

ClipCannon's analytical power derives from its use of multiple specialized embedding models, each trained for a distinct perceptual modality. These models transform raw sensory data -- pixels, audio waveforms, text -- into dense vector representations in learned metric spaces where semantic similarity corresponds to geometric proximity.

The system employs **nine distinct embedding models** across five embedding spaces:

### 4.1 Visual Embeddings -- SigLIP-SO400M (1152 dimensions)

**Model**: `google/siglip-so400m-patch14-384` (Google)
**Dimension**: 1152 (float32)
**Storage**: `vec_frames` virtual table (sqlite-vec)
**Pipeline Stage**: `visual_embed` (Level 3)
**Input**: Extracted JPEG frames at configured FPS

SigLIP (Sigmoid Language-Image Pre-training) is a vision-language model trained with a sigmoid loss function on image-text pairs. Unlike CLIP's contrastive softmax loss, SigLIP's sigmoid formulation enables each image-text pair to be treated as an independent binary classification, improving scalability and visual grounding quality.

**Processing Pipeline**:

1. Frames are loaded and preprocessed to 384x384 resolution via the SigLIP processor.
2. The vision encoder produces 1152-dimensional embeddings per frame.
3. Embeddings are L2-normalized for cosine similarity computation.
4. Frames are processed in configurable batches (default 64) for GPU efficiency.
5. Embeddings are inserted into the `vec_frames` sqlite-vec table with frame path, timestamp, and project ID metadata.

**Scene Detection**: After embedding all frames, the system computes pairwise cosine similarities between consecutive frame embeddings. A new scene boundary is detected when similarity drops below a configurable threshold (default 0.75). This approach detects semantic scene changes rather than just visual discontinuities -- a gradual topic shift in a single-camera interview is detected because the visual content (gestures, props, expressions) changes semantically even when the camera angle remains constant.

**Dual Use for Shot Classification**: The same SigLIP model is reused in the `shot_type` stage (Level 4) for zero-shot image-text classification. Each scene's key frame is compared against five text prompts describing shot types (extreme close-up, close-up, medium, wide, establishing), and the highest-similarity label is assigned. This eliminates the need for a separate shot classification model while leveraging SigLIP's strong vision-language alignment.

**Color Extraction**: For each detected scene, the system also extracts dominant colors via PIL's median-cut quantization algorithm on a 64x64 thumbnail, producing the top 5 hex color values for visual metadata.

### 4.2 Semantic Embeddings -- Nomic Embed Text v1.5 (768 dimensions)

**Model**: `nomic-ai/nomic-embed-text-v1.5` (Nomic AI)
**Dimension**: 768 (float32)
**Storage**: `vec_semantic` virtual table (sqlite-vec)
**Pipeline Stage**: `semantic_embed` (Level 4)
**Input**: Transcript segments from the `transcript_segments` table

Nomic Embed is a text embedding model designed for semantic search and retrieval. It produces high-quality sentence embeddings that cluster semantically related content in vector space.

**Processing Pipeline**:

1. Transcript segments are prefixed with `"search_document: "` (Nomic's recommended prefix for document encoding) to align with the model's training distribution.
2. Segments are batch-encoded via `sentence-transformers.SentenceTransformer`, producing 768-dimensional L2-normalized embeddings.
3. Embeddings are inserted into the `vec_semantic` sqlite-vec table with segment ID, timestamp, and transcript text.

**Topic Clustering**: After embedding all segments, the system performs agglomerative clustering with:
- Distance threshold: 1.2
- Metric: cosine
- Linkage: average

For each discovered topic cluster, the system computes:
- **Keywords**: Top-5 words by frequency (after stop-word removal)
- **Coherence**: Average pairwise cosine similarity within the cluster
- **Semantic density**: `1 / (1 + mean_distance_from_centroid)`, measuring how tightly the cluster's segments relate to each other

These topic records are stored in the `topics` table and directly feed the highlight scoring system, where semantic density is weighted at 0.20 in the composite score.

**Semantic Search**: The `clipcannon_search_content` MCP tool uses the `vec_semantic` table for KNN nearest-neighbor search. User queries are embedded with the `"search_query: "` prefix and compared against stored segment embeddings, enabling natural-language search across video content (e.g., "find where they talk about authentication").

### 4.3 Emotion Embeddings -- Wav2Vec2 (1024 dimensions)

**Model**: `facebook/wav2vec2-large-960h` (Meta/Facebook)
**Dimension**: 1024 (float32)
**Storage**: `vec_emotion` virtual table (sqlite-vec)
**Pipeline Stage**: `emotion_embed` (Level 4)
**Input**: Audio waveform (16kHz mono, from vocals.wav or audio_16k.wav)

Wav2Vec2 is a self-supervised speech representation model originally trained for automatic speech recognition. ClipCannon repurposes its latent representations as a proxy for emotional content, exploiting the fact that Wav2Vec2's hidden states encode prosodic features (pitch contour, energy dynamics, speaking rate variations) that correlate with emotional expression.

**Processing Pipeline**:

1. Audio is loaded and resampled to 16kHz mono.
2. The waveform is segmented into 5-second windows with 2.5-second stride (50% overlap).
3. Each window is processed through Wav2Vec2's encoder.
4. From the last hidden state (shape: `[1, T, 1024]`), three scalar signals are derived:
   - **Energy**: `RMS / (RMS + 1)` -- normalized root-mean-square amplitude, range [0, 1]
   - **Arousal**: `variance / (variance + 1)` -- temporal variability of the hidden state, range [0, 1]
   - **Valence**: `0.5 + mean / (|mean| + 2)` -- directional bias of the representation, range [0, 1]
5. The full 1024-dimensional mean-pooled hidden state is stored as the emotion embedding.
6. Scalar signals are inserted into the `emotion_curve` table; embeddings into `vec_emotion`.

**Fallback Mechanism**: If Wav2Vec2 fails to load (insufficient VRAM, missing dependencies), the system falls back to raw audio RMS analysis:
- Energy: `rms * 5.0`, clipped to [0, 1]
- Arousal: Sub-window energy variance
- Valence: Fixed at 0.5
- Embedding: 1024-dimensional zero vector

This ensures the emotion curve is always populated, even without the ML model, preserving downstream highlight scoring at reduced fidelity.

### 4.4 Speaker Embeddings -- WavLM (512 dimensions)

**Model**: `microsoft/wavlm-base-plus-sv` (Microsoft)
**Dimension**: 512 (float32)
**Storage**: `vec_speakers` virtual table (sqlite-vec)
**Pipeline Stage**: `speaker_embed` (Level 4)
**Input**: Audio waveform + transcript segments from database

WavLM (Wave Language Model) is a self-supervised speech representation model fine-tuned for speaker verification. Its embeddings capture speaker-discriminative characteristics -- vocal timbre, fundamental frequency, formant structure -- enabling speaker diarization through clustering.

**Processing Pipeline**:

1. Audio is loaded and resampled to 16kHz mono.
2. **Voice Activity Detection**: Silero VAD identifies speech segments, filtering out silence and background noise. If Silero is unavailable, an energy-threshold detector provides a fallback.
3. Each speech segment is processed through WavLM. The last hidden state is mean-pooled across time, L2-normalized, and truncated/padded to exactly 512 dimensions.
4. **Speaker Clustering**: Agglomerative clustering with `distance_threshold=0.7`, `metric="cosine"`, `linkage="average"` groups segments by speaker identity.
5. Speaker records are created in the `speakers` table with labels (`speaker_0`, `speaker_1`, ...), total speaking time, and speaking percentage.
6. Transcript segments and words are updated with assigned `speaker_id` values via max-overlap matching between VAD speech segments and transcript time ranges.
7. Speaker embeddings are stored in `vec_speakers` for subsequent similarity queries.

**Diarization Strategy**: Rather than traditional diarization (which requires a known number of speakers), ClipCannon uses agglomerative clustering with a cosine distance threshold, allowing automatic discovery of an arbitrary number of speakers. The distance threshold of 0.7 was tuned to balance between over-segmentation (splitting one speaker into multiples) and under-segmentation (merging different speakers).

**Fallback**: If WavLM fails entirely, all transcript segments are assigned to a single `speaker_0` via `_insert_fallback_speaker()`, ensuring downstream stages (chronemic analysis, highlight scoring) can still execute.

### 4.5 Voice Identity Embeddings -- Qwen3-TTS ECAPA-TDNN (2048 dimensions)

**Model**: `marksverdhei/Qwen3-Voice-Embedding-12Hz-1.7B` (ECAPA-TDNN speaker encoder)
**Dimension**: 2048 (float32)
**Storage**: `voice_profiles` table (in `~/.clipcannon/voice_profiles.db`)
**Usage Context**: Voice cloning verification (Phase 3) and Voice Agent identity matching

This is the highest-dimensional embedding in the system, designed specifically for speaker verification in the context of voice cloning. The ECAPA-TDNN (Emphasized Channel Attention, Propagation and Aggregation with Time Delay Neural Network) architecture is purpose-built for extracting speaker-discriminative features.

**Role in Voice Cloning**:

1. **Profile Creation**: When a voice profile is created, the system computes a 2048-dimensional reference embedding from the speaker's training audio clips. This embedding is stored as a BLOB in the `voice_profiles` table.
2. **Synthesis Verification**: During voice synthesis (`clipcannon_speak`), each generated audio candidate is embedded using the same ECAPA-TDNN model. The cosine similarity between the candidate's embedding and the reference profile embedding determines identity fidelity.
3. **Multi-Gate Verification**: The voice verification pipeline applies three sequential gates:
   - **Sanity Gate**: Duration check, clipping detection, SNR measurement, silence ratio
   - **Intelligibility Gate**: Word Error Rate (WER) via Whisper transcription, punctuation-normalized comparison
   - **Identity Gate**: Speaker Embedding Cosine Similarity (SECS) against the reference embedding, with a configurable threshold (default 0.80)
4. **SECS-Optimized Synthesis**: The `clipcannon_speak_optimized` tool generates N candidates (default 8), scores each by SECS against the reference, and returns the best match.

**Relationship to Pipeline Embeddings**: While the four pipeline embedding spaces (visual, semantic, emotion, speaker) operate on video content during analysis, the voice identity embedding operates on synthesized audio during production. The pipeline's WavLM speaker embeddings (512-dim) identify who is speaking in the source video; the ECAPA-TDNN embeddings (2048-dim) verify that synthesized speech sounds like the target speaker. These are complementary but distinct tasks -- diarization vs. verification -- hence the different models and dimensionalities.

### 4.6 Supporting Models (Non-Embedding)

Beyond the five embedding models, ClipCannon employs additional ML models that do not produce stored embeddings but are critical to the pipeline:

| Model | Purpose | Stage |
|-------|---------|-------|
| HTDemucs v4 (Meta) | Audio source separation into vocals/music/drums/bass stems | `source_separation` |
| WhisperX + wav2vec2 alignment | Speech-to-text with 20-50ms word-level precision | `transcribe` |
| PaddleOCR PP-OCRv5 | On-screen text detection | `ocr` |
| pyiqa BRISQUE | Frame quality assessment | `quality` |
| SenseVoice Small (FunASR) | Reaction detection (laughter, applause) | `reactions` |
| Qwen3-8B (Qwen) | Narrative structure analysis | `narrative_llm` |
| Qwen3-TTS 1.7B (Qwen) | Voice synthesis for video production | `speak` tool |
| Qwen3-TTS 0.6B (faster-qwen3-tts) | Real-time voice synthesis for Voice Agent | Voice Agent TTS |
| ACE-Step v1.5 | AI music generation via diffusion | `generate_music` tool |
| LatentSync 1.6 (ByteDance) | Lip-sync video diffusion | `lip_sync` tool |
| Silero VAD | Voice activity detection | `speaker_embed`, Voice Agent |
| OpenCV Haar Cascades / MediaPipe | Face detection for scene analysis and smart crop | `scene_analysis`, `smart_crop` |
| openWakeWord | "Hey Jarvis" wake word detection | Voice Agent activation |

---

## 5. Vector Storage and Retrieval

ClipCannon uses `sqlite-vec`, a SQLite extension that provides `vec0` virtual tables for approximate nearest-neighbor (ANN) search. Four vector tables are created per project:

| Table | Dimension | Source Model | Content |
|-------|-----------|-------------|---------|
| `vec_frames` | float[1152] | SigLIP-SO400M | One embedding per extracted frame |
| `vec_semantic` | float[768] | Nomic Embed v1.5 | One embedding per transcript segment |
| `vec_emotion` | float[1024] | Wav2Vec2 | One embedding per 5-second audio window |
| `vec_speakers` | float[512] | WavLM | One embedding per speech segment |

### 5.1 Query Patterns

The primary query interface is the `clipcannon_search_content` MCP tool, which supports two modes:

1. **Semantic Search**: The query text is embedded using Nomic Embed (with `"search_query: "` prefix) and compared against `vec_semantic` using sqlite-vec's KNN operator. This returns transcript segments ranked by cosine similarity to the query.

2. **Text Match Fallback**: If sqlite-vec is unavailable (the extension is optional), the system falls back to SQL `LIKE` queries against the `transcript_segments.text` column.

### 5.2 Cross-Modal Retrieval

While the vector tables are queried independently, the results are joined with temporal metadata to enable cross-modal analysis. For example, the `clipcannon_get_frame` tool returns not just the frame image but also the concurrent transcript text, speaker identity, emotion values, topic, shot type, quality score, pacing label, OCR text, and profanity status -- all retrieved by joining against the frame's timestamp across multiple tables.

---

## 6. Cross-Stream Intelligence

The Discovery Engine (`src/clipcannon/tools/discovery.py`) implements four MCP tools that synthesize signals across all embedding spaces and structured analysis results:

### 6.1 Find Best Moments

`clipcannon_find_best_moments` identifies key moments using **purpose-aware scoring**. The scoring weights shift based on the intended purpose:

| Purpose | Primary Signal | Secondary Signals |
|---------|---------------|-------------------|
| hook | Emotion energy, visual variety | Reactions, pacing |
| highlight | Emotion energy, reactions | Semantic density, quality |
| cta | Speaker confidence, pacing | Semantic density |
| tutorial_step | Semantic density, pacing | OCR presence, quality |

Each moment candidate is scored across all available streams, with weights adjusted by purpose. This is where the embedding architecture provides its greatest value: moments that score highly across multiple modalities (high emotion + audience reaction + topic shift + scene boundary) are ranked above moments that are strong in only one dimension.

### 6.2 Find Cut Points

`clipcannon_find_cut_points` detects natural edit boundaries by computing **convergence scores** across four signal types:

1. **Silence boundaries** -- from `silence_gaps` table (acoustic analysis)
2. **Beat boundaries** -- from `beats` table (beat detection via librosa/scipy)
3. **Scene boundaries** -- from `scenes` table (visual embedding similarity drops)
4. **Sentence boundaries** -- from `transcript_segments` table (end of sentences)

Points where multiple signal types converge (e.g., a silence gap that coincides with a scene boundary and sentence end) receive the highest scores. This approach produces cuts that feel natural across all perceptual channels rather than cutting mid-sentence or mid-beat.

### 6.3 Narrative Flow Analysis

`clipcannon_get_narrative_flow` validates the narrative coherence of a proposed edit before rendering. Given a sequence of segments, it analyzes:

- Temporal ordering and gap detection
- Topic continuity (via semantic embeddings)
- Speaker consistency
- Emotional arc coherence
- Story beat alignment (from Qwen3-8B narrative analysis)

This tool enables the AI assistant to evaluate whether a proposed edit tells a coherent story before committing to the computationally expensive rendering step.

### 6.4 Audio-Safe Cut Points

`clipcannon_find_safe_cuts` identifies cut points where all audio signals are quiet or transitioning, avoiding cuts that produce jarring audio discontinuities.

### 6.5 Highlight Scoring Algorithm

The `highlights` pipeline stage (Level 6) produces the system's most comprehensive cross-stream synthesis. It scores 30-second candidate windows using seven weighted signals:

| Signal | Weight | Source | Computation |
|--------|--------|--------|-------------|
| Emotion energy | 0.25 | `emotion_curve` (Wav2Vec2) | Average energy of overlapping windows |
| Reaction presence | 0.20 | `reactions` (SenseVoice) | Binary: 1.0 if any reaction overlaps |
| Semantic density | 0.20 | `topics` (Nomic Embed) | Average topic coherence in window |
| Narrative | 0.15 | `transcript_segments` | Sentence boundary alignment score |
| Visual variety | 0.10 | `scenes` (SigLIP) | Scene change frequency vs. expected |
| Quality | 0.05 | `scenes` (BRISQUE) | Average frame quality |
| Speaker confidence | 0.05 | `transcript_segments` (WavLM) | Single-speaker dominance score |

The weighted sum produces a composite score that reflects the "interestingness" of each moment from a multi-modal perspective. Highlights are classified by their dominant signal (emotional peak, audience reaction, key topic, visual montage, etc.) and stored in the `highlights` table for use by discovery tools and the AI assistant.

---

## 7. Narrative Analysis via Large Language Model

The `narrative_llm` pipeline stage runs **Qwen3-8B** (Qwen, 8 billion parameters, FP16) after transcription to perform structural analysis of the video's content. Unlike the embedding-based analysis stages, this stage uses a generative language model to reason about narrative structure.

**Inputs**: The full transcript text, concatenated from `transcript_segments`.

**Outputs** (JSON stored in `narrative_analysis` table):
- **Story beats**: Identified narrative turning points with timestamps
- **Open loops**: Questions or tensions raised but not yet resolved, creating audience engagement hooks
- **Chapter boundaries**: Natural thematic divisions of the content
- **Key moments**: The most narratively significant moments for editing
- **Narrative summary**: A condensed textual summary of the content

**Implementation Detail**: The model runs in a subprocess (`HF_HUB_OFFLINE=1`) for clean GPU memory management. This prevents VRAM fragmentation from model co-residency and ensures the 8B-parameter model can load on GPUs that may already have pipeline models resident.

The narrative analysis results feed into the highlight scoring algorithm (narrative signal, weight 0.15) and the narrative flow validation tool, providing a higher-order structural understanding that pure embedding similarity cannot capture.

---

## 8. Scene Analysis and Layout Computation

The `scene_analysis` pipeline stage provides content-aware spatial intelligence for the editing engine.

### 8.1 Scene Boundary Detection

Using SSIM (Structural Similarity Index Measure) comparison between consecutive frames, the system detects visual scene boundaries. A maximum scene duration of 8 seconds is enforced to prevent excessively long scenes in static content.

### 8.2 Spatial Region Detection

For each scene, OpenCV-based analysis identifies:

- **Face positions**: Bounding boxes of detected faces (Haar cascades or MediaPipe)
- **Webcam overlay regions**: Small face-containing rectangles in typical webcam positions (screen corners), common in screen-recording content
- **Content areas**: The main content region, excluding browser chrome (top 70px) and OS taskbar (bottom 50px)
- **Content type classification**: code, slides, browser, terminal, or unknown -- based on detected text patterns and layout

### 8.3 Pre-Computed Canvas Regions

For each scene, the system pre-computes canvas regions for four standard layout types on a 1080x1920 (9:16) canvas:

| Layout | Description | Speaker Region | Content Region |
|--------|-------------|----------------|----------------|
| A | 30/70 vertical split | 576px top | 1344px bottom |
| B | 40/60 vertical split | 768px top | 1152px bottom |
| C | Picture-in-Picture | 240px circle overlay at (24, 140) | Full canvas |
| D | Full-screen face | Full canvas | N/A |

These pre-computed regions are stored as JSON in the `scene_map` table's `canvas_regions_json` column, enabling the AI assistant to create edits with precise canvas compositing without manual coordinate measurement.

---

## 9. The Editing Engine

The editing engine implements a declarative **Edit Decision List (EDL)** architecture, fully described by Pydantic models.

### 9.1 EDL Structure

An `EditDecisionList` specifies:
- **Segments**: Time ranges from the source video, with speed adjustments (0.25x-4.0x) and per-segment canvas overrides
- **Captions**: Adaptive caption chunking (max 3 words, speech-rate-aware, 4 ASS styles)
- **Crop**: Smart cropping with face tracking, split-screen, PIP, or canvas compositing
- **Canvas**: Multi-region compositing with z-index ordering, fit modes, opacity, and animated zoom
- **Audio**: Source volume, background music mixing, speech-aware ducking, sound effects
- **Transitions**: 10 transition types mapped to FFmpeg xfade filters
- **Overlays**: Lower thirds, title cards, logos, watermarks, CTAs with animation
- **Color**: Brightness, contrast, saturation, gamma, hue shift (global or per-segment)
- **Motion**: Zoom, pan, Ken Burns effects with configurable easing

### 9.2 Iterative Editing Workflow

ClipCannon is designed for iterative refinement, not one-shot generation:

1. **Create**: `clipcannon_create_edit` builds an EDL from segment specifications
2. **Modify**: `clipcannon_modify_edit` applies deep-merge changes with automatic version history
3. **Feedback**: `clipcannon_apply_feedback` parses natural language (e.g., "make it shorter", "cut the intro") into structured EDL changes
4. **Branch**: `clipcannon_branch_edit` forks platform-specific variants (e.g., TikTok -> Instagram)
5. **Revert**: `clipcannon_revert_edit` restores previous versions from the version chain
6. **Preview**: `clipcannon_preview_clip` renders 2-5 second 540p previews without consuming credits

Every modification auto-saves the previous state to the `edit_versions` table, creating a complete version history chain.

### 9.3 Caption Generation

The caption engine performs adaptive chunking of transcript words:
- Maximum 3 words per caption chunk
- Breaks at sentence punctuation and commas
- Adapts to speech rate: fast speech (>200 WPM) reduces words per chunk; slow speech (<80 WPM) increases them
- Merges chunks separated by gaps < 200ms
- Generates ASS subtitle files with four visual styles: bold centered, word highlight, subtitle bar, and karaoke

---

## 10. The Rendering Engine

The rendering engine translates EDL specifications into platform-optimized video files through an async FFmpeg pipeline.

### 10.1 Pipeline Steps

1. **Source validation**: SHA-256 verification, generation-loss prevention (blocks re-rendering of rendered output)
2. **Profile resolution**: One of 7 encoding profiles selected by target platform
3. **Caption writing**: ASS subtitle file generation
4. **Crop computation**: Face-tracking crop regions, smoothed via EMA across scenes
5. **FFmpeg execution**: Async subprocess with dynamic filter graph construction
6. **Thumbnail generation**: JPEG frame extraction at the optimal timestamp
7. **Provenance recording**: Hash chain linking the output to its source
8. **Database update**: Render metadata stored in the `renders` table

### 10.2 Encoding Profiles

| Profile | Resolution | Bitrate | Aspect | Use Case |
|---------|-----------|---------|--------|----------|
| tiktok_vertical | 1080x1920 | 8 Mbps | 9:16 | TikTok |
| instagram_reels | 1080x1920 | 6 Mbps | 9:16 | Instagram Reels |
| youtube_shorts | 1080x1920 | 8 Mbps | 9:16 | YouTube Shorts |
| youtube_standard | 1920x1080 | 12 Mbps | 16:9 | YouTube long-form |
| youtube_4k | 3840x2160 | 40 Mbps | 16:9 | YouTube 4K |
| facebook | 1080x1920 | 6 Mbps | 9:16 | Facebook Reels |
| linkedin | 1080x1080 | 5 Mbps | 1:1 | LinkedIn |

All profiles use `h264_nvenc` (NVENC hardware encoder) with automatic fallback to `libx264` software encoding.

### 10.3 Segment-Level Caching

The rendering engine computes a deterministic content hash for each segment based on the source SHA-256, segment specification, encoding profile, canvas configuration, color settings, and overlay specifications. Previously rendered segments with identical hashes are served from cache, dramatically reducing re-render time during iterative editing.

---

## 11. The Audio Engine

The audio engine provides three tiers of audio generation plus mixing and cleanup:

### Tier 1: AI Music Generation (ACE-Step v1.5)

GPU-accelerated music diffusion model generating original music from text prompts. Requires 4+ GB VRAM; uses CPU offload on GPUs with < 8 GB. Produces WAV at 44.1 kHz.

### Tier 2: MIDI Composition (FluidSynth)

Six preset chord progressions (ambient pad, upbeat pop, corporate, dramatic, minimal piano, intro jingle) with theory-correct harmonies, multi-track MIDI generation (chords, melody, optional bass, optional drums), and FluidSynth SoundFont rendering.

### Tier 3: DSP Sound Effects (NumPy/SciPy)

Nine programmatic sound effects (whoosh, riser, downer, impact, chime, tick, bass drop, shimmer, stinger) generated via mathematical waveform synthesis. Zero GPU usage.

### Audio Mixing

Speech-aware mixing with automatic ducking: RMS energy analysis in 50ms windows identifies speech regions, and background music is reduced by 6 dB with 200ms attack / 300ms release ramps during speech.

---

## 12. The Voice Engine

The voice engine implements a complete voice cloning pipeline:

### 12.1 Data Preparation

`clipcannon_prepare_voice_data` extracts vocal stems from ingested projects, splits audio at silence boundaries, matches segments with transcript words, performs phonemization, and produces train/validation manifests.

### 12.2 Voice Profile Management

Voice profiles store:
- Profile metadata (name, model path, training status)
- **2048-dimensional ECAPA-TDNN reference embedding** (the speaker's voice fingerprint)
- Verification threshold (default 0.80 cosine similarity)
- Training data provenance (source project IDs, training hours)

### 12.3 Synthesis Pipeline

The `clipcannon_speak` tool uses **Qwen3-TTS 1.7B** for high-quality voice synthesis with an iterative verification loop:

1. **Generate**: Qwen3-TTS produces a speech candidate using Full ICL (In-Context Learning) mode with reference audio
2. **Verify**: Three-gate verification:
   - Sanity: Duration bounds, clipping check, SNR measurement, silence ratio
   - Intelligibility: WER via Whisper transcription (punctuation-stripped comparison)
   - Identity: SECS (Speaker Embedding Cosine Similarity) against reference 2048-dim embedding
3. **Retry or Accept**: If any gate fails, regenerate (up to `max_attempts`, default 5)
4. **Enhance**: Post-process via Resemble Enhance (denoise + latent flow matching upsampling from 24kHz to 44.1kHz broadcast quality)

### 12.4 Optimized Synthesis

`clipcannon_speak_optimized` generates N candidates (default 8), scores each by SECS, and returns the best match. This approach maximizes voice identity fidelity at the cost of N times the inference compute.

### 12.5 Multi-Voice Conversation

`MultiVoiceSynth` enables instant voice swapping for multi-speaker conversation generation. Voice prompts are loaded once per session, and segments are concatenated with configurable inter-speaker pauses.

---

## 13. The Avatar Engine

The avatar engine uses **LatentSync 1.6** (ByteDance), a diffusion-based lip-synchronization model, to generate talking-head videos from audio input and a driver video.

**Architecture**: VAE encoder/decoder + UNet3D + DDIM scheduler
**Output Resolution**: 512x512
**Configurable**: Inference steps (default 20), random seed

The `clipcannon_generate_video` tool chains voice synthesis and lip-sync into a single end-to-end pipeline: text -> Qwen3-TTS -> LatentSync -> lip-synced video.

---

## 14. The Voice Agent

The Voice Agent ("Jarvis") is a standalone real-time conversational AI system with on-demand GPU lifecycle management.

### 14.1 Architecture

```
Activation (CPU only)
  Wake Word ("Hey Jarvis") or Hotkey (Ctrl+Space)
      |
  GPU Loading (~10-20s)
      |
Audio Pipeline (GPU, ~30 GB VRAM)
  Mic -> Silero VAD -> faster-whisper (Large v3)
      -> Qwen3-14B FP8 (local LLM)
      -> faster-qwen3-tts (0.6B, CUDA graphs)
      -> Speaker
```

### 14.2 Lifecycle States

| State | GPU Usage | Trigger |
|-------|-----------|---------|
| DORMANT | Zero (CPU-only wake word) | System startup / dismiss phrase |
| LOADING | Growing (~10-20s) | Wake word or hotkey detected |
| ACTIVE | Full (~30 GB) | All models loaded |
| UNLOADING | Shrinking | "Go to sleep", "goodbye", "dismiss" |

### 14.3 TTS Model Selection

The Voice Agent uses a different TTS model than ClipCannon's voice engine:

| Component | Voice Agent | ClipCannon |
|-----------|-------------|------------|
| Model | faster-qwen3-tts **0.6B** | Qwen3-TTS **1.7B** |
| TTFB | ~500ms | ~2-5s |
| Quality | Good (real-time optimized) | Broadcast (verification loop) |
| CUDA Graphs | Yes (4-5x speedup) | No |
| Use Case | Live conversation | Video voiceover production |

The 0.6B model achieves ~500ms time-to-first-byte through CUDA graph capture, making it suitable for interactive conversation where latency is critical. The 1.7B model produces higher-fidelity output suitable for video production, where quality justifies the additional inference time.

### 14.4 GPU Resource Sharing

The Voice Agent manages VRAM contention with ClipCannon through process-level signal control:
- **Activation**: `pause_gpu_workers()` sends SIGSTOP to ClipCannon GPU processes
- **Deactivation**: `resume_gpu_workers()` sends SIGCONT to restore them
- **Memory cap**: `torch.cuda.set_per_process_memory_fraction(0.93)` prevents OOM thrashing

### 14.5 VRAM Budget (RTX 5090 32 GB target)

| Component | Model | VRAM |
|-----------|-------|------|
| ASR | Whisper Large v3 float32 | ~6 GB |
| LLM | Qwen3-14B FP8 (vLLM/Ollama) | ~15 GB |
| TTS | faster-qwen3-tts 0.6B | ~4 GB |
| Overhead | KV caches + activations | ~5 GB |
| **Total** | | **~30 GB** |

---

## 15. Provenance and Data Integrity

ClipCannon implements a tamper-evident hash chain that records every pipeline operation, linking each step to its predecessor through cryptographic hashing.

### 15.1 Chain Hash Formula

```
chain_hash = SHA256("{parent_hash}|{input_sha256}|{output_sha256}|{operation}|{model_name}|{model_version}|{json.dumps(model_params, sort_keys=True)}")
```

The first record in a project uses the sentinel `GENESIS_HASH = "GENESIS"` as the parent hash. Each subsequent record incorporates the parent's chain hash, creating a linked chain where modifying any historical record invalidates all downstream hashes.

### 15.2 Provenance Records

Each record captures 22 fields including input/output file paths and SHA-256 hashes, model metadata (name, version, quantization, parameters), execution metrics (duration, GPU device, peak VRAM), and the computed chain hash.

### 15.3 Verification

`verify_chain()` walks the entire chain in chronological order, recomputing each record's chain hash and comparing it against the stored value. Any discrepancy identifies the exact record where tampering or corruption occurred.

### 15.4 Finalize-Stage Verification

The pipeline's `finalize` stage runs chain verification as its penultimate step. If verification fails, the project is marked as `"error"` rather than `"ready"`, preventing use of potentially corrupted analysis data.

---

## 16. Billing and Credit System

ClipCannon uses a credit-based billing model with HMAC-signed balances for tamper resistance.

### 16.1 Credit Rates

| Operation | Credits |
|-----------|---------|
| Analyze (ingest) | 10 |
| Render | 2 |
| Metadata generation | 1 |
| Publish | 1 |

### 16.2 HMAC Integrity

Balance values are signed with HMAC-SHA256 using a machine-derived key:
```
machine_id = SHA256("{hostname}|{mac_addr}|{cpu_arch}")[:32]
hmac_key = SHA256("clipcannon-v1|{machine_id}")
signature = HMAC-SHA256(hmac_key, "balance:{balance}")
```

Every balance read verifies the HMAC signature via constant-time comparison. A signature mismatch triggers a CRITICAL log and raises a fatal `BillingError`.

### 16.3 Credit Packages

| Package | Credits | Price | Per-Credit |
|---------|---------|-------|------------|
| Starter | 50 | $5 | $0.10 |
| Creator | 250 | $20 | $0.08 |
| Pro | 1,000 | $60 | $0.06 |
| Studio | 5,000 | $200 | $0.04 |

---

## 17. GPU Management and Resource Optimization

### 17.1 Precision Auto-Detection

The system automatically selects the optimal quantization precision based on GPU compute capability:

| Compute Capability | Architecture | Precision |
|-------------------|-------------|-----------|
| 12.0 | Blackwell | nvfp4 |
| 8.9 | Ada Lovelace | int8 |
| 8.6 | Ampere | int8 |
| 7.5 | Turing | fp16 |
| No GPU | CPU fallback | fp32 |

### 17.2 Model Manager

The `ModelManager` uses an LRU (Least Recently Used) eviction strategy:
- **> 16 GB VRAM**: Concurrent mode -- multiple models stay loaded; LRU eviction frees space when needed
- **<= 16 GB VRAM**: Sequential mode -- all models unloaded before loading a new one

### 17.3 Per-Stage Memory Pattern

Individual pipeline stages manage their own GPU memory lifecycle: import -> load model -> inference -> delete model -> `torch.cuda.empty_cache()`. This prevents VRAM fragmentation across the 22-stage pipeline.

---

## 18. MCP Protocol Integration

ClipCannon exposes 51 tools via the Model Context Protocol:

| Category | Tools | Description |
|----------|-------|-------------|
| Project | 5 | Create, open, list, status, delete projects |
| Understanding | 4 | Ingest, transcript, frame retrieval, semantic search |
| Discovery | 4 | Best moments, cut points, narrative flow, safe cuts |
| Editing | 11 | Full EDL lifecycle with iterative refinement |
| Rendering | 8 | Platform rendering, preview, inspection, scene map |
| Audio | 4 | AI music, MIDI, SFX, cleanup |
| Voice | 4 | Data prep, profiles, synthesis, optimized synthesis |
| Avatar | 1 | Lip-sync video generation |
| Video Generation | 1 | End-to-end text-to-video |
| Billing | 4 | Balance, history, estimates, spending limits |
| Disk | 2 | Usage analysis, cleanup |
| Config | 3 | Get, set, list configuration |

The MCP server runs on stdio transport by default, with all tool results serialized as JSON `TextContent`. Image-returning tools also provide `ImageContent` with base64-encoded inline data.

---

## 19. Database Architecture

### 19.1 Per-Project Database

Each project maintains its own SQLite database at `~/.clipcannon/projects/{project_id}/analysis.db` with:

- **31 core tables** covering project metadata, transcripts, visual analysis, audio analysis, scoring, content safety, pipeline tracking, scene analysis, narrative analysis, editing, rendering, and audio assets
- **4 vector tables** (sqlite-vec `vec0`): `vec_frames`, `vec_semantic`, `vec_emotion`, `vec_speakers`
- **19 indexes** optimized for time-range queries, status filtering, and version history traversal

### 19.2 Schema Versioning

The database uses a three-version migration chain:
- **v1**: Phase 1 core tables (22 tables)
- **v2**: Phase 2 editing/rendering tables (6 tables)
- **v3**: Phase 3 voice profiles table (1 table)

New projects include all versions from creation; existing projects are migrated idempotently.

### 19.3 Connection Configuration

All connections apply: WAL journal mode, NORMAL synchronous, 64 MB page cache, foreign keys ON, temp store in memory.

### 19.4 Separate Databases

| Database | Location | Purpose |
|----------|----------|---------|
| Project DB | `~/.clipcannon/projects/*/analysis.db` | All analysis, editing, rendering data |
| License DB | `~/.clipcannon/license.db` | Credit balances and transactions |
| Voice Profiles DB | `~/.clipcannon/voice_profiles.db` | Voice profiles with 2048-dim embeddings |
| Voice Agent DB | `~/.voiceagent/agent.db` | Conversation logs and latency metrics |

---

## 20. Testing and Verification

ClipCannon maintains 626 tests across 43 test files:

- **425 ClipCannon tests** (24 files): Pipeline stages, billing, provenance, editing, rendering, audio, discovery, voice, avatar
- **201 Voice Agent tests** (19 files): ASR, TTS, LLM, conversation, transport, activation, database

Additionally, 10 FSV (Full State Verification) scripts provide forensic-level testing with 750+ individual checks, verifying database state, module imports, edge cases, and integration correctness.

---

## 21. Graceful Degradation

The system implements five layers of degradation:

1. **Stage-level**: Required stages abort the pipeline; optional stages log failures and continue
2. **Audio resolution**: `vocals.wav` -> `audio_16k.wav` fallback chain
3. **Model-level**: WhisperX -> faster-whisper, pyiqa -> Laplacian, Wav2Vec2 -> RMS, WavLM -> single-speaker fallback, SenseVoice -> spectral analysis, librosa -> scipy, NVENC -> libx264
4. **Extension-level**: sqlite-vec unavailable -> SQL LIKE search fallback
5. **Finalize reconciliation**: All failed/skipped streams documented in degradation note; project still usable for editing

---

## 22. Conclusion

ClipCannon demonstrates that multi-modal embedding architectures can transform video understanding from a manual, intuition-driven process into a programmatic, AI-assisted workflow. By maintaining five distinct embedding spaces -- visual (1152-dim SigLIP), semantic (768-dim Nomic Embed), emotional (1024-dim Wav2Vec2), speaker identity (512-dim WavLM), and voice verification (2048-dim ECAPA-TDNN) -- the system captures the full perceptual richness of video content and makes it queryable through a unified database interface.

The cross-stream intelligence layer -- highlight scoring, convergence-based cut detection, narrative flow analysis -- demonstrates that the combination of multiple specialized embeddings produces insights that no single modality can provide. A "best moment" is not just a visual highlight or an emotional peak; it is a convergence of signals across all channels, weighted by the intended editorial purpose.

The system's architecture -- local-first execution, tamper-evident provenance, credit-based billing, graceful degradation, and MCP protocol integration -- positions ClipCannon as a production-grade tool for AI-assisted video production. The addition of voice cloning with ECAPA-TDNN verification and real-time conversational AI via the Voice Agent extends the platform from passive video analysis to active content generation, creating a complete pipeline from raw footage to lip-synced, voice-cloned, platform-optimized output.

---

## Appendix A: Model Summary Table

| # | Model | Provider | Parameters | Purpose | Stage/Tool | GPU Required |
|---|-------|----------|-----------|---------|------------|-------------|
| 1 | SigLIP-SO400M-patch14-384 | Google | ~400M | Visual embeddings + shot classification | `visual_embed`, `shot_type` | Yes |
| 2 | Nomic Embed Text v1.5 | Nomic AI | ~137M | Semantic text embeddings + topic clustering | `semantic_embed` | Yes |
| 3 | Wav2Vec2-large-960h | Meta/Facebook | ~317M | Emotion embeddings from audio | `emotion_embed` | Yes |
| 4 | WavLM-base-plus-sv | Microsoft | ~94M | Speaker embeddings + diarization | `speaker_embed` | Yes |
| 5 | Qwen3-Voice-Embedding ECAPA-TDNN | Qwen/marksverdhei | ~1.7B | Voice identity verification (2048-dim) | Voice verification | Yes |
| 6 | HTDemucs v4 | Meta | ~83M | Audio source separation | `source_separation` | Yes |
| 7 | WhisperX / faster-whisper (Large v3) | OpenAI | ~1.5B | Speech-to-text with word alignment | `transcribe` | Yes |
| 8 | PaddleOCR PP-OCRv5 | PaddlePaddle | ~12M | On-screen text detection | `ocr` | Optional |
| 9 | SenseVoice Small | FunASR | ~234M | Reaction detection (laughter, applause) | `reactions` | Yes |
| 10 | Qwen3-8B | Qwen | 8B | Narrative structure analysis | `narrative_llm` | Yes |
| 11 | Qwen3-TTS 1.7B | Qwen | 1.7B | High-quality voice synthesis | `speak` tool | Yes |
| 12 | faster-qwen3-tts 0.6B | Qwen | 0.6B | Real-time voice synthesis | Voice Agent | Yes |
| 13 | ACE-Step v1.5 | ACE | ~1B | AI music generation (diffusion) | `generate_music` | Yes |
| 14 | LatentSync 1.6 | ByteDance | ~500M | Lip-sync video diffusion | `lip_sync` | Yes |
| 15 | Silero VAD | Silero | ~2M | Voice activity detection | Multiple | No (CPU) |
| 16 | Qwen3-14B FP8 | Qwen | 14B | Local LLM reasoning (Voice Agent) | Voice Agent brain | Yes |
| 17 | openWakeWord | David Scripka | ~5M | "Hey Jarvis" wake word detection | Voice Agent activation | No (CPU) |

---

## Appendix B: Embedding Dimension Reference

| Embedding Space | Dimension | Model | Storage Table | Data Type | Normalization |
|----------------|-----------|-------|---------------|-----------|---------------|
| Visual | 1152 | SigLIP-SO400M | `vec_frames` | float32 | L2-normalized |
| Semantic | 768 | Nomic Embed v1.5 | `vec_semantic` | float32 | L2-normalized |
| Emotion | 1024 | Wav2Vec2-large | `vec_emotion` | float32 | Mean-pooled |
| Speaker | 512 | WavLM-base-plus-sv | `vec_speakers` | float32 | L2-normalized |
| Voice Identity | 2048 | ECAPA-TDNN (Qwen3) | `voice_profiles` (BLOB) | float32 | L2-normalized |

**Total embedding dimensionality per video**: 1152 + 768 + 1024 + 512 = **3,456 dimensions** across four vector spaces for video content analysis, plus 2048 dimensions for voice identity verification.

---

*ClipCannon is source-available under the Business Source License 1.1. Free to use, modify, and self-host. Converts to Apache 2.0 on 2030-03-31. For commercial licensing inquiries, visit the project repository.*
