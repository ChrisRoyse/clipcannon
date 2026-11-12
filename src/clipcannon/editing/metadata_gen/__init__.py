"""Metadata generation for ClipCannon edits.

Generates platform-specific titles, descriptions, hashtags, and
thumbnail timestamps from VUD data (topics, highlights, transcript).
Each platform has different character limits and content style rules.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all

from .generator import _select_thumbnail_timestamp, generate_metadata, logger
from .limits import (
    _CASUAL_PREFIXES,
    _PROFESSIONAL_PREFIXES,
    _SEO_PREFIXES,
    PLATFORM_LIMITS,
    MetadataResult,
    PlatformLimits,
)
from .queries import (
    _fetch_highlights_for_range,
    _fetch_topics_for_range,
    _fetch_transcript_for_range,
    _get_edit_time_range,
)
from .text import _build_hashtags, _extract_keywords, _generate_description, _generate_title

__all__: list[str] = [
    "MetadataResult", "PLATFORM_LIMITS", "PlatformLimits", "TYPE_CHECKING", "_CASUAL_PREFIXES",
    "_PROFESSIONAL_PREFIXES", "_SEO_PREFIXES", "_build_hashtags", "_extract_keywords",
    "_fetch_highlights_for_range", "_fetch_topics_for_range", "_fetch_transcript_for_range",
    "_generate_description", "_generate_title", "_get_edit_time_range",
    "_select_thumbnail_timestamp", "dataclass", "fetch_all", "field", "generate_metadata",
    "get_connection", "json", "logger", "logging", "re",
]
