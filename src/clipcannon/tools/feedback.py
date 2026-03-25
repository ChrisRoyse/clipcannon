"""Feedback intent parser for ClipCannon iterative editing.

Translates natural language video feedback into structured EDL
modifications. Uses pattern matching (regex + keyword detection)
for deterministic, fast parsing -- no LLM calls.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from clipcannon.editing.edl import EditDecisionList, SegmentSpec


class FeedbackIntent(BaseModel):
    """Structured representation of parsed user feedback."""

    intent_type: str
    target_segment_ids: list[int] = Field(default_factory=list)
    target_timestamp_ms: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    raw_feedback: str = ""


# ============================================================
# TIMESTAMP PARSING
# ============================================================
_TS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\d{1,2}):(\d{2})(?:\.(\d+))?\b"), "mm_ss"),
    (re.compile(r"\b(?:at\s+)?(\d+)\s*(?:seconds?|sec|s)\b", re.I), "sec"),
    (re.compile(r"\b(?:at\s+(?:the\s+)?)?(\d+)\s*(?:minutes?|min)\s*(?:mark|in)?\b", re.I), "min"),
]


def parse_timestamp_ms(text: str) -> int | None:
    """Extract a timestamp in milliseconds from feedback text.

    Handles: "0:15", "0:15.5", "at 15 seconds", "15s", "1:30",
    "at the 1 minute mark".
    """
    for pat, fmt in _TS_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        if fmt == "mm_ss":
            mins, secs = int(m.group(1)), int(m.group(2))
            frac = float(f"0.{m.group(3)}") if m.group(3) else 0.0
            return int((mins * 60 + secs + frac) * 1000)
        if fmt == "sec":
            return int(m.group(1)) * 1000
        return int(m.group(1)) * 60_000
    return None


def find_segment_at_timestamp(
    edl: EditDecisionList, timestamp_ms: int,
) -> SegmentSpec | None:
    """Find the output segment containing the given timestamp."""
    for seg in edl.segments:
        if seg.output_start_ms <= timestamp_ms < seg.output_start_ms + seg.output_duration_ms:
            return seg
    return None


# ============================================================
# PARAMETER EXTRACTORS (private, one per intent type)
# ============================================================
def _seg_to_raw(seg: SegmentSpec) -> dict[str, Any]:
    """Serialize a SegmentSpec to a raw dict for modify_edit."""
    d: dict[str, Any] = {
        "source_start_ms": seg.source_start_ms,
        "source_end_ms": seg.source_end_ms,
        "speed": seg.speed,
    }
    if seg.transition_in:
        d["transition_in"] = seg.transition_in.model_dump()
    if seg.transition_out:
        d["transition_out"] = seg.transition_out.model_dump()
    return d


def _ext_transition_fix(_m: re.Match[str], text: str) -> dict[str, Any]:
    return {"timestamp_ms": parse_timestamp_ms(text), "transition_type": "crossfade", "duration_ms": 300}


def _ext_speed(m: re.Match[str], text: str) -> dict[str, Any]:
    lo = text.lower()
    if "too fast" in lo:
        return {"direction": "slower", "magnitude": 0.15}
    if "too slow" in lo:
        return {"direction": "faster", "magnitude": 0.15}
    if any(w in lo for w in ("speed up", "faster")):
        return {"direction": "faster", "magnitude": 0.15}
    if any(w in lo for w in ("slow down", "slower")):
        return {"direction": "slower", "magnitude": 0.15}
    return {"direction": "slower", "magnitude": 0.1}


def _ext_caption(_m: re.Match[str], text: str) -> dict[str, Any]:
    lo = text.lower()
    direction = "bigger" if any(w in lo for w in ("bigger", "larger", "increase")) else "smaller"
    return {"direction": direction}


def _ext_canvas(_m: re.Match[str], text: str) -> dict[str, Any]:
    lo = text.lower()
    direction = "bigger" if any(w in lo for w in ("too small", "bigger", "larger")) else "smaller"
    return {"direction": direction, "region": "speaker"}


def _ext_remove(_m: re.Match[str], text: str) -> dict[str, Any]:
    m2 = re.search(r"(?:where|about|when)\s+(.+?)(?:\.|$)", text, re.I)
    return {"search_text": m2.group(1).strip() if m2 else ""}


def _ext_audio(_m: re.Match[str], text: str) -> dict[str, Any]:
    lo = text.lower()
    if any(w in lo for w in ("too loud", "quieter", "lower the music", "turn down")):
        return {"direction": "quieter", "magnitude_db": -3.0}
    if any(w in lo for w in ("too quiet", "louder", "turn up")):
        return {"direction": "louder", "magnitude_db": 3.0}
    return {"direction": "quieter", "magnitude_db": -3.0}


def _ext_motion(_m: re.Match[str], text: str) -> dict[str, Any]:
    m2 = re.search(r"zoom\s+in\s+(?:on|when|at)\s+(.+?)(?:\.|$)", text, re.I)
    return {"effect": "zoom_in", "search_text": m2.group(1).strip() if m2 else ""}


def _ext_color(_m: re.Match[str], text: str) -> dict[str, Any]:
    lo = text.lower()
    if "warmer" in lo:
        return {"parameter": "saturation", "direction": "increase", "magnitude": 0.2}
    if "cooler" in lo:
        return {"parameter": "saturation", "direction": "decrease", "magnitude": 0.2}
    if "brighter" in lo:
        return {"parameter": "brightness", "direction": "increase", "magnitude": 0.15}
    if "darker" in lo:
        return {"parameter": "brightness", "direction": "decrease", "magnitude": 0.15}
    return {"parameter": "saturation", "direction": "increase", "magnitude": 0.1}


def _ext_overlay(_m: re.Match[str], text: str) -> dict[str, Any]:
    otype = "lower_third" if "lower third" in text.lower() else "title_card"
    m2 = re.search(r'["\u201c](.+?)["\u201d]', text)
    return {"overlay_type": otype, "text": m2.group(1) if m2 else ""}


def _ext_transition_add(_m: re.Match[str], text: str) -> dict[str, Any]:
    lo = text.lower()
    for kw, tt in [("crossfade", "crossfade"), ("fade", "fade"), ("wipe", "wipe_left"), ("dissolve", "dissolve")]:
        if kw in lo:
            return {"timestamp_ms": parse_timestamp_ms(text), "transition_type": tt, "duration_ms": 500}
    return {"timestamp_ms": parse_timestamp_ms(text), "transition_type": "crossfade", "duration_ms": 500}


# ============================================================
# PATTERN RULES: (regex, intent_type, base_confidence, extractor)
# ============================================================
_RULES: list[tuple[re.Pattern[str], str, float, Any]] = [
    (re.compile(r"(?:cut|transition|edit)\s+(?:at\s+)?\S*\s*(?:is\s+)?(?:too\s+)?(?:abrupt|harsh|jarring|rough|sudden)", re.I), "transition_fix", 0.85, _ext_transition_fix),
    (re.compile(r"(?:too\s+fast|too\s+slow|speed\s+up|slow\s*down|faster|slower)", re.I), "speed_adjust", 0.80, _ext_speed),
    (re.compile(r"(?:text|caption|subtitle|font)\s+(?:\S+\s+)*(?:bigger|smaller|larger|tiny|huge|increase|decrease)", re.I), "caption_resize", 0.85, _ext_caption),
    (re.compile(r"(?:make\s+(?:the\s+)?(?:text|caption|subtitle|font)\s+(?:bigger|smaller|larger))", re.I), "caption_resize", 0.90, _ext_caption),
    (re.compile(r"(?:speaker|webcam|face|person)\s+(?:\S+\s+)*(?:too\s+)?(?:small|big|tiny|huge|larger|smaller)", re.I), "canvas_resize", 0.75, _ext_canvas),
    (re.compile(r"(?:remove|cut\s+out|delete|drop)\s+(?:the\s+)?(?:part|section|bit)\s+(?:where|about|when)", re.I), "segment_remove", 0.80, _ext_remove),
    (re.compile(r"(?:music|background\s*(?:music|audio|track))\s+(?:\S+\s+)*(?:too\s+)?(?:loud|quiet|soft|low|high)", re.I), "audio_adjust", 0.85, _ext_audio),
    (re.compile(r"zoom\s+in\s+(?:on|when|at)", re.I), "motion_add", 0.80, _ext_motion),
    (re.compile(r"(?:make\s+it|make\s+(?:the\s+)?(?:video|clip))?\s*(?:warmer|cooler|brighter|darker)", re.I), "color_adjust", 0.80, _ext_color),
    (re.compile(r"(?:add\s+(?:a\s+)?(?:title|lower\s*third|text\s+overlay))", re.I), "overlay_add", 0.75, _ext_overlay),
    (re.compile(r"(?:(?:add\s+(?:a\s+)?)?(?:transition|crossfade|fade|wipe|dissolve)\s+(?:at|between))", re.I), "transition_add", 0.80, _ext_transition_add),
]


# ============================================================
# CORE PARSE
# ============================================================
def parse_feedback(feedback_text: str, edl: EditDecisionList) -> FeedbackIntent:
    """Parse natural language feedback into a structured FeedbackIntent.

    Uses pattern matching (regex + keyword detection) to classify
    feedback. No LLM calls -- deterministic and fast.
    """
    text = feedback_text.strip()
    if not text:
        return FeedbackIntent(intent_type="unknown", confidence=0.0, raw_feedback=feedback_text)

    best: FeedbackIntent | None = None
    best_conf = 0.0

    for pattern, itype, base_conf, extractor in _RULES:
        match = pattern.search(text)
        if not match:
            continue
        params = extractor(match, text)
        conf = base_conf
        ts_ms = parse_timestamp_ms(text)
        target_ids: list[int] = []
        if ts_ms is not None:
            seg = find_segment_at_timestamp(edl, ts_ms)
            if seg is not None:
                target_ids = [seg.segment_id]
                conf = min(conf + 0.05, 1.0)
        if conf > best_conf:
            best_conf = conf
            best = FeedbackIntent(
                intent_type=itype, target_segment_ids=target_ids,
                target_timestamp_ms=ts_ms, parameters=params,
                confidence=conf, raw_feedback=feedback_text,
            )

    return best or FeedbackIntent(intent_type="unknown", confidence=0.0, raw_feedback=feedback_text)


# ============================================================
# INTENT -> CHANGES CONVERSION
# ============================================================
def intent_to_changes(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    """Convert a FeedbackIntent into a changes dict for modify_edit."""
    handler = _INTENT_HANDLERS.get(intent.intent_type)
    return handler(intent, edl) if handler else {}


def _h_transition_fix(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    t_type = intent.parameters.get("transition_type", "crossfade")
    dur = intent.parameters.get("duration_ms", 300)
    segs = []
    for seg in edl.segments:
        d = _seg_to_raw(seg)
        if seg.segment_id in intent.target_segment_ids:
            d["transition_in"] = {"type": t_type, "duration_ms": dur}
        segs.append(d)
    return {"segments": segs}


def _h_speed(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    direction = intent.parameters.get("direction", "slower")
    mag = intent.parameters.get("magnitude", 0.15)
    tids = intent.target_segment_ids
    segs = []
    for seg in edl.segments:
        d = _seg_to_raw(seg)
        if not tids or seg.segment_id in tids:
            d["speed"] = max(0.25, seg.speed - mag) if direction == "slower" else min(4.0, seg.speed + mag)
        segs.append(d)
    return {"segments": segs}


def _h_caption(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    delta = 8 if intent.parameters.get("direction", "bigger") == "bigger" else -8
    return {"captions": {"font_size": max(8, min(200, edl.captions.font_size + delta))}}


def _h_canvas(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    delta = 0.05 if intent.parameters.get("direction", "bigger") == "bigger" else -0.05
    return {"crop": {"safe_area_pct": max(0.0, min(1.0, edl.crop.safe_area_pct + delta))}}


def _h_remove(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    if not intent.target_segment_ids:
        return {}
    remaining = [_seg_to_raw(s) for s in edl.segments if s.segment_id not in intent.target_segment_ids]
    return {"segments": remaining} if remaining else {}


def _h_audio(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    mag = intent.parameters.get("magnitude_db", -3.0)
    return {"audio": {"source_volume_db": edl.audio.source_volume_db + mag}}


def _h_motion(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    tids = intent.target_segment_ids or ([edl.segments[0].segment_id] if edl.segments else [])
    if not tids:
        return {}
    return {
        "segments": [_seg_to_raw(s) for s in edl.segments],
        "_motion_targets": {"segment_ids": tids, "effect": intent.parameters.get("effect", "zoom_in")},
    }


def _h_color(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    p = intent.parameters
    param, direction, mag = p.get("parameter", "saturation"), p.get("direction", "increase"), p.get("magnitude", 0.2)
    c = edl.color
    b, co, s, g, h = (c.brightness, c.contrast, c.saturation, c.gamma, c.hue_shift) if c else (0.0, 1.0, 1.0, 1.0, 0.0)
    sign = 1.0 if direction == "increase" else -1.0
    if param == "saturation":
        s = max(0.0, min(3.0, s + sign * mag))
    elif param == "brightness":
        b = max(-1.0, min(1.0, b + sign * mag))
    elif param == "contrast":
        co = max(0.0, min(3.0, co + sign * mag))
    return {"_color": {"brightness": b, "contrast": co, "saturation": s, "gamma": g, "hue_shift": h}}


def _h_overlay(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    return {"_overlay": {"overlay_type": intent.parameters.get("overlay_type", "title_card"), "text": intent.parameters.get("text", "")}}


def _h_transition_add(intent: FeedbackIntent, edl: EditDecisionList) -> dict[str, Any]:
    t_type = intent.parameters.get("transition_type", "crossfade")
    dur = intent.parameters.get("duration_ms", 500)
    segs = []
    for seg in edl.segments:
        d = _seg_to_raw(seg)
        if seg.segment_id in intent.target_segment_ids:
            d["transition_in"] = {"type": t_type, "duration_ms": dur}
        segs.append(d)
    return {"segments": segs}


_INTENT_HANDLERS: dict[str, Any] = {
    "transition_fix": _h_transition_fix,
    "speed_adjust": _h_speed,
    "caption_resize": _h_caption,
    "canvas_resize": _h_canvas,
    "segment_remove": _h_remove,
    "audio_adjust": _h_audio,
    "motion_add": _h_motion,
    "color_adjust": _h_color,
    "overlay_add": _h_overlay,
    "transition_add": _h_transition_add,
}
