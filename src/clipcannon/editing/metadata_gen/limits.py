"""Platform metadata limits, title prefixes and the MetadataResult container."""

from __future__ import annotations

from dataclasses import dataclass, field


# ============================================================
# Platform metadata constraints
# ============================================================
@dataclass(frozen=True)
class PlatformLimits:
    """Character limits and style rules for a target platform."""

    title_max: int | None
    description_max: int
    hashtag_min: int
    hashtag_max: int
    tone: str  # casual, professional, seo


PLATFORM_LIMITS: dict[str, PlatformLimits] = {
    "tiktok": PlatformLimits(
        title_max=None,
        description_max=2200,
        hashtag_min=3,
        hashtag_max=5,
        tone="casual",
    ),
    "instagram_reels": PlatformLimits(
        title_max=None,
        description_max=2200,
        hashtag_min=20,
        hashtag_max=30,
        tone="casual",
    ),
    "youtube_shorts": PlatformLimits(
        title_max=100,
        description_max=5000,
        hashtag_min=3,
        hashtag_max=15,
        tone="seo",
    ),
    "youtube_standard": PlatformLimits(
        title_max=100,
        description_max=5000,
        hashtag_min=3,
        hashtag_max=15,
        tone="seo",
    ),
    "youtube_4k": PlatformLimits(
        title_max=100,
        description_max=5000,
        hashtag_min=3,
        hashtag_max=15,
        tone="seo",
    ),
    "facebook": PlatformLimits(
        title_max=None,
        description_max=63206,
        hashtag_min=0,
        hashtag_max=5,
        tone="casual",
    ),
    "linkedin": PlatformLimits(
        title_max=None,
        description_max=3000,
        hashtag_min=3,
        hashtag_max=5,
        tone="professional",
    ),
}


# Casual prefixes for social platforms
_CASUAL_PREFIXES: list[str] = [
    "Watch this:",
    "You need to see this:",
    "This is incredible:",
    "Check this out:",
    "Don't miss this:",
]


# Professional prefixes for LinkedIn
_PROFESSIONAL_PREFIXES: list[str] = [
    "Key insight:",
    "Here's what matters:",
    "Important takeaway:",
    "Worth considering:",
]


# SEO prefixes for YouTube
_SEO_PREFIXES: list[str] = [
    "",
    "WATCH:",
    "NEW:",
]


# ============================================================
# Result dataclass
# ============================================================
@dataclass
class MetadataResult:
    """Generated metadata for an edit."""

    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)
    thumbnail_timestamp_ms: int | None = None
