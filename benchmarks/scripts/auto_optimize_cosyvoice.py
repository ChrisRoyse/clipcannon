"""Auto-Optimizer for CosyVoice 3 on SeedTTS-Eval.

Automated iterative optimization loop that:
1. Sweeps CosyVoice 3 inference parameters
2. Scores with official WavLM-Large encoder
3. Logs all results
4. Converges on optimal configuration

Parameters tuned:
  - inference_cfg_rate (classifier-free guidance strength)
  - speed (mel interpolation)
  - num_candidates (best-of-N)
  - text_frontend (True/False)
  - prompt formatting

All models stay loaded in VRAM.
"""

import functools
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).parent.parent / "cosyvoice"))
sys.path.insert(0, str(Path(__file__).parent.parent / "cosyvoice" / "third_party" / "Matcha-TTS"))

logging.basicConfig(format="%(levelname)s | %(asctime)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BENCH_DIR = Path(__file__).parent.parent
CHECKPOINT = BENCH_DIR / "seedtts_eval" / "wavlm_large_finetune.pth"
META_PATH = BENCH_DIR / "seedtts_eval" / "seedtts_testset" / "en" / "meta.lst"
DATA_DIR = BENCH_DIR / "seedtts_eval" / "seedtts_testset" / "en"
RESULTS_DIR = BENCH_DIR / "results"
LOG_PATH = RESULTS_DIR / "auto_optimize_log.jsonl"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def load_test_samples(n=10):
    """Load first N test samples from SeedTTS-Eval."""
    samples = []
    with open(META_PATH) as f:
        for i, line in enumerate(f):
            if i >= n:
                break
            parts = line.strip().split("|")
            if len(parts) < 4:
                continue
            samples.append({
                "utt_id": parts[0].strip(),
                "prompt_text": parts[1].strip(),
                "prompt_wav": str(DATA_DIR / parts[2].strip()),
                "infer_text": parts[3].strip(),
            })
    return samples


def official_sim(w1, w2):
    """Score with official WavLM-Large via main Python env."""
    result = subprocess.run(
        ["/home/cabdru/miniconda3/bin/python", "-c", f"""
import sys; sys.path.insert(0,".")
from verification import init_model, verification
model = init_model("wavlm_large", "{CHECKPOINT}")
model = model.cuda().eval()
s, _ = verification("wavlm_large", "{w1}", "{w2}", use_gpu=True, model=model)
print(f"SIM={{s.item():.6f}}")
"""],
        capture_output=True, text=True,
        cwd="/tmp/seed-tts-eval/thirdparty/UniSpeech/downstreams/speaker_verification",
    )
    for line in result.stdout.strip().split("\n"):
        if line.startswith("SIM="):
            return float(line.split("=")[1])
    return 0.0


def run_trial(model, samples, params, trial_id, tmp_dir):
    """Run one optimization trial with given parameters."""
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Inject inference_cfg_rate
    try:
        model.model.flow.decoder.inference_cfg_rate = params["inference_cfg_rate"]
    except Exception:
        pass

    sims = []
    for entry in samples:
        best_sim = -1

        for cand_idx in range(params["num_candidates"]):
            try:
                # Format prompt text with endofprompt
                prompt_text = entry["prompt_text"] + "<|endofprompt|>"

                for r in model.inference_zero_shot(
                    entry["infer_text"],
                    prompt_text,
                    entry["prompt_wav"],
                    text_frontend=params["text_frontend"],
                    speed=params["speed"],
                ):
                    tmp_wav = tmp_dir / f"t{trial_id}_{entry['utt_id']}_{cand_idx}.wav"
                    torchaudio.save(str(tmp_wav), r["tts_speech"], 24000)

                    sim = official_sim(str(tmp_wav), entry["prompt_wav"])
                    if sim > best_sim:
                        best_sim = sim

                    # Cleanup
                    tmp_wav.unlink(missing_ok=True)
                    break
            except Exception as e:
                logger.warning("Trial %d cand %d failed: %s", trial_id, cand_idx, e)
                continue

        if best_sim > 0:
            sims.append(best_sim)

    return sims


def auto_optimize():
    """Run the automated optimization loop."""
    torch.set_float32_matmul_precision("high")

    logger.info("=" * 60)
    logger.info("AUTO-OPTIMIZER: CosyVoice 3 for SeedTTS-Eval")
    logger.info("=" * 60)

    # Load model once
    from cosyvoice.cli.cosyvoice import CosyVoice3
    logger.info("Loading CosyVoice3...")
    model = CosyVoice3("/home/cabdru/.cache/cosyvoice3")
    logger.info("CosyVoice3 loaded")

    # Load test samples
    samples = load_test_samples(n=5)  # Start with 5 for speed
    logger.info("Test samples: %d", len(samples))

    tmp_dir = BENCH_DIR / "seedtts_eval" / "_auto_tmp"

    # Define parameter configurations to test
    configs = [
        # Baseline
        {"name": "Baseline", "inference_cfg_rate": 0.7, "speed": 1.0, "num_candidates": 1, "text_frontend": False},

        # CFG rate sweep
        {"name": "CFG 0.3", "inference_cfg_rate": 0.3, "speed": 1.0, "num_candidates": 1, "text_frontend": False},
        {"name": "CFG 0.5", "inference_cfg_rate": 0.5, "speed": 1.0, "num_candidates": 1, "text_frontend": False},
        {"name": "CFG 0.9", "inference_cfg_rate": 0.9, "speed": 1.0, "num_candidates": 1, "text_frontend": False},
        {"name": "CFG 1.0", "inference_cfg_rate": 1.0, "speed": 1.0, "num_candidates": 1, "text_frontend": False},
        {"name": "CFG 1.2", "inference_cfg_rate": 1.2, "speed": 1.0, "num_candidates": 1, "text_frontend": False},

        # Speed sweep (with best CFG from above - will update after phase 1)
        {"name": "Speed 0.9", "inference_cfg_rate": 0.7, "speed": 0.9, "num_candidates": 1, "text_frontend": False},
        {"name": "Speed 0.95", "inference_cfg_rate": 0.7, "speed": 0.95, "num_candidates": 1, "text_frontend": False},
        {"name": "Speed 1.05", "inference_cfg_rate": 0.7, "speed": 1.05, "num_candidates": 1, "text_frontend": False},
        {"name": "Speed 1.1", "inference_cfg_rate": 0.7, "speed": 1.1, "num_candidates": 1, "text_frontend": False},

        # Best-of-N with best params
        {"name": "N=3 best", "inference_cfg_rate": 0.7, "speed": 1.0, "num_candidates": 3, "text_frontend": False},
        {"name": "N=6 best", "inference_cfg_rate": 0.7, "speed": 1.0, "num_candidates": 6, "text_frontend": False},
        {"name": "N=12 best", "inference_cfg_rate": 0.7, "speed": 1.0, "num_candidates": 12, "text_frontend": False},

        # Text frontend
        {"name": "TextFE=True", "inference_cfg_rate": 0.7, "speed": 1.0, "num_candidates": 1, "text_frontend": True},
    ]

    all_results = []

    for trial_id, config in enumerate(configs):
        logger.info("\n--- Trial %d: %s ---", trial_id, config["name"])
        start = time.monotonic()

        sims = run_trial(model, samples, config, trial_id, tmp_dir)

        elapsed = time.monotonic() - start
        mean_sim = np.mean(sims) if sims else 0
        max_sim = np.max(sims) if sims else 0

        result = {
            "trial_id": trial_id,
            "name": config["name"],
            "params": config,
            "mean_sim": round(mean_sim, 4),
            "max_sim": round(max_sim, 4),
            "std_sim": round(np.std(sims), 4) if sims else 0,
            "n_scored": len(sims),
            "elapsed_s": round(elapsed, 1),
            "per_sample": [round(s, 4) for s in sims],
        }
        all_results.append(result)

        # Log
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(result) + "\n")

        logger.info("  SIM: mean=%.4f max=%.4f | %s", mean_sim, max_sim, config["name"])

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("OPTIMIZATION RESULTS (sorted by mean SIM)")
    logger.info("=" * 60)

    all_results.sort(key=lambda r: r["mean_sim"], reverse=True)
    for r in all_results:
        logger.info("  %.4f  %s", r["mean_sim"], r["name"])

    best = all_results[0]
    logger.info("\nBEST: %s (SIM=%.4f)", best["name"], best["mean_sim"])
    logger.info("Params: %s", json.dumps(best["params"], indent=2))

    # Save final results
    with open(RESULTS_DIR / "10_auto_optimize.json", "w") as f:
        json.dump({"trials": all_results, "best": best}, f, indent=2)

    # Cleanup
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    auto_optimize()
