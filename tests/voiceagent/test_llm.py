"""Tests for LLMBrain custom inference harness -- real model, NO MOCKS.

Requires: RTX 5090 GPU, Qwen3-14B-FP8 model downloaded.
"""

import pytest
import torch

from voiceagent.brain.llm import GenerationMetrics, LLMBrain
from voiceagent.errors import LLMError

MODEL_PATH = "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/"


class TestConfig:
    model_path = MODEL_PATH
    quantization = "fp8"
    gpu_memory_utilization = 0.45
    max_model_len = 32768
    max_tokens = 64


# --- Model Loading ---

def test_model_loads_to_gpu(session_llm_brain, check_gpu):
    """Model is loaded and consuming significant VRAM."""
    assert session_llm_brain.is_loaded is True
    vram_gb = session_llm_brain.vram_bytes / (1024 ** 3)
    print(f"VRAM allocated: {vram_gb:.2f} GB")
    assert vram_gb > 1.0, f"Expected >1GB VRAM, got {vram_gb:.2f}GB"


def test_model_has_tokenizer(session_llm_brain):
    """Tokenizer loaded with correct vocab."""
    assert session_llm_brain._tokenizer is not None
    assert session_llm_brain._tokenizer.vocab_size > 100


def test_model_load_time_recorded(session_llm_brain):
    """Load time is tracked."""
    assert session_llm_brain._load_time_ms > 0
    print(f"Load time: {session_llm_brain._load_time_ms:.0f}ms")


# --- Chat Prompt Building ---

def test_build_chat_prompt_basic(session_llm_brain):
    """Produces non-empty prompt containing user message."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]
    prompt = session_llm_brain._build_chat_prompt(messages)
    assert isinstance(prompt, str)
    assert len(prompt) > 0
    assert "Hello" in prompt


def test_build_chat_prompt_preserves_system(session_llm_brain):
    """System message content appears in prompt."""
    messages = [
        {"role": "system", "content": "CUSTOM_SYSTEM_MARKER"},
        {"role": "user", "content": "test"},
    ]
    prompt = session_llm_brain._build_chat_prompt(messages)
    assert "CUSTOM_SYSTEM_MARKER" in prompt


def test_build_chat_prompt_multi_turn(session_llm_brain):
    """Multi-turn conversation renders all messages."""
    messages = [
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "And 3+3?"},
    ]
    prompt = session_llm_brain._build_chat_prompt(messages)
    assert "2+2" in prompt
    assert "4" in prompt
    assert "3+3" in prompt


def test_build_chat_prompt_empty_raises(session_llm_brain):
    """Empty messages list raises LLMError."""
    with pytest.raises(LLMError, match="Empty messages"):
        session_llm_brain._build_chat_prompt([])


# --- Token Streaming ---

@pytest.mark.asyncio
async def test_generate_stream_yields_tokens(session_llm_brain):
    """generate_stream yields individual token strings."""
    messages = [{"role": "user", "content": "Say hello in one word."}]
    tokens = []
    async for token in session_llm_brain.generate_stream(messages):
        tokens.append(token)
    assert len(tokens) > 0, "No tokens yielded"
    full_text = "".join(tokens)
    assert len(full_text) > 0
    print(f"Tokens: {len(tokens)}, text: {full_text[:100]}")


@pytest.mark.asyncio
async def test_generate_stream_actually_streams(session_llm_brain):
    """Tokens arrive incrementally, not all at once."""
    messages = [{"role": "user", "content": "Count from 1 to 5."}]
    tokens = []
    async for token in session_llm_brain.generate_stream(messages):
        tokens.append(token)
    # Real streaming should produce multiple tokens, not one big chunk
    assert len(tokens) >= 3, f"Expected multiple tokens, got {len(tokens)}: {''.join(tokens)}"
    print(f"Stream produced {len(tokens)} individual tokens")


@pytest.mark.asyncio
async def test_generate_stream_empty_messages_raises(session_llm_brain):
    """Empty messages raises LLMError before any tokens."""
    with pytest.raises(LLMError, match="Empty messages"):
        async for _ in session_llm_brain.generate_stream([]):
            pass


@pytest.mark.asyncio
async def test_generate_stream_records_metrics(session_llm_brain):
    """Metrics are recorded after generation."""
    messages = [{"role": "user", "content": "Say hi."}]
    async for _ in session_llm_brain.generate_stream(messages):
        pass
    m = session_llm_brain.metrics
    assert m is not None
    assert isinstance(m, GenerationMetrics)
    assert m.prompt_tokens > 0
    assert m.generated_tokens > 0
    assert m.time_to_first_token_ms > 0
    assert m.total_generation_ms > 0
    assert m.tokens_per_second > 0
    print(f"Metrics: prompt={m.prompt_tokens}, gen={m.generated_tokens}, "
          f"ttft={m.time_to_first_token_ms}ms, total={m.total_generation_ms}ms, "
          f"speed={m.tokens_per_second} tok/s")


@pytest.mark.asyncio
async def test_generate_with_custom_sampling(session_llm_brain):
    """Custom temperature/top_p/top_k work without error."""
    messages = [{"role": "user", "content": "Say hello."}]
    tokens = []
    async for token in session_llm_brain.generate_stream(
        messages, temperature=0.3, top_p=0.95, top_k=20, repetition_penalty=1.1
    ):
        tokens.append(token)
    assert len(tokens) > 0
    print(f"Custom sampling: {len(tokens)} tokens")


@pytest.mark.asyncio
async def test_generate_greedy(session_llm_brain):
    """temperature=0 triggers greedy decoding."""
    messages = [{"role": "user", "content": "What is 1+1? Answer with just the number."}]
    tokens = []
    async for token in session_llm_brain.generate_stream(messages, temperature=0.0):
        tokens.append(token)
    text = "".join(tokens)
    assert len(text) > 0
    print(f"Greedy: {text[:50]}")


# --- Error Handling ---

def test_bad_model_path_raises(check_gpu):
    """Nonexistent model path raises LLMError with descriptive message."""
    class BadConfig:
        model_path = "/nonexistent/model/path"
        quantization = "fp8"
        gpu_memory_utilization = 0.45
        max_model_len = 32768
        max_tokens = 64
    with pytest.raises(LLMError, match="Failed to load tokenizer"):
        LLMBrain(BadConfig())


def test_bad_quantization_raises(check_gpu):
    """Invalid quantization string raises LLMError."""
    class BadConfig:
        model_path = MODEL_PATH
        quantization = "int3_nonsense"
        gpu_memory_utilization = 0.45
        max_model_len = 32768
        max_tokens = 64
    with pytest.raises(LLMError, match="Unsupported quantization"):
        LLMBrain(BadConfig())


# --- Release ---

def test_release_clears_model_state(check_gpu):
    """release() dereferences model and tokenizer, marks as not loaded."""
    b = LLMBrain(TestConfig())
    assert b.is_loaded is True
    assert b._model is not None
    assert b._tokenizer is not None
    b.release()
    assert b.is_loaded is False
    assert b._model is None
    assert b._tokenizer is None
    assert b._device is None
    print("Release verified: model=None, tokenizer=None, is_loaded=False")


@pytest.mark.asyncio
async def test_generate_after_release_raises(check_gpu):
    """Generating after release() raises LLMError."""
    b = LLMBrain(TestConfig())
    b.release()
    with pytest.raises(LLMError, match="Model not loaded"):
        async for _ in b.generate_stream([{"role": "user", "content": "hello"}]):
            pass


# --- Dtype Resolution ---

def test_resolve_dtype():
    """All supported quantization strings resolve correctly."""
    assert LLMBrain._resolve_dtype("fp8") == torch.float16
    assert LLMBrain._resolve_dtype("fp16") == torch.float16
    assert LLMBrain._resolve_dtype("bf16") == torch.bfloat16
    assert LLMBrain._resolve_dtype("fp32") == torch.float32


def test_resolve_dtype_invalid():
    """Invalid quantization raises LLMError."""
    with pytest.raises(LLMError, match="Unsupported quantization"):
        LLMBrain._resolve_dtype("invalid")
