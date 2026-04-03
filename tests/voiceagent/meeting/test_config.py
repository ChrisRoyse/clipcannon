"""Tests for voiceagent.meeting.config -- real objects, no mocks."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from voiceagent.errors import ConfigError
from voiceagent.meeting.config import (
    AudioCaptureConfig,
    BehaviorConfig,
    BotJoinConfig,
    BrowserBotConfig,
    CloneConfig,
    DiarizationConfig,
    LipSyncConfig,
    MeetingConfig,
    ResponseConfig,
    TranscriptConfig,
    TranscriptionConfig,
    VoiceConfig,
    ZoomSdkConfig,
    load_meeting_config,
)


class TestDefaultConfig:
    """Verify MeetingConfig() has correct defaults across all sub-configs."""

    def test_default_config(self) -> None:
        cfg = MeetingConfig()
        assert isinstance(cfg.clones, dict) and len(cfg.clones) == 0
        assert isinstance(cfg.audio_capture, AudioCaptureConfig)
        assert isinstance(cfg.transcription, TranscriptionConfig)
        assert isinstance(cfg.diarization, DiarizationConfig)
        assert isinstance(cfg.voice, VoiceConfig)
        assert isinstance(cfg.lip_sync, LipSyncConfig)
        assert isinstance(cfg.response, ResponseConfig)
        assert isinstance(cfg.transcript, TranscriptConfig)
        assert isinstance(cfg.behavior, BehaviorConfig)
        assert isinstance(cfg.bot_join, BotJoinConfig)

    def test_secs_threshold_default(self) -> None:
        cfg = MeetingConfig()
        assert cfg.voice.secs_threshold == 0.95

    def test_fps_default(self) -> None:
        cfg = MeetingConfig()
        assert cfg.lip_sync.output_fps == 30
        assert cfg.lip_sync.idle_fps == 30

    def test_ocr_provenance_url(self) -> None:
        cfg = MeetingConfig()
        assert cfg.transcript.ocr_provenance_url == "http://localhost:3377/mcp"

    def test_bot_join_defaults(self) -> None:
        cfg = MeetingConfig()
        assert cfg.bot_join.enabled is False
        assert cfg.bot_join.default_display_name == "AI Notes"
        assert isinstance(cfg.bot_join.zoom_sdk, ZoomSdkConfig)
        assert isinstance(cfg.bot_join.browser_bot, BrowserBotConfig)

    def test_behavior_defaults(self) -> None:
        cfg = MeetingConfig()
        assert cfg.behavior.default_muted is True
        assert cfg.behavior.unmute_before_speak_ms == 200
        assert cfg.behavior.mute_after_speak_ms == 300
        assert cfg.behavior.comfort_noise_dbfs == -60


class TestLoadFromFile:
    """Verify config loading from JSON files."""

    def test_load_from_json(self) -> None:
        data = {
            "voice": {"secs_threshold": 0.97, "secs_candidates_max": 3},
            "lip_sync": {"output_fps": 25, "idle_fps": 15},
            "clones": {
                "nate": {
                    "voice_profile": "boris",
                    "aliases": ["Nate", "Nathan"],
                    "address_threshold": 0.85,
                }
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(data, f)
            f.flush()
            cfg = load_meeting_config(f.name)

        assert cfg.voice.secs_threshold == 0.97
        assert cfg.voice.secs_candidates_max == 3
        assert cfg.lip_sync.output_fps == 25
        assert cfg.lip_sync.idle_fps == 15
        assert "nate" in cfg.clones
        assert cfg.clones["nate"].voice_profile == "boris"
        assert cfg.clones["nate"].aliases == ["Nate", "Nathan"]
        Path(f.name).unlink()

    def test_load_nested_bot_join(self) -> None:
        data = {
            "bot_join": {
                "enabled": True,
                "default_display_name": "Clone Bot",
                "zoom_sdk": {
                    "client_id": "test_id",
                    "client_secret": "test_secret",
                },
                "browser_bot": {
                    "headless": False,
                    "chromium_path": "/usr/bin/chromium",
                },
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(data, f)
            f.flush()
            cfg = load_meeting_config(f.name)

        assert cfg.bot_join.enabled is True
        assert cfg.bot_join.default_display_name == "Clone Bot"
        assert cfg.bot_join.zoom_sdk.client_id == "test_id"
        assert cfg.bot_join.zoom_sdk.client_secret == "test_secret"
        assert cfg.bot_join.browser_bot.headless is False
        assert cfg.bot_join.browser_bot.chromium_path == "/usr/bin/chromium"
        Path(f.name).unlink()

    def test_invalid_json(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            f.write("{broken json!!!")
            f.flush()
            with pytest.raises(ConfigError, match="Invalid JSON"):
                load_meeting_config(f.name)
        Path(f.name).unlink()

    def test_range_validation(self) -> None:
        data = {"voice": {"secs_threshold": 1.5}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(data, f)
            f.flush()
            with pytest.raises(ConfigError, match="out of range"):
                load_meeting_config(f.name)
        Path(f.name).unlink()

    def test_missing_file(self) -> None:
        cfg = load_meeting_config("/tmp/does_not_exist_meeting_cfg.json")
        # Missing file returns defaults
        assert cfg.voice.secs_threshold == 0.95
        assert cfg.lip_sync.output_fps == 30
