"""Conversation state machine and manager."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Strip Qwen3 <think>...</think> reasoning blocks from LLM output
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

import numpy as np

from voiceagent.conversation.state import ConversationState
from voiceagent.errors import ConversationError

logger = logging.getLogger(__name__)

# Patterns for voice switching commands
_VOICE_SWITCH_RE = re.compile(
    r"(?:switch\s+to|use|change\s+(?:to|voice\s+to))\s+"
    r"(\w+?)(?:\s*(?:'s\s+)?voice)?$",
    re.IGNORECASE,
)

VALID_TRANSITIONS: dict[ConversationState, set[ConversationState]] = {
    ConversationState.IDLE: {ConversationState.LISTENING},
    ConversationState.LISTENING: {ConversationState.THINKING, ConversationState.IDLE},
    ConversationState.THINKING: {ConversationState.SPEAKING, ConversationState.IDLE},
    ConversationState.SPEAKING: {ConversationState.LISTENING, ConversationState.IDLE},
}


@runtime_checkable
class ASRProtocol(Protocol):
    @property
    def vad(self) -> object: ...
    async def process_chunk(self, audio: np.ndarray) -> object | None: ...


@runtime_checkable
class BrainProtocol(Protocol):
    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


@runtime_checkable
class TTSProtocol(Protocol):
    async def stream(self, token_stream: AsyncIterator[str]) -> AsyncIterator[np.ndarray]: ...


@runtime_checkable
class TransportProtocol(Protocol):
    async def send_audio(self, audio: np.ndarray) -> None: ...
    async def send_event(self, event: dict) -> None: ...


@runtime_checkable
class ContextProtocol(Protocol):
    def build_messages(
        self,
        system_prompt: str,
        conversation_history: list[dict[str, str]],
        user_input: str,
    ) -> list[dict[str, str]]: ...


@runtime_checkable
class VoiceSwitcherProtocol(Protocol):
    def switch_voice(self, voice_name: str) -> None: ...
    @property
    def active_voice(self) -> str: ...
    @property
    def available_voices(self) -> list[str]: ...


class ConversationManager:
    def __init__(
        self,
        asr: ASRProtocol,
        brain: BrainProtocol,
        tts: TTSProtocol,
        transport: TransportProtocol,
        context_manager: ContextProtocol,
        system_prompt: str,
        voice_switcher: VoiceSwitcherProtocol | None = None,
    ) -> None:
        self._state = ConversationState.IDLE
        self._asr = asr
        self._brain = brain
        self._tts = tts
        self._transport = transport
        self._context = context_manager
        self._system_prompt = system_prompt
        self._voice_switcher = voice_switcher
        self._history: list[dict[str, str]] = []

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    async def _set_state(self, new_state: ConversationState) -> None:
        allowed = VALID_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise ConversationError(
                f"Invalid state transition: {self._state.value} -> {new_state.value}. "
                f"Allowed transitions from {self._state.value}: "
                f"{[s.value for s in allowed]}. "
                f"Fix: ensure the pipeline follows IDLE->LISTENING->THINKING->SPEAKING->LISTENING."
            )
        old = self._state
        self._state = new_state
        await self._transport.send_event({"type": "state", "state": new_state.value})
        logger.info("State %s -> %s", old.value, new_state.value)

    async def handle_audio_chunk(self, audio: np.ndarray) -> None:
        if not isinstance(audio, np.ndarray):
            logger.error(
                "handle_audio_chunk received %s instead of np.ndarray",
                type(audio).__name__,
            )
            return
        if audio.size == 0:
            logger.warning("handle_audio_chunk received empty audio array, ignoring")
            return
        if self._state in (ConversationState.THINKING, ConversationState.SPEAKING):
            return

        if self._state == ConversationState.IDLE:
            if not self._detect_speech(audio):
                return
            await self._set_state(ConversationState.LISTENING)

        if self._state == ConversationState.LISTENING:
            event = await self._asr.process_chunk(audio)
            if event is not None and hasattr(event, 'final') and event.final:
                await self._set_state(ConversationState.THINKING)
                await self._generate_response(event.text)

    def _detect_speech(self, audio: np.ndarray) -> bool:
        """Check if any 512-sample sub-chunk contains speech via VAD."""
        chunk_size = 512
        if not (hasattr(self._asr, 'vad') and hasattr(self._asr.vad, 'is_speech')):
            return False
        for i in range(0, len(audio) - chunk_size + 1, chunk_size):
            if self._asr.vad.is_speech(audio[i:i + chunk_size]):
                return True
        return False

    def _check_voice_switch(self, text: str) -> str | None:
        """Check if user text is a voice switch command.

        Returns voice name if matched, None otherwise.
        """
        match = _VOICE_SWITCH_RE.search(text.strip())
        if match:
            return match.group(1).lower()
        return None

    async def _handle_voice_switch(self, voice_name: str) -> None:
        """Switch voice and speak confirmation."""
        if self._voice_switcher is None:
            return

        available = self._voice_switcher.available_voices
        if voice_name not in available:
            response = f"I don't have a voice called {voice_name}. Available voices: {', '.join(available)}."
        else:
            self._voice_switcher.switch_voice(voice_name)
            response = f"Switched to {voice_name} voice."
            logger.info("Voice switched to: %s", voice_name)

        await self._set_state(ConversationState.SPEAKING)
        async for audio_chunk in self._tts.stream(self._iter_text(response)):
            await self._transport.send_audio(audio_chunk)
        self._history.append({"role": "user", "content": f"[switch to {voice_name}]"})
        self._history.append({"role": "assistant", "content": response})
        await self._set_state(ConversationState.LISTENING)

    async def _generate_response(self, user_text: str) -> None:
        # Check for voice switch command before hitting LLM
        if self._voice_switcher:
            switch_target = self._check_voice_switch(user_text)
            if switch_target:
                await self._handle_voice_switch(switch_target)
                return

        messages = self._context.build_messages(
            self._system_prompt, self._history, user_text
        )

        full_response = ""
        async for token in self._brain.generate_stream(messages):
            full_response += token

        # Strip <think>...</think> reasoning blocks (Qwen3 chain-of-thought)
        spoken_text = _THINK_RE.sub("", full_response).strip()
        # Also strip any unclosed <think> block (model hit max tokens mid-thought)
        if "<think>" in spoken_text:
            spoken_text = spoken_text.split("</think>")[-1].strip()
            if spoken_text.startswith("<think>"):
                spoken_text = ""

        if not spoken_text:
            spoken_text = "I'm not sure how to respond to that."
            logger.warning("LLM produced only <think> content, using fallback")

        await self._set_state(ConversationState.SPEAKING)

        async for audio_chunk in self._tts.stream(self._iter_text(spoken_text)):
            await self._transport.send_audio(audio_chunk)

        self._history.append({"role": "user", "content": user_text})
        self._history.append({"role": "assistant", "content": spoken_text})
        await self._set_state(ConversationState.LISTENING)

    async def dismiss(self) -> None:
        if self._state == ConversationState.IDLE:
            return
        old = self._state
        self._state = ConversationState.IDLE
        await self._transport.send_event({"type": "state", "state": "idle"})
        logger.info("Dismissed: %s -> IDLE", old.value)

    @staticmethod
    async def _iter_text(text: str) -> AsyncIterator[str]:
        yield text
