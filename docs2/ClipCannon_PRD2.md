
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

> **Implementation Status (Phase 2 Complete):** 51 MCP tools implemented (25 Phase 1 + 26 Phase 2). The tool names and signatures below reflect the original PRD design. The actual implemented tools may differ in naming and parameters -- see the source code in `src/clipcannon/tools/` for authoritative signatures. Sections 6.1-6.2 (project, understanding), 6.3 (editing -- 11 tools), 6.4 (audio -- 4 tools), 6.6 (rendering -- 11 tools), 6.7 (metadata), 6.9 (provenance), 6.10 (session/robustness), and 6.11 (configuration) are implemented. Section 6.5 (animation/overlay) features are integrated into the editing and rendering tools. Section 6.8 (publishing) remains Phase 3.


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


### 6.3 Editing Tools (Phase 2 -- IMPLEMENTED)

> **Implemented as 11 tools:** clipcannon_create_edit, clipcannon_modify_edit, clipcannon_list_edits, clipcannon_generate_metadata, clipcannon_auto_trim, clipcannon_color_adjust, clipcannon_add_motion, clipcannon_add_overlay, clipcannon_extract_subject, clipcannon_replace_background, clipcannon_remove_region. The original PRD design below has been superseded by the actual implementation.

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


### 6.4 Audio Generation Tools (Phase 2 -- IMPLEMENTED)

> **Implemented as 4 tools:** clipcannon_generate_music, clipcannon_compose_midi, clipcannon_generate_sfx, clipcannon_audio_cleanup. Audio preview, soundfont listing, edit attachment, and mixing are integrated into the rendering pipeline.

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_generate_music | Generate AI background music via ACE-Step | prompt, duration_ms, model_variant? (turbo-rl|turbo|sft), lora? (Text2Samples|RapMachine), guidance_scale?, seed?, output_path? |
| clipcannon_compose_midi | Generate deterministic music via MIDI composition | tempo_bpm, key, mood, chord_progression[], bars, instruments[], soundfont?, output_path? |
| clipcannon_generate_sfx | Generate programmatic sound effect via DSP | type (whoosh|riser|downer|impact|chime|tick|bass_drop|shimmer|stinger), duration_ms?, params?, output_path? |
| clipcannon_preview_audio | Generate and preview audio asset without attaching to edit | audio_spec (same as EDL audio object) |
| clipcannon_list_soundfonts | List available SoundFont files for MIDI rendering |  |
| clipcannon_set_edit_audio | Attach audio configuration to an existing edit | edit_id, audio (full audio object from EDL spec) |
| clipcannon_mix_audio | Generate final audio mix for an edit (background + source + SFX) | edit_id, duck_under_speech?, duck_level_db?, normalize? |


### 6.5 Animation & Overlay Tools (Phase 2 -- integrated into editing/rendering tools)

> **Note:** Animation and overlay features are implemented through clipcannon_add_overlay (editing) and the rendering pipeline rather than as separate standalone tools. The PRD-designed tools below were consolidated during implementation.

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


### 6.6 Rendering Tools (Phase 2 -- IMPLEMENTED)

> **Implemented as 11 tools:** clipcannon_render, clipcannon_render_status, clipcannon_render_batch, clipcannon_get_editing_context, clipcannon_analyze_frame, clipcannon_preview_clip, clipcannon_inspect_render, clipcannon_preview_layout, clipcannon_measure_layout, clipcannon_get_storyboard, clipcannon_get_scene_map. The render_all_platforms and render_thumbnail features are handled through render_batch with platform profiles.

| Tool | Description | Parameters |
|:---|:---|:---|
| clipcannon_render | Render an edit to final output video (includes audio mix + animations) | edit_id, profile?, output_path? |
| clipcannon_render_batch | Render multiple edits in parallel (up to 3 on RTX 5090) | edit_ids[], profiles? |
| clipcannon_render_all_platforms | Render one edit to all target platforms | edit_id, platforms[] |
| clipcannon_render_status | Check render progress | render_job_id |
| clipcannon_render_thumbnail | Generate thumbnail image from edit | edit_id, timestamp_ms? |


### 6.7 Metadata & Content Tools (Phase 2 -- IMPLEMENTED)

> **Implemented as clipcannon_generate_metadata** (in the editing module). The individual generate_title, generate_description, generate_hashtags, and batch_metadata tools were consolidated into the single generate_metadata tool.

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


