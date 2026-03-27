"""ClipCannon Voice Cloning Benchmark Suite.

Runs all benchmarks designed for personalized voice cloning:
  1. Speaker Verification EER (can an independent verifier tell real from clone?)
  2. Pipeline Ablation Study (incremental value of each component)
  3. Reference Scaling Study (SECS vs number of reference clips)
  4. UTMOS Naturalness (automated MOS prediction)
  5. Cross-encoder SECS (SpeechBrain 192-dim as independent verifier)

All tests use Chris's real voice data and score against his actual recordings.
"""

import gc
import json
import logging
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

logging.basicConfig(
    format="%(levelname)s | %(asctime)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BENCH_DIR = Path(__file__).parent.parent
RESULTS_DIR = BENCH_DIR / "results"
GENERATED_DIR = BENCH_DIR / "generated"
VOICE_DATA = Path.home() / ".clipcannon" / "voice_data" / "boris" / "wavs"
REAL_REFERENCE = Path("/home/cabdru/.clipcannon/projects/proj_f0101c2d/audio/chris_real_reference.wav")
REF_TEXT = "OCR Provenance MCP server is the best AI memory system in existence"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# 50 novel sentences Chris never said - for generating test clips
TEST_SENTENCES = [
    "The weather outside is absolutely beautiful today.",
    "I just finished reading a really interesting book about space exploration.",
    "Can you believe how fast technology is advancing these days?",
    "Let me show you how this new feature works in the application.",
    "The meeting has been rescheduled to three o'clock tomorrow afternoon.",
    "We need to discuss the quarterly budget before the end of the week.",
    "I think the best approach would be to start with the basics first.",
    "Have you ever tried cooking Italian food from scratch at home?",
    "The traffic on the highway was absolutely terrible this morning.",
    "I'm really excited about the upcoming product launch next month.",
    "Please make sure to save your work before closing the application.",
    "The customer feedback has been overwhelmingly positive so far.",
    "Let's take a quick break and come back in about fifteen minutes.",
    "I noticed a few small issues that we should probably address soon.",
    "The sunset over the mountains was one of the most beautiful things I've ever seen.",
    "Don't forget to update your password at least once every ninety days.",
    "We should consider expanding our team to handle the increased workload.",
    "The presentation went really well and the client seemed very impressed.",
    "I'll send you the report by end of business today at the latest.",
    "Running every morning has completely changed my energy levels throughout the day.",
    "The new restaurant downtown has the best tacos I've ever tasted.",
    "Make sure you double check the numbers before submitting the final report.",
    "I've been working on this project for almost three months now.",
    "The conference call is scheduled for nine thirty eastern time.",
    "We should probably back up all the important files before the migration.",
    "The garden is looking amazing after all the rain we had last week.",
    "I'll pick up some groceries on my way home from the office.",
    "The documentary about ocean life was absolutely fascinating to watch.",
    "Please review the pull request when you get a chance today.",
    "The kids had so much fun at the park yesterday afternoon.",
    "We need a more efficient way to process these incoming requests.",
    "The flight to New York has been delayed by approximately two hours.",
    "I'm thinking about signing up for that online photography course.",
    "The team really pulled together and delivered an amazing result.",
    "Can you send me the link to the shared document we discussed?",
    "The air conditioning in the office needs to be repaired urgently.",
    "I learned so much from attending that workshop last weekend.",
    "The database performance has improved significantly after the optimization.",
    "Let me know if you have any questions about the new process.",
    "The morning fog made the drive to work quite a bit more challenging.",
    "We should celebrate the team's achievement with a dinner this Friday.",
    "The software update includes several important security patches.",
    "I just got back from vacation and I'm feeling completely refreshed.",
    "The quarterly results exceeded our expectations by a significant margin.",
    "Please remember to lock the door when you leave the building tonight.",
    "The podcast episode about artificial intelligence was incredibly thought provoking.",
    "We might need to adjust our timeline based on the latest feedback.",
    "The autumn leaves are changing color and the whole neighborhood looks stunning.",
    "I'm going to reorganize my desk this weekend to be more productive.",
    "The project deadline has been moved up by two weeks unfortunately.",
]


def load_speechbrain_encoder():
    """Load SpeechBrain ECAPA-TDNN (192-dim, independent from our pipeline)."""
    from speechbrain.inference.speaker import SpeakerRecognition
    model_dir = BENCH_DIR / "models" / "speechbrain-ecapa"
    model_dir.mkdir(parents=True, exist_ok=True)
    model = SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(model_dir),
    )
    logger.info("SpeechBrain ECAPA-TDNN loaded (192-dim, independent encoder)")
    return model


def extract_sb_embedding(model, audio_path: Path) -> np.ndarray:
    """Extract 192-dim embedding using SpeechBrain (independent encoder)."""
    wav, sr = torchaudio.load(str(audio_path))
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)
    return model.encode_batch(wav).squeeze().cpu().numpy().astype(np.float32)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm > 1e-12 else 0.0


def generate_single(engine, text: str, ref_path: Path, ref_text: str,
                     temperature: float = 0.5, use_icl: bool = True) -> np.ndarray:
    """Generate a single TTS clip."""
    from clipcannon.voice.inference import _trim_reference
    trimmed = _trim_reference(ref_path)
    prompt = engine.create_voice_clone_prompt(
        ref_audio=str(trimmed),
        ref_text=ref_text if use_icl else None,
        x_vector_only_mode=not use_icl,
    )
    wavs, sr = engine.generate_voice_clone(
        text=text, language="English", voice_clone_prompt=prompt,
        max_new_tokens=2048, temperature=temperature,
        top_p=0.85, repetition_penalty=1.05,
    )
    wav_np = wavs[0] if isinstance(wavs[0], np.ndarray) else wavs[0].cpu().numpy()
    return wav_np, sr


def generate_best_of_n(engine, text: str, ref_path: Path, ref_text: str,
                        real_emb: np.ndarray, n: int = 8) -> tuple:
    """Generate N candidates, return best by SECS against real voice."""
    from clipcannon.voice.verify import _extract_embedding
    best_secs, best_wav, best_sr = -1, None, 24000
    for i in range(n):
        torch.manual_seed(int(torch.randint(0, 2**31, (1,)).item()))
        wav_np, sr = generate_single(engine, text, ref_path, ref_text)
        tmp = GENERATED_DIR / "_tmp_bench.wav"
        sf.write(str(tmp), wav_np, sr)
        cand_emb = _extract_embedding(tmp)
        norm = np.linalg.norm(real_emb) * np.linalg.norm(cand_emb)
        secs = float(np.dot(real_emb, cand_emb) / norm)
        if secs > best_secs:
            best_secs, best_wav, best_sr = secs, wav_np, sr
        tmp.unlink(missing_ok=True)
    return best_wav, best_sr, best_secs


def denoise_audio(input_path: Path, output_path: Path) -> Path:
    """Apply Resemble Enhance denoise."""
    from resemble_enhance.enhancer.inference import denoise
    dwav, sr = torchaudio.load(str(input_path))
    dwav = dwav.mean(dim=0).float()
    dwav, sr = denoise(dwav, sr, "cuda")
    torchaudio.save(str(output_path), dwav.unsqueeze(0).cpu(), sr)
    return output_path


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
