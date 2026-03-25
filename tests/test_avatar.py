"""Tests for avatar lip-sync module.

Tests module structure, prerequisites validation, and tool dispatch.
Actual LatentSync inference requires 18GB VRAM and model loading,
so pipeline tests are gated behind model availability.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clipcannon.avatar.lip_sync import (
    LipSyncEngine,
    LipSyncResult,
    _CHECKPOINT_PATH,
    _LATENTSYNC_DIR,
    _WHISPER_TINY,
    _validate_prerequisites,
)
from clipcannon.tools.avatar import dispatch_avatar_tool
from clipcannon.tools.avatar_defs import AVATAR_TOOL_DEFINITIONS


class TestAvatarToolDefinitions:
    """Verify tool definitions are correct."""

    def test_tool_count(self) -> None:
        """Exactly 1 avatar tool defined."""
        assert len(AVATAR_TOOL_DEFINITIONS) == 1

    def test_lip_sync_tool_name(self) -> None:
        """Tool has correct name."""
        assert AVATAR_TOOL_DEFINITIONS[0].name == "clipcannon_lip_sync"

    def test_lip_sync_required_params(self) -> None:
        """Tool requires project_id, audio_path, driver_video_path."""
        schema = AVATAR_TOOL_DEFINITIONS[0].inputSchema
        assert set(schema["required"]) == {
            "project_id", "audio_path", "driver_video_path",
        }


class TestPrerequisites:
    """Test prerequisite validation."""

    def test_validate_with_real_models(self) -> None:
        """Prerequisites pass if models are downloaded."""
        if not _CHECKPOINT_PATH.exists():
            pytest.skip("LatentSync checkpoint not downloaded")
        # Should not raise
        _validate_prerequisites()

    def test_validate_missing_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing LatentSync dir raises FileNotFoundError."""
        import clipcannon.avatar.lip_sync as ls
        monkeypatch.setattr(ls, "_LATENTSYNC_DIR", tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError, match="LatentSync not found"):
            _validate_prerequisites()


class TestLipSyncEngine:
    """Test LipSyncEngine construction."""

    def test_engine_creation(self) -> None:
        """Engine creates without loading model."""
        engine = LipSyncEngine()
        assert engine._pipeline is None  # lazy load

    def test_generate_missing_video(self, tmp_path: Path) -> None:
        """generate() raises for missing video file."""
        if not _CHECKPOINT_PATH.exists():
            pytest.skip("LatentSync checkpoint not downloaded")
        engine = LipSyncEngine()
        with pytest.raises(FileNotFoundError, match="Driver video not found"):
            engine.generate(
                video_path=tmp_path / "nonexistent.mp4",
                audio_path=tmp_path / "audio.wav",
                output_path=tmp_path / "out.mp4",
            )

    def test_generate_missing_audio(self, tmp_path: Path) -> None:
        """generate() raises for missing audio file."""
        if not _CHECKPOINT_PATH.exists():
            pytest.skip("LatentSync checkpoint not downloaded")
        # Create a dummy video file
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00" * 100)
        engine = LipSyncEngine()
        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            engine.generate(
                video_path=video,
                audio_path=tmp_path / "nonexistent.wav",
                output_path=tmp_path / "out.mp4",
            )


class TestAvatarToolDispatch:
    """Test MCP tool dispatch."""

    @pytest.mark.asyncio()
    async def test_missing_project_id(self) -> None:
        """Missing project_id returns error."""
        result = await dispatch_avatar_tool(
            "clipcannon_lip_sync",
            {"audio_path": "/tmp/a.wav", "driver_video_path": "/tmp/v.mp4"},
        )
        assert "error" in result

    @pytest.mark.asyncio()
    async def test_missing_audio_path(self) -> None:
        """Missing audio_path returns error."""
        result = await dispatch_avatar_tool(
            "clipcannon_lip_sync",
            {"project_id": "proj_test", "driver_video_path": "/tmp/v.mp4"},
        )
        assert "error" in result

    @pytest.mark.asyncio()
    async def test_nonexistent_audio_file(self) -> None:
        """Non-existent audio file returns FILE_NOT_FOUND error."""
        result = await dispatch_avatar_tool(
            "clipcannon_lip_sync",
            {
                "project_id": "proj_test",
                "audio_path": "/tmp/nonexistent_fsv_audio.wav",
                "driver_video_path": "/tmp/nonexistent_fsv_video.mp4",
            },
        )
        assert "error" in result
        assert result["error"]["code"] == "FILE_NOT_FOUND"

    @pytest.mark.asyncio()
    async def test_unknown_tool(self) -> None:
        """Unknown tool name returns error."""
        result = await dispatch_avatar_tool("clipcannon_unknown", {})
        assert "error" in result
        assert result["error"]["code"] == "INTERNAL_ERROR"
