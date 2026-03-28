"""Streaming ASR with VAD-gated Whisper transcription."""
from __future__ import annotations

import logging

import numpy as np

from voiceagent.asr.endpointing import EndpointDetector
from voiceagent.asr.types import ASREvent, AudioBuffer
from voiceagent.asr.vad import SileroVAD
from voiceagent.errors import ASRError

logger = logging.getLogger(__name__)


class StreamingASR:
    CHUNK_MS: int = 200
    SAMPLES_PER_CHUNK: int = 3200
    VAD_CHUNK_SIZE: int = 512

    def __init__(self, config, vad: SileroVAD | None = None) -> None:
        try:
            import faster_whisper
            self.model = faster_whisper.WhisperModel(
                config.model_name,
                device="cuda",
                compute_type="int8",
            )
        except Exception as e:
            raise ASRError(
                f"Failed to load Whisper model '{config.model_name}': {e}. "
                f"Ensure faster-whisper is installed and CUDA GPU is available."
            ) from e

        self.vad = vad or SileroVAD(threshold=config.vad_threshold)
        self.buffer = AudioBuffer()
        self.endpoint = EndpointDetector(
            silence_ms=config.endpoint_silence_ms,
            chunk_ms=self.CHUNK_MS,
        )
        logger.info("StreamingASR initialized: model=%s", config.model_name)

    def _vad_check(self, audio: np.ndarray) -> bool:
        """Rechunk into 512-sample sub-chunks for SileroVAD. True if ANY has speech."""
        num = len(audio) // self.VAD_CHUNK_SIZE
        for i in range(num):
            sub = audio[i * self.VAD_CHUNK_SIZE:(i + 1) * self.VAD_CHUNK_SIZE]
            if self.vad.is_speech(sub):
                return True
        return False

    async def process_chunk(self, audio: np.ndarray) -> ASREvent | None:
        if audio.shape[0] != self.SAMPLES_PER_CHUNK:
            raise ASRError(
                f"Expected {self.SAMPLES_PER_CHUNK} samples, got {audio.shape[0]}."
            )
        # Convert int16 to float32 for VAD
        if audio.dtype == np.int16:
            audio_f32 = audio.astype(np.float32) / 32768.0
        else:
            audio_f32 = audio.astype(np.float32)

        is_speech = self._vad_check(audio_f32)
        endpoint_reached = self.endpoint.update(is_speech)

        if is_speech:
            self.buffer.append(audio_f32)
            buffered = self.buffer.get_audio()
            segments, _ = self.model.transcribe(buffered, beam_size=1, language="en")
            text = " ".join(s.text for s in segments).strip()
            if text:
                return ASREvent(text=text, final=False)

        elif endpoint_reached and self.buffer.has_audio():
            buffered = self.buffer.get_audio()
            segments, _ = self.model.transcribe(buffered, beam_size=5, language="en")
            text = " ".join(s.text for s in segments).strip()
            self.buffer.clear()
            self.endpoint.reset()
            self.vad.reset()
            if text:
                logger.info("Final transcript: '%s'", text)
                return ASREvent(text=text, final=True)
            logger.warning("Endpoint reached but empty transcript")
            return None

        return None

    def reset(self) -> None:
        self.buffer.clear()
        self.endpoint.reset()
        self.vad.reset()
