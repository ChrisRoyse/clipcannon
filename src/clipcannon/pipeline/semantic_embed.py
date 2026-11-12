"""Nomic semantic embedding and topic clustering pipeline stage.

Runs nomic-ai/nomic-embed-text-v1.5 through the pinned native port
(``nomic_native``, no remote code, independent of the transformers version) to compute
768-dim semantic embeddings for each transcript segment, then clusters
segments into topics using agglomerative clustering with TF-IDF-based
topic label generation.
"""

# Implementation lives in the semantic_embed_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
import logging
import struct  # noqa: F401
import time  # noqa: F401
from collections import Counter  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

import numpy as np  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.db.queries import batch_insert, execute, fetch_all  # noqa: F401
from clipcannon.exceptions import PipelineError  # noqa: F401
from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.pipeline.semantic_embed_stage import run_semantic_embed  # noqa: F401
from clipcannon.pipeline.semantic_embed_store import (  # noqa: F401
    EMBEDDING_DIM,
    MODEL_ID,
    OPERATION,
    SEARCH_PREFIX,
    STAGE,
    _compute_embeddings,
    _insert_results,
    _load_segments_from_db,
    _pack_embedding,
)
from clipcannon.pipeline.semantic_embed_topics import (  # noqa: F401
    _STOP_WORDS,
    DISTANCE_THRESHOLD,
    MIN_CLUSTER_SIZE,
    _cluster_segments,
    _compute_sentiment,
    _extract_keywords,
)
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)
