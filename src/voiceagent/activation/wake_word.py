"""Personalized wake word detection with speaker verification.

Three-stage detection (all CPU, no GPU):
  1. Energy VAD -- detects when someone is speaking
  2. Whisper keyword check -- confirms "jarvis" is in the utterance
  3. Speaker verification -- confirms it's the owner's voice via WavLM

Only activates when ALL stages pass. The speaker centroid is calibrated
from the owner's voice recordings in ~/.voiceagent/wake_word_centroid.npz.

This replaces openwakeword which was unreliable with PulseAudio TCP mic
setups (very low gain, ~4% int16 peak). The energy VAD + whisper approach
handles any mic gain level.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from voiceagent.errors import WakeWordError

logger = logging.getLogger(__name__)

_CENTROID_PATH = Path.home() / ".voiceagent" / "wake_word_centroid.npz"
_SPEAKER_MODEL_ID = "microsoft/wavlm-base-plus-sv"

# Ring buffer: 2.5s at 16kHz for accumulating speech
_RING_BUFFER_SECONDS = 2.5
_SAMPLE_RATE = 16000
_RING_BUFFER_SAMPLES = int(_RING_BUFFER_SECONDS * _SAMPLE_RATE)

# Speech detection: RMS threshold relative to noise floor
_SPEECH_FRAMES_NEEDED = 2  # Need 2 consecutive speech frames (~40ms)
_SILENCE_FRAMES_NEEDED = 8  # 8 consecutive silence frames = end of utterance (~1.6s)


class WakeWordDetector:
    """Personalized wake word: energy VAD + whisper keyword + speaker ID.

    All processing runs on CPU. No GPU needed in DORMANT state.
    """

    def __init__(
        self,
        threshold: float = 0.3,
        speaker_threshold: float | None = None,
    ) -> None:
        self.threshold = threshold  # kept for API compat, not used internally

        # Ring buffer for accumulating speech audio
        self._ring_buffer = np.zeros(_RING_BUFFER_SAMPLES, dtype=np.int16)
        self._ring_len = 0

        # Energy VAD state
        self._noise_floor: float = 0.0
        self._noise_samples = 0
        self._speech_frame_count = 0
        self._silence_frame_count = 0
        self._in_speech = False
        self._speech_frames_total = 0  # Total frames since speech start

        # Whisper (lazy-loaded on first speech detection)
        self._whisper = None

        # Speaker verification
        self._centroid: np.ndarray | None = None
        self._speaker_threshold = 0.85
        self._speaker_model = None
        self._speaker_extractor = None

        if _CENTROID_PATH.exists():
            data = np.load(_CENTROID_PATH)
            self._centroid = data["centroid"]
            self._speaker_threshold = (
                speaker_threshold
                if speaker_threshold is not None
                else float(data.get("threshold", 0.85))
            )
            logger.info(
                "Speaker centroid loaded: dim=%d, threshold=%.3f (%d clips)",
                self._centroid.shape[0],
                self._speaker_threshold,
                int(data.get("clip_count", 0)),
            )
        else:
            logger.warning(
                "No speaker centroid at %s -- keyword-only mode (anyone can activate)",
                _CENTROID_PATH,
            )

        logger.info("Wake word detector ready (energy VAD + whisper + speaker ID)")

    def _ensure_whisper(self) -> object:
        """Lazy-load whisper base on CPU."""
        if self._whisper is not None:
            return self._whisper
        try:
            from faster_whisper import WhisperModel
            self._whisper = WhisperModel("base", device="cpu", compute_type="int8")
            logger.info("Whisper base loaded (CPU, int8)")
        except Exception as e:
            raise WakeWordError(
                f"faster-whisper required for wake word detection: {e}. "
                f"Install: pip install faster-whisper"
            ) from e
        return self._whisper

    def _ensure_speaker_model(self) -> None:
        """Lazy-load WavLM speaker encoder on CPU."""
        if self._speaker_model is not None or self._centroid is None:
            return
        try:
            from transformers import Wav2Vec2FeatureExtractor, WavLMForXVector
            self._speaker_extractor = Wav2Vec2FeatureExtractor.from_pretrained(
                _SPEAKER_MODEL_ID,
            )
            self._speaker_model = WavLMForXVector.from_pretrained(
                _SPEAKER_MODEL_ID,
            ).eval()
            logger.info("Speaker encoder loaded (CPU): %s", _SPEAKER_MODEL_ID)
        except Exception as e:
            logger.warning("Speaker encoder unavailable: %s", e)
            self._centroid = None

    def _append_ring(self, audio: np.ndarray) -> None:
        """Append audio to ring buffer, shifting if full."""
        n = len(audio)
        if self._ring_len + n <= _RING_BUFFER_SAMPLES:
            self._ring_buffer[self._ring_len:self._ring_len + n] = audio
            self._ring_len += n
        else:
            # Shift left to make room
            keep = _RING_BUFFER_SAMPLES - n
            if keep > 0:
                self._ring_buffer[:keep] = self._ring_buffer[self._ring_len - keep:self._ring_len]
            self._ring_buffer[keep:keep + n] = audio
            self._ring_len = keep + n

    def _compute_rms(self, audio: np.ndarray) -> float:
        """RMS energy of int16 audio."""
        return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))

    def _is_speech_frame(self, audio: np.ndarray) -> bool:
        """Check if this chunk contains speech based on energy."""
        rms = self._compute_rms(audio)

        # Bootstrap noise floor from first 5 quiet frames (~1s)
        if self._noise_samples < 5:
            if rms < 500:  # Quiet enough to be noise
                self._noise_floor = (
                    (self._noise_floor * self._noise_samples + rms)
                    / (self._noise_samples + 1)
                )
                self._noise_samples += 1
            return False

        # Minimum noise floor: prevents everything being "speech"
        # when bootstrap runs on pure digital silence
        if self._noise_floor < 20:
            self._noise_floor = 20.0

        # Update noise floor slowly, only from quiet frames
        if not self._in_speech and rms < self._noise_floor * 2:
            self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms

        # Speech if RMS > 4x noise floor
        speech_threshold = self._noise_floor * 4.0
        return rms > speech_threshold

    def _check_keyword(self, audio_int16: np.ndarray) -> bool:
        """Run whisper on accumulated audio to check for 'jarvis'."""
        whisper = self._ensure_whisper()

        # Convert to float32 and normalize for quiet mic input
        audio_f32 = audio_int16.astype(np.float32) / 32767.0
        peak = np.max(np.abs(audio_f32))
        if 0 < peak < 0.5:
            audio_f32 = audio_f32 / peak * 0.7  # Normalize to 70%

        try:
            segs, _ = whisper.transcribe(
                audio_f32,
                language="en",
                initial_prompt="Hey Jarvis",
            )
            text = " ".join(s.text.strip() for s in segs).lower()
        except Exception as e:
            logger.warning("Whisper transcription failed: %s", e)
            return False

        found = "jarvis" in text or "jarv" in text
        if found:
            logger.info("Keyword confirmed: '%s'", text)
        else:
            logger.info("No keyword in: '%s'", text)
        return found

    def _verify_speaker(self, audio_int16: np.ndarray) -> bool:
        """Check if audio matches the owner's voice centroid."""
        if self._centroid is None:
            return True

        self._ensure_speaker_model()
        if self._speaker_model is None:
            return True

        import torch

        audio_f32 = audio_int16.astype(np.float32) / 32767.0
        inputs = self._speaker_extractor(
            audio_f32, sampling_rate=16000, return_tensors="pt",
        )
        with torch.no_grad():
            out = self._speaker_model(**inputs)
            emb = out.embeddings.squeeze().numpy()

        emb_norm = emb / np.linalg.norm(emb)
        similarity = float(np.dot(emb_norm, self._centroid))

        passed = similarity >= self._speaker_threshold
        logger.info(
            "Speaker verify: sim=%.3f threshold=%.3f -> %s",
            similarity, self._speaker_threshold,
            "PASS" if passed else "REJECT",
        )
        return passed

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """Detect wake word in audio chunk.

        Called with each mic chunk (~200ms at 16kHz = 3200 samples).
        Returns True when "hey jarvis" is detected from the owner's voice.
        """
        if not isinstance(audio_chunk, np.ndarray):
            return False
        if audio_chunk.size == 0:
            return False
        if audio_chunk.dtype != np.int16:
            audio_chunk = audio_chunk.astype(np.int16)

        is_speech = self._is_speech_frame(audio_chunk)

        if is_speech:
            self._speech_frame_count += 1
            self._silence_frame_count = 0

            if not self._in_speech and self._speech_frame_count >= _SPEECH_FRAMES_NEEDED:
                self._in_speech = True
                self._ring_len = 0
                self._speech_frames_total = 0
                logger.debug("Speech started")

            if self._in_speech:
                self._append_ring(audio_chunk)
                self._speech_frames_total += 1
        else:
            self._silence_frame_count += 1
            self._speech_frame_count = 0

            if self._in_speech:
                self._append_ring(audio_chunk)
                self._speech_frames_total += 1

        # Evaluate utterance when:
        # 1. Silence after speech (normal end), OR
        # 2. Speech has been going for 2s+ (max duration timeout)
        should_evaluate = False
        if self._in_speech and self._silence_frame_count >= _SILENCE_FRAMES_NEEDED:
            should_evaluate = True
            self._in_speech = False
        elif self._in_speech and self._speech_frames_total >= 12:
            # ~2.4s at 200ms/chunk -- force evaluate even without silence
            should_evaluate = True
            self._in_speech = False

        if not should_evaluate:
            return False

        utterance = self._ring_buffer[:self._ring_len].copy()
        self._speech_frames_total = 0

        if len(utterance) < 6400:  # < 400ms -- too short
            logger.debug("Utterance too short (%dms)", len(utterance) // 16)
            return False

        logger.info("Evaluating utterance: %dms", len(utterance) // 16)

        # Stage 2: Keyword check via whisper
        if not self._check_keyword(utterance):
            return False

        # Stage 3: Speaker verification
        if not self._verify_speaker(utterance):
            return False

        logger.info("WAKE WORD ACTIVATED")
        return True
