"""Tests for the compositor bridge (numpy uint8 ↔ CuPy GPU)."""
import numpy as np
import pytest

from phoenix.render.compositor_bridge import (
    gpu_alpha_blend,
    gpu_brightness_jitter,
    gpu_composite_face,
    gpu_film_grain,
)


class TestGpuCompositeFace:
    """Test face compositing via GPU bridge."""

    def test_paste_face_center(self) -> None:
        base = np.zeros((100, 100, 3), dtype=np.uint8)
        face = np.full((20, 20, 3), 200, dtype=np.uint8)
        result = gpu_composite_face(base, face, x=40, y=40, w=20, h=20)
        assert result.dtype == np.uint8
        assert result.shape == (100, 100, 3)
        # Center should be bright
        assert result[50, 50, 0] > 150

    def test_paste_with_blend(self) -> None:
        base = np.full((64, 64, 3), 100, dtype=np.uint8)
        face = np.full((16, 16, 3), 200, dtype=np.uint8)
        result = gpu_composite_face(base, face, x=24, y=24, w=16, h=16, blend_alpha=0.5)
        # Should be approximately 150 (midpoint of 100 and 200)
        pixel = result[32, 32]
        assert 130 < pixel[0] < 170, f"Expected ~150, got {pixel[0]}"

    def test_face_resize_on_gpu(self) -> None:
        """Face 10x10 resized to 30x30 target region."""
        base = np.zeros((100, 100, 3), dtype=np.uint8)
        face = np.full((10, 10, 3), 255, dtype=np.uint8)
        result = gpu_composite_face(base, face, x=10, y=10, w=30, h=30)
        # 30x30 region should be bright
        assert result[25, 25, 0] > 200

    def test_boundary_clip(self) -> None:
        """Face extends beyond frame edge — should not crash."""
        base = np.zeros((50, 50, 3), dtype=np.uint8)
        face = np.full((20, 20, 3), 128, dtype=np.uint8)
        result = gpu_composite_face(base, face, x=40, y=40, w=20, h=20)
        assert result.shape == (50, 50, 3)


class TestGpuFilmGrain:
    """Test film grain via GPU bridge."""

    def test_adds_noise(self) -> None:
        frame = np.full((64, 64, 3), 128, dtype=np.uint8)
        result = gpu_film_grain(frame, intensity=0.05)
        assert result.dtype == np.uint8
        diff = np.abs(result.astype(float) - frame.astype(float))
        assert diff.mean() > 1.0, "Expected visible noise"

    def test_zero_intensity(self) -> None:
        frame = np.full((32, 32, 3), 100, dtype=np.uint8)
        result = gpu_film_grain(frame, intensity=0.0)
        np.testing.assert_array_equal(result, frame)


class TestGpuBrightnessJitter:
    """Test brightness jitter via GPU bridge."""

    def test_positive_shift(self) -> None:
        frame = np.full((32, 32, 3), 100, dtype=np.uint8)
        result = gpu_brightness_jitter(frame, amount=0.2)
        assert result.mean() > frame.mean(), (
            f"Expected brighter: input={frame.mean()}, output={result.mean()}"
        )

    def test_negative_shift(self) -> None:
        frame = np.full((32, 32, 3), 100, dtype=np.uint8)
        result = gpu_brightness_jitter(frame, amount=-0.2)
        assert result.mean() < frame.mean(), (
            f"Expected darker: input={frame.mean()}, output={result.mean()}"
        )


class TestGpuAlphaBlend:
    """Test alpha blending via GPU bridge."""

    def test_uniform_alpha(self) -> None:
        fg = np.full((32, 32, 3), 200, dtype=np.uint8)
        bg = np.full((32, 32, 3), 50, dtype=np.uint8)
        result = gpu_alpha_blend(fg, bg, alpha=0.5)
        # Should be ~125
        assert 110 < result[16, 16, 0] < 140

    def test_mask_alpha(self) -> None:
        fg = np.full((32, 32, 3), 255, dtype=np.uint8)
        bg = np.zeros((32, 32, 3), dtype=np.uint8)
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[:16, :] = 255  # Top half opaque
        result = gpu_alpha_blend(fg, bg, alpha=mask)
        assert result[8, 16, 0] > 200  # Top half bright
        assert result[24, 16, 0] < 50  # Bottom half dark
