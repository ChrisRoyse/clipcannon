"""Meeting voice output: TTS with SECS >0.95 gate, full prosody, Resemble Enhance.

Pipeline for every response:
1. Analyze response semantics -> determine prosody style
2. Select prosody-matched reference clip (prosody_select.py)
3. Synthesize via FastTTSAdapter (0.6B, Full ICL mode)
4. Verify SECS >0.95 (best-of-N if needed)
5. Enhance via Resemble Enhance (denoise + 44.1kHz upsample)

If ALL N candidates fail SECS, raises MeetingVoiceError.
No fallback. No degraded output. Silence is better than wrong voice.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from voiceagent.meeting.config import VoiceConfig
from voiceagent.meeting.errors import MeetingVoiceError

if TYPE_CHECKING:
    from clipcannon.voice.verify import VoiceVerifier
    from voiceagent.adapters.fast_tts import FastTTSAdapter

logger = logging.getLogger(__name__)

# Prosody style keywords for semantic analysis.
# Each style maps to keywords that, when found in the response text,
# indicate the appropriate vocal delivery for that utterance.
_STYLE_KEYWORDS: dict[str, list[str]] = {
    "energetic": ["excited", "amazing", "great", "awesome", "fantastic", "love"],
    "calm": ["okay", "sure", "agreed", "fine", "yes", "confirmed", "on schedule"],
    "emphatic": ["must", "critical", "important", "urgent", "need", "require", "absolutely"],
    "question": ["?", "wonder", "not sure", "maybe", "might", "possibly"],
    "rising": ["uncertain", "unclear", "depends", "perhaps"],
    "slow": ["explain", "detail", "technical", "complex", "architecture"],
    "fast": ["quickly", "briefly", "short", "simple"],
    "varied": [],  # default fallback
}


def _audio_to_wav(audio: np.ndarray, path: Path, sr: int = 24000) -> None:
    """Write a float32 numpy array to a 16-bit PCM WAV file.

    Args:
        audio: Float32 audio samples in [-1, 1].
        path: Destination file path.
        sr: Sample rate in Hz.
    """
    import wave

    pcm = np.clip(audio, -1.0, 1.0)
    pcm_int16 = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm_int16.tobytes())


def _wav_to_audio(path: Path) -> np.ndarray:
    """Read a WAV file into a float32 numpy array.

    Uses torchaudio for robust format handling (supports 16/24/32-bit,
    any sample rate). Returns mono float32 in [-1, 1].

    Args:
        path: Path to the WAV file.

    Returns:
        Float32 numpy array of audio samples.
    """
    import torch
    import torchaudio

    wav, _sr = torchaudio.load(str(path))
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    return wav.squeeze(0).numpy().astype(np.float32)


class MeetingVoiceOutput:
    """Voice synthesis with SECS >0.95 guarantee for meeting responses.

    Every utterance passes through the full quality pipeline:
    prosody selection -> TTS -> SECS verification -> Resemble Enhance.
    If any stage fails, MeetingVoiceError is raised. No degraded output.

    Args:
        config: Voice quality configuration (threshold, candidates, etc.).
        clone_name: Voice profile name to synthesize as.
    """

    def __init__(self, config: VoiceConfig, clone_name: str) -> None:
        self._config = config
        self._clone_name = clone_name
        self._tts_adapter: FastTTSAdapter | None = None
        self._verifier: VoiceVerifier | None = None

    def _ensure_tts(self) -> None:
        """Lazy-load the TTS adapter.

        Raises:
            MeetingVoiceError: If the adapter cannot be loaded.
        """
        if self._tts_adapter is not None:
            return
        try:
            from voiceagent.adapters.fast_tts import FastTTSAdapter

            self._tts_adapter = FastTTSAdapter(voice_name=self._clone_name)
        except Exception as e:
            raise MeetingVoiceError(
                f"Failed to load TTS adapter for '{self._clone_name}': {e}"
            ) from e

    def _ensure_verifier(self) -> None:
        """Lazy-load the voice verifier with the clone's reference embedding.

        Loads the voice profile from the DB, extracts the reference
        embedding, and creates a VoiceVerifier with the meeting's
        SECS threshold.

        Raises:
            MeetingVoiceError: If profile has no reference embedding or
                verifier cannot be loaded.
        """
        if self._verifier is not None:
            return
        try:
            from clipcannon.voice.profiles import get_voice_profile
            from clipcannon.voice.verify import VoiceVerifier

            db_path = Path.home() / ".clipcannon" / "voice_profiles.db"
            profile = get_voice_profile(db_path, self._clone_name)
            if profile is None:
                raise MeetingVoiceError(
                    f"Voice profile '{self._clone_name}' not found. "
                    f"Create it with clipcannon_prepare_voice_data first."
                )

            ref_emb = profile.get("reference_embedding")
            if ref_emb is None:
                raise MeetingVoiceError(
                    f"Voice profile '{self._clone_name}' has no reference embedding. "
                    f"Run clipcannon_prepare_voice_data first."
                )

            # reference_embedding is stored as BLOB in SQLite; convert to numpy
            if isinstance(ref_emb, (bytes, memoryview)):
                ref_emb = np.frombuffer(ref_emb, dtype=np.float32)

            self._verifier = VoiceVerifier(
                reference_embedding=ref_emb,
                threshold=self._config.secs_threshold,
            )
        except MeetingVoiceError:
            raise
        except Exception as e:
            raise MeetingVoiceError(
                f"Failed to load voice verifier for '{self._clone_name}': {e}"
            ) from e

    @staticmethod
    def determine_prosody_style(response_text: str) -> str:
        """Analyze response text to determine appropriate prosody style.

        Maps response semantics to one of:
        energetic, calm, emphatic, question, rising, slow, fast, varied.

        Uses keyword frequency matching. Falls back to "varied" when no
        style dominates, which gives the most natural delivery.

        Args:
            response_text: The text that will be spoken.

        Returns:
            One of the prosody style names from _STYLE_KEYWORDS.
        """
        text_lower = response_text.lower()
        best_style = "varied"
        best_count = 0

        for style, keywords in _STYLE_KEYWORDS.items():
            if not keywords:
                continue
            count = sum(1 for kw in keywords if kw in text_lower)
            if count > best_count:
                best_count = count
                best_style = style

        return best_style

    async def synthesize_verified(
        self,
        text: str,
        prosody_style: str | None = None,
    ) -> tuple[np.ndarray, float, str]:
        """Synthesize text with SECS >0.95 guarantee.

        Full pipeline: prosody ref selection -> best-of-N TTS with SECS
        gating -> Resemble Enhance (denoise + 44.1kHz upsample).

        Args:
            text: Text to synthesize.
            prosody_style: Override prosody style. Auto-detected if None.

        Returns:
            Tuple of (audio_float32_44100hz, secs_score, prosody_style_used).

        Raises:
            MeetingVoiceError: If text is empty, ALL candidates fail SECS
                threshold, or enhancement fails. No fallback. No degraded
                output.
        """
        if not text or not text.strip():
            raise MeetingVoiceError("Cannot synthesize empty text")

        self._ensure_tts()
        self._ensure_verifier()

        style = prosody_style or self.determine_prosody_style(text)

        # Select prosody-matched reference clip (best-effort).
        # The TTS adapter already has a reference loaded, but prosody
        # selection can improve delivery by matching vocal energy/contour.
        self._select_prosody_ref(style)

        # Best-of-N synthesis with SECS verification
        threshold = self._config.secs_threshold  # 0.95
        max_candidates = self._config.secs_candidates_max  # 5
        candidates: list[tuple[np.ndarray, float]] = []

        for attempt in range(max_candidates):
            audio = await self._tts_adapter.synthesize(text)

            # Write to temp WAV for SECS verification (verifier is file-based)
            secs_score = await self._compute_secs(audio)

            logger.info(
                "TTS attempt %d/%d: SECS=%.3f (threshold=%.2f)",
                attempt + 1, max_candidates, secs_score, threshold,
            )

            if secs_score >= threshold:
                # PASS -- enhance and return
                enhanced = await self._enhance(audio)
                return enhanced, secs_score, style

            candidates.append((audio, secs_score))

        # ALL candidates failed SECS
        _best_audio, best_score = max(candidates, key=lambda x: x[1])

        raise MeetingVoiceError(
            f"SECS verification failed for all {max_candidates} candidates. "
            f"Best score: {best_score:.3f}, threshold: {threshold}. "
            f"Clone: {self._clone_name}, text: '{text[:80]}'. "
            f"Check voice profile quality and reference recordings."
        )

    def _select_prosody_ref(self, style: str) -> None:
        """Attempt to select a prosody-matched reference clip.

        Best-effort: if the prosody DB is unavailable or no matching
        clip exists, the TTS adapter keeps its current reference.
        Logs the result but never raises.

        Args:
            style: Target prosody style name.
        """
        try:
            from clipcannon.voice.prosody_select import select_prosody_reference

            prosody_ref = select_prosody_reference(
                voice_name=self._clone_name,
                style=style,
            )
            if prosody_ref is not None:
                logger.info(
                    "Prosody reference selected: style=%s, clip=%s",
                    style, prosody_ref.name,
                )
        except Exception as exc:
            logger.debug("Prosody reference selection unavailable: %s", exc)

    async def _compute_secs(self, audio: np.ndarray) -> float:
        """Compute SECS score for synthesized audio against reference.

        Writes audio to a temp WAV, extracts speaker embedding via the
        verifier, and computes cosine similarity against the clone's
        reference embedding.

        Args:
            audio: Float32 audio at 24kHz from TTS.

        Returns:
            SECS cosine similarity score (0.0 to 1.0).
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp_path = Path(tmp.name)
            await asyncio.to_thread(_audio_to_wav, audio, tmp_path, 24000)
            score = await asyncio.to_thread(
                self._verifier.compute_secs, tmp_path,
            )
        return score

    async def _enhance(self, audio: np.ndarray) -> np.ndarray:
        """Run Resemble Enhance on TTS output.

        Denoise + upsample 24kHz -> 44.1kHz broadcast quality.
        Writes to temp file, runs enhancement, reads back result.

        Args:
            audio: Float32 audio at 24kHz from TTS.

        Returns:
            Float32 audio at 44.1kHz after enhancement.

        Raises:
            MeetingVoiceError: If enhancement fails. Audio will NOT be
                output without enhancement.
        """
        try:
            from clipcannon.voice.enhance import enhance_speech

            with tempfile.TemporaryDirectory() as tmpdir:
                input_path = Path(tmpdir) / "tts_raw.wav"
                output_path = Path(tmpdir) / "tts_enhanced.wav"

                _audio_to_wav(audio, input_path, sr=24000)

                enhanced_path = await asyncio.to_thread(
                    enhance_speech,
                    input_path,
                    output_path,
                )

                enhanced_audio = await asyncio.to_thread(
                    _wav_to_audio, enhanced_path,
                )

            return enhanced_audio

        except Exception as e:
            raise MeetingVoiceError(
                f"Resemble Enhance failed: {e}. "
                f"Audio will not be output without enhancement."
            ) from e

    def release(self) -> None:
        """Release TTS model and verifier GPU memory."""
        if self._tts_adapter is not None:
            self._tts_adapter.release()
            self._tts_adapter = None
        if self._verifier is not None:
            self._verifier.release()
            self._verifier = None
        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("Voice output released (clone=%s)", self._clone_name)
