"""SigLIP visual embedding and scene detection pipeline stage.

Loads the SigLIP-SO400M model to compute 1152-dim visual embeddings
for all extracted frames, then detects scene boundaries by measuring
cosine similarity between consecutive frame embeddings.

Scenes are defined by boundaries where similarity drops below
SCENE_THRESHOLD (0.85). Each scene records its key frame, average
visual similarity, and dominant colors. Scenes longer than
MAX_SCENE_DURATION_MS (30 s) are force-split to avoid very long
monotonic stretches in screen recordings.
"""

# Implementation lives in the visual_embed_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
import logging
import os  # noqa: F401
import struct  # noqa: F401
import time  # noqa: F401
from collections import Counter  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.db.queries import batch_insert  # noqa: F401
from clipcannon.exceptions import PipelineError  # noqa: F401
from clipcannon.pipeline.frame_utils import frame_timestamp_ms  # noqa: F401
from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.pipeline.visual_embed_model import _run_embedding_pipeline  # noqa: F401
from clipcannon.pipeline.visual_embed_scenes import (  # noqa: F401
    BATCH_SIZE,
    EMBEDDING_DIM,
    FRAME_RESIZE,
    MAX_SCENE_DURATION_MS,
    OPERATION,
    SCENE_THRESHOLD,
    SIGLIP_MODEL_ID,
    STAGE,
    _cosine_similarity,
    _detect_scenes,
    _extract_dominant_colors,
    _get_sorted_frames,
    _serialize_embedding,
)
from clipcannon.pipeline.visual_embed_stage import run_visual_embed  # noqa: F401
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)
