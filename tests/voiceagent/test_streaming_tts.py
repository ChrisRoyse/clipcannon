"""Tests for StreamingTTS."""
import asyncio

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock

from voiceagent.tts.chunker import SentenceChunker
from voiceagent.tts.streaming import StreamingTTS


async def make_token_stream(tokens: list[str]):
    for token in tokens:
        yield token


def make_dummy_audio(n: int = 2400) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


async def collect_chunks(stream_iter) -> list[np.ndarray]:
    chunks = []
    async for chunk in stream_iter:
        chunks.append(chunk)
    return chunks


@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.synthesize = AsyncMock(return_value=make_dummy_audio())
    return adapter


@pytest.fixture
def chunker():
    return SentenceChunker()


def test_two_sentences(mock_adapter, chunker):
    tts = StreamingTTS(mock_adapter, chunker)
    tokens = ["I", " am", " good", ".", " You", " are", " too", ".", " "]
    chunks = asyncio.get_event_loop().run_until_complete(
        collect_chunks(tts.stream(make_token_stream(tokens)))
    )
    assert len(chunks) == 2
    calls = [c.args[0] for c in mock_adapter.synthesize.call_args_list]
    assert calls[0] == "I am good."
    assert calls[1] == "You are too."


def test_flush_remaining(mock_adapter, chunker):
    tts = StreamingTTS(mock_adapter, chunker)
    tokens = ["Hi", " there"]
    chunks = asyncio.get_event_loop().run_until_complete(
        collect_chunks(tts.stream(make_token_stream(tokens)))
    )
    assert len(chunks) == 1
    mock_adapter.synthesize.assert_called_once_with("Hi there")


def test_empty_flush_skipped(mock_adapter, chunker):
    tts = StreamingTTS(mock_adapter, chunker)
    tokens = ["I", " am", " good", ".", " "]
    chunks = asyncio.get_event_loop().run_until_complete(
        collect_chunks(tts.stream(make_token_stream(tokens)))
    )
    assert len(chunks) == 1
    mock_adapter.synthesize.assert_called_once_with("I am good.")


def test_empty_stream(mock_adapter, chunker):
    tts = StreamingTTS(mock_adapter, chunker)
    chunks = asyncio.get_event_loop().run_until_complete(
        collect_chunks(tts.stream(make_token_stream([])))
    )
    assert len(chunks) == 0
    mock_adapter.synthesize.assert_not_called()


def test_single_word_flushed(mock_adapter, chunker):
    tts = StreamingTTS(mock_adapter, chunker)
    tokens = ["Hello"]
    chunks = asyncio.get_event_loop().run_until_complete(
        collect_chunks(tts.stream(make_token_stream(tokens)))
    )
    assert len(chunks) == 1
    mock_adapter.synthesize.assert_called_once_with("Hello")


def test_yields_numpy_arrays(mock_adapter, chunker):
    tts = StreamingTTS(mock_adapter, chunker)
    tokens = ["I", " am", " good", ".", " "]
    chunks = asyncio.get_event_loop().run_until_complete(
        collect_chunks(tts.stream(make_token_stream(tokens)))
    )
    for chunk in chunks:
        assert isinstance(chunk, np.ndarray)
        assert chunk.dtype == np.float32


def test_hello_how_are_you(mock_adapter, chunker):
    tts = StreamingTTS(mock_adapter, chunker)
    tokens = ["Hello", ".", " How", " are", " you", "?", " "]
    chunks = asyncio.get_event_loop().run_until_complete(
        collect_chunks(tts.stream(make_token_stream(tokens)))
    )
    assert len(chunks) == 1
    mock_adapter.synthesize.assert_called_once_with("Hello. How are you?")
