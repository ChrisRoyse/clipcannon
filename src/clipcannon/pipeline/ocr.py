"""OCR on-screen text detection pipeline stage.

Runs PaddleOCR PP-OCRv5 on extracted frames at 1fps to detect on-screen text,
deduplicates consecutive identical text, classifies text regions by
position, and detects slide-transition events.
"""

# Implementation lives in the ocr_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import json  # noqa: F401
import logging
import tempfile  # noqa: F401
import time  # noqa: F401
from pathlib import Path  # noqa: F401
from typing import TYPE_CHECKING  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.db.queries import batch_insert  # noqa: F401
from clipcannon.pipeline.ocr_engine import (  # noqa: F401
    _classify_region,
    _classify_region_from_relative_y,
    _estimate_font_size,
    _estimate_font_size_from_height,
    _run_paddleocr_on_frames,
    _texts_differ_significantly,
)
from clipcannon.pipeline.ocr_stage import OPERATION, STAGE, run_ocr  # noqa: F401
from clipcannon.pipeline.orchestrator import StageResult  # noqa: F401
from clipcannon.provenance import (  # noqa: F401
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)
