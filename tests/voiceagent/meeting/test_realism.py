"""Tests for voiceagent.meeting.realism -- real numpy ops, no mocks."""
from __future__ import annotations

import numpy as np

from voiceagent.meeting.meeting_behavior import MeetingBehavior
from voiceagent.meeting.realism import (
    BlinkGenerator,
    add_film_grain,
    apply_brightness_jitter,
    generate_micro_saccade,
)


def _make_frame(val: int = 128, h: int = 720, w: int = 1280) -> np.ndarray:
    """Create a solid-color uint8 RGB test frame."""
    return np.full((h, w, 3), val, dtype=np.uint8)


class TestFilmGrain:

    def test_film_grain_output_type(self) -> None:
        frame = _make_frame()
        result = add_film_grain(frame)
        assert result.dtype == np.uint8
        assert result.shape == (720, 1280, 3)

    def test_film_grain_modifies_frame(self) -> None:
        frame = _make_frame()
        result = add_film_grain(frame, intensity=0.05)
        assert not np.array_equal(result, frame)

    def test_film_grain_bounded(self) -> None:
        frame = _make_frame(val=250)
        result = add_film_grain(frame, intensity=0.03)
        assert result.min() >= 0
        assert result.max() <= 255

    def test_film_grain_near_black(self) -> None:
        frame = _make_frame(val=2)
        result = add_film_grain(frame, intensity=0.03)
        assert result.min() >= 0


class TestBrightnessJitter:

    def test_brightness_jitter_output_type(self) -> None:
        frame = _make_frame()
        result = apply_brightness_jitter(frame, phase=0.5)
        assert result.dtype == np.uint8
        assert result.shape == frame.shape

    def test_brightness_jitter_at_zero_phase(self) -> None:
        frame = _make_frame()
        result = apply_brightness_jitter(frame, phase=0.0)
        # sin(0) = 0, so factor = 1.0 -- output should be identical
        assert np.array_equal(result, frame)


class TestMicroSaccade:

    def test_micro_saccade_range(self) -> None:
        for i in range(100):
            dx, dy = generate_micro_saccade(i)
            assert -3 <= dx <= 3, f"dx={dx} out of range at frame {i}"
            assert -3 <= dy <= 3, f"dy={dy} out of range at frame {i}"

    def test_micro_saccade_deterministic(self) -> None:
        a = generate_micro_saccade(42)
        b = generate_micro_saccade(42)
        assert a == b


class TestBlinkGenerator:

    def test_blink_generator_produces_blinks(self) -> None:
        blink = BlinkGenerator(mean_interval_s=1.0, std_s=0.3)
        alphas = [blink.get_blink_alpha(i) for i in range(200)]
        blink_frames = [a for a in alphas if a > 0.1]
        print(f"Blinks in 200 frames: {len(blink_frames)}")
        assert len(blink_frames) >= 1

    def test_blink_alpha_range(self) -> None:
        blink = BlinkGenerator(mean_interval_s=1.0, std_s=0.3)
        for i in range(300):
            alpha = blink.get_blink_alpha(i)
            assert 0.0 <= alpha <= 1.0, f"alpha={alpha} out of range at frame {i}"

    def test_blink_apply_darkens(self) -> None:
        blink = BlinkGenerator()
        frame = _make_frame(val=200, h=100, w=100)
        eye_region = (20, 20, 30, 15)
        result = blink.apply_blink(frame, alpha=0.8, eye_region=eye_region)
        # Eye region should be darker
        orig_mean = frame[20:35, 20:50].mean()
        new_mean = result[20:35, 20:50].mean()
        print(f"Blink darken: orig_mean={orig_mean:.1f}, new_mean={new_mean:.1f}")
        assert new_mean < orig_mean


class TestComfortNoise:

    def test_comfort_noise_amplitude(self) -> None:
        noise = MeetingBehavior.generate_comfort_noise(
            duration_ms=100, sample_rate=44100, dbfs=-60,
        )
        # -60 dBFS = amplitude of 0.001
        assert noise.dtype == np.float32
        assert np.abs(noise).max() < 0.01, (
            f"Max amplitude {np.abs(noise).max():.6f} too high for -60dBFS"
        )

    def test_comfort_noise_duration(self) -> None:
        noise = MeetingBehavior.generate_comfort_noise(
            duration_ms=200, sample_rate=44100, dbfs=-60,
        )
        expected_samples = int(44100 * 200 / 1000)
        assert len(noise) == expected_samples
