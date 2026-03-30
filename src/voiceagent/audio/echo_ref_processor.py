"""Pipecat processor that captures speaker output for AEC reference.

Sits in the pipeline after TTS, intercepts audio frames going to the
speaker, and feeds them to the AEC filter as the echo reference signal.
Also tracks bot speaking state for mic gating.
"""
from __future__ import annotations

import logging

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    OutputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceagent.audio.aec_filter import AECFilter

logger = logging.getLogger(__name__)


class EchoReferenceProcessor(FrameProcessor):
    """Captures output audio and bot speaking state for AEC.

    Insert this processor in the pipeline between TTS and the output
    transport. It passes all frames through unchanged but:
    - Feeds OutputAudioRawFrame data to the AEC filter as reference
    - Notifies the AEC filter when the bot starts/stops speaking
    """

    def __init__(self, aec_filter: AECFilter, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._aec = aec_filter

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Intercept frames for AEC reference, then pass through."""
        await super().process_frame(frame, direction)

        if isinstance(frame, OutputAudioRawFrame):
            # Feed speaker audio to AEC as reference signal
            self._aec.feed_reference(frame.audio, frame.sample_rate)

        elif isinstance(frame, BotStartedSpeakingFrame):
            self._aec.set_bot_speaking(True)
            logger.debug("EchoRef: bot started speaking")

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._aec.set_bot_speaking(False)
            logger.debug("EchoRef: bot stopped speaking")

        # Always pass frame through unchanged
        await self.push_frame(frame, direction)
