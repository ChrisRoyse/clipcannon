"""Canvas region pre-computation and content classification."""

from __future__ import annotations

# Output canvas (9:16 vertical)
CANVAS_W, CANVAS_H = 1080, 1920
LAYOUT_HEIGHTS = {"A": (576, 1344), "B": (768, 1152)}
PIP_SIZE, PIP_POS = 240, (24, 140)
EYE_LINE_PCT = 0.38


def _region(
    rid: str, sx: int, sy: int, sw: int, sh: int,
    ox: int, oy: int, ow: int, oh: int, z: int,
    fit: str = "cover",
) -> dict[str, object]:
    """Build a canvas region dict."""
    return {
        "region_id": rid,
        "source_x": sx, "source_y": sy,
        "source_width": sw, "source_height": sh,
        "output_x": ox, "output_y": oy,
        "output_width": ow, "output_height": oh,
        "z_index": z, "fit_mode": fit,
    }


def _pick_screen_fit_mode(cw: int, ch: int, ow: int, oh: int) -> str:
    """Choose fit_mode: contain for wide content, cover for vertical."""
    content_aspect = cw / max(ch, 1)
    output_aspect = ow / max(oh, 1)
    return "contain" if content_aspect > output_aspect * 1.3 else "cover"


def _compute_speaker_crop(
    face: dict[str, object], out_w: int, out_h: int,
    frame_w: int, frame_h: int,
) -> dict[str, int]:
    """Compute source crop for speaker region centered on face."""
    fx, fy = int(face["x"]), int(face["y"])
    fw, fh = int(face["w"]), int(face["h"])
    aspect = out_w / out_h
    if aspect >= 1.0:
        crop_h = int(fh * 2.5)
        crop_w = int(crop_h * aspect)
    else:
        crop_w = int(fw / 0.65)
        crop_h = int(crop_w / aspect)
    eye_y = fy + fh * EYE_LINE_PCT
    face_cx = fx + fw / 2.0
    crop_y = int(eye_y - crop_h / 3.0)
    crop_x = int(face_cx - crop_w / 2)
    crop_x = max(0, min(crop_x, frame_w - crop_w))
    crop_y = max(0, min(crop_y, frame_h - crop_h))
    return {"x": crop_x, "y": crop_y,
            "w": min(crop_w, frame_w), "h": min(crop_h, frame_h)}


def _build_canvas_regions(
    face: dict[str, object] | None, webcam: dict[str, int] | None,
    content: dict[str, int], frame_w: int, frame_h: int,
) -> dict[str, list[dict[str, object]]]:
    """Pre-compute canvas regions for all layout types."""
    result: dict[str, list[dict[str, object]]] = {}
    cx, cy, cw, ch = content["x"], content["y"], content["w"], content["h"]

    if face is None:
        fm = _pick_screen_fit_mode(cw, ch, CANVAS_W, CANVAS_H)
        scr = _region("screen", cx, cy, cw, ch,
                       0, 0, CANVAS_W, CANVAS_H, 1, fm)
        for layout in ("A", "B", "C", "D"):
            result[layout] = [scr]
        return result

    # Use webcam region for speaker (stable, shows full person)
    if webcam is not None:
        wx, wy, ww, wh = webcam["x"], webcam["y"], webcam["w"], webcam["h"]
    else:
        sc = _compute_speaker_crop(face, CANVAS_W, 576, frame_w, frame_h)
        wx, wy, ww, wh = sc["x"], sc["y"], sc["w"], sc["h"]

    for name, (spk_h, scr_h) in LAYOUT_HEIGHTS.items():
        fm = _pick_screen_fit_mode(cw, ch, CANVAS_W, scr_h)
        result[name] = [
            _region("speaker", wx, wy, ww, wh,
                    0, 0, CANVAS_W, spk_h, 2, "contain"),
            _region("screen", cx, cy, cw, ch,
                    0, spk_h, CANVAS_W, scr_h, 1, fm),
        ]

    pc = _compute_speaker_crop(face, PIP_SIZE, PIP_SIZE, frame_w, frame_h)
    fm = _pick_screen_fit_mode(cw, ch, CANVAS_W, CANVAS_H)
    result["C"] = [
        _region("screen", cx, cy, cw, ch,
                0, 0, CANVAS_W, CANVAS_H, 1, fm),
        _region("pip_speaker", pc["x"], pc["y"], pc["w"], pc["h"],
                PIP_POS[0], PIP_POS[1], PIP_SIZE, PIP_SIZE, 2),
    ]

    result["D"] = [
        _region("speaker_full", wx, wy, ww, wh,
                0, 0, CANVAS_W, CANVAS_H, 1, "contain"),
    ]
    return result


def _classify_content_type(
    face: dict[str, object] | None,
    webcam: dict[str, int] | None,
    content: dict[str, int],
    frame_w: int,
    frame_h: int,
) -> str:
    """Classify the content type of a scene based on detected regions.

    Uses heuristics from face area percentage, webcam presence, and
    content region size to determine the dominant content type.

    Returns one of: 'talking_head', 'screen_with_webcam', 'screen_only',
    'presentation', 'split_content', 'unknown'.
    """
    face_area_pct = 0.0
    if face is not None:
        face_area = int(face["w"]) * int(face["h"])
        face_area_pct = face_area / (frame_w * frame_h) * 100

    has_webcam = webcam is not None
    content_area_pct = (content["w"] * content["h"]) / (frame_w * frame_h) * 100

    # Face takes up >30% of frame = talking head
    if face_area_pct > 30:
        return "talking_head"

    # Webcam detected with content area = screen recording with webcam
    if has_webcam and content_area_pct > 40:
        return "screen_with_webcam"

    # Face detected but small, with large content area
    if face is not None and face_area_pct > 1 and content_area_pct > 50:
        return "screen_with_webcam"

    # No face, large content area = pure screen content
    if face is None and content_area_pct > 60:
        return "screen_only"

    # Small content area with face = presentation/slide
    if face is not None and content_area_pct < 40:
        return "presentation"

    return "screen_only"
