# ClipCannon Phase 2: Editing Engine + Audio + Dashboard

## Executive Summary

Phase 2 transforms ClipCannon from a video understanding system into a complete editing and rendering platform. Phase 1 delivers the "eyes and ears" (understanding pipeline). Phase 2 delivers the "hands" (editing, rendering, audio generation) and the "control room" (dashboard with human-in-the-loop review).

Phase 1 was completed and verified on 2026-03-21 with 750/750 FSV checks, 181 pytest tests, 27 MCP tools, and 20 pipeline stages.

## Goals

- EDL (Edit Decision List) format for declarative video editing
- Rendering pipeline with NVENC hardware acceleration and typed-ffmpeg
- Caption generation with word-level timing from WhisperX data
- Face-aware smart cropping for platform-specific aspect ratios
- AI audio generation (ACE-Step music, MIDI composition, DSP sound effects)
- Audio mixing with speech-aware ducking
- Metadata generation (titles, descriptions, hashtags per platform)
- Full dashboard with project view, timeline visualization, edit review, approve/reject workflow, batch review mode

## Phase 2 Deliverables Summary

| # | Component | New Files | New MCP Tools | New DB Tables |
|---|-----------|-----------|---------------|---------------|
| 1 | EDL Format & Edit Creation | editing/edl.py, tools/editing.py | 3 (create_edit, modify_edit, list_edits) | edits, edit_segments |
| 2 | Caption Generation | editing/captions.py | 0 (part of EDL) | 0 (captions in EDL) |
| 3 | Smart Cropping | editing/smart_crop.py | 0 (part of render) | 0 (crop in EDL) |
| 4 | Rendering Pipeline | rendering/renderer.py, rendering/profiles.py, rendering/batch.py, rendering/thumbnail.py, tools/rendering.py | 3 (render, render_status, render_batch) | renders, render_outputs |
| 5 | Audio Generation | audio/music_gen.py, audio/midi_compose.py, audio/midi_render.py, audio/sfx.py, audio/mixer.py, audio/effects.py, tools/audio.py | 3 (generate_music, compose_midi, generate_sfx) | audio_assets |
| 6 | Metadata Generation | editing/metadata_gen.py | 1 (generate_metadata) | 0 (metadata in edits table) |
| 7 | Dashboard Expansion | dashboard/routes/timeline.py, dashboard/routes/editing.py, dashboard/routes/review.py, dashboard/static/* | 0 | 0 |

Total new MCP tools: ~10 (bringing total from 27 to ~37)

## Architecture Changes

Phase 2 adds three new engine modules alongside the existing codebase:

```
src/clipcannon/
    editing/          # NEW - EDL format, captions, smart crop, metadata
    rendering/        # NEW - FFmpeg rendering, profiles, batch, thumbnails
    audio/            # NEW - ACE-Step, MIDI, DSP SFX, mixing, effects
    tools/            # EXTENDED - editing.py, rendering.py, audio.py added
    dashboard/        # EXTENDED - new route modules for editing/review
    pipeline/         # UNCHANGED
    billing/          # UNCHANGED (render/metadata/publish charges activated)
    provenance/       # EXTENDED (render provenance records)
    db/               # EXTENDED (new tables for edits, renders, audio)
    gpu/              # UNCHANGED
```

## Execution Timeline

| Week | Focus | Tasks |
|------|-------|-------|
| 1-2 | EDL + Captions + Cropping | 2.1.1-2.1.5, 2.2.1-2.2.3, 2.3.1-2.3.4 |
| 3-4 | Rendering Pipeline | 2.4.1-2.4.9, 2.6.1-2.6.2 |
| 5-6 | Audio Generation Engine | 2.5.1-2.5.9 |
| 7-8 | Dashboard + Integration Testing | 2.7.1-2.7.6 + E2E tests |

## Success Criteria

- [ ] AI can produce 10+ platform-ready clips from a single 1-hour source
- [ ] Render time < 30 seconds per clip (including audio + captions)
- [ ] Captions are word-accurate and properly timed (< 100ms drift)
- [ ] Output passes platform validation for all 5 target platforms (TikTok, Instagram Reels, YouTube, Facebook, LinkedIn)
- [ ] Human can review and approve 20 clips in under 5 minutes via dashboard
- [ ] AI-generated music is coherent, mood-appropriate, and at least 30 seconds long
- [ ] DSP sound effects are clean (no clicks/pops) and properly timed to transitions
- [ ] Audio ducking correctly reduces music under speech segments within 200ms

## Dependencies on Phase 1

Phase 2 depends on the following Phase 1 components being complete:

- Project management (create, open, status) - for project context
- Video understanding pipeline (VUD, transcript, scenes, highlights) - for editing decisions
- Provenance system - extended to cover renders
- Billing system - render/metadata credit charges activated
- Dashboard scaffold - extended with new pages
- Database layer - new tables added via schema migration
- GPU manager - used for ACE-Step and face detection models

## New Dependencies (Python Packages)

| Package | Version | Purpose | License |
|---------|---------|---------|---------|
| typed-ffmpeg | >=3.0 | Type-safe FFmpeg command building | MIT |
| mediapipe | >=0.10 | Face detection for smart cropping | Apache 2.0 |
| ace-step | >=1.5 | AI music generation | MIT |
| midiutil | >=1.2 | MIDI file creation | MIT |
| music21 | >=9.0 | Music theory (chord progressions) | LGPL |
| pyfluidsynth | >=1.3 | MIDI to WAV rendering | LGPL |
| pydub | >=0.25 | Audio mixing, ducking, crossfade | MIT |
| pedalboard | >=0.9 | Audio effects (reverb, EQ, compression) | GPLv3 |

## Configuration Additions

Phase 2 adds two new config sections to `config/default_config.json`:

```json
{
  "audio": {
    "music_model": "ace-step-v15-turbo-rl",
    "music_lora": "Text2Samples",
    "music_guidance_scale": 7.5,
    "music_default_volume_db": -18,
    "duck_under_speech": true,
    "duck_level_db": -6,
    "sfx_on_transitions": true,
    "sfx_default_type": "whoosh",
    "midi_soundfont": "GeneralUser_GS.sf2",
    "normalize_output": true,
    "sample_rate": 44100
  },
  "rendering": {
    "... existing keys ...": "",
    "max_parallel_renders": 3,
    "default_caption_style": "bold_centered"
  }
}
```

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| ACE-Step music quality inconsistency | Medium | Seed-based generation for reproducibility; fall back to MIDI; human review |
| Smart cropping on complex multi-person scenes | Medium | Fall back to center crop; use shot_type from Phase 1 for guidance |
| Caption timing drift on fast speech | Medium | Use WhisperX word-level timestamps (20-50ms precision); minimum display duration per word chunk |
| typed-ffmpeg filter graph complexity | Medium | Validate filter graphs before execution; comprehensive test suite |
| Audio ducking timing mismatch | Low | Use Silero VAD timestamps from understanding pipeline; 200ms lookahead buffer |
| NVENC session limits | Low | Queue renders when > 3 concurrent; batch scheduling |

## Document Index

| Document | Description |
|----------|-------------|
| [01_edl_format.md](01_edl_format.md) | EDL JSON schema, validation rules, edit creation workflow |
| [02_caption_generation.md](02_caption_generation.md) | Caption chunking, ASS subtitle generation, styles |
| [03_smart_cropping.md](03_smart_cropping.md) | Face detection, crop calculation, platform profiles |
| [04_rendering_pipeline.md](04_rendering_pipeline.md) | typed-ffmpeg integration, profiles, batch rendering |
| [05_audio_generation.md](05_audio_generation.md) | ACE-Step, MIDI, DSP SFX, mixing pipeline |
| [06_metadata_generation.md](06_metadata_generation.md) | Per-platform metadata generation |
| [07_dashboard_expansion.md](07_dashboard_expansion.md) | New dashboard pages and review workflow |
| [08_database_changes.md](08_database_changes.md) | Schema v2 additions for edits, renders, audio |
| [09_mcp_tools.md](09_mcp_tools.md) | All new Phase 2 MCP tools |
| [10_testing_strategy.md](10_testing_strategy.md) | Test plan and acceptance criteria |
| [11_task_breakdown.md](11_task_breakdown.md) | Complete task list with dependencies and file mappings |
