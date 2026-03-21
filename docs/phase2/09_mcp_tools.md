# Phase 2 MCP Tools

## 1. Overview
Phase 2 adds ~10 new MCP tools, bringing the total from 27 to ~37.

## 2. New Tools

### Editing Tools (3)
| Tool | Parameters | Returns |
|------|-----------|---------|
| clipcannon_create_edit | project_id, name, target_platform, segments[], captions{}, crop{}, audio{}, overlays{}, metadata{} | edit_id, status, segment_count, total_duration_ms |
| clipcannon_modify_edit | project_id, edit_id, changes{} | edit_id, status, updated fields |
| clipcannon_list_edits | project_id, status_filter? | edits[], total |

### Rendering Tools (3)
| Tool | Parameters | Returns |
|------|-----------|---------|
| clipcannon_render | project_id, edit_id | render_id, status, output_path |
| clipcannon_render_status | project_id, render_id | status, progress_pct, output_path, file_size |
| clipcannon_render_batch | project_id, edit_ids[] | batch_id, render_ids[] |

### Audio Tools (3)
| Tool | Parameters | Returns |
|------|-----------|---------|
| clipcannon_generate_music | project_id, edit_id, prompt, duration_s, tier, seed?, volume_db? | audio_asset_id, file_path, duration_ms |
| clipcannon_compose_midi | project_id, edit_id, preset, duration_s, tempo_bpm?, key? | audio_asset_id, file_path, midi_path |
| clipcannon_generate_sfx | project_id, edit_id, sfx_type, duration_ms?, params? | audio_asset_id, file_path, duration_ms |

### Metadata Tools (1)
| Tool | Parameters | Returns |
|------|-----------|---------|
| clipcannon_generate_metadata | project_id, edit_id, target_platform | title, description, hashtags[], thumbnail_ms |

## 3. Tool Response Size Budget
All responses must be under 25K tokens. Phase 2 tools return compact JSON:
- create_edit: ~500 tokens
- list_edits: ~200 tokens per edit, paginate at 50
- render_status: ~300 tokens
- generate_music: ~200 tokens

## 4. Credit Charges
| Operation | Credits | Notes |
|-----------|---------|-------|
| render | 2 | Per output clip rendered |
| metadata | 1 | Per clip per platform |
These rates are already defined in Phase 1's credits.py but not yet active.
