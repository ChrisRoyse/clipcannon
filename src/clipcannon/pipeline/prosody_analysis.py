"""Prosody analysis pipeline stage for ClipCannon.

Extracts prosodic features (F0 contour, energy, speaking rate, pitch
variation) from the vocal stem per sentence. Stores tagged clips with
their prosody metadata for use as voice cloning references.

Runs after source_separation + transcription. CPU-only (pyworld/numpy).
Each sentence-aligned clip is tagged with energy level, pitch range,
speaking rate, and a composite expressiveness score.

The prosody_segments table enables automatic reference clip selection
during voice synthesis -- pick the clip whose prosody matches the
target style (energetic, calm, emphatic, etc).
"""

# Implementation lives in the prosody_analysis_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import json  # noqa: F401
import logging
import sqlite3  # noqa: F401
import subprocess  # noqa: F401
import time  # noqa: F401
from dataclasses import dataclass  # noqa: F401
from pathlib import Path  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

import numpy as np  # noqa: F401

from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.pipeline.prosody_analysis_stage import (  # noqa: F401
    _CREATE_TABLE_SQL,
    _INSERT_SQL,
    MAX_CLIP_MS,
    MIN_CLIP_MS,
    OPERATION,
    STAGE,
    _ensure_table,
    _get_emotion_for_time,
    _get_transcript_sentences,
    run_prosody_analysis,
)
from clipcannon.pipeline.prosody_features import (  # noqa: F401
    ProsodyFeatures,
    _extract_clip,
    _extract_prosody,
    _load_audio,
)
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)
