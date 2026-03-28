"""OpenWakeWord wake word detection."""
import logging

import numpy as np

from voiceagent.errors import WakeWordError

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Detects wake words in audio chunks using openwakeword."""

    def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.6) -> None:
        self.model_name = model_name
        self.threshold = threshold

        try:
            import openwakeword
        except ImportError:
            raise ImportError(
                "openwakeword is required for wake word detection. "
                "Install with: pip install openwakeword"
            )

        try:
            from openwakeword.model import Model as OWWModel

            # Find the pretrained model path matching the requested model name
            model_paths = openwakeword.get_pretrained_model_paths()
            matching = [p for p in model_paths if model_name in p]
            if matching:
                self._model = OWWModel(wakeword_model_paths=matching)
            else:
                # Fall back to loading all pretrained models
                self._model = OWWModel()

            logger.info("Wake word model loaded: %s (threshold=%.2f)", model_name, threshold)
        except Exception as e:
            raise WakeWordError(
                f"Failed to load wake word model '{model_name}': {e}. "
                f"Fix: check network, ensure model name is valid."
            ) from e

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """Detect wake word in audio chunk (~1280 samples at 16kHz)."""
        if not isinstance(audio_chunk, np.ndarray):
            logger.error("detect() received %s instead of np.ndarray", type(audio_chunk).__name__)
            return False
        if audio_chunk.size == 0:
            logger.warning("detect() received empty audio array")
            return False
        if audio_chunk.dtype != np.int16:
            audio_chunk = audio_chunk.astype(np.int16)
        prediction = self._model.predict(audio_chunk)
        return any(score > self.threshold for score in prediction.values())
