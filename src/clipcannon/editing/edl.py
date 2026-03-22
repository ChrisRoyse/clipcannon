"""Edit Decision List (EDL) models and validation for ClipCannon.

Defines Pydantic models for the complete EDL schema -- segments,
captions, crop, audio, overlays, metadata, and render settings.
Provides validation and duration computation utilities.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ============================================================
# Platform duration limits (min_s, max_s)
# ============================================================
PLATFORM_DURATION_LIMITS: dict[str, tuple[int, int]] = {
    "tiktok": (5, 180),
    "instagram_reels": (5, 90),
    "youtube_shorts": (5, 180),
    "youtube_standard": (30, 600),
    "youtube_4k": (30, 600),
    "facebook": (5, 90),
    "linkedin": (10, 600),
}

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


# ============================================================
# SUB-MODELS
# ============================================================
class TransitionSpec(BaseModel):
    """Transition effect between segments."""

    type: TransitionType
    duration_ms: int = Field(ge=100, le=2000)


class SegmentSpec(BaseModel):
    """A contiguous time range extracted from the source video."""

    segment_id: int = Field(ge=1)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(ge=0)
    output_start_ms: int = Field(ge=0)
    speed: float = Field(ge=0.25, le=4.0, default=1.0)
    transition_in: TransitionSpec | None = None
    transition_out: TransitionSpec | None = None

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
        """Effective duration in the output timeline."""
        return int(self.source_duration_ms / self.speed)


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
    position: CaptionPosition = "center"
    animation: CaptionAnimation = "word_by_word"
    chunks: list[CaptionChunk] = Field(default_factory=list)


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
    """Visual overlay configuration (placeholder for Phase 3)."""

    lower_third: dict[str, object] | None = None
    title_card: dict[str, object] | None = None
    animations: list[dict[str, object]] = Field(default_factory=list)
    watermark: dict[str, object] | None = None


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
    overlays: OverlaySpec = Field(default_factory=OverlaySpec)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)
    render_settings: RenderSettingsSpec = Field(
        default_factory=RenderSettingsSpec,
    )


# ============================================================
# VALIDATION
# ============================================================
def validate_edl(
    edl: EditDecisionList,
    project_db_path: Path,
) -> list[str]:
    """Validate an EDL against project data and platform constraints.

    Checks source hash, segment ordering, overlap, transition limits,
    speed range, and platform duration limits.

    Args:
        edl: The EditDecisionList to validate.
        project_db_path: Path to the project SQLite database.

    Returns:
        List of validation error strings. Empty means valid.
    """
    errors: list[str] = []

    # --- Source hash validation ---
    try:
        conn = sqlite3.connect(str(project_db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT source_sha256, duration_ms FROM project "
                "WHERE project_id = ?",
                (edl.project_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            errors.append(
                f"Project {edl.project_id!r} not found in database"
            )
            return errors

        db_sha256 = str(row["source_sha256"])
        source_duration_ms = int(row["duration_ms"])

        if edl.source_sha256 and edl.source_sha256 != db_sha256:
            errors.append(
                f"source_sha256 mismatch: EDL has {edl.source_sha256!r}, "
                f"DB has {db_sha256!r}"
            )
    except sqlite3.Error as exc:
        errors.append(f"Database error during validation: {exc}")
        return errors

    # --- Segment validation ---
    segments = edl.segments
    if not segments:
        errors.append("EDL must have at least one segment")
        return errors

    for seg in segments:
        # Time range within source bounds
        if seg.source_start_ms < 0:
            errors.append(
                f"Segment {seg.segment_id}: source_start_ms < 0"
            )
        if seg.source_end_ms > source_duration_ms:
            errors.append(
                f"Segment {seg.segment_id}: source_end_ms "
                f"({seg.source_end_ms}) > source duration "
                f"({source_duration_ms})"
            )
        if seg.source_end_ms <= seg.source_start_ms:
            errors.append(
                f"Segment {seg.segment_id}: source_end_ms must be > "
                f"source_start_ms"
            )

        # Minimum segment duration (500ms before speed)
        if seg.source_duration_ms < 500:
            errors.append(
                f"Segment {seg.segment_id}: source duration "
                f"({seg.source_duration_ms}ms) < minimum 500ms"
            )

        # Speed range
        if not (0.25 <= seg.speed <= 4.0):
            errors.append(
                f"Segment {seg.segment_id}: speed {seg.speed} "
                f"outside [0.25, 4.0]"
            )

    # --- Segment ordering ---
    for i in range(1, len(segments)):
        if segments[i].output_start_ms < segments[i - 1].output_start_ms:
            errors.append(
                f"Segments not ordered by output_start_ms: "
                f"segment {segments[i].segment_id} at "
                f"{segments[i].output_start_ms} < segment "
                f"{segments[i - 1].segment_id} at "
                f"{segments[i - 1].output_start_ms}"
            )

    # --- Overlap detection (accounting for transitions) ---
    for i in range(1, len(segments)):
        prev = segments[i - 1]
        curr = segments[i]
        prev_end = prev.output_start_ms + prev.output_duration_ms

        # Allow transition overlap
        overlap_allowance = 0
        if prev.transition_out:
            overlap_allowance += prev.transition_out.duration_ms
        if curr.transition_in:
            overlap_allowance += curr.transition_in.duration_ms

        if curr.output_start_ms < prev_end - overlap_allowance:
            errors.append(
                f"Segments {prev.segment_id} and {curr.segment_id} "
                f"overlap in output timeline beyond transition allowance"
            )

    # --- Transition duration constraints ---
    for i, seg in enumerate(segments):
        seg_dur = seg.output_duration_ms

        if (
            seg.transition_in
            and seg.transition_in.type != "cut"
            and i > 0
        ):
            prev_dur = segments[i - 1].output_duration_ms
            shorter = min(seg_dur, prev_dur)
            if seg.transition_in.duration_ms > shorter * 0.5:
                errors.append(
                    f"Segment {seg.segment_id}: transition_in "
                    f"duration ({seg.transition_in.duration_ms}ms) "
                    f"exceeds 50% of shorter adjacent segment "
                    f"({shorter}ms)"
                )

        if (
            seg.transition_out
            and seg.transition_out.type != "cut"
            and i < len(segments) - 1
        ):
            next_dur = segments[i + 1].output_duration_ms
            shorter = min(seg_dur, next_dur)
            if seg.transition_out.duration_ms > shorter * 0.5:
                errors.append(
                    f"Segment {seg.segment_id}: transition_out "
                    f"duration ({seg.transition_out.duration_ms}ms) "
                    f"exceeds 50% of shorter adjacent segment "
                    f"({shorter}ms)"
                )

    # --- Platform duration limits ---
    total_ms = compute_total_duration(segments)
    limits = PLATFORM_DURATION_LIMITS.get(edl.target_platform)
    if limits:
        min_s, max_s = limits
        total_s = total_ms / 1000.0
        if total_s < min_s:
            errors.append(
                f"Total output duration ({total_s:.1f}s) below platform "
                f"minimum ({min_s}s) for {edl.target_platform}"
            )
        if total_s > max_s:
            errors.append(
                f"Total output duration ({total_s:.1f}s) exceeds platform "
                f"maximum ({max_s}s) for {edl.target_platform}"
            )

    return errors


# ============================================================
# DURATION COMPUTATION
# ============================================================
def compute_total_duration(segments: list[SegmentSpec]) -> int:
    """Calculate total output duration in milliseconds.

    Accounts for speed adjustments and transition overlaps between
    adjacent segments.

    Args:
        segments: Ordered list of EDL segments.

    Returns:
        Total output duration in milliseconds.
    """
    if not segments:
        return 0

    # Find the maximum extent of the output timeline
    max_end = 0
    for seg in segments:
        seg_end = seg.output_start_ms + seg.output_duration_ms
        if seg_end > max_end:
            max_end = seg_end

    return max_end
