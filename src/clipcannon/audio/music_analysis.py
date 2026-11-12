"""Video-analysis helpers behind the music planner.

Reads emotion, pacing, beat and speech data from a project's analysis.db
and maps it to music parameters (mood, energy, tempo, key, ACE-Step
prompt). Split out of ``clipcannon.audio.music_planner`` (pure move).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from clipcannon.db.queries import fetch_all, fetch_one

logger = logging.getLogger(__name__)


@dataclass
class MusicBrief:
    """Structured music parameters derived from video analysis."""

    overall_mood: str
    energy_level: str
    suggested_tempo_bpm: int
    suggested_key: str
    suggested_preset: str
    ace_step_prompt: str
    edit_duration_ms: int
    speech_regions: list[tuple[int, int]] = field(default_factory=list)


# ============================================================
# Mood -> music parameter mapping table
# ============================================================
# Each entry: (preset, key, bpm_low, bpm_high)
_MOOD_MAP: dict[str, tuple[str, str, int, int]] = {
    "joy": ("upbeat_pop", "C", 120, 140),
    "excitement": ("upbeat_pop", "C", 120, 140),
    "happiness": ("upbeat_pop", "C", 120, 140),
    "calm": ("ambient_pad", "C", 60, 80),
    "neutral": ("lofi_chill", "C", 60, 80),
    "sadness": ("minimal_piano", "Am", 60, 80),
    "tension": ("dramatic", "Am", 90, 120),
    "anger": ("dramatic", "Am", 90, 120),
    "fear": ("dramatic", "Am", 90, 120),
    "professional": ("corporate", "C", 90, 110),
    "inspiring": ("cinematic_epic", "C", 100, 130),
    "surprise": ("cinematic_epic", "C", 100, 130),
}

# Default fallback when video analysis is unavailable
_DEFAULT_BRIEF = MusicBrief(
    overall_mood="professional",
    energy_level="medium",
    suggested_tempo_bpm=100,
    suggested_key="C",
    suggested_preset="corporate",
    ace_step_prompt=(
        "professional corporate background music, "
        "100 BPM, medium energy, warm, polished"
    ),
    edit_duration_ms=60000,
    speech_regions=[],
)


def _table_exists(conn: object, table_name: str) -> bool:
    """Check if a table exists in the database."""
    try:
        row = fetch_one(
            conn,  # type: ignore[arg-type]
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return row is not None
    except Exception:
        return False


def _aggregate_emotions(
    conn: object, project_id: str, start_ms: int, end_ms: int,
) -> tuple[str, float, float]:
    """Aggregate emotion_curve data for a time range.

    Returns:
        (dominant_emotion, avg_valence, avg_arousal).
        Falls back to ("neutral", 0.5, 0.5) if no data.

    Handles two schemas:
      - New: columns include dominant_emotion, valence, arousal
      - Legacy: columns are valence, arousal, energy (no dominant_emotion)
    """
    if not _table_exists(conn, "emotion_curve"):
        logger.debug("emotion_curve table not found; using defaults")
        return "neutral", 0.5, 0.5

    # Detect which columns exist
    try:
        col_info = fetch_all(conn, "PRAGMA table_info(emotion_curve)", ())  # type: ignore[arg-type]
        col_names = {str(c["name"]) if isinstance(c, dict) else str(c[1]) for c in col_info}
    except Exception:
        col_names = set()

    has_dominant = "dominant_emotion" in col_names

    if has_dominant:
        query = """SELECT dominant_emotion, valence, arousal
                   FROM emotion_curve
                   WHERE project_id = ? AND start_ms >= ? AND end_ms <= ?"""
    else:
        query = """SELECT valence, arousal
                   FROM emotion_curve
                   WHERE project_id = ? AND start_ms >= ? AND end_ms <= ?"""

    rows = fetch_all(conn, query, (project_id, start_ms, end_ms))  # type: ignore[arg-type]

    if not rows:
        # Try without time range filter (some projects have overlapping windows)
        if has_dominant:
            rows = fetch_all(
                conn,  # type: ignore[arg-type]
                "SELECT dominant_emotion, valence, arousal FROM emotion_curve WHERE project_id = ?",
                (project_id,),
            )
        else:
            rows = fetch_all(
                conn,  # type: ignore[arg-type]
                "SELECT valence, arousal FROM emotion_curve WHERE project_id = ?",
                (project_id,),
            )

    if not rows:
        logger.debug(
            "No emotion_curve rows for project=%s range=[%d, %d]; defaults",
            project_id, start_ms, end_ms,
        )
        return "neutral", 0.5, 0.5

    total_valence, total_arousal = 0.0, 0.0
    counts: dict[str, int] = {}

    for row in rows:
        total_valence += float(row.get("valence", 0.5) if isinstance(row, dict) else 0.5)
        total_arousal += float(row.get("arousal", 0.5) if isinstance(row, dict) else 0.5)
        if has_dominant:
            emotion = str(
                row.get("dominant_emotion", "neutral") if isinstance(row, dict) else "neutral"
            ).lower()
        else:
            emotion = ""  # Will be classified from valence/arousal below
        if emotion:
            counts[emotion] = counts.get(emotion, 0) + 1

    avg_valence = total_valence / len(rows)
    avg_arousal = total_arousal / len(rows)

    # No dominant_emotion column -> "" (classified from valence/arousal by _classify_mood)
    dominant = max(counts, key=counts.get) if counts else ""  # type: ignore[arg-type]

    return dominant, avg_valence, avg_arousal


def _determine_energy(
    conn: object, project_id: str, start_ms: int, end_ms: int,
    avg_arousal: float,
) -> str:
    """Determine energy level from pacing data and arousal.

    Returns:
        "low", "medium", or "high".
    """
    if not _table_exists(conn, "pacing"):
        # Fall back to arousal-based estimation
        if avg_arousal > 0.65:
            return "high"
        if avg_arousal < 0.35:
            return "low"
        return "medium"

    # Detect column name: real DB uses 'label', test schema uses 'pace_label'
    try:
        col_info = fetch_all(conn, "PRAGMA table_info(pacing)", ())  # type: ignore[arg-type]
        col_names = {str(c["name"]) if isinstance(c, dict) else str(c[1]) for c in col_info}
    except Exception:
        col_names = set()

    label_col = "label" if "label" in col_names else "pace_label"

    rows = fetch_all(
        conn,  # type: ignore[arg-type]
        f"""SELECT {label_col} AS pace_label FROM pacing
           WHERE project_id = ?
             AND start_ms >= ? AND end_ms <= ?""",
        (project_id, start_ms, end_ms),
    )

    if not rows:
        # Try without time range filter
        rows = fetch_all(
            conn,  # type: ignore[arg-type]
            f"SELECT {label_col} AS pace_label FROM pacing WHERE project_id = ?",
            (project_id,),
        )

    if not rows:
        if avg_arousal > 0.65:
            return "high"
        if avg_arousal < 0.35:
            return "low"
        return "medium"

    # Count pace labels
    fast_count = sum(
        1 for r in rows if str(r.get("pace_label", "")).lower() == "fast"
    )
    slow_count = sum(
        1 for r in rows if str(r.get("pace_label", "")).lower() == "slow"
    )
    total = len(rows)

    if fast_count > total * 0.5:
        return "high"
    if slow_count > total * 0.5:
        return "low"
    return "medium"


def _suggest_tempo(
    conn: object, project_id: str, start_ms: int, end_ms: int,
    mood: str, energy: str,
) -> int:
    """Suggest tempo from beat_sections or mood mapping.

    Returns:
        Suggested BPM as integer.
    """
    # Try beat_sections for real tempo data
    if _table_exists(conn, "beat_sections"):
        # Detect column: real DB uses 'tempo_bpm', test schema uses 'avg_bpm'
        try:
            col_info = fetch_all(conn, "PRAGMA table_info(beat_sections)", ())  # type: ignore[arg-type]
            col_names = {str(c["name"]) if isinstance(c, dict) else str(c[1]) for c in col_info}
        except Exception:
            col_names = set()
        bpm_col = "tempo_bpm" if "tempo_bpm" in col_names else "avg_bpm"

        rows = fetch_all(
            conn,  # type: ignore[arg-type]
            f"""SELECT {bpm_col} AS bpm FROM beat_sections
               WHERE project_id = ?
                 AND start_ms >= ? AND end_ms <= ?
                 AND {bpm_col} > 0""",
            (project_id, start_ms, end_ms),
        )
        if not rows:
            rows = fetch_all(
                conn,  # type: ignore[arg-type]
                f"SELECT {bpm_col} AS bpm FROM beat_sections "
                f"WHERE project_id = ? AND {bpm_col} > 0",
                (project_id,),
            )
        if rows:
            avg_bpm = sum(float(r["bpm"]) for r in rows) / len(rows)
            return max(50, min(180, int(round(avg_bpm))))

    # Fall back to mood-based tempo
    _, _, bpm_low, bpm_high = _MOOD_MAP.get(
        mood, ("corporate", "C", 90, 110)
    )
    # Shift within range based on energy
    if energy == "high":
        return bpm_high
    if energy == "low":
        return bpm_low
    return (bpm_low + bpm_high) // 2


def _map_mood_to_music(mood: str) -> tuple[str, str]:
    """Map a mood to (preset, key).

    Returns:
        (preset_name, musical_key).
    """
    entry = _MOOD_MAP.get(mood)
    if entry:
        return entry[0], entry[1]
    # Default
    return "corporate", "C"


def _build_ace_step_prompt(
    mood: str, energy: str, tempo: int, key: str,
) -> str:
    """Build a text prompt suitable for ACE-Step generation.

    Returns:
        A descriptive prompt string.
    """
    # Mood descriptors
    mood_words: dict[str, str] = {
        "joy": "upbeat joyful cheerful",
        "excitement": "exciting energetic dynamic",
        "happiness": "happy bright uplifting",
        "calm": "calm peaceful serene ambient",
        "neutral": "gentle smooth background",
        "sadness": "melancholic emotional gentle piano",
        "tension": "tense dramatic suspenseful",
        "anger": "intense powerful aggressive",
        "fear": "dark ominous suspenseful",
        "professional": "professional corporate polished warm",
        "inspiring": "inspiring cinematic epic soaring",
        "surprise": "dynamic surprising cinematic",
    }

    descriptors = mood_words.get(mood, "professional background")

    # Energy modifier
    energy_words = {
        "low": "soft understated minimal",
        "medium": "balanced moderate steady",
        "high": "powerful driving full",
    }
    energy_desc = energy_words.get(energy, "moderate")

    return (
        f"{descriptors} background music, "
        f"{tempo} BPM, key of {key}, "
        f"{energy_desc} energy, "
        "instrumental, no vocals"
    )


def _get_speech_regions(
    conn: object, project_id: str, start_ms: int, end_ms: int,
) -> list[tuple[int, int]]:
    """Extract speech regions from transcript_segments for ducking.

    Returns:
        List of (start_ms, end_ms) tuples where speech occurs.
    """
    if not _table_exists(conn, "transcript_segments"):
        return []

    rows = fetch_all(
        conn,  # type: ignore[arg-type]
        """SELECT start_ms, end_ms FROM transcript_segments
           WHERE project_id = ?
             AND start_ms >= ? AND end_ms <= ?
           ORDER BY start_ms""",
        (project_id, start_ms, end_ms),
    )

    if not rows:
        return []

    return [
        (int(r["start_ms"]), int(r["end_ms"]))
        for r in rows
        if r.get("start_ms") is not None and r.get("end_ms") is not None
    ]
