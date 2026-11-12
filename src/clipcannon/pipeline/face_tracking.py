"""Shots, face tracks, people and lip activity from face_worker output.

Pure numpy (no GPU); everything here is deterministic given the worker's .npz.

Vocabulary:
    shot    a run of frames between hard cuts
    track   one face followed through consecutive frames of one shot
    person  tracks (across shots) whose identity embeddings agree
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

CUT_MIN_L1 = 0.35          # histogram L1 jump that always counts as a cut
CUT_MEDIAN_FACTOR = 6.0    # ...or this many times the median frame-to-frame change
TRACK_IOU = 0.25
TRACK_MAX_GAP = 4          # frames a track may go undetected and continue
TRACK_MIN_LEN = 5          # frames; shorter tracks are discarded as noise
PERSON_SIM = 0.45          # cosine similarity to merge reliable tracks into a person
PERSON_ASSIGN_SIM = 0.30   # weaker threshold for small-face tracks joining a person
RELIABLE_FACE_PX = 60      # face height at which identity embeddings are trustworthy
LIP_WINDOW = 5             # frames each side for the lip-activity std (+-0.5 s @10 fps)


@dataclass
class Track:
    track_id: int
    shot_id: int
    frames: list[int] = field(default_factory=list)    # frame indices
    dets: list[int] = field(default_factory=list)      # detection indices
    person_id: int = -1
    embedding: np.ndarray | None = None
    median_height: float = 0.0


@dataclass
class FaceAnalysis:
    frame_t_ms: np.ndarray
    shot_of_frame: np.ndarray            # [F] shot id per frame
    shots: list[tuple[int, int]]         # (first_frame, last_frame) per shot
    tracks: list[Track]
    track_of_det: np.ndarray             # [D] track id per detection, -1 if dropped
    lip_activity: np.ndarray             # [D] rolling std of mouth openness
    persons: dict[int, dict[str, object]]
    source_size: tuple[int, int]


def detect_shots(hist: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Hard cuts from frame-to-frame HSV histogram L1 jumps."""
    n = len(hist)
    if n == 0:
        return np.zeros(0, np.int32), []
    diff = np.zeros(n)
    diff[1:] = np.abs(hist[1:] - hist[:-1]).sum(axis=1)
    thr = max(CUT_MIN_L1, CUT_MEDIAN_FACTOR * float(np.median(diff[1:])) if n > 1 else 1.0)
    cuts = [0] + [i for i in range(1, n) if diff[i] > thr]
    shot_of_frame = np.zeros(n, np.int32)
    shots: list[tuple[int, int]] = []
    for s, start in enumerate(cuts):
        end = cuts[s + 1] - 1 if s + 1 < len(cuts) else n - 1
        shot_of_frame[start:end + 1] = s
        shots.append((start, end))
    return shot_of_frame, shots


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / ua) if ua > 0 else 0.0


def build_tracks(det_frame: np.ndarray, det_bbox: np.ndarray,
                 shot_of_frame: np.ndarray) -> tuple[list[Track], np.ndarray]:
    """Greedy IoU association frame to frame, never across a cut."""
    order = np.argsort(det_frame, kind="stable")
    tracks: list[Track] = []
    active: list[int] = []
    for d in order:
        f = int(det_frame[d])
        shot = int(shot_of_frame[f])
        active = [t for t in active
                  if tracks[t].shot_id == shot and f - tracks[t].frames[-1] <= TRACK_MAX_GAP + 1]
        best, best_iou = -1, TRACK_IOU
        for t in active:
            if tracks[t].frames[-1] == f:
                continue  # one detection per track per frame
            iou = _iou(det_bbox[tracks[t].dets[-1]], det_bbox[d])
            if iou > best_iou:
                best, best_iou = t, iou
        if best < 0:
            tracks.append(Track(track_id=len(tracks), shot_id=shot))
            best = len(tracks) - 1
            active.append(best)
        tracks[best].frames.append(f)
        tracks[best].dets.append(int(d))
    kept = [t for t in tracks if len(t.frames) >= TRACK_MIN_LEN]
    track_of_det = np.full(len(det_frame), -1, np.int32)
    for new_id, t in enumerate(kept):
        t.track_id = new_id
        track_of_det[t.dets] = new_id
    return kept, track_of_det


def lip_activity(tracks: list[Track], det_mouth: np.ndarray) -> np.ndarray:
    """Rolling std of mouth openness along each track (talking = oscillation)."""
    out = np.zeros(len(det_mouth), np.float32)
    for t in tracks:
        m = det_mouth[t.dets].astype(np.float64)
        for k in range(len(m)):
            lo, hi = max(0, k - LIP_WINDOW), min(len(m), k + LIP_WINDOW + 1)
            out[t.dets[k]] = float(np.std(m[lo:hi]))
    return out


def _new_person(persons: list[dict[str, object]], t: Track) -> None:
    persons.append({"centroid": t.embedding, "_sum": t.embedding * len(t.frames),
                    "tracks": [t.track_id], "frames": len(t.frames)})
    t.person_id = len(persons) - 1


def _join(persons: list[dict[str, object]], p: int, t: Track) -> None:
    person = persons[p]
    person["_sum"] = person["_sum"] + t.embedding * len(t.frames)  # type: ignore[operator]
    c = person["_sum"]
    person["centroid"] = c / max(np.linalg.norm(c), 1e-9)  # type: ignore[arg-type]
    person["tracks"].append(t.track_id)  # type: ignore[union-attr]
    person["frames"] = int(person["frames"]) + len(t.frames)  # type: ignore[arg-type]
    t.person_id = p


def assign_persons(tracks: list[Track], det_bbox: np.ndarray, det_emb: np.ndarray,
                   det_has_emb: np.ndarray) -> dict[int, dict[str, object]]:
    """Cluster tracks into people by identity embedding.

    Large-face tracks are clustered first (their embeddings are reliable);
    small-face tracks then join the nearest person above a lower threshold,
    or become their own person.
    """
    for t in tracks:
        h = det_bbox[t.dets, 3] - det_bbox[t.dets, 1]
        t.median_height = float(np.median(h))
        idx = [d for d in t.dets if det_has_emb[d]]
        if idx:
            w = (det_bbox[idx, 3] - det_bbox[idx, 1]).astype(np.float64)
            e = (det_emb[idx].astype(np.float64) * w[:, None]).sum(axis=0)
            t.embedding = e / max(np.linalg.norm(e), 1e-9)

    persons: list[dict[str, object]] = []

    def _nearest(e: np.ndarray) -> tuple[int, float]:
        best, sim = -1, -1.0
        for p, info in enumerate(persons):
            s = float(np.dot(info["centroid"], e))  # type: ignore[arg-type]
            if s > sim:
                best, sim = p, s
        return best, sim

    reliable = sorted((t for t in tracks if t.embedding is not None
                       and t.median_height >= RELIABLE_FACE_PX),
                      key=lambda t: -len(t.frames))
    for t in reliable:
        p, s = _nearest(t.embedding)  # type: ignore[arg-type]
        if p >= 0 and s >= PERSON_SIM:
            _join(persons, p, t)
        else:
            _new_person(persons, t)
    for t in tracks:
        if t.person_id >= 0 or t.embedding is None:
            continue
        p, s = _nearest(t.embedding)
        if p >= 0 and s >= PERSON_ASSIGN_SIM:
            _join(persons, p, t)
        else:
            _new_person(persons, t)
    return {i: {"tracks": p["tracks"], "frames": p["frames"]} for i, p in enumerate(persons)}


def analyze(npz: dict[str, np.ndarray]) -> FaceAnalysis:
    """Full analysis of one face_worker output."""
    shot_of_frame, shots = detect_shots(npz["frame_hist"])
    tracks, track_of_det = build_tracks(npz["det_frame"], npz["det_bbox"], shot_of_frame)
    lip = lip_activity(tracks, npz["det_mouth"])
    persons = assign_persons(tracks, npz["det_bbox"], npz["det_emb"], npz["det_has_emb"])
    w, h = (int(v) for v in npz["source_size"])
    return FaceAnalysis(
        frame_t_ms=npz["frame_t_ms"], shot_of_frame=shot_of_frame, shots=shots,
        tracks=tracks, track_of_det=track_of_det, lip_activity=lip,
        persons=persons, source_size=(w, h),
    )
