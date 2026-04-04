# Phoenix Real-Time Avatar Rendering: First Principles Architecture

## RTX 5090 Blackwell + CUDA 13.2

**Date**: 2026-04-04
**Target**: Photorealistic avatar indistinguishable from real person on video call
**Hardware**: RTX 5090 (32GB GDDR7, 170 SMs, 680 Tensor Cores, 1792 GB/s BW)

---

## Key Insight: Video Call ≠ Cinema

A video call runs at 720p, 1-3 Mbps WebRTC compression, with expected artifacts.
The RTX 5090 can render this with **3-5x headroom**. The challenge is pipeline
design, not raw compute.

## Human Perception Requirements (Video Call Context)

| Attribute | Minimum | Why |
|-----------|---------|-----|
| Resolution | 1280x720 | Standard webcam; face ~350px tall |
| Frame rate | 25 FPS | Captures 40ms microexpressions |
| Temporal consistency | Zero visible jumps | #1 uncanny trigger |
| Lip sync | <80ms audio-to-visual | Below annoyance threshold |
| Eye animation | Microsaccades + gaze | Biggest social presence driver |
| Skin rendering | Approximate SSS | 94% of skin appearance |
| Motion blur | Half-shutter synthetic | Without it, motion too crisp |
| Film grain/noise | Subtle sensor noise | Too clean = obviously synthetic |
| Breathing | 12-20 BPM chest motion | Static torso = dead |

## Pipeline Architecture

```
Speech Audio ──→ [Audio2Face-3D] ──→ ARKit Blendshapes ──┐
                     (3-5ms)                              │
Emotion State ──→ [BehaviorEngine] ──→ Expression ────────┤
                     (0.5ms)                              │
Social Context ──→ [Gaze/Gesture] ──→ Pose Params ───────┤
                     (0.3ms)                              │
                                                          ▼
Reference Face ──→ [Trained 3DGS Model] ──→ [gsplat Render] ──→ [NVENC] ──→ Video
                   (loaded at startup)        (2-4ms)           (1-2ms)     Stream
```

## Per-Stage Latency (RTX 5090)

| Stage | Operation | Latency | Hardware |
|-------|-----------|---------|----------|
| 1 | Audio2Face-3D (regression v2.2) | 3-5ms | Tensor Cores FP4, 16 SMs |
| 2 | BehaviorEngine emotion+gesture | 0.5ms | CPU |
| 3 | Blendshape → Gaussian params | 0.3ms | CUDA kernel, 8 SMs |
| 4 | Gaussian splatting render 720p | 2-4ms | gsplat, 24 SMs |
| 5 | Compositing (grain, noise, SSS) | 0.5ms | CuPy kernels |
| 6 | RGB → NV12 conversion | 0.2ms | CuPy kernel |
| 7 | NVENC H.264 encode | 1-2ms | Dedicated HW (async) |
| **TOTAL** | | **7-13ms** | **27-33ms headroom** |

## VRAM Budget

| Component | VRAM | Status |
|-----------|------|--------|
| 3DGS head model (~100K Gaussians) | 2-4 GB | Phase 3 |
| Audio2Face-3D regression | 1-2 GB | Phase 1 |
| gsplat rasterizer buffers | 0.3 GB | Phase 3 |
| CuPy compositor | 0.1 GB | Existing |
| NVENC session | 0.1 GB | Phase 0 |
| Whisper (ASR) | 3-4 GB | Existing |
| Ollama 8B (LLM) | 5 GB | Existing |
| TTS 0.6B | 2 GB | Existing |
| **TOTAL** | **13-17 GB** | **15-19 GB free** |

## Green Context SM Partitioning

| Partition | SMs | % | Purpose |
|-----------|-----|---|---------|
| Render | 24 | 14% | Gaussian splatting + compositing |
| Audio2Face | 16 | 9% | Audio → blendshape inference |
| General | 130 | 77% | LLM, ASR, TTS |

## Key Technologies

| Technology | Source | License | Purpose |
|-----------|--------|---------|---------|
| Audio2Face-3D | NVIDIA | MIT | Audio → 52 ARKit blendshapes, 3-5ms |
| gsplat | Nerfstudio | Apache 2.0 | Gaussian splatting rasterizer, 400+ FPS |
| GaussianAvatars/RGBAvatar | Research | Varies | FLAME-rigged head avatar, 398 FPS |
| PyNvVideoCodec 2.0 | NVIDIA | MIT | Zero-copy GPU encode, replaces FFmpeg |
| FLAME | MPI | Research | Parametric face model, 53 blendshapes |
| CUDA Green Contexts | NVIDIA | CUDA | SM partitioning for deterministic latency |

## Phased Implementation

### Phase 0: GPU-Native Video Pipeline (3-5 days)
- Replace Y4MWriter with PyNvVideoCodec (GPU → NVENC → pipe, zero CPU copies)
- Add webcam imperfection layer (auto-exposure jitter, color temp drift)
- Add temporal consistency filter (EMA on params, not pixels)

### Phase 1: Audio2Face Integration (3-5 days)
- Install nvidia-audio2face-3d (already installed)
- Create Audio2Face adapter → AvatarExpression mapping
- Replace RMS lip sync with full facial animation from audio
- Wire emotion modulation from EmotionFusion

### Phase 2: LivePortrait Intermediate (1 week)
- FasterLivePortrait with TensorRT (60+ FPS on 5090)
- Driven by Audio2Face blendshapes
- Immediate visual improvement while Phase 3 trains

### Phase 3: 3D Gaussian Avatar (2-3 weeks)
- Train GaussianAvatars/RGBAvatar from source video (80s for RGBAvatar)
- Integrate gsplat rasterizer into Phoenix
- FLAME blendshape driver: Audio2Face → FLAME → Gaussian → gsplat
- Eye behavior model (microsaccades, blinks, gaze tracking)
- Subsurface scattering approximation

### Phase 4: Green Context Isolation (1 week)
- C extension for Green Context API
- SM partitioning: render vs AI workloads
- Frame pipelining: encode N while rendering N+1
- Target: consistent sub-10ms, zero jitter

## Critical Success Factors

1. **Temporal consistency > spatial quality** — Smooth but blurry beats sharp but flickery
2. **Audio2Face-3D is the single highest-impact addition** — Full facial animation from audio
3. **Eye behavior after lip sync is #2 priority** — Gaze drives social presence
4. **Deliberate imperfections increase realism** — Grain, exposure flicker, compression
5. **EMA smoothing on Gaussian params, NOT on pixels** — Prevents ghosting
6. **RGBAvatar trains in 80 seconds** — Fast iteration on quality

## References

- GaussianAvatars (CVPR 2024): FLAME-rigged Gaussian heads, 187 FPS
- RGBAvatar (CVPR 2025): Online modeling in 80s, 398 FPS
- Audio2Face-3D: github.com/NVIDIA/Audio2Face-3D-Samples (MIT)
- gsplat: github.com/nerfstudio-project/gsplat (Apache 2.0)
- PyNvVideoCodec: developer.nvidia.com/pynvvideocodec
- "Inner Thoughts" (CHI 2025, arxiv 2501.00383)
- CUDA 13.2 Green Contexts: developer.nvidia.com/cuda-toolkit
