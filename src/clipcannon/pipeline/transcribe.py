"""WhisperX transcription pipeline stage for ClipCannon.

Transcribes audio using WhisperX with wav2vec2 forced alignment
for 20-50ms word-level precision. Falls back to faster-whisper
if WhisperX is not installed.

Includes a multi-layer anti-hallucination pipeline:
1. VAD tuning (vad_onset/vad_offset for WhisperX)
2. Threshold parameters (for faster-whisper fallback)
3. Post-transcription filtering:
   - Known hallucination phrase detection
   - Repetition/looping detection and delooping
   - Confidence-based word and segment filtering
   - Single-word segment removal

Per the constitution, WhisperX with forced alignment is MANDATORY
for production use. The faster-whisper fallback is for development
and testing only.
"""

# Implementation lives in the transcribe_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
import logging
import math  # noqa: F401
import wave  # noqa: F401
import zlib  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

import numpy as np  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.exceptions import PipelineError  # noqa: F401
from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.pipeline.source_resolution import resolve_audio_input  # noqa: F401
from clipcannon.pipeline.transcribe_audio_checks import (  # noqa: F401
    _amp_to_dbfs,
    _compute_audio_diagnostics,
    _reject_if_silent,
)
from clipcannon.pipeline.transcribe_backends import (  # noqa: F401
    _check_faster_whisper_available,
    _check_whisperx_available,
    _transcribe_faster_whisper,
    _transcribe_whisperx,
)
from clipcannon.pipeline.transcribe_config import (  # noqa: F401
    _AUDIBLE_FRAME_DBFS,
    _COMPRESSION_RATIO_THRESHOLD,
    _HALLUCINATION_EXACT,
    _HALLUCINATION_PHRASES,
    _HALLUCINATION_SILENCE_THRESHOLD,
    _LOG_PROB_THRESHOLD,
    _MAX_COMPRESSION_RATIO,
    _MIN_AUDIBLE_PCT,
    _MIN_SEGMENT_CONFIDENCE,
    _MIN_WORD_CONFIDENCE,
    _NO_SPEECH_THRESHOLD,
    _SILENCE_PEAK_DBFS,
    _VAD_OFFSET,
    _VAD_ONSET,
    OPERATION,
    STAGE,
)
from clipcannon.pipeline.transcribe_hallucination import (  # noqa: F401
    _compression_ratio,
    _deloop_text,
    _detect_repetition,
    _filter_hallucinations,
    _is_hallucination_phrase,
    _word_confidence,
)
from clipcannon.pipeline.transcribe_stage import _insert_transcript, run_transcribe  # noqa: F401
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
    sha256_string,
)

logger: logging.Logger = logging.getLogger(__name__)
