# Phase 2 Testing Strategy

## 1. Overview
Phase 2 testing follows the same patterns established in Phase 1: pytest unit tests + FSV (Full State Verification) scripts.

## 2. New Test Files

| File | Scope | Est. Tests |
|------|-------|------------|
| tests/test_edl.py | EDL schema validation, segment models, creation | 15-20 |
| tests/test_captions.py | Caption chunking, ASS generation, timing alignment | 15-20 |
| tests/test_smart_crop.py | Face detection mocks, crop calculation, platform profiles | 10-15 |
| tests/test_rendering.py | Filter graph building, profile validation, thumbnail gen | 15-20 |
| tests/test_audio_generation.py | DSP SFX generation, MIDI creation, mixing, ducking | 20-25 |
| tests/test_metadata.py | Per-platform metadata generation, character limits | 8-10 |
| tests/test_editing_tools.py | MCP tool tests: create_edit, modify_edit, list_edits | 10-15 |
| tests/test_rendering_tools.py | MCP tool tests: render, render_status, render_batch | 8-12 |
| tests/test_audio_tools.py | MCP tool tests: generate_music, compose_midi, generate_sfx | 8-10 |
| tests/dashboard/test_dashboard_phase2.py | New dashboard endpoints | 15-20 |
| tests/integration/test_edit_render.py | E2E: create edit -> render -> verify output | 10-15 |

Estimated total new tests: ~140-180

## 3. FSV Scripts
- `tests/fsv_editing_rendering.py` - EDL, captions, cropping, rendering, provenance
- `tests/fsv_audio_generation.py` - ACE-Step (mocked), MIDI, DSP, mixing

## 4. Acceptance Tests
- [ ] Create edit from highlights -> renders valid MP4
- [ ] Captions appear at correct word timestamps (< 100ms drift)
- [ ] Vertical crop keeps face centered on 10 test frames
- [ ] Audio ducking reduces music volume during speech
- [ ] DSP SFX have no clicks/pops (zero-crossing check)
- [ ] Platform profiles produce valid output (ffprobe validation)
- [ ] Batch render of 5 clips completes without error
- [ ] Dashboard edit review page loads and displays render

## 5. Test Infrastructure
- Synthetic test videos (short, deterministic) for rendering tests
- Mock ACE-Step model for CI (actual GPU tests are separate)
- Pre-generated MIDI files for FluidSynth tests
- Pillow-generated test frames for face detection mocks
