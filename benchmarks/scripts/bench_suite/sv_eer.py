"""Benchmark 1: speaker-verification EER with an independent SpeechBrain encoder."""
import gc
import json
import logging

import numpy as np
import soundfile as sf
import torch

from .common import (
    cosine_sim,
    denoise_audio,
    extract_sb_embedding,
    generate_best_of_n,
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
# BENCHMARK 1: Speaker Verification EER
# ==========================================================================

def benchmark_sv_eer(n_test=20):
    """Test if an independent speaker verification system can tell real from clone."""
    logger.info("=" * 60)
    logger.info("BENCHMARK 1: Speaker Verification EER")
    logger.info("=" * 60)

    sb_model = load_speechbrain_encoder()

    # Split real clips: 50 enrollment, rest for testing
    all_clips = sorted(VOICE_DATA.glob("*.wav"))
    enrollment_clips = all_clips[:50]
    real_test_clips = all_clips[50:50 + n_test]

    # Build enrollment centroid (average of 50 real clips)
    logger.info("Building enrollment centroid from %d clips...", len(enrollment_clips))
    enroll_embs = [extract_sb_embedding(sb_model, c) for c in enrollment_clips]
    enroll_centroid = np.mean(enroll_embs, axis=0)
    enroll_centroid = enroll_centroid / (np.linalg.norm(enroll_centroid) + 1e-12)

    # Score real test clips against enrollment
    logger.info("Scoring %d real test clips...", len(real_test_clips))
    real_scores = []
    for clip in real_test_clips:
        emb = extract_sb_embedding(sb_model, clip)
        real_scores.append(cosine_sim(enroll_centroid, emb))

    # Generate synthetic clips and score
    logger.info("Generating %d synthetic clips...", n_test)
    from clipcannon.voice.inference import VoiceSynthesizer
    from clipcannon.voice.verify import _extract_embedding

    synth = VoiceSynthesizer()
    engine = synth._ensure_engine()
    real_emb = _extract_embedding(REAL_REFERENCE)

    synth_scores = []
    gen_dir = GENERATED_DIR / "sv_eer"
    gen_dir.mkdir(parents=True, exist_ok=True)

    for i, text in enumerate(TEST_SENTENCES[:n_test]):
        out_path = gen_dir / f"synth_{i:03d}.wav"
        if not out_path.exists():
            wav_np, sr, secs = generate_best_of_n(
                engine, text, REAL_REFERENCE, REF_TEXT, real_emb, n=4,
            )
            sf.write(str(out_path), wav_np, sr)
            # Denoise
            dn_path = gen_dir / f"synth_{i:03d}_dn.wav"
            denoise_audio(out_path, dn_path)
            out_path = dn_path
        else:
            dn_path = gen_dir / f"synth_{i:03d}_dn.wav"
            if dn_path.exists():
                out_path = dn_path

        emb = extract_sb_embedding(sb_model, out_path)
        synth_scores.append(cosine_sim(enroll_centroid, emb))
        logger.info("  Synth %d: SB-SECS=%.4f", i, synth_scores[-1])

    synth.release()

    # Compute EER
    real_mean = np.mean(real_scores)
    synth_mean = np.mean(synth_scores)
    real_std = np.std(real_scores)
    synth_std = np.std(synth_scores)

    # Can the verifier distinguish? If synth scores overlap with real scores, EER ~ 50% (can't tell)
    all_scores = real_scores + synth_scores
    all_labels = [1] * len(real_scores) + [0] * len(synth_scores)

    # Sweep thresholds
    thresholds = np.linspace(min(all_scores) - 0.01, max(all_scores) + 0.01, 1000)
    best_eer = 1.0
    best_thresh = 0.0
    for t in thresholds:
        # Real clips above threshold = correctly accepted
        # Synth clips above threshold = falsely accepted (spoofed)
        frr = sum(1 for s in real_scores if s < t) / len(real_scores)
        far = sum(1 for s in synth_scores if s >= t) / len(synth_scores)
        eer = (frr + far) / 2
        if abs(frr - far) < abs(best_eer * 2 - 1):
            best_eer = (frr + far) / 2
            best_thresh = t

    results = {
        "benchmark": "Speaker Verification EER",
        "encoder": "SpeechBrain ECAPA-TDNN 192-dim (independent)",
        "enrollment_clips": len(enrollment_clips),
        "real_test_clips": len(real_test_clips),
        "synthetic_clips": len(synth_scores),
        "real_scores_mean": round(real_mean, 4),
        "real_scores_std": round(real_std, 4),
        "synthetic_scores_mean": round(synth_mean, 4),
        "synthetic_scores_std": round(synth_std, 4),
        "eer": round(best_eer, 4),
        "eer_threshold": round(best_thresh, 4),
        "interpretation": (
            "INDISTINGUISHABLE" if best_eer > 0.40
            else "HARD TO DISTINGUISH" if best_eer > 0.25
            else "DISTINGUISHABLE"
        ),
        "real_scores": [round(s, 4) for s in real_scores],
        "synthetic_scores": [round(s, 4) for s in synth_scores],
    }

    logger.info("Real scores:  mean=%.4f std=%.4f", real_mean, real_std)
    logger.info("Synth scores: mean=%.4f std=%.4f", synth_mean, synth_std)
    logger.info("EER: %.2f%% at threshold %.4f", best_eer * 100, best_thresh)
    logger.info("Interpretation: %s", results["interpretation"])

    with open(RESULTS_DIR / "01_sv_eer.json", "w") as f:
        json.dump(results, f, indent=2)

    del sb_model
    gc.collect()
    torch.cuda.empty_cache()
    return results
