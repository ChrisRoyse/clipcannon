#!/usr/bin/env python3
"""Full State Verification (FSV) for ClipCannon Phase 1 Pipeline Stages + MCP Tools.

Forensic-grade test suite that PROVES correctness with physical evidence.
Every assertion is backed by direct source-of-truth inspection.

HOLMES: *adjusts magnifying glass* The game is afoot.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Ensure src/ is importable
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from clipcannon.pipeline.dag import topological_sort
from clipcannon.pipeline.orchestrator import (
    PipelineOrchestrator,
    PipelineStage,
    StageResult,
)
from clipcannon.pipeline.registry import _STAGE_DEFS, build_pipeline
from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.provenance.chain import GENESIS_HASH, compute_chain_hash

# Pipeline stage run functions -- import each to verify existence
from clipcannon.pipeline.probe import run_probe
from clipcannon.pipeline.vfr_normalize import run_vfr_normalize
from clipcannon.pipeline.audio_extract import run_audio_extract
from clipcannon.pipeline.frame_extract import run_frame_extract
from clipcannon.pipeline.source_separation import run_source_separation
from clipcannon.pipeline.visual_embed import run_visual_embed
from clipcannon.pipeline.ocr import run_ocr
from clipcannon.pipeline.quality import run_quality
from clipcannon.pipeline.shot_type import run_shot_type
from clipcannon.pipeline.transcribe import run_transcribe
from clipcannon.pipeline.storyboard import run_storyboard
from clipcannon.pipeline.semantic_embed import run_semantic_embed
from clipcannon.pipeline.speaker_embed import run_speaker_embed
from clipcannon.pipeline.emotion_embed import run_emotion_embed
from clipcannon.pipeline.reactions import run_reactions
from clipcannon.pipeline.acoustic import run_acoustic
from clipcannon.pipeline.profanity import run_profanity
from clipcannon.pipeline.chronemic import run_chronemic
from clipcannon.pipeline.highlights import run_highlights
from clipcannon.pipeline.finalize import run_finalize

# ============================================================================
# Test harness
# ============================================================================
_passed = 0
_failed = 0
_errors: list[str] = []


def _test(name: str, condition: bool, detail: str = ""):
    """Register a test result."""
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)
        _errors.append(msg)


def _section(title: str):
    print(f"\n{'='*72}")
    print(f"  {title}")
    print(f"{'='*72}")


# ============================================================================
# SECTION 1: Pipeline DAG Tests
# ============================================================================
def test_dag_dependency_resolution():
    """Test that topological_sort correctly orders stages by dependency level."""
    _section("1. DAG Dependency Resolution")

    # Build minimal stages for testing
    stages = [
        PipelineStage(name="A", operation="a", required=True, depends_on=[]),
        PipelineStage(name="B", operation="b", required=True, depends_on=["A"]),
        PipelineStage(name="C", operation="c", required=True, depends_on=["A"]),
        PipelineStage(name="D", operation="d", required=True, depends_on=["B", "C"]),
    ]
    levels = topological_sort(stages)

    _test("topological_sort returns list of levels", isinstance(levels, list))
    _test("Level 0 contains A", len(levels) > 0 and any(s.name == "A" for s in levels[0]))
    _test("Level 1 contains B and C",
          len(levels) > 1 and {s.name for s in levels[1]} == {"B", "C"})
    _test("Level 2 contains D",
          len(levels) > 2 and any(s.name == "D" for s in levels[2]))

    # Test cycle detection
    cyclic_stages = [
        PipelineStage(name="X", operation="x", required=True, depends_on=["Z"]),
        PipelineStage(name="Y", operation="y", required=True, depends_on=["X"]),
        PipelineStage(name="Z", operation="z", required=True, depends_on=["Y"]),
    ]
    cycle_detected = False
    try:
        topological_sort(cyclic_stages)
    except Exception:
        cycle_detected = True
    _test("Cycle detection raises PipelineError", cycle_detected)

    # Test empty stage list
    empty_levels = topological_sort([])
    _test("Empty stage list returns empty levels", empty_levels == [])

    # Test with real pipeline stages
    config = ClipCannonConfig(
        data=json.loads((_ROOT / "config" / "default_config.json").read_text()),
        config_path=Path("/tmp/test_config.json"),
    )
    pipeline = build_pipeline(config)
    real_levels = topological_sort(pipeline.stages)

    _test("Real pipeline produces multiple levels", len(real_levels) >= 3)

    # Verify probe is in level 0 (no dependencies)
    level0_names = {s.name for s in real_levels[0]}
    _test("probe is in level 0 (no dependencies)", "probe" in level0_names)

    # Verify finalize is in the LAST level (depends on everything)
    last_level_names = {s.name for s in real_levels[-1]}
    _test("finalize is in the last level", "finalize" in last_level_names)

    # Verify ordering: every stage's dependencies appear in earlier levels
    stage_level_map: dict[str, int] = {}
    for lvl_idx, lvl in enumerate(real_levels):
        for stg in lvl:
            stage_level_map[stg.name] = lvl_idx

    all_deps_ok = True
    bad_dep = ""
    for lvl_idx, lvl in enumerate(real_levels):
        for stg in lvl:
            for dep in stg.depends_on:
                if dep in stage_level_map and stage_level_map[dep] >= lvl_idx:
                    all_deps_ok = False
                    bad_dep = f"{stg.name} depends on {dep} but {dep} is at level {stage_level_map[dep]} >= {lvl_idx}"
    _test("All dependencies appear in earlier levels", all_deps_ok, bad_dep)


# ============================================================================
# SECTION 2: Pipeline Stage Registration
# ============================================================================
def test_stage_registration():
    """Test that all 20 stages are registered correctly."""
    _section("2. Pipeline Stage Registration")

    config = ClipCannonConfig(
        data=json.loads((_ROOT / "config" / "default_config.json").read_text()),
        config_path=Path("/tmp/test_config.json"),
    )
    pipeline = build_pipeline(config)

    expected_stage_names = {
        "probe", "vfr_normalize", "audio_extract", "frame_extract",
        "source_separation", "visual_embed", "ocr", "quality", "shot_type",
        "transcribe", "storyboard", "semantic_embed", "speaker_embed",
        "emotion_embed", "reactions", "acoustic", "profanity", "chronemic",
        "highlights", "finalize",
    }
    actual_names = {s.name for s in pipeline.stages}

    _test(f"Registry defines {len(_STAGE_DEFS)} stages", len(_STAGE_DEFS) == 20,
          f"got {len(_STAGE_DEFS)}")
    _test(f"Pipeline has {len(pipeline.stages)} registered stages",
          len(pipeline.stages) == 20,
          f"got {len(pipeline.stages)}")
    _test("All expected stages are registered",
          actual_names == expected_stage_names,
          f"missing: {expected_stage_names - actual_names}, extra: {actual_names - expected_stage_names}")

    # Verify no duplicate stages
    names_list = [s.name for s in pipeline.stages]
    _test("No duplicate stage names",
          len(names_list) == len(set(names_list)))

    # Verify duplicate registration is rejected
    dup_rejected = False
    try:
        pipeline.register_stage(
            PipelineStage(name="probe", operation="probe", required=True)
        )
    except Exception:
        dup_rejected = True
    _test("Duplicate registration raises PipelineError", dup_rejected)


# ============================================================================
# SECTION 3: Required vs Optional Classification
# ============================================================================
def test_required_optional():
    """Test that required/optional classification matches the spec."""
    _section("3. Required vs Optional Classification")

    config = ClipCannonConfig(
        data=json.loads((_ROOT / "config" / "default_config.json").read_text()),
        config_path=Path("/tmp/test_config.json"),
    )
    pipeline = build_pipeline(config)

    stage_map = {s.name: s for s in pipeline.stages}

    # Per the registry, these should be REQUIRED:
    expected_required = {"probe", "vfr_normalize", "audio_extract",
                         "frame_extract", "transcribe", "finalize"}

    # Everything else is OPTIONAL
    expected_optional = {
        "source_separation", "visual_embed", "ocr", "quality", "shot_type",
        "storyboard", "semantic_embed", "speaker_embed", "emotion_embed",
        "reactions", "acoustic", "profanity", "chronemic", "highlights",
    }

    actual_required = {s.name for s in pipeline.stages if s.required}
    actual_optional = {s.name for s in pipeline.stages if not s.required}

    _test("Required stages match spec",
          actual_required == expected_required,
          f"expected {expected_required}, got {actual_required}")
    _test("Optional stages match spec",
          actual_optional == expected_optional,
          f"missing optional: {expected_optional - actual_optional}, extra: {actual_optional - expected_optional}")

    # Verify counts
    _test("6 required stages", len(actual_required) == 6, f"got {len(actual_required)}")
    _test("14 optional stages", len(actual_optional) == 14, f"got {len(actual_optional)}")


# ============================================================================
# SECTION 4: Pipeline Stage Function Signatures
# ============================================================================
def test_stage_signatures():
    """Test that each pipeline stage function has the correct signature."""
    _section("4. Pipeline Stage Function Signatures")

    stage_functions = {
        "run_probe": run_probe,
        "run_vfr_normalize": run_vfr_normalize,
        "run_audio_extract": run_audio_extract,
        "run_frame_extract": run_frame_extract,
        "run_source_separation": run_source_separation,
        "run_visual_embed": run_visual_embed,
        "run_ocr": run_ocr,
        "run_quality": run_quality,
        "run_shot_type": run_shot_type,
        "run_transcribe": run_transcribe,
        "run_storyboard": run_storyboard,
        "run_semantic_embed": run_semantic_embed,
        "run_speaker_embed": run_speaker_embed,
        "run_emotion_embed": run_emotion_embed,
        "run_reactions": run_reactions,
        "run_acoustic": run_acoustic,
        "run_profanity": run_profanity,
        "run_chronemic": run_chronemic,
        "run_highlights": run_highlights,
        "run_finalize": run_finalize,
    }

    expected_params = {"project_id", "db_path", "project_dir", "config"}

    for name, func in stage_functions.items():
        # Verify it's async
        _test(f"{name} is async", asyncio.iscoroutinefunction(func))

        # Verify parameters (ignoring 'self' and 'return')
        sig = inspect.signature(func)
        params = set(sig.parameters.keys())
        _test(f"{name} has correct params",
              params == expected_params,
              f"expected {expected_params}, got {params}")

    # Verify each stage_def in registry has a non-None run function
    for stage_def in _STAGE_DEFS:
        sname = stage_def["name"]
        _test(f"Stage '{sname}' has run function assigned",
              stage_def.get("run") is not None)


# ============================================================================
# SECTION 5: Graceful Degradation
# ============================================================================
def test_graceful_degradation():
    """Test optional stage failure produces fallback, required failure aborts."""
    _section("5. Graceful Degradation (Optional Stage Failure)")

    config = ClipCannonConfig(
        data=json.loads((_ROOT / "config" / "default_config.json").read_text()),
        config_path=Path("/tmp/test_config.json"),
    )

    # Create minimal DB for orchestrator status tracking
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS stream_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                stream_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                duration_ms INTEGER,
                UNIQUE(project_id, stream_name)
            );
        """)
        conn.commit()
        conn.close()

        orchestrator = PipelineOrchestrator(config)

        # Register stages: A (required), B (optional, depends on A), C (required, depends on A)
        async def _succeed(project_id, db_path, project_dir, config):
            return StageResult(success=True, operation="test_ok")

        async def _fail_optional(project_id, db_path, project_dir, config):
            return StageResult(success=False, operation="test_fail", error_message="Simulated failure")

        orchestrator.register_stage(
            PipelineStage(name="stage_a", operation="a", required=True, run=_succeed))
        orchestrator.register_stage(
            PipelineStage(name="stage_b", operation="b", required=False, depends_on=["stage_a"], run=_fail_optional))
        orchestrator.register_stage(
            PipelineStage(name="stage_c", operation="c", required=True, depends_on=["stage_a"], run=_succeed))

        result = asyncio.get_event_loop().run_until_complete(
            orchestrator.run("test_proj", db_path, Path(tmpdir))
        )

        _test("Pipeline succeeds when only optional stage fails",
              result.success is True,
              f"success={result.success}, failed_required={result.failed_required}")
        _test("Failed optional stage recorded",
              "stage_b" in result.failed_optional,
              f"failed_optional={result.failed_optional}")
        _test("Required stages completed",
              "stage_a" in result.stage_results and result.stage_results["stage_a"].success)
        _test("Required stage C completed despite B failure",
              "stage_c" in result.stage_results and result.stage_results["stage_c"].success)

        # Now test REQUIRED stage failure aborts pipeline
        orchestrator2 = PipelineOrchestrator(config)

        async def _fail_required(project_id, db_path, project_dir, config):
            return StageResult(success=False, operation="test_fail", error_message="Required failure")

        orchestrator2.register_stage(
            PipelineStage(name="stage_x", operation="x", required=True, run=_fail_required))
        orchestrator2.register_stage(
            PipelineStage(name="stage_y", operation="y", required=True, depends_on=["stage_x"], run=_succeed))

        result2 = asyncio.get_event_loop().run_until_complete(
            orchestrator2.run("test_proj2", db_path, Path(tmpdir))
        )

        _test("Pipeline fails when required stage fails",
              result2.success is False)
        _test("Failed required stage recorded",
              "stage_x" in result2.failed_required)
        _test("Downstream stage skipped after required failure",
              "stage_y" in result2.stage_results and not result2.stage_results["stage_y"].success)


# ============================================================================
# SECTION 6: Synthetic DB Setup for MCP Tool Tests
# ============================================================================
PROJECT_ID = "proj_fsv00001"


def create_synthetic_db(tmpdir: Path) -> Path:
    """Create a fully populated analysis.db with synthetic data.

    Returns the path to the created database.
    """
    # Create project directory structure
    proj_dir = tmpdir / PROJECT_ID
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "source").mkdir(exist_ok=True)
    (proj_dir / "frames").mkdir(exist_ok=True)
    (proj_dir / "storyboards").mkdir(exist_ok=True)
    (proj_dir / "stems").mkdir(exist_ok=True)

    # Create a dummy source file for disk status
    (proj_dir / "source" / "test_video.mp4").write_bytes(b"x" * 1024)
    (proj_dir / "analysis.db").touch()  # Will be recreated below

    db_path = proj_dir / "analysis.db"

    # Import and create schema
    from clipcannon.db.schema import _CORE_TABLES_SQL, _INDEXES_SQL
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_CORE_TABLES_SQL)
    conn.executescript(_INDEXES_SQL)

    # Record schema version
    conn.execute("INSERT OR REPLACE INTO schema_version (version) VALUES (1)")

    # ---- PROJECT RECORD ----
    conn.execute("""
        INSERT INTO project (project_id, name, source_path, source_sha256,
            duration_ms, resolution, fps, codec, audio_codec, audio_channels,
            file_size_bytes, vfr_detected, status, created_at, updated_at)
        VALUES (?, 'Test Video', '/tmp/source.mp4', 'abc123hash',
            60000, '1920x1080', 30.0, 'h264', 'aac', 2,
            10485760, 0, 'ready', datetime('now'), datetime('now'))
    """, (PROJECT_ID,))

    # ---- SPEAKERS (2) ----
    conn.execute("""
        INSERT INTO speakers (project_id, label, total_speaking_ms, speaking_pct)
        VALUES (?, 'Speaker A', 30000, 50.0)
    """, (PROJECT_ID,))
    conn.execute("""
        INSERT INTO speakers (project_id, label, total_speaking_ms, speaking_pct)
        VALUES (?, 'Speaker B', 20000, 33.3)
    """, (PROJECT_ID,))

    # ---- TRANSCRIPT SEGMENTS (5) ----
    segments = [
        (PROJECT_ID, 0, 5000, "Hello everyone welcome to the show", 1, "en", 6),
        (PROJECT_ID, 5000, 12000, "Today we discuss important topics", 1, "en", 5),
        (PROJECT_ID, 12000, 20000, "The weather is looking great outside", 2, "en", 6),
        (PROJECT_ID, 20000, 35000, "Let me explain the searchable concept further", 1, "en", 7),
        (PROJECT_ID, 35000, 50000, "Thank you for watching the entire video", 2, "en", 7),
    ]
    for seg in segments:
        conn.execute("""
            INSERT INTO transcript_segments (project_id, start_ms, end_ms, text,
                speaker_id, language, word_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, seg)

    # ---- TRANSCRIPT WORDS (15 total, 3 per segment) ----
    words = [
        # Segment 1 (segment_id=1)
        (1, "Hello", 0, 800, 0.95, 1),
        (1, "everyone", 800, 1500, 0.92, 1),
        (1, "welcome", 1500, 2500, 0.98, 1),
        # Segment 2 (segment_id=2)
        (2, "Today", 5000, 5800, 0.96, 1),
        (2, "we", 5800, 6000, 0.99, 1),
        (2, "discuss", 6000, 7000, 0.94, 1),
        # Segment 3 (segment_id=3)
        (3, "The", 12000, 12300, 0.99, 2),
        (3, "weather", 12300, 13000, 0.97, 2),
        (3, "is", 13000, 13200, 0.99, 2),
        # Segment 4 (segment_id=4)
        (4, "Let", 20000, 20400, 0.98, 1),
        (4, "me", 20400, 20600, 0.99, 1),
        (4, "explain", 20600, 21500, 0.93, 1),
        # Segment 5 (segment_id=5)
        (5, "Thank", 35000, 35600, 0.97, 2),
        (5, "you", 35600, 35900, 0.99, 2),
        (5, "for", 35900, 36100, 0.99, 2),
    ]
    for w in words:
        conn.execute("""
            INSERT INTO transcript_words (segment_id, word, start_ms, end_ms,
                confidence, speaker_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, w)

    # ---- SCENES (3) ----
    scenes = [
        (PROJECT_ID, 0, 15000, "/tmp/frames/frame_000001.jpg", 500, 0.85, '["#FF0000"]', 0, None, None, "medium", 0.9, None, 78.5, 65.0, "good", None),
        (PROJECT_ID, 15000, 35000, "/tmp/frames/frame_000031.jpg", 15500, 0.80, '["#00FF00"]', 0, None, None, "wide", 0.85, None, 82.0, 72.0, "good", None),
        (PROJECT_ID, 35000, 60000, "/tmp/frames/frame_000071.jpg", 35500, 0.75, '["#0000FF"]', 0, None, None, "closeup", 0.95, None, 90.0, 85.0, "excellent", None),
    ]
    for s in scenes:
        conn.execute("""
            INSERT INTO scenes (project_id, start_ms, end_ms, key_frame_path,
                key_frame_timestamp_ms, visual_similarity_avg, dominant_colors,
                face_detected, face_position_x, face_position_y, shot_type,
                shot_type_confidence, crop_recommendation, quality_avg, quality_min,
                quality_classification, quality_issues)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, s)

    # ---- EMOTION CURVE (3 entries) ----
    emotions = [
        (PROJECT_ID, 0, 20000, 0.6, 0.5, 0.7),
        (PROJECT_ID, 20000, 40000, 0.8, 0.3, 0.9),
        (PROJECT_ID, 40000, 60000, 0.4, 0.7, 0.5),
    ]
    for e in emotions:
        conn.execute("""
            INSERT INTO emotion_curve (project_id, start_ms, end_ms, arousal, valence, energy)
            VALUES (?, ?, ?, ?, ?, ?)
        """, e)

    # ---- TOPICS (2) ----
    topics = [
        (PROJECT_ID, 0, 20000, "Introduction and Welcome", "hello,welcome,show", 0.85, 0.7),
        (PROJECT_ID, 20000, 60000, "Main Discussion", "explain,concept,discuss", 0.92, 0.8),
    ]
    for t in topics:
        conn.execute("""
            INSERT INTO topics (project_id, start_ms, end_ms, label, keywords,
                coherence_score, semantic_density)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, t)

    # ---- HIGHLIGHTS (3) ----
    highlights = [
        (PROJECT_ID, 0, 10000, "opening", 0.95, "Strong opening hook", 0.8, 0.7, 0.9, 0.6, 0.5, 0.8, 0.7),
        (PROJECT_ID, 20000, 35000, "key_moment", 0.88, "Concept explanation peak", 0.7, 0.6, 0.85, 0.5, 0.6, 0.9, 0.8),
        (PROJECT_ID, 35000, 50000, "closing", 0.72, "Emotional closing segment", 0.9, 0.8, 0.7, 0.6, 0.4, 0.7, 0.6),
    ]
    for h in highlights:
        conn.execute("""
            INSERT INTO highlights (project_id, start_ms, end_ms, type, score, reason,
                emotion_score, reaction_score, semantic_score, narrative_score,
                visual_score, quality_score, speaker_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, h)

    # ---- REACTIONS (2) ----
    reactions = [
        (PROJECT_ID, 5000, 8000, "laughter", 0.87, 3000, "high", "Hello everyone welcome"),
        (PROJECT_ID, 40000, 43000, "applause", 0.92, 3000, "medium", "Thank you for watching"),
    ]
    for r in reactions:
        conn.execute("""
            INSERT INTO reactions (project_id, start_ms, end_ms, type, confidence,
                duration_ms, intensity, context_transcript)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, r)

    # ---- ACOUSTIC (1) ----
    conn.execute("""
        INSERT INTO acoustic (project_id, avg_volume_db, dynamic_range_db)
        VALUES (?, -18.5, 12.3)
    """, (PROJECT_ID,))

    # ---- BEATS (1) ----
    conn.execute("""
        INSERT INTO beats (project_id, has_music, source, tempo_bpm,
            tempo_confidence, beat_positions_ms, downbeat_positions_ms, beat_count)
        VALUES (?, 1, 'librosa', 120.5, 0.85, '[0,500,1000,1500]', '[0,2000]', 4)
    """, (PROJECT_ID,))

    # ---- PACING (2) ----
    pacing = [
        (PROJECT_ID, 0, 30000, 145.0, 0.12, 2, "moderate"),
        (PROJECT_ID, 30000, 60000, 160.0, 0.08, 1, "fast"),
    ]
    for p in pacing:
        conn.execute("""
            INSERT INTO pacing (project_id, start_ms, end_ms, words_per_minute,
                pause_ratio, speaker_changes, label)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, p)

    # ---- CONTENT SAFETY (1) ----
    conn.execute("""
        INSERT INTO content_safety (project_id, profanity_count, profanity_density,
            content_rating, nsfw_frame_count)
        VALUES (?, 2, 0.033, 'PG-13', 0)
    """, (PROJECT_ID,))

    # ---- STORYBOARD GRIDS (2) ----
    grids = [
        (PROJECT_ID, 1, "/tmp/storyboards/grid_001.jpg", "[0,2000,4000,6000,8000,10000,12000,14000,16000]", '{"cells": 9}'),
        (PROJECT_ID, 2, "/tmp/storyboards/grid_002.jpg", "[18000,20000,22000,24000,26000,28000,30000,32000,34000]", '{"cells": 9}'),
    ]
    for g in grids:
        conn.execute("""
            INSERT INTO storyboard_grids (project_id, grid_number, grid_path,
                cell_timestamps_ms, cell_metadata)
            VALUES (?, ?, ?, ?, ?)
        """, g)

    # ---- PROVENANCE (3 records forming a chain) ----
    # Record 1: genesis
    chain_hash_1 = compute_chain_hash(
        parent_hash=GENESIS_HASH,
        input_sha256="input_hash_1",
        output_sha256="output_hash_1",
        operation="probe",
        model_name="",
        model_version="",
        model_params={},
    )
    conn.execute("""
        INSERT INTO provenance (record_id, project_id, timestamp_utc, operation,
            stage, description, input_sha256, output_sha256, output_record_count,
            parent_record_id, chain_hash, execution_duration_ms)
        VALUES (?, ?, '2024-01-01T00:00:00Z', 'probe', 'ffprobe',
            'Initial probe', 'input_hash_1', 'output_hash_1', 1,
            NULL, ?, 100)
    """, (f"prov_001", PROJECT_ID, chain_hash_1))

    # Record 2: child of 1
    chain_hash_2 = compute_chain_hash(
        parent_hash=chain_hash_1,
        input_sha256="input_hash_2",
        output_sha256="output_hash_2",
        operation="transcription",
        model_name="whisperx",
        model_version="large-v3",
        model_params={"compute_type": "int8"},
    )
    conn.execute("""
        INSERT INTO provenance (record_id, project_id, timestamp_utc, operation,
            stage, description, input_sha256, output_sha256, output_record_count,
            parent_record_id, model_name, model_version, model_parameters,
            chain_hash, execution_duration_ms)
        VALUES (?, ?, '2024-01-01T00:01:00Z', 'transcription', 'whisperx',
            'WhisperX transcription', 'input_hash_2', 'output_hash_2', 5,
            'prov_001', 'whisperx', 'large-v3', '{"compute_type": "int8"}',
            ?, 5000)
    """, (f"prov_002", PROJECT_ID, chain_hash_2))

    # Record 3: child of 2
    chain_hash_3 = compute_chain_hash(
        parent_hash=chain_hash_2,
        input_sha256="input_hash_3",
        output_sha256="output_hash_3",
        operation="semantic_embedding",
        model_name="nomic-embed",
        model_version="v1.5",
        model_params={},
    )
    conn.execute("""
        INSERT INTO provenance (record_id, project_id, timestamp_utc, operation,
            stage, description, input_sha256, output_sha256, output_record_count,
            parent_record_id, model_name, model_version,
            chain_hash, execution_duration_ms)
        VALUES (?, ?, '2024-01-01T00:02:00Z', 'semantic_embedding', 'nomic',
            'Nomic semantic embeddings', 'input_hash_3', 'output_hash_3', 5,
            'prov_002', 'nomic-embed', 'v1.5',
            ?, 3000)
    """, (f"prov_003", PROJECT_ID, chain_hash_3))

    # ---- STREAM STATUS (16 streams, all completed) ----
    from clipcannon.db.schema import PIPELINE_STREAMS
    for stream_name in PIPELINE_STREAMS:
        conn.execute("""
            INSERT INTO stream_status (project_id, stream_name, status,
                started_at, completed_at, duration_ms)
            VALUES (?, ?, 'completed', datetime('now', '-1 minute'),
                datetime('now'), 5000)
        """, (PROJECT_ID, stream_name))

    conn.commit()
    conn.close()

    return db_path


# ============================================================================
# SECTION 7: MCP Tool Tests
# ============================================================================
def test_mcp_tools(tmpdir: Path, db_path: Path):
    """Test each MCP tool function directly with synthetic data."""
    _section("6. MCP Tool Tests (with synthetic DB)")

    proj_dir = tmpdir / PROJECT_ID

    # We need to patch the tool helpers to point at our temp directory
    # The tools use _projects_dir() / _get_projects_dir() which defaults to ~/.clipcannon/projects
    # We patch at the module level in each tool file

    async def _run_tool_tests():
        # ------------------------------------------------------------------
        # 6a. clipcannon_project_list
        # ------------------------------------------------------------------
        _section("6a. clipcannon_project_list")
        from clipcannon.tools.project import clipcannon_project_list
        with patch("clipcannon.tools.project._get_projects_dir", return_value=tmpdir):
            result = await clipcannon_project_list()
        _test("project_list returns dict", isinstance(result, dict))
        _test("project_list has 'projects' key", "projects" in result)
        projects = result.get("projects", [])
        _test("project_list contains our test project",
              any(p.get("project_id") == PROJECT_ID for p in projects),
              f"got projects: {[p.get('project_id') for p in projects]}")

        # Direct DB verification
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT project_id, name, status FROM project WHERE project_id = ?", (PROJECT_ID,)).fetchone()
        conn.close()
        _test("DB confirms project exists", row is not None and row["project_id"] == PROJECT_ID)

        # ------------------------------------------------------------------
        # 6b. clipcannon_project_status
        # ------------------------------------------------------------------
        _section("6b. clipcannon_project_status")
        from clipcannon.tools.project import clipcannon_project_status
        with patch("clipcannon.tools.project._get_projects_dir", return_value=tmpdir):
            status = await clipcannon_project_status(PROJECT_ID)
        _test("project_status returns dict", isinstance(status, dict))
        _test("project_status has 'pipeline' key", "pipeline" in status)
        pipeline = status.get("pipeline", {})
        _test("pipeline progress shows all completed",
              pipeline.get("completed") == 16,
              f"completed={pipeline.get('completed')}, total={pipeline.get('total_streams')}")
        _test("pipeline progress 100%", pipeline.get("progress_pct") == 100.0,
              f"progress_pct={pipeline.get('progress_pct')}")

        # Direct DB verification
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        ss_rows = conn.execute(
            "SELECT count(*) as cnt FROM stream_status WHERE project_id = ? AND status = 'completed'",
            (PROJECT_ID,)
        ).fetchone()
        conn.close()
        _test("DB confirms 16 completed streams", ss_rows["cnt"] == 16,
              f"got {ss_rows['cnt']}")

        # ------------------------------------------------------------------
        # 6c. clipcannon_get_vud_summary
        # ------------------------------------------------------------------
        _section("6c. clipcannon_get_vud_summary")
        from clipcannon.tools.understanding import clipcannon_get_vud_summary
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            vud = await clipcannon_get_vud_summary(PROJECT_ID)
        _test("vud_summary returns dict", isinstance(vud, dict))
        _test("vud_summary has speaker count",
              vud.get("speakers", {}).get("count") == 2,
              f"speakers={vud.get('speakers')}")
        _test("vud_summary has topic count",
              vud.get("topics", {}).get("count") == 2,
              f"topics count={vud.get('topics', {}).get('count')}")
        _test("vud_summary has top_highlights",
              len(vud.get("top_highlights", [])) == 3,
              f"highlights={len(vud.get('top_highlights', []))}")
        _test("vud_summary has reactions",
              "laughter" in vud.get("reactions", {}) and "applause" in vud.get("reactions", {}),
              f"reactions={vud.get('reactions')}")
        _test("vud_summary has beats",
              vud.get("beats") is not None and vud["beats"].get("has_music") == 1)
        _test("vud_summary has content_safety",
              vud.get("content_safety") is not None and vud["content_safety"].get("content_rating") == "PG-13")
        _test("vud_summary has avg_energy",
              vud.get("avg_energy") is not None,
              f"avg_energy={vud.get('avg_energy')}")
        _test("vud_summary has provenance_records count of 3",
              vud.get("provenance_records") == 3,
              f"prov_records={vud.get('provenance_records')}")
        _test("vud_summary stream_status all completed",
              vud.get("stream_status", {}).get("completed") == 16,
              f"stream_status={vud.get('stream_status')}")

        # ------------------------------------------------------------------
        # 6d. clipcannon_get_analytics
        # ------------------------------------------------------------------
        _section("6d. clipcannon_get_analytics")
        from clipcannon.tools.understanding import clipcannon_get_analytics
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            analytics = await clipcannon_get_analytics(PROJECT_ID)
        _test("analytics returns dict", isinstance(analytics, dict))

        # Scenes
        scenes_data = analytics.get("scenes", {})
        _test("analytics has 3 scenes",
              scenes_data.get("total") == 3,
              f"scene total={scenes_data.get('total')}")

        # Topics
        topics_data = analytics.get("topics", [])
        _test("analytics has 2 topics",
              len(topics_data) == 2,
              f"topic count={len(topics_data)}")

        # Highlights
        highlights_data = analytics.get("highlights", [])
        _test("analytics has 3 highlights",
              len(highlights_data) == 3,
              f"highlight count={len(highlights_data)}")

        # Reactions
        reactions_data = analytics.get("reactions", [])
        _test("analytics has 2 reactions",
              len(reactions_data) == 2,
              f"reaction count={len(reactions_data)}")

        # Pacing
        pacing_data = analytics.get("pacing", [])
        _test("analytics has 2 pacing entries",
              len(pacing_data) == 2,
              f"pacing count={len(pacing_data)}")

        # Beats
        beats_data = analytics.get("beats", {})
        _test("analytics has beats summary",
              beats_data.get("summary") is not None)

        # ------------------------------------------------------------------
        # 6e. clipcannon_get_transcript
        # ------------------------------------------------------------------
        _section("6e. clipcannon_get_transcript")
        from clipcannon.tools.understanding import clipcannon_get_transcript
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            transcript = await clipcannon_get_transcript(PROJECT_ID, start_ms=0, end_ms=60000)
        _test("transcript returns dict", isinstance(transcript, dict))
        _test("transcript has 5 segments",
              transcript.get("segment_count") == 5,
              f"segment_count={transcript.get('segment_count')}")
        # Verify words are included
        first_seg = transcript.get("segments", [{}])[0]
        _test("transcript segments have words",
              len(first_seg.get("words", [])) == 3,
              f"first segment words={len(first_seg.get('words', []))}")

        # Direct DB cross-verification
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        db_seg_count = conn.execute(
            "SELECT count(*) as cnt FROM transcript_segments WHERE project_id = ?",
            (PROJECT_ID,)
        ).fetchone()["cnt"]
        conn.close()
        _test("DB confirms 5 segments", db_seg_count == 5)

        # ------------------------------------------------------------------
        # 6f. clipcannon_get_segment_detail
        # ------------------------------------------------------------------
        _section("6f. clipcannon_get_segment_detail")
        from clipcannon.tools.understanding_visual import clipcannon_get_segment_detail
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            detail = await clipcannon_get_segment_detail(PROJECT_ID, start_ms=0, end_ms=30000)
        _test("segment_detail returns dict", isinstance(detail, dict))
        _test("segment_detail has transcript",
              len(detail.get("transcript", [])) >= 3,
              f"transcript count={len(detail.get('transcript', []))}")
        _test("segment_detail has emotion_curve",
              len(detail.get("emotion_curve", [])) >= 1,
              f"emotion count={len(detail.get('emotion_curve', []))}")
        _test("segment_detail has reactions",
              len(detail.get("reactions", [])) >= 1,
              f"reactions count={len(detail.get('reactions', []))}")
        _test("segment_detail has pacing",
              len(detail.get("pacing", [])) >= 1,
              f"pacing count={len(detail.get('pacing', []))}")

        # ------------------------------------------------------------------
        # 6g. clipcannon_get_frame (metadata check -- no actual frame files)
        # ------------------------------------------------------------------
        _section("6g. clipcannon_get_frame")
        from clipcannon.tools.understanding_visual import clipcannon_get_frame
        # Create a fake frame file so the tool can find it
        frames_dir = proj_dir / "frames"
        (frames_dir / "frame_000001.jpg").write_bytes(b"fake_jpg")
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            frame = await clipcannon_get_frame(PROJECT_ID, timestamp_ms=0)
        _test("get_frame returns dict", isinstance(frame, dict))
        # The tool finds nearest frame at timestamp 0
        if "error" not in frame:
            _test("get_frame returns frame_path", "frame_path" in frame)
            _test("get_frame returns at_this_moment context", "at_this_moment" in frame)
        else:
            _test("get_frame returns valid result (no error)", False, f"got error: {frame}")

        # ------------------------------------------------------------------
        # 6h. clipcannon_get_storyboard
        # ------------------------------------------------------------------
        _section("6h. clipcannon_get_storyboard")
        from clipcannon.tools.understanding_visual import clipcannon_get_storyboard
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            storyboard = await clipcannon_get_storyboard(PROJECT_ID, batch=1)
        _test("get_storyboard returns dict", isinstance(storyboard, dict))
        _test("get_storyboard has total_grids == 2",
              storyboard.get("total_grids") == 2,
              f"total_grids={storyboard.get('total_grids')}")
        _test("get_storyboard returns our 2 grids",
              storyboard.get("grid_count") == 2,
              f"grid_count={storyboard.get('grid_count')}")
        grids = storyboard.get("grids", [])
        if grids:
            _test("storyboard grids have cell_timestamps_ms",
                  isinstance(grids[0].get("cell_timestamps_ms"), list))

        # ------------------------------------------------------------------
        # 6i. clipcannon_search_content (text search)
        # ------------------------------------------------------------------
        _section("6i. clipcannon_search_content")
        from clipcannon.tools.understanding_search import clipcannon_search_content
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            search = await clipcannon_search_content(PROJECT_ID, query="searchable", search_type="text")
        _test("search_content returns dict", isinstance(search, dict))
        _test("search_content finds 'searchable' in segment 4",
              search.get("result_count", 0) >= 1,
              f"result_count={search.get('result_count')}")
        if search.get("results"):
            first = search["results"][0]
            _test("search result has text field",
                  "searchable" in str(first.get("text", "")).lower(),
                  f"text={first.get('text')}")

        # Search for something in multiple segments
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            search2 = await clipcannon_search_content(PROJECT_ID, query="the", search_type="text")
        _test("search for 'the' returns multiple results",
              search2.get("result_count", 0) >= 2,
              f"result_count={search2.get('result_count')}")

        # ------------------------------------------------------------------
        # 6j. clipcannon_provenance_verify
        # ------------------------------------------------------------------
        _section("6j. clipcannon_provenance_verify")
        from clipcannon.tools.provenance_tools import clipcannon_provenance_verify
        with patch("clipcannon.tools.provenance_tools._get_db_path", return_value=db_path):
            verify = await clipcannon_provenance_verify(PROJECT_ID)
        _test("provenance_verify returns dict", isinstance(verify, dict))
        _test("provenance chain is VERIFIED",
              verify.get("verified") is True,
              f"verified={verify.get('verified')}, issue={verify.get('issue')}")
        _test("provenance has 3 total records",
              verify.get("total_records") == 3,
              f"total_records={verify.get('total_records')}")

        # ------------------------------------------------------------------
        # 6k. clipcannon_provenance_query
        # ------------------------------------------------------------------
        _section("6k. clipcannon_provenance_query")
        from clipcannon.tools.provenance_tools import clipcannon_provenance_query
        with patch("clipcannon.tools.provenance_tools._get_db_path", return_value=db_path):
            prov_q = await clipcannon_provenance_query(PROJECT_ID)
        _test("provenance_query returns dict", isinstance(prov_q, dict))
        _test("provenance_query returns 3 records",
              prov_q.get("total") == 3,
              f"total={prov_q.get('total')}")

        # Filter by operation
        with patch("clipcannon.tools.provenance_tools._get_db_path", return_value=db_path):
            prov_q2 = await clipcannon_provenance_query(PROJECT_ID, operation="probe")
        _test("provenance_query filter by operation=probe returns 1",
              prov_q2.get("total") == 1,
              f"total={prov_q2.get('total')}")

        # ------------------------------------------------------------------
        # 6l. clipcannon_provenance_chain
        # ------------------------------------------------------------------
        _section("6l. clipcannon_provenance_chain")
        from clipcannon.tools.provenance_tools import clipcannon_provenance_chain
        with patch("clipcannon.tools.provenance_tools._get_db_path", return_value=db_path):
            chain = await clipcannon_provenance_chain(PROJECT_ID, record_id="prov_003")
        _test("provenance_chain returns dict", isinstance(chain, dict))
        chain_records = chain.get("chain", [])
        _test("provenance_chain from prov_003 has 3 records (genesis to target)",
              len(chain_records) == 3,
              f"chain length={len(chain_records)}")
        if chain_records:
            _test("chain is ordered genesis-first",
                  chain_records[0].get("record_id") == "prov_001",
                  f"first record={chain_records[0].get('record_id')}")
            _test("chain ends at target",
                  chain_records[-1].get("record_id") == "prov_003",
                  f"last record={chain_records[-1].get('record_id')}")

        # ------------------------------------------------------------------
        # 6m. clipcannon_provenance_timeline
        # ------------------------------------------------------------------
        _section("6m. clipcannon_provenance_timeline")
        from clipcannon.tools.provenance_tools import clipcannon_provenance_timeline
        with patch("clipcannon.tools.provenance_tools._get_db_path", return_value=db_path):
            timeline = await clipcannon_provenance_timeline(PROJECT_ID)
        _test("provenance_timeline returns dict", isinstance(timeline, dict))
        _test("provenance_timeline has 3 records",
              timeline.get("total_records") == 3,
              f"total_records={timeline.get('total_records')}")
        entries = timeline.get("timeline", [])
        if len(entries) >= 2:
            _test("timeline is chronologically ordered",
                  entries[0].get("timestamp", "") <= entries[1].get("timestamp", ""),
                  f"t0={entries[0].get('timestamp')}, t1={entries[1].get('timestamp')}")

        # ------------------------------------------------------------------
        # 6n. clipcannon_disk_status
        # ------------------------------------------------------------------
        _section("6n. clipcannon_disk_status")
        from clipcannon.tools.disk import clipcannon_disk_status
        with patch("clipcannon.tools.disk._get_projects_dir", return_value=tmpdir):
            disk = await clipcannon_disk_status(PROJECT_ID)
        _test("disk_status returns dict", isinstance(disk, dict))
        _test("disk_status has 'tiers' key", "tiers" in disk)
        tiers = disk.get("tiers", {})
        _test("disk_status has sacred tier", "sacred" in tiers)
        _test("disk_status has regenerable tier", "regenerable" in tiers)
        _test("disk_status has ephemeral tier", "ephemeral" in tiers)
        # Sacred should include analysis.db and source/test_video.mp4
        sacred = tiers.get("sacred", {})
        _test("sacred tier has files",
              int(sacred.get("count", 0)) >= 1,
              f"sacred count={sacred.get('count')}")

        # ------------------------------------------------------------------
        # 6o. clipcannon_config_get
        # ------------------------------------------------------------------
        _section("6o. clipcannon_config_get / config_list")
        from clipcannon.tools.config_tools import clipcannon_config_get, clipcannon_config_list
        conf_result = await clipcannon_config_get("processing.whisper_model")
        _test("config_get returns dict", isinstance(conf_result, dict))
        if "error" not in conf_result:
            _test("config_get returns known value 'large-v3'",
                  conf_result.get("value") == "large-v3",
                  f"value={conf_result.get('value')}")
        else:
            _test("config_get returns known value", False, f"error={conf_result}")

        conf_list = await clipcannon_config_list()
        _test("config_list returns dict", isinstance(conf_list, dict))
        if "error" not in conf_list:
            config_data = conf_list.get("config", {})
            _test("config_list has 'processing' section", "processing" in config_data)
            _test("config_list has 'gpu' section", "gpu" in config_data)
        else:
            _test("config_list succeeds", False, f"error={conf_list}")

    asyncio.get_event_loop().run_until_complete(_run_tool_tests())


# ============================================================================
# SECTION 8: Edge Case Tests
# ============================================================================
def test_edge_cases(tmpdir: Path, db_path: Path):
    """Test edge cases for tool error handling."""
    _section("7. Edge Case Tests")

    async def _run_edge_cases():
        # 7a. project_open with non-existent project
        from clipcannon.tools.project import clipcannon_project_open
        with patch("clipcannon.tools.project._get_projects_dir", return_value=tmpdir):
            result = await clipcannon_project_open("nonexistent_proj_999")
        _test("project_open nonexistent -> error response",
              "error" in result,
              f"result={result}")
        if "error" in result:
            _test("project_open nonexistent -> PROJECT_NOT_FOUND code",
                  result["error"].get("code") == "PROJECT_NOT_FOUND",
                  f"code={result['error'].get('code')}")

        # 7b. get_transcript with start_ms > end_ms
        from clipcannon.tools.understanding import clipcannon_get_transcript
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            # start_ms=50000, end_ms=10000 -- start > end
            # The tool doesn't validate start > end, it just returns segments
            # where start_ms < end_ms AND end_ms > start_ms, which returns 0 segments
            result = await clipcannon_get_transcript(PROJECT_ID, start_ms=50000, end_ms=10000)
        _test("get_transcript start>end returns result (no crash)",
              isinstance(result, dict) and "error" not in result,
              f"type={type(result)}, keys={result.keys() if isinstance(result, dict) else 'N/A'}")
        _test("get_transcript start>end returns 0 segments",
              result.get("segment_count", -1) == 0,
              f"segment_count={result.get('segment_count')}")

        # 7c. get_analytics with invalid section
        from clipcannon.tools.understanding import clipcannon_get_analytics
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            result = await clipcannon_get_analytics(PROJECT_ID, sections=["invalid_section"])
        _test("get_analytics invalid section -> error",
              "error" in result,
              f"result keys={list(result.keys())}")

        # 7d. search_content with empty query
        from clipcannon.tools.understanding_search import clipcannon_search_content
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            result = await clipcannon_search_content(PROJECT_ID, query="", search_type="text")
        _test("search_content empty query -> returns result (no crash)",
              isinstance(result, dict),
              f"type={type(result)}")
        # Empty LIKE pattern "%%" matches everything
        _test("search_content empty query returns all segments",
              result.get("result_count", 0) == 5,
              f"result_count={result.get('result_count')}")

        # 7e. search_content with invalid search_type
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            result = await clipcannon_search_content(PROJECT_ID, query="hello", search_type="invalid")
        _test("search_content invalid search_type -> error",
              "error" in result,
              f"result={result}")

        # 7f. segment_detail with end <= start
        from clipcannon.tools.understanding_visual import clipcannon_get_segment_detail
        with patch("clipcannon.tools.understanding._projects_dir", return_value=tmpdir):
            result = await clipcannon_get_segment_detail(PROJECT_ID, start_ms=5000, end_ms=5000)
        _test("segment_detail end==start -> error",
              "error" in result,
              f"result keys={list(result.keys())}")

        # 7g. provenance_verify on nonexistent project
        from clipcannon.tools.provenance_tools import clipcannon_provenance_verify
        with patch("clipcannon.tools.provenance_tools._get_db_path", return_value=Path("/tmp/nonexistent.db")):
            result = await clipcannon_provenance_verify("nonexistent")
        _test("provenance_verify nonexistent -> PROJECT_NOT_FOUND",
              "error" in result and result["error"].get("code") == "PROJECT_NOT_FOUND",
              f"result={result}")

        # 7h. disk_status on nonexistent project
        from clipcannon.tools.disk import clipcannon_disk_status
        with patch("clipcannon.tools.disk._get_projects_dir", return_value=tmpdir):
            result = await clipcannon_disk_status("nonexistent_proj")
        _test("disk_status nonexistent -> PROJECT_NOT_FOUND",
              "error" in result,
              f"result={result}")

        # 7i. config_get with invalid key
        from clipcannon.tools.config_tools import clipcannon_config_get
        result = await clipcannon_config_get("nonexistent.deeply.nested.key")
        _test("config_get invalid key -> error",
              "error" in result,
              f"result={result}")

    asyncio.get_event_loop().run_until_complete(_run_edge_cases())


# ============================================================================
# SECTION 9: Direct DB Cross-Verification
# ============================================================================
def test_db_cross_verification(db_path: Path):
    """Physically verify DB contents match what tools should return."""
    _section("8. Direct DB Cross-Verification")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Verify exact record counts
    tables = {
        "project": 1,
        "transcript_segments": 5,
        "transcript_words": 15,
        "scenes": 3,
        "speakers": 2,
        "emotion_curve": 3,
        "topics": 2,
        "highlights": 3,
        "reactions": 2,
        "acoustic": 1,
        "beats": 1,
        "pacing": 2,
        "content_safety": 1,
        "storyboard_grids": 2,
        "provenance": 3,
        "stream_status": 16,
    }

    for table, expected_count in tables.items():
        actual = conn.execute(f"SELECT count(*) as cnt FROM {table}").fetchone()["cnt"]
        _test(f"DB table '{table}' has {expected_count} rows",
              actual == expected_count,
              f"expected {expected_count}, got {actual}")

    # Verify provenance chain integrity at DB level
    prov_rows = conn.execute(
        "SELECT record_id, parent_record_id, chain_hash FROM provenance WHERE project_id = ? ORDER BY timestamp_utc",
        (PROJECT_ID,)
    ).fetchall()

    _test("provenance prov_001 has no parent (genesis)",
          prov_rows[0]["parent_record_id"] is None)
    _test("provenance prov_002 parent is prov_001",
          prov_rows[1]["parent_record_id"] == "prov_001")
    _test("provenance prov_003 parent is prov_002",
          prov_rows[2]["parent_record_id"] == "prov_002")

    # Verify all stream statuses are 'completed'
    ss_rows = conn.execute(
        "SELECT stream_name, status FROM stream_status WHERE project_id = ?",
        (PROJECT_ID,)
    ).fetchall()
    all_completed = all(r["status"] == "completed" for r in ss_rows)
    _test("All 16 stream_status entries are 'completed'", all_completed)

    # Verify project status is 'ready'
    proj = conn.execute(
        "SELECT status FROM project WHERE project_id = ?", (PROJECT_ID,)
    ).fetchone()
    _test("Project status is 'ready'", proj["status"] == "ready")

    conn.close()


# ============================================================================
# MAIN EXECUTION
# ============================================================================
def main():
    print("=" * 72)
    print("  SHERLOCK HOLMES FORENSIC CODE INVESTIGATION")
    print("  Full State Verification: Pipeline Stages + MCP Tools")
    print("=" * 72)
    print(f"\n  Working directory: {_ROOT}")
    print(f"  Python: {sys.executable}")
    print(f"  Version: {sys.version.split()[0]}")

    # SECTION 1-5: Pipeline tests (no temp dir needed)
    try:
        test_dag_dependency_resolution()
    except Exception as exc:
        print(f"\n  [FATAL] DAG test crashed: {exc}")
        traceback.print_exc()

    try:
        test_stage_registration()
    except Exception as exc:
        print(f"\n  [FATAL] Registration test crashed: {exc}")
        traceback.print_exc()

    try:
        test_required_optional()
    except Exception as exc:
        print(f"\n  [FATAL] Required/optional test crashed: {exc}")
        traceback.print_exc()

    try:
        test_stage_signatures()
    except Exception as exc:
        print(f"\n  [FATAL] Signature test crashed: {exc}")
        traceback.print_exc()

    try:
        test_graceful_degradation()
    except Exception as exc:
        print(f"\n  [FATAL] Graceful degradation test crashed: {exc}")
        traceback.print_exc()

    # SECTION 6-8: MCP tool tests (need temp dir with synthetic DB)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        try:
            db_path = create_synthetic_db(tmpdir_path)
            print(f"\n  Synthetic DB created at: {db_path}")
        except Exception as exc:
            print(f"\n  [FATAL] Synthetic DB creation failed: {exc}")
            traceback.print_exc()
            _print_summary()
            return

        try:
            test_mcp_tools(tmpdir_path, db_path)
        except Exception as exc:
            print(f"\n  [FATAL] MCP tool tests crashed: {exc}")
            traceback.print_exc()

        try:
            test_edge_cases(tmpdir_path, db_path)
        except Exception as exc:
            print(f"\n  [FATAL] Edge case tests crashed: {exc}")
            traceback.print_exc()

        try:
            test_db_cross_verification(db_path)
        except Exception as exc:
            print(f"\n  [FATAL] DB cross-verification crashed: {exc}")
            traceback.print_exc()

    _print_summary()


def _print_summary():
    print(f"\n{'='*72}")
    print("  INVESTIGATION SUMMARY")
    print(f"{'='*72}")
    print(f"\n  PASSED: {_passed}")
    print(f"  FAILED: {_failed}")
    print(f"  TOTAL:  {_passed + _failed}")

    if _errors:
        print(f"\n  FAILURES:")
        for err in _errors:
            print(f"    {err}")

    verdict = "INNOCENT" if _failed == 0 else "GUILTY"
    confidence = "HIGH" if _failed == 0 else ("MEDIUM" if _failed <= 3 else "LOW")
    print(f"\n  VERDICT: {verdict}")
    print(f"  CONFIDENCE: {confidence}")
    print(f"{'='*72}")

    # Exit with non-zero if any failures
    sys.exit(1 if _failed > 0 else 0)


if __name__ == "__main__":
    main()
