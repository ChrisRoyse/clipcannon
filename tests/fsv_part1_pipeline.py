"""FSV Part 1: Full Pipeline Happy Path + Database Verification."""
import sys
import asyncio
import sqlite3
import json
import os
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from clipcannon.config import ClipCannonConfig
from clipcannon.db.schema import create_project_db, init_project_directory
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.pipeline.probe import run_probe
from clipcannon.pipeline.audio_extract import run_audio_extract
from clipcannon.pipeline.frame_extract import run_frame_extract
from clipcannon.pipeline.acoustic import run_acoustic
from clipcannon.pipeline.storyboard import run_storyboard
from clipcannon.pipeline.profanity import run_profanity
from clipcannon.pipeline.chronemic import run_chronemic
from clipcannon.pipeline.highlights import run_highlights
from clipcannon.pipeline.finalize import run_finalize
from clipcannon.provenance import sha256_file

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')

VIDEO_PATH = Path("/home/cabdru/clipcannon/testdata/2026-03-20 14-43-20.mp4")
PROJECT_ID = "fsv_test_001"

VERDICTS = []

def verdict(test_name, passed, expected="", actual="", reason=""):
    status = "PASS" if passed else "FAIL"
    VERDICTS.append((test_name, status, reason))
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    if expected:
        print(f"EXPECTED: {expected}")
    if actual:
        print(f"ACTUAL:   {actual}")
    print(f"VERDICT: {status}")
    if reason and not passed:
        print(f"REASON:  {reason}")
    print(f"{'='*60}")


async def run_full_pipeline():
    """Run the full pipeline on the test video and verify everything."""
    import tempfile
    import shutil

    # Use a temp directory for this test
    base_dir = Path(tempfile.mkdtemp(prefix="fsv_clipcannon_"))
    project_dir = base_dir / PROJECT_ID
    db_path = project_dir / "analysis.db"

    print(f"\n{'#'*60}")
    print(f"# FSV PART 1: FULL PIPELINE HAPPY PATH")
    print(f"# Base dir: {base_dir}")
    print(f"# Video: {VIDEO_PATH}")
    print(f"{'#'*60}")

    try:
        # Step 0: Initialize project directory and database
        print("\n--- STEP 0: Project Initialization ---")
        project_dir_result = init_project_directory(PROJECT_ID, base_dir)
        assert project_dir_result == project_dir, f"Expected {project_dir}, got {project_dir_result}"

        # Verify directory structure
        for subdir in ["source", "stems", "frames", "storyboards"]:
            sd = project_dir / subdir
            exists = sd.exists() and sd.is_dir()
            verdict(f"Directory {subdir} exists", exists,
                    expected=f"{sd} exists",
                    actual=f"exists={exists}")

        # Verify DB was created
        verdict("Database created", db_path.exists(),
                expected=f"{db_path} exists",
                actual=f"exists={db_path.exists()}")

        # Load config
        config = ClipCannonConfig.load()

        # Insert initial project record (simulating project_create)
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            execute(conn,
                """INSERT INTO project (project_id, name, source_path, source_sha256,
                   duration_ms, resolution, fps, codec, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created')""",
                (PROJECT_ID, "FSV Test Video", str(VIDEO_PATH), "pending",
                 0, "0x0", 0, "unknown"))
            conn.commit()
        finally:
            conn.close()

        # Step 1: Probe
        print("\n--- STEP 1: Probe ---")
        probe_result = await run_probe(PROJECT_ID, db_path, project_dir, config)
        verdict("Probe success", probe_result.success,
                expected="success=True",
                actual=f"success={probe_result.success}",
                reason=getattr(probe_result, 'error_message', ''))

        # Verify probe data in DB
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(conn, "SELECT * FROM project WHERE project_id = ?", (PROJECT_ID,))
        finally:
            conn.close()

        if row:
            dur = int(row['duration_ms'])
            verdict("Duration populated", dur > 0,
                    expected="duration_ms > 0",
                    actual=f"duration_ms={dur}")
            verdict("Resolution populated", str(row['resolution']) != "0x0",
                    expected="resolution != 0x0",
                    actual=f"resolution={row['resolution']}")
            verdict("FPS populated", float(row['fps']) > 0,
                    expected="fps > 0",
                    actual=f"fps={row['fps']}")
            verdict("Source SHA256 populated", str(row['source_sha256']) != "pending",
                    expected="source_sha256 != 'pending'",
                    actual=f"source_sha256={str(row['source_sha256'])[:16]}...")
            verdict("Status is 'probed'", str(row['status']) == 'probed',
                    expected="status='probed'",
                    actual=f"status={row['status']}")

        # Step 2: Audio Extract
        print("\n--- STEP 2: Audio Extract ---")
        audio_result = await run_audio_extract(PROJECT_ID, db_path, project_dir, config)
        verdict("Audio extract success", audio_result.success,
                expected="success=True",
                actual=f"success={audio_result.success}",
                reason=getattr(audio_result, 'error_message', ''))

        # Verify audio files
        audio_16k = project_dir / "stems" / "audio_16k.wav"
        audio_orig = project_dir / "stems" / "audio_original.wav"
        verdict("audio_16k.wav exists", audio_16k.exists(),
                expected=f"{audio_16k} exists",
                actual=f"exists={audio_16k.exists()}")
        verdict("audio_16k.wav non-empty", audio_16k.exists() and audio_16k.stat().st_size > 0,
                expected="size > 0",
                actual=f"size={audio_16k.stat().st_size if audio_16k.exists() else 0}")
        verdict("audio_original.wav exists", audio_orig.exists(),
                expected=f"{audio_orig} exists",
                actual=f"exists={audio_orig.exists()}")
        verdict("audio_original.wav non-empty", audio_orig.exists() and audio_orig.stat().st_size > 0,
                expected="size > 0",
                actual=f"size={audio_orig.stat().st_size if audio_orig.exists() else 0}")

        # Step 3: Frame Extract
        print("\n--- STEP 3: Frame Extract ---")
        frame_result = await run_frame_extract(PROJECT_ID, db_path, project_dir, config)
        verdict("Frame extract success", frame_result.success,
                expected="success=True",
                actual=f"success={frame_result.success}",
                reason=getattr(frame_result, 'error_message', ''))

        frames_dir = project_dir / "frames"
        frame_files = sorted(frames_dir.glob("frame_*.jpg"))
        frame_count = len(frame_files)
        verdict("Frames extracted", frame_count > 0,
                expected="frame count > 0",
                actual=f"frame count={frame_count}")

        if frame_files:
            first_frame = frame_files[0]
            last_frame = frame_files[-1]
            sample_size = first_frame.stat().st_size
            print(f"  First frame: {first_frame.name} ({sample_size} bytes)")
            print(f"  Last frame: {last_frame.name} ({last_frame.stat().st_size} bytes)")
            verdict("Frame files are JPEGs with content", sample_size > 100,
                    expected="frame size > 100 bytes",
                    actual=f"first frame size={sample_size}")

        # Step 4: Acoustic Analysis
        print("\n--- STEP 4: Acoustic Analysis ---")
        acoustic_result = await run_acoustic(PROJECT_ID, db_path, project_dir, config)
        verdict("Acoustic analysis success", acoustic_result.success,
                expected="success=True",
                actual=f"success={acoustic_result.success}",
                reason=getattr(acoustic_result, 'error_message', ''))

        # Step 5: Storyboard Generation
        print("\n--- STEP 5: Storyboard Generation ---")
        storyboard_result = await run_storyboard(PROJECT_ID, db_path, project_dir, config)
        verdict("Storyboard generation success", storyboard_result.success,
                expected="success=True",
                actual=f"success={storyboard_result.success}",
                reason=getattr(storyboard_result, 'error_message', ''))

        # Verify storyboard files
        storyboard_dir = project_dir / "storyboards"
        grid_files = sorted(storyboard_dir.glob("grid_*.jpg"))
        verdict("Storyboard grids created", len(grid_files) > 0,
                expected="grid count > 0",
                actual=f"grid count={len(grid_files)}")

        if grid_files:
            # Verify grid dimensions with PIL
            from PIL import Image
            first_grid = Image.open(grid_files[0])
            print(f"  First grid: {grid_files[0].name}, size={first_grid.size}, file_size={grid_files[0].stat().st_size}")
            verdict("Grid dimensions correct", first_grid.size[0] == 1044 and first_grid.size[1] == 1044,
                    expected="1044x1044",
                    actual=f"{first_grid.size[0]}x{first_grid.size[1]}")

        # Step 6: Profanity Detection (runs even without transcripts)
        print("\n--- STEP 6: Profanity Detection ---")
        profanity_result = await run_profanity(PROJECT_ID, db_path, project_dir, config)
        verdict("Profanity detection success", profanity_result.success,
                expected="success=True",
                actual=f"success={profanity_result.success}",
                reason=getattr(profanity_result, 'error_message', ''))

        # Step 7: Chronemic Analysis (runs even without transcripts)
        print("\n--- STEP 7: Chronemic Analysis ---")
        chronemic_result = await run_chronemic(PROJECT_ID, db_path, project_dir, config)
        verdict("Chronemic analysis success", chronemic_result.success,
                expected="success=True",
                actual=f"success={chronemic_result.success}",
                reason=getattr(chronemic_result, 'error_message', ''))

        # Step 8: Highlight Scoring
        print("\n--- STEP 8: Highlight Scoring ---")
        highlight_result = await run_highlights(PROJECT_ID, db_path, project_dir, config)
        verdict("Highlight scoring success", highlight_result.success,
                expected="success=True",
                actual=f"success={highlight_result.success}",
                reason=getattr(highlight_result, 'error_message', ''))

        # Step 9: Finalize
        print("\n--- STEP 9: Finalize ---")
        finalize_result = await run_finalize(PROJECT_ID, db_path, project_dir, config)
        verdict("Finalize success", finalize_result.success,
                expected="success=True",
                actual=f"success={finalize_result.success}",
                reason=getattr(finalize_result, 'error_message', ''))

        # ===== DATABASE DEEP INSPECTION (Source of Truth) =====
        print(f"\n{'#'*60}")
        print(f"# DATABASE DEEP INSPECTION (RAW SQLITE3)")
        print(f"{'#'*60}")

        # Use RAW sqlite3, not the app's helpers
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.row_factory = sqlite3.Row

        tables_to_check = [
            "project", "silence_gaps", "acoustic", "beats", "beat_sections",
            "music_sections", "pacing", "content_safety", "profanity_events",
            "highlights", "storyboard_grids", "stream_status", "provenance"
        ]

        for table in tables_to_check:
            try:
                count = raw_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                rows = raw_conn.execute(f"SELECT * FROM {table} LIMIT 3").fetchall()
                print(f"\n--- TABLE: {table} --- COUNT: {count}")
                for r in rows:
                    print(f"  {dict(r)}")

                # Some tables might be empty because we skipped transcription etc.
                # Required tables are: project (1), acoustic (1), content_safety (1+)
                # highlights, pacing, storyboard_grids, stream_status, provenance
                if table in ("project", "acoustic", "content_safety", "provenance", "stream_status"):
                    verdict(f"Table {table} has data", count > 0,
                            expected=f"{table} count > 0",
                            actual=f"count={count}")
                else:
                    print(f"  ({table}: {count} rows)")
            except Exception as e:
                print(f"  ERROR querying {table}: {e}")
                verdict(f"Table {table} queryable", False, reason=str(e))

        raw_conn.close()

        # ===== PROVENANCE CHAIN VERIFICATION =====
        print(f"\n{'#'*60}")
        print(f"# PROVENANCE CHAIN VERIFICATION")
        print(f"{'#'*60}")

        from clipcannon.provenance import verify_chain

        chain_result = verify_chain(PROJECT_ID, db_path)
        verdict("Provenance chain verified", chain_result.verified,
                expected="verified=True",
                actual=f"verified={chain_result.verified}, records={chain_result.total_records}",
                reason=chain_result.issue or "")

        # Independent chain hash recomputation
        print("\n--- Independent Chain Hash Recomputation ---")
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.row_factory = sqlite3.Row
        prov_rows = raw_conn.execute(
            "SELECT * FROM provenance WHERE project_id = ? ORDER BY timestamp_utc ASC, record_id ASC",
            (PROJECT_ID,)
        ).fetchall()
        raw_conn.close()

        record_hash_map = {}
        chain_ok = True
        for prov_row in prov_rows:
            pr = dict(prov_row)
            parent_id = pr['parent_record_id']
            if parent_id is None:
                parent_hash = "GENESIS"
            else:
                parent_hash = record_hash_map.get(parent_id, "")

            model_params = {}
            if pr.get('model_parameters'):
                try:
                    model_params = json.loads(pr['model_parameters'])
                except (json.JSONDecodeError, TypeError):
                    pass

            preimage = (
                f"{parent_hash}|{pr.get('input_sha256') or ''}|{pr.get('output_sha256') or ''}|"
                f"{pr['operation']}|{pr.get('model_name') or ''}|{pr.get('model_version') or ''}|"
                f"{json.dumps(model_params, sort_keys=True)}"
            )
            expected_hash = hashlib.sha256(preimage.encode("utf-8")).hexdigest()

            if expected_hash != pr['chain_hash']:
                print(f"  MISMATCH at {pr['record_id']}: expected={expected_hash[:16]}..., stored={pr['chain_hash'][:16]}...")
                chain_ok = False
            else:
                print(f"  OK: {pr['record_id']} chain_hash matches ({pr['chain_hash'][:16]}...)")
                record_hash_map[pr['record_id']] = pr['chain_hash']

        verdict("Independent chain hash recomputation", chain_ok,
                expected="All chain hashes match",
                actual=f"match={chain_ok}, records={len(prov_rows)}")

        # ===== TAMPER TEST =====
        print("\n--- Tamper Test: Modify provenance record ---")
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.row_factory = sqlite3.Row
        first_prov = raw_conn.execute(
            "SELECT record_id, input_sha256 FROM provenance WHERE project_id = ? ORDER BY timestamp_utc ASC LIMIT 1",
            (PROJECT_ID,)
        ).fetchone()
        if first_prov:
            original_sha = first_prov['input_sha256']
            raw_conn.execute(
                "UPDATE provenance SET input_sha256 = ? WHERE record_id = ?",
                ("TAMPERED_" + (original_sha or ""), first_prov['record_id'])
            )
            raw_conn.commit()
            raw_conn.close()

            tamper_result = verify_chain(PROJECT_ID, db_path)
            verdict("Tamper detected in provenance", not tamper_result.verified,
                    expected="verified=False (tamper detected)",
                    actual=f"verified={tamper_result.verified}, broken_at={tamper_result.broken_at}",
                    reason=tamper_result.issue or "")

            # Restore
            raw_conn = sqlite3.connect(str(db_path))
            raw_conn.execute(
                "UPDATE provenance SET input_sha256 = ? WHERE record_id = ?",
                (original_sha, first_prov['record_id'])
            )
            raw_conn.commit()
            raw_conn.close()

            # Verify restoration
            restore_result = verify_chain(PROJECT_ID, db_path)
            verdict("Chain restored after fix", restore_result.verified,
                    expected="verified=True",
                    actual=f"verified={restore_result.verified}")

        # ===== FILE TAMPER TEST =====
        print("\n--- File Tamper Test: Modify frame file ---")
        if frame_files:
            test_frame = frame_files[0]
            original_hash = sha256_file(test_frame)

            # Append 1 byte
            with open(test_frame, "ab") as f:
                f.write(b"\x00")

            tampered_hash = sha256_file(test_frame)
            verdict("File tamper changes hash", original_hash != tampered_hash,
                    expected="hash changes after tampering",
                    actual=f"original={original_hash[:16]}... tampered={tampered_hash[:16]}...")

            # Restore by removing the byte
            with open(test_frame, "rb") as f:
                data = f.read()
            with open(test_frame, "wb") as f:
                f.write(data[:-1])

        # Print final project status
        print("\n--- Final Project Status (raw DB) ---")
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.row_factory = sqlite3.Row
        proj = raw_conn.execute("SELECT status FROM project WHERE project_id = ?", (PROJECT_ID,)).fetchone()
        if proj:
            verdict("Final project status is 'ready'", proj['status'] == 'ready',
                    expected="status='ready'",
                    actual=f"status={proj['status']}")
        raw_conn.close()

    finally:
        # Cleanup
        if base_dir.exists():
            shutil.rmtree(base_dir, ignore_errors=True)

    return VERDICTS


if __name__ == "__main__":
    results = asyncio.run(run_full_pipeline())

    print(f"\n\n{'='*60}")
    print("FSV PART 1 SUMMARY")
    print(f"{'='*60}")
    passes = sum(1 for _, s, _ in results if s == "PASS")
    fails = sum(1 for _, s, _ in results if s == "FAIL")
    for name, status, reason in results:
        marker = "[PASS]" if status == "PASS" else "[FAIL]"
        line = f"  {marker} {name}"
        if reason and status == "FAIL":
            line += f" -- {reason}"
        print(line)
    print(f"\nTotal: {passes} passed, {fails} failed out of {len(results)}")
