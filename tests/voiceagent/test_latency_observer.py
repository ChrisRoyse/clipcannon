"""Full State Verification tests for LatencyObserver.

Source of truth: observer.stats (SessionStats dataclass).
Each test verifies the stats object reflects the correct state
after simulated pipeline events.
"""
import asyncio

import pytest

from voiceagent.latency_observer import LatencyObserver, SessionStats


@pytest.fixture
def observer():
    return LatencyObserver()


# ------------------------------------------------------------------
# SessionStats unit tests
# ------------------------------------------------------------------

class TestSessionStats:
    def test_empty_stats(self):
        s = SessionStats()
        assert s.e2e_p50 == 0.0
        assert s.e2e_p95 == 0.0
        assert s.turn_count == 0

    def test_percentile_single_value(self):
        s = SessionStats(e2e_latencies=[500.0])
        assert s.e2e_p50 == 500.0
        assert s.e2e_p95 == 500.0

    def test_percentile_multiple_values(self):
        s = SessionStats(e2e_latencies=[100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])
        p50 = s.e2e_p50
        p95 = s.e2e_p95
        print(f"FSV: P50={p50}, P95={p95}")
        assert 400 <= p50 <= 600  # median area
        assert p95 >= 900  # 95th percentile


# ------------------------------------------------------------------
# Observer frame processing
# ------------------------------------------------------------------

class TestObserverFrames:
    def test_initializes_clean(self, observer):
        assert observer.stats.turn_count == 0
        assert not observer._turn_active

    @pytest.mark.asyncio
    async def test_user_started_activates(self, observer):
        from pipecat.frames.frames import UserStartedSpeakingFrame
        await observer.on_push_frame(None, UserStartedSpeakingFrame(), None, None)
        assert observer._turn_active is True
        print(f"FSV: turn_active={observer._turn_active}")

    @pytest.mark.asyncio
    async def test_user_stopped_records_time(self, observer):
        from pipecat.frames.frames import UserStartedSpeakingFrame, UserStoppedSpeakingFrame
        await observer.on_push_frame(None, UserStartedSpeakingFrame(), None, None)
        await observer.on_push_frame(None, UserStoppedSpeakingFrame(), None, None)
        assert observer._user_stop > 0
        assert observer._user_stop >= observer._user_start
        print(f"FSV: user_start={observer._user_start:.4f}, user_stop={observer._user_stop:.4f}")

    @pytest.mark.asyncio
    async def test_full_turn_records_stats(self, observer):
        """Simulate a complete turn and verify stats are populated."""
        from pipecat.frames.frames import (
            LLMFullResponseStartFrame,
            TranscriptionFrame,
            TTSAudioRawFrame,
            TTSStartedFrame,
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )
        import time

        await observer.on_push_frame(None, UserStartedSpeakingFrame(), None, None)
        time.sleep(0.01)  # simulate speech
        await observer.on_push_frame(None, UserStoppedSpeakingFrame(), None, None)
        time.sleep(0.01)  # simulate ASR processing
        await observer.on_push_frame(None, TranscriptionFrame(text="hello", user_id="t", timestamp="t"), None, None)
        time.sleep(0.01)  # simulate LLM processing
        await observer.on_push_frame(None, LLMFullResponseStartFrame(), None, None)
        time.sleep(0.01)  # simulate TTS processing
        await observer.on_push_frame(None, TTSStartedFrame(), None, None)
        time.sleep(0.01)
        await observer.on_push_frame(None, TTSAudioRawFrame(audio=b"\x00" * 100, sample_rate=24000, num_channels=1), None, None)

        # Source of truth: stats object
        print(f"FSV: turn_count={observer.stats.turn_count}")
        print(f"FSV: e2e_latencies={observer.stats.e2e_latencies}")
        print(f"FSV: asr_latencies={observer.stats.asr_latencies}")
        print(f"FSV: llm_ttfts={observer.stats.llm_ttfts}")
        print(f"FSV: tts_ttfbs={observer.stats.tts_ttfbs}")

        assert observer.stats.turn_count == 1
        assert len(observer.stats.e2e_latencies) == 1
        assert observer.stats.e2e_latencies[0] > 0
        assert len(observer.stats.asr_latencies) == 1
        assert len(observer.stats.llm_ttfts) == 1
        assert len(observer.stats.tts_ttfbs) == 1
        # Turn should be deactivated
        assert not observer._turn_active


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_audio_without_turn_start_ignored(self, observer):
        """Audio frames without a preceding UserStartedSpeaking should be ignored."""
        from pipecat.frames.frames import TTSAudioRawFrame
        await observer.on_push_frame(None, TTSAudioRawFrame(audio=b"\x00", sample_rate=24000, num_channels=1), None, None)
        assert observer.stats.turn_count == 0
        print(f"FSV: orphan audio ignored, turn_count={observer.stats.turn_count}")

    def test_session_report_interval(self, observer):
        """Session report interval should be a positive integer."""
        assert observer.SESSION_REPORT_INTERVAL > 0
        assert isinstance(observer.SESSION_REPORT_INTERVAL, int)
