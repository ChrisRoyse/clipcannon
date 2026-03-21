#!/usr/bin/env python3
"""Manual verification script for ClipCannon full pipeline.

Runs the complete non-model pipeline on the real test video and prints
detailed output for every table, file, and verification check.

Usage:
    PYTHONPATH=src python tests/integration/manual_verify.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

# Ensure src is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.db.schema import PIPELINE_STREAMS, init_project_directory
from clipcannon.pipeline.acoustic import run_acoustic
from clipcannon.pipeline.audio_extract import run_audio_extract
from clipcannon.pipeline.chronemic import run_chronemic
from clipcannon.pipeline.finalize import run_finalize
from clipcannon.pipeline.frame_extract import run_frame_extract
from clipcannon.pipeline.highlights import run_highlights
from clipcannon.pipeline.probe import run_probe
from clipcannon.pipeline.profanity import run_profanity
from clipcannon.pipeline.storyboard import run_storyboard
from clipcannon.provenance import verify_chain

TEST_VIDEO = PROJECT_ROOT / "testdata" / "2026-03-20 14-43-20.mp4"
SEPARATOR = "=" * 60


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n{SEPARATOR}")
    print(f"=== {title} ===")
    print(SEPARATOR)


async def main() -> int:
    """Run the full pipeline and verify everything."""
    if not TEST_VIDEO.exists():
        print(f"ERROR: Test video not found: {TEST_VIDEO}")
        return 1

    config = ClipCannonConfig.load()
    project_id = "proj_manual_verify"
    base_dir = PROJECT_ROOT / ".manual_verify_tmp"

    # Clean up any previous run
    if base_dir.exists():
        shutil.rmtree(base_dir)

    project_dir = base_dir / project_id
    init_project_directory(project_id, base_dir)
    db_path = project_dir / "analysis.db"

    # Copy test video to project source
    source_dir = project_dir / "source"
    source_video = source_dir / TEST_VIDEO.name
    shutil.copy2(str(TEST_VIDEO), str(source_video))

    # Insert initial project record
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        conn.execute(
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created')""",
            (project_id, "Manual Verify", str(source_video), "pending",
             0, "unknown", 0, "unknown"),
        )
        for stream_name in PIPELINE_STREAMS:
            conn.execute(
                "INSERT INTO stream_status (project_id, stream_name, status) "
                "VALUES (?, ?, 'pending')",
                (project_id, stream_name),
            )
        conn.commit()
    finally:
        conn.close()

    total_start = time.monotonic()
    all_passed = True
    stage_times: dict[str, float] = {}

    # ---------------------------------------------------------------
    # Stage 1: Probe
    # ---------------------------------------------------------------
    print_section("RUNNING: probe")
    t0 = time.monotonic()
    probe_result = await run_probe(project_id, db_path, project_dir, config)
    stage_times["probe"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if probe_result.success else 'FAIL'}")
    if not probe_result.success:
        print(f"  Error: {probe_result.error_message}")
        all_passed = False

    # ---------------------------------------------------------------
    # Stage 2: Audio Extract
    # ---------------------------------------------------------------
    print_section("RUNNING: audio_extract")
    t0 = time.monotonic()
    audio_result = await run_audio_extract(project_id, db_path, project_dir, config)
    stage_times["audio_extract"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if audio_result.success else 'FAIL'}")
    if not audio_result.success:
        print(f"  Error: {audio_result.error_message}")
        all_passed = False

    # ---------------------------------------------------------------
    # Stage 3: Frame Extract
    # ---------------------------------------------------------------
    print_section("RUNNING: frame_extract")
    t0 = time.monotonic()
    frame_result = await run_frame_extract(project_id, db_path, project_dir, config)
    stage_times["frame_extract"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if frame_result.success else 'FAIL'}")
    if not frame_result.success:
        print(f"  Error: {frame_result.error_message}")
        all_passed = False

    # ---------------------------------------------------------------
    # Stage 4: Acoustic
    # ---------------------------------------------------------------
    print_section("RUNNING: acoustic")
    t0 = time.monotonic()
    acoustic_result = await run_acoustic(project_id, db_path, project_dir, config)
    stage_times["acoustic"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if acoustic_result.success else 'FAIL'}")
    if not acoustic_result.success:
        print(f"  Error: {acoustic_result.error_message}")
        all_passed = False

    # ---------------------------------------------------------------
    # Stage 5: Storyboard
    # ---------------------------------------------------------------
    print_section("RUNNING: storyboard")
    t0 = time.monotonic()
    storyboard_result = await run_storyboard(project_id, db_path, project_dir, config)
    stage_times["storyboard"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if storyboard_result.success else 'FAIL'}")
    if not storyboard_result.success:
        print(f"  Error: {storyboard_result.error_message}")
        all_passed = False

    # ---------------------------------------------------------------
    # Stage 6: Profanity
    # ---------------------------------------------------------------
    print_section("RUNNING: profanity")
    t0 = time.monotonic()
    profanity_result = await run_profanity(project_id, db_path, project_dir, config)
    stage_times["profanity"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if profanity_result.success else 'FAIL'}")
    if not profanity_result.success:
        print(f"  Error: {profanity_result.error_message}")
        all_passed = False

    # ---------------------------------------------------------------
    # Stage 7: Chronemic
    # ---------------------------------------------------------------
    print_section("RUNNING: chronemic")
    t0 = time.monotonic()
    chronemic_result = await run_chronemic(project_id, db_path, project_dir, config)
    stage_times["chronemic"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if chronemic_result.success else 'FAIL'}")
    if not chronemic_result.success:
        print(f"  Error: {chronemic_result.error_message}")
        all_passed = False

    # ---------------------------------------------------------------
    # Stage 8: Highlights
    # ---------------------------------------------------------------
    print_section("RUNNING: highlights")
    t0 = time.monotonic()
    highlights_result = await run_highlights(project_id, db_path, project_dir, config)
    stage_times["highlights"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if highlights_result.success else 'FAIL'}")
    if not highlights_result.success:
        print(f"  Error: {highlights_result.error_message}")
        all_passed = False

    # ---------------------------------------------------------------
    # Stage 9: Finalize
    # ---------------------------------------------------------------
    print_section("RUNNING: finalize")
    t0 = time.monotonic()
    finalize_result = await run_finalize(project_id, db_path, project_dir, config)
    stage_times["finalize"] = time.monotonic() - t0
    print(f"  Result: {'PASS' if finalize_result.success else 'FAIL'}")
    if not finalize_result.success:
        print(f"  Error: {finalize_result.error_message}")
        all_passed = False

    total_elapsed = time.monotonic() - total_start

    # ===============================================================
    # DETAILED VERIFICATION
    # ===============================================================
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        # --- PROJECT ---
        print_section("PROJECT")
        proj = fetch_one(conn, "SELECT * FROM project WHERE project_id = ?",
                         (project_id,))
        if proj:
            print(f"  project_id: {proj['project_id']}")
            print(f"  name: {proj['name']}")
            print(f"  duration_ms: {proj['duration_ms']}")
            print(f"  resolution: {proj['resolution']}")
            print(f"  fps: {proj['fps']}")
            print(f"  codec: {proj['codec']}")
            print(f"  audio_codec: {proj.get('audio_codec')}")
            print(f"  audio_channels: {proj.get('audio_channels')}")
            print(f"  vfr_detected: {proj.get('vfr_detected')}")
            print(f"  source_sha256: {str(proj.get('source_sha256', ''))[:32]}...")
            print(f"  status: {proj['status']}")
        else:
            print("  ERROR: No project record found!")
            all_passed = False

        # --- AUDIO FILES ---
        print_section("AUDIO FILES")
        stems_dir = project_dir / "stems"
        for name in ["audio_16k.wav", "audio_original.wav"]:
            path = stems_dir / name
            if path.exists():
                size_mb = path.stat().st_size / (1024 * 1024)
                print(f"  {name}: EXISTS, size={size_mb:.2f}MB")
            else:
                print(f"  {name}: MISSING!")
                all_passed = False

        # --- FRAMES ---
        print_section("FRAMES")
        frames_dir = project_dir / "frames"
        frames = sorted(frames_dir.glob("frame_*.jpg"))
        if frames:
            sample_size_kb = frames[0].stat().st_size / 1024
            print(f"  Total frames: {len(frames)}")
            print(f"  First: {frames[0].name}")
            print(f"  Last: {frames[-1].name}")
            print(f"  Sample frame size: {sample_size_kb:.1f}KB")
        else:
            print("  ERROR: No frames found!")
            all_passed = False

        # --- STORYBOARD GRIDS ---
        print_section("STORYBOARD GRIDS")
        grids = fetch_all(
            conn,
            "SELECT * FROM storyboard_grids WHERE project_id = ? ORDER BY grid_number",
            (project_id,),
        )
        print(f"  Total grids in DB: {len(grids)}")
        if grids:
            from PIL import Image
            for g in grids[:3]:
                gp = Path(str(g["grid_path"]))
                exists = gp.exists()
                size_info = ""
                if exists:
                    img = Image.open(gp)
                    size_info = f" ({img.size[0]}x{img.size[1]})"
                    img.close()
                print(f"  Grid {g['grid_number']}: {'EXISTS' if exists else 'MISSING'}{size_info}")
            if len(grids) > 3:
                print(f"  ... and {len(grids) - 3} more grids")
        else:
            all_passed = False

        # --- SILENCE GAPS ---
        print_section("SILENCE GAPS")
        gaps = fetch_all(
            conn,
            "SELECT * FROM silence_gaps WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        print(f"  Total gaps: {len(gaps)}")
        for g in gaps[:5]:
            print(f"  Gap: start={g['start_ms']}ms, end={g['end_ms']}ms, "
                  f"duration={g['duration_ms']}ms, type={g.get('type')}")
        if len(gaps) > 5:
            print(f"  ... and {len(gaps) - 5} more gaps")

        # --- ACOUSTIC ---
        print_section("ACOUSTIC")
        acoustic = fetch_all(
            conn,
            "SELECT * FROM acoustic WHERE project_id = ?",
            (project_id,),
        )
        if acoustic:
            a = acoustic[0]
            print(f"  avg_volume_db: {a['avg_volume_db']}")
            print(f"  dynamic_range_db: {a['dynamic_range_db']}")
        else:
            print("  ERROR: No acoustic data!")
            all_passed = False

        # --- BEATS ---
        print_section("BEATS")
        beats = fetch_all(
            conn,
            "SELECT * FROM beats WHERE project_id = ?",
            (project_id,),
        )
        if beats:
            b = beats[0]
            print(f"  has_music: {b['has_music']}")
            print(f"  source: {b.get('source')}")
            print(f"  tempo_bpm: {b.get('tempo_bpm')}")
            print(f"  beat_count: {b.get('beat_count')}")
        else:
            print("  ERROR: No beats data!")
            all_passed = False

        # --- PACING ---
        print_section("PACING")
        pacing = fetch_all(
            conn,
            "SELECT * FROM pacing WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        print(f"  Total windows: {len(pacing)}")
        for p in pacing[:3]:
            print(f"  Window: start={p['start_ms']}ms, end={p['end_ms']}ms, "
                  f"wpm={p['words_per_minute']}, label={p['label']}")
        if len(pacing) > 3:
            print(f"  ... and {len(pacing) - 3} more windows")

        # --- CONTENT SAFETY ---
        print_section("CONTENT SAFETY")
        safety = fetch_all(
            conn,
            "SELECT * FROM content_safety WHERE project_id = ?",
            (project_id,),
        )
        if safety:
            s = safety[0]
            print(f"  content_rating: {s['content_rating']}")
            print(f"  profanity_count: {s['profanity_count']}")
            print(f"  profanity_density: {s.get('profanity_density')}")
        else:
            print("  ERROR: No content safety data!")
            all_passed = False

        # --- HIGHLIGHTS ---
        print_section("HIGHLIGHTS")
        highlights = fetch_all(
            conn,
            "SELECT * FROM highlights WHERE project_id = ? ORDER BY score DESC",
            (project_id,),
        )
        print(f"  Total highlights: {len(highlights)}")
        for h in highlights[:5]:
            print(f"  Score={float(h['score']):.4f}, type={h['type']}, "
                  f"reason={str(h['reason'])[:80]}")
        if len(highlights) > 5:
            print(f"  ... and {len(highlights) - 5} more highlights")

        # --- STREAM STATUS ---
        print_section("STREAM STATUS")
        streams = fetch_all(
            conn,
            "SELECT stream_name, status FROM stream_status WHERE project_id = ? "
            "ORDER BY stream_name",
            (project_id,),
        )
        for s in streams:
            print(f"  {s['stream_name']}: {s['status']}")

        # --- PROVENANCE ---
        print_section("PROVENANCE")
        provenance = fetch_all(
            conn,
            "SELECT * FROM provenance WHERE project_id = ? ORDER BY timestamp_utc",
            (project_id,),
        )
        print(f"  Total records: {len(provenance)}")

        chain_result = verify_chain(project_id, db_path)
        status = "VERIFIED" if chain_result.verified else "BROKEN"
        print(f"  Chain integrity: {status}")
        if not chain_result.verified:
            print(f"  Issue: {chain_result.issue}")
            all_passed = False

        for prov in provenance:
            chain_hash = str(prov["chain_hash"])
            print(f"  [{prov['record_id']}] op={prov['operation']}, "
                  f"stage={prov['stage']}, chain={chain_hash[:16]}...")

    finally:
        conn.close()

    # --- STAGE TIMING ---
    print_section("STAGE TIMING")
    for stage_name, elapsed in stage_times.items():
        print(f"  {stage_name}: {elapsed:.2f}s")
    print(f"  TOTAL: {total_elapsed:.2f}s")

    # --- FINAL RESULT ---
    print_section("FINAL RESULT")
    if all_passed:
        print("  *** ALL VERIFICATIONS PASSED ***")
    else:
        print("  *** SOME VERIFICATIONS FAILED ***")

    # Clean up
    print(f"\n  Cleaning up temp dir: {base_dir}")
    shutil.rmtree(base_dir, ignore_errors=True)

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
