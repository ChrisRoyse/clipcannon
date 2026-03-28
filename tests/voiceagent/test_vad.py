"""Tests for SileroVAD -- uses REAL model, NO MOCKS."""
import numpy as np
import pytest

from voiceagent.errors import VADError


def test_vad_instantiates(session_vad):
    assert hasattr(session_vad, "model")
    assert session_vad.threshold == 0.5


def test_vad_silence_returns_false(session_vad):
    assert session_vad.is_speech(np.zeros(512, dtype=np.float32)) is False


def test_vad_tone_440hz(session_vad):
    t = np.linspace(0, 512 / 16000, 512, endpoint=False, dtype=np.float32)
    tone = 0.5 * np.sin(2 * np.pi * 440 * t)
    result = session_vad.is_speech(tone)
    assert isinstance(result, bool)


def test_vad_int16_silence(session_vad):
    assert session_vad.is_speech(np.zeros(512, dtype=np.int16)) is False


def test_vad_reset(session_vad):
    session_vad.reset()


def test_vad_chunk_256_rejected(session_vad):
    """256 samples is only valid at 8kHz; rejected at 16kHz."""
    with pytest.raises(VADError, match="Invalid chunk size: 256"):
        session_vad.is_speech(np.zeros(256, dtype=np.float32))


def test_vad_chunk_768_rejected(session_vad):
    """768 samples is not a valid chunk size for Silero VAD v5."""
    with pytest.raises(VADError, match="Invalid chunk size: 768"):
        session_vad.is_speech(np.zeros(768, dtype=np.float32))


def test_vad_invalid_chunk_size(session_vad):
    with pytest.raises(VADError, match="Invalid chunk size: 3200"):
        session_vad.is_speech(np.zeros(3200, dtype=np.float32))


def test_vad_empty_array(session_vad):
    with pytest.raises(VADError, match="Empty audio chunk"):
        session_vad.is_speech(np.array([], dtype=np.float32))


def test_vad_nan_values(session_vad):
    with pytest.raises(VADError, match="NaN"):
        session_vad.is_speech(np.full(512, np.nan, dtype=np.float32))
