"""ClipCannon voice synthesis adapter for the voice agent.

Uses the SAME approach as ClipCannon's own speak tool:
  1. Reference audio from vocal stems (training projects), NOT short clips
  2. x_vector_only mode (embedding carries identity, vocal stem carries style)
  3. Speaker embedding verification for identity gating
  4. Optional enhancement via Resemble Enhance (removes metallic artifacts)

For real-time voice agent use: max_attempts=1, no enhancement (speed).
For high-quality: max_attempts=5, enhancement on.
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from voiceagent.errors import TTSError

logger = logging.getLogger(__name__)


class ClipCannonAdapter:
    """Voice synthesis using ClipCannon's proven voice cloning pipeline."""

    DEFAULT_DB: str = "~/.clipcannon/voice_profiles.db"
    PROJECTS_DIR: str = "~/.clipcannon/projects"
    VOICE_DATA_DIR: str = "~/.clipcannon/voice_data"

    def __init__(
        self,
        voice_name: str = "boris",
        db_path: str | None = None,
        enhance: bool = False,
        max_attempts: int = 1,
    ) -> None:
        self._voice_name = voice_name
        self._enhance = enhance
        self._max_attempts = max_attempts
        db = str(Path(db_path or self.DEFAULT_DB).expanduser())

        # Load profile (same as ClipCannon's resolve_voice_profile)
        from clipcannon.voice.profiles import get_voice_profile

        self._profile = get_voice_profile(db, voice_name)
        if self._profile is None:
            raise TTSError(
                f"Voice profile '{voice_name}' not found in {db}."
            )

        # Reference embedding (2048-dim speaker encoder)
        self._reference_embedding: np.ndarray | None = None
        raw = self._profile.get("reference_embedding")
        if raw is not None and len(raw) > 0:
            self._reference_embedding = np.frombuffer(
                raw, dtype=np.float32,
            ).copy()

        # Verification threshold
        self._verification_threshold = float(
            self._profile.get("verification_threshold", 0.80)
        )

        # Find reference audio -- SAME logic as ClipCannon's tools:
        # First try vocal stems from training projects, then fall
        # back to clips in voice_data/wavs/
        self._reference_audio = self._find_reference_audio()

        logger.info(
            "ClipCannonAdapter: voice=%s, ref=%s, "
            "embedding=%s, threshold=%.2f, enhance=%s",
            voice_name,
            self._reference_audio.name if self._reference_audio else "None",
            self._reference_embedding.shape if self._reference_embedding is not None else "None",
            self._verification_threshold,
            enhance,
        )

        # Synthesizer (lazy-loads Qwen3-TTS on first speak)
        from clipcannon.voice.inference import VoiceSynthesizer

        self._synth = VoiceSynthesizer()

    def _find_reference_audio(self) -> Path | None:
        """Find reference audio using ClipCannon's own resolution order.

        1. Vocal stems from training projects (best quality)
        2. WAV clips in voice_data/{name}/wavs/ (fallback)
        """
        # Try vocal stems first
        training_projects_raw = self._profile.get(
            "training_projects", "[]",
        )
        try:
            proj_ids = (
                json.loads(training_projects_raw)
                if isinstance(training_projects_raw, str)
                else []
            )
        except (json.JSONDecodeError, TypeError):
            proj_ids = []

        projects_dir = Path(self.PROJECTS_DIR).expanduser()
        for pid in proj_ids:
            vocals = projects_dir / pid / "stems" / "vocals.wav"
            if vocals.exists():
                logger.info(
                    "Using vocal stem: %s/%s",
                    pid, "stems/vocals.wav",
                )
                return vocals

        # Fallback: clips in voice_data
        wavs_dir = (
            Path(self.VOICE_DATA_DIR).expanduser()
            / self._voice_name / "wavs"
        )
        if wavs_dir.is_dir():
            clips = sorted(wavs_dir.glob("*.wav"))
            if clips:
                logger.info(
                    "Using voice data clip: %s", clips[0].name,
                )
                return clips[0]

        logger.warning("No reference audio found for %s", self._voice_name)
        return None

    async def synthesize(self, text: str) -> np.ndarray:
        """Synthesize text to float32 audio array.

        Uses the same pipeline as ClipCannon's speak tool:
        reference_audio (vocal stem) + reference_embedding +
        x_vector_only mode (no reference_text).
        """
        if not text or not text.strip():
            raise TTSError("Cannot synthesize empty text.")

        tmp_path = Path(tempfile.mktemp(suffix=".wav"))
        try:
            # Call speak() exactly like ClipCannon's own tool does:
            # - reference_audio = vocal stem
            # - reference_text = None (x_vector_only mode)
            # - reference_embedding for verification gating
            result = await asyncio.to_thread(
                self._synth.speak,
                text=text,
                output_path=tmp_path,
                reference_audio=self._reference_audio,
                reference_text=None,  # x_vector_only
                reference_embedding=self._reference_embedding,
                verification_threshold=self._verification_threshold,
                max_attempts=self._max_attempts,
                speed=1.0,
            )

            final_path = result.audio_path

            # Enhancement (removes metallic vocoder artifacts)
            if self._enhance:
                enhanced_path = Path(
                    tempfile.mktemp(suffix="_enhanced.wav"),
                )
                try:
                    from clipcannon.voice.enhance import enhance_speech

                    await asyncio.to_thread(
                        enhance_speech,
                        result.audio_path,
                        enhanced_path,
                    )
                    final_path = enhanced_path
                except Exception as e:
                    logger.warning(
                        "Enhancement failed, using raw: %s", e,
                    )

            if not final_path.exists():
                raise TTSError(
                    f"Output file missing: {final_path}"
                )

            audio, sr = sf.read(str(final_path), dtype="float32")
            logger.info(
                "Synthesized '%s': %dms, sr=%d, attempts=%d, "
                "SECS=%s, enhanced=%s",
                text[:40],
                result.duration_ms,
                sr,
                result.attempts,
                (
                    f"{result.verification.secs_score:.3f}"
                    if result.verification
                    else "n/a"
                ),
                self._enhance and final_path != result.audio_path,
            )
            return audio

        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(
                f"Synthesis failed for '{text[:80]}': {exc}"
            ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    def release(self) -> None:
        """Release GPU resources."""
        if hasattr(self, "_synth") and self._synth is not None:
            self._synth.release()
            logger.info("Released VoiceSynthesizer")
