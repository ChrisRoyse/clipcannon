"""Pre-generated filler audio for latency masking.

Synthesizes short acknowledgment phrases in the user's cloned voice
at startup, then plays them instantly when the user stops speaking
to mask LLM processing latency. All fillers use the same Full ICL
pipeline as normal speech to maintain SECS > 0.95.

Filler selection is context-aware:
  - After a question: "Let me think..." or "Hmm..."
  - After a command:  "Sure." or "On it."
  - Generic:          "Okay." or "Mm-hmm."
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Filler phrases grouped by context
FILLER_PHRASES: dict[str, list[str]] = {
    "question": ["Let me think.", "Hmm.", "Good question."],
    "command": ["Sure.", "On it.", "Okay."],
    "generic": ["Mm-hmm.", "Okay.", "Right."],
}

# All phrases flattened for pre-generation
ALL_PHRASES: list[str] = [
    phrase for phrases in FILLER_PHRASES.values() for phrase in phrases
]


@dataclass
class FillerClip:
    """A pre-synthesized filler audio clip."""

    phrase: str
    audio_int16: bytes
    duration_ms: int
    category: str


class FillerAudioCache:
    """Pre-generates and caches filler audio clips in the cloned voice.

    All clips are synthesized using the same Full ICL pipeline and
    reference audio as normal speech, preserving voice quality.
    Synthesis happens in a background thread at startup.
    """

    def __init__(self) -> None:
        self._clips: dict[str, list[FillerClip]] = {
            "question": [],
            "command": [],
            "generic": [],
        }
        self._ready = False

    @property
    def ready(self) -> bool:
        """Whether all filler clips have been synthesized."""
        return self._ready

    async def pregenerate(self, voice_name: str) -> None:
        """Synthesize all filler clips in background.

        Uses the same FastTTSAdapter as the main TTS service to
        ensure identical voice quality (SECS > 0.95).

        Args:
            voice_name: Voice profile name (e.g., "boris").
        """
        t0 = time.monotonic()
        logger.info("Pre-generating %d filler clips...", len(ALL_PHRASES))

        def _generate_all() -> dict[str, list[FillerClip]]:
            from voiceagent.adapters.fast_tts import FastTTSAdapter

            adapter = FastTTSAdapter(voice_name=voice_name)
            adapter._warmup()

            clips: dict[str, list[FillerClip]] = {
                "question": [],
                "command": [],
                "generic": [],
            }

            for category, phrases in FILLER_PHRASES.items():
                for phrase in phrases:
                    try:
                        engine = adapter._ensure_engine()
                        kwargs = adapter._clone_kwargs(phrase)
                        wavs, sr = engine.generate_voice_clone(**kwargs)
                        wav = wavs[0]
                        if not isinstance(wav, np.ndarray):
                            wav = wav.cpu().numpy()
                        wav = wav.astype(np.float32)
                        wav = adapter._trim_silence(wav, sr)

                        audio_int16 = (wav * 32767).astype(np.int16)
                        duration_ms = int(len(audio_int16) / sr * 1000)
                        clips[category].append(FillerClip(
                            phrase=phrase,
                            audio_int16=audio_int16.tobytes(),
                            duration_ms=duration_ms,
                            category=category,
                        ))
                        logger.debug("Filler '%s': %dms", phrase, duration_ms)
                    except Exception as exc:
                        logger.warning("Filler generation failed for '%s': %s", phrase, exc)

            adapter.release()
            return clips

        self._clips = await asyncio.to_thread(_generate_all)
        self._ready = True

        total = sum(len(v) for v in self._clips.values())
        elapsed = time.monotonic() - t0
        logger.info(
            "Filler audio ready: %d clips in %.1fs", total, elapsed,
        )

    def get_filler(self, category: str = "generic") -> FillerClip | None:
        """Get a random filler clip from the specified category.

        Args:
            category: One of "question", "command", "generic".

        Returns:
            A FillerClip or None if no clips available.
        """
        if not self._ready:
            return None
        clips = self._clips.get(category, self._clips.get("generic", []))
        if not clips:
            return None
        return random.choice(clips)

    def classify_context(self, last_user_text: str) -> str:
        """Classify the user's utterance to select appropriate filler.

        Args:
            last_user_text: The user's transcribed speech.

        Returns:
            Category string: "question", "command", or "generic".
        """
        text = last_user_text.lower().strip()
        # Question detection: ends with ? or starts with question words
        if text.endswith("?") or any(
            text.startswith(w) for w in (
                "what", "how", "why", "when", "where", "who",
                "which", "can", "could", "would", "should", "is",
                "are", "do", "does", "did", "will",
            )
        ):
            return "question"
        # Command detection: imperative verbs
        if any(
            text.startswith(w) for w in (
                "tell", "show", "find", "get", "make", "set",
                "open", "close", "play", "stop", "search",
                "create", "delete", "update", "run", "do",
            )
        ):
            return "command"
        return "generic"
