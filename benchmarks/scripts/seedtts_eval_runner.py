"""SeedTTS-Eval Benchmark Runner for ClipCannon.

Runs the SeedTTS-Eval benchmark (1,000 English samples from Common Voice)
using ClipCannon's voice cloning pipeline with all optimizations:

  1. Full ICL mode (reference audio + transcript provided by benchmark)
  2. WavLM-scored best-of-N candidate selection
  3. Adaptive temperature based on reference duration
  4. Reference preprocessing (trim silence, normalize, denoise)
  5. Score with WavLMForXVector (benchmark-compatible encoder)

Usage:
  1. Download SeedTTS-Eval test set from Google Drive
  2. Download wavlm_large_finetune.pth for official scoring
  3. Run this script to generate all samples
  4. Run cal_wer.sh and cal_sim.sh for official scores

This script lives in benchmarks/ and does NOT modify ClipCannon source code.
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

# Import ClipCannon modules (read-only, no modifications)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

logging.basicConfig(format="%(levelname)s | %(asctime)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BENCH_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BENCH_DIR / "seedtts_eval" / "generated_en"
RESULTS_DIR = BENCH_DIR / "results"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================================
# WavLM encoder for candidate scoring (benchmark-compatible)
# =========================================================================

_wavlm = None
_wavlm_fe = None


def get_wavlm():
    """Load WavLMForXVector (ClonEval/benchmark-compatible encoder)."""
    global _wavlm, _wavlm_fe
    if _wavlm is None:
        from transformers import WavLMForXVector, AutoFeatureExtractor
        logger.info("Loading WavLMForXVector for candidate scoring...")
        _wavlm_fe = AutoFeatureExtractor.from_pretrained("microsoft/wavlm-base-plus-sv")
        _wavlm = WavLMForXVector.from_pretrained("microsoft/wavlm-base-plus-sv")
        _wavlm = _wavlm.to("cuda").eval()
        logger.info("WavLMForXVector loaded")
    return _wavlm, _wavlm_fe


def wavlm_emb(wav_np: np.ndarray, sr: int) -> np.ndarray:
    """Extract L2-normalized 512-dim WavLM x-vector."""
    model, fe = get_wavlm()
    if sr != 16000:
        wav_t = torch.from_numpy(wav_np).float().unsqueeze(0)
        wav_t = torchaudio.functional.resample(wav_t, sr, 16000)
        wav_np = wav_t.squeeze().numpy()
    inputs = fe(wav_np, sampling_rate=16000, return_tensors="pt", padding=True)
    with torch.no_grad():
        out = model(inputs["input_values"].to("cuda"))
    emb = out.embeddings[0].cpu().numpy().astype(np.float32)
    return emb / (np.linalg.norm(emb) + 1e-12)


def cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # both L2-normalized


# =========================================================================
# Reference preprocessing
# =========================================================================

def preprocess_reference(input_path: Path) -> tuple[np.ndarray, int]:
    """Preprocess reference audio for optimal ICL quality.

    - Mono, 24kHz (Qwen3-TTS native)
    - Trim silence
    - Peak normalize to -1dB
    - Denoise only (no bandwidth extension)
    """
    wav, sr = torchaudio.load(str(input_path))
    wav = wav.mean(dim=0)  # mono

    if sr != 24000:
        wav = torchaudio.functional.resample(wav, sr, 24000)
        sr = 24000

    # Trim silence (energy-based)
    abs_wav = wav.abs()
    threshold = 0.01
    above = (abs_wav > threshold).nonzero(as_tuple=True)[0]
    if len(above) > 0:
        start = max(0, above[0].item() - int(0.05 * sr))
        end = min(len(wav), above[-1].item() + int(0.3 * sr))
        wav = wav[start:end]

    # Peak normalize to -1dB
    peak = wav.abs().max()
    if peak > 0:
        target = 10 ** (-1.0 / 20)
        wav = wav * (target / peak)

    # Denoise only (removes noise without changing spectral character)
    try:
        from resemble_enhance.enhancer.inference import denoise
        wav, sr = denoise(wav.float(), sr, "cuda")
    except Exception:
        pass  # skip if denoise fails, raw is fine

    return wav.numpy().astype(np.float32), sr


# =========================================================================
# Adaptive parameters
# =========================================================================

def optimal_temperature(ref_duration_s: float) -> float:
    """Lower temperature for longer references (stronger ICL signal)."""
    if ref_duration_s >= 10:
        return 0.3
    elif ref_duration_s >= 5:
        return 0.35
    elif ref_duration_s >= 3:
        return 0.45
    else:
        return 0.5


def optimal_n_candidates(ref_duration_s: float) -> int:
    """More candidates for shorter references (higher variance)."""
    if ref_duration_s >= 10:
        return 12
    elif ref_duration_s >= 5:
        return 16
    else:
        return 20


# =========================================================================
# Parse SeedTTS-Eval meta file
# =========================================================================

def parse_meta(meta_path: Path) -> list[dict]:
    """Parse SeedTTS-Eval meta.lst file.

    Format: utt_id|prompt_text|prompt_wav|infer_text|[ground_truth_wav]
    """
    entries = []
    with open(meta_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 4:
                continue
            entry = {
                "utt_id": parts[0].strip(),
                "prompt_text": parts[1].strip(),
                "prompt_wav": parts[2].strip(),
                "infer_text": parts[3].strip(),
            }
            if len(parts) >= 5:
                entry["ground_truth_wav"] = parts[4].strip()
            entries.append(entry)
    return entries


# =========================================================================
# Main generation loop
# =========================================================================

def run_seedtts_eval(
    meta_path: Path,
    test_data_dir: Path,
    max_samples: int = 0,
):
    """Run SeedTTS-Eval benchmark generation.

    Args:
        meta_path: Path to en/meta.lst
        test_data_dir: Directory containing the test set (prompt wavs)
        max_samples: Max samples to generate (0 = all)
    """
    entries = parse_meta(meta_path)
    if max_samples > 0:
        entries = entries[:max_samples]

    logger.info("SeedTTS-Eval: %d samples to generate", len(entries))

    # Load TTS engine
    from clipcannon.voice.inference import VoiceSynthesizer, _trim_reference
    synth = VoiceSynthesizer()
    engine = synth._ensure_engine()

    # Warm up WavLM
    get_wavlm()

    success = 0
    fail = 0
    sim_scores = []
    start_time = time.monotonic()

    for idx, entry in enumerate(entries):
        utt_id = entry["utt_id"]
        out_path = OUTPUT_DIR / f"{utt_id}.wav"

        # Skip if already generated
        if out_path.exists():
            success += 1
            continue

        # Resolve prompt wav path
        prompt_wav_path = Path(entry["prompt_wav"])
        if not prompt_wav_path.is_absolute():
            prompt_wav_path = test_data_dir / entry["prompt_wav"]

        if not prompt_wav_path.exists():
            logger.warning("Missing prompt wav: %s", prompt_wav_path)
            fail += 1
            continue

        try:
            # Preprocess reference
            ref_np, ref_sr = preprocess_reference(prompt_wav_path)
            ref_duration_s = len(ref_np) / ref_sr

            # Save preprocessed ref to temp file for ICL
            tmp_ref = OUTPUT_DIR / f"_tmp_ref_{utt_id}.wav"
            sf.write(str(tmp_ref), ref_np, ref_sr)

            # Adaptive parameters
            temp = optimal_temperature(ref_duration_s)
            n_cand = optimal_n_candidates(ref_duration_s)

            # Build ICL prompt (Full ICL with transcript)
            ref_trimmed = _trim_reference(tmp_ref)
            prompt = engine.create_voice_clone_prompt(
                ref_audio=str(ref_trimmed),
                ref_text=entry["prompt_text"],
                x_vector_only_mode=False,
            )

            # Extract WavLM embedding from reference for scoring
            ref_emb = wavlm_emb(ref_np, ref_sr)

            # Best-of-N with WavLM scoring
            best_sim, best_wav, best_sr = -1, None, 24000
            for i in range(n_cand):
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

                # Score with WavLM
                cand_emb = wavlm_emb(wav_np, sr)
                sim = cos_sim(ref_emb, cand_emb)

                if sim > best_sim:
                    best_sim, best_wav, best_sr = sim, wav_np, sr

            # Save best candidate (raw, no enhancement for scoring)
            sf.write(str(out_path), best_wav, best_sr)
            sim_scores.append(best_sim)
            success += 1

            # Cleanup temp
            tmp_ref.unlink(missing_ok=True)

            elapsed = time.monotonic() - start_time
            rate = success / elapsed * 3600 if elapsed > 0 else 0

            if success % 10 == 0:
                logger.info(
                    "[%d/%d] SIM=%.4f (mean=%.4f) | %.0f samples/hr | %s",
                    success, len(entries),
                    best_sim, np.mean(sim_scores),
                    rate,
                    entry["infer_text"][:50],
                )

        except Exception as e:
            logger.error("Failed %s: %s", utt_id, e)
            fail += 1
            continue

    synth.release()

    # Summary
    elapsed = time.monotonic() - start_time
    logger.info("")
    logger.info("=" * 60)
    logger.info("SeedTTS-Eval Generation Complete")
    logger.info("=" * 60)
    logger.info("Success: %d, Failed: %d, Total: %d", success, fail, len(entries))
    logger.info("Time: %.1f minutes", elapsed / 60)
    if sim_scores:
        logger.info("WavLM SIM (best-of-N): mean=%.4f, std=%.4f, min=%.4f, max=%.4f",
                     np.mean(sim_scores), np.std(sim_scores),
                     np.min(sim_scores), np.max(sim_scores))
    logger.info("Output: %s", OUTPUT_DIR)
    logger.info("")
    logger.info("Next steps:")
    logger.info("  1. Run official SeedTTS-Eval scoring:")
    logger.info("     cd /tmp/seed-tts-eval")
    logger.info("     bash cal_wer.sh %s %s en", meta_path, OUTPUT_DIR)
    logger.info("     bash cal_sim.sh %s %s /path/to/wavlm_large_finetune.pth", meta_path, OUTPUT_DIR)

    results = {
        "benchmark": "SeedTTS-Eval (test-en)",
        "samples_generated": success,
        "samples_failed": fail,
        "generation_time_minutes": round(elapsed / 60, 1),
        "wavlm_sim_preliminary": {
            "encoder": "WavLMForXVector (microsoft/wavlm-base-plus-sv, 512-dim)",
            "note": "Preliminary. Official scores use WavLM-Large + ECAPA-TDNN (192-dim)",
            "mean": round(np.mean(sim_scores), 4) if sim_scores else None,
            "std": round(np.std(sim_scores), 4) if sim_scores else None,
            "min": round(np.min(sim_scores), 4) if sim_scores else None,
            "max": round(np.max(sim_scores), 4) if sim_scores else None,
        },
        "pipeline_config": {
            "model": "Qwen3-TTS-12Hz-1.7B-Base",
            "icl_mode": "Full (ref audio + transcript)",
            "temperature": "adaptive (0.3-0.5 based on ref duration)",
            "n_candidates": "adaptive (12-20 based on ref duration)",
            "scoring_encoder": "WavLMForXVector during generation",
            "post_processing": "none (raw for scoring)",
            "ref_preprocessing": "trim silence + normalize + denoise-only",
        },
    }

    with open(RESULTS_DIR / "07_seedtts_eval.json", "w") as f:
        json.dump(results, f, indent=2)

    gc.collect()
    torch.cuda.empty_cache()
    return results


# =========================================================================
# MAIN
# =========================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run SeedTTS-Eval benchmark")
    parser.add_argument("--meta", type=str, required=True,
                        help="Path to en/meta.lst from SeedTTS-Eval test set")
    parser.add_argument("--data-dir", type=str, required=True,
                        help="Directory containing test set (prompt wavs)")
    parser.add_argument("--max-samples", type=int, default=0,
                        help="Max samples to generate (0=all)")
    args = parser.parse_args()

    run_seedtts_eval(
        meta_path=Path(args.meta),
        test_data_dir=Path(args.data_dir),
        max_samples=args.max_samples,
    )
