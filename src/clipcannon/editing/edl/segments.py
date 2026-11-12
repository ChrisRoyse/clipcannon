"""Segment-level EDL models: transitions, zoom, tracking, canvas, captions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Runtime imports: pydantic resolves these annotations when building the models.
from .canvas import CanvasRegion  # noqa: TC001
from .literals import (
    CaptionAnimation,  # noqa: TC001
    CaptionPosition,  # noqa: TC001
    CaptionStyle,  # noqa: TC001
    TransitionType,  # noqa: TC001
)
from .specs import ColorSpec, MotionSpec  # noqa: TC001


# ============================================================
# SUB-MODELS
# ============================================================
class TransitionSpec(BaseModel):
    """Transition effect between segments."""

    type: TransitionType
    duration_ms: int = Field(ge=100, le=2000)


class ZoomSpec(BaseModel):
    """Animated zoom/crop specification for a segment.

    Interpolates from a wide crop to a tight crop (or vice versa)
    over the segment duration. Uses FFmpeg time-varying crop
    expressions. After setpts=PTS-STARTPTS, the t variable resets
    to 0 per segment, making expressions self-contained.
    """

    start_x: int = Field(ge=0, description="Starting crop X position")
    start_y: int = Field(ge=0, description="Starting crop Y position")
    start_w: int = Field(ge=1, description="Starting crop width")
    start_h: int = Field(ge=1, description="Starting crop height")

    end_x: int = Field(ge=0, description="Ending crop X position (zoom target)")
    end_y: int = Field(ge=0, description="Ending crop Y position (zoom target)")
    end_w: int = Field(ge=1, description="Ending crop width (zoom target)")
    end_h: int = Field(ge=1, description="Ending crop height (zoom target)")

    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out"] = "ease_in_out"


class TrackedPiece(BaseModel):
    """One shot's worth of tracked framing: fixed window, moving position.

    ``keyframes`` are (source_ms, x, y) of the window's top-left corner;
    positions between keyframes are linearly interpolated.
    """

    start_ms: int = Field(ge=0, description="Source start (ms)")
    end_ms: int = Field(ge=0, description="Source end (ms)")
    width: int = Field(ge=2, description="Crop window width (source px)")
    height: int = Field(ge=2, description="Crop window height (source px)")
    keyframes: list[tuple[int, int, int]] = Field(min_length=1)


class TrackedFraming(BaseModel):
    """Speaker-following framing for a segment, one piece per shot."""

    pieces: list[TrackedPiece] = Field(min_length=1)
    speakers: list[str] = Field(
        default_factory=list, description="Person keys framed while speaking (audit)",
    )


class SegmentCanvasSpec(BaseModel):
    """Per-segment canvas override.

    When attached to a SegmentSpec, replaces the top-level canvas
    for that segment only. Enables the AI to use different visual
    layouts at different timestamps within a single clip.

    Use regions[] for multi-region compositing (speaker + screen).
    Use zoom for animated crop (zoom into a UI element).
    Regions and zoom are mutually exclusive.
    """

    regions: list[CanvasRegion] = Field(
        default_factory=list,
        description="Regions to composite for this segment.",
    )
    background_color: str = Field(
        default="#000000",
        description="Canvas background for this segment.",
    )
    zoom: ZoomSpec | None = Field(
        default=None,
        description="Animated zoom for this segment. "
        "Mutually exclusive with regions[].",
    )
    track: TrackedFraming | None = Field(
        default=None,
        description="Speaker-following framing (computed from speaker tracking). "
        "Mutually exclusive with regions[] and zoom.",
    )


class SegmentSpec(BaseModel):
    """A contiguous time range extracted from the source video."""

    segment_id: int = Field(ge=1)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(ge=0)
    output_start_ms: int = Field(ge=0)
    speed: float = Field(ge=0.25, le=4.0, default=1.0)
    transition_in: TransitionSpec | None = None
    transition_out: TransitionSpec | None = None

    canvas: SegmentCanvasSpec | None = Field(
        default=None,
        description="Per-segment canvas override. When set, replaces "
        "the top-level CanvasSpec for this segment only. "
        "Enables different layouts per segment.",
    )
    motion: MotionSpec | None = Field(
        default=None,
        description="Motion effect (zoom, pan, ken burns) for this segment.",
    )
    color: ColorSpec | None = Field(
        default=None,
        description="Per-segment color grading override.",
    )

    @field_validator("source_end_ms")
    @classmethod
    def end_after_start(cls, v: int, info: object) -> int:
        """Validate source_end_ms > source_start_ms."""
        data = getattr(info, "data", {})
        start = data.get("source_start_ms")
        if start is not None and v <= start:
            msg = f"source_end_ms ({v}) must be > source_start_ms ({start})"
            raise ValueError(msg)
        return v

    @property
    def source_duration_ms(self) -> int:
        """Duration in the source timeline."""
        return self.source_end_ms - self.source_start_ms

    @property
    def output_duration_ms(self) -> int:
        """Effective duration in the output timeline.

        Uses round() to avoid cumulative truncation drift when
        speed != 1.0.  See: int(1000/1.3)=769 vs round(1000/1.3)=769
        — the difference is sub-ms per segment but compounds across
        many segments to produce visible caption desync.
        """
        return round(self.source_duration_ms / self.speed)


class CaptionWord(BaseModel):
    """A single word with timestamp from transcript_words."""

    word: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class CaptionChunk(BaseModel):
    """A group of words displayed together as one caption frame."""

    chunk_id: int = Field(ge=1)
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    words: list[CaptionWord] = Field(default_factory=list)


class CaptionSpec(BaseModel):
    """Caption configuration for the EDL."""

    enabled: bool = True
    style: CaptionStyle = "bold_centered"
    font: str = "Montserrat-Bold"
    font_size: int = Field(default=48, ge=8, le=200)
    color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = Field(default=3, ge=0, le=20)
    # "bottom" = the safe zone above platform UI on vertical video (see
    # caption_render._position_fields); matches the long-standing look.
    position: CaptionPosition = "bottom"
    animation: CaptionAnimation = "word_by_word"
    chunks: list[CaptionChunk] = Field(default_factory=list)
