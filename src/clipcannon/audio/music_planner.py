"""Video-aware music planning engine.

Reads video analysis data and produces a MusicBrief with ideal music
parameters for a given edit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass as dataclass
from dataclasses import field as field
from pathlib import Path  # noqa: TC003 - kept at runtime on the module surface

from clipcannon.audio.music_analysis import (
    _DEFAULT_BRIEF,
    MusicBrief,
    _aggregate_emotions,
    _build_ace_step_prompt,
    _determine_energy,
    _get_speech_regions,
    _map_mood_to_music,
    _suggest_tempo,
    _table_exists,
)
from clipcannon.audio.music_analysis import _MOOD_MAP as _MOOD_MAP_TABLE
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one

logger = logging.getLogger(__name__)

# Same dict object as music_analysis._MOOD_MAP, re-bound with its annotation so this
# module keeps the module-level ``__annotations__`` it exposed before the split.
_MOOD_MAP: dict[str, tuple[str, str, int, int]] = _MOOD_MAP_TABLE


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
