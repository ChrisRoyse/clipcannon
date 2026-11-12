"""ClipCannon Voice Cloning Benchmark Suite.

Runs all benchmarks designed for personalized voice cloning:
  1. Speaker Verification EER (can an independent verifier tell real from clone?)
  2. Pipeline Ablation Study (incremental value of each component)
  3. Reference Scaling Study (SECS vs number of reference clips)
  4. UTMOS Naturalness (automated MOS prediction)
  5. Cross-encoder SECS (SpeechBrain 192-dim as independent verifier)

All tests use Chris's real voice data and score against his actual recordings.
"""
# Implementation lives in the sibling package benchmarks/scripts/bench_suite/ (split for
# the 500-line file limit). This file is the unchanged entry point and re-exports every
# top-level name of the original script.

import gc
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio
from bench_suite.ablation import benchmark_ablation
from bench_suite.common import (
    cosine_sim,
    denoise_audio,
    extract_sb_embedding,
    generate_best_of_n,
    generate_single,
    load_speechbrain_encoder,
)
from bench_suite.config import (
    BENCH_DIR,
    GENERATED_DIR,
    REAL_REFERENCE,
    REF_TEXT,
    RESULTS_DIR,
    TEST_SENTENCES,
    VOICE_DATA,
)
from bench_suite.scaling import benchmark_scaling
from bench_suite.sv_eer import benchmark_sv_eer

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

logging.basicConfig(
    format="%(levelname)s | %(asctime)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


__all__ = [
    "gc", "json", "logging", "sys", "time", "dataclass", "field", "asdict", "Path", "np", "sf",
    "torch", "torchaudio", "logger", "BENCH_DIR", "RESULTS_DIR", "GENERATED_DIR", "VOICE_DATA",
    "REAL_REFERENCE", "REF_TEXT", "TEST_SENTENCES", "load_speechbrain_encoder",
    "extract_sb_embedding", "cosine_sim", "generate_single", "generate_best_of_n",
    "denoise_audio", "benchmark_sv_eer", "benchmark_ablation", "benchmark_scaling", "main",
]


# ==========================================================================
# MAIN
# ==========================================================================

def main():
    logger.info("ClipCannon Voice Cloning Benchmark Suite")
    logger.info("Target speaker: Chris Royse (profile: boris)")
    logger.info("Reference recording: %s", REAL_REFERENCE)
    logger.info("Voice data clips: %d", len(list(VOICE_DATA.glob("*.wav"))))
    logger.info("")

    all_results = {}

    # Benchmark 3: Scaling (fast, no generation needed)
    all_results["scaling"] = benchmark_scaling(n_test=10)

    # Benchmark 2: Ablation (generates test clips)
    all_results["ablation"] = benchmark_ablation(n_test=10)

    # Benchmark 1: SV-EER (the big one)
    all_results["sv_eer"] = benchmark_sv_eer(n_test=20)

    # Save combined results
    with open(RESULTS_DIR / "00_all_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    logger.info("")
    logger.info("=" * 60)
    logger.info("ALL BENCHMARKS COMPLETE")
    logger.info("Results saved to: %s", RESULTS_DIR)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
