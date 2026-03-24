"""Tests for the change impact classifier.

Tests cover the full classification matrix:
- Name-only changes (no invalidation)
- Caption style changes (captions only)
- Global color changes (all segments + captions)
- Per-segment speed changes (specific segments + captions + audio)
- Segment addition/removal (all + captions + audio)
- Overlay changes (specific segments only)
- Per-segment canvas changes (specific segments + captions)
- Motion changes (specific segments only)
- Metadata changes (no invalidation)
- Audio changes (audio only)
- Render settings changes (all segments)
- Global canvas changes (all + captions)
- Crop changes (all + captions)
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from clipcannon.editing.change_classifier import RenderHint, classify_changes
from clipcannon.editing.edl import (
    AudioSpec,
    CanvasRegion,
    CanvasSpec,
    CaptionSpec,
    ColorSpec,
    CropSpec,
    EditDecisionList,
    MetadataSpec,
    MotionSpec,
    OverlaySpec,
    RenderSettingsSpec,
    SegmentCanvasSpec,
    SegmentSpec,
)


# ============================================================
# FIXTURES
# ============================================================
def _make_segment(
    segment_id: int,
    start_ms: int,
    end_ms: int,
    output_start_ms: int = 0,
    speed: float = 1.0,
    **kwargs: object,
) -> SegmentSpec:
    """Build a SegmentSpec with sensible defaults.

    Args:
        segment_id: 1-based segment ID.
        start_ms: Source start in ms.
        end_ms: Source end in ms.
        output_start_ms: Output start in ms.
        speed: Playback speed.
        **kwargs: Additional SegmentSpec fields.

    Returns:
        SegmentSpec instance.
    """
    return SegmentSpec(
        segment_id=segment_id,
        source_start_ms=start_ms,
        source_end_ms=end_ms,
        output_start_ms=output_start_ms,
        speed=speed,
        **kwargs,
    )


def _make_edl(**overrides: object) -> EditDecisionList:
    """Build a minimal EDL with sensible defaults.

    Args:
        **overrides: Fields to override on the EDL.

    Returns:
        EditDecisionList instance.
    """
    defaults: dict[str, object] = {
        "edit_id": "edit_test01",
        "project_id": "proj_test01",
        "name": "Test Edit",
        "target_platform": "tiktok",
        "target_profile": "tiktok_vertical",
        "source_sha256": "a" * 64,
        "segments": [
            _make_segment(1, 0, 5000, output_start_ms=0),
            _make_segment(2, 6000, 11000, output_start_ms=5000),
            _make_segment(3, 15000, 20000, output_start_ms=10000),
            _make_segment(4, 25000, 32000, output_start_ms=15000),
        ],
    }
    defaults.update(overrides)
    return EditDecisionList(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def base_edl() -> EditDecisionList:
    """A 4-segment base EDL for change classification tests."""
    return _make_edl()


# ============================================================
# RENDER HINT MODEL
# ============================================================
class TestRenderHintModel:
    """Verify RenderHint Pydantic model defaults."""

    def test_defaults(self) -> None:
        """Default hint has nothing invalidated."""
        hint = RenderHint()
        assert hint.segments_invalidated == []
        assert hint.all_segments_invalidated is False
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is False

    def test_serialization(self) -> None:
        """RenderHint round-trips through JSON."""
        hint = RenderHint(
            segments_invalidated=[1, 3],
            captions_invalidated=True,
        )
        data = hint.model_dump()
        assert data["segments_invalidated"] == [1, 3]
        assert data["captions_invalidated"] is True
        assert data["audio_invalidated"] is False

        restored = RenderHint(**data)
        assert restored == hint


# ============================================================
# NAME CHANGE
# ============================================================
class TestNameChangeNoInvalidation:
    """Name-only changes should not invalidate anything."""

    def test_name_change_no_invalidation(self, base_edl: EditDecisionList) -> None:
        """Changing only the name produces an empty render hint."""
        new_edl = deepcopy(base_edl)
        new_edl.name = "Renamed Edit"

        hint = classify_changes(base_edl, new_edl)

        assert hint.segments_invalidated == []
        assert hint.all_segments_invalidated is False
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is False


# ============================================================
# CAPTION STYLE CHANGE
# ============================================================
class TestCaptionStyleChange:
    """Caption changes should only invalidate captions."""

    def test_caption_style_change(self, base_edl: EditDecisionList) -> None:
        """Changing caption style invalidates captions only."""
        new_edl = deepcopy(base_edl)
        new_edl.captions = CaptionSpec(
            enabled=True,
            style="karaoke",
            font_size=72,
            color="#FF0000",
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.segments_invalidated == []
        assert hint.all_segments_invalidated is False
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is False

    def test_caption_disable(self, base_edl: EditDecisionList) -> None:
        """Disabling captions invalidates captions only."""
        new_edl = deepcopy(base_edl)
        new_edl.captions = CaptionSpec(enabled=False)

        hint = classify_changes(base_edl, new_edl)

        assert hint.captions_invalidated is True
        assert hint.all_segments_invalidated is False
        assert hint.audio_invalidated is False


# ============================================================
# GLOBAL COLOR CHANGE
# ============================================================
class TestGlobalColorChange:
    """Global color changes invalidate all segments + captions."""

    def test_global_color_change(self, base_edl: EditDecisionList) -> None:
        """Adding global color invalidates all segments and captions."""
        new_edl = deepcopy(base_edl)
        new_edl.color = ColorSpec(brightness=0.3, contrast=1.5)

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is True
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is False

    def test_global_color_removal(self) -> None:
        """Removing global color invalidates all segments and captions."""
        old_edl = _make_edl(color=ColorSpec(saturation=2.0))
        new_edl = deepcopy(old_edl)
        new_edl.color = None

        hint = classify_changes(old_edl, new_edl)

        assert hint.all_segments_invalidated is True
        assert hint.captions_invalidated is True


# ============================================================
# SEGMENT SPEED CHANGE
# ============================================================
class TestSegmentSpeedChange:
    """Speed change on one segment invalidates that segment + captions + audio."""

    def test_segment_speed_change(self, base_edl: EditDecisionList) -> None:
        """Changing speed on segment 2 invalidates [2] + captions + audio."""
        new_edl = deepcopy(base_edl)
        new_edl.segments[1] = _make_segment(
            2, 6000, 11000, output_start_ms=5000, speed=1.5,
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is False
        assert 2 in hint.segments_invalidated
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is True

    def test_segment_timing_change(self, base_edl: EditDecisionList) -> None:
        """Changing source_start_ms on segment 3 invalidates [3]."""
        new_edl = deepcopy(base_edl)
        new_edl.segments[2] = _make_segment(
            3, 16000, 20000, output_start_ms=10000,
        )

        hint = classify_changes(base_edl, new_edl)

        assert 3 in hint.segments_invalidated
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is True


# ============================================================
# SEGMENTS ADDED/REMOVED
# ============================================================
class TestSegmentsAdded:
    """Adding or removing segments invalidates everything."""

    def test_segments_added(self, base_edl: EditDecisionList) -> None:
        """Adding a segment invalidates all + captions + audio."""
        new_edl = deepcopy(base_edl)
        new_edl.segments.append(
            _make_segment(5, 40000, 45000, output_start_ms=22000),
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is True
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is True

    def test_segments_removed(self, base_edl: EditDecisionList) -> None:
        """Removing a segment invalidates all + captions + audio."""
        new_edl = deepcopy(base_edl)
        new_edl.segments = new_edl.segments[:3]

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is True
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is True

    def test_segment_id_reorder(self, base_edl: EditDecisionList) -> None:
        """Changing segment IDs (reorder) invalidates everything."""
        new_edl = deepcopy(base_edl)
        # Swap segment IDs for segments 1 and 2
        new_edl.segments[0] = _make_segment(
            2, 0, 5000, output_start_ms=0,
        )
        new_edl.segments[1] = _make_segment(
            1, 6000, 11000, output_start_ms=5000,
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is True
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is True


# ============================================================
# OVERLAY CHANGE
# ============================================================
class TestOverlayChange:
    """Overlay changes only invalidate affected segments."""

    def test_overlay_change(self) -> None:
        """Adding an overlay at segment 3 invalidates [3] only."""
        old_edl = _make_edl(overlays=[])
        new_edl = deepcopy(old_edl)
        # Segment 3 spans output_start_ms=10000, duration=5000 => 10000-15000
        new_edl.overlays = [
            OverlaySpec(
                overlay_type="lower_third",
                text="Speaker Name",
                start_ms=11000,
                end_ms=14000,
            ),
        ]

        hint = classify_changes(old_edl, new_edl)

        assert hint.all_segments_invalidated is False
        assert 3 in hint.segments_invalidated
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is False

    def test_overlay_removal(self) -> None:
        """Removing an overlay invalidates the affected segment."""
        old_edl = _make_edl(
            overlays=[
                OverlaySpec(
                    overlay_type="logo",
                    text="Logo",
                    start_ms=0,
                    end_ms=4000,
                ),
            ],
        )
        new_edl = deepcopy(old_edl)
        new_edl.overlays = []

        hint = classify_changes(old_edl, new_edl)

        assert 1 in hint.segments_invalidated
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is False


# ============================================================
# PER-SEGMENT CANVAS CHANGE
# ============================================================
class TestPerSegmentCanvasChange:
    """Per-segment canvas changes invalidate that segment + captions."""

    def test_per_segment_canvas_change(self, base_edl: EditDecisionList) -> None:
        """Adding a canvas override to segment 1 invalidates [1] + captions."""
        new_edl = deepcopy(base_edl)
        new_edl.segments[0] = _make_segment(
            1, 0, 5000, output_start_ms=0,
            canvas=SegmentCanvasSpec(
                background_color="#FF0000",
                regions=[
                    CanvasRegion(
                        region_id="speaker",
                        source_x=0,
                        source_y=0,
                        source_width=1920,
                        source_height=1080,
                        output_x=0,
                        output_y=0,
                        output_width=1080,
                        output_height=1920,
                    ),
                ],
            ),
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is False
        assert 1 in hint.segments_invalidated
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is False


# ============================================================
# MOTION CHANGE
# ============================================================
class TestMotionChange:
    """Motion changes invalidate only the specific segment."""

    def test_motion_change(self, base_edl: EditDecisionList) -> None:
        """Adding motion to segment 4 invalidates [4] only."""
        new_edl = deepcopy(base_edl)
        new_edl.segments[3] = _make_segment(
            4, 25000, 32000, output_start_ms=15000,
            motion=MotionSpec(effect="zoom_in", start_scale=1.0, end_scale=1.3),
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is False
        assert 4 in hint.segments_invalidated
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is False

    def test_motion_removal(self) -> None:
        """Removing motion from a segment invalidates that segment."""
        old_edl = _make_edl(
            segments=[
                _make_segment(1, 0, 5000, output_start_ms=0),
                _make_segment(
                    2, 6000, 11000, output_start_ms=5000,
                    motion=MotionSpec(
                        effect="pan_left",
                        start_scale=1.0,
                        end_scale=1.0,
                    ),
                ),
                _make_segment(3, 15000, 20000, output_start_ms=10000),
                _make_segment(4, 25000, 32000, output_start_ms=15000),
            ],
        )
        new_edl = deepcopy(old_edl)
        new_edl.segments[1] = _make_segment(
            2, 6000, 11000, output_start_ms=5000,
        )

        hint = classify_changes(old_edl, new_edl)

        assert 2 in hint.segments_invalidated
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is False


# ============================================================
# METADATA CHANGE
# ============================================================
class TestMetadataChangeNoInvalidation:
    """Metadata changes should not invalidate anything."""

    def test_metadata_change_no_invalidation(
        self, base_edl: EditDecisionList,
    ) -> None:
        """Changing metadata produces an empty render hint."""
        new_edl = deepcopy(base_edl)
        new_edl.metadata = MetadataSpec(
            title="New Title",
            description="A new description",
            hashtags=["#video", "#edit"],
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.segments_invalidated == []
        assert hint.all_segments_invalidated is False
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is False


# ============================================================
# AUDIO CHANGE
# ============================================================
class TestAudioChange:
    """Audio changes invalidate audio only."""

    def test_audio_volume_change(self, base_edl: EditDecisionList) -> None:
        """Changing audio volume invalidates audio only."""
        new_edl = deepcopy(base_edl)
        new_edl.audio = AudioSpec(
            source_audio=True,
            source_volume_db=-3.0,
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.segments_invalidated == []
        assert hint.all_segments_invalidated is False
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is True

    def test_background_music_change(self, base_edl: EditDecisionList) -> None:
        """Adding background music invalidates audio only."""
        new_edl = deepcopy(base_edl)
        new_edl.audio = AudioSpec(
            source_audio=True,
            background_music="lofi_beat.mp3",
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.audio_invalidated is True
        assert hint.all_segments_invalidated is False
        assert hint.captions_invalidated is False


# ============================================================
# GLOBAL CANVAS CHANGE
# ============================================================
class TestGlobalCanvasChange:
    """Global canvas changes invalidate all segments + captions."""

    def test_global_canvas_change(self, base_edl: EditDecisionList) -> None:
        """Enabling global canvas invalidates all + captions."""
        new_edl = deepcopy(base_edl)
        new_edl.canvas = CanvasSpec(
            enabled=True,
            canvas_width=1080,
            canvas_height=1920,
            regions=[
                CanvasRegion(
                    region_id="full",
                    source_x=0,
                    source_y=0,
                    source_width=1920,
                    source_height=1080,
                    output_x=0,
                    output_y=0,
                    output_width=1080,
                    output_height=1920,
                ),
            ],
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is True
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is False


# ============================================================
# CROP CHANGE
# ============================================================
class TestCropChange:
    """Crop changes invalidate all segments + captions."""

    def test_crop_change(self, base_edl: EditDecisionList) -> None:
        """Changing crop mode invalidates all + captions."""
        new_edl = deepcopy(base_edl)
        new_edl.crop = CropSpec(
            mode="manual",
            aspect_ratio="16:9",
            face_tracking=False,
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is True
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is False


# ============================================================
# RENDER SETTINGS CHANGE
# ============================================================
class TestRenderSettingsChange:
    """Render settings changes invalidate all segments."""

    def test_render_settings_change(self, base_edl: EditDecisionList) -> None:
        """Changing quality invalidates all segments."""
        new_edl = deepcopy(base_edl)
        new_edl.render_settings = RenderSettingsSpec(
            profile="youtube_4k",
            quality="low",
            use_nvenc=False,
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is True


# ============================================================
# MULTIPLE CHANGES
# ============================================================
class TestMultipleChanges:
    """Multiple simultaneous changes produce combined hints."""

    def test_speed_and_audio_change(self, base_edl: EditDecisionList) -> None:
        """Speed on seg 2 + audio change sets all relevant flags."""
        new_edl = deepcopy(base_edl)
        new_edl.segments[1] = _make_segment(
            2, 6000, 11000, output_start_ms=5000, speed=2.0,
        )
        new_edl.audio = AudioSpec(source_volume_db=-6.0)

        hint = classify_changes(base_edl, new_edl)

        assert 2 in hint.segments_invalidated
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is True

    def test_no_changes_at_all(self, base_edl: EditDecisionList) -> None:
        """Identical EDLs produce an empty render hint."""
        new_edl = deepcopy(base_edl)

        hint = classify_changes(base_edl, new_edl)

        assert hint.segments_invalidated == []
        assert hint.all_segments_invalidated is False
        assert hint.captions_invalidated is False
        assert hint.audio_invalidated is False


# ============================================================
# PER-SEGMENT COLOR CHANGE
# ============================================================
class TestPerSegmentColorChange:
    """Per-segment color grading changes."""

    def test_per_segment_color_change(self, base_edl: EditDecisionList) -> None:
        """Adding color to segment 2 invalidates [2] + captions."""
        new_edl = deepcopy(base_edl)
        new_edl.segments[1] = _make_segment(
            2, 6000, 11000, output_start_ms=5000,
            color=ColorSpec(brightness=0.5, saturation=1.8),
        )

        hint = classify_changes(base_edl, new_edl)

        assert hint.all_segments_invalidated is False
        assert 2 in hint.segments_invalidated
        assert hint.captions_invalidated is True
        assert hint.audio_invalidated is False


# ============================================================
# SEGMENTS INVALIDATED IS SORTED
# ============================================================
class TestSegmentsInvalidatedSorted:
    """Segments invalidated list should always be sorted."""

    def test_sorted_output(self) -> None:
        """Multiple per-segment changes produce a sorted list."""
        old_edl = _make_edl()
        new_edl = deepcopy(old_edl)
        # Change motion on seg 4 and color on seg 1
        new_edl.segments[3] = _make_segment(
            4, 25000, 32000, output_start_ms=15000,
            motion=MotionSpec(effect="zoom_out"),
        )
        new_edl.segments[0] = _make_segment(
            1, 0, 5000, output_start_ms=0,
            color=ColorSpec(hue_shift=30.0),
        )

        hint = classify_changes(old_edl, new_edl)

        assert hint.segments_invalidated == [1, 4]
        assert hint.segments_invalidated == sorted(hint.segments_invalidated)
