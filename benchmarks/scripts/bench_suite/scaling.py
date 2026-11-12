"""Benchmark 3: reference scaling study (SECS vs number of reference clips)."""
import json
import logging

import numpy as np

from .common import cosine_sim
from .config import RESULTS_DIR, VOICE_DATA

logger = logging.getLogger(__name__)


# ==========================================================================
# BENCHMARK 3: Reference Scaling Study
# ==========================================================================

def benchmark_scaling(n_test=10):
    """Show how SECS improves with more reference clips."""
    logger.info("=" * 60)
    logger.info("BENCHMARK 3: Reference Scaling Study")
    logger.info("=" * 60)

    from clipcannon.voice.verify import build_reference_embedding, _extract_embedding

    all_clips = sorted(VOICE_DATA.glob("*.wav"))
    scale_points = [1, 3, 5, 10, 25, 50, 100, 250, len(all_clips)]
    scale_points = [s for s in scale_points if s <= len(all_clips)]

    scaling_results = []

    for n_refs in scale_points:
        ref_subset = all_clips[:n_refs]
        ref_emb = build_reference_embedding(ref_subset)

        # Score held-out real clips against this fingerprint
        held_out = all_clips[max(n_refs, 50):max(n_refs, 50) + n_test]
        if len(held_out) < n_test:
            held_out = all_clips[-n_test:]

        scores = []
        for clip in held_out:
            emb = _extract_embedding(clip)
            scores.append(cosine_sim(ref_emb, emb))

        result = {
            "n_reference_clips": n_refs,
            "secs_mean": round(np.mean(scores), 4),
            "secs_std": round(np.std(scores), 4),
            "secs_min": round(np.min(scores), 4),
            "secs_max": round(np.max(scores), 4),
        }
        scaling_results.append(result)
        logger.info(
            "  %3d refs -> SECS: %.4f +/- %.4f (range: %.4f - %.4f)",
            n_refs, result["secs_mean"], result["secs_std"],
            result["secs_min"], result["secs_max"],
        )

    with open(RESULTS_DIR / "03_scaling.json", "w") as f:
        json.dump(scaling_results, f, indent=2)

    return scaling_results
