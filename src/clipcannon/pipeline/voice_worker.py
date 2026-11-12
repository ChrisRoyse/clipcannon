"""GPU worker: one speaker-verification embedding per transcript segment.

    python -m clipcannon.pipeline.voice_worker AUDIO_OR_VIDEO SEGMENTS.json OUT.npz

SEGMENTS.json is [[start_ms, end_ms], ...]. Uses the frozen ECAPA-TDNN
speaker model (speechbrain/spkrec-ecapa-voxceleb). Measured on this project's
press-conference audio it separates speakers far better than the
wavlm-base-plus-sv x-vector head (pairwise same/different-speaker accuracy
99.5% vs 79.5%; mean cosine 0.63 vs 0.04 same/different).

Output (.npz): voice_emb[N, 192] (L2-normalised), voice_valid[N]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

import numpy as np

MODEL_ID = "speechbrain/spkrec-ecapa-voxceleb"
SR = 16000
MIN_MS = 500
MAX_S = 20.0   # long segments: embed the first 20 s (plenty for identity)


def _audio(src: str) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", str(SR),
         "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def run(src: str, segs_path: str, out: str) -> dict[str, object]:
    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    from clipcannon.paths import hf_snapshot_dir

    t0 = time.time()
    with open(segs_path) as f:
        segs = json.load(f)
    audio = _audio(src)
    snap = str(hf_snapshot_dir(MODEL_ID))
    enc = EncoderClassifier.from_hparams(source=snap, savedir=snap, run_opts={"device": "cuda"})
    emb = np.zeros((len(segs), 192), np.float32)
    valid = np.zeros(len(segs), bool)
    for i, (s, e) in enumerate(segs):
        if e - s < MIN_MS:
            continue
        a = audio[int(s / 1000 * SR): int(min(e / 1000, s / 1000 + MAX_S) * SR)]
        if len(a) < MIN_MS / 1000 * SR:
            continue
        with torch.no_grad():
            v = enc.encode_batch(torch.from_numpy(a.copy()).unsqueeze(0).cuda())
        v = v.squeeze().float().cpu().numpy()
        emb[i] = v / max(float(np.linalg.norm(v)), 1e-9)
        valid[i] = True
    np.savez_compressed(out, voice_emb=emb, voice_valid=valid)
    return {"segments": len(segs), "embedded": int(valid.sum()),
            "seconds": round(time.time() - t0, 1)}


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    print(json.dumps(run(*sys.argv[1:4])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
