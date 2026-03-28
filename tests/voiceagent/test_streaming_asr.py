"""Tests for EndpointDetector and StreamingASR."""
import numpy as np
import pytest
from voiceagent.asr.endpointing import EndpointDetector


def test_endpoint_no_speech_no_endpoint():
    ep = EndpointDetector(silence_ms=600, chunk_ms=200)
    for _ in range(10):
        assert ep.update(is_speech=False) is False
    assert ep.has_speech is False


def test_endpoint_speech_resets_silence():
    ep = EndpointDetector(silence_ms=600, chunk_ms=200)
    ep.update(is_speech=True)
    assert ep.has_speech is True
    assert ep.update(is_speech=False) is False
    ep.update(is_speech=True)
    assert ep.update(is_speech=False) is False


def test_endpoint_speech_then_silence_triggers():
    ep = EndpointDetector(silence_ms=600, chunk_ms=200)
    ep.update(is_speech=True)
    assert ep.update(is_speech=False) is False   # 200ms
    assert ep.update(is_speech=False) is False   # 400ms
    assert ep.update(is_speech=False) is True    # 600ms


def test_endpoint_exact_threshold():
    ep = EndpointDetector(silence_ms=400, chunk_ms=200)
    ep.update(is_speech=True)
    assert ep.update(is_speech=False) is False
    assert ep.update(is_speech=False) is True


def test_endpoint_reset():
    ep = EndpointDetector(silence_ms=600, chunk_ms=200)
    ep.update(is_speech=True)
    ep.reset()
    assert ep.has_speech is False
    for _ in range(10):
        assert ep.update(is_speech=False) is False


# GPU-dependent StreamingASR tests
@pytest.fixture(scope="module")
def check_gpu():
    import torch
    if not torch.cuda.is_available():
        pytest.fail("CUDA GPU required for StreamingASR tests.")


@pytest.fixture(scope="module")
def streaming_asr(check_gpu):
    from voiceagent.asr.streaming import StreamingASR
    class ASRConfig:
        model_name = "Systran/faster-whisper-large-v3"
        vad_threshold = 0.5
        endpoint_silence_ms = 600
        chunk_ms = 200
    return StreamingASR(ASRConfig())


@pytest.mark.asyncio
async def test_silence_returns_none(streaming_asr):
    result = await streaming_asr.process_chunk(np.zeros(3200, dtype=np.float32))
    assert result is None


@pytest.mark.asyncio
async def test_wrong_chunk_size_raises(streaming_asr):
    from voiceagent.errors import ASRError
    with pytest.raises(ASRError, match="Expected 3200"):
        await streaming_asr.process_chunk(np.zeros(1600, dtype=np.float32))


@pytest.mark.asyncio
async def test_reset_clears(streaming_asr):
    streaming_asr.reset()
    assert not streaming_asr.buffer.has_audio()
    assert not streaming_asr.endpoint.has_speech
