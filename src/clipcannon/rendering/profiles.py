"""Platform encoding profiles for ClipCannon rendering.

Defines FFmpeg encoding parameters for each supported platform.
Each profile specifies resolution, codec, bitrate, and audio settings.
Provides lookup and software fallback utilities.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from clipcannon.exceptions import PipelineError


@dataclass
class EncodingProfile:
    """FFmpeg encoding parameters for a target platform.

    Attributes:
        name: Profile identifier (e.g. "tiktok_vertical").
        width: Output video width in pixels.
        height: Output video height in pixels.
        aspect_ratio: Display aspect ratio string (e.g. "9:16").
        fps: Output frame rate.
        video_codec: FFmpeg video codec name.
        video_bitrate: Target video bitrate (e.g. "8M").
        max_bitrate: Maximum video bitrate for VBV.
        bufsize: VBV buffer size.
        audio_codec: FFmpeg audio codec name.
        audio_bitrate: Audio bitrate (e.g. "192k").
        audio_sample_rate: Audio sample rate in Hz.
        movflags: FFmpeg movflags for MP4 output.
    """

    name: str
    width: int
    height: int
    aspect_ratio: str
    fps: int
    video_codec: str
    video_bitrate: str
    max_bitrate: str
    bufsize: str
    audio_codec: str
    audio_bitrate: str
    audio_sample_rate: int
    movflags: str


# ============================================================
# PROFILE REGISTRY
# ============================================================
_PROFILES: dict[str, EncodingProfile] = {
    "tiktok_vertical": EncodingProfile(
        name="tiktok_vertical",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        fps=30,
        video_codec="h264_nvenc",
        video_bitrate="8M",
        max_bitrate="10M",
        bufsize="20M",
        audio_codec="aac",
        audio_bitrate="192k",
        audio_sample_rate=44100,
        movflags="+faststart",
    ),
    "instagram_reels": EncodingProfile(
        name="instagram_reels",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        fps=30,
        video_codec="h264_nvenc",
        video_bitrate="6M",
        max_bitrate="8M",
        bufsize="16M",
        audio_codec="aac",
        audio_bitrate="192k",
        audio_sample_rate=44100,
        movflags="+faststart",
    ),
    "youtube_shorts": EncodingProfile(
        name="youtube_shorts",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        fps=30,
        video_codec="h264_nvenc",
        video_bitrate="8M",
        max_bitrate="10M",
        bufsize="20M",
        audio_codec="aac",
        audio_bitrate="192k",
        audio_sample_rate=48000,
        movflags="+faststart",
    ),
    "youtube_standard": EncodingProfile(
        name="youtube_standard",
        width=1920,
        height=1080,
        aspect_ratio="16:9",
        fps=30,
        video_codec="h264_nvenc",
        video_bitrate="12M",
        max_bitrate="15M",
        bufsize="30M",
        audio_codec="aac",
        audio_bitrate="192k",
        audio_sample_rate=48000,
        movflags="+faststart",
    ),
    "youtube_4k": EncodingProfile(
        name="youtube_4k",
        width=3840,
        height=2160,
        aspect_ratio="16:9",
        fps=30,
        video_codec="h264_nvenc",
        video_bitrate="40M",
        max_bitrate="50M",
        bufsize="80M",
        audio_codec="aac",
        audio_bitrate="192k",
        audio_sample_rate=48000,
        movflags="+faststart",
    ),
    "facebook": EncodingProfile(
        name="facebook",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        fps=30,
        video_codec="h264_nvenc",
        video_bitrate="6M",
        max_bitrate="8M",
        bufsize="16M",
        audio_codec="aac",
        audio_bitrate="192k",
        audio_sample_rate=44100,
        movflags="+faststart",
    ),
    "linkedin": EncodingProfile(
        name="linkedin",
        width=1080,
        height=1080,
        aspect_ratio="1:1",
        fps=30,
        video_codec="h264_nvenc",
        video_bitrate="5M",
        max_bitrate="7M",
        bufsize="14M",
        audio_codec="aac",
        audio_bitrate="192k",
        audio_sample_rate=44100,
        movflags="+faststart",
    ),
}


def get_profile(name: str) -> EncodingProfile:
    """Look up an encoding profile by name.

    Args:
        name: Profile name (e.g. "tiktok_vertical").

    Returns:
        The matching EncodingProfile.

    Raises:
        PipelineError: If the profile name is not recognized.
    """
    profile = _PROFILES.get(name)
    if profile is None:
        raise PipelineError(
            f"Unknown encoding profile: {name!r}. "
            f"Valid profiles: {', '.join(sorted(_PROFILES))}",
            stage_name="rendering",
            operation="profile_lookup",
        )
    return profile


def list_profiles() -> list[str]:
    """Return sorted list of available profile names.

    Returns:
        Sorted list of profile name strings.
    """
    return sorted(_PROFILES.keys())


def get_software_fallback(profile: EncodingProfile) -> EncodingProfile:
    """Return a copy of the profile using software encoding.

    Replaces h264_nvenc with libx264 and hevc_nvenc with libx265
    for systems without NVIDIA GPU hardware encoding support.

    Args:
        profile: The hardware-accelerated profile to convert.

    Returns:
        New EncodingProfile with software codec substituted.
    """
    codec_map: dict[str, str] = {
        "h264_nvenc": "libx264",
        "hevc_nvenc": "libx265",
        "av1_nvenc": "libsvtav1",
    }
    sw_codec = codec_map.get(profile.video_codec, profile.video_codec)

    return replace(profile, video_codec=sw_codec)
