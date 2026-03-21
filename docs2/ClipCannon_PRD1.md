
# PRD: AI-Native Video Editor MCP Server

Product Requirements Document
**Version: 5.1 Date: 2026-03-21 Product: ClipCannon (clipcannon.com) Author: Product Team**

> **Phase 1 Status**: COMPLETED and VERIFIED on 2026-03-21. 750/750 FSV checks passed. 181 pytest tests pass. 0 lint errors. 27 MCP tools implemented. See [Verification Report](../docs/codestate/12_verification_report.md) for details.



## 1. Executive Summary


### 1.1 Problem Statement

All existing video editing software is built for human operators. Even "AI-assisted" tools (CapCut, Descript, Opus Clip) are fundamentally GUI-driven applications that bolt AI features onto a human-centric editing paradigm. There is no system that allows an AI model to truly understand a video at a multimodal level and autonomously produce edited outputs.

Content creators who produce long-form video (podcasts, talks, interviews, tutorials, livestreams) need to repurpose that content into dozens of platform-specific clips. This process currently requires hours of manual editing per source video, or expensive human editors.


### 1.2 Proposed Solution

ClipCannon is an AI-native video editing MCP (Model Context Protocol) server that runs entirely locally on consumer GPU hardware. It decomposes video into 12 parallel understanding streams, delivers sampled frames + timestamped transcript + quantitative embedder analytics to a multimodal AI (Claude Code), and enables the AI to see, understand, and edit video through tool calls — producing platform-ready outputs for Instagram, TikTok, Facebook, LinkedIn, and YouTube.

The key insight: a multimodal AI with a 1M context window can look at actual video frames while simultaneously reading the transcript and embedder analytics — all temporally aligned. The AI does not need text descriptions of what it's seeing. It looks at the frames directly, the same way a human editor would, but augmented with quantitative signals (emotion energy, speaker identity, reaction events, beat positions) that humans can only estimate intuitively. No traditional video editing UI is needed.


### 1.3 Target Hardware

| Component | Specification | Role |
|:---|:---|:---|
| GPU | NVIDIA GeForce RTX 5090 (32GB GDDR7, 21,760 CUDA cores, 680 Tensor Cores, 170 SMs, 1,792 GB/s bandwidth) | Model inference (NVFP4/INT8), NVENC encoding (3 parallel), CUDA 13.2 Tile kernels, Green Contexts |
| CUDA | CUDA Toolkit 13.2, Driver R595+, Compute Capability 12.0 | CUDA Tile (Python DSL), NVFP4, Green Contexts, CCCL 3.2, CuPy interop |
| CPU | AMD Ryzen 9 9950X3D (16C/32T, 5.7GHz) | FFmpeg orchestration, I/O, file hashing (provenance), MIDI/FluidSynth audio synthesis, profanity word matching |
| RAM | 128GB DDR5 (3592 MT/s) | Video buffers, frame caches, concurrent model loading |
| Motherboard | ASUS ROG STRIX X870E-E GAMING WIFI | PCIe 5.0 x16 for full GPU bandwidth |
| OS | Windows 11 Pro (WSL2 Linux 6.6) | Dual-environment execution |


### 1.4 Core Value Proposition

One video in, many videos out: A single source video produces shorts, reels, clips, highlights, and long-form edits automatically
AI-native: The AI doesn't assist a human editor; the AI is the editor. Humans approve output, not individual cuts
AI-generated soundtracks: The AI composes original background music, transition stingers, and sound effects programmatically -- no stock audio licensing needed
Professional motion graphics: Built-in library of animated lower thirds, title cards, transitions, pop-ups, subscribe CTAs, and callout overlays -- rendered dynamically with custom text, colors, and timing
Fully local: No cloud dependencies. All processing on local GPU. No data leaves the machine
Platform-aware: Output is pre-formatted for each social media platform's requirements
MCP-integrated: Plugs into any AI model (Claude, GPT, Llama, etc.) via Model Context Protocol

## 2. Architecture Overview


### 2.1 System Architecture

```
                         +---------------------------+
                         |     AI Model (Claude)     |
                         |   via MCP Client          |
                         +---------------------------+
                                    |
                              MCP Protocol
                           (stdio / SSE)
                                    |
                         +---------------------------+
                         |   ClipCannon MCP Server      |
                         |                           |
                         |  +---------------------+  |
                         |  |   Tool Registry      |  |
                         |  | (27 Phase 1, 60+ planned)|  |
                         |  +---------------------+  |
                         |            |               |
                         |  +---------------------+  |
                         |  |   Project Manager    |  |
                         |  |   (State, Sessions)  |  |
                         |  +---------------------+  |
                         |            |               |
                         +---------------------------+
                                    |
                    +-------+-------+-------+-------+
                    |       |       |       |       |
            +-------+--+ +--+------+ +-----+--+ +--+--------+
            |Understand| | Editing | | Audio  | |  Rendering|
            |  Engine  | | Engine  | | Engine | |  Engine   |
            +----------+ +---------+ +--------+ +-----------+
            |          | |         | |        | |           |
            | -Whisper | | -CutPlan| | -ACE-  | | -FFmpeg   |
            | -SigLIP  | | -Timeline| |  Step | | -NVENC    |
            | -Embedders| | -Effects| | -Audio-| | -Platform |
            | -Scene   | | -Captions| |  Gen  | |  Profiles |
            | -Diarize | | -Titles | | -MIDI/ | | -Batch    |
            +----------+ +---------+ | Fluid  | +-----------+
                    |         |      | -DSP   |       |
                    |    +----+----+ +--------+       |
                    |    | Motion  |                   |
                    |    | Graphics|                   |
                    |    | Engine  |                   |
                    |    +---------+                   |
                    |    | -Lottie |                   |
                    |    | -PyCairo|                   |
                    |    | -WebM   |                   |
                    |    | -FFmpeg |                   |
                    |    |  native |                   |
                    |    +---------+                   |
                    +-------+-------+-------+---------+
                                    |
                         +---------------------------+
                         |   Publishing Engine       |
                         |   (Platform APIs)         |
                         |                           |
                         |  Instagram | TikTok       |
                         |  Facebook  | LinkedIn     |
                         |  YouTube                  |
                         +---------------------------+
```

### 2.2 Design Principles

AI-First: The AI Is the Editor: Every design decision answers one question: "Does the AI have what it needs to make this editing decision?" The AI is multimodal — it can read text, view images, and reason over structured data simultaneously. It receives sampled frames (actual images), word-level transcripts, and embedder analytics, all temporally aligned on the same millisecond timeline. The AI sees the video, reads what was said, and knows the quantitative signals — all at once.
The AI Sees the Actual Frames: This system is designed for Claude Code (or equivalent multimodal LLM) with a 1 million token context window and native image understanding. Sampled frames at 2fps are extracted as JPEGs and delivered to the AI alongside their timestamps. The AI sees what is happening in the video the same way a human editor would — by looking at it.
Temporal Alignment Is Everything: All data — frames, transcript words, embedder analytics — shares a unified millisecond timeline. At any timestamp, the AI can see: the frame (what is being shown), the transcript (what is being said), the speaker (who is saying it), the energy (how engaging it is), and every other signal. This temporal alignment is the core data structure of the system.
Embedders Provide Quantitative Signals the AI Cannot See in Frames: The AI can look at a frame and understand its visual content. But it cannot "hear" emotion from an image, detect laughter, measure speaking pace, or compute semantic similarity. The 12 understanding streams provide quantitative signals that augment the AI's visual perception: energy scores, speaker labels, topic clusters, reaction events, beat positions, quality metrics, and more.
Provenance Hash Chain on Every Transformation: Every data transformation — from source video to audio extraction, from audio to transcript, from frames to embeddings — is recorded with SHA-256 hashes into an immutable provenance chain. This provides full visibility into every stage of the pipeline for debugging, audit, and replay.
FFmpeg Is the Renderer: All actual video manipulation is delegated to FFmpeg. The AI produces edit decision lists (EDLs); FFmpeg executes them. The EDL is a declarative contract — the AI says what, FFmpeg does how.
Platform-Native Content Strategy: Different platforms reward different content. TikTok rewards hook-in-3-seconds pacing, YouTube rewards retention, LinkedIn rewards professionalism. Platform profiles include both technical specs AND content strategy guidance that the AI uses when making editorial decisions.
Human-in-the-Loop for Publishing Only: The AI handles all creative decisions autonomously. Humans review and approve final outputs before publishing.
Every MCP Response Under 25K Tokens: Claude Code truncates MCP tool responses exceeding ~25,000 tokens. Every tool in ClipCannon is designed to return under 25K tokens per response. Large data (transcripts, storyboards, analytics) is delivered progressively through paginated or batched tool calls. The AI requests what it needs, when it needs it.
GPU-First Processing: Every pipeline step that can run on GPU MUST run on GPU. The RTX 5090 has 21,760 CUDA cores, 680 Tensor Cores, and 1,792 GB/s bandwidth — CPU fallback is used only for operations with no GPU implementation (profanity word matching, provenance hash computation). CUDA Tile kernels, CuPy, cuFFT, and NVENC/NVDEC are used everywhere applicable.
Stateless Tools, Stateful Projects: Each MCP tool call is stateless. Project state (source videos, analysis results, edit plans, provenance records) persists in a project directory.

### 2.3 AI Agent Decision Framework

This section defines the central question of the entire system: What information does the AI need, in what format, to make intelligent video editing decisions?

The AI agent is Claude Code — a multimodal LLM with a 1 million token context window that can read text, view images, and reason over structured data simultaneously. It connects to ClipCannon via MCP (Model Context Protocol). The AI perceives the video through three channels delivered together:

Actual frames (JPEG images) — the AI looks at sampled video frames directly, the same way a human editor would
Transcript (timestamped text) — the AI reads what is being said, word by word, aligned to the frames
Embedder analytics (structured JSON) — quantitative signals the AI cannot derive from looking at frames alone: energy scores, speaker IDs, topic clusters, reaction events, beat positions, quality metrics
All three channels share the same millisecond timeline. At any moment in the video, the AI can see the frame, read the words, and check every quantitative signal.


#### 2.3.1 The AI's Perception Model

The AI perceives the video through the Video Understanding Document (VUD) — a JSON document containing all analytics — plus direct access to sampled frames via clipcannon_get_frame. Key frames (scene boundaries, highlights) are delivered proactively with the VUD so the AI can immediately see the most important moments.

| Channel | What the AI Receives | Format | What It Tells the AI |
|:---|:---|:---|:---|
| Frames (direct visual) | Actual JPEG images at 2fps with timestamps | Images via clipcannon_get_frame | The AI SEES the video. It looks at frames the same way a human editor would. Key frames (scene boundaries, highlights) are delivered proactively. Additional frames available on demand by timestamp. |
| Transcript (faster-whisper) | transcript.segments[]: {id, start_ms, end_ms, text, speaker, words[]} | JSON | What is being said, when, and by whom. The AI reads the transcript aligned to the frames it's viewing. Word-level timestamps enable precise cut placement. |
| Topics (Nomic Embed) | topics[]: {id, start_ms, end_ms, label, keywords[]} | JSON | What subjects are discussed. Derived from transcript embedding clusters. The AI uses these for chapter boundaries and content search. |
| Emotion/Energy (Wav2Vec2) | emotion_curve[]: {start_ms, end_ms, arousal, valence, energy} | JSON | How energetic each moment is. 0.0-1.0 scores. The AI cannot "hear" energy from a frame image — this stream provides the quantitative signal. Processed on clean vocal stem. |
| Speakers (WavLM) | speakers[]: {id, label, total_speaking_ms} + per-segment speaker field | JSON | Who is speaking when. The AI can see faces in frames but cannot match voice to face without this stream. Processed on clean vocal stem. |
| Reactions (SenseVoice) | reactions[]: {start_ms, end_ms, type, confidence, intensity} | JSON | Where laughter and applause occur. The AI cannot hear audio from frames — this is the strongest highlight signal for conversational content. |
| On-Screen Text (PaddleOCR) | on_screen_text[]: {start_ms, end_ms, texts[], type} + text_change_events[] | JSON | What text is displayed on screen. The AI could read text from frames visually, but OCR provides structured, searchable, timestamped text and detects slide transitions automatically. |
| Beats (madmom) | beats: {beat_positions_ms[], downbeat_positions_ms[], tempo_bpm} | JSON | Where musical beats fall. Enables cut-on-beat editing. The AI cannot perceive audio rhythm from frames. |
| Quality (BRISQUE/DOVER) | quality[]: {scene_id, quality_avg, classification, issues[]} | JSON | Which segments are blurry/shaky. The AI could judge quality from frames visually, but pre-computed scores enable automated filtering without spending context on every frame. |
| Shot Type (ResNet-50) | scenes[].shot_type + crop_recommendation | JSON | Camera framing. Close-up vs wide. The AI could judge this from frames, but pre-computed labels enable automated crop strategy without visual inspection of every scene. |
| Silence/Acoustic (Librosa) | silence_gaps[] + acoustic.music_sections[] | JSON | Where silence and music are. The AI cannot hear audio from frames. Silence gaps = natural cut points. |
| Content Safety (word list) | content_safety: {profanity_events[], content_rating} | JSON | Where profanity occurs. Auto-bleep timestamps derived from transcript. |
| Pacing (Chronemic) | pacing[]: {start_ms, end_ms, words_per_minute, pause_ratio, label} | JSON | How fast-paced each section is. Derived from transcript + speakers + acoustic. |

Key architectural principle: The AI CAN see and understand frames visually (it's multimodal). The embedder streams provide signals the AI cannot derive from images alone: audio energy, speaker identity, laughter detection, beat positions, and semantic topic clustering. Frames give the AI eyes. Embedders give it ears and analytical instruments. Together, they give the AI complete perception of the video.

Embedding vectors (stored in sqlite-vec tables in analysis.db) are never sent to the AI. They exist in the database for computational operations (similarity search, clustering, re-analysis) but the AI only receives the derived analytics and the actual frames.


#### 2.3.2 The AI's Decision Loop

When the AI edits a video, it follows this protocol:

```
STAGE 1 — READ THE MAP (progressive, chunked under 25K per response)
   ├─ Call 1: clipcannon_get_vud_summary (~8K tokens)
   │   AI learns: duration, speakers, topics, top highlights, content rating
   │   AI now knows WHAT the video is about and WHERE the best moments are
   │
   ├─ Call 2: clipcannon_get_analytics (~18K tokens)
   │   AI learns: every scene boundary, every topic, every highlight, every reaction
   │   AI now has the complete structural map of the video
   │
   ├─ Calls 3-8: clipcannon_get_transcript (targeted pages, ~12K each)
   │   AI reads transcript ONLY for sections it plans to edit
   │   Guided by highlights from Call 2 — reads those regions first
   │   Does NOT read the entire 4-hour transcript — only relevant sections
   │
   ├─ At this point (~80K tokens accumulated, 0 images) the AI can make
   │   55-60% of all editing decisions: cut plan, chapter markers, music mood
   └─ The AI has formed a complete mental model of the video's content
```

STAGE 2 — WATCH THE OVERVIEW (storyboard grids, batched under 25K)
```
   ├─ Calls 9-15: clipcannon_get_storyboard (7 batches of 12 grids, ~24K each)
   │   OR: targeted storyboards for only the regions being edited
   │   Each batch covers ~34 minutes; AI sees 12 composite images per batch
   │
   ├─ The AI SEES the video — scene changes, speaker appearances, camera
   │   framing, visual style, on-screen content
   │   Cross-references with text data already in context
   │
   └─ Now can make 85% of all editing decisions
```

STAGE 3 — INSPECT DETAILS (on-demand, under 25K per response)
```
   ├─ Calls 16+: clipcannon_get_frame / clipcannon_get_frame_strip
   │   For thumbnail selection, framing verification, quality spot-checks
   │   Typical: 5-10 calls for detail frames
   │
   └─ The AI now has complete understanding equivalent to a human editor
```

PLAN — The AI decides what to create
```
   ├─ Which segments to extract (time ranges from transcript + highlights)
   ├─ What aspect ratio and crop strategy (from shot_type + face_position + platform)
   ├─ What transitions between segments (snapped to beat_positions_ms if music present)
   ├─ What audio to generate (mood from emotion_curve, style from platform strategy)
   ├─ What overlays to add (lower thirds from speakers[], CTAs per platform)
   ├─ What captions style to use (platform-specific from decision matrix)
   └─ What metadata to generate (from transcript + topics + platform)
```

EXECUTE — The AI writes EDLs and triggers renders
```
   ├─ Call clipcannon_create_edit with the EDL (one per output clip)
   ├─ Call clipcannon_render to produce the final video
   ├─ Call clipcannon_generate_metadata for platform-specific copy
   └─ Repeat for each clip — the AI can produce 20+ clips from one source
```

VERIFY — Check output integrity
```
   ├─ Call clipcannon_render_status to confirm success
   ├─ Call clipcannon_provenance_verify to confirm hash chain integrity
   └─ Call clipcannon_publish_queue to submit for human review
The AI can produce unlimited edits from one video. After Stages 1-3, the full video understanding persists in the AI's context. Every subsequent edit draws from the same understanding — the AI does not need to re-analyze the video. A single 4-hour source video session can produce dozens of clips for multiple platforms.
```


#### 2.3.3 What the AI Needs for Each Decision Type

| Decision | Required VUD Fields | How the AI Uses Them |
|:---|:---|:---|
| "Where should I cut?" | transcript.segments[].words[] (sentence boundaries), scenes[].start_ms/end_ms (visual transitions), silence_gaps[] (natural pauses) | Cut at sentence boundaries that coincide with scene changes or silence gaps. Never cut mid-word. |
| "What are the best highlights?" | highlights[] (pre-scored with type, score, reason), emotion_curve[] (energy peaks), topics[].keywords[] (information density) | Select segments with highest highlight scores. Cross-reference with emotion energy peaks. Ensure narrative completeness (beginning + end). |
| "Who is speaking?" | speakers[] (id, label, total_ms), transcript.segments[].speaker | Create speaker-specific clips. Format interview clips with speaker labels. Detect monologue vs. dialogue for different editing styles. |
| "What music fits this clip?" | emotion_curve[] (avg energy, avg valence for the clip range), pacing[] (WPM), target platform | High energy + positive valence → upbeat music. Low energy + reflective → ambient. Fast pacing → higher BPM. LinkedIn → subtle/no music. TikTok → trendy/bass-heavy. |
| "Which segments are filler?" | emotion_curve[].energy (low values), pacing[].pause_ratio (high = lots of silence), chronemic[].words_per_minute (low = slow/tangent) | Remove segments where energy < 0.2 AND pause_ratio > 0.4 AND WPM < 80. These are likely tangents, dead air, or filler. |
| "What aspect ratio?" | platform field in the edit request | TikTok/Reels/Shorts → 9:16. YouTube standard → 16:9. LinkedIn → 1:1. YouTube 4K → 16:9 at 3840x2160. Facebook → 9:16. |
| "Where to place lower thirds?" | speakers[] + first appearance of each speaker in clip + scenes[].description | Show lower third when a speaker first appears in a clip. Position based on where faces are detected in the scene. |


#### 2.3.4 What the AI Sees vs. What the Embedders Provide

The AI has two perception channels that complement each other:

| Perception | Source | Example |
|:---|:---|:---|
| Visual (AI sees directly) | Actual JPEG frames at 2fps | The AI looks at a frame and sees: "two people at a desk, one is gesturing, there's a whiteboard behind them" |
| Transcript (AI reads directly) | Word-level timestamped text | "And that's when we realized the whole approach was wrong" at 185200ms |
| Audio signals (embedders provide — AI cannot hear from images) | Quantitative scores + event labels | energy: 0.94 at 845000ms, reaction: laughter at 845200ms, beat: downbeat at 845500ms, speaker: "Guest" |

The division of labor: The AI's eyes are the frames. The AI's ears are the embedder analytics. The AI's analytical instruments are the derived scores (topic clusters, pacing metrics, quality assessments). Together, the AI has richer perception than a human editor — it can see every frame, read every word, and access quantitative signals that humans estimate intuitively.

Embedding vectors (in sqlite-vec tables) are never sent to the AI. They exist in analysis.db for computational operations (cosine similarity search, k-means clustering, re-analysis). The AI receives only: frames (images), transcript (text), and derived analytics (structured data queried from the database).


#### 2.3.5 Video Understanding Protocol (How the AI Comprehends a 4-Hour Video)

This is the core design of the entire system. A 4-hour video at 2fps produces 28,800 frames. At ~1,600 tokens per image, that is 46M tokens — 46x larger than the 1M context window. The AI cannot see every frame. Instead, ClipCannon uses a 3-stage understanding protocol that mirrors how professional editors work: read the script first, look at the visual overview, then inspect specific moments in detail.

Claude's image token formula: tokens = (width * height) / 750, max ~1,600 tokens per image (auto-resized at 1568px max edge). Practical session limit: ~100 images to avoid context issues.

The critical insight from research: 55-60% of video editing decisions require NO visual data at all — they are purely transcript and analytics-based. Another 25% need only a storyboard-level overview. Only 15-20% need detail-level inspection of specific frames. This means the AI can understand and edit most of a video from text alone, using images selectively.


##### Stage 1: Text Map (Progressive Chunked Delivery — No Images)

Critical constraint: MCP tool responses are truncated at ~25K tokens. The full VUD for a 4-hour video is ~106K tokens. Therefore, the VUD is delivered progressively through multiple focused tool calls, each under 25K tokens. The AI builds up its understanding incrementally, exactly like a human editor reading through notes.


##### Step 1a — Video Summary (clipcannon_get_vud_summary, ~8K tokens):


The AI's first perception. A single compact overview of the entire video:

```json
{
  "source": {"file": "podcast_ep42.mp4", "duration_ms": 14400000, "resolution": "3840x2160"},
  "summary": {
    "total_scenes": 142,
    "total_speakers": 3,
    "speakers": [
      {"id": "speaker_0", "label": "Host", "speaking_pct": 45.2},
      {"id": "speaker_1", "label": "Guest 1", "speaking_pct": 35.1},
      {"id": "speaker_2", "label": "Guest 2", "speaking_pct": 19.7}
    ],
    "total_topics": 18,
    "topics": [
      {"id": "topic_001", "start_ms": 0, "end_ms": 300000, "label": "Introduction & Welcomes"},
      {"id": "topic_002", "start_ms": 300000, "end_ms": 1800000, "label": "AI in Healthcare: Current State"}
    ],
    "total_highlights": 24,
    "top_highlights": [
      {"start_ms": 845000, "end_ms": 905000, "score": 0.96, "reason": "Breakthrough revelation + laughter + high energy"},
      {"start_ms": 3200000, "end_ms": 3260000, "score": 0.93, "reason": "Emotional personal story + applause"}
    ],
    "reaction_summary": {"total_laughter": 14, "total_applause": 3, "reaction_density": 0.013},
    "beats": {"has_music": true, "avg_bpm": 120.4},
    "content_safety": {"rating": "mild", "profanity_count": 7},
    "avg_energy": 0.62,
    "silence_gap_count": 89,
    "on_screen_text_events": 12,
    "provenance": {"chain_hash": "7e4a...", "records": 18, "integrity": "verified"},
    "stream_status": {
      "source_separation": "completed", "visual": "completed", "ocr": "completed",
      "quality": "completed", "shot_type": "completed", "transcription": "completed",
      "semantic": "completed", "emotion": "completed", "speaker": "completed",
      "reactions": "completed", "acoustic": "completed", "beats": "completed",
      "chronemic": "completed", "storyboards": "completed"
    },
    "failed_streams": [],
    "vfr_detected": false,
    "vfr_normalized": false
  }
}
After this call, the AI knows: how long the video is, who speaks, what topics are covered, where the best highlights are, whether there's music, the content rating, and the overall energy level. This is enough to plan the editing strategy.
```


##### Step 1b — Highlights + Scenes + Topics (clipcannon_get_analytics, ~15-20K tokens):


Detailed analytics for the full video — highlights with reasons, scene boundaries with shot types and quality, topic boundaries with keywords:

clipcannon_get_analytics(project_id, sections=["highlights", "scenes", "topics", "reactions"])
This gives the AI the complete structural map: every scene boundary, every topic change, every highlight moment, every reaction event. Under 25K tokens even for a 4-hour video because these are summary-level entries (timestamps + labels), not per-frame data.


##### Step 1c — Transcript (clipcannon_get_transcript, paginated, ~12K per page):


The full transcript is too large for one response (~48K for 4 hours). It is delivered in time-range pages:

clipcannon_get_transcript(project_id, start_ms=0, end_ms=900000)  // first 15 minutes
clipcannon_get_transcript(project_id, start_ms=900000, end_ms=1800000)  // next 15 minutes
Each page contains ~15 minutes of transcript at ~12K tokens. The AI requests transcript pages for time ranges it's interested in (guided by the highlights and topics from Step 1b). The AI does NOT need to read the entire 4-hour transcript — it reads the sections it plans to edit.


##### Step 1d — Segment Deep Dive (clipcannon_get_segment_detail, ~10-20K tokens):


For any specific time range, returns ALL stream data at full resolution:

clipcannon_get_segment_detail(project_id, start_ms=840000, end_ms=910000)
// Returns: transcript, emotion_curve (per-second), speakers, reactions, beats,
// on_screen_text, pacing, quality, silence_gaps — all for that 70-second range
This is used when the AI is making fine-grained decisions about a specific clip: exactly where to cut, what music mood to use, where to place transitions.

Total Stage 1 calls for a typical 4-hour edit session: 6-10 tool calls, each under 25K tokens. The AI processes incrementally:

| Call | Tool | Tokens | What AI Learns |
|:---|:---|:---|:---|
| 1 | get_vud_summary | ~8K | Overall structure, speakers, top highlights, content rating |
| 2 | get_analytics | ~18K | All scenes, topics, highlights, reactions |
| 3 | get_transcript (highlight range 1) | ~12K | What's being said in best highlight |
| 4 | get_transcript (highlight range 2) | ~12K | Second best highlight |
| 5-8 | get_transcript (more ranges as needed) | ~12K each | Additional sections for editing |
| 9-10 | get_segment_detail (fine-grained) | ~15K each | Full-resolution data for specific clips |
| Total |  | ~100-120K | Complete understanding for editing decisions |


##### Stage 2: Visual Overview — Storyboard Grids (clipcannon_get_storyboard)

The AI's second perception is a visual overview of the entire video via storyboard grids — composite images where multiple frames are arranged in a single image. This technique is academically validated (IG-VLM, TS-LLaVA) and is 5-10x more token-efficient than individual frames.

How storyboard grids work: 9 frames are composited into a single 3x3 grid image (each sub-frame ~348x348 pixels in a 1044x1044 composite). Each cell has a timestamp overlay. The AI sees one image but perceives 9 moments in time. Token cost: ~1,454 tokens per grid (vs ~14,400 for 9 individual images).

Dynamic grid count: ClipCannon generates 80 storyboard grids for every video regardless of length. The frame sampling interval adapts to the video's duration. This means short videos get near-complete visual coverage, and long videos get the densest coverage that fits within the image budget (reserving 20 image slots for Stage 3 detail requests).

Adaptive interval formula:

frames_needed = 80 grids × 9 frames_per_grid = 720 frames
interval_s = max(video_duration_s / 720, 0.5)
// 0.5s floor because extraction rate is 2fps — can't sample denser than that
| Video Length | Interval | AI Visual Coverage |
|:---|:---|:---|
| 4 hours | 1 frame per 20s | Every scene change, every speaker transition, every major visual shift |
| 2 hours | 1 frame per 10s | Dense — catches most visual events |
| 1 hour | 1 frame per 5s | Very dense — near-continuous visual perception |
| 30 min | 1 frame per 2.5s | Nearly every extracted frame |
| 10 min | 1 frame per 0.83s | Exceeds extraction rate — sees every extracted frame |
| 4 min | capped at 2fps | Sees every single extracted frame — complete visual coverage |

For short videos (under ~6 minutes): The AI sees literally every extracted frame. It has complete visual understanding of the entire video, equivalent to watching it.

For long videos (4 hours): The AI sees 720 frames at 20-second intervals. Combined with the text map from Stage 1 (which covers every second via transcript + embedder analytics), the AI has continuous understanding with visual checkpoints every 20 seconds.

Token cost: 80 grids × ~1,454 tokens = ~116K tokens total across multiple batched responses.

Chunked delivery (each batch under 25K tokens):

Each storyboard grid image ≈ 1,454 tokens
Metadata JSON per grid ≈ 500 tokens (per-cell timestamps + stream data)
Per grid total ≈ ~2K tokens
12 grids per batch = ~24K tokens (under 25K limit)
80 grids = 7 batches via clipcannon_get_storyboard(project_id, batch=1) through batch=7
The AI calls each batch sequentially, building up visual understanding progressively
Each batch covers ~34 minutes of a 4-hour video (12 grids × 9 frames × 20s interval)
The AI can request storyboards for specific time ranges instead of the full video:

clipcannon_get_storyboard(project_id, start_ms=840000, end_ms=1200000)
// Returns grids covering only the 6-minute range around a highlight
This lets the AI be strategic: get storyboards for the top highlight regions first, skip sections it's not editing.

After Stage 1 + Stage 2: ~120K text + ~116K visual = ~236K tokens accumulated in context. The AI has complete textual understanding AND adaptive visual overview. It can make 80-85% of all editing decisions.


##### Stage 3: Detail Inspection (clipcannon_get_frame, clipcannon_get_frame_strip — on demand)

For the remaining 15-20% of decisions that require close visual inspection (thumbnail selection, framing checks, B-roll identification, visual quality verification), the AI requests specific frames:

Individual frames: clipcannon_get_frame(project_id, timestamp_ms) — returns a single frame as an image with all temporal metadata. ~1,600 tokens.

Frame strips: clipcannon_get_frame_strip(project_id, start_ms, end_ms, count) — returns a 3x3 grid of frames from a specific time range. The AI uses this to preview a potential clip's visual flow before committing. ~1,454 tokens for 9 frames.

Typical detail budget: 30-50 additional images (individual frames + strips) = ~50-80K tokens.

Token Budget for a Complete 4-Hour Edit Session
All data is delivered in chunks under 25K tokens per MCP response. The AI accumulates understanding progressively across multiple tool calls.

| Component | Tokens | % of 1M | Tool Calls | Images |
|:---|:---|:---|:---|:---|
| System prompt + platform strategy | 5K | 0.5% | 0 | 0 |
| Stage 1a: VUD Summary | 8K | 0.8% | 1 | 0 |
| Stage 1b: Analytics (scenes, topics, highlights, reactions) | 18K | 1.8% | 1 | 0 |
| Stage 1c: Transcript pages (as needed, ~6 pages typical) | 72K | 7.2% | 6 | 0 |
| Stage 1d: Segment details (2-3 deep dives) | 40K | 4.0% | 3 | 0 |
| Stage 2: Storyboard grids (7 batches of 12) | 116K | 11.6% | 7 | 80 |
| Stage 3: Detail frames (on demand) | 32K | 3.2% | 5-10 | 20 |
| Total input | ~291K | ~29.1% | ~25 calls | 100 |
| Available for AI reasoning + output | ~709K | ~70.9% | — | — |

Every tool response is under 25K tokens. No truncation, no data loss. The AI processes the video progressively:

Read the summary (1 call) → know the structure
Read the analytics (1 call) → know every highlight and scene
Read transcript for highlights of interest (3-6 calls) → know what's being said
View storyboards for regions of interest (3-7 calls) → see the video
Deep dive into specific segments (2-3 calls) → fine-grained decisions
Request detail frames (5-10 calls) → thumbnail selection, quality verification
The AI does NOT need to request everything. For a simple "extract top 5 highlights as TikTok clips" task, the AI may need only: summary (1 call) + analytics (1 call) + storyboard for each highlight region (5 calls) + transcript for each (5 calls) = 12 calls total. The full 25-call budget is for comprehensive editing sessions producing 20+ clips.

For shorter videos, fewer calls are needed — a 10-minute video's entire VUD fits in 2-3 calls, and all storyboards fit in 1-2 calls.

The Frame-Transcript-Embedder Alignment
Every frame delivered to the AI (whether in a grid or individually) is accompanied by temporal metadata showing what every stream knows about that moment:

```json
{
  "frame": {
    "timestamp_ms": 845000,
    "image": "[JPEG — Claude sees this as an image]"
  },
  "at_this_moment": {
    "transcript": "and the results were absolutely stunning, nobody expected—",
    "speaker": "speaker_1 (Guest)",
    "emotion": {"energy": 0.94, "arousal": 0.91, "valence": 0.78},
    "topic": "Main Discussion: AI in Healthcare",
    "reaction": {"nearest_laughter_ms": 845200, "distance_ms": 200},
    "shot_type": "closeup",
    "quality": 82.5,
    "pacing": {"wpm": 165, "label": "fast_dialogue"},
    "beat": {"nearest_beat_ms": 845500, "tempo_bpm": 120.4},
    "on_screen_text": null,
    "profanity": false
  }
}
For storyboard grids, the temporal metadata is provided as a JSON array (one entry per cell in the grid) alongside the grid image, so the AI can cross-reference each thumbnail with its corresponding data.
```

Why This Works
| Decision Type | Stage Needed | % of Decisions | Data Used |
|:---|:---|:---|:---|
| Remove silence/dead air | Stage 1 (text only) | 15% | silence_gaps |
| Remove filler words | Stage 1 (text only) | 15% | transcript |
| Identify highlights | Stage 1 (text only) | 15% | highlights, emotion_curve, reactions |
| Create chapter boundaries | Stage 1 + 2 (text + overview) | 10% | topics, text_change_events, storyboard |
| Select segments for clips | Stage 1 + 2 (text + overview) | 15% | transcript + energy + storyboard |
| Choose music mood | Stage 1 (text only) | 5% | emotion_curve, platform |
| Verify visual quality | Stage 2 or 3 (overview or detail) | 5% | quality scores + visual check |
| Select thumbnail | Stage 3 (detail) | 5% | individual frames |
| Check framing/crop | Stage 2 or 3 (overview or detail) | 5% | shot_type + visual check |
| Place transitions | Stage 1 + 2 | 5% | scenes, beats, storyboard |
| Metadata generation | Stage 1 (text only) | 5% | transcript, topics, platform |

70% of decisions use Stage 1 only (text). 85% use Stage 1 + 2. Only 15% need Stage 3.

Storyboard Grid Generation
ClipCannon generates storyboard grids during the preprocessing pipeline. Each grid is a 3x3 composite image:

```python
from PIL import Image, ImageDraw, ImageFont

def create_storyboard_grid(frames, timestamps, cols=3, rows=3):
    """Create a 3x3 grid of frames with timestamp overlays.
    Output: 1044x1044 image (~1,454 tokens in Claude).
    Each cell: 348x348 pixels (sufficient to identify scenes, people, text).
    """
    cell_w, cell_h = 348, 348
    grid = Image.new('RGB', (cols * cell_w, rows * cell_h), (0, 0, 0))
    font = ImageFont.truetype("Montserrat-Bold.ttf", 14)
```

    for i, (frame, ts_ms) in enumerate(zip(frames, timestamps)):
        if i >= cols * rows:
            break
        row, col = divmod(i, cols)
        thumb = frame.resize((cell_w, cell_h), Image.LANCZOS)
        grid.paste(thumb, (col * cell_w, row * cell_h))

        # Timestamp overlay (top-left of each cell)
        draw = ImageDraw.Draw(grid)
        ts_str = format_timestamp(ts_ms)  # "1:23:45"
        draw.rectangle([col*cell_w, row*cell_h, col*cell_w+80, row*cell_h+20], fill=(0,0,0,180))
        draw.text((col*cell_w+4, row*cell_h+2), ts_str, fill='white', font=font)

    return grid  # Save as JPEG quality 80
Adaptive interval calculation:

```python
def compute_storyboard_interval(video_duration_s, grid_count=80, frames_per_grid=9):
    """Calculate frame sampling interval based on video length.
    Short videos get denser coverage. Long videos spread frames evenly.
    Floor at 0.5s because frame extraction rate is 2fps.
    """
    total_frames_needed = grid_count * frames_per_grid  # 720
    interval_s = video_duration_s / total_frames_needed
    return max(interval_s, 0.5)  # Never sample faster than extraction rate

# Examples:
# 4hr video: max(14400/720, 0.5) = 20.0s interval
# 1hr video: max(3600/720, 0.5)  = 5.0s interval
# 10min video: max(600/720, 0.5) = 0.83s interval
# 4min video: max(240/720, 0.5)  = 0.5s interval (capped — sees every frame)
Grids are stored in analysis/storyboards/ and served by clipcannon_get_storyboard.
```


## 3. Video Understanding Pipeline


### 3.1 Multi-Stream Decomposition

Inspired by the Hexa-Modal Fusion architecture (Streams A-F), ClipCannon decomposes video into 12 parallel understanding streams fed by a source separation preprocessor. HTDemucs separates the audio into clean stems (vocals, music, drums, other) before any audio analysis, dramatically improving the quality of every downstream audio model.


#### 3.1.1 Source Separation Preprocessor (HTDemucs)

Before any audio stream runs, the source audio is separated into clean stems:

| Stem | Contents | Fed To |
|:---|:---|:---|
| Vocals | Isolated human speech, no music/noise | Streams T (Transcript), E (Emotion), K (Speaker), R (Reactions) |
| Music | Isolated background music/instruments | Stream B (Beat Detection), Stream A (Acoustic — music analysis) |
| Drums | Isolated percussion/rhythm | Stream B (Beat Detection) |
| Other | Ambient noise, sound effects, room tone | Stream A (Acoustic — noise floor analysis) |

Model: HTDemucs / htdemucs_ft (Meta, MIT license) VRAM: ~4 GB (GPU recommended, CPU fallback available) Speed: ~20-30s for a 3-minute track on GPU; scales linearly with duration Output: 4 WAV stems at source sample rate

Why this is first in the pipeline: Every audio embedder performs better on clean input. Wav2Vec2 emotion detection on a vocal stem without background music is dramatically more accurate than on a mixed signal. faster-whisper transcription on an isolated vocal stem produces fewer errors, especially with music-heavy sources. WavLM speaker embeddings are cleaner without music contamination. This single preprocessing step is a force multiplier for the entire audio pipeline.

Fallback (No GPU / Minimal tier): Skip separation and feed mixed audio directly to all streams (current behavior). Quality degrades but system still functions.


#### 3.1.2 Stream Table

| Stream | Name | Input | Model/Method | Output | Purpose |
|:---|:---|:---|:---|:---|:---|
| D | Source Separation | Raw audio | HTDemucs (MIT) | 4 stems: vocals, music, drums, other | Clean input for all audio streams |
| V | Visual Semantic | Frames (2fps) | SigLIP-SO400M | 1152-dim embeddings per frame | Scene content, objects, actions, visual similarity |
| O | On-Screen Text | Frames (1fps) | PaddleOCR PP-OCRv5 (Apache 2.0) | Detected text + bounding boxes per frame | Slide detection, text extraction, chapter markers |
| Q | Visual Quality | Frames (2fps) | pyiqa BRISQUE (GPU) + DOVER-Mobile (GPU) | Quality score 0-100 per frame | Filter out blurry/noisy/shaky segments |
| H | Shot Type | Key frames | ResNet-50 shot classifier | Shot type label per scene | Cropping strategy, pacing decisions |
| T | Transcript | Vocal stem | faster-whisper large-v3 | Word-level timestamped text | Spoken content, topic segmentation |
| S | Semantic | Transcript text | Nomic Embed Text v1.5 | 768-dim embeddings per segment | Topic clustering, content similarity |
| E | Emotion/Energy | Vocal stem | Wav2Vec2 Emotion | 1024-dim embeddings per segment | Emotional arc, energy levels, engagement |
| K | Speaker | Vocal stem | WavLM Base Plus SV | 512-dim X-vectors per segment | Speaker diarization, speaker change detection |
| R | Reactions | Vocal stem | SenseVoice-Small (Apache 2.0) | Event labels: laughter, applause, BGM, speech | Audience engagement signals, highlight markers |
| A | Acoustic | Full mix + stems | cuFFT (GPU) + Beat This! (GPU) | Energy/RMS/spectral + beat grid | Silence, music sections, volume, beat positions |
| C | Chronemic | Derived from T,K,A | CuPy (GPU) | 4-dim temporal features | Pacing, silence patterns, rhythm |


### 3.2 Stream V: Visual Semantic (Frame Analysis)

Model: google/siglip-so400m-patch14-384 VRAM: ~1.2GB Output: 1152-dim embedding per frame Extraction Rate: 2 frames per second (every 500ms)

Why SigLIP over CLIP: SigLIP (Sigmoid Loss for Language-Image Pre-Training) provides better zero-shot classification and more discriminative embeddings than CLIP, with native 384x384 input resolution. The SO400M variant offers the best quality/speed tradeoff for local inference.

Pipeline:

Extract frames at 2fps using FFmpeg hardware-accelerated decode (NVDEC)
Resize to 384x384 maintaining aspect ratio with padding
Run batch inference through SigLIP on GPU (batch size 32-64)
Store embeddings with millisecond timestamps
Compute inter-frame cosine similarity for scene change detection
Scene Change Detection:

For consecutive frames f[i] and f[i+1]:
  similarity = cosine_sim(embed(f[i]), embed(f[i+1]))
  if similarity < SCENE_THRESHOLD (0.75):
    mark_scene_boundary(timestamp[i])
What The AI Receives (in VUD scenes[] + the actual frame image):

```json
{
  "id": "scene_003",
  "start_ms": 45000,
  "end_ms": 128000,
  "key_frame_path": "analysis/frames/frame_000090.jpg",
  "key_frame_timestamp_ms": 45000,
  "visual_similarity_avg": 0.89,
  "dominant_colors": ["#3a2a1a", "#f0e6d2"],
  "face_detected": true,
  "face_position": {"x_center_pct": 0.52, "y_center_pct": 0.38},
  "shot_type": "closeup",
  "quality_avg": 78.5,
  "crop_recommendation": "safe_for_vertical"
}
The AI looks at the actual key frame image (delivered via clipcannon_get_vud_summary with key frames). It sees what the scene looks like — no text description needed. The structured data provides quantitative signals: visual_similarity_avg (how visually stable), face_position (for smart cropping), shot_type and crop_recommendation (for aspect ratio decisions). The AI never reads the 1152-dim SigLIP embeddings — those are used internally for scene boundary computation.
```


### 3.3 Stream O: On-Screen Text (OCR)

Model: PaddleOCR PP-OCRv5 (mobile pipeline) VRAM: ~1-2GB (GPU accelerated; CPU fallback available) Output: Detected text strings + bounding boxes per frame Extraction Rate: 1 frame per second (every 1000ms) — lower than visual stream because text changes less frequently License: Apache 2.0 (commercial OK)

Pipeline:

Sample frames at 1fps from source video
Run PP-OCRv5 text detection + recognition on each frame
Deduplicate: if text is identical to previous frame, skip (avoids redundant entries for static slides)
Output: list of text regions with bounding boxes, confidence scores, and timestamps
Detect text-change events: when on-screen text changes significantly = slide transition / new section
What The AI Receives (in VUD on_screen_text[]):

```json
{
  "on_screen_text": [
    {
      "start_ms": 120000,
      "end_ms": 185000,
      "texts": [
        {"text": "Key Findings: 3x Improvement", "confidence": 0.96, "region": "center_top", "font_size_est": "large"},
        {"text": "Clinical Trial Results 2025", "confidence": 0.94, "region": "center_middle", "font_size_est": "medium"},
        {"text": "www.example.com/results", "confidence": 0.91, "region": "bottom", "font_size_est": "small"}
      ],
      "type": "slide",
      "change_from_previous": true
    },
    {
      "start_ms": 540000,
      "end_ms": 542000,
      "texts": [
        {"text": "Dr. Sarah Chen - AI Research Director", "confidence": 0.98, "region": "bottom_third", "font_size_est": "medium"}
      ],
      "type": "lower_third",
      "change_from_previous": true
    }
  ],
  "text_change_events": [
    {"timestamp_ms": 120000, "type": "slide_transition", "new_title": "Key Findings: 3x Improvement"},
    {"timestamp_ms": 185000, "type": "slide_transition", "new_title": "Implementation Timeline"},
    {"timestamp_ms": 540000, "type": "lower_third_appeared", "name": "Dr. Sarah Chen"}
  ]
}
The AI uses text_change_events as structural markers (slide transition = topic boundary, reinforces semantic topic detection). It reads texts[].text for chapter titles and metadata. It avoids cutting during important text display (keep slide on screen for minimum readable duration). It detects existing lower thirds in the source video to avoid duplicating them. The AI never needs to process frames through OCR itself — this is pre-computed.
```


### 3.4 Stream Q: Visual Quality Assessment

Model: pyiqa BRISQUE (GPU, via PyTorch) + DOVER-Mobile (GPU) VRAM: ~1.0 GB (BRISQUE GPU batch) + ~1.9 GB (DOVER-Mobile) = ~2.9 GB total (shared with other models at NVFP4) Output: Per-frame quality score (0-100) + per-scene quality classification License: Public domain (BRISQUE) + MIT (DOVER-Mobile)

Pipeline (all GPU-accelerated):

For each extracted frame (2fps), compute BRISQUE score on GPU via pyiqa batch inference
Compute Laplacian variance for blur detection via CuPy (GPU)
Run DOVER-Mobile for aesthetic + technical quality separation (GPU)
Aggregate per scene using CCCL 3.2 DeviceSegmentedReduce (GPU, up to 66x faster than CPU aggregation)
Classify each scene: good (avg > 60), acceptable (40-60), poor (< 40)
What The AI Receives (in VUD quality[] per scene):

```json
{
  "quality": [
    {
      "scene_id": "scene_003",
      "start_ms": 45000,
      "end_ms": 128000,
      "quality_avg": 78.5,
      "quality_min": 42.1,
      "blur_frames": 3,
      "blur_pct": 1.8,
      "classification": "good",
      "issues": []
    },
    {
      "scene_id": "scene_012",
      "start_ms": 720000,
      "end_ms": 755000,
      "quality_avg": 31.2,
      "quality_min": 12.4,
      "blur_frames": 48,
      "blur_pct": 68.6,
      "classification": "poor",
      "issues": ["heavy_blur", "camera_shake"]
    }
  ]
}
The AI reads classification and issues to avoid selecting low-quality segments for highlights. A segment with "classification": "poor" is never selected as a highlight regardless of its content score. quality_avg is used as a penalty factor in the highlight scoring formula.
```


### 3.5 Stream H: Shot Type Classification

Model: ResNet-50 fine-tuned on MovieShots dataset (46K shots from 7K movie trailers) VRAM: ~1-2GB Output: Shot type label per key frame (1 per scene) License: Open source (ResNet-50 weights are MIT/Apache)

Alternative (zero new models): SigLIP zero-shot classification with text prompts: ["extreme close-up of face", "close-up shot", "medium shot", "wide shot", "establishing shot"]. Less accurate but uses existing model.

Pipeline:

Extract one key frame per scene (from scene detection in Stream V)
Run ResNet-50 shot classifier on each key frame
Output: shot type label + confidence per scene
Shot Types:

| Shot Type | Description | Cropping Implication |
|:---|:---|:---|
| extreme_closeup | Face fills frame | No cropping needed for any aspect ratio |
| closeup | Head and shoulders | Safe for 9:16 with minimal reframe |
| medium | Waist up | Moderate cropping needed for 9:16; center on face |
| wide | Full body or room | Aggressive cropping for 9:16; may lose context. Consider keeping 16:9. |
| establishing | Location/environment | Do NOT crop to 9:16 — keep as 16:9 or use as B-roll |

What The AI Receives (in VUD scenes[].shot_type):

```json
{
  "id": "scene_003",
  "start_ms": 45000,
  "end_ms": 128000,
  "shot_type": "closeup",
  "shot_type_confidence": 0.91,
  "crop_recommendation": "safe_for_vertical"
}
The AI reads shot_type and crop_recommendation to decide cropping strategy per scene. For multi-scene clips with mixed shot types, the AI picks the crop strategy that works for the majority of frames, or uses dynamic crop (pan-and-scan for wide shots, center-face for close-ups).
```


### 3.6 Stream T: Transcript

Model: WhisperX (faster-whisper large-v3 + wav2vec2 forced alignment) — MANDATORY VRAM: ~3GB (Whisper) + ~0.5GB (wav2vec2 aligner) Output: Word-level timestamps with 20-50ms precision + text segments License: BSD-4-Clause (WhisperX)

WhisperX with wav2vec2 forced alignment achieves 20-50ms word-level timestamp precision. Combined with HTDemucs clean vocal stem input, this produces the most accurate word-level timestamps achievable with current open-source models. See Section 8.3 for implementation details.

Pipeline:

Extract audio track from video via FFmpeg (PCM 16kHz mono)
Run faster-whisper with word_timestamps=True (or WhisperX for millisecond precision)
Output: list of segments, each with start_ms, end_ms, text, and per-word timestamps
Detect language automatically (multilingual support)
Optional: WhisperX speaker diarization pass (supplements Stream K)
Segment Granularity:

Word-level: Individual words with start/end timestamps (for precise cuts)
Sentence-level: Natural sentence boundaries (for content segmentation)
Paragraph-level: Topic-coherent blocks (for chapter detection)
What The AI Receives (in VUD transcript):

```json
{
  "language": "en",
  "total_words": 12450,
  "total_segments": 847,
  "segments": [
    {
      "id": "seg_042",
      "start_ms": 185200,
      "end_ms": 192800,
      "text": "And that's when we realized the whole approach was fundamentally wrong.",
      "speaker": "speaker_1",
      "words": [
        {"word": "And", "start_ms": 185200, "end_ms": 185400},
        {"word": "that's", "start_ms": 185450, "end_ms": 185700},
        {"word": "when", "start_ms": 185750, "end_ms": 185950}
      ]
    }
  ]
}
This is the primary signal the AI uses for content-based editing. The AI reads the transcript like a script and identifies key quotes, arguments, topic transitions, and narrative arcs. Word-level timestamps enable precise cuts at sentence boundaries without cutting mid-word.
```


### 3.7 Stream S: Semantic Content

Model: nomic-ai/nomic-embed-text-v1.5 VRAM: ~0.5GB Output: 768-dim embedding per transcript segment

Pipeline:

Take transcript segments from Stream T
Prepend task prefix: search_document: {segment_text}
Run through Nomic Embed to produce 768-dim vectors
L2-normalize embeddings
Cluster segments by cosine similarity for topic detection
Uses:

Topic segmentation: detect when the conversation shifts subjects
Content search: find segments discussing specific topics
Highlight detection: identify segments with high semantic density (information-rich)
Duplicate detection: find repeated/redundant content across the video
What The AI Receives (in VUD topics[]):

```json
{
  "id": "topic_003",
  "start_ms": 420000,
  "end_ms": 1200000,
  "label": "Main Discussion: AI in Healthcare",
  "keywords": ["machine learning", "diagnosis", "clinical trials", "FDA approval"],
  "coherence_score": 0.87,
  "semantic_density": 0.72,
  "segment_ids": ["seg_042", "seg_043", "seg_044"]
}
The AI reads label (human-readable topic name, generated from clustering + transcript keywords), keywords (for understanding subject matter), and semantic_density (high = information-rich, good for highlights; low = filler). The AI never reads the 768-dim Nomic embeddings.
```


### 3.8 Stream E: Emotion/Energy

Model: wav2vec2 large (fine-tuned for emotion) or facebook/hubert-large-ll60k VRAM: ~1.5GB Output: 1024-dim embedding + scalar energy/arousal/valence per segment

Pipeline:

Segment audio into overlapping windows (5s windows, 2.5s stride)
Run through emotion model on GPU
Extract: arousal (energy level), valence (positive/negative), dominance
Compute per-segment emotion trajectory
Uses:

Energy curve: map the emotional arc of the video over time
Peak detection: find high-energy moments (enthusiasm, laughter, key points)
Valley detection: find low-energy sections (tangents, dead air, filler)
Emotional bookends: identify strong openings and closings for clips
What The AI Receives (in VUD emotion_curve[] and highlights[]):

```json
{
  "emotion_curve": [
    {"start_ms": 840000, "end_ms": 845000, "arousal": 0.91, "valence": 0.78, "energy": 0.94},
    {"start_ms": 845000, "end_ms": 850000, "arousal": 0.88, "valence": 0.82, "energy": 0.90}
  ],
  "highlights": [
    {
      "start_ms": 840000,
      "end_ms": 900000,
      "type": "high_energy",
      "score": 0.94,
      "reason": "Animated discussion about breakthrough results with rising energy and positive sentiment"
    }
  ]
}
The AI reads energy as a 0.0-1.0 score (high = engaging, low = filler), arousal (excitement level), valence (positive/negative), and highlights[].reason (natural language explanation of why this moment is notable). The AI uses these to find the best clips and to decide music mood. The AI never reads the 1024-dim Wav2Vec2 embeddings.
```


### 3.9 Stream K: Speaker Identification

Model: microsoft/wavlm-base-plus-sv VRAM: ~0.4GB Output: 512-dim X-vector per speech segment

Pipeline:

Run Voice Activity Detection (Silero VAD) to identify speech segments
Extract 512-dim speaker embeddings per segment
Cluster embeddings to identify unique speakers
Assign speaker labels to all transcript segments
Uses:

Speaker diarization: know who is speaking when
Speaker-specific clips: extract all segments from a specific speaker
Interview formatting: alternate speaker detection for split-screen edits
Solo-speaker detection: identify monologue vs. dialogue sections
What The AI Receives (in VUD speakers[] + transcript speaker field):

```json
{
  "speakers": [
    {"id": "speaker_0", "label": "Host", "total_speaking_ms": 1800000, "speaking_pct": 60.0},
    {"id": "speaker_1", "label": "Guest", "total_speaking_ms": 1200000, "speaking_pct": 40.0}
  ]
}
Plus every transcript.segments[].speaker field is set to "speaker_0" or "speaker_1". The AI reads labels and speaking percentages to understand the conversation dynamics. It uses the per-segment speaker assignment to create speaker-specific clips ("all segments where Guest is speaking") and to add appropriate lower thirds. The AI never reads the 512-dim WavLM X-vectors.
```


### 3.10 Stream A: Acoustic Features

Method: cuFFT (GPU) + CuPy for GPU-accelerated spectral analysis. VRAM: ~0.5 GB (cuFFT buffers) Output: Per-frame acoustic features

Features Extracted:

RMS Energy: Volume envelope over time
Spectral Centroid: Brightness/frequency content
Zero Crossing Rate: Noisiness vs. tonality
Onset Detection: Musical/rhythmic beat detection
Silence Detection: Gaps > 500ms flagged for potential cut points
Music vs. Speech Classification: Simple spectral analysis to detect background music sections
What The AI Receives (in VUD silence_gaps[] and acoustic):

```json
{
  "silence_gaps": [
    {"start_ms": 600000, "end_ms": 603500, "duration_ms": 3500, "type": "natural_break"},
    {"start_ms": 1245000, "end_ms": 1246200, "duration_ms": 1200, "type": "pause"}
  ],
  "acoustic": {
    "music_sections": [
      {"start_ms": 0, "end_ms": 5000, "type": "intro_music", "confidence": 0.92},
      {"start_ms": 3595000, "end_ms": 3600000, "type": "outro_music", "confidence": 0.88}
    ],
    "avg_volume_db": -18.5,
    "dynamic_range_db": 24.3
  }
}
The AI reads silence_gaps as candidate cut points (natural pauses where a cut won't feel jarring). It reads music_sections to know where existing music exists in the source (affects music generation decisions -- don't layer AI music on top of existing music). avg_volume_db and dynamic_range_db inform loudness normalization.
```


### 3.11 Stream R: Reactions (Laughter/Applause Detection)

Model: SenseVoice-Small (FunAudioLLM) VRAM: ~1.1GB Output: Timestamped audio event labels Speed: 70ms to process 10 seconds of audio (15x faster than Whisper-Large) License: Apache 2.0 (commercial OK)

Pipeline:

Feed vocal stem (from HTDemucs) to SenseVoice-Small
Model outputs audio event tags with timestamps: <Laughter>, <Applause>, <BGM>, <Speech>, <Cry>, <Breath>, <Cough>
Filter to editing-relevant events: laughter, applause
Compute confidence and duration for each event
Why this is critical for highlight detection: For podcasts, talks, comedy, interviews, and presentations, audience/participant reactions are the single strongest signal for "this moment is worth clipping." A laugh after a joke, applause after a key point, a gasp at a reveal — these are editing gold that no other stream captures. Wav2Vec2 (Stream E) detects general "high energy" but cannot distinguish laughter from excited speech from a music crescendo.

What The AI Receives (in VUD reactions[]):

```json
{
  "reactions": [
    {
      "start_ms": 845200,
      "end_ms": 848900,
      "type": "laughter",
      "confidence": 0.94,
      "duration_ms": 3700,
      "intensity": "strong",
      "context_transcript": "...and that's when we realized the data was upside down the whole time"
    },
    {
      "start_ms": 1205000,
      "end_ms": 1212000,
      "type": "applause",
      "confidence": 0.91,
      "duration_ms": 7000,
      "intensity": "moderate",
      "context_transcript": "So in conclusion, we proved it can be done in half the time"
    }
  ],
  "reaction_summary": {
    "total_laughter_events": 14,
    "total_applause_events": 3,
    "total_reaction_ms": 48200,
    "reaction_density": 0.013
  }
}
The AI reads reactions[] as high-confidence highlight markers. A transcript segment that immediately precedes a laughter event is very likely a good clip (joke → punchline → laugh). An applause event marks a strong segment ending. reaction_density (total reaction time / total video time) tells the AI how audience-reactive the content is overall — high density = lots of highlight candidates.
```

Integration with highlight scoring (updated formula):

highlight_score(segment) =
    0.25 * emotion_energy(segment)        +  // High energy = engaging
    0.20 * reaction_presence(segment)     +  // Laughter/applause = confirmed engagement
    0.20 * semantic_density(segment)      +  // Information-rich = valuable
    0.15 * narrative_completeness(segment) +  // Has beginning + end = satisfying
    0.10 * visual_variety(segment)        +  // Scene changes = dynamic
    0.05 * visual_quality(segment)        +  // Not blurry/shaky
    0.05 * speaker_confidence(segment)       // Clear speech = watchable

### 3.12 Stream B: Beat Detection

Model: Beat This! (GPU, Transformer + Convolution, state-of-the-art ISMIR 2024) VRAM: ~1-2 GB (GPU-accelerated, runs on CUDA Tensor Cores) Output: Beat timestamps (ms), downbeat timestamps (ms), estimated BPM License: Open source (check repo)

Pipeline:

Feed music stem (from HTDemucs) to Beat This! — if no music detected, feed full mix
Transformer model detects beat positions and downbeats on GPU
Estimate tempo (BPM) per section
Generate beat grid: array of millisecond timestamps where beats occur
Beat This! achieves state-of-the-art F1 scores (ISMIR 2024) and runs on GPU via the RTX 5090's Tensor Cores, processing a 4-hour audio track in seconds.

What The AI Receives (in VUD beats):

```json
{
  "beats": {
    "has_music": true,
    "source": "music_stem",
    "tempo_bpm": 120.4,
    "tempo_confidence": 0.88,
    "beat_positions_ms": [500, 1000, 1499, 1998, 2498, 2997],
    "downbeat_positions_ms": [500, 2498, 4496],
    "beat_count": 842,
    "sections": [
      {"start_ms": 0, "end_ms": 5000, "tempo_bpm": 120.4, "time_signature": "4/4"},
      {"start_ms": 3595000, "end_ms": 3600000, "tempo_bpm": 118.2, "time_signature": "4/4"}
    ]
  }
}
The AI uses beat_positions_ms as snap points for cut placement. When placing a cut, the AI finds the nearest beat timestamp and snaps to it for a professional cut-on-beat feel. downbeat_positions_ms (beat 1 of each measure) are preferred for major transitions. When the AI generates music via ACE-Step, the BPM from the beat grid can inform the music prompt: "120 BPM, matches existing beat".
```


### 3.13 Stream P: Profanity / Content Safety

Model: No new model required — post-processing on existing faster-whisper output VRAM: 0 GB Output: Profanity word timestamps + NSFW frame flags License: N/A (word list + logic)

Pipeline:

Match faster-whisper word-level transcript against a profanity word list (~4000 words, covers English profanity, slurs, sensitive terms)
For each match: record word, start_ms, end_ms, severity (mild/moderate/severe)
Optionally: run CLIP-based NSFW classifier (~20MB MLP on top of existing SigLIP embeddings) on key frames
Output: profanity timestamps for auto-bleep, NSFW frame flags for exclusion
What The AI Receives (in VUD content_safety):

```json
{
  "content_safety": {
    "profanity_events": [
      {"word": "[REDACTED]", "start_ms": 342100, "end_ms": 342500, "severity": "moderate"},
      {"word": "[REDACTED]", "start_ms": 891200, "end_ms": 891800, "severity": "severe"}
    ],
    "profanity_count": 7,
    "profanity_density": 0.002,
    "content_rating": "moderate",
    "nsfw_frames": [],
    "nsfw_frame_count": 0
  }
}
The AI uses profanity_events to: (1) auto-generate bleeped audio variants for family-friendly platforms, (2) avoid selecting profanity-heavy segments for platforms with strict content policies (LinkedIn), (3) add content warnings in metadata. content_rating gives a single-value summary: "clean", "mild", "moderate", "explicit".
```


### 3.14 Stream C: Chronemic (Temporal Dynamics)

Method: CuPy GPU-accelerated computation from Streams T, K, A. All array operations (WPM calculation, pause detection, variance computation, speaker change counting) run on GPU via CuPy with zero-copy PyTorch stream sharing (CUDA 13.2 Stream Protocol). VRAM: ~0.1 GB (CuPy buffers, negligible) Output: 4-dim vector per segment [pacing_wpm, pause_duration_ms, energy_variance, speaker_change_rate]

Pipeline:

From transcript: calculate words-per-minute per segment
From VAD: measure pause durations and silence patterns
From energy: compute variance of energy within segments
From speaker labels: track speaker change frequency
Uses:

Pacing analysis: fast sections vs. slow sections
Natural break points: long pauses indicate topic transitions
Energy rhythm: identify the "pulse" of the content
What The AI Receives (in VUD pacing[]):

```json
{
  "pacing": [
    {
      "start_ms": 420000,
      "end_ms": 480000,
      "words_per_minute": 165,
      "pause_ratio": 0.08,
      "speaker_changes": 4,
      "label": "fast_dialogue"
    },
    {
      "start_ms": 1800000,
      "end_ms": 1860000,
      "words_per_minute": 72,
      "pause_ratio": 0.35,
      "speaker_changes": 0,
      "label": "slow_monologue"
    }
  ]
}
The AI reads words_per_minute (high = dense/exciting, low = slow/potential filler), pause_ratio (high = lots of dead air), speaker_changes (high = dynamic conversation), and label (pre-classified: "fast_dialogue", "normal", "slow_monologue", "dead_air"). This directly informs filler detection and pacing decisions.
```


### 3.9 Temporal Alignment & Unified Timeline

All 7 streams are aligned to a unified millisecond timeline. The output is a single JSON structure called the Video Understanding Document (VUD) that the AI model uses to reason about the video.

```json
{
  "source": {
    "file": "podcast_ep42.mp4",
    "duration_ms": 3600000,
    "resolution": "3840x2160",
    "fps": 30,
    "codec": "h264",
    "audio_codec": "aac",
    "audio_channels": 2,
    "file_size_bytes": 4294967296
  },
  "streams": {
    "transcript": {
      "language": "en",
      "segments": [
        {
          "id": "seg_001",
          "start_ms": 1200,
          "end_ms": 5800,
          "text": "Welcome back to the show, today we're going to talk about...",
          "speaker": "speaker_0",
          "words": [
            {"word": "Welcome", "start_ms": 1200, "end_ms": 1600},
            {"word": "back", "start_ms": 1650, "end_ms": 1900}
          ]
        }
      ]
    },
    "scenes": [
      {
        "id": "scene_001",
        "start_ms": 0,
        "end_ms": 15000,
        "key_frame_path": "analysis/frames/frame_000000.jpg",
        "key_frame_timestamp_ms": 0,
        "visual_similarity_avg": 0.92,
        "dominant_colors": ["#2a2a2a", "#f5f5dc"],
        "face_detected": true,
        "face_position": {"x_center_pct": 0.48, "y_center_pct": 0.35},
        "shot_type": "medium",
        "quality_avg": 85.2,
        "crop_recommendation": "safe_for_vertical"
      }
    ],
    "speakers": [
      {"id": "speaker_0", "label": "Host", "total_speaking_ms": 1800000},
      {"id": "speaker_1", "label": "Guest", "total_speaking_ms": 1200000}
    ],
    "emotion_curve": [
      {"start_ms": 0, "end_ms": 5000, "arousal": 0.45, "valence": 0.72, "energy": 0.38}
    ],
    "topics": [
      {"id": "topic_001", "start_ms": 1200, "end_ms": 420000, "label": "Introduction", "keywords": ["welcome", "show", "today"]},
      {"id": "topic_002", "start_ms": 420000, "end_ms": 1200000, "label": "Main Discussion: AI in Healthcare"}
    ],
    "highlights": [
      {"start_ms": 840000, "end_ms": 900000, "type": "high_energy", "score": 0.94, "reason": "Animated discussion about breakthrough results"},
      {"start_ms": 1500000, "end_ms": 1560000, "type": "emotional_peak", "score": 0.88, "reason": "Personal story with audience engagement"}
    ],
    "silence_gaps": [
      {"start_ms": 600000, "end_ms": 603500, "duration_ms": 3500, "type": "natural_break"}
    ]
  },
  "analysis_metadata": {
    "total_frames_extracted": 7200,
    "total_scenes_detected": 47,
    "total_speakers": 2,
    "total_topics": 12,
    "processing_time_seconds": 180,
    "models_used": {
      "transcription": "faster-whisper-large-v3",
      "visual": "siglip-so400m-patch14-384",
      "semantic": "nomic-embed-text-v1.5",
      "emotion": "wav2vec2-large-emotion",
      "speaker": "wavlm-base-plus-sv"
    }
  },
  "provenance": {
    "source_file_sha256": "a3f74d2e1b8c9f5a6d3e7b2c4f1a9d8e5b3c7f2a6d4e8b1c9f5a3d7e2b4c6f",
    "vud_sha256": "9c4e7a2f1d6b3e8a5f2d7c4b9e1a6f3d8c5b2e7a4f9d1c6b3e8a5f2d7c4b9e",
    "pipeline_chain_hash": "7e4a2f9d1c6b3e8a5f2d7c4b9e1a6f3d8c5b2e7a4f9d1c6b3e8a5f2d7c4b9e",
    "total_provenance_records": 13,
    "stages_completed": ["probe", "extract_audio", "extract_frames", "transcribe",
                          "embed_visual", "detect_scenes", "embed_semantic", "detect_topics",
                          "embed_emotion", "embed_speakers", "analyze_acoustic",
                          "compute_chronemic", "synthesize_vud"],
    "models_used": {
      "transcription": {"name": "faster-whisper-large-v3", "version": "1.0.0", "quantization": "int8"},
      "visual": {"name": "siglip-so400m-patch14-384", "version": "1.0.0"},
      "semantic": {"name": "nomic-embed-text-v1.5", "version": "1.5.0"},
      "emotion": {"name": "wav2vec2-large-emotion", "version": "1.0.0"},
      "speaker": {"name": "wavlm-base-plus-sv", "version": "1.0.0"}
    },
    "total_processing_time_ms": 285000,
    "integrity_status": "verified"
  }
}
```

### 3.10 VRAM Budget

Concurrent model loading plan for RTX 5090 (32GB VRAM):

| Model | VRAM | Duration |
|:---|:---|:---|

With NVFP4 on RTX 5090 (CUDA 13.2) — all models fit concurrently:		
| Model | INT8 VRAM | NVFP4 VRAM | Phase |
|:---|:---|:---|:---|
| HTDemucs (source separation) | ~4.0 GB | ~2.0 GB | Audio separation |
| faster-whisper large-v3 | ~3.0 GB | ~1.5 GB | Transcription (on vocal stem) |
| SigLIP SO400M | ~1.2 GB | ~0.6 GB | Frame embedding |
| PaddleOCR PP-OCRv5 (mobile) | ~1.5 GB | ~0.75 GB | On-screen text detection |
| Nomic Embed v1.5 | ~0.5 GB | ~0.25 GB | Semantic embedding |
| Wav2Vec2 Large Emotion | ~1.5 GB | ~0.75 GB | Emotion analysis (on vocal stem) |
| WavLM Base Plus SV | ~0.4 GB | ~0.2 GB | Speaker embedding (on vocal stem) |
| SenseVoice-Small | ~1.1 GB | ~0.55 GB | Reaction detection |
| BRISQUE + DOVER-Mobile | ~1.9 GB | ~1.0 GB | Visual quality |
| ResNet-50 shot classifier | ~1.5 GB | ~0.75 GB | Shot type classification |
| Total (ALL concurrent at NVFP4) | — | ~8.4 GB | All models loaded simultaneously |
| Beat This! (beat detection) | ~2.0 GB | ~1.0 GB | GPU Transformer-based beat detection |
| cuFFT + CuPy (acoustic/chronemic) | ~0.5 GB | ~0.5 GB | GPU spectral analysis + pacing computation |
| FFmpeg NVENC/NVDEC | ~0.5 GB | ~0.5 GB | Dedicated silicon (outside SM budget) |
| Peak (ALL models concurrent at NVFP4) | — | ~10.4 GB | Leaves 21.6 GB free for frame buffers, batch processing, NVENC |

At NVFP4, the entire 12-stream understanding pipeline runs with ALL models loaded simultaneously in ~10.4 GB. No sequential loading, no model swapping, no VRAM juggling. Every operation runs on GPU — only profanity word matching and provenance hash computation use CPU (both trivially fast). This is the Blackwell + CUDA 13.2 advantage: NVFP4 delivers 87.5% VRAM savings over FP32 with <1% accuracy loss, CUDA Tile kernels run custom GPU operations in Python, CuPy enables zero-copy data sharing between PyTorch and CUDA, and CCCL 3.2 algorithms accelerate aggregation operations by up to 66x.

The AI (Claude Code) views frames directly via its multimodal context window — frame images are delivered alongside structured analytics through MCP tool responses.

Remaining VRAM headroom: ~20GB for batch processing, frame buffers, and the AI model itself if running locally.

Audio Generation Phase (runs after understanding models are unloaded):

| Model | VRAM | Duration |
|:---|:---|:---|
| ACE-Step v1.5 turbo-rl (cpu_offload) | ~4.0 GB | Music generation only |
| ACE-Step v1.5 turbo-rl (full GPU) | ~8.0 GB | Music generation only |
| ACE-Step v1.5 sft (high quality) | ~10.0 GB | Music generation only |
| MIDI/FluidSynth + DSP SFX | 0 GB (CPU) | Always available |
| Audio peak | ~10.0 GB | Only during music gen, models unloaded after |

Audio models are loaded on-demand and unloaded immediately after generation completes. They never compete with the understanding pipeline for VRAM.


### 3.11 GPU Compatibility Tiers

ClipCannon is designed for the RTX 5090 but supports any NVIDIA GPU with CUDA compute capability 7.0+. Features degrade gracefully based on available VRAM.

| Tier | VRAM | GPUs | Capabilities |
|:---|:---|:---|:---|
| Full (Blackwell) | 24-32 GB | RTX 5090, RTX 5080 | NVFP4: All models concurrent (~10.6 GB), CUDA Tile kernels, Green Contexts, 3 parallel NVENC renders, full 12-stream pipeline, ACE-Step at full speed |
| Full (Ada) | 24 GB | RTX 4090 | INT8/FP8: All models concurrent (~16 GB), CUDA Tile kernels (via 13.2), 2 parallel NVENC renders, full 12-stream pipeline |
| Standard | 12-16 GB | RTX 4070 Ti, RTX 3090, RTX 4080 | INT8: Sequential model loading, CUDA Tile kernels (via 13.2), single render stream, ACE-Step with cpu_offload |
| Minimal | 8 GB | RTX 4060, RTX 3070 | INT8: Whisper medium + SigLIP only, CUDA Tile kernels (via 13.2), MIDI/DSP audio fallback, no source separation |

Quantization Strategy for Lower-VRAM GPUs:

INT8 quantization on all embedding models (via CTranslate2 / ONNX Runtime)
FP4 quantization available on Blackwell GPUs (RTX 5090) via NVFP4 for ~70% memory reduction
WhisperX with large-v3-turbo (809M params, ~3GB INT8) on Standard tier for lower VRAM usage
small Whisper model (~2GB) on Minimal tier with acceptable accuracy tradeoff
Runtime Detection:

```python
def detect_gpu_tier():
    vram_gb = torch.cuda.get_device_properties(0).total_mem / (1024**3)
    compute_cap = torch.cuda.get_device_capability()
```

    if vram_gb >= 24:
        return "full"
    elif vram_gb >= 12:
        return "standard"
    elif vram_gb >= 8:
        return "minimal"
    else:
        raise RuntimeError(f"GPU has {vram_gb:.1f}GB VRAM. Minimum 8GB required.")

## 4. Video Editing Engine


### 4.1 Edit Decision List (EDL)

The AI model produces edits as an Edit Decision List -- a structured JSON document describing all operations to perform on the source video. The EDL is the contract between the AI's creative decisions and FFmpeg's execution.

```json
{
  "edl_version": "1.0",
  "source_file": "podcast_ep42.mp4",
  "output_id": "tiktok_highlight_01",
  "platform": "tiktok",
  "profile": "vertical_9x16_60s",
  "segments": [
    {
      "source_start_ms": 840000,
      "source_end_ms": 900000,
      "output_start_ms": 0,
      "transitions": {
        "in": {"type": "fade", "duration_ms": 500},
        "out": {"type": "fade", "duration_ms": 500}
      }
    }
  ],
  "transforms": {
    "crop": {"strategy": "center_face", "aspect_ratio": "9:16"},
    "speed": 1.0,
    "volume_normalize": true
  },
  "audio": {
    "background_music": {
      "source": "ai_generated",
      "prompt": "upbeat corporate podcast background, 110 BPM, positive energy, no vocals",
      "model": "ace-step-turbo",
      "duration_ms": 62000,
      "volume_db": -18,
      "fade_in_ms": 2000,
      "fade_out_ms": 3000,
      "duck_under_speech": true,
      "duck_level_db": -6
    },
    "sound_effects": [
      {
        "type": "transition_whoosh",
        "source": "programmatic_dsp",
        "trigger_ms": 0,
        "duration_ms": 500,
        "volume_db": -12,
        "params": {"sweep_hz_start": 200, "sweep_hz_end": 8000, "method": "logarithmic"}
      },
      {
        "type": "stinger_impact",
        "source": "programmatic_dsp",
        "trigger_ms": 500,
        "duration_ms": 300,
        "volume_db": -10,
        "params": {"decay_rate": 20, "noise_burst": true}
      }
    ],
    "intro_jingle": {
      "source": "midi_composition",
      "tempo_bpm": 120,
      "mood": "bright",
      "instrument": "electric_piano",
      "chord_progression": ["C", "G", "Am", "F"],
      "duration_ms": 4000,
      "volume_db": -14,
      "soundfont": "GeneralUser_GS.sf2"
    }
  },
  "overlays": {
    "captions": {
      "enabled": true,
      "style": "bold_centered",
      "font": "Montserrat-Bold",
      "font_size": 48,
      "color": "#FFFFFF",
      "stroke_color": "#000000",
      "stroke_width": 3,
      "position": "bottom_third",
      "words_per_line": 4,
      "animation": "word_highlight"
    },
    "watermark": null,
    "title_card": {
      "text": "This changed everything",
      "duration_ms": 2000,
      "position": "center",
      "animation": "fade_scale",
      "background_color": "#000000CC",
      "font": "Montserrat-Bold",
      "font_size": 64,
      "text_color": "#FFFFFF"
    },
    "lower_third": {
      "name": "Dr. Sarah Chen",
      "title": "AI Research Director",
      "start_ms": 2000,
      "duration_ms": 6000,
      "style": "slide_left",
      "template": "modern_bar",
      "primary_color": "#2563EB",
      "text_color": "#FFFFFF",
      "position": "bottom_left"
    },
    "animations": [
      {
        "type": "subscribe_cta",
        "template": "lottie",
        "asset_id": "subscribe_bounce_01",
        "start_ms": 55000,
        "duration_ms": 4000,
        "position": {"x": "right-120", "y": "bottom-200"},
        "scale": 0.8
      },
      {
        "type": "emoji_reaction",
        "template": "lottie",
        "asset_id": "fire_emoji_pop",
        "start_ms": 15000,
        "duration_ms": 2000,
        "position": {"x": "center", "y": "top+100"},
        "scale": 1.0
      }
    ],
    "progress_bar": {
      "enabled": true,
      "style": "thin_bottom",
      "color": "#2563EB",
      "height_px": 4,
      "position": "bottom"
    }
  },
  "metadata": {
    "title": "This changed everything about AI in healthcare",
    "description": "Dr. Sarah Chen reveals the breakthrough that nobody expected. Full episode link in bio.\n\n#AI #Healthcare #Technology #Podcast",
    "hashtags": ["AI", "Healthcare", "Technology", "Podcast", "Innovation"],
    "thumbnail_frame_ms": 845000
  }
}
```

### 4.2 Supported Edit Operations

| Category | Operation | Description | FFmpeg Implementation |
|:---|:---|:---|:---|
| Cuts | Trim | Extract time range from source | -ss {start} -to {end} |
| Cuts | Multi-segment join | Concatenate multiple non-contiguous segments | concat demuxer + filter_complex |
| Cuts | J-cut / L-cut | Audio leads or trails video at cut points | Separate audio/video stream timing |
| Transform | Crop to aspect ratio | Reframe for vertical/square/horizontal | crop=w:h:x:y filter |
| Transform | Smart crop (face-tracking) | Keep faces centered in frame | Face detection + dynamic crop |
| Transform | Speed change | Slow-mo or fast-forward sections | setpts, atempo filters |
| Transform | Resolution scaling | Upscale/downscale for platform | scale filter with lanczos |
| Audio | Volume normalization | Loudness normalization to platform spec | loudnorm filter (EBU R128) |
| Audio | Silence removal | Remove dead air sections | Trim based on VAD analysis |
| Audio | Music ducking | Lower background music under speech | Sidechain compression via filter |
| Audio | AI background music | Generate original background music from text prompt | ACE-Step model → pydub mix |
| Audio | MIDI composition | Deterministic music from tempo/mood/chords | MIDIUtil → FluidSynth → WAV |
| Audio | Transition SFX | Programmatic whooshes, risers, impacts, chimes | numpy/scipy DSP → WAV |
| Audio | AI sound effects | Text-described ambient/environmental audio | Stable Audio Open → WAV |
| Audio | Intro/outro jingle | Short musical ident from parameters | MIDI composition or ACE-Step |
| Audio | Audio crossfade | Smooth audio transition between segments | pydub crossfade or acrossfade |
| Overlay | Captions/subtitles | Burn-in animated word-by-word captions | drawtext or ASS subtitle burn |
| Overlay | Title cards | Animated intro/outro title slides | PyCairo frames → overlay filter |
| Overlay | Lower thirds | Animated name/title bar at bottom of frame | PyCairo/Lottie → overlay filter |
| Overlay | Progress bar | Add viewing progress indicator | drawbox with animation |
| Overlay | Logo/watermark | Brand overlay | overlay filter |
| Overlay | Subscribe CTA | Animated call-to-action pop-up | Lottie render → overlay filter |
| Overlay | Emoji reactions | Animated emoji pop-ups at key moments | Lottie render → overlay filter |
| Overlay | Callout/highlight | Arrow or box pointing to area of interest | PyCairo frames → overlay filter |
| Overlay | Social handle | Animated @username display | PyCairo frames → overlay filter |
| Transition | Fade in/out | Opacity fade at segment boundaries | fade filter |
| Transition | Crossfade | Dissolve between segments | xfade filter |
| Transition | Wipe (8 directions) | Directional reveal transitions | xfade=transition=wipeleft etc. |
| Transition | Slide (4 directions) | Slide-in/slide-out between clips | xfade=transition=slideleft etc. |
| Transition | Circle open/close | Circular iris transition | xfade=transition=circleopen |
| Transition | Pixelize | Pixelation dissolve | xfade=transition=pixelize |
| Transition | Radial | Clock-wipe style rotation | xfade=transition=radial |
| Transition | GL Shader | Custom GLSL shader transitions (60+ available) | xfade=transition=custom:expr= |
| Output | Encoding | Platform-optimized encoding | NVENC H.264/H.265, AAC |


### 4.3 Content-Aware Editing Strategies

The AI model receives the Video Understanding Document and applies editing strategies based on content type and target platform. These strategies guide the AI's creative decisions.


#### 4.3.1 Highlight Extraction (Short-Form)

Goal: Find the most engaging 15-60 second segments for Reels/TikTok/Shorts.

Scoring Formula (updated with reaction, quality, and beat signals):

highlight_score(segment) =
    0.25 * emotion_energy(segment)        +  // High energy = engaging (from vocal stem)
    0.20 * reaction_presence(segment)     +  // Laughter/applause = confirmed engagement (SenseVoice)
    0.20 * semantic_density(segment)      +  // Information-rich = valuable (Nomic Embed)
    0.15 * narrative_completeness(segment) +  // Has beginning + end = satisfying
    0.10 * visual_variety(segment)        +  // Scene changes = dynamic (SigLIP)
    0.05 * visual_quality(segment)        +  // Not blurry/shaky (BRISQUE/DOVER)
    0.05 * speaker_confidence(segment)       // Clear speech = watchable

    // Post-scoring adjustments:
    * quality_gate(segment)               // Multiply by 0 if quality_avg < 30 (reject poor footage)
    * profanity_penalty(segment)          // Reduce score for segments with severe profanity (platform-dependent)
Cut Point Selection:

Prefer cuts at sentence boundaries (from transcript)
Prefer cuts at scene boundaries (from visual stream)
Prefer cuts at silence gaps > 300ms (from acoustic stream)
Avoid cutting mid-word (use word-level timestamps)
Add 200ms padding before speech starts (room for fade-in)

#### 4.3.2 Topic Segmentation (Mid-Form)

Goal: Break a long video into topic-coherent chapters (2-10 minutes each).

Method:

Compute semantic embeddings for sliding windows (30s window, 15s stride)
Calculate cosine distance between adjacent windows
Topic boundaries = local maxima of semantic distance curve
Merge segments shorter than 2 minutes with their best neighbor
Generate chapter titles from transcript content

#### 4.3.3 Narrative Arc (Long-Form)

Goal: Create a polished long-form edit that removes filler while preserving story flow.

Method:

Identify and remove: long pauses, "um/uh" filler, repeated phrases, tangents
Preserve: key arguments, emotional peaks, narrative transitions
Maintain temporal ordering (no resequencing)
Apply J-cuts at topic transitions for smooth flow

### 4.4 Caption Generation

Captions are critical for social media engagement (85% of Facebook videos are watched with sound off).

Pipeline:

Use word-level timestamps from Whisper
Group into display chunks (3-5 words per line)
Apply platform-appropriate styling
Support word-by-word highlight animation (karaoke-style)
Render via FFmpeg drawtext or ASS subtitle burn-in
Caption Styles:

| Style | Description | Use Case |
|:---|:---|:---|
| bold_centered | Large bold text, centered bottom-third | TikTok, Reels |
| subtitle_bar | Semi-transparent bar with white text | LinkedIn, YouTube |
| word_highlight | Each word highlights as spoken | High engagement format |
| minimal | Small text, bottom-left | YouTube long-form |


### 4.5 AI Audio Generation Engine

ClipCannon generates all audio assets programmatically. No stock music licensing, no royalty fees, no copyright claims. The AI composes original background music, transition sound effects, stingers, jingles, and ambient beds -- all tailored to the content being edited.


#### 4.5.1 Architecture: 3-Tier Audio Generation

The audio engine uses three tiers, selected automatically based on the audio asset type:

| Tier | Engine | Use Case | Latency | Quality | License |
|:---|:---|:---|:---|:---|:---|
| 1: AI Model | ACE-Step v1.5 | Background music, mood-specific scores, genre tracks | 2-5s per minute of audio | 44.1kHz stereo, production quality | MIT (commercial OK) |
| 2: MIDI Composition | MIDIUtil + FluidSynth | Deterministic jingles, intro/outro idents, chord-driven beds | <1s | 44.1kHz stereo, SoundFont quality | MIT/LGPL (commercial OK) |
| 3: Programmatic DSP | numpy + scipy.signal | Whooshes, risers, impacts, chimes, transition stingers | <100ms | 44.1kHz, precise and repeatable | BSD (commercial OK) |

The AI model (Claude or other LLM connected via MCP) decides which tier to use for each audio asset based on the editing context. For example:

Full background music bed → Tier 1 (ACE-Step) for creative, unique compositions
Short repeatable jingle → Tier 2 (MIDI) for pixel-perfect timing and consistency
Transition whoosh between clips → Tier 3 (DSP) for instant, deterministic generation

#### 4.5.2 Tier 1: AI Music Generation (ACE-Step v1.5)

Model: ACE-Step v1.5 (MIT license, github.com/ace-step/ACE-Step) Architecture: Hybrid Language Model (Qwen3-based, 0.6B-4B params) + Diffusion Transformer (3.5B params) VRAM: Under 4GB with CPU offload; 8GB recommended for full speed Output: 44.1kHz stereo WAV Max Duration: 4+ minutes per generation Speed: RTX 5090 estimated ~1.5s per minute of audio; RTX 3090: ~4.7s per minute

Model Variants (shipped with ClipCannon):

| Variant | Steps | Speed | Quality | Best For |
|:---|:---|:---|:---|:---|
| acestep-v15-turbo-rl | 8 | Fastest | Best quality-to-speed ratio | Default for all music generation |
| acestep-v15-turbo | 8 | Very fast | Good | Quick previews |
| acestep-v15-sft | 50 | Slower | Highest quality | Final renders when quality is critical |

LoRA Fine-Tunes (shipped with ClipCannon):

| LoRA | Purpose |
|:---|:---|
| Text2Samples | Instrumental/background music without vocals -- default for video editing |
| RapMachine | Beat-driven music for energetic content |

Conditioning Parameters (all specified in the EDL audio.background_music object):

| Parameter | Type | Description | Example |
|:---|:---|:---|:---|
| prompt | string | Text description of desired music | "cinematic orchestral, slow tempo, emotional, no vocals" |
| duration_ms | int | Target duration in milliseconds | 60000 |
| model_variant | string | Which ACE-Step variant to use | "turbo-rl" |
| lora | string | Which LoRA to apply | "Text2Samples" |
| guidance_scale | float | How closely to follow the prompt (1.0-15.0) | 7.5 |
| seed | int | Reproducibility seed (same seed + prompt = same output) | 42 |

Prompt Engineering for Video Editing Music:

The AI model constructs ACE-Step prompts from the Video Understanding Document analysis:

Content energy: high → "upbeat, energetic, driving rhythm"
Content energy: low → "calm, ambient, atmospheric, minimal"
Content mood: positive → "bright, major key, warm"
Content mood: negative → "dark, minor key, tense"
Content type: interview → "soft background, conversational, unobtrusive"
Content type: highlight → "dramatic, cinematic, building intensity"
Platform: TikTok → "modern, trendy, bass-heavy, 120+ BPM"
Platform: LinkedIn → "corporate, professional, subtle, clean"
All prompts end with: "no vocals, instrumental only" (default for background music)
Why ACE-Step and not MusicGen: MusicGen (Meta) uses CC-BY-NC-4.0 license which prohibits commercial use of generated audio. ACE-Step uses MIT license -- all generated audio is fully commercially usable with zero licensing restrictions. ACE-Step also requires less VRAM (under 4GB vs 6-13GB) and generates faster (1.5s vs ~30s per minute on comparable hardware).

Fallback (No GPU available or VRAM exhausted): Fall back to Tier 2 (MIDI composition) which requires zero GPU.


#### 4.5.3 Tier 2: MIDI Composition Pipeline

For deterministic, repeatable audio that requires precise timing control (jingles, idents, chord-driven beds), ClipCannon uses an algorithmic MIDI composition pipeline:

Parameters (tempo, mood, genre, chords, duration)
    → music21 (generate theory-correct progression + melody)
    → MIDIUtil (write .mid file)
    → FluidSynth + SoundFont (render to 44.1kHz stereo WAV)
    → pydub (fade in/out, normalize, export)
Components:

| Component | Role | License | Install |
|:---|:---|:---|:---|
| music21 (v9.9+) | Music theory toolkit: key detection, voice leading, harmonic progressions | BSD-3 | pip install music21 |
| MIDIUtil | Create multi-track MIDI files from note/chord data | MIT | pip install MIDIUtil |
| FluidSynth + pyfluidsynth | Render MIDI to WAV using SF2 SoundFont instruments | LGPL-2.1 | apt install fluidsynth && pip install pyfluidsynth |

Shipped SoundFonts (stored in ~/.clipcannon/soundfonts/):

| SoundFont | Size | Instruments | Quality | Use Case |
|:---|:---|:---|:---|:---|
| GeneralUser_GS.sf2 | ~30MB | Full General MIDI set (128 instruments) | High | Default for all MIDI rendering |
| FluidR3_GM.sf2 | ~140MB | Full General MIDI, richer samples | Very High | When higher quality needed |

Mood-to-Chord Mapping (used by the AI to construct MIDI compositions):

| Mood | Typical Progressions | Tempo Range | Instruments |
|:---|:---|:---|:---|
| Bright/uplifting | I-V-vi-IV (C-G-Am-F) | 110-130 BPM | Piano, acoustic guitar, strings |
| Calm/reflective | I-vi-IV-V, I-iii-vi-IV | 70-90 BPM | Piano, pads, soft strings |
| Dramatic/tense | i-VI-III-VII (Am-F-C-G) | 80-100 BPM | Strings, brass, timpani |
| Corporate/professional | I-IV-V-I, I-ii-V-I | 100-120 BPM | Piano, light percussion |
| Energetic/fun | I-V-vi-IV with syncopation | 120-140 BPM | Electric piano, bass, drums |

EDL Specification (the AI writes this into the EDL audio.intro_jingle or audio.background_music object):

```json
{
  "source": "midi_composition",
  "tempo_bpm": 120,
  "key": "C_major",
  "mood": "bright",
  "chord_progression": ["C", "G", "Am", "F"],
  "bars": 8,
  "instruments": [
    {"channel": 0, "program": 0, "name": "piano", "role": "chords"},
    {"channel": 1, "program": 33, "name": "electric_bass", "role": "bass"},
    {"channel": 9, "program": 0, "name": "drums", "role": "rhythm"}
  ],
  "duration_ms": 16000,
  "volume_db": -16,
  "fade_in_ms": 500,
  "fade_out_ms": 2000,
  "soundfont": "GeneralUser_GS.sf2"
}
```
