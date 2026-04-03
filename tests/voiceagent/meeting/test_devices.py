"""Tests for voiceagent.meeting.devices -- real objects, no mocks.

Note: PulseAudio (pactl) and v4l2loopback may not be available
on WSL2 or CI. Tests verify code paths that don't need running services.
"""
from __future__ import annotations

from voiceagent.meeting.app_controller import (
    PLATFORM_SHORTCUTS,
    WINDOW_PATTERNS,
)
from voiceagent.meeting.devices import CloneDeviceManager, CloneDevicePair


class TestCloneDeviceManager:

    def test_device_manager_empty(self) -> None:
        dm = CloneDeviceManager()
        assert dm.list_active() == []

    def test_v4l2loopback_check(self) -> None:
        dm = CloneDeviceManager()
        result = dm.check_v4l2loopback()
        # On WSL2 without the module loaded, this should be False
        assert isinstance(result, bool)
        print(f"v4l2loopback loaded: {result}")


class TestCloneDevicePair:

    def test_clone_device_pair_fields(self) -> None:
        pair = CloneDevicePair(
            clone_name="nate",
            video_device="/dev/video20",
            video_label="Clone Nate",
            audio_sink="clone_nate_sink",
            audio_source="clone_nate_mic",
        )
        assert pair.clone_name == "nate"
        assert pair.video_device == "/dev/video20"
        assert pair.video_label == "Clone Nate"
        assert pair.audio_sink == "clone_nate_sink"
        assert pair.audio_source == "clone_nate_mic"
        assert pair.pulse_sink_module is None
        assert pair.pulse_source_module is None


class TestPlatformShortcuts:

    def test_platform_shortcuts(self) -> None:
        """All 3 major platforms have shortcuts defined."""
        for platform in ("zoom", "google_meet", "teams"):
            assert platform in PLATFORM_SHORTCUTS, f"Missing shortcut for {platform}"
            assert isinstance(PLATFORM_SHORTCUTS[platform], str)

    def test_window_patterns(self) -> None:
        """All 3 major platforms have window patterns defined."""
        for platform in ("zoom", "google_meet", "teams"):
            assert platform in WINDOW_PATTERNS, f"Missing window pattern for {platform}"
            assert isinstance(WINDOW_PATTERNS[platform], str)
