"""Tests for Audio2Face adapter: BlendshapeFrame, Audio2FaceLocal, edge cases.

Uses real audio data (sine waves, white noise, silence) rather than mocks.
Covers creation, validation, EMA smoothing, and error handling.
"""

from __future__ import annotations

import numpy as np
import pytest

from phoenix.adapters.audio2face_adapter import (
    ARKIT_BLENDSHAPE_NAMES,
    NUM_ARKIT_BLENDSHAPES,
    Audio2FaceLocal,
    Audio2FaceNIM,
    BlendshapeFrame,
    _clamp,
)
from phoenix.errors import ExpressionError


# ---------------------------------------------------------------------------
# Fixtures: synthetic audio generators
# ---------------------------------------------------------------------------

@pytest.fixture()
def sine_wave() -> np.ndarray:
    """440 Hz sine wave at 16 kHz, 0.5 seconds, moderate amplitude."""
    sr = 16000
    t = np.linspace(0, 0.5, sr // 2, endpoint=False, dtype=np.float32)
    return 0.3 * np.sin(2 * np.pi * 440 * t).astype(np.float32)


@pytest.fixture()
def loud_sine() -> np.ndarray:
    """440 Hz sine wave at high amplitude."""
    sr = 16000
    t = np.linspace(0, 0.5, sr // 2, endpoint=False, dtype=np.float32)
    return 0.8 * np.sin(2 * np.pi * 440 * t).astype(np.float32)


@pytest.fixture()
def white_noise() -> np.ndarray:
    """White noise at moderate amplitude, 0.5 seconds at 16 kHz."""
    rng = np.random.default_rng(42)
    return (rng.standard_normal(8000) * 0.2).astype(np.float32)


@pytest.fixture()
def silence() -> np.ndarray:
    """Silent audio (zeros), 0.5 seconds at 16 kHz."""
    return np.zeros(8000, dtype=np.float32)


@pytest.fixture()
def speech_like() -> np.ndarray:
    """Synthetic speech-like signal: F0 modulated tone with harmonics."""
    sr = 16000
    n_samples = sr // 2
    t = np.linspace(0, 0.5, n_samples, endpoint=False, dtype=np.float32)
    f0 = 120 + 80 * t / 0.5
    phase = 2 * np.pi * np.cumsum(f0) / sr
    signal = (
        0.3 * np.sin(phase)
        + 0.15 * np.sin(2 * phase)
        + 0.08 * np.sin(3 * phase)
    )
    return signal.astype(np.float32)


@pytest.fixture()
def adapter() -> Audio2FaceLocal:
    """Fresh Audio2FaceLocal instance."""
    return Audio2FaceLocal(ema_alpha=0.5)


# ---------------------------------------------------------------------------
# BlendshapeFrame tests
# ---------------------------------------------------------------------------

class TestBlendshapeFrame:
    """Tests for BlendshapeFrame creation and validation."""

    def test_create_valid_frame(self) -> None:
        coeffs = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        frame = BlendshapeFrame(coefficients=coeffs)
        assert frame.coefficients.shape == (52,)
        assert frame.timestamp == 0.0
        assert frame.duration_ms == 0.0

    def test_create_frame_with_metadata(self) -> None:
        coeffs = np.ones(NUM_ARKIT_BLENDSHAPES, dtype=np.float32) * 0.5
        frame = BlendshapeFrame(
            coefficients=coeffs, timestamp=1.5, duration_ms=3.2,
        )
        assert frame.timestamp == 1.5
        assert frame.duration_ms == 3.2

    def test_wrong_shape_raises(self) -> None:
        with pytest.raises(ExpressionError, match="requires"):
            BlendshapeFrame(coefficients=np.zeros(10, dtype=np.float32))

    def test_2d_shape_raises(self) -> None:
        with pytest.raises(ExpressionError, match="requires"):
            BlendshapeFrame(
                coefficients=np.zeros((52, 1), dtype=np.float32),
            )

    def test_nan_raises(self) -> None:
        coeffs = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        coeffs[5] = np.nan
        with pytest.raises(ExpressionError, match="NaN"):
            BlendshapeFrame(coefficients=coeffs)

    def test_get_by_name(self) -> None:
        coeffs = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        coeffs[17] = 0.75  # jawOpen
        frame = BlendshapeFrame(coefficients=coeffs)
        assert frame.get("jawOpen") == pytest.approx(0.75)

    def test_get_unknown_name_raises(self) -> None:
        coeffs = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        frame = BlendshapeFrame(coefficients=coeffs)
        with pytest.raises(ExpressionError, match="Unknown blendshape"):
            frame.get("notABlendshape")

    def test_all_52_names_exist(self) -> None:
        assert len(ARKIT_BLENDSHAPE_NAMES) == 52
        for name in [
            "jawOpen", "mouthClose", "mouthSmileLeft", "mouthSmileRight",
            "browDownLeft", "browDownRight", "eyeBlinkLeft",
            "eyeBlinkRight", "browInnerUp", "tongueOut",
        ]:
            assert name in ARKIT_BLENDSHAPE_NAMES


# ---------------------------------------------------------------------------
# Audio2FaceLocal tests
# ---------------------------------------------------------------------------

class TestAudio2FaceLocal:
    """Tests for local signal-processing adapter."""

    def test_sine_wave_produces_jaw_open(
        self, adapter: Audio2FaceLocal, sine_wave: np.ndarray,
    ) -> None:
        frame = adapter.process_audio_chunk(sine_wave, 16000)
        assert frame.get("jawOpen") > 0.1

    def test_louder_audio_more_jaw_open(
        self, sine_wave: np.ndarray, loud_sine: np.ndarray,
    ) -> None:
        a = Audio2FaceLocal(ema_alpha=1.0)
        b = Audio2FaceLocal(ema_alpha=1.0)
        f_quiet = a.process_audio_chunk(sine_wave, 16000)
        f_loud = b.process_audio_chunk(loud_sine, 16000)
        assert f_loud.get("jawOpen") > f_quiet.get("jawOpen")

    def test_silence_returns_neutral(
        self, adapter: Audio2FaceLocal, silence: np.ndarray,
    ) -> None:
        frame = adapter.process_audio_chunk(silence, 16000)
        assert np.all(frame.coefficients < 0.01)

    def test_silence_after_speech_returns_to_neutral(
        self, sine_wave: np.ndarray, silence: np.ndarray,
    ) -> None:
        adapter = Audio2FaceLocal(ema_alpha=0.6)
        frame_speech = adapter.process_audio_chunk(sine_wave, 16000)
        assert frame_speech.get("jawOpen") > 0.05
        for _ in range(10):
            frame_silent = adapter.process_audio_chunk(silence, 16000)
        assert frame_silent.get("jawOpen") < 0.01

    def test_white_noise_high_zcr(
        self, adapter: Audio2FaceLocal, white_noise: np.ndarray,
    ) -> None:
        frame = adapter.process_audio_chunk(white_noise, 16000)
        assert frame.get("jawOpen") > 0.0
        stretch = (
            frame.get("mouthStretchLeft") + frame.get("mouthStretchRight")
        )
        assert stretch > 0.0

    def test_speech_like_activates_jaw(
        self, speech_like: np.ndarray,
    ) -> None:
        adapter = Audio2FaceLocal(ema_alpha=1.0)
        frame = adapter.process_audio_chunk(speech_like, 16000)
        assert frame.get("jawOpen") > 0.0

    def test_coefficients_in_valid_range(
        self, adapter: Audio2FaceLocal, sine_wave: np.ndarray,
    ) -> None:
        frame = adapter.process_audio_chunk(sine_wave, 16000)
        assert np.all(frame.coefficients >= 0.0)
        assert np.all(frame.coefficients <= 1.0)

    def test_ema_smoothing_gradual_transition(
        self, silence: np.ndarray, loud_sine: np.ndarray,
    ) -> None:
        adapter = Audio2FaceLocal(ema_alpha=0.3)
        adapter.process_audio_chunk(silence, 16000)
        frame1 = adapter.process_audio_chunk(loud_sine, 16000)
        frame2 = adapter.process_audio_chunk(loud_sine, 16000)
        assert frame1.get("jawOpen") <= frame2.get("jawOpen") + 0.01

    def test_reset_clears_state(
        self, adapter: Audio2FaceLocal, sine_wave: np.ndarray,
        silence: np.ndarray,
    ) -> None:
        adapter.process_audio_chunk(sine_wave, 16000)
        adapter.reset()
        frame = adapter.process_audio_chunk(silence, 16000)
        assert np.all(frame.coefficients == 0.0)

    def test_invalid_ema_alpha_raises(self) -> None:
        with pytest.raises(ExpressionError, match="ema_alpha"):
            Audio2FaceLocal(ema_alpha=0.0)
        with pytest.raises(ExpressionError, match="ema_alpha"):
            Audio2FaceLocal(ema_alpha=1.5)

    def test_frame_has_duration_ms(
        self, adapter: Audio2FaceLocal, sine_wave: np.ndarray,
    ) -> None:
        frame = adapter.process_audio_chunk(sine_wave, 16000)
        assert frame.duration_ms >= 0.0

    def test_frame_has_timestamp(
        self, adapter: Audio2FaceLocal, sine_wave: np.ndarray,
    ) -> None:
        frame = adapter.process_audio_chunk(sine_wave, 16000)
        assert frame.timestamp > 0.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_audio_raises(self) -> None:
        adapter = Audio2FaceLocal()
        with pytest.raises(ExpressionError, match="empty"):
            adapter.process_audio_chunk(
                np.array([], dtype=np.float32), 16000,
            )

    def test_nan_audio_raises(self) -> None:
        adapter = Audio2FaceLocal()
        audio = np.array([0.1, np.nan, 0.2], dtype=np.float32)
        with pytest.raises(ExpressionError, match="NaN"):
            adapter.process_audio_chunk(audio, 16000)

    def test_wrong_sample_rate_raises(self) -> None:
        adapter = Audio2FaceLocal()
        audio = np.zeros(1000, dtype=np.float32)
        with pytest.raises(ExpressionError, match="Sample rate"):
            adapter.process_audio_chunk(audio, 0)
        with pytest.raises(ExpressionError, match="Sample rate"):
            adapter.process_audio_chunk(audio, -16000)

    def test_very_short_chunk(self) -> None:
        adapter = Audio2FaceLocal(ema_alpha=1.0)
        audio = (0.3 * np.sin(np.linspace(0, 2 * np.pi, 10))).astype(
            np.float32,
        )
        frame = adapter.process_audio_chunk(audio, 16000)
        assert frame.coefficients.shape == (52,)
        assert np.all(frame.coefficients >= 0.0)
        assert np.all(frame.coefficients <= 1.0)

    def test_2d_audio_flattened(self) -> None:
        adapter = Audio2FaceLocal(ema_alpha=1.0)
        audio = np.zeros((2, 500), dtype=np.float32)
        audio[0, :] = 0.3 * np.sin(np.linspace(0, 20 * np.pi, 500))
        frame = adapter.process_audio_chunk(audio, 16000)
        assert frame.coefficients.shape == (52,)

    def test_different_sample_rates(self) -> None:
        adapter = Audio2FaceLocal(ema_alpha=1.0)
        for sr in [8000, 16000, 22050, 24000, 44100, 48000]:
            n = sr // 2
            audio = (
                0.3 * np.sin(2 * np.pi * 440 * np.linspace(0, 0.5, n))
            ).astype(np.float32)
            frame = adapter.process_audio_chunk(audio, sr)
            assert frame.coefficients.shape == (52,)
            assert np.all(frame.coefficients >= 0.0)
            assert np.all(frame.coefficients <= 1.0)


# ---------------------------------------------------------------------------
# Audio2FaceNIM tests (without actual NIM container)
# ---------------------------------------------------------------------------

class TestAudio2FaceNIM:
    """Tests for NIM adapter fallback behavior."""

    def test_nim_falls_back_when_no_container(self) -> None:
        fallback = Audio2FaceLocal(ema_alpha=1.0)
        nim = Audio2FaceNIM(
            host="localhost", port=99999, fallback=fallback,
        )
        sr = 16000
        audio = (
            0.3 * np.sin(
                2 * np.pi * 440
                * np.linspace(0, 0.5, sr // 2, dtype=np.float32),
            )
        ).astype(np.float32)
        frame = nim.process_audio_chunk(audio, sr)
        assert frame.coefficients.shape == (52,)
        assert np.all(frame.coefficients >= 0.0)

    def test_nim_connect_fails_gracefully(self) -> None:
        nim = Audio2FaceNIM(host="localhost", port=99999)
        assert nim.connect() is False
        assert nim.connected is False

    def test_nim_reset_clears_state(self) -> None:
        nim = Audio2FaceNIM(host="localhost", port=99999)
        nim.reset()
        assert nim.connected is False


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------

class TestUtility:
    """Tests for utility functions."""

    def test_clamp_within_range(self) -> None:
        assert _clamp(0.5) == 0.5

    def test_clamp_below(self) -> None:
        assert _clamp(-0.1) == 0.0

    def test_clamp_above(self) -> None:
        assert _clamp(1.5) == 1.0

    def test_clamp_custom_range(self) -> None:
        assert _clamp(5.0, 0.0, 10.0) == 5.0
        assert _clamp(-1.0, 0.0, 10.0) == 0.0
        assert _clamp(15.0, 0.0, 10.0) == 10.0
