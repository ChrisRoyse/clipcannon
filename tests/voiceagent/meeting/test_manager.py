"""Tests for voiceagent.meeting.manager -- real objects, no mocks.

External services (PulseAudio, Ollama, OCR Provenance) are not running
during tests. Tests verify construction, field presence, and sync-only
operations.
"""
from __future__ import annotations

import dataclasses

from voiceagent.meeting.config import (
    CloneConfig,
    MeetingConfig,
    VoiceConfig,
)
from voiceagent.meeting.manager import CloneInstance, CloneMeetingManager


class TestCloneMeetingManager:

    def test_manager_creation(self) -> None:
        cfg = MeetingConfig()
        mgr = CloneMeetingManager(config=cfg)
        assert mgr is not None

    def test_manager_creation_default_config(self) -> None:
        """Manager with no explicit config loads defaults."""
        mgr = CloneMeetingManager()
        assert mgr is not None

    def test_list_clones_empty(self) -> None:
        mgr = CloneMeetingManager(config=MeetingConfig())
        assert mgr.list_clones() == []

    def test_get_clone_missing(self) -> None:
        mgr = CloneMeetingManager(config=MeetingConfig())
        assert mgr.get_clone("nonexistent") is None

    def test_manager_config_propagation(self) -> None:
        custom_voice = VoiceConfig(secs_threshold=0.99)
        cfg = MeetingConfig(voice=custom_voice)
        mgr = CloneMeetingManager(config=cfg)
        # Access internal config to verify propagation
        assert mgr._config.voice.secs_threshold == 0.99


class TestCloneInstance:

    def test_clone_instance_fields(self) -> None:
        """All required fields are present in CloneInstance dataclass."""
        fields = {f.name for f in dataclasses.fields(CloneInstance)}
        expected = {
            "clone_name",
            "meeting_id",
            "config",
            "clone_config",
            "transcript_store",
            "audio_capture",
            "transcriber",
            "address_detector",
            "responder",
            "voice_output",
            "behavior",
            "device_manager",
            "summary_generator",
            "recent_segments",
            "_running",
            "_flush_task",
        }
        for field_name in expected:
            assert field_name in fields, f"Missing field: {field_name}"
