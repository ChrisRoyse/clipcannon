"""Top-level EditDecisionList model."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .canvas import CanvasSpec
from .literals import EditStatus, TargetPlatform  # noqa: TC001 - pydantic resolves at runtime
from .segments import CaptionSpec, SegmentSpec
from .specs import (
    AudioSpec,
    ColorSpec,
    CropSpec,
    MetadataSpec,
    OverlaySpec,
    RemovalSpec,
    RenderSettingsSpec,
)


# ============================================================
# TOP-LEVEL EDL MODEL
# ============================================================
class EditDecisionList(BaseModel):
    """Complete Edit Decision List describing one output clip.

    The EDL is declarative: it describes what the output should look
    like. The rendering engine translates it into FFmpeg commands.
    """

    edit_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    status: EditStatus = "draft"
    source_sha256: str = ""

    target_platform: TargetPlatform
    target_profile: str = ""

    segments: list[SegmentSpec] = Field(min_length=1)
    captions: CaptionSpec = Field(default_factory=CaptionSpec)
    crop: CropSpec = Field(default_factory=CropSpec)
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    audio: AudioSpec = Field(default_factory=AudioSpec)
    color: ColorSpec | None = Field(
        default=None,
        description="Global color grading applied to entire edit.",
    )
    removals: list[RemovalSpec] = Field(
        default_factory=list,
        description="Regions to remove from source (delogo filter).",
    )
    overlays: list[OverlaySpec] = Field(
        default_factory=list,
        description="Visual overlays (lower thirds, titles, logos).",
    )
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)
    render_settings: RenderSettingsSpec = Field(
        default_factory=RenderSettingsSpec,
    )
