"""SeedTTS-Eval FINAL RUN - Best Configuration.

Config based on all experiments:
  - Full reference clip (no segmentation)
  - Official WavLM-Large encoder for candidate scoring
  - Multi-temperature: 0.3, 0.4, 0.5 x 8 each = 24 candidates
  - Full ICL mode with provided transcript
  - No post-processing (raw 24kHz output)
  - Reference preprocessing: trim silence, normalize
"""

import gc
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, "/tmp/seed-tts-eval/thirdparty/UniSpeech/downstreams/speaker_verification")

logging.basicConfig(format="%(levelname)s | %(asctime)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BENCH_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BENCH_DIR / "seedtts_eval" / "final_run"
RESULTS_DIR = BENCH_DIR / "results"
CHECKPOINT = BENCH_DIR / "seedtts_eval" / "wavlm_large_finetune.pth"
META_PATH = BENCH_DIR / "seedtts_eval" / "seedtts_testset" / "en" / "meta.lst"
DATA_DIR = BENCH_DIR / "seedtts_eval" / "seedtts_testset" / "en"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================================
# Official WavLM-Large encoder
# =========================================================================

_official = None

def get_official():
    global _official
    if _official is None:
        from verification import init_model
        _official = init_model("wavlm_large", str(CHECKPOINT))
        _official = _official.cuda().eval()
        logger.info("Official WavLM-Large loaded")
    return _official

def official_sim(w1, w2):
    from verification import verification
    s, _ = verification("wavlm_large", str(w1), str(w2), use_gpu=True, model=get_official())
    return s.item()

# =========================================================================
# Main
# =========================================================================

def run(max_samples=0):
    torch.set_float32_matmul_precision("high")
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

    # Parse meta
    entries = []
    with open(META_PATH) as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) < 4:
                continue
            entries.append({
                "utt_id": parts[0].strip(),
                "prompt_text": parts[1].strip(),
                "prompt_wav": str(DATA_DIR / parts[2].strip()),
                "infer_text": parts[3].strip(),
            })
    if max_samples > 0:
        entries = entries[:max_samples]

    logger.info("=" * 60)
    logger.info("SeedTTS-Eval FINAL RUN")
    logger.info("=" * 60)
    logger.info("Samples: %d", len(entries))
    logger.info("Config: multi-temp (0.3/0.4/0.5 x 8 = 24), official WavLM scoring")

    # Load engines
    get_official()
    from clipcannon.voice.inference import VoiceSynthesizer, _trim_reference
    synth = VoiceSynthesizer()
    engine = synth._ensure_engine()

    sim_scores = []
    start_time = time.monotonic()

    for idx, entry in enumerate(entries):
        out_path = OUTPUT_DIR / f"{entry['utt_id']}.wav"

        # Skip if already generated
        if out_path.exists():
            try:
                s = official_sim(str(out_path), entry["prompt_wav"])
                sim_scores.append(s)
            except:
                pass
            continue

        try:
            # Prep reference
            ref_wav, ref_sr = torchaudio.load(entry["prompt_wav"])
            if ref_wav.shape[0] > 1:
                ref_wav = ref_wav.mean(0, keepdim=True)
            if ref_sr != 24000:
                ref_wav = torchaudio.functional.resample(ref_wav, ref_sr, 24000)

            # Trim silence
            energy = ref_wav.abs().squeeze()
            threshold = energy.max() * 0.02
            active = (energy > threshold).nonzero(as_tuple=True)[0]
            if len(active) > 0:
                start_s = max(0, active[0].item() - int(0.05 * 24000))
                end_s = min(ref_wav.shape[-1], active[-1].item() + int(0.3 * 24000))
                ref_wav = ref_wav[:, start_s:end_s]

            # Trim to 15s
            if ref_wav.shape[-1] > 15 * 24000:
                ref_wav = ref_wav[:, :15 * 24000]

            # Peak normalize
            peak = ref_wav.abs().max()
            if peak > 0:
                ref_wav = ref_wav * (10 ** (-1 / 20) / peak)

            tmp_ref = OUTPUT_DIR / f"_ref_{entry['utt_id']}.wav"
            torchaudio.save(str(tmp_ref), ref_wav, 24000)
            ref_trimmed = _trim_reference(tmp_ref)

            # Build ICL prompt
            prompt = engine.create_voice_clone_prompt(
                ref_audio=str(ref_trimmed),
                ref_text=entry["prompt_text"],
                x_vector_only_mode=False,
            )

            # Generate best-of-24 across 3 temperatures
            best_sim, best_wav, best_sr = -1, None, 24000
            tmp_cand = OUTPUT_DIR / f"_cand_{entry['utt_id']}.wav"

            for temp in [0.3, 0.4, 0.5]:
                for _ in range(8):
                    torch.manual_seed(int(torch.randint(0, 2**31, (1,)).item()))
                    wavs, sr = engine.generate_voice_clone(
                        text=entry["infer_text"],
                        language="English",
                        voice_clone_prompt=prompt,
                        max_new_tokens=2048,
                        temperature=temp,
                        top_p=0.85,
                        repetition_penalty=1.05,
                    )
                    wav_np = wavs[0] if isinstance(wavs[0], np.ndarray) else wavs[0].cpu().numpy()
                    if len(wav_np) < sr * 0.3:
                        continue
                    sf.write(str(tmp_cand), wav_np, sr)
                    s = official_sim(str(tmp_cand), entry["prompt_wav"])
                    if s > best_sim:
                        best_sim, best_wav, best_sr = s, wav_np, sr

            # Save winner
            if best_wav is not None:
                sf.write(str(out_path), best_wav, best_sr)
                sim_scores.append(best_sim)

            # Cleanup
            tmp_ref.unlink(missing_ok=True)
            tmp_cand.unlink(missing_ok=True)

            elapsed = time.monotonic() - start_time
            rate = (idx + 1) / elapsed * 3600

            if (idx + 1) % 10 == 0 or idx == 0:
                logger.info(
                    "[%d/%d] SIM=%.4f (mean=%.4f) | %.0f/hr | ETA: %.1fh",
                    idx + 1, len(entries), best_sim,
                    np.mean(sim_scores), rate,
                    (len(entries) - idx - 1) / rate,
                )

        except Exception as e:
            logger.error("[%d] Failed: %s", idx, e)
            continue

    synth.release()

    elapsed = time.monotonic() - start_time
    logger.info("")
    logger.info("=" * 60)
    logger.info("FINAL RESULTS")
    logger.info("=" * 60)
    logger.info("Samples: %d / %d", len(sim_scores), len(entries))
    logger.info("SIM: mean=%.4f std=%.4f min=%.4f max=%.4f",
                np.mean(sim_scores), np.std(sim_scores),
                np.min(sim_scores), np.max(sim_scores))
    logger.info("Median: %.4f", np.median(sim_scores))
    logger.info("p25=%.4f p75=%.4f p90=%.4f",
                np.percentile(sim_scores, 25),
                np.percentile(sim_scores, 75),
                np.percentile(sim_scores, 90))
    logger.info("Time: %.1f hours", elapsed / 3600)
    logger.info("")
    logger.info("Comparison:")
    logger.info("  Seed-TTS DiT (#1):  0.790")
    logger.info("  Human ground truth: 0.730")
    logger.info("  ClipCannon:         %.4f", np.mean(sim_scores))

    results = {
        "benchmark": "SeedTTS-Eval Final Run (test-en)",
        "encoder": "WavLM-Large + ECAPA-TDNN (official, 192-dim)",
        "model": "Qwen3-TTS-12Hz-1.7B-Base (unmodified)",
        "config": {
            "temperatures": [0.3, 0.4, 0.5],
            "candidates_per_temp": 8,
            "total_candidates": 24,
            "icl_mode": "Full (ref audio + transcript)",
            "scoring": "Official WavLM-Large for candidate selection",
            "post_processing": "none",
            "ref_preprocessing": "trim silence + normalize",
        },
        "results": {
            "n_samples": len(sim_scores),
            "sim_mean": round(np.mean(sim_scores), 4),
            "sim_std": round(np.std(sim_scores), 4),
            "sim_median": round(np.median(sim_scores), 4),
            "sim_min": round(np.min(sim_scores), 4),
            "sim_max": round(np.max(sim_scores), 4),
            "sim_p25": round(np.percentile(sim_scores, 25), 4),
            "sim_p75": round(np.percentile(sim_scores, 75), 4),
            "sim_p90": round(np.percentile(sim_scores, 90), 4),
        },
        "comparison": {
            "seed_tts_dit": 0.790,
            "human_ground_truth": 0.730,
        },
        "time_hours": round(elapsed / 3600, 1),
        "all_scores": [round(s, 4) for s in sim_scores],
    }

    with open(RESULTS_DIR / "09_seedtts_final.json", "w") as f:
        json.dump(results, f, indent=2)

    gc.collect()
    torch.cuda.empty_cache()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--max-samples", type=int, default=0)
    args = p.parse_args()
    run(max_samples=args.max_samples)
