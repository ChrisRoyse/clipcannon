"""Tests for Qwen3-TTS voice synthesis with verification loop.

Uses real Qwen3-TTS inference and real voice data from proj_76961210.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault('HF_TOKEN', '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')

from clipcannon.voice.inference import SpeakResult, VoiceSynthesizer
from clipcannon.voice.verify import build_reference_embedding


# Shared synthesizer to avoid reloading model for every test
_synth: VoiceSynthesizer | None = None


def _get_synth() -> VoiceSynthesizer:
    global _synth
    if _synth is None:
        _synth = VoiceSynthesizer()
    return _synth


VOCALS_PATH = Path("/home/cabdru/.clipcannon/projects/proj_76961210/stems/vocals.wav")
CLIP_PATH = Path("/home/cabdru/.clipcannon/voice_data/boris/wavs")


class TestVoiceSynthesizer:
    """Tests for Qwen3-TTS VoiceSynthesizer."""

    @pytest.mark.asyncio()
    async def test_speak_requires_reference(self, tmp_path: Path) -> None:
        """speak() without reference audio raises ValueError."""
        synth = _get_synth()
        output = tmp_path / "test_no_ref.wav"
        with pytest.raises(ValueError, match="reference audio"):
            synth.speak(
                text="Hello world.",
                output_path=output,
                max_attempts=1,
            )

    @pytest.mark.asyncio()
    async def test_speak_generates_audio(self, tmp_path: Path) -> None:
        """speak() with reference audio creates a WAV file."""
        clips = sorted(CLIP_PATH.glob("*.wav")) if CLIP_PATH.exists() else []
        if not clips:
            pytest.skip("No voice data clips available")
        synth = _get_synth()
        output = tmp_path / "test_speak.wav"
        result = synth.speak(
            text="Hello world, this is a test of Qwen 3 TTS.",
            output_path=output,
            reference_audio=clips[0],
            max_attempts=1,
            max_new_tokens=1024,
        )
        assert isinstance(result, SpeakResult)
        assert result.audio_path.exists()
        assert result.duration_ms > 0
        assert result.attempts == 1

    @pytest.mark.asyncio()
    async def test_speak_with_reference_audio(self, tmp_path: Path) -> None:
        """speak() with reference audio uses voice cloning."""
        clips = sorted(CLIP_PATH.glob("*.wav")) if CLIP_PATH.exists() else []
        if not clips:
            pytest.skip("No voice data clips available")
        synth = _get_synth()
        output = tmp_path / "test_ref.wav"
        result = synth.speak(
            text="This is a test with reference voice.",
            output_path=output,
            reference_audio=clips[0],
            max_attempts=1,
            max_new_tokens=1024,
        )
        assert result.audio_path.exists()
        assert result.duration_ms > 0

    @pytest.mark.asyncio()
    async def test_speak_with_verification(self, tmp_path: Path) -> None:
        """speak() with reference embedding runs verification gates."""
        clips = sorted(CLIP_PATH.glob("*.wav")) if CLIP_PATH.exists() else []
        if len(clips) < 3:
            pytest.skip("Need at least 3 voice clips")

        ref_emb = build_reference_embedding(clips[:3])

        synth = _get_synth()
        output = tmp_path / "test_verify.wav"
        result = synth.speak(
            text="Testing verification with voice fingerprint.",
            output_path=output,
            reference_audio=clips[0],
            reference_embedding=ref_emb,
            verification_threshold=0.30,
            max_attempts=2,
            max_new_tokens=1024,
        )
        assert result.verification is not None
        assert isinstance(result.verification.secs_score, float)

    @pytest.mark.asyncio()
    async def test_speak_fails_verification_with_high_threshold(self, tmp_path: Path) -> None:
        """speak() with impossibly high threshold returns failed verification."""
        clips = sorted(CLIP_PATH.glob("*.wav")) if CLIP_PATH.exists() else []
        if len(clips) < 3:
            pytest.skip("Need at least 3 voice clips")

        ref_emb = build_reference_embedding(clips[:3])

        synth = _get_synth()
        output = tmp_path / "test_fail.wav"
        result = synth.speak(
            text="This sentence tests that verification fails with an impossibly high threshold.",
            output_path=output,
            reference_audio=clips[0],
            reference_embedding=ref_emb,
            verification_threshold=0.99,
            max_attempts=2,
            max_new_tokens=1024,
        )
        assert result.verification is not None
        assert not result.verification.passed
        assert result.audio_path.exists()
        assert result.duration_ms > 0
