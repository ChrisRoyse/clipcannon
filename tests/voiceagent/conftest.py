"""Session-scoped shared fixtures for voiceagent tests.

Loads expensive GPU models (LLM, TTS, ASR, VAD, wake word) exactly ONCE
for the entire test session, eliminating redundant model loads across
test files.
"""
import pytest
import torch

MODEL_PATH = (
    "/home/cabdru/.cache/huggingface/hub/"
    "models--Qwen--Qwen3-14B-FP8/snapshots/"
    "9a283b4a5efbc09ce247e0ae5b02b744739e525a/"
)


@pytest.fixture(scope="session")
def check_gpu():
    """Verify CUDA GPU is available. Fails the session early if not."""
    if not torch.cuda.is_available():
        pytest.fail("CUDA GPU required for voiceagent tests.")


@pytest.fixture(scope="session")
def session_vad(check_gpu):
    """SileroVAD loaded once for the entire session."""
    from voiceagent.asr.vad import SileroVAD
    return SileroVAD(threshold=0.5)


@pytest.fixture(scope="session")
def session_asr(check_gpu):
    """StreamingASR loaded once for the entire session."""
    from voiceagent.asr.streaming import StreamingASR

    class ASRConfig:
        model_name = "Systran/faster-whisper-large-v3"
        vad_threshold = 0.5
        endpoint_silence_ms = 600
        chunk_ms = 200

    return StreamingASR(ASRConfig())


@pytest.fixture(scope="session")
def session_llm_brain(check_gpu):
    """LLMBrain (Qwen3-14B-FP8) loaded once, released at session end."""
    from voiceagent.brain.llm import LLMBrain

    class LLMTestConfig:
        model_path = MODEL_PATH
        quantization = "fp8"
        gpu_memory_utilization = 0.45
        max_model_len = 32768
        max_tokens = 64

    brain = LLMBrain(LLMTestConfig())
    yield brain
    brain.release()


@pytest.fixture(scope="session")
def session_tts_adapter(check_gpu):
    """ClipCannonAdapter loaded once, released at session end."""
    from voiceagent.adapters.clipcannon import ClipCannonAdapter
    adapter = ClipCannonAdapter(voice_name="boris")
    yield adapter
    adapter.release()


@pytest.fixture(scope="session")
def session_wake_word(check_gpu):
    """WakeWordDetector loaded once for the entire session."""
    pytest.importorskip(
        "openwakeword", reason="openwakeword not installed"
    )
    from voiceagent.activation.wake_word import WakeWordDetector
    return WakeWordDetector()
