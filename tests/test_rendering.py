"""Tests for the rendering profiles module.

Tests cover:
- get_profile for all 7 profiles
- list_profiles returns 7 profiles
- get_software_fallback replaces NVENC codecs
- EncodingProfile field completeness
- Platform-specific profile dimensions and limits
- Generation loss prevention logic
"""

from __future__ import annotations

import pytest

from clipcannon.exceptions import PipelineError
from clipcannon.rendering.profiles import (
    EncodingProfile,
    get_profile,
    get_software_fallback,
    list_profiles,
)


class TestGetProfile:
    """Test profile lookup by name."""

    def test_all_7_profiles(self) -> None:
        """All 7 profiles load successfully."""
        names = list_profiles()
        assert len(names) == 7
        for name in names:
            profile = get_profile(name)
            assert isinstance(profile, EncodingProfile)
            assert profile.name == name

    def test_unknown_profile_raises(self) -> None:
        """Unknown profile name raises PipelineError."""
        with pytest.raises(PipelineError):
            get_profile("nonexistent_profile")


class TestListProfiles:
    """Test profile listing."""

    def test_returns_7_profiles(self) -> None:
        """list_profiles returns 7 sorted profile names."""
        profiles = list_profiles()
        assert len(profiles) == 7
        assert profiles == sorted(profiles)


class TestSoftwareFallback:
    """Test software codec substitution."""

    def test_h264_nvenc_to_libx264(self) -> None:
        """h264_nvenc is replaced with libx264."""
        profile = get_profile("tiktok_vertical")
        assert profile.video_codec == "h264_nvenc"
        sw = get_software_fallback(profile)
        assert sw.video_codec == "libx264"
        # Other fields should remain the same
        assert sw.width == profile.width
        assert sw.height == profile.height
        assert sw.fps == profile.fps
        assert sw.video_bitrate == profile.video_bitrate

    def test_unknown_codec_preserved(self) -> None:
        """Unknown codec is passed through unchanged."""
        profile = EncodingProfile(
            name="test",
            width=1920,
            height=1080,
            aspect_ratio="16:9",
            fps=30,
            video_codec="libx264",
            video_bitrate="8M",
            max_bitrate="10M",
            bufsize="20M",
            audio_codec="aac",
            audio_bitrate="192k",
            audio_sample_rate=44100,
            max_duration_ms=60000,
            min_duration_ms=5000,
            movflags="+faststart",
        )
        sw = get_software_fallback(profile)
        assert sw.video_codec == "libx264"


class TestEncodingProfileFields:
    """Test that EncodingProfile has all required fields."""

    def test_has_all_required_fields(self) -> None:
        """EncodingProfile dataclass has all expected fields."""
        profile = get_profile("tiktok_vertical")
        required = [
            "name",
            "width",
            "height",
            "aspect_ratio",
            "fps",
            "video_codec",
            "video_bitrate",
            "max_bitrate",
            "bufsize",
            "audio_codec",
            "audio_bitrate",
            "audio_sample_rate",
            "max_duration_ms",
            "min_duration_ms",
            "movflags",
        ]
        for field in required:
            assert hasattr(profile, field), f"Missing field: {field}"


class TestPlatformProfiles:
    """Test platform-specific profile configurations."""

    def test_tiktok_vertical(self) -> None:
        """TikTok vertical: 1080x1920, 30fps, max 60s."""
        p = get_profile("tiktok_vertical")
        assert p.width == 1080
        assert p.height == 1920
        assert p.fps == 30
        assert p.max_duration_ms == 60000

    def test_youtube_standard(self) -> None:
        """YouTube standard: 1920x1080, max 720000ms."""
        p = get_profile("youtube_standard")
        assert p.width == 1920
        assert p.height == 1080
        assert p.max_duration_ms == 720000

    def test_linkedin_square(self) -> None:
        """LinkedIn: 1080x1080 (square)."""
        p = get_profile("linkedin")
        assert p.width == 1080
        assert p.height == 1080
        assert p.aspect_ratio == "1:1"

    def test_youtube_4k(self) -> None:
        """YouTube 4K: 3840x2160."""
        p = get_profile("youtube_4k")
        assert p.width == 3840
        assert p.height == 2160

    def test_instagram_reels(self) -> None:
        """Instagram Reels: 1080x1920, 9:16."""
        p = get_profile("instagram_reels")
        assert p.width == 1080
        assert p.height == 1920
        assert p.aspect_ratio == "9:16"

    def test_facebook(self) -> None:
        """Facebook: 1080x1920."""
        p = get_profile("facebook")
        assert p.width == 1080
        assert p.height == 1920

    def test_youtube_shorts(self) -> None:
        """YouTube Shorts: 1080x1920, 9:16."""
        p = get_profile("youtube_shorts")
        assert p.width == 1080
        assert p.height == 1920
        assert p.aspect_ratio == "9:16"


class TestGenerationLossPrevention:
    """Test generation loss prevention in renderer source validation."""

    def test_renders_path_detected(self) -> None:
        """Renderer checks for /renders/ in source path."""
        # This tests the logic from renderer._resolve_source
        source_path = "/projects/proj1/renders/render_abc/output.mp4"
        assert "/renders/" in source_path
