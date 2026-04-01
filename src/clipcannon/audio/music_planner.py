"""Video-aware music planning engine.

Reads video analysis data and produces a MusicBrief with ideal music
parameters for a given edit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from clipcannon.db.connection import get_connection
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
            emotion = str(row.get("dominant_emotion", "neutral") if isinstance(row, dict) else "neutral").lower()
        else:
            emotion = ""  # Will be classified from valence/arousal below
        if emotion:
            counts[emotion] = counts.get(emotion, 0) + 1

    avg_valence = total_valence / len(rows)
    avg_arousal = total_arousal / len(rows)

    if counts:
        dominant = max(counts, key=counts.get)  # type: ignore[arg-type]
    else:
        # No dominant_emotion column -- classify from valence/arousal
        dominant = ""  # Will be classified by _classify_mood

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
                f"SELECT {bpm_col} AS bpm FROM beat_sections WHERE project_id = ? AND {bpm_col} > 0",
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


class MusicPlanner:
    """Analyzes video data and produces music generation parameters.

    Reads emotion curves, pacing data, beat sections, and transcript
    segments from a project's analysis.db to generate a ``MusicBrief``
    tailored to the content of a specific edit.
    """

    def plan_for_edit(
        self,
        db_path: Path,
        project_id: str,
        edit_id: str,
    ) -> MusicBrief:
        """Analyze video data and produce a MusicBrief for an edit.

        Reads the edit's time range, queries emotion/pacing/beat data
        for that range, and maps the analysis to music parameters.
        Handles gracefully when analysis tables are empty or missing
        by falling back to sensible defaults.

        Args:
            db_path: Path to the project's analysis.db.
            project_id: Project identifier.
            edit_id: Edit identifier.

        Returns:
            A MusicBrief with all music parameters populated.

        Raises:
            ValueError: If the edit is not found in the database.
        """
        if not db_path.exists():
            logger.warning(
                "Database not found at %s; returning default brief", db_path
            )
            return _DEFAULT_BRIEF

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            return self._plan(conn, project_id, edit_id)
        finally:
            conn.close()

    def _plan(
        self, conn: object, project_id: str, edit_id: str,
    ) -> MusicBrief:
        """Core planning logic with an open connection."""
        # Step 1: Get edit duration and time range
        edit_duration_ms, start_ms, end_ms = self._get_edit_range(
            conn, project_id, edit_id,
        )

        # Step 2: Aggregate emotions
        dominant_emotion, avg_valence, avg_arousal = _aggregate_emotions(
            conn, project_id, start_ms, end_ms,
        )

        # Step 3: Map raw emotion to our mood categories
        mood = self._classify_mood(dominant_emotion, avg_valence, avg_arousal)

        # Step 4: Determine energy from pacing
        energy = _determine_energy(
            conn, project_id, start_ms, end_ms, avg_arousal,
        )

        # Step 5: Suggest tempo
        tempo = _suggest_tempo(
            conn, project_id, start_ms, end_ms, mood, energy,
        )

        # Step 6: Map mood to preset and key
        preset, key = _map_mood_to_music(mood)

        # Step 7: Build ACE-Step prompt
        ace_prompt = _build_ace_step_prompt(mood, energy, tempo, key)

        # Step 8: Get speech regions for ducking
        speech_regions = _get_speech_regions(
            conn, project_id, start_ms, end_ms,
        )

        brief = MusicBrief(
            overall_mood=mood,
            energy_level=energy,
            suggested_tempo_bpm=tempo,
            suggested_key=key,
            suggested_preset=preset,
            ace_step_prompt=ace_prompt,
            edit_duration_ms=edit_duration_ms,
            speech_regions=speech_regions,
        )

        logger.info(
            "MusicBrief for edit=%s: mood=%s, energy=%s, tempo=%d, "
            "preset=%s, key=%s, duration=%dms, speech_regions=%d",
            edit_id, mood, energy, tempo, preset, key,
            edit_duration_ms, len(speech_regions),
        )

        return brief

    def _get_edit_range(
        self, conn: object, project_id: str, edit_id: str,
    ) -> tuple[int, int, int]:
        """Get total duration and source time range of an edit.

        Returns:
            (total_duration_ms, earliest_start_ms, latest_end_ms).
        """
        # Get edit duration
        edit_row = fetch_one(
            conn,  # type: ignore[arg-type]
            "SELECT total_duration_ms FROM edits WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
        if edit_row is None:
            raise ValueError(
                f"Edit not found: {edit_id} in project {project_id}"
            )

        total_duration_ms = int(edit_row.get("total_duration_ms", 60000))

        # Get segment time ranges to know what source content is covered
        if _table_exists(conn, "edit_segments"):
            segments = fetch_all(
                conn,  # type: ignore[arg-type]
                """SELECT source_start_ms, source_end_ms
                   FROM edit_segments
                   WHERE edit_id = ?
                   ORDER BY source_start_ms""",
                (edit_id,),
            )
            if segments:
                start_ms = min(
                    int(s["source_start_ms"]) for s in segments
                )
                end_ms = max(
                    int(s["source_end_ms"]) for s in segments
                )
                return total_duration_ms, start_ms, end_ms

        # Fallback: use 0 to total_duration_ms
        return total_duration_ms, 0, total_duration_ms

    @staticmethod
    def _classify_mood(
        dominant_emotion: str, avg_valence: float, avg_arousal: float,
    ) -> str:
        """Classify raw emotion data into our mood categories.

        Combines the dominant emotion label with valence/arousal scores
        to produce a stable mood classification.

        Returns:
            One of: joy, calm, sadness, tension, professional, inspiring.
        """
        emotion = dominant_emotion.lower()

        # Direct mappings
        direct_map: dict[str, str] = {
            "joy": "joy",
            "happiness": "joy",
            "happy": "joy",
            "excitement": "joy",
            "excited": "joy",
            "calm": "calm",
            "relaxed": "calm",
            "peaceful": "calm",
            "sad": "sadness",
            "sadness": "sadness",
            "melancholy": "sadness",
            "tense": "tension",
            "tension": "tension",
            "fear": "tension",
            "anger": "tension",
            "angry": "tension",
            "surprise": "inspiring",
            "awe": "inspiring",
            "inspired": "inspiring",
        }

        mapped = direct_map.get(emotion)
        if mapped:
            return mapped

        # Fall back to valence/arousal quadrant analysis
        if avg_valence > 0.6 and avg_arousal > 0.6:
            return "joy"
        if avg_valence > 0.6 and avg_arousal <= 0.6:
            return "calm"
        if avg_valence <= 0.4 and avg_arousal > 0.6:
            return "tension"
        if avg_valence <= 0.4 and avg_arousal <= 0.4:
            return "sadness"

        # Neutral zone
        return "professional"
