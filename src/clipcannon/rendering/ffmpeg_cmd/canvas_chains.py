"""Per-segment canvas filter chains: regions, zoom, tracked pieces, plain, region scale."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .filters import (
    _apply_color_grading,
    _build_delogo_chain,
    _segment_pts,
    _speed_resample,
)

if TYPE_CHECKING:
    from clipcannon.editing.edl import CanvasRegion, SegmentCanvasSpec, SegmentSpec
    from clipcannon.rendering.profiles import EncodingProfile


def _build_region_scale(region: CanvasRegion) -> str:
    """Build FFmpeg scale filter for a canvas region respecting fit_mode.

    - stretch: Force exact output dimensions (may distort aspect ratio)
    - contain: Fit inside output dimensions, pad with black (no distort)
    - cover: Fill output dimensions completely, center-crop excess (no distort)

    Args:
        region: Canvas region with source and output dimensions + fit_mode.

    Returns:
        FFmpeg filter expression string (scale + optional pad/crop).
    """
    ow = region.output_width
    oh = region.output_height
    fit = region.fit_mode

    if fit == "stretch":
        return f"scale={ow}:{oh},setsar=1"

    if fit == "contain":
        # Scale to fit inside output, preserving aspect ratio.
        # Then pad to exact output size (centered, black padding).
        return (
            f"scale={ow}:{oh}:force_original_aspect_ratio=decrease,"
            f"pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )

    # cover (default): Scale to fill output, preserving aspect ratio.
    # Then center-crop to exact output size.
    return (
        f"scale={ow}:{oh}:force_original_aspect_ratio=increase,"
        f"crop={ow}:{oh},setsar=1"
    )


def _build_segment_canvas_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
    cw: int,
    ch: int,
    canvas: SegmentCanvasSpec,
    removals: list | None = None,
) -> None:
    """Build filter chain for one segment with canvas regions.

    Creates an independent compositing pipeline: trim source,
    create background, split into N copies, crop+scale each
    region, overlay onto background.

    Args:
        filters: Accumulating filter parts (modified in place).
        seg: Segment specification.
        idx: Segment index for label naming.
        profile: Encoding profile.
        cw: Canvas width.
        ch: Canvas height.
        canvas: Canvas spec with regions for this segment.
        removals: Regions to remove via FFmpeg delogo filter.
    """
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0
    bg_hex = canvas.background_color.lstrip("#")
    regions = sorted(canvas.regions, key=lambda r: r.z_index)
    n_regions = len(regions)
    seg_dur_s = (end_s - start_s) / seg.speed

    delogo_chain = _build_delogo_chain(removals)

    # 1. Trim source (with delogo if removals present), retimed by speed
    filters.append(
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts={_segment_pts(seg)}{_speed_resample(seg, profile.fps)}"
        f"{delogo_chain}[seg{idx}_src]"
    )

    # 2+3. Background + split into copies for regions
    use_blur_bg = canvas.background_color.lower() == "blur"

    if use_blur_bg:
        # Split into N+1 copies: one for blur bg, N for regions
        total_copies = n_regions + 1
        split_out = (
            f"[seg{idx}_bgcopy]"
            + "".join(f"[seg{idx}_r{j}]" for j in range(n_regions))
        )
        filters.append(
            f"[seg{idx}_src]split={total_copies}{split_out}"
        )
        # Blur background: scale to fill canvas, apply heavy blur
        filters.append(
            f"[seg{idx}_bgcopy]"
            f"scale={cw}:{ch}:force_original_aspect_ratio=increase,"
            f"crop={cw}:{ch},gblur=sigma=40,setsar=1"
            f"[seg{idx}_bg]"
        )
    else:
        # Solid color background
        filters.append(
            f"color=c=0x{bg_hex}:s={cw}x{ch}:d={seg_dur_s + 1:.1f}"
            f":r={profile.fps},setsar=1[seg{idx}_bg]"
        )
        # Split trimmed source into N copies for regions
        if n_regions == 1:
            filters.append(f"[seg{idx}_src]null[seg{idx}_r0]")
        else:
            split_out = "".join(
                f"[seg{idx}_r{j}]" for j in range(n_regions)
            )
            filters.append(
                f"[seg{idx}_src]split={n_regions}{split_out}"
            )

    # 4. Crop and scale each region (respecting fit_mode)
    for j, region in enumerate(regions):
        scale_filter = _build_region_scale(region)
        filters.append(
            f"[seg{idx}_r{j}]"
            f"crop={region.source_width}:{region.source_height}"
            f":{region.source_x}:{region.source_y},"
            f"{scale_filter}"
            f"[seg{idx}_cr{j}]"
        )

    # 5. Overlay each region onto canvas
    current = f"seg{idx}_bg"
    for j, region in enumerate(regions):
        out = f"seg{idx}_ov{j}" if j < n_regions - 1 else f"seg{idx}_composed"
        filters.append(
            f"[{current}][seg{idx}_cr{j}]"
            f"overlay=x={region.output_x}:y={region.output_y}"
            f":shortest=1[{out}]"
        )
        current = out

    # 6. Apply per-segment color grading
    color_in = f"seg{idx}_composed"
    if seg.color is not None:
        color_in = _apply_color_grading(
            filters, color_in, f"seg{idx}_colored", seg.color,
        )

    # Final label for this segment
    if color_in != f"v{idx}":
        filters.append(f"[{color_in}]null[v{idx}]")


def _build_segment_zoom_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
    cw: int,
    ch: int,
    removals: list | None = None,
) -> None:
    """Build filter chain for one segment with animated zoom.

    Interpolates the crop window (position and size) from the start
    region to the end region over the segment duration via a per-frame
    scale followed by a fixed-size crop. After setpts=PTS-STARTPTS, t
    resets to 0 per segment.

    Args:
        filters: Accumulating filter parts (modified in place).
        seg: Segment specification with canvas.zoom set.
        idx: Segment index for label naming.
        profile: Encoding profile.
        cw: Canvas width.
        ch: Canvas height.
        removals: Regions to remove via FFmpeg delogo filter.
    """
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0
    zoom = seg.canvas.zoom  # type: ignore[union-attr]
    seg_dur_s = (end_s - start_s) / seg.speed

    delogo_chain = _build_delogo_chain(removals)

    # Trim, reset PTS so t starts at 0, and apply speed so t runs in output
    # time (the easing below spans seg_dur_s, which is already speed-scaled)
    filters.append(
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts={_segment_pts(seg)}{_speed_resample(seg, profile.fps)}"
        f"{delogo_chain}[seg{idx}_src]"
    )

    # Build easing progress expression
    d = f"{seg_dur_s:.3f}"
    p_raw = f"min(t/{d}\\,1)"

    if zoom.easing == "ease_in":
        progress = f"pow({p_raw}\\,2)"
    elif zoom.easing == "ease_out":
        progress = f"(2*{p_raw}-pow({p_raw}\\,2))"
    elif zoom.easing == "ease_in_out":
        progress = f"(3*pow({p_raw}\\,2)-2*pow({p_raw}\\,3))"
    else:  # linear
        progress = p_raw

    def lerp(start_val: int, end_val: int) -> str:
        delta = end_val - start_val
        if delta == 0:
            return str(start_val)
        return f"({start_val}+{delta}*{progress})"

    crop_w = lerp(zoom.start_w, zoom.end_w)
    crop_h = lerp(zoom.start_h, zoom.end_h)
    crop_x = lerp(zoom.start_x, zoom.end_x)
    crop_y = lerp(zoom.start_y, zoom.end_y)

    # FFmpeg's crop evaluates w/h once at configuration, so a time-varying
    # crop size never animates (#69, measured: the window snapped to one size
    # while x/y kept panning, drifting the target off-centre). Instead scale
    # the whole frame per frame by canvas/window, then cut a fixed canvas-sized
    # window whose offset is the window origin in the scaled frame. Dimensions
    # round up to even so the scaled frame always covers the canvas.
    crop_scale = (
        f"scale=w='2*ceil(iw*{cw}/{crop_w}/2)':h='2*ceil(ih*{ch}/{crop_h}/2)'"
        f":eval=frame,"
        f"crop=w={cw}:h={ch}:x='{crop_x}*{cw}/{crop_w}':y='{crop_y}*{ch}/{crop_h}',"
        f"setsar=1"
    )

    if seg.color is not None:
        zoom_out_label = f"seg{idx}_zoomed"
        filters.append(
            f"[seg{idx}_src]{crop_scale}[{zoom_out_label}]"
        )
        final = _apply_color_grading(
            filters, zoom_out_label, f"v{idx}", seg.color,
        )
        if final != f"v{idx}":
            filters.append(f"[{final}]null[v{idx}]")
    else:
        filters.append(f"[seg{idx}_src]{crop_scale}[v{idx}]")


def _piecewise_expr(keyframes: list[tuple[float, int]]) -> str:
    """FFmpeg expression of t: linear interpolation through (t, value) points.

    Commas are escaped for use inside a quoted filter option.
    """
    if len(keyframes) == 1:
        return str(keyframes[0][1])
    expr = str(keyframes[-1][1])
    for (t0, v0), (t1, v1) in reversed(list(zip(keyframes, keyframes[1:], strict=False))):
        if t1 <= t0:
            continue
        seg = f"{v0}+({v1 - v0})*(t-{t0:.3f})/{t1 - t0:.3f}" if v1 != v0 else str(v0)
        expr = f"if(lt(t\\,{t1:.3f})\\,{seg}\\,{expr})"
    return expr


def _build_segment_track_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    cw: int,
    ch: int,
    removals: list | None = None,
    fps: int = 30,
) -> None:
    """Speaker-following framing: one crop path per shot piece, concatenated.

    FFmpeg's crop evaluates w/h once but x/y per frame, so each piece has a
    fixed window (constant zoom within a shot) and a time-varying position.
    """
    track = seg.canvas.track  # type: ignore[union-attr]
    delogo_chain = _build_delogo_chain(removals)
    labels: list[str] = []
    for k, piece in enumerate(track.pieces):
        a, b = piece.start_ms / 1000.0, piece.end_ms / 1000.0
        xs = [((t - piece.start_ms) / 1000.0, x) for t, x, _ in piece.keyframes]
        ys = [((t - piece.start_ms) / 1000.0, y) for t, _, y in piece.keyframes]
        label = f"seg{idx}_p{k}"
        filters.append(
            f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS{delogo_chain},"
            f"crop=w={piece.width}:h={piece.height}"
            f":x='{_piecewise_expr(xs)}':y='{_piecewise_expr(ys)}',"
            f"scale={cw}:{ch}:flags=lanczos,setsar=1[{label}]"
        )
        labels.append(label)
    speed = (f",setpts=PTS/{seg.speed}{_speed_resample(seg, fps)}"
             if seg.speed != 1.0 else "")
    joined = f"seg{idx}_tracked"
    if len(labels) == 1:
        filters.append(f"[{labels[0]}]null{speed}[{joined}]")
    else:
        filters.append(
            "".join(f"[{lb}]" for lb in labels)
            + f"concat=n={len(labels)}:v=1:a=0{speed}[{joined}]"
        )
    if seg.color is not None:
        final = _apply_color_grading(filters, joined, f"v{idx}", seg.color)
        if final != f"v{idx}":
            filters.append(f"[{final}]null[v{idx}]")
    else:
        filters.append(f"[{joined}]null[v{idx}]")


def _build_segment_plain_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
    removals: list | None = None,
) -> None:
    """Build filter chain for a segment with no canvas: trim + scale.

    Args:
        filters: Accumulating filter parts (modified in place).
        seg: Segment specification.
        idx: Segment index for label naming.
        profile: Encoding profile.
        removals: Regions to remove via FFmpeg delogo filter.
    """
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0
    delogo_chain = _build_delogo_chain(removals)

    trim_scale = (
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts={_segment_pts(seg)}{_speed_resample(seg, profile.fps)}{delogo_chain},"
        f"scale={profile.width}:{profile.height},setsar=1"
    )

    if seg.color is not None:
        filters.append(f"{trim_scale}[seg{idx}_scaled]")
        final = _apply_color_grading(
            filters, f"seg{idx}_scaled", f"v{idx}", seg.color,
        )
        if final != f"v{idx}":
            filters.append(f"[{final}]null[v{idx}]")
    else:
        filters.append(f"{trim_scale}[v{idx}]")
