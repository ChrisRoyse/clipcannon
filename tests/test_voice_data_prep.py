"""Tests for voice data preparation and voice profile management.

Tests cover:
- prepare_voice_data with real proj_76961210 data
- Clip duration bounds (1-12s)
- Phonemized text in output
- Voice profile CRUD (create, get, list, update, delete)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

# Real project data paths
REAL_PROJECT_ID = "proj_76961210"
REAL_PROJECTS_BASE = Path.home() / ".clipcannon" / "projects"
REAL_VOCALS = REAL_PROJECTS_BASE / REAL_PROJECT_ID / "stems" / "vocals.wav"
REAL_DB = REAL_PROJECTS_BASE / REAL_PROJECT_ID / "analysis.db"


@pytest.fixture()
def voice_output_dir(tmp_path: Path) -> Path:
    """Temporary directory for voice training output."""
    d = tmp_path / "voice_data"
    d.mkdir()
    return d


@pytest.fixture()
def voice_db(tmp_path: Path) -> Path:
    """Temporary database for voice profiles."""
    return tmp_path / "voice_profiles.db"


# ============================================================
# VOICE DATA PREPARATION TESTS
# ============================================================
class TestPrepareVoiceData:
    """Test voice training data preparation with real project data."""

    @pytest.mark.skipif(
        not REAL_VOCALS.exists(),
        reason="Real project vocals.wav not available",
    )
    def test_prepare_voice_data_creates_output(
        self, voice_output_dir: Path,
    ) -> None:
        """Prepare voice data produces WAV clips and manifest files."""
        from clipcannon.voice.data_prep import prepare_voice_training_data

        result = asyncio.run(
            prepare_voice_training_data(
                project_ids=[REAL_PROJECT_ID],
                speaker_label="test_speaker",
                output_dir=voice_output_dir,
                projects_base=REAL_PROJECTS_BASE,
                min_clip_duration_ms=1000,
                max_clip_duration_ms=12000,
            )
        )

        # Verify result fields
        assert result.total_clips > 0
        assert result.total_duration_s > 0
        assert result.train_count + result.val_count == result.total_clips
        assert result.output_dir == voice_output_dir

        # Verify WAV files exist
        wavs_dir = voice_output_dir / "wavs"
        assert wavs_dir.exists()
        wav_files = list(wavs_dir.glob("*.wav"))
        assert len(wav_files) == result.total_clips

        # Verify manifest files
        train_list = voice_output_dir / "train_list.txt"
        val_list = voice_output_dir / "val_list.txt"
        assert train_list.exists()
        assert val_list.exists()

        train_lines = train_list.read_text().strip().split("\n")
        val_lines = val_list.read_text().strip().split("\n")
        assert len(train_lines) == result.train_count
        assert len(val_lines) == result.val_count

        # Verify clip durations are 1-12 seconds
        from pydub import AudioSegment

        for wav_file in wav_files:
            audio = AudioSegment.from_wav(str(wav_file))
            duration_ms = len(audio)
            assert duration_ms >= 1000, (
                f"Clip {wav_file.name} is too short: {duration_ms}ms"
            )
            assert duration_ms <= 12000, (
                f"Clip {wav_file.name} is too long: {duration_ms}ms"
            )

        # Verify manifest format: path|text|speaker
        for line in train_lines + val_lines:
            parts = line.split("|")
            assert len(parts) == 3, f"Bad manifest line: {line}"
            clip_path, phonemes, speaker = parts
            assert Path(clip_path).exists(), f"Clip missing: {clip_path}"
            assert len(phonemes) > 0, "Empty phonemes"
            assert speaker == "test_speaker"

    @pytest.mark.skipif(
        not REAL_VOCALS.exists(),
        reason="Real project vocals.wav not available",
    )
    def test_prepare_voice_data_phonemizes(
        self, voice_output_dir: Path,
    ) -> None:
        """Verify phonemized text contains IPA-like characters."""
        from clipcannon.voice.data_prep import prepare_voice_training_data

        result = asyncio.run(
            prepare_voice_training_data(
                project_ids=[REAL_PROJECT_ID],
                speaker_label="phoneme_test",
                output_dir=voice_output_dir,
                projects_base=REAL_PROJECTS_BASE,
            )
        )

        assert result.total_clips > 0

        # Read first train line and check phonemes look phonemized
        train_list = voice_output_dir / "train_list.txt"
        first_line = train_list.read_text().strip().split("\n")[0]
        _, phonemes, _ = first_line.split("|")

        # Phonemized text should contain IPA characters not in
        # normal English (e.g., vowels with diacritics, schwa)
        has_ipa = any(
            ord(c) > 127 or c in "??e??i??u??a??o???"
            for c in phonemes
        )
        assert has_ipa, (
            f"Phonemes don't look phonemized: {phonemes!r}"
        )

    def test_prepare_voice_data_missing_vocals(
        self, voice_output_dir: Path, tmp_path: Path,
    ) -> None:
        """Raises FileNotFoundError when vocals.wav is missing."""
        from clipcannon.voice.data_prep import prepare_voice_training_data

        fake_base = tmp_path / "fake_projects"
        fake_base.mkdir()
        (fake_base / "proj_fake" / "stems").mkdir(parents=True)

        with pytest.raises(FileNotFoundError, match="vocals.wav not found"):
            asyncio.run(
                prepare_voice_training_data(
                    project_ids=["proj_fake"],
                    speaker_label="test",
                    output_dir=voice_output_dir,
                    projects_base=fake_base,
                )
            )


# ============================================================
# VOICE PROFILE CRUD TESTS
# ============================================================
class TestVoiceProfileCrud:
    """Test voice profile create, get, list, update, delete."""

    def test_create_and_get_profile(self, voice_db: Path) -> None:
        """Create a profile and retrieve it by name."""
        from clipcannon.voice.profiles import (
            create_voice_profile,
            get_voice_profile,
        )

        profile_id = create_voice_profile(
            voice_db, "test_voice", "/models/test_voice",
        )
        assert profile_id.startswith("vp_")

        profile = get_voice_profile(voice_db, "test_voice")
        assert profile is not None
        assert profile["profile_id"] == profile_id
        assert profile["name"] == "test_voice"
        assert profile["model_path"] == "/models/test_voice"
        assert profile["training_status"] == "pending"
        assert profile["sample_rate"] == 24000

    def test_list_profiles(self, voice_db: Path) -> None:
        """List returns all created profiles."""
        from clipcannon.voice.profiles import (
            create_voice_profile,
            list_voice_profiles,
        )

        create_voice_profile(voice_db, "voice_a", "/models/a")
        create_voice_profile(voice_db, "voice_b", "/models/b")

        profiles = list_voice_profiles(voice_db)
        assert len(profiles) == 2
        names = {p["name"] for p in profiles}
        assert names == {"voice_a", "voice_b"}

    def test_update_profile(self, voice_db: Path) -> None:
        """Update profile fields and verify changes persist."""
        from clipcannon.voice.profiles import (
            create_voice_profile,
            get_voice_profile,
            update_voice_profile,
        )

        create_voice_profile(voice_db, "update_test", "/models/update")
        update_voice_profile(
            voice_db, "update_test",
            training_status="training",
            training_hours=2.5,
        )

        profile = get_voice_profile(voice_db, "update_test")
        assert profile is not None
        assert profile["training_status"] == "training"
        assert profile["training_hours"] == 2.5

    def test_delete_profile(self, voice_db: Path) -> None:
        """Delete a profile and verify it is gone."""
        from clipcannon.voice.profiles import (
            create_voice_profile,
            delete_voice_profile,
            get_voice_profile,
        )

        create_voice_profile(voice_db, "delete_me", "/models/delete")
        delete_voice_profile(voice_db, "delete_me")

        profile = get_voice_profile(voice_db, "delete_me")
        assert profile is None

    def test_delete_nonexistent_raises(self, voice_db: Path) -> None:
        """Deleting nonexistent profile raises ValueError."""
        from clipcannon.voice.profiles import delete_voice_profile

        with pytest.raises(ValueError, match="Voice profile not found"):
            delete_voice_profile(voice_db, "nope")

    def test_update_nonexistent_raises(self, voice_db: Path) -> None:
        """Updating nonexistent profile raises ValueError."""
        from clipcannon.voice.profiles import update_voice_profile

        with pytest.raises(ValueError, match="Voice profile not found"):
            update_voice_profile(
                voice_db, "nope", training_status="ready",
            )

    def test_get_nonexistent_returns_none(self, voice_db: Path) -> None:
        """Getting nonexistent profile returns None."""
        from clipcannon.voice.profiles import get_voice_profile

        profile = get_voice_profile(voice_db, "nope")
        assert profile is None

    def test_duplicate_name_raises(self, voice_db: Path) -> None:
        """Creating duplicate profile name raises IntegrityError."""
        import sqlite3

        from clipcannon.voice.profiles import create_voice_profile

        create_voice_profile(voice_db, "unique_name", "/models/first")

        with pytest.raises(
            (sqlite3.IntegrityError, Exception),
        ):
            create_voice_profile(voice_db, "unique_name", "/models/second")
