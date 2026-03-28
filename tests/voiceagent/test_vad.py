"""Tests for SileroVAD -- uses REAL model, NO MOCKS."""
import numpy as np
import pytest
from voiceagent.asr.vad import SileroVAD
from voiceagent.errors import VADError


@pytest.fixture(scope="module")
def vad() -> SileroVAD:
    return SileroVAD(threshold=0.5)


def test_vad_instantiates(vad):
    assert hasattr(vad, "model")
    assert vad.threshold == 0.5


def test_vad_silence_returns_false(vad):
    assert vad.is_speech(np.zeros(512, dtype=np.float32)) is False


def test_vad_tone_440hz(vad):
    t = np.linspace(0, 512 / 16000, 512, endpoint=False, dtype=np.float32)
    tone = 0.5 * np.sin(2 * np.pi * 440 * t)
    result = vad.is_speech(tone)
    assert isinstance(result, bool)


def test_vad_int16_silence(vad):
    assert vad.is_speech(np.zeros(512, dtype=np.int16)) is False


def test_vad_reset(vad):
    vad.reset()


def test_vad_chunk_256_rejected(vad):
    """256 samples is only valid at 8kHz; rejected at 16kHz."""
    with pytest.raises(VADError, match="Invalid chunk size: 256"):
        vad.is_speech(np.zeros(256, dtype=np.float32))


def test_vad_chunk_768_rejected(vad):
    """768 samples is not a valid chunk size for Silero VAD v5."""
    with pytest.raises(VADError, match="Invalid chunk size: 768"):
        vad.is_speech(np.zeros(768, dtype=np.float32))


def test_vad_invalid_chunk_size(vad):
    with pytest.raises(VADError, match="Invalid chunk size: 3200"):
        vad.is_speech(np.zeros(3200, dtype=np.float32))


def test_vad_empty_array(vad):
    with pytest.raises(VADError, match="Empty audio chunk"):
        vad.is_speech(np.array([], dtype=np.float32))


def test_vad_nan_values(vad):
    with pytest.raises(VADError, match="NaN"):
        vad.is_speech(np.full(512, np.nan, dtype=np.float32))
