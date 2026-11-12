#!/usr/bin/env python3
"""Label training clips with full teleological constellation coordinates.

Uses the precomputed face landmarks file (from precompute_face_landmarks.py)
as the SINGLE SOURCE OF TRUTH for face positions and mouth bboxes. No more
scene_map interpolation, no more geometric mouth bbox derivation.

For each word in the transcript, creates a 2-second clip (49 frames at 25fps)
centered on that word, with labels for:
  - Linguistic: words, phonemes, visemes per frame
  - Face geometry per frame (from YOLOv5-Face landmarks)
  - Mouth bbox per frame (from actual mouth corners)
  - Prosody: f0, energy, speaking rate
  - Emotion: arousal, valence
  - Category: speaking/breathing/emotional

Usage:
    # First run precompute_face_landmarks.py to generate landmarks file
    python scripts/label_training_clips.py
"""
# Implementation lives in the sibling package scripts/clip_labeling/ (split for the
# 500-line file limit). This file is the unchanged entry point and re-exports every
# top-level name of the original script.
import json
import logging
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from clip_labeling.build import build_labels
from clip_labeling.schema import (
    ALL_VISEMES,
    CLIP_DURATION_MS,
    CLIP_FRAMES,
    DB_PATH,
    LANDMARKS_FILE,
    OUTPUT_DIR,
    OUTPUT_LABELS,
    PHONEME_TO_VISEME,
    PROJECT_ID,
    SOURCE_VIDEO,
    SRC_HEIGHT,
    SRC_WIDTH,
    TARGET_FPS,
    VOCALS_WAV,
    TeleologicalLabel,
)
from clip_labeling.sources import (
    build_frame_viseme_sequence,
    get_emotion_for_range,
    get_landmarks_for_frame,
    get_prosody_for_range,
    is_in_long_silence,
    load_analysis_data,
    load_cmu_dict,
    load_precomputed_landmarks,
    word_to_visemes,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("label")

__all__ = [
    "json", "logging", "os", "sqlite3", "sys", "dataclass", "field", "asdict", "Path",
    "Optional", "np", "log", "PROJECT_ID", "DB_PATH", "SOURCE_VIDEO", "VOCALS_WAV",
    "LANDMARKS_FILE", "OUTPUT_DIR", "OUTPUT_LABELS", "CLIP_FRAMES", "TARGET_FPS",
    "CLIP_DURATION_MS", "SRC_WIDTH", "SRC_HEIGHT", "TeleologicalLabel", "PHONEME_TO_VISEME",
    "ALL_VISEMES", "load_cmu_dict", "word_to_visemes", "build_frame_viseme_sequence",
    "load_precomputed_landmarks", "get_landmarks_for_frame", "load_analysis_data",
    "get_prosody_for_range", "get_emotion_for_range", "is_in_long_silence", "build_labels",
]


if __name__ == "__main__":
    build_labels()
