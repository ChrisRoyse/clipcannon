"""SECS-driven voice synthesis optimization for Qwen3-TTS.

Uses speaker encoder fingerprints as the quality gate for ranking
candidates.

Optimization pipeline:
  1. Select best reference clips by speaker encoder SECS
  2. Build Qwen3-TTS voice clone prompt from best reference
  3. Generate N candidates with different seeds
  4. Score all by SECS (speaker encoder cosine similarity)
  5. Return the winner
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from clipcannon.voice.verify import VoiceVerifier

logger = logging.getLogger(__name__)


@dataclass
class OptimizedSpeakResult:
    """Result from SECS-optimized voice synthesis.

    Attributes:
        audio_path: Path to the best candidate WAV.
        duration_ms: Duration of the audio.
        sample_rate: Output sample rate.
        secs_score: SECS of the winning candidate.
        candidates_generated: Total candidates evaluated.
        best_candidate_index: Which candidate won (0-indexed).
        reference_clip_used: Reference clip path used.
        elapsed_s: Total time for the optimized generation.
    """

    audio_path: Path
    duration_ms: int
    sample_rate: int
    secs_score: float
    candidates_generated: int
    best_candidate_index: int
    reference_clip_used: str
    elapsed_s: float


def select_best_reference(
    candidate_clips: list[Path],
    verifier: VoiceVerifier,
    max_candidates: int = 20,
) -> tuple[float, Path]:
    """Score candidate clips by speaker encoder similarity and return the best.

    Args:
        candidate_clips: Paths to WAV clips to evaluate.
        verifier: VoiceVerifier with target speaker's fingerprint.
        max_candidates: Max clips to score (for speed).

    Returns:
        Tuple of (best_secs_score, best_path).

    Raises:
        ValueError: If no valid clips found.
    """
    import random
    clips = list(candidate_clips)
    if len(clips) > max_candidates:
        random.seed(42)
        clips = random.sample(clips, max_candidates)

    best_secs = -1.0
    best_path: Path | None = None

    for clip in clips:
        try:
            secs = verifier.compute_secs(clip)
            if secs > best_secs:
                best_secs = secs
                best_path = clip
        except Exception as exc:
            logger.debug("Failed to score %s: %s", clip.name, exc)

    if best_path is None:
        raise ValueError(f"No valid reference clips from {len(candidate_clips)} candidates")

    logger.info("Best reference: %s (SECS=%.3f)", best_path.name, best_secs)
    return best_secs, best_path


def best_of_n_speak(
    engine: object,
    text: str,
    prompt: object,
    verifier: VoiceVerifier,
    output_path: Path,
    n_candidates: int = 12,
    temperature: float | tuple[float, ...] = (0.3, 0.4, 0.5),
    max_new_tokens: int = 2048,
) -> tuple[np.ndarray, float, int, int]:
    """Generate N candidates and return the one with highest SECS.

    Supports multi-temperature generation: when temperature is a tuple,
    candidates are distributed evenly across temperatures. Different
    temperatures capture different aspects of the speaker's voice,
    increasing the chance of finding a high-SECS candidate.

    Args:
        engine: Qwen3TTSModel instance.
        text: Text to synthesize.
        prompt: VoiceClonePromptItem from create_voice_clone_prompt.
        verifier: VoiceVerifier for SECS scoring.
        output_path: Where to write the winning candidate.
        n_candidates: Number of candidates to generate.
        temperature: Sampling temperature. Pass a tuple of floats
            for multi-temperature sweep (recommended: (0.3, 0.4, 0.5)).
        max_new_tokens: Max generation tokens.

    Returns:
        Tuple of (best_wav, best_secs, best_index, sample_rate).
    """
    candidates: list[tuple[float, np.ndarray, int, int]] = []
    temp_path = output_path.parent / f"_temp_{output_path.stem}.wav"

    # Build temperature schedule
    if isinstance(temperature, (list, tuple)):
        temps = list(temperature)
        per_temp = max(1, n_candidates // len(temps))
        temp_schedule = []
        for t in temps:
            temp_schedule.extend([t] * per_temp)
        # Fill remaining with middle temperature
        while len(temp_schedule) < n_candidates:
            temp_schedule.append(temps[len(temps) // 2])
        temp_schedule = temp_schedule[:n_candidates]
    else:
        temp_schedule = [temperature] * n_candidates

    for i in range(n_candidates):
        seed = int(torch.randint(0, 2**31, (1,)).item())
        torch.manual_seed(seed)
        current_temp = temp_schedule[i]

        wavs, sr = engine.generate_voice_clone(  # type: ignore[union-attr]
            text=text,
            language="English",
            voice_clone_prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=current_temp,
            top_p=0.85,
            repetition_penalty=1.05,
        )

        wav_np = wavs[0] if isinstance(wavs[0], np.ndarray) else wavs[0].cpu().numpy()

        # Write temp for SECS scoring
        sf.write(str(temp_path), wav_np, sr)
        secs = verifier.compute_secs(temp_path)
        candidates.append((secs, wav_np, i, sr))

        logger.debug(
            "Candidate %d/%d (temp=%.1f): SECS=%.4f (seed=%d)",
            i + 1, n_candidates, current_temp, secs, seed,
        )

    temp_path.unlink(missing_ok=True)

    # Pick the winner
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_secs, best_wav, best_idx, best_sr = candidates[0]

    sf.write(str(output_path), best_wav, best_sr)

    logger.info(
        "Best-of-%d: winner=%d, SECS=%.4f (range: %.4f-%.4f)",
        n_candidates, best_idx, best_secs,
        candidates[-1][0], candidates[0][0],
    )

    return best_wav, best_secs, best_idx, best_sr


def optimized_speak(
    engine: object,
    text: str,
    output_path: Path,
    verifier: VoiceVerifier,
    reference_clips: list[Path],
    reference_text: str | None = None,
    n_candidates: int = 12,
    temperature: float | tuple[float, ...] = (0.3, 0.4, 0.5),
    max_new_tokens: int = 2048,
) -> OptimizedSpeakResult:
    """Full SECS-optimized voice synthesis pipeline.

    Pipeline:
      1. Select best reference clip by speaker encoder SECS
      2. Build Qwen3-TTS voice clone prompt from it
      3. Generate N candidates with different seeds
      4. Score all by SECS (speaker encoder cosine similarity)
      5. Return the winner

    Args:
        engine: Qwen3TTSModel instance.
        text: Text to synthesize.
        output_path: Where to write the final WAV.
        verifier: VoiceVerifier with target speaker's fingerprint.
        reference_clips: All available reference audio clips.
        reference_text: Transcript of the best reference clip.
        n_candidates: Candidates to generate (8 = good tradeoff).
        temperature: Sampling temperature.
        max_new_tokens: Max generation tokens.

    Returns:
        OptimizedSpeakResult with the winning candidate details.
    """
    from clipcannon.voice.inference import _trim_reference

    start = time.monotonic()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Find best reference clip
    _, best_ref = select_best_reference(reference_clips, verifier)

    # Step 2: Build prompt (trim ref to 15s max)
    ref_path = _trim_reference(best_ref)
    use_xvec = reference_text is None

    prompt = engine.create_voice_clone_prompt(  # type: ignore[union-attr]
        ref_audio=str(ref_path),
        ref_text=reference_text if not use_xvec else None,
        x_vector_only_mode=use_xvec,
    )

    # Step 3+4: Best-of-N with SECS scoring
    best_wav, best_secs, best_idx, best_sr = best_of_n_speak(
        engine=engine,
        text=text,
        prompt=prompt,
        verifier=verifier,
        output_path=output_path,
        n_candidates=n_candidates,
        temperature=temperature,
        max_new_tokens=max_new_tokens,
    )

    elapsed = time.monotonic() - start
    duration_ms = int(len(best_wav) / best_sr * 1000)

    logger.info(
        "Optimized speak: SECS=%.4f, %d candidates, %.1fs",
        best_secs, n_candidates, elapsed,
    )

    return OptimizedSpeakResult(
        audio_path=output_path,
        duration_ms=duration_ms,
        sample_rate=best_sr,
        secs_score=best_secs,
        candidates_generated=n_candidates,
        best_candidate_index=best_idx,
        reference_clip_used=str(best_ref),
        elapsed_s=round(elapsed, 2),
    )
