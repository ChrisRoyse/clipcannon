"""Phase 3 Manual FSV - Testing 7 new MCP tools.

Full State Verification for:
1. clipcannon_auto_trim - Filler word/pause removal
2. clipcannon_color_adjust - Color grading
3. clipcannon_add_motion - Motion effects
4. clipcannon_add_overlay - Text/graphic overlays
5. clipcannon_audio_cleanup - Audio cleanup via FFmpeg
6. clipcannon_preview_clip - Short preview render
7. clipcannon_inspect_render - Render output inspection
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

PASS_COUNT = 0
FAIL_COUNT = 0
FAILURES: list[str] = []


def record(label: str, passed: bool, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if passed:
        PASS_COUNT += 1
        print(f"  [PASS] {label}")
    else:
        FAIL_COUNT += 1
        FAILURES.append(f"{label}: {detail}")
        print(f"  [FAIL] {label} -- {detail}")


def separator(title: str) -> None:
    print(f"\n{'='*70}\n  {title}\n{'='*70}\n")


# ============================================================
# Test 1: Auto-Trim
# ============================================================
async def test_auto_trim() -> None:
    separator("AUTO-TRIM - Filler Detection + Segment Building")
    from clipcannon.editing.auto_trim import (
        FILLER_WORDS,
        build_trimmed_segments,
    )

    # Verify FILLER_WORDS content
    record("FILLER_WORDS has 20+ entries", len(FILLER_WORDS) >= 20,
           f"count={len(FILLER_WORDS)}")
    record("'um' in FILLER_WORDS", "um" in FILLER_WORDS)
    record("'you know' in FILLER_WORDS", "you know" in FILLER_WORDS)
    record("'basically' in FILLER_WORDS", "basically" in FILLER_WORDS)
    record("'uh' in FILLER_WORDS", "uh" in FILLER_WORDS)

    # Test build_trimmed_segments with known data
    fillers = [
        {"word": "um", "start_ms": 2000, "end_ms": 2500},
        {"word": "like", "start_ms": 8000, "end_ms": 8300},
        {"word": "basically", "start_ms": 15000, "end_ms": 15800},
    ]
    pauses = [
        {"start_ms": 5000, "end_ms": 6200, "duration_ms": 1200},
        {"start_ms": 12000, "end_ms": 13000, "duration_ms": 1000},
    ]
    segs = build_trimmed_segments(20000, fillers, pauses)

    record("Segments generated", len(segs) > 0, f"count={len(segs)}")
    # Verify no segment overlaps a dead zone
    dead_zones = [(f["start_ms"], f["end_ms"]) for f in fillers] + [
        (p["start_ms"], p["end_ms"]) for p in pauses
    ]
    for s in segs:
        for dz_start, dz_end in dead_zones:
            overlap = (
                s["source_start_ms"] < dz_end
                and s["source_end_ms"] > dz_start
            )
            record(
                f"Seg {s['source_start_ms']}-{s['source_end_ms']} "
                f"skips dead zone {dz_start}-{dz_end}",
                not overlap,
            )

    total_kept = sum(int(s["duration_ms"]) for s in segs)
    record("Total kept < 20000ms", total_kept < 20000, f"kept={total_kept}")
    record(
        "Total kept > 0ms",
        total_kept > 0,
        f"kept={total_kept}",
    )

    # Edge: no fillers, no pauses
    segs_full = build_trimmed_segments(10000, [], [])
    record("No dead zones = 1 full segment", len(segs_full) == 1,
           f"count={len(segs_full)}")
    if segs_full:
        record(
            "Full segment covers 0-10000",
            segs_full[0]["source_start_ms"] == 0
            and segs_full[0]["source_end_ms"] == 10000,
        )

    # Edge: all filler
    segs_empty = build_trimmed_segments(
        5000,
        [{"word": "um", "start_ms": 0, "end_ms": 5000}],
        [],
    )
    record("All-filler = 0 segments", len(segs_empty) == 0,
           f"count={len(segs_empty)}")

    # Edge: zero duration
    segs_zero = build_trimmed_segments(0, [], [])
    record("Zero duration = 0 segments", len(segs_zero) == 0)

    # Edge: overlapping dead zones get merged
    segs_overlap = build_trimmed_segments(
        10000,
        [
            {"word": "um", "start_ms": 1000, "end_ms": 3000},
            {"word": "uh", "start_ms": 2500, "end_ms": 4000},
        ],
        [],
    )
    record("Overlapping dead zones merged", len(segs_overlap) >= 1)
    for s in segs_overlap:
        # No segment should start in the 1000-4000 range
        overlap = s["source_start_ms"] < 4000 and s["source_end_ms"] > 1000
        record(
            f"Merged zone: seg {s['source_start_ms']}-{s['source_end_ms']} "
            "avoids 1000-4000",
            not overlap,
        )


# ============================================================
# Test 2: Color Grading
# ============================================================
async def test_color_grading() -> None:
    separator("COLOR GRADING - Filter Generation")
    from clipcannon.editing.motion import build_color_filters

    # Happy path
    f = build_color_filters(
        brightness=0.2, contrast=1.5, saturation=0.8,
        gamma=1.2, hue_shift=30,
    )
    record("Color filter generated", len(f) > 0)
    record("Contains eq filter", "eq=" in f)
    record("Contains hue filter", "hue=" in f)
    record("Brightness in filter", "brightness=0.200" in f)
    record("Contrast in filter", "contrast=1.500" in f)
    record("Saturation in filter", "saturation=0.800" in f)
    record("Gamma in filter", "gamma=1.200" in f)
    record("Hue shift value", "h=30.0" in f)

    # No-op
    f_noop = build_color_filters()
    record("Default values = empty filter", f_noop == "", f"got={f_noop!r}")

    # Only brightness
    f_bright = build_color_filters(brightness=-0.5)
    record(
        "Brightness-only filter",
        "eq=brightness=-0.500" in f_bright,
        f"got={f_bright!r}",
    )
    record("No hue in brightness-only", "hue" not in f_bright)

    # Only hue shift
    f_hue = build_color_filters(hue_shift=90)
    record("Hue-only filter", "hue=h=90.0" in f_hue, f"got={f_hue!r}")
    record("No eq in hue-only", "eq=" not in f_hue)

    # Extreme values
    f_extreme = build_color_filters(
        brightness=1.0, contrast=3.0, saturation=3.0,
        gamma=10.0, hue_shift=180,
    )
    record(
        "Extreme values generate valid filter",
        "eq=" in f_extreme and "hue=" in f_extreme,
    )


# ============================================================
# Test 3: Motion Effects
# ============================================================
async def test_motion_effects() -> None:
    separator("MOTION EFFECTS - Zoompan Filter Generation")
    from clipcannon.editing.motion import build_motion_filter

    effects = [
        "zoom_in", "zoom_out", "pan_left", "pan_right",
        "pan_up", "pan_down", "ken_burns",
    ]
    for effect in effects:
        f = build_motion_filter(
            effect, 1.0, 1.3, "linear",
            1080, 1920, 1920, 1080, 30, 5.0,
        )
        record(f"{effect} produces zoompan filter", "zoompan" in f)
        record(f"{effect} has correct size", "s=1080x1920" in f)
        record(f"{effect} has fps=30", "fps=30" in f)

    # Test easing functions
    for easing in ["linear", "ease_in", "ease_out", "ease_in_out"]:
        f = build_motion_filter(
            "zoom_in", 1.0, 1.5, easing,
            1080, 1920, 1920, 1080, 30, 3.0,
        )
        record(f"Easing {easing} accepted", "zoompan" in f)

    # Edge: very short duration
    f_short = build_motion_filter(
        "zoom_in", 1.0, 1.3, "linear",
        1080, 1920, 1920, 1080, 30, 0.1,
    )
    record("Short duration accepted", "zoompan" in f_short)

    # Edge: unknown easing falls back to linear
    f_unknown = build_motion_filter(
        "zoom_in", 1.0, 1.3, "unknown_easing",
        1080, 1920, 1920, 1080, 30, 5.0,
    )
    record("Unknown easing falls back to linear", "zoompan" in f_unknown)

    # Duration frames calculation
    # 30fps * 5s = 150 frames
    f_frames = build_motion_filter(
        "zoom_in", 1.0, 1.3, "linear",
        1080, 1920, 1920, 1080, 30, 5.0,
    )
    record("Frame count d=150", "d=150" in f_frames, f"filter={f_frames}")


# ============================================================
# Test 4: Overlays
# ============================================================
async def test_overlays() -> None:
    separator("OVERLAYS - FFmpeg Filter Generation")
    from clipcannon.editing.overlays import build_overlay_filters

    # Lower third
    f_lt = build_overlay_filters(
        "lower_third", text="John Smith", subtitle="CEO",
        start_ms=1000, end_ms=5000,
    )
    record("Lower third generates filters", len(f_lt) >= 2,
           f"count={len(f_lt)}")
    record("Has drawbox for background", any("drawbox" in x for x in f_lt))
    record("Has drawtext for name", any("John Smith" in x for x in f_lt))
    record("Has drawtext for subtitle", any("CEO" in x for x in f_lt))
    record("Has time enable", any("between" in x for x in f_lt))

    # Lower third without subtitle
    f_lt_nosub = build_overlay_filters(
        "lower_third", text="Solo Speaker",
        start_ms=0, end_ms=3000,
    )
    record("Lower third no-subtitle = 2 filters", len(f_lt_nosub) == 2,
           f"count={len(f_lt_nosub)}")

    # Title card
    f_tc = build_overlay_filters(
        "title_card", text="Chapter 1",
        start_ms=0, end_ms=3000,
    )
    record("Title card generates 2+ filters", len(f_tc) >= 2,
           f"count={len(f_tc)}")
    record("Title card has centered text", any("(w-tw)/2" in x for x in f_tc))

    # Watermark
    f_wm = build_overlay_filters(
        "watermark", text="@brand",
        start_ms=0, end_ms=30000, opacity=0.3,
    )
    record("Watermark generates filter", len(f_wm) >= 1,
           f"count={len(f_wm)}")
    record("Watermark has drawtext", any("drawtext" in x for x in f_wm))

    # CTA
    f_cta = build_overlay_filters(
        "cta", text="Subscribe!",
        start_ms=5000, end_ms=10000,
    )
    record("CTA generates 2 filters", len(f_cta) == 2,
           f"count={len(f_cta)}")
    record("CTA has drawbox", any("drawbox" in x for x in f_cta))
    record("CTA has drawtext", any("drawtext" in x for x in f_cta))

    # Logo with text fallback (no image_path)
    f_logo = build_overlay_filters(
        "logo", text="LOGO",
        start_ms=0, end_ms=5000,
    )
    record("Logo fallback generates filter", len(f_logo) >= 1)

    # Edge: invalid type
    try:
        build_overlay_filters(
            "nonexistent", text="test",
            start_ms=0, end_ms=1000,
        )
        record("Invalid overlay type rejected", False,
               "should have raised ValueError")
    except ValueError:
        record("Invalid overlay type rejected", True)


# ============================================================
# Test 5: Audio Cleanup
# ============================================================
async def test_audio_cleanup() -> None:
    separator("AUDIO CLEANUP - Filter Generation")
    from clipcannon.audio.cleanup import (
        SUPPORTED_CLEANUP_OPS,
        build_cleanup_filters,
    )

    record(
        "4 cleanup ops supported",
        len(SUPPORTED_CLEANUP_OPS) == 4,
        f"count={len(SUPPORTED_CLEANUP_OPS)}",
    )
    record(
        "Has noise_reduction",
        "noise_reduction" in SUPPORTED_CLEANUP_OPS,
    )
    record("Has de_hum", "de_hum" in SUPPORTED_CLEANUP_OPS)
    record("Has de_ess", "de_ess" in SUPPORTED_CLEANUP_OPS)
    record(
        "Has normalize_loudness",
        "normalize_loudness" in SUPPORTED_CLEANUP_OPS,
    )

    # Individual ops
    for op in sorted(SUPPORTED_CLEANUP_OPS):
        f = build_cleanup_filters([op])
        record(f"{op} produces filter(s)", len(f) >= 1, f"count={len(f)}")

    # All ops combined
    f_all = build_cleanup_filters(list(SUPPORTED_CLEANUP_OPS))
    record("All ops combined", len(f_all) >= 4, f"count={len(f_all)}")

    # De-hum with 60Hz (US)
    f_hum60 = build_cleanup_filters(["de_hum"], hum_frequency=60)
    record("60Hz de-hum", any("f=60" in x for x in f_hum60),
           f"filters={f_hum60}")
    record("120Hz harmonic", any("f=120" in x for x in f_hum60),
           f"filters={f_hum60}")
    record("180Hz harmonic", any("f=180" in x for x in f_hum60),
           f"filters={f_hum60}")

    # De-hum with 50Hz (EU default)
    f_hum50 = build_cleanup_filters(["de_hum"])
    record("50Hz de-hum default", any("f=50" in x for x in f_hum50),
           f"filters={f_hum50}")

    # Noise reduction filter
    f_nr = build_cleanup_filters(["noise_reduction"])
    record("Noise reduction = anlmdn", any("anlmdn" in x for x in f_nr),
           f"filters={f_nr}")

    # Loudnorm filter
    f_ln = build_cleanup_filters(["normalize_loudness"])
    record("Loudnorm filter present", any("loudnorm" in x for x in f_ln))
    record("EBU R128 target -16 LUFS", any("I=-16" in x for x in f_ln))
    record("True peak -1.5", any("TP=-1.5" in x for x in f_ln))

    # De-ess
    f_de = build_cleanup_filters(["de_ess"])
    record("De-ess produces filters", len(f_de) >= 1, f"count={len(f_de)}")

    # Edge: invalid op
    try:
        build_cleanup_filters(["nonexistent"])
        record("Invalid op rejected", False, "should have raised ValueError")
    except ValueError:
        record("Invalid op rejected", True)

    # Edge: empty ops - the cleanup_audio function raises but
    # build_cleanup_filters returns empty list
    f_empty = build_cleanup_filters([])
    record("Empty ops = empty filters", len(f_empty) == 0,
           f"count={len(f_empty)}")


# ============================================================
# Test 6: Preview + Inspector
# ============================================================
async def test_preview_inspector() -> None:
    separator("PREVIEW + INSPECTOR - Module Functions")
    from clipcannon.rendering.inspector import (
        InspectionResult,
        _parse_fps,
    )
    from clipcannon.rendering.preview import (
        PREVIEW_HEIGHT,
        PREVIEW_WIDTH,
        PreviewResult,
    )

    record("PreviewResult importable", PreviewResult is not None)
    record("Preview width = 540", PREVIEW_WIDTH == 540,
           f"got={PREVIEW_WIDTH}")
    record("Preview height = 960", PREVIEW_HEIGHT == 960,
           f"got={PREVIEW_HEIGHT}")
    record("InspectionResult importable", InspectionResult is not None)

    # Test fps parsing
    record("30/1 = 30.0", _parse_fps("30/1") == 30.0,
           f"got={_parse_fps('30/1')}")
    record(
        "30000/1001 ~ 29.97",
        abs(_parse_fps("30000/1001") - 29.97) < 0.01,
        f"got={_parse_fps('30000/1001')}",
    )
    record("0/1 = 0.0", _parse_fps("0/1") == 0.0,
           f"got={_parse_fps('0/1')}")
    record("invalid = 0.0", _parse_fps("garbage") == 0.0,
           f"got={_parse_fps('garbage')}")
    record("24/1 = 24.0", _parse_fps("24/1") == 24.0,
           f"got={_parse_fps('24/1')}")
    record("60/1 = 60.0", _parse_fps("60/1") == 60.0,
           f"got={_parse_fps('60/1')}")
    record("empty string = 0.0", _parse_fps("") == 0.0,
           f"got={_parse_fps('')}")

    # Test InspectionResult defaults
    ir = InspectionResult(render_id="test", output_path="/tmp/test.mp4")
    record("InspectionResult defaults: all_passed=True", ir.all_passed)
    record("InspectionResult defaults: frames=[]", ir.frames == [])
    record("InspectionResult defaults: checks=[]", ir.checks == [])
    record("InspectionResult defaults: elapsed_ms=0", ir.elapsed_ms == 0)

    # Test PreviewResult creation
    pr = PreviewResult(
        preview_path=Path("/tmp/p.mp4"),
        duration_ms=3000,
        file_size_bytes=12345,
        elapsed_ms=500,
        thumbnail_base64="abc",
    )
    record("PreviewResult creation", pr.duration_ms == 3000)
    record("PreviewResult file_size", pr.file_size_bytes == 12345)


# ============================================================
# Test 7: Pydantic Model Validation
# ============================================================
async def test_pydantic_models() -> None:
    separator("PYDANTIC MODELS - ColorSpec, MotionSpec, OverlaySpec")
    from clipcannon.editing.edl import (
        ColorSpec,
        EditDecisionList,
        MotionSpec,
        OverlaySpec,
        SegmentSpec,
    )

    # ColorSpec - valid creation
    c = ColorSpec(
        brightness=0.5, contrast=2.0, saturation=0.5,
        gamma=2.0, hue_shift=-90,
    )
    record("ColorSpec creation", c.brightness == 0.5)
    record("ColorSpec contrast", c.contrast == 2.0)
    record("ColorSpec saturation", c.saturation == 0.5)
    record("ColorSpec gamma", c.gamma == 2.0)
    record("ColorSpec hue_shift", c.hue_shift == -90)

    # ColorSpec defaults
    c_def = ColorSpec()
    record("ColorSpec default brightness=0", c_def.brightness == 0.0)
    record("ColorSpec default contrast=1", c_def.contrast == 1.0)
    record("ColorSpec default saturation=1", c_def.saturation == 1.0)
    record("ColorSpec default gamma=1", c_def.gamma == 1.0)
    record("ColorSpec default hue_shift=0", c_def.hue_shift == 0.0)

    # ColorSpec validation
    try:
        ColorSpec(brightness=5.0)
        record("ColorSpec rejects brightness > 1", False,
               "should have raised")
    except Exception:
        record("ColorSpec rejects brightness > 1", True)

    try:
        ColorSpec(brightness=-2.0)
        record("ColorSpec rejects brightness < -1", False,
               "should have raised")
    except Exception:
        record("ColorSpec rejects brightness < -1", True)

    try:
        ColorSpec(contrast=-1.0)
        record("ColorSpec rejects negative contrast", False,
               "should have raised")
    except Exception:
        record("ColorSpec rejects negative contrast", True)

    try:
        ColorSpec(saturation=5.0)
        record("ColorSpec rejects saturation > 3", False,
               "should have raised")
    except Exception:
        record("ColorSpec rejects saturation > 3", True)

    try:
        ColorSpec(gamma=0.01)
        record("ColorSpec rejects gamma < 0.1", False,
               "should have raised")
    except Exception:
        record("ColorSpec rejects gamma < 0.1", True)

    try:
        ColorSpec(hue_shift=200)
        record("ColorSpec rejects hue_shift > 180", False,
               "should have raised")
    except Exception:
        record("ColorSpec rejects hue_shift > 180", True)

    # MotionSpec
    m = MotionSpec(
        effect="ken_burns", start_scale=1.0,
        end_scale=1.5, easing="ease_in_out",
    )
    record("MotionSpec creation", m.effect == "ken_burns")
    record("MotionSpec start_scale", m.start_scale == 1.0)
    record("MotionSpec end_scale", m.end_scale == 1.5)
    record("MotionSpec easing", m.easing == "ease_in_out")

    try:
        MotionSpec(effect="invalid_effect", start_scale=1.0, end_scale=1.3)
        record("MotionSpec rejects invalid effect", False,
               "should have raised")
    except Exception:
        record("MotionSpec rejects invalid effect", True)

    # All valid effects
    for eff in [
        "zoom_in", "zoom_out", "pan_left", "pan_right",
        "pan_up", "pan_down", "ken_burns",
    ]:
        ms = MotionSpec(effect=eff, start_scale=1.0, end_scale=1.3)
        record(f"MotionSpec accepts '{eff}'", ms.effect == eff)

    # OverlaySpec
    o = OverlaySpec(
        overlay_type="lower_third", text="Test",
        start_ms=0, end_ms=5000,
    )
    record("OverlaySpec creation", o.overlay_type == "lower_third")
    record("OverlaySpec defaults: font_size=36", o.font_size == 36)
    record("OverlaySpec defaults: opacity=1.0", o.opacity == 1.0)

    try:
        OverlaySpec(
            overlay_type="lower_third", text="Test",
            start_ms=5000, end_ms=1000,
        )
        record("OverlaySpec rejects end < start", False,
               "should have raised")
    except Exception:
        record("OverlaySpec rejects end < start", True)

    try:
        OverlaySpec(
            overlay_type="invalid", text="Test",
            start_ms=0, end_ms=1000,
        )
        record("OverlaySpec rejects invalid type", False,
               "should have raised")
    except Exception:
        record("OverlaySpec rejects invalid type", True)

    # All valid overlay types
    for otype in ["lower_third", "title_card", "logo", "watermark", "cta"]:
        ov = OverlaySpec(
            overlay_type=otype, text="Test",
            start_ms=0, end_ms=1000,
        )
        record(f"OverlaySpec accepts '{otype}'", ov.overlay_type == otype)

    # SegmentSpec with motion + color
    s = SegmentSpec(
        segment_id=1, source_start_ms=0, source_end_ms=10000,
        output_start_ms=0,
        motion=MotionSpec(
            effect="zoom_in", start_scale=1.0, end_scale=1.5,
        ),
        color=ColorSpec(brightness=0.1),
    )
    record(
        "SegmentSpec with motion+color",
        s.motion is not None and s.color is not None,
    )
    record("SegmentSpec source_duration_ms", s.source_duration_ms == 10000)
    record("SegmentSpec output_duration_ms", s.output_duration_ms == 10000)

    # EDL with overlays + color
    edl = EditDecisionList(
        edit_id="test", project_id="proj_test", name="Test",
        target_platform="tiktok",
        segments=[s],
        color=ColorSpec(contrast=1.2),
        overlays=[o],
    )
    record(
        "EDL with color + overlays",
        edl.color is not None and len(edl.overlays) == 1,
    )

    # EDL JSON round-trip
    json_str = edl.model_dump_json()
    edl2 = EditDecisionList(**json.loads(json_str))
    record("EDL JSON round-trip", edl2.color is not None
           and edl2.color.contrast == 1.2)
    record("Overlays preserved in round-trip", len(edl2.overlays) == 1)
    record(
        "Motion preserved in round-trip",
        edl2.segments[0].motion is not None
        and edl2.segments[0].motion.effect == "zoom_in",
    )
    record(
        "Color preserved in round-trip",
        edl2.segments[0].color is not None
        and edl2.segments[0].color.brightness == 0.1,
    )
    record(
        "Overlay type preserved",
        edl2.overlays[0].overlay_type == "lower_third",
    )


# ============================================================
# Test 8: Tool Dispatch
# ============================================================
async def test_tool_dispatch() -> None:
    separator("TOOL DISPATCH - All 7 new tools respond correctly")
    from clipcannon.tools.audio import dispatch_audio_tool
    from clipcannon.tools.editing import dispatch_editing_tool
    from clipcannon.tools.rendering import dispatch_rendering_tool

    # Auto-trim on nonexistent project should return PROJECT_NOT_FOUND
    result = await dispatch_editing_tool(
        "clipcannon_auto_trim", {"project_id": "proj_nonexistent"},
    )
    record(
        "auto_trim nonexistent = PROJECT_NOT_FOUND",
        result.get("error", {}).get("code") == "PROJECT_NOT_FOUND",
        f"got={result}",
    )

    # Color adjust on nonexistent project
    result = await dispatch_editing_tool(
        "clipcannon_color_adjust",
        {"project_id": "proj_nonexistent", "edit_id": "e1"},
    )
    record(
        "color_adjust nonexistent = PROJECT_NOT_FOUND",
        result.get("error", {}).get("code") == "PROJECT_NOT_FOUND",
        f"got={result.get('error', {}).get('code')}",
    )

    # Add motion on nonexistent project
    result = await dispatch_editing_tool(
        "clipcannon_add_motion",
        {
            "project_id": "proj_nonexistent", "edit_id": "e1",
            "segment_id": 1, "effect": "zoom_in",
        },
    )
    record(
        "add_motion nonexistent = PROJECT_NOT_FOUND",
        result.get("error", {}).get("code") == "PROJECT_NOT_FOUND",
        f"got={result.get('error', {}).get('code')}",
    )

    # Add overlay on nonexistent project
    result = await dispatch_editing_tool(
        "clipcannon_add_overlay",
        {
            "project_id": "proj_nonexistent", "edit_id": "e1",
            "overlay_type": "lower_third", "text": "Test",
            "start_ms": 0, "end_ms": 5000,
        },
    )
    record(
        "add_overlay nonexistent = PROJECT_NOT_FOUND",
        result.get("error", {}).get("code") == "PROJECT_NOT_FOUND",
        f"got={result.get('error', {}).get('code')}",
    )

    # Audio cleanup on nonexistent project
    result = await dispatch_audio_tool(
        "clipcannon_audio_cleanup",
        {
            "project_id": "proj_nonexistent", "edit_id": "e1",
            "operations": ["noise_reduction"],
        },
    )
    record(
        "audio_cleanup nonexistent = error",
        "error" in result,
        f"got={result}",
    )

    # Preview clip on nonexistent project
    result = await dispatch_rendering_tool(
        "clipcannon_preview_clip",
        {"project_id": "proj_nonexistent", "start_ms": 0},
    )
    record(
        "preview_clip nonexistent = PROJECT_NOT_FOUND",
        result.get("error", {}).get("code") == "PROJECT_NOT_FOUND",
        f"got={result.get('error', {}).get('code')}",
    )

    # Inspect render on nonexistent project
    result = await dispatch_rendering_tool(
        "clipcannon_inspect_render",
        {"project_id": "proj_nonexistent", "render_id": "r1"},
    )
    record(
        "inspect_render nonexistent = PROJECT_NOT_FOUND",
        result.get("error", {}).get("code") == "PROJECT_NOT_FOUND",
        f"got={result.get('error', {}).get('code')}",
    )

    # Unknown tool name
    result = await dispatch_editing_tool(
        "clipcannon_does_not_exist", {"project_id": "x"},
    )
    record(
        "Unknown editing tool = INTERNAL_ERROR",
        result.get("error", {}).get("code") == "INTERNAL_ERROR",
        f"got={result.get('error', {}).get('code')}",
    )


# ============================================================
# Main
# ============================================================
async def main() -> None:
    print("\n" + "=" * 70)
    print("  PHASE 3 FULL STATE VERIFICATION")
    print("  Testing 7 new MCP tools")
    print("=" * 70)

    await test_auto_trim()
    await test_color_grading()
    await test_motion_effects()
    await test_overlays()
    await test_audio_cleanup()
    await test_preview_inspector()
    await test_pydantic_models()
    await test_tool_dispatch()

    print("\n" + "=" * 70)
    print("  PHASE 3 FSV SUMMARY")
    print("=" * 70)
    print(f"\n  TOTAL: {PASS_COUNT + FAIL_COUNT}")
    print(f"  PASSED: {PASS_COUNT}")
    print(f"  FAILED: {FAIL_COUNT}")
    if FAILURES:
        print("\n  FAILURES:")
        for f in FAILURES:
            print(f"    - {f}")
    print(
        f"\n  VERDICT: "
        f"{'ALL PASSED' if FAIL_COUNT == 0 else f'{FAIL_COUNT} FAILURE(S)'}"
    )
    print("=" * 70)

    # Exit with non-zero code if any failures
    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
