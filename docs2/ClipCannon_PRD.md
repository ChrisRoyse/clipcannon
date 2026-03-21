
# PRD: AI-Native Video Editor MCP Server

Product Requirements Document
**Version: 5.0 Date: 2026-03-20 Product: ClipCannon (clipcannon.com) Author: Product Team**



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
                         |  |   (60+ MCP Tools)    |  |
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
The AI looks at the actual key frame image (delivered via clipcannon_get_vud with key frames). It sees what the scene looks like — no text description needed. The structured data provides quantitative signals: visual_similarity_avg (how visually stable), face_position (for smart cropping), shot_type and crop_recommendation (for aspect ratio decisions). The AI never reads the 1152-dim SigLIP embeddings — those are used internally for scene boundary computation.
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

#### 4.5.4 Tier 3: Programmatic DSP (Sound Effects)

For instant, deterministic, royalty-free sound effects, ClipCannon synthesizes audio using mathematical signal processing. These are generated in under 100ms with zero GPU usage.

Sound Effect Library (all generated at 44.1kHz, 16-bit):

| SFX Type | Method | Typical Duration | Parameters |
|:---|:---|:---|:---|
| Whoosh/swoosh | Logarithmic frequency chirp with exponential decay | 0.3-1.0s | sweep_hz_start, sweep_hz_end, decay_rate |
| Riser | Ascending chirp with increasing amplitude | 1.0-3.0s | start_hz, end_hz, method (linear/log) |
| Downer | Descending chirp with decreasing amplitude | 0.5-2.0s | start_hz, end_hz, decay_rate |
| Impact/hit | Noise burst with fast exponential decay | 0.1-0.5s | decay_rate, noise_type (white/pink) |
| Notification chime | Harmonically-related sine tones with decay | 0.3-1.0s | base_freq_hz, harmonics[], decay_rate |
| Subtle tick | Short click sound for UI-style transitions | 0.05-0.1s | freq_hz, attack_ms |
| Bass drop | Low-frequency sine sweep with resonance | 0.5-2.0s | start_hz, end_hz, resonance |
| Shimmer | High-frequency filtered noise with slow attack | 1.0-3.0s | filter_hz, attack_ms, decay_ms |
| Dramatic stinger | Impact + riser combined for scene transitions | 0.5-1.5s | impact_params, riser_params, mix_ratio |

Implementation (pure Python, no external dependencies beyond numpy/scipy):

```python
import numpy as np
from scipy.signal import chirp
from scipy.io import wavfile
```

SAMPLE_RATE = 44100

```python
def generate_whoosh(duration_s=0.5, start_hz=200, end_hz=8000, decay_rate=3.0):
    t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s))
    signal = chirp(t, f0=start_hz, f1=end_hz, t1=duration_s, method='logarithmic')
    envelope = np.exp(-decay_rate * t)
    return (signal * envelope * 0.8 * 32767).astype(np.int16)

def generate_impact(duration_s=0.3, decay_rate=20.0):
    samples = int(SAMPLE_RATE * duration_s)
    noise = np.random.randn(samples)
    envelope = np.exp(-decay_rate * np.linspace(0, 1, samples))
    return (noise * envelope * 0.8 * 32767).astype(np.int16)

def generate_chime(duration_s=0.5, base_freq=880, harmonics=[1.0, 0.5, 0.25]):
    t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s))
    signal = np.zeros_like(t)
    for i, amp in enumerate(harmonics):
        signal += amp * np.sin(2 * np.pi * base_freq * (i + 1) * t)
    envelope = np.exp(-5 * t)
    return (signal * envelope * 0.5 * 32767).astype(np.int16)

def generate_riser(duration_s=2.0, start_hz=100, end_hz=4000):
    t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s))
    signal = chirp(t, f0=start_hz, f1=end_hz, t1=duration_s, method='linear')
    envelope = np.linspace(0.3, 1.0, len(t))  # crescendo
    return (signal * envelope * 0.7 * 32767).astype(np.int16)
EDL Specification (the AI writes these into audio.sound_effects[]):

{
  "type": "transition_whoosh",
  "source": "programmatic_dsp",
  "trigger_ms": 0,
  "duration_ms": 500,
  "volume_db": -12,
  "params": {
    "sweep_hz_start": 200,
    "sweep_hz_end": 8000,
    "decay_rate": 3.0,
    "method": "logarithmic"
  }
}
```

#### 4.5.5 Audio Post-Processing Pipeline

All generated audio passes through a post-processing pipeline before being mixed into the final video:

Tools:

| Tool | Role | License |
|:---|:---|:---|
| pydub | Fade in/out, crossfade, volume adjustment, audio ducking, mixing, format conversion | MIT |
| pedalboard (Spotify) | Reverb, compression, EQ, limiting, professional audio effects | GPLv3 |
| librosa | Time stretching, pitch shifting (match music tempo to content pacing) | ISC |

Audio Ducking Pipeline (automatically lower music volume under speech):

1. Load generated background music (WAV from Tier 1, 2, or 3)
2. Load source audio track (speech from original video)
3. Run Silero VAD on source audio to detect speech segments
4. For each speech segment:
   a. Reduce music volume by duck_level_db (default: -6dB) starting 200ms before speech
   b. Ramp volume back up 300ms after speech ends
   c. Apply smooth fade on transitions (50ms cosine ramp) to prevent clicks
5. Mix ducked music with source audio
6. Apply loudnorm (EBU R128) to final mix
7. Export as 44.1kHz stereo WAV for FFmpeg muxing
Audio Mixing Order (layered from bottom to top):

Layer 1 (lowest): Background music bed (ducked under speech)
Layer 2: Source audio (speech, original audio from video)
Layer 3: Sound effects (whooshes, impacts at transition points)
Layer 4 (highest): Jingles/stingers (intro/outro, placed at specific times)
Final Mix → FFmpeg:

```bash
ffmpeg -i rendered_video_no_audio.mp4 -i final_audio_mix.wav \
  -c:v copy -c:a aac -b:a 192k -ar 44100 \
  -map 0:v:0 -map 1:a:0 \
  -movflags +faststart \
  output_with_audio.mp4
```

#### 4.5.6 AI Audio VRAM Budget

Audio models are loaded on-demand and unloaded after generation -- they are not kept resident like the understanding pipeline models.

| Model | VRAM | Duration | When Loaded |
|:---|:---|:---|:---|
| ACE-Step v1.5 turbo-rl (with cpu_offload) | ~4 GB | During music generation only | On clipcannon_generate_music call |
| ACE-Step v1.5 turbo-rl (full GPU) | ~8 GB | During music generation only | On clipcannon_generate_music call |
| ACE-Step v1.5 sft (high quality) | ~10 GB | During music generation only | When quality=high specified |
| MIDI/FluidSynth pipeline | 0 GB (CPU) | Always available | No GPU needed |
| DSP SFX generation | 0 GB (CPU) | Always available | No GPU needed |

Scheduling: The audio generation phase runs after the video understanding pipeline completes and understanding models are unloaded. This means the full 32GB VRAM is available for ACE-Step if needed. On lower-tier GPUs (8GB), cpu_offload=True is automatically enabled.


#### 4.5.7 AI-Composed vs. Pre-Built Audio Decision Matrix

The AI model uses this matrix to decide what type of audio to generate for each editing scenario:

| Scenario | Audio Type | Tier | Rationale |
|:---|:---|:---|:---|
| 60s TikTok highlight clip | Full background music | Tier 1 (ACE-Step) | Unique, mood-matched, engaging |
| 15s Instagram Reel | Short music bed | Tier 1 (ACE-Step, 15s) | Platform expects music |
| Podcast chapter (5-10 min) | Subtle ambient bed | Tier 2 (MIDI, long loop) | Unobtrusive, consistent |
| YouTube long-form edit | Intro jingle + ambient bed | Tier 2 (MIDI intro) + Tier 1 (ACE-Step bed) | Professional feel |
| Transition between clips | Whoosh/impact SFX | Tier 3 (DSP) | Instant, precise timing |
| LinkedIn professional clip | No music or very subtle | Tier 2 (minimal piano) or none | Platform expects restraint |
| Intro title card reveal | Stinger + shimmer | Tier 3 (DSP combined) | Punctuation, not distraction |
| High-energy moment | Dramatic riser → impact | Tier 3 (DSP riser + impact) | Build and release tension |
| End card / CTA screen | Outro jingle | Tier 2 (MIDI, branded feel) | Clean ending, professional |


### 4.6 Motion Graphics & Animation Engine

ClipCannon includes a multi-tier motion graphics system that provides the AI with a library of animated overlays: lower thirds, title cards, subscribe CTAs, emoji reactions, callout overlays, pop-ups, transitions, progress bars, and social media handles. These are rendered dynamically with custom text, colors, timing, and positioning -- not baked-in static assets.


#### 4.6.1 Architecture: 4-Tier Animation System

| Tier | Engine | Asset Types | Rendering | Quality |
|:---|:---|:---|:---|:---|
| 1: FFmpeg Native | drawtext, drawbox, overlay, xfade filters | Text titles, colored bars, progress indicators, basic transitions | Direct in FFmpeg filter graph | Good (basic shapes + text) |
| 2: PyCairo Frames | PyCairo vector rendering → PNG frames → FFmpeg overlay | Lower thirds, title cards, callouts, social handles, branded overlays | Python renders frames, FFmpeg composites | Professional (anti-aliased vectors, gradients) |
| 3: Lottie Library | rlottie-python rendering → PNG frames → FFmpeg overlay | Subscribe CTAs, emoji reactions, animated icons, complex animations | Lottie JSON → PNG frames → FFmpeg | High (After Effects-quality animations) |
| 4: Pre-Rendered WebM | WebM VP9 with alpha channel → FFmpeg overlay | Complex particle effects, fire/smoke, cinematic transitions, branded intros | Direct FFmpeg overlay of WebM with alpha | Highest (pre-rendered at any quality) |

Selection Logic: The AI picks the tier based on the complexity of the desired animation:

Simple text overlay → Tier 1 (zero overhead)
Styled lower third with animation → Tier 2 (fast, customizable)
Complex animated icon/CTA → Tier 3 (rich animation library)
Particle effects or cinematic transitions → Tier 4 (pre-rendered quality)

#### 4.6.2 Tier 1: FFmpeg Native Animations

These require zero additional dependencies -- they are filter expressions evaluated directly by FFmpeg during rendering.

Available FFmpeg Native Animations:

| Animation | FFmpeg Implementation | Description |
|:---|:---|:---|
| Text fade in/out | drawtext with alpha='if(lt(t,S),(t-S+D)/D, ...)' | Smooth opacity fade on text |
| Text slide in from left | drawtext with x='if(lt(t,S),-tw+(tw+X)*((t-A)/D),X)' | Horizontal text entry |
| Text slide up from bottom | drawtext with y='if(lt(t,S),h,(h-Y)*max(0,1-(t-S)/D)+Y)' | Vertical text entry |
| Text typewriter | drawtext with text= using substr() expression | Character-by-character reveal |
| Background bar | drawbox with animated width | Expanding colored bar behind text |
| Progress bar | drawbox with w='(t/D)*W' | Timeline progress indicator |

44+ transitions	xfade=transition=TYPE	Full list: fade, fadeblack, fadewhite, wipeleft, wiperight, wipeup, wipedown, slideleft, slideright, slideup, slidedown, smoothleft, smoothright, circlecrop, rectcrop, circleopen, circleclose, vertopen, vertclose, horzopen, horzclose, dissolve, pixelize, diagtl, diagtr, diagbl, diagbr, hlslice, hrslice, vuslice, vdslice, radial, squeezeh, squeezev, coverleft, coverright, coverup, coverdown, revealleft, revealright, revealup, revealdown, distance, zoomin
GL Transition Shaders (via xfade-easing, works with standard FFmpeg):

An additional 60+ transitions from the GL Transitions open-source collection (gl-transitions.com, MIT license) are available through the xfade=transition=custom:expr= syntax. The xfade-easing project (github.com/scriptituk/xfade-easing) transpiles GLSL shaders into FFmpeg custom expressions, adding transitions like: crosswarp, burn, directional-warp, swirl, mosaic, morph, cube-rotate, and many more -- plus 10 Robert Penner easing functions (quadratic, cubic, sinusoidal, elastic, bounce, etc.) that smooth the timing of any transition.

These are stored as expression files in ~/.clipcannon/transitions/ and referenced by name in the EDL.


#### 4.6.3 Tier 2: PyCairo Programmatic Animations

For styled, branded overlays that need custom text, colors, and smooth animation, ClipCannon renders PNG frame sequences using PyCairo and composites them with FFmpeg.

Pipeline:

1. AI specifies animation in EDL (type, text, colors, timing, style)
2. Python animation renderer calculates frame count from duration × fps
3. PyCairo renders each frame as RGBA PNG (transparent background)
4. Frames piped to FFmpeg via stdin or written to temp directory
5. FFmpeg composites frames over video using overlay filter with alpha
Built-In Animation Templates (PyCairo-rendered):

| Template ID | Description | Customizable Parameters | Animation |
|:---|:---|:---|:---|
| modern_bar | Solid color bar with name + title text | name, title, primary_color, text_color, width | Slide in from left, hold, slide out |
| glass_panel | Semi-transparent panel with blur effect | name, title, background_opacity, accent_color | Fade + scale in, hold, fade out |
| minimal_line | Thin accent line above name text | name, title, line_color, text_color | Line draws in, text fades in |
| bold_stack | Large name stacked above smaller title | name, title, colors, font_sizes | Pop in with overshoot bounce |
| corner_tag | Angled tag in bottom-left corner | name, title, tag_color | Diagonal slide in |
| title_center | Full-screen centered title text | title, subtitle, background_color, text_color | Scale + fade in, hold, scale + fade out |
| title_kinetic | Word-by-word reveal, centered | words[], colors, timing_ms[] | Each word pops in sequentially |
| chapter_marker | Chapter number + title in top-left | chapter_number, title, accent_color | Slide down from top |
| callout_arrow | Arrow pointing to coordinates with label | label, target_x, target_y, color | Arrow draws in, label fades in |
| social_handle | @username with platform icon | platform, username, icon_color | Slide in from right, pulse icon |

PyCairo Rendering Capabilities:

Anti-aliased vector graphics (crisp at any resolution)
Full font support via Pango integration (Google Fonts, system fonts)
Gradients (linear, radial)
Rounded rectangles, bezier curves, arbitrary shapes
Drop shadows, glow effects (via gaussian blur on duplicate layer)
Alpha transparency on all elements
Sub-pixel positioning for smooth animation
Example: Lower Third Rendering:

```python
import cairo
import math

def render_lower_third_frame(frame_num, fps, width, height, name, title, color):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    t = frame_num / fps
    # Animation: slide in from left over 0.4s, hold, slide out over 0.3s
    anim_in_end = 2.4   # appears at t=2.0, fully in by t=2.4
    anim_out_start = 8.0
    anim_out_end = 8.3
    if t < 2.0 or t > anim_out_end:
        return surface  # transparent frame
    # Calculate x offset with ease-out
    if t < anim_in_end:
        progress = (t - 2.0) / 0.4
        progress = 1 - (1 - progress) ** 3  # ease-out cubic
        x_offset = -400 + 400 * progress
    elif t > anim_out_start:
        progress = (t - anim_out_start) / 0.3
        progress = progress ** 3  # ease-in cubic
        x_offset = -400 * progress
    else:
        x_offset = 0
    # Draw background bar
    bar_x = 40 + x_offset
    bar_y = height - 140
    ctx.set_source_rgba(*color, 0.85)
    rounded_rect(ctx, bar_x, bar_y, 360, 100, 8)
    ctx.fill()
    # Draw name text
    ctx.select_font_face("Montserrat", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(28)
    ctx.set_source_rgba(1, 1, 1, 1)
    ctx.move_to(bar_x + 20, bar_y + 38)
    ctx.show_text(name)
    # Draw title text
    ctx.set_font_size(18)
    ctx.set_source_rgba(1, 1, 1, 0.8)
    ctx.move_to(bar_x + 20, bar_y + 68)
    ctx.show_text(title)
    return surface
```

#### 4.6.4 Tier 3: Lottie Animation Library

ClipCannon ships with a curated set of Lottie JSON animations and can access the 100,000+ free animations on LottieFiles.com (Lottie Simple License: free commercial use, no attribution required).

Rendering Pipeline:

1. Load Lottie JSON file
2. rlottie-python renders each frame to Pillow Image (RGBA, transparent background)
3. Save frames as PNG sequence (or pipe directly to FFmpeg)
4. FFmpeg composites PNG sequence over video:
```bash
   ffmpeg -i video.mp4 -framerate 30 -i frame_%04d.png \
     -filter_complex "[0][1]overlay=x=X:y=Y:enable='between(t,START,END)'" \
     -c:v libx264 output.mp4
Rendering Library: rlottie-python (pip install rlottie-python)
```

Wraps Samsung's rlottie C library via ctypes
Pre-compiled binaries in wheel -- no external C dependencies
Renders individual frames via render_pillow_frame(frame_num) or save_frame(path, frame_num)
Supports resolution-independent rendering (Lottie is vector-based: render at 1080p, 4K, or any size)
MIT license
Shipped Lottie Asset Pack (stored in ~/.clipcannon/assets/lottie/):

| Category | Asset IDs | Count | Description |
|:---|:---|:---|:---|
| Subscribe CTAs | subscribe_bounce_01 through _05 | 5 | Animated "Subscribe" / "Follow" buttons |
| Like/Heart | heart_pop_01 through _03 | 3 | Heart animation, tap-to-like style |
| Emoji Reactions | fire_emoji_pop, laugh_emoji, mind_blown, clap_emoji, 100_emoji | 5 | Animated emoji pop-ups |
| Arrows/Pointers | arrow_bounce_down, arrow_circle, swipe_up | 3 | Directional indicators |
| Loading/Progress | loading_dots, checkmark_success | 2 | Status indicators |
| Social Icons | icon_youtube, icon_instagram, icon_tiktok, icon_linkedin, icon_twitter | 5 | Animated platform icons |
| Decorative | sparkle_burst, confetti_pop, star_spin | 3 | Celebration/emphasis effects |
| Notification | bell_ring, new_badge | 2 | Alert-style animations |

Total shipped assets: ~28 Lottie animations (~50KB each = ~1.4MB total)

Dynamic Asset Fetching (optional, requires internet):

When the AI requests an animation not in the shipped pack, ClipCannon can download from LottieFiles.com:

Search LottieFiles API with descriptive query (e.g., "thumbs up animated")
Download Lottie JSON to ~/.clipcannon/assets/lottie/cache/
Render and composite as normal
Cache locally for future use
This is opt-in (disabled by default for fully-offline operation). Configured via clipcannon_config_set animation.fetch_remote true.


#### 4.6.5 Tier 4: Pre-Rendered WebM Asset Pack

For effects that are too complex for real-time generation (particle systems, cinematic light leaks, smoke, fire, bokeh overlays), ClipCannon ships a curated pack of pre-rendered WebM videos with alpha transparency.

Format: WebM VP9 with yuva420p pixel format (alpha channel) Resolution: 1920x1080 at 30fps Compositing: FFmpeg overlay filter handles alpha transparency natively

```bash
ffmpeg -i background.mp4 -c:v libvpx-vp9 -i overlay_alpha.webm \
  -filter_complex "[0][1]overlay=x=0:y=0:enable='between(t,2,7)'" \
  -c:v libx264 -pix_fmt yuv420p output.mp4
Shipped WebM Asset Pack (stored in ~/.clipcannon/assets/webm/):
```

| Category | Count | Duration | Approx Size Each | Description |
|:---|:---|:---|:---|:---|
| Light leaks | 5 | 3-5s | ~600KB | Warm/cool light flares for transitions |
| Bokeh overlays | 3 | 5-8s (loopable) | ~800KB | Defocused light circles |
| Film grain | 2 | 5s (loopable) | ~400KB | Subtle film texture overlay |
| Glitch effects | 3 | 1-2s | ~300KB | Digital glitch for dynamic transitions |
| Particle rise | 3 | 3-5s | ~500KB | Rising particles/dust for drama |
| Smoke/fog | 2 | 5s (loopable) | ~700KB | Atmospheric haze |
| Confetti burst | 2 | 3s | ~400KB | Celebration overlay |

Total shipped WebM pack: ~20 assets, ~11MB total

Expanding the Asset Library:

Users can add custom WebM overlays to ~/.clipcannon/assets/webm/custom/. Requirements:

WebM VP9 codec with alpha (yuva420p)
1080p resolution (auto-scaled if different)
30fps (auto-resampled if different)
Named with descriptive ID: category_description_variant.webm

#### 4.6.6 Animation EDL Specification

The AI writes animation instructions into the EDL overlays.animations[] array and overlays.lower_third / overlays.title_card objects. The rendering pipeline reads these and applies them in order.

Full Animation Object Schema:

```json
{
  "type": "subscribe_cta | emoji_reaction | callout | social_handle | light_leak | custom",
  "template": "lottie | pycairo | webm | ffmpeg_native",
  "asset_id": "subscribe_bounce_01",
  "start_ms": 55000,
  "duration_ms": 4000,
  "position": {
    "x": "left+40 | center | right-120 | 500",
    "y": "top+100 | center | bottom-200 | 300"
  },
  "scale": 0.8,
  "opacity": 1.0,
  "z_index": 10,
  "params": {}
}
Lower Third Object Schema:

{
  "name": "Dr. Sarah Chen",
  "title": "AI Research Director",
  "start_ms": 2000,
  "duration_ms": 6000,
  "style": "slide_left | fade | pop_bounce | minimal_line",
  "template": "modern_bar | glass_panel | minimal_line | bold_stack | corner_tag",
  "primary_color": "#2563EB",
  "secondary_color": "#1E40AF",
  "text_color": "#FFFFFF",
  "font": "Montserrat",
  "position": "bottom_left | bottom_right | bottom_center",
  "animation_in_ms": 400,
  "animation_out_ms": 300,
  "easing": "ease_out_cubic"
}
Title Card Object Schema:

{
  "text": "This changed everything",
  "subtitle": "The story behind the breakthrough",
  "duration_ms": 3000,
  "position": "center | top_third | bottom_third",
  "animation": "fade_scale | slide_up | typewriter | kinetic_words",
  "background_color": "#000000CC",
  "font": "Montserrat-Bold",
  "font_size": 64,
  "subtitle_font_size": 28,
  "text_color": "#FFFFFF",
  "accent_color": "#2563EB",
  "animation_in_ms": 600,
  "hold_ms": 1800,
  "animation_out_ms": 600
}
```

#### 4.6.7 Animation Rendering Pipeline (Integrated with Video Render)

```
ANIMATION RENDER (part of clipcannon_render)
=============================================
```

1. PARSE EDL ANIMATIONS (CPU, <100ms)
```
   └─> Extract all overlay/animation objects from EDL
   └─> Sort by z_index and start_ms

2. RENDER TIER 1: FFmpeg Native (CPU, <1s)
   └─> Build drawtext/drawbox filter expressions for FFmpeg native animations
   └─> Append to main FFmpeg filter_complex graph

3. RENDER TIER 2: PyCairo Frames (CPU, ~2-5s per animation)
   └─> For each PyCairo animation: render PNG frame sequence
   └─> Store in temp directory: /tmp/clipcannon/{edit_id}/anim_{id}/frame_%04d.png

4. RENDER TIER 3: Lottie Frames (CPU, ~1-3s per animation)
   └─> For each Lottie animation: render via rlottie-python
   └─> Store in temp directory: /tmp/clipcannon/{edit_id}/lottie_{id}/frame_%04d.png

5. BUILD COMPOSITE FILTER GRAPH (CPU, <100ms)
   └─> Chain overlay filters for each animation layer:
       [base][anim0]overlay=x=X:y=Y:enable='between(t,S,E)'[v0];
       [v0][anim1]overlay=x=X:y=Y:enable='between(t,S,E)'[v1];
       ...

6. GENERATE AUDIO MIX (CPU/GPU, ~5-30s)
   └─> Generate all audio assets (music, SFX) per Section 4.5
   └─> Mix with source audio via pydub
   └─> Export final audio WAV
```

7. FINAL RENDER (GPU NVENC, ~10-30s)
```
   └─> Execute full FFmpeg filter graph with:
       - Video input (source segments)
       - All overlay inputs (PNG sequences, WebM files)
       - Audio input (mixed WAV)
   └─> NVENC encode to final output
```

## 5. Platform Profiles


### 5.1 Platform-Specific Requirements

Each platform has strict technical requirements AND content style preferences. ClipCannon encodes to the right specs AND the AI uses the content strategy guidance to make editing decisions (clip length, pacing, music, overlays, caption style) that are native to each platform.

The AI reads platform profiles when deciding HOW to edit, not just what resolution to render at.


#### 5.1.1 TikTok

Technical Specs:

| Parameter | Specification |
|:---|:---|
| Aspect Ratio | 9:16 (vertical) -- mandatory for reach |
| Resolution | 1080x1920 |
| Duration | 15-60 seconds (sweet spot for algorithm) |
| File Size | Max 287.6 MB (iOS), 72 MB (Android), 500 MB (web) |
| Codec | H.264, MP4 |
| Frame Rate | 30fps |
| Audio | AAC, 44.1kHz, stereo |
| Bitrate | 8 Mbps |
| Captions | Burned-in (algorithm favors text-on-screen) |

Content Strategy (AI reads this when editing for TikTok):

| Principle | Guidance for AI |
|:---|:---|
| Hook in first 3 seconds | The clip MUST open with the most attention-grabbing moment. Do NOT start with "so..." or filler. Lead with the punchline, surprising statement, or boldest claim. If the best moment is at 14:32 in the source, that becomes second 0 of the TikTok. |
| Pacing | Fast. Cut dead air aggressively. Remove all pauses > 500ms. Target 150+ WPM. Jump cuts between sentences are expected and encouraged. |
| Music | Required. Trending-style, bass-heavy, 120+ BPM. Music should be audible throughout, not just background. Duck under speech to -6dB, but keep it present. |
| Captions | Bold, centered, word-by-word highlight animation (bold_centered style). Large font (48px+). High contrast (white on black stroke). Captions are not optional -- they are a primary engagement driver. |
| Transitions | Quick cuts (no fade). Occasional zoom-in transition on key moments. Avoid slow dissolves. |
| Overlays | Emoji reactions on key moments. Subscribe CTA in final 5 seconds. Progress bar at bottom. |
| Tone | Energetic, direct, conversational. LinkedIn-style professionalism actively hurts reach. |
| Hashtags | 3-5 relevant hashtags in description. Include 1-2 trending/broad tags. |


#### 5.1.2 Instagram Reels

Technical Specs:

| Parameter | Specification |
|:---|:---|
| Aspect Ratio | 9:16 (Reels), 1:1 (Feed), 4:5 (Feed preferred) |
| Resolution | 1080x1920 (Reels), 1080x1350 (Feed 4:5), 1080x1080 (Square) |
| Duration | Reels: 15-60 seconds. Stories: 15 seconds. Feed: 30-60 seconds |
| File Size | Max 650 MB |
| Codec | H.264, MP4 |
| Frame Rate | 30fps |
| Audio | AAC, 44.1kHz |
| Bitrate | 6 Mbps |
| Captions | Burned-in strongly recommended |
| Cover Image | 1080x1920 for Reels |

Content Strategy (AI reads this when editing for Instagram):

| Principle | Guidance for AI |
|:---|:---|
| Aesthetic first | Instagram is visual. Clips should look polished. Use light leak overlays, subtle color grading feel. Avoid raw/unfinished look. |
| Hook in 2 seconds | Even faster than TikTok. The first frame should be visually compelling. |
| Music | Music-driven. Rhythm should align with cuts (cut on beat if possible). Trendy, modern, slightly less bass-heavy than TikTok. |
| Captions | Styled, on-brand. word_highlight style preferred. Consistent font and colors across all Reels from same source. |
| Length | 30-45 seconds is the sweet spot for Reels. Under 15s feels too short. Over 60s loses retention. |
| Transitions | Smooth. Use slide or dissolve transitions between segments. Avoid jarring jump cuts. |
| CTA | "Follow for more" in final 3 seconds. Subtler than TikTok. |


#### 5.1.3 YouTube

YouTube has TWO distinct formats that require completely different editing:

YouTube Shorts (Vertical):

| Parameter | Specification |
|:---|:---|
| Aspect Ratio | 9:16 (vertical) |
| Resolution | 1080x1920 |
| Duration | Up to 3 minutes (60 seconds optimal) |
| Codec | H.264, MP4 |
| Frame Rate | 30fps |
| Audio | AAC, 48kHz, stereo |
| Bitrate | 8 Mbps |
| Hashtag | Include #Shorts in title or description |

YouTube Standard (Landscape):

| Parameter | Specification |
|:---|:---|
| Aspect Ratio | 16:9 (landscape) -- this is the canonical YouTube format |
| Resolution | 1920x1080 (1080p) or 3840x2160 (4K) |
| Duration | 3-20 minutes (8-12 min optimal for ad revenue) |
| File Size | Max 256 GB |
| Codec | H.264 (recommended), H.265, VP9, AV1 |
| Frame Rate | 30fps (standard), 60fps (premium) |
| Audio | AAC-LC, 48kHz, stereo |
| Bitrate | 12 Mbps (1080p60), 35-45 Mbps (4K) |
| Chapters | Supported via description timestamps |
| Subtitles | SRT/VTT upload (preferred over burned-in) |

Content Strategy -- Shorts (AI reads this):

| Principle | Guidance for AI |
|:---|:---|
| Similar to TikTok | Fast-paced, hook-first, burned-in captions. |
| But more informational | YouTube Shorts audience expects to learn something. Lead with "insight" rather than "entertainment". |
| Captions | Required. Bold centered style. |
| Music | Optional. If used, more subtle than TikTok. |

Content Strategy -- Standard/Long-Form (AI reads this):

| Principle | Guidance for AI |
|:---|:---|
| Retention over hook | YouTube rewards watch time, not initial click. The edit should remove filler and tangents but preserve the complete narrative arc. Do NOT resequence -- maintain temporal order. |
| Chapter markers | Generate chapter timestamps for the description. One per topic segment. Format: 00:00 Introduction\n02:15 Main Topic\n08:30 Key Insight |
| Intro + Outro | Add a 3-5 second title card intro. Add an end card with subscribe CTA for final 10 seconds. |
| Lower thirds | Add lower thirds for each speaker on first appearance. Professional glass_panel or minimal_line template. |
| Captions | SRT/VTT file uploaded separately (NOT burned in). YouTube has native caption support and this helps search/SEO. |
| Music | Subtle ambient background only. Duck heavily under speech (-8dB). No music during dialogue-heavy sections. Use MIDI composition (Tier 2) for intro/outro jingle. |
| Pacing | Moderate. Remove pauses > 2 seconds and filler words, but don't remove natural breathing room. Target 120-140 WPM. |
| Transitions | Minimal. Simple cuts at scene/sentence boundaries. Crossfade at topic transitions only. |
| Aspect ratio | 16:9 at 1920x1080 minimum. 3840x2160 (4K) if source supports it. |
| Tone | Polished but authentic. Not over-produced. |


#### 5.1.4 Facebook

Note: As of June 2025, all Facebook videos are Reels.

Technical Specs:

| Parameter | Specification |
|:---|:---|
| Aspect Ratio | 9:16 (Reels) preferred, 16:9, 1:1, 4:5 also accepted |
| Resolution | 1080x1920 |
| Duration | 15-60 seconds optimal |
| File Size | Max 4 GB |
| Codec | H.264, MP4/MOV |
| Frame Rate | 30fps |
| Audio | AAC, stereo, 128kbps+ |
| Captions | Burned-in or SRT upload |

Content Strategy (AI reads this):

| Principle | Guidance for AI |
|:---|:---|
| Similar to Instagram Reels | Facebook Reels share the same algorithm. Edit similarly to Instagram. |
| Slightly older demographic | Less trend-chasing. Content can be slightly slower-paced than TikTok. |
| Text overlays work well | Facebook audiences engage with text-heavy content. Use larger captions, title cards. |
| Share-friendly | Content that people want to share with friends performs well. Pull emotional or surprising quotes. |


#### 5.1.5 LinkedIn

Technical Specs:

| Parameter | Specification |
|:---|:---|
| Aspect Ratio | 1:1 (square) recommended for feed, 16:9 for landscape, 9:16 supported |
| Resolution | 1080x1080 (1:1), 1920x1080 (16:9) |
| Duration | 30 seconds to 3 minutes optimal |
| File Size | Max 5 GB |
| Codec | H.264, MP4 |
| Frame Rate | 30fps |
| Audio | AAC or MP3, 64kbps+ |
| Bitrate | 5 Mbps |

Content Strategy (AI reads this):

| Principle | Guidance for AI |
|:---|:---|
| Professional tone is mandatory | No flashy effects, no emoji reactions, no trending sounds. Clean, polished, authoritative. |
| Square (1:1) is the default | LinkedIn feed is desktop-heavy. Square video takes up more feed real estate than vertical. Only use 9:16 for mobile-first content. |
| Insight-led | Open with a key insight or data point, not entertainment. "Here's what we learned..." not "You won't believe..." |
| Lower thirds | Required. Show name + title for all speakers. Use minimal_line or glass_panel template. Corporate colors. |
| Captions | subtitle_bar style (semi-transparent bar). Professional appearance. Burned-in (many watch on mute at work). |
| Music | Very subtle or none. If used, corporate/professional piano or ambient. -20dB under speech. MIDI Tier 2 composition only (no AI-generated music with personality). |
| No CTAs | No "subscribe" or "follow" animations. No emoji reactions. No progress bars. |
| Duration | 60-90 seconds optimal. Under 30s feels incomplete. Over 3 minutes loses attention. |
| Transitions | Simple cuts and fades only. No wipes, slides, or effects. |


### 5.2 Platform Decision Matrix (AI Reference)

When the AI receives a platform target, it uses this matrix to configure all editing decisions:

| Decision | TikTok (9:16) | Instagram Reels (9:16) | YouTube Shorts (9:16) | YouTube Standard (16:9) | Facebook Reels (9:16) | LinkedIn (1:1) |
|:---|:---|:---|:---|:---|:---|:---|
| Aspect ratio | 9:16 | 9:16 | 9:16 | 16:9 | 9:16 | 1:1 |
| Resolution | 1080x1920 | 1080x1920 | 1080x1920 | 1920x1080 (or 3840x2160) | 1080x1920 | 1080x1080 |
| Duration target | 30-60s | 30-45s | 30-60s | 5-15 min | 30-60s | 60-90s |
| Hook urgency | 3 seconds | 2 seconds | 3 seconds | 10 seconds | 3 seconds | 5 seconds |
| Pacing (WPM) | 150+ | 140+ | 145+ | 120-140 | 135+ | 120-130 |
| Music | Required, 120+ BPM | Required, modern | Optional, subtle | Subtle ambient only | Required, moderate | Very subtle or none |
| Music volume | -6dB ducked | -6dB ducked | -8dB ducked | -10dB ducked (or muted under speech) | -6dB ducked | -20dB or none |
| Caption style | bold_centered | word_highlight | bold_centered | SRT file (not burned in) | bold_centered | subtitle_bar |
| Lower thirds | No (wastes screen space) | No | No | Yes (all speakers) | No | Yes (all speakers) |
| Title card | No (skip to content) | Optional (1s max) | No | Yes (3-5s intro) | Optional (1s max) | Yes (2-3s) |
| Subscribe CTA | Yes (final 5s) | Yes (final 3s) | Yes (final 5s) | Yes (end card 10s) | No | No |
| Emoji reactions | Yes | Subtle | Yes | No | Occasionally | Never |
| Transitions | Jump cut | Smooth slide/dissolve | Jump cut | Simple cut + crossfade at topics | Slide | Simple cut + fade |
| Progress bar | Yes | Optional | Yes | No | Optional | No |
| Crop strategy | center_face | center_face | center_face | No crop (keep 16:9) | center_face | center_face to square |


### 5.3 Output Encoding Profiles

Pre-configured FFmpeg encoding profiles per platform:

PROFILES = {
  "tiktok_vertical": {
    "resolution": "1080x1920",
    "codec": "h264_nvenc",
    "preset": "p4",
    "bitrate": "8M",
    "maxrate": "10M",
    "bufsize": "20M",
    "fps": 30,
    "audio_codec": "aac",
    "audio_bitrate": "192k",
    "audio_sample_rate": 44100,
    "pixel_format": "yuv420p",
    "container": "mp4",
    "movflags": "+faststart"
  },
  "instagram_reel": {
    "resolution": "1080x1920",
    "codec": "h264_nvenc",
    "preset": "p4",
    "bitrate": "6M",
    "maxrate": "8M",
    "bufsize": "16M",
    "fps": 30,
    "audio_codec": "aac",
    "audio_bitrate": "192k",
    "audio_sample_rate": 44100,
    "pixel_format": "yuv420p",
    "container": "mp4",
    "movflags": "+faststart"
  },
  "youtube_standard": {
    "resolution": "1920x1080",
    "codec": "h264_nvenc",
    "preset": "p5",
    "bitrate": "12M",
    "maxrate": "15M",
    "bufsize": "30M",
    "fps": 30,
    "audio_codec": "aac",
    "audio_bitrate": "256k",
    "audio_sample_rate": 48000,
    "pixel_format": "yuv420p",
    "container": "mp4",
    "movflags": "+faststart"
  },
  "youtube_short": {
    "resolution": "1080x1920",
    "codec": "h264_nvenc",
    "preset": "p4",
    "bitrate": "8M",
    "maxrate": "10M",
    "bufsize": "20M",
    "fps": 30,
    "audio_codec": "aac",
    "audio_bitrate": "192k",
    "audio_sample_rate": 48000,
    "pixel_format": "yuv420p",
    "container": "mp4",
    "movflags": "+faststart"
  },
  "youtube_4k": {
    "resolution": "3840x2160",
    "codec": "h264_nvenc",
    "preset": "p5",
    "bitrate": "40M",
    "maxrate": "45M",
    "bufsize": "90M",
    "fps": 30,
    "audio_codec": "aac",
    "audio_bitrate": "256k",
    "audio_sample_rate": 48000,
    "pixel_format": "yuv420p",
    "container": "mp4",
    "movflags": "+faststart"
  },
  "linkedin_square": {
    "resolution": "1080x1080",
    "codec": "h264_nvenc",
    "preset": "p4",
    "bitrate": "5M",
    "maxrate": "7M",
    "bufsize": "14M",
    "fps": 30,
    "audio_codec": "aac",
    "audio_bitrate": "192k",
    "audio_sample_rate": 44100,
    "pixel_format": "yuv420p",
    "container": "mp4",
    "movflags": "+faststart"
  },
  "facebook_reel": {
    "resolution": "1080x1920",
    "codec": "h264_nvenc",
    "preset": "p4",
    "bitrate": "6M",
    "maxrate": "8M",
    "bufsize": "16M",
    "fps": 30,
    "audio_codec": "aac",
    "audio_bitrate": "128k",
    "audio_sample_rate": 44100,
    "pixel_format": "yuv420p",
    "container": "mp4",
    "movflags": "+faststart"
  }
}

## 6. MCP Tool Definitions


### 6.1 Project Management Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_project_create | Create a new editing project | name, source_video_path |
| clipcannon_project_open | Open an existing project | project_id |
| clipcannon_project_list | List all projects | status_filter? |
| clipcannon_project_status | Get project status and progress | project_id |
| clipcannon_project_delete | Delete a project and its outputs | project_id |


### 6.2 Video Understanding Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_ingest | Ingest a video file and run full analysis pipeline | video_path, options? |
| clipcannon_transcribe | Run/re-run transcription on source video | project_id, language?, model_size? |
| clipcannon_analyze_frames | Extract and embed frames from video | project_id, fps?, start_ms?, end_ms? |
| clipcannon_analyze_audio | Run audio embedding pipeline (emotion, speaker, acoustic) | project_id |
| clipcannon_analyze_scenes | Detect scene boundaries and generate descriptions | project_id, threshold? |
| clipcannon_detect_speakers | Run speaker diarization | project_id, num_speakers? |
| clipcannon_detect_topics | Segment transcript into topics | project_id, min_topic_length_ms? |
| clipcannon_detect_highlights | Find high-engagement moments | project_id, count?, min_duration_ms? |
| clipcannon_get_vud_summary | Stage 1a: Compact overview of entire video (~8K tokens). Source metadata, speaker list, topic list, top highlights, reaction summary, beat summary, content rating, provenance status. The AI's first perception — enough to plan editing strategy. | project_id |
| clipcannon_get_analytics | Stage 1b: Detailed analytics (~15-20K tokens). Full scene list, topic boundaries with keywords, all highlights with scores/reasons, all reaction events, silence gaps. The structural map of the video. | project_id, sections? (default: all. Options: scenes, topics, highlights, reactions, silence_gaps, beats, quality, pacing) |
| clipcannon_get_transcript | Stage 1c: Paginated transcript (~12K per page). Returns word-level timestamped transcript for a time range. The AI requests pages for sections it plans to edit. | project_id, start_ms, end_ms |
| clipcannon_get_segment_detail | Stage 1d: Full-resolution data for a time range (~10-20K tokens). Returns ALL stream data (transcript, emotion curve per second, speakers, reactions, beats, on-screen text, pacing, quality) for the specified range. Used for fine-grained editing decisions. | project_id, start_ms, end_ms |
| clipcannon_get_storyboard | Stage 2: Batched storyboard grids (~24K per batch including metadata). Returns 12 grids per batch, each a 3x3 composite (9 frames) with timestamp overlays + per-cell stream metadata. Can target specific time ranges. | project_id, batch? (1-7 for full video), start_ms?, end_ms? |
| clipcannon_get_frame | Stage 3: Single full-resolution frame at a timestamp, with all stream data at that moment. For thumbnail selection, quality verification, visual judgment. | project_id, timestamp_ms |
| clipcannon_get_frame_strip | Stage 3: 3x3 grid of 9 frames from a time range, with per-cell metadata. Preview a potential clip's visual flow. | project_id, start_ms, end_ms |
| clipcannon_search_content | Semantic search across video content — returns matching segments with timestamps. Response always under 25K tokens. | project_id, query, stream?, limit? (default 20) |


### 6.3 Editing Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_create_edit | Create an edit plan (EDL) from segments | project_id, edl |
| clipcannon_suggest_edits | Auto-generate edit suggestions for a platform | project_id, platform, style, count? |
| clipcannon_extract_clip | Quick-extract a single clip by time range | project_id, start_ms, end_ms, platform? |
| clipcannon_add_captions | Add caption overlay to an edit | edit_id, style?, language? |
| clipcannon_add_title_card | Add title card to beginning of edit | edit_id, text, duration_ms?, style? |
| clipcannon_set_crop | Set crop/reframe strategy for an edit | edit_id, strategy, aspect_ratio |
| clipcannon_set_audio | Configure audio processing for an edit | edit_id, normalize?, remove_silence?, duck_music? |
| clipcannon_preview_edit | Generate a low-res preview of an edit | edit_id |
| clipcannon_list_edits | List all edits for a project | project_id |
| clipcannon_update_edit | Modify an existing edit plan | edit_id, changes |
| clipcannon_delete_edit | Remove an edit plan | edit_id |


### 6.4 Audio Generation Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_generate_music | Generate AI background music via ACE-Step | prompt, duration_ms, model_variant? (turbo-rl|turbo|sft), lora? (Text2Samples|RapMachine), guidance_scale?, seed?, output_path? |
| clipcannon_compose_midi | Generate deterministic music via MIDI composition | tempo_bpm, key, mood, chord_progression[], bars, instruments[], soundfont?, output_path? |
| clipcannon_generate_sfx | Generate programmatic sound effect via DSP | type (whoosh|riser|downer|impact|chime|tick|bass_drop|shimmer|stinger), duration_ms?, params?, output_path? |
| clipcannon_preview_audio | Generate and preview audio asset without attaching to edit | audio_spec (same as EDL audio object) |
| clipcannon_list_soundfonts | List available SoundFont files for MIDI rendering |  |
| clipcannon_set_edit_audio | Attach audio configuration to an existing edit | edit_id, audio (full audio object from EDL spec) |
| clipcannon_mix_audio | Generate final audio mix for an edit (background + source + SFX) | edit_id, duck_under_speech?, duck_level_db?, normalize? |


### 6.5 Animation & Overlay Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_list_animations | List all available animation assets (shipped + cached + custom) | category? (lottie|webm|pycairo_template), search? |
| clipcannon_preview_animation | Render a single animation to preview video | animation_spec (same as EDL animation object), duration_ms, background_color? |
| clipcannon_add_lower_third | Add animated lower third to an edit | edit_id, name, title, start_ms, duration_ms, template?, style?, colors? |
| clipcannon_add_title_card | Add animated title card to an edit | edit_id, text, subtitle?, duration_ms, animation?, colors?, position? |
| clipcannon_add_animation | Add any animation overlay to an edit | edit_id, animation (full animation object from EDL spec) |
| clipcannon_add_transition | Set transition type between segments in an edit | edit_id, segment_index, transition_type, duration_ms?, easing? |
| clipcannon_list_transitions | List all available transition types (FFmpeg native + GL shaders) |  |
| clipcannon_fetch_lottie | Download a Lottie animation from LottieFiles.com | query, max_results? |
| clipcannon_import_asset | Import custom WebM/Lottie asset into local library | file_path, category, asset_id |


### 6.6 Rendering Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_render | Render an edit to final output video (includes audio mix + animations) | edit_id, profile?, output_path? |
| clipcannon_render_batch | Render multiple edits in parallel (up to 3 on RTX 5090) | edit_ids[], profiles? |
| clipcannon_render_all_platforms | Render one edit to all target platforms | edit_id, platforms[] |
| clipcannon_render_status | Check render progress | render_job_id |
| clipcannon_render_thumbnail | Generate thumbnail image from edit | edit_id, timestamp_ms? |


### 6.7 Metadata & Content Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_generate_title | Generate platform-optimized title for a clip | edit_id, platform, style? |
| clipcannon_generate_description | Generate description/caption text | edit_id, platform, include_hashtags? |
| clipcannon_generate_hashtags | Generate relevant hashtags | edit_id, platform, count? |
| clipcannon_generate_metadata | Generate complete post metadata (title + desc + tags) | edit_id, platform |
| clipcannon_batch_metadata | Generate metadata for multiple edits/platforms at once | edit_ids[], platforms[] |


### 6.8 Publishing Tools (Phase 3)

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_publish_queue | Add rendered video to publishing queue | render_id, platform, metadata, scheduled_time? |
| clipcannon_publish_review | Get all items pending human approval | status_filter? |
| clipcannon_publish_approve | Approve a queued post for publishing | queue_id |
| clipcannon_publish_reject | Reject a queued post with feedback | queue_id, reason |
| clipcannon_publish_execute | Push approved post to platform API | queue_id |
| clipcannon_publish_status | Check publishing status | queue_id |
| clipcannon_publish_analytics | Get post-publish analytics (if available) | queue_id |
| clipcannon_accounts_list | List connected social media accounts |  |
| clipcannon_accounts_connect | Initiate OAuth flow for a platform | platform |
| clipcannon_accounts_disconnect | Disconnect a platform account | platform, account_id |


### 6.9 Provenance Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_provenance_verify | Verify the full SHA-256 hash chain for a project. Returns integrity status and any chain breaks. | project_id |
| clipcannon_provenance_query | Query provenance records by operation, stage, or time range | project_id, operation?, stage? (understanding|editing|rendering|publishing), start_time?, end_time? |
| clipcannon_provenance_get | Get a specific provenance record by ID | project_id, record_id |
| clipcannon_provenance_chain | Walk the hash chain from a specific output back to the source video | project_id, output_sha256 |
| clipcannon_provenance_timeline | Get an ordered timeline of all provenance records for a project | project_id |
| clipcannon_provenance_diff | Compare two provenance chains (e.g., two renders of the same source with different settings) | project_id, chain_hash_a, chain_hash_b |
| clipcannon_provenance_replay | Re-run a specific pipeline stage with the exact same parameters recorded in provenance | project_id, record_id |
| clipcannon_provenance_stats | Get aggregate provenance statistics (avg processing times per stage, model versions used, etc.) | project_id? (omit for global stats) |


### 6.10 Session & Robustness Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_get_clip_registry | Returns the current list of all clips produced in this session — IDs, time ranges, platforms, status. Used to re-orient after context compression. | project_id |
| clipcannon_validate_edl | Validates all timestamps in an EDL against source bounds, snaps to silence gaps/word boundaries/frames. Returns corrected EDL + drift report. Called automatically by create_edit. | project_id, edl |
| clipcannon_session_restore | Restore a session from disk after MCP reconnection or crash. Reloads VUD cache + clip registry. | project_id |
| clipcannon_disk_status | Returns current disk usage by tier (sacred/regenerable/ephemeral) and free space. | project_id |
| clipcannon_disk_cleanup | Frees disk space by deleting ephemeral files first, then regenerable (largest first). | project_id, target_free_gb? (default 20) |
| clipcannon_pipeline_status | Returns status of all 12 streams — completed/failed/skipped with error details. | project_id |


### 6.11 Configuration Tools

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_config_get | Get current configuration | key? |
| clipcannon_config_set | Update configuration | key, value |
| clipcannon_profiles_list | List available encoding profiles |  |
| clipcannon_profiles_create | Create a custom encoding profile | name, settings |
| clipcannon_models_status | Check loaded models and VRAM usage |  |
| clipcannon_system_health | System health check (GPU, disk, models) |  |


## 7. Technical Implementation


### 7.1 Technology Stack

| Layer | Technology | Rationale |
|:---|:---|:---|
| MCP Server | Python (FastMCP / mcp-python-sdk) | Best ML ecosystem, native PyTorch/CUDA bindings |
| Video Processing | FFmpeg 7.x with NVENC/NVDEC | Industry standard, hardware acceleration, comprehensive filter system |
| Transcription | WhisperX (faster-whisper + wav2vec2 forced alignment, mandatory) | 20-50ms word timestamp precision. Base Whisper drifts 200-500ms — unacceptable. |
| EDL Rendering | typed-ffmpeg v3.0 (type-safe FFmpeg command builder) | Type-validated filter graphs. AI writes EDL JSON, typed-ffmpeg builds FFmpeg commands. |
| Visual Embeddings | SigLIP via transformers/ONNX | Best zero-shot vision encoder for content understanding |
| Semantic Embeddings | Nomic Embed v1.5 via sentence-transformers | Excellent topic clustering quality, 768-dim embeddings |
| Emotion Analysis | Wav2Vec2 Large via transformers | Rich emotion features: arousal, valence, energy per segment |
| Speaker Diarization | WavLM + clustering or pyannote.audio | X-vector approach for speaker identification |
| Scene Detection | SigLIP cosine similarity + PySceneDetect | Dual approach: embedding-based + traditional |
| Source Separation | HTDemucs v4 (Meta, MIT license) | 4-stem separation: vocals/music/drums/other. Force multiplier for all audio models |
| Reaction Detection | SenseVoice-Small (Apache 2.0) | Laughter, applause, BGM detection. 70ms per 10s audio. Strongest highlight signal |
| OCR | PaddleOCR PP-OCRv5 (Apache 2.0) | On-screen text detection. Slide transitions, text extraction, 100+ languages |
| Video Quality | pyiqa BRISQUE (GPU) + DOVER-Mobile (GPU, MIT) | GPU-accelerated quality scoring. Batch inference on all frames |
| Shot Classification | ResNet-50 on MovieShots (GPU) | Close-up/medium/wide detection on GPU Tensor Cores |
| Beat Detection | Beat This! (GPU, Transformer, ISMIR 2024 SOTA) | GPU-accelerated beat/downbeat detection |
| Content Safety | Word list (CPU) + CLIP-NSFW (GPU, reuses SigLIP) | Profanity timestamps. NSFW via existing GPU embeddings |
| Face Detection | MediaPipe or InsightFace (ONNX) | Fast, accurate, for smart cropping |
| Audio Processing | cuFFT (GPU) + CuPy (GPU) + torchaudio (GPU) | GPU-accelerated spectral analysis, feature extraction, preprocessing |
| VAD | Silero VAD | Best open-source VAD, runs on CPU, <1ms latency |
| AI Music Gen | ACE-Step v1.5 (MIT license) | Best local music model: <4GB VRAM, 44.1kHz stereo, commercial OK |
| MIDI Composition | MIDIUtil + music21 | Algorithmic music: theory-correct progressions, deterministic output |
| MIDI Rendering | FluidSynth + pyfluidsynth | SoundFont-based MIDI→WAV at 44.1kHz stereo |
| DSP/SFX | numpy + scipy.signal | Programmatic sound effects: whooshes, risers, impacts, chimes |
| Audio Mixing | pydub | Fade, crossfade, ducking, mixing, volume normalization |
| Audio Effects | pedalboard (Spotify) | Reverb, compression, EQ, limiting (GPLv3) |
| Lottie Rendering | rlottie-python | Samsung rlottie C wrapper: render Lottie JSON to PNG frames (MIT) |
| 2D Vector Graphics | PyCairo + Pango | Anti-aliased lower thirds, title cards, callouts, custom overlays |
| Animation Assets | LottieFiles.com (100K+ free) | Lottie Simple License: free commercial use, no attribution |
| Transition Shaders | xfade-easing (GL Transitions port) | 60+ GLSL transitions as FFmpeg expressions (MIT) |
| Database | SQLite + sqlite-vec (single .db per project) | ALL project data: metadata, transcript, embeddings (4 vector tables), provenance, EDLs, session state |
| GPU Management | PyTorch CUDA + NVIDIA Management Library | Model loading, VRAM monitoring, multi-stream inference |
| GPU Video SDK | PyNvVideoCodec 2.0 / NVIDIA VPF | Direct Python access to NVENC/NVDEC hardware, bypasses FFmpeg overhead for decode |
| CUDA Toolkit | CUDA 13.2 (required) | CUDA Tile (Blackwell+Ampere+Ada), Green Contexts, cuFFT device API, CCCL 3.2 (Top-K, Segmented Reduction, FindIf), CuPy interop |
| Precision | NVFP4 default on Blackwell, INT8 fallback | NVFP4 = 87.5% VRAM savings, 3x dense compute vs FP8, <1% accuracy loss. INT8 on Ampere/Ada |


### 7.2 CUDA & GPU Acceleration Architecture

ClipCannon leverages the RTX 5090's Blackwell architecture (compute capability 12.0) and CUDA 13.2 features for maximum throughput. CUDA 13.2 is the most significant toolkit update in CUDA's history — it extends CUDA Tile to Ampere/Ada GPUs, adds NVFP4 full-stack support, introduces CCCL 3.2 high-performance algorithms, and provides Python-first development tools. All GPU features degrade gracefully on older architectures.

RTX 5090 Full Specifications:

| Spec | Value | Impact for ClipCannon |
|:---|:---|:---|
| Architecture | Blackwell (GB202), Compute Cap 12.0 | Full CUDA 13.2 + NVFP4 + Green Contexts |
| CUDA Cores | 21,760 (+33% vs 4090) | Faster embedding computation |
| Tensor Cores | 680 (5th generation) | NVFP4/INT8/FP8 accelerated inference |
| SMs | 170 | Green Context partitioning with fine granularity |
| VRAM | 32GB GDDR7 | All 12 stream models fit concurrently |
| Memory Bandwidth | 1,792 GB/s (+78% vs 4090) | 1.78x faster memory-bound operations (embedding loads, frame buffers) |
| L2 Cache | 98MB | Hot embedding batches stay in cache |
| NVENC | 3 encoders (9th gen) | 3 parallel clip renders simultaneously |
| NVDEC | 2 decoders (6th gen) | Decode source + preview concurrently |
| INT8 TOPS | 3,352 (+154% vs 4090) | Embedding models at INT8 run 2.5x faster |
| FP4 Support | NVFP4 (Blackwell-exclusive) | 87.5% VRAM savings, 3x compute vs FP8 |
| TDP | 575W (peaks 600W+) | Requires 1000W+ PSU |
| PCIe | 5.0 x16 | Full bandwidth for CPU↔GPU transfers |


#### 7.2.1 NVENC/NVDEC Hardware Codec Pipeline

The RTX 5090 has 3 NVENC encoders (9th gen) and 2 NVDEC decoders (6th gen). This enables:

| Capability | Specification | Impact |
|:---|:---|:---|
| Parallel encoding | 3 independent NVENC sessions | Render 3 clips simultaneously |
| Parallel decoding | 2 independent NVDEC sessions | Decode source + preview concurrently |
| 4:2:2 color | First consumer GPU with 4:2:2 encode/decode | Professional color fidelity preservation |
| AV1 Ultra Quality | 5% better compression than previous gen | Smaller files at same quality |
| Encode speed | 60% faster than RTX 4090; 5x faster than x264 CPU | 1080p @ 500+ fps encode rate |
| Codec support | H.264, H.265/HEVC, AV1 | All platform requirements covered |
| Bit depth | 8-bit and 10-bit | HDR content preservation |

Parallel Render Pipeline:

Source Video
```
    │
    ├──[NVDEC Decoder 0]──► Frame Buffer ──► Filter Graph ──[NVENC Encoder 0]──► TikTok clip
    │                                                    ──[NVENC Encoder 1]──► Instagram clip
    │                                                    ──[NVENC Encoder 2]──► YouTube clip
    │
    └──[NVDEC Decoder 1]──► Preview generation (low-res, concurrent)
With 3 NVENC encoders, a batch of 20 clips renders in ~7 minutes. NVENC operates on dedicated silicon — it does not consume CUDA cores or interfere with model inference.
```


#### 7.2.2 Green Contexts (SM Partitioning)

CUDA 13.2 Green Contexts enable static SM partitioning of the RTX 5090's 170 Streaming Multiprocessors into isolated execution domains. Unlike MPS (percentage-based) or MIG (fixed partitions), Green Contexts provide SM-level granularity with dynamic reconfiguration. ClipCannon uses this for deterministic workload isolation during the analysis phase:

RTX 5090: 170 SMs, 680 Tensor Cores, 32GB GDDR7
All models at NVFP4 = ~8.4 GB total (23+ GB free)
```
┌─────────────────────────────────────────────────────────┐
│ Green Context A (60% = 102 SMs)                         │
│ ► Neural model inference (NVFP4 on Tensor Cores):       │
│   HTDemucs, Whisper, SigLIP, Wav2Vec2, WavLM,          │
│   SenseVoice, PaddleOCR, Nomic Embed, DOVER-Mobile      │
│ ► All models loaded concurrently at ~8.4 GB NVFP4       │
├─────────────────────────────────────────────────────────┤
│ Green Context B (25% = 42 SMs)                          │
│ ► CUDA Tile custom kernels (cuTile Python):             │
│   frame_similarity, embedding_cluster, highlight_scorer,│
│   quality_aggregate, caption_layout                     │
│ ► CCCL 3.2 algorithms: Top-K, Segmented Reduction       │
│ ► cuFFT spectral analysis, CuPy post-processing         │
├─────────────────────────────────────────────────────────┤
│ Green Context C (15% = 26 SMs)                          │
│ ► Storyboard grid generation (frame compositing)        │
│ ► Face detection (MediaPipe/InsightFace)                 │
│ ► ResNet-50 shot classification                         │
└─────────────────────────────────────────────────────────┘
│ NVENC x3 (dedicated silicon, outside SM budget)          │
│ NVDEC x2 (dedicated silicon, outside SM budget)          │
└─────────────────────────────────────────────────────────┘
Why Green Contexts matter: Without partitioning, a large Whisper batch could starve the face detection pipeline of GPU resources, causing inconsistent smart-crop timing. Green Contexts guarantee each workload gets its allocated SMs regardless of other workloads.
```

Fallback: On GPUs without Green Context support (pre-Blackwell), ClipCannon uses CUDA streams with priority scheduling. Functional but without hard isolation guarantees.


#### 7.2.3 CUDA Tile for Custom Kernels (cuTile Python)

CUDA 13.2 extends CUDA Tile support to Ampere (RTX 3000) and Ada (RTX 4000) GPUs — not just Blackwell. This means ClipCannon's custom Tile kernels run on all supported GPU tiers, not just the RTX 5090. The cuTile Python DSL is pip-installable (pip install cuda-tile) and requires no system-wide CUDA Toolkit installation.

CUDA 13.2 cuTile Python enhancements used by ClipCannon:

Recursive functions: Used in divide-and-conquer topic clustering
Closures with capture: Lambda functions for per-frame scoring expressions
Custom reduction functions: User-defined parallel reduction for highlight scoring aggregation
Array.slice: Zero-copy subarray views for windowed audio processing
Type-annotated assignments: Stronger typing for embedding dimension safety
ClipCannon Custom Tile Kernels:

| Kernel | Purpose | Benefit | GPU Support |
|:---|:---|:---|:---|
| frame_cosine_similarity | Batch cosine similarity between consecutive SigLIP embeddings | 100x faster scene detection | Blackwell + Ada + Ampere |
| audio_energy_rms | Windowed RMS energy computation over audio buffer | Real-time energy curve | Blackwell + Ada + Ampere |
| embedding_cluster | K-means clustering of speaker X-vectors | Fast speaker diarization | Blackwell + Ada + Ampere |
| caption_layout | Per-word timing calculation and line-break optimization | Instant caption generation | Blackwell + Ada + Ampere |
| highlight_scorer | Custom parallel reduction for multi-signal highlight scoring | Instant highlight ranking | Blackwell + Ada + Ampere |
| quality_aggregate | Per-scene quality aggregation from per-frame BRISQUE scores | Fast quality classification | Blackwell + Ada + Ampere |

Example: Frame Similarity Kernel (cuTile Python, CUDA 13.2):

```python
import cuda.tile as ct

@ct.kernel
def frame_cosine_similarity(embeddings, similarities, dim: ct.Constant[int]):
    """Compute cosine similarity between consecutive frame embeddings.
    Runs on Blackwell, Ada, and Ampere GPUs via CUDA 13.2 Tile support.
    """
    idx = ct.bid(0)
    a = ct.load(embeddings, index=(idx,), shape=(dim,))
    b = ct.load(embeddings, index=(idx + 1,), shape=(dim,))
    dot = ct.sum(a * b)
    norm_a = ct.sqrt(ct.sum(a * a))
    norm_b = ct.sqrt(ct.sum(b * b))
    sim = dot / (norm_a * norm_b)
    ct.store(similarities, index=(idx,), tile=sim)
Fallback: On GPUs without any CUDA Tile support (pre-Ampere), these operations fall back to PyTorch tensor ops (still GPU-accelerated, but ~2-3x slower than Tile kernels).
```


#### 7.2.4 CCCL 3.2 High-Performance Algorithms

CUDA 13.2 ships with CCCL (CUDA Core Compute Libraries) 3.2, which provides new algorithms that ClipCannon uses directly:

| Algorithm | CCCL API | ClipCannon Use Case | Speedup |
|:---|:---|:---|:---|
| Top-K | cub::DeviceTopK | Select top K highlights from scored segments without full sort | 5x over radix sort for small K |
| Segmented Reduction | cub::DeviceSegmentedReduce with fixed segment size | Aggregate per-scene quality scores, per-topic emotion averages | Up to 66x for small segments |
| FindIf | cub::DeviceFindIf with early exit | Find first silence gap > threshold, first profanity occurrence | Up to 7x faster than full scan |
| Binary Search | cub::DeviceBinarySearch | Look up timestamps in sorted beat grid, find nearest scene boundary | Parallel multi-value search |

Top-K for Highlight Selection: When the AI requests "top 20 highlights from a 4-hour video" with 1000+ scored candidate segments, DeviceTopK selects the top 20 in a single GPU pass without sorting all 1000+. This is 5x faster than sorting all candidates and taking the first 20.

Segmented Reduction for Per-Scene Analytics: When computing quality_avg per scene across 28,800 per-frame BRISQUE scores, DeviceSegmentedReduce with uniform segment sizes eliminates the overhead of variable-length offset arrays, achieving up to 66x speedup for scenes with few frames.


#### 7.2.5 CuPy Interoperability (Zero-Copy Data Sharing)

CUDA 13.2 CuPy implements the CUDA Stream Protocol for zero-copy stream sharing between CuPy, PyTorch, and JAX:

```python
import cupy
import torch

# Share a CuPy stream with PyTorch — zero-copy, no synchronization overhead
cupy_stream = cupy.cuda.Stream()
pytorch_stream = torch.cuda.ExternalStream(cupy_stream.ptr)

# Embedding model runs in PyTorch, post-processing in CuPy — same stream
with torch.cuda.stream(pytorch_stream):
    embeddings = siglip_model(frames)  # PyTorch inference
with cupy_stream:
    similarities = cupy.dot(embeddings[:-1], embeddings[1:].T)  # CuPy post-processing
    # No CPU roundtrip, no stream synchronization — data stays on GPU
This eliminates CPU-GPU data transfer overhead between the PyTorch embedding models and CuPy-based post-processing (similarity computation, clustering, quality aggregation). The ml_dtypes.bfloat16 support in CuPy enables native BF16 computation for reduced-precision embedding operations.
```

7.2.6 cuFFT for Audio Spectral Analysis
The acoustic feature stream uses cuFFT's CUDA 13.2 device API (with improved Blackwell utilization and LTO kernel support) for GPU-accelerated spectral analysis:

Spectral centroid: FFT-based frequency content analysis
Onset detection: Spectral flux computation for beat/transition detection
Music vs. speech classification: Spectral flatness and harmonic ratio
Silence detection: Energy thresholding on frequency-domain representation
Processing 1 hour of 16kHz audio through cuFFT: ~200ms (vs ~5s on CPU with Librosa).


#### 7.2.5 PyNvVideoCodec for Direct GPU Decode

For maximum decode throughput, ClipCannon can bypass FFmpeg and use NVIDIA's PyNvVideoCodec 2.0 for direct GPU-to-GPU frame extraction:

```python
import PyNvVideoCodec as nvc
```

decoder = nvc.CreateDecoder(
    gpu_id=0,
    codec=nvc.CudaVideoCodec.H264,
    output_format=nvc.PixelFormat.NV12
)

# Frames stay in GPU memory -- no CPU roundtrip
for frame in decoder.decode("source.mp4"):
    # frame.cuda_array is already a CUDA tensor
    # Pass directly to SigLIP for embedding
    embedding = siglip_model(preprocess(frame.cuda_array))
This eliminates the CPU-GPU data transfer bottleneck: frames are decoded on NVDEC, stay in GPU VRAM, and are fed directly to the embedding model. On a 1-hour 4K source, this saves ~15 seconds compared to FFmpeg decode + CPU transfer.

Fallback: FFmpeg with -hwaccel cuda -hwaccel_output_format cuda provides similar GPU-resident decode on any NVDEC-capable GPU.


#### 7.2.6 Precision & Quantization

| Precision | VRAM Savings | Quality Impact | GPU Support |
|:---|:---|:---|:---|
| FP32 (baseline) | 0% | Reference | All CUDA GPUs |
| FP16 / BF16 | 50% | Negligible for inference | Volta+ (CC 7.0+) |
| INT8 | 75% | <1% accuracy loss | Turing+ (CC 7.5+) |
| FP8 (E4M3) | 75% | <1% accuracy loss | Ada/Blackwell (CC 8.9+) |
| NVFP4 | 87.5% | <1% accuracy loss | Blackwell only (CC 12.0) |

ClipCannon defaults — NVFP4 is the primary precision on Blackwell, delivering 3x dense compute vs FP8 with <1% accuracy loss (validated across MLPerf benchmarks):

Blackwell (RTX 5090): NVFP4 for all embedding models (87.5% VRAM savings vs FP32, 3x throughput vs FP8). INT8 fallback for models without FP4 quantization support.
Ada (RTX 4000 series): INT8 for all models, FP8 (E4M3) for compatible models
Ampere (RTX 3000 series): INT8 where supported, FP16 fallback
Turing (RTX 2000 series): FP16 for all models (minimum supported)
NVFP4 VRAM Savings for ClipCannon Models on RTX 5090:

| Model | FP16 VRAM | INT8 VRAM | NVFP4 VRAM | NVFP4 Savings |
|:---|:---|:---|:---|:---|
| faster-whisper large-v3 | ~6.0 GB | ~3.0 GB | ~1.5 GB | 75% |
| SigLIP SO400M | ~2.4 GB | ~1.2 GB | ~0.6 GB | 75% |
| HTDemucs | ~8.0 GB | ~4.0 GB | ~2.0 GB | 75% |
| Wav2Vec2 Large | ~3.0 GB | ~1.5 GB | ~0.75 GB | 75% |
| WavLM Base Plus SV | ~0.8 GB | ~0.4 GB | ~0.2 GB | 75% |
| Nomic Embed v1.5 | ~1.0 GB | ~0.5 GB | ~0.25 GB | 75% |
| SenseVoice-Small | ~2.2 GB | ~1.1 GB | ~0.55 GB | 75% |
| PaddleOCR PP-OCRv5 | ~3.0 GB | ~1.5 GB | ~0.75 GB | 75% |
| ACE-Step v1.5 turbo-rl | ~16.0 GB | ~8.0 GB | ~4.0 GB | 75% |
| Total (all concurrent) | ~42.4 GB | ~21.2 GB | ~10.6 GB | 75% |

At NVFP4 precision, ALL ClipCannon models fit in 10.6 GB — leaving 21.4 GB free on the 32GB RTX 5090 for frame buffers, batch processing, and NVENC rendering. All models run concurrently with zero load/unload overhead.


### 7.3 Project Directory Structure

All project analysis data, embeddings, provenance records, and metadata are stored in a single SQLite database per project (analysis.db) using sqlite-vec for vector storage. One portable .db file contains everything the AI needs.

~/.clipcannon/
  config.db                      # Global configuration (SQLite)
  models/                        # Downloaded model weights
    whisperx-large-v3/           # WhisperX (mandatory, with wav2vec2 aligner)
    siglip-so400m/
    nomic-embed-text-v1.5/
    wav2vec2-emotion/
    wavlm-base-plus-sv/
    sensevoice-small/
    htdemucs/
    paddleocr-ppv5/
    beat-this/
    dover-mobile/
    resnet50-shottype/
    silero-vad/
    ace-step-v15-turbo-rl/
    ace-step-lora-text2samples/
  soundfonts/
    GeneralUser_GS.sf2
  assets/                        # Animation & overlay assets
    lottie/                      # ~28 shipped Lottie animations
    webm/                        # ~20 pre-rendered WebM with alpha
    transitions/                 # ~60 GL Transition shader expressions
    fonts/                       # Bundled fonts (Montserrat, Inter)
  projects/
    {project_id}/
      analysis.db                # ★ SINGLE DATABASE: all analysis, embeddings, provenance, metadata
      source/
        original.mp4             # Source video (never modified)
        source_cfr.mp4           # VFR-normalized copy (only if VFR detected)
      stems/                     # HTDemucs output (Regenerable tier — can recreate from source)
        vocals.wav
        music.wav
        drums.wav
        other.wav
      frames/                    # Extracted frames at 2fps (Regenerable tier)
        frame_000000.jpg
        ...
      storyboards/               # 3x3 grid composites (Regenerable tier)
        grid_001.jpg
        ...
        grid_080.jpg
      edits/
        {edit_id}/
          audio/                 # Generated audio assets (Ephemeral after render)
            background_music.wav
            sfx_whoosh_0.wav
            final_mix.wav
          animations/            # Rendered animation frames (Ephemeral after render)
            lower_third_001/
            lottie_subscribe/
      renders/
        {render_id}/
          output.mp4             # Final rendered video (Sacred)
          thumbnail.jpg          # Generated thumbnail (Sacred)
What's in analysis.db vs what's on disk:

In the database: ALL structured data — transcript, embeddings (via sqlite-vec), scenes, topics, speakers, reactions, beats, quality scores, pacing, on-screen text, content safety, highlights, provenance records, EDLs, publish metadata, session state
On disk as files: Binary media only — source video, audio stems (WAV), extracted frames (JPEG), storyboard grids (JPEG), rendered outputs (MP4), generated audio (WAV), animation frames (PNG)
The database references disk files by path. Disk files are classified by tier (Sacred/Regenerable/Ephemeral) per Section 8.6.


### 7.4 Database Schema (analysis.db)

The entire project analysis is stored in a single SQLite database with sqlite-vec for vector columns. All MCP tools query this database internally and return results as JSON (under 25K tokens per response).

-- ============================================================
-- PRAGMAS (set on every connection)
-- ============================================================
```sql
PRAGMA journal_mode=WAL;          -- Concurrent reads during pipeline writes
PRAGMA synchronous=NORMAL;        -- Performance + safety balance
PRAGMA cache_size=-64000;         -- 64MB cache
PRAGMA foreign_keys=ON;

-- ============================================================
-- PROJECT METADATA
-- ============================================================
CREATE TABLE project (
    project_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,     -- Immutable source reference (Section 8.8)
    source_cfr_path TEXT,            -- NULL if source was already CFR
    duration_ms INTEGER NOT NULL,
    resolution TEXT NOT NULL,        -- "3840x2160"
    fps REAL NOT NULL,
    codec TEXT NOT NULL,
    audio_codec TEXT,
    audio_channels INTEGER,
    file_size_bytes INTEGER,
    vfr_detected BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- TRANSCRIPT (WhisperX forced-aligned, from vocal stem)
-- ============================================================
CREATE TABLE transcript_words (
    word_id INTEGER PRIMARY KEY,
    segment_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    confidence REAL,
    speaker_id INTEGER,
    FOREIGN KEY (segment_id) REFERENCES transcript_segments(segment_id)
);

CREATE TABLE transcript_segments (
    segment_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    speaker_id INTEGER,
    language TEXT DEFAULT 'en',
    word_count INTEGER,
    FOREIGN KEY (speaker_id) REFERENCES speakers(speaker_id)
);

CREATE INDEX idx_words_time ON transcript_words(start_ms, end_ms);
CREATE INDEX idx_segments_time ON transcript_segments(start_ms, end_ms);
CREATE INDEX idx_segments_speaker ON transcript_segments(speaker_id);

-- ============================================================
-- SCENES (SigLIP scene detection + shot type + quality)
-- ============================================================
CREATE TABLE scenes (
    scene_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    key_frame_path TEXT,            -- Path to JPEG on disk
    visual_similarity_avg REAL,
    dominant_colors TEXT,            -- JSON array of hex colors
    face_detected BOOLEAN,
    face_x_pct REAL,                -- Face center X as percentage
    face_y_pct REAL,                -- Face center Y as percentage
    shot_type TEXT,                  -- 'extreme_closeup','closeup','medium','wide','establishing'
    shot_type_confidence REAL,
    crop_recommendation TEXT,        -- 'safe_for_vertical','needs_pan_scan','keep_landscape'
    quality_avg REAL,
    quality_min REAL,
    quality_classification TEXT,     -- 'good','acceptable','poor'
    quality_issues TEXT              -- JSON array: ['heavy_blur','camera_shake']
);

CREATE INDEX idx_scenes_time ON scenes(start_ms, end_ms);
CREATE INDEX idx_scenes_quality ON scenes(quality_classification);

-- ============================================================
-- SPEAKERS (WavLM diarization from vocal stem)
-- ============================================================
CREATE TABLE speakers (
    speaker_id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,             -- 'Host', 'Guest 1', 'Speaker_0'
    total_speaking_ms INTEGER,
    speaking_pct REAL,
    first_appearance_ms INTEGER
);

-- ============================================================
-- EMOTION CURVE (Wav2Vec2 from vocal stem)
-- ============================================================
CREATE TABLE emotion_curve (
    chunk_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    arousal REAL NOT NULL,           -- 0.0-1.0
    valence REAL NOT NULL,           -- 0.0-1.0 (negative to positive)
    energy REAL NOT NULL,            -- 0.0-1.0
    label TEXT                       -- 'high_energy','calm','emotional_peak'
);

CREATE INDEX idx_emotion_time ON emotion_curve(start_ms, end_ms);
CREATE INDEX idx_emotion_energy ON emotion_curve(energy);

-- ============================================================
-- TOPICS (Nomic semantic clustering)
-- ============================================================
CREATE TABLE topics (
    topic_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    label TEXT NOT NULL,             -- 'Main Discussion: AI in Healthcare'
    keywords TEXT,                   -- JSON array: ['machine learning','diagnosis']
    coherence_score REAL,
    semantic_density REAL
);

CREATE INDEX idx_topics_time ON topics(start_ms, end_ms);

-- ============================================================
-- REACTIONS (SenseVoice from vocal stem)
-- ============================================================
CREATE TABLE reactions (
    reaction_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    type TEXT NOT NULL,              -- 'laughter','applause','gasp'
    confidence REAL,
    duration_ms INTEGER,
    intensity TEXT                   -- 'strong','moderate','subtle'
);

CREATE INDEX idx_reactions_time ON reactions(start_ms);
CREATE INDEX idx_reactions_type ON reactions(type);

-- ============================================================
-- BEATS (Beat This! from music stem)
-- ============================================================
CREATE TABLE beats (
    beat_id INTEGER PRIMARY KEY,
    timestamp_ms INTEGER NOT NULL,
    beat_type TEXT NOT NULL,         -- 'beat','downbeat'
    strength REAL
);

CREATE TABLE beat_sections (
    section_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    tempo_bpm REAL,
    time_signature TEXT,             -- '4/4','3/4'
    has_music BOOLEAN
);

CREATE INDEX idx_beats_time ON beats(timestamp_ms);

-- ============================================================
-- ON-SCREEN TEXT (PaddleOCR)
-- ============================================================
CREATE TABLE on_screen_text (
    text_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    region TEXT,                     -- 'center_top','bottom_third','full_screen'
    confidence REAL,
    font_size_est TEXT,              -- 'large','medium','small'
    type TEXT                        -- 'slide','lower_third','title','url','code'
);

CREATE TABLE text_change_events (
    event_id INTEGER PRIMARY KEY,
    timestamp_ms INTEGER NOT NULL,
    type TEXT NOT NULL,              -- 'slide_transition','lower_third_appeared','text_disappeared'
    new_title TEXT
);

CREATE INDEX idx_ocr_time ON on_screen_text(start_ms, end_ms);
CREATE INDEX idx_text_events_time ON text_change_events(timestamp_ms);

-- ============================================================
-- SILENCE GAPS (cuFFT acoustic analysis)
-- ============================================================
CREATE TABLE silence_gaps (
    gap_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    type TEXT                        -- 'natural_break','pause','dead_air'
);

CREATE INDEX idx_silence_time ON silence_gaps(start_ms);

-- ============================================================
-- ACOUSTIC FEATURES (cuFFT + CuPy)
-- ============================================================
CREATE TABLE acoustic (
    project_id TEXT PRIMARY KEY,
    avg_volume_db REAL,
    dynamic_range_db REAL,
    has_background_music BOOLEAN,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE TABLE music_sections (
    section_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    type TEXT,                       -- 'intro_music','background','outro_music'
    confidence REAL
);

-- ============================================================
-- PACING / CHRONEMIC (CuPy-computed)
-- ============================================================
CREATE TABLE pacing (
    segment_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    words_per_minute REAL,
    pause_ratio REAL,
    speaker_changes INTEGER,
    energy_variance REAL,
    label TEXT                       -- 'fast_dialogue','normal','slow_monologue','dead_air'
);

CREATE INDEX idx_pacing_time ON pacing(start_ms, end_ms);

-- ============================================================
-- CONTENT SAFETY (word list + CLIP-NSFW)
-- ============================================================
CREATE TABLE profanity_events (
    event_id INTEGER PRIMARY KEY,
    word TEXT NOT NULL,              -- '[REDACTED]' in API responses
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    severity TEXT                    -- 'mild','moderate','severe'
);

CREATE TABLE content_safety (
    project_id TEXT PRIMARY KEY,
    content_rating TEXT,             -- 'clean','mild','moderate','explicit'
    profanity_count INTEGER,
    profanity_density REAL,
    nsfw_frame_count INTEGER,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- HIGHLIGHTS (computed from emotion + reactions + semantic density + quality)
-- ============================================================
CREATE TABLE highlights (
    highlight_id INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    score REAL NOT NULL,             -- 0.0-1.0 composite highlight score
    type TEXT,                       -- 'high_energy','emotional_peak','laughter_moment','information_dense'
    reason TEXT,                     -- Natural language explanation
    energy_score REAL,
    reaction_score REAL,
    semantic_density REAL,
    visual_variety REAL,
    quality_score REAL
);

CREATE INDEX idx_highlights_score ON highlights(score DESC);
CREATE INDEX idx_highlights_time ON highlights(start_ms, end_ms);

-- ============================================================
-- STORYBOARD GRID METADATA
-- ============================================================
CREATE TABLE storyboard_grids (
    grid_id INTEGER PRIMARY KEY,
    grid_path TEXT NOT NULL,         -- Path to JPEG on disk
    start_ms INTEGER NOT NULL,       -- First frame timestamp in grid
    end_ms INTEGER NOT NULL,         -- Last frame timestamp in grid
    frame_count INTEGER NOT NULL,    -- Typically 9 (3x3)
    frame_timestamps TEXT NOT NULL   -- JSON array of ms timestamps per cell
);

-- ============================================================
-- VECTOR TABLES (sqlite-vec) — embeddings linked to source data
-- ============================================================

-- Visual embeddings: one per frame, linked to frame timestamp + scene
CREATE VIRTUAL TABLE vec_frames USING vec0(
    frame_id INTEGER PRIMARY KEY,
    visual_embedding float[1152] distance_metric=cosine,
    timestamp_ms integer,
    scene_id integer,
    energy_score float,
    quality_score float,
    +frame_path text                 -- Auxiliary: path to JPEG on disk
);

-- Semantic embeddings: one per transcript segment, linked to text
CREATE VIRTUAL TABLE vec_semantic USING vec0(
    segment_id INTEGER PRIMARY KEY,
    semantic_embedding float[768] distance_metric=cosine,
    topic_id integer,
    timestamp_ms integer,
    +transcript_text text            -- Auxiliary: the actual text (pulled with the vector)
);

-- Emotion embeddings: one per audio chunk, linked to energy/arousal
CREATE VIRTUAL TABLE vec_emotion USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    emotion_embedding float[1024] distance_metric=cosine,
    timestamp_ms integer,
    energy float,
    arousal float
);

-- Speaker embeddings: one per utterance, linked to speaker identity
CREATE VIRTUAL TABLE vec_speakers USING vec0(
    utterance_id INTEGER PRIMARY KEY,
    speaker_embedding float[512] distance_metric=cosine,
    speaker_id integer,
    timestamp_ms integer,
    +segment_text text               -- Auxiliary: what was said
);

-- ============================================================
-- PROVENANCE HASH CHAIN (Section 7.5)
-- ============================================================
CREATE TABLE provenance (
    record_id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    operation TEXT NOT NULL,
    stage TEXT NOT NULL,
    description TEXT,
    input_path TEXT,
    input_sha256 TEXT NOT NULL,
    input_size_bytes INTEGER,
    parent_record_id TEXT,
    output_table TEXT,               -- Which DB table was written to
    output_sha256 TEXT NOT NULL,
    output_row_count INTEGER,
    model_name TEXT,
    model_version TEXT,
    model_params TEXT,               -- JSON
    duration_ms INTEGER,
    gpu_device TEXT,
    vram_peak_mb INTEGER,
    chain_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_prov_operation ON provenance(operation);
CREATE INDEX idx_prov_stage ON provenance(stage);

-- ============================================================
-- EDITS AND RENDERS
-- ============================================================
CREATE TABLE edits (
    edit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    edl TEXT NOT NULL,               -- Full EDL as JSON
    platform TEXT,
    profile TEXT,
    status TEXT DEFAULT 'draft',     -- 'draft','validated','rendering','rendered','published'
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE TABLE renders (
    render_id TEXT PRIMARY KEY,
    edit_id TEXT NOT NULL,
    output_path TEXT,
    output_sha256 TEXT,
    thumbnail_path TEXT,
    duration_ms INTEGER,
    file_size_bytes INTEGER,
    status TEXT DEFAULT 'pending',
    started_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id)
);

CREATE TABLE publish_queue (
    queue_id TEXT PRIMARY KEY,
    render_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    metadata TEXT NOT NULL,          -- JSON: title, description, hashtags
    scheduled_time TEXT,
    status TEXT DEFAULT 'pending_review',
    published_at TEXT,
    platform_post_id TEXT,
    FOREIGN KEY (render_id) REFERENCES renders(render_id)
);

-- ============================================================
-- SESSION STATE (for context eviction recovery, Section 8.1)
-- ============================================================
CREATE TABLE session_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Stores: clip_registry, current_task, pinned_manifest

-- ============================================================
-- STREAM STATUS (for graceful degradation, Section 8.7)
-- ============================================================
CREATE TABLE stream_status (
    stream_name TEXT PRIMARY KEY,
    status TEXT NOT NULL,            -- 'completed','failed','skipped','running'
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    fallback_used BOOLEAN DEFAULT FALSE
);
Database size estimate (4-hour video):
```

| Table | Rows | Size |
|:---|:---|:---|
| vec_frames (28,800 × 1152-dim float32) | 28,800 | ~133 MB |
| vec_emotion (14,400 × 1024-dim float32) | 14,400 | ~59 MB |
| vec_semantic (~2,000 × 768-dim float32) | 2,000 | ~6 MB |
| vec_speakers (~2,000 × 512-dim float32) | 2,000 | ~4 MB |
| All metadata tables | ~50,000 rows total | ~20 MB |
| Provenance records | ~20 | <1 MB |
| Total analysis.db |  | ~250-350 MB |

Query performance (sqlite-vec brute-force on 28,800 vectors at 1152-dim): ~5-15ms per KNN query. All metadata queries via standard SQL indexes: <5ms.


#### 7.4.1 Database Capabilities

| Capability | How |
|:---|:---|
| Single portable file per project | One .db file — copyable, backupable |
| Cross-stream queries | SQL JOINs across all tables by timestamp |
| Atomic writes | ACID transactions — no partial/corrupt writes |
| Vector similarity search | sqlite-vec KNN in <15ms on 28K vectors |
| Provenance audit trail | Provenance records with foreign keys in same DB |
| Analytics | GROUP BY, AVG(), SUM(), window functions |
| Concurrent pipeline writes | WAL mode — concurrent readers + writer |


#### 7.4.2 Embedding Space Isolation (No Cross-Space Comparison)

Each embedding model produces vectors in its own mathematical space. Vectors from different models are NEVER compared to each other. A 1152-dim SigLIP visual embedding and a 768-dim Nomic semantic embedding exist in entirely different spaces — computing cosine similarity between them is mathematically meaningless.

This is enforced architecturally by storing each embedding type in its own vec0 virtual table with its own dimension:

| Vector Table | Model | Dimensions | Space | Comparable With |
|:---|:---|:---|:---|:---|
| vec_frames | SigLIP SO400M | 1152 | Visual | Only other vec_frames rows (frame-to-frame visual similarity) |
| vec_semantic | Nomic Embed v1.5 | 768 | Text semantic | Only other vec_semantic rows (segment-to-segment topic similarity) |
| vec_emotion | Wav2Vec2 | 1024 | Audio emotion | Only other vec_emotion rows (emotion-to-emotion similarity) |
| vec_speakers | WavLM | 512 | Speaker voice | Only other vec_speakers rows (voice-to-voice similarity for diarization) |

sqlite-vec enforces dimension matching per table — you cannot query a 1152-dim table with a 768-dim vector. It will error.

Cross-stream correlation is done via timestamps, not vectors. To find "the moment where high visual change coincides with high emotion energy," the system JOINs tables on timestamp_ms ranges — not by comparing embedding vectors:

-- CORRECT: Join on timestamps (apples to apples within each space)
```sql
SELECT s.scene_id, s.start_ms, s.visual_similarity_avg, e.energy
FROM scenes s
JOIN emotion_curve e ON e.start_ms BETWEEN s.start_ms AND s.end_ms
WHERE s.visual_similarity_avg < 0.5   -- High visual change (within visual space)
  AND e.energy > 0.8;                 -- High emotion (within emotion space)

-- WRONG (never done): Comparing vectors across spaces
-- SELECT vec_distance_cosine(f.visual_embedding, e.emotion_embedding) -- MEANINGLESS
The derived scalar scores (energy, quality, similarity) are the bridge between spaces. Each embedding model produces its own scalars (energy 0-1, quality 0-100, similarity 0-1) which are directly comparable because they're on normalized scales. The AI reads these scalars, not the raw vectors.
```


#### 7.4.3 Vector-Metadata Co-Storage Pattern

The key advantage of sqlite-vec: vectors are stored alongside their source data in the same row. When you query for similar vectors, you get the metadata back in the same result — no second lookup.

Example: "Find frames visually similar to timestamp 845000ms":

```sql
SELECT f.frame_id, f.timestamp_ms, f.energy_score, f.quality_score,
       f.frame_path, f.distance
FROM vec_frames f
WHERE f.visual_embedding MATCH (
    SELECT visual_embedding FROM vec_frames WHERE timestamp_ms = 845000
)
AND k = 10
ORDER BY f.distance;
Returns: 10 most similar frames with their timestamps, energy scores, quality scores, and file paths — in a single query, ~10ms.
```

Example: "Find transcript segments semantically similar to 'breakthrough results'":

```sql
SELECT s.segment_id, s.transcript_text, s.timestamp_ms, s.distance
FROM vec_semantic s
WHERE s.semantic_embedding MATCH vec_encode(:query_embedding)
AND k = 5;
Returns: 5 most semantically similar segments with the actual transcript text attached — the vector and its source text come back together.
```

Example: "Identify which speaker said something similar to this utterance":

```sql
SELECT sp.speaker_id, sp.segment_text, sp.timestamp_ms, sp.distance,
       speakers.label
FROM vec_speakers sp
JOIN speakers ON speakers.speaker_id = sp.speaker_id
WHERE sp.speaker_embedding MATCH vec_encode(:query_embedding)
AND k = 3;
```

#### 7.4.3 MCP Tools Query the Database

All MCP tools internally execute SQL queries against analysis.db and return results as JSON (under 25K tokens per response). The AI never writes SQL — it calls MCP tools which encapsulate the queries.

| MCP Tool | Internal SQL | Returns |
|:---|:---|:---|
| clipcannon_get_vud_summary | SELECT * FROM project + SELECT COUNT(*) FROM scenes + SELECT * FROM speakers + SELECT * FROM highlights ORDER BY score DESC LIMIT 10 + ... | Compact overview JSON (~8K tokens) |
| clipcannon_get_analytics | SELECT * FROM scenes + SELECT * FROM topics + SELECT * FROM highlights + SELECT * FROM reactions | Structural map JSON (~18K tokens) |
| clipcannon_get_transcript | SELECT * FROM transcript_segments WHERE start_ms >= ? AND end_ms <= ? ORDER BY start_ms | Paginated transcript JSON (~12K tokens) |
| clipcannon_get_segment_detail | JOINs across emotion_curve, reactions, beats, pacing, on_screen_text for a time range | Full-resolution detail JSON (~15K tokens) |
| clipcannon_search_content | SELECT ... FROM vec_semantic WHERE semantic_embedding MATCH ? AND k = ? | Semantically similar segments with text |


### 7.3 Processing Pipeline

```
INGEST PIPELINE (clipcannon_ingest)
================================
Each step computes SHA-256 hashes and writes a provenance record.
HTDemucs runs FIRST to produce clean stems for all audio models.

1. PROBE (CPU, <1s)
   └─> FFprobe: extract duration, resolution, fps, codecs, audio channels
   └─> Detect VFR: run ffmpeg vfrdet filter (see Section 8.4)
   └─> Validate: supported format, file integrity
   └─> PROVENANCE: hash(source.mp4) → prov_001 [probe]

1.5. VFR NORMALIZATION (GPU NVDEC+NVENC, ~30-60s if VFR detected, SKIP if CFR)
   └─> If vfrdet ratio > 0.0: normalize to CFR at nearest standard rate
   └─> FFmpeg: fps filter + NVENC re-encode at CRF 18 (near-lossless)
   └─> Output: source_cfr.mp4 (becomes the working source for all subsequent steps)
   └─> If already CFR: skip, use original directly
   └─> PROVENANCE: hash(source) + hash(source_cfr.mp4) + target_fps → prov_001b [normalize_vfr]

2. EXTRACT AUDIO (GPU NVDEC + CPU, ~5s for 1hr video)
   └─> FFmpeg: demux audio → PCM 16kHz mono WAV + original sample rate WAV
   └─> Store: analysis/audio_16k.wav, analysis/audio_original.wav
   └─> PROVENANCE: hash(source) + hash(audio files) → prov_002 [extract_audio]

3. SOURCE SEPARATION (GPU, ~60-90s for 1hr audio) ★ NEW
   └─> HTDemucs: separate audio into 4 stems
   └─> Output: analysis/stems/vocals.wav, music.wav, drums.wav, other.wav
   └─> Unload HTDemucs from VRAM after completion
   └─> PROVENANCE: hash(audio_original) + hash(all stems) + model_version → prov_003 [separate_audio]

4. EXTRACT FRAMES (GPU NVDEC, ~30s for 1hr video)
   └─> FFmpeg: decode → extract 2fps JPEGs via NVDEC
   └─> Output: frames/frame_NNNNNN.jpg (7200 frames for 1hr)
   └─> PROVENANCE: hash(source) + hash(frame_manifest) → prov_004 [extract_frames]

5. TRANSCRIBE (GPU — WhisperX on VOCAL STEM, mandatory forced alignment)
   └─> WhisperX on stems/vocals.wav: transcribe + wav2vec2 forced alignment (20-50ms precision)
   └─> INSERT INTO analysis.db: transcript_segments, transcript_words
   └─> PROVENANCE → prov_005 [transcribe]

6. EMBED VISUAL (GPU — SigLIP batch inference)
   └─> SigLIP SO400M: batch=64, NVFP4 precision
   └─> INSERT INTO analysis.db: vec_frames (embedding + timestamp + frame_path)
   └─> Compute scene boundaries via sqlite-vec cosine similarity on consecutive frames
   └─> INSERT INTO analysis.db: scenes
   └─> PROVENANCE → prov_006 [embed_visual]

7. OCR TEXT DETECTION (GPU — PaddleOCR)
   └─> PP-OCRv5 on frames at 1fps, deduplicate consecutive identical text
   └─> INSERT INTO analysis.db: on_screen_text, text_change_events
   └─> PROVENANCE → prov_007 [detect_text]

8. QUALITY ASSESSMENT (GPU — pyiqa BRISQUE + DOVER-Mobile)
   └─> Batch inference on all frames, aggregate per scene via CCCL 3.2
   └─> UPDATE analysis.db: scenes SET quality_avg, quality_classification, quality_issues
   └─> PROVENANCE → prov_008 [assess_quality]

9. SHOT TYPE CLASSIFICATION (GPU — ResNet-50)
   └─> Classify 1 key frame per scene
   └─> UPDATE analysis.db: scenes SET shot_type, crop_recommendation
   └─> PROVENANCE → prov_009 [classify_shots]

10. EMBED SEMANTIC (GPU — Nomic Embed)
    └─> Embed transcript segments, cluster for topics
    └─> INSERT INTO analysis.db: vec_semantic (embedding + transcript_text), topics
    └─> PROVENANCE → prov_010 [embed_semantic]

11. EMBED EMOTION (GPU — Wav2Vec2 on VOCAL STEM)
    └─> 5s windows, 2.5s stride on stems/vocals.wav
    └─> INSERT INTO analysis.db: vec_emotion (embedding + energy + arousal), emotion_curve
    └─> PROVENANCE → prov_011 [embed_emotion]

12. EMBED SPEAKERS (GPU — WavLM on VOCAL STEM)
    └─> Extract X-vectors, cluster unique speakers
    └─> INSERT INTO analysis.db: vec_speakers (embedding + segment_text), speakers
    └─> UPDATE transcript_segments SET speaker_id, transcript_words SET speaker_id
    └─> PROVENANCE → prov_012 [embed_speakers]

13. DETECT REACTIONS (GPU — SenseVoice on VOCAL STEM)
    └─> Detect laughter, applause, BGM leakage with timestamps
    └─> INSERT INTO analysis.db: reactions
    └─> PROVENANCE → prov_013 [detect_reactions]

14. ACOUSTIC ANALYSIS + BEAT DETECTION (GPU — cuFFT + Beat This!)
    └─> cuFFT + CuPy: RMS energy, spectral features, silence detection
    └─> Beat This!: beat positions, downbeats, BPM from music stem
    └─> INSERT INTO analysis.db: silence_gaps, acoustic, music_sections, beats, beat_sections
    └─> PROVENANCE → prov_014 [analyze_acoustic]

15. PROFANITY DETECTION (CPU + GPU)
    └─> Word list match on transcript_words → INSERT INTO profanity_events
    └─> CLIP-NSFW on key frames → INSERT INTO content_safety
    └─> PROVENANCE → prov_015 [detect_profanity]

16. CHRONEMIC COMPUTATION (GPU — CuPy)
    └─> WPM, pause ratios, energy variance, speaker change rates
    └─> INSERT INTO analysis.db: pacing
    └─> PROVENANCE → prov_016 [compute_chronemic]

17. COMPUTE HIGHLIGHTS (GPU — CCCL 3.2 DeviceTopK)
    └─> Multi-signal scoring: emotion + reactions + semantic density + quality
    └─> INSERT INTO analysis.db: highlights (score, type, reason, component scores)
    └─> PROVENANCE → prov_017 [compute_highlights]

18. GENERATE STORYBOARD GRIDS (GPU — CuPy compositing)
    └─> 80 grids, adaptive interval: max(video_duration_s / 720, 0.5)
    └─> Store grid JPEGs to disk: storyboards/grid_001.jpg through grid_080.jpg
    └─> INSERT INTO analysis.db: storyboard_grids (path, timestamps per cell)
    └─> PROVENANCE → prov_018 [generate_storyboards]

19. FINALIZE + VERIFY (CPU, <1s)
    └─> UPDATE analysis.db: stream_status for all streams (completed/failed/skipped)
    └─> Verify provenance chain integrity across all 18 prior records
    └─> UPDATE session_state with pinned manifest
    └─> PROVENANCE → prov_019 [finalize]
```

All structured data goes to analysis.db.
Binary media (frames, storyboards, stems, renders) is stored on disk as files, referenced by path in the database.

TOTAL (RTX 5090, NVFP4, all models concurrent):
  ~3-5 minutes for a 1-hour source video
  ~12-18 minutes for a 4-hour source video
  (NVFP4 enables concurrent model loading — no load/unload overhead)
  (CUDA Tile kernels accelerate similarity, clustering, scoring by 100x over CPU)
  (CCCL 3.2 Top-K + Segmented Reduction accelerate highlight/quality aggregation)
PROVENANCE: 18 records in understanding chain, full integrity verification at synthesis

### 7.4 Rendering Pipeline

```
RENDER PIPELINE (clipcannon_render)
================================

1. VALIDATE EDL (CPU, <1s)
   └─> Check all time ranges are within source bounds
   └─> Validate profile compatibility

2. BUILD FILTER GRAPH (CPU, <1s)
   └─> Translate EDL into FFmpeg filter_complex string
   └─> Handle: crop, scale, transitions, captions, overlays

3. GENERATE CAPTIONS (CPU, ~2s)
   └─> Extract word timestamps for clip time range
   └─> Group into display chunks
   └─> Generate ASS subtitle file or drawtext filter chain

4. RENDER (GPU NVENC, ~10-30s per clip, up to 3 parallel on RTX 5090)
   └─> FFmpeg with hardware encoding:
       - NVDEC for decode (2 decoders available)
       - CUDA filters for crop/scale
       - NVENC for encode (3 encoders available — 3 clips simultaneously)
   └─> Output: renders/{render_id}/output.mp4
   └─> RTX 5090 encodes 1080p @ 500+ fps (5x faster than x264 CPU)

5. GENERATE THUMBNAIL (GPU, <2s)
   └─> Extract frame at specified timestamp
   └─> Apply platform-specific sizing

6. VALIDATE OUTPUT (CPU, <1s)
   └─> FFprobe: verify output matches profile specs
   └─> Check: duration, resolution, codec, bitrate, file size
```

### 7.5 Provenance Hash Chain System

Every data transformation in ClipCannon is tracked with a SHA-256 hash chain. This creates an immutable audit trail from source video to published output -- enabling debugging, replay, integrity verification, and full system visibility at every stage.


#### 7.5.1 Architecture

SOURCE VIDEO ──hash──► AUDIO EXTRACT ──hash──► TRANSCRIPT ──hash──► SEMANTIC EMBED ──hash──►
```
    │                      │                       │                      │
    │                      │                       │                      │
    ▼                      ▼                       ▼                      ▼
 ┌──────────┐         ┌──────────┐           ┌──────────┐          ┌──────────┐
 │ prov_001 │────────►│ prov_002 │──────────►│ prov_003 │─────────►│ prov_004 │──► ...
 │ sha256:  │         │ sha256:  │           │ sha256:  │          │ sha256:  │
 │ a3f7...  │         │ 8b2c...  │           │ d91e...  │          │ 4f6a...  │
 └──────────┘         └──────────┘           └──────────┘          └──────────┘
                                                                        │
                                                                        ▼
                                                              ┌─────────────────┐
                                                              │ PROVENANCE DB    │
                                                              │ (SQLite)         │
                                                              │ project_id/      │
                                                              │   provenance.db  │
                                                              └─────────────────┘
Every provenance record links to its parent(s) via parent_hash, forming a directed acyclic graph (DAG) from source to output.
```


#### 7.5.2 Provenance Record Schema

Every data transformation produces a provenance record:

```json
{
  "record_id": "prov_003",
  "project_id": "proj_abc123",
  "timestamp_utc": "2026-03-20T14:32:05.123Z",
  "operation": "transcribe",
  "stage": "understanding",
  "description": "Transcribe audio to word-level text via faster-whisper",

  "input": {
    "file_path": "analysis/audio_16k.wav",
    "sha256": "8b2c4f1a9d3e7b6c5a8f2d1e4b7c9a3f6d8e2b5c1a4f7d9e3b6c8a2f5d1e4b",
    "size_bytes": 115200000,
    "parent_record_id": "prov_002"
  },

  "output": {
    "file_path": "analysis.db:transcript_segments",
    "sha256": "d91e3f7a2b5c8d4e6f1a9b3c7d5e2f8a4b6c1d9e3f7a2b5c8d4e6f1a9b3c7d",
    "size_bytes": 245678,
    "record_count": 847
  },

  "model": {
    "name": "faster-whisper-large-v3",
    "version": "1.0.0",
    "quantization": "int8",
    "compute_type": "cuda",
    "parameters": {
      "language": "en",
      "word_timestamps": true,
      "beam_size": 5,
      "vad_filter": true
    }
  },

  "execution": {
    "duration_ms": 67452,
    "gpu_device": "cuda:0",
    "gpu_name": "NVIDIA GeForce RTX 5090",
    "vram_peak_mb": 3120,
    "cpu_threads_used": 4
  },

  "chain_hash": "SHA256(parent_hash + input.sha256 + output.sha256 + operation + model.name + model.version + model.parameters_json)",
  "chain_hash_value": "7e4a2f9d1c6b3e8a5f2d7c4b9e1a6f3d8c5b2e7a4f9d1c6b3e8a5f2d7c4b9e"
}
chain_hash computation: The chain hash incorporates the parent hash, creating an unbreakable chain. If any prior record is tampered with, all downstream chain hashes become invalid.

import hashlib, json

def compute_chain_hash(parent_hash, input_sha256, output_sha256, operation, model_name, model_version, model_params):
    payload = f"{parent_hash}|{input_sha256}|{output_sha256}|{operation}|{model_name}|{model_version}|{json.dumps(model_params, sort_keys=True)}"
    return hashlib.sha256(payload.encode()).hexdigest()
```

#### 7.5.3 Provenance Points (Every Data Transformation)

Every stage in the pipeline where data is transformed produces a provenance record:

| Stage | Operation ID | Input | Output (DB table or file) | What Is Hashed |
|:---|:---|:---|:---|:---|
| 1. Probe | probe | Source video file | project table | Source file SHA-256, FFprobe metadata |
| 1.5. VFR Normalize | normalize_vfr | Source video | source_cfr.mp4 (if VFR) | Source hash, CFR hash, target FPS |
| 2. Audio Extract | extract_audio | Source video | stems/*.wav | Source hash, WAV hashes, FFmpeg params |
| 3. Source Separation | separate_audio | Raw audio | stems/vocals.wav, music.wav, drums.wav, other.wav | Audio hash, all stem hashes, HTDemucs version |
| 4. Frame Extract | extract_frames | Source video | frames/frame_*.jpg | Source hash, frame manifest hash |
| 5. Transcribe | transcribe | stems/vocals.wav | transcript_segments, transcript_words tables | Vocal hash, DB table hash, WhisperX version |
| 6. Visual Embed | embed_visual | Frames | vec_frames + scenes tables | Frame manifest hash, vector table hash, SigLIP version |
| 7. OCR | detect_text | Frames | on_screen_text, text_change_events tables | Frame hash, table hash, PaddleOCR version |
| 8. Quality | assess_quality | Frames | scenes table (quality columns) | Frame hash, quality hash |
| 9. Shot Type | classify_shots | Key frames | scenes table (shot_type columns) | Key frame hash, classification hash |
| 10. Semantic Embed | embed_semantic | Transcript | vec_semantic + topics tables | Transcript hash, vector table hash |
| 11. Emotion Embed | embed_emotion | stems/vocals.wav | vec_emotion + emotion_curve tables | Vocal hash, vector table hash |
| 12. Speaker Embed | embed_speakers | stems/vocals.wav | vec_speakers + speakers tables | Vocal hash, vector table hash |
| 13. Reactions | detect_reactions | stems/vocals.wav | reactions table | Vocal hash, table hash |
| 14. Acoustic + Beats | analyze_acoustic | Audio + music stem | silence_gaps, beats, acoustic tables | Audio hashes, table hashes |
| 15. Profanity | detect_profanity | Transcript | profanity_events, content_safety tables | Transcript hash, table hash |
| 16. Chronemic | compute_chronemic | Multiple tables | pacing table | Input table hashes, output hash |
| 17. Highlights | compute_highlights | Multiple tables | highlights table | Input hashes, output hash |
| 18. Storyboards | generate_storyboards | Frames | storyboard_grids table + grid JPEGs | Frame hash, grid manifest hash |
| 19. Finalize | finalize | All tables | stream_status, session_state | All table hashes, chain verification |
| 20. EDL Create | create_edl | AI decision | edits table | DB state hash, EDL hash, AI model ID |
| 21. Music Generate | generate_music | ACE-Step params | background_music.wav | Params hash, WAV hash, model version + seed |
| 22. SFX Generate | generate_sfx | DSP parameters | sfx_*.wav | Params hash, WAV hash |
| 23. Audio Mix | mix_audio | Source audio + generated audio | final_mix.wav | All input hashes, mix params |
| 24. Animation Render | render_animation | Animation spec | PNG frame sequence | Spec hash, manifest hash |
| 25. Video Render | render_video | EDL + all assets | output.mp4 + renders table | EDL hash, asset hashes, FFmpeg command hash |
| 26. Publish | publish | Rendered video + metadata | publish_queue table + Platform post ID | Video hash, metadata hash, platform response |

Total: 26 provenance points per full pipeline run. Each links to its parent(s) via chain hash. All provenance records are stored in the provenance table within analysis.db.


#### 7.5.4 Provenance Storage

Provenance records are stored in the provenance table within analysis.db (the same database as all other project data):

~/.clipcannon/projects/{project_id}/analysis.db → provenance table
Schema:

```sql
CREATE TABLE provenance (
    record_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    operation TEXT NOT NULL,
    stage TEXT NOT NULL,              -- 'understanding' | 'editing' | 'rendering' | 'publishing'
    description TEXT,
```

    input_path TEXT,
    input_sha256 TEXT NOT NULL,
    input_size_bytes INTEGER,
    parent_record_id TEXT,            -- links to parent provenance record

    output_path TEXT,
    output_sha256 TEXT NOT NULL,
    output_size_bytes INTEGER,

    model_name TEXT,
    model_version TEXT,
    model_params_json TEXT,           -- JSON string of model parameters

    duration_ms INTEGER,
    gpu_device TEXT,
    vram_peak_mb INTEGER,

    chain_hash TEXT NOT NULL UNIQUE,  -- immutable chain integrity hash
    metadata_json TEXT                -- arbitrary extra data

    -- FOREIGN KEY (parent_record_id) REFERENCES provenance(record_id)
);

```sql
CREATE INDEX idx_prov_operation ON provenance(operation);
CREATE INDEX idx_prov_stage ON provenance(stage);
CREATE INDEX idx_prov_chain ON provenance(chain_hash);
CREATE INDEX idx_prov_output ON provenance(output_sha256);
```

#### 7.5.5 Provenance Verification

At any point, the entire chain can be verified:

```python
def verify_provenance_chain(project_id):
    """Walk the provenance DAG from leaves to root, verify every chain_hash."""
    records = load_all_provenance_records(project_id)
```

    for record in records:
        # Recompute chain hash from stored fields
        expected = compute_chain_hash(
            parent_hash=get_parent_chain_hash(record.parent_record_id),
            input_sha256=record.input_sha256,
            output_sha256=record.output_sha256,
            operation=record.operation,
            model_name=record.model_name or "",
            model_version=record.model_version or "",
            model_params=json.loads(record.model_params_json or "{}")
        )
        if expected != record.chain_hash:
            raise ProvenanceIntegrityError(
                f"Chain hash mismatch at {record.record_id} ({record.operation}). "
                f"Expected {expected}, got {record.chain_hash}. "
                f"Data may have been tampered with or corrupted."
            )

        # Verify output file still matches its recorded hash
        if record.output_path and os.path.exists(record.output_path):
            actual_hash = sha256_file(record.output_path)
            if actual_hash != record.output_sha256:
                raise ProvenanceIntegrityError(
                    f"File hash mismatch for {record.output_path}. "
                    f"Recorded: {record.output_sha256}, Actual: {actual_hash}. "
                    f"File has been modified since provenance was recorded."
                )

    return {"status": "verified", "records_checked": len(records)}

#### 7.5.6 Provenance Use Cases

| Use Case | How Provenance Helps |
|:---|:---|
| Debugging: "Why did the AI cut here?" | Trace the highlight that led to the cut: highlight → emotion_curve peak → Wav2Vec2 embedding → audio segment → source timestamp. Every step is hashed and verifiable. |
| Debugging: "Why is the transcript wrong?" | Check prov_004 (transcribe): see the exact Whisper model version, quantization, beam size, and audio input hash. Re-run with same params for deterministic reproduction. |
| Debugging: "Music sounds wrong" | Check prov_016 (generate_music): see the exact ACE-Step prompt, seed, guidance_scale, LoRA. Same seed + same prompt = same output. Compare with expected. |
| Audit: "Prove this video came from this source" | Walk the chain from output.mp4 back to source.mp4. Every intermediate hash is verifiable. No step can be forged without breaking the chain. |
| Replay: "Re-run with different settings" | Provenance records store all model parameters. Change one parameter, re-run from that point, and the new branch gets its own provenance chain. |
| Monitoring: "Which stage is slowest?" | Every record has duration_ms and vram_peak_mb. Query across projects to find bottlenecks: SELECT operation, AVG(duration_ms) FROM provenance GROUP BY operation ORDER BY 2 DESC. |
| Integrity: "Has anything been tampered with?" | Run clipcannon_provenance_verify. If any file has been modified or any record altered, the chain hash mismatch is immediately detected. |


#### 7.5.7 Provenance in the VUD

The VUD itself carries a provenance summary so the AI knows the lineage of the data it's reasoning about:

```json
{
  "provenance": {
    "source_file_sha256": "a3f7...",
    "vud_sha256": "9c4e...",
    "pipeline_chain_hash": "7e4a...",
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

### 7.6 Face-Aware Smart Cropping

When converting landscape (16:9) source to vertical (9:16), simple center-crop loses critical content. ClipCannon implements face-aware smart cropping:

Face Detection: Run MediaPipe Face Detection on key frames (1 per scene)
Face Tracking: Interpolate face positions between key frames
Crop Window: Position the 9:16 crop window to keep primary face(s) centered
Smoothing: Apply temporal smoothing to prevent jerky crop movements
Fallback: If no faces detected, use center crop with rule-of-thirds bias

## 8. Robustness & Failure Handling

This section addresses the 8 architectural risks that would cause the system to fail in production if not mitigated.


### 8.1 Context Eviction Mitigation (Long Editing Sessions)

Problem: The AI uses ~291K tokens to understand a 4-hour video. After producing 10+ clips, the conversation exceeds 500K+ tokens and Claude Code compresses early messages — evicting the VUD summary, storyboards, and transcript pages. The AI loses its understanding of the video mid-session.

Solution: The MCP server acts as a stateful VUD cache. The AI can re-query any data at any time without it needing to persist in the conversation context. All understanding data is server-side, not context-side.

Implementation:

Server-Side VUD Cache: The MCP server holds the full VUD, all storyboard grids, and all analysis outputs in memory (or SQLite) for the duration of the session. The AI's context window is a viewport into the data, not the data itself. Data that scrolls out of context is not lost — it is re-queryable.

Pinned Context Block (~3K tokens, always in conversation): A compact manifest that the AI keeps in its working context:

```json
{
  "project_id": "proj_abc123",
  "source": "podcast_ep42.mp4",
  "duration_ms": 14400000,
  "speakers": ["Host", "Guest 1", "Guest 2"],
  "total_highlights": 24,
  "total_scenes": 142,
  "clips_produced": [
    {"clip_id": "clip_001", "range": "14:00-15:00", "platform": "tiktok", "status": "rendered"},
    {"clip_id": "clip_002", "range": "53:20-54:50", "platform": "instagram", "status": "rendered"}
  ],
  "current_task": "Producing clip_003 from highlight at 2:15:00"
}
This manifest is small enough to survive context compression and reminds the AI what it's working on.
```

Re-Query Pattern: When the AI needs data for clip #15 that was loaded for clip #3 (now evicted from context), it simply re-calls the same MCP tool:
clipcannon_get_segment_detail(project_id, start_ms=8100000, end_ms=8160000)
The MCP server returns the same data instantly from cache — no reprocessing.

Clip Registry Tool: clipcannon_get_clip_registry(project_id) returns the current list of all clips produced, their status, and what remains to be done. The AI calls this after context compression to re-orient itself.

Session Persistence: The full session state (VUD cache + clip registry + provenance records) is written to disk at {project_id}/session.db. If Claude Code crashes or the MCP connection drops, the session can be restored with clipcannon_session_restore(project_id).


### 8.2 EDL-to-FFmpeg Translation Layer

Problem: Converting JSON Edit Decision Lists into working ffmpeg -filter_complex commands is extremely error-prone. A 60-second clip with captions + lower third + music + SFX + transitions + smart crop produces a filter_complex string of 2000+ characters with dozens of named stream labels. One wrong bracket crashes the render with a cryptic FFmpeg error.

Solution: Use typed-ffmpeg v3.0 as the primary command builder. All FFmpeg commands are constructed via a type-safe Python API with IDE auto-completion, compile-time validation, and visual debugging.

Library: typed-ffmpeg (github.com/livingbio/typed-ffmpeg, MIT license)

Type safety: catches invalid filter names/parameters before execution
IDE auto-completion: every FFmpeg filter is a typed method
Reversible: can parse existing FFmpeg CLI strings back into Python objects
Visual debugger: v3.0 includes a drag-and-drop graph editor
Pure Python stdlib: no dependencies beyond Python 3.10+
Architecture:

EDL JSON (from AI)
```
    │
    ▼
EDL Validator (Section 8.5)
    │
    ▼
typed-ffmpeg Graph Builder
    ├─ Input streams (source video, audio stems, overlay PNGs, WebM assets)
    ├─ Video filters (trim, crop, scale, overlay, xfade, drawtext)
    ├─ Audio filters (atrim, amix, loudnorm, afade)
    └─ Output (NVENC encode to platform profile)
    │
    ▼
FFmpeg CLI String (auto-generated, type-validated)
    │
    ▼
subprocess.run(["ffmpeg", ...])
    │
    ▼
Rendered output.mp4
Key rule: The AI NEVER writes FFmpeg commands. The AI writes EDL JSON (a high-level declarative spec). The typed-ffmpeg translation layer converts the EDL into valid FFmpeg commands. This separation ensures that FFmpeg complexity is encapsulated in tested, type-safe code — not in LLM-generated strings.
```

Fallback: ffmpegio filtergraph module (python-ffmpegio.github.io) provides an operator-based graph construction API as an alternative.


### 8.3 WhisperX Forced Alignment

Every cut point, caption sync, and temporal alignment depends on word-level timestamp precision. WhisperX with wav2vec2 forced alignment achieves 20-50ms accuracy for word boundaries on the clean vocal stem from HTDemucs.

Pipeline:

```python
import whisperx

# Step 1: Transcribe with Whisper (batch mode for speed)
model = whisperx.load_model("large-v3", device="cuda", compute_type="float16")
audio = whisperx.load_audio("analysis/stems/vocals.wav")  # Clean vocal stem
result = model.transcribe(audio, batch_size=16)

# Step 2: Force-align with wav2vec2 (the critical accuracy step)
align_model, metadata = whisperx.load_align_model(language_code="en", device="cuda")
result = whisperx.align(
    result["segments"], align_model, metadata, audio, device="cuda",
    return_char_alignments=False
)

# Step 3: Speaker diarization (supplements WavLM Stream K)
diarize_model = whisperx.DiarizePipeline(use_auth_token="HF_TOKEN")
diarize_segments = diarize_model(audio)
result = whisperx.assign_word_speakers(diarize_segments, result)
The combination of HTDemucs (clean vocal stem) + WhisperX (forced alignment) produces the most accurate word-level timestamps achievable with current open-source models. This is the foundation every other system depends on.
```


### 8.4 Variable Frame Rate (VFR) Detection and Normalization

Problem: Phone videos, screen recordings, and game captures frequently use variable frame rate (VFR). FFmpeg's timestamp handling with VFR is unreliable. If the source is VFR, all timestamp-based alignment (frames ↔ transcript ↔ embedder data) breaks silently — the AI thinks frame at "timestamp 845000ms" shows one thing, but it actually shows something 200ms earlier or later.

Solution: Detect VFR in the PROBE step (pipeline step 1) and normalize to constant frame rate (CFR) BEFORE any other processing. The CFR-normalized copy becomes the working source for the entire pipeline.

Detection (FFmpeg vfrdet filter):

```bash
ffmpeg -i input.mp4 -vf vfrdet -an -f null - 2>&1 | grep "VFR:"
# Output: VFR:0.354167 — any value > 0.0 means variable frame rate
Normalization (MUST happen before ANY timestamp-dependent processing):

# Normalize to nearest standard CFR rate using NVDEC decode + NVENC encode
ffmpeg -hwaccel cuda -i input_vfr.mp4 \
  -vf "fps=30" \
  -c:v h264_nvenc -preset p4 -crf 18 \
  -c:a copy -vsync cfr \
  source_cfr.mp4
Pipeline integration: VFR normalization is step 1.5 — after PROBE, before EXTRACT AUDIO. If the source is already CFR (detected by vfrdet returning 0.0), this step is skipped and the original file is used directly. The provenance record captures whether normalization occurred and what target frame rate was selected.
```

Target frame rate selection: Round the source's detected maximum frame rate to the nearest standard rate (24, 25, 30, 50, 60 fps). Never upsample — if the source maxes at 24fps, normalize to 24fps.


### 8.5 EDL Timestamp Validation and Snapping

Problem: When the AI writes "source_start_ms": 845200, it is recalling a timestamp from the VUD. LLMs approximate — it might write 845200 instead of 845000, or reference a timestamp that falls mid-word. There is no guarantee the AI-specified timestamps are valid cut points.

Solution: A 3-layer timestamp validator that runs on every EDL before rendering. Each timestamp is snapped to the nearest valid cut point using a priority hierarchy: silence gap > word boundary > nearest frame.

Layer 1 — Bounds Check: Verify all timestamps fall within [0, source_duration_ms]. Reject any EDL with out-of-bounds timestamps.

Layer 2 — Silence Snap (best audio cut quality): Check if a silence gap exists within ±300ms of the specified timestamp. If yes, snap to the midpoint of the silence gap. Silence-based cuts produce zero audio artifacts.

Layer 3 — Word Boundary Snap (no mid-word cuts): For clip start points, snap to the END of the preceding word. For clip end points, snap to the START of the following word. This ensures no word is cut in half. Uses WhisperX forced-alignment timestamps (20-50ms precision).

Layer 4 — Frame Snap: Snap to the nearest extracted frame timestamp (500ms intervals at 2fps). This ensures the visual cut aligns with an actual frame rather than interpolating between frames.

Validation output (returned to the AI so it can verify):

```json
{
  "original_start_ms": 845200,
  "validated_start_ms": 845000,
  "start_snap_type": "silence_gap",
  "start_drift_ms": 200,
  "original_end_ms": 900500,
  "validated_end_ms": 900300,
  "end_snap_type": "word_boundary",
  "end_drift_ms": 200,
  "validation": "passed"
}
MCP Tool: clipcannon_validate_edl(project_id, edl) — validates all timestamps in an EDL and returns the corrected version. This is called automatically by clipcannon_create_edit before saving the EDL.
```


### 8.6 Disk Space Management

Problem: A 4-hour 4K video project can consume 80-120GB of disk space. Multiple projects can exhaust storage quickly. There is no cleanup strategy.

Solution: 3-tier file classification with lifecycle policies. Every file produced by the pipeline is classified as Sacred (never delete), Regenerable (can be recreated from sacred files), or Ephemeral (delete after use).


##### Tier 1 — Sacred (never auto-delete):


| File | Why Sacred |
|:---|:---|
| Original source video | Cannot be recreated |
| EDL JSON files | The AI's creative decisions (tiny files) |
| Project manifest + provenance.db | Audit trail (tiny files) |
| Final rendered output clips | Delivered product |


##### Tier 2 — Regenerable (delete when disk space needed, recreate from sacred files on demand):


| File | Recreated By |
|:---|:---|
| CFR-normalized source copy | Re-run VFR normalization on original |
| Audio stems (vocals.wav, music.wav, etc.) | Re-run FFmpeg extract + HTDemucs on original |
| Extracted frames (JPEGs) | Re-run FFmpeg frame extraction |
| Storyboard grid JPEGs | Re-composite from extracted frames |
| analysis.db (entire database) | Re-run full pipeline on original source |


##### Tier 3 — Ephemeral (delete immediately after their consumer completes):


| File | Lifetime |
|:---|:---|
| Intermediate render segments | Deleted after final concatenation |
| Temp audio chunks | Deleted after WhisperX completes |
| Preview renders (low-res) | Deleted after human review |
| Animation frame sequences (PNGs) | Deleted after FFmpeg composites them |

Disk budget estimate (4-hour 4K source):

| Tier | Size | Persistent? |
|:---|:---|:---|
| Sacred (source + renders + metadata) | 30-45 GB | Always |
| Regenerable (when all analysis cached) | 30-50 GB | Until space needed |
| Ephemeral (during pipeline run) | 10-30 GB | Deleted automatically |
| Peak usage | 70-125 GB | During processing |
| Steady-state | 30-45 GB | After cleanup |

MCP Tool: clipcannon_disk_status(project_id) — returns current usage by tier. clipcannon_disk_cleanup(project_id, target_free_gb) — frees space by deleting ephemeral first, then regenerable (largest first).

Proactive cleanup: Ephemeral files are deleted automatically as each pipeline step completes. The system warns when disk space falls below 20GB free.


### 8.7 Graceful Pipeline Degradation

Problem: The 12-stream understanding pipeline runs 18 processing steps. If one stream fails (e.g., Wav2Vec2 crashes on a corrupt audio segment, PaddleOCR fails on unusual frame encoding), should the entire pipeline fail? If yes, the user gets nothing from a 15-minute processing run. If no, how does the AI know which data is missing?

Solution: DAG-based execution with required and optional tasks. Required tasks (audio extraction, VFR normalization) stop the pipeline on failure. Optional tasks (emotion analysis, OCR, beat detection) provide fallback empty values and mark themselves as failed in the VUD.

Task Classification:

| Task | Required? | If It Fails |
|:---|:---|:---|
| Probe | Yes | Pipeline stops — can't read the file |
| VFR normalization | Yes | Pipeline stops — timestamps will be unreliable |
| Audio extraction | Yes | Pipeline stops — no audio = no transcript |
| HTDemucs source separation | No | Fallback: feed mixed audio to all audio models (lower quality, still functional) |
| WhisperX transcription | Yes | Pipeline stops — transcript is the primary editing signal |
| SigLIP visual embedding | No | Fallback: no scene detection, no visual similarity. AI relies on storyboard grids only. |
| PaddleOCR text detection | No | Fallback: empty on_screen_text[]. AI can still read text from storyboard grid images. |
| Quality assessment | No | Fallback: all scenes classified as "unknown" quality. AI skips quality filtering. |
| Shot type classification | No | Fallback: all scenes classified as "unknown" shot type. AI uses default crop strategy. |
| Nomic semantic embedding | No | Fallback: no topic segmentation. AI uses transcript directly for topic identification. |
| Wav2Vec2 emotion | No | Fallback: flat emotion curve (energy=0.5 everywhere). Highlights rely on reactions + transcript only. |
| WavLM speaker diarization | No | Fallback: single speaker "speaker_0" for all segments. WhisperX diarization may partially cover. |
| SenseVoice reactions | No | Fallback: empty reactions[]. Highlights rely on emotion + transcript only. |
| Beat This! beat detection | No | Fallback: no beat grid. AI places cuts without beat-snapping. |
| Acoustic analysis | No | Fallback: no silence gaps detected. AI uses word boundaries for cut points. |
| Content safety | No | Fallback: content rated "unknown". AI includes content safety disclaimer. |
| Chronemic computation | No | Fallback: no pacing data. AI estimates pacing from transcript word count. |
| Storyboard generation | No | Fallback: AI requests individual frames via clipcannon_get_frame instead. |

VUD marks failed streams explicitly:

```json
{
  "stream_status": {
    "transcription": "completed",
    "visual": "completed",
    "ocr": "failed",
    "quality": "completed",
    "shot_type": "completed",
    "semantic": "completed",
    "emotion": "failed",
    "speaker": "completed",
    "reactions": "completed",
    "beats": "completed",
    "acoustic": "completed",
    "chronemic": "completed"
  },
  "failed_streams": ["ocr", "emotion"],
  "degradation_note": "OCR and emotion analysis failed. On-screen text detection unavailable. Emotion energy data is flat (0.5). Highlights rely on reactions and transcript only."
}
The AI reads stream_status and degradation_note and adjusts its editing strategy accordingly. It does not crash or refuse to edit — it works with what it has, like a human editor working with incomplete notes.
```


### 8.8 Generation Loss Prevention

Problem: If the user rejects a clip and the AI re-renders with changes, the system might accidentally render from a previously rendered output instead of the original source. Each re-encode degrades quality (generation loss). Over 2-3 re-renders, compression artifacts become visible.

Solution: Immutable Source Reference architecture. Every EDL and every render command traces back to the original source video via a SHA-256-verified reference. The rendering engine physically cannot accept a rendered output as input.

Enforcement rules:

Every EDL contains an immutable source reference: source_file_sha256 that was computed during probe. The rendering engine verifies this hash matches the file before rendering. If the file has been modified or replaced, rendering is rejected.

Rendered outputs are tagged: All rendered files are written to renders/{render_id}/output.mp4. The rendering engine refuses to open any file from a renders/ directory as a source input.

Single-pass rendering: When an EDL specifies multiple segments (multi-segment clip), the typed-ffmpeg translation layer builds ONE FFmpeg filter_complex command that reads all segments from the original source and concatenates in a single encode pass. There are no intermediate rendered segments that get re-encoded.

Re-render = new render from source: When the AI modifies an EDL and re-renders, it creates a new render job that reads from the original source. The previous render output is not touched — it can be deleted (ephemeral tier) or kept for comparison.

Provenance enforces lineage: Every render provenance record contains input.sha256 pointing to the original source's hash. If a render record's input hash matches any output hash from a prior render, the provenance chain integrity check fails — detecting accidental generation loss.


## 9. Publishing Pipeline

(Section numbers 9.1, 9.2 below)


### 9.1 Platform API Integration

Publishing is the final phase. Each platform requires OAuth authentication and has specific API endpoints for video upload.


#### 8.1.1 YouTube Data API v3

| Aspect | Details |
|:---|:---|
| Auth | OAuth 2.0 (Google Cloud Console project required) |
| Scopes | youtube.upload, youtube.readonly |
| Upload | Resumable upload via videos.insert |
| Max File | 256 GB / 12 hours |
| Rate Limits | 10,000 units/day (each upload costs 1600 units) |
| Metadata | Title (100 chars), description (5000 chars), tags, category, privacy |
| Shorts | Upload as regular video with #Shorts in title/description, vertical aspect |


#### 8.1.2 Meta Graph API (Instagram + Facebook)

| Aspect | Details |
|:---|:---|
| Auth | OAuth 2.0 via Facebook Login (Meta Business Suite) |
| Instagram Reels | Content Publishing API: POST /{ig-user-id}/media (type=REELS) |
| Instagram Feed | Content Publishing API: POST /{ig-user-id}/media (type=VIDEO) |
| Facebook Reels | POST /{page-id}/video_reels |
| Facebook Feed | POST /{page-id}/videos |
| Requirements | Instagram Business/Creator account, Facebook Page |
| Upload | Resumable upload with upload session |
| Rate Limits | 25 content publishes per day (Instagram), 50 API calls/hour |


#### 8.1.3 TikTok Content Posting API

| Aspect | Details |
|:---|:---|
| Auth | OAuth 2.0 (TikTok Developer Portal app required) |
| Scopes | video.publish, video.upload |
| Upload Flow | 1) Init upload → 2) Upload video chunks → 3) Publish with metadata |
| Metadata | Description (2200 chars), privacy level, disable comments/duet/stitch flags |
| Requirements | TikTok Developer account, app review |
| Rate Limits | Varies by app tier |
| Note | Direct posting requires app review; "Share to TikTok" is alternative |


#### 8.1.4 LinkedIn API

| Aspect | Details |
|:---|:---|
| Auth | OAuth 2.0 (LinkedIn Developer app) |
| Scopes | w_member_social (personal), w_organization_social (company) |
| Upload Flow | 1) Register upload → 2) Upload binary → 3) Create post with video asset |
| Metadata | Commentary text (3000 chars), visibility |
| Rate Limits | 100 API calls/day for most apps |
| Requirements | LinkedIn Developer app with Marketing API access |


### 9.2 Human Approval Workflow

All content goes through human approval before publishing:

```
PUBLISH WORKFLOW
================
```

1. AI generates edit + renders output + generates metadata
2. Post enters REVIEW queue with:
   - Rendered video file (playable locally)
   - Platform-specific metadata (title, description, hashtags)
   - Suggested publish time (if scheduling enabled)
   - Thumbnail image

3. Human reviews via MCP tool calls:
   clipcannon_publish_review → see all pending posts
   clipcannon_get_frame → inspect specific moments
   (Watch the rendered video locally)

4. Human decides:
   clipcannon_publish_approve → approve for publishing
   clipcannon_publish_reject → reject with feedback
                            (AI can regenerate based on feedback)

5. Approved posts are published:
   clipcannon_publish_execute → push to platform API
   clipcannon_publish_status → confirm successful upload

## 9. Business Model & Billing


### 9.1 Strategic Positioning (Value Equation)

ClipCannon's competitive advantage is built on the Hormozi Value Equation:

Value = (Dream Outcome × Perceived Likelihood) / (Time Delay × Effort & Sacrifice)
| Element | ClipCannon Delivery | Competitor (Manual) |
|:---|:---|:---|
| Dream Outcome | 20+ platform-ready clips from one video, with titles, descriptions, captions | Same result, eventually |
| Perceived Likelihood | Consistent AI analysis + human approval gate = reliable output | Depends on editor skill |
| Time Delay | 5 min analysis + seconds per render = minutes total | 4-8 hours per source video |
| Effort & Sacrifice | Drop video in, approve outputs. Zero editing skills needed | Learn editing software, make decisions frame-by-frame |

Competitive Vectors (win on all four):

Speed: 5-minute analysis vs. hours. Render in seconds, not minutes. 3 parallel NVENC encoders
Risk: AI produces consistent quality. Human approval prevents bad posts. Performance-based billing (only charge on success)
Ease: One video in → everything handled. No editing skills required. Dashboard shows everything clearly
Price: Local GPU = zero per-API-call cost. Amortized over volume, drastically cheaper than human editors ($50-150/hour) or cloud services ($20-50/video)

### 9.2 Grand Slam Offer

Make the offer so good people feel stupid saying no:

What they get:

Full multimodal video understanding (12 parallel AI streams)
AI-generated edit plans with highlight detection
Platform-optimized renders for 5 platforms (TikTok, Instagram, YouTube, Facebook, LinkedIn)
Word-level animated captions burned in
Face-aware smart cropping (landscape → vertical)
AI-composed original background music (no licensing fees, no copyright claims, commercially safe)
Programmatic sound effects (transition whooshes, risers, impacts, stingers, chimes)
Professional animated lower thirds (10 template styles, custom text/colors/animation)
Animated title cards with kinetic typography
28+ built-in Lottie animations (subscribe CTAs, emoji reactions, social icons, decorative effects)
20+ pre-rendered video effects (light leaks, bokeh, glitch, particles, film grain)
104+ transition types (44 FFmpeg native + 60 GL shader ports)
AI-generated titles, descriptions, and hashtags per platform
Human approval dashboard before anything publishes
All processing on their own GPU (data never leaves their machine)
What they risk: Nothing. Performance-based billing — only charged when analysis completes successfully. Failed processing = automatic refund.

The guarantee: Conditional — if analysis doesn't produce at least 5 viable clips from a video over 10 minutes long, no charge. Once you have reputation (anti-guarantee), the guarantee becomes unnecessary because results speak.


### 9.3 Pricing Model

Adapted from OCR Provenance's proven dual-layer billing architecture:


#### 9.3.1 Per-Video Credit System

| Operation | Credit Cost | Rationale |
|:---|:---|:---|
| Video Analysis (full 12-stream pipeline) | 10 credits | GPU-intensive: transcription + embeddings + frame extraction |
| Clip Render (per output clip, includes audio + animations) | 2 credits | NVENC encoding + caption burn + crop + audio mix + overlay compositing |
| AI Music Generation (per track, included in render) | 0 credits | Included in clip render cost -- no separate music licensing fees |
| Metadata Generation (per clip per platform) | 1 credit | AI-generated title + description + hashtags |
| Platform Publish (per post) | 1 credit | API call + upload + status tracking |

Credit Packages (Stripe checkout):

| Package | Credits | Price | Per-Credit | Use Case |
|:---|:---|:---|:---|:---|
| Starter | 50 | $5 | $0.10 | Try it out (5 source videos) |
| Creator | 250 | $20 | $0.08 | Weekly content creator |
| Pro | 1,000 | $60 | $0.06 | Daily content production |
| Studio | 5,000 | $200 | $0.04 | Agency / multi-channel |
| Unlimited | Unlimited | $99/month | — | Subscription for high-volume users |

Why credits, not subscription-only: Credits align cost with value delivered. A user who processes 2 videos/month shouldn't pay the same as someone processing 50. Credits also have zero ongoing cost when idle (no monthly drain). The unlimited tier serves power users who want predictability.

Example workflow cost: 1-hour podcast → full analysis (10 credits) + 15 clips rendered (30 credits) + metadata for all 5 platforms per clip (75 credits) = 115 credits = ~$7-12 depending on package. Compare to hiring a human editor: $200-500 for the same output.


#### 9.3.2 Billing Architecture

Directly adapted from OCR Provenance's proven system:

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  ClipCannon MCP     │     │  License Server   │     │  Cloudflare D1   │
│  Server (local)  │────▶│  (port 3100)      │────▶│  (source of truth)│
│                  │     │  SQLite cache      │     │  Stripe webhooks  │
│  LicenseClient   │     │  HMAC integrity    │     │  Credit balances  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
Charge Flow:
```

User initiates video analysis via MCP tool
MCP server calls POST /v1/charge on local license server
License server deducts credits locally + verifies with Cloudflare D1 (source of truth)
On success: credits confirmed, processing begins
On failure (insufficient credits): automatic refund, processing blocked with clear message
On processing error: automatic refund to local + central balance
HMAC Balance Integrity: Every credit mutation is HMAC-SHA256 signed. Tampered balances trigger fatal exit. Same proven pattern as OCR Provenance.

Machine ID + License Key: Deterministic HMAC key from machine ID. Same machine always gets same key. Balance persists across container restarts.


#### 9.3.3 Spending Controls

Monthly spending caps: $5 - $500 (user-configurable)
Dashboard warning at 80% of limit
Per-video cost estimate shown before processing begins
Detailed cost breakdown in project view

### 9.4 Revenue Model

Revenue = Credits Sold × Margin

Cost per credit to us:
  - Infrastructure: ~$0 (user's GPU, user's electricity)
  - Cloudflare D1: ~$0.001/transaction
  - Stripe fees: 2.9% + $0.30 per checkout
  - Development + maintenance: amortized

Gross Margin: ~95% (no cloud compute costs — user provides GPU)
Growth levers:

Volume: More creators → more credits purchased
Platform expansion: Add more platforms (Twitter/X, Pinterest, Threads) → more renders per source
Premium features: Advanced ACE-Step LoRA fine-tuning, custom brand audio styles, premium animation packs at higher credit rates
Agency tier: Multi-seat dashboard, team management, bulk pricing
Template marketplace: User-created editing templates (audio presets, animation styles, brand kits), revenue share
Animation marketplace: Community-contributed Lottie/WebM animation packs, credit-based purchasing

## 10. Dashboard & Human-in-the-Loop Interface


### 10.1 Architecture

The dashboard is a web application running locally as part of the ClipCannon container, providing the human-in-the-loop interface for reviewing, approving, and managing all AI-generated content.

```
┌──────────────────────────────────────────────────────┐
│  Docker Container (3 Mandatory Services)              │
│                                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐│
│  │ ClipCannon MCP │  │License Server│  │  Dashboard   ││
│  │ Server      │  │  port 3100   │  │  port 3200   ││
│  │ port 3366   │  │  Billing/Auth│  │  Web UI      ││
│  │ 60+ tools   │  │  Credits     │  │  Review/     ││
│  │             │  │  Stripe      │  │  Approve     ││
│  └──────┬──────┘  └──────────────┘  └──────────────┘│
│         │                                             │
│  ┌──────▼───────────────────────────────────────────┐│
│  │  GPU Processing Pipeline (Python Workers)         ││
│  │  Whisper │ SigLIP │ Wav2Vec2 │ WavLM │ FFmpeg   ││
│  └──────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
```

### 10.2 Dashboard Pages


#### 10.2.1 Main Dashboard (Home)

Credit Balance: Current credits remaining + credits consumed this month
Projects Overview: Active projects with status indicators (analyzing, ready for review, published)
Recent Activity: Timeline of analyses, renders, approvals, and publications
Quick Stats: Videos processed, clips generated, posts published (this week/month)
System Health: GPU status, VRAM usage, model loading status, disk space

#### 10.2.2 Project View

Source Video: Thumbnail, duration, resolution, file info
Analysis Status: Progress bar for each of the 12 streams (source separation, visual, OCR, quality, shot type, transcript, semantic, emotion, speaker, reactions, acoustic/beats, chronemic)
Video Understanding Summary: AI-generated summary of the video content, topics detected, speakers identified, highlight moments
Timeline Visualization: Interactive timeline showing:
Scene boundaries (visual)
Speaker segments (color-coded)
Emotion/energy curve (graph overlay)
Topic segments (labeled regions)
Detected highlights (starred markers)
Transcript Panel: Full searchable transcript with speaker labels and timestamps. Click to jump to that point in the video preview

#### 10.2.3 Edit Review Page (Core Human-in-the-Loop)

This is where the human reviews and approves AI-generated edits:

Clip Preview Player: Watch the rendered clip directly in the browser
Platform Preview: Side-by-side mockups showing how the clip will appear on each target platform (phone frame for TikTok/Reels, desktop for YouTube/LinkedIn)
Metadata Review:
Title (editable)
Description (editable)
Hashtags (editable, with suggestions)
Thumbnail (selectable from key frames)
Caption Preview: See burned-in captions in real-time in the video player
Action Buttons:
Approve → moves to publishing queue
Approve with Edits → save metadata changes, then approve
Reject → provides feedback to AI for regeneration
Regenerate → re-run AI edit suggestions with adjusted parameters
Skip → move to next clip in batch

#### 10.2.4 Publishing Queue

Pending Approval: All clips awaiting human review (batch review mode)
Approved (Ready to Publish): Clips approved but not yet published
Scheduled: Clips scheduled for future publishing
Published: History of all published posts with links
Rejected: Clips that were rejected with feedback notes
Platform Status: Connection status for each social media account (connected/disconnected/token expiring)

#### 10.2.5 Account & Billing

Credit Balance: Current balance with visual indicator
Add Credits: Preset buttons ($5, $20, $60, $200) → Stripe checkout
Subscription Management: Upgrade/downgrade/cancel unlimited plan
Usage History: Table of all charges (date, operation, credits used, project)
Spending Limit: Set monthly cap with 80% warning threshold
API Key: Display (prefix only) with regeneration option
Connected Platforms: OAuth connection status for all 5 platforms

#### 10.2.6 Settings

Processing Defaults: Default whisper model, frame extraction rate, caption style
Platform Profiles: Default encoding profiles, preferred aspect ratios per platform
Output Preferences: Default output directory, naming convention, thumbnail settings
GPU Configuration: VRAM allocation, concurrent model limits, NVENC encoder count

### 10.3 Authentication

Adapted from OCR Provenance's magic link system:

User enters email → POST /login
Server generates signed JWT (10-min expiry)
Email sent via Resend API (or dev mode returns token in console)
User clicks magic link → GET /auth/verify?token=...
Token verified → session created (30-day TTL)
HTTP-only cookie set → redirect to /dashboard
Environment Isolation: Dashboard runs with whitelisted env vars only. Cannot access license signing keys or Stripe webhook secrets. Even if compromised, cannot forge credits or payments.


### 10.4 Human-in-the-Loop Workflow

```
AI GENERATES CONTENT
        │
        ▼
┌───────────────────────────────────┐
│        DASHBOARD REVIEW           │
│                                   │
│  ┌─────────┐  ┌──────────────┐  │
│  │ Preview  │  │  Metadata    │  │
│  │ Player   │  │  Editor      │  │
│  │          │  │              │  │
│  │ [Play]   │  │  Title: ...  │  │
│  │          │  │  Desc: ...   │  │
│  │          │  │  Tags: ...   │  │
│  └─────────┘  └──────────────┘  │
│                                   │
│  ┌─────────────────────────────┐ │
│  │ Platform Previews           │ │
│  │  📱 TikTok  📱 Reels       │ │
│  │  🖥️ YouTube  💼 LinkedIn   │ │
│  └─────────────────────────────┘ │
│                                   │
│  [✓ Approve] [✎ Edit] [✗ Reject] │
└───────────────────────────────────┘
        │
        ├── Approved ──► Publishing Queue ──► Platform API
        │
        ├── Edited ──► Save changes ──► Approved
        │
        └── Rejected ──► Feedback to AI ──► Regenerate
Batch Review Mode: For efficiency, the dashboard supports batch review where the human can swipe through all clips from a source video, approve/reject each with one click, and edit metadata inline. Target: review 20 clips in under 5 minutes.
```

Notification System: When analysis completes or clips are ready for review, the dashboard shows a notification badge. Optional: browser push notifications, email notifications, or webhook to Slack/Discord.


## 11. Business Strategy


### 11.1 Go-to-Market: Content Creators First

Initial Target: Solo content creators who produce long-form video (podcasts, interviews, talks, tutorials) and need to repurpose for social media but can't afford editors.

Why this segment first:

Pain is acute and daily (hours spent editing every week)
They already own capable GPUs (gaming/streaming rigs with RTX 3070+)
Price-sensitive (can't afford $200/video human editors)
Technical enough to run Docker containers
Small enough that 1-2 users per machine is fine
Vocal community (will share tools that save them time)
Expansion path: Solo creators → Small agencies → Media companies → Enterprise


### 11.2 Acquisition Strategy (Hormozi Leads Framework)

Free content lead generation (eat your own dog food):

Use ClipCannon to process YOUR OWN content about ClipCannon
Every demo video is also a proof-of-concept: "This video was cut into 15 clips and posted to 5 platforms by ClipCannon"
Technical tutorials as lead magnets
Open-source the MCP server, monetize through credits (freemium model)
The 4 ways to get customers (Hormozi):

Warm outreach: DM content creators you follow. "I built something that turns your 1-hour podcast into 20 platform-ready clips in 5 minutes. Want to try it?"
Content: YouTube/Twitter showing before/after of ClipCannon processing a real video
Cold outreach: Automated but personalized emails to creators with >10K subscribers who post long-form
Paid ads: After product-market fit, scale with paid acquisition

### 11.3 Retention Levers

Consistency (Hormozi risk vector): Every analysis produces reliable, predictable output. Users learn to trust it
Speed addiction (Hormozi speed vector): Once you've experienced 5-minute video repurposing, going back to manual editing is painful
Data lock-in (positive): Project history, editorial preferences, platform analytics accumulate over time
Habit formation: Content creators produce on a schedule. ClipCannon becomes part of the weekly workflow
Credit balance: Pre-purchased credits create commitment (sunk cost + convenience)

### 11.4 Pricing Psychology

From Hormozi's framework:

Charge more, not less: Position as premium tool ($0.04-0.10/credit) not race-to-bottom. The value delivered ($200+ of human editor time saved per video) supports premium pricing
Anchor to alternatives: "A human editor charges $200/video. ClipCannon processes the same video for $7-12"
Remove risk: Performance-based billing. Only charged on successful analysis. Failed = refund
Stack the value: Analysis + editing + rendering + captions + metadata + thumbnail + publishing prep = one price. Don't unbundle
Urgency via volume: Show "X credits remaining" prominently. Credit packages feel like buying ammunition — you want to have enough

### 11.5 Moat & Defensibility

Speed + Ease dominance: No competitor offers 12-stream multimodal understanding locally. Existing tools (Opus Clip, Descript) are cloud-only, per-video priced, and don't run locally
Local-first: Data never leaves the machine. Critical for creators with unreleased content, brand deals, or NDAs
GPU utilization: Amortizes the RTX 5090 investment that creators already made for gaming/streaming. Zero marginal compute cost
Embedder architecture: The Hexa-Modal-derived 12-stream approach is novel and produces richer understanding than competitors using only transcription
MCP protocol: Plugs into any AI model, not locked to one vendor. Future-proof against model provider changes
Zero-cost audio: AI-generated music and programmatic SFX eliminate stock music licensing fees ($15-50/track at competitors). Every generated track is original, commercially safe, and tailored to the content
Full creative suite: Professional motion graphics (lower thirds, titles, transitions, CTAs) built in -- competitors like Opus Clip produce bare clips with no overlays. CapCut has templates but requires manual selection. ClipCannon's AI selects and parameterizes overlays autonomously

## 12. Phased Delivery (Updated)


### Phase 1: Video Understanding + Billing + Provenance Foundation

Deliverables:

MCP server scaffold with project management tools
Video ingestion pipeline (FFmpeg probe + audio extraction + frame extraction)
Transcription via faster-whisper with word-level timestamps
Frame embedding via SigLIP
Scene boundary detection
Video Understanding Document (VUD) generation with AI-readable translations (scene descriptions, topic labels, energy scores -- not raw embeddings)
SHA-256 Provenance Hash Chain: provenance.db per project, hash computation at every pipeline stage, chain integrity verification, provenance query MCP tools (clipcannon_provenance_verify, clipcannon_provenance_query, clipcannon_provenance_chain)
Basic MCP tools: clipcannon_ingest, clipcannon_get_vud, clipcannon_get_transcript, clipcannon_get_frame
License server with credit-based billing (Cloudflare D1 + Stripe)
Machine ID provisioning + HMAC balance integrity
Basic dashboard: balance display, add credits, system health, provenance chain viewer
Success Criteria:

Process a 1-hour video in under 5 minutes
Accurate word-level timestamps (WER < 5% on English content)
Scene detection captures 90%+ of visual transitions
Credit charge/refund flow works end-to-end
VUD contains AI-readable data (text labels, scores, timestamps) not raw embeddings
Provenance chain has 11 records (probe through VUD synthesis) with valid chain hashes
clipcannon_provenance_verify passes on every completed project
Any file modification after provenance recording is detected by hash mismatch

### Phase 2: Editing Engine + Audio + Dashboard

Deliverables:

Full audio embedding pipeline (emotion, speaker, acoustic)
Topic segmentation and highlight detection
EDL format and edit creation tools (with audio + animation specs)
Caption generation and rendering
Face-aware smart cropping
Platform encoding profiles
FFmpeg rendering pipeline with NVENC
All editing and rendering MCP tools
Batch rendering
AI Audio Generation Engine:
ACE-Step v1.5 integration for AI-generated background music
MIDI composition pipeline (MIDIUtil + music21 + FluidSynth)
Programmatic DSP sound effects (whooshes, risers, impacts, chimes)
Audio mixing pipeline with ducking, crossfade, normalization (pydub + pedalboard)
Audio generation MCP tools (clipcannon_generate_music, clipcannon_compose_midi, clipcannon_generate_sfx)
Full dashboard with project view, timeline visualization, clip preview player
Edit review page with approve/reject/edit workflow
Batch review mode for human-in-the-loop efficiency
Success Criteria:

AI can produce 10+ platform-ready clips from a single 1-hour source
Render time < 30 seconds per clip
Captions are word-accurate and properly timed
Output passes platform validation for all 5 target platforms
Human can review and approve 20 clips in under 5 minutes via dashboard
AI-generated music is coherent, mood-appropriate, and at least 30 seconds long
DSP sound effects are clean (no clicks/pops) and properly timed to transitions
Audio ducking correctly reduces music under speech segments

### Phase 3: Motion Graphics, Publishing & Full Dashboard

Deliverables:

Motion Graphics & Animation Engine:
PyCairo-based lower third rendering (10 template styles) with slide/fade/pop animations
PyCairo-based title card rendering with kinetic typography
Lottie animation rendering pipeline (rlottie-python) with shipped 28-asset pack
Pre-rendered WebM overlay system with shipped 20-asset effects pack
60+ GL Transition shaders ported to FFmpeg xfade expressions
Animation MCP tools (clipcannon_add_lower_third, clipcannon_add_animation, clipcannon_add_transition, etc.)
Optional LottieFiles.com asset fetching (100K+ free animations)
Custom asset import system for user-provided WebM/Lottie files
Metadata generation (titles, descriptions, hashtags per platform)
Thumbnail generation
Human approval workflow
OAuth integration for all 5 platforms
Publishing API integration (YouTube, Instagram, TikTok, Facebook, LinkedIn)
Publishing queue management with scheduling
Post-publish status tracking
Publishing queue dashboard page with batch approve/reject
Platform connection management (OAuth flows in dashboard)
Account & billing page with full credit history, spending limits
Success Criteria:

Generated metadata is platform-appropriate and engaging
OAuth flows work for all 5 platforms
Successful automated posting with human approval gate
Full audit trail of all publishing actions
Credit billing accurate across all operations
Lower thirds render at 1080p with smooth animation (no jank/stutter)
Lottie animations render at correct frame rate with proper alpha transparency
All 44+ FFmpeg native transitions work reliably between segments
Animation overlays do not degrade render speed by more than 20%

### Phase 4: Intelligence, Optimization & Growth

Deliverables:

Content performance feedback loop (if analytics APIs available)
Improved highlight detection using performance data
A/B testing support (generate multiple versions of same clip)
Scheduling optimization (best time to post per platform)
Template system for recurring content types (save audio/animation presets)
Multi-language support for captions and metadata
Advanced Audio: ACE-Step LoRA fine-tuning on user's brand audio style, custom SoundFont import, audio style presets per content type
Advanced Animation: User-created PyCairo template builder (define custom lower third designs), brand kit system (consistent colors/fonts across all overlays), animated thumbnail generation
Animation Marketplace: Community-contributed Lottie/WebM animation packs with credit-based purchasing
Agency tier: Multi-seat dashboard, team accounts, bulk credit pricing
Usage analytics dashboard: Cost per video, ROI tracking, performance heatmaps
Unlimited subscription tier for high-volume creators

## 10. Data Flow Summary

SOURCE VIDEO (mp4/mov/mkv/webm)
```
         │
         ▼
    ┌─────────┐
    │  INGEST  │──── FFprobe metadata
    └─────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
 AUDIO     FRAMES
 (16kHz)   (2fps JPEGs)
    │         │
    ├─────┐   │
    │     │   │
    ▼     ▼   ▼
 WHISPER  AUDIO  SIGLIP
 (transcript) (embedders) (visual embeddings)
    │     │         │
    │     ├─────┐   │
    │     │     │   │
    ▼     ▼     ▼   ▼
 NOMIC  EMOTION SPEAKER SCENES
 (semantic) (energy) (who)  (where)
    │     │     │     │
    └─────┴─────┴─────┘
              │
              ▼
    ┌─────────────────┐
    │  VIDEO UNDERSTANDING  │
    │    DOCUMENT (VUD)     │
    └─────────────────┘
              │
         AI MODEL READS VUD
         AI MODEL PRODUCES EDL
              │
              ▼
    ┌─────────────────┐
    │   EDIT DECISION  │
    │  LIST (EDL) with │
    │  audio + animation│
    │  specifications   │
    └─────────────────┘
              │
    ┌────┬────┴────┬────┐
    │    │         │    │
    ▼    ▼         ▼    ▼
  AUDIO  MIDI    DSP   ANIMATION
  GEN    COMP    SFX   RENDER
  (ACE-  (music21 (numpy (PyCairo
  Step)  +Fluid  scipy) +rlottie
         Synth)         +WebM)
    │    │         │    │
    └────┴────┬────┴────┘
              │
         AUDIO MIX
         (pydub)
              │
              ▼
    ┌─────────────────┐
    │  FFMPEG RENDER   │
    │  (NVENC/NVDEC)   │
    │  + overlay comp  │
    │  + audio mux     │
    └─────────────────┘
              │
    ┌────┬────┬────┬────┐
    │    │    │    │    │
    ▼    ▼    ▼    ▼    ▼
  TIKTOK INSTA  YT   FB  LI
  9:16  9:16  16:9  9:16 1:1
  60s   90s   10m   60s  3m

              │
         HUMAN REVIEW
              │
              ▼
    ┌─────────────────┐
    │  PUBLISH TO      │
    │  PLATFORM APIs   │
    └─────────────────┘
```

## 11. Feasibility Assessment


### 11.1 Can the AI Edit Video With This Information?

Yes. Here is why:

The fundamental question is whether the decomposed streams provide sufficient information for an AI to make intelligent editing decisions. The answer is definitively yes, because the 12-stream pipeline covers every dimension a human editor considers:

Source Separation (HTDemucs) isolates clean vocal, music, and noise stems — ensuring every downstream audio model operates on clean input rather than a mixed signal. This is the force multiplier that makes all audio analysis dramatically more accurate.

Transcript + timestamps (faster-whisper on vocal stem) gives the AI complete knowledge of what is being said and when. With source separation, transcription accuracy improves significantly on music-heavy sources.

Visual embeddings + scene detection (SigLIP) gives the AI knowledge of what is being shown and when the visual context changes.

On-screen text (PaddleOCR) gives the AI knowledge of what text is displayed — slide titles, URLs, names, code. Critical for tutorials, presentations, and product demos. Enables slide-based chapter detection.

Visual quality (BRISQUE/DOVER) gives the AI knowledge of which frames are sharp and well-lit vs. blurry and shaky. The AI never selects low-quality footage for highlights.

Shot type (ResNet-50) gives the AI knowledge of how the camera is framed — close-up, medium, wide. Directly drives cropping decisions for platform-specific aspect ratios.

Emotion/energy (Wav2Vec2 on vocal stem) gives the AI knowledge of the emotional arc. With source separation, emotion detection is not contaminated by background music energy.

Speaker diarization (WavLM on vocal stem) gives the AI knowledge of who is speaking when. With source separation, speaker embeddings are cleaner.

Reactions (SenseVoice) gives the AI knowledge of where laughter, applause, and audience engagement occurs. This is the strongest highlight signal for conversational content — a signal no other stream captures.

Beat detection (madmom on music stem) gives the AI knowledge of where musical beats fall. Enables professional cut-on-beat editing when music is present.

Acoustic features (Librosa) gives the AI knowledge of silence gaps, music sections, and volume dynamics.

Content safety (profanity detection) gives the AI knowledge of where profanity occurs for auto-bleep and platform-appropriate content selection.

Chronemic features give the AI knowledge of pacing and rhythm. Fast-paced sections indicate excitement. Slow sections may indicate reflection or filler.

The AI does NOT need to:

See every pixel of the video (sampled frames at 2fps + on-demand frame retrieval are sufficient)
Process video in real-time (batch analysis is fine)
Understand video at the codec level (FFmpeg handles all encoding/decoding)
Make frame-accurate edits visually (timestamp-based cuts with sentence/scene alignment are more important than frame-perfect timing)

### 11.2 Hardware Sufficiency

The RTX 5090 with 32GB VRAM is more than sufficient:

| Workload | VRAM Required | Time (1hr source) |
|:---|:---|:---|
| All embedding models loaded concurrently | ~6.6 GB | One-time load |
| Transcription (faster-whisper large-v3) | ~3.0 GB | 60-120s |
| Frame embedding (SigLIP, batch=64) | ~1.2 GB + batch | 60s |
| Video decode (NVDEC) | ~0.5 GB | During extraction |
| Video encode (NVENC, per render) | ~0.5 GB | 10-30s per clip |
| Peak concurrent | ~12 GB | Well within 32GB |

The Ryzen 9 9950X3D with 32 threads handles FFmpeg orchestration, I/O, and CPU-bound preprocessing with significant headroom.

128GB DDR5 RAM accommodates frame caches (7200 JPEGs ~ 2-3GB), embedding arrays, and multiple concurrent operations.


### 11.3 Key Technical Risks

| Risk | Impact | Mitigation |
|:---|:---|:---|
| Smart cropping quality on complex scenes | Medium | Fall back to center crop; use face detection when available |
| Caption timing drift on fast speech | Medium | Use word-level timestamps; minimum display duration per chunk |
| Social media API rate limits | Low | Queue with rate limiting; batch scheduling |
| Social media API changes/deprecation | Medium | Abstract API layer; modular platform adapters |
| Large source files (4K, multi-hour) | Medium | Chunked processing; stream-based pipeline; NVDEC acceleration |
| AI-generated music quality inconsistency | Medium | Use seed-based generation for reproducibility; fall back to MIDI composition if quality score is low; human review in dashboard |
| AI music copyright concerns | Low | ACE-Step MIT license covers model + output; all MIDI compositions are original; DSP SFX are mathematical -- no copyright applies |
| Lottie rendering fidelity gaps | Low | rlottie does not support all After Effects features; curate shipped assets to only include fully-compatible animations; fall back to PyCairo for custom overlays |
| Animation frame rendering speed | Medium | Pre-render animation frames in parallel with audio generation; cache rendered frames for re-use across edits; use Tier 1 (FFmpeg native) for simple overlays |
| Audio ducking timing mismatch | Low | Use same Silero VAD timestamps as the understanding pipeline; 200ms lookahead buffer prevents late ducking |
| FluidSynth SoundFont quality | Low | Ship high-quality GeneralUser_GS SoundFont; support user-imported SoundFonts for brand-specific sounds |


## 12. File Format Support


### 12.1 Input Formats

| Format | Container | Video Codec | Audio Codec | Notes |
|:---|:---|:---|:---|:---|
| MP4 | MPEG-4 Part 14 | H.264, H.265, AV1 | AAC, MP3 | Most common format |
| MOV | QuickTime | H.264, H.265, ProRes | AAC, PCM | Apple ecosystem |
| MKV | Matroska | H.264, H.265, VP9, AV1 | AAC, Opus, FLAC | Open container |
| WebM | WebM | VP8, VP9, AV1 | Vorbis, Opus | Web-optimized |
| AVI | AVI | Various | Various | Legacy support |
| TS/MTS | MPEG-TS | H.264, H.265 | AAC, AC3 | Broadcast/camera |

All formats supported by FFmpeg 7.x are accepted. Hardware-accelerated decode via NVDEC for H.264, H.265, VP9, and AV1.


## 13. Security & Privacy


### 13.1 Data Handling

All processing is local. No video data, transcripts, or embeddings leave the machine
Source video files are never modified (read-only access)
Project data stored in user-controlled directory (~/.clipcannon/)
Platform API credentials stored in OS keychain (not plaintext config files)

### 13.2 API Credential Management

OAuth tokens stored in system keychain (Windows Credential Manager / libsecret)
Refresh tokens encrypted at rest
Token refresh handled automatically
Credentials never logged or exposed in MCP tool responses
Revocation supported via clipcannon_accounts_disconnect

### 13.3 Content Safety

No content moderation is applied by ClipCannon (that is the user's responsibility)
Platform-specific content policies should be reviewed before publishing
Human approval gate prevents accidental publishing of inappropriate content

## 14. Configuration


### 14.1 Default Configuration

```json
{
  "version": "1.0",
  "directories": {
    "projects": "~/.clipcannon/projects",
    "models": "~/.clipcannon/models",
    "temp": "~/.clipcannon/tmp"
  },
  "processing": {
    "frame_extraction_fps": 2,
    "whisper_model": "large-v3",
    "whisper_compute_type": "int8",
    "batch_size_visual": 64,
    "scene_change_threshold": 0.75,
    "highlight_count_default": 10,
    "min_clip_duration_ms": 5000,
    "max_clip_duration_ms": 600000
  },
  "rendering": {
    "default_profile": "youtube_standard",
    "use_nvenc": true,
    "nvenc_preset": "p4",
    "caption_default_style": "bold_centered",
    "thumbnail_format": "jpg",
    "thumbnail_quality": 95
  },
  "audio": {
    "music_model": "ace-step-v15-turbo-rl",
    "music_lora": "Text2Samples",
    "music_guidance_scale": 7.5,
    "music_default_volume_db": -18,
    "duck_under_speech": true,
    "duck_level_db": -6,
    "sfx_on_transitions": true,
    "sfx_default_type": "whoosh",
    "midi_soundfont": "GeneralUser_GS.sf2",
    "normalize_output": true,
    "sample_rate": 44100
  },
  "animation": {
    "lower_third_template": "modern_bar",
    "lower_third_duration_ms": 6000,
    "title_card_animation": "fade_scale",
    "default_transition": "fade",
    "default_transition_duration_ms": 500,
    "fetch_remote_lottie": false,
    "default_font": "Montserrat",
    "default_primary_color": "#2563EB",
    "default_text_color": "#FFFFFF"
  },
  "publishing": {
    "require_approval": true,
    "max_daily_posts_per_platform": 5
  },
  "gpu": {
    "device": "cuda:0",
    "max_vram_usage_gb": 24,
    "concurrent_models": true,
    "ace_step_cpu_offload": false
  }
}
```

## 15. Success Metrics

| Metric | Target | Measurement |
|:---|:---|:---|
| Ingestion speed | < 5 min for 1hr 1080p video | Wall clock time |
| Render speed | < 30s per clip (including audio + animations) | Wall clock time |
| Transcript accuracy | WER < 5% (English) | Word Error Rate |
| Scene detection recall | > 90% | Manual validation |
| Caption sync accuracy | < 100ms drift | Manual validation |
| Platform compliance | 100% pass rate | FFprobe validation |
| Clips per source video | 10-30 (configurable) | Count of unique outputs |
| VRAM usage peak | < 16GB during normal operation | nvidia-smi monitoring |
| Human approval time | < 2 min per clip batch | User testing |
| Music generation speed | < 5s per minute of audio (RTX 5090) | Wall clock time |
| Music coherence | No abrupt cuts, consistent rhythm | Manual listening |
| SFX generation speed | < 100ms per effect | Wall clock time |
| Audio ducking accuracy | Music reduces within 200ms of speech onset | Waveform analysis |
| Lower third render quality | Smooth animation, no aliasing at 1080p | Visual inspection |
| Lottie render fidelity | Alpha channel clean, no fringing | Visual inspection |
| Animation overlay speed | < 5s additional render time per animation layer | Wall clock time |
| Transition smoothness | No frame drops or artifacts at transition points | Frame-by-frame inspection |


## 16. Glossary

| Term | Definition |
|:---|:---|
| EDL | Edit Decision List. Structured description of all edits to apply to source video. |
| VUD | Video Understanding Document. Complete multimodal analysis of a source video. |
| MCP | Model Context Protocol. Standard for connecting AI models to external tools. |
| NVENC | NVIDIA Video Encoder. Hardware-accelerated video encoding on NVIDIA GPUs. |
| NVDEC | NVIDIA Video Decoder. Hardware-accelerated video decoding on NVIDIA GPUs. |
| SigLIP | Sigmoid Loss for Language-Image Pre-Training. Vision encoder for image understanding. |
| X-vector | Speaker embedding vector used for speaker identification/verification. |
| VAD | Voice Activity Detection. Identifies speech vs. non-speech in audio. |
| Chronemic | Relating to temporal patterns in communication (pacing, pauses, rhythm). |
| Hexa-Modal | Six-stream parallel embedding architecture for multimodal understanding. |
| ASS | Advanced SubStation Alpha. Subtitle format supporting styled/animated text. |
| ACE-Step | AI music generation model (MIT license). Hybrid LM + Diffusion Transformer architecture. |
| Lottie | Lightweight, vector-based animation format (JSON). Originally exported from After Effects. |
| rlottie | Samsung's C library for rendering Lottie animations. Used via rlottie-python bindings. |
| PyCairo | Python bindings for the Cairo 2D vector graphics library. Used for rendering lower thirds and title cards. |
| FluidSynth | Software synthesizer that renders MIDI files to audio using SoundFont instrument banks. |
| SoundFont | .sf2 file containing sampled instrument sounds for MIDI rendering. |
| DSP | Digital Signal Processing. Mathematical manipulation of audio signals (filters, synthesis, effects). |
| Ducking | Automatically reducing background music volume when speech is detected. |
| Lower Third | On-screen text overlay in the bottom portion of the frame showing a person's name and title. |
| Stinger | Short, impactful audio cue used at transitions or to punctuate a moment. |
| Riser | Ascending sound effect that builds tension, typically used before a reveal or transition. |
| xfade | FFmpeg filter for creating transitions between two video segments. Supports 44+ built-in types. |
| GL Transitions | Open-source collection of GLSL shader-based video transitions (MIT license). |
| WebM Alpha | WebM video format (VP9 codec) with alpha transparency channel for overlay compositing. |
| Provenance | Complete record of data lineage: what input was transformed, by what operation, with what parameters, producing what output, verified by SHA-256 hash. |
| Chain Hash | SHA-256 hash incorporating the parent record's hash + current input/output hashes + operation details. Creates an immutable linked chain. Tampering with any record invalidates all downstream chain hashes. |
| Provenance Record | Single entry in the provenance database documenting one data transformation. Contains input hash, output hash, model info, parameters, timing, and chain hash. |
| Provenance DAG | Directed Acyclic Graph of all provenance records for a project. Root = source video. Leaves = published outputs. Every path is hash-verified. |
| AI-Readable | Data formatted for LLM comprehension: text labels, scalar scores, timestamps, and natural language explanations. Contrasted with machine-readable (raw embeddings, numpy arrays). |
| Translation Layer | The software component that converts raw model outputs (embedding vectors, feature arrays) into AI-readable analytics (scene descriptions, topic labels, energy scores) for the VUD. |


## Appendix A: FFmpeg Command Examples

Extract Audio for Transcription
```bash
ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output_16k.wav
Extract Frames at 2fps with NVDEC
ffmpeg -hwaccel cuda -hwaccel_output_format cuda -i input.mp4 \
  -vf "fps=2,hwdownload,format=nv12" \
  -q:v 2 frames/frame_%06d.jpg
Render Vertical Clip with Captions (NVENC)
ffmpeg -hwaccel cuda -i input.mp4 \
  -ss 00:14:00 -to 00:15:00 \
  -vf "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920,subtitles=captions.ass" \
  -c:v h264_nvenc -preset p4 -b:v 8M -maxrate 10M -bufsize 20M \
  -c:a aac -b:a 192k -ar 44100 \
  -movflags +faststart \
  output_tiktok.mp4
Batch Concatenate Segments
# segments.txt:
# file 'segment_001.mp4'
# file 'segment_002.mp4'
# file 'segment_003.mp4'
ffmpeg -f concat -safe 0 -i segments.txt \
  -c:v h264_nvenc -preset p4 -b:v 8M \
  -c:a aac -b:a 192k \
  output_combined.mp4
Crossfade Between Two Segments
ffmpeg -i segment1.mp4 -i segment2.mp4 \
  -filter_complex "[0:v][1:v]xfade=transition=fade:duration=0.5:offset=14.5[v]; \
                    [0:a][1:a]acrossfade=d=0.5[a]" \
  -map "[v]" -map "[a]" \
  -c:v h264_nvenc -preset p4 -b:v 8M \
  output_crossfade.mp4
```

## Appendix B: Existing MCP Video Ecosystem

ClipCannon builds on but goes far beyond existing MCP video servers. For reference:

| Server | Capabilities | Gap ClipCannon Fills |
|:---|:---|:---|
| video-audio-mcp | FFmpeg wrapper: convert, trim, overlay | No AI understanding, no multi-stream analysis |
| ffmpeg-mcp (multiple) | Basic FFmpeg commands via MCP | No content awareness, no platform optimization |
| VibeStudio | Media info, conversion, trimming, subtitles | No embedding pipeline, no highlight detection |
| VideoDB Director | Semantic search, VLM descriptions, generative media | Cloud-based, not local; no editing pipeline |
| video-edit-mcp | MoviePy-based editing | No GPU acceleration, no multimodal understanding |

ClipCannon is the first MCP server that delivers actual video frames + 12-stream embedder analytics to a multimodal AI, enabling the AI to see, hear (via analytics), and edit video autonomously with hardware-accelerated rendering in a fully local, GPU-optimized pipeline.


## Appendix C: AI Audio Generation Model Comparison

Models evaluated for the audio generation engine. ACE-Step v1.5 was selected as the primary model based on license, VRAM, quality, and speed.

| Model | Params | License | Commercial Use | VRAM | Sample Rate | Max Duration | Speed (1 min audio) |
|:---|:---|:---|:---|:---|:---|:---|:---|
| ACE-Step v1.5 turbo-rl | 0.6B-4B LM + 3.5B DiT | MIT | Yes | <4GB (offload) | 44.1kHz stereo | 4+ min | ~1.7s (RTX 4090) |
| MusicGen Medium | 1.5B | CC-BY-NC 4.0 | No | ~6GB | 32kHz | 30s | ~30s |
| MusicGen Large | 3.3B | CC-BY-NC 4.0 | No | ~13GB | 32kHz | 30s | ~60s |
| Stable Audio Open 1.0 | ~1B | Community (non-commercial) | No | ~8-10GB | 44.1kHz stereo | 47s | Variable (8-200 steps) |
| AudioGen Medium | 1.5B | CC-BY-NC 4.0 | No | ~6GB | 16kHz | 10s | ~10s |
| JASCO 1B | 1B | CC-BY-NC 4.0 | No | ~8GB | 16kHz | 10s | ~5s |
| MAGNeT Medium | 1.5B | CC-BY-NC 4.0 | No | ~6GB | 32kHz | 30s | Faster than MusicGen |
| TangoFlux | Unknown | Non-commercial | No | ~8GB | 44.1kHz | 30s | 25-50 steps |
| AudioLDM2-Music | 1.1B | CC-BY-NC-SA 4.0 | No | ~4-6GB | 16kHz | 10s | Variable |
| Riffusion | - | MIT | Yes | ~4GB | - | Short | - |

Why ACE-Step won: It is the only model that simultaneously satisfies all four requirements: (1) MIT license permitting commercial use of generated audio, (2) runs on consumer GPUs with as little as 4GB VRAM, (3) generates minutes of audio in seconds, and (4) outputs at 44.1kHz stereo -- broadcast quality. All Meta AudioCraft models (MusicGen, AudioGen, JASCO, MAGNeT) use CC-BY-NC-4.0 which prohibits commercial use of generated content.


## Appendix D: Animation Asset Sources

Sources evaluated for the motion graphics and animation library. A multi-tier approach was selected combining open formats (Lottie, WebM) with programmatic generation (PyCairo, FFmpeg).

Free Sources (Commercial Use Allowed)
| Source | Asset Type | Count | License | API | Format |
|:---|:---|:---|:---|:---|:---|
| LottieFiles.com | Animated icons, CTAs, reactions | 100,000+ free | Lottie Simple License (commercial OK, no attribution) | Yes (developer portal) | Lottie JSON |
| Mixkit.co (Envato) | Video overlays, stock footage, motion templates | Thousands | Mixkit Free License (commercial OK, no attribution) | No | MP4, MOGRT (needs Premiere) |
| Pixabay.com | Motion graphics clips, overlays | 9,500+ | Free commercial use, no attribution | Limited API | MP4 |
| GL Transitions | GLSL video transitions | 60+ | MIT | GitHub | GLSL (ported to FFmpeg expressions) |
| xfade-easing | FFmpeg transition expressions with easing | 60+ ported + 10 easings | MIT | GitHub | FFmpeg expressions |
| Motion Canvas | Code-first animation framework | Framework | MIT | GitHub | TypeScript → video |
| pycairo-animations | PyCairo animation framework | Framework | MIT | GitHub | Python → video |

Commercial Sources (API Access Available)
| Source | Asset Type | API | Pricing | Notes |
|:---|:---|:---|:---|:---|
| Storyblocks | Stock footage, templates, motion graphics | REST API v2.0 | Subscription ($252-360/yr) + API pricing (flat fee by MAU) | Best API for programmatic access |
| Shutterstock | Stock footage, images | REST API + OAuth | Free tier (500 watermarked/month); Enterprise $40K+/yr | Stock footage only, no templates via API |
| Shotstack | JSON-to-video rendering | REST API + Python SDK | $49-309/month | Cloud-only rendering, not local |
| Creatomate | Template-to-video rendering | REST API | $41-249/month | Cloud-only rendering, not local |

Rendering Engines Evaluated
| Engine | Approach | Local? | License | Language | Best For |
|:---|:---|:---|:---|:---|:---|
| rlottie-python | Lottie JSON → PNG frames | Yes | MIT | Python | Rendering Lottie animations (selected) |
| PyCairo | Vector graphics → PNG frames | Yes | LGPL | Python | Lower thirds, titles, callouts (selected) |
| Pillow/PIL | Raster graphics → PNG frames | Yes | HPND | Python | Simple text overlays |
| Remotion | React → headless Chrome → video | Yes (Node.js) | BSL (paid for >3 people) | TypeScript | Complex web-style animations |
| Manim | Python → Cairo → video | Yes | MIT | Python | Mathematical/educational animations |
| puppeteer-lottie | Lottie → headless Chrome → video | Yes (Node.js) | MIT | Node.js | Highest fidelity Lottie rendering |
| Blender VSE | Python scripted → Blender render | Yes | GPL | Python | 3D compositing (overkill for our needs) |

File Formats for Transparent Overlay
| Format | Codec | Alpha Support | FFmpeg Support | Size | Quality |
|:---|:---|:---|:---|:---|:---|
| WebM VP9 | libvpx-vp9 | yuva420p | Native overlay filter | Small | Good (selected for shipped assets) |
| PNG Sequence | N/A | Full RGBA | Native overlay filter | Large (many files) | Perfect |
| ProRes 4444 | prores_ks -profile:v 4 | yuva444p10le | Native | Very large | Best quality |
| MOV Animation | qtrle | Full RGBA | Native | Enormous | Lossless |


## Appendix E: Audio Generation FFmpeg Integration Examples

Mix AI-Generated Music with Source Audio (Ducked)
```bash
# Step 1: Generate music via ACE-Step (Python, outputs background_music.wav)
# Step 2: Generate SFX via DSP (Python, outputs whoosh.wav, impact.wav)
# Step 3: Mix all audio tracks with pydub (Python, outputs final_mix.wav)
# Step 4: Mux with video via FFmpeg:
ffmpeg -i rendered_video_no_audio.mp4 -i final_mix.wav \
  -c:v copy -c:a aac -b:a 192k -ar 44100 \
  -map 0:v:0 -map 1:a:0 \
  -movflags +faststart \
  output_with_audio.mp4
Overlay Lottie Animation + Lower Third + WebM Effect
# Inputs: main video, rendered lottie frames, pycairo lower third frames, webm effect
ffmpeg -i main.mp4 \
  -framerate 30 -i /tmp/lottie_subscribe/frame_%04d.png \
  -framerate 30 -i /tmp/lower_third_001/frame_%04d.png \
  -c:v libvpx-vp9 -i light_leak_warm_01.webm \
  -filter_complex "\
    [0][1]overlay=x=W-w-120:y=H-w-200:enable='between(t,55,59)'[v1];\
    [v1][2]overlay=x=40:y=H-140:enable='between(t,2,8)'[v2];\
    [v2][3]overlay=x=0:y=0:enable='between(t,0,3)'[vout]" \
  -map "[vout]" -map 0:a \
  -c:v h264_nvenc -preset p4 -b:v 8M \
  -c:a aac -b:a 192k \
  output_with_overlays.mp4
Apply GL Transition Between Two Clips
# Using xfade-easing ported expression (no custom FFmpeg build needed)
ffmpeg -i clip1.mp4 -i clip2.mp4 \
  -filter_complex "\
    [0:v][1:v]xfade=transition=custom:\
    expr='if(gte(P,0.5),B,A)':\
    duration=1:offset=4[v];\
    [0:a][1:a]acrossfade=d=1[a]" \
  -map "[v]" -map "[a]" \
  -c:v h264_nvenc -preset p4 -b:v 8M \
  output_with_transition.mp4
(For actual GL transition expressions, load from ~/.clipcannon/transitions/{name}.expr)
```


---

*End of PRD*
