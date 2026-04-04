"""Integration tests: BlendshapeToFLAME, real speech audio, performance.

Tests ARKit-to-FLAME conversion, real voice data from
~/.clipcannon/voice_data/santa/wavs/, and per-chunk benchmarks.
"""

from __future__ import annotations

import glob
import os
import time

import numpy as np
import pytest

from phoenix.adapters.audio2face_adapter import (
    ARKIT_BLENDSHAPE_NAMES,
    NUM_ARKIT_BLENDSHAPES,
    NUM_FLAME_EXPRESSIONS,
    Audio2FaceLocal,
    BlendshapeFrame,
    BlendshapeToFLAME,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def flame_converter() -> BlendshapeToFLAME:
    """Fresh BlendshapeToFLAME instance."""
    return BlendshapeToFLAME()


# ---------------------------------------------------------------------------
# BlendshapeToFLAME tests
# ---------------------------------------------------------------------------

class TestBlendshapeToFLAME:
    """Tests for ARKit-to-FLAME blendshape conversion."""

    def test_neutral_produces_zero_flame(
        self, flame_converter: BlendshapeToFLAME,
    ) -> None:
        frame = BlendshapeFrame(
            coefficients=np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32),
        )
        flame = flame_converter.convert(frame)
        assert flame.shape == (NUM_FLAME_EXPRESSIONS,)
        np.testing.assert_array_equal(flame, 0.0)

    def test_flame_output_shape(
        self, flame_converter: BlendshapeToFLAME,
    ) -> None:
        coeffs = np.random.default_rng(42).random(
            NUM_ARKIT_BLENDSHAPES,
        ).astype(np.float32)
        frame = BlendshapeFrame(coefficients=coeffs)
        flame = flame_converter.convert(frame)
        assert flame.shape == (NUM_FLAME_EXPRESSIONS,)

    def test_flame_values_clipped(
        self, flame_converter: BlendshapeToFLAME,
    ) -> None:
        coeffs = np.ones(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        frame = BlendshapeFrame(coefficients=coeffs)
        flame = flame_converter.convert(frame)
        assert np.all(flame >= -2.0)
        assert np.all(flame <= 2.0)

    def test_jaw_open_maps_to_flame_jaw(
        self, flame_converter: BlendshapeToFLAME,
    ) -> None:
        coeffs = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        coeffs[ARKIT_BLENDSHAPE_NAMES.index("jawOpen")] = 1.0
        frame = BlendshapeFrame(coefficients=coeffs)
        flame = flame_converter.convert(frame)
        assert flame[0] > 0.0

    def test_smile_maps_to_flame_lips(
        self, flame_converter: BlendshapeToFLAME,
    ) -> None:
        coeffs = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        coeffs[ARKIT_BLENDSHAPE_NAMES.index("mouthSmileLeft")] = 0.8
        coeffs[ARKIT_BLENDSHAPE_NAMES.index("mouthSmileRight")] = 0.8
        frame = BlendshapeFrame(coefficients=coeffs)
        flame = flame_converter.convert(frame)
        assert flame[13] > 0.0
        assert flame[14] > 0.0

    def test_blink_maps_to_flame_eyes(
        self, flame_converter: BlendshapeToFLAME,
    ) -> None:
        coeffs = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        coeffs[ARKIT_BLENDSHAPE_NAMES.index("eyeBlinkLeft")] = 1.0
        frame = BlendshapeFrame(coefficients=coeffs)
        flame = flame_converter.convert(frame)
        assert flame[40] > 0.0

    def test_from_local_adapter(
        self, flame_converter: BlendshapeToFLAME,
    ) -> None:
        adapter = Audio2FaceLocal(ema_alpha=1.0)
        sr = 16000
        t = np.linspace(0, 0.5, sr // 2, endpoint=False, dtype=np.float32)
        audio = 0.3 * np.sin(2 * np.pi * 200 * t).astype(np.float32)
        frame = adapter.process_audio_chunk(audio, sr)
        flame = flame_converter.convert(frame)
        assert flame.shape == (NUM_FLAME_EXPRESSIONS,)
        assert np.all(np.isfinite(flame))


# ---------------------------------------------------------------------------
# Real speech audio tests
# ---------------------------------------------------------------------------

class TestRealSpeechAudio:
    """Tests using real voice data from ~/.clipcannon/voice_data/santa/wavs/."""

    @staticmethod
    def _load_wav(path: str) -> tuple[np.ndarray, int]:
        """Load a WAV file as float32 mono."""
        import wave

        with wave.open(path, "rb") as wf:
            sr = wf.getframerate()
            n_channels = wf.getnchannels()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
            sw = wf.getsampwidth()

        if sw == 2:
            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            data /= 32768.0
        elif sw == 4:
            data = np.frombuffer(raw, dtype=np.int32).astype(np.float32)
            data /= 2147483648.0
        else:
            raise ValueError(f"Unsupported sample width: {sw}")

        if n_channels > 1:
            data = data[::n_channels]
        return data, sr

    @staticmethod
    def _find_voice_wavs() -> list[str]:
        pattern = os.path.expanduser(
            "~/.clipcannon/voice_data/santa/wavs/*.wav",
        )
        return sorted(glob.glob(pattern))

    def test_real_speech_produces_nonzero_blendshapes(self) -> None:
        wavs = self._find_voice_wavs()
        if not wavs:
            pytest.skip("No voice WAV files found")

        audio, sr = self._load_wav(wavs[0])
        adapter = Audio2FaceLocal(ema_alpha=0.5)
        chunk_size = sr // 20
        active_frames = 0
        total_frames = 0

        for start in range(0, len(audio) - chunk_size, chunk_size):
            chunk = audio[start:start + chunk_size]
            frame = adapter.process_audio_chunk(chunk, sr)
            total_frames += 1
            if frame.get("jawOpen") > 0.05:
                active_frames += 1

        assert active_frames > 0, (
            f"No active jaw frames out of {total_frames} total"
        )

    def test_real_speech_jaw_varies(self) -> None:
        wavs = self._find_voice_wavs()
        if not wavs:
            pytest.skip("No voice WAV files found")

        audio, sr = self._load_wav(wavs[0])
        adapter = Audio2FaceLocal(ema_alpha=0.6)
        chunk_size = sr // 20
        jaw_values: list[float] = []

        for start in range(0, len(audio) - chunk_size, chunk_size):
            chunk = audio[start:start + chunk_size]
            frame = adapter.process_audio_chunk(chunk, sr)
            jaw_values.append(frame.get("jawOpen"))

        if len(jaw_values) < 3:
            pytest.skip("Audio too short for variation test")

        assert float(np.std(jaw_values)) > 0.001

    def test_real_speech_all_coefficients_valid(self) -> None:
        wavs = self._find_voice_wavs()
        if not wavs:
            pytest.skip("No voice WAV files found")

        audio, sr = self._load_wav(wavs[0])
        adapter = Audio2FaceLocal(ema_alpha=0.5)
        chunk_size = sr // 20

        for start in range(0, len(audio) - chunk_size, chunk_size):
            chunk = audio[start:start + chunk_size]
            frame = adapter.process_audio_chunk(chunk, sr)
            assert np.all(frame.coefficients >= 0.0)
            assert np.all(frame.coefficients <= 1.0)
            assert not np.any(np.isnan(frame.coefficients))

    def test_real_speech_flame_conversion(self) -> None:
        wavs = self._find_voice_wavs()
        if not wavs:
            pytest.skip("No voice WAV files found")

        audio, sr = self._load_wav(wavs[0])
        adapter = Audio2FaceLocal(ema_alpha=0.5)
        converter = BlendshapeToFLAME()
        chunk_size = sr // 20
        chunk = audio[:chunk_size]
        frame = adapter.process_audio_chunk(chunk, sr)
        flame = converter.convert(frame)

        assert flame.shape == (NUM_FLAME_EXPRESSIONS,)
        assert np.all(np.isfinite(flame))
        assert np.all(flame >= -2.0)
        assert np.all(flame <= 2.0)


# ---------------------------------------------------------------------------
# Performance benchmark
# ---------------------------------------------------------------------------

class TestPerformance:
    """Benchmark: measure ms per chunk (target <5ms)."""

    def test_local_adapter_under_5ms(self) -> None:
        adapter = Audio2FaceLocal(ema_alpha=0.5)
        sr = 16000
        chunk_size = sr // 20
        audio = (
            0.3 * np.sin(
                2 * np.pi * 200
                * np.linspace(0, 0.05, chunk_size, dtype=np.float32),
            )
        ).astype(np.float32)

        for _ in range(5):
            adapter.process_audio_chunk(audio, sr)

        n_runs = 100
        t0 = time.perf_counter()
        for _ in range(n_runs):
            adapter.process_audio_chunk(audio, sr)
        avg_ms = (time.perf_counter() - t0) * 1000.0 / n_runs

        assert avg_ms < 5.0, (
            f"Average processing time {avg_ms:.2f}ms exceeds 5ms target"
        )

    def test_flame_conversion_under_1ms(self) -> None:
        converter = BlendshapeToFLAME()
        coeffs = np.random.default_rng(42).random(
            NUM_ARKIT_BLENDSHAPES,
        ).astype(np.float32)
        frame = BlendshapeFrame(coefficients=coeffs)

        for _ in range(5):
            converter.convert(frame)

        n_runs = 1000
        t0 = time.perf_counter()
        for _ in range(n_runs):
            converter.convert(frame)
        avg_ms = (time.perf_counter() - t0) * 1000.0 / n_runs

        assert avg_ms < 1.0, (
            f"FLAME conversion {avg_ms:.3f}ms exceeds 1ms target"
        )
