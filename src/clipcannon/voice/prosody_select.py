"""Prosody-aware reference clip selection for voice cloning.

Selects the best reference audio clip from the prosody_segments table
based on a target prosody style. Used by clipcannon_speak to
automatically pick reference clips that match the desired delivery.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Style presets map to SQL query conditions
STYLE_PRESETS: dict[str, dict[str, object]] = {
    "energetic": {
        "energy_level": "high",
        "min_prosody_score": 50,
        "order": "prosody_score DESC",
    },
    "calm": {
        "energy_level": "low",
        "pitch_contour_type": "flat",
        "order": "speaking_rate_wpm ASC",
    },
    "emphatic": {
        "has_emphasis": 1,
        "min_prosody_score": 40,
        "order": "f0_range DESC",
    },
    "varied": {
        "pitch_contour_type": "varied",
        "min_prosody_score": 40,
        "order": "f0_std DESC",
    },
    "fast": {
        "min_speaking_rate": 160,
        "order": "speaking_rate_wpm DESC",
    },
    "slow": {
        "max_speaking_rate": 120,
        "order": "speaking_rate_wpm ASC",
    },
    "rising": {
        "pitch_contour_type": "rising",
        "order": "prosody_score DESC",
    },
    "question": {
        "pitch_contour_type": "rising",
        "order": "f0_range DESC",
    },
    "best": {
        "min_prosody_score": 0,
        "order": "prosody_score DESC",
    },
}


def select_prosody_reference(
    voice_name: str,
    style: str = "best",
    project_ids: list[str] | None = None,
) -> Path | None:
    """Select the best reference clip matching a prosody style.

    Searches the prosody_segments table across all projects associated
    with the voice profile, or specific projects if given.

    Args:
        voice_name: Voice profile name (to find associated projects).
        style: Prosody style preset name or "best" for highest score.
        project_ids: Specific project IDs to search. If None, uses
            all projects from the voice profile's training_projects.

    Returns:
        Path to the best matching reference clip, or None if no match.
    """
    import json as _json

    # Resolve project IDs from voice profile if not given
    if project_ids is None:
        from clipcannon.voice.profiles import get_voice_profile

        db_path = Path.home() / ".clipcannon" / "voice_profiles.db"
        profile = get_voice_profile(db_path, voice_name)
        if profile is None:
            return None

        training_projects = profile.get("training_projects", "[]")
        try:
            project_ids = _json.loads(training_projects) if isinstance(training_projects, str) else []
        except Exception:
            project_ids = []

    if not project_ids:
        return None

    preset = STYLE_PRESETS.get(style, STYLE_PRESETS["best"])

    projects_base = Path.home() / ".clipcannon" / "projects"

    best_clip: Path | None = None
    best_score: float = -1

    for pid in project_ids:
        db_path = projects_base / pid / "analysis.db"
        if not db_path.exists():
            continue

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            # Build query from preset
            conditions = ["project_id = ?"]
            params: list[object] = [pid]

            if "energy_level" in preset:
                conditions.append("energy_level = ?")
                params.append(preset["energy_level"])

            if "pitch_contour_type" in preset:
                conditions.append("pitch_contour_type = ?")
                params.append(preset["pitch_contour_type"])

            if "has_emphasis" in preset:
                conditions.append("has_emphasis = ?")
                params.append(preset["has_emphasis"])

            if "min_prosody_score" in preset:
                conditions.append("prosody_score >= ?")
                params.append(preset["min_prosody_score"])

            if "min_speaking_rate" in preset:
                conditions.append("speaking_rate_wpm >= ?")
                params.append(preset["min_speaking_rate"])

            if "max_speaking_rate" in preset:
                conditions.append("speaking_rate_wpm <= ?")
                params.append(preset["max_speaking_rate"])

            # Must have a clip file
            conditions.append("clip_path IS NOT NULL")

            order = str(preset.get("order", "prosody_score DESC"))
            where = " AND ".join(conditions)

            query = f"SELECT clip_path, prosody_score FROM prosody_segments WHERE {where} ORDER BY {order} LIMIT 5"  # noqa: S608
            rows = conn.execute(query, params).fetchall()

            for row in rows:
                clip = Path(str(row["clip_path"]))
                score = float(row["prosody_score"])
                if clip.exists() and score > best_score:
                    best_score = score
                    best_clip = clip

        except sqlite3.OperationalError:
            continue
        finally:
            conn.close()

    if best_clip is not None:
        logger.info(
            "Prosody reference selected: style=%s, score=%.1f, clip=%s",
            style, best_score, best_clip.name,
        )

    return best_clip


def get_prosody_stats(
    project_id: str,
) -> dict[str, object]:
    """Get prosody statistics for a project.

    Returns:
        Dict with total segments, score distribution, style breakdown.
    """
    db_path = Path.home() / ".clipcannon" / "projects" / project_id / "analysis.db"
    if not db_path.exists():
        return {"error": "Project not found"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute(
            "SELECT COUNT(*) as n FROM prosody_segments WHERE project_id = ?",
            (project_id,),
        ).fetchone()

        if total is None or int(total["n"]) == 0:
            return {"total_segments": 0}

        stats = conn.execute(
            "SELECT "
            "  COUNT(*) as total, "
            "  AVG(prosody_score) as avg_score, "
            "  MAX(prosody_score) as max_score, "
            "  AVG(f0_range) as avg_pitch_range, "
            "  AVG(speaking_rate_wpm) as avg_rate "
            "FROM prosody_segments WHERE project_id = ?",
            (project_id,),
        ).fetchone()

        by_energy = conn.execute(
            "SELECT energy_level, COUNT(*) as n "
            "FROM prosody_segments WHERE project_id = ? "
            "GROUP BY energy_level",
            (project_id,),
        ).fetchall()

        by_contour = conn.execute(
            "SELECT pitch_contour_type, COUNT(*) as n "
            "FROM prosody_segments WHERE project_id = ? "
            "GROUP BY pitch_contour_type",
            (project_id,),
        ).fetchall()

        return {
            "total_segments": int(stats["total"]),
            "avg_prosody_score": round(float(stats["avg_score"]), 1),
            "max_prosody_score": round(float(stats["max_score"]), 1),
            "avg_pitch_range_hz": round(float(stats["avg_pitch_range"]), 1),
            "avg_speaking_rate_wpm": round(float(stats["avg_rate"]), 1),
            "energy_distribution": {str(r["energy_level"]): int(r["n"]) for r in by_energy},
            "contour_distribution": {str(r["pitch_contour_type"]): int(r["n"]) for r in by_contour},
        }

    except sqlite3.OperationalError:
        return {"total_segments": 0, "note": "prosody_segments table not found"}
    finally:
        conn.close()
