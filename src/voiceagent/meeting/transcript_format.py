"""Meeting transcript Markdown document builder.

Creates structured Markdown with YAML-like frontmatter that OCR Provenance
can ingest as a text document (Markdown passthrough -- no OCR, no GPU).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from voiceagent.meeting.errors import MeetingTranscriptStoreError

logger = logging.getLogger(__name__)


@dataclass
class MeetingSegment:
    """A single utterance in the meeting.

    Args:
        start_ms: Segment start time in milliseconds from meeting start.
        end_ms: Segment end time in milliseconds from meeting start.
        text: Transcribed text content.
        speaker_id: Internal speaker identifier from diarization.
        speaker_name: Display name of the speaker.
        is_clone: Whether this segment is from a voice clone.
        clone_name: Name of the clone (if is_clone is True).
        confidence: ASR confidence score (0.0-1.0).
        segment_type: Type of segment: "speech", "question", or "response".
        secs_score: Speaker Embedding Cosine Similarity score for clone output.
    """

    start_ms: int
    end_ms: int
    text: str
    speaker_id: str = ""
    speaker_name: str = ""
    is_clone: bool = False
    clone_name: str = ""
    confidence: float = 0.0
    segment_type: str = "speech"
    secs_score: float = 0.0


@dataclass
class CloneInteraction:
    """A question-and-response between a participant and a clone.

    Args:
        clone_name: Name of the clone that responded.
        question_text: The question asked by the participant.
        response_text: The clone's response.
        questioner: Display name of the person who asked.
        question_at_ms: Timestamp of the question in milliseconds.
        response_at_ms: Timestamp of the response in milliseconds.
        latency_ms: Time between question end and response start.
        secs_score: SECS score of the clone's TTS output.
        prosody_style: Prosody style used for the response.
        address_confidence: Confidence that the clone was addressed.
    """

    clone_name: str
    question_text: str
    response_text: str
    questioner: str = ""
    question_at_ms: int = 0
    response_at_ms: int = 0
    latency_ms: int = 0
    secs_score: float = 0.0
    prosody_style: str = ""
    address_confidence: float = 0.0


@dataclass
class MeetingDocument:
    """All data needed to build a meeting transcript Markdown document.

    Args:
        meeting_id: Unique meeting identifier (e.g. "mtg_abc123").
        title: Meeting title (auto-generated if empty).
        started_at: Meeting start timestamp.
        ended_at: Meeting end timestamp (None if still in progress).
        duration_minutes: Total meeting duration in minutes.
        platform: Meeting platform name (e.g. "zoom", "teams").
        clone_names: List of clone names participating in the meeting.
        participant_names: List of human participant names.
        tags: List of tags for categorization.
        summary: Post-meeting summary text.
        segments: Ordered list of transcript segments.
        interactions: List of clone Q&A interactions.
    """

    meeting_id: str
    title: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_minutes: int = 0
    platform: str = "unknown"
    clone_names: list[str] | None = None
    participant_names: list[str] | None = None
    tags: list[str] | None = None
    summary: str = ""
    segments: list[MeetingSegment] | None = None
    interactions: list[CloneInteraction] | None = None

    def __post_init__(self) -> None:
        """Initialize mutable default lists to avoid shared state."""
        if self.clone_names is None:
            self.clone_names = []
        if self.participant_names is None:
            self.participant_names = []
        if self.tags is None:
            self.tags = []
        if self.segments is None:
            self.segments = []
        if self.interactions is None:
            self.interactions = []


def _ms_to_timestamp(ms: int) -> str:
    """Convert milliseconds to HH:MM:SS or M:SS format.

    Args:
        ms: Time in milliseconds. Negative values are clamped to 0.

    Returns:
        Formatted timestamp string. Uses HH:MM:SS if hours > 0,
        otherwise M:SS.
    """
    if ms < 0:
        ms = 0
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _build_frontmatter(doc: MeetingDocument) -> str:
    """Build YAML-style frontmatter block.

    Args:
        doc: The meeting document to extract metadata from.

    Returns:
        Frontmatter string with --- delimiters.
    """
    lines: list[str] = ["---"]
    lines.append(f"title: {doc.title}")
    lines.append(f"meeting_id: {doc.meeting_id}")
    lines.append(f"date: {doc.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if doc.ended_at:
        lines.append(f"ended: {doc.ended_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"duration_minutes: {doc.duration_minutes}")
    lines.append(f"platform: {doc.platform}")
    if doc.clone_names:
        lines.append(f"clones: {', '.join(doc.clone_names)}")
    if doc.participant_names:
        lines.append(f"participants: {', '.join(doc.participant_names)}")
    if doc.tags:
        lines.append(f"tags: {', '.join(doc.tags)}")
    lines.append("---")
    return "\n".join(lines)


def _build_summary_section(doc: MeetingDocument) -> str:
    """Build the summary section.

    Args:
        doc: The meeting document.

    Returns:
        Summary section Markdown or empty string if no summary.
    """
    if not doc.summary:
        return ""
    lines: list[str] = [
        "",
        "## Summary",
        "",
        doc.summary,
    ]
    return "\n".join(lines)


def _build_interactions_section(doc: MeetingDocument) -> str:
    """Build the Clone Interactions section listing each Q&A pair.

    Args:
        doc: The meeting document.

    Returns:
        Interactions section Markdown or empty string if no interactions.
    """
    if not doc.interactions:
        return ""
    lines: list[str] = [
        "",
        "## Clone Interactions",
        "",
    ]
    for idx, interaction in enumerate(doc.interactions, start=1):
        q_ts = _ms_to_timestamp(interaction.question_at_ms)
        r_ts = _ms_to_timestamp(interaction.response_at_ms)
        questioner = interaction.questioner or "Unknown"
        lines.append(f"### Q{idx}: {questioner} -> {interaction.clone_name}")
        lines.append("")
        lines.append(f"**Question** [{q_ts}]: {interaction.question_text}")
        lines.append("")
        score_parts: list[str] = []
        if interaction.secs_score > 0:
            score_parts.append(f"SECS: {interaction.secs_score:.2f}")
        if interaction.latency_ms > 0:
            score_parts.append(f"Latency: {interaction.latency_ms}ms")
        if interaction.prosody_style:
            score_parts.append(f"Prosody: {interaction.prosody_style}")
        if interaction.address_confidence > 0:
            score_parts.append(f"Address: {interaction.address_confidence:.2f}")
        score_str = f" [{', '.join(score_parts)}]" if score_parts else ""
        lines.append(f"**Response** [{r_ts}]{score_str}: {interaction.response_text}")
        lines.append("")
    return "\n".join(lines)


def _build_transcript_section(doc: MeetingDocument) -> str:
    """Build the full transcript section with all segments.

    Args:
        doc: The meeting document.

    Returns:
        Transcript section Markdown or empty string if no segments.
    """
    if not doc.segments:
        return ""
    lines: list[str] = [
        "",
        "## Transcript",
        "",
    ]
    for segment in doc.segments:
        ts = _ms_to_timestamp(segment.start_ms)
        speaker = segment.speaker_name or segment.speaker_id or "Unknown"
        if segment.is_clone and segment.secs_score > 0:
            lines.append(f"**{ts} -- {speaker}** [SECS: {segment.secs_score:.2f}]")
        else:
            lines.append(f"**{ts} -- {speaker}**")
        lines.append(segment.text)
        lines.append("")
    return "\n".join(lines)


def build_transcript_markdown(doc: MeetingDocument) -> str:
    """Build a complete Markdown transcript document.

    Structure:
    1. Frontmatter (title, date, duration, platform, clones, participants, tags)
    2. Summary section (if available)
    3. Clone Interactions section (Q&A pairs for quick review)
    4. Full Transcript section (all segments with timestamps and speakers)

    Args:
        doc: The meeting document containing all transcript data.

    Returns:
        Markdown string ready for OCR Provenance ingestion.

    Raises:
        MeetingTranscriptStoreError: If document data is invalid.
    """
    if not doc.meeting_id:
        raise MeetingTranscriptStoreError("MeetingDocument.meeting_id is required")
    if not doc.started_at:
        raise MeetingTranscriptStoreError("MeetingDocument.started_at is required")

    parts: list[str] = [_build_frontmatter(doc)]
    summary = _build_summary_section(doc)
    if summary:
        parts.append(summary)
    interactions = _build_interactions_section(doc)
    if interactions:
        parts.append(interactions)
    transcript = _build_transcript_section(doc)
    if transcript:
        parts.append(transcript)

    return "\n".join(parts) + "\n"


def build_partial_transcript(doc: MeetingDocument) -> str:
    """Build a partial transcript for mid-meeting flush.

    Used during the meeting for crash safety -- writes what we have so far.
    No summary section, no interactions section. Only frontmatter and
    transcript segments.

    Args:
        doc: The meeting document with current in-progress data.

    Returns:
        Partial Markdown string for crash-safety flush to disk.
    """
    parts: list[str] = [_build_frontmatter(doc)]
    transcript = _build_transcript_section(doc)
    if transcript:
        parts.append(transcript)

    return "\n".join(parts) + "\n"
