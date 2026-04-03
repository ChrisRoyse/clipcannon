"""Tests for voiceagent.meeting.transcript_format -- real objects, no mocks."""
from __future__ import annotations

from datetime import datetime

import pytest

from voiceagent.meeting.errors import MeetingTranscriptStoreError
from voiceagent.meeting.transcript_format import (
    CloneInteraction,
    MeetingDocument,
    MeetingSegment,
    _ms_to_timestamp,
    build_partial_transcript,
    build_transcript_markdown,
)


class TestMsToTimestamp:
    """Verify _ms_to_timestamp conversion for edge cases and normal values."""

    def test_ms_to_timestamp_zero(self) -> None:
        assert _ms_to_timestamp(0) == "0:00"

    def test_ms_to_timestamp_seconds(self) -> None:
        assert _ms_to_timestamp(5000) == "0:05"

    def test_ms_to_timestamp_minutes(self) -> None:
        assert _ms_to_timestamp(65000) == "1:05"

    def test_ms_to_timestamp_hours(self) -> None:
        assert _ms_to_timestamp(3661000) == "1:01:01"

    def test_ms_to_timestamp_negative_clamped(self) -> None:
        assert _ms_to_timestamp(-500) == "0:00"

    def test_ms_to_timestamp_exact_minute(self) -> None:
        assert _ms_to_timestamp(60000) == "1:00"


class TestMeetingDocument:

    def test_meeting_document_defaults(self) -> None:
        doc = MeetingDocument(
            meeting_id="mtg_test01",
            title="Test",
            started_at=datetime.now(),
        )
        assert doc.segments == []
        assert doc.interactions == []
        assert doc.clone_names == []
        assert doc.participant_names == []
        assert doc.tags == []
        assert doc.summary == ""
        assert doc.ended_at is None
        assert doc.duration_minutes == 0


class TestBuildMarkdown:

    @pytest.fixture()
    def sample_doc(self) -> MeetingDocument:
        doc = MeetingDocument(
            meeting_id="mtg_abc123",
            title="Sprint Review",
            started_at=datetime(2026, 4, 3, 10, 0),
            platform="zoom",
            clone_names=["nate"],
            participant_names=["Sarah", "Mike"],
            summary="- Reviewed sprint goals\n- Action items assigned",
        )
        doc.segments.append(
            MeetingSegment(
                start_ms=0,
                end_ms=3000,
                text="Let's get started.",
                speaker_name="Sarah",
            )
        )
        doc.segments.append(
            MeetingSegment(
                start_ms=3000,
                end_ms=6000,
                text="Everything is on schedule.",
                speaker_name="Nate (Clone)",
                is_clone=True,
                clone_name="nate",
                secs_score=0.97,
                segment_type="response",
            )
        )
        doc.interactions.append(
            CloneInteraction(
                clone_name="nate",
                question_text="What is the status?",
                response_text="Everything is on schedule.",
                questioner="Sarah",
                question_at_ms=0,
                response_at_ms=3500,
                latency_ms=500,
                secs_score=0.97,
                prosody_style="calm",
                address_confidence=0.95,
            )
        )
        return doc

    def test_build_markdown_has_frontmatter(self, sample_doc: MeetingDocument) -> None:
        md = build_transcript_markdown(sample_doc)
        assert md.startswith("---")
        assert "title: Sprint Review" in md
        assert "meeting_id: mtg_abc123" in md
        assert "platform: zoom" in md

    def test_build_markdown_has_speakers(self, sample_doc: MeetingDocument) -> None:
        md = build_transcript_markdown(sample_doc)
        assert "Sarah" in md
        assert "Nate (Clone)" in md

    def test_build_markdown_has_secs_score(self, sample_doc: MeetingDocument) -> None:
        md = build_transcript_markdown(sample_doc)
        assert "0.97" in md
        assert "SECS" in md

    def test_build_markdown_has_interactions(self, sample_doc: MeetingDocument) -> None:
        md = build_transcript_markdown(sample_doc)
        assert "## Clone Interactions" in md
        assert "Q1:" in md
        assert "Sarah -> nate" in md

    def test_build_partial_no_summary(self, sample_doc: MeetingDocument) -> None:
        partial = build_partial_transcript(sample_doc)
        assert "## Summary" not in partial
        assert "## Clone Interactions" not in partial
        # But frontmatter and transcript present
        assert "---" in partial
        assert "Sarah" in partial

    def test_build_markdown_empty_segments(self) -> None:
        doc = MeetingDocument(
            meeting_id="mtg_empty",
            title="Empty Meeting",
            started_at=datetime(2026, 4, 3, 11, 0),
        )
        md = build_transcript_markdown(doc)
        assert "---" in md
        assert "Empty Meeting" in md
        # No transcript section if no segments
        assert "## Transcript" not in md

    def test_build_markdown_requires_meeting_id(self) -> None:
        doc = MeetingDocument(
            meeting_id="",
            title="Bad",
            started_at=datetime.now(),
        )
        with pytest.raises(MeetingTranscriptStoreError, match="meeting_id"):
            build_transcript_markdown(doc)
