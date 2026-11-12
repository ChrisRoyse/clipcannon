"""Chronemic/pacing computation pipeline stage for ClipCannon.

Computes words-per-minute, pause ratios, speaker change density,
and pacing labels in 60-second sliding windows across the video.
This is an optional stage -- failure does not abort the pipeline.
"""

# Implementation lives in the chronemic_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import asyncio  # noqa: F401
import logging
import time  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.db.queries import batch_insert, fetch_all, fetch_one  # noqa: F401
from clipcannon.pipeline.chronemic_data import (  # noqa: F401
    _get_duration_ms,
    _insert_pacing,
    _load_segments_with_speakers,
    _load_silence_gaps,
    _load_transcript_words,
)
from clipcannon.pipeline.chronemic_math import (  # noqa: F401
    WINDOW_MS,
    _classify_pacing,
    _compute_pacing_windows,
    _compute_pause_ratio,
    _count_speaker_changes,
    _count_words_in_window,
)
from clipcannon.pipeline.chronemic_stage import OPERATION, STAGE, run_chronemic  # noqa: F401
from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)
