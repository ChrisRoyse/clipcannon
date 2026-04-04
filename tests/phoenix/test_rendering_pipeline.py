"""Tests for Phase 0 rendering pipeline components.

Covers: TemporalFilter, WebcamEffects, EyeBehavior.
All tests use real GPU/CPU operations, no mocks.
"""
from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# TemporalFilter tests
# ---------------------------------------------------------------------------
class TestTemporalFilter:
    def test_first_call_returns_input_unchanged(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        params = {"jawOpen": 0.5, "browInnerUp": 0.3}
        result = f.update(params)
        assert result["jawOpen"] == pytest.approx(0.5)
        assert result["browInnerUp"] == pytest.approx(0.3)

    def test_smoothing_moves_toward_target(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        f.update({"jawOpen": 0.0})
        result = f.update({"jawOpen": 1.0})
        # jaw_alpha = 0.6, so: 0.6*1.0 + 0.4*0.0 = 0.6
        assert result["jawOpen"] == pytest.approx(0.6)

    def test_multiple_updates_converge(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        f.update({"jawOpen": 0.0})
        for _ in range(20):
            result = f.update({"jawOpen": 1.0})
        assert result["jawOpen"] > 0.99  # Should converge close to 1.0

    def test_jaw_faster_than_head(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        f.update({"jawOpen": 0.0, "headPitch": 0.0})
        result = f.update({"jawOpen": 1.0, "headPitch": 1.0})
        # Jaw (alpha=0.6) should respond faster than head (alpha=0.2)
        assert result["jawOpen"] > result["headPitch"]

    def test_different_mouth_params_use_mouth_alpha(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        f.update({"mouthSmileLeft": 0.0, "mouthFrownRight": 0.0})
        result = f.update({"mouthSmileLeft": 1.0, "mouthFrownRight": 1.0})
        # mouth_alpha = 0.5
        assert result["mouthSmileLeft"] == pytest.approx(0.5)
        assert result["mouthFrownRight"] == pytest.approx(0.5)

    def test_reset_clears_state(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        f.update({"jawOpen": 0.5})
        f.update({"jawOpen": 0.8})
        f.reset()
        result = f.update({"jawOpen": 0.0})
        assert result["jawOpen"] == pytest.approx(0.0)  # Fresh start

    def test_update_array_smoothing(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        v1 = np.zeros(10, dtype=np.float32)
        r1 = f.update_array(v1)
        assert np.allclose(r1, 0.0)

        v2 = np.ones(10, dtype=np.float32)
        r2 = f.update_array(v2, alpha=0.5)
        assert np.allclose(r2, 0.5)

    def test_update_array_different_length_resets(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        f.update_array(np.zeros(10))
        result = f.update_array(np.ones(5))  # Different length
        assert np.allclose(result, 1.0)  # Reset, returns input

    def test_unknown_param_uses_default_alpha(self):
        from phoenix.render.temporal_filter import TemporalFilter
        f = TemporalFilter()
        f.update({"customParam": 0.0})
        result = f.update({"customParam": 1.0})
        # default_alpha = 0.4
        assert result["customParam"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# WebcamEffects tests
# ---------------------------------------------------------------------------
class TestWebcamEffects:
    @pytest.fixture(autouse=True)
    def _check_cupy(self):
        try:
            import cupy as cp
            cp.cuda.Device(0).compute_capability
        except Exception:
            pytest.skip("CuPy/CUDA not available")

    def test_apply_returns_same_shape(self):
        import cupy as cp
        from phoenix.render.webcam_effects import WebcamEffects
        fx = WebcamEffects()
        frame = cp.ones((720, 1280, 3), dtype=cp.float32) * 0.5
        result = fx.apply(frame)
        assert result.shape == (720, 1280, 3)

    def test_output_clamped_to_01(self):
        import cupy as cp
        from phoenix.render.webcam_effects import WebcamEffects
        fx = WebcamEffects(noise_intensity=0.5, exposure_drift=0.5)
        frame = cp.ones((100, 100, 3), dtype=cp.float32) * 0.9
        result = fx.apply(frame)
        assert float(cp.max(result)) <= 1.0
        assert float(cp.min(result)) >= 0.0

    def test_noise_adds_variation(self):
        import cupy as cp
        from phoenix.render.webcam_effects import WebcamEffects
        fx = WebcamEffects(noise_intensity=0.1, exposure_drift=0, vignette_strength=0)
        frame = cp.ones((100, 100, 3), dtype=cp.float32) * 0.5
        result = fx.apply(frame)
        diff = float(cp.std(result))
        assert diff > 0.01  # Noise should add variation

    def test_vignette_darkens_corners(self):
        import cupy as cp
        from phoenix.render.webcam_effects import WebcamEffects
        fx = WebcamEffects(noise_intensity=0, exposure_drift=0, vignette_strength=0.3)
        frame = cp.ones((200, 200, 3), dtype=cp.float32) * 0.5
        result = fx.apply(frame)
        center = float(result[100, 100, 0])
        corner = float(result[0, 0, 0])
        assert corner < center  # Corner should be darker

    def test_effects_vary_over_time(self):
        import cupy as cp
        from phoenix.render.webcam_effects import WebcamEffects
        fx = WebcamEffects(exposure_drift=0.1, noise_intensity=0)
        frame = cp.ones((50, 50, 3), dtype=cp.float32) * 0.5
        means = []
        for _ in range(10):
            result = fx.apply(frame.copy())
            means.append(float(cp.mean(result)))
        # Exposure drift should cause slight variation
        assert max(means) - min(means) > 0.001

    def test_apply_uint8_roundtrip(self):
        from phoenix.render.webcam_effects import WebcamEffects
        fx = WebcamEffects(noise_intensity=0.01, exposure_drift=0, vignette_strength=0)
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        result = fx.apply_uint8(frame)
        assert result.shape == (100, 100, 3)
        assert result.dtype == np.uint8

    def test_reset_restarts_time(self):
        import cupy as cp
        from phoenix.render.webcam_effects import WebcamEffects
        fx = WebcamEffects()
        frame = cp.ones((50, 50, 3), dtype=cp.float32) * 0.5
        for _ in range(100):
            fx.apply(frame)
        fx.reset()
        assert fx._frame_count == 0


# ---------------------------------------------------------------------------
# EyeBehavior tests
# ---------------------------------------------------------------------------
class TestEyeBehavior:
    def test_initial_state_neutral(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior()
        state = eye.update()
        assert state.gaze_x == pytest.approx(0.0, abs=0.1)
        assert state.gaze_y == pytest.approx(0.0, abs=0.1)
        assert state.blink_left == pytest.approx(0.0, abs=0.1)

    def test_blink_occurs_within_10_seconds(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior(fps=25, blink_rate_per_min=30)  # Frequent blinks
        saw_blink = False
        for _ in range(250):  # 10 seconds at 25fps
            state = eye.update()
            if state.blink_left > 0.5:
                saw_blink = True
                break
        assert saw_blink, "Expected at least one blink in 10 seconds"

    def test_blink_closes_and_opens(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior()
        eye.force_blink()
        values = []
        for _ in range(15):  # ~600ms at 25fps
            state = eye.update()
            values.append(state.blink_left)
        assert max(values) > 0.8  # Should fully close
        assert values[-1] < 0.2  # Should reopen

    def test_gaze_tracks_target(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior()
        eye.set_gaze_target(5.0, 3.0)
        for _ in range(50):  # 2 seconds
            state = eye.update()
        assert state.gaze_x > 2.0  # Should have moved toward target
        assert state.gaze_y > 1.0

    def test_microsaccades_add_variation(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior()
        eye.set_gaze_target(0.0, 0.0)
        positions = set()
        for _ in range(75):  # 3 seconds
            state = eye.update()
            positions.add(round(state.gaze_x, 3))
        # Microsaccades should create multiple distinct positions
        assert len(positions) > 3

    def test_arousal_affects_eye_wideness(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye_calm = EyeBehavior()
        eye_calm.set_arousal(0.0)
        calm = eye_calm.update()
        eye_exc = EyeBehavior()
        eye_exc.set_arousal(1.0)
        excited = eye_exc.update()
        assert excited.eye_wide_left > calm.eye_wide_left

    def test_blink_asymmetry(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior()
        eye.force_blink()
        saw_asymmetry = False
        for _ in range(10):
            state = eye.update()
            if state.blink_left > 0.1 and state.blink_left != state.blink_right:
                saw_asymmetry = True
                break
        assert saw_asymmetry, "Blink should be slightly asymmetric"

    def test_to_arkit_dict_has_all_keys(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior()
        state = eye.update()
        arkit = state.to_arkit_dict()
        expected_keys = {
            "eyeLookInLeft", "eyeLookOutLeft", "eyeLookInRight", "eyeLookOutRight",
            "eyeLookUpLeft", "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight",
            "eyeBlinkLeft", "eyeBlinkRight", "eyeWideLeft", "eyeWideRight",
            "eyeSquintLeft", "eyeSquintRight",
        }
        assert set(arkit.keys()) == expected_keys

    def test_arkit_values_in_valid_range(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior()
        eye.set_gaze_target(10.0, 10.0)
        eye.set_arousal(1.0)
        eye.force_blink()
        for _ in range(10):
            state = eye.update()
            arkit = state.to_arkit_dict()
            for k, v in arkit.items():
                assert v >= 0.0, f"{k}={v} is negative"
                assert v <= 2.0, f"{k}={v} is too large"

    def test_reset_returns_to_neutral(self):
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior()
        eye.set_gaze_target(5.0, 5.0)
        for _ in range(50):
            eye.update()
        eye.reset()
        eye.set_gaze_target(0.0, 0.0)
        # After reset + several frames, gaze should approach zero
        for _ in range(50):
            state = eye.update()
        assert abs(state.gaze_x) < 1.0  # Close to zero (microsaccades add noise)
        assert state.blink_left == pytest.approx(0.0, abs=0.2)

    def test_25fps_consistent_timing(self):
        """Verify 250 frames = 10 seconds worth of behavior."""
        from phoenix.expression.eye_behavior import EyeBehavior
        eye = EyeBehavior(fps=25, blink_rate_per_min=18)
        blink_count = 0
        for _ in range(250):
            state = eye.update()
            if state.blink_left > 0.9:
                blink_count += 1
        # 18 blinks/min = ~3 blinks in 10 seconds
        assert 1 <= blink_count <= 8, f"Expected 1-8 blinks in 10s, got {blink_count}"
