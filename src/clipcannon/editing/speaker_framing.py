"""Virtual camera operator: frame the active speaker for vertical output.

Uses the speaker_tracking tables (face_shots, face_tracks, face_detections,
speaker_segments) to produce, for a source time range, a TrackedFraming:
one piece per shot with a fixed window size and a smoothed x/y path.

Per 100 ms frame the target is, in order:
  1. the face of the person speaking now (speaker_segments, which binds face
     and voice evidence), if they are in this shot; in a pause, the person
     about to speak, then the person who just spoke;
  2. otherwise the face the active-speaker model scores as talking;
  3. otherwise the previous target, if still visible;
  4. otherwise the largest face.
A new target must persist 400 ms before the frame moves to it (no flicker).
Within a shot the camera eases with a deadzone; across a cut it snaps.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from clipcannon.editing.edl import TrackedFraming, TrackedPiece

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import EditDecisionList

STEP_MS = 100
FACE_FRAC = 0.28          # target face height as a fraction of the window height
MAX_ZOOM = 1.6            # never crop smaller than 1/1.6 of the source height
FACE_CENTER_Y = 0.40      # face centre sits 40% down the window (headroom)
SWITCH_HOLD = 4           # frames a new target must persist before switching
DEADZONE = 0.05           # fraction of the window the subject may drift freely
EASE = 0.30               # per-frame approach rate toward the desired position
SPEAKER_CARRY_MS = 2000   # keep the last speaker through short pauses
SPEAKER_LOOKAHEAD_MS = 1500  # in a pause, frame whoever speaks next (editor's cut)
RDP_TOL_PX = 3.0


class SpeakerTrackingMissingError(RuntimeError):
    """Speaker framing was requested but the speaker_tracking stage has no data."""

    code = "SPEAKER_TRACKING_MISSING"

    def __init__(self, project_id: str) -> None:
        super().__init__(
            f"Speaker framing was requested (crop mode auto + face_tracking) but project "
            f"{project_id} has no speaker_tracking data. Remediation: run the pipeline "
            "stage 'speaker_tracking', or set crop.face_tracking=false / give the "
            "segments explicit framing.")
        self.remediation = ("run stage speaker_tracking, or set crop.face_tracking=false, "
                            "or pass explicit framing")


@dataclass
class _Det:
    track_id: int
    person_id: int | None
    x1: float
    y1: float
    x2: float
    y2: float
    asd: float | None

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2


def wants_speaker_framing(edl: EditDecisionList) -> bool:
    """True when the EDL asks the renderer to follow the active speaker."""
    return (edl.crop.mode == "auto" and bool(edl.crop.face_tracking)
            and edl.crop.layout == "crop" and any(s.canvas is None for s in edl.segments))


def require_speaker_tracking(db_path: Path, project_id: str) -> None:
    """Raise SpeakerTrackingMissingError unless the stage has stored shots for the project."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM face_shots WHERE project_id=?",
                        (project_id,)).fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    finally:
        con.close()
    if not n:
        raise SpeakerTrackingMissingError(project_id)


def _load(db_path: Path, project_id: str, s: int, e: int) -> tuple[
        list[tuple[int, int, int]], dict[int, list[_Det]], list[tuple[int, int, int | None]]]:
    require_speaker_tracking(db_path, project_id)
    con = sqlite3.connect(str(db_path))
    try:
        shots = con.execute(
            "SELECT shot_id, start_ms, end_ms FROM face_shots WHERE project_id=? "
            "AND end_ms > ? AND start_ms < ? ORDER BY start_ms", (project_id, s, e)).fetchall()
        person = dict(con.execute(
            "SELECT track_id, person_id FROM face_tracks WHERE project_id=?", (project_id,)))
        dets: dict[int, list[_Det]] = {}
        for t, tr, x1, y1, x2, y2, a in con.execute(
                "SELECT t_ms, track_id, x1, y1, x2, y2, asd FROM face_detections "
                "WHERE project_id=? AND t_ms >= ? AND t_ms <= ?", (project_id, s - STEP_MS, e)):
            dets.setdefault(int(t), []).append(_Det(tr, person.get(tr), x1, y1, x2, y2, a))
        segs = con.execute(
            "SELECT start_ms, end_ms, person_id FROM speaker_segments WHERE project_id=? "
            "AND end_ms > ? AND start_ms < ? ORDER BY start_ms",
            (project_id, s - SPEAKER_CARRY_MS, e + SPEAKER_LOOKAHEAD_MS)).fetchall()
        return shots, dets, segs
    finally:
        con.close()


def _speakers_at(segs: list[tuple[int, int, int | None]], t: int) -> list[int]:
    """People to frame at t, in priority order.

    The person speaking now; in a pause, the person about to speak (within
    SPEAKER_LOOKAHEAD_MS, as an editor would cut) before the one who just
    stopped (within SPEAKER_CARRY_MS). Offline analysis makes look-ahead free.
    """
    now = upcoming = last = None
    for s, e, p in segs:
        if s <= t < e:
            now = p
        elif s > t and s - t <= SPEAKER_LOOKAHEAD_MS and upcoming is None:
            upcoming = p
        elif e <= t and t - e <= SPEAKER_CARRY_MS:
            last = p
    return [p for p in (now, upcoming, last) if p is not None]


def _choose(dets: list[_Det], speakers: list[int], prev_track: int | None) -> _Det | None:
    if not dets:
        return None
    for speaker in speakers:
        mine = [d for d in dets if d.person_id == speaker]
        if mine:
            return max(mine, key=lambda d: d.h)
    talking = [d for d in dets if d.asd is not None and d.asd > 0]
    if talking:
        return max(talking, key=lambda d: d.asd or 0)
    if prev_track is not None:
        for d in dets:
            if d.track_id == prev_track:
                return d
    return max(dets, key=lambda d: d.h)


def _rdp(points: list[tuple[float, float]], tol: float) -> list[int]:
    """Indices kept by Ramer-Douglas-Peucker on (t, v) points."""
    if len(points) < 3:
        return list(range(len(points)))
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (t0, v0), (t1, v1) = points[a], points[b]
        best, dmax = -1, tol
        for i in range(a + 1, b):
            t, v = points[i]
            interp = v0 + (v1 - v0) * (t - t0) / (t1 - t0) if t1 != t0 else v0
            if abs(v - interp) > dmax:
                best, dmax = i, abs(v - interp)
        if best >= 0:
            keep.add(best)
            stack += [(a, best), (best, b)]
    return sorted(keep)


def compute_tracked_framing(
    db_path: Path, project_id: str, src_start_ms: int, src_end_ms: int,
    *, source_size: tuple[int, int], canvas_size: tuple[int, int],
) -> TrackedFraming | None:
    """Speaker-following framing for one source range.

    Returns None only when the stage ran but no face is visible in this range
    (nothing to follow; the caller records that). Raises SpeakerTrackingMissingError
    when the stage never ran for the project.
    """
    shots, dets, segs = _load(db_path, project_id, src_start_ms, src_end_ms)
    if not shots or not dets:
        return None
    sw, sh = source_size
    cw, ch = canvas_size
    pieces: list[TrackedPiece] = []
    speakers_used: set[str] = set()

    for _shot_id, s0, s1 in shots:
        a, b = max(s0, src_start_ms), min(s1, src_end_ms)
        if b - a < 40:
            continue
        grid = list(range(a - a % STEP_MS, b, STEP_MS))
        # Pass 1: target per frame with hysteresis.
        chosen: list[_Det | None] = []
        cur: int | None = None
        pending: int | None = None
        pending_n = 0
        for t in grid:
            spks = _speakers_at(segs, t)
            d = _choose(dets.get(t, []), spks, cur)
            if d is None:
                chosen.append(None)
                continue
            if cur is None or d.track_id == cur:
                cur, pending, pending_n = d.track_id, None, 0
            elif not any(x.track_id == cur for x in dets.get(t, [])):
                cur, pending, pending_n = d.track_id, None, 0  # old target gone: switch now
            else:
                pending_n = pending_n + 1 if pending == d.track_id else 1
                pending = d.track_id
                if pending_n >= SWITCH_HOLD:
                    cur, pending, pending_n = d.track_id, None, 0
            hold = next((x for x in dets.get(t, []) if x.track_id == cur), d)
            chosen.append(hold)
            if hold.person_id is not None and hold.person_id in spks:
                speakers_used.add(f"P{hold.person_id}")

        heights = [d.h for d in chosen if d is not None]
        if heights:
            win_h = float(np.clip(np.median(heights) / FACE_FRAC, sh / MAX_ZOOM, sh))
        else:
            win_h = float(sh)
        win_w = win_h * cw / ch
        if win_w > sw:
            win_w, win_h = float(sw), sw * ch / cw
        win_wpx, win_hpx = int(win_w) // 2 * 2, int(win_h) // 2 * 2

        # Pass 2: desired position -> eased path.
        xs, ys = [], []
        px = py = None
        for d in chosen:
            if d is None:
                tx = (sw - win_wpx) / 2 if px is None else px
                ty = (sh - win_hpx) / 2 if py is None else py
            else:
                tx = d.cx - win_wpx / 2
                ty = d.cy - FACE_CENTER_Y * win_hpx
            tx = min(max(tx, 0.0), sw - win_wpx)
            ty = min(max(ty, 0.0), sh - win_hpx)
            if px is None:
                px, py = tx, ty
            else:
                if abs(tx - px) > DEADZONE * win_wpx:
                    px += EASE * (tx - px - np.sign(tx - px) * DEADZONE * win_wpx * 0.5)
                if abs(ty - py) > DEADZONE * win_hpx:
                    py += EASE * (ty - py - np.sign(ty - py) * DEADZONE * win_hpx * 0.5)
            xs.append(px)
            ys.append(py)

        keep = sorted(set(_rdp(list(zip(grid, xs, strict=True)), RDP_TOL_PX))
                      | set(_rdp(list(zip(grid, ys, strict=True)), RDP_TOL_PX)))
        kfs = [(max(grid[i], a), int(round(xs[i])), int(round(ys[i]))) for i in keep]
        pieces.append(TrackedPiece(start_ms=a, end_ms=b, width=win_wpx, height=win_hpx,
                                   keyframes=kfs))

    if not pieces:
        return None
    # Pieces must tile the range exactly, or video and audio lengths diverge.
    pieces[0].start_ms = src_start_ms
    pieces[-1].end_ms = src_end_ms
    for prev, nxt in zip(pieces, pieces[1:], strict=False):
        nxt.start_ms = prev.end_ms
    return TrackedFraming(pieces=pieces, speakers=sorted(speakers_used))
