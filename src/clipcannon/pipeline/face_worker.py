"""GPU worker: per-frame face detection, 106-point landmarks, mouth openness,
identity embeddings and shot-change features for a whole video.

Run as a subprocess (keeps CUDA/ONNX memory out of the server process):

    python -m clipcannon.pipeline.face_worker SOURCE.mp4 OUT.npz [--fps 10]

Output (.npz):
    frame_t_ms[F]            timestamp of each sampled frame
    frame_hist[F, 48]        HSV histogram per frame (shot-change detection)
    det_frame[D]             frame index of each detection
    det_bbox[D, 4]           x1, y1, x2, y2 in source pixels
    det_score[D]             detector confidence
    det_mouth[D]             inner-lip gap / mouth width (scale-free openness)
    det_lmk[D, 106, 2]       landmarks (source pixels, float16)
    det_emb[D, 512]          ArcFace embedding (float16), zeros where skipped
    det_has_emb[D]           whether det_emb was computed for that detection
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import numpy as np

# insightface 2d106 lip points (verified visually on a close-up):
#   corners 52 / 61; inner upper lip 66, 62, 70 over inner lower lip 54, 60, 57.
_LIP_PAIRS = ((66, 54), (62, 60), (70, 57))
_LIP_CORNERS = (52, 61)

MIN_FACE_PX = 14          # ignore detections smaller than this (source pixels)
DET_THRESHOLD = 0.5
EMB_EVERY_N_FRAMES = 5    # identity embedding cadence (2/s at 10 fps)


def _probe(src: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "json", src],
        capture_output=True, text=True, check=True,
    ).stdout
    s = json.loads(out)["streams"][0]
    return int(s["width"]), int(s["height"])


def _mouth_open(lmk: np.ndarray) -> float:
    width = float(np.linalg.norm(lmk[_LIP_CORNERS[0]] - lmk[_LIP_CORNERS[1]]))
    if width < 1e-3:
        return 0.0
    gap = np.mean([np.linalg.norm(lmk[a] - lmk[b]) for a, b in _LIP_PAIRS])
    return float(gap / width)


def _hist(frame: np.ndarray, cv2: object) -> np.ndarray:
    small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    feats = [cv2.calcHist([hsv], [c], None, [16], [0, 256 if c else 180]).ravel()
             for c in range(3)]
    h = np.concatenate(feats).astype(np.float32)
    return h / max(h.sum(), 1.0)


def run(src: str, out: str, fps: float) -> dict[str, object]:
    import cv2
    from insightface.app import FaceAnalysis
    from insightface.utils import face_align

    width, height = _probe(src)
    providers = [("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"}),
                 "CPUExecutionProvider"]
    app = FaceAnalysis(name="buffalo_l", providers=providers,
                       allowed_modules=["detection", "landmark_2d_106", "recognition"])
    app.prepare(ctx_id=0, det_size=(640, 640), det_thresh=DET_THRESHOLD)
    det, lmk_model, rec = app.det_model, app.models["landmark_2d_106"], app.models["recognition"]
    if "CUDAExecutionProvider" not in det.session.get_providers():
        raise RuntimeError("face detector is not running on CUDA")
    lsz = lmk_model.input_size[0]

    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={fps}", "-f", "rawvideo",
         "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, bufsize=width * height * 3 * 4,
    )
    frame_bytes = width * height * 3
    frame_t, hists = [], []
    d_frame, d_bbox, d_score, d_mouth, d_lmk, d_emb, d_has = [], [], [], [], [], [], []
    t0 = time.time()
    fi = 0
    assert proc.stdout is not None
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(height, width, 3)
        frame_t.append(int(round(fi * 1000.0 / fps)))
        hists.append(_hist(frame, cv2))

        bboxes, kpss = det.detect(frame, max_num=0, metric="default")
        keep = [i for i, b in enumerate(bboxes)
                if min(b[2] - b[0], b[3] - b[1]) >= MIN_FACE_PX]
        if keep:
            # Batched 106-point landmarks (mirrors insightface Landmark.get).
            blobs, inv = [], []
            for i in keep:
                x1, y1, x2, y2 = bboxes[i][:4]
                w, h = x2 - x1, y2 - y1
                center = ((x1 + x2) / 2, (y1 + y2) / 2)
                aimg, m = face_align.transform(frame, center, lsz, lsz / (max(w, h) * 1.5), 0)
                blobs.append(aimg)
                inv.append(cv2.invertAffineTransform(m))
            blob = cv2.dnn.blobFromImages(
                blobs, 1.0 / lmk_model.input_std, (lsz, lsz),
                (lmk_model.input_mean,) * 3, swapRB=True)
            preds = lmk_model.session.run(lmk_model.output_names,
                                          {lmk_model.input_name: blob})[0]
            do_emb = fi % EMB_EVERY_N_FRAMES == 0
            crops = []
            for j, i in enumerate(keep):
                p = preds[j].reshape(-1, 2)[-106:].copy()
                p += 1
                p *= lsz // 2
                lm = face_align.trans_points(p, inv[j])
                d_frame.append(fi)
                d_bbox.append(bboxes[i][:4])
                d_score.append(float(bboxes[i][4]))
                d_mouth.append(_mouth_open(lm))
                d_lmk.append(lm.astype(np.float16))
                d_has.append(do_emb)
                if do_emb:
                    crops.append(face_align.norm_crop(frame, landmark=kpss[i]))
            embs = rec.get_feat(crops) if crops else np.zeros((0, 512), np.float32)
            k = 0
            for j in range(len(keep)):
                if d_has[len(d_has) - len(keep) + j]:
                    e = embs[k] / max(np.linalg.norm(embs[k]), 1e-6)
                    d_emb.append(e.astype(np.float16))
                    k += 1
                else:
                    d_emb.append(np.zeros(512, np.float16))
        fi += 1
        if fi % 1000 == 0:
            el = time.time() - t0
            print(f"[face-worker] {fi} frames, {len(d_frame)} faces, "
                  f"{fi / el:.1f} fps", file=sys.stderr, flush=True)
    proc.wait()
    if proc.returncode not in (0, None):
        raise RuntimeError(f"ffmpeg decode failed (rc={proc.returncode})")

    np.savez_compressed(
        out,
        frame_t_ms=np.array(frame_t, np.int64),
        frame_hist=np.array(hists, np.float32).reshape(-1, 48),
        det_frame=np.array(d_frame, np.int32),
        det_bbox=np.array(d_bbox, np.float32).reshape(-1, 4),
        det_score=np.array(d_score, np.float32),
        det_mouth=np.array(d_mouth, np.float32),
        det_lmk=np.array(d_lmk, np.float16).reshape(-1, 106, 2),
        det_emb=np.array(d_emb, np.float16).reshape(-1, 512),
        det_has_emb=np.array(d_has, bool),
        source_size=np.array([width, height], np.int32),
        fps=np.array([fps], np.float32),
    )
    return {"frames": fi, "detections": len(d_frame), "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=10.0)
    a = ap.parse_args()
    stats = run(a.source, a.out, a.fps)
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
