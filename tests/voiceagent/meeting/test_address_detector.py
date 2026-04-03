"""Tests for voiceagent.meeting.address_detector -- real objects, no mocks."""
from __future__ import annotations

from voiceagent.meeting.address_detector import AddressDetector, AddressResult
from voiceagent.meeting.config import CloneConfig
from voiceagent.meeting.transcript_format import MeetingSegment


def _make_detector(
    name: str = "nate",
    aliases: list[str] | None = None,
    threshold: float = 0.8,
) -> AddressDetector:
    """Build a real AddressDetector with the given config."""
    config = CloneConfig(
        aliases=aliases or [],
        address_threshold=threshold,
    )
    return AddressDetector(name, config)


def _make_segment(text: str, speaker: str = "Sarah", is_clone: bool = False) -> MeetingSegment:
    return MeetingSegment(
        start_ms=0,
        end_ms=5000,
        text=text,
        speaker_name=speaker,
        is_clone=is_clone,
    )


class TestAddressDetection:

    def test_name_plus_question_mark(self) -> None:
        det = _make_detector()
        result = det.check_segment(_make_segment("Nate, what's the status?"))
        assert result.is_addressed is True
        assert result.confidence >= 0.9
        assert result.trigger_signal == "name_question"

    def test_name_plus_question_word(self) -> None:
        det = _make_detector()
        result = det.check_segment(_make_segment("Hey Nate can you update us"))
        assert result.is_addressed is True
        assert result.confidence >= 0.9
        assert result.trigger_signal == "name_question"

    def test_no_name(self) -> None:
        det = _make_detector()
        result = det.check_segment(_make_segment("What's the status?"))
        assert result.is_addressed is False
        assert result.confidence == 0.0

    def test_clone_self_speech(self) -> None:
        det = _make_detector()
        result = det.check_segment(
            _make_segment("Nate, what do you think?", is_clone=True)
        )
        assert result.is_addressed is False
        print(f"Clone self-speech: is_addressed={result.is_addressed}, confidence={result.confidence}")

    def test_name_only_below_threshold(self) -> None:
        det = _make_detector()
        result = det.check_segment(_make_segment("I agree with Nate on this"))
        print(f"Name-only: is_addressed={result.is_addressed}, confidence={result.confidence}")
        assert result.is_addressed is False
        assert result.confidence == 0.65
        assert result.trigger_signal == "name_mention"

    def test_alias_detection(self) -> None:
        det = _make_detector(aliases=["Nathan", "hey Nate"])
        result = det.check_segment(_make_segment("Nathan, what do you think?"))
        assert result.is_addressed is True
        assert result.confidence >= 0.9

    def test_contextual_boost(self) -> None:
        det = _make_detector()
        # Name-only (0.65) should get boosted to >=0.8 with context
        context = [
            _make_segment("Can Nate chime in?"),
            _make_segment("Yeah, let's hear from him."),
        ]
        result = det.check_segment(
            _make_segment("I agree with nate"),
            recent_context=context,
        )
        print(f"Contextual: is_addressed={result.is_addressed}, confidence={result.confidence}")
        assert result.is_addressed is True
        assert result.confidence >= 0.8
        assert result.trigger_signal == "contextual"

    def test_result_fields(self) -> None:
        det = _make_detector()
        result = det.check_segment(_make_segment("Random talk about weather."))
        assert isinstance(result, AddressResult)
        assert hasattr(result, "is_addressed")
        assert hasattr(result, "confidence")
        assert hasattr(result, "clone_name")
        assert hasattr(result, "extracted_question")
        assert hasattr(result, "trigger_signal")
        assert result.clone_name == "nate"
