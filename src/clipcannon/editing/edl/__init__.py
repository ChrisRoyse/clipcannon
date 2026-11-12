"""Edit Decision List (EDL) models and validation for ClipCannon.

Defines Pydantic models for the complete EDL schema -- segments,
captions, crop, audio, overlays, metadata, and render settings.
Provides validation and duration computation utilities.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from .canvas import CanvasRegion, CanvasSpec, RegionKeyframe
from .literals import (
    CaptionAnimation,
    CaptionPosition,
    CaptionStyle,
    CropMode,
    EditStatus,
    LayoutMode,
    MotionEasing,
    MotionEffect,
    OverlayAnimation,
    OverlayPosition,
    OverlayType,
    RenderQuality,
    TargetPlatform,
    TransitionType,
)
from .model import EditDecisionList
from .segments import (
    CaptionChunk,
    CaptionSpec,
    CaptionWord,
    SegmentCanvasSpec,
    SegmentSpec,
    TrackedFraming,
    TrackedPiece,
    TransitionSpec,
    ZoomSpec,
)
from .specs import (
    AudioSpec,
    ColorSpec,
    CropSpec,
    DuckingSpec,
    MetadataSpec,
    MotionSpec,
    OverlaySpec,
    PipSpec,
    RemovalSpec,
    RenderSettingsSpec,
    SplitScreenSpec,
)
from .validation import compute_total_duration, validate_edl

__all__ = [
    "AudioSpec", "BaseModel", "CanvasRegion", "CanvasSpec", "CaptionAnimation", "CaptionChunk",
    "CaptionPosition", "CaptionSpec", "CaptionStyle", "CaptionWord", "ColorSpec", "CropMode",
    "CropSpec", "DuckingSpec", "EditDecisionList", "EditStatus", "Field", "LayoutMode", "Literal",
    "MetadataSpec", "MotionEasing", "MotionEffect", "MotionSpec", "OverlayAnimation",
    "OverlayPosition", "OverlaySpec", "OverlayType", "PipSpec", "RegionKeyframe", "RemovalSpec",
    "RenderQuality", "RenderSettingsSpec", "SegmentCanvasSpec", "SegmentSpec", "SplitScreenSpec",
    "TYPE_CHECKING", "TargetPlatform", "TrackedFraming", "TrackedPiece", "TransitionSpec",
    "TransitionType", "UTC", "ZoomSpec", "compute_total_duration", "datetime", "field_validator",
    "sqlite3", "validate_edl",
]
