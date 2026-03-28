```xml
<task_spec id="TASK-VA-002" version="2.0">
<metadata>
  <title>Configuration -- VoiceAgentConfig Frozen Dataclass and Config Loading</title>
  <status>ready</status>
  <layer>foundation</layer>
  <sequence>2</sequence>
  <implements>
    <item ref="PHASE1-CONFIG">VoiceAgentConfig frozen dataclass with nested sections</item>
    <item ref="PHASE1-CONFIG-LOAD">Config file loading from ~/.voiceagent/config.json</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-001</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>2 files (config.py + test_config.py)</estimated_files>
</metadata>

<context>
Creates the configuration system for the voice agent. The VoiceAgentConfig is a FROZEN
dataclass (immutable after creation) that holds all settings organized into nested
sub-configs: LLMConfig, ASRConfig, TTSConfig, ConversationConfig, TransportConfig,
GPUConfig. A load_config() function reads from ~/.voiceagent/config.json with sensible
defaults. Almost every subsequent task depends on this config being available.

IMPORTANT CONTEXT:
- Working directory: /home/cabdru/clipcannon
- src/voiceagent/ is created by TASK-VA-001 (must be complete first)
- All import/run commands MUST use PYTHONPATH=src:
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "..."
- Python 3.12+ required (NOT 3.11)
- Config file path: ~/.voiceagent/config.json
- Data directory: ~/.voiceagent/ (in Docker: /data/agent/)
- The LLM model is Qwen3-14B-FP8 at a specific local path (see defaults below)
- Default voice profile: "boris"
- Default WebSocket port: 8765
- Default ASR endpoint silence: 600ms
- Default VAD threshold: 0.5
- NO external dependencies -- only stdlib (dataclasses, json, pathlib)
- NO Pydantic -- use frozen dataclasses with manual validation
- src/voiceagent/errors.py already exists with ConfigError class
</context>

<input_context_files>
  <file purpose="package_structure">src/voiceagent/__init__.py</file>
  <file purpose="error_types">src/voiceagent/errors.py -- contains ConfigError</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-001 complete: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.errors import ConfigError; print('OK')"</check>
  <check>Python 3.12+ available: python3 --version must show 3.12 or higher</check>
</prerequisites>

<scope>
  <in_scope>
    - src/voiceagent/config.py with ALL config dataclasses and load_config() function
    - LLMConfig: model_path, quantization, gpu_memory_utilization, max_model_len, max_tokens
    - ASRConfig: model_name, vad_threshold, endpoint_silence_ms, chunk_ms, sample_rate
    - TTSConfig: voice_name, sample_rate, enhance
    - ConversationConfig: max_history_turns, system_prompt_template
    - TransportConfig: host, port, ws_path
    - GPUConfig: device, compute_type
    - VoiceAgentConfig: all sub-configs + data_dir
    - load_config(path) reads JSON, returns VoiceAgentConfig
    - Validation: raise ConfigError for bad types, out-of-range values, malformed JSON
    - tests/voiceagent/test_config.py with comprehensive tests
  </in_scope>
  <out_of_scope>
    - Database configuration (TASK-VA-003)
    - Runtime config changes (config is frozen/immutable)
    - Config file creation wizard
    - Pydantic or any external validation library
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/config.py">
      """Voice agent configuration system.

      All config classes are frozen dataclasses (immutable after creation).
      load_config() reads from ~/.voiceagent/config.json with sensible defaults.
      """
      from dataclasses import dataclass, field
      from pathlib import Path
      import json
      from voiceagent.errors import ConfigError

      @dataclass(frozen=True)
      class LLMConfig:
          model_path: str = "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/"
          quantization: str = "fp8"
          gpu_memory_utilization: float = 0.45
          max_model_len: int = 32768
          max_tokens: int = 512

      @dataclass(frozen=True)
      class ASRConfig:
          model_name: str = "distil-whisper-large-v3"
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

      def load_config(path: str | Path | None = None) -> VoiceAgentConfig: ...
    </signature>
  </signatures>

  <constraints>
    - ALL dataclasses use frozen=True (immutable after creation)
    - All fields have sensible defaults so VoiceAgentConfig() works with no args
    - load_config() returns default config if file does not exist (no error)
    - load_config() raises ConfigError for malformed JSON (json.JSONDecodeError)
    - load_config() raises ConfigError for invalid field types (e.g., vad_threshold="abc")
    - load_config() raises ConfigError for out-of-range values (e.g., vad_threshold=5.0)
    - data_dir defaults to ~/.voiceagent
    - model_path uses the EXACT Qwen3-14B-FP8 path shown in defaults
    - Only stdlib: dataclasses, json, pathlib -- NO pydantic, NO attrs
    - Use pathlib.Path for file operations
    - Partial config JSON must work: missing sections get defaults, present sections override
    - Unknown keys in JSON are silently ignored (forward compatibility)
    - All errors raise ConfigError with a clear message explaining what is wrong and how to fix it
  </constraints>

  <verification>
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.config import VoiceAgentConfig; c = VoiceAgentConfig(); print(c.llm.model_path)"
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.config import load_config; c = load_config(); print(c.asr.vad_threshold)"
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_config.py -v
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/config.py:
  """Voice agent configuration system.

  All config classes are frozen dataclasses (immutable after creation).
  load_config() reads from ~/.voiceagent/config.json with sensible defaults.
  """
  from dataclasses import dataclass, field
  from pathlib import Path
  import json
  from voiceagent.errors import ConfigError

  @dataclass(frozen=True)
  class LLMConfig:
      model_path: str = "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/"
      quantization: str = "fp8"
      gpu_memory_utilization: float = 0.45
      max_model_len: int = 32768
      max_tokens: int = 512

  @dataclass(frozen=True)
  class ASRConfig:
      model_name: str = "distil-whisper-large-v3"
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

  # Map of section name -> (dataclass, valid_fields_with_types)
  _SECTION_MAP = {
      "llm": LLMConfig,
      "asr": ASRConfig,
      "tts": TTSConfig,
      "conversation": ConversationConfig,
      "transport": TransportConfig,
      "gpu": GPUConfig,
  }

  def _validate_range(section: str, key: str, value, low, high) -> None:
      """Raise ConfigError if value is outside [low, high]."""
      if not (low <= value <= high):
          raise ConfigError(
              f"Config [{section}].{key} = {value!r} is out of range [{low}, {high}]. "
              f"Fix: set {key} to a value between {low} and {high} in ~/.voiceagent/config.json"
          )

  def _build_section(section_name: str, cls: type, data: dict) -> object:
      """Build a frozen dataclass instance from a dict, ignoring unknown keys."""
      import dataclasses
      valid_fields = {f.name: f for f in dataclasses.fields(cls)}
      filtered = {}
      for k, v in data.items():
          if k in valid_fields:
              # Type check: ensure v matches the expected type
              expected_type = valid_fields[k].type
              # Handle str | None specially
              if expected_type == "str | None":
                  if v is not None and not isinstance(v, str):
                      raise ConfigError(
                          f"Config [{section_name}].{k} must be str or null, got {type(v).__name__}. "
                          f"Fix: set {k} to a string or null in ~/.voiceagent/config.json"
                      )
              filtered[k] = v
          # Unknown keys silently ignored
      instance = cls(**filtered)
      # Range validation
      if section_name == "asr":
          _validate_range("asr", "vad_threshold", instance.vad_threshold, 0.0, 1.0)
          _validate_range("asr", "endpoint_silence_ms", instance.endpoint_silence_ms, 100, 5000)
      if section_name == "llm":
          _validate_range("llm", "gpu_memory_utilization", instance.gpu_memory_utilization, 0.1, 1.0)
          _validate_range("llm", "max_tokens", instance.max_tokens, 1, 131072)
      if section_name == "transport":
          _validate_range("transport", "port", instance.port, 1, 65535)
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

      # Build each section
      kwargs = {}
      for section_name, cls in _SECTION_MAP.items():
          if section_name in data and isinstance(data[section_name], dict):
              try:
                  kwargs[section_name] = _build_section(section_name, cls, data[section_name])
              except TypeError as e:
                  raise ConfigError(
                      f"Invalid config for [{section_name}]: {e}. "
                      f"Fix: check field names and types in ~/.voiceagent/config.json"
                  ) from e

      if "data_dir" in data:
          kwargs["data_dir"] = str(data["data_dir"])

      return VoiceAgentConfig(**kwargs)

tests/voiceagent/test_config.py:
  """Tests for voiceagent.config module."""
  import json
  import pytest
  from pathlib import Path
  from voiceagent.config import (
      VoiceAgentConfig, LLMConfig, ASRConfig, TTSConfig,
      ConversationConfig, TransportConfig, GPUConfig, load_config,
  )
  from voiceagent.errors import ConfigError

  def test_default_config_all_fields():
      c = VoiceAgentConfig()
      assert c.llm.model_path == "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/"
      assert c.llm.quantization == "fp8"
      assert c.llm.gpu_memory_utilization == 0.45
      assert c.llm.max_model_len == 32768
      assert c.llm.max_tokens == 512
      assert c.asr.model_name == "distil-whisper-large-v3"
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
      assert c.asr.model_name == "distil-whisper-large-v3"  # default preserved
      assert c.tts.voice_name == "nova"
      assert c.transport.port == 9000
      assert c.llm == LLMConfig()  # untouched section gets defaults

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
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/config.py">VoiceAgentConfig frozen dataclass and load_config function</file>
  <file path="tests/voiceagent/__init__.py">Test package init (empty, just a docstring)</file>
  <file path="tests/voiceagent/test_config.py">Unit tests for config loading and validation</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>VoiceAgentConfig() instantiates with all defaults -- every field has a value</criterion>
  <criterion>All dataclasses are frozen (immutable) -- assignment raises AttributeError</criterion>
  <criterion>load_config() returns defaults when no config file exists</criterion>
  <criterion>load_config(path) reads and parses valid JSON, merging over defaults</criterion>
  <criterion>load_config(path) raises ConfigError for malformed JSON</criterion>
  <criterion>load_config(path) raises ConfigError for out-of-range values</criterion>
  <criterion>Partial config JSON preserves defaults for missing sections</criterion>
  <criterion>Unknown JSON keys are silently ignored</criterion>
  <criterion>All tests pass with: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_config.py -v</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_config.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.config import VoiceAgentConfig; c = VoiceAgentConfig(); assert c.asr.vad_threshold == 0.5; assert c.tts.voice_name == 'boris'; assert c.transport.port == 8765; assert c.asr.endpoint_silence_ms == 600; print('All defaults OK')"</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.config import VoiceAgentConfig; c = VoiceAgentConfig(); c.data_dir = 'x'" 2>&1 | grep -q "AttributeError" && echo "Frozen OK" || echo "FAIL: config is not frozen"</command>
</test_commands>

<full_state_verification>
  <source_of_truth>
    The loaded VoiceAgentConfig object's attributes are the source of truth.
    Files on disk:
      /home/cabdru/clipcannon/src/voiceagent/config.py
      /home/cabdru/clipcannon/tests/voiceagent/__init__.py
      /home/cabdru/clipcannon/tests/voiceagent/test_config.py
    The config file itself: ~/.voiceagent/config.json (may or may not exist)
  </source_of_truth>

  <execute_and_inspect>
    Step 1: Create src/voiceagent/config.py with all dataclasses and load_config().
    Step 2: Create tests/voiceagent/__init__.py and tests/voiceagent/test_config.py.
    Step 3: Run `ls -la /home/cabdru/clipcannon/src/voiceagent/config.py` to prove it exists.
    Step 4: Run `cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.config import VoiceAgentConfig; print(VoiceAgentConfig())"` to prove it imports and instantiates.
    Step 5: Run `cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.config import load_config; c = load_config(); print(c)"` to prove load_config works with no config file.
    Step 6: Run `cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_config.py -v` to prove all tests pass.
  </execute_and_inspect>

  <edge_case_audit>
    Edge case 1: Config file is empty string
      Create file with empty content "", call load_config(path)
      Expected: ConfigError with "Invalid JSON" message (empty string is not valid JSON)

    Edge case 2: Config file is valid JSON but not a dict (e.g., a JSON array)
      Create file with "[1, 2, 3]", call load_config(path)
      Expected: ConfigError with "JSON object" message

    Edge case 3: VAD threshold set to negative value
      Create file with {"asr": {"vad_threshold": -0.5}}
      Expected: ConfigError with "out of range" message

    Edge case 4: Trying to mutate frozen config
      c = VoiceAgentConfig(); c.data_dir = "/tmp"
      Expected: AttributeError (frozen dataclass)

    Edge case 5: Config file exists but is not readable (permissions)
      Create file, chmod 000, call load_config(path)
      Expected: ConfigError with "Cannot read" message
  </edge_case_audit>

  <evidence_of_success>
    Command 1: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.config import VoiceAgentConfig
c = VoiceAgentConfig()
assert c.llm.model_path.endswith('9a283b4a5efbc09ce247e0ae5b02b744739e525a/')
assert c.asr.vad_threshold == 0.5
assert c.asr.endpoint_silence_ms == 600
assert c.tts.voice_name == 'boris'
assert c.transport.port == 8765
assert c.asr.sample_rate == 16000
print('All default values verified')
"
    Must print: All default values verified

    Command 2: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_config.py -v
    Must show: all tests PASSED, 0 failures

    Command 3: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.config import VoiceAgentConfig
c = VoiceAgentConfig()
try:
    c.data_dir = 'x'
    print('FAIL: should have raised AttributeError')
except AttributeError:
    print('OK: config is frozen')
"
    Must print: OK: config is frozen
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  Test config JSON file (write to tmp_path / "config.json" in tests):

  Input JSON:
  {
    "llm": {
      "max_tokens": 1024,
      "gpu_memory_utilization": 0.8
    },
    "asr": {
      "vad_threshold": 0.7,
      "endpoint_silence_ms": 800,
      "sample_rate": 16000
    },
    "tts": {
      "voice_name": "nova",
      "sample_rate": 22050
    },
    "conversation": {
      "max_history_turns": 20,
      "system_prompt_template": "You are a helpful assistant."
    },
    "transport": {
      "host": "127.0.0.1",
      "port": 9000,
      "ws_path": "/audio"
    },
    "gpu": {
      "device": "cuda:1",
      "compute_type": "float16"
    },
    "data_dir": "/data/agent"
  }

  Expected VoiceAgentConfig attributes after load_config():
    c.llm.max_tokens == 1024
    c.llm.gpu_memory_utilization == 0.8
    c.llm.model_path == "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/"  # default preserved
    c.asr.vad_threshold == 0.7
    c.asr.endpoint_silence_ms == 800
    c.asr.sample_rate == 16000
    c.tts.voice_name == "nova"
    c.tts.sample_rate == 22050
    c.conversation.max_history_turns == 20
    c.conversation.system_prompt_template == "You are a helpful assistant."
    c.transport.host == "127.0.0.1"
    c.transport.port == 9000
    c.transport.ws_path == "/audio"
    c.gpu.device == "cuda:1"
    c.gpu.compute_type == "float16"
    c.data_dir == "/data/agent"

  Invalid input 1: {"asr": {"vad_threshold": 5.0}}
  Expected: ConfigError raised, message contains "out of range"

  Invalid input 2: "{not valid json"
  Expected: ConfigError raised, message contains "Invalid JSON"

  Invalid input 3: [1, 2, 3]
  Expected: ConfigError raised, message contains "JSON object"
</synthetic_test_data>

<manual_verification>
  The implementing agent MUST perform these checks AFTER creating all files:

  1. Run: ls -la /home/cabdru/clipcannon/src/voiceagent/config.py
     Verify: File exists, non-zero size

  2. Run: ls -la /home/cabdru/clipcannon/tests/voiceagent/test_config.py
     Verify: File exists, non-zero size

  3. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.config import VoiceAgentConfig, load_config
from voiceagent.config import LLMConfig, ASRConfig, TTSConfig, ConversationConfig, TransportConfig, GPUConfig
print('All imports OK')
"
     Verify: "All imports OK" printed

  4. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.config import VoiceAgentConfig
c = VoiceAgentConfig()
print(f'vad_threshold={c.asr.vad_threshold}')
print(f'endpoint_silence_ms={c.asr.endpoint_silence_ms}')
print(f'voice_name={c.tts.voice_name}')
print(f'port={c.transport.port}')
print(f'data_dir={c.data_dir}')
"
     Verify: vad_threshold=0.5, endpoint_silence_ms=600, voice_name=boris, port=8765, data_dir=~/.voiceagent

  5. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_config.py -v
     Verify: All tests PASSED

  6. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.config import VoiceAgentConfig
c = VoiceAgentConfig()
try:
    c.data_dir = '/tmp'
except AttributeError:
    print('Frozen OK')
"
     Verify: "Frozen OK" printed
</manual_verification>
</task_spec>
```
