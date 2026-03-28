"""Streaming TTS -- sentence-chunked text-to-speech pipeline."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import numpy as np

from voiceagent.adapters.clipcannon import ClipCannonAdapter
from voiceagent.tts.chunker import SentenceChunker

logger = logging.getLogger(__name__)


class StreamingTTS:
    def __init__(self, adapter: ClipCannonAdapter, chunker: SentenceChunker) -> None:
        self.adapter = adapter
        self.chunker = chunker

    async def stream(self, token_stream: AsyncIterator[str]) -> AsyncIterator[np.ndarray]:
        """Convert async token stream into async stream of audio chunks.

        Accumulates tokens, extracts sentences via chunker, synthesizes each.
        Flushes remaining text at end.
        """
        buffer = ""
        chunks_yielded = 0

        async for token in token_stream:
            buffer += token

            while True:
                sentence = self.chunker.extract_sentence(buffer)
                if sentence is None:
                    break
                buffer = buffer[len(sentence):].lstrip()
                logger.info("Extracted sentence (%d chars): '%s'", len(sentence), sentence[:80])
                audio = await self.adapter.synthesize(sentence)
                chunks_yielded += 1
                logger.info("Audio chunk #%d: %d samples (%.2fs)", chunks_yielded, len(audio), len(audio) / 24000)
                yield audio

        remaining = buffer.strip()
        if remaining:
            logger.info("Flushing remaining (%d chars): '%s'", len(remaining), remaining[:80])
            audio = await self.adapter.synthesize(remaining)
            chunks_yielded += 1
            yield audio

        logger.info("Stream complete: %d chunks", chunks_yielded)
