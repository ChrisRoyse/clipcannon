# ClipCannon Music System Plan: AI-Generated Royalty-Free Music

**Date**: 2026-03-31
**Status**: Proposed
**Scope**: Replace royalty/licensed music with fully local AI music generation

---

## 1. Problem Statement

ClipCannon currently has a three-tier audio system:
- **Tier 1**: ACE-Step v1 (3.5B) AI music generation (GPU)
- **Tier 2**: MIDI composition from 6 presets + FluidSynth rendering (CPU)
- **Tier 3**: Programmatic DSP sound effects (CPU)

The goal is to **remove any dependency on royalty/licensed music libraries** and make all music generation happen locally via AI, producing novel audio that is royalty-free by nature. Everything must run **100% locally** -- no cloud APIs, no external services, no internet required at generation time.

---

## 2. Current State

### What Exists

| Component | File | Status |
|-----------|------|--------|
| ACE-Step v1 3.5B integration | `src/clipcannon/audio/music_gen.py` | Working, needs upgrade to v1.5 |
| MIDI composer (6 presets) | `src/clipcannon/audio/midi_compose.py` | Working, needs AI-driven expansion |
| FluidSynth MIDI renderer | `src/clipcannon/audio/midi_render.py` | Working |
| Audio mixer with ducking | `src/clipcannon/audio/mixer.py` | Working |
| Effects chain (pedalboard) | `src/clipcannon/audio/effects.py` | Working |
| DSP sound effects (9 types) | `src/clipcannon/audio/sfx.py` | Working |
| Audio cleanup | `src/clipcannon/audio/cleanup.py` | Working |
| MCP tools (4 audio tools) | `src/clipcannon/tools/audio.py` | Working |

### What Needs to Change

1. **Upgrade ACE-Step v1 -> v1.5** (1.7B LM + DiT hybrid, better quality, faster)
2. **Add MusicGen as Tier 1B** fallback (Meta's AudioCraft, MIT code license)
3. **Add AI-driven MIDI composition** using local LLM (Qwen3-8B already available)
4. **Add music style transfer / variation** capabilities
5. **Add video-aware music generation** that reads analysis data to match mood
6. **Remove any royalty music file references** from codebase
7. **New MCP tools** for the expanded capabilities

---

## 3. Architecture

### 3.1 New Four-Tier Music System

```
Tier 1A: ACE-Step v1.5 (primary)
    - 1.7B LM + DiT hybrid architecture
    - 48 kHz stereo, up to 10 minutes
    - ~4 GB VRAM minimum, ~8 GB for full GPU
    - Text prompt -> novel music
    - Supports lyrics, LoRA style tuning
    - Apache 2.0 license
    |
Tier 1B: MusicGen Medium (fallback)
    - Meta AudioCraft, 1.5B params
    - 32 kHz mono, up to ~2 min (windowed)
    - ~6-8 GB VRAM
    - Text prompt + optional melody conditioning
    - MIT code license, CC-BY-NC model weights
    - Outputs are NOT restricted by model license
    |
Tier 2: AI-Enhanced MIDI Composition (CPU or light GPU)
    - Local LLM generates MIDI parameters from text description
    - Theory-correct chord progressions, melodies, arrangements
    - FluidSynth + SoundFont rendering to WAV
    - Unlimited duration, zero GPU for synthesis
    - Full control: tempo, key, time signature, instruments
    |
Tier 3: Programmatic DSP (CPU, instant)
    - 9 sound effect types (existing)
    - Add: ambient textures, drones, pads via additive synthesis
    - Pure numpy/scipy, no models needed
```

### 3.2 Video-Aware Music Selection

```
clipcannon_ingest (existing)
    -> emotion_curve, beats, pacing, narrative_analysis
        |
New: MusicPlanner (reads analysis DB)
    -> Determines mood arc, energy curve, tempo alignment
    -> Generates prompt for ACE-Step / selects MIDI preset
    -> Aligns music beats to video cut points
    -> Applies ducking around speech (existing mixer)
```

### 3.3 File Layout (per project)

```
~/.clipcannon/projects/{project_id}/
    audio/
        {asset_id}_music.wav        # AI-generated music
        {asset_id}_composition.mid  # MIDI source
        {asset_id}_composition.wav  # MIDI rendered
        {asset_id}_{sfx_type}.wav   # Sound effects
        {asset_id}_cleaned.wav      # Cleaned audio
```

No change to existing file layout. The `audio_assets` DB table already tracks all generated audio.

### 3.4 Model Storage (all local)

```
~/.cache/ace-step/checkpoints/        # ACE-Step v1.5 weights (~3.5 GB)
~/.cache/huggingface/hub/             # MusicGen weights (~3 GB for medium)
~/.clipcannon/models/GeneralUser_GS.sf2  # SoundFont for MIDI rendering
```

All models downloaded once on first use, cached permanently. No internet required after initial download.

---

## 4. Implementation Plan

### Phase 1: ACE-Step v1.5 Upgrade (Priority: HIGH)

**Files to modify:**
- `src/clipcannon/audio/music_gen.py` -- update pipeline import and params
- `config/default_config.json` -- update `audio.music_model` default
- `src/clipcannon/config.py` -- add v1.5-specific config fields
- `tests/test_audio_generation.py` -- update tests

**Changes:**

1. **Update ACE-Step import path** from `acestep.pipeline_ace_step.ACEStepPipeline` to the v1.5 API:
   ```python
   from ace_step.pipeline import ACEStepPipeline  # v1.5 new import
   ```

2. **Add v1.5-specific parameters**:
   - `lyrics` parameter (already passed as empty string, now functional)
   - `tags` parameter for genre/mood tags (new in v1.5)
   - `infer_step` count (v1.5 default: 100 DiT steps, configurable)
   - LoRA style loading support

3. **Update model identifier** from `"ACE-Step-v1-3.5B"` to `"ACE-Step-v1.5-1.7B"`

4. **Add config fields** to `AudioConfig`:
   ```python
   music_infer_steps: int = 100        # DiT inference steps (quality vs speed)
   music_lora_path: str | None = None  # Optional LoRA for style customization
   ```

5. **VRAM optimization**: v1.5 uses ~4 GB VRAM at INT8 (down from v1's 8 GB). Update the `cpu_offload` threshold from 8 GB to 4 GB.

**Estimated effort**: 2-3 hours

---

### Phase 2: MusicGen Fallback (Priority: MEDIUM)

**New files:**
- `src/clipcannon/audio/musicgen.py` -- MusicGen integration

**Files to modify:**
- `src/clipcannon/audio/__init__.py` -- export new module
- `src/clipcannon/audio/music_gen.py` -- add fallback routing
- `src/clipcannon/tools/audio.py` -- update `clipcannon_generate_music` tool
- `pyproject.toml` -- add `audiocraft` to `[ml]` extras
- `tests/test_audio_generation.py` -- add MusicGen tests

**Changes:**

1. **New `musicgen.py` module**:
   ```python
   async def generate_music_musicgen(
       prompt: str,
       duration_s: float,
       output_path: Path,
       model_size: str = "medium",  # small/medium/large
       seed: int | None = None,
       gpu_device: str = "cuda:0",
   ) -> MusicResult:
       """Fallback music generation via Meta MusicGen."""
       from audiocraft.models import MusicGen
       from audiocraft.data.audio import audio_write
       
       model = MusicGen.get_pretrained(f"facebook/musicgen-{model_size}")
       model.set_generation_params(duration=min(duration_s, 30))
       
       wav = model.generate([prompt])
       audio_write(str(output_path.with_suffix("")), wav[0].cpu(), 
                   model.sample_rate, strategy="loudness")
       # ... validation, cleanup ...
   ```

2. **Windowed generation for >30s**: Generate 30s chunks with 5s overlap, crossfade at seams.

3. **Automatic fallback**: If ACE-Step fails (import error, VRAM exhaustion), fall through to MusicGen. If MusicGen fails, fall through to MIDI.

4. **Config addition**:
   ```json
   "audio": {
       "music_model": "ace-step",
       "music_fallback_model": "musicgen-medium",
       "musicgen_model_size": "medium"
   }
   ```

**Estimated effort**: 4-5 hours

---

### Phase 3: AI-Enhanced MIDI Composition (Priority: MEDIUM)

**New files:**
- `src/clipcannon/audio/midi_ai.py` -- LLM-driven MIDI parameter generation

**Files to modify:**
- `src/clipcannon/audio/midi_compose.py` -- expand preset system
- `src/clipcannon/tools/audio.py` -- new/updated MCP tool
- `tests/test_audio_generation.py` -- tests

**Changes:**

1. **LLM-driven MIDI planning**: Use the local Qwen3-8B model (already loaded for `narrative_llm` pipeline stage) to translate natural language music descriptions into structured MIDI parameters:

   ```python
   async def plan_midi_from_prompt(prompt: str) -> MidiPlan:
       """Use local LLM to convert text prompt to MIDI parameters.
       
       Input: "upbeat electronic music, 130 BPM, energetic, major key"
       Output: MidiPlan(
           tempo_bpm=130, key="C", time_sig=(4,4),
           chord_progression=["C","G","Am","F"],
           instruments=[piano, synth_bass, drums],
           dynamics=(70, 110),
           melody_style="arpeggiated",
           sections=["intro:4bars", "verse:8bars", "chorus:8bars", "outro:4bars"]
       )
       """
   ```

2. **Expand preset system** from 6 to 12+ presets:
   - Add: `lofi_chill`, `cinematic_epic`, `tech_corporate`, `acoustic_folk`, `synth_wave`, `jazz_smooth`
   - Each with theory-correct progressions, instrument sets, and dynamics

3. **Section-based composition**: Instead of repeating one progression, compose intro/verse/chorus/bridge/outro sections with variation:
   ```python
   class MidiSection:
       name: str           # "intro", "verse", "chorus", "bridge", "outro"
       bars: int           # Length in bars
       progression: list   # Chord progression for this section
       dynamics: tuple     # Volume range
       instruments: list   # Active instruments
   ```

4. **New MCP tool** `clipcannon_compose_music`:
   ```
   Parameters:
     - project_id, edit_id
     - description: str  ("calm background music for a tutorial video")
     - duration_s: float
     - tempo_bpm: int (optional, AI decides if omitted)
     - key: str (optional)
     - energy: str (low/medium/high, optional)
     - instruments: list[str] (optional)
   ```
   The tool uses the LLM to plan, then composes MIDI, then renders via FluidSynth.

**Estimated effort**: 6-8 hours

---

### Phase 4: Video-Aware Music Generation (Priority: HIGH)

**New files:**
- `src/clipcannon/audio/music_planner.py` -- reads video analysis, produces music plan

**Files to modify:**
- `src/clipcannon/tools/audio.py` -- new MCP tool
- `tests/test_audio_generation.py` -- tests

**Changes:**

1. **MusicPlanner** reads the project's analysis database to build a music brief:

   ```python
   class MusicPlanner:
       """Generate music parameters from video analysis data."""
       
       def plan_for_edit(self, db_path: Path, project_id: str, 
                          edit_id: str) -> MusicBrief:
           """Read edit segments, emotion curve, narrative, pacing, beats.
           
           Returns a MusicBrief with:
             - Overall mood (from emotion_curve aggregate)
             - Energy arc (from pacing analysis)
             - Tempo suggestion (from beats/pacing)
             - Key moments where music should shift
             - Speech regions for ducking
             - Suggested prompt for ACE-Step
             - Suggested preset for MIDI fallback
           """
   ```

2. **Mood-to-music mapping**:

   | Emotion | Energy | Suggested Style | Tempo Range | Key |
   |---------|--------|-----------------|-------------|-----|
   | joy/excitement | high | upbeat_pop, electronic | 120-140 BPM | Major |
   | calm/neutral | low | ambient_pad, lofi | 60-80 BPM | Major |
   | sadness | low | minimal_piano, strings | 60-80 BPM | Minor |
   | tension/anger | high | dramatic, cinematic | 90-120 BPM | Minor |
   | professional | medium | corporate, acoustic | 90-110 BPM | Major |
   | inspiring | medium-high | cinematic_epic, strings | 100-130 BPM | Major |

3. **Beat alignment**: Align generated music tempo to detected video beats where possible. Use the `beats` and `beat_sections` tables from the analysis pipeline.

4. **New MCP tool** `clipcannon_auto_music`:
   ```
   Parameters:
     - project_id, edit_id
     - style_override: str (optional, overrides auto-detected mood)
     - tier: str ("ai" | "midi" | "auto", default "auto")
     - duration_override_s: float (optional, defaults to edit duration)
   
   Returns:
     - audio_asset_id, file_path, duration_ms
     - detected_mood, suggested_tempo, energy_arc
     - generation_method ("ace-step" | "musicgen" | "midi")
   ```

**Estimated effort**: 6-8 hours

---

### Phase 5: Ambient/Drone Synthesis Expansion (Priority: LOW)

**Files to modify:**
- `src/clipcannon/audio/sfx.py` -- add ambient texture types

**Changes:**

Add 4 new DSP-based ambient generators (pure numpy, no GPU):

| Type | Algorithm | Use Case |
|------|-----------|----------|
| `ambient_drone` | Layered sine waves with slow LFO modulation + reverb | Background atmosphere |
| `ambient_texture` | Filtered noise with granular envelope modulation | Textural bed |
| `pad_swell` | Harmonic series with slow attack/release ADSR | Emotional swells |
| `nature_bed` | Pink noise + filtered white noise layered | Outdoor ambiance |

These provide instant, GPU-free background textures when full music generation is overkill.

**Estimated effort**: 3-4 hours

---

### Phase 6: Cleanup & Removal (Priority: HIGH)

**Files to audit and clean:**

1. **Remove any hardcoded royalty music paths** -- search codebase for references to `.mp3`, `.aac`, music library paths, royalty, licensed, stock music
2. **Update documentation** -- `docs/codestate/15_audio_engine.md` to reflect new architecture
3. **Update config defaults** -- ensure `audio.music_model` defaults to `"ace-step-v1.5"`
4. **Update `pyproject.toml`** -- add `audiocraft` and updated `ace-step` to extras

**Estimated effort**: 1-2 hours

---

## 5. New/Modified MCP Tools

### Modified Tools

| Tool | Change |
|------|--------|
| `clipcannon_generate_music` | Add `model` param (ace-step/musicgen/auto), auto-fallback chain |
| `clipcannon_compose_midi` | Accept free-text `description` as alternative to `preset` |

### New Tools

| Tool | Description |
|------|-------------|
| `clipcannon_auto_music` | Video-aware automatic music generation from analysis data |
| `clipcannon_compose_music` | AI-planned MIDI composition from natural language description |

### Tool Count Impact

Current: 51 tools. After: 53 tools (+2 new).

---

## 6. Config Changes

### `config/default_config.json` additions

```json
{
  "audio": {
    "music_model": "ace-step-v1.5",
    "music_fallback_model": "musicgen-medium",
    "music_guidance_scale": 15.0,
    "music_infer_steps": 100,
    "music_lora_path": null,
    "music_default_volume_db": -12,
    "musicgen_model_size": "medium",
    "auto_music_tier": "auto",
    "duck_under_speech": true,
    "sfx_on_transitions": true,
    "normalize_output": true
  }
}
```

---

## 7. Dependencies

### New Python Packages

| Package | Version | Extra Group | Purpose | GPU Required |
|---------|---------|-------------|---------|--------------|
| `ace-step` | >=1.5 | `[ml]` | ACE-Step v1.5 music generation | Yes (4+ GB) |
| `audiocraft` | >=1.3 | `[ml]` | MusicGen fallback | Yes (6+ GB) |

### Existing (no change)

| Package | Purpose |
|---------|---------|
| `midiutil` | MIDI file creation |
| `pyfluidsynth` | MIDI-to-WAV rendering |
| `pydub` | Audio mixing |
| `pedalboard` | Effects processing |
| `numpy`, `scipy` | DSP sound effects |

All packages install locally. No cloud APIs or online services used at runtime.

---

## 8. GPU VRAM Budget

On RTX 5090 (32 GB) with voice agent potentially active:

| Scenario | Models Loaded | VRAM Used |
|----------|---------------|-----------|
| Music gen only (ACE-Step v1.5) | ACE-Step 1.7B | ~4 GB |
| Music gen only (MusicGen medium) | MusicGen 1.5B | ~6 GB |
| Music gen during ingest | Pipeline models + ACE-Step | ~12 GB total |
| Music gen with voice agent active | Not possible -- voice agent uses ~30 GB |
| MIDI composition | No GPU models | 0 GB |
| DSP sound effects | No GPU models | 0 GB |

Music generation should not run concurrently with the voice agent. The existing GPU worker pause/resume system (`voiceagent/gpu_manager.py`) handles this.

---

## 9. Legal Analysis: AI-Generated Music Copyright

### Why AI-Generated Music is Royalty-Free

1. **Novel output**: ACE-Step and MusicGen generate new audio via diffusion/transformer, not by sampling or remixing training data. The output is a novel creation.

2. **No third-party copyright on outputs**: Unlike royalty music libraries where a composer holds copyright, AI-generated audio from locally-run open-source models has no third-party rights holder.

3. **Model licenses permit commercial use of outputs**:
   - ACE-Step: Apache 2.0 -- fully permissive
   - MusicGen code: MIT -- fully permissive
   - MusicGen model weights: CC-BY-NC 4.0 -- restricts redistribution of weights, NOT outputs
   - MIDI: No model involved, just math

4. **U.S. Copyright Office position (2025)**: AI-generated works with meaningful human authorship (prompt crafting, selection, editing, mixing) can receive copyright protection. ClipCannon's workflow involves substantial human direction (video analysis -> prompt -> selection -> mixing -> ducking -> rendering), which strengthens the copyright position.

5. **No performance royalties**: Unlike licensed music tracks (which may require ASCAP/BMI royalties for public performance), AI-generated music has no songwriter/performer collecting royalties.

### Risk Mitigation

- ACE-Step's Apache 2.0 license is the safest choice
- Always store generation metadata (prompt, seed, model) in `audio_assets` table for provenance
- The existing provenance chain system can be extended to cover audio generation

---

## 10. Implementation Priority & Timeline

| Phase | Priority | Effort | Dependencies |
|-------|----------|--------|--------------|
| **1: ACE-Step v1.5 upgrade** | HIGH | 2-3 hrs | None |
| **6: Cleanup & removal** | HIGH | 1-2 hrs | None |
| **4: Video-aware generation** | HIGH | 6-8 hrs | Phase 1 |
| **2: MusicGen fallback** | MEDIUM | 4-5 hrs | Phase 1 |
| **3: AI-enhanced MIDI** | MEDIUM | 6-8 hrs | None |
| **5: Ambient DSP expansion** | LOW | 3-4 hrs | None |

**Total estimated effort**: 22-30 hours across all phases.

Recommended execution order: Phase 1 -> Phase 6 -> Phase 4 -> Phase 2 -> Phase 3 -> Phase 5

---

## 11. Testing Strategy

### Unit Tests (per phase)

| Phase | Test Focus | Count (est) |
|-------|-----------|-------------|
| 1 | ACE-Step v1.5 pipeline, VRAM detection, output validation | 8 |
| 2 | MusicGen fallback, windowed generation, crossfade | 10 |
| 3 | LLM MIDI planning, section composition, 12 presets | 15 |
| 4 | MusicPlanner mood detection, beat alignment, auto-music | 12 |
| 5 | 4 new ambient DSP generators | 8 |
| 6 | No royalty references, config validation | 5 |

### Integration Tests

- End-to-end: `ingest -> get_editing_context -> auto_music -> mix -> render`
- Fallback chain: ACE-Step unavailable -> MusicGen -> MIDI
- VRAM contention: music gen during active pipeline stage
- Duration accuracy: generated music within 10% of requested duration

### FSV Additions

- Add audio generation checks to `manual_fsv_phase3.py`
- Verify all 4 audio MCP tools dispatch correctly
- Verify `audio_assets` table populated with correct metadata

---

## 12. Rollback Plan

All changes are additive. The existing `music_gen.py`, `midi_compose.py`, and `midi_render.py` remain functional throughout. If any phase fails:

- Phase 1: Revert to ACE-Step v1 import (existing code)
- Phase 2: MusicGen is optional fallback; removing it leaves ACE-Step as sole Tier 1
- Phase 3: AI MIDI planning is additive; existing 6 presets remain
- Phase 4: Video-aware planner is a new tool; not modifying existing tools
- Phase 5: New DSP types are additive to existing 9

No existing functionality is removed until Phase 6 cleanup, which only removes dead references.
