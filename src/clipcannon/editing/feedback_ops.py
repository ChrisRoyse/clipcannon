"""Typed edit operations for iterative feedback.

Feedback about an edit ("bigger captions and keep the speaker in frame") is
turned into a list of *typed, validated operations* rather than a single
regex-matched intent. Every parser backend (the calling agent itself, MCP
sampling, the regex fallback) produces the same ``FeedbackPlan``; this module
is the only place that turns operations into EDL changes.

Design rules:
  * One feedback may contain several operations; all are applied together.
  * Operations are validated by pydantic before anything touches the EDL, so a
    model hallucinating a field or an out-of-range value fails loudly.
  * Changes are *merged* into the current EDL (e.g. a caption resize keeps the
    existing caption chunks) instead of replacing whole sub-specs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Runtime imports: pydantic evaluates these Literal aliases when building models.
from clipcannon.editing.edl import CaptionPosition, CaptionStyle, TransitionType  # noqa: TC001

if TYPE_CHECKING:
    from clipcannon.editing.edl import EditDecisionList, SegmentSpec


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaptionsOp(_Op):
    """Caption appearance. Give font_size (absolute) or font_size_delta."""

    op: Literal["captions"]
    font_size: int | None = Field(default=None, ge=8, le=200)
    font_size_delta: int | None = Field(default=None, ge=-150, le=150)
    position: CaptionPosition | None = None
    style: CaptionStyle | None = None
    enabled: bool | None = None


class SpeedOp(_Op):
    """Playback speed. Give speed (absolute) or delta. Empty segment_ids = all."""

    op: Literal["speed"]
    segment_ids: list[int] = Field(default_factory=list)
    speed: float | None = Field(default=None, ge=0.25, le=4.0)
    delta: float | None = Field(default=None, ge=-3.75, le=3.75)


class TrimOp(_Op):
    """Move a segment's in/out points. Positive deltas move the point later.

    start_delta_ms=+1500 drops the first 1.5 s; end_delta_ms=-2000 drops the
    last 2 s; end_delta_ms=+3000 extends the segment by 3 s of source.
    """

    op: Literal["trim"]
    segment_id: int = Field(ge=1)
    start_delta_ms: int = 0
    end_delta_ms: int = 0


class TransitionOp(_Op):
    """Set a transition on one edge of a segment."""

    op: Literal["transition"]
    segment_id: int = Field(ge=1)
    edge: Literal["in", "out"] = "in"
    type: TransitionType = "crossfade"
    duration_ms: int = Field(default=400, ge=100, le=2000)


class RemoveSegmentsOp(_Op):
    """Drop whole segments from the edit."""

    op: Literal["remove_segments"]
    segment_ids: list[int] = Field(min_length=1)


class AudioOp(_Op):
    """Source audio level in dB. Give source_volume_db or delta_db."""

    op: Literal["audio"]
    source_volume_db: float | None = Field(default=None, ge=-60.0, le=20.0)
    delta_db: float | None = Field(default=None, ge=-60.0, le=20.0)


class FramingOp(_Op):
    """Re-frame segments for the vertical canvas.

    focus_x / focus_y are the normalized point of the *source* frame to keep
    centered (0 = left/top, 1 = right/bottom), e.g. the speaker's face.
    zoom > 1 crops tighter. Empty segment_ids = all segments.
    """

    op: Literal["framing"]
    segment_ids: list[int] = Field(default_factory=list)
    focus_x: float = Field(ge=0.0, le=1.0)
    focus_y: float = Field(default=0.5, ge=0.0, le=1.0)
    zoom: float = Field(default=1.0, ge=1.0, le=4.0)


class ColorOp(_Op):
    """Relative color adjustment (applied via clipcannon_color_adjust)."""

    op: Literal["color"]
    brightness_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    contrast_delta: float = Field(default=0.0, ge=-2.0, le=2.0)
    saturation_delta: float = Field(default=0.0, ge=-2.0, le=2.0)


class OverlayOp(_Op):
    """Add a text overlay (applied via clipcannon_add_overlay)."""

    op: Literal["overlay"]
    overlay_type: Literal["lower_third", "title_card"] = "title_card"
    text: str = Field(min_length=1)


class MotionOp(_Op):
    """Add a motion effect (applied via clipcannon_add_motion)."""

    op: Literal["motion"]
    segment_ids: list[int] = Field(default_factory=list)
    effect: Literal[
        "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "ken_burns",
    ] = "zoom_in"


FeedbackOp = Annotated[
    CaptionsOp | SpeedOp | TrimOp | TransitionOp | RemoveSegmentsOp | AudioOp
    | FramingOp | ColorOp | OverlayOp | MotionOp,
    Field(discriminator="op"),
]


class FeedbackPlan(BaseModel):
    """A validated set of operations derived from one piece of feedback."""

    model_config = ConfigDict(extra="forbid")

    ops: list[FeedbackOp] = Field(min_length=1)
    summary: str = ""

    @model_validator(mode="after")
    def _check_exclusive_fields(self) -> FeedbackPlan:
        for op in self.ops:
            if (isinstance(op, CaptionsOp) and op.font_size is not None
                    and op.font_size_delta is not None):
                raise ValueError("captions: give font_size or font_size_delta, not both")
            if isinstance(op, SpeedOp) and (op.speed is None) == (op.delta is None):
                raise ValueError("speed: give exactly one of speed or delta")
            if isinstance(op, AudioOp) and (op.source_volume_db is None) == (op.delta_db is None):
                raise ValueError("audio: give exactly one of source_volume_db or delta_db")
        return self


def plan_json_schema() -> dict[str, Any]:
    """JSON schema for FeedbackPlan (used in tool definitions and prompts)."""
    return FeedbackPlan.model_json_schema()


class OpError(ValueError):
    """An operation is valid in isolation but cannot apply to this EDL."""


# ============================================================
# OPS -> CHANGES
# ============================================================
def _seg_raw(seg: SegmentSpec) -> dict[str, Any]:
    d: dict[str, Any] = {
        "source_start_ms": seg.source_start_ms,
        "source_end_ms": seg.source_end_ms,
        "speed": seg.speed,
    }
    for key in ("transition_in", "transition_out", "canvas", "motion", "color"):
        val = getattr(seg, key, None)
        if val is not None:
            d[key] = val.model_dump()
    return d


def _framing_canvas(
    op: FramingOp, src_w: int, src_h: int, out_w: int, out_h: int,
) -> dict[str, Any]:
    """A single full-canvas region cropping the source around the focus point."""
    win_h = src_h / op.zoom
    win_w = win_h * out_w / out_h
    if win_w > src_w:  # canvas wider than source aspect: fit width instead
        win_w = src_w / op.zoom
        win_h = win_w * out_h / out_w
    x = min(max(op.focus_x * src_w - win_w / 2, 0), src_w - win_w)
    y = min(max(op.focus_y * src_h - win_h / 2, 0), src_h - win_h)
    return {
        "regions": [{
            "region_id": "framing",
            "source_x": int(round(x)), "source_y": int(round(y)),
            "source_width": int(round(win_w)), "source_height": int(round(win_h)),
            "output_x": 0, "output_y": 0,
            "output_width": out_w, "output_height": out_h,
            "z_index": 1, "fit_mode": "cover",
        }],
        "background_color": "#000000",
    }


def ops_to_changes(
    plan: FeedbackPlan,
    edl: EditDecisionList,
    *,
    source_size: tuple[int, int] = (1920, 1080),
    canvas_size: tuple[int, int] = (1080, 1920),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Translate a plan into ``modify_edit`` changes plus follow-up actions.

    Returns:
        (changes, special_actions). ``changes`` is safe to pass to
        clipcannon_modify_edit; ``special_actions`` name tools that must be
        called separately (color, overlay, motion).

    Raises:
        OpError: an operation references a segment that does not exist, or
            would produce an invalid segment.
    """
    seg_ids = {s.segment_id for s in edl.segments}
    segs = {s.segment_id: _seg_raw(s) for s in edl.segments}
    order = [s.segment_id for s in edl.segments]
    removed: set[int] = set()
    captions: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None
    segments_touched = False
    special: list[dict[str, Any]] = []

    def _check(ids: list[int]) -> list[int]:
        bad = [i for i in ids if i not in seg_ids]
        if bad:
            raise OpError(f"unknown segment_id(s) {bad}; edit has {sorted(seg_ids)}")
        return ids or order

    for op in plan.ops:
        if isinstance(op, CaptionsOp):
            if captions is None:
                captions = edl.captions.model_dump()
            if op.font_size is not None:
                captions["font_size"] = op.font_size
            if op.font_size_delta is not None:
                captions["font_size"] = max(8, min(200, captions["font_size"] + op.font_size_delta))
            for key in ("position", "style", "enabled"):
                val = getattr(op, key)
                if val is not None:
                    captions[key] = val
        elif isinstance(op, SpeedOp):
            for sid in _check(op.segment_ids):
                cur = segs[sid]["speed"]
                new = op.speed if op.speed is not None else cur + (op.delta or 0.0)
                segs[sid]["speed"] = max(0.25, min(4.0, round(new, 3)))
            segments_touched = True
        elif isinstance(op, TrimOp):
            _check([op.segment_id])
            s = segs[op.segment_id]
            start = s["source_start_ms"] + op.start_delta_ms
            end = s["source_end_ms"] + op.end_delta_ms
            if start < 0 or end - start < 500:
                raise OpError(
                    f"trim on segment {op.segment_id} gives {start}-{end} ms; "
                    "segments must start >= 0 and last >= 500 ms",
                )
            s["source_start_ms"], s["source_end_ms"] = start, end
            segments_touched = True
        elif isinstance(op, TransitionOp):
            _check([op.segment_id])
            segs[op.segment_id][f"transition_{op.edge}"] = {
                "type": op.type, "duration_ms": op.duration_ms,
            }
            segments_touched = True
        elif isinstance(op, RemoveSegmentsOp):
            removed.update(_check(op.segment_ids))
            segments_touched = True
        elif isinstance(op, AudioOp):
            if audio is None:
                audio = edl.audio.model_dump()
            if op.source_volume_db is not None:
                audio["source_volume_db"] = op.source_volume_db
            else:
                audio["source_volume_db"] = audio["source_volume_db"] + (op.delta_db or 0.0)
        elif isinstance(op, FramingOp):
            canvas = _framing_canvas(op, *source_size, *canvas_size)
            for sid in _check(op.segment_ids):
                segs[sid]["canvas"] = canvas
            segments_touched = True
        elif isinstance(op, ColorOp):
            # clipcannon_color_adjust takes absolute values: resolve deltas here.
            c = edl.color
            base_b, base_c, base_s = (
                (c.brightness, c.contrast, c.saturation) if c else (0.0, 1.0, 1.0)
            )
            special.append({"action": "clipcannon_color_adjust", "parameters": {
                "brightness": round(max(-1.0, min(1.0, base_b + op.brightness_delta)), 3),
                "contrast": round(max(0.0, min(3.0, base_c + op.contrast_delta)), 3),
                "saturation": round(max(0.0, min(3.0, base_s + op.saturation_delta)), 3),
            }})
        elif isinstance(op, OverlayOp):
            special.append({
                "action": "clipcannon_add_overlay",
                "parameters": op.model_dump(exclude={"op"}),
            })
        elif isinstance(op, MotionOp):
            for sid in _check(op.segment_ids):
                special.append({
                    "action": "clipcannon_add_motion",
                    "parameters": {"segment_id": sid, "effect": op.effect},
                })

    changes: dict[str, Any] = {}
    if segments_touched:
        kept = [segs[i] for i in order if i not in removed]
        if not kept:
            raise OpError("operations would remove every segment")
        changes["segments"] = kept
    if captions is not None:
        changes["captions"] = captions
    if audio is not None:
        changes["audio"] = audio
    return changes, special
