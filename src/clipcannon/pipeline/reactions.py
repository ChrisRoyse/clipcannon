"""SenseVoice reaction detection pipeline stage for ClipCannon.

Detects audience reactions (laughter, applause) in audio using the
SenseVoice model. Falls back to energy-based detection if unavailable.
"""

# Implementation lives in the reactions_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
import logging
import time  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

import numpy as np  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.db.queries import batch_insert, fetch_all  # noqa: F401
from clipcannon.exceptions import PipelineError  # noqa: F401
from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.pipeline.reactions_detect import (  # noqa: F401
    ENERGY_REACTION_THRESHOLD,
    OPERATION,
    STAGE,
    STRIDE_S,
    TARGET_SR,
    WINDOW_S,
    _check_sensevoice_funasr,
    _detect_reactions_energy,
    _detect_reactions_funasr,
    _load_audio,
)
from clipcannon.pipeline.reactions_stage import (  # noqa: F401
    _attach_context_transcripts,
    _insert_reactions,
    _merge_overlapping_reactions,
    run_reactions,
)
from clipcannon.pipeline.source_resolution import resolve_audio_input  # noqa: F401
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
    sha256_string,
)

logger = logging.getLogger(__name__)
