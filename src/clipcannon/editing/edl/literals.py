"""Literal type aliases used by the EDL models."""

from __future__ import annotations

from typing import Literal

# Valid transition type literals
TransitionType = Literal[
    "fade",
    "crossfade",
    "wipe_left",
    "wipe_right",
    "wipe_up",
    "wipe_down",
    "slide_left",
    "slide_right",
    "dissolve",
    "zoom_in",
    "cut",
]


# Valid status literals
EditStatus = Literal[
    "draft",
    "rendering",
    "rendered",
    "approved",
    "rejected",
    "failed",
]


# Valid platform literals
TargetPlatform = Literal[
    "tiktok",
    "instagram_reels",
    "youtube_shorts",
    "youtube_standard",
    "youtube_4k",
    "facebook",
    "linkedin",
]


# Caption style literals
CaptionStyle = Literal[
    "bold_centered",
    "word_highlight",
    "subtitle_bar",
    "karaoke",
]


# Caption position literals
CaptionPosition = Literal["center", "bottom", "top"]


# Caption animation literals
CaptionAnimation = Literal["word_by_word", "fade", "none"]


# Crop mode literals
CropMode = Literal["auto", "manual", "none"]


# Layout mode literals for vertical video
LayoutMode = Literal[
    "crop",           # Single face-centered crop (default, existing behavior)
    "split_screen",   # Speaker top + screen content bottom (or configurable)
    "pip",            # Picture-in-picture: small speaker over full screen
]


# Render quality literals
RenderQuality = Literal["low", "medium", "high"]


# Overlay type literals
OverlayType = Literal[
    "lower_third",
    "title_card",
    "logo",
    "watermark",
    "cta",
]


# Overlay position literals
OverlayPosition = Literal[
    "bottom_left",
    "bottom_center",
    "bottom_right",
    "top_left",
    "top_center",
    "top_right",
    "center",
]


# Overlay animation literals
OverlayAnimation = Literal[
    "none",
    "fade_in",
    "fade_out",
    "slide_up",
    "slide_down",
]


# Motion effect type literals
MotionEffect = Literal[
    "zoom_in",
    "zoom_out",
    "pan_left",
    "pan_right",
    "pan_up",
    "pan_down",
    "ken_burns",
]


# Motion easing literals
MotionEasing = Literal["linear", "ease_in", "ease_out", "ease_in_out"]
