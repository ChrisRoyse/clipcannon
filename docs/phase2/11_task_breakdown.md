# Phase 2 Complete Task Breakdown

## 1. EDL Format & Edit Creation (5 tasks)

| ID | Task | Files | Dependencies | Priority |
|----|------|-------|-------------|----------|
| 2.1.1 | Define EDL JSON schema (Pydantic models for segments, transitions, captions, audio, overlays) | src/clipcannon/editing/edl.py | Phase 1 complete | P0 |
| 2.1.2 | Implement EDL validation (time ranges, profile compat, source SHA-256 check) | src/clipcannon/editing/edl.py | 2.1.1 | P0 |
| 2.1.3 | Implement clipcannon_create_edit MCP tool | src/clipcannon/tools/editing.py | 2.1.1, 2.1.2 | P0 |
| 2.1.4 | Implement clipcannon_modify_edit MCP tool | src/clipcannon/tools/editing.py | 2.1.3 | P1 |
| 2.1.5 | Implement clipcannon_list_edits MCP tool | src/clipcannon/tools/editing.py | 2.1.3 | P1 |

## 2. Caption Generation (3 tasks)

| ID | Task | Files | Dependencies | Priority |
|----|------|-------|-------------|----------|
| 2.2.1 | Implement word-level caption chunking algorithm (max words, min display, line breaks) | src/clipcannon/editing/captions.py | Phase 1 (transcript_words) | P0 |
| 2.2.2 | Implement ASS subtitle file generation (bold_centered, word_highlight, subtitle_bar, karaoke styles) | src/clipcannon/editing/captions.py | 2.2.1 | P0 |
| 2.2.3 | Implement FFmpeg drawtext filter fallback for simple captions | src/clipcannon/editing/captions.py | 2.2.1 | P2 |

## 3. Smart Cropping (4 tasks)

| ID | Task | Files | Dependencies | Priority |
|----|------|-------|-------------|----------|
| 2.3.1 | Integrate face detection model (MediaPipe or InsightFace ONNX) | src/clipcannon/editing/smart_crop.py | Phase 1 | P0 |
| 2.3.2 | Implement face-aware crop calculation (center on face, safe area margins) | src/clipcannon/editing/smart_crop.py | 2.3.1 | P0 |
| 2.3.3 | Implement dynamic pan-and-scan (smooth crop transitions between scenes) | src/clipcannon/editing/smart_crop.py | 2.3.2 | P1 |
| 2.3.4 | Implement per-platform crop profiles (9:16, 1:1, 16:9, 4:5) | src/clipcannon/editing/smart_crop.py | 2.3.2 | P0 |

## 4. Rendering Pipeline (9 tasks)

| ID | Task | Files | Dependencies | Priority |
|----|------|-------|-------------|----------|
| 2.4.1 | Implement typed-ffmpeg filter graph builder (EDL -> FFmpeg command) | src/clipcannon/rendering/renderer.py | 2.1.1 | P0 |
| 2.4.2 | Implement platform encoding profiles (7 profiles: tiktok, instagram, youtube, youtube_shorts, facebook, linkedin_square, linkedin_landscape) | src/clipcannon/rendering/profiles.py | 2.4.1 | P0 |
| 2.4.3 | Implement single-pass rendering (multi-segment concat in one FFmpeg command) | src/clipcannon/rendering/renderer.py | 2.4.1 | P0 |
| 2.4.4 | Implement generation loss prevention (source SHA-256 verification, refuse renders/ as input) | src/clipcannon/rendering/renderer.py | 2.4.1, Phase 1 provenance | P0 |
| 2.4.5 | Implement batch rendering (up to 3 parallel NVENC sessions, queue management) | src/clipcannon/rendering/batch.py | 2.4.3 | P1 |
| 2.4.6 | Implement thumbnail generation (extract frame, apply crop, JPEG output) | src/clipcannon/rendering/thumbnail.py | 2.4.1 | P1 |
| 2.4.7 | Implement clipcannon_render MCP tool | src/clipcannon/tools/rendering.py | 2.4.3 | P0 |
| 2.4.8 | Implement clipcannon_render_status MCP tool | src/clipcannon/tools/rendering.py | 2.4.7 | P1 |
| 2.4.9 | Implement clipcannon_render_batch MCP tool | src/clipcannon/tools/rendering.py | 2.4.5 | P1 |

## 5. Audio Generation Engine (9 tasks)

| ID | Task | Files | Dependencies | Priority |
|----|------|-------|-------------|----------|
| 2.5.1 | Implement ACE-Step v1.5 integration (text prompt -> music WAV) | src/clipcannon/audio/music_gen.py | Phase 1 GPU manager | P0 |
| 2.5.2 | Implement MIDI composition pipeline (MIDIUtil + music21 chord progressions) | src/clipcannon/audio/midi_compose.py | None | P0 |
| 2.5.3 | Implement FluidSynth MIDI -> WAV rendering | src/clipcannon/audio/midi_render.py | 2.5.2 | P0 |
| 2.5.4 | Implement DSP sound effects (whoosh, riser, impact, chime, bass drop, shimmer, stinger) | src/clipcannon/audio/sfx.py | None | P0 |
| 2.5.5 | Implement audio mixing pipeline (ducking, crossfade, normalization, layer ordering) | src/clipcannon/audio/mixer.py | 2.5.1, 2.5.3, 2.5.4 | P0 |
| 2.5.6 | Implement pedalboard audio effects (reverb, compression, EQ, limiting) | src/clipcannon/audio/effects.py | 2.5.5 | P1 |
| 2.5.7 | Implement clipcannon_generate_music MCP tool | src/clipcannon/tools/audio.py | 2.5.1 | P0 |
| 2.5.8 | Implement clipcannon_compose_midi MCP tool | src/clipcannon/tools/audio.py | 2.5.2 | P1 |
| 2.5.9 | Implement clipcannon_generate_sfx MCP tool | src/clipcannon/tools/audio.py | 2.5.4 | P0 |

## 6. Metadata Generation (2 tasks)

| ID | Task | Files | Dependencies | Priority |
|----|------|-------|-------------|----------|
| 2.6.1 | Implement per-platform metadata generation (title, description, hashtags) | src/clipcannon/editing/metadata_gen.py | Phase 1 (topics, highlights) | P1 |
| 2.6.2 | Implement clipcannon_generate_metadata MCP tool | src/clipcannon/tools/editing.py | 2.6.1 | P1 |

## 7. Dashboard Expansion (6 tasks)

| ID | Task | Files | Dependencies | Priority |
|----|------|-------|-------------|----------|
| 2.7.1 | Build project view page (source video info, analysis status, stream progress bars) | dashboard/routes/, dashboard/static/ | Phase 1 | P1 |
| 2.7.2 | Build timeline visualization (scene boundaries, speakers, emotion curve, topics, highlights) | dashboard/routes/timeline.py, dashboard/static/ | Phase 1 | P1 |
| 2.7.3 | Build transcript panel (searchable, clickable timestamps, speaker labels) | dashboard/routes/, dashboard/static/ | Phase 1 | P1 |
| 2.7.4 | Build edit review page (clip preview player, platform mockups, metadata editor) | dashboard/routes/editing.py, dashboard/routes/review.py | 2.4.7 | P0 |
| 2.7.5 | Build approve/reject/edit workflow (action buttons, feedback to AI) | dashboard/routes/review.py | 2.7.4 | P0 |
| 2.7.6 | Build batch review mode (swipe through clips, one-click approve/reject) | dashboard/routes/review.py, dashboard/static/ | 2.7.5 | P1 |

## 8. Infrastructure & Config (3 tasks)

| ID | Task | Files | Dependencies | Priority |
|----|------|-------|-------------|----------|
| 2.8.1 | Add audio and rendering config sections to default_config.json + Pydantic models | config/default_config.json, src/clipcannon/config.py | Phase 1 | P0 |
| 2.8.2 | Implement database schema v2 migration (edits, edit_segments, renders, audio_assets tables) | src/clipcannon/db/schema.py | Phase 1 | P0 |
| 2.8.3 | Add Phase 2 dependencies to pyproject.toml (typed-ffmpeg, mediapipe, pydub, etc.) | pyproject.toml | Phase 1 | P0 |

## Summary

| Category | Tasks | P0 | P1 | P2 |
|----------|-------|----|----|-----|
| EDL Format | 5 | 3 | 2 | 0 |
| Captions | 3 | 2 | 0 | 1 |
| Smart Crop | 4 | 3 | 1 | 0 |
| Rendering | 9 | 4 | 5 | 0 |
| Audio Gen | 9 | 6 | 3 | 0 |
| Metadata | 2 | 0 | 2 | 0 |
| Dashboard | 6 | 2 | 4 | 0 |
| Infrastructure | 3 | 3 | 0 | 0 |
| **Total** | **41** | **23** | **17** | **1** |

## Execution Order

### Sprint 1 (Week 1-2): Foundation
Infrastructure (2.8.1-2.8.3) -> EDL (2.1.1-2.1.3) -> Captions (2.2.1-2.2.2) -> Smart Crop (2.3.1-2.3.2, 2.3.4)

### Sprint 2 (Week 3-4): Rendering
Rendering (2.4.1-2.4.4, 2.4.7) -> EDL (2.1.4-2.1.5) -> Batch render (2.4.5, 2.4.8-2.4.9) -> Thumbnails (2.4.6) -> Metadata (2.6.1-2.6.2)

### Sprint 3 (Week 5-6): Audio
DSP SFX (2.5.4, 2.5.9) -> MIDI (2.5.2-2.5.3, 2.5.8) -> ACE-Step (2.5.1, 2.5.7) -> Mixer (2.5.5-2.5.6)

### Sprint 4 (Week 7-8): Dashboard + Integration
Dashboard (2.7.1-2.7.6) -> Smart crop pan-scan (2.3.3) -> Caption drawtext (2.2.3) -> E2E integration testing
