"""FSV (#68 follow-up): the reaction instrument used without FunASR detects real,
human-labelled laughter and applause, and stays silent on other sounds.

Source of truth: ESC-50 human labels (meta/esc50.csv) for a pinned 560-clip
subset: all 40 `laughing` + all 40 `clapping` clips, plus 2 clips per fold of
each of the other 48 classes (480 negatives). The subset and its sha256 sums
live in ~/.clipcannon/bench/esc50 (CC BY-NC 3.0, not redistributed here).
Thresholds were chosen on folds 1-3; folds 4-5 are the held-out claim.

The real detector (reactions_ast.detect_reactions_ast) runs once over all clips
laid end to end on its 5 s window grid, so window k covers exactly clip k.

    python scripts/fsv/fsv_reactions_bench.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from kit import Run, sha256_file

from clipcannon.pipeline.reactions_ast import IDENTITY, detect_reactions_ast
from clipcannon.pipeline.reactions_detect import _load_audio

BENCH = Path.home() / ".clipcannon" / "bench" / "esc50"
POS = {"laughing": "laughter", "clapping": "applause"}
CLIP = 80_000  # 5 s at 16 kHz
# Removed energy/spectral heuristic on the same 560 clips (measured at d1dd3dd,
# bench/esc50/baseline.json): laughter 1/40, applause 6/40, 82/480 negatives flagged.
BEFORE = {"laughing": "1/40", "clapping": "6/40", "negatives_flagged": "82/480",
          "sensevoice_reference": {"laughing": "32/40", "clapping": "17/40",
                                   "negatives_flagged": "2/480"}}


def corpus() -> tuple[list[dict], dict]:
    sums = dict(reversed(line.split()) for line in (BENCH / "SHA256SUMS").read_text().splitlines())
    meta = {r["filename"]: r for r in csv.DictReader((BENCH / "esc50.csv").open())}
    files = (BENCH / "subset.txt").read_text().split()
    bad = [f for f in files if sha256_file(BENCH / "audio" / f) != sums.get(f)]
    rows = [{"f": f, "cat": meta[f]["category"], "fold": int(meta[f]["fold"])} for f in files]
    return rows, {"files": len(files), "hash_mismatch": bad,
                  "manifest_sha256": hashlib.sha256((BENCH / "SHA256SUMS").read_bytes()).hexdigest()}


def tally(rows: list[dict]) -> dict:
    out: dict = {}
    for cat, kind in POS.items():
        p = [r for r in rows if r["cat"] == cat]
        out[cat] = [sum(kind in r["hit"] for r in p), len(p)]
    n = [r for r in rows if r["cat"] not in POS]
    out["negatives_flagged"] = [sum(bool(r["hit"]) for r in n), len(n)]
    out["wrong_type_on_positives"] = sum(
        bool(r["hit"] - {POS[r["cat"]]}) for r in rows if r["cat"] in POS)
    out["false_positive_classes"] = sorted({r["cat"] for r in n if r["hit"]})
    return out


def main() -> int:
    run = Run("reactions-bench", issue=68, source_of_truth="ESC-50 human labels",
              claim="the AST reaction instrument finds labelled laughter/applause on held-out "
                    "folds and flags no other sound class; it refuses when not cached",
              corpus="560 pinned ESC-50 clips (80 positive, 480 negative over 48 classes)",
              why_minimal="all labelled positives, and every other class in every fold, so "
                          "a false positive in any sound family is visible")
    rows, man = corpus()
    run.check("corpus_pinned", man["files"] == 560 and not man["hash_mismatch"], after=man)

    audio = np.zeros(CLIP * len(rows), dtype=np.float32)
    for i, r in enumerate(rows):
        a, sr = _load_audio(BENCH / "audio" / r["f"])
        a = a[:CLIP]
        audio[i * CLIP : i * CLIP + len(a)] = a
    found = detect_reactions_ast(audio, 16000)
    by_start: dict[int, set] = {}
    conf: dict[tuple[int, str], float] = {}
    for x in found:
        by_start.setdefault(int(x["start_ms"]), set()).add(x["type"])
        conf[(int(x["start_ms"]), x["type"])] = x["confidence"]
    for i, r in enumerate(rows):
        r["hit"] = by_start.get(i * 5000, set())
    dev = tally([r for r in rows if r["fold"] <= 3])
    test = tally([r for r in rows if r["fold"] >= 4])
    (run.path("per_clip.json")).write_text(json.dumps(
        [{**r, "hit": sorted(r["hit"]),
          "conf": {k: conf.get((i * 5000, k)) for k in ("laughter", "applause")}}
         for i, r in enumerate(rows)], indent=0))
    run.check("heldout_recall_and_no_false_positives",
              test["laughing"][0] / test["laughing"][1] >= 0.5
              and test["clapping"][0] / test["clapping"][1] >= 0.8
              and test["negatives_flagged"][0] == 0 and test["wrong_type_on_positives"] == 0,
              before=BEFORE, after={"heldout_folds_4_5": test, "tuning_folds_1_3": dev,
                                    "thresholds": IDENTITY.as_params()})

    silent = detect_reactions_ast(np.zeros(16000 * 30, dtype=np.float32), 16000)
    run.check("silence_yields_nothing", silent == [], after={"rows": silent})

    with tempfile.TemporaryDirectory() as empty:
        env = {**os.environ, "HF_HUB_CACHE": empty, "HF_HOME": empty, "HF_HUB_OFFLINE": "1"}
        code = ("import numpy as np\nfrom clipcannon.pipeline.reactions_ast import "
                "detect_reactions_ast as d\ntry:\n d(np.zeros(80000, dtype=np.float32), 16000)\n"
                "except Exception as e:\n print(getattr(e, 'code', type(e).__name__))\n"
                " print(getattr(e, 'remediation', ''))\n")
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                             text=True, check=False).stdout.strip().splitlines()
    run.check("uncached_model_refused", out[:1] == ["REACTION_INSTRUMENT_UNAVAILABLE"]
              and "huggingface-cli download" in " ".join(out), after={"stdout": out})
    return run.finish(limitations=[
        "ESC-50 clips are isolated 5 s sound events; reactions under speech in a real "
        "recording are harder, and no labelled long-form corpus was measured",
        "laughter recall on held-out folds is the weak side (misses scored 0.015-0.031)",
        "GPU (RTX 5090) fp32 only"])


if __name__ == "__main__":
    sys.exit(main())
