# Project Phoenix — GPU-Native Avatar Engine

## Implementation Plan

**Version**: 1.0
**Date**: 2026-04-04
**Target Hardware**: NVIDIA RTX 5090 32GB (Blackwell GB202, CUDA 13.2, 21,760 CUDA cores, 680 5th-gen Tensor Cores, 1,792 GB/s bandwidth)

---

## 1. Problem Statement

Every tool in the current avatar pipeline was designed before the hardware and AI capabilities we have today. FFmpeg (2000), OpenCV (1999), and even modern diffusion-based lip-sync models (2024) all assume CPU-centric architectures with GPU as an accelerator — not as the primary compute surface.

Current pipeline for a single avatar response:

```
Audio → CPU → GPU (Whisper) → CPU → GPU (Ollama) → CPU → GPU (TTS) → CPU
→ GPU (MuseTalk) → CPU → OpenCV compositing (CPU!) → NVENC (GPU) → CPU → output
= 7 GPU↔CPU roundtrips per frame, ~2-5 second response latency
```

Phoenix pipeline:

```
Audio → GPU memory → all processing on GPU → NVENC encode (async hardware)
= 0 GPU↔CPU copies in render path, ~15ms per frame = 66 FPS, ~500ms response
```

---

## 2. The Embedding Advantage

ClipCannon has 9 embedding systems that convert every aspect of human communication into mathematical vectors. This is the foundation that makes Phoenix possible — not just rendering faces, but rendering *intelligent, emotionally aware, contextually appropriate* behavior.

### 2.1 Embedding Inventory

| # | Embedder | Model | Dimensions | Captures |
|---|----------|-------|-----------|----------|
| 1 | **Visual** | SigLIP (google/siglip-so400m-patch14-384) | 1152 | Scene composition, visual content, frame similarity |
| 2 | **Semantic** | Nomic Embed v1.5 (nomic-ai/nomic-embed-text-v1.5) | 768 | Text meaning, topical content, sentiment |
| 3 | **Emotion** | Wav2Vec2 (facebook/wav2vec2-large-960h) | 1024 | Energy (RMS), arousal (variance), valence (mean) |
| 4 | **Speaker** | WavLM (microsoft/wavlm-base-plus-sv) | 512 | Speaker identity, voice characteristics |
| 5 | **Voice Profile** | ECAPA-TDNN (Qwen3-TTS integrated) | 2048 | Speaker fingerprint for voice cloning verification |
| 6 | **Prosody** | pyworld + numpy (CPU) | 12 features | F0 contour, energy, speaking rate, pitch variation, expressiveness |
| 7 | **OCR Provenance** | Configurable (384-1024) | Variable | Document content, meeting history, semantic search |
| 8 | **Memory** | RuFlo V3 HNSW | Variable | Hierarchical knowledge, patterns, causal graphs |
| 9 | **Sentence** | sentence-transformers | 384 | Wake word matching, command detection, intent |

**Total dimensionality**: 6,908+ features capturing visual, auditory, linguistic, emotional, prosodic, and identity information.

### 2.2 What Embeddings Enable for Avatar Rendering

When you have everything converted to numbers, you can compute things that were previously impossible:

#### Cross-Modal Emotion Fusion
```
Emotion embedding (1024-dim) → arousal, valence, energy scalars
  + Prosody features → F0 contour, speaking rate, emphasis
  + Semantic embedding (768-dim) → topic sentiment
  = FULL emotional state vector
```
A sentence like "great job" with low energy + falling F0 = sarcasm.
Same words with high energy + rising F0 = genuine praise.
The avatar responds differently to each. No existing system does this.

#### Speaker-Aware Gaze and Attention
```
Speaker embedding (512-dim) → identify WHO is speaking
  + Emotion embedding → HOW they're feeling
  + Semantic embedding → WHAT they're discussing
  = Avatar knows who to look at, when to nod, when to react
```

#### Prosody-Matched Voice Synthesis
```
Room prosody profile = mean(all speakers' F0, energy, rate)
  → TTS reference clip selected to MATCH room energy
  → Avatar never sounds out-of-place
```
If everyone is excited, the avatar speaks excitedly. If it's a somber discussion, the avatar's tone matches. This is unconscious human behavior that no meeting bot does today.

#### Predictive Behavior from Embedding Trajectories
```
emotion_curve[t-5..t] → energy trend (rising? falling? stable?)
  + semantic_trajectory → topic shift detection
  + prosody_trajectory → turn-taking prediction
  = Avatar can anticipate when it will be asked to speak
    and pre-render response animations before the question ends
```

#### Gesture Selection from Semantic Space
```
Semantic embedding of response text → nearest gesture cluster:
  "I'm not sure" → shrug gesture + slight head tilt
  "Absolutely" → firm nod + forward lean
  "Let me explain" → hand raise + deliberate pace
  "That's funny" → smile + slight head back
```
Pre-computed gesture library indexed by semantic embedding. Retrieval is a single vector search — sub-millisecond.

#### Memory-Enhanced Personality
```
RuFlo Memory (HNSW) stores:
  - Each participant's communication style (embedding centroid)
  - Topics that generated high engagement (emotion peaks)
  - The avatar's own successful responses (reward signal)
  → Avatar develops a persistent personality over time
```

---

## 3. Architecture

### 3.1 System Layers

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 5: OUTPUT                                                 │
│   NVENC H.264/HEVC → WebRTC/v4l2/Named Pipe                   │
│   [Async hardware encoder, 0 CUDA cores used]                  │
├─────────────────────────────────────────────────────────────────┤
│ Layer 4: COMPOSITOR (CUDA Tile / CuPy kernels)                 │
│   Face + Body + Background + Overlays → Final frame            │
│   Alpha blend, color match, lighting correction                │
│   [~1ms per frame, custom GPU kernel]                          │
├─────────────────────────────────────────────────────────────────┤
│ Layer 3: RENDERER (3D Gaussian Splatting)                      │
│   Deformed face mesh → Photorealistic 2D pixels                │
│   FlashAvatar (speed) or GaussianAvatars (quality)             │
│   [~3-5ms per frame, 100-400 FPS capable]                      │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2: DEFORMER (FLAME mesh + expression params)             │
│   Expression params → Morph Gaussian point cloud               │
│   Body motion → Upper body skeleton pose                       │
│   [<1ms per frame, matrix multiply on Tensor Cores]            │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: EXPRESSION ENGINE (Embedding-Driven)                  │
│   Audio embeddings → 53 FLAME blendshapes + jaw + gaze + blink │
│   Emotion fusion → Reactive expressions (mirror room emotion)  │
│   Semantic analysis → Gesture selection from library           │
│   Prosody matching → TTS style adaptation                      │
│   [~5-8ms per frame, small transformer on Tensor Cores]        │
├─────────────────────────────────────────────────────────────────┤
│ Layer 0: FACE CAPTURE (One-time, offline)                      │
│   Reference photos/video → 3D Gaussian Splat model             │
│   + FLAME mesh fit + Texture atlas + Expression calibration    │
│   [5-30 minutes per identity]                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow (Zero-Copy GPU Pipeline)

```
                    ┌──────────────────────────────────────────┐
                    │           GPU MEMORY (32GB VRAM)          │
                    │                                          │
  Audio In ──┬───→ │ Whisper ASR ─→ text tensor               │
  (CUDA buf) │     │                    │                      │
             │     │ Wav2Vec2 ──→ emotion_embedding (1024)     │
             │     │ WavLM ─────→ speaker_embedding (512)      │
             │     │ Mel Spec ──→ audio_features               │
             │     │                    │                      │
             │     │ ┌──────────────────┴───────────────┐      │
             │     │ │     EXPRESSION ENGINE             │      │
             │     │ │                                   │      │
             │     │ │ audio_features ──→ Audio2Exp net  │      │
             │     │ │ emotion_emb ────→ Emotion mirror  │      │
             │     │ │ speaker_emb ────→ Gaze target     │      │
             │     │ │ semantic_emb ───→ Gesture select  │      │
             │     │ │ prosody_feat ───→ TTS style       │      │
             │     │ │                                   │      │
             │     │ │ Output: 53 blendshapes + jaw +    │      │
             │     │ │         gaze + blink + gesture_id │      │
             │     │ └──────────────────┬───────────────┘      │
             │     │                    │                      │
             │     │ FLAME Deformer ────→ deformed_gaussians   │
             │     │ Body Motion ───────→ body_pose            │
             │     │                    │                      │
             │     │ Gaussian Splat ────→ face_pixels (1080p)  │
             │     │ Compositor ────────→ final_frame          │
             │     │                    │                      │
             │     │ NVENC ─────────────→ H.264 bitstream ──→ Output
             │     │  (async HW)                               │
             │     └──────────────────────────────────────────┘
```

### 3.3 Green Context Partitioning (RTX 5090, 170 SMs)

```
┌─────────────────────────────────────────────────────┐
│ Green Context A: REAL-TIME RENDER (34 SMs, 20%)     │
│   Guaranteed <16ms frame budget                     │
│   Expression engine + FLAME deform + Gaussian       │
│   render + compositor                               │
│   Always running at 30-60 FPS                       │
├─────────────────────────────────────────────────────┤
│ Green Context B: AI PIPELINE (136 SMs, 80%)         │
│   Whisper ASR (burst, 200ms per utterance)          │
│   Ollama LLM (burst, 1-3s per response)             │
│   TTS synthesis (burst, 500ms per response)         │
│   Embedding computation (burst, 5-10ms each)        │
│   Not latency-critical — can queue                  │
└─────────────────────────────────────────────────────┘
│ NVENC: Dedicated hardware, independent of both      │
└─────────────────────────────────────────────────────┘
```

---

## 4. VRAM Budget

| Component | VRAM | Location |
|-----------|------|----------|
| 3D Gaussian face model (per identity) | 200-500 MB | Green Context A |
| Audio2Expression transformer (FP4) | 5-10 MB | Green Context A |
| Body motion MLP (FP4) | 2-5 MB | Green Context A |
| Gaussian rasterizer workspace | 100-200 MB | Green Context A |
| Compositor framebuffer (1080p, triple) | 24 MB | Green Context A |
| Gesture library embeddings | 50 MB | Green Context A |
| **Subtotal Render** | **~0.5-1 GB** | |
| | | |
| Whisper Large v3 Turbo (float16) | 3-4 GB | Green Context B |
| Ollama Qwen3-14B (Q4/FP8) | 8-12 GB | Green Context B |
| TTS 0.6B (bfloat16) | 2 GB | Green Context B |
| Wav2Vec2 emotion (burst load) | 1.5 GB | Green Context B |
| WavLM speaker (burst load) | 0.5 GB | Green Context B |
| Nomic Embed semantic (burst load) | 0.5 GB | Green Context B |
| ECAPA-TDNN voice verify (burst load) | 0.5 GB | Green Context B |
| **Subtotal AI** | **~16-21 GB** | |
| | | |
| **Total** | **~17-22 GB** | |
| **Free** | **10-15 GB** | Headroom for peaks |

---

## 5. Embedding-Driven Behavior System

This is the core innovation. Every human behavior the avatar exhibits is driven by mathematical operations on embedding vectors — not hardcoded rules.

### 5.1 Emotion Mirror System

```python
# Pseudocode — runs every frame on GPU

def compute_avatar_emotion(room_state):
    # Fuse all available signals into a single emotion vector
    emotion_vec = room_state.wav2vec2_embedding[-1]  # 1024-dim
    arousal = torch.var(emotion_vec)                   # How activated
    valence = torch.mean(emotion_vec)                  # How positive
    energy = torch.norm(emotion_vec)                   # How intense

    # Prosody reinforcement
    f0_trend = room_state.f0_contour[-10:]  # Last 10 frames
    energy_trend = room_state.energy_curve[-10:]

    # Cross-modal sarcasm detection
    semantic_sentiment = room_state.semantic_embedding  # 768-dim
    text_positive = classifier(semantic_sentiment)  # 0-1
    voice_positive = valence > 0.5 and energy > 0.3

    if text_positive > 0.7 and not voice_positive:
        # Words say positive but voice says negative = sarcasm
        avatar_reaction = "knowing_smile"
    elif arousal > 0.7 and energy > 0.6:
        avatar_reaction = "engaged_excited"
    elif arousal < 0.3:
        avatar_reaction = "calm_attentive"

    return blend_expressions(avatar_reaction, intensity=energy)
```

### 5.2 Speaker Attention System

```python
def compute_gaze_target(room_state):
    current_speaker = room_state.speaker_embedding  # 512-dim
    all_speakers = room_state.speaker_history        # List of 512-dim

    # Identify who is speaking by nearest embedding
    speaker_id = cosine_nearest(current_speaker, all_speakers)

    # Gaze intensity based on address detection
    if room_state.addressed_to_avatar:
        gaze = direct_eye_contact(speaker_id)
        head_tilt = attentive_lean(intensity=0.8)
    else:
        gaze = relaxed_look_toward(speaker_id)
        head_tilt = neutral

    # Micro-movements: slight head tracking of active speaker
    gaze_smoothed = exponential_moving_average(gaze, alpha=0.15)
    return gaze_smoothed, head_tilt
```

### 5.3 Gesture Selection via Semantic Search

```python
# Pre-indexed gesture library (built offline)
gesture_library = {
    "nod_agreement": embed("I agree, that makes sense"),      # 768-dim
    "shrug_uncertain": embed("I'm not sure about that"),       # 768-dim
    "hand_explain": embed("Let me walk you through this"),     # 768-dim
    "lean_forward": embed("This is really important"),         # 768-dim
    "head_tilt_curious": embed("That's an interesting point"), # 768-dim
    "hands_open": embed("I'm open to suggestions"),            # 768-dim
    "point_reference": embed("As I mentioned earlier"),        # 768-dim
    "laugh_genuine": embed("That's really funny"),             # 768-dim
    "think_pause": embed("Give me a moment to consider"),      # 768-dim
    "wave_greeting": embed("Hello everyone, good to see you"), # 768-dim
    # ... 50-100 gesture clips
}

def select_gesture(response_text):
    response_embedding = nomic_embed(response_text)  # 768-dim
    gesture_id = cosine_nearest(response_embedding, gesture_library)
    return gesture_id  # Sub-millisecond via sqlite-vec or FAISS
```

### 5.4 Prosody-Matched TTS

```python
def select_tts_style(room_state, response_text):
    # Analyze room's speaking energy
    room_f0_mean = mean(s.f0_mean for s in room_state.recent_prosody)
    room_energy = mean(s.energy_mean for s in room_state.recent_prosody)
    room_rate = mean(s.speaking_rate_wpm for s in room_state.recent_prosody)

    # Analyze response intent
    response_embedding = nomic_embed(response_text)  # 768-dim
    emotion = classify_emotion(response_embedding)

    # Select prosody reference clip that matches both room energy
    # and response intent (uses prosody_segments table)
    style = "energetic" if room_energy > 0.6 else "calm"
    if "?" in response_text:
        style = "question"
    elif emotion == "emphatic":
        style = "emphatic"

    ref_clip = select_prosody_reference(voice_name, style)
    return ref_clip, style
```

### 5.5 Predictive Pre-Rendering

```python
def predictive_pipeline(room_state):
    # Track emotion trajectory
    emotion_trajectory = room_state.emotion_embeddings[-20:]  # Last 20 frames
    energy_slope = linear_regression_slope(
        [torch.norm(e) for e in emotion_trajectory]
    )

    # Track semantic trajectory
    recent_topics = room_state.semantic_embeddings[-5:]
    topic_drift = 1.0 - cosine_similarity(recent_topics[0], recent_topics[-1])

    # Predict: is a question coming?
    if energy_slope > 0.1 and topic_drift > 0.3:
        # Energy rising + topic shifting = someone is building to a question
        # Pre-warm: start computing relevant context from OCR Provenance
        asyncio.create_task(
            preload_context(room_state.current_topic_embedding)
        )
        # Pre-render: shift avatar to "attentive listening" pose
        avatar.set_anticipation_mode(True)
```

### 5.6 Continuous Identity Verification

```python
def verify_avatar_voice_quality(tts_output, identity_embedding):
    """
    Uses the 2048-dim ECAPA-TDNN voice profile embedding to verify
    that every utterance sounds like the cloned identity.
    SECS > 0.95 hard gate — silence is better than wrong voice.
    """
    output_embedding = ecapa_tdnn.embed(tts_output)   # 2048-dim
    secs_score = cosine_similarity(output_embedding, identity_embedding)
    if secs_score < 0.95:
        # Re-synthesize with different prosody reference
        return None, secs_score
    return tts_output, secs_score
```

---

## 6. Implementation Phases

### Phase 0: Foundation (Days 1-3)

**Goal**: Replace CPU bottlenecks with GPU equivalents. No new models.

| Task | Description | Effort |
|------|-------------|--------|
| 0.1 | Install PyNvVideoCodec or VPF for direct GPU encode/decode | 2h |
| 0.2 | Write CuPy compositor kernel (alpha blend, color convert, resize) | 4h |
| 0.3 | Replace numpy/OpenCV compositing in `idle_renderer.py` with CuPy | 3h |
| 0.4 | Replace numpy/OpenCV compositing in `avatar_rt.py` with CuPy | 3h |
| 0.5 | Replace FFmpeg subprocess in `lip_sync.py` with PyNvVideoCodec | 4h |
| 0.6 | Benchmark: measure GPU↔CPU copies eliminated, latency reduction | 2h |
| 0.7 | Tests for all CuPy kernels | 3h |

**Expected result**: 15-30% latency reduction on existing pipeline. All compositing stays on GPU.

### Phase 1: LivePortrait Integration (Days 4-8)

**Goal**: Replace MuseTalk with LivePortrait for real-time avatar rendering. 50+ FPS.

| Task | Description | Effort |
|------|-------------|--------|
| 1.1 | Clone LivePortrait repo, install dependencies | 2h |
| 1.2 | Export LivePortrait to TensorRT for RTX 5090 optimization | 4h |
| 1.3 | Write `avatar_liveportrait.py` adapter matching `RealtimeLipSync` interface | 6h |
| 1.4 | Build audio-to-keypoint driver (mel spectrogram → LivePortrait keypoints) | 8h |
| 1.5 | Integrate with meeting pipeline (replace MuseTalk in `avatar_rt.py`) | 4h |
| 1.6 | Benchmark FPS, quality, VRAM usage | 2h |
| 1.7 | Tests | 4h |

**Expected result**: 50-60 FPS avatar rendering, better expression fidelity, ~2GB VRAM.

### Phase 2: Embedding-Driven Behavior Engine (Days 9-16)

**Goal**: Wire all 9 embedding systems into the avatar's behavior. The avatar becomes emotionally intelligent.

| Task | Description | Effort |
|------|-------------|--------|
| 2.1 | Build `EmotionFusion` module: Wav2Vec2 + prosody + semantic → emotion state | 6h |
| 2.2 | Build `SpeakerTracker` module: WavLM embeddings → speaker identification + gaze | 4h |
| 2.3 | Build `GestureLibrary`: Pre-record 50+ gesture clips, index by Nomic semantic embedding | 8h |
| 2.4 | Build `GestureSelector`: Semantic search over gesture library for response text | 4h |
| 2.5 | Build `ProsodyMatcher`: Analyze room prosody → select matching TTS reference | 4h |
| 2.6 | Build `EmotionMirror`: Map room emotion to avatar facial expression parameters | 6h |
| 2.7 | Build `PredictivePreloader`: Track embedding trajectories → pre-warm context | 4h |
| 2.8 | Build `CrossModalDetector`: Sarcasm, irony, humor detection from embedding disagreement | 6h |
| 2.9 | Wire all modules into `CloneMeetingManager` event loop | 4h |
| 2.10 | Build `BehaviorConfig` with tunable weights for each embedding signal | 3h |
| 2.11 | Tests for all behavior modules | 6h |

**Expected result**: Avatar that mirrors room emotion, tracks speakers, selects contextual gestures, and adapts its voice to match the conversation energy.

### Phase 3: 3D Gaussian Avatar Engine (Days 17-30)

**Goal**: Build the full from-scratch rendering pipeline. Photorealistic, 100+ FPS.

| Task | Description | Effort |
|------|-------------|--------|
| 3.1 | Research and select between FlashAvatar (speed) and GaussianAvatars (quality) | 4h |
| 3.2 | Build `FaceCapture` module: reference video → 3D Gaussian Splat + FLAME fit | 16h |
| 3.3 | Build `Audio2Expression` transformer: mel spectrogram → 53 FLAME params | 12h |
| 3.4 | Train Audio2Expression on talking head dataset (HDTF, MEAD, VoxCeleb2) | 8h |
| 3.5 | Fine-tune Audio2Expression on target identity's voice data (Santa, Boris) | 4h |
| 3.6 | Fork and optimize gsplat rasterizer for Blackwell (CUDA Tile TMA ops) | 12h |
| 3.7 | Build `GaussianDeformer`: FLAME params → deform Gaussian point cloud | 8h |
| 3.8 | Build `BodyMotion` MLP: expression params → upper body pose | 8h |
| 3.9 | Build CUDA compositor kernel: face + body + background → final frame | 6h |
| 3.10 | Build NVENC zero-copy output: GPU framebuffer → H.264 bitstream | 6h |
| 3.11 | Green Context setup: partition RTX 5090 into render + AI contexts | 4h |
| 3.12 | CUDA Graph: chain entire render pipeline into single launch | 6h |
| 3.13 | Build `PhoenixRenderer` class matching existing interface | 4h |
| 3.14 | Integration tests: end-to-end from audio to encoded video | 8h |
| 3.15 | Quality benchmarks: compare to MuseTalk, LivePortrait, LatentSync | 4h |

**Expected result**: Photorealistic avatar at 60-100+ FPS, zero CPU copies in render path, full embedding-driven behavior.

### Phase 4: Rust Orchestrator (Days 31-40)

**Goal**: Replace Python orchestration with Rust for deterministic latency.

| Task | Description | Effort |
|------|-------------|--------|
| 4.1 | Set up Rust project with cudarc, tokio, PulseAudio bindings | 4h |
| 4.2 | Build audio capture module (PulseAudio → CUDA memory, zero copy) | 8h |
| 4.3 | Build CUDA Graph pipeline launcher (wraps Python-trained models via TensorRT) | 8h |
| 4.4 | Build NVENC output module (CUDA framebuffer → v4l2loopback or WebRTC) | 6h |
| 4.5 | Build async event loop: audio in → AI pipeline → render → encode | 6h |
| 4.6 | Benchmark: measure GIL elimination latency improvement | 2h |
| 4.7 | Integration with existing Python models via PyO3 or TensorRT C API | 8h |

**Expected result**: Sub-10ms render latency, deterministic frame delivery, no Python GIL.

### Phase 5: Advanced Embedding Applications (Days 41-50)

**Goal**: Push embedding intelligence to its limits.

| Task | Description | Effort |
|------|-------------|--------|
| 5.1 | **Style Transfer**: Capture someone's communication style as an embedding centroid, avatar can adopt it | 6h |
| 5.2 | **Rapport Building**: Track convergence of avatar + human prosody embeddings over time (vocal accommodation) | 6h |
| 5.3 | **Engagement Heatmap**: Use emotion embedding trajectories to identify which topics generate peak engagement | 4h |
| 5.4 | **Turn Prediction**: Train small classifier on embedding trajectories to predict when avatar will be addressed | 8h |
| 5.5 | **Multi-Avatar Coordination**: Multiple avatars in one meeting, coordinated via shared embedding space | 8h |
| 5.6 | **Personality Memory**: RuFlo HNSW stores long-term personality traits learned from embedding patterns | 6h |
| 5.7 | **Cultural Adaptation**: Detect communication norms from prosody/semantic patterns, adapt avatar accordingly | 8h |

---

## 7. Embedding Data Flow Matrix

Shows how each embedding feeds into each avatar behavior:

| Behavior | Visual (1152) | Semantic (768) | Emotion (1024) | Speaker (512) | Voice (2048) | Prosody (12) | OCR Prov | Memory | Sentence (384) |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Facial expression | | | **PRIMARY** | | | **SUPPORT** | | | |
| Eye gaze direction | | | | **PRIMARY** | | | | | |
| Gesture selection | | **PRIMARY** | **SUPPORT** | | | | | | |
| TTS prosody style | | | **SUPPORT** | | | **PRIMARY** | | | |
| Voice identity | | | | | **PRIMARY** | | | | |
| Response content | | **PRIMARY** | | | | | **PRIMARY** | **PRIMARY** | |
| Turn prediction | | | **PRIMARY** | **SUPPORT** | | **PRIMARY** | | | |
| Emotion mirroring | | **SUPPORT** | **PRIMARY** | | | **SUPPORT** | | | |
| Sarcasm detection | | **PRIMARY** | **PRIMARY** | | | **PRIMARY** | | | |
| Engagement tracking | | | **PRIMARY** | **SUPPORT** | | **SUPPORT** | | **STORE** | |
| Context preloading | | **PRIMARY** | | | | | **PRIMARY** | **PRIMARY** | |
| Address detection | | | | **SUPPORT** | | | | | **PRIMARY** |
| Personality adapt | | | | | | | | **PRIMARY** | |

---

## 8. Performance Targets

| Metric | Current | Phase 0 | Phase 1 | Phase 3 | Phase 4 |
|--------|---------|---------|---------|---------|---------|
| Render FPS | 30 | 35 | 50-60 | 100+ | 100+ |
| Render latency/frame | 33ms | 28ms | 18ms | 10ms | 8ms |
| GPU→CPU copies/frame | 3 | 1 | 1 | 0 | 0 |
| Response latency (e2e) | 2-5s | 1.5-4s | 1-3s | 500ms-2s | 400ms-1.5s |
| VRAM (render) | 3GB | 3GB | 2GB | 1GB | 1GB |
| VRAM (total) | 24GB | 22GB | 20GB | 18GB | 18GB |
| Expression awareness | None | None | Basic | Full 9-embedder | Full + predictive |

---

## 9. File Structure

```
src/
  phoenix/                          # New package — GPU-native avatar engine
    __init__.py
    config.py                       # PhoenixConfig (frozen dataclass)

    capture/                        # Phase 3: One-time face capture
      gaussian_trainer.py           # Reference video → 3D Gaussian Splat
      flame_fitter.py               # FLAME mesh fitting to identity
      texture_atlas.py              # Skin/eye/hair texture extraction

    expression/                     # Phase 2-3: Embedding-driven behavior
      audio2expression.py           # Mel → 53 FLAME blendshapes (transformer)
      emotion_fusion.py             # Cross-modal emotion state (Wav2Vec2 + prosody + semantic)
      emotion_mirror.py             # Room emotion → avatar expression mapping
      speaker_tracker.py            # WavLM → speaker ID → gaze target
      gesture_selector.py           # Semantic search over gesture library
      prosody_matcher.py            # Room prosody → TTS reference selection
      cross_modal_detector.py       # Sarcasm/irony from embedding disagreement
      predictive_preloader.py       # Embedding trajectory → anticipatory behavior
      turn_predictor.py             # Predict when avatar will be addressed

    render/                         # Phase 0-3: GPU rendering pipeline
      cupy_compositor.py            # CuPy/Triton kernels for alpha blend, color convert
      gaussian_renderer.py          # 3DGS rasterizer (fork of gsplat)
      flame_deformer.py             # FLAME params → Gaussian point cloud morph
      body_motion.py                # Expression → upper body pose MLP
      nvenc_encoder.py              # Zero-copy CUDA → NVENC → bitstream
      green_context.py              # SM partitioning for render vs AI
      cuda_graph_pipeline.py        # Full render chain as single CUDA Graph

    adapters/                       # Phase 1: Intermediate solutions
      liveportrait_adapter.py       # LivePortrait + TensorRT wrapper
      musetalk_adapter.py           # Current MuseTalk wrapper (kept for fallback)

    behavior/                       # Phase 5: Advanced intelligence
      style_transfer.py             # Capture + adopt communication style
      rapport_tracker.py            # Prosody convergence measurement
      engagement_heatmap.py         # Emotion trajectories per topic
      personality_memory.py         # Long-term trait storage (RuFlo HNSW)

    gesture_library/                # Pre-recorded gesture clips
      gestures.db                   # SQLite with Nomic embeddings per clip
      clips/                        # WAV + BVH/pose files per gesture

  voiceagent/meeting/               # Existing meeting modules (updated)
    avatar_rt.py                    # Updated to use Phoenix renderer
    manager.py                      # Updated with embedding-driven behavior
    responder.py                    # Already has OCR Provenance RAG
```

---

## 10. Dependencies

### New (Phase 0)
- `cupy-cuda13x` — GPU array operations, custom kernels
- `pynvvideocodec` or `nvidia-vpf` — Direct GPU encode/decode

### New (Phase 1)
- `liveportrait` — Real-time portrait animation
- `tensorrt` — Model optimization for RTX 5090

### New (Phase 3)
- `gsplat` — 3D Gaussian Splatting rasterizer
- `flame-pytorch` — FLAME parametric face model
- `pytorch3d` — 3D vision utilities
- `cuda-tile` (pip install) — CUDA Tile Python DSL

### New (Phase 4)
- Rust toolchain + `cudarc` + `tokio` + `pyo3`

### Existing (already in project)
- `faster-whisper` — ASR
- `faster-qwen3-tts` — Voice synthesis
- `torch` — PyTorch 2.x with CUDA
- `sentence-transformers` — Nomic Embed, sentence embeddings
- `sqlite-vec` — Vector search
- `httpx` — Ollama + OCR Provenance HTTP
- `playwright` — Browser automation for meeting join

---

## 11. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| GaussianAvatars training fails for bearded faces | FlashAvatar as fallback (simpler UV-space approach); LivePortrait as 2D fallback |
| Green Contexts not supported on consumer RTX 5090 | Fall back to CUDA stream priorities (high-priority render stream) |
| Audio2Expression quality insufficient | Use NVIDIA Audio2Face SDK as bridge; fine-tune on target identity data |
| NVENC zero-copy path breaks on WSL2 | Fall back to PyNvVideoCodec with single GPU→CPU copy for encode |
| Rust+CUDA interop too complex | Keep Python orchestrator, use CuPy for critical kernels instead |
| Expression prediction adds visible latency | Pre-render at 60 FPS, blend new expressions over 2-3 frames for smoothing |

---

## 12. Prosody as the Core Differentiator

Prosody is the single most important signal that separates a convincing human from an obvious AI. It is not an add-on — it is the foundation of every behavior in Phoenix.

### 12.1 What Prosody Captures (12 features per utterance)

| Feature | What It Measures | Human Perception |
|---------|-----------------|-----------------|
| **F0 mean** | Average pitch (Hz) | Gender, age, identity |
| **F0 std** | Pitch variation | Expressiveness vs monotone |
| **F0 min/max** | Pitch range | Emotional range |
| **F0 range** | Max - min | How animated the speaker is |
| **Energy mean** | Average volume | Confidence, engagement |
| **Energy peak** | Loudest moment | Emphasis, surprise |
| **Energy std** | Volume variation | Dynamic vs flat delivery |
| **Speaking rate (WPM)** | Words per minute | Urgency, thoughtfulness |
| **Pitch contour type** | flat/rising/falling/varied | Statement vs question vs excitement |
| **Has emphasis** | Stressed words detected | Key points, conviction |
| **Has breath** | Audible breaths | Natural pacing |
| **Prosody score** | Composite expressiveness | Overall human-likeness |

### 12.2 Where Prosody Is Captured

1. **Ingest pipeline** (`prosody_analysis.py`): Every sentence in every video gets F0, energy, rate analysis. Stored in `prosody_segments` table.
2. **Voice data preparation** (`data_prep.py`): Training clips tagged with prosody features for reference selection.
3. **Real-time meeting audio** (`audio_capture.py` → `transcriber.py`): Live prosody extraction from speakers.
4. **TTS output verification**: Generated speech measured against reference prosody to ensure naturalness.

### 12.3 Where Prosody MUST Be Used (Non-Negotiable)

| System | Prosody Role | Without Prosody |
|--------|-------------|----------------|
| **TTS reference selection** | Pick reference clip matching target delivery style | Monotone, robotic output |
| **Avatar facial expression** | Map F0 contour → eyebrow raise, lip tension, jaw opening | Dead face during speech |
| **Avatar head motion** | F0 peaks → head nods, F0 drops → head tilts | Bobblehead or statue |
| **Avatar breathing** | Breath markers → chest rise, slight pause | Unnatural continuous speech |
| **Gesture timing** | Energy peaks → gesture onset, rate → gesture speed | Gestures out of sync with speech |
| **Turn-taking** | F0 drop + energy drop + rate slow → end of utterance | Interrupts or awkward pauses |
| **Emotion detection** | F0 range + energy std → arousal, F0 mean shift → mood change | Misreads emotional state |
| **Room energy matching** | Room avg(F0 std, energy, rate) → avatar delivery calibration | Avatar sounds out of place |

### 12.4 Prosody Pipeline in Phoenix

```
CAPTURE (every frame):
  Raw audio → pyworld F0 extraction (2ms)
            → RMS energy computation (0.1ms)
            → Speaking rate from transcript words (0.1ms)
            → Contour classification: flat/rising/falling/varied (0.5ms)
            → Emphasis detection from F0 peaks > 1.5 std (0.1ms)
            → Breath detection from energy dips + silence (0.1ms)

USE (every avatar frame):
  Current F0 → jaw opening angle (linear map)
  Current F0 → eyebrow height (exponential map for peaks)
  F0 derivative → head pitch velocity (nod on rising F0)
  Energy → lip tension + mouth width
  Speaking rate → gesture speed multiplier
  Contour type → head motion pattern:
    flat → minimal movement
    rising → slight upward head tilt
    falling → downward nod
    varied → natural head sway

  Room prosody centroid → TTS reference selection:
    high energy room → energetic reference clip
    low energy room → calm reference clip
    fast room → faster speaking rate
    slow room → deliberate pacing

VERIFY (every TTS output):
  Output F0 contour vs reference F0 contour → correlation > 0.7
  Output energy profile vs reference energy → within 20%
  Output speaking rate vs target rate → within 15%
  If ANY check fails → re-synthesize with adjusted parameters
  SECS > 0.95 ALWAYS (identity gate, non-negotiable)
```

### 12.5 Prosody-Driven Expression Mapping

```python
# Direct numerical mapping from prosody → FLAME blendshapes
def prosody_to_expression(prosody):
    expressions = {}

    # Jaw: opens proportional to F0 and energy
    expressions["jaw_open"] = clamp(prosody.energy_mean * 0.6 + prosody.f0_norm * 0.3, 0, 1)

    # Eyebrows: rise on F0 peaks, furrow on emphasis
    f0_surprise = max(0, (prosody.f0_current - prosody.f0_mean) / prosody.f0_std)
    expressions["brow_raise"] = clamp(f0_surprise * 0.5, 0, 1)
    expressions["brow_furrow"] = 0.3 if prosody.has_emphasis else 0.0

    # Mouth width: wider at higher energy (smiling while speaking)
    expressions["mouth_stretch"] = clamp(prosody.energy_mean * 0.4, 0, 0.5)

    # Head nod: triggered by F0 falling contour (statement emphasis)
    if prosody.pitch_contour_type == "falling" and prosody.energy_peak > 0.5:
        expressions["head_nod_intensity"] = 0.6

    # Head tilt: rising contour = question = slight tilt
    if prosody.pitch_contour_type == "rising":
        expressions["head_tilt"] = 0.3

    # Breathing: insert chest rise at breath markers
    if prosody.has_breath:
        expressions["chest_rise"] = 0.2

    return expressions
```

---

## 13. Competitive Benchmarks (Ground Truth)

These are published benchmarks from competing systems. Phoenix MUST meet or exceed every one to be considered viable. Any metric below these marks indicates a fundamental flaw.

### 13.1 Lip Sync Quality

| System | Lip Sync Score (LSE-D ↓) | FID ↓ | FPS | Source |
|--------|--------------------------|-------|-----|--------|
| Wav2Lip | 6.35 | 12.8 | 25-30 | ACMMM 2020 |
| VideoReTalking | 7.41 | 11.2 | 15-20 | SIGGRAPH Asia 2022 |
| SadTalker | 7.90 | 18.4 | 8-15 | CVPR 2023 |
| MuseTalk 1.5 | ~6.0 (est) | ~10 (est) | 60-90 | 2025, non-diffusion |
| LatentSync 1.6 | ~5.5 (est) | ~8 (est) | 0.5-2 | 2024, diffusion |
| LivePortrait | ~6.8 | ~11 | 40-70 | 2024, keypoint-based |
| **Phoenix target** | **< 6.0** | **< 10** | **60+** | Gaussian + prosody |

### 13.2 Avatar Realism (User Studies)

| System | MOS (Mean Opinion Score, 1-5 ↑) | Identity Preservation | Real-time? |
|--------|--------------------------------|----------------------|-----------|
| Synthesia | 3.8 | High (trained per person) | Yes (cloud) |
| HeyGen | 3.5 | Medium | Yes (cloud) |
| D-ID | 3.2 | Medium | Yes (cloud) |
| Audio2Face (NVIDIA) | 4.0 | N/A (3D model) | Yes (local) |
| GaussianAvatars | 4.2 | Very high | Yes (100+ FPS) |
| **Phoenix target** | **> 4.0** | **Very high** | **Yes (local, 60+)** |

### 13.3 Voice Cloning Quality

| System | SECS ↑ | WER ↓ | MOS-naturalness ↑ |
|--------|--------|-------|-------------------|
| XTTS v2 (Coqui) | 0.82 | 4.2% | 3.8 |
| Bark (Suno) | 0.75 | 6.1% | 3.5 |
| Qwen3-TTS 1.7B (ours, offline) | 0.95+ | 3.8% | 4.1 |
| Qwen3-TTS 0.6B (ours, real-time) | 0.92-0.97 | 4.1% | 3.9 |
| **Phoenix target** | **> 0.95** | **< 4%** | **> 4.0** |

### 13.4 Expression Accuracy (Audio-to-Face)

| System | Vertex Error (mm ↓) | Lip Vertex Error (mm ↓) | Real-time? |
|--------|---------------------|------------------------|-----------|
| FaceFormer | 4.62 | 3.71 | ~100 FPS |
| CodeTalker | 4.45 | 3.56 | ~80 FPS |
| NVIDIA Audio2Face | ~3.5 (est) | ~2.8 (est) | 60+ FPS |
| EMOTE (CVPR 2024) | 4.12 | 3.21 | ~50 FPS |
| **Phoenix target** | **< 4.0** | **< 3.0** | **60+ FPS** |

### 13.5 End-to-End Latency (Audio In → Video Out)

| System | E2E Latency | Components |
|--------|------------|-----------|
| Zoom avatar | ~200ms | Simple 2D deform, no AI |
| Synthesia (cloud) | 5-30s | Full diffusion pipeline |
| HeyGen (cloud) | 3-10s | Full diffusion pipeline |
| NVIDIA Maxine | ~50ms | Dedicated SDK, no voice |
| Our current (santa_meet_bot) | 2-5s | Whisper + Ollama + TTS + MuseTalk |
| **Phoenix Phase 1 target** | **1-3s** | Whisper + Ollama + TTS + LivePortrait |
| **Phoenix Phase 3 target** | **500ms-2s** | Full GPU pipeline |
| **Phoenix Phase 4 target** | **400ms-1.5s** | Rust orchestrator |

### 13.6 Benchmark Protocol

Every Phoenix milestone must be tested against these marks:

1. **LSE-D**: Lip sync distance on HDTF test set (lower is better). If > 7.0, lip sync is visibly wrong.
2. **FID**: Frechet Inception Distance on generated frames vs ground truth. If > 15, visual quality is degraded.
3. **SECS**: Speaker Encoder Cosine Similarity. Hard gate at 0.95 — no exceptions.
4. **FPS**: Measured end-to-end including encode. If < 30 on RTX 5090, something is fundamentally wrong.
5. **Vertex Error**: FLAME mesh comparison on VOCASET. If > 5mm, expression prediction needs retraining.
6. **User MOS**: 5 human raters score naturalness 1-5. If < 3.5, the avatar feels wrong.

If ANY benchmark falls below the ground truth established by existing systems, development stops and the issue is diagnosed before proceeding. We should always be at or above what others have achieved, because we have better hardware and more embedding data than any of them.

---

## 14. Success Criteria

**Phase 0 Complete When**:
- Zero numpy/OpenCV CPU compositing in render path
- FFmpeg subprocess eliminated from lip-sync pipeline
- Benchmark shows measurable latency reduction

**Phase 1 Complete When**:
- LivePortrait running at 50+ FPS on RTX 5090
- Avatar renders in Google Meet via Playwright
- Quality matches or exceeds MuseTalk

**Phase 2 Complete When**:
- Avatar mirrors room emotion (visible expression change when speaker gets excited)
- Avatar tracks active speaker with gaze
- Gesture selection works from semantic search
- TTS adapts prosody to room energy

**Phase 3 Complete When**:
- 3D Gaussian avatar of Santa renders at 100+ FPS
- Full pipeline audio-to-frame in <15ms
- Zero GPU→CPU copies in render path
- NVENC encodes from GPU memory

**Phase 4 Complete When**:
- Rust orchestrator delivers <10ms render latency
- No Python in critical render path
- Deterministic frame delivery at 60 FPS

**Phase 5 Complete When**:
- Avatar develops measurable personality over 5+ meetings
- Turn prediction accuracy >80%
- Engagement heatmap correlates with human-rated highlights

---

*This system does not exist anywhere else. Every component has been individually proven in research or production, but nobody has assembled them into a unified, embedding-driven, zero-copy GPU pipeline for photorealistic avatar rendering. The RTX 5090 is the first consumer GPU with enough bandwidth, VRAM, and tensor core density to run all of this simultaneously.*
