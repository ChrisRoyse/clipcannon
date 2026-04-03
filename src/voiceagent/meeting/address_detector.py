"""Clone address detection from meeting transcript segments.

Multi-signal detection:
1. Name mention -- clone's name or aliases appear in the segment text
2. Question pattern -- text ends with ? or contains question keywords after name
3. Contextual -- name + question within proximity

Threshold: Only trigger when confidence > address_threshold (default 0.8).
Conservative: silence is better than false triggers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from voiceagent.meeting.config import CloneConfig
from voiceagent.meeting.transcript_format import MeetingSegment

logger = logging.getLogger(__name__)

# Question indicator words that suggest someone is asking the clone something.
_QUESTION_WORDS: list[str] = [
    "what",
    "how",
    "when",
    "where",
    "why",
    "who",
    "which",
    "can you",
    "could you",
    "would you",
    "do you",
    "are you",
    "tell us",
    "tell me",
    "thoughts",
    "think",
    "opinion",
    "update",
    "status",
]


@dataclass
class AddressResult:
    """Result of address detection on a segment.

    Attributes:
        is_addressed: Whether the clone was addressed (confidence >= threshold).
        confidence: Detection confidence between 0.0 and 1.0.
        clone_name: The clone's primary name.
        extracted_question: The question text if addressed, empty otherwise.
        trigger_signal: Detection signal that fired: ``"name_mention"``,
            ``"name_question"``, ``"contextual"``, or empty string.
    """

    is_addressed: bool
    confidence: float
    clone_name: str
    extracted_question: str
    trigger_signal: str  # "name_mention", "name_question", "contextual"


class AddressDetector:
    """Detect when a clone is being addressed in meeting speech.

    Uses a conservative multi-signal approach: a name mention alone is not
    enough (confidence 0.65, below the default 0.8 threshold).  The name must
    appear alongside a question mark or question-indicator keywords to reach
    the threshold.  Contextual boost from recent segments can lift a borderline
    detection over the threshold.

    Args:
        clone_name: The clone's primary name.
        clone_config: Clone configuration with aliases and threshold.
    """

    def __init__(self, clone_name: str, clone_config: CloneConfig) -> None:
        self._clone_name = clone_name
        self._config = clone_config

        # Build list of name variants to watch for (case-insensitive).
        self._names: list[str] = [clone_name.lower()]
        for alias in clone_config.aliases:
            cleaned = alias.lower().strip()
            if cleaned and cleaned not in self._names:
                self._names.append(cleaned)

        # Also match without a leading "hey " prefix so that both
        # "hey nate" and "nate" trigger on the same input.
        self._clean_names: list[str] = []
        for name in self._names:
            if name not in self._clean_names:
                self._clean_names.append(name)
            stripped = name.removeprefix("hey ")
            if stripped != name and stripped not in self._clean_names:
                self._clean_names.append(stripped)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_segment(
        self,
        segment: MeetingSegment,
        recent_context: list[MeetingSegment] | None = None,
    ) -> AddressResult:
        """Check if *segment* addresses the clone.

        Args:
            segment: The current transcript segment to evaluate.
            recent_context: Recent preceding segments for contextual analysis
                (newest last).  Only the last three entries are considered.

        Returns:
            An :class:`AddressResult` with confidence and extracted question.
        """
        text_lower = segment.text.lower().strip()

        # Never detect the clone addressing itself.
        if segment.is_clone:
            return self._negative()

        # Signal 1: Does the text contain a recognised name?
        name_found, matched_name = self._find_name(text_lower)
        if not name_found:
            return self._negative()

        # Signal 2: Question indicators (question mark or question words).
        has_question_mark = "?" in segment.text
        has_question_word = any(qw in text_lower for qw in _QUESTION_WORDS)

        # Assign confidence based on signal combination.
        confidence = 0.0
        trigger = ""

        if name_found and has_question_mark:
            confidence = 0.95
            trigger = "name_question"
        elif name_found and has_question_word:
            confidence = 0.90
            trigger = "name_question"
        elif name_found:
            # Name only -- below default threshold (0.8).
            confidence = 0.65
            trigger = "name_mention"

        # Signal 3: Contextual boost from recent segments.
        if (
            recent_context
            and confidence > 0
            and confidence < self._config.address_threshold
        ):
            for ctx_seg in recent_context[-3:]:
                ctx_lower = ctx_seg.text.lower()
                if any(n in ctx_lower for n in self._clean_names):
                    confidence = min(confidence + 0.15, 0.95)
                    trigger = "contextual"
                    break

        is_addressed = confidence >= self._config.address_threshold

        # Extract question text only when addressed.
        question = segment.text.strip() if is_addressed else ""

        if is_addressed:
            logger.info(
                "Address detected: clone=%s, confidence=%.2f, trigger=%s, "
                "text='%s'",
                self._clone_name,
                confidence,
                trigger,
                segment.text[:80],
            )

        return AddressResult(
            is_addressed=is_addressed,
            confidence=confidence,
            clone_name=self._clone_name,
            extracted_question=question,
            trigger_signal=trigger,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_name(self, text_lower: str) -> tuple[bool, str]:
        """Return ``(found, matched_name)`` for the first alias in *text_lower*."""
        for name in self._clean_names:
            if name in text_lower:
                return True, name
        return False, ""

    def _negative(self) -> AddressResult:
        """Return a not-addressed result."""
        return AddressResult(
            is_addressed=False,
            confidence=0.0,
            clone_name=self._clone_name,
            extracted_question="",
            trigger_signal="",
        )
