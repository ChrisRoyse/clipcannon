"""Canvas compositing EDL models: keyframes, regions, canvas spec."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ============================================================
# COMPOSITING MODEL -- Full AI creative control
# ============================================================


class RegionKeyframe(BaseModel):
    """A keyframe for animating a region's position/size over time.

    The AI can define multiple keyframes to animate a region across
    the output canvas (e.g., move speaker from top to bottom, or
    scale screen content larger as the speaker gestures to it).
    """

    time_ms: int = Field(ge=0, description="Time in the output timeline")
    x: int = Field(description="X position on output canvas (px)")
    y: int = Field(description="Y position on output canvas (px)")
    width: int = Field(ge=1, description="Display width on canvas (px)")
    height: int = Field(ge=1, description="Display height on canvas (px)")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    easing: str = Field(
        default="linear",
        description="Easing: linear, ease_in, ease_out, ease_in_out",
    )


class CanvasRegion(BaseModel):
    """A region extracted from the source and placed on the output canvas.

    This is the core compositing primitive. The AI extracts any
    rectangular region from the source frame, scales it, and places
    it at any position on the output canvas. Multiple regions are
    layered by z_index.

    The AI has FULL control: it specifies exact pixel coordinates
    for both source extraction and output placement.
    """

    region_id: str = Field(
        min_length=1,
        description="Unique identifier for this region (e.g., 'speaker', 'screen', 'webcam')",
    )

    # SOURCE: what to extract from the source frame
    source_x: int = Field(ge=0, description="Left edge in source frame (px)")
    source_y: int = Field(ge=0, description="Top edge in source frame (px)")
    source_width: int = Field(ge=1, description="Width to extract from source (px)")
    source_height: int = Field(ge=1, description="Height to extract from source (px)")

    # OUTPUT: where to place on the canvas
    output_x: int = Field(description="X position on output canvas (px)")
    output_y: int = Field(description="Y position on output canvas (px)")
    output_width: int = Field(ge=1, description="Display width on canvas (px)")
    output_height: int = Field(ge=1, description="Display height on canvas (px)")

    # LAYERING
    z_index: int = Field(
        default=0,
        description="Layer order. Higher z_index = rendered on top.",
    )
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)

    # SCALING
    fit_mode: Literal["stretch", "contain", "cover"] = Field(
        default="cover",
        description=(
            "How to scale the source into the output dimensions. "
            "'stretch' = force exact dimensions (may distort). "
            "'contain' = fit inside output, pad with background (no crop, no distort). "
            "'cover' = fill output completely, crop excess (no distort, no padding)."
        ),
    )

    # STYLING
    border_px: int = Field(default=0, ge=0, le=20)
    border_color: str = "#FFFFFF"
    corner_radius: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Rounded corner radius in px. 0 = square.",
    )
    background_color: str | None = Field(
        default=None,
        description="Fill color behind the region (for padding). None = transparent.",
    )

    # ANIMATION: optional keyframes for position/size over time
    keyframes: list[RegionKeyframe] = Field(
        default_factory=list,
        description="If provided, the region animates between keyframes. "
        "Empty = static position.",
    )


class CanvasSpec(BaseModel):
    """Full compositing canvas specification.

    The AI defines the output canvas size and places multiple
    regions from the source video anywhere on it. This gives
    the AI complete creative control over the visual layout.

    Example: For a tutorial with speaker + screen content:
    - Region 'speaker': source(1600,840,320,240) -> output(0,0,1080,672)
    - Region 'screen': source(0,0,1600,1080) -> output(0,676,1080,1244)

    Example: For a reaction-style layout:
    - Region 'main_content': source(0,0,1920,1080) -> output(0,0,1080,960)
    - Region 'reactor': source(1500,800,420,280) -> output(700,680,350,280)

    The AI is NOT limited to presets. It can position regions
    anywhere with any size, creating any layout it can imagine.
    """

    enabled: bool = Field(
        default=False,
        description="When True, regions[] defines the layout. "
        "CropSpec is ignored.",
    )
    canvas_width: int = Field(default=1080, ge=1)
    canvas_height: int = Field(default=1920, ge=1)
    background_color: str = Field(
        default="#000000",
        description="Canvas background color (visible where no regions cover).",
    )
    regions: list[CanvasRegion] = Field(
        default_factory=list,
        description="Regions to composite. Layered by z_index.",
    )
