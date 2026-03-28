"""Silero VAD v5 wrapper for real-time voice activity detection.

Silero VAD v5 accepts ONLY 512 sample chunks at 16kHz (or 256 at 8kHz).
"""
import logging

import numpy as np
import torch

from voiceagent.errors import VADError

logger = logging.getLogger(__name__)


class SileroVAD:
    SAMPLE_RATE: int = 16000
    VALID_CHUNK_SIZES: tuple[int, ...] = (512,)

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        try:
            self.model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
        except Exception as e:
            raise VADError(
                f"Failed to load Silero VAD model: {e}. "
                f"Ensure torch is installed and internet is available for first download."
            ) from e
        logger.info("SileroVAD loaded (threshold=%.2f)", self.threshold)

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """Determine if an audio chunk contains speech.

        Args:
            audio_chunk: 512 samples at 16kHz. float32 or int16.

        Returns:
            True if speech confidence exceeds threshold.

        Raises:
            VADError: If chunk size is invalid, empty, or contains NaN.
        """
        if audio_chunk.size == 0:
            raise VADError("Empty audio chunk. Expected 512 samples at 16kHz, got 0.")
        if np.any(np.isnan(audio_chunk)):
            raise VADError("Audio chunk contains NaN values. Check audio capture pipeline.")
        if audio_chunk.shape[0] not in self.VALID_CHUNK_SIZES:
            raise VADError(
                f"Invalid chunk size: {audio_chunk.shape[0]}. "
                f"Silero VAD v5 at 16kHz accepts only {self.VALID_CHUNK_SIZES} samples. "
                f"Rechunk your audio before calling is_speech()."
            )
        if audio_chunk.dtype == np.int16:
            audio = audio_chunk.astype(np.float32) / 32768.0
        else:
            audio = audio_chunk.astype(np.float32)
        tensor = torch.from_numpy(audio)
        confidence = self.model(tensor, self.SAMPLE_RATE).item()
        return confidence > self.threshold

    def reset(self) -> None:
        """Reset model hidden states."""
        self.model.reset_states()
