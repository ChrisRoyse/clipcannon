"""Editing package for ClipCannon Phase 2.

Provides EDL format models, caption generation, smart cropping,
and change impact classification for the video editing and
rendering pipeline.
"""

from clipcannon.editing.captions import (
    chunk_transcript_words,
    fetch_words_for_segments,
    generate_ass_file,
    generate_drawtext_filters,
    remap_timestamps,
)
from clipcannon.editing.change_classifier import (
    RenderHint,
    classify_changes,
)
from clipcannon.editing.edl import (
    AudioSpec,
    CaptionSpec,
    ColorSpec,
    CropSpec,
    EditDecisionList,
    MotionSpec,
    OverlaySpec,
    SegmentSpec,
    compute_total_duration,
    validate_edl,
)
from clipcannon.editing.smart_crop import (
    PLATFORM_ASPECTS,
    compute_crop_region,
    detect_faces,
    get_crop_for_scene,
    smooth_crop_positions,
)

__all__ = [
    "AudioSpec",
    "CaptionSpec",
    "ColorSpec",
    "CropSpec",
    "EditDecisionList",
    "MotionSpec",
    "OverlaySpec",
    "PLATFORM_ASPECTS",
    "RenderHint",
    "SegmentSpec",
    "chunk_transcript_words",
    "classify_changes",
    "compute_crop_region",
    "compute_total_duration",
    "detect_faces",
    "fetch_words_for_segments",
    "generate_ass_file",
    "generate_drawtext_filters",
    "get_crop_for_scene",
    "remap_timestamps",
    "smooth_crop_positions",
    "validate_edl",
]
