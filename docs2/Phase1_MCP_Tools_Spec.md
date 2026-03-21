# Phase 1: Foundation — MCP Tool Specifications

**Version:** 1.0
**Date:** 2026-03-21

All tools follow these rules:
- Every response < 25,000 tokens
- Stateless tool calls, stateful project data
- JSON responses with consistent error format
- Provenance-verified data

---

## 1. Error Response Format

All tools return errors in this format:

```json
{
  "error": {
    "code": "PROJECT_NOT_FOUND",
    "message": "Project 'proj_xyz' does not exist",
    "details": {}
  }
}
```

Common error codes: `PROJECT_NOT_FOUND`, `PROJECT_NOT_READY`, `INVALID_PARAMETER`, `INSUFFICIENT_CREDITS`, `PIPELINE_ERROR`, `INTERNAL_ERROR`.

---

## 2. Project Management Tools (5 tools)

### clipcannon_project_create

Create a new editing project from a source video.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| name | string | Yes | Human-readable project name |
| source_video_path | string | Yes | Absolute path to source video file |

**Response (~500 tokens):**
```json
{
  "project_id": "proj_a1b2c3d4",
  "name": "Podcast Ep 42",
  "source_path": "/videos/podcast_ep42.mp4",
  "source_sha256": "a3f74d2e...",
  "duration_ms": 3600000,
  "resolution": "3840x2160",
  "fps": 30.0,
  "codec": "h264",
  "file_size_bytes": 4294967296,
  "vfr_detected": false,
  "status": "created",
  "created_at": "2026-03-21T10:00:00Z"
}
```

**Behavior:** Runs probe stage. Does NOT start full analysis. Use `clipcannon_ingest` to begin analysis.

---

### clipcannon_project_open

Open an existing project by ID.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project identifier |

**Response:** Same format as create. Returns current project state.

---

### clipcannon_project_list

List all projects with optional status filter.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| status_filter | string | No | Filter: created, analyzing, ready, error, all (default: all) |

**Response (~2K tokens for 10 projects):**
```json
{
  "projects": [
    {
      "project_id": "proj_a1b2c3d4",
      "name": "Podcast Ep 42",
      "status": "ready",
      "duration_ms": 3600000,
      "resolution": "3840x2160",
      "created_at": "2026-03-21T10:00:00Z"
    }
  ],
  "total_count": 1
}
```

---

### clipcannon_project_status

Get detailed project status including pipeline progress.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project identifier |

**Response (~3K tokens):**
```json
{
  "project_id": "proj_a1b2c3d4",
  "status": "analyzing",
  "pipeline_progress": {
    "total_stages": 19,
    "completed": 12,
    "running": 2,
    "pending": 4,
    "failed": 1,
    "stages": {
      "probe": "completed",
      "audio_extract": "completed",
      "source_separation": "completed",
      "frame_extract": "completed",
      "transcribe": "completed",
      "visual_embed": "running",
      "ocr": "failed",
      "quality": "running",
      "shot_type": "pending",
      "semantic_embed": "completed",
      "emotion_embed": "completed",
      "speaker_embed": "completed",
      "reactions": "completed",
      "acoustic": "completed",
      "profanity": "completed",
      "chronemic": "completed",
      "highlights": "pending",
      "storyboard": "pending",
      "finalize": "pending"
    }
  },
  "disk_usage": {
    "sacred_mb": 4096,
    "regenerable_mb": 2048,
    "ephemeral_mb": 512,
    "total_mb": 6656
  }
}
```

---

### clipcannon_project_delete

Delete a project and all its data.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project identifier |
| keep_source | boolean | No | Keep source video file (default: true) |

**Response:**
```json
{
  "deleted": true,
  "freed_mb": 6656,
  "source_kept": true
}
```

---

## 3. Video Understanding Tools (9 tools)

### clipcannon_ingest

Ingest a video and run the full 12-stream analysis pipeline.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID (must be in "created" state) |
| options | object | No | Override defaults: whisper_model, frame_fps, scene_threshold |

**Response (~1K tokens):**
```json
{
  "project_id": "proj_a1b2c3d4",
  "status": "analyzing",
  "estimated_duration_s": 300,
  "credits_charged": 10,
  "message": "Analysis started. Use clipcannon_project_status to monitor progress."
}
```

**Behavior:** Starts async pipeline. Returns immediately. Pipeline runs in background. Credits charged at start; refunded if pipeline fails.

---

### clipcannon_get_vud_summary

Get the compact overview of a video's understanding (~8K tokens). First tool the AI calls.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID (must be "ready") |

**Response (~8K tokens):**
```json
{
  "source": {
    "file": "podcast_ep42.mp4",
    "duration_ms": 14400000,
    "resolution": "3840x2160",
    "fps": 30.0
  },
  "summary": {
    "total_scenes": 142,
    "total_speakers": 3,
    "speakers": [
      {"id": "speaker_0", "label": "Host", "speaking_pct": 45.2},
      {"id": "speaker_1", "label": "Guest 1", "speaking_pct": 35.1},
      {"id": "speaker_2", "label": "Guest 2", "speaking_pct": 19.7}
    ],
    "total_topics": 18,
    "topics_preview": [
      {"id": "topic_001", "start_ms": 0, "end_ms": 300000, "label": "Introduction"},
      {"id": "topic_002", "start_ms": 300000, "end_ms": 1800000, "label": "AI in Healthcare"}
    ],
    "total_highlights": 24,
    "top_highlights": [
      {"start_ms": 845000, "end_ms": 905000, "score": 0.96, "reason": "Breakthrough revelation + laughter"},
      {"start_ms": 3200000, "end_ms": 3260000, "score": 0.93, "reason": "Emotional personal story + applause"}
    ],
    "reaction_summary": {"total_laughter": 14, "total_applause": 3},
    "beats": {"has_music": true, "avg_bpm": 120.4},
    "content_safety": {"rating": "mild", "profanity_count": 7},
    "avg_energy": 0.62,
    "stream_status": { ... },
    "failed_streams": [],
    "provenance": {"chain_hash": "7e4a...", "records": 19, "integrity": "verified"}
  }
}
```

---

### clipcannon_get_analytics

Get full structural analytics: all scenes, topics, highlights, reactions (~18K tokens).

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| sections | array[string] | No | Which sections: highlights, scenes, topics, reactions, beats, pacing (default: all) |

**Response (~15-20K tokens):** Full arrays for each requested section.

---

### clipcannon_get_transcript

Get paginated transcript for a time range (~12K tokens per page).

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| start_ms | integer | No | Start of range (default: 0) |
| end_ms | integer | No | End of range (default: start + 900000 = 15 min) |
| include_words | boolean | No | Include word-level timestamps (default: true) |

**Response (~12K tokens per 15 minutes):**
```json
{
  "project_id": "proj_a1b2c3d4",
  "range": {"start_ms": 0, "end_ms": 900000},
  "total_segments_in_range": 63,
  "segments": [
    {
      "id": "seg_001",
      "start_ms": 1200,
      "end_ms": 5800,
      "text": "Welcome back to the show...",
      "speaker": "speaker_0",
      "words": [
        {"word": "Welcome", "start_ms": 1200, "end_ms": 1600},
        {"word": "back", "start_ms": 1650, "end_ms": 1900}
      ]
    }
  ],
  "has_more": true,
  "next_start_ms": 900000
}
```

---

### clipcannon_get_segment_detail

Get all stream data at full resolution for a specific time range (~10-20K tokens).

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| start_ms | integer | Yes | Start of range |
| end_ms | integer | Yes | End of range |

**Response:** Includes transcript, emotion_curve (per-second), speakers, reactions, beats, on_screen_text, pacing, quality, silence_gaps — all for that time range.

---

### clipcannon_get_frame

Get a single frame as an image with all temporal metadata.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| timestamp_ms | integer | Yes | Timestamp to extract frame at |

**Response (~1,600 tokens for image + ~500 tokens metadata):**
Returns the JPEG image (inline for multimodal AI) plus `at_this_moment` metadata:
```json
{
  "frame": {
    "timestamp_ms": 845000,
    "image": "[JPEG binary — delivered as image to multimodal AI]"
  },
  "at_this_moment": {
    "transcript": "and the results were absolutely stunning...",
    "speaker": "speaker_1 (Guest)",
    "emotion": {"energy": 0.94, "arousal": 0.91, "valence": 0.78},
    "topic": "Main Discussion: AI in Healthcare",
    "shot_type": "closeup",
    "quality": 82.5,
    "pacing": {"wpm": 165, "label": "fast_dialogue"},
    "on_screen_text": null,
    "profanity": false
  }
}
```

---

### clipcannon_get_frame_strip

Get a 3x3 grid of frames from a specific time range (~1,454 tokens for image).

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| start_ms | integer | Yes | Start of range |
| end_ms | integer | Yes | End of range |
| count | integer | No | Number of frames (default: 9, max: 9) |

**Response:** Returns composite 1044x1044 JPEG grid + per-cell metadata.

---

### clipcannon_get_storyboard

Get batched storyboard grids (12 per batch, ~24K tokens per batch).

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| batch | integer | No | Batch number 1-7 (default: 1) |
| start_ms | integer | No | Optional: get grids for specific time range instead |
| end_ms | integer | No | Optional: end of time range |

**Response (~24K tokens per batch of 12 grids):**
```json
{
  "batch": 1,
  "total_batches": 7,
  "grids": [
    {
      "grid_number": 1,
      "image": "[JPEG — 3x3 composite grid]",
      "cells": [
        {
          "cell_index": 0,
          "timestamp_ms": 0,
          "transcript_snippet": "Welcome back to...",
          "speaker": "Host",
          "energy": 0.38,
          "scene_id": "scene_001"
        }
      ]
    }
  ]
}
```

---

### clipcannon_search_content

Search video content semantically using sqlite-vec vector similarity.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| query | string | Yes | Natural language search query |
| limit | integer | No | Max results (default: 10) |
| search_type | string | No | "semantic" (text), "visual" (frames), or "both" (default: semantic) |

**Response (~5K tokens):**
```json
{
  "results": [
    {
      "type": "transcript",
      "segment_id": "seg_042",
      "start_ms": 185200,
      "end_ms": 192800,
      "text": "And that's when we realized the whole approach was wrong.",
      "speaker": "Guest",
      "similarity_score": 0.89,
      "energy": 0.72
    }
  ],
  "total_results": 5,
  "search_time_ms": 12
}
```

---

## 4. Provenance Tools (4 tools)

### clipcannon_provenance_verify

Verify the entire provenance chain for a project.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |

**Response:**
```json
{
  "integrity": "verified",
  "total_records": 19,
  "chain_valid": true,
  "file_hashes_valid": true,
  "issues": []
}
```

Or on failure:
```json
{
  "integrity": "broken",
  "total_records": 19,
  "chain_valid": false,
  "broken_at": "prov_007",
  "issue": "Output hash mismatch: file was modified after provenance recording"
}
```

---

### clipcannon_provenance_query

Query provenance records for a project.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| operation | string | No | Filter by operation (e.g., "transcribe") |
| stage | string | No | Filter by stage ("understanding") |

**Response:** Array of provenance records.

---

### clipcannon_provenance_chain

Get the full chain from source to a specific output.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| record_id | string | No | Target record (default: latest) |

**Response:** Ordered list of provenance records forming the chain from GENESIS to target.

---

### clipcannon_provenance_timeline

Get a timeline visualization of all provenance records.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |

**Response:** Chronological list with duration, operation, and chain hash summary.

---

## 5. Disk Management Tools (2 tools)

### clipcannon_disk_status

Get disk usage by tier for a project.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |

**Response:**
```json
{
  "project_id": "proj_a1b2c3d4",
  "tiers": {
    "sacred": {"files": 2, "size_mb": 4096},
    "regenerable": {"files": 7282, "size_mb": 2048},
    "ephemeral": {"files": 0, "size_mb": 0}
  },
  "total_mb": 6144,
  "system_free_mb": 245000
}
```

---

### clipcannon_disk_cleanup

Free disk space by deleting regenerable files.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| project_id | string | Yes | Project ID |
| target_free_gb | number | No | Target free space in GB |

**Response:**
```json
{
  "freed_mb": 2048,
  "deleted": ["frames (7200 files)", "storyboards (80 files)"],
  "kept": ["source video", "analysis.db", "stems"]
}
```

---

## 6. Configuration Tools (3 tools)

### clipcannon_config_get

Get a configuration value.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| key | string | Yes | Dot-notation key (e.g., "processing.whisper_model") |

---

### clipcannon_config_set

Set a configuration value.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| key | string | Yes | Dot-notation key |
| value | any | Yes | New value |

---

### clipcannon_config_list

List all configuration values.

---

## 7. Billing Tools (4 tools)

### clipcannon_credits_balance

Get current credit balance.

**Response:**
```json
{
  "balance": 842,
  "spending_limit_monthly": 200,
  "spent_this_month": 58,
  "spending_pct": 29
}
```

---

### clipcannon_credits_history

Get credit transaction history.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| limit | integer | No | Max results (default: 20) |

---

### clipcannon_credits_estimate

Estimate credit cost for an operation.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| operation | string | Yes | "analyze", "render", "publish", etc. |
| project_id | string | No | For context-aware estimates |

---

### clipcannon_spending_limit

Set monthly spending limit.

**Parameters:**
| Name | Type | Required | Description |
|:-----|:-----|:---------|:-----------|
| limit_dollars | number | Yes | Monthly limit ($5 - $500) |

---

## Summary: Phase 1 Tool Count

| Category | Count |
|:---------|:------|
| Project Management | 5 |
| Video Understanding | 9 |
| Provenance | 4 |
| Disk Management | 2 |
| Configuration | 3 |
| Billing | 4 |
| **Total Phase 1** | **27 tools** |

---

*End of Phase 1 MCP Tool Spec*
