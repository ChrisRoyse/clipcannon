"""Reference-voice lookup and output trimming for the fast TTS adapter.

Split out of ``voiceagent.adapters.fast_tts`` (pure move): the reference
clip / transcript lookup and trailing-silence trimming that
``FastTTSAdapter`` inherits from ``_VoiceReferenceMixin``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class _VoiceReferenceMixin:
    """Reference audio / text lookup and trailing-silence trimming."""

    def _find_reference_with_text(
        self,
        voice_name: str,
        db_path: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Find reference audio and transcribe for Full ICL mode.

        Returns:
            Tuple of (ref_audio_path, ref_text). ref_text may be None
            if transcription fails, in which case xvec_only mode is used.
        """
        # 1. Check real mic overrides (much better than Demucs clips)
        override = self.REAL_MIC_OVERRIDES.get(voice_name)
        if override:
            expanded = str(Path(override).expanduser())
            if Path(expanded).exists():
                logger.info("Using real mic override for %s", voice_name)
                ref_text = self._transcribe(expanded)
                return expanded, ref_text

        # 2. Try voice profiles DB for training project vocals
        db = str(Path(db_path or self.DEFAULT_DB).expanduser())
        try:
            from clipcannon.voice.profiles import get_voice_profile
            profile = get_voice_profile(db, voice_name)
        except (ImportError, OSError, KeyError) as e:
            logger.debug("Voice profile lookup failed for %s: %s", voice_name, e)
            profile = None

        if profile:
            training_raw = profile.get("training_projects", "[]")
            try:
                if isinstance(training_raw, str):
                    proj_ids = json.loads(training_raw)
                elif isinstance(training_raw, list):
                    proj_ids = training_raw
                else:
                    proj_ids = []
            except (json.JSONDecodeError, TypeError):
                proj_ids = []

            projects_dir = Path(self.PROJECTS_DIR).expanduser()
            for pid in proj_ids:
                vocals = projects_dir / pid / "stems" / "vocals.wav"
                if vocals.exists():
                    ref_text = self._transcribe(str(vocals))
                    return str(vocals), ref_text

        # 3. Fallback: first clip from voice_data
        wavs_dir = (
            Path(self.VOICE_DATA_DIR).expanduser()
            / voice_name / "wavs"
        )
        if wavs_dir.is_dir():
            clips = sorted(wavs_dir.glob("*.wav"))
            if clips:
                ref_text = self._transcribe(str(clips[0]))
                return str(clips[0]), ref_text

        return None, None

    @staticmethod
    def _transcribe(audio_path: str) -> str | None:
        """Transcribe reference audio for Full ICL ref_text."""
        try:
            from faster_whisper import WhisperModel
            whisper = WhisperModel("base", device="cpu", compute_type="int8")
            segs, _ = whisper.transcribe(audio_path, language="en")
            text = " ".join(s.text.strip() for s in segs)
            logger.info("Transcribed ref (%d chars): %s...", len(text), text[:60])
            return text if text.strip() else None
        except (ImportError, OSError, RuntimeError) as e:
            logger.warning("Transcription failed for %s: %s", audio_path, e)
            return None

    @staticmethod
    def _trim_silence(audio: np.ndarray, sr: int = 24000) -> np.ndarray:
        """Trim trailing silence and degraded audio from TTS output.

        Two-pass trimming:
        1. Forward pass: find where speech energy drops significantly
           compared to the peak energy (catches garbled/degraded tail)
        2. Backward pass: find last non-silent window (catches silence)

        This prevents both:
        - Silence padding (model generates tokens past EOS)
        - Voice quality degradation (model output becomes generic/garbled)
        """
        if len(audio) == 0:
            return audio

        window = int(sr * 0.1)  # 100ms windows
        silence_threshold = 0.003

        # Forward pass: compute energy per window, find where it drops
        energies = []
        for i in range(0, len(audio) - window, window):
            chunk = audio[i : i + window]
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            energies.append(rms)

        if not energies:
            return audio

        # Find the peak energy in the first half (where real speech is)
        half = max(1, len(energies) // 2)
        peak_energy = max(energies[:half]) if any(e > 0 for e in energies[:half]) else 0.01

        # Find where energy drops below 10% of peak for 3+ consecutive windows
        # This catches the transition from real speech to garbled/degraded output
        cutoff_window = len(energies)
        consecutive_low = 0
        for i, e in enumerate(energies):
            if e < peak_energy * 0.1:
                consecutive_low += 1
                if consecutive_low >= 3:
                    cutoff_window = i - 2  # Back up to start of low region
                    break
            else:
                consecutive_low = 0

        # Backward pass: from cutoff, find last non-silent window
        last_speech = cutoff_window * window
        for i in range(min(cutoff_window, len(energies)) - 1, -1, -1):
            if energies[i] > silence_threshold:
                last_speech = (i + 1) * window + int(sr * 0.15)  # 150ms pad
                break

        last_speech = min(last_speech, len(audio))
        # Safety: never trim to less than 0.5s — return original if trim is too aggressive
        min_samples = int(sr * 0.5)
        if last_speech < min_samples:
            return audio
        if last_speech < len(audio):
            audio = audio[:last_speech]
            # Gentle 50ms fade-out
            fade_len = min(int(sr * 0.05), len(audio))
            if fade_len > 0:
                fade = np.linspace(1.0, 0.0, fade_len)
                audio[-fade_len:] *= fade

        return audio
