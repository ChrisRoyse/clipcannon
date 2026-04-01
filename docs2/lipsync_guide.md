# ClipCannon Lip-Sync & Webcam System Guide

Complete technical guide covering everything done to get LatentSync 1.6 lip-sync working at production quality with ClipCannon's voice cloning pipeline.

## Architecture Overview

```
Source Video (4K 60fps screen recording with webcam PIP)
    |
    v
clipcannon_ingest (22-stage DAG)
    -> scene_analysis: face detection, webcam region, content area
    -> transcription: word-level timestamps
    -> scene_map: pre-computed canvas regions for all layouts
    |
    v
clipcannon_extract_webcam
    -> Reads scene_map face/webcam coordinates
    -> FFmpeg crops webcam region from source
    -> Forces 25fps output (critical for LatentSync)
    |
    v
clipcannon_speak (voice cloning)
    -> Qwen3-TTS 1.7B with reference audio
    -> Iterative verification (sanity -> intelligibility -> identity)
    -> Resemble Enhance post-processing (24kHz -> 44.1kHz)
    |
    v
clipcannon_lip_sync
    -> LatentSync 1.6 diffusion pipeline
    -> Whisper tiny audio embeddings -> UNet cross-attention
    -> Face detection (InsightFace) -> alignment -> 512x512 processing
    -> Face restoration back to original resolution
    -> Audio remux: replace 16kHz output with original 44.1kHz
    |
    v
Final output: lip-synced video with broadcast-quality voice
```

## Prerequisites

### Hardware
- NVIDIA GPU with 18+ GB VRAM (RTX 4090, RTX 5090, A100)
- Additional ~4GB for Qwen3-TTS voice synthesis
- Additional ~6GB for Whisper Large v3 (ingest pipeline)

### Software
```bash
# ClipCannon core + phase3 avatar deps
pip install -e ".[ml,phase2,phase3]"

# LatentSync-specific deps
pip install kornia insightface onnxruntime-gpu einops DeepCache accelerate
```

### Model Downloads

**LatentSync** (auto-downloaded by `scripts/download_models.py`):
```
~/.clipcannon/models/latentsync/
    checkpoints/
        latentsync_unet.pt          # 4.72 GB - UNet diffusion model
        whisper/
            tiny.pt                  # 72 MB - Whisper audio encoder
    configs/
        unet/
            stage2_512.yaml          # Model config (512x512 resolution)
        scheduler_config.json        # DDIM scheduler config
    latentsync/
        utils/
            mask.png                 # Lower-face mask for inpainting
```

Clone the LatentSync repo if not present:
```bash
git clone https://github.com/bytedance/LatentSync.git ~/.clipcannon/models/latentsync
```

Download checkpoints:
```bash
huggingface-cli download ByteDance/LatentSync-1.6 latentsync_unet.pt --local-dir ~/.clipcannon/models/latentsync/checkpoints
huggingface-cli download ByteDance/LatentSync-1.6 whisper/tiny.pt --local-dir ~/.clipcannon/models/latentsync/checkpoints
```

**Voice profiles** must be set up separately via `clipcannon_prepare_voice_data` + `clipcannon_voice_profiles`.

## Critical Fixes That Made It Work

### Fix 1: UNet Loading (from_pretrained, not from_config)

The original wrapper used `from_config + load_state_dict` which silently failed because the LatentSync checkpoint wraps weights in `{"state_dict": ..., "global_step": ...}`. The official `from_pretrained` method handles this extraction.

```python
# WRONG (silent failure - loads empty/random weights)
unet = UNet3DConditionModel.from_config(config.model)
unet.load_state_dict(torch.load(path), strict=False)

# CORRECT (extracts state_dict from checkpoint dict)
unet, _ = UNet3DConditionModel.from_pretrained(
    OmegaConf.to_container(config.model),
    str(checkpoint_path),
    device="cpu",
)
```

### Fix 2: audio_feat_length Must Be a List

The Whisper audio encoder expects `audio_feat_length=[2, 2]` (2 past + 2 future context frames). The original code passed a scalar `2`, causing the audio embedding slicing to break.

```python
# WRONG
audio_feat_length=config.data.get("audio_feat_length", 2)

# CORRECT
audio_feat_length=config.data.audio_feat_length  # [2, 2] from config
```

### Fix 3: Driver Video MUST Be 25fps

LatentSync is hardcoded to 25fps (`video_fps: 25` in config). The Whisper audio features are sliced at 50Hz and aligned to 25fps video frames (2 audio frames per video frame). Feeding 60fps video causes every frame to be misaligned -- the model processes frame N thinking it's at time T, but the audio embedding is for a completely different time.

```python
# In webcam extraction FFmpeg command:
cmd = [
    "ffmpeg", "-y", "-loglevel", "error",
    "-i", str(source_path),
    "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
    "-r", "25",  # CRITICAL: force 25fps for LatentSync
    "-c:v", "libx264", "-crf", "18",
    str(output_path),
]
```

### Fix 4: Audio Remux (16kHz -> 44.1kHz)

LatentSync internally downsamples audio to 16kHz for Whisper processing, then writes the output video with that 16kHz audio. This destroys voice quality. After LatentSync finishes, we remux the original high-quality audio back in:

```python
# After LatentSync generates the video:
remux_cmd = [
    "ffmpeg", "-y", "-loglevel", "error",
    "-i", str(output_path),        # video from LatentSync
    "-i", str(audio_path),          # original 44.1kHz audio
    "-map", "0:v:0",                # video track from LatentSync
    "-map", "1:a:0",                # audio track from original
    "-c:v", "copy",                  # no video re-encode
    "-c:a", "aac", "-b:a", "192k",  # high-quality AAC
    "-shortest",
    str(remuxed_path),
]
```

This single fix takes audio from 16kHz/68kbps to 44.1kHz/192kbps -- the difference is immediately obvious.

### Fix 5: imageio/PyAV Compatibility

imageio 2.37+ with PyAV 16+ dropped the `macro_block_size` parameter from `get_writer()`. The LatentSync `write_video` function needed to be patched to use OpenCV's VideoWriter instead:

```python
# In latentsync/utils/util.py - replaced imageio writer with cv2:
def write_video(video_output_path, video_frames, fps):
    height, width = video_frames[0].shape[:2]
    out = cv2.VideoWriter(
        video_output_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps, (width, height),
    )
    for frame in video_frames:
        out.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    out.release()
```

### Fix 6: weight_dtype Passthrough

The official inference script passes `weight_dtype` to the pipeline call and converts the UNet to the target dtype before assembly. Our wrapper was missing both:

```python
# Determine dtype from GPU capability
is_fp16 = torch.cuda.get_device_capability()[0] > 7
dtype = torch.float16 if is_fp16 else torch.float32

# Convert UNet BEFORE pipeline assembly
unet = unet.to(dtype=dtype)

# Pass weight_dtype in the pipeline call
pipeline(
    ...,
    weight_dtype=dtype,
    width=config.data.resolution,   # 512
    height=config.data.resolution,  # 512
)
```

## What NOT to Do (Lessons Learned)

### DO NOT apply CodeFormer to lip-sync output

CodeFormer is a face restoration model trained to produce "natural" faces. It normalizes mouth shapes back toward neutral expressions, completely destroying the phoneme-specific lip movements that LatentSync generated. Tested with fidelity=0.6 and it made lips 100% out of sync.

If you want face enhancement, apply it ONLY to non-mouth regions, or use it on the driver video BEFORE lip-sync, not after.

### DO NOT use Poisson blending for face paste-back

`cv2.seamlessClone` with `MIXED_CLONE` averages gradients between the source (lip-synced) and destination (original) faces. This dilutes the mouth movements. LatentSync's built-in soft mask blending (erosion + Gaussian blur) is specifically designed to preserve the generated lip detail while smoothing boundaries.

### DO NOT increase guidance_scale above 2.0

`guidance_scale=1.5` is the sweet spot. At 2.0+ the model over-conditions on audio features, causing face jitter and distortion artifacts. The config default of 1.5 was chosen by ByteDance for good reason.

### DO NOT use speak_optimized for lip-sync voice generation

The best-of-N SECS selection (`speak_optimized`) picks the candidate with highest speaker encoder cosine similarity. This optimizes for voice identity matching but can select candidates with unnatural prosody or pacing that hurts lip-sync. Regular `speak` with its iterative verification loop (sanity -> intelligibility -> identity gates) produces more natural speech that syncs better.

### DO NOT over-engineer inference_steps

20 steps is the sweet spot. 30 steps gives ~5% visual improvement for 50% more processing time. 40-50 steps show no perceptible improvement. DDIM converges rapidly -- the marginal returns aren't worth the compute.

## Optimal Parameters

| Parameter | Value | Why |
|-----------|-------|-----|
| inference_steps | 20 | Sweet spot: 90% of max quality at baseline speed |
| guidance_scale | 1.5 | Balanced sync accuracy without face distortion |
| Driver FPS | 25 | Matches LatentSync internal processing (hardcoded) |
| Audio format | WAV (any sample rate) | Whisper resamples to 16kHz internally |
| Output audio | 44.1kHz AAC 192kbps | Remuxed from original after LatentSync |
| DeepCache | Enabled (interval=3) | ~1.5x speedup with negligible quality loss |
| Seed | 1247 (or random) | Default from ByteDance; different seeds give different mouth shapes |
| Voice synthesis | speak (not speak_optimized) | More natural prosody for lip-sync |
| Voice enhance | true | Resemble Enhance removes metallic TTS artifacts |

## How LatentSync Actually Works

Understanding the pipeline helps debug issues:

1. **Audio encoding**: Whisper tiny converts audio to 80-channel mel spectrograms at 16kHz, then encodes to 384-dim embeddings at 50Hz

2. **Frame alignment**: Audio embeddings are sliced into chunks aligned to 25fps video frames. Each frame gets `audio_feat_length=[2,2]` = 4 audio embedding frames (2 past + 2 future context)

3. **Face detection**: InsightFace with 106-point landmarks detects faces in every frame. If face < 50x80px or confidence < 0.5, it fails with "Face not detected"

4. **Affine alignment**: 3-point affine transform (left eyebrow, right eyebrow, nose) warps the face to a standardized 512x512 template using kornia

5. **Video looping**: If audio is longer than video, the video frames are looped with ping-pong (forward then reverse) to maintain natural head movement

6. **Diffusion inpainting**: The lower face (defined by `mask.png`) is inpainted using a 3D UNet conditioned on audio embeddings via cross-attention. The upper face (eyes, forehead) is preserved as reference. Processing happens in 16-frame chunks.

7. **Face restoration**: Inverse affine transform pastes the processed 512x512 face back into the original frame. Erosion + Gaussian blur creates a soft mask boundary.

8. **Output assembly**: Frames are written to video via OpenCV, audio is remuxed via FFmpeg at original quality.

## MCP Tools Reference

| Tool | Purpose |
|------|---------|
| `clipcannon_extract_webcam` | Extract webcam/face region from ingested video at 25fps |
| `clipcannon_speak` | Voice-clone speech with verification gating |
| `clipcannon_lip_sync` | LatentSync diffusion lip-sync with audio remux |
| `clipcannon_generate_video` | End-to-end: auto-webcam + voice + lip-sync |

### Full workflow example:
```
1. clipcannon_project_create(source_video_path="/path/to/video.mp4")
2. clipcannon_ingest(project_id="proj_xxx")
3. clipcannon_extract_webcam(project_id="proj_xxx", padding_pct=0.1)
4. clipcannon_speak(project_id="proj_xxx", text="New script...", voice_name="boris")
5. clipcannon_lip_sync(
       project_id="proj_xxx",
       audio_path="<from step 4>",
       driver_video_path="<from step 3>",
       inference_steps=20,
       guidance_scale=1.5
   )
```

Or in one shot:
```
clipcannon_generate_video(
    project_id="proj_xxx",
    script="New script...",
    voice_name="boris"
)
```

## Files Modified/Created

### New files:
- `src/clipcannon/avatar/face_enhance.py` -- CodeFormer wrapper (kept for future non-mouth use)
- `src/clipcannon/tools/avatar_defs.py` -- Updated with extract_webcam + n_candidates
- `docs2/lipsync_guide.md` -- This guide

### Modified files:
- `src/clipcannon/avatar/lip_sync.py` -- Complete rewrite: correct UNet loading, DeepCache, audio remux, multi-seed
- `src/clipcannon/tools/avatar.py` -- Added extract_webcam handler, multi-seed support
- `src/clipcannon/tools/generate_video.py` -- Auto webcam extraction, optional driver_video_path
- `src/clipcannon/tools/generate_defs.py` -- Updated schema (driver_video_path optional)
- `pyproject.toml` -- Added phase3 optional deps
- `scripts/download_models.py` -- Added LatentSync download
- `tests/test_avatar.py` -- Expanded from 12 to 30 tests

### Patched LatentSync files (in ~/.clipcannon/models/latentsync/):
- `latentsync/utils/util.py` -- write_video: imageio -> cv2 for PyAV 16 compat
- `latentsync/utils/affine_transform.py` -- Kept original soft mask blending (reverted Poisson)
- `latentsync/pipelines/lipsync_pipeline.py` -- Kept original restore_video (reverted CodeFormer)

## Performance

| Operation | Time | Hardware |
|-----------|------|----------|
| Ingest (22 stages) | ~105s | RTX 5090 |
| Webcam extraction | ~7-10s | CPU (FFmpeg) |
| Voice synthesis (40s speech) | ~45s | RTX 5090 |
| Voice enhancement | ~15s | RTX 5090 |
| Lip-sync (40s video, 20 steps) | ~300s | RTX 5090 |
| Audio remux | ~1s | CPU (FFmpeg) |
| **Total pipeline** | **~8 min** | **for 40s of output** |

First run adds ~30s for LatentSync model loading (~18GB into VRAM). Subsequent runs reuse the cached pipeline singleton.
