"""Tests for wake word detector -- real model, NO MOCKS."""
import numpy as np
import pytest

openwakeword = pytest.importorskip("openwakeword", reason="openwakeword not installed")



def test_detector_instantiates(session_wake_word):
    assert isinstance(session_wake_word.threshold, float)


def test_silence_returns_false(session_wake_word):
    assert session_wake_word.detect(np.zeros(1280, dtype=np.int16)) is False


def test_noise_returns_false(session_wake_word):
    rng = np.random.default_rng(42)
    noise = rng.integers(-1000, 1000, size=1280, dtype=np.int16)
    assert session_wake_word.detect(noise) is False


def test_empty_returns_false(session_wake_word):
    assert session_wake_word.detect(np.array([], dtype=np.int16)) is False


def test_returns_bool(session_wake_word):
    assert type(session_wake_word.detect(np.zeros(1280, dtype=np.int16))) is bool


def test_float32_auto_converts(session_wake_word):
    assert isinstance(session_wake_word.detect(np.zeros(1280, dtype=np.float32)), bool)


def test_sequential_detections(session_wake_word):
    for _ in range(10):
        assert session_wake_word.detect(np.zeros(1280, dtype=np.int16)) is False
