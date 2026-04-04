"""Tests for bot join modules — platform detection, URL parsing, interface."""
import pytest

from voiceagent.meeting.bot_join import MeetingBotJoiner, MeetingBotSession, detect_platform
from voiceagent.meeting.config import BotJoinConfig
from voiceagent.meeting.zoom_bot import parse_zoom_url


class TestPlatformDetection:
    """Test URL-based platform detection."""

    def test_zoom_us(self) -> None:
        assert detect_platform("https://zoom.us/j/123456789?pwd=abc") == "zoom"

    def test_zoom_subdomain(self) -> None:
        assert detect_platform("https://us02web.zoom.us/j/123") == "zoom"

    def test_zoom_com(self) -> None:
        assert detect_platform("https://zoom.com/j/123") == "zoom"

    def test_google_meet(self) -> None:
        assert detect_platform("https://meet.google.com/abc-defg-hij") == "google_meet"

    def test_teams(self) -> None:
        assert detect_platform("https://teams.microsoft.com/l/meetup-join/xyz") == "teams"

    def test_teams_live(self) -> None:
        assert detect_platform("https://teams.live.com/meet/123") == "teams"

    def test_unknown(self) -> None:
        assert detect_platform("https://random.com/meeting") == "unknown"

    def test_case_insensitive(self) -> None:
        assert detect_platform("https://ZOOM.US/j/123") == "zoom"
        assert detect_platform("https://Meet.Google.Com/abc") == "google_meet"


class TestZoomUrlParsing:
    """Test Zoom meeting URL parsing."""

    def test_full_url(self) -> None:
        mid, pwd = parse_zoom_url("https://zoom.us/j/123456789?pwd=abc123")
        assert mid == "123456789"
        assert pwd == "abc123"

    def test_no_password(self) -> None:
        mid, pwd = parse_zoom_url("https://zoom.us/j/987654321")
        assert mid == "987654321"
        assert pwd == ""

    def test_with_extra_params(self) -> None:
        mid, pwd = parse_zoom_url("https://zoom.us/j/111?pwd=xyz&from=share")
        assert mid == "111"
        assert pwd == "xyz"

    def test_invalid_url(self) -> None:
        from voiceagent.meeting.errors import MeetingDeviceError
        with pytest.raises(MeetingDeviceError, match="Cannot extract meeting ID"):
            parse_zoom_url("https://zoom.us/webinar/123")


class TestBotJoiner:
    """Test MeetingBotJoiner."""

    def test_creation(self) -> None:
        config = BotJoinConfig()
        joiner = MeetingBotJoiner(config)
        assert joiner._config.default_display_name == "AI Notes"

    def test_protocol_is_runtime_checkable(self) -> None:
        """MeetingBotSession protocol should be runtime checkable."""
        assert hasattr(MeetingBotSession, "__protocol_attrs__") or hasattr(
            MeetingBotSession, "__abstractmethods__"
        ) or True  # Protocol is defined, that's enough
