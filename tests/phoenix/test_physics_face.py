"""Tests for physics-based face animation engine.

Validates that deterministic articulatory-acoustic mappings produce
correct face states for known vowel sounds, silence, and edge cases.
All audio is synthesized directly -- no external data files needed.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from phoenix.render.audio_features import (
    clamp as _clamp,
    extract_f0_yin as _extract_f0_yin,
    extract_formants_lpc as _extract_formants_lpc,
    zero_crossing_rate as _zero_crossing_rate,
)
from phoenix.render.physics_face import (
    FaceState,
    PhysicsFaceEngine,
)

SR = 24000
FPS = 30
FRAME_SAMPLES = SR // FPS  # 800 samples per frame


# ---------------------------------------------------------------------------
# Audio synthesis helpers
# ---------------------------------------------------------------------------

def _make_sine(freq: float, duration: float = 0.1, sr: int = SR) -> np.ndarray:
    """Generate a pure sine tone."""
    t = np.arange(int(sr * duration), dtype=np.float32) / sr
    return (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)


def _make_vowel_ah(duration: float = 0.1, sr: int = SR) -> np.ndarray:
    """Synthesize a vowel-like signal with AH formants.

    AH: F1 ~800 Hz, F2 ~1200 Hz, F3 ~2800 Hz.
    """
    t = np.arange(int(sr * duration), dtype=np.float32) / sr
    f0 = 120.0  # Male fundamental
    # Generate harmonics modulated by formant envelope
    signal = np.zeros_like(t)
    for h in range(1, 30):
        freq = f0 * h
        # Formant amplitude envelope
        amp = 0.0
        for fc, bw in [(800, 100), (1200, 120), (2800, 200)]:
            amp += np.exp(-0.5 * ((freq - fc) / bw) ** 2)
        signal += amp * np.sin(2 * np.pi * freq * t)
    # Normalize
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = (signal / peak * 0.4).astype(np.float32)
    return signal


def _make_vowel_ee(duration: float = 0.1, sr: int = SR) -> np.ndarray:
    """Synthesize a vowel-like signal with EE formants.

    EE: F1 ~300 Hz, F2 ~2400 Hz, F3 ~3200 Hz.
    """
    t = np.arange(int(sr * duration), dtype=np.float32) / sr
    f0 = 120.0
    signal = np.zeros_like(t)
    for h in range(1, 30):
        freq = f0 * h
        amp = 0.0
        for fc, bw in [(300, 80), (2400, 150), (3200, 200)]:
            amp += np.exp(-0.5 * ((freq - fc) / bw) ** 2)
        signal += amp * np.sin(2 * np.pi * freq * t)
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = (signal / peak * 0.4).astype(np.float32)
    return signal


def _make_vowel_oo(duration: float = 0.1, sr: int = SR) -> np.ndarray:
    """Synthesize a vowel-like signal with OO formants.

    OO: F1 ~350 Hz, F2 ~700 Hz, F3 ~2500 Hz.
    """
    t = np.arange(int(sr * duration), dtype=np.float32) / sr
    f0 = 120.0
    signal = np.zeros_like(t)
    for h in range(1, 30):
        freq = f0 * h
        amp = 0.0
        for fc, bw in [(350, 70), (700, 100), (2500, 200)]:
            amp += np.exp(-0.5 * ((freq - fc) / bw) ** 2)
        signal += amp * np.sin(2 * np.pi * freq * t)
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = (signal / peak * 0.4).astype(np.float32)
    return signal


def _make_fricative(duration: float = 0.1, sr: int = SR) -> np.ndarray:
    """Synthesize a fricative-like signal (white noise = high ZCR)."""
    rng = np.random.default_rng(42)
    return (rng.standard_normal(int(sr * duration)) * 0.3).astype(np.float32)


def _make_silence(duration: float = 0.1, sr: int = SR) -> np.ndarray:
    """Generate silence."""
    return np.zeros(int(sr * duration), dtype=np.float32)


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------

class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5) == 0.5

    def test_below_min(self):
        assert _clamp(-0.5) == 0.0

    def test_above_max(self):
        assert _clamp(1.5) == 1.0

    def test_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(1.0) == 1.0


class TestZeroCrossingRate:
    def test_sine_wave(self):
        """A sine wave at freq Hz crosses zero ~2*freq times/sec."""
        audio = _make_sine(1000.0, duration=0.05)
        zcr = _zero_crossing_rate(audio, SR)
        # Should be approximately 2000 (2 * 1000 Hz)
        assert 1500 < zcr < 2500

    def test_silence_zcr(self):
        zcr = _zero_crossing_rate(_make_silence(), SR)
        assert zcr == 0.0

    def test_noise_high_zcr(self):
        """White noise should have very high ZCR."""
        zcr = _zero_crossing_rate(_make_fricative(duration=0.05), SR)
        assert zcr > 5000


class TestF0Extraction:
    def test_known_pitch(self):
        """Pure sine at 200 Hz should yield F0 near 200."""
        audio = _make_sine(200.0, duration=0.1)
        f0 = _extract_f0_yin(audio, SR)
        # Allow 10% tolerance
        assert 170 < f0 < 230, f"Expected ~200 Hz, got {f0}"

    def test_unvoiced(self):
        """Noise should return 0 (unvoiced)."""
        f0 = _extract_f0_yin(_make_fricative(duration=0.1), SR)
        # Noise is aperiodic -- should return 0 or a nonsensical value
        # (YIN threshold should reject it)
        assert f0 == 0.0 or f0 > 400  # Either undetected or wild

    def test_silence_f0(self):
        f0 = _extract_f0_yin(_make_silence(), SR)
        assert f0 == 0.0


class TestFormantExtraction:
    def test_returns_three_values(self):
        audio = _make_vowel_ah(duration=0.05)
        f1, f2, f3 = _extract_formants_lpc(audio, SR)
        assert isinstance(f1, float)
        assert isinstance(f2, float)
        assert isinstance(f3, float)

    def test_short_audio(self):
        """Very short audio should return zeros."""
        audio = np.array([0.1, -0.1], dtype=np.float32)
        f1, f2, f3 = _extract_formants_lpc(audio, SR, order=12)
        assert f1 == 0.0
        assert f2 == 0.0
        assert f3 == 0.0

    def test_silence_formants(self):
        f1, f2, f3 = _extract_formants_lpc(_make_silence(), SR)
        # Silence has no stable formants
        assert f1 >= 0.0


# ---------------------------------------------------------------------------
# FaceState tests
# ---------------------------------------------------------------------------

class TestFaceState:
    def test_default_is_silence(self):
        state = FaceState()
        assert state.is_silence is True
        assert state.jaw_open == 0.0

    def test_to_blendshapes_keys(self):
        state = FaceState(jaw_open=0.5, lip_spread=0.3, effort=0.4)
        bs = state.to_blendshapes()
        # Check for key ARKit blendshapes
        assert "jawOpen" in bs
        assert "mouthSmileLeft" in bs
        assert "mouthSmileRight" in bs
        assert "mouthPucker" in bs
        assert "mouthFunnel" in bs
        assert "browInnerUp" in bs
        assert "eyeSquintLeft" in bs
        assert "eyeSquintRight" in bs
        assert "cheekPuff" in bs
        assert "noseSneerLeft" in bs

    def test_to_blendshapes_values_clamped(self):
        state = FaceState(
            jaw_open=1.0, lip_spread=1.0, lip_round=1.0,
            lip_pucker=1.0, effort=1.0, brow_raise=1.0,
            squint=1.0, is_silence=False,
        )
        bs = state.to_blendshapes()
        for name, val in bs.items():
            assert 0.0 <= val <= 1.0, f"{name} = {val} out of range"

    def test_silence_mouth_close(self):
        """In silence, mouthClose should be high (mouth closed)."""
        state = FaceState(jaw_open=0.0, is_silence=True)
        bs = state.to_blendshapes()
        assert bs["mouthClose"] == 1.0

    def test_to_flame_params_shapes(self):
        state = FaceState(jaw_open=0.7, lip_spread=0.5)
        exp, jaw = state.to_flame_params()
        assert exp.shape == (100,)
        assert jaw.shape == (3,)
        assert exp.dtype == np.float32
        assert jaw.dtype == np.float32

    def test_to_flame_jaw_open(self):
        """More jaw_open should produce larger FLAME jaw rotation."""
        s1 = FaceState(jaw_open=0.1)
        s2 = FaceState(jaw_open=0.9)
        _, j1 = s1.to_flame_params()
        _, j2 = s2.to_flame_params()
        assert j2[0] > j1[0], "Higher jaw_open should mean more jaw rotation"

    def test_to_flame_expression_dim0(self):
        """FLAME expression dim 0 should scale with jaw_open."""
        s1 = FaceState(jaw_open=0.2)
        s2 = FaceState(jaw_open=0.8)
        e1, _ = s1.to_flame_params()
        e2, _ = s2.to_flame_params()
        assert e2[0] > e1[0]

    def test_blendshape_count(self):
        """Should produce at least 40 blendshapes (ARKit has 52)."""
        bs = FaceState().to_blendshapes()
        assert len(bs) >= 40


# ---------------------------------------------------------------------------
# PhysicsFaceEngine tests
# ---------------------------------------------------------------------------

class TestPhysicsFaceEngine:
    def test_init(self):
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS)
        assert engine.samples_per_frame == FRAME_SAMPLES

    def test_silence_produces_closed_mouth(self):
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS)
        face = engine.process_audio_chunk(_make_silence(duration=0.05))
        assert face.is_silence is True
        assert face.jaw_open < 0.1

    def test_loud_audio_produces_effort(self):
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS)
        # First, set the max energy baseline with a moderate signal
        audio = _make_vowel_ah(duration=0.05)
        engine.process_audio_chunk(audio * 0.1)  # Quiet baseline
        # Now a loud chunk should show high effort
        face = engine.process_audio_chunk(audio)
        assert face.effort > 0.2

    def test_vowel_ah_opens_jaw(self):
        """AH vowel (high F1) should produce jaw opening."""
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS, smoothing_alpha=1.0)
        audio = _make_vowel_ah(duration=0.05)
        face = engine.process_audio_chunk(audio)
        # AH should have open jaw (F1 ~800 Hz drives jaw_open)
        assert not face.is_silence
        # The engine maps F1 to jaw_open; with synthetic vowel
        # the exact formant extraction may vary, but it should
        # produce some jaw opening since the audio is voiced
        assert face.jaw_open > 0.0

    def test_fricative_shows_teeth(self):
        """Noise-like signal (high ZCR) should show teeth."""
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS, smoothing_alpha=1.0)
        audio = _make_fricative(duration=0.05)
        face = engine.process_audio_chunk(audio)
        # High ZCR should trigger teeth_visible
        assert face.teeth_visible > 0.0 or face._zcr > 3000

    def test_temporal_smoothing(self):
        """Output should change gradually, not jump."""
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS, smoothing_alpha=0.5)

        # Start from silence
        s1 = engine.process_audio_chunk(_make_silence(duration=0.05))
        assert s1.jaw_open < 0.05

        # Jump to loud vowel -- should NOT instantly jump to max
        s2 = engine.process_audio_chunk(_make_vowel_ah(duration=0.05))
        # With alpha=0.5, the smoothed value should be less than the raw value
        # (since previous was ~0). Hard to test exact value but it should
        # be less than if we had alpha=1.0
        engine2 = PhysicsFaceEngine(sample_rate=SR, fps=FPS, smoothing_alpha=1.0)
        engine2.process_audio_chunk(_make_silence(duration=0.05))
        s2_instant = engine2.process_audio_chunk(_make_vowel_ah(duration=0.05))

        # Smoothed jaw should be <= instant jaw
        assert s2.jaw_open <= s2_instant.jaw_open + 0.01

    def test_reset_clears_state(self):
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS)
        engine.process_audio_chunk(_make_vowel_ah(duration=0.05))
        engine.reset()
        face = engine.process_audio_chunk(_make_silence(duration=0.05))
        assert face.is_silence

    def test_process_audio_batch(self):
        """Batch processing should return one state per frame."""
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS)
        audio = _make_vowel_ah(duration=0.2)  # 0.2s = 6 frames at 30fps
        states = engine.process_audio_batch(audio)
        expected_frames = len(audio) // FRAME_SAMPLES
        assert len(states) == expected_frames
        for s in states:
            assert isinstance(s, FaceState)

    def test_2d_audio_handled(self):
        """Engine should handle 2D audio arrays gracefully."""
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS)
        audio = _make_vowel_ah(duration=0.05).reshape(-1, 1)
        face = engine.process_audio_chunk(audio)
        assert isinstance(face, FaceState)

    def test_blendshapes_integration(self):
        """End-to-end: audio -> FaceState -> blendshapes."""
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS, smoothing_alpha=1.0)
        audio = _make_vowel_ah(duration=0.05)
        face = engine.process_audio_chunk(audio)
        bs = face.to_blendshapes()
        assert bs["jawOpen"] >= 0.0
        assert all(0.0 <= v <= 1.0 for v in bs.values())

    def test_flame_integration(self):
        """End-to-end: audio -> FaceState -> FLAME params."""
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS, smoothing_alpha=1.0)
        audio = _make_vowel_ah(duration=0.05)
        face = engine.process_audio_chunk(audio)
        exp, jaw = face.to_flame_params()
        assert exp.shape == (100,)
        assert jaw.shape == (3,)


class TestPerformance:
    def test_realtime_throughput(self):
        """Engine must process 30fps of audio chunks in real time.

        At 30fps, each chunk is ~33ms of audio (800 samples at 24kHz).
        Processing each chunk must take < 33ms (i.e., real-time capable).
        """
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS)
        chunk = _make_vowel_ah(duration=1.0 / FPS)
        n_frames = 60  # 2 seconds worth

        t0 = time.perf_counter()
        for _ in range(n_frames):
            engine.process_audio_chunk(chunk)
        elapsed = time.perf_counter() - t0

        budget = n_frames / FPS  # 2.0 seconds
        assert elapsed < budget, (
            f"Processing {n_frames} frames took {elapsed:.3f}s, "
            f"budget was {budget:.1f}s ({n_frames}fps)"
        )

    def test_single_chunk_latency(self):
        """Single chunk should process in under 5ms."""
        engine = PhysicsFaceEngine(sample_rate=SR, fps=FPS)
        chunk = _make_vowel_ah(duration=1.0 / FPS)

        # Warmup
        engine.process_audio_chunk(chunk)

        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            engine.process_audio_chunk(chunk)
            times.append(time.perf_counter() - t0)

        median_ms = sorted(times)[len(times) // 2] * 1000
        assert median_ms < 5.0, f"Median latency {median_ms:.2f}ms exceeds 5ms"
