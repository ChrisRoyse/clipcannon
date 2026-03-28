"""ASR data types for the voice agent.

ASREvent: Represents a transcription result (partial or final).
AudioBuffer: Accumulates PCM audio chunks for batch processing.

Audio format: 16kHz mono float32 PCM.
"""
from dataclasses import dataclass, field
import time

import numpy as np


@dataclass
class ASREvent:
    """A single transcription event from the ASR engine."""
    text: str
    final: bool
    timestamp: float = field(default_factory=time.time)


class AudioBuffer:
    """Accumulates PCM audio chunks for batch ASR processing.

    Audio format: 16kHz mono float32 numpy arrays.
    """
    SAMPLE_RATE: int = 16000

    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []

    def append(self, chunk: np.ndarray) -> None:
        """Append a PCM audio chunk to the buffer."""
        self._chunks.append(chunk)

    def get_audio(self) -> np.ndarray:
        """Return all buffered audio as a single concatenated array."""
        if not self._chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._chunks)

    def clear(self) -> None:
        """Remove all buffered audio chunks."""
        self._chunks.clear()

    def has_audio(self) -> bool:
        """Return True if any audio chunks have been appended."""
        return len(self._chunks) > 0

    def duration_s(self) -> float:
        """Return the total duration of buffered audio in seconds."""
        total_samples = sum(len(c) for c in self._chunks)
        return total_samples / self.SAMPLE_RATE
