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


