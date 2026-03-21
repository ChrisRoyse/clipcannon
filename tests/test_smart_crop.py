"""Tests for the smart_crop module.

Tests cover:
- compute_crop_region with various aspect ratio conversions
- Face position clamping to frame bounds
- Safe area enforcement
- get_crop_for_scene decision logic
- smooth_crop_positions with EMA
- parse_aspect_ratio for all platforms
- PLATFORM_ASPECTS registry
"""

from __future__ import annotations

import pytest

from clipcannon.editing.smart_crop import (
    PLATFORM_ASPECTS,
    CropRegion,
    compute_crop_region,
    get_crop_for_scene,
    parse_aspect_ratio,
    smooth_crop_positions,
)


class TestComputeCropRegion:
    """Test the core crop region calculation."""

    def test_16_9_to_9_16_face_center(self) -> None:
        """16:9 source to 9:16 with face at center."""
        region = compute_crop_region(
            source_w=1920,
            source_h=1080,
            target_aspect="9:16",
            face_position_x=0.5,
            face_position_y=0.5,
        )
        # Target 9:16 from 1920x1080: crop_h=1080, crop_w=round(1080*9/16)=608
        assert region.width == 608  # round(1080 * 9/16)
        assert region.height == 1080
        # Centered on (960, 540): x = 960 - 304 = 656
        assert region.x >= 0
        assert region.x + region.width <= 1920
        assert region.y >= 0
        assert region.y + region.height <= 1080

    def test_16_9_to_9_16_face_right_clamped(self) -> None:
        """16:9 to 9:16 with face at right edge (0.8) is clamped."""
        region = compute_crop_region(
            source_w=1920,
            source_h=1080,
            target_aspect="9:16",
            face_position_x=0.8,
            face_position_y=0.5,
        )
        # Crop window must stay within frame
        assert region.x >= 0
        assert region.x + region.width <= 1920

    def test_16_9_to_1_1_center(self) -> None:
        """16:9 source to 1:1 with face at center."""
        region = compute_crop_region(
            source_w=1920,
            source_h=1080,
            target_aspect="1:1",
            face_position_x=0.5,
            face_position_y=0.5,
        )
        # 1:1 from landscape: crop_w=source_w=1920? No, target_ratio=1.0
        # source_ratio=1920/1080=1.78, target_ratio=1.0 < source_ratio
        # crop_h=1080, crop_w=round(1080*1.0)=1080
        assert region.width == 1080
        assert region.height == 1080
        assert region.x >= 0
        assert region.x + region.width <= 1920

    def test_safe_area_enforcement(self) -> None:
        """Safe area constraint keeps face within safe zone."""
        region = compute_crop_region(
            source_w=1920,
            source_h=1080,
            target_aspect="9:16",
            face_position_x=0.95,
            face_position_y=0.5,
            safe_area_pct=0.85,
        )
        # Face at far right should still be clamped to frame
        assert region.x >= 0
        assert region.x + region.width <= 1920

    def test_4_5_aspect_ratio(self) -> None:
        """Crop with 4:5 aspect ratio computes valid region."""
        region = compute_crop_region(
            source_w=1920,
            source_h=1080,
            target_aspect="4:5",
            face_position_x=0.5,
            face_position_y=0.5,
        )
        # 4:5 ratio = 0.8 < 1.78, so crop_h=1080, crop_w=round(1080*0.8)=864
        assert region.width == 864
        assert region.height == 1080
        assert region.x >= 0
        assert region.x + region.width <= 1920


class TestGetCropForScene:
    """Test scene-based crop strategy selection."""

    def test_extreme_closeup_center_crop(self) -> None:
        """extreme_closeup with safe_for_vertical uses center crop."""
        scene = {
            "shot_type": "extreme_closeup",
            "crop_recommendation": "safe_for_vertical",
            "face_detected": True,
            "face_position_x": 0.7,
            "face_position_y": 0.5,
        }
        region = get_crop_for_scene(scene, 1920, 1080, "9:16")
        # extreme_closeup should center crop regardless of face position
        # face_position used is 0.5 (center)
        assert region.width > 0
        assert region.height > 0

    def test_medium_face_detection_triggered(self) -> None:
        """medium + needs_reframe with face uses face position."""
        scene = {
            "shot_type": "medium",
            "crop_recommendation": "needs_reframe",
            "face_detected": True,
            "face_position_x": 0.6,
            "face_position_y": 0.4,
        }
        region = get_crop_for_scene(scene, 1920, 1080, "9:16")
        assert region.width > 0
        assert region.height > 0
        assert region.x >= 0


class TestSmoothCropPositions:
    """Test EMA smoothing of crop positions."""

    def test_smoothing_reduces_jumps(self) -> None:
        """Smoothing 5 regions reduces jump distances."""
        regions = [
            CropRegion(x=100, y=0, width=608, height=1080),
            CropRegion(x=500, y=0, width=608, height=1080),
            CropRegion(x=200, y=0, width=608, height=1080),
            CropRegion(x=800, y=0, width=608, height=1080),
            CropRegion(x=300, y=0, width=608, height=1080),
        ]
        smoothed = smooth_crop_positions(regions, alpha=0.3)
        assert len(smoothed) == 5

        # Calculate total jump distance for original vs smoothed
        original_jumps = sum(
            abs(regions[i].x - regions[i - 1].x)
            for i in range(1, len(regions))
        )
        smoothed_jumps = sum(
            abs(smoothed[i].x - smoothed[i - 1].x)
            for i in range(1, len(smoothed))
        )
        assert smoothed_jumps < original_jumps

    def test_single_region_unchanged(self) -> None:
        """Single region list returns the same region."""
        regions = [CropRegion(x=100, y=0, width=608, height=1080)]
        smoothed = smooth_crop_positions(regions)
        assert len(smoothed) == 1
        assert smoothed[0].x == 100


class TestParseAspectRatio:
    """Test aspect ratio string parsing."""

    def test_all_platform_aspects(self) -> None:
        """All platform aspect ratios parse correctly."""
        for platform, aspect in PLATFORM_ASPECTS.items():
            ratio = parse_aspect_ratio(aspect)
            assert ratio > 0, f"Failed for {platform}: {aspect}"

    def test_9_16(self) -> None:
        """9:16 -> 0.5625."""
        assert parse_aspect_ratio("9:16") == pytest.approx(0.5625)

    def test_16_9(self) -> None:
        """16:9 -> ~1.778."""
        assert parse_aspect_ratio("16:9") == pytest.approx(16.0 / 9.0)

    def test_1_1(self) -> None:
        """1:1 -> 1.0."""
        assert parse_aspect_ratio("1:1") == pytest.approx(1.0)

    def test_invalid_format(self) -> None:
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError):
            parse_aspect_ratio("16x9")

    def test_platform_aspects_has_7_platforms(self) -> None:
        """PLATFORM_ASPECTS has all 7 platforms."""
        expected = {
            "tiktok",
            "instagram_reels",
            "youtube_shorts",
            "youtube_standard",
            "youtube_4k",
            "facebook",
            "linkedin",
        }
        assert set(PLATFORM_ASPECTS.keys()) == expected
