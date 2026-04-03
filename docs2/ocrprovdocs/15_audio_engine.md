# Audio Engine

Source: `src/clipcannon/audio/`

All outputs: WAV at 44100 Hz (`SAMPLE_RATE`).

```
Tier 1 (AI):   generate_music()  [ACE-Step GPU]
Tier 2 (Synth): compose_midi() + render_midi_to_wav()
Tier 3 (DSP):  generate_sfx()   [9 types, no GPU]
Cleanup:        cleanup_audio()  [noise/norm/trim/EQ]
Effects:        apply_effects()  [5 chains]
Mixing:         mix_audio()      [speech-aware ducking]
```

---

## 1. AI Music Generation (`music_gen.py`)

`async generate_music(prompt, duration_s, output_path, seed=None, guidance_scale=7.5, gpu_device="cuda:0") -> MusicResult`

- Model: ACE-Step v1.5 turbo RL diffusion
- GPU: 4+ GB VRAM required, `cpu_offload` if < 8 GB
- Random seed generated if not provided (for reproducibility)
- Validates output exists and duration within 10% of requested
- Cleans GPU memory after generation

**MusicResult**: `file_path`, `duration_ms`, `sample_rate`, `seed`, `model_used` ("ace-step-v15-turbo-rl"), `prompt`

---

## 2. MIDI Composition (`midi_compose.py`, `midi_render.py`)

### Presets (6)

| Preset | BPM | Key | Drums | Dynamics |
|---|---|---|---|---|
| ambient_pad | 70 | C | No | 40-70 |
| upbeat_pop | 128 | C | Yes | 70-100 |
| corporate | 100 | C | No | 55-80 |
| dramatic | 90 | A | Yes | 60-110 |
| minimal_piano | 80 | C | No | 45-75 |
| intro_jingle | 120 | C | Yes | 70-100 |

Chord progressions: Cmaj7-Am7-Fmaj7-G7 (ambient), C-G-Am-F (pop/piano), C-F-Am-G (corporate), Am-F-C-G (dramatic), C-F-G-C (jingle).

`compose_midi(preset, duration_s, output_path, tempo_bpm=None, key=None) -> MidiResult`: Multi-track MIDI (chords, melody, optional bass, optional drums on channel 9) via MIDIUtil.

`async render_midi_to_wav(midi_path, output_path, soundfont_path=None) -> Path`: FluidSynth synthesis. Searches 5 common SoundFont locations, falls back to `~/.clipcannon/models/GeneralUser_GS.sf2`.

**MidiResult**: `midi_path`, `duration_ms`, `tempo_bpm`, `key`, `preset`

---

## 3. DSP Sound Effects (`sfx.py`)

`generate_sfx(sfx_type, output_path, duration_ms=500, params=None) -> SfxResult`

| Type | Algorithm |
|---|---|
| whoosh | Log chirp 200->8000 Hz + exp decay |
| riser | Linear chirp 100->4000 Hz + crescendo |
| downer | Linear chirp 4000->100 Hz + decrescendo |
| impact | White noise burst + fast decay |
| chime | 3 harmonic sines (880 Hz base) + decay |
| tick | 1000 Hz sine + sharp attack/decay |
| bass_drop | 200->40 Hz sweep + sub-harmonic |
| shimmer | HP filtered noise + slow attack/decay |
| stinger | Impact (first half) + riser (second half) |

Processing: dispatch -> 50-sample zero-crossing fade in/out -> normalize 80% -> 16-bit WAV. Pure numpy/scipy, no GPU.

**SfxResult**: `file_path`, `duration_ms`, `sample_rate`, `sfx_type`

---

## 4. Audio Effects (`effects.py`)

`apply_effects(audio_path, output_path, effects, params=None) -> Path`

Uses Spotify `pedalboard`. Effects chain applied in order:

| Effect | Defaults |
|---|---|
| reverb | room_size=0.5, damping=0.5, wet=0.3, dry=0.7 |
| compression | threshold=-20dB, ratio=4.0, attack=10ms, release=100ms |
| eq_low_cut | cutoff_hz=80 |
| eq_high_cut | cutoff_hz=16000 |
| limiter | threshold=-1dB, release=100ms |

---

## 5. Audio Mixing (`mixer.py`)

`async mix_audio(source_audio_path, output_path, background_music_path=None, sfx_entries=None, music_volume_db=-18.0, duck_under_speech=True, duck_level_db=-6.0, duck_attack_ms=200, duck_release_ms=300, normalize=True) -> MixResult`

Layers (bottom to top): background music (looped/trimmed) -> source speech -> SFX (at offsets).

**Speech-aware ducking**: RMS energy analysis in 50ms windows (threshold 300.0) -> identify speech regions -> reduce music by `duck_level_db` (-6 dB default) with 200ms attack / 300ms release ramps.

**Normalization**: Peak normalize to -1 dBFS via pydub.

**MixResult**: `file_path`, `duration_ms`, `sample_rate`, `layers_mixed`

---

## 6. Audio Cleanup (`cleanup.py`)

`cleanup_audio(input_path, output_path, operations=None) -> CleanupResult`

Operations (default: all): `noise_reduction` (spectral gating), `normalize` (peak -1 dBFS), `silence_trim` (leading/trailing), `eq_adjust` (low/high cut for speech clarity). Each independently selectable.

**CleanupResult**: `file_path`, `duration_ms`, `sample_rate`, `operations_applied`

---

## 7. Database Storage

`audio_assets` table: `asset_id`, `edit_id`, `project_id`, `type` (music/sfx/voiceover), `file_path`, `duration_ms`, `sample_rate`, `model_used`, `generation_params` (JSON), `seed`, `volume_db`. Files stored in `{project_dir}/edits/{edit_id}/audio/`.
