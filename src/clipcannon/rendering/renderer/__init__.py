"""Core rendering engine for ClipCannon.

Translates an EDL (Edit Decision List) into FFmpeg commands and
executes them as subprocesses. Handles source validation, caption
generation, crop computation, and provenance recording.
Enforces generation loss prevention and source integrity checks.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.caption_render import generate_ass_file
from clipcannon.editing.edl import (
    EditDecisionList,
    compute_total_duration,
)
from clipcannon.editing.smart_crop import CropRegion, compute_crop_region
from clipcannon.exceptions import PipelineError
from clipcannon.provenance.hasher import sha256_file
from clipcannon.provenance.recorder import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
)
from clipcannon.rendering.ffmpeg_cmd import (
    _escape_subtitle_path,
    build_encoding_args,
    build_ffmpeg_cmd,
)
from clipcannon.rendering.profiles import (
    EncodingProfile,
    get_profile,
    get_software_fallback,
)
from clipcannon.rendering.segment_hash import compute_segment_hash
from clipcannon.rendering.thumbnail import generate_thumbnail

from .engine import RenderEngine, logger
from .helpers import (
    _SEGMENT_CACHE_DDL,
    RenderResult,
    _parse_sfx_offset_ms,
    _probe_duration_ms,
    _probe_size,
    _scale_ass_file,
    ensure_segment_cache_table,
)

__all__ = [
    "CropRegion", "EditDecisionList", "EncodingProfile", "ExecutionInfo", "InputInfo",
    "OutputInfo", "Path", "PipelineError", "RenderEngine", "RenderResult", "TYPE_CHECKING",
    "_SEGMENT_CACHE_DDL", "_escape_subtitle_path", "_parse_sfx_offset_ms", "_probe_duration_ms",
    "_probe_size", "_scale_ass_file", "asyncio", "build_encoding_args", "build_ffmpeg_cmd",
    "compute_crop_region", "compute_segment_hash", "compute_total_duration", "dataclass",
    "ensure_segment_cache_table", "execute", "fetch_all", "fetch_one", "generate_ass_file",
    "generate_thumbnail", "get_connection", "get_profile", "get_software_fallback", "logger",
    "logging", "record_provenance", "secrets", "sha256_file", "time",
]
