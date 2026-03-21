# AI Audio Generation Engine

## 1. Overview

ClipCannon's audio engine generates original background music, MIDI compositions, and programmatic sound effects. All generated audio is original work, eliminating licensing fees entirely. The engine operates across three tiers of increasing complexity and resource requirements, unified by a mixing pipeline that produces broadcast-ready output.

### Three-Tier Architecture

| Tier | Technology | Compute | Latency | Use Case |
|------|-----------|---------|---------|----------|
| **Tier 1** | ACE-Step v1.5 AI Music Generation | GPU, ~4GB VRAM | ~1.7s/min of audio | Full songs from text prompts |
| **Tier 2** | MIDI Composition + FluidSynth Rendering | CPU only | Deterministic | Theory-correct compositions |
| **Tier 3** | Programmatic DSP Sound Effects | CPU only | <100ms per effect | Mathematical synthesis |

All tiers feed into a shared **audio mixing pipeline** (pydub + pedalboard) that combines sources with speech-aware ducking, loudness normalization, and broadcast-standard output.

### Design Principles

- **Zero licensing cost**: Every generated audio asset is original, created on-the-fly.
- **Deterministic when needed**: Seeded generation (ACE-Step) and rule-based composition (MIDI) guarantee reproducibility.
- **GPU-aware scheduling**: Audio generation coordinates with the understanding pipeline to avoid VRAM contention.
- **Speech-first mixing**: Background music and SFX always defer to speech intelligibility through automatic ducking.

---

## 2. Tier 1: ACE-Step v1.5 AI Music Generation

### Model Details

| Property | Value |
|----------|-------|
| Model | ACE-Step v1.5 turbo-rl |
| License | MIT |
| Architecture | Hybrid Language Model + Diffusion Transformer |
| VRAM (cpu_offload) | ~4GB |
| VRAM (full GPU) | ~8GB |
| Output format | 44.1kHz stereo WAV |
| Speed (RTX 4090) | ~1.7 seconds per minute of generated audio |
| Maximum duration | 4+ minutes per generation |
| LoRA support | Text2Samples LoRA for SFX-style generation |

### Integration

```python
from ace_step import ACEStepPipeline

pipeline = ACEStepPipeline.from_pretrained(
    "ace-step-v15-turbo-rl",
    lora_path="Text2Samples",
    cpu_offload=True  # Saves VRAM, slightly slower
)

result = pipeline.generate(
    prompt="upbeat electronic background music, 120 BPM, energetic, podcast intro",
    duration_seconds=30,
    guidance_scale=7.5,
    seed=42  # Reproducible
)
result.save("background_music.wav")
```

### Prompt Engineering for Music

The AI constructs music prompts by combining multiple context signals from the Phase 1 understanding pipeline:

| Signal Source | Prompt Contribution | Example |
|---------------|---------------------|---------|
| `emotion_curve` (Phase 1) | Content mood descriptors | "melancholic, building tension" |
| Platform target | Energy and style | TikTok = "energetic, catchy"; LinkedIn = "professional, understated" |
| Content type | Genre and structure | Podcast = "ambient, atmospheric"; Highlight = "dramatic, cinematic" |
| BPM analysis | Tempo matching | Match speaking pace or detected musical beats |
| Segment duration | Generation length | Short transition = 5s; full bed = 60s |

#### Prompt Templates

```
# Podcast background
"gentle ambient electronic pad, {bpm} BPM, warm, professional, podcast background music"

# TikTok/Reels
"upbeat {genre}, {bpm} BPM, energetic, catchy hook, social media short form"

# LinkedIn professional
"corporate background music, {bpm} BPM, piano and light strings, professional"

# Dramatic highlight
"cinematic orchestral build, {bpm} BPM, dramatic, rising tension, climax at {peak_pct}%"

# Intro/outro jingle
"short jingle, {bpm} BPM, memorable melody, {mood}, brand intro"
```

### VRAM Scheduling

ACE-Step shares GPU resources with the understanding pipeline. The following rules govern VRAM allocation:

1. ACE-Step loads **only after** all understanding pipeline models (Whisper, CLIP, etc.) are fully unloaded from VRAM.
2. On RTX 5090 (32GB): full GPU mode (`cpu_offload=False`), consuming ~8GB VRAM.
3. On 8GB GPUs (e.g., RTX 4060): automatic `cpu_offload=True`, consuming ~4GB VRAM.
4. On GPUs with <4GB VRAM: fall back to Tier 2 (MIDI composition).
5. Model is unloaded immediately after generation completes to free VRAM for downstream stages.

```python
# VRAM-aware model loading
class AudioModelScheduler:
    def __init__(self, gpu_manager):
        self.gpu = gpu_manager

    async def generate_music(self, prompt: str, duration_s: float, seed: int) -> Path:
        vram_available = self.gpu.get_free_vram_gb()

        if vram_available < 4.0:
            # Fall back to MIDI
            return await self.midi_fallback(prompt, duration_s)

        cpu_offload = vram_available < 8.0

        async with self.gpu.exclusive_lock("ace_step"):
            pipeline = ACEStepPipeline.from_pretrained(
                "ace-step-v15-turbo-rl",
                cpu_offload=cpu_offload,
            )
            result = pipeline.generate(
                prompt=prompt,
                duration_seconds=duration_s,
                seed=seed,
            )
            del pipeline  # Free VRAM immediately
            torch.cuda.empty_cache()

        return result.save_path
```

### Quality Controls

- **Seed pinning**: Every generation records its seed in provenance for exact reproducibility.
- **Guidance scale tuning**: Default 7.5; lower (5.0) for more creative variation, higher (10.0) for tighter prompt adherence.
- **Duration limits**: Generations >4 minutes are split into overlapping segments and crossfaded.
- **Output validation**: Generated WAV is checked for silence, clipping, and minimum RMS level before acceptance.

---

## 3. Tier 2: MIDI Composition + FluidSynth

### When to Use MIDI

| Scenario | Rationale |
|----------|-----------|
| Long ambient beds (>2 min) | More consistent than AI generation for extended durations |
| Deterministic output required | Exact reproducibility guaranteed, byte-for-byte identical |
| Specific musical requirements | Exact chord progressions, time signatures, modulations |
| Low-resource environments | CPU only, zero GPU dependency |
| GPU unavailable or busy | Automatic fallback when VRAM < 4GB |

### Pipeline

```
music21 (theory engine)
    |
    v
MIDIUtil (MIDI file writer)
    |
    v
FluidSynth (MIDI -> WAV renderer using SoundFont)
    |
    v
44.1kHz stereo WAV output
```

1. **music21** generates chord progressions and melodies based on music theory rules (key, mode, voice leading).
2. **MIDIUtil** writes the MIDI file with precise timing, velocity, and instrument assignments.
3. **FluidSynth** renders MIDI to WAV using high-quality SoundFont instrument samples (GeneralUser GS or equivalent).

### Composition Presets

| Preset | Style | Instruments | Tempo | Use Case |
|--------|-------|-------------|-------|----------|
| `ambient_pad` | Gentle ambient pad | Pad, strings | 60-80 BPM | Background for podcasts |
| `upbeat_pop` | Energetic pop | Piano, bass, drums | 120-140 BPM | TikTok/Reels |
| `corporate` | Professional | Piano, light strings | 90-110 BPM | LinkedIn |
| `dramatic` | Cinematic build | Strings, brass, percussion | 80-100 BPM | Highlight moments |
| `minimal_piano` | Solo piano | Piano | 70-90 BPM | Reflective content |
| `intro_jingle` | Short jingle | Mixed | 120 BPM | Intro/outro (5-10s) |

### Chord Progression Rules

Each preset maps to a set of theory-correct chord progressions:

```python
PROGRESSIONS = {
    "ambient_pad": [
        ["Cmaj7", "Am7", "Fmaj7", "G7"],       # I-vi-IV-V with 7ths
        ["Dm7", "G7", "Cmaj7", "Am7"],          # ii-V-I-vi
    ],
    "upbeat_pop": [
        ["C", "G", "Am", "F"],                   # I-V-vi-IV (pop canon)
        ["C", "Am", "F", "G"],                   # I-vi-IV-V
    ],
    "corporate": [
        ["C", "F", "Am", "G"],                   # I-IV-vi-V
        ["C", "Em", "F", "G"],                   # I-iii-IV-V
    ],
    "dramatic": [
        ["Cm", "Ab", "Eb", "Bb"],               # i-VI-III-VII (minor epic)
        ["Cm", "Fm", "G", "Cm"],                # i-iv-V-i
    ],
    "minimal_piano": [
        ["C", "Am", "F", "G"],                   # I-vi-IV-V
        ["Am", "F", "C", "G"],                   # vi-IV-I-V
    ],
    "intro_jingle": [
        ["C", "G", "C"],                         # I-V-I (short resolution)
    ],
}
```

### Implementation

```python
from midiutil import MIDIFile
from music21 import chord, stream, key, meter

def compose_midi(
    preset: str,
    duration_s: float,
    tempo_bpm: int,
    key_sig: str = "C",
    instruments: list[str] | None = None,
) -> Path:
    """Generate a MIDI composition from a preset."""
    progression = select_progression(preset)
    score = stream.Score()
    score.insert(0, key.Key(key_sig))
    score.insert(0, meter.TimeSignature("4/4"))

    # Generate parts based on preset instruments
    for instrument_name in (instruments or PRESET_INSTRUMENTS[preset]):
        part = generate_part(instrument_name, progression, duration_s, tempo_bpm)
        score.append(part)

    # Write MIDI via MIDIUtil for precise control
    midi = MIDIFile(len(score.parts))
    for track_idx, part in enumerate(score.parts):
        midi.addTrackName(track_idx, 0, part.partName)
        midi.addTempo(track_idx, 0, tempo_bpm)
        for note in part.flat.notes:
            midi.addNote(
                track=track_idx,
                channel=track_idx,
                pitch=note.pitch.midi,
                time=note.offset,
                duration=note.quarterLength,
                volume=note.volume.velocity or 80,
            )

    midi_path = Path(f"/tmp/clipcannon_midi_{uuid4().hex}.mid")
    with open(midi_path, "wb") as f:
        midi.writeFile(f)

    return midi_path


def render_midi_to_wav(midi_path: Path, soundfont_path: Path) -> Path:
    """Render MIDI file to 44.1kHz stereo WAV using FluidSynth."""
    import fluidsynth

    fs = fluidsynth.Synth(samplerate=44100.0)
    sfid = fs.sfload(str(soundfont_path))
    fs.program_select(0, sfid, 0, 0)

    wav_path = midi_path.with_suffix(".wav")
    # FluidSynth renders MIDI to audio buffer
    fs.midi_player_add(str(midi_path))
    fs.midi_player_play()
    # ... write rendered buffer to WAV ...

    fs.delete()
    return wav_path
```

---

## 4. Tier 3: Programmatic DSP Sound Effects

### Design

All sound effects are generated mathematically using numpy and scipy.signal. Zero external audio files are needed. Every effect is generated at 44.1kHz, 16-bit, mono or stereo as specified.

### Available Effects

| SFX Type | Method | Duration | Parameters |
|----------|--------|----------|------------|
| `whoosh` | Logarithmic frequency chirp + exponential decay | 0.3-1.0s | `sweep_hz_start`, `sweep_hz_end`, `decay_rate` |
| `riser` | Ascending chirp + increasing amplitude | 1.0-3.0s | `start_hz`, `end_hz`, `method` (linear/exponential) |
| `downer` | Descending chirp + decreasing amplitude | 0.5-2.0s | `start_hz`, `end_hz`, `decay_rate` |
| `impact` | Noise burst + fast exponential decay | 0.1-0.5s | `decay_rate`, `noise_type` (white/pink) |
| `chime` | Harmonic sine tones + decay | 0.3-1.0s | `base_freq_hz`, `harmonics`, `decay_rate` |
| `tick` | Short click | 0.05-0.1s | `freq_hz`, `attack_ms` |
| `bass_drop` | Low-frequency sine sweep + resonance | 0.5-2.0s | `start_hz`, `end_hz`, `resonance` |
| `shimmer` | High-frequency filtered noise + slow attack | 1.0-3.0s | `filter_hz`, `attack_ms`, `decay_ms` |
| `stinger` | Impact + riser combined | 0.5-1.5s | `impact_params`, `riser_params`, `mix_ratio` |

### Implementation

```python
import numpy as np
from scipy import signal
import struct
import wave

SAMPLE_RATE = 44100

def generate_whoosh(
    duration_s: float = 0.5,
    sweep_hz_start: float = 200.0,
    sweep_hz_end: float = 8000.0,
    decay_rate: float = 3.0,
) -> np.ndarray:
    """Generate a whoosh/swoosh sound effect."""
    n_samples = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n_samples, dtype=np.float64)

    # Logarithmic frequency chirp
    chirp = signal.chirp(t, f0=sweep_hz_start, f1=sweep_hz_end, t1=duration_s, method="logarithmic")

    # Exponential decay envelope
    envelope = np.exp(-decay_rate * t / duration_s)

    # Apply envelope
    audio = chirp * envelope

    # Normalize to [-1, 1]
    audio = audio / np.max(np.abs(audio))
    return audio


def generate_impact(
    duration_s: float = 0.2,
    decay_rate: float = 8.0,
    noise_type: str = "white",
) -> np.ndarray:
    """Generate an impact/hit sound effect."""
    n_samples = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n_samples, dtype=np.float64)

    # Noise burst
    if noise_type == "pink":
        noise = _generate_pink_noise(n_samples)
    else:
        noise = np.random.randn(n_samples)

    # Very fast exponential decay
    envelope = np.exp(-decay_rate * t / duration_s)

    audio = noise * envelope
    audio = audio / np.max(np.abs(audio))
    return audio


def generate_chime(
    duration_s: float = 0.5,
    base_freq_hz: float = 880.0,
    harmonics: int = 4,
    decay_rate: float = 5.0,
) -> np.ndarray:
    """Generate a notification chime sound effect."""
    n_samples = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n_samples, dtype=np.float64)

    audio = np.zeros(n_samples, dtype=np.float64)

    for h in range(1, harmonics + 1):
        freq = base_freq_hz * h
        amplitude = 1.0 / h  # Harmonic falloff
        tone = amplitude * np.sin(2 * np.pi * freq * t)
        audio += tone

    # Decay envelope
    envelope = np.exp(-decay_rate * t / duration_s)
    audio = audio * envelope
    audio = audio / np.max(np.abs(audio))
    return audio


def generate_riser(
    duration_s: float = 2.0,
    start_hz: float = 100.0,
    end_hz: float = 4000.0,
    method: str = "logarithmic",
) -> np.ndarray:
    """Generate a riser (ascending tension builder)."""
    n_samples = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n_samples, dtype=np.float64)

    chirp = signal.chirp(t, f0=start_hz, f1=end_hz, t1=duration_s, method=method)

    # Increasing amplitude envelope
    envelope = t / duration_s
    audio = chirp * envelope
    audio = audio / np.max(np.abs(audio))
    return audio


def save_wav(audio: np.ndarray, path: str, sample_rate: int = SAMPLE_RATE) -> None:
    """Save a numpy audio array as a 16-bit WAV file."""
    audio_16bit = np.int16(audio * 32767)
    with wave.open(path, "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio_16bit.tobytes())
```

### Performance

All DSP effects generate in <100ms on any modern CPU. Typical timings:

| Effect | Duration Generated | Generation Time |
|--------|-------------------|-----------------|
| `whoosh` (0.5s) | 22,050 samples | ~2ms |
| `riser` (2.0s) | 88,200 samples | ~5ms |
| `impact` (0.2s) | 8,820 samples | ~1ms |
| `chime` (0.5s) | 22,050 samples | ~3ms |
| `stinger` (1.0s) | 44,100 samples | ~4ms |

---

## 5. Audio Mixing Pipeline

### Layer Order (bottom to top)

```
Layer 4: Jingles / stingers (intro/outro)
Layer 3: Sound effects (at transition points)
Layer 2: Source audio (speech from original video)
Layer 1: Background music bed (ducked under speech)
```

Higher layers take priority. The background music bed is dynamically ducked whenever speech is detected in the source audio.

### Speech-Aware Ducking Algorithm

```
1. Load source audio (speech track)
2. Run Silero VAD to detect speech segments
   (reuse VAD model from Phase 1 understanding pipeline)
3. For each speech segment [start_ms, end_ms]:
   a. Begin duck 200ms BEFORE speech onset (lookahead)
   b. Reduce music volume by duck_level_db (default: -6 dB)
   c. Apply 50ms cosine ramp on the leading edge (no click)
   d. Hold ducked level for duration of speech
   e. Begin release 300ms AFTER speech ends
   f. Apply 50ms cosine ramp on the trailing edge
4. Mix all layers at their specified volumes
5. Apply loudness normalization (EBU R128, target: -16 LUFS)
6. Apply limiter (ceiling: -1 dBFS) to prevent clipping
7. Export as 44.1kHz stereo WAV
```

### Ducking Implementation

```python
import numpy as np
from pydub import AudioSegment

def apply_ducking(
    music: np.ndarray,
    speech_segments: list[tuple[float, float]],
    sample_rate: int = 44100,
    duck_level_db: float = -6.0,
    attack_ms: float = 200.0,
    release_ms: float = 300.0,
    ramp_ms: float = 50.0,
) -> np.ndarray:
    """Apply speech-aware ducking to a music track.

    Args:
        music: Music audio array (float64, normalized to [-1, 1]).
        speech_segments: List of (start_s, end_s) tuples for speech regions.
        sample_rate: Audio sample rate.
        duck_level_db: Volume reduction during speech (negative dB).
        attack_ms: Start ducking this many ms before speech onset.
        release_ms: Release ducking this many ms after speech ends.
        ramp_ms: Duration of cosine ramp transitions.

    Returns:
        Ducked music array.
    """
    duck_gain = 10 ** (duck_level_db / 20.0)  # Convert dB to linear
    gain_curve = np.ones(len(music), dtype=np.float64)

    attack_samples = int(sample_rate * attack_ms / 1000)
    release_samples = int(sample_rate * release_ms / 1000)
    ramp_samples = int(sample_rate * ramp_ms / 1000)

    for start_s, end_s in speech_segments:
        # Duck region with lookahead and release
        duck_start = max(0, int(start_s * sample_rate) - attack_samples)
        duck_end = min(len(music), int(end_s * sample_rate) + release_samples)

        # Set ducked gain
        gain_curve[duck_start:duck_end] = duck_gain

        # Cosine ramp in (leading edge)
        ramp_end = min(duck_start + ramp_samples, len(music))
        ramp_length = ramp_end - duck_start
        if ramp_length > 0:
            ramp = 0.5 * (1 + np.cos(np.linspace(0, np.pi, ramp_length)))
            gain_curve[duck_start:ramp_end] = 1.0 - (1.0 - duck_gain) * (1.0 - ramp)

        # Cosine ramp out (trailing edge)
        ramp_start = max(0, duck_end - ramp_samples)
        ramp_length = duck_end - ramp_start
        if ramp_length > 0:
            ramp = 0.5 * (1 + np.cos(np.linspace(np.pi, 0, ramp_length)))
            gain_curve[ramp_start:duck_end] = 1.0 - (1.0 - duck_gain) * (1.0 - ramp)

    return music * gain_curve
```

### Final Mix and Mastering

```python
from pydub import AudioSegment
import pedalboard
import numpy as np

def mix_and_master(
    source_audio: AudioSegment,
    background_music: AudioSegment,
    sfx_layers: list[tuple[int, AudioSegment]],  # (offset_ms, audio)
    jingle: AudioSegment | None = None,
    duck_level_db: float = -6.0,
    target_lufs: float = -16.0,
) -> AudioSegment:
    """Mix all audio layers and apply mastering chain."""

    # 1. Apply ducking to background music
    speech_segments = detect_speech_segments(source_audio)
    ducked_music = apply_ducking(
        audio_to_numpy(background_music),
        speech_segments,
        duck_level_db=duck_level_db,
    )
    ducked_music_seg = numpy_to_audio(ducked_music)

    # 2. Layer: music bed
    final = ducked_music_seg

    # 3. Overlay source audio
    final = final.overlay(source_audio)

    # 4. Overlay SFX at specified positions
    for offset_ms, sfx in sfx_layers:
        final = final.overlay(sfx, position=offset_ms)

    # 5. Overlay jingle (intro/outro)
    if jingle:
        final = final.overlay(jingle, position=0)

    # 6. Mastering chain via pedalboard
    samples = audio_to_numpy(final)
    board = pedalboard.Pedalboard([
        pedalboard.Compressor(threshold_db=-10, ratio=4),
        pedalboard.Limiter(threshold_db=-1),
    ])
    mastered = board(samples, sample_rate=44100)

    # 7. EBU R128 loudness normalization
    mastered = normalize_lufs(mastered, target_lufs=target_lufs)

    return numpy_to_audio(mastered)
```

---

## 6. Audio EDL Specification

The AI writes audio specifications into the EDL `audio{}` object. This declarative format is consumed by the audio rendering pipeline.

### Full Schema

```json
{
  "audio": {
    "source_audio": true,
    "source_volume_db": 0,
    "background_music": {
      "source": "ace_step | midi | none",
      "prompt": "string (for ace_step)",
      "preset": "string (for midi)",
      "duration_ms": 30000,
      "volume_db": -18,
      "fade_in_ms": 2000,
      "fade_out_ms": 3000,
      "seed": 42,
      "tempo_bpm": 120,
      "key": "C",
      "instruments": ["piano", "strings"]
    },
    "sound_effects": [
      {
        "type": "whoosh | riser | downer | impact | chime | tick | bass_drop | shimmer | stinger",
        "source": "programmatic_dsp",
        "trigger_ms": 0,
        "duration_ms": 500,
        "volume_db": -12,
        "params": {
          "sweep_hz_start": 200,
          "sweep_hz_end": 8000,
          "decay_rate": 3.0
        }
      }
    ],
    "jingle": {
      "source": "ace_step | midi | asset",
      "position": "intro | outro | both",
      "duration_ms": 5000,
      "volume_db": -6,
      "fade_in_ms": 500,
      "fade_out_ms": 1000
    },
    "ducking": {
      "enabled": true,
      "duck_level_db": -6,
      "attack_ms": 200,
      "release_ms": 300,
      "ramp_ms": 50
    },
    "mastering": {
      "target_lufs": -16,
      "compressor_threshold_db": -10,
      "compressor_ratio": 4,
      "limiter_ceiling_db": -1
    }
  }
}
```

### Example: Podcast with Background Music

```json
{
  "audio": {
    "source_audio": true,
    "source_volume_db": 0,
    "background_music": {
      "source": "midi",
      "preset": "ambient_pad",
      "duration_ms": 120000,
      "volume_db": -20,
      "fade_in_ms": 3000,
      "fade_out_ms": 5000,
      "tempo_bpm": 70,
      "key": "C"
    },
    "sound_effects": [],
    "ducking": {
      "enabled": true,
      "duck_level_db": -8,
      "attack_ms": 200,
      "release_ms": 500
    }
  }
}
```

### Example: TikTok Highlight Reel

```json
{
  "audio": {
    "source_audio": true,
    "source_volume_db": -3,
    "background_music": {
      "source": "ace_step",
      "prompt": "upbeat electronic, 128 BPM, energetic, catchy drop",
      "duration_ms": 30000,
      "volume_db": -12,
      "fade_in_ms": 500,
      "fade_out_ms": 2000,
      "seed": 42
    },
    "sound_effects": [
      {
        "type": "whoosh",
        "source": "programmatic_dsp",
        "trigger_ms": 0,
        "duration_ms": 400,
        "volume_db": -10,
        "params": {"sweep_hz_start": 300, "sweep_hz_end": 6000, "decay_rate": 4.0}
      },
      {
        "type": "impact",
        "source": "programmatic_dsp",
        "trigger_ms": 8500,
        "duration_ms": 200,
        "volume_db": -8,
        "params": {"decay_rate": 10.0, "noise_type": "white"}
      },
      {
        "type": "riser",
        "source": "programmatic_dsp",
        "trigger_ms": 25000,
        "duration_ms": 3000,
        "volume_db": -14,
        "params": {"start_hz": 100, "end_hz": 5000, "method": "logarithmic"}
      }
    ],
    "ducking": {
      "enabled": true,
      "duck_level_db": -6,
      "attack_ms": 150,
      "release_ms": 200
    }
  }
}
```

---

## 7. MCP Tools

### clipcannon_generate_music

Generate background music using ACE-Step AI or MIDI composition.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | Yes | Project identifier |
| `edit_id` | string | Yes | Edit to attach audio to |
| `prompt` | string | Yes (ace_step) | Text description of desired music |
| `duration_s` | float | Yes | Duration in seconds |
| `tier` | string | No | `ace_step` or `midi` (default: auto-select based on GPU availability) |
| `seed` | int | No | Random seed for reproducibility |
| `volume_db` | float | No | Volume level in dB (default: -18) |

**Returns:**

```json
{
  "audio_asset_id": "aud_abc123",
  "file_path": "/projects/proj_1/audio/music_abc123.wav",
  "duration_ms": 30000,
  "model_used": "ace_step_v15_turbo_rl",
  "seed": 42,
  "provenance": {
    "generator": "ace_step",
    "prompt_hash": "sha256:...",
    "model_version": "v1.5-turbo-rl"
  }
}
```

### clipcannon_compose_midi

Compose music using MIDI with theory-correct progressions and FluidSynth rendering.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | Yes | Project identifier |
| `edit_id` | string | Yes | Edit to attach audio to |
| `preset` | string | Yes | Composition preset name |
| `duration_s` | float | Yes | Duration in seconds |
| `tempo_bpm` | int | No | Tempo in BPM (default: from preset) |
| `key` | string | No | Musical key (default: "C") |
| `instruments` | list[string] | No | Override preset instruments |

**Returns:**

```json
{
  "audio_asset_id": "aud_def456",
  "file_path": "/projects/proj_1/audio/midi_def456.wav",
  "duration_ms": 60000,
  "midi_path": "/projects/proj_1/audio/midi_def456.mid",
  "preset": "ambient_pad",
  "tempo_bpm": 70,
  "key": "C"
}
```

### clipcannon_generate_sfx

Generate a programmatic DSP sound effect.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | Yes | Project identifier |
| `edit_id` | string | Yes | Edit to attach SFX to |
| `sfx_type` | string | Yes | Effect type (whoosh, riser, impact, etc.) |
| `duration_ms` | int | No | Duration in milliseconds (default: type-dependent) |
| `params` | object | No | Type-specific parameters |

**Returns:**

```json
{
  "audio_asset_id": "aud_ghi789",
  "file_path": "/projects/proj_1/audio/sfx_ghi789.wav",
  "duration_ms": 500,
  "sfx_type": "whoosh",
  "params_used": {
    "sweep_hz_start": 200,
    "sweep_hz_end": 8000,
    "decay_rate": 3.0
  }
}
```

---

## 8. Implementation Files

| File | Responsibility |
|------|---------------|
| `src/clipcannon/audio/__init__.py` | Package init, public API exports |
| `src/clipcannon/audio/music_gen.py` | ACE-Step v1.5 integration, prompt construction, VRAM scheduling |
| `src/clipcannon/audio/midi_compose.py` | MIDI composition with music21, chord progressions, melody generation |
| `src/clipcannon/audio/midi_render.py` | FluidSynth MIDI-to-WAV rendering, SoundFont management |
| `src/clipcannon/audio/sfx.py` | DSP sound effect generation (all 9 effect types) |
| `src/clipcannon/audio/mixer.py` | Audio mixing pipeline with speech-aware ducking |
| `src/clipcannon/audio/effects.py` | pedalboard audio effects, EBU R128 normalization, mastering chain |
| `src/clipcannon/audio/schemas.py` | Pydantic models for audio EDL schema validation |
| `src/clipcannon/tools/audio.py` | MCP tool definitions (generate_music, compose_midi, generate_sfx) |

### Dependency Summary

| Dependency | Version | License | Purpose |
|------------|---------|---------|---------|
| ace-step | >=1.5 | MIT | AI music generation |
| midiutil | >=1.2.1 | MIT | MIDI file writing |
| music21 | >=9.1 | BSD | Music theory engine |
| pyfluidsynth | >=1.3 | LGPL-2.1 | MIDI-to-WAV rendering |
| pydub | >=0.25.1 | MIT | Audio segment manipulation |
| pedalboard | >=0.9 | GPL-3.0 | Audio effects processing |
| numpy | >=1.24 | BSD | DSP array operations |
| scipy | >=1.10 | BSD | Signal processing (chirps, filters) |
| silero-vad | >=5.1 | MIT | Voice activity detection (reused from Phase 1) |

---

## 9. Testing Strategy

### Unit Tests

| Test Area | What Is Verified |
|-----------|-----------------|
| DSP SFX generators | Valid WAV output, correct sample count matches requested duration, no NaN/Inf values, peak amplitude within [-1, 1] |
| SFX click/pop detection | Generated audio has no discontinuities (max sample-to-sample delta < threshold) |
| MIDI composition | Valid MIDI file (parseable by music21), correct note count per bar, notes within instrument range |
| MIDI rendering | FluidSynth produces non-silent WAV output with correct sample rate |
| Ducking algorithm | Volume correctly reduced during speech segments, ramps are smooth (no clicks), gain returns to 1.0 outside speech regions |
| Audio EDL schema | Pydantic validation accepts valid schemas, rejects invalid ones |
| Prompt construction | Music prompts include mood, tempo, and platform signals |

### Integration Tests

| Test | Steps |
|------|-------|
| Full pipeline (ACE-Step) | Generate 10s of music via ACE-Step, generate whoosh SFX, mix with dummy speech audio, verify output WAV is valid and non-silent |
| Full pipeline (MIDI) | Compose 30s MIDI ambient pad, render to WAV, apply ducking with speech segments, verify ducked regions have lower RMS |
| VRAM fallback | Mock GPU with <4GB VRAM, verify system falls back to MIDI tier automatically |
| MCP tool roundtrip | Call `clipcannon_generate_music` via MCP, verify returned asset exists on disk and has correct metadata |

### Quality Tests (Manual Verification)

- Listen to ACE-Step output for musical coherence and prompt adherence.
- Listen to MIDI compositions for correct chord voicings and instrument balance.
- Listen to mixed output for smooth ducking transitions and proper layer balance.
- Verify no audible clicks, pops, or artifacts in any generated audio.

### Test File Locations

| File | Coverage |
|------|----------|
| `tests/unit/audio/test_sfx.py` | All 9 DSP effect generators |
| `tests/unit/audio/test_midi_compose.py` | MIDI composition logic |
| `tests/unit/audio/test_midi_render.py` | FluidSynth rendering |
| `tests/unit/audio/test_mixer.py` | Ducking algorithm and layer mixing |
| `tests/unit/audio/test_schemas.py` | Audio EDL Pydantic models |
| `tests/integration/audio/test_audio_pipeline.py` | End-to-end audio generation and mixing |
| `tests/integration/audio/test_mcp_audio_tools.py` | MCP tool integration |
