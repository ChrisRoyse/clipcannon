"""Scene analysis pipeline stage for automated video editing.

Analyzes extracted frames to detect scene boundaries, face positions,
webcam overlay regions, and content areas. Pre-computes canvas regions
for all layout types so the AI never needs to manually measure coordinates.

Performance optimizations:
- Frames are downsampled to 1280x720 before analysis (7.5x fewer pixels)
- MediaPipe face detector is created once and reused across all scenes
- SSIM comparison uses 320x180 thumbnails
- Face detection runs only on scene representative frames (not every frame)

Runs during ingest after frame_extract.
"""

# Implementation lives in the scene_analysis_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import json  # noqa: F401
import logging
import sqlite3  # noqa: F401
import time  # noqa: F401
from pathlib import Path  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

import cv2  # noqa: F401
import numpy as np  # noqa: F401

from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.pipeline.scene_analysis_boundaries import (  # noqa: F401
    _CREATE_TABLE_SQL,
    _INSERT_SQL,
    AUDIO_SNAP_RADIUS_MS,
    SCENE_THRESHOLD,
    _detect_scene_boundaries,
    _ensure_scene_map_table,
    _fetch_silence_gaps,
    _fetch_word_boundaries,
    _get_transcript_segments,
    _parse_frame_number,
    _snap_boundary_to_audio,
    _store_scene_records,
)
from clipcannon.pipeline.scene_analysis_canvas import (  # noqa: F401
    CANVAS_H,
    CANVAS_W,
    EYE_LINE_PCT,
    LAYOUT_HEIGHTS,
    PIP_POS,
    PIP_SIZE,
    _build_canvas_regions,
    _classify_content_type,
    _compute_speaker_crop,
    _pick_screen_fit_mode,
    _region,
)
from clipcannon.pipeline.scene_analysis_stage import run_scene_analysis  # noqa: F401
from clipcannon.pipeline.scene_analysis_vision import (  # noqa: F401
    ANALYSIS_H,
    ANALYSIS_W,
    CHROME_BOTTOM,
    CHROME_TOP,
    _compute_ssim,
    _create_face_detector,
    _detect_content_region,
    _detect_face_with_detector,
    _detect_webcam_region,
    _downsample,
)
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)
