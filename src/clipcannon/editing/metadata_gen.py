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

if TYPE_CHECKING:
    from pathlib import Path

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all

logger = logging.getLogger(__name__)


# ============================================================
# Platform metadata constraints
# ============================================================
@dataclass(frozen=True)
class PlatformLimits:
    """Character limits and style rules for a target platform."""

    title_max: int | None
    description_max: int
    hashtag_min: int
    hashtag_max: int
    tone: str  # casual, professional, seo


PLATFORM_LIMITS: dict[str, PlatformLimits] = {
    "tiktok": PlatformLimits(
        title_max=None,
        description_max=2200,
        hashtag_min=3,
        hashtag_max=5,
        tone="casual",
    ),
    "instagram_reels": PlatformLimits(
        title_max=None,
        description_max=2200,
        hashtag_min=20,
        hashtag_max=30,
        tone="casual",
    ),
    "youtube_shorts": PlatformLimits(
        title_max=100,
        description_max=5000,
        hashtag_min=3,
        hashtag_max=15,
        tone="seo",
    ),
    "youtube_standard": PlatformLimits(
        title_max=100,
        description_max=5000,
        hashtag_min=3,
        hashtag_max=15,
        tone="seo",
    ),
    "youtube_4k": PlatformLimits(
        title_max=100,
        description_max=5000,
        hashtag_min=3,
        hashtag_max=15,
        tone="seo",
    ),
    "facebook": PlatformLimits(
        title_max=None,
        description_max=63206,
        hashtag_min=0,
        hashtag_max=5,
        tone="casual",
    ),
    "linkedin": PlatformLimits(
        title_max=None,
        description_max=3000,
        hashtag_min=3,
        hashtag_max=5,
        tone="professional",
    ),
}

# Casual prefixes for social platforms
_CASUAL_PREFIXES: list[str] = [
    "Watch this:",
    "You need to see this:",
    "This is incredible:",
    "Check this out:",
    "Don't miss this:",
]

# Professional prefixes for LinkedIn
_PROFESSIONAL_PREFIXES: list[str] = [
    "Key insight:",
    "Here's what matters:",
    "Important takeaway:",
    "Worth considering:",
]

# SEO prefixes for YouTube
_SEO_PREFIXES: list[str] = [
    "",
    "WATCH:",
    "NEW:",
]


# ============================================================
# Result dataclass
# ============================================================
@dataclass
class MetadataResult:
    """Generated metadata for an edit."""

    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)
    thumbnail_timestamp_ms: int | None = None


# ============================================================
# Data extraction helpers
# ============================================================
def _fetch_topics_for_range(
    db_path: Path,
    project_id: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, object]]:
    """Fetch topics overlapping the given time range.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        start_ms: Range start in milliseconds.
        end_ms: Range end in milliseconds.

    Returns:
        List of topic rows as dicts.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT label, keywords, coherence_score "
            "FROM topics "
            "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
            "ORDER BY coherence_score DESC",
            (project_id, end_ms, start_ms),
        )
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _fetch_highlights_for_range(
    db_path: Path,
    project_id: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, object]]:
    """Fetch highlights overlapping the given time range, sorted by score.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        start_ms: Range start in milliseconds.
        end_ms: Range end in milliseconds.

    Returns:
        List of highlight rows as dicts.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT start_ms, end_ms, type, score, reason "
            "FROM highlights "
            "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
            "ORDER BY score DESC",
            (project_id, end_ms, start_ms),
        )
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _fetch_transcript_for_range(
    db_path: Path,
    project_id: str,
    start_ms: int,
    end_ms: int,
    max_chars: int = 2000,
) -> str:
    """Fetch transcript text for the given time range.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        start_ms: Range start in milliseconds.
        end_ms: Range end in milliseconds.
        max_chars: Maximum characters to return.

    Returns:
        Concatenated transcript text.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT text FROM transcript_segments "
            "WHERE project_id = ? AND start_ms < ? AND end_ms > ? "
            "ORDER BY start_ms",
            (project_id, end_ms, start_ms),
        )
    finally:
        conn.close()

    parts: list[str] = []
    total = 0
    for row in rows:
        text = str(row.get("text", ""))
        if total + len(text) > max_chars:
            remaining = max_chars - total
            if remaining > 0:
                parts.append(text[:remaining])
            break
        parts.append(text)
        total += len(text)

    return " ".join(parts).strip()


def _get_edit_time_range(
    edl_json: dict[str, object],
) -> tuple[int, int]:
    """Extract the min start and max end from an EDL's segments.

    Args:
        edl_json: Parsed EDL JSON dict.

    Returns:
        Tuple of (min_source_start_ms, max_source_end_ms).
    """
    segments = edl_json.get("segments", [])
    if not segments:
        return (0, 0)

    starts = [int(s.get("source_start_ms", 0)) for s in segments]  # type: ignore[union-attr]
    ends = [int(s.get("source_end_ms", 0)) for s in segments]  # type: ignore[union-attr]
    return (min(starts), max(ends))


# ============================================================
# Keyword / hashtag extraction
# ============================================================
def _extract_keywords(
    topics: list[dict[str, object]],
    highlights: list[dict[str, object]],
) -> list[str]:
    """Extract unique keywords from topics and highlight reasons.

    Args:
        topics: Topic rows with label and keywords fields.
        highlights: Highlight rows with reason field.

    Returns:
        Deduplicated list of keyword strings.
    """
    seen: set[str] = set()
    keywords: list[str] = []

    for topic in topics:
        # Add topic label words
        label = str(topic.get("label", ""))
        for word in label.split():
            clean = re.sub(r"[^a-zA-Z0-9]", "", word).lower()
            if clean and len(clean) > 2 and clean not in seen:
                seen.add(clean)
                keywords.append(clean)

        # Add keywords from the keywords field (comma-separated JSON)
        kw_raw = topic.get("keywords", "")
        if kw_raw:
            try:
                kw_list = json.loads(str(kw_raw))
                if isinstance(kw_list, list):
                    for kw in kw_list:
                        clean = re.sub(r"[^a-zA-Z0-9]", "", str(kw)).lower()
                        if clean and len(clean) > 2 and clean not in seen:
                            seen.add(clean)
                            keywords.append(clean)
            except (json.JSONDecodeError, TypeError):
                # Try as plain comma-separated
                for kw in str(kw_raw).split(","):
                    clean = re.sub(r"[^a-zA-Z0-9]", "", kw).lower()
                    if clean and len(clean) > 2 and clean not in seen:
                        seen.add(clean)
                        keywords.append(clean)

    # Also pick words from highlight reasons
    for hl in highlights[:5]:
        reason = str(hl.get("reason", ""))
        for word in reason.split():
            clean = re.sub(r"[^a-zA-Z0-9]", "", word).lower()
            if clean and len(clean) > 3 and clean not in seen:
                seen.add(clean)
                keywords.append(clean)

    return keywords


def _build_hashtags(
    keywords: list[str],
    limits: PlatformLimits,
) -> list[str]:
    """Build platform-appropriate hashtag list from keywords.

    Args:
        keywords: Raw keyword strings.
        limits: Platform constraints.

    Returns:
        List of hashtags with # prefix.
    """
    tags: list[str] = []
    for kw in keywords:
        tag = f"#{kw}"
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= limits.hashtag_max:
            break

    # Pad with generic tags if under minimum
    generic_tags = [
        "#viral", "#trending", "#fyp", "#content",
        "#video", "#mustwatch", "#reels", "#shorts",
    ]
    for gt in generic_tags:
        if len(tags) >= limits.hashtag_min:
            break
        if gt not in tags:
            tags.append(gt)

    return tags[:limits.hashtag_max]


# ============================================================
# Title generation
# ============================================================
def _generate_title(
    topics: list[dict[str, object]],
    highlights: list[dict[str, object]],
    limits: PlatformLimits,
) -> str:
    """Generate a platform-appropriate title.

    Uses the top highlight reason or topic label with a
    tone-appropriate prefix.

    Args:
        topics: Topic rows from the database.
        highlights: Highlight rows from the database.
        limits: Platform character limits.

    Returns:
        Generated title string.
    """
    # Pick the best content source
    base_text = ""
    if highlights:
        base_text = str(highlights[0].get("reason", ""))
    if not base_text and topics:
        base_text = str(topics[0].get("label", ""))
    if not base_text:
        base_text = "Clip highlight"

    # Clean up the base text
    base_text = base_text.strip().rstrip(".")

    # Pick a prefix based on tone
    if limits.tone == "professional":
        prefix = _PROFESSIONAL_PREFIXES[0]
    elif limits.tone == "seo":
        prefix = _SEO_PREFIXES[0]
    else:
        prefix = _CASUAL_PREFIXES[0]

    title = f"{prefix} {base_text}" if prefix else base_text

    # Capitalize first letter
    if title:
        title = title[0].upper() + title[1:]

    # Enforce character limit
    if limits.title_max is not None and len(title) > limits.title_max:
        title = title[: limits.title_max - 3].rstrip() + "..."

    return title


# ============================================================
# Description generation
# ============================================================
def _generate_description(
    topics: list[dict[str, object]],
    highlights: list[dict[str, object]],
    transcript_text: str,
    limits: PlatformLimits,
) -> str:
    """Generate a platform-appropriate description.

    Summarizes content from transcript segments, includes
    topic context and a call-to-action.

    Args:
        topics: Topic rows from the database.
        highlights: Highlight rows from the database.
        transcript_text: Transcript text for the edit's time range.
        limits: Platform character limits.

    Returns:
        Generated description string.
    """
    parts: list[str] = []

    # Opening line from highlight or topic
    if highlights:
        reason = str(highlights[0].get("reason", ""))
        if reason:
            parts.append(reason.strip().rstrip(".") + ".")
    elif topics:
        label = str(topics[0].get("label", ""))
        if label:
            parts.append(f"This clip covers: {label}.")

    # Add transcript summary (first few sentences)
    if transcript_text:
        sentences = re.split(r"(?<=[.!?])\s+", transcript_text)
        summary = " ".join(sentences[:3]).strip()
        if summary:
            if not summary.endswith((".", "!", "?")):
                summary += "."
            parts.append(summary)

    # Add topic context if multiple topics
    if len(topics) > 1:
        labels = [str(t.get("label", "")) for t in topics[1:4] if t.get("label")]
        if labels:
            parts.append(f"Also covers: {', '.join(labels)}.")

    # Call-to-action based on tone
    if limits.tone == "professional":
        parts.append(
            "Share your thoughts in the comments. "
            "Follow for more insights."
        )
    elif limits.tone == "seo":
        parts.append(
            "Like and subscribe for more content! "
            "Hit the bell for notifications."
        )
    else:
        parts.append(
            "Follow for more! Like and share if you enjoyed this."
        )

    description = "\n\n".join(parts)

    # Enforce character limit
    if len(description) > limits.description_max:
        description = description[: limits.description_max - 3].rstrip() + "..."

    return description


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
