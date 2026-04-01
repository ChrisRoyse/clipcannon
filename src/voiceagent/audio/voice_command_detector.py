"""Voice command detector using sentence embedding similarity.

Detects voice switch commands from ASR text by comparing against
pre-computed embeddings of known command patterns. Runs as a Pipecat
processor between STT and LLM, intercepting switch commands before
they reach the LLM.

Uses sentence-transformers for fast CPU-based embedding (~5ms per query).
Cosine similarity threshold determines whether text is a command.
"""
from __future__ import annotations

import logging
import os
import re
import signal
from collections.abc import Callable, Coroutine
from typing import Any

import numpy as np
from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

# Known voice switch command patterns (from user's actual speech)
SWITCH_COMMANDS = [
    "switch to {voice} voice",
    "switch to {voice}'s voice",
    "swap to {voice} voice",
    "switch over to {voice} voice",
    "go to {voice} voice",
    "change to {voice} voice",
    "use {voice} voice",
    "switch to {voice}",
    "swap to {voice}",
]

# Similarity threshold -- above this = voice command, below = normal speech
SIMILARITY_THRESHOLD = 0.78


class VoiceCommandDetector(FrameProcessor):
    """Detects voice switch commands from ASR transcriptions.

    Sits between STT and LLM in the pipeline. When a voice switch
    command is detected (via cosine similarity to known patterns),
    it triggers the voice switch directly and blocks the frame from
    reaching the LLM. Normal speech passes through unchanged.
    """

    def __init__(
        self,
        voice_names: list[str],
        switch_callback: Callable[[str], Coroutine[Any, Any, None]],
        threshold: float = SIMILARITY_THRESHOLD,
        **kwargs: object,
    ) -> None:
        """Initialize the command detector.

        Args:
            voice_names: List of available voice profile names.
            switch_callback: Async callable(voice_name: str) to execute switch.
            threshold: Cosine similarity threshold for command detection.
        """
        super().__init__(**kwargs)
        self._voice_names = [v.lower() for v in voice_names]
        self._switch_callback = switch_callback
        self._threshold = threshold
        self._embeddings: dict[str, dict[str, np.ndarray | str]] = {}
        self._model = None
        self._initialized = False

    def _ensure_model(self) -> None:
        """Lazy-load the sentence embedding model (CPU, fast)."""
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(
            "all-MiniLM-L6-v2", device="cpu",
        )
        logger.info("Voice command detector: model loaded")

        # Pre-compute embeddings for all command patterns x voices
        patterns = []
        pattern_keys = []
        for voice in self._voice_names:
            for template in SWITCH_COMMANDS:
                cmd = template.format(voice=voice)
                patterns.append(cmd)
                pattern_keys.append((cmd, voice))

        embeddings = self._model.encode(patterns, normalize_embeddings=True)
        for i, (cmd, voice) in enumerate(pattern_keys):
            self._embeddings[cmd] = {
                "embedding": embeddings[i],
                "voice": voice,
            }

        logger.info(
            "Voice command detector: %d patterns for %d voices",
            len(self._embeddings), len(self._voice_names),
        )
        self._initialized = True

    def _detect_command(self, text: str) -> str | None:
        """Check if text matches a voice switch command.

        Returns the target voice name if a match is found, None otherwise.
        Uses two-stage detection:
          1. Fast regex pre-filter (eliminates most non-commands)
          2. Embedding similarity for confirmed candidates

        Args:
            text: Transcribed text from ASR.

        Returns:
            Voice name to switch to, or None if not a command.
        """
        text_lower = text.lower().strip()

        # Stage 1: Fast regex pre-filter
        # Must contain a switch verb AND a known voice name
        switch_verbs = r"\b(switch|swap|go|change|use)\b"
        if not re.search(switch_verbs, text_lower):
            return None

        if not any(voice in text_lower for voice in self._voice_names):
            return None

        # Stage 2: Also check this isn't part of a longer sentence
        # Voice commands are typically short (3-6 words)
        word_count = len(text_lower.split())
        if word_count > 10:
            # Too long to be a voice command -- probably conversational
            return None

        # Stage 3: Embedding similarity
        self._ensure_model()
        query_emb = self._model.encode(
            [text_lower], normalize_embeddings=True,
        )[0]

        best_score = 0.0
        best_voice = None
        for cmd, data in self._embeddings.items():
            score = float(np.dot(query_emb, data["embedding"]))
            if score > best_score:
                best_score = score
                best_voice = data["voice"]

        if best_score >= self._threshold:
            logger.info(
                "Voice command detected: '%s' -> %s (score=%.3f)",
                text_lower, best_voice, best_score,
            )
            return best_voice

        logger.debug(
            "Not a voice command: '%s' (best=%.3f < %.3f)",
            text_lower, best_score, self._threshold,
        )
        return None

    async def process_frame(
        self, frame: Frame, direction: FrameDirection,
    ) -> None:
        """Process frames, intercepting voice switch commands."""
        await super().process_frame(frame, direction)

        # Only intercept transcription frames going downstream
        if direction == FrameDirection.DOWNSTREAM and isinstance(
            frame, TranscriptionFrame,
        ):
            target_voice = self._detect_command(frame.text)

            if target_voice:
                # Execute voice switch directly -- don't pass to LLM
                try:
                    await self._switch_callback(target_voice)
                except (RuntimeError, OSError, ValueError) as e:
                    logger.error("Voice switch failed: %s", e)
                # Don't push this frame downstream -- command consumed
                return

        # Pass everything else through (including non-transcription frames)
        await self.push_frame(frame, direction)


class SleepCommandDetector(FrameProcessor):
    """Detects 'go to sleep' commands to shut down the agent.

    Uses embedding similarity (same approach as voice commands) to
    detect sleep/shutdown phrases. When detected, terminates the
    process to cleanly stop all audio I/O.
    """

    SLEEP_PATTERNS = [
        "go to sleep",
        "go to sleep now",
        "shut down",
        "goodnight",
        "good night",
        "stop listening",
        "turn off",
    ]

    def __init__(
        self, threshold: float = 0.75, **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._threshold = threshold
        self._model = None
        self._embeddings: list[np.ndarray] = []

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        self._embeddings = self._model.encode(
            self.SLEEP_PATTERNS, normalize_embeddings=True,
        )
        logger.info("Sleep detector: %d patterns loaded", len(self._embeddings))

    def _is_sleep_command(self, text: str) -> bool:
        text_lower = text.lower().strip()

        # Fast check: must contain a sleep-related word
        sleep_words = r"\b(sleep|shut|goodnight|night|off|stop)\b"
        if not re.search(sleep_words, text_lower):
            return False

        # Short utterances only (sleep commands are brief)
        if len(text_lower.split()) > 8:
            return False

        self._ensure_model()
        query = self._model.encode([text_lower], normalize_embeddings=True)[0]
        best = max(float(np.dot(query, e)) for e in self._embeddings)
        if best >= self._threshold:
            logger.info("Sleep command matched (score=%.3f): '%s'", best, text_lower)
            return True
        return False

    async def process_frame(
        self, frame: Frame, direction: FrameDirection,
    ) -> None:
        await super().process_frame(frame, direction)

        if direction == FrameDirection.DOWNSTREAM and isinstance(
            frame, TranscriptionFrame,
        ):
            if self._is_sleep_command(frame.text):
                logger.info("Shutting down voice agent...")
                os.kill(os.getpid(), signal.SIGTERM)
                return

        await self.push_frame(frame, direction)
