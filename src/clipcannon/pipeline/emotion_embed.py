"""Dimensional speech-emotion analysis pipeline stage for ClipCannon.

This is one of the frozen-embedder *instruments* of the panel (the emotion
axis). Per the differentiation contract it MUST emit grounded, non-degenerate
signal about real emotional state — not a constant or an arbitrary statistic
of an unrelated model.

Segments audio into 5-second windows with 2.5-second stride and predicts
dimensional **arousal** and **valence** (plus a grounded acoustic **energy**)
using a wav2vec2 model fine-tuned for dimensional speech emotion recognition
on MSP-Podcast (audEERING; Wagner et al. 2023, "Dawn of the Transformer Era
in Speech Emotion Recognition: Closing the Valence Gap", IEEE TPAMI). The
model's pooled last-layer hidden states (1024-d) are stored as the emotion
embedding in vec_emotion.

There is NO fallback: if the emotion model cannot be loaded or run, the stage
fails loudly with diagnostics. A silent RMS/zero-vector placeholder would make
this instrument contribute ~0 bits and silently corrupt the constellation.

Model license note: the audEERING model is CC BY-NC-SA 4.0 (research use). A
commercial deployment requires a commercial license from audEERING or a
drop-in dimensional-SER replacement that satisfies the same output contract
(arousal, valence in [0,1] + 1024-d pooled hidden states).
"""

# Implementation lives in the emotion_embed_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
import logging
import struct  # noqa: F401
import time  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

import numpy as np  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.db.queries import batch_insert  # noqa: F401
from clipcannon.exceptions import PipelineError  # noqa: F401
from clipcannon.pipeline.emotion_embed_audio import (  # noqa: F401
    EMBEDDING_DIM,
    MODEL_ID,
    OPERATION,
    STAGE,
    STRIDE_S,
    TARGET_SR,
    WINDOW_S,
    _load_audio,
    _segment_audio,
)
from clipcannon.pipeline.emotion_embed_model import (  # noqa: F401
    _assert_not_degenerate,
    _build_emotion_model_class,
    _compute_emotion_model,
)
from clipcannon.pipeline.emotion_embed_stage import (  # noqa: F401
    _insert_results,
    _pack_embedding,
    run_emotion_embed,
)
from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
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
