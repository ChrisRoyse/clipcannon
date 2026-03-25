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
    "highlight_count_default": 20,
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
  "publishing": {
    "require_approval": true,
    "max_daily_posts_per_platform": 5
  },
  "gpu": {
    "device": "cuda:0",
    "max_vram_usage_gb": 24,
    "concurrent_models": true
  }
}
```

> **Note (Phase 2 actual):** The implementation's `config/default_config.json` contains 7 sections: `version`, `directories`, `processing`, `rendering`, `audio`, `publishing`, `gpu`. The `audio` section was added in Phase 2 with simplified keys: `music_model` ("ace-step"), `music_guidance_scale` (3.5), `music_default_volume_db` (-12), `duck_under_speech` (true), `sfx_on_transitions` (true), `normalize_output` (true). The `rendering` section gained `max_parallel_renders` (3). The `animation` config section below is planned for Phase 3.
>
> **Phase 3 config additions (planned):**
> ```json
> "animation": {
>   "lower_third_template": "modern_bar",
>   "lower_third_duration_ms": 6000,
>   "title_card_animation": "fade_scale",
>   "default_transition": "fade",
>   "default_transition_duration_ms": 500,
>   "fetch_remote_lottie": false,
>   "default_font": "Montserrat",
>   "default_primary_color": "#2563EB",
>   "default_text_color": "#FFFFFF"
> }
> ```

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
