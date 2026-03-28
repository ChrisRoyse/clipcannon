"""ClipCannon voice synthesis adapter for the voice agent.

Wraps ClipCannon's VoiceSynthesizer for real-time TTS.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from voiceagent.errors import TTSError

logger = logging.getLogger(__name__)


class ClipCannonAdapter:
    """Adapter that bridges ClipCannon's VoiceSynthesizer into the voice agent.

    Loads a voice profile from the ClipCannon profile DB, locates reference
    audio on disk, and exposes an async ``synthesize`` method that returns
    24 kHz float32 numpy audio.
    """

    DEFAULT_DB: str = "~/.clipcannon/voice_profiles.db"
    VOICE_DATA_DIR: str = "~/.clipcannon/voice_data"

    def __init__(self, voice_name: str = "boris", db_path: str | None = None) -> None:
        self._voice_name = voice_name
        db = str(Path(db_path or self.DEFAULT_DB).expanduser())

        # -- load profile ---------------------------------------------------
        from clipcannon.voice.profiles import get_voice_profile

        self._profile = get_voice_profile(db, voice_name)
        if self._profile is None:
            raise TTSError(
                f"Voice profile '{voice_name}' not found in {db}. "
                f"Create it with: clipcannon voice profile create {voice_name}"
            )
        logger.info("Loaded voice profile '%s'", voice_name)

        # -- reference audio ------------------------------------------------
        voice_wavs_dir = Path(self.VOICE_DATA_DIR).expanduser() / voice_name / "wavs"
        self._reference_audio = self._find_reference_audio(voice_wavs_dir)

        # -- reference embedding (BLOB -> float32 ndarray) ------------------
        self._reference_embedding: np.ndarray | None = None
        raw = self._profile.get("reference_embedding")
        if raw is not None and len(raw) > 0:
            self._reference_embedding = np.frombuffer(raw, dtype=np.float32).copy()
            logger.info(
                "Reference embedding: shape=%s", self._reference_embedding.shape
            )

        # -- verification threshold -----------------------------------------
        self._verification_threshold = float(
            self._profile.get("verification_threshold", 0.80)
        )

        # -- synthesizer ----------------------------------------------------
        from clipcannon.voice.inference import VoiceSynthesizer

        self._synth = VoiceSynthesizer()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_reference_audio(wavs_dir: Path) -> Path:
        """Return the first .wav file in *wavs_dir*."""
        if not wavs_dir.is_dir():
            raise TTSError(f"Voice data directory not found: {wavs_dir}")
        wav_files = sorted(wavs_dir.glob("*.wav"))
        if not wav_files:
            raise TTSError(f"No .wav files in {wavs_dir}")
        logger.info("Using reference audio: %s", wav_files[0])
        return wav_files[0]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(self, text: str) -> np.ndarray:
        """Synthesize *text* and return 24 kHz float32 mono audio.

        Raises ``TTSError`` on failure or empty input.
        """
        if not text or not text.strip():
            raise TTSError("Cannot synthesize empty text.")

        tmp_path = Path(tempfile.mktemp(suffix=".wav"))
        try:
            result = await asyncio.to_thread(
                self._synth.speak,
                text=text,
                output_path=tmp_path,
                reference_audio=self._reference_audio,
                reference_embedding=self._reference_embedding,
                verification_threshold=self._verification_threshold,
                max_attempts=1,
                speed=1.0,
            )

            if not result.audio_path.exists():
                raise TTSError(
                    f"speak() audio_path {result.audio_path} does not exist"
                )

            audio, _sr = sf.read(str(result.audio_path), dtype="float32")
            logger.info(
                "Synthesized '%s': %dms, %d samples",
                text[:50],
                result.duration_ms,
                len(audio),
            )
            return audio

        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(
                f"Synthesis failed for '{text[:80]}': {exc}"
            ) from exc
        finally:
            if tmp_path.exists():
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def release(self) -> None:
        """Release GPU resources held by the underlying synthesizer."""
        if hasattr(self, "_synth") and self._synth is not None:
            self._synth.release()
            logger.info("Released VoiceSynthesizer")
