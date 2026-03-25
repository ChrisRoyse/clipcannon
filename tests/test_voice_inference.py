"""Tests for StyleTTS2 voice synthesis with verification loop.

Uses real StyleTTS2 inference (default model) and real voice data
from proj_76961210.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from clipcannon.voice.inference import SpeakResult, VoiceSynthesizer
from clipcannon.voice.train import TrainConfig, validate_training_data
from clipcannon.voice.verify import build_reference_embedding


# Shared synthesizer to avoid reloading model for every test
_synth: VoiceSynthesizer | None = None


def _get_synth() -> VoiceSynthesizer:
    global _synth
    if _synth is None:
        _synth = VoiceSynthesizer()
    return _synth


VOCALS_PATH = Path("/home/cabdru/.clipcannon/projects/proj_76961210/stems/vocals.wav")


class TestVoiceSynthesizer:
    """Tests for VoiceSynthesizer."""

    @pytest.mark.asyncio()
    async def test_speak_generates_audio(self, tmp_path: Path) -> None:
        """speak() with default model creates a WAV file."""
        synth = _get_synth()
        output = tmp_path / "test_speak.wav"
        result = synth.speak(
            text="Hello world.",
            output_path=output,
            max_attempts=1,
        )
        assert isinstance(result, SpeakResult)
        assert result.audio_path.exists()
        assert result.duration_ms > 0
        assert result.sample_rate == 24000
        assert result.attempts == 1

    @pytest.mark.asyncio()
    async def test_speak_with_reference_audio(self, tmp_path: Path) -> None:
        """speak() with reference audio uses style transfer."""
        if not VOCALS_PATH.exists():
            pytest.skip("vocals.wav not available")
        synth = _get_synth()
        output = tmp_path / "test_ref.wav"
        result = synth.speak(
            text="This is a test with reference voice.",
            output_path=output,
            reference_audio=VOCALS_PATH,
            max_attempts=1,
        )
        assert result.audio_path.exists()
        assert result.duration_ms > 0

    @pytest.mark.asyncio()
    async def test_speak_with_verification(self, tmp_path: Path) -> None:
        """speak() with reference embedding runs verification gates."""
        if not VOCALS_PATH.exists():
            pytest.skip("vocals.wav not available")

        # Build reference embedding from vocals
        import torchaudio
        wav, sr = torchaudio.load(str(VOCALS_PATH))
        # Extract first 10 seconds for reference
        clip_samples = sr * 10
        clip = wav[:, :clip_samples]
        clip_path = tmp_path / "ref_clip.wav"
        torchaudio.save(str(clip_path), clip, sr)

        ref_emb = build_reference_embedding([clip_path])

        synth = _get_synth()
        output = tmp_path / "test_verify.wav"
        result = synth.speak(
            text="Testing verification.",
            output_path=output,
            reference_embedding=ref_emb,
            verification_threshold=0.50,  # low threshold for default model
            max_attempts=2,
        )
        assert result.verification is not None
        assert isinstance(result.verification.secs_score, float)  # score computed
        assert result.verification.secs_score <= 1.0

    @pytest.mark.asyncio()
    async def test_speak_fails_verification_with_high_threshold(self, tmp_path: Path) -> None:
        """speak() with impossibly high threshold returns failed verification."""
        if not VOCALS_PATH.exists():
            pytest.skip("vocals.wav not available")

        import torchaudio
        wav, sr = torchaudio.load(str(VOCALS_PATH))
        clip = wav[:, :sr * 5]
        clip_path = tmp_path / "ref.wav"
        torchaudio.save(str(clip_path), clip, sr)
        ref_emb = build_reference_embedding([clip_path])

        synth = _get_synth()
        output = tmp_path / "test_escalate.wav"
        result = synth.speak(
            text="This is a longer sentence to avoid duration ratio issues with short text.",
            output_path=output,
            reference_embedding=ref_emb,
            verification_threshold=0.99,  # impossibly high
            max_attempts=2,
        )
        # Verification should have failed (default model voice != reference)
        assert result.verification is not None
        assert not result.verification.passed
        # Audio should still be generated (best attempt returned)
        assert result.audio_path.exists()
        assert result.duration_ms > 0


class TestTrainValidation:
    """Tests for training data validation."""

    @pytest.mark.asyncio()
    async def test_validate_missing_dir(self) -> None:
        """Non-existent directory fails validation."""
        result = await validate_training_data(Path("/tmp/nonexistent_dir"))
        assert not result.valid
        assert len(result.issues) > 0

    @pytest.mark.asyncio()
    async def test_validate_empty_dir(self, tmp_path: Path) -> None:
        """Empty directory fails validation (no train_list.txt)."""
        result = await validate_training_data(tmp_path)
        assert not result.valid
        assert any("Missing" in i for i in result.issues)

    @pytest.mark.asyncio()
    async def test_validate_valid_data(self, tmp_path: Path) -> None:
        """Valid training data passes validation."""
        import soundfile as sf

        wavs_dir = tmp_path / "wavs"
        wavs_dir.mkdir()

        # Create a dummy WAV
        audio = np.random.randn(24000).astype(np.float32) * 0.1
        wav_path = wavs_dir / "clip_001.wav"
        sf.write(str(wav_path), audio, 24000)

        # Create train/val lists
        (tmp_path / "train_list.txt").write_text(f"{wav_path}|hɛlˈoʊ|speaker_0\n")
        (tmp_path / "val_list.txt").write_text(f"{wav_path}|hɛlˈoʊ|speaker_0\n")

        result = await validate_training_data(tmp_path)
        assert result.valid
        assert result.train_count == 1
        assert result.val_count == 1
        assert result.total_duration_s > 0
