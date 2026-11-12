"""Top-level metadata generation for an edit."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .limits import PLATFORM_LIMITS, MetadataResult
from .queries import (
    _fetch_highlights_for_range,
    _fetch_topics_for_range,
    _fetch_transcript_for_range,
    _get_edit_time_range,
)
from .text import _build_hashtags, _extract_keywords, _generate_description, _generate_title

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# Thumbnail selection
# ============================================================
def _select_thumbnail_timestamp(
    highlights: list[dict[str, object]],
    start_ms: int,
    end_ms: int,
) -> int | None:
    """Select the best thumbnail timestamp from highlights.

    Picks the midpoint of the highest-scoring highlight that
    overlaps the edit's time range.

    Args:
        highlights: Highlight rows sorted by score descending.
        start_ms: Edit time range start.
        end_ms: Edit time range end.

    Returns:
        Timestamp in ms for the best thumbnail, or None.
    """
    if not highlights:
        # Fall back to 1/3 into the edit range
        if end_ms > start_ms:
            return start_ms + (end_ms - start_ms) // 3
        return None

    best = highlights[0]
    hl_start = int(best.get("start_ms", start_ms))
    hl_end = int(best.get("end_ms", end_ms))

    # Clamp to edit range
    hl_start = max(hl_start, start_ms)
    hl_end = min(hl_end, end_ms)

    if hl_end <= hl_start:
        return start_ms + (end_ms - start_ms) // 3

    return hl_start + (hl_end - hl_start) // 2


# ============================================================
# Main entry point
# ============================================================
def generate_metadata(
    project_id: str,
    edit_id: str,
    target_platform: str,
    db_path: Path,
    edl_json: dict[str, object],
) -> MetadataResult:
    """Generate platform-specific metadata for an edit.

    Queries the database for topics, highlights, and transcript
    data within the edit's time range, then generates title,
    description, hashtags, and thumbnail timestamp appropriate
    for the target platform.

    Args:
        project_id: Project identifier.
        edit_id: Edit identifier.
        target_platform: Target platform (tiktok, instagram_reels, etc.).
        db_path: Path to the project's analysis.db.
        edl_json: Parsed EDL JSON dict with segments.

    Returns:
        MetadataResult with generated title, description, hashtags,
        and thumbnail timestamp.
    """
    limits = PLATFORM_LIMITS.get(
        target_platform,
        PLATFORM_LIMITS["tiktok"],
    )

    # Determine the source time range from EDL segments
    start_ms, end_ms = _get_edit_time_range(edl_json)

    if start_ms >= end_ms:
        logger.warning(
            "Empty time range for edit %s, returning defaults",
            edit_id,
        )
        return MetadataResult(
            title="Untitled clip",
            description="",
            hashtags=[],
            thumbnail_timestamp_ms=None,
        )

    # Fetch VUD data for the edit's time range
    topics = _fetch_topics_for_range(db_path, project_id, start_ms, end_ms)
    highlights = _fetch_highlights_for_range(
        db_path, project_id, start_ms, end_ms
    )
    transcript_text = _fetch_transcript_for_range(
        db_path, project_id, start_ms, end_ms
    )

    # Extract keywords for hashtags
    keywords = _extract_keywords(topics, highlights)

    # Generate each metadata component
    title = _generate_title(topics, highlights, limits)
    description = _generate_description(
        topics, highlights, transcript_text, limits
    )
    hashtags = _build_hashtags(keywords, limits)
    thumbnail_ts = _select_thumbnail_timestamp(highlights, start_ms, end_ms)

    logger.info(
        "Generated metadata for edit %s: title=%r, %d hashtags, thumb=%s",
        edit_id,
        title[:50],
        len(hashtags),
        thumbnail_ts,
    )

    return MetadataResult(
        title=title,
        description=description,
        hashtags=hashtags,
        thumbnail_timestamp_ms=thumbnail_ts,
    )
