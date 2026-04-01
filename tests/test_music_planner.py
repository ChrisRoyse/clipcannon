"""Tests for the video-aware music planner and new MCP audio tools.

Tests cover:
- MusicBrief dataclass construction
- MusicPlanner.plan_for_edit with mock databases
- Mood classification from emotion data
- Energy determination from pacing data
- Tempo suggestion from beat sections
- ACE-Step prompt generation
- Default fallbacks when tables are empty
- _map_mood_to_music and _build_ace_step_prompt helpers
- New tool definitions: auto_music, compose_music
- Updated generate_music model parameter
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from clipcannon.audio.music_planner import (
    MusicBrief,
    MusicPlanner,
    _build_ace_step_prompt,
    _map_mood_to_music,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture()
def analysis_db(tmp_path: Path) -> Path:
    """Create a minimal analysis.db with all required tables."""
    db_path = tmp_path / "test_project" / "analysis.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE edits (
            edit_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            edl_json TEXT,
            total_duration_ms INTEGER NOT NULL
        );
        CREATE TABLE edit_segments (
            id INTEGER PRIMARY KEY,
            edit_id TEXT NOT NULL,
            source_start_ms INTEGER NOT NULL,
            source_end_ms INTEGER NOT NULL
        );
        CREATE TABLE emotion_curve (
            project_id TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            valence REAL NOT NULL,
            arousal REAL NOT NULL,
            dominant_emotion TEXT NOT NULL
        );
        CREATE TABLE pacing (
            project_id TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            words_per_minute REAL,
            pause_ratio REAL,
            pace_label TEXT
        );
        CREATE TABLE beat_sections (
            project_id TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            avg_bpm REAL NOT NULL,
            beat_count INTEGER
        );
        CREATE TABLE transcript_segments (
            project_id TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            text TEXT
        );
    """)

    # Insert test edit
    conn.execute(
        "INSERT INTO edits VALUES (?, ?, ?, ?)",
        ("edit_001", "proj_001", "{}", 60000),
    )
    # Insert segments covering 0-60000ms
    conn.execute(
        "INSERT INTO edit_segments VALUES (?, ?, ?, ?)",
        (1, "edit_001", 0, 30000),
    )
    conn.execute(
        "INSERT INTO edit_segments VALUES (?, ?, ?, ?)",
        (2, "edit_001", 30000, 60000),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def planner() -> MusicPlanner:
    """Create a MusicPlanner instance."""
    return MusicPlanner()


# ============================================================
# MusicBrief TESTS
# ============================================================

class TestMusicBrief:
    """Test MusicBrief dataclass."""

    def test_defaults(self) -> None:
        """MusicBrief has correct default for speech_regions."""
        brief = MusicBrief(
            overall_mood="calm",
            energy_level="low",
            suggested_tempo_bpm=70,
            suggested_key="C",
            suggested_preset="ambient_pad",
            ace_step_prompt="calm music",
            edit_duration_ms=30000,
        )
        assert brief.speech_regions == []
        assert brief.overall_mood == "calm"
        assert brief.suggested_tempo_bpm == 70

    def test_with_speech_regions(self) -> None:
        """MusicBrief can store speech regions."""
        brief = MusicBrief(
            overall_mood="professional",
            energy_level="medium",
            suggested_tempo_bpm=100,
            suggested_key="C",
            suggested_preset="corporate",
            ace_step_prompt="corporate background",
            edit_duration_ms=60000,
            speech_regions=[(0, 5000), (10000, 15000)],
        )
        assert len(brief.speech_regions) == 2
        assert brief.speech_regions[0] == (0, 5000)


# ============================================================
# MusicPlanner TESTS
# ============================================================

class TestMusicPlanner:
    """Test MusicPlanner.plan_for_edit."""

    def test_plan_with_empty_analysis(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan returns sensible defaults when analysis tables are empty."""
        brief = planner.plan_for_edit(analysis_db, "proj_001", "edit_001")
        assert isinstance(brief, MusicBrief)
        assert brief.edit_duration_ms == 60000
        # With no emotion data, should default to "professional"
        assert brief.overall_mood == "professional"
        assert brief.energy_level in ("low", "medium", "high")
        assert 50 <= brief.suggested_tempo_bpm <= 180

    def test_plan_with_joy_emotion(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan detects joy mood from emotion curve."""
        conn = sqlite3.connect(str(analysis_db))
        for start in range(0, 60000, 5000):
            conn.execute(
                "INSERT INTO emotion_curve VALUES (?, ?, ?, ?, ?, ?)",
                ("proj_001", start, start + 5000, 0.85, 0.8, "joy"),
            )
        conn.commit()
        conn.close()

        brief = planner.plan_for_edit(analysis_db, "proj_001", "edit_001")
        assert brief.overall_mood == "joy"
        assert brief.suggested_preset == "upbeat_pop"
        assert brief.suggested_key == "C"

    def test_plan_with_sadness_emotion(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan detects sadness mood from emotion curve."""
        conn = sqlite3.connect(str(analysis_db))
        for start in range(0, 60000, 5000):
            conn.execute(
                "INSERT INTO emotion_curve VALUES (?, ?, ?, ?, ?, ?)",
                ("proj_001", start, start + 5000, 0.2, 0.2, "sadness"),
            )
        conn.commit()
        conn.close()

        brief = planner.plan_for_edit(analysis_db, "proj_001", "edit_001")
        assert brief.overall_mood == "sadness"
        assert brief.suggested_preset == "minimal_piano"
        assert brief.suggested_key == "Am"

    def test_plan_with_fast_pacing(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan detects high energy from fast pacing data."""
        conn = sqlite3.connect(str(analysis_db))
        for start in range(0, 60000, 5000):
            conn.execute(
                "INSERT INTO pacing VALUES (?, ?, ?, ?, ?, ?)",
                ("proj_001", start, start + 5000, 200, 0.1, "fast"),
            )
        conn.commit()
        conn.close()

        brief = planner.plan_for_edit(analysis_db, "proj_001", "edit_001")
        assert brief.energy_level == "high"

    def test_plan_with_slow_pacing(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan detects low energy from slow pacing data."""
        conn = sqlite3.connect(str(analysis_db))
        for start in range(0, 60000, 5000):
            conn.execute(
                "INSERT INTO pacing VALUES (?, ?, ?, ?, ?, ?)",
                ("proj_001", start, start + 5000, 80, 0.5, "slow"),
            )
        conn.commit()
        conn.close()

        brief = planner.plan_for_edit(analysis_db, "proj_001", "edit_001")
        assert brief.energy_level == "low"

    def test_plan_with_beat_sections(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan uses beat_sections for tempo suggestion."""
        conn = sqlite3.connect(str(analysis_db))
        conn.execute(
            "INSERT INTO beat_sections VALUES (?, ?, ?, ?, ?)",
            ("proj_001", 0, 30000, 120.0, 60),
        )
        conn.execute(
            "INSERT INTO beat_sections VALUES (?, ?, ?, ?, ?)",
            ("proj_001", 30000, 60000, 130.0, 65),
        )
        conn.commit()
        conn.close()

        brief = planner.plan_for_edit(analysis_db, "proj_001", "edit_001")
        # Average BPM should be 125
        assert brief.suggested_tempo_bpm == 125

    def test_plan_with_speech_regions(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan extracts speech regions for ducking info."""
        conn = sqlite3.connect(str(analysis_db))
        conn.execute(
            "INSERT INTO transcript_segments VALUES (?, ?, ?, ?)",
            ("proj_001", 5000, 10000, "Hello world"),
        )
        conn.execute(
            "INSERT INTO transcript_segments VALUES (?, ?, ?, ?)",
            ("proj_001", 20000, 25000, "More speech here"),
        )
        conn.commit()
        conn.close()

        brief = planner.plan_for_edit(analysis_db, "proj_001", "edit_001")
        assert len(brief.speech_regions) == 2
        assert brief.speech_regions[0] == (5000, 10000)

    def test_plan_missing_db(
        self, tmp_path: Path, planner: MusicPlanner,
    ) -> None:
        """Plan returns defaults when database file does not exist."""
        fake_db = tmp_path / "nonexistent" / "analysis.db"
        brief = planner.plan_for_edit(fake_db, "proj_001", "edit_001")
        assert isinstance(brief, MusicBrief)
        assert brief.overall_mood == "professional"

    def test_plan_missing_edit_raises(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan raises ValueError for nonexistent edit."""
        with pytest.raises(ValueError, match="Edit not found"):
            planner.plan_for_edit(analysis_db, "proj_001", "nonexistent_edit")

    def test_ace_step_prompt_generated(
        self, analysis_db: Path, planner: MusicPlanner,
    ) -> None:
        """Plan generates a non-empty ACE-Step prompt."""
        brief = planner.plan_for_edit(analysis_db, "proj_001", "edit_001")
        assert len(brief.ace_step_prompt) > 10
        assert "BPM" in brief.ace_step_prompt
        assert "instrumental" in brief.ace_step_prompt


# ============================================================
# HELPER FUNCTION TESTS
# ============================================================

class TestMoodMapping:
    """Test mood-to-music mapping helpers."""

    def test_joy_maps_to_upbeat_pop(self) -> None:
        preset, key = _map_mood_to_music("joy")
        assert preset == "upbeat_pop"
        assert key == "C"

    def test_sadness_maps_to_minimal_piano(self) -> None:
        preset, key = _map_mood_to_music("sadness")
        assert preset == "minimal_piano"
        assert key == "Am"

    def test_tension_maps_to_dramatic(self) -> None:
        preset, key = _map_mood_to_music("tension")
        assert preset == "dramatic"
        assert key == "Am"

    def test_calm_maps_to_ambient_pad(self) -> None:
        preset, key = _map_mood_to_music("calm")
        assert preset == "ambient_pad"
        assert key == "C"

    def test_professional_maps_to_corporate(self) -> None:
        preset, key = _map_mood_to_music("professional")
        assert preset == "corporate"
        assert key == "C"

    def test_inspiring_maps_to_cinematic(self) -> None:
        preset, key = _map_mood_to_music("inspiring")
        assert preset == "cinematic_epic"
        assert key == "C"

    def test_unknown_mood_defaults(self) -> None:
        preset, key = _map_mood_to_music("unknown_mood_xyz")
        assert preset == "corporate"
        assert key == "C"


class TestPromptGeneration:
    """Test ACE-Step prompt generation."""

    def test_prompt_contains_tempo(self) -> None:
        prompt = _build_ace_step_prompt("joy", "high", 130, "C")
        assert "130 BPM" in prompt

    def test_prompt_contains_key(self) -> None:
        prompt = _build_ace_step_prompt("calm", "low", 70, "Am")
        assert "Am" in prompt

    def test_prompt_contains_energy(self) -> None:
        prompt = _build_ace_step_prompt("tension", "high", 100, "Am")
        assert "powerful" in prompt or "driving" in prompt

    def test_prompt_instrumental(self) -> None:
        prompt = _build_ace_step_prompt("calm", "low", 70, "C")
        assert "instrumental" in prompt
        assert "no vocals" in prompt


# ============================================================
# TOOL DEFINITION TESTS
# ============================================================

class TestToolDefinitions:
    """Test that new tool definitions are registered correctly."""

    def test_auto_music_tool_exists(self) -> None:
        from clipcannon.tools.audio_defs import AUDIO_TOOL_DEFINITIONS
        names = [t.name for t in AUDIO_TOOL_DEFINITIONS]
        assert "clipcannon_auto_music" in names

    def test_compose_music_tool_exists(self) -> None:
        from clipcannon.tools.audio_defs import AUDIO_TOOL_DEFINITIONS
        names = [t.name for t in AUDIO_TOOL_DEFINITIONS]
        assert "clipcannon_compose_music" in names

    def test_generate_music_has_model_param(self) -> None:
        from clipcannon.tools.audio_defs import AUDIO_TOOL_DEFINITIONS
        gen_tool = next(
            t for t in AUDIO_TOOL_DEFINITIONS
            if t.name == "clipcannon_generate_music"
        )
        props = gen_tool.inputSchema["properties"]
        assert "model" in props
        assert props["model"]["enum"] == ["ace-step", "musicgen"]

    def test_auto_music_has_tier_param(self) -> None:
        from clipcannon.tools.audio_defs import AUDIO_TOOL_DEFINITIONS
        tool = next(
            t for t in AUDIO_TOOL_DEFINITIONS
            if t.name == "clipcannon_auto_music"
        )
        props = tool.inputSchema["properties"]
        assert "tier" in props
        assert set(props["tier"]["enum"]) == {"ai", "midi", "auto"}

    def test_compose_music_required_params(self) -> None:
        from clipcannon.tools.audio_defs import AUDIO_TOOL_DEFINITIONS
        tool = next(
            t for t in AUDIO_TOOL_DEFINITIONS
            if t.name == "clipcannon_compose_music"
        )
        required = tool.inputSchema["required"]
        assert "description" in required
        assert "duration_s" in required

    def test_total_tool_count(self) -> None:
        """Should now have 6 audio tools total."""
        from clipcannon.tools.audio_defs import AUDIO_TOOL_DEFINITIONS
        assert len(AUDIO_TOOL_DEFINITIONS) == 6


# ============================================================
# MOOD CLASSIFICATION TESTS
# ============================================================

class TestMoodClassification:
    """Test MusicPlanner._classify_mood static method."""

    def test_direct_joy_mapping(self) -> None:
        mood = MusicPlanner._classify_mood("joy", 0.8, 0.8)
        assert mood == "joy"

    def test_direct_sadness_mapping(self) -> None:
        mood = MusicPlanner._classify_mood("sadness", 0.2, 0.2)
        assert mood == "sadness"

    def test_direct_anger_maps_to_tension(self) -> None:
        mood = MusicPlanner._classify_mood("anger", 0.2, 0.8)
        assert mood == "tension"

    def test_valence_arousal_fallback_joy(self) -> None:
        mood = MusicPlanner._classify_mood("unknown", 0.8, 0.8)
        assert mood == "joy"

    def test_valence_arousal_fallback_calm(self) -> None:
        mood = MusicPlanner._classify_mood("unknown", 0.8, 0.3)
        assert mood == "calm"

    def test_valence_arousal_fallback_tension(self) -> None:
        mood = MusicPlanner._classify_mood("unknown", 0.2, 0.8)
        assert mood == "tension"

    def test_valence_arousal_fallback_sadness(self) -> None:
        mood = MusicPlanner._classify_mood("unknown", 0.2, 0.2)
        assert mood == "sadness"

    def test_neutral_zone_returns_professional(self) -> None:
        mood = MusicPlanner._classify_mood("unknown", 0.5, 0.5)
        assert mood == "professional"
