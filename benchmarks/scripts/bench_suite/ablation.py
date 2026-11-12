"""Benchmark 2: pipeline ablation study (incremental value of each component)."""
import gc
import json
import logging
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from .common import (
    cosine_sim,
    denoise_audio,
    extract_sb_embedding,
    generate_best_of_n,
    generate_single,
    load_speechbrain_encoder,
)
from .config import (
    GENERATED_DIR,
    REAL_REFERENCE,
    REF_TEXT,
    RESULTS_DIR,
    TEST_SENTENCES,
    VOICE_DATA,
)

logger = logging.getLogger(__name__)


# ==========================================================================
# BENCHMARK 2: Pipeline Ablation Study
# ==========================================================================

def benchmark_ablation(n_test=10):
    """Show incremental value of each pipeline component."""
    logger.info("=" * 60)
    logger.info("BENCHMARK 2: Pipeline Ablation Study")
    logger.info("=" * 60)

    from clipcannon.voice.inference import VoiceSynthesizer, _trim_reference
    from clipcannon.voice.verify import _extract_embedding

    sb_model = load_speechbrain_encoder()
    synth = VoiceSynthesizer()
    engine = synth._ensure_engine()
    real_emb = _extract_embedding(REAL_REFERENCE)

    # Build SpeechBrain centroid from real clips for cross-encoder scoring
    all_clips = sorted(VOICE_DATA.glob("*.wav"))
    sb_enroll = [extract_sb_embedding(sb_model, c) for c in all_clips[:30]]
    sb_centroid = np.mean(sb_enroll, axis=0)
    sb_centroid = sb_centroid / (np.linalg.norm(sb_centroid) + 1e-12)

    configs = [
        {
            "name": "A: Zero-shot (1 random clip, x-vector only, temp=0.8)",
            "ref_clips": [all_clips[200]],  # random single clip
            "use_icl": False,
            "temperature": 0.8,
            "best_of_n": 1,
            "denoise": False,
        },
        {
            "name": "B: + Best reference selection",
            "ref_clips": None,  # will use select_best
            "use_icl": False,
            "temperature": 0.8,
            "best_of_n": 1,
            "denoise": False,
        },
        {
            "name": "C: + Full ICL mode",
            "ref_clips": None,
            "use_icl": True,
            "temperature": 0.5,
            "best_of_n": 1,
            "denoise": False,
        },
        {
            "name": "D: + Best-of-8 selection",
            "ref_clips": None,
            "use_icl": True,
            "temperature": 0.5,
            "best_of_n": 8,
            "denoise": False,
        },
        {
            "name": "E: + Resemble Enhance denoise (FULL PIPELINE)",
            "ref_clips": None,
            "use_icl": True,
            "temperature": 0.5,
            "best_of_n": 8,
            "denoise": True,
        },
    ]

    # Select best reference once
    from clipcannon.voice.optimize import select_best_reference
    from clipcannon.voice.verify import VoiceVerifier
    from clipcannon.voice.profiles import get_voice_profile

    DB_PATH = Path.home() / ".clipcannon" / "voice_profiles.db"
    profile = get_voice_profile(DB_PATH, "boris")
    profile_emb = np.frombuffer(profile["reference_embedding"], dtype=np.float32).copy()
    verifier = VoiceVerifier(profile_emb, threshold=0.50)
    best_secs, best_ref = select_best_reference(all_clips, verifier, max_candidates=30)
    logger.info("Best reference clip: %s (SECS=%.4f)", best_ref.name, best_secs)
    verifier.release()

    # Whisper for ref text of best ref
    from faster_whisper import WhisperModel
    whisper = WhisperModel("base", device="cpu", compute_type="int8")
    segs, _ = whisper.transcribe(str(best_ref), language="en")
    best_ref_text = " ".join(s.text.strip() for s in segs)

    ablation_results = []

    for config in configs:
        logger.info("\nConfig: %s", config["name"])
        ref_path = best_ref if config["ref_clips"] is None else config["ref_clips"][0]
        r_text = best_ref_text if config["ref_clips"] is None else REF_TEXT

        qwen_scores = []
        sb_scores = []

        for i, text in enumerate(TEST_SENTENCES[:n_test]):
            if config["best_of_n"] > 1:
                wav_np, sr, secs = generate_best_of_n(
                    engine, text, ref_path, r_text, real_emb, n=config["best_of_n"],
                )
            else:
                wav_np, sr = generate_single(
                    engine, text, ref_path, r_text,
                    temperature=config["temperature"], use_icl=config["use_icl"],
                )

            tmp_path = GENERATED_DIR / "ablation" / f"_tmp_abl.wav"
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(tmp_path), wav_np, sr)

            if config["denoise"]:
                dn_path = GENERATED_DIR / "ablation" / f"_tmp_abl_dn.wav"
                denoise_audio(tmp_path, dn_path)
                tmp_path = dn_path

            # Score with both encoders
            cand_emb = _extract_embedding(tmp_path)
            qwen_secs = cosine_sim(real_emb, cand_emb)
            qwen_scores.append(qwen_secs)

            sb_emb = extract_sb_embedding(sb_model, tmp_path)
            sb_secs = cosine_sim(sb_centroid, sb_emb)
            sb_scores.append(sb_secs)

        result = {
            "config": config["name"],
            "qwen3_secs_mean": round(np.mean(qwen_scores), 4),
            "qwen3_secs_std": round(np.std(qwen_scores), 4),
            "speechbrain_secs_mean": round(np.mean(sb_scores), 4),
            "speechbrain_secs_std": round(np.std(sb_scores), 4),
            "n_samples": n_test,
        }
        ablation_results.append(result)
        logger.info(
            "  Qwen3 SECS: %.4f +/- %.4f | SpeechBrain SECS: %.4f +/- %.4f",
            result["qwen3_secs_mean"], result["qwen3_secs_std"],
            result["speechbrain_secs_mean"], result["speechbrain_secs_std"],
        )

    synth.release()
    del sb_model
    gc.collect()
    torch.cuda.empty_cache()

    with open(RESULTS_DIR / "02_ablation.json", "w") as f:
        json.dump(ablation_results, f, indent=2)

    return ablation_results
