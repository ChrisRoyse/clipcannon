"""Silence-based endpoint detection for streaming ASR."""
import logging

logger = logging.getLogger(__name__)


class EndpointDetector:
    def __init__(self, silence_ms: int = 350, chunk_ms: int = 200) -> None:
        self.silence_threshold_ms = silence_ms
        self.chunk_ms = chunk_ms
        self._silence_ms: int = 0
        self._has_speech: bool = False

    @property
    def has_speech(self) -> bool:
        return self._has_speech

    def update(self, is_speech: bool) -> bool:
        if is_speech:
            self._has_speech = True
            self._silence_ms = 0
            return False
        if self._has_speech:
            self._silence_ms += self.chunk_ms
            if self._silence_ms >= self.silence_threshold_ms:
                logger.debug("Endpoint: %dms silence after speech", self._silence_ms)
                return True
        return False

    def reset(self) -> None:
        self._silence_ms = 0
        self._has_speech = False
