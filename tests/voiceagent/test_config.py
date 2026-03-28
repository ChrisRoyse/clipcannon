"""Tests for voiceagent.config module."""
import json

import pytest

from voiceagent.config import (
    ASRConfig,
    LLMConfig,
    VoiceAgentConfig,
    load_config,
)
from voiceagent.errors import ConfigError


def test_default_config_all_fields():
    c = VoiceAgentConfig()
    assert c.llm.model_path.endswith("9a283b4a5efbc09ce247e0ae5b02b744739e525a/")
    assert c.llm.quantization == "fp8"
    assert c.llm.gpu_memory_utilization == 0.45
    assert c.llm.max_model_len == 32768
    assert c.llm.max_tokens == 512
    assert c.asr.model_name == "Systran/faster-whisper-large-v3"
    assert c.asr.vad_threshold == 0.5
    assert c.asr.endpoint_silence_ms == 600
    assert c.asr.chunk_ms == 200
    assert c.asr.sample_rate == 16000
    assert c.tts.voice_name == "boris"
    assert c.tts.sample_rate == 24000
    assert c.tts.enhance is False
    assert c.conversation.max_history_turns == 50
    assert c.conversation.system_prompt_template is None
    assert c.transport.host == "0.0.0.0"
    assert c.transport.port == 8765
    assert c.transport.ws_path == "/ws"
    assert c.gpu.device == "cuda"
    assert c.gpu.compute_type == "int8"
    assert c.data_dir == "~/.voiceagent"


def test_config_is_frozen():
    c = VoiceAgentConfig()
    with pytest.raises(AttributeError):
        c.data_dir = "/tmp"
    with pytest.raises(AttributeError):
        c.asr = ASRConfig(vad_threshold=0.8)


def test_load_config_missing_file_returns_defaults(tmp_path):
    c = load_config(tmp_path / "nonexistent.json")
    assert c == VoiceAgentConfig()


def test_load_config_valid_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "asr": {"vad_threshold": 0.7, "endpoint_silence_ms": 800},
        "tts": {"voice_name": "nova"},
        "transport": {"port": 9000},
    }))
    c = load_config(config_file)
    assert c.asr.vad_threshold == 0.7
    assert c.asr.endpoint_silence_ms == 800
    assert c.asr.model_name == "Systran/faster-whisper-large-v3"
    assert c.tts.voice_name == "nova"
    assert c.transport.port == 9000
    assert c.llm == LLMConfig()


def test_load_config_invalid_json_raises_config_error(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{invalid json!!!")
    with pytest.raises(ConfigError, match="Invalid JSON"):
        load_config(config_file)


def test_load_config_vad_threshold_out_of_range(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"asr": {"vad_threshold": 5.0}}))
    with pytest.raises(ConfigError, match="out of range"):
        load_config(config_file)


def test_load_config_partial_preserves_defaults(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"data_dir": "/data/agent"}))
    c = load_config(config_file)
    assert c.data_dir == "/data/agent"
    assert c.llm == LLMConfig()
    assert c.asr == ASRConfig()


def test_load_config_unknown_keys_ignored(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "asr": {"vad_threshold": 0.6, "unknown_field": 42},
        "totally_unknown_section": {"a": 1},
    }))
    c = load_config(config_file)
    assert c.asr.vad_threshold == 0.6


def test_load_config_non_dict_raises_config_error(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(ConfigError, match="JSON object"):
        load_config(config_file)


def test_load_config_empty_file_raises(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("")
    with pytest.raises(ConfigError, match="Invalid JSON"):
        load_config(config_file)


def test_load_config_port_out_of_range(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"transport": {"port": 99999}}))
    with pytest.raises(ConfigError, match="out of range"):
        load_config(config_file)
