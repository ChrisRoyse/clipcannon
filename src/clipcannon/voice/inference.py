"""Qwen3-TTS voice synthesis with iterative verification loop.

Wraps the Qwen3-TTS-12Hz-1.7B-Base model for voice cloning with
speaker encoder verification gating. Uses SDPA attention backend
optimized for RTX 5090 Blackwell (compute cap 12.0) with BF16 precision.

Key features:
  - Voice cloning via reference audio (10-15s clip + transcript)
  - x_vector_only mode for embedding-only cloning (no ref text needed)
  - create_voice_clone_prompt for reusable speaker prompts
  - Multi-reference averaging via speaker embeddings
  - max_new_tokens controls generation length (prevents runaway)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from clipcannon.voice.verify import VerificationResult, VoiceVerifier

logger = logging.getLogger(__name__)

# Qwen3-TTS outputs at 24kHz
_OUTPUT_SR = 24000

# Max reference audio duration (seconds) — longer causes runaway generation
_MAX_REF_DURATION_S = 15.0

# HuggingFace model ID
_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"


@dataclass
class SpeakResult:
    """Result of a speak() call with optional verification."""

    audio_path: Path
    duration_ms: int
    sample_rate: int
    verification: VerificationResult | None
    attempts: int
    parameters_used: dict[str, object] = field(default_factory=dict)


def _trim_reference(audio_path: Path, max_duration_s: float = _MAX_REF_DURATION_S) -> Path:
    """Preprocess reference audio for optimal voice cloning.

    Steps:
      1. Convert to mono
      2. Trim leading/trailing silence (energy-based)
      3. Truncate to max duration (prevents runaway generation)
      4. Peak normalize to -1dB (consistent input level)

    Args:
        audio_path: Path to reference WAV.
        max_duration_s: Maximum duration in seconds.

    Returns:
        Original path if no changes needed, or path to preprocessed copy.
    """
    import torchaudio

    wav, sr = torchaudio.load(str(audio_path))

    # Mono
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)

    # Trim silence from ends
    energy = wav.abs().squeeze()
    threshold = energy.max() * 0.02
    active = (energy > threshold).nonzero(as_tuple=True)[0]
    if len(active) > 0:
        pad = int(0.05 * sr)  # 50ms padding
        start = max(0, active[0].item() - pad)
        end = min(wav.shape[-1], active[-1].item() + int(0.3 * sr))
        wav = wav[:, start:end]

    # Truncate to max duration
    max_samples = int(max_duration_s * sr)
    if wav.shape[-1] > max_samples:
        wav = wav[:, :max_samples]

    # Peak normalize to -1dB
    peak = wav.abs().max()
    if peak > 0:
        target = 10 ** (-1.0 / 20)
        wav = wav * (target / peak)

    # Only save if something changed
    original_wav, _ = torchaudio.load(str(audio_path))
    if wav.shape != original_wav.shape or not torch.allclose(wav, original_wav[:1, :wav.shape[-1]], atol=1e-4):
        trimmed = audio_path.parent / f"{audio_path.stem}_trimmed.wav"
        torchaudio.save(str(trimmed), wav, sr)
        logger.info(
            "Preprocessed reference %s: %.1fs, normalized",
            audio_path.name, wav.shape[-1] / sr,
        )
        return trimmed

    return audio_path


class VoiceSynthesizer:
    """Qwen3-TTS voice cloning engine with verification gating.

    Loads the model lazily on first speak() call. Uses SDPA attention
    backend (optimal for RTX 5090 Blackwell without flash-attn).
    All inference in BF16 for maximum Tensor Core utilization.
    """

    def __init__(self, model_id: str = _MODEL_ID) -> None:
        """Configure the synthesizer. Model loads on first use.

        Args:
            model_id: HuggingFace model ID or local path.
        """
        self._model_id = model_id
        self._engine: object | None = None
        self._cached_prompt: object | None = None
        self._cached_prompt_key: str | None = None
        self._cached_verifier: VoiceVerifier | None = None
        self._cached_verifier_key: tuple[int, float] | None = None

    def release(self) -> None:
        """Release GPU memory held by the engine.

        Call when the synthesizer is no longer needed to prevent
        VRAM leaks on WSL2.
        """
        import gc
        if self._engine is not None:
            del self._engine
            self._engine = None
        self._cached_prompt = None
        self._cached_verifier = None
        gc.collect()
        torch.cuda.empty_cache()
        logger.info("VoiceSynthesizer released GPU memory")

    def _ensure_engine(self) -> object:
        """Lazy-load Qwen3-TTS model on first call."""
        if self._engine is not None:
            return self._engine

        # RTX 5090 Blackwell optimizations
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
        torch.set_float32_matmul_precision("high")

        from qwen_tts import Qwen3TTSModel

        logger.info("Loading Qwen3-TTS model: %s ...", self._model_id)
        start = time.monotonic()

        self._engine = Qwen3TTSModel.from_pretrained(
            self._model_id,
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )

        elapsed = time.monotonic() - start
        logger.info(
            "Qwen3-TTS loaded in %.1fs, VRAM: %.2fGB",
            elapsed, torch.cuda.memory_allocated() / 1024**3,
        )
        return self._engine

    def _get_or_create_prompt(
        self,
        ref_audio: Path,
        ref_text: str | None = None,
    ) -> object:
        """Get or create a cached voice clone prompt.

        Caches the prompt so repeated calls with the same reference
        don't recompute speaker embeddings and codec tokens.

        Args:
            ref_audio: Path to reference audio (10-15s max).
            ref_text: Transcript of reference audio. If None, uses
                     x_vector_only_mode (embedding only, no ICL).

        Returns:
            VoiceClonePromptItem for generate_voice_clone.
        """
        cache_key = f"{ref_audio}:{ref_text or 'xvec'}"
        if self._cached_prompt_key == cache_key and self._cached_prompt is not None:
            return self._cached_prompt

        engine = self._ensure_engine()

        # Trim reference if too long
        ref_path = _trim_reference(ref_audio)
        use_xvec = ref_text is None

        logger.info(
            "Creating voice clone prompt: ref=%s, x_vector_only=%s",
            ref_path.name, use_xvec,
        )

        items = engine.create_voice_clone_prompt(  # type: ignore[union-attr]
            ref_audio=str(ref_path),
            ref_text=ref_text if not use_xvec else None,
            x_vector_only_mode=use_xvec,
        )

        self._cached_prompt = items
        self._cached_prompt_key = cache_key
        return items

    def speak(
        self,
        text: str,
        output_path: Path,
        reference_audio: Path | None = None,
        reference_text: str | None = None,
        reference_embedding: np.ndarray | None = None,
        verification_threshold: float = 0.80,
        max_attempts: int = 5,
        temperature: float = 0.5,
        max_new_tokens: int = 2048,
        speed: float = 1.0,
    ) -> SpeakResult:
        """Generate speech with iterative verification.

        Args:
            text: Text to synthesize.
            output_path: Where to write the final WAV file.
            reference_audio: WAV clip of the target speaker (10-15s).
            reference_text: Transcript of the reference audio.
            reference_embedding: Speaker encoder embedding for
                identity verification (cosine similarity gate).
            verification_threshold: SECS threshold for identity gate.
            max_attempts: Maximum generation attempts (best-of-N).
            temperature: Sampling temperature (0.5 = optimal for speaker
                identity preservation with Full ICL mode).
            max_new_tokens: Max generation tokens (2048 = ~170s audio).
            speed: Playback speed multiplier.

        Returns:
            SpeakResult with audio path and verification details.
        """
        if speed <= 0:
            raise ValueError(f"speed must be positive, got {speed}")

        engine = self._ensure_engine()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build voice clone prompt from reference audio
        prompt = None
        if reference_audio is not None:
            prompt = self._get_or_create_prompt(reference_audio, reference_text)

        # Build or reuse cached verifier
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
            seed = int(torch.randint(0, 2**31, (1,)).item())
            torch.manual_seed(seed)

            params = {
                "temperature": temperature,
                "max_new_tokens": max_new_tokens,
                "seed": seed,
            }

            logger.info(
                "Attempt %d/%d: temp=%.1f, max_tokens=%d, seed=%d",
                attempt_idx + 1, max_attempts, temperature, max_new_tokens, seed,
            )

            # Generate voice clone
            if prompt is None:
                raise ValueError(
                    "Qwen3-TTS requires a reference audio clip for voice cloning. "
                    "Provide reference_audio when calling speak()."
                )

            wavs, sr = engine.generate_voice_clone(  # type: ignore[union-attr]
                text=text,
                language="English",
                voice_clone_prompt=prompt,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=0.85,
                repetition_penalty=1.05,
            )

            wav_np = wavs[0] if isinstance(wavs[0], np.ndarray) else wavs[0].cpu().numpy()

            # Apply speed adjustment
            effective_sr = sr
            if speed != 1.0:
                effective_sr = int(sr * speed)

            # Write output
            sf.write(str(output_path), wav_np, effective_sr)
            duration_ms = int(len(wav_np) / effective_sr * 1000)

            result = SpeakResult(
                audio_path=output_path,
                duration_ms=duration_ms,
                sample_rate=effective_sr,
                verification=None,
                attempts=attempt_idx + 1,
                parameters_used=params,
            )

            # No verification: return first result
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
                "Attempt %d/%d: SECS=%.3f (threshold=%.2f), gate=%s%s",
                attempt_idx + 1, max_attempts, vr.secs_score,
                verification_threshold,
                vr.gate_failed or "pass",
                "" if vr.passed else ", retrying...",
            )

            if vr.secs_score > best_secs:
                best_secs = vr.secs_score
                best_result = result

            if vr.passed:
                return result

        assert best_result is not None
        logger.warning(
            "Max attempts (%d) exhausted. Best SECS=%.3f",
            max_attempts, best_secs,
        )
        return best_result
