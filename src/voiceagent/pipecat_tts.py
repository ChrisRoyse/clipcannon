"""Pipecat TTS service wrapping faster-qwen3-tts for voice cloning.

Integrates our FastTTSAdapter into Pipecat's frame-based pipeline.
Converts text frames into audio frames using the 0.6B Qwen3-TTS
model with CUDA graphs for ~500ms TTFB.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import numpy as np
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService

from voiceagent.errors import TTSError

logger = logging.getLogger(__name__)


class FastQwen3TTSService(TTSService):
    """Pipecat TTS service using faster-qwen3-tts (0.6B) with CUDA graphs."""

    def __init__(
        self,
        voice_name: str = "boris",
        **kwargs: object,
    ) -> None:
        super().__init__(
            sample_rate=24000,
            push_stop_frames=True,
            **kwargs,
        )
        self._voice_name = voice_name
        self._adapter = None

    async def start(self, frame: StartFrame) -> None:
        """Initialize and pre-load the TTS adapter + model when pipeline starts."""
        await super().start(frame)
        from voiceagent.adapters.fast_tts import FastTTSAdapter

        self._adapter = FastTTSAdapter(voice_name=self._voice_name)

        # Pre-load model and warm up CUDA graphs NOW so first response is fast
        def _preload() -> None:
            self._adapter._warmup()

        await asyncio.to_thread(_preload)
        logger.info(
            "FastQwen3TTSService started and warmed up (voice=%s)",
            self._voice_name,
        )

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Strip emoji, markdown, and non-speech characters."""
        # Remove emoji (Unicode emoji ranges)
        text = re.sub(
            r"[\U0001F300-\U0001FAF8\U0001F600-\U0001F64F"
            r"\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF"
            r"\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
            r"\U0000200D\U00002600-\U000026FF]+",
            "", text,
        )
        # Remove markdown artifacts
        text = re.sub(r"[*_~`#]+", "", text)
        return text.strip()

    async def run_tts(
        self, text: str, context_id: str,
    ) -> AsyncGenerator[Frame, None]:
        """Convert text to audio frames.

        Called by Pipecat when a complete sentence arrives from the LLM.
        Uses non-streaming synthesis which is stable across voice switches
        (~0.9s for short sentences after warmup).
        """
        # Clean text: strip emoji, markdown, whitespace
        text = self._clean_for_speech(text) if text else ""
        if not text:
            return

        if self._adapter is None:
            logger.error("TTS adapter not initialized")
            return

        logger.info("TTS synthesizing: '%s'", text[:80])

        yield TTSStartedFrame()

        try:
            t0 = time.monotonic()
            audio = await self._adapter.synthesize(text)
            elapsed = time.monotonic() - t0
            audio_int16 = (audio * 32767).astype(np.int16)
            audio_dur = len(audio_int16) / 24000
            logger.info(
                "TTS done: %.2fs synth, %.2fs audio (RTF %.1f)",
                elapsed, audio_dur, audio_dur / max(elapsed, 0.01),
            )
            yield TTSAudioRawFrame(
                audio=audio_int16.tobytes(),
                sample_rate=24000,
                num_channels=1,
            )
        except (TTSError, RuntimeError, OSError):
            logger.exception("TTS synthesis failed for text: '%s'", text[:80])

        yield TTSStoppedFrame()

    def switch_voice(self, voice_name: str) -> None:
        """Switch to a different voice profile at runtime."""
        if self._adapter is None:
            raise RuntimeError("TTS adapter not initialized")
        self._adapter.switch_voice(voice_name)
        self._voice_name = voice_name
        logger.info("TTS voice switched to: %s", voice_name)

    async def cancel(self, frame: CancelFrame) -> None:
        """Handle cancellation (barge-in)."""
        await super().cancel(frame)

    async def stop(self, frame: EndFrame) -> None:
        """Clean up when pipeline stops."""
        await super().stop(frame)
        if self._adapter:
            self._adapter.release()
            self._adapter = None
        logger.info("FastQwen3TTSService stopped")
