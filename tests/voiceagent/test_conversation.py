"""Tests for conversation state machine."""

import numpy as np
import pytest

from voiceagent.conversation.manager import ConversationManager
from voiceagent.conversation.state import ConversationState
from voiceagent.errors import ConversationError


class StubASREvent:
    def __init__(self, text: str, final: bool = False):
        self.text = text
        self.final = final


class StubVAD:
    def __init__(self, speech: bool = False):
        self._speech = speech
    def is_speech(self, audio: np.ndarray) -> bool:
        return self._speech


class StubASR:
    def __init__(self, vad: StubVAD, events: list | None = None):
        self._vad = vad
        self._events = events or []
        self._idx = 0
    @property
    def vad(self) -> StubVAD:
        return self._vad
    async def process_chunk(self, audio: np.ndarray) -> object | None:
        if self._idx < len(self._events):
            evt = self._events[self._idx]
            self._idx += 1
            return evt
        return None


class StubBrain:
    def __init__(self, response: str = "Hello"):
        self._response = response
    async def generate_stream(self, messages: list[dict[str, str]]):
        for word in self._response.split():
            yield word + " "


class StubTTS:
    async def stream(self, token_stream):
        text = ""
        async for t in token_stream:
            text += t
        yield np.zeros(1600, dtype=np.int16)


class StubTransport:
    def __init__(self):
        self.events: list[dict] = []
        self.audio_chunks: list[np.ndarray] = []
    async def send_event(self, event: dict) -> None:
        self.events.append(event)
    async def send_audio(self, audio: np.ndarray) -> None:
        self.audio_chunks.append(audio)


class StubContext:
    def build_messages(self, system_prompt: str, history: list[dict[str, str]], user_input: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": system_prompt}] + history


def _make_mgr(speech=False, events=None, response="Hello"):
    vad = StubVAD(speech=speech)
    asr = StubASR(vad, events=events)
    transport = StubTransport()
    return ConversationManager(asr, StubBrain(response), StubTTS(), transport, StubContext(), "sys"), transport


def test_initial_state_is_idle():
    mgr, _ = _make_mgr()
    assert mgr.state == ConversationState.IDLE


@pytest.mark.asyncio
async def test_idle_to_listening_on_speech():
    mgr, transport = _make_mgr(speech=True, events=[StubASREvent("", final=False)])
    await mgr.handle_audio_chunk(np.zeros(1600, dtype=np.int16))
    assert mgr.state == ConversationState.LISTENING
    assert {"type": "state", "state": "listening"} in transport.events


@pytest.mark.asyncio
async def test_full_pipeline():
    mgr, transport = _make_mgr(
        speech=True,
        events=[StubASREvent("", final=False), StubASREvent("hello world", final=True)],
        response="Hi there",
    )
    audio = np.zeros(1600, dtype=np.int16)
    await mgr.handle_audio_chunk(audio)
    assert mgr.state == ConversationState.LISTENING
    await mgr.handle_audio_chunk(audio)
    assert mgr.state == ConversationState.LISTENING


@pytest.mark.asyncio
async def test_audio_while_thinking_ignored():
    mgr, _ = _make_mgr()
    mgr._state = ConversationState.THINKING
    await mgr.handle_audio_chunk(np.zeros(1600, dtype=np.int16))
    assert mgr.state == ConversationState.THINKING


@pytest.mark.asyncio
async def test_audio_while_speaking_ignored():
    mgr, _ = _make_mgr()
    mgr._state = ConversationState.SPEAKING
    await mgr.handle_audio_chunk(np.zeros(1600, dtype=np.int16))
    assert mgr.state == ConversationState.SPEAKING


@pytest.mark.asyncio
async def test_empty_audio_ignored():
    mgr, _ = _make_mgr()
    await mgr.handle_audio_chunk(np.array([], dtype=np.int16))
    assert mgr.state == ConversationState.IDLE


@pytest.mark.asyncio
async def test_invalid_transition_raises():
    mgr, _ = _make_mgr()
    with pytest.raises(ConversationError, match="Invalid state transition"):
        await mgr._set_state(ConversationState.SPEAKING)


@pytest.mark.asyncio
async def test_dismiss_from_any_state():
    mgr, transport = _make_mgr()
    for state in [ConversationState.LISTENING, ConversationState.THINKING, ConversationState.SPEAKING]:
        mgr._state = state
        await mgr.dismiss()
        assert mgr.state == ConversationState.IDLE


@pytest.mark.asyncio
async def test_dismiss_while_idle_is_noop():
    mgr, transport = _make_mgr()
    await mgr.dismiss()
    assert mgr.state == ConversationState.IDLE
    assert len(transport.events) == 0


@pytest.mark.asyncio
async def test_history_tracks_turns():
    mgr, _ = _make_mgr(
        speech=True,
        events=[StubASREvent("", final=False), StubASREvent("What is 2+2?", final=True)],
        response="Four",
    )
    audio = np.zeros(1600, dtype=np.int16)
    await mgr.handle_audio_chunk(audio)
    await mgr.handle_audio_chunk(audio)
    history = mgr.history
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "What is 2+2?"
    assert history[1]["role"] == "assistant"


def test_conversation_state_enum_has_4_values():
    assert len(ConversationState) == 4
    assert set(s.value for s in ConversationState) == {"idle", "listening", "thinking", "speaking"}
