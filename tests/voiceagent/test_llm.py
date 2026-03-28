"""Tests for LLMBrain -- real model, NO MOCKS. Requires GPU."""
import pytest
import torch
from voiceagent.brain.llm import LLMBrain
from voiceagent.errors import LLMError

MODEL_PATH = "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/"


@pytest.fixture(scope="module")
def check_gpu():
    if not torch.cuda.is_available():
        pytest.fail("CUDA GPU required for LLMBrain tests.")


class LLMConfig:
    model_path = MODEL_PATH
    quantization = "fp8"
    gpu_memory_utilization = 0.45
    max_model_len = 32768
    max_tokens = 64


@pytest.fixture(scope="module")
def brain(check_gpu):
    b = LLMBrain(LLMConfig())
    yield b
    b.release()


def test_llm_loads_to_gpu(brain, check_gpu):
    vram_gb = torch.cuda.memory_allocated() / (1024 ** 3)
    print(f"VRAM: {vram_gb:.2f} GB")
    assert vram_gb > 1.0, f"Expected >1GB VRAM, got {vram_gb:.2f}GB"


def test_build_chat_prompt(brain):
    messages = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "Hello"}]
    prompt = brain._build_chat_prompt(messages)
    assert isinstance(prompt, str) and len(prompt) > 0 and "Hello" in prompt


def test_build_chat_prompt_empty_raises(brain):
    with pytest.raises(LLMError, match="Empty messages"):
        brain._build_chat_prompt([])


@pytest.mark.asyncio
async def test_generate_stream_yields_text(brain):
    messages = [{"role": "user", "content": "Say hello in one word."}]
    tokens = []
    async for token in brain.generate_stream(messages):
        tokens.append(token)
    full = "".join(tokens)
    print(f"Generated: {full[:200]}")
    assert len(full) > 0


@pytest.mark.asyncio
async def test_generate_stream_empty_messages_raises(brain):
    with pytest.raises(LLMError, match="Empty messages"):
        async for _ in brain.generate_stream([]):
            pass


def test_llm_error_on_bad_path(check_gpu):
    class BadConfig:
        model_path = "/nonexistent/model"
        quantization = "fp8"
        gpu_memory_utilization = 0.45
        max_model_len = 32768
        max_tokens = 64
    with pytest.raises(LLMError):
        LLMBrain(BadConfig())
