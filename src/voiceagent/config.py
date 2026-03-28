"""Voice agent configuration system.

All config classes are frozen dataclasses (immutable after creation).
load_config() reads from ~/.voiceagent/config.json with sensible defaults.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from voiceagent.errors import ConfigError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMConfig:
    model_path: str = "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/"
    quantization: str = "fp8"
    gpu_memory_utilization: float = 0.45
    max_model_len: int = 32768
    max_tokens: int = 512


@dataclass(frozen=True)
class ASRConfig:
    model_name: str = "Systran/faster-whisper-large-v3"
    vad_threshold: float = 0.5
    endpoint_silence_ms: int = 600
    chunk_ms: int = 200
    sample_rate: int = 16000


@dataclass(frozen=True)
class TTSConfig:
    voice_name: str = "boris"
    sample_rate: int = 24000
    enhance: bool = False


@dataclass(frozen=True)
class ConversationConfig:
    max_history_turns: int = 50
    system_prompt_template: str | None = None


@dataclass(frozen=True)
class TransportConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    ws_path: str = "/ws"


@dataclass(frozen=True)
class GPUConfig:
    device: str = "cuda"
    compute_type: str = "int8"


@dataclass(frozen=True)
class VoiceAgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    conversation: ConversationConfig = field(default_factory=ConversationConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    gpu: GPUConfig = field(default_factory=GPUConfig)
    data_dir: str = "~/.voiceagent"


_SECTION_MAP: dict[str, type] = {
    "llm": LLMConfig,
    "asr": ASRConfig,
    "tts": TTSConfig,
    "conversation": ConversationConfig,
    "transport": TransportConfig,
    "gpu": GPUConfig,
}

_RANGE_CHECKS: dict[str, dict[str, tuple[float, float]]] = {
    "asr": {"vad_threshold": (0.0, 1.0), "endpoint_silence_ms": (100, 5000)},
    "llm": {"gpu_memory_utilization": (0.1, 1.0), "max_tokens": (1, 131072)},
    "transport": {"port": (1, 65535)},
}


def _validate_range(section: str, key: str, value: float | int, low: float | int, high: float | int) -> None:
    if not (low <= value <= high):
        raise ConfigError(
            f"Config [{section}].{key} = {value!r} is out of range [{low}, {high}]. "
            f"Fix: set {key} to a value between {low} and {high} in ~/.voiceagent/config.json"
        )


def _build_section(section_name: str, cls: type, data: dict) -> object:
    valid_fields = {f.name: f for f in dataclasses.fields(cls)}
    filtered = {}
    for k, v in data.items():
        if k in valid_fields:
            filtered[k] = v
    try:
        instance = cls(**filtered)
    except TypeError as e:
        raise ConfigError(
            f"Invalid config for [{section_name}]: {e}. "
            f"Fix: check field names and types in ~/.voiceagent/config.json"
        ) from e
    checks = _RANGE_CHECKS.get(section_name, {})
    for key, (low, high) in checks.items():
        _validate_range(section_name, key, getattr(instance, key), low, high)
    return instance


def load_config(path: str | Path | None = None) -> VoiceAgentConfig:
    """Load config from JSON file, returning defaults if file does not exist.

    Args:
        path: Path to config JSON file. Defaults to ~/.voiceagent/config.json.

    Returns:
        VoiceAgentConfig with values from file merged over defaults.

    Raises:
        ConfigError: If JSON is malformed or field values are invalid.
    """
    if path is None:
        path = Path.home() / ".voiceagent" / "config.json"
    path = Path(path).expanduser()

    if not path.exists():
        return VoiceAgentConfig()

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Cannot read config file {path}: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"Invalid JSON in config file {path}: {e}. "
            f"Fix: validate your JSON at ~/.voiceagent/config.json"
        ) from e

    if not isinstance(data, dict):
        raise ConfigError(
            f"Config file must contain a JSON object (dict), got {type(data).__name__}. "
            f"Fix: ensure ~/.voiceagent/config.json starts with {{ and ends with }}"
        )

    kwargs: dict = {}
    for section_name, cls in _SECTION_MAP.items():
        if section_name in data and isinstance(data[section_name], dict):
            kwargs[section_name] = _build_section(section_name, cls, data[section_name])

    if "data_dir" in data:
        kwargs["data_dir"] = str(data["data_dir"])

    return VoiceAgentConfig(**kwargs)
