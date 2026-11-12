"""Keyword, hashtag, title and description text generation."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from .limits import _CASUAL_PREFIXES, _PROFESSIONAL_PREFIXES, _SEO_PREFIXES

if TYPE_CHECKING:
    from .limits import PlatformLimits


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
