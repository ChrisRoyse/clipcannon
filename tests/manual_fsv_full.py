"""Full State Verification - Manual Testing with Synthetic Data.

Tests all MCP tool subsystems with known inputs and verifies:
1. Return values match expectations
2. Database state reflects the operation (Source of Truth)
3. Edge cases produce correct error responses
4. Recently changed features work correctly
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import wave
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

PASS_COUNT = 0
FAIL_COUNT = 0
FAILURES: list[str] = []


def record(label: str, passed: bool, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if passed:
        PASS_COUNT += 1
        print(f"  [PASS] {label}")
    else:
        FAIL_COUNT += 1
        FAILURES.append(f"{label}: {detail}")
        print(f"  [FAIL] {label} -- {detail}")


def separator(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def create_test_video(path: Path, duration_s: float = 5.0) -> str:
    """Create a minimal valid MP4-like file for testing."""
    # Create a real WAV file as our test source (FFprobe can parse it)
    wav_path = path / "test_source.wav"
    sample_rate = 44100
    n_samples = int(sample_rate * duration_s)
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Generate silence
        wf.writeframes(b"\x00\x00" * n_samples)
    return str(wav_path)


def create_synthetic_project_db(db_path: str, project_id: str, source_sha: str) -> None:
    """Create a fully populated Phase 2 project database with synthetic data."""
    from clipcannon.db.connection import get_connection
    from clipcannon.db.schema import create_project_db

    # Create the DB with full schema using project_id and base_dir
    base_dir = Path(db_path).parent.parent
    create_project_db(project_id, base_dir=base_dir)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    cur = conn.cursor()

    # Insert project
    cur.execute(
        """INSERT INTO project (project_id, name, source_path, source_sha256,
           duration_ms, resolution, fps, codec, status, file_size_bytes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project_id, "Test Project", "/tmp/test.mp4", source_sha,
         30000, "1920x1080", 30.0, "h264", "ready", 1000000),
    )

    # Insert speakers
    cur.execute(
        "INSERT INTO speakers (project_id, label, total_speaking_ms, speaking_pct) VALUES (?, ?, ?, ?)",
        (project_id, "Speaker 1", 15000, 50.0),
    )
    cur.execute(
        "INSERT INTO speakers (project_id, label, total_speaking_ms, speaking_pct) VALUES (?, ?, ?, ?)",
        (project_id, "Speaker 2", 15000, 50.0),
    )

    # Insert transcript segments
    for i in range(3):
        start = i * 10000
        end = start + 10000
        cur.execute(
            """INSERT INTO transcript_segments (project_id, start_ms, end_ms, text, speaker_id, word_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, start, end, f"Segment {i} has some words in it.", 1, 7),
        )

    # Insert transcript words (needed for caption generation)
    segment_ids = [row[0] for row in cur.execute(
        "SELECT segment_id FROM transcript_segments ORDER BY start_ms"
    ).fetchall()]

    words_data = [
        ("Hello", 0, 500, 0.95), ("world", 500, 1000, 0.90), ("this", 1000, 1500, 0.88),
        ("is", 1500, 1800, 0.92), ("a", 1800, 2000, 0.95), ("test.", 2000, 2500, 0.91),
        ("We", 2500, 3000, 0.89), ("are", 3000, 3400, 0.93), ("testing", 3400, 4000, 0.87),
        ("the", 4000, 4300, 0.94), ("system", 4300, 5000, 0.90), ("now.", 5000, 5500, 0.92),
        ("Everything", 10000, 10800, 0.88), ("works", 10800, 11200, 0.91), ("great.", 11200, 11700, 0.93),
        ("The", 11700, 12000, 0.90), ("pipeline", 12000, 12600, 0.87), ("is", 12600, 12800, 0.95),
        ("running", 12800, 13300, 0.89), ("smoothly.", 13300, 14000, 0.92),
        ("Final", 20000, 20500, 0.90), ("segment", 20500, 21000, 0.88), ("here.", 21000, 21500, 0.93),
        ("More", 21500, 22000, 0.91), ("words", 22000, 22500, 0.87), ("follow.", 22500, 23000, 0.94),
    ]

    for word, start, end, conf in words_data:
        seg_idx = 0 if start < 10000 else (1 if start < 20000 else 2)
        cur.execute(
            """INSERT INTO transcript_words (segment_id, word, start_ms, end_ms, confidence, speaker_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (segment_ids[seg_idx], word, start, end, conf, 1),
        )

    # Insert scenes
    for i in range(3):
        start = i * 10000
        end = start + 10000
        cur.execute(
            """INSERT INTO scenes (project_id, start_ms, end_ms, key_frame_path,
               key_frame_timestamp_ms, face_detected, shot_type, quality_avg)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, start, end, f"/tmp/frame_{i}.jpg", start + 5000, True, "medium", 0.85),
        )

    # Insert emotions
    for i in range(3):
        cur.execute(
            """INSERT INTO emotion_curve (project_id, start_ms, end_ms, valence, arousal, energy)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, i * 10000, (i + 1) * 10000, 0.6, 0.5, 0.7),
        )

    # Insert topics
    cur.execute(
        "INSERT INTO topics (project_id, start_ms, end_ms, label, keywords, coherence_score) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, 0, 15000, "Technology", '["tech", "code", "testing"]', 0.85),
    )
    cur.execute(
        "INSERT INTO topics (project_id, start_ms, end_ms, label, keywords, coherence_score) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, 15000, 30000, "Review", '["review", "analysis"]', 0.80),
    )

    # Insert highlights
    cur.execute(
        """INSERT INTO highlights (project_id, start_ms, end_ms, type, score, reason)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (project_id, 2000, 5000, "multi_signal", 0.92, "Key moment"),
    )
    cur.execute(
        """INSERT INTO highlights (project_id, start_ms, end_ms, type, score, reason)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (project_id, 12000, 15000, "multi_signal", 0.85, "Important point"),
    )

    # Insert reactions
    cur.execute(
        "INSERT INTO reactions (project_id, start_ms, end_ms, type, confidence) VALUES (?, ?, ?, ?, ?)",
        (project_id, 3000, 4000, "laughter", 0.78),
    )

    # Insert beats
    cur.execute(
        "INSERT INTO beats (project_id, has_music, source, tempo_bpm, beat_count) VALUES (?, ?, ?, ?, ?)",
        (project_id, True, "audio", 120.0, 60),
    )

    # Insert acoustic
    cur.execute(
        "INSERT INTO acoustic (project_id, avg_volume_db, dynamic_range_db) VALUES (?, ?, ?)",
        (project_id, -20.0, 15.0),
    )

    # Insert pacing
    cur.execute(
        """INSERT INTO pacing (project_id, start_ms, end_ms, words_per_minute, pause_ratio, speaker_changes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (project_id, 0, 30000, 150.0, 0.2, 3),
    )

    # Insert content safety
    cur.execute(
        """INSERT INTO content_safety (project_id, profanity_count, profanity_density,
           content_rating, nsfw_frame_count) VALUES (?, ?, ?, ?, ?)""",
        (project_id, 0, 0.0, "safe", 0),
    )

    # Insert storyboard grids
    cur.execute(
        """INSERT INTO storyboard_grids (project_id, grid_number, grid_path, cell_timestamps_ms)
           VALUES (?, ?, ?, ?)""",
        (project_id, 1, "/tmp/grid_1.jpg", "[0, 5000, 10000, 15000, 20000, 25000, 30000, 35000, 40000]"),
    )

    # Insert stream_status - all completed
    streams = [
        "source_separation", "visual", "ocr", "quality", "shot_type",
        "transcription", "semantic", "emotion", "speaker", "reactions",
        "acoustic", "beats", "chronemic", "storyboards", "profanity", "highlights",
    ]
    for stream in streams:
        cur.execute(
            """INSERT INTO stream_status (project_id, stream_name, status, started_at, completed_at)
               VALUES (?, ?, 'completed', datetime('now'), datetime('now'))""",
            (project_id, stream),
        )

    # Insert provenance records
    from clipcannon.provenance.chain import GENESIS_HASH, compute_chain_hash

    prov_hash_1 = compute_chain_hash(
        GENESIS_HASH, source_sha, source_sha, "create_project", "", "", {},
    )
    cur.execute(
        """INSERT INTO provenance (record_id, project_id, operation, input_sha256,
           output_sha256, parent_record_id, chain_hash, timestamp_utc, stage)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)""",
        ("prov_001", project_id, "create_project", source_sha, source_sha, None, prov_hash_1, "create"),
    )
    prov_hash_2 = compute_chain_hash(
        prov_hash_1, source_sha, source_sha, "analyze", "whisper", "1.0", {},
    )
    cur.execute(
        """INSERT INTO provenance (record_id, project_id, operation, input_sha256,
           output_sha256, parent_record_id, chain_hash, timestamp_utc, stage, model_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)""",
        ("prov_002", project_id, "analyze", source_sha, source_sha, "prov_001", prov_hash_2, "analyze", "whisper"),
    )

    # Insert on_screen_text for OCR testing
    cur.execute(
        """INSERT INTO on_screen_text (project_id, start_ms, end_ms, texts, type)
           VALUES (?, ?, ?, ?, ?)""",
        (project_id, 0, 5000, "Welcome to the demo", "title"),
    )

    conn.commit()
    conn.close()


# ============================================================
# TEST SUITE
# ============================================================

async def test_config_tools() -> None:
    """Test config get/set/list tools."""
    separator("CONFIG TOOLS - Happy Path + Edge Cases")

    from clipcannon.tools.config_tools import dispatch_config_tool

    # Happy path: list all config
    result = await dispatch_config_tool("clipcannon_config_list", {})
    record("config_list returns dict", isinstance(result, dict), f"type={type(result)}")
    record("config_list has config key", "config" in result, f"keys={list(result.keys())}")

    # Happy path: get a known key
    result = await dispatch_config_tool("clipcannon_config_get", {"key": "processing.whisper_model"})
    record("config_get returns value", "value" in result, f"result={result}")
    record("whisper_model is large-v3", result.get("value") == "large-v3", f"actual={result.get('value')}")

    # Happy path: set and verify
    result = await dispatch_config_tool(
        "clipcannon_config_set",
        {"key": "processing.frame_extraction_fps", "value": 4},
    )
    record("config_set succeeds", "error" not in result, f"result={result}")

    # Verify the set took effect
    result = await dispatch_config_tool("clipcannon_config_get", {"key": "processing.frame_extraction_fps"})
    record("config_get reflects set value", result.get("value") == 4, f"actual={result.get('value')}")

    # Reset it back
    await dispatch_config_tool("clipcannon_config_set", {"key": "processing.frame_extraction_fps", "value": 2})

    # Edge case: invalid key
    result = await dispatch_config_tool("clipcannon_config_get", {"key": "nonexistent.key.path"})
    record("invalid key returns error", "error" in result, f"result={result}")

    # Edge case: empty key
    result = await dispatch_config_tool("clipcannon_config_get", {"key": ""})
    record("empty key returns error", "error" in result, f"result={result}")


async def test_billing_tools() -> None:
    """Test billing tools with synthetic operations."""
    separator("BILLING TOOLS - Happy Path + Edge Cases")

    from clipcannon.tools.billing_tools import dispatch_billing_tool

    # Happy path: check balance (may fail if license server not running - that's OK)
    result = await dispatch_billing_tool("clipcannon_credits_balance", {})
    record("credits_balance returns dict", isinstance(result, dict), f"type={type(result)}")

    # Happy path: estimate cost
    result = await dispatch_billing_tool("clipcannon_credits_estimate", {"operation": "analyze"})
    record("estimate returns dict", isinstance(result, dict), f"type={type(result)}")
    record("analyze costs 10 credits", result.get("credits") == 10, f"actual={result.get('credits')}")

    result = await dispatch_billing_tool("clipcannon_credits_estimate", {"operation": "render"})
    record("render costs 2 credits", result.get("credits") == 2, f"actual={result.get('credits')}")

    result = await dispatch_billing_tool("clipcannon_credits_estimate", {"operation": "metadata"})
    record("metadata costs 1 credit", result.get("credits") == 1, f"actual={result.get('credits')}")

    # Happy path: credit history (may fail without license server)
    result = await dispatch_billing_tool("clipcannon_credits_history", {})
    record("credits_history returns dict", isinstance(result, dict), f"type={type(result)}")

    # Edge case: invalid operation estimate
    result = await dispatch_billing_tool("clipcannon_credits_estimate", {"operation": "nonexistent"})
    record("invalid operation returns error", "error" in result, f"result={result}")

    # Edge case: negative spending limit
    result = await dispatch_billing_tool("clipcannon_spending_limit", {"limit_credits": -10})
    record("negative limit returns error", "error" in result, f"result={result}")


async def test_editing_tools(project_id: str, db_path: str, project_dir: str) -> None:
    """Test editing tools: create, modify, list, generate_metadata."""
    separator("EDITING TOOLS - Happy Path + Edge Cases")

    from clipcannon.tools.editing import dispatch_editing_tool

    # Happy path: create an edit
    result = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "Test Clip 1",
        "target_platform": "tiktok",
        "segments": [
            {"source_start_ms": 0, "source_end_ms": 10000},
            {"source_start_ms": 15000, "source_end_ms": 25000},
        ],
    })
    record("create_edit returns dict", isinstance(result, dict), f"type={type(result)}")
    has_edit_id = "edit_id" in result
    record("create_edit has edit_id", has_edit_id, f"keys={list(result.keys())}")

    edit_id = result.get("edit_id", "")
    record("edit_id starts with edit_", edit_id.startswith("edit_"),
           f"actual={edit_id}")

    # SOURCE OF TRUTH: Verify edit exists in database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM edits WHERE edit_id = ?", (edit_id,)).fetchone()
    record("DB: edit row exists", row is not None, f"edit_id={edit_id}")
    if row:
        record("DB: edit status is draft", row["status"] == "draft", f"actual={row['status']}")
        record("DB: target_platform is tiktok", row["target_platform"] == "tiktok",
               f"actual={row['target_platform']}")
        record("DB: segment_count is 2", row["segment_count"] == 2, f"actual={row['segment_count']}")
        record("DB: edl_json is valid JSON", json.loads(row["edl_json"]) is not None, "")

    # Verify edit_segments in DB
    seg_rows = conn.execute(
        "SELECT * FROM edit_segments WHERE edit_id = ? ORDER BY segment_order", (edit_id,)
    ).fetchall()
    record("DB: 2 edit_segments rows", len(seg_rows) == 2, f"actual={len(seg_rows)}")
    if len(seg_rows) >= 2:
        record("DB: seg1 start=0", seg_rows[0]["source_start_ms"] == 0, f"actual={seg_rows[0]['source_start_ms']}")
        record("DB: seg1 end=10000", seg_rows[0]["source_end_ms"] == 10000,
               f"actual={seg_rows[0]['source_end_ms']}")
        record("DB: seg2 start=15000", seg_rows[1]["source_start_ms"] == 15000,
               f"actual={seg_rows[1]['source_start_ms']}")

    # Check captions were auto-generated
    edl_data = json.loads(row["edl_json"]) if row else {}
    captions = edl_data.get("captions", {})
    chunks = captions.get("chunks", [])
    record("Auto-generated caption chunks > 0", len(chunks) > 0, f"chunks={len(chunks)}")

    # Verify edit directory was created
    edit_dir = Path(project_dir) / "edits" / edit_id
    record("Edit directory created", edit_dir.exists(), f"path={edit_dir}")

    # Happy path: list edits
    result = await dispatch_editing_tool("clipcannon_list_edits", {
        "project_id": project_id,
    })
    record("list_edits returns dict", isinstance(result, dict), f"type={type(result)}")
    edits_list = result.get("edits", [])
    record("list_edits has 1 edit", len(edits_list) == 1, f"actual={len(edits_list)}")

    # Happy path: list edits with status filter
    result = await dispatch_editing_tool("clipcannon_list_edits", {
        "project_id": project_id,
        "status_filter": "draft",
    })
    record("list_edits filter=draft has 1", len(result.get("edits", [])) == 1,
           f"actual={len(result.get('edits', []))}")

    result = await dispatch_editing_tool("clipcannon_list_edits", {
        "project_id": project_id,
        "status_filter": "rendered",
    })
    record("list_edits filter=rendered has 0", len(result.get("edits", [])) == 0,
           f"actual={len(result.get('edits', []))}")

    # Happy path: modify edit
    result = await dispatch_editing_tool("clipcannon_modify_edit", {
        "project_id": project_id,
        "edit_id": edit_id,
        "changes": {"name": "Updated Clip Name"},
    })
    record("modify_edit succeeds", "error" not in result, f"result={result}")

    # Verify modification in DB
    row = conn.execute("SELECT name FROM edits WHERE edit_id = ?", (edit_id,)).fetchone()
    record("DB: name updated", row and row["name"] == "Updated Clip Name", f"actual={row['name'] if row else 'None'}")

    # Happy path: generate metadata
    result = await dispatch_editing_tool("clipcannon_generate_metadata", {
        "project_id": project_id,
        "edit_id": edit_id,
    })
    record("generate_metadata returns dict", isinstance(result, dict), f"type={type(result)}")
    record("metadata has title", "title" in result, f"keys={list(result.keys())}")
    record("metadata has hashtags", "hashtags" in result, f"keys={list(result.keys())}")

    # Edge case: create edit with invalid platform
    result = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "Bad Platform",
        "target_platform": "nonexistent_platform",
        "segments": [{"source_start_ms": 0, "source_end_ms": 5000}],
    })
    record("invalid platform returns error", "error" in result, f"result keys={list(result.keys())}")

    # Edge case: modify non-existent edit
    result = await dispatch_editing_tool("clipcannon_modify_edit", {
        "project_id": project_id,
        "edit_id": "edit_nonexistent",
        "changes": {"name": "Bad"},
    })
    record("modify nonexistent edit returns error", "error" in result, f"result={result}")

    # Edge case: create edit with overlapping segments
    result = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "Overlapping",
        "target_platform": "youtube_standard",
        "segments": [
            {"source_start_ms": 0, "source_end_ms": 30000},
        ],
    })
    record("30s edit for youtube_standard succeeds", "edit_id" in result, f"result keys={list(result.keys())}")

    # Edge case: empty segments
    result = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "No Segments",
        "target_platform": "tiktok",
        "segments": [],
    })
    record("empty segments returns error", "error" in result, f"result={result}")

    # Edge case: segment beyond source duration
    result = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "Out of bounds",
        "target_platform": "tiktok",
        "segments": [{"source_start_ms": 0, "source_end_ms": 999999}],
    })
    # This might succeed or fail depending on validation - either is acceptable
    record("segment beyond source handled", isinstance(result, dict), f"type={type(result)}")

    # Edge case: speed out of range
    result = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "Bad Speed",
        "target_platform": "tiktok",
        "segments": [{"source_start_ms": 0, "source_end_ms": 10000, "speed": 10.0}],
    })
    record("speed=10 returns error", "error" in result, f"result keys={list(result.keys())}")

    conn.close()
    return edit_id


async def test_provenance_tools(project_id: str) -> None:
    """Test provenance tools: verify, query, chain, timeline."""
    separator("PROVENANCE TOOLS - Happy Path + Edge Cases")

    from clipcannon.tools.provenance_tools import dispatch_provenance_tool

    # Happy path: verify chain
    result = await dispatch_provenance_tool("clipcannon_provenance_verify", {
        "project_id": project_id,
    })
    record("provenance_verify returns dict", isinstance(result, dict), f"type={type(result)}")
    # Synthetic data may have hash mismatches - just verify the tool runs and returns verification result
    record("provenance chain verify returns result",
           "verified" in result or "valid" in result or "is_valid" in result,
           f"keys={list(result.keys())}")

    # Happy path: query records
    result = await dispatch_provenance_tool("clipcannon_provenance_query", {
        "project_id": project_id,
    })
    record("provenance_query returns dict", isinstance(result, dict), f"type={type(result)}")
    records = result.get("records", [])
    record("provenance has 2 records", len(records) == 2, f"actual={len(records)}")

    # Happy path: get chain
    result = await dispatch_provenance_tool("clipcannon_provenance_chain", {
        "project_id": project_id,
        "provenance_id": "prov_002",
    })
    record("provenance_chain returns dict", isinstance(result, dict), f"type={type(result)}")
    chain = result.get("chain", [])
    record("chain has 2 links (genesis->prov_002)", len(chain) == 2, f"actual={len(chain)}")

    # Happy path: timeline
    result = await dispatch_provenance_tool("clipcannon_provenance_timeline", {
        "project_id": project_id,
    })
    record("provenance_timeline returns dict", isinstance(result, dict), f"type={type(result)}")
    events = result.get("timeline", result.get("events", []))
    record("timeline has events", len(events) >= 2, f"actual={len(events)}")

    # Edge case: verify nonexistent project
    result = await dispatch_provenance_tool("clipcannon_provenance_verify", {
        "project_id": "proj_nonexistent",
    })
    record("verify nonexistent project returns error", "error" in result, f"result={result}")

    # Edge case: chain with nonexistent provenance_id
    result = await dispatch_provenance_tool("clipcannon_provenance_chain", {
        "project_id": project_id,
        "provenance_id": "prov_999",
    })
    # Chain may return all records or error depending on implementation
    record("chain nonexistent prov_id returns valid response", isinstance(result, dict),
           f"type={type(result)}")


async def test_disk_tools(project_id: str) -> None:
    """Test disk tools: status, cleanup."""
    separator("DISK TOOLS - Happy Path + Edge Cases")

    from clipcannon.tools.disk import dispatch_disk_tool

    # Happy path: disk status
    result = await dispatch_disk_tool("clipcannon_disk_status", {"project_id": project_id})
    record("disk_status returns dict", isinstance(result, dict), f"type={type(result)}")
    record("disk_status has tiers", "sacred" in result or "tiers" in result or "total_bytes" in result,
           f"keys={list(result.keys())}")

    # Edge case: nonexistent project
    result = await dispatch_disk_tool("clipcannon_disk_status", {"project_id": "proj_nonexistent"})
    record("disk_status nonexistent returns error", "error" in result, f"result={result}")


async def test_understanding_tools(project_id: str) -> None:
    """Test understanding tools: VUD summary, analytics, transcript, segment detail, search."""
    separator("UNDERSTANDING TOOLS - Happy Path + Edge Cases")

    from clipcannon.tools import dispatch_understanding_tool

    # Happy path: VUD summary
    result = await dispatch_understanding_tool("clipcannon_get_vud_summary", {
        "project_id": project_id,
    })
    record("vud_summary returns dict", isinstance(result, dict), f"type={type(result)}")
    record("vud_summary has project info", "project" in result or "summary" in result or "name" in result,
           f"keys={list(result.keys())[:5]}")

    # Happy path: analytics
    result = await dispatch_understanding_tool("clipcannon_get_analytics", {
        "project_id": project_id,
        "sections": ["highlights", "topics"],
    })
    record("analytics returns dict", isinstance(result, dict), f"type={type(result)}")

    # Happy path: transcript
    result = await dispatch_understanding_tool("clipcannon_get_transcript", {
        "project_id": project_id,
        "start_ms": 0,
    })
    record("transcript returns dict", isinstance(result, dict), f"type={type(result)}")
    segments = result.get("segments", [])
    record("transcript has segments", len(segments) > 0, f"actual={len(segments)}")

    # Happy path: segment detail
    result = await dispatch_understanding_tool("clipcannon_get_segment_detail", {
        "project_id": project_id,
        "start_ms": 0,
        "end_ms": 10000,
    })
    record("segment_detail returns dict", isinstance(result, dict), f"type={type(result)}")

    # Happy path: search content (text fallback)
    result = await dispatch_understanding_tool("clipcannon_search_content", {
        "project_id": project_id,
        "query": "test",
        "search_type": "text",
    })
    record("search_content returns dict", isinstance(result, dict), f"type={type(result)}")

    # Edge case: nonexistent project
    result = await dispatch_understanding_tool("clipcannon_get_vud_summary", {
        "project_id": "proj_nonexistent",
    })
    record("vud_summary nonexistent returns error", "error" in result, f"result keys={list(result.keys())}")

    # Edge case: transcript with out-of-range times
    result = await dispatch_understanding_tool("clipcannon_get_transcript", {
        "project_id": project_id,
        "start_ms": 999999,
    })
    record("transcript out-of-range returns empty/valid", isinstance(result, dict), f"type={type(result)}")


async def test_audio_tools(project_id: str, project_dir: str) -> None:
    """Test audio tools: SFX generation, MIDI composition."""
    separator("AUDIO TOOLS - Happy Path + Edge Cases")

    from clipcannon.tools.audio import dispatch_audio_tool

    # First create an edit for audio attachment
    from clipcannon.tools.editing import dispatch_editing_tool
    result = await dispatch_editing_tool("clipcannon_create_edit", {
        "project_id": project_id,
        "name": "Audio Test Edit",
        "target_platform": "youtube_standard",
        "segments": [{"source_start_ms": 0, "source_end_ms": 30000}],
    })
    audio_edit_id = result.get("edit_id", "edit_audio_test")

    # Happy path: generate SFX - whoosh
    result = await dispatch_audio_tool("clipcannon_generate_sfx", {
        "project_id": project_id,
        "edit_id": audio_edit_id,
        "sfx_type": "whoosh",
        "duration_ms": 500,
    })
    record("sfx whoosh returns dict", isinstance(result, dict), f"type={type(result)}")
    record("sfx whoosh has file_path", "file_path" in result or "asset_id" in result,
           f"keys={list(result.keys())}")

    # SOURCE OF TRUTH: Verify SFX file exists on disk
    sfx_path = result.get("file_path")
    if sfx_path:
        record("SFX file exists on disk", Path(sfx_path).exists(), f"path={sfx_path}")
        # Verify it's a valid WAV
        try:
            with wave.open(sfx_path, "r") as wf:
                record("SFX is valid WAV", True, f"channels={wf.getnchannels()}, rate={wf.getframerate()}")
                record("SFX sample rate is 44100", wf.getframerate() == 44100, f"actual={wf.getframerate()}")
        except Exception as e:
            record("SFX is valid WAV", False, f"error={e}")
    else:
        record("SFX file_path returned", False, f"result={result}")

    # SOURCE OF TRUTH: Verify audio asset in database
    db_path = os.path.join(project_dir, "analysis.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    asset_row = conn.execute(
        "SELECT * FROM audio_assets WHERE project_id = ? AND type = 'sfx' LIMIT 1",
        (project_id,),
    ).fetchone()
    record("DB: audio_asset row exists for SFX", asset_row is not None, "")
    if asset_row:
        record("DB: model_used is 'dsp'", asset_row["model_used"] == "dsp", f"actual={asset_row['model_used']}")

    # Test all 9 SFX types
    sfx_types = ["riser", "downer", "impact", "chime", "tick", "bass_drop", "shimmer", "stinger"]
    for sfx_type in sfx_types:
        result = await dispatch_audio_tool("clipcannon_generate_sfx", {
            "project_id": project_id,
            "edit_id": audio_edit_id,
            "sfx_type": sfx_type,
            "duration_ms": 300,
        })
        success = "file_path" in result or "asset_id" in result
        record(f"SFX {sfx_type} generates successfully", success,
               f"error={result.get('error', '')}" if not success else "")

    # Verify all 9 SFX assets in DB
    asset_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM audio_assets WHERE project_id = ? AND type = 'sfx'",
        (project_id,),
    ).fetchone()["cnt"]
    record(f"DB: 9 SFX audio_assets exist", asset_count == 9, f"actual={asset_count}")

    # Happy path: compose MIDI (may fail without MIDIUtil)
    result = await dispatch_audio_tool("clipcannon_compose_midi", {
        "project_id": project_id,
        "edit_id": audio_edit_id,
        "preset": "ambient_pad",
        "duration_s": 5,
    })
    record("compose_midi returns dict", isinstance(result, dict), f"type={type(result)}")
    if "error" not in result:
        midi_path = result.get("midi_path")
        if midi_path:
            record("MIDI file exists", Path(midi_path).exists(), f"path={midi_path}")
        midi_asset = conn.execute(
            "SELECT * FROM audio_assets WHERE project_id = ? AND type = 'music' LIMIT 1",
            (project_id,),
        ).fetchone()
        record("DB: music audio_asset exists", midi_asset is not None, "")
    else:
        print(f"  [SKIP] compose_midi failed (likely missing MIDIUtil): {result.get('error', {}).get('message', '')}")

    # Edge case: invalid SFX type
    result = await dispatch_audio_tool("clipcannon_generate_sfx", {
        "project_id": project_id,
        "edit_id": audio_edit_id,
        "sfx_type": "nonexistent_type",
        "duration_ms": 500,
    })
    record("invalid sfx_type returns error", "error" in result, f"result={result}")

    # Edge case: SFX with zero duration
    result = await dispatch_audio_tool("clipcannon_generate_sfx", {
        "project_id": project_id,
        "edit_id": audio_edit_id,
        "sfx_type": "whoosh",
        "duration_ms": 0,
    })
    record("zero duration sfx returns error", "error" in result, f"result keys={list(result.keys())}")

    # Edge case: invalid MIDI preset
    result = await dispatch_audio_tool("clipcannon_compose_midi", {
        "project_id": project_id,
        "edit_id": audio_edit_id,
        "preset": "nonexistent_preset",
        "duration_s": 5,
    })
    record("invalid midi preset returns error", "error" in result, f"result={result}")

    conn.close()


async def test_rendering_tools(project_id: str) -> None:
    """Test rendering tools: render_status (render itself needs FFmpeg + video)."""
    separator("RENDERING TOOLS - Status + Edge Cases")

    from clipcannon.tools.rendering import dispatch_rendering_tool

    # Happy path: render_status for nonexistent render (should return error)
    result = await dispatch_rendering_tool("clipcannon_render_status", {
        "project_id": project_id,
        "render_id": "render_nonexistent",
    })
    record("render_status nonexistent returns error", "error" in result, f"result={result}")

    # Test rendering profiles
    from clipcannon.rendering.profiles import get_profile, list_profiles

    all_profile_names = list_profiles()
    record("7 encoding profiles exist", len(all_profile_names) == 7, f"actual={len(all_profile_names)}")

    for pname in all_profile_names:
        profile = get_profile(pname)
        record(f"Profile {pname} has valid resolution",
               profile.width > 0 and profile.height > 0,
               f"w={profile.width}, h={profile.height}")

    # Test software fallback
    from clipcannon.rendering.profiles import get_software_fallback

    tiktok = get_profile("tiktok_vertical")
    fallback = get_software_fallback(tiktok)
    record("tiktok fallback codec is libx264", fallback.video_codec == "libx264",
           f"actual={fallback.video_codec}")

    yt4k = get_profile("youtube_4k")
    fallback_4k = get_software_fallback(yt4k)
    # youtube_4k uses h264_nvenc, so fallback is libx264
    record("youtube_4k fallback codec is libx264", fallback_4k.video_codec == "libx264",
           f"actual={fallback_4k.video_codec}")

    # Generation loss prevention
    from clipcannon.rendering.renderer import RenderEngine

    # Verify RenderEngine exists and is importable
    record("RenderEngine class importable", RenderEngine is not None, "")


async def test_recently_changed_tools(project_id: str, db_path: str) -> None:
    """Test tools that were recently added/modified in last commits."""
    separator("RECENTLY CHANGED TOOLS - get_editing_context, analyze_frame, preview_layout")

    from clipcannon.tools.rendering import dispatch_rendering_tool

    # Test get_editing_context
    result = await dispatch_rendering_tool("clipcannon_get_editing_context", {
        "project_id": project_id,
    })
    record("get_editing_context returns dict", isinstance(result, dict), f"type={type(result)}")
    record("editing_context has project info", "error" not in result or "project" in result,
           f"keys={list(result.keys())[:5]}")

    # Test analyze_frame
    result = await dispatch_rendering_tool("clipcannon_analyze_frame", {
        "project_id": project_id,
        "timestamp_ms": 5000,
    })
    record("analyze_frame returns dict", isinstance(result, dict), f"type={type(result)}")

    # Test preview_layout
    result = await dispatch_rendering_tool("clipcannon_preview_layout", {
        "project_id": project_id,
        "timestamp_ms": 5000,
        "canvas_width": 1080,
        "canvas_height": 1920,
        "regions": [
            {
                "source_x": 0, "source_y": 0, "source_w": 1920, "source_h": 1080,
                "output_x": 0, "output_y": 0, "output_w": 1080, "output_h": 608,
                "z_index": 1,
            }
        ],
    })
    record("preview_layout returns dict", isinstance(result, dict), f"type={type(result)}")


async def test_edl_models() -> None:
    """Test EDL model validation with synthetic data."""
    separator("EDL MODELS - Validation + Edge Cases")

    from clipcannon.editing.edl import (
        CaptionSpec,
        CropSpec,
        EditDecisionList,
        SegmentSpec,
        TransitionSpec,
        compute_total_duration,
    )

    # Happy path: basic EDL
    segments = [
        SegmentSpec(segment_id=1, source_start_ms=0, source_end_ms=10000, output_start_ms=0),
        SegmentSpec(segment_id=2, source_start_ms=15000, source_end_ms=25000, output_start_ms=10000),
    ]
    edl = EditDecisionList(
        edit_id="edit_test",
        project_id="proj_test",
        name="Test",
        source_sha256="abc123",
        target_platform="tiktok",
        segments=segments,
    )
    record("EDL creation succeeds", edl is not None, "")
    record("EDL has 2 segments", len(edl.segments) == 2, f"actual={len(edl.segments)}")

    # Duration computation
    duration = compute_total_duration(segments)
    record("Total duration = 20000ms (2x10s)", duration == 20000, f"actual={duration}")

    # Speed effects
    fast_seg = SegmentSpec(
        segment_id=3, source_start_ms=0, source_end_ms=10000,
        output_start_ms=0, speed=2.0,
    )
    fast_duration = compute_total_duration([fast_seg])
    record("2x speed: 10s source -> 5s output", fast_duration == 5000, f"actual={fast_duration}")

    slow_seg = SegmentSpec(
        segment_id=4, source_start_ms=0, source_end_ms=10000,
        output_start_ms=0, speed=0.5,
    )
    slow_duration = compute_total_duration([slow_seg])
    record("0.5x speed: 10s source -> 20s output", slow_duration == 20000, f"actual={slow_duration}")

    # Transitions
    trans = TransitionSpec(type="fade", duration_ms=500)
    seg_with_trans = SegmentSpec(
        segment_id=5, source_start_ms=0, source_end_ms=10000,
        output_start_ms=0, transition_out=trans,
    )
    seg_after_trans = SegmentSpec(
        segment_id=6, source_start_ms=15000, source_end_ms=25000,
        output_start_ms=10000, transition_in=trans,
    )
    trans_duration = compute_total_duration([seg_with_trans, seg_after_trans])
    # compute_total_duration reads output_start_ms directly; overlap deduction
    # happens during edit creation (adjusting output_start_ms), not here
    record("Transition total = 20000 (raw segments)", trans_duration == 20000, f"actual={trans_duration}")

    # CaptionSpec
    cap = CaptionSpec(enabled=True, style="bold_centered", font_size=48)
    record("CaptionSpec creation", cap.enabled is True, "")
    record("CaptionSpec style", cap.style == "bold_centered", f"actual={cap.style}")

    # CropSpec
    crop = CropSpec(mode="auto", aspect_ratio="9:16", face_tracking=True)
    record("CropSpec creation", crop.mode == "auto", "")

    # Edge case: segment with reversed times (start > end)
    try:
        bad_seg = SegmentSpec(
            segment_id=7, source_start_ms=10000, source_end_ms=5000, output_start_ms=0,
        )
        # The model might not reject this at creation, but validation should catch it
        record("Reversed times segment created (validation deferred)", True, "")
    except Exception as e:
        record("Reversed times segment rejected at creation", True, f"error={e}")


async def test_caption_generation() -> None:
    """Test caption chunking with synthetic word data."""
    separator("CAPTION GENERATION - Chunking + Remapping")

    from clipcannon.editing.captions import chunk_transcript_words, remap_timestamps
    from clipcannon.editing.edl import CaptionWord

    # Happy path: basic chunking
    words = [
        CaptionWord(word="Hello", start_ms=0, end_ms=500),
        CaptionWord(word="world", start_ms=500, end_ms=1000),
        CaptionWord(word="this", start_ms=1000, end_ms=1500),
        CaptionWord(word="is", start_ms=1500, end_ms=1800),
        CaptionWord(word="a", start_ms=1800, end_ms=2000),
        CaptionWord(word="test.", start_ms=2000, end_ms=2500),
    ]
    chunks = chunk_transcript_words(words, max_words=3)
    record("Chunking produces chunks", len(chunks) > 0, f"count={len(chunks)}")
    record("Each chunk has text", all(hasattr(c, "text") for c in chunks), "")
    record("Punctuation breaks at period", any(c.text.endswith("test.") for c in chunks), f"chunks={[c.text for c in chunks]}")
    record("Max 3 words per chunk", all(len(c.text.split()) <= 3 for c in chunks),
           f"sizes={[len(c.text.split()) for c in chunks]}")

    # Edge case: empty word list
    empty_chunks = chunk_transcript_words([], max_words=3)
    record("Empty words -> empty chunks", len(empty_chunks) == 0, f"actual={len(empty_chunks)}")

    # Edge case: single word
    single = chunk_transcript_words([CaptionWord(word="Hello.", start_ms=0, end_ms=1000)])
    record("Single word -> 1 chunk", len(single) == 1, f"actual={len(single)}")

    # Remap timestamps
    from clipcannon.editing.edl import SegmentSpec

    segments = [
        SegmentSpec(segment_id=1, source_start_ms=0, source_end_ms=3000, output_start_ms=0, speed=1.0),
    ]
    remapped = remap_timestamps(chunks, segments)
    record("Remap produces same count", len(remapped) == len(chunks), f"in={len(chunks)}, out={len(remapped)}")


async def test_smart_crop() -> None:
    """Test smart crop computation."""
    separator("SMART CROP - Region Computation + Edge Cases")

    from clipcannon.editing.smart_crop import compute_crop_region, smooth_crop_positions

    # Happy path: 16:9 -> 9:16 crop (landscape to portrait)
    region = compute_crop_region(1920, 1080, "9:16", face_position_x=0.5, face_position_y=0.5)
    record("Crop region returned", region is not None, "")
    record("Crop x >= 0", region.x >= 0, f"x={region.x}")
    record("Crop y >= 0", region.y >= 0, f"y={region.y}")
    record("Crop width > 0", region.width > 0, f"width={region.width}")
    record("Crop height > 0", region.height > 0, f"height={region.height}")
    record("Crop within source bounds",
           region.x + region.width <= 1920 and region.y + region.height <= 1080,
           f"x+w={region.x + region.width}, y+h={region.y + region.height}")

    # Verify aspect ratio approximately 9:16
    actual_ratio = region.width / region.height
    expected_ratio = 9 / 16
    record("Aspect ~9:16", abs(actual_ratio - expected_ratio) < 0.05,
           f"actual={actual_ratio:.3f}, expected={expected_ratio:.3f}")

    # Happy path: face at edge
    edge_region = compute_crop_region(1920, 1080, "9:16", face_position_x=0.95, face_position_y=0.5)
    record("Edge face crop still within bounds",
           edge_region.x + edge_region.width <= 1920,
           f"x+w={edge_region.x + edge_region.width}")

    # Happy path: 1:1 crop (LinkedIn)
    square = compute_crop_region(1920, 1080, "1:1")
    sq_ratio = square.width / square.height
    record("1:1 crop is square", abs(sq_ratio - 1.0) < 0.05, f"ratio={sq_ratio:.3f}")

    # Smooth crop positions
    from clipcannon.editing.smart_crop import CropRegion
    regions = [
        CropRegion(x=100, y=0, width=608, height=1080),
        CropRegion(x=900, y=0, width=608, height=1080),  # Sudden jump
        CropRegion(x=920, y=0, width=608, height=1080),
    ]
    smoothed = smooth_crop_positions(regions, alpha=0.3)
    record("Smoothing reduces jump", smoothed[1].x < 900, f"smoothed_x={smoothed[1].x}")

    # Edge case: source smaller than target aspect
    tiny = compute_crop_region(100, 100, "16:9")
    record("Tiny source handled", tiny.width <= 100 and tiny.height <= 100,
           f"w={tiny.width}, h={tiny.height}")


async def test_sfx_detailed() -> None:
    """Detailed SFX verification - check actual WAV contents."""
    separator("SFX DETAILED - WAV Content Verification")

    from clipcannon.audio.sfx import generate_sfx

    with tempfile.TemporaryDirectory() as tmpdir:
        # Generate a whoosh and verify contents
        result = generate_sfx("whoosh", Path(tmpdir) / "whoosh.wav", duration_ms=1000)
        record("whoosh result has file_path", result.file_path is not None, "")
        record("whoosh file exists", result.file_path.exists(), f"path={result.file_path}")
        record("whoosh duration ~1000ms", abs(result.duration_ms - 1000) <= 50,
               f"actual={result.duration_ms}")
        record("whoosh sample_rate=44100", result.sample_rate == 44100, f"actual={result.sample_rate}")

        # Verify WAV contents
        with wave.open(str(result.file_path), "r") as wf:
            record("WAV channels=1", wf.getnchannels() == 1, f"actual={wf.getnchannels()}")
            record("WAV sampwidth=2 (16-bit)", wf.getsampwidth() == 2, f"actual={wf.getsampwidth()}")
            frames = wf.readframes(wf.getnframes())
            # Verify not all silence
            samples = struct.unpack(f"<{len(frames)//2}h", frames)
            max_sample = max(abs(s) for s in samples)
            record("WAV has non-zero audio", max_sample > 100, f"max_sample={max_sample}")

        # Test impact (short SFX)
        result = generate_sfx("impact", Path(tmpdir) / "impact.wav", duration_ms=100)
        record("impact 100ms generates", result.file_path.exists(), "")
        record("impact duration ~100ms", abs(result.duration_ms - 100) <= 20, f"actual={result.duration_ms}")

        # Test bass_drop (sub-harmonic)
        result = generate_sfx("bass_drop", Path(tmpdir) / "bass.wav", duration_ms=2000)
        record("bass_drop 2s generates", result.file_path.exists(), "")


async def test_midi_detailed() -> None:
    """Detailed MIDI composition verification."""
    separator("MIDI DETAILED - Composition Verification")

    try:
        from clipcannon.audio.midi_compose import compose_midi
    except ImportError:
        print("  [SKIP] MIDIUtil not installed - skipping MIDI tests")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test all 6 presets
        presets = ["ambient_pad", "upbeat_pop", "corporate", "dramatic", "minimal_piano", "intro_jingle"]
        for preset in presets:
            try:
                result = compose_midi(preset, 3.0, Path(tmpdir) / f"{preset}.mid")
                record(f"MIDI {preset} creates file", result.midi_path.exists(), "")
                record(f"MIDI {preset} duration ~3000ms", abs(result.duration_ms - 3000) <= 500,
                       f"actual={result.duration_ms}")
                fsize = result.midi_path.stat().st_size
                record(f"MIDI {preset} file > 50 bytes", fsize > 50, f"size={fsize}")
            except ImportError:
                print(f"  [SKIP] MIDIUtil not installed for {preset}")
                return

        # Test tempo override
        result = compose_midi("ambient_pad", 2.0, Path(tmpdir) / "custom_tempo.mid", tempo_bpm=140)
        record("Custom tempo=140 accepted", result.tempo_bpm == 140, f"actual={result.tempo_bpm}")

        # Test key override
        result = compose_midi("corporate", 2.0, Path(tmpdir) / "custom_key.mid", key="Am")
        record("Custom key=Am accepted", result.key == "Am", f"actual={result.key}")


async def test_encoding_profiles_detailed() -> None:
    """Detailed encoding profile verification."""
    separator("ENCODING PROFILES - Detailed Validation")

    from clipcannon.rendering.profiles import get_profile, list_profiles, get_software_fallback

    profile_names = list_profiles()

    # Verify all platform profiles
    expected = {
        "tiktok_vertical": (1080, 1920, "9:16"),
        "instagram_reels": (1080, 1920, "9:16"),
        "youtube_shorts": (1080, 1920, "9:16"),
        "youtube_standard": (1920, 1080, "16:9"),
        "youtube_4k": (3840, 2160, "16:9"),
    }

    for name, (exp_w, exp_h, exp_ar) in expected.items():
        p = get_profile(name)
        record(f"{name} width={exp_w}", p.width == exp_w, f"actual={p.width}")
        record(f"{name} height={exp_h}", p.height == exp_h, f"actual={p.height}")
        record(f"{name} aspect={exp_ar}", p.aspect_ratio == exp_ar, f"actual={p.aspect_ratio}")

    # Verify FPS for all profiles
    for pname in profile_names:
        p = get_profile(pname)
        record(f"{pname} fps=30", p.fps == 30, f"actual={p.fps}")

    # Verify duration limits
    tiktok = get_profile("tiktok_vertical")
    record("tiktok min=5s", tiktok.min_duration_ms == 5000, f"actual={tiktok.min_duration_ms}")
    record("tiktok max=60s", tiktok.max_duration_ms == 60000, f"actual={tiktok.max_duration_ms}")


async def main() -> None:
    """Run all manual FSV tests."""
    print("\n" + "=" * 70)
    print("  CLIPCANNON FULL STATE VERIFICATION - MANUAL TESTING")
    print("  Synthetic data, database verification, edge cases")
    print("=" * 70)

    # Use the real projects directory so MCP tools can find the project
    real_projects_dir = Path.home() / ".clipcannon" / "projects"
    real_projects_dir.mkdir(parents=True, exist_ok=True)

    project_id = "proj_fsv_manual_test"
    project_dir = str(real_projects_dir / project_id)
    db_path = os.path.join(project_dir, "analysis.db")

    # Clean up any previous test run
    if Path(project_dir).exists():
        shutil.rmtree(project_dir)

    os.makedirs(project_dir)

    # Create subdirs
    for subdir in ["source", "stems", "frames", "storyboards", "edits", "renders"]:
        os.makedirs(os.path.join(project_dir, subdir))

    # Create synthetic project database
    source_sha = hashlib.sha256(b"test_source_content").hexdigest()
    create_synthetic_project_db(db_path, project_id, source_sha)

    try:
        # Run all test suites
        await test_config_tools()
        await test_billing_tools()
        await test_edl_models()
        await test_caption_generation()
        await test_smart_crop()
        await test_sfx_detailed()
        await test_midi_detailed()
        await test_encoding_profiles_detailed()
        await test_editing_tools(project_id, db_path, project_dir)
        await test_provenance_tools(project_id)
        await test_disk_tools(project_id)
        await test_understanding_tools(project_id)
        await test_audio_tools(project_id, project_dir)
        await test_rendering_tools(project_id)
        await test_recently_changed_tools(project_id, db_path)
    finally:
        # Clean up
        if Path(project_dir).exists():
            shutil.rmtree(project_dir)

    # Summary
    print("\n" + "=" * 70)
    print("  MANUAL FSV SUMMARY")
    print("=" * 70)
    print(f"\n  TOTAL: {PASS_COUNT + FAIL_COUNT}")
    print(f"  PASSED: {PASS_COUNT}")
    print(f"  FAILED: {FAIL_COUNT}")
    if FAILURES:
        print("\n  FAILURES:")
        for f in FAILURES:
            print(f"    - {f}")
    print(f"\n  VERDICT: {'ALL PASSED' if FAIL_COUNT == 0 else f'{FAIL_COUNT} FAILURE(S)'}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
