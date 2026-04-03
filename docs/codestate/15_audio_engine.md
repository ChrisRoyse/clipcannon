# Audio Engine

Source: `src/clipcannon/audio/`

All outputs: WAV at 44100 Hz (`SAMPLE_RATE`), except ACE-Step which outputs 48kHz stereo.

```
Tier 1A (AI):    generate_music()            [ACE-Step v1.5 GPU]
Tier 1B (AI):    generate_music_musicgen()   [MusicGen GPU]
Tier 2 (Synth):  compose_midi() + render_midi_to_wav()
                  compose_midi_sectioned()    [multi-section]
                  plan_midi_from_keywords()   [AI-enhanced planning]
Tier 3 (DSP):    generate_sfx()              [13 types, no GPU]
Planner:         MusicPlanner.plan_for_edit() [video-aware]
Cleanup:         cleanup_audio()             [noise/norm/trim/EQ]
Effects:         apply_effects()             [5 chains]
Mixing:          mix_audio()                 [speech-aware ducking]
```

---

## 1. AI Music Generation -- ACE-Step v1.5 (`music_gen.py`)

`async generate_music(prompt, duration_s, output_path, seed=None, guidance_scale=15.0, gpu_device="cuda:0", tags="", lyrics="", infer_steps=100) -> MusicResult`

- Model: ACE-Step v1.5 hybrid LM+DiT architecture
- GPU: 4+ GB VRAM minimum, `cpu_offload` if < 4 GB
- Output: 48 kHz stereo WAV, up to 600 seconds
- Random seed generated if not provided (for reproducibility)
- Validates output exists and duration within 10% of requested
- Cleans GPU memory after generation
- License: Apache 2.0 (outputs are royalty-free)

**MusicResult**: `file_path`, `duration_ms`, `sample_rate`, `seed`, `model_used` ("ACE-Step-v1.5"), `prompt`

---

## 2. AI Music Generation -- MusicGen (`musicgen.py`)

`async generate_music_musicgen(prompt, duration_s, output_path, model_size="medium", seed=None, gpu_device="cuda:0") -> MusicResult`

- Model: Meta AudioCraft MusicGen (small/medium/large)
- GPU: 6-8 GB VRAM for medium
- Output: Resampled from 32kHz to 44100Hz mono WAV, up to 120 seconds
- Windowed generation for >30s: 30s chunks with 5s overlap, linear crossfade
- Validates output and duration
- License: MIT code, CC-BY-NC model weights (outputs unrestricted)

---

## 3. MIDI Composition (`midi_compose.py`, `midi_render.py`)

### Presets (12)

| Preset | BPM | Key | Drums | Dynamics |
|---|---|---|---|---|
| ambient_pad | 70 | C | No | 40-70 |
| upbeat_pop | 128 | C | Yes | 70-100 |
| corporate | 100 | C | No | 55-80 |
| dramatic | 90 | C | Yes | 60-110 |
| minimal_piano | 80 | C | No | 45-75 |
| intro_jingle | 120 | C | Yes | 70-100 |
| lofi_chill | 75 | C | No | 35-60 |
| cinematic_epic | 95 | C | Yes | 50-120 |
| tech_corporate | 110 | C | No | 60-85 |
| acoustic_folk | 105 | C | No | 50-80 |
| synth_wave | 118 | C | Yes | 65-95 |
| jazz_smooth | 112 | C | No | 55-85 |

`compose_midi(preset, duration_s, output_path, tempo_bpm=None, key=None) -> MidiResult`: Multi-track MIDI via MIDIUtil.

`compose_midi_sectioned(plan, output_path) -> MidiResult`: Multi-section composition with intro/verse/chorus/bridge/outro, each with independent dynamics.

`async render_midi_to_wav(midi_path, output_path, soundfont_path=None, sample_rate=44100) -> Path`: FluidSynth synthesis. Searches 7 default SoundFont locations including system paths and `~/.clipcannon/models/GeneralUser_GS.sf2`. Also called automatically during render when audio assets contain MIDI files (compose_music outputs .mid).

---

## 4. AI-Enhanced MIDI Planning (`midi_ai.py`)

`plan_midi_from_keywords(description) -> MidiPlan`: Maps natural language keywords to MIDI parameters (preset, tempo, key, energy, sections). 8 keyword categories.

`async plan_midi_from_prompt(description) -> MidiPlan`: Uses local Qwen3-8B LLM to generate structured MIDI parameters. Falls back to keyword planning if LLM unavailable.

**MidiPlan**: `tempo_bpm`, `key`, `time_sig`, `preset`, `energy`, `sections[]`
**MidiSection**: `name`, `bars`, `dynamics`

---

## 5. Video-Aware Music Planner (`music_planner.py`)

`MusicPlanner.plan_for_edit(db_path, project_id, edit_id) -> MusicBrief`

Reads video analysis data to auto-generate music parameters:
1. Edit segments -> time range and duration
2. emotion_curve -> aggregate mood (joy/calm/sadness/tension/professional/inspiring)
3. pacing -> energy level (low/medium/high)
4. beat_sections -> tempo suggestion
5. transcript_segments -> speech regions for ducking

**MusicBrief**: `overall_mood`, `energy_level`, `suggested_tempo_bpm`, `suggested_key`, `suggested_preset`, `ace_step_prompt`, `edit_duration_ms`, `speech_regions`

---

## 6. DSP Sound Effects (`sfx.py`)

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
| ambient_drone | 3 layered sines + LFO modulation |
| ambient_texture | Pink noise + granular envelope gates |
| pad_swell | Harmonic series + ADSR envelope |
| nature_bed | Pink noise + bandpass filtered white noise |

Processing: dispatch -> fade in/out -> normalize 80% -> 16-bit WAV. Pure numpy/scipy, no GPU.

---

## 7. Audio Effects (`effects.py`)

`apply_effects(audio_path, output_path, effects, params=None) -> Path`

Uses Spotify `pedalboard`. 5 effects: reverb, compression, eq_low_cut, eq_high_cut, limiter.

---

## 8. Audio Mixing (`mixer.py`)

`async mix_audio(source_audio_path, output_path, ...) -> MixResult`

Speech-aware ducking: RMS energy analysis in 50ms windows -> identify speech regions -> reduce music volume with attack/release ramps. Peak normalize to -1 dBFS.

---

## 9. Audio Cleanup (`cleanup.py`)

`cleanup_audio(input_path, output_path, operations, hum_frequency=50) -> CleanupResult`

Operations: noise_reduction, de_hum, de_ess, normalize_loudness. FFmpeg audio filters.

---

## 10. MCP Tools (6 Audio Tools)

| Tool | Description |
|---|---|
| `clipcannon_generate_music` | AI music via ACE-Step or MusicGen (model param selects) |
| `clipcannon_compose_midi` | MIDI from 12 presets, rendered to WAV via FluidSynth |
| `clipcannon_generate_sfx` | 13 DSP sound effects, CPU-only, instant |
| `clipcannon_audio_cleanup` | Source audio cleanup via FFmpeg filters |
| `clipcannon_auto_music` | Video-aware automatic music from analysis data |
| `clipcannon_compose_music` | AI-planned MIDI from natural language description |

---

## 11. Database Storage

`audio_assets` table: `asset_id`, `edit_id`, `project_id`, `type` (music/sfx/voiceover/midi/cleaned), `file_path`, `duration_ms`, `sample_rate`, `model_used`, `generation_params` (JSON), `seed`, `volume_db`. Files stored in `{project_dir}/audio/`.
