# Multi-Embedding Clone Model: 9-Embedder Avatar Training

## Overview

Train a 13M parameter model on 9 simultaneous embedding spaces to reproduce
a human clone (Santa Claus) with maximum fidelity. The model replaces
hand-crafted behavior rules with learned mappings trained on real video data.

**This has never been done before.**

## The 9 Embeddings (5,900 dimensions total)

| # | Embedding | Model | Dim | What It Captures |
|---|-----------|-------|-----|-----------------|
| 1 | Visual | SigLIP-SO400M | 1152 | What Santa looks like |
| 2 | Semantic | Nomic-embed-text-v1.5 | 768 | What Santa says/means |
| 3 | Emotion | Wav2Vec2-large | 1024 | Emotional state of voice |
| 4 | Speaker | WavLM-base-plus-sv | 512 | Voice identity fingerprint |
| 5 | Voice | ECAPA-TDNN | 2048 | Detailed voice characteristics |
| 6 | Prosody | pyworld extraction | 12 | F0, energy, rate, contour |
| 7 | OCR Context | OCR Provenance | 512* | Document/meeting history |
| 8 | Memory | RuFlo Memory | 512* | Persistent agent memory |
| 9 | Sentence | all-MiniLM-L6-v2 | 384 | Sentence-level semantics |

*projected to 512-dim

## Model Architecture (13M parameters)

```
9 Embeddings → Per-modality Linear Projection (each → 512-dim)
                     + Learned Modality Embeddings
                            ↓
              Perceiver Cross-Attention (4 layers, 128 latent queries)
                            ↓
              FiLM Conditioning (prosody 12 scalars → gamma/beta)
                            ↓
              Transformer Decoder (4 self-attention layers)
                            ↓
              ┌─────────────┼──────────────┐
              ↓             ↓              ↓
         Blendshape    Voice Params    Behavior
         Head (8)      Head (16)       Head (6)
```

## Output Dimensions (30 total)

**Blendshapes (8):** jaw_open, brow_raise, brow_furrow, mouth_stretch,
head_nod_intensity, head_tilt, eye_wide, squint

**Voice Params (16):** prosody_style, speaking_rate, pitch_target,
pitch_variation, energy_target, emphasis_strength, breathiness,
formant_shift, emotion_blend (4), tts_temperature, tts_top_p,
ref_clip_weight, pause_probability

**Behavior (6):** speak_probability, expression_intensity, gesture_id,
reaction_type, head_motion_scale, gaze_target

## Training Data

- Source: 975s Santa video (already fully embedded)
- Frames: 24,375 at 25fps
- Each frame: all 9 embeddings + ground truth blendshapes
- Dataset size: ~2.3GB (fits in 128GB RAM)

## Training Pipeline

### Stage 1: Supervised (fast, ~7 minutes)
- Loss: MSE(predicted, ground_truth_blendshapes) + contrastive across embeddings
- 2000 epochs, batch size 256
- No re-embedding needed

### Stage 2: Cycle Consistency (optional, ~2 minutes)
- Render avatar → re-embed through all 9 systems
- Loss: cosine distance between input and output embeddings
- 100-500 fine-tuning steps
- Gradient checkpointing for VRAM management

## Loss Function

```
L = w_visual * (1 - cos_sim(visual_in, visual_out))
  + w_semantic * (1 - cos_sim(semantic_in, semantic_out))
  + w_emotion * (1 - cos_sim(emotion_in, emotion_out))
  + w_speaker * (1 - cos_sim(speaker_in, speaker_out))
  + w_voice * (1 - cos_sim(voice_in, voice_out))
  + w_prosody * MSE(prosody_in, prosody_out)
  + w_sentence * (1 - cos_sim(sentence_in, sentence_out))
  + L_temporal  (smoothness regularization)
  + L_identity  (voice fingerprint preservation)
```

## Hardware Requirements

- GPU: RTX 5090 32GB (model uses <100MB VRAM)
- RAM: 128GB (dataset ~2.3GB + embedder models)
- Training time: <10 minutes total
- Inference: <1ms per frame

## Additional Embedders to Add

| # | Embedder | Dim | Priority |
|---|----------|-----|----------|
| 10 | FACS Action Units | 46 | High |
| 11 | Gaze Direction | 6 | High |
| 12 | Lip Reading (AV-HuBERT) | 768 | High |
| 13 | Body Pose (MediaPipe) | 99 | Medium |
| 14 | Breath Pattern | 4 | Medium |

## Why This Is Novel

1. **9+ simultaneous conditioning spaces** — nobody has done more than 2-3
2. **Self-referential evaluation** — same embedders used for input AND quality measurement
3. **Clone-specific training** — optimized for one person, not generalization
4. **Cycle consistency in embedding space** — output re-embedded must match input
5. **Practical scale** — 13M params, 10 min training, <1ms inference

## Implementation Phases

1. **Data Pipeline** (2-3 days): Extract ground truth blendshapes, temporal alignment
2. **Model + Stage 1** (2-3 days): Build architecture, train supervised
3. **Integration** (2-3 days): Replace BehaviorEngine rules with learned model
4. **Cycle Consistency** (1-2 days): Stage 2 fine-tuning
5. **Expand Embedders** (1-2 days): Add FACS, gaze, body pose
