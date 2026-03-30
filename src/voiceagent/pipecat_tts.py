"""Pipecat TTS service wrapping faster-qwen3-tts for voice cloning.

Integrates our FastTTSAdapter into Pipecat's frame-based pipeline.
Converts text frames into audio frames using the 0.6B Qwen3-TTS
model with CUDA graphs for ~500ms TTFB.
"""
from __future__ import annotations

import logging
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
        """Initialize the TTS adapter when the pipeline starts."""
        await super().start(frame)
        from voiceagent.adapters.fast_tts import FastTTSAdapter

        self._adapter = FastTTSAdapter(voice_name=self._voice_name)
        logger.info(
            "FastQwen3TTSService started (voice=%s)", self._voice_name,
        )

    async def run_tts(
        self, text: str, context_id: str,
    ) -> AsyncGenerator[Frame, None]:
        """Convert text to audio frames.

        Called by Pipecat when a complete sentence arrives from the LLM.
        """
        if not text or not text.strip():
            return

        if self._adapter is None:
            logger.error("TTS adapter not initialized")
            return

        logger.info("TTS synthesizing: '%s'", text[:80])

        yield TTSStartedFrame()

        try:
            audio = await self._adapter.synthesize(text)
            audio_int16 = (audio * 32767).astype(np.int16)
            yield TTSAudioRawFrame(
                audio=audio_int16.tobytes(),
                sample_rate=24000,
                num_channels=1,
            )
        except Exception as e:
            logger.error("TTS synthesis failed: %s", e)

        yield TTSStoppedFrame()

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
