"""Tests for voiceagent.asr.types module."""
import time

import numpy as np
import pytest

from voiceagent.asr.types import ASREvent, AudioBuffer


def test_asr_event_creation():
    event = ASREvent(text="hello world", final=True)
    assert event.text == "hello world"
    assert event.final is True
    assert isinstance(event.timestamp, float)


def test_asr_event_partial():
    event = ASREvent(text="hel", final=False)
    assert event.final is False


def test_asr_event_default_timestamp():
    before = time.time()
    event = ASREvent(text="test", final=True)
    after = time.time()
    assert before <= event.timestamp <= after


def test_asr_event_custom_timestamp():
    event = ASREvent(text="test", final=True, timestamp=1234567890.0)
    assert event.timestamp == 1234567890.0


def test_audio_buffer_empty():
    buf = AudioBuffer()
    assert buf.has_audio() is False
    assert buf.duration_s() == 0.0
    audio = buf.get_audio()
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) == 0


def test_audio_buffer_append_and_get():
    buf = AudioBuffer()
    chunk1 = np.ones(1600, dtype=np.float32)
    chunk2 = np.zeros(1600, dtype=np.float32)
    chunk3 = np.full(1600, 0.5, dtype=np.float32)
    buf.append(chunk1)
    buf.append(chunk2)
    buf.append(chunk3)
    audio = buf.get_audio()
    assert len(audio) == 4800
    assert np.array_equal(audio[:1600], chunk1)
    assert np.array_equal(audio[1600:3200], chunk2)
    assert np.array_equal(audio[3200:4800], chunk3)


def test_audio_buffer_has_audio():
    buf = AudioBuffer()
    assert buf.has_audio() is False
    buf.append(np.zeros(100, dtype=np.float32))
    assert buf.has_audio() is True


def test_audio_buffer_clear():
    buf = AudioBuffer()
    buf.append(np.zeros(1600, dtype=np.float32))
    assert buf.has_audio() is True
    buf.clear()
    assert buf.has_audio() is False
    assert buf.duration_s() == 0.0
    assert len(buf.get_audio()) == 0


def test_audio_buffer_duration_s_200ms():
    buf = AudioBuffer()
    buf.append(np.zeros(3200, dtype=np.float32))
    assert buf.duration_s() == pytest.approx(0.2)


def test_audio_buffer_duration_s_1s():
    buf = AudioBuffer()
    buf.append(np.zeros(16000, dtype=np.float32))
    assert buf.duration_s() == pytest.approx(1.0)


def test_audio_buffer_duration_s_multiple_chunks():
    buf = AudioBuffer()
    buf.append(np.zeros(8000, dtype=np.float32))
    buf.append(np.zeros(4000, dtype=np.float32))
    assert buf.duration_s() == pytest.approx(0.75)


def test_audio_buffer_sample_rate():
    assert AudioBuffer.SAMPLE_RATE == 16000
