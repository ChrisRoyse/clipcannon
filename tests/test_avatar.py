"""Tests for avatar lip-sync and webcam extraction modules.

Tests module structure, prerequisites validation, tool dispatch,
and webcam extraction logic.

Actual LatentSync inference requires 18GB VRAM and model loading,
so pipeline tests are gated behind model availability.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from clipcannon.avatar.lip_sync import (
    LipSyncEngine,
    LipSyncResult,
    _CHECKPOINT_PATH,
    _LATENTSYNC_DIR,
    _MASK_PATH,
    _WHISPER_TINY,
    _validate_prerequisites,
)
from clipcannon.tools.avatar import (
    _get_source_info,
    _get_webcam_region,
    dispatch_avatar_tool,
)
from clipcannon.tools.avatar_defs import AVATAR_TOOL_DEFINITIONS


class TestAvatarToolDefinitions:
    """Verify tool definitions are correct."""

    def test_tool_count(self) -> None:
        """Exactly 2 avatar tools defined (lip_sync + extract_webcam)."""
        assert len(AVATAR_TOOL_DEFINITIONS) == 2

    def test_lip_sync_tool_name(self) -> None:
        """Lip sync tool has correct name."""
        names = [t.name for t in AVATAR_TOOL_DEFINITIONS]
        assert "clipcannon_lip_sync" in names

    def test_extract_webcam_tool_name(self) -> None:
        """Extract webcam tool has correct name."""
        names = [t.name for t in AVATAR_TOOL_DEFINITIONS]
        assert "clipcannon_extract_webcam" in names

    def test_lip_sync_required_params(self) -> None:
        """Lip sync tool requires project_id, audio_path, driver_video_path."""
        tool = next(t for t in AVATAR_TOOL_DEFINITIONS if t.name == "clipcannon_lip_sync")
        assert set(tool.inputSchema["required"]) == {
            "project_id", "audio_path", "driver_video_path",
        }

    def test_extract_webcam_required_params(self) -> None:
        """Extract webcam tool requires only project_id."""
        tool = next(t for t in AVATAR_TOOL_DEFINITIONS if t.name == "clipcannon_extract_webcam")
        assert tool.inputSchema["required"] == ["project_id"]

    def test_lip_sync_has_guidance_scale(self) -> None:
        """Lip sync tool exposes guidance_scale parameter."""
        tool = next(t for t in AVATAR_TOOL_DEFINITIONS if t.name == "clipcannon_lip_sync")
        assert "guidance_scale" in tool.inputSchema["properties"]

    def test_extract_webcam_has_padding(self) -> None:
        """Extract webcam tool has padding_pct parameter."""
        tool = next(t for t in AVATAR_TOOL_DEFINITIONS if t.name == "clipcannon_extract_webcam")
        assert "padding_pct" in tool.inputSchema["properties"]


class TestPrerequisites:
    """Test prerequisite validation."""

    def test_validate_with_real_models(self) -> None:
        """Prerequisites pass if models are downloaded."""
        if not _CHECKPOINT_PATH.exists():
            pytest.skip("LatentSync checkpoint not downloaded")
        _validate_prerequisites()

    def test_validate_missing_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing LatentSync dir raises FileNotFoundError."""
        import clipcannon.avatar.lip_sync as ls
        monkeypatch.setattr(ls, "_LATENTSYNC_DIR", tmp_path / "nonexistent")
        with pytest.raises(FileNotFoundError, match="LatentSync not found"):
            _validate_prerequisites()

    def test_validate_missing_checkpoint(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing checkpoint raises FileNotFoundError with download instructions."""
        import clipcannon.avatar.lip_sync as ls
        monkeypatch.setattr(ls, "_LATENTSYNC_DIR", tmp_path)
        monkeypatch.setattr(ls, "_CHECKPOINT_PATH", tmp_path / "checkpoints" / "missing.pt")
        monkeypatch.setattr(ls, "_CONFIG_PATH", tmp_path / "configs" / "unet" / "stage2_512.yaml")
        tmp_path.mkdir(exist_ok=True)
        with pytest.raises(FileNotFoundError, match="UNet checkpoint not found"):
            _validate_prerequisites()

    def test_validate_missing_mask(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing mask raises FileNotFoundError."""
        import clipcannon.avatar.lip_sync as ls
        # Create all prerequisites except mask
        monkeypatch.setattr(ls, "_LATENTSYNC_DIR", tmp_path)
        monkeypatch.setattr(ls, "_CHECKPOINT_PATH", tmp_path / "ckpt.pt")
        monkeypatch.setattr(ls, "_WHISPER_TINY", tmp_path / "whisper.pt")
        monkeypatch.setattr(ls, "_CONFIG_PATH", tmp_path / "config.yaml")
        monkeypatch.setattr(ls, "_MASK_PATH", tmp_path / "mask.png")
        (tmp_path / "ckpt.pt").write_bytes(b"\x00")
        (tmp_path / "whisper.pt").write_bytes(b"\x00")
        (tmp_path / "config.yaml").write_text("data: {}")
        with pytest.raises(FileNotFoundError, match="mask image not found"):
            _validate_prerequisites()


class TestLipSyncEngine:
    """Test LipSyncEngine construction."""

    def test_engine_creation(self) -> None:
        """Engine creates without loading model."""
        engine = LipSyncEngine()
        assert engine._pipeline is None  # lazy load

    def test_engine_deepcache_default(self) -> None:
        """DeepCache is enabled by default."""
        engine = LipSyncEngine()
        assert engine._enable_deepcache is True

    def test_engine_deepcache_disabled(self) -> None:
        """DeepCache can be disabled."""
        engine = LipSyncEngine(enable_deepcache=False)
        assert engine._enable_deepcache is False

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
        video = tmp_path / "video.mp4"
        video.write_bytes(b"\x00" * 100)
        engine = LipSyncEngine()
        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            engine.generate(
                video_path=video,
                audio_path=tmp_path / "nonexistent.wav",
                output_path=tmp_path / "out.mp4",
            )

    def test_unload(self) -> None:
        """unload() clears pipeline without error."""
        engine = LipSyncEngine()
        engine.unload()
        assert engine._pipeline is None
        assert engine._deepcache_helper is None


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

    @pytest.mark.asyncio()
    async def test_extract_webcam_missing_project(self) -> None:
        """Extract webcam with missing project returns error."""
        result = await dispatch_avatar_tool(
            "clipcannon_extract_webcam",
            {"project_id": ""},
        )
        assert "error" in result
        assert result["error"]["code"] == "MISSING_PARAMETER"

    @pytest.mark.asyncio()
    async def test_extract_webcam_nonexistent_project(self) -> None:
        """Extract webcam with non-existent project returns error."""
        result = await dispatch_avatar_tool(
            "clipcannon_extract_webcam",
            {"project_id": "proj_nonexistent_12345"},
        )
        assert "error" in result
        assert result["error"]["code"] == "PROJECT_NOT_FOUND"


class TestWebcamRegionExtraction:
    """Test webcam region detection from scene_map data."""

    def _create_scene_map_db(self, db_path: Path, project_id: str,
                              scenes: list[dict]) -> None:
        """Create a test DB with scene_map entries."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project (
                project_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_cfr_path TEXT,
                resolution TEXT NOT NULL,
                duration_ms INTEGER NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO project (project_id, source_path, resolution, duration_ms) "
            "VALUES (?, ?, ?, ?)",
            (project_id, "/fake/source.mp4", "2560x1440", 60000),
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scene_map (
                scene_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                face_x INTEGER, face_y INTEGER,
                face_w INTEGER, face_h INTEGER,
                face_confidence REAL,
                webcam_x INTEGER, webcam_y INTEGER,
                webcam_w INTEGER, webcam_h INTEGER,
                content_x INTEGER, content_y INTEGER,
                content_w INTEGER, content_h INTEGER,
                content_type TEXT DEFAULT 'unknown',
                visible_text TEXT DEFAULT '[]',
                layout_recommendation TEXT DEFAULT 'A',
                canvas_regions_json TEXT DEFAULT '{}',
                transcript_text TEXT DEFAULT ''
            )
        """)
        for scene in scenes:
            conn.execute(
                "INSERT INTO scene_map (project_id, start_ms, end_ms, "
                "face_x, face_y, face_w, face_h, face_confidence, "
                "webcam_x, webcam_y, webcam_w, webcam_h, "
                "content_x, content_y, content_w, content_h) "
                "VALUES (?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?,?)",
                (
                    project_id, scene.get("start_ms", 0), scene.get("end_ms", 5000),
                    scene.get("face_x"), scene.get("face_y"),
                    scene.get("face_w"), scene.get("face_h"),
                    scene.get("face_confidence"),
                    scene.get("webcam_x"), scene.get("webcam_y"),
                    scene.get("webcam_w"), scene.get("webcam_h"),
                    scene.get("content_x", 0), scene.get("content_y", 0),
                    scene.get("content_w", 1920), scene.get("content_h", 1080),
                ),
            )
        conn.commit()
        conn.close()

    def test_webcam_region_from_explicit_webcam(self, tmp_path: Path) -> None:
        """Finds webcam region when webcam_x/y/w/h are stored."""
        db_path = tmp_path / "analysis.db"
        self._create_scene_map_db(db_path, "proj_1", [
            {"webcam_x": 1800, "webcam_y": 900, "webcam_w": 400, "webcam_h": 350},
            {"webcam_x": 1810, "webcam_y": 910, "webcam_w": 410, "webcam_h": 360},
        ])
        region = _get_webcam_region(db_path, "proj_1")
        assert region is not None
        assert region["x"] == 1805  # median
        assert region["w"] == 405

    def test_webcam_region_from_face(self, tmp_path: Path) -> None:
        """Falls back to face bbox when no explicit webcam region."""
        db_path = tmp_path / "analysis.db"
        self._create_scene_map_db(db_path, "proj_1", [
            {"face_x": 100, "face_y": 50, "face_w": 200, "face_h": 250,
             "face_confidence": 0.95},
        ])
        region = _get_webcam_region(db_path, "proj_1")
        assert region is not None
        assert region["w"] > 200  # expanded from face

    def test_webcam_region_no_faces(self, tmp_path: Path) -> None:
        """Returns None when no faces detected."""
        db_path = tmp_path / "analysis.db"
        self._create_scene_map_db(db_path, "proj_1", [
            {"content_x": 0, "content_y": 0, "content_w": 2560, "content_h": 1440},
        ])
        region = _get_webcam_region(db_path, "proj_1")
        assert region is None

    def test_source_info(self, tmp_path: Path) -> None:
        """Gets source video info from project table."""
        db_path = tmp_path / "analysis.db"
        self._create_scene_map_db(db_path, "proj_1", [])
        info = _get_source_info(db_path, "proj_1")
        assert info is not None
        assert info["width"] == 2560
        assert info["height"] == 1440
        assert info["duration_ms"] == 60000

    def test_source_info_missing_project(self, tmp_path: Path) -> None:
        """Returns None for missing project."""
        db_path = tmp_path / "analysis.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project (
                project_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_cfr_path TEXT,
                resolution TEXT NOT NULL,
                duration_ms INTEGER NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        info = _get_source_info(db_path, "nonexistent")
        assert info is None


class TestGenerateToolDefs:
    """Test generate_video tool definitions."""

    def test_driver_video_not_required(self) -> None:
        """driver_video_path is not in required params (auto-extract supported)."""
        from clipcannon.tools.generate_defs import GENERATE_TOOL_DEFINITIONS

        tool = GENERATE_TOOL_DEFINITIONS[0]
        assert "driver_video_path" not in tool.inputSchema["required"]
        assert set(tool.inputSchema["required"]) == {"project_id", "script"}

    def test_guidance_scale_parameter(self) -> None:
        """generate_video exposes guidance_scale."""
        from clipcannon.tools.generate_defs import GENERATE_TOOL_DEFINITIONS

        tool = GENERATE_TOOL_DEFINITIONS[0]
        assert "guidance_scale" in tool.inputSchema["properties"]
