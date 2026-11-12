"""Multi-signal highlight scoring pipeline stage for ClipCannon.

Computes highlight scores for candidate time windows using a weighted
combination of seven signals: emotion energy, reaction presence,
semantic density, narrative completeness, visual variety, visual
quality, and speaker confidence. This is an optional stage.
"""

# Implementation lives in the highlights_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import asyncio  # noqa: F401
import logging
import time  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.db.queries import batch_insert, fetch_all, fetch_one  # noqa: F401
from clipcannon.pipeline.highlights_loaders import (  # noqa: F401
    _get_duration_ms,
    _load_emotion_curve,
    _load_reactions,
    _load_scenes,
    _load_segments_with_speakers,
    _load_topics,
)
from clipcannon.pipeline.highlights_scoring import (  # noqa: F401
    CANDIDATE_WINDOW_MS,
    W_EMOTION,
    W_NARRATIVE,
    W_QUALITY,
    W_REACTION,
    W_SEMANTIC,
    W_SPEAKER,
    W_VISUAL_VARIETY,
    _avg_emotion_energy,
    _avg_semantic_density,
    _avg_visual_quality,
    _classify_highlight_type,
    _generate_reason,
    _has_reaction,
    _narrative_completeness,
    _score_candidates,
    _speaker_confidence_score,
    _visual_variety_score,
)
from clipcannon.pipeline.highlights_stage import (  # noqa: F401
    OPERATION,
    STAGE,
    _insert_highlights,
    run_highlights,
)
from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)
