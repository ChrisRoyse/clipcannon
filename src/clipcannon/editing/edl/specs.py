"""Layout, audio, overlay, motion, color, removal, metadata and render EDL specs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Runtime imports: pydantic resolves these annotations when building the models.
from .literals import (
    CropMode,  # noqa: TC001
    LayoutMode,  # noqa: TC001
    MotionEasing,  # noqa: TC001
    MotionEffect,  # noqa: TC001
    OverlayAnimation,  # noqa: TC001
    OverlayPosition,  # noqa: TC001
    OverlayType,  # noqa: TC001
    RenderQuality,  # noqa: TC001
)


class SplitScreenSpec(BaseModel):
    """Split-screen layout configuration for vertical video.

    Used when source is a screen recording or tutorial where
    naive center-crop would lose the screen content. Stacks
    the speaker region and screen content region vertically.
    """

    speaker_position: Literal["top", "bottom"] = "top"
    split_ratio: float = Field(
        default=0.35,
        ge=0.15,
        le=0.85,
        description="Speaker region as fraction of output height. "
        "0.35 = 35% speaker, 65% screen content.",
    )
    separator_px: int = Field(default=4, ge=0, le=20)
    separator_color: str = "#FFFFFF"
    speaker_region: dict[str, int] | None = Field(
        default=None,
        description="Manual speaker/webcam region in source frame: "
        "{x, y, width, height}. Auto-detected if None.",
    )
    screen_region: dict[str, int] | None = Field(
        default=None,
        description="Manual screen content region in source frame: "
        "{x, y, width, height}. Auto-detected if None.",
    )


class PipSpec(BaseModel):
    """Picture-in-picture configuration.

    Small speaker overlay on top of full-screen content.
    """

    pip_size: float = Field(
        default=0.25,
        ge=0.1,
        le=0.5,
        description="PIP window as fraction of output width.",
    )
    pip_position: Literal[
        "top_left", "top_right", "bottom_left", "bottom_right"
    ] = "bottom_right"
    pip_margin_px: int = Field(default=20, ge=0, le=100)
    pip_border_px: int = Field(default=3, ge=0, le=10)
    pip_border_color: str = "#FFFFFF"
    pip_corner_radius: int = Field(default=0, ge=0, le=50)


class CropSpec(BaseModel):
    """Crop and reframing configuration."""

    mode: CropMode = "auto"
    aspect_ratio: str = "9:16"
    face_tracking: bool = True
    safe_area_pct: float = Field(default=0.85, ge=0.0, le=1.0)
    layout: LayoutMode = "crop"
    split_screen: SplitScreenSpec = Field(
        default_factory=SplitScreenSpec,
    )
    pip: PipSpec = Field(default_factory=PipSpec)

    @field_validator("aspect_ratio")
    @classmethod
    def valid_aspect_ratio(cls, v: str) -> str:
        """Validate aspect ratio format like '9:16'."""
        parts = v.split(":")
        if len(parts) != 2:
            msg = f"Invalid aspect ratio format: {v!r} (expected 'W:H')"
            raise ValueError(msg)
        try:
            w, h = int(parts[0]), int(parts[1])
        except ValueError as exc:
            msg = f"Aspect ratio components must be integers: {v!r}"
            raise ValueError(msg) from exc
        if w <= 0 or h <= 0:
            msg = f"Aspect ratio components must be positive: {v!r}"
            raise ValueError(msg)
        return v


class DuckingSpec(BaseModel):
    """Audio ducking configuration for speech-aware mixing."""

    enabled: bool = True
    duck_level_db: float = Field(default=-6.0)
    attack_ms: int = Field(default=200, ge=0)
    release_ms: int = Field(default=300, ge=0)


class AudioSpec(BaseModel):
    """Audio mixing configuration."""

    source_audio: bool = True
    source_volume_db: float = Field(default=0.0)
    background_music: str | None = None
    sound_effects: list[dict[str, object]] = Field(default_factory=list)
    ducking: DuckingSpec = Field(default_factory=DuckingSpec)


class OverlaySpec(BaseModel):
    """Visual overlay specification for text, graphics, or images.

    Supports lower thirds (speaker name/title), title cards,
    logos, watermarks, and call-to-action buttons. Each overlay
    has position, timing, styling, and optional animation.
    """

    overlay_type: OverlayType
    text: str = ""
    subtitle: str = ""
    image_path: str | None = None
    position: OverlayPosition = "bottom_left"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    font: str = "Montserrat"
    font_size: int = Field(default=36, ge=8, le=200)
    text_color: str = "#FFFFFF"
    bg_color: str = "#000000"
    bg_opacity: float = Field(default=0.7, ge=0.0, le=1.0)
    animation: OverlayAnimation = "fade_in"
    animation_duration_ms: int = Field(default=500, ge=0, le=3000)

    @field_validator("end_ms")
    @classmethod
    def overlay_end_after_start(cls, v: int, info: object) -> int:
        """Validate end_ms > start_ms for overlay timing."""
        data = getattr(info, "data", {})
        start = data.get("start_ms")
        if start is not None and v <= start:
            msg = f"end_ms ({v}) must be > start_ms ({start})"
            raise ValueError(msg)
        return v


class MotionSpec(BaseModel):
    """Motion/animation effect applied to a segment.

    Generates FFmpeg zoompan filter for smooth camera-like
    movements. Ken Burns combines zoom + pan simultaneously.
    """

    effect: MotionEffect
    start_scale: float = Field(default=1.0, ge=0.5, le=3.0)
    end_scale: float = Field(default=1.3, ge=0.5, le=3.0)
    easing: MotionEasing = "linear"


class ColorSpec(BaseModel):
    """Color grading and visual adjustment specification.

    Applied via FFmpeg eq and hue filters. Can be set globally
    on the EDL or per-segment for targeted color correction.
    """

    brightness: float = Field(default=0.0, ge=-1.0, le=1.0)
    contrast: float = Field(default=1.0, ge=0.0, le=3.0)
    saturation: float = Field(default=1.0, ge=0.0, le=3.0)
    gamma: float = Field(default=1.0, ge=0.1, le=10.0)
    hue_shift: float = Field(default=0.0, ge=-180.0, le=180.0)


class RemovalSpec(BaseModel):
    """A rectangular region to remove/mask from the source video.

    Uses FFmpeg delogo filter to blur the specified region using
    surrounding pixel data. Applied before any crop/scale operations.
    """

    x: int = Field(ge=0, description="Left edge of region to remove (px)")
    y: int = Field(ge=0, description="Top edge of region to remove (px)")
    width: int = Field(ge=1, description="Width of region to remove (px)")
    height: int = Field(ge=1, description="Height of region to remove (px)")
    description: str = Field(
        default="",
        description="What is being removed (e.g., 'browser chrome')",
    )


class MetadataSpec(BaseModel):
    """Platform metadata for the rendered clip."""

    title: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    thumbnail_timestamp_ms: int | None = None


class RenderSettingsSpec(BaseModel):
    """Encoding and quality settings."""

    profile: str = "tiktok_vertical"
    quality: RenderQuality = "high"
    use_nvenc: bool = True
