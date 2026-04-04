"""Streaming meeting transcription via faster-whisper.

Processes audio in sliding windows and delivers transcript segments
to a callback. Maintains a rolling audio buffer for continuous recognition.

Uses the same model as the voice agent (large-v3-turbo) but in batch mode
rather than Pipecat's streaming mode.
"""
from __future__ import annotations

import gc
import logging
import threading
import time
from collections.abc import Callable

import numpy as np

from voiceagent.meeting.config import TranscriptionConfig
from voiceagent.meeting.errors import MeetingTranscriptionError
from voiceagent.meeting.transcript_format import MeetingSegment

logger = logging.getLogger(__name__)


class MeetingTranscriber:
    """Streaming meeting transcription using faster-whisper.

    Receives audio chunks, accumulates them in a buffer, and processes
    them in sliding windows. Delivers MeetingSegment objects to a callback.

    Args:
        config: Transcription configuration.
        on_segment: Callback receiving completed MeetingSegment objects.
        meeting_start_ms: Timestamp (ms since epoch) when the meeting started.
            Used to compute segment start_ms/end_ms relative to meeting start.
    """

    def __init__(
        self,
        config: TranscriptionConfig,
        on_segment: Callable[[MeetingSegment], None],
        meeting_start_ms: int = 0,
    ) -> None:
        self._config = config
        self._on_segment = on_segment
        self._meeting_start_ms = meeting_start_ms or int(time.time() * 1000)
        self._model: object | None = None
        self._buffer: list[np.ndarray] = []
        self._buffer_duration_s: float = 0.0
        self._running = False
        self._process_lock = threading.Lock()

    def _ensure_model(self) -> None:
        """Lazy-load the faster-whisper model.

        The model is loaded on first use rather than at construction to
        avoid GPU memory allocation until audio actually arrives.

        Raises:
            MeetingTranscriptionError: If faster-whisper is not installed
                or the model fails to load.
        """
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise MeetingTranscriptionError(
                "faster-whisper required. Install: pip install faster-whisper"
            ) from exc

        logger.info(
            "Loading whisper model: %s (%s)...",
            self._config.model,
            self._config.compute_type,
        )
        try:
            self._model = WhisperModel(
                self._config.model,
                device="cuda",
                compute_type=self._config.compute_type,
            )
        except Exception as exc:
            raise MeetingTranscriptionError(
                f"Failed to load whisper model '{self._config.model}': {exc}"
            ) from exc
        logger.info("Whisper model loaded")

    def feed_audio(self, audio: np.ndarray, sample_rate: int) -> None:
        """Feed an audio chunk into the buffer.

        When the buffer reaches ``window_seconds``, triggers processing.
        Thread-safe -- can be called from the audio capture thread.

        Args:
            audio: Float32 audio array normalised to [-1, 1].
            sample_rate: Sample rate of the input audio.
        """
        # Resample to 16kHz if needed
        if sample_rate != 16000:
            try:
                import scipy.signal
            except ImportError as exc:
                raise MeetingTranscriptionError(
                    "scipy required for resampling. Install: pip install scipy"
                ) from exc
            audio = scipy.signal.resample(
                audio, int(len(audio) * 16000 / sample_rate)
            ).astype(np.float32)

        self._buffer.append(audio)
        self._buffer_duration_s += len(audio) / 16000.0

        # Cap buffer at 2x window to prevent unbounded growth if processing
        # is slower than audio arrival
        max_duration = self._config.window_seconds * 2.0
        if self._buffer_duration_s > max_duration:
            overflow = self._buffer_duration_s - max_duration
            while self._buffer and overflow > 0:
                dropped = self._buffer.pop(0)
                dropped_s = len(dropped) / 16000.0
                self._buffer_duration_s -= dropped_s
                overflow -= dropped_s
            logger.warning(
                "Audio buffer overflow — dropped oldest chunks "
                "(buffer capped at %.1fs)", max_duration,
            )

        if self._buffer_duration_s >= self._config.window_seconds:
            self._process_buffer()

    def _process_buffer(self) -> None:
        """Process the accumulated audio buffer through Whisper.

        Uses a non-blocking lock to avoid piling up processing when
        the previous window has not finished yet. Concatenates all
        buffered chunks, clears the buffer, and runs transcription.
        Resulting segments are delivered to the callback as
        MeetingSegment objects.

        Raises:
            MeetingTranscriptionError: On model load failure or
                unrecoverable transcription errors.
        """
        if not self._process_lock.acquire(blocking=False):
            return  # Already processing

        try:
            self._ensure_model()

            # Concatenate buffer
            if not self._buffer:
                return
            audio = np.concatenate(self._buffer)
            buffer_duration_s = self._buffer_duration_s

            # Clear buffer
            self._buffer.clear()
            self._buffer_duration_s = 0.0

            # Transcribe
            segments, _info = self._model.transcribe(
                audio,
                language="en",
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )

            # Convert to MeetingSegments
            now_ms = int(time.time() * 1000)
            for seg in segments:
                start_ms = now_ms - int((buffer_duration_s - seg.start) * 1000)
                end_ms = now_ms - int((buffer_duration_s - seg.end) * 1000)

                # Make relative to meeting start
                rel_start = max(0, start_ms - self._meeting_start_ms)
                rel_end = max(rel_start, end_ms - self._meeting_start_ms)

                text = seg.text.strip()
                if not text:
                    continue

                meeting_seg = MeetingSegment(
                    start_ms=rel_start,
                    end_ms=rel_end,
                    text=text,
                    confidence=getattr(seg, "avg_logprob", 0.0),
                    segment_type="speech",
                )
                self._on_segment(meeting_seg)

        except MeetingTranscriptionError:
            raise
        except Exception as exc:
            logger.error("Transcription error: %s", exc, exc_info=True)
            raise MeetingTranscriptionError(
                f"Transcription failed: {exc}"
            ) from exc
        finally:
            self._process_lock.release()

    def flush(self) -> None:
        """Force-process any remaining audio in the buffer.

        Call this when the meeting ends to ensure no audio is left
        unprocessed.
        """
        if self._buffer:
            self._process_buffer()

    def release(self) -> None:
        """Release the Whisper model and free GPU memory.

        Deletes the model reference, runs garbage collection, and
        empties the CUDA cache if torch is available. Safe to call
        multiple times or before the model has been loaded.
        """
        if self._model is not None:
            del self._model
            self._model = None
            gc.collect()
            try:
                import torch
                torch.cuda.empty_cache()
            except ImportError:
                pass
            logger.info("Whisper model released")
        self._buffer.clear()
        self._buffer_duration_s = 0.0
