# 15 - Audio Engine

> Current-state documentation of the Phase 2 audio generation subsystem as implemented in `src/clipcannon/audio/`.

## Architecture Overview

The audio engine provides a three-tier audio generation system with mixing and effects processing:

```
┌─────────────────────────────────────────────────────────┐
│                    Audio Module Stack                    │
├─────────────────────────────────────────────────────────┤
│  Tier 1 (AI):     generate_music() [ACE-Step GPU]       │
│  Tier 2 (Synth):  compose_midi() + render_midi_to_wav() │
│  Tier 3 (DSP):    generate_sfx() [9 effect types]       │
├─────────────────────────────────────────────────────────┤
│  Cleanup:         cleanup_audio() [noise/norm/trim/EQ]  │
│  Processing:      apply_effects() [5 effects chains]    │
│  Mixing:          mix_audio() [speech-aware ducking]     │
├─────────────────────────────────────────────────────────┤
│  MCP Integration: audio.py [4 tools + database storage] │
└─────────────────────────────────────────────────────────┘
```

All audio outputs use WAV format at 44100 Hz sample rate (`SAMPLE_RATE` constant).

---

## 1. AI Music Generation (Tier 1)

**Source:** `src/clipcannon/audio/music_gen.py`

### MusicResult Dataclass

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `Path` | Path to generated WAV file |
| `duration_ms` | `int` | Actual duration in ms |
| `sample_rate` | `int` | Sample rate (44100) |
| `seed` | `int` | Random seed used |
| `model_used` | `str` | `"ace-step-v15-turbo-rl"` |
| `prompt` | `str` | Text prompt used |

### Generation

`async generate_music(prompt, duration_s, output_path, seed=None, guidance_scale=7.5, gpu_device="cuda:0") -> MusicResult`

- **Model**: ACE-Step v1.5 turbo RL diffusion model
- **Requirements**: GPU with 4+ GB VRAM
- **Memory management**: Uses `cpu_offload` if VRAM < 8 GB
- Generates random seed if not provided (for reproducibility logging)
- Validates output file exists and duration is within 10% of requested
- Cleans up GPU memory (`torch.cuda.empty_cache()`) after generation

---

## 2. MIDI Composition (Tier 2)

**Source:** `src/clipcannon/audio/midi_compose.py`, `midi_render.py`

### MidiResult Dataclass

| Field | Type | Description |
|-------|------|-------------|
| `midi_path` | `Path` | Path to MIDI file |
| `duration_ms` | `int` | Duration in ms |
| `tempo_bpm` | `int` | Tempo used |
| `key` | `str` | Musical key |
| `preset` | `str` | Preset name |

### Presets (6)

| Preset | Tempo | Key | Drums | Instruments | Dynamics |
|--------|-------|-----|-------|-------------|----------|
| `ambient_pad` | 70 BPM | C | No | Pad, Strings | 40-70 (soft) |
| `upbeat_pop` | 128 BPM | C | Yes | Piano, Bass | 70-100 (high) |
| `corporate` | 100 BPM | C | No | Piano, Strings | 55-80 (mid) |
| `dramatic` | 90 BPM | A | Yes | Strings, Brass | 60-110 (wide) |
| `minimal_piano` | 80 BPM | C | No | Piano only | 45-75 (soft) |
| `intro_jingle` | 120 BPM | C | Yes | Piano, Strings, Bass | 70-100 (high) |

### Chord Progressions

| Name | Chords | Used By |
|------|--------|---------|
| C Major 7th Cycle | Cmaj7-Am7-Fmaj7-G7 | ambient_pad |
| Pop Canon | C-G-Am-F | upbeat_pop, minimal_piano |
| Corporate | C-F-Am-G | corporate |
| Dramatic | Am-F-C-G | dramatic |
| Jingle | C-F-G-C | intro_jingle |

### Composition Flow

`compose_midi(preset, duration_s, output_path, tempo_bpm=None, key=None) -> MidiResult`:

1. Loads preset configuration (or applies overrides)
2. Creates multi-track MIDI:
   - Track 0: Chord progression (piano/pad/strings)
   - Track 1: Melody (scale degree patterns)
   - Track 2: Bass (optional, one octave below chord roots)
   - Track 3: Drums (optional, kick/snare/hihat pattern on channel 9)
3. Applies velocity dynamics within preset range
4. Writes MIDI file via MIDIUtil

### MIDI Rendering

`async render_midi_to_wav(midi_path, output_path, soundfont_path=None, sample_rate=44100) -> Path`:

- Uses FluidSynth to synthesize MIDI with SoundFont instruments
- Searches 5 common SoundFont locations (FluidR3_GM, GeneralUser_GS)
- Falls back to `~/.clipcannon/models/GeneralUser_GS.sf2` if system fonts unavailable

---

## 3. DSP Sound Effects (Tier 3)

**Source:** `src/clipcannon/audio/sfx.py`

### SfxResult Dataclass

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `Path` | Path to WAV file |
| `duration_ms` | `int` | Duration in ms |
| `sample_rate` | `int` | Sample rate (44100) |
| `sfx_type` | `str` | Effect type name |

### Supported SFX Types (9)

| Type | Algorithm | Description |
|------|-----------|-------------|
| `whoosh` | Logarithmic frequency chirp (200->8000 Hz) + exponential decay | Swoosh/pass-by sound |
| `riser` | Linear chirp (100->4000 Hz) + crescendo envelope | Building tension |
| `downer` | Linear chirp (4000->100 Hz) + decrescendo envelope | Deflating/falling |
| `impact` | White noise burst + fast decay | Hit/punch emphasis |
| `chime` | 3 harmonically-related sines (880 Hz base) + decay | Notification/alert |
| `tick` | Single 1000 Hz sine + sharp attack/decay | Click/metronome |
| `bass_drop` | 200->40 Hz sweep + sub-harmonic resonance | Low-end emphasis |
| `shimmer` | High-pass filtered noise + slow attack/decay | Sparkle/magic |
| `stinger` | Combined impact (first half) + riser (second half) | Dramatic reveal |

### Generation

`generate_sfx(sfx_type, output_path, duration_ms=500, params=None) -> SfxResult`:

1. Dispatches to type-specific generator function
2. Applies zero-crossing fade-in/fade-out (50 samples) to prevent clicks
3. Normalizes to 80% of max amplitude
4. Converts to 16-bit integer WAV
5. Saves at 44100 Hz via scipy

All synthesis is pure numpy/scipy -- no ML model, no GPU required.

---

## 4. Audio Effects Processing

**Source:** `src/clipcannon/audio/effects.py`

### Supported Effects (5)

| Effect | Default Parameters | Description |
|--------|-------------------|-------------|
| `reverb` | room_size=0.5, damping=0.5, wet=0.3, dry=0.7, width=1.0 | Room reverb simulation |
| `compression` | threshold=-20dB, ratio=4.0, attack=10ms, release=100ms | Dynamic range compression |
| `eq_low_cut` | cutoff_hz=80 | High-pass filter (removes low rumble) |
| `eq_high_cut` | cutoff_hz=16000 | Low-pass filter (removes hiss) |
| `limiter` | threshold=-1dB, release=100ms | Peak limiting |

### Processing

`apply_effects(audio_path, output_path, effects, params=None) -> Path`:

- Uses Spotify's `pedalboard` library
- Builds effects chain in order specified
- Merges user parameters with defaults
- Processes audio and saves WAV output

---

## 5. Audio Mixing

**Source:** `src/clipcannon/audio/mixer.py`

### MixResult Dataclass

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `Path` | Path to mixed WAV |
| `duration_ms` | `int` | Duration in ms |
| `sample_rate` | `int` | Sample rate |
| `layers_mixed` | `int` | Number of audio layers |

### Mixing Pipeline

`async mix_audio(source_audio_path, output_path, background_music_path=None, sfx_entries=None, music_volume_db=-18.0, duck_under_speech=True, duck_level_db=-6.0, duck_attack_ms=200, duck_release_ms=300, normalize=True, sample_rate=44100) -> MixResult`

**Layer order** (bottom to top):
1. Background music (looped/trimmed to match source duration)
2. Source speech audio
3. Sound effects (at specified offsets)

### Speech-Aware Ducking

`_detect_speech_regions(audio_segment, window_ms=50, threshold_rms=300.0) -> list[tuple[int, int]]`:
- Analyzes audio in 50ms windows using RMS energy
- Windows exceeding RMS threshold (300.0) are marked as speech
- Adjacent windows merged into contiguous regions

`_apply_ducking(music_segment, speech_regions, duck_level_db, attack_ms, release_ms)`:
- Reduces music volume by `duck_level_db` (default -6 dB) during speech regions
- Applies attack ramp (200ms) and release ramp (300ms) for smooth transitions

### Peak Normalization

When `normalize=True` (default), the final mix is peak-normalized to -1 dBFS using pydub's `normalize()`.

---

## 6. Audio Cleanup

**Source:** `src/clipcannon/audio/cleanup.py`

### CleanupResult Dataclass

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `Path` | Path to cleaned WAV file |
| `duration_ms` | `int` | Duration in ms |
| `sample_rate` | `int` | Sample rate |
| `operations_applied` | `list[str]` | List of cleanup operations that were applied |

### Supported Operations

`SUPPORTED_CLEANUP_OPS` defines the available cleanup operations:

| Operation | Description |
|-----------|-------------|
| `noise_reduction` | Reduces background noise using spectral gating |
| `normalize` | Peak normalization to -1 dBFS |
| `silence_trim` | Removes leading and trailing silence |
| `eq_adjust` | Applies EQ adjustments (low cut, high cut) for speech clarity |

### Processing

`cleanup_audio(input_path, output_path, operations=None) -> CleanupResult`:

- Applies specified operations in order (defaults to all operations)
- Each operation is independently applied and can be selected individually
- Output is WAV at the source sample rate

---

## 7. Database Storage

All generated audio assets are stored in the `audio_assets` table with:
- `asset_id`: unique identifier
- `asset_type`: "music", "sfx", or "voiceover"
- `file_path`: path to the WAV file
- `model_used`: "ace-step-v15-turbo-rl", "midiutil", "midiutil+fluidsynth", or "dsp"
- `generation_params_json`: JSON-encoded parameters for reproducibility
- `seed`: random seed (for AI-generated music)
- `volume_db`: volume adjustment level

Audio files are stored in `{project_dir}/edits/{edit_id}/audio/`.
