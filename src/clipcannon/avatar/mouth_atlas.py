"""Mouth atlas builder for MouthMemory voice profiles.

Aggregates mouth_frames data from multiple ingested projects into
a single atlas database stored alongside the voice profile data.
The atlas provides richer viseme coverage for lip-sync generation.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)


async def build_mouth_atlas(
    voice_name: str,
    project_ids: list[str] | None = None,
    min_quality: float = 0.2,
) -> dict[str, object]:
    """Build a mouth atlas for a voice profile.

    Indexes mouth frames from all training projects and merges
    them into a single atlas database.

    Args:
        voice_name: Voice profile name (e.g. "boris").
        project_ids: Specific project IDs. If None, reads from profile.
        min_quality: Minimum quality score for included frames.

    Returns:
        Summary dict with statistics.
    """
    start_time = time.monotonic()

    # Resolve project IDs from voice profile
    if project_ids is None:
        from clipcannon.voice.profiles import get_voice_profile

        profile_db = Path.home() / ".clipcannon" / "voice_profiles.db"
        profile = get_voice_profile(profile_db, voice_name)
        if profile is None:
            return {"error": f"Voice profile not found: {voice_name}"}

        training_projects = profile.get("training_projects", "[]")
        try:
            project_ids = json.loads(training_projects) if isinstance(training_projects, str) else []
        except Exception:
            project_ids = []

    if not project_ids:
        return {"error": "No project IDs available for atlas building"}

    projects_base = Path.home() / ".clipcannon" / "projects"

    # Atlas output location
    atlas_dir = Path.home() / ".clipcannon" / "voice_data" / voice_name
    atlas_dir.mkdir(parents=True, exist_ok=True)
    atlas_db_path = atlas_dir / "mouth_atlas.db"

    from clipcannon.avatar.mouth_index import (
        ensure_mouth_tables,
        index_mouth_frames,
    )

    total_indexed = 0
    total_copied = 0
    processed_projects = 0

    for pid in project_ids:
        proj_dir = projects_base / pid
        db_path = proj_dir / "analysis.db"

        if not db_path.exists():
            logger.debug("Atlas: skipping project %s (no analysis.db)", pid)
            continue

        # Check if source video exists
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT source_cfr_path, source_path FROM project WHERE project_id = ?",
                (pid,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            continue

        video_path = Path(str(row["source_cfr_path"] or row["source_path"]))
        if not video_path.exists():
            logger.debug("Atlas: skipping project %s (video not found)", pid)
            continue

        # Index mouth frames for this project
        logger.info("Atlas: indexing project %s", pid)
        result = await index_mouth_frames(
            pid, db_path, proj_dir, video_path=video_path, fps=25,
        )

        if "error" in result:
            logger.warning("Atlas: failed to index %s: %s", pid, result["error"])
            continue

        frames_indexed = int(result.get("frames_indexed", 0))
        total_indexed += frames_indexed
        processed_projects += 1

        # Copy qualifying frames to atlas DB
        ensure_mouth_tables(atlas_db_path)

        src_conn = sqlite3.connect(str(db_path))
        src_conn.row_factory = sqlite3.Row
        dst_conn = sqlite3.connect(str(atlas_db_path))

        try:
            rows = src_conn.execute(
                "SELECT * FROM mouth_frames "
                "WHERE project_id = ? AND quality_score >= ?",
                (pid, min_quality),
            ).fetchall()

            for row in rows:
                dst_conn.execute(
                    "INSERT INTO mouth_frames ("
                    "  project_id, timestamp_ms, face_crop_path, mouth_crop_path,"
                    "  landmarks_json, head_yaw, head_pitch, head_roll,"
                    "  viseme, phoneme, word, word_position, prev_viseme, next_viseme,"
                    "  mouth_openness, mouth_width, energy, f0, emotion_label,"
                    "  speaker_id, quality_score"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        voice_name,  # Use voice_name as project_id in atlas
                        row["timestamp_ms"], row["face_crop_path"], row["mouth_crop_path"],
                        row["landmarks_json"], row["head_yaw"], row["head_pitch"], row["head_roll"],
                        row["viseme"], row["phoneme"], row["word"], row["word_position"],
                        row["prev_viseme"], row["next_viseme"],
                        row["mouth_openness"], row["mouth_width"], row["energy"],
                        row["f0"], row["emotion_label"],
                        row["speaker_id"], row["quality_score"],
                    ),
                )
                total_copied += 1

            dst_conn.commit()
        finally:
            src_conn.close()
            dst_conn.close()

        logger.info("Atlas: project %s contributed %d frames", pid, frames_indexed)

    elapsed_s = time.monotonic() - start_time

    # Compute viseme coverage in atlas
    coverage: dict[str, int] = {}
    if atlas_db_path.exists():
        conn = sqlite3.connect(str(atlas_db_path))
        try:
            rows = conn.execute(
                "SELECT viseme, COUNT(*) as n FROM mouth_frames "
                "WHERE project_id = ? GROUP BY viseme ORDER BY n DESC",
                (voice_name,),
            ).fetchall()
            coverage = {str(r[0]): int(r[1]) for r in rows}
        finally:
            conn.close()

    logger.info(
        "Atlas build complete: %d projects, %d frames indexed, %d in atlas, %.1fs",
        processed_projects, total_indexed, total_copied, elapsed_s,
    )

    return {
        "voice_name": voice_name,
        "projects_processed": processed_projects,
        "projects_total": len(project_ids),
        "frames_indexed": total_indexed,
        "frames_in_atlas": total_copied,
        "atlas_db": str(atlas_db_path),
        "viseme_coverage": coverage,
        "elapsed_s": round(elapsed_s, 2),
    }
