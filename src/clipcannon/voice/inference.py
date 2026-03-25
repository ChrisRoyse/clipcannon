"""StyleTTS2 voice synthesis with iterative verification loop.

Wraps the StyleTTS2 inference engine and integrates the multi-gate
VoiceVerifier for quality-gated output. Each speak() call optionally
runs up to N attempts, varying generation parameters until the
verification threshold is met or attempts are exhausted.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

from clipcannon.voice.verify import VerificationResult, VoiceVerifier

logger = logging.getLogger(__name__)

_TARGET_SR = 24000  # StyleTTS2 default output sample rate


@dataclass
class SpeakResult:
    """Result of a speak() call with optional verification."""

    audio_path: Path
    duration_ms: int
    sample_rate: int
    verification: VerificationResult | None
    attempts: int
    parameters_used: dict[str, object] = field(default_factory=dict)


# -- Parameter escalation schedule -------------------------------------------

_ESCALATION = [
    # (diffusion_steps, alpha_override)
    (5, None),
    (10, None),
    (20, 0.15),
    (20, 0.1),
    (20, 0.05),
]


def _escalation_params(
    attempt: int, base_alpha: float, base_beta: float,
) -> dict[str, object]:
    """Return parameters for a given attempt (0-indexed).

    Escalation strategy:
      Attempt 0: base parameters + random seed
      Attempt 1: seed + diffusion_steps 10
      Attempt 2: seed + steps 20 + alpha 0.15
      Attempt 3: seed + steps 20 + alpha 0.1
      Attempt 4: seed + steps 20 + alpha 0.05
    """
    idx = min(attempt, len(_ESCALATION) - 1)
    steps, alpha_override = _ESCALATION[idx]
    seed = int(torch.randint(0, 2**31, (1,)).item())
    return {
        "diffusion_steps": steps,
        "alpha": alpha_override if alpha_override is not None else base_alpha,
        "beta": base_beta,
        "seed": seed,
    }


# -- Audio resampling helper -------------------------------------------------

def _resample_to_24k(audio_path: Path) -> Path:
    """Resample audio file to 24 kHz WAV for StyleTTS2 compute_style().

    Returns the original path if already 24 kHz, otherwise writes a
    resampled copy next to the original.
    """
    wav, sr = torchaudio.load(str(audio_path))
    if sr == _TARGET_SR:
        return audio_path
    wav = torchaudio.functional.resample(wav, sr, _TARGET_SR)
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    resampled_path = audio_path.parent / f"{audio_path.stem}_24k.wav"
    torchaudio.save(str(resampled_path), wav, _TARGET_SR)
    logger.info("Resampled %s (%d Hz) -> %s (24000 Hz)", audio_path, sr, resampled_path)
    return resampled_path


# -- VoiceSynthesizer --------------------------------------------------------

class VoiceSynthesizer:
    """StyleTTS2 wrapper with verification-gated output.

    Loads the model lazily on first speak() call to avoid slow startup
    when the synthesizer is instantiated but not immediately used.
    """

    def __init__(self, model_path: str | None = None) -> None:
        """Configure the synthesizer. Model loads on first use.

        Args:
            model_path: Path to a fine-tuned StyleTTS2 checkpoint.
                        None uses the default LJSpeech model.
        """
        self._model_path = model_path
        self._engine: object | None = None
        self._cached_verifier: VoiceVerifier | None = None
        self._cached_verifier_key: tuple[int, float] | None = None

    def _ensure_engine(self) -> object:
        """Lazy-load StyleTTS2 engine on first call."""
        if self._engine is not None:
            return self._engine
        from styletts2.tts import StyleTTS2

        logger.info("Loading StyleTTS2 model (path=%s)...", self._model_path or "default")
        start = time.monotonic()
        if self._model_path:
            self._engine = StyleTTS2(model_checkpoint_path=self._model_path)
        else:
            self._engine = StyleTTS2()
        elapsed = time.monotonic() - start
        logger.info("StyleTTS2 model loaded in %.1fs", elapsed)
        return self._engine

    def speak(
        self,
        text: str,
        output_path: Path,
        reference_audio: Path | None = None,
        reference_embedding: np.ndarray | None = None,
        verification_threshold: float = 0.80,
        max_attempts: int = 5,
        alpha: float = 0.3,
        beta: float = 0.7,
        diffusion_steps: int = 5,
        speed: float = 1.0,
    ) -> SpeakResult:
        """Generate speech with iterative verification.

        The verification loop:
          1. Generate audio with current parameters
          2. If reference_embedding is provided, run verification gates
          3. If verification fails, adjust parameters and retry
          4. Return best result after max_attempts

        Args:
            text: Text to synthesize.
            output_path: Where to write the final WAV file.
            reference_audio: WAV for StyleTTS2 style transfer.
            reference_embedding: ECAPA-TDNN embedding for verification.
            verification_threshold: SECS threshold for identity gate.
            max_attempts: Maximum generation attempts.
            alpha: StyleTTS2 alpha (timbre strength). Lower = closer to ref.
            beta: StyleTTS2 beta (prosody strength).
            diffusion_steps: Initial diffusion sampling steps.
            speed: Playback speed multiplier (1.0 = normal).

        Returns:
            SpeakResult with audio path and verification details.
        """
        if speed <= 0:
            raise ValueError(f"speed must be positive, got {speed}")
        engine = self._ensure_engine()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Compute style vector from reference audio
        ref_s = None
        if reference_audio is not None:
            ref_path = _resample_to_24k(reference_audio)
            ref_s = engine.compute_style(str(ref_path))  # type: ignore[union-attr]

        # Build or reuse cached verifier for the given embedding/threshold
        verifier: VoiceVerifier | None = None
        if reference_embedding is not None:
            cache_key = (id(reference_embedding), verification_threshold)
            if self._cached_verifier_key == cache_key and self._cached_verifier is not None:
                verifier = self._cached_verifier
            else:
                verifier = VoiceVerifier(
                    reference_embedding=reference_embedding,
                    threshold=verification_threshold,
                )
                self._cached_verifier = verifier
                self._cached_verifier_key = cache_key

        best_result: SpeakResult | None = None
        best_secs: float = -1.0

        for attempt_idx in range(max_attempts):
            params = _escalation_params(attempt_idx, alpha, beta)
            # Override diffusion_steps on first attempt to use caller's value
            if attempt_idx == 0:
                params["diffusion_steps"] = diffusion_steps

            torch.manual_seed(int(params["seed"]))

            # Generate audio
            wav_np: np.ndarray = engine.inference(  # type: ignore[union-attr]
                text,
                ref_s=ref_s,
                alpha=float(params["alpha"]),
                beta=float(params["beta"]),
                diffusion_steps=int(params["diffusion_steps"]),
                output_sample_rate=_TARGET_SR,
            )

            # Apply speed adjustment via resampling
            effective_sr = _TARGET_SR
            if speed != 1.0:
                effective_sr = int(_TARGET_SR * speed)

            # Write to output path
            sf.write(str(output_path), wav_np, effective_sr)
            duration_ms = int(len(wav_np) / effective_sr * 1000)

            result = SpeakResult(
                audio_path=output_path,
                duration_ms=duration_ms,
                sample_rate=effective_sr,
                verification=None,
                attempts=attempt_idx + 1,
                parameters_used=dict(params),
            )

            # No verification requested: return immediately
            if verifier is None:
                logger.info(
                    "Attempt %d/%d: generated %dms audio (no verification)",
                    attempt_idx + 1, max_attempts, duration_ms,
                )
                return result

            # Run verification
            vr = verifier.verify(
                audio_path=output_path,
                expected_text=text,
                attempt=attempt_idx + 1,
                max_attempts=max_attempts,
            )
            result.verification = vr

            logger.info(
                "Attempt %d/%d: SECS=%.2f (threshold=%.2f), gate_failed=%s%s",
                attempt_idx + 1, max_attempts, vr.secs_score,
                verification_threshold,
                vr.gate_failed or "none",
                "" if vr.passed else ", retrying...",
            )

            # Track best result by SECS score
            if vr.secs_score > best_secs:
                best_secs = vr.secs_score
                best_result = result

            if vr.passed:
                return result

        # All attempts exhausted: return the best one
        assert best_result is not None
        logger.warning(
            "Max attempts (%d) exhausted. Returning best result (SECS=%.3f)",
            max_attempts, best_secs,
        )
        return best_result
