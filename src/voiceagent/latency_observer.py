"""Pipeline latency observer for measuring per-stage timings.

Hooks into Pipecat's observer system to track actual end-to-end
latency and per-stage breakdown. Logs a summary after each turn
and maintains session-level P50/P95 statistics for enterprise
quality monitoring.

Enterprise targets:
  - E2E latency P95 < 800ms
  - TTS TTFB P95 < 300ms
  - ASR latency P95 < 500ms
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver

logger = logging.getLogger(__name__)


@dataclass
class SessionStats:
    """Aggregated session-level latency statistics."""

    e2e_latencies: list[float] = field(default_factory=list)
    asr_latencies: list[float] = field(default_factory=list)
    tts_ttfbs: list[float] = field(default_factory=list)
    llm_ttfts: list[float] = field(default_factory=list)
    turn_count: int = 0
    error_count: int = 0

    def _percentile(self, values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = int(len(s) * pct / 100)
        return s[min(idx, len(s) - 1)]

    @property
    def e2e_p50(self) -> float:
        return self._percentile(self.e2e_latencies, 50)

    @property
    def e2e_p95(self) -> float:
        return self._percentile(self.e2e_latencies, 95)

    @property
    def tts_ttfb_p95(self) -> float:
        return self._percentile(self.tts_ttfbs, 95)

    @property
    def asr_p95(self) -> float:
        return self._percentile(self.asr_latencies, 95)

    @property
    def llm_ttft_p95(self) -> float:
        return self._percentile(self.llm_ttfts, 95)


class LatencyObserver(BaseObserver):
    """Tracks per-turn latency breakdown across the voice pipeline.

    Measured intervals:
      - speech_duration: how long the user spoke
      - asr_latency: time from UserStoppedSpeaking to TranscriptionFrame
      - llm_ttft: time from TranscriptionFrame to LLMFullResponseStart
      - tts_ttfb: time from TTSStarted to first TTSAudioRawFrame
      - total_e2e: time from UserStoppedSpeaking to first audio output

    Session stats (P50, P95) are logged every 5 turns and available
    via the .stats property.
    """

    SESSION_REPORT_INTERVAL = 5

    def __init__(self) -> None:
        super().__init__()
        self._user_start: float = 0.0
        self._user_stop: float = 0.0
        self._transcription_time: float = 0.0
        self._llm_start: float = 0.0
        self._tts_start: float = 0.0
        self._first_audio: float = 0.0
        self._turn_active = False
        self.stats = SessionStats()

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
            self._llm_start = 0.0
            self._tts_start = 0.0

        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_stop = now

        elif isinstance(frame, TranscriptionFrame) and self._turn_active:
            if self._transcription_time == 0.0:
                self._transcription_time = now

        elif isinstance(frame, LLMFullResponseStartFrame) and self._turn_active:
            if self._llm_start == 0.0:
                self._llm_start = now

        elif isinstance(frame, TTSStartedFrame) and self._turn_active:
            self._tts_start = now

        elif isinstance(frame, TTSAudioRawFrame) and self._turn_active:
            if self._first_audio == 0.0:
                self._first_audio = now
                self._turn_active = False
                self._record_turn()

    def _ms_between(self, start: float, end: float) -> float:
        if start > 0 and end > start:
            return (end - start) * 1000
        return 0.0

    def _record_turn(self) -> None:
        """Record metrics for the completed turn."""
        self.stats.turn_count += 1

        speech_dur = self._ms_between(self._user_start, self._user_stop)
        asr_lat = self._ms_between(self._user_stop, self._transcription_time)
        llm_ttft = self._ms_between(self._transcription_time, self._llm_start)
        tts_ttfb = self._ms_between(self._tts_start, self._first_audio)
        total_e2e = self._ms_between(self._user_stop, self._first_audio)

        if total_e2e > 0:
            self.stats.e2e_latencies.append(total_e2e)
        if asr_lat > 0:
            self.stats.asr_latencies.append(asr_lat)
        if llm_ttft > 0:
            self.stats.llm_ttfts.append(llm_ttft)
        if tts_ttfb > 0:
            self.stats.tts_ttfbs.append(tts_ttfb)

        logger.info(
            "LATENCY turn #%d: e2e=%.0fms | speech=%.0fms "
            "asr=%.0fms llm_ttft=%.0fms tts_ttfb=%.0fms",
            self.stats.turn_count, total_e2e, speech_dur,
            asr_lat, llm_ttft, tts_ttfb,
        )

        # Enterprise quality gate: warn if E2E exceeds 800ms
        if total_e2e > 800:
            logger.warning(
                "E2E latency %.0fms exceeds 800ms enterprise target", total_e2e,
            )

        # Session report every N turns
        if self.stats.turn_count % self.SESSION_REPORT_INTERVAL == 0:
            self._log_session_stats()

    def _log_session_stats(self) -> None:
        """Log session-level P50/P95 statistics."""
        s = self.stats
        logger.info(
            "SESSION stats (%d turns): "
            "e2e P50=%.0fms P95=%.0fms | "
            "asr P95=%.0fms | llm_ttft P95=%.0fms | tts_ttfb P95=%.0fms",
            s.turn_count,
            s.e2e_p50, s.e2e_p95,
            s.asr_p95, s.llm_ttft_p95, s.tts_ttfb_p95,
        )
