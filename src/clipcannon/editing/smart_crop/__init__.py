"""Smart cropping and layout for ClipCannon EDL rendering.

Supports three layout modes for vertical video:
- crop: Single face-centered crop (default). Good for talking-head.
- split_screen: Speaker top + screen content bottom. For tutorials,
  screen shares, demos where center-crop loses the screen content.
- pip: Picture-in-picture. Small speaker overlay on full screen.

Uses face detection to anchor the crop window on the primary
speaker when converting landscape (16:9) source video to vertical
(9:16) or square (1:1) target aspect ratios.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .crop import (
    PLATFORM_ASPECTS,
    CropRegion,
    compute_crop_region,
    get_crop_for_scene,
    parse_aspect_ratio,
    smooth_crop_positions,
)
from .faces import (
    _FACE_MODEL_PATH,
    FaceDetection,
    _detect_faces_insightface,
    _detect_faces_mediapipe,
    _parse_mediapipe_detections,
    detect_faces,
    logger,
)
from .pip import PipLayout, compute_pip_layout
from .split_screen import (
    SplitScreenLayout,
    compute_screen_region,
    compute_split_screen_layout,
    detect_speaker_region,
)

__all__: list[str] = [
    "Any", "CropRegion", "FaceDetection", "PLATFORM_ASPECTS", "Path", "PipLayout",
    "SplitScreenLayout", "_FACE_MODEL_PATH", "_detect_faces_insightface",
    "_detect_faces_mediapipe", "_parse_mediapipe_detections", "compute_crop_region",
    "compute_pip_layout", "compute_screen_region", "compute_split_screen_layout", "dataclass",
    "detect_faces", "detect_speaker_region", "get_crop_for_scene", "logger", "logging",
    "parse_aspect_ratio", "smooth_crop_positions",
]
