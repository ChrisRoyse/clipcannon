"""GPU worker: active-speaker scores for every face track (Light-ASD).

    python -m clipcannon.pipeline.asd_worker SOURCE.mp4 FACES.npz OUT.npz

Follows the upstream Light-ASD inference recipe (Columbia_test.py): 25 fps face
crops (median-smoothed box, crop scale 0.40, 224 -> centre 112 grayscale),
16 kHz MFCC (13 coeffs, 25 ms window, 10 ms hop), and an ensemble over
1-6 s windows. Tracks come from face_tracking.analyze() on the face_worker
output (10 fps) and are interpolated to 25 fps.

Output (.npz):
    det_asd[D]   speaking logit per face_worker detection (NaN if the
                 detection belongs to no track); > 0 means speaking
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ASD_FPS = 25
CROP_SCALE = 0.40
DURATIONS = (1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 6)   # upstream "more reliable" set
WEIGHTS = Path.home() / ".clipcannon" / "models" / "light-asd" / "pretrain_AVA_CVPR.model"


def _audio_16k(src: str) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"], capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, np.int16)


def _track_boxes_25(track_frames: np.ndarray, boxes: np.ndarray, fps_in: float,
                    medfilt: object) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate a 10 fps track to 25 fps; return (frame25 idx, [n, 3] x,y,s)."""
    t_in = track_frames / fps_in
    f0 = int(math.ceil(t_in[0] * ASD_FPS))
    f1 = int(math.floor(t_in[-1] * ASD_FPS))
    frames25 = np.arange(f0, max(f0, f1) + 1)
    t25 = frames25 / ASD_FPS
    cx = (boxes[:, 0] + boxes[:, 2]) / 2
    cy = (boxes[:, 1] + boxes[:, 3]) / 2
    s = np.maximum(boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]) / 2
    out = np.stack([np.interp(t25, t_in, v) for v in (cx, cy, s)], axis=1)
    if len(out) >= 13:
        for c in range(3):
            out[:, c] = medfilt(out[:, c], kernel_size=13)
    return frames25, out


def _crop(frame: np.ndarray, x: float, y: float, s: float, cv2: object) -> np.ndarray:
    """Upstream crop: pad by bsi with value 110, cut, resize 224, gray, centre 112."""
    bs = s
    bsi = int(bs * (1 + 2 * CROP_SCALE))
    h, w = frame.shape[:2]
    my, mx = y + bsi, x + bsi
    y0, y1 = int(my - bs), int(my + bs * (1 + 2 * CROP_SCALE))
    x0, x1 = int(mx - bs * (1 + CROP_SCALE)), int(mx + bs * (1 + CROP_SCALE))
    canvas = np.full((max(1, y1 - y0), max(1, x1 - x0), 3), 110, np.uint8)
    sy0, sy1 = max(y0 - bsi, 0), min(y1 - bsi, h)
    sx0, sx1 = max(x0 - bsi, 0), min(x1 - bsi, w)
    if sy1 > sy0 and sx1 > sx0:
        canvas[sy0 - (y0 - bsi):sy1 - (y0 - bsi), sx0 - (x0 - bsi):sx1 - (x0 - bsi)] = \
            frame[sy0:sy1, sx0:sx1]
    face = cv2.cvtColor(cv2.resize(canvas, (224, 224)), cv2.COLOR_BGR2GRAY)
    return face[56:168, 56:168]


def _score_track(net: object, mfcc: np.ndarray, faces: np.ndarray, torch: object) -> np.ndarray:
    length = min((mfcc.shape[0] - mfcc.shape[0] % 4) / 100, faces.shape[0] / ASD_FPS)
    if length <= 0:
        return np.zeros(len(faces), np.float32)
    mfcc = mfcc[:int(round(length * 100))]
    faces = faces[:int(round(length * ASD_FPS))]
    runs = []
    for dur in DURATIONS:
        scores: list[float] = []
        for i in range(int(math.ceil(length / dur))):
            a = torch.from_numpy(mfcc[i * dur * 100:(i + 1) * dur * 100]).float()
            v = torch.from_numpy(faces[i * dur * ASD_FPS:(i + 1) * dur * ASD_FPS]).float()
            if len(v) == 0 or len(a) < 4:
                continue
            scores.extend(net.score(a.unsqueeze(0).cuda(), v.unsqueeze(0).cuda()).tolist())
        runs.append(scores[:len(faces)])
    n = min(len(r) for r in runs)
    out = np.mean([r[:n] for r in runs], axis=0).astype(np.float32)
    full = np.zeros(len(faces), np.float32)
    full[:n] = out
    if n < len(faces) and n:
        full[n:] = out[-1]
    return full


def run(src: str, faces_npz: str, out: str) -> dict[str, object]:
    import cv2
    import python_speech_features
    import torch
    from scipy.signal import medfilt

    from clipcannon.pipeline.face_tracking import analyze
    from clipcannon.pipeline.light_asd import load_light_asd

    t0 = time.time()
    z = dict(np.load(faces_npz))
    fps_in = float(z["fps"][0])
    fa = analyze(z)
    w, h = fa.source_size

    plans = []   # per track: (frames25, boxes25)
    by_frame: dict[int, list[tuple[int, int]]] = {}
    for ti, tr in enumerate(fa.tracks):
        frames = np.array(tr.frames, np.float64)
        f25, b25 = _track_boxes_25(frames, z["det_bbox"][tr.dets], fps_in, medfilt)
        plans.append((f25, b25))
        for k, f in enumerate(f25):
            by_frame.setdefault(int(f), []).append((ti, k))
    crops = [np.zeros((len(p[0]), 112, 112), np.uint8) for p in plans]

    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={ASD_FPS}", "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, bufsize=w * h * 3 * 4,
        stderr=subprocess.DEVNULL)  # we stop reading early on purpose (broken pipe is expected)
    assert proc.stdout is not None
    nbytes, fi = w * h * 3, 0
    last = max(by_frame) if by_frame else -1
    while fi <= last:
        buf = proc.stdout.read(nbytes)
        if len(buf) < nbytes:
            break
        if fi in by_frame:
            frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            for ti, k in by_frame[fi]:
                x, y, s = plans[ti][1][k]
                crops[ti][k] = _crop(frame, x, y, s, cv2)
        fi += 1
        if fi % 5000 == 0:
            print(f"[asd-worker] decoded {fi} frames", file=sys.stderr, flush=True)
    proc.stdout.close()
    proc.kill()
    t_dec = time.time() - t0

    audio = _audio_16k(src)
    net = load_light_asd(WEIGHTS)
    det_asd = np.full(len(z["det_frame"]), np.nan, np.float32)
    for ti, tr in enumerate(fa.tracks):
        f25 = plans[ti][0]
        a0, a1 = int(f25[0] / ASD_FPS * 16000), int((f25[-1] + 1) / ASD_FPS * 16000)
        mfcc = python_speech_features.mfcc(audio[a0:a1], 16000, numcep=13,
                                           winlen=0.025, winstep=0.010)
        sc = _score_track(net, mfcc, crops[ti], torch)
        # Map 25 fps scores onto this track's 10 fps detections (+-2 frame mean).
        for f10, d in zip(tr.frames, tr.dets, strict=True):
            k = int(round(f10 / fps_in * ASD_FPS)) - int(f25[0])
            lo, hi = max(0, k - 2), min(len(sc), k + 3)
            if hi > lo:
                det_asd[d] = float(np.mean(sc[lo:hi]))
    np.savez_compressed(out, det_asd=det_asd)
    return {"tracks": len(fa.tracks), "decode_s": round(t_dec, 1),
            "total_s": round(time.time() - t0, 1),
            "scored": int(np.isfinite(det_asd).sum())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("faces")
    ap.add_argument("out")
    a = ap.parse_args()
    print(json.dumps(run(a.source, a.faces, a.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
