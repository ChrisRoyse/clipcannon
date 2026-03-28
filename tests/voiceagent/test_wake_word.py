"""Tests for wake word detector -- real model, NO MOCKS."""
import numpy as np
import pytest

openwakeword = pytest.importorskip("openwakeword", reason="openwakeword not installed")

from voiceagent.activation.wake_word import WakeWordDetector


@pytest.fixture(scope="module")
def detector():
    return WakeWordDetector(model_name="hey_jarvis", threshold=0.6)


def test_detector_instantiates(detector):
    assert detector.model_name == "hey_jarvis"
    assert detector.threshold == 0.6


def test_silence_returns_false(detector):
    assert detector.detect(np.zeros(1280, dtype=np.int16)) is False


def test_noise_returns_false(detector):
    rng = np.random.default_rng(42)
    noise = rng.integers(-1000, 1000, size=1280, dtype=np.int16)
    assert detector.detect(noise) is False


def test_empty_returns_false(detector):
    assert detector.detect(np.array([], dtype=np.int16)) is False


def test_returns_bool(detector):
    assert type(detector.detect(np.zeros(1280, dtype=np.int16))) is bool


def test_float32_auto_converts(detector):
    assert isinstance(detector.detect(np.zeros(1280, dtype=np.float32)), bool)


def test_sequential_detections(detector):
    for _ in range(10):
        assert detector.detect(np.zeros(1280, dtype=np.int16)) is False
