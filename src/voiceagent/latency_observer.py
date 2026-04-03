"""Pipeline latency observer for measuring per-stage timings.

Hooks into Pipecat's metrics system to track actual end-to-end
latency and per-stage breakdown. Logs a summary after each turn.
"""
from __future__ import annotations

import logging
import time

from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver

logger = logging.getLogger(__name__)


class LatencyObserver(BaseObserver):
    """Tracks per-turn latency breakdown across the voice pipeline.

    Measured intervals:
      - user_speech_duration: how long the user spoke
      - endpointing_delay: time from last speech to UserStoppedSpeaking
      - asr_latency: time from UserStoppedSpeaking to TranscriptionFrame
      - tts_ttfb: time from TranscriptionFrame to first TTSAudioRawFrame
      - total_e2e: time from UserStoppedSpeaking to first audio output

    These overlap in a pipelined system, but the total_e2e is what the
    user perceives as response latency.
    """

    def __init__(self) -> None:
        super().__init__()
        self._user_start: float = 0.0
        self._user_stop: float = 0.0
        self._transcription_time: float = 0.0
        self._tts_start: float = 0.0
        self._first_audio: float = 0.0
        self._turn_active = False
        self._turn_count = 0

    async def on_push_frame(
        self,
        src: object,
        frame: Frame,
        direction: object,
        timestamp: object,
    ) -> None:
        """Called by Pipecat for every frame pushed through the pipeline."""
        now = time.monotonic()

        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_start = now
            self._turn_active = True
            self._first_audio = 0.0
            self._transcription_time = 0.0
            self._tts_start = 0.0

        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_stop = now

        elif isinstance(frame, TranscriptionFrame) and self._turn_active:
            if self._transcription_time == 0.0:
                self._transcription_time = now

        elif isinstance(frame, TTSStartedFrame) and self._turn_active:
            self._tts_start = now

        elif isinstance(frame, TTSAudioRawFrame) and self._turn_active:
            if self._first_audio == 0.0:
                self._first_audio = now
                self._turn_active = False
                self._turn_count += 1
                self._log_turn()

    def _log_turn(self) -> None:
        """Log the latency breakdown for the completed turn."""
        speech_dur = (
            (self._user_stop - self._user_start) * 1000
            if self._user_start > 0 and self._user_stop > self._user_start
            else 0
        )
        asr_lat = (
            (self._transcription_time - self._user_stop) * 1000
            if self._transcription_time > 0 and self._user_stop > 0
            else 0
        )
        tts_ttfb = (
            (self._first_audio - self._tts_start) * 1000
            if self._first_audio > 0 and self._tts_start > 0
            else 0
        )
        total_e2e = (
            (self._first_audio - self._user_stop) * 1000
            if self._first_audio > 0 and self._user_stop > 0
            else 0
        )

        logger.info(
            "LATENCY turn #%d: e2e=%.0fms | speech=%.0fms "
            "asr=%.0fms tts_ttfb=%.0fms",
            self._turn_count, total_e2e, speech_dur,
            asr_lat, tts_ttfb,
        )
