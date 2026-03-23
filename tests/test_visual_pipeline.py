"""Tests for visual pipeline stages.

Tests storyboard generation end-to-end with synthetic frames,
and verifies quality assessment with Laplacian fallback.
ML-dependent stages (visual_embed, ocr, shot_type) are tested
for import correctness and graceful failure handling.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from clipcannon.config import ClipCannonConfig
from clipcannon.db.schema import create_project_db, init_project_directory
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.pipeline.orchestrator import StageResult


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def tmp_project(tmp_path: Path) -> tuple[str, Path, Path]:
    """Create a temporary project with synthetic frames.

    Returns:
        Tuple of (project_id, db_path, project_dir).
    """
    project_id = "test_visual_001"
    project_dir = tmp_path / project_id

    # Initialize project directory and database
    db_path = create_project_db(project_id, base_dir=tmp_path)

    # Create subdirectories
    frames_dir = project_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    storyboard_dir = project_dir / "storyboards"
    storyboard_dir.mkdir(parents=True, exist_ok=True)

    # Generate synthetic frames (20 frames at 2fps = 10 seconds)
    num_frames = 20
    for i in range(1, num_frames + 1):
        frame_path = frames_dir / f"frame_{i:06d}.jpg"
        # Create colored frames that change every 5 frames (scene change)
        if i <= 5:
            color = (255, 0, 0)  # Red scene
        elif i <= 10:
            color = (0, 255, 0)  # Green scene
        elif i <= 15:
            color = (0, 0, 255)  # Blue scene
        else:
            color = (255, 255, 0)  # Yellow scene

        img = Image.new("RGB", (640, 480), color=color)
        # Add some variation within scenes
        for x in range(0, 640, 64):
            for y in range(0, 480, 64):
                variation = ((i * 17 + x * 3 + y * 7) % 50) - 25
                r = max(0, min(255, color[0] + variation))
                g = max(0, min(255, color[1] + variation))
                b = max(0, min(255, color[2] + variation))
                img.putpixel((x, y), (r, g, b))

        img.save(str(frame_path), "JPEG", quality=80)

    # Insert project metadata
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        execute(
            conn,
            "INSERT INTO project (project_id, name, source_path, "
            "source_sha256, duration_ms, resolution, fps, codec) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id, "Test Visual", "/tmp/test.mp4",
                "abc123", 10000, "640x480", 30.0, "h264",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return project_id, db_path, project_dir


@pytest.fixture
def config() -> ClipCannonConfig:
    """Create a test configuration."""
    data = {
        "version": "1.0",
        "directories": {
            "projects": "/tmp/clipcannon_test/projects",
            "models": "/tmp/clipcannon_test/models",
            "temp": "/tmp/clipcannon_test/tmp",
        },
        "processing": {
            "frame_extraction_fps": 2,
            "whisper_model": "large-v3",
            "whisper_compute_type": "int8",
            "batch_size_visual": 64,
            "scene_change_threshold": 0.85,
            "highlight_count_default": 20,
            "min_clip_duration_ms": 5000,
            "max_clip_duration_ms": 600000,
        },
        "rendering": {
            "default_profile": "youtube_standard",
            "use_nvenc": False,
            "nvenc_preset": "p4",
            "caption_default_style": "bold_centered",
            "thumbnail_format": "jpg",
            "thumbnail_quality": 95,
        },
        "publishing": {
            "require_approval": True,
            "max_daily_posts_per_platform": 5,
        },
        "gpu": {
            "device": "cpu",
            "max_vram_usage_gb": 24,
            "concurrent_models": True,
        },
    }
    return ClipCannonConfig(data, config_path=Path("/tmp/test_config.json"))


# ============================================================
# STORYBOARD TESTS
# ============================================================


class TestStoryboard:
    """Tests for storyboard grid generation."""

    def test_storyboard_generates_grids(
        self,
        tmp_project: tuple[str, Path, Path],
        config: ClipCannonConfig,
    ) -> None:
        """Verify storyboard creates grid images on disk."""
        from clipcannon.pipeline.storyboard import run_storyboard

        project_id, db_path, project_dir = tmp_project
        result = asyncio.run(
            run_storyboard(project_id, db_path, project_dir, config),
        )

        assert result.success is True
        assert result.operation == "storyboard_generation"
        assert result.provenance_record_id is not None

        # Check grid files exist on disk
        storyboard_dir = project_dir / "storyboards"
        grids = sorted(storyboard_dir.glob("grid_*.jpg"))
        assert len(grids) > 0, "No storyboard grid files generated"

        # With 20 frames at 9 per grid: ceil(20/9) = 3 grids
        assert len(grids) == 3

    def test_storyboard_grid_dimensions(
        self,
        tmp_project: tuple[str, Path, Path],
        config: ClipCannonConfig,
    ) -> None:
        """Verify generated grids have correct dimensions."""
        from clipcannon.pipeline.storyboard import run_storyboard

        project_id, db_path, project_dir = tmp_project
        asyncio.run(run_storyboard(project_id, db_path, project_dir, config))

        storyboard_dir = project_dir / "storyboards"
        first_grid = storyboard_dir / "grid_001.jpg"
        assert first_grid.exists()

        img = Image.open(first_grid)
        assert img.size == (1044, 1044)

    def test_storyboard_inserts_db_records(
        self,
        tmp_project: tuple[str, Path, Path],
        config: ClipCannonConfig,
    ) -> None:
        """Verify storyboard_grids table has correct records."""
        from clipcannon.pipeline.storyboard import run_storyboard

        project_id, db_path, project_dir = tmp_project
        asyncio.run(run_storyboard(project_id, db_path, project_dir, config))

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT * FROM storyboard_grids WHERE project_id = ? "
                "ORDER BY grid_number",
                (project_id,),
            )
        finally:
            conn.close()

        assert len(rows) == 3

        # Verify first grid
        first = rows[0]
        assert first["grid_number"] == 1
        assert first["project_id"] == project_id
        assert "grid_001.jpg" in str(first["grid_path"])

        # Verify timestamps are valid JSON
        ts_data = json.loads(str(first["cell_timestamps_ms"]))
        assert isinstance(ts_data, list)
        assert len(ts_data) == 9  # Full grid of 9

        # Last grid should have fewer frames (20 - 18 = 2)
        last = rows[2]
        ts_last = json.loads(str(last["cell_timestamps_ms"]))
        assert len(ts_last) == 2

    def test_storyboard_writes_provenance(
        self,
        tmp_project: tuple[str, Path, Path],
        config: ClipCannonConfig,
    ) -> None:
        """Verify provenance record is written."""
        from clipcannon.pipeline.storyboard import run_storyboard

        project_id, db_path, project_dir = tmp_project
        result = asyncio.run(
            run_storyboard(project_id, db_path, project_dir, config),
        )

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT * FROM provenance WHERE project_id = ? "
                "AND operation = ?",
                (project_id, "storyboard_generation"),
            )
        finally:
            conn.close()

        assert row is not None
        assert row["stage"] == "storyboard_grids"
        assert row["record_id"] == result.provenance_record_id

    def test_storyboard_no_frames(
        self,
        tmp_path: Path,
        config: ClipCannonConfig,
    ) -> None:
        """Verify graceful failure when no frames exist."""
        from clipcannon.pipeline.storyboard import run_storyboard

        project_id = "test_empty_001"
        db_path = create_project_db(project_id, base_dir=tmp_path)
        project_dir = tmp_path / project_id
        (project_dir / "frames").mkdir(parents=True, exist_ok=True)

        result = asyncio.run(
            run_storyboard(project_id, db_path, project_dir, config),
        )

        assert result.success is False
        assert "No frames found" in (result.error_message or "")

    def test_format_timestamp(self) -> None:
        """Verify timestamp formatting."""
        from clipcannon.pipeline.storyboard import _format_timestamp

        assert _format_timestamp(0) == "0:00"
        assert _format_timestamp(5000) == "0:05"
        assert _format_timestamp(65000) == "1:05"
        assert _format_timestamp(3661000) == "1:01:01"

    def test_select_frames_under_limit(self) -> None:
        """Verify all frames returned when under 720 limit."""
        from clipcannon.pipeline.storyboard import _select_frames

        frames = [Path(f"frame_{i:06d}.jpg") for i in range(1, 101)]
        selected = _select_frames(frames, 50000, 2)
        assert len(selected) == 100

    def test_select_frames_over_limit(self) -> None:
        """Verify frame subsampling when over 720 limit."""
        from clipcannon.pipeline.storyboard import _select_frames

        frames = [Path(f"frame_{i:06d}.jpg") for i in range(1, 2001)]
        selected = _select_frames(frames, 1000000, 2)
        assert len(selected) <= 720


# ============================================================
# QUALITY ASSESSMENT TESTS
# ============================================================


class TestQuality:
    """Tests for quality assessment stage."""

    def test_brisque_to_quality_conversion(self) -> None:
        """Verify BRISQUE to 0-100 conversion formula."""
        from clipcannon.pipeline.quality import _brisque_to_quality

        assert _brisque_to_quality(0.0) == 100.0
        assert _brisque_to_quality(50.0) == 50.0
        assert _brisque_to_quality(100.0) == 0.0
        assert _brisque_to_quality(-10.0) == 100.0  # Clamped
        assert _brisque_to_quality(150.0) == 0.0  # Clamped

    def test_quality_classification(self) -> None:
        """Verify quality classification thresholds."""
        from clipcannon.pipeline.quality import _classify_quality

        assert _classify_quality(80.0) == "good"
        assert _classify_quality(50.0) == "acceptable"
        assert _classify_quality(30.0) == "poor"
        assert _classify_quality(60.1) == "good"
        assert _classify_quality(40.0) == "poor"

    def test_detect_issues_blur(self) -> None:
        """Verify heavy blur detection."""
        from clipcannon.pipeline.quality import _detect_issues

        issues = _detect_issues([20.0, 25.0, 15.0])
        assert "heavy_blur" in issues

    def test_detect_issues_camera_shake(self) -> None:
        """Verify camera shake detection from high variance."""
        from clipcannon.pipeline.quality import _detect_issues

        scores = [80.0, 30.0, 85.0, 25.0, 90.0]
        issues = _detect_issues(scores)
        assert "camera_shake" in issues

    def test_detect_issues_clean(self) -> None:
        """Verify no issues for good stable footage."""
        from clipcannon.pipeline.quality import _detect_issues

        issues = _detect_issues([75.0, 77.0, 76.0, 78.0])
        assert len(issues) == 0

    def test_laplacian_fallback(
        self,
        tmp_project: tuple[str, Path, Path],
        config: ClipCannonConfig,
    ) -> None:
        """Verify Laplacian fallback produces reasonable scores."""
        from clipcannon.pipeline.quality import _run_laplacian_fallback

        project_id, db_path, project_dir = tmp_project
        frames = sorted((project_dir / "frames").glob("frame_*.jpg"))

        scores = _run_laplacian_fallback(frames[:5])
        assert len(scores) == 5
        for score in scores:
            assert 0.0 <= score <= 100.0

    def test_quality_with_scenes(
        self,
        tmp_project: tuple[str, Path, Path],
        config: ClipCannonConfig,
    ) -> None:
        """Verify quality updates scene records when scenes exist."""
        from clipcannon.pipeline.quality import run_quality

        project_id, db_path, project_dir = tmp_project

        # Insert a couple of test scenes first
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            execute(
                conn,
                "INSERT INTO scenes (project_id, start_ms, end_ms, "
                "key_frame_path, key_frame_timestamp_ms) VALUES (?, ?, ?, ?, ?)",
                (project_id, 0, 5000,
                 str(project_dir / "frames" / "frame_000001.jpg"), 0),
            )
            execute(
                conn,
                "INSERT INTO scenes (project_id, start_ms, end_ms, "
                "key_frame_path, key_frame_timestamp_ms) VALUES (?, ?, ?, ?, ?)",
                (project_id, 5000, 10000,
                 str(project_dir / "frames" / "frame_000011.jpg"), 5000),
            )
            conn.commit()
        finally:
            conn.close()

        result = asyncio.run(
            run_quality(project_id, db_path, project_dir, config),
        )

        assert result.success is True

        # Verify scenes were updated
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            scenes = fetch_all(
                conn,
                "SELECT quality_avg, quality_classification FROM scenes "
                "WHERE project_id = ?",
                (project_id,),
            )
        finally:
            conn.close()

        assert len(scenes) == 2
        for scene in scenes:
            assert scene["quality_avg"] is not None
            assert scene["quality_classification"] in (
                "good", "acceptable", "poor",
            )


# ============================================================
# VISUAL EMBED UNIT TESTS (no model download)
# ============================================================


class TestVisualEmbedHelpers:
    """Unit tests for visual embedding helper functions."""

    def test_cosine_similarity_identical(self) -> None:
        """Verify cosine similarity of identical vectors is 1.0."""
        from clipcannon.pipeline.visual_embed import _cosine_similarity

        vec = [1.0, 2.0, 3.0, 4.0]
        sim = _cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    def test_cosine_similarity_orthogonal(self) -> None:
        """Verify cosine similarity of orthogonal vectors is 0.0."""
        from clipcannon.pipeline.visual_embed import _cosine_similarity

        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        sim = _cosine_similarity(a, b)
        assert abs(sim) < 1e-6

    def test_frame_timestamp_ms(self) -> None:
        """Verify frame timestamp calculation."""
        from clipcannon.pipeline.frame_utils import frame_timestamp_ms

        assert frame_timestamp_ms(Path("frame_000001.jpg"), 2) == 0
        assert frame_timestamp_ms(Path("frame_000002.jpg"), 2) == 500
        assert frame_timestamp_ms(Path("frame_000003.jpg"), 2) == 1000

    def test_extract_dominant_colors(
        self, tmp_path: Path,
    ) -> None:
        """Verify dominant color extraction returns hex strings."""
        from clipcannon.pipeline.visual_embed import _extract_dominant_colors

        img = Image.new("RGB", (100, 100), color=(200, 50, 80))
        img_path = tmp_path / "test_color.jpg"
        img.save(str(img_path))

        colors = _extract_dominant_colors(img_path, num_colors=3)
        assert len(colors) > 0
        for c in colors:
            assert c.startswith("#")
            assert len(c) == 7

    def test_scene_detection_logic(self) -> None:
        """Verify scene boundary detection from embeddings."""
        from clipcannon.pipeline.visual_embed import _detect_scenes

        # Create 6 frames: 3 similar + 3 different
        frames = [Path(f"frame_{i:06d}.jpg") for i in range(1, 7)]

        # Similar embeddings for first 3, different for last 3
        emb_a = [1.0, 0.0, 0.0]
        emb_b = [0.0, 1.0, 0.0]  # Orthogonal = similarity 0

        embeddings = [emb_a, emb_a, emb_a, emb_b, emb_b, emb_b]

        scenes = _detect_scenes(frames, embeddings, fps=2, threshold=0.75)

        # Should detect at least 2 scenes (boundary at frame 4)
        assert len(scenes) >= 2


# ============================================================
# OCR UNIT TESTS
# ============================================================


class TestOCRHelpers:
    """Unit tests for OCR helper functions."""

    def test_classify_region_top(self) -> None:
        """Verify top region classification."""
        from clipcannon.pipeline.ocr import _classify_region

        bbox = [[0, 10], [200, 10], [200, 50], [0, 50]]
        result = _classify_region(bbox, 640, 480)
        assert result == "center_top"

    def test_classify_region_middle(self) -> None:
        """Verify middle region classification."""
        from clipcannon.pipeline.ocr import _classify_region

        bbox = [[0, 200], [200, 200], [200, 240], [0, 240]]
        result = _classify_region(bbox, 640, 480)
        assert result == "center_middle"

    def test_classify_region_bottom(self) -> None:
        """Verify bottom third region classification."""
        from clipcannon.pipeline.ocr import _classify_region

        bbox = [[0, 350], [200, 350], [200, 380], [0, 380]]
        result = _classify_region(bbox, 640, 480)
        assert result == "bottom_third"

    def test_estimate_font_size_small(self) -> None:
        """Verify small font size estimation."""
        from clipcannon.pipeline.ocr import _estimate_font_size

        bbox = [[0, 100], [100, 100], [100, 110], [0, 110]]  # 10px
        result = _estimate_font_size(bbox, 480)
        assert result == "small"

    def test_estimate_font_size_large(self) -> None:
        """Verify large font size estimation."""
        from clipcannon.pipeline.ocr import _estimate_font_size

        bbox = [[0, 100], [100, 100], [100, 200], [0, 200]]  # 100px
        result = _estimate_font_size(bbox, 480)
        assert result == "large"

    def test_texts_differ_significantly(self) -> None:
        """Verify text change detection."""
        from clipcannon.pipeline.ocr import _texts_differ_significantly

        assert _texts_differ_significantly([], ["new text"]) is True
        assert _texts_differ_significantly(["old"], []) is True
        assert _texts_differ_significantly(["same"], ["same"]) is False
        assert _texts_differ_significantly(
            ["A", "B", "C"], ["D", "E", "F"],
        ) is True
        assert _texts_differ_significantly(
            ["A", "B", "C"], ["A", "B", "D"],
        ) is False  # 2/4 overlap = 50%


# ============================================================
# SHOT TYPE UNIT TESTS
# ============================================================


class TestShotTypeHelpers:
    """Unit tests for shot type helper constants."""

    def test_crop_recommendations_complete(self) -> None:
        """Verify all shot types have crop recommendations."""
        from clipcannon.pipeline.shot_type import (
            CROP_RECOMMENDATIONS,
            SHOT_PROMPTS,
        )

        for _, label in SHOT_PROMPTS:
            assert label in CROP_RECOMMENDATIONS

    def test_shot_prompt_labels(self) -> None:
        """Verify expected shot type labels."""
        from clipcannon.pipeline.shot_type import SHOT_PROMPTS

        labels = [label for _, label in SHOT_PROMPTS]
        expected = [
            "extreme_closeup", "closeup", "medium", "wide", "establishing",
        ]
        assert labels == expected


# ============================================================
# INTEGRATION: MODULE IMPORTS
# ============================================================


class TestModuleImports:
    """Verify all visual pipeline modules import correctly."""

    def test_import_visual_embed(self) -> None:
        """Verify visual_embed module imports."""
        from clipcannon.pipeline.visual_embed import (
            OPERATION,
            STAGE,
            run_visual_embed,
        )
        assert OPERATION == "visual_embedding"
        assert callable(run_visual_embed)

    def test_import_ocr(self) -> None:
        """Verify ocr module imports."""
        from clipcannon.pipeline.ocr import OPERATION, STAGE, run_ocr
        assert OPERATION == "ocr_detection"
        assert callable(run_ocr)

    def test_import_quality(self) -> None:
        """Verify quality module imports."""
        from clipcannon.pipeline.quality import OPERATION, STAGE, run_quality
        assert OPERATION == "quality_assessment"
        assert callable(run_quality)

    def test_import_shot_type(self) -> None:
        """Verify shot_type module imports."""
        from clipcannon.pipeline.shot_type import (
            OPERATION,
            STAGE,
            run_shot_type,
        )
        assert OPERATION == "shot_type_classification"
        assert callable(run_shot_type)

    def test_import_storyboard(self) -> None:
        """Verify storyboard module imports."""
        from clipcannon.pipeline.storyboard import (
            OPERATION,
            STAGE,
            run_storyboard,
        )
        assert OPERATION == "storyboard_generation"
        assert callable(run_storyboard)

    def test_pipeline_init_exports(self) -> None:
        """Verify pipeline __init__ exports all visual stages."""
        from clipcannon.pipeline import (
            run_ocr,
            run_quality,
            run_shot_type,
            run_storyboard,
            run_visual_embed,
        )
        assert callable(run_visual_embed)
        assert callable(run_ocr)
        assert callable(run_quality)
        assert callable(run_shot_type)
        assert callable(run_storyboard)
