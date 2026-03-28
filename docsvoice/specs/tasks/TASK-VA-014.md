```xml
<task_spec id="TASK-VA-014" version="2.0">
<metadata>
  <title>Wake Word Detector -- OpenWakeWord Wrapper</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>14</sequence>
  <implements>
    <item ref="PHASE1-WAKEWORD">WakeWordDetector with detect() using OpenWakeWord</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-002</task_ref>
  </depends_on>
  <estimated_complexity>low</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Wraps the openwakeword library for wake word detection. The detector listens for a
configurable wake word (default "hey_jarvis") in audio chunks and returns a boolean.
This is used by the VoiceAgent orchestrator (TASK-VA-018) to transition from IDLE to
LISTENING state as an alternative to VAD-only activation. Runs on CPU with ONNX
inference for minimal latency.

This is 100% greenfield -- src/voiceagent/ does not exist yet. The implementing agent
must create all directories and files from scratch. Python 3.12+, RTX 5090 GPU.

The openwakeword library expects audio chunks of approximately 1280 samples (80ms at
16kHz). The model is downloaded automatically on first use via
openwakeword.utils.download_models(). If openwakeword is not installed, the code MUST
raise a clear error telling the user to "pip install openwakeword".
</context>

<input_context_files>
  <file purpose="wakeword_spec">docsvoice/01_phase1_core_pipeline.md#section-7.1</file>
  <file purpose="config">src/voiceagent/config.py (create if not exists)</file>
  <file purpose="errors">src/voiceagent/errors.py (create if not exists)</file>
</input_context_files>

<prerequisites>
  <check>Python 3.12+ available: python3 --version</check>
  <check>numpy installed: python3 -c "import numpy; print(numpy.__version__)"</check>
  <check>openwakeword installed: python3 -c "import openwakeword; print(openwakeword.__version__)"</check>
  <check>If openwakeword missing: pip install openwakeword</check>
  <check>If dirs missing, create: mkdir -p src/voiceagent/activation &amp;&amp; touch src/voiceagent/__init__.py src/voiceagent/activation/__init__.py</check>
</prerequisites>

<scope>
  <in_scope>
    - WakeWordDetector class in src/voiceagent/activation/wake_word.py
    - __init__(model_name="hey_jarvis", threshold=0.6) loads OpenWakeWord model
    - detect(audio_chunk: np.ndarray) -> bool
    - Audio: 16kHz, ~1280 samples per chunk (80ms) for openwakeword
    - Downloads model on first use via openwakeword.utils.download_models()
    - Clear error messages for: missing library, model download failure, wrong audio format
    - Unit tests with REAL openwakeword model (NO MOCKS)
  </in_scope>
  <out_of_scope>
    - Custom wake word training
    - Multiple wake word support
    - Hotkey activation (TASK-VA-015)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/activation/wake_word.py">
      import numpy as np

      class WakeWordDetector:
          def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.6) -> None: ...
          def detect(self, audio_chunk: np.ndarray) -> bool: ...
    </signature>
  </signatures>

  <constraints>
    - Uses openwakeword.Model for inference
    - Downloads models on first use via openwakeword.utils.download_models()
    - inference_framework="onnx" for CPU performance
    - threshold default 0.6
    - detect() returns True if any prediction score exceeds threshold
    - detect() returns False for silence and random noise
    - Input audio: 16kHz int16 numpy array, ~1280 samples per chunk
    - If openwakeword is not installed: raise ImportError with message "openwakeword is required. Install with: pip install openwakeword"
    - If model download fails: raise VoiceAgentError with message including the download URL and network error details
    - If audio has wrong dtype or shape: log warning, attempt conversion, fail gracefully
    - All errors logged with what/why/how-to-fix pattern
  </constraints>

  <verification>
    - WakeWordDetector() instantiates and loads model
    - detect(silence) returns False
    - detect(random_noise) returns False
    - detect() returns bool type always
    - Missing openwakeword raises clear ImportError
    - pytest tests/voiceagent/test_wake_word.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/activation/wake_word.py:
  """OpenWakeWord wake word detection."""
  import logging
  import numpy as np

  logger = logging.getLogger(__name__)

  class WakeWordDetector:
      """Detects wake words in audio chunks using openwakeword.

      Args:
          model_name: Wake word model name (default "hey_jarvis").
          threshold: Detection confidence threshold 0.0-1.0 (default 0.6).

      Raises:
          ImportError: If openwakeword is not installed.
          VoiceAgentError: If model download or load fails.
      """

      def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.6):
          self.model_name = model_name
          self.threshold = threshold

          try:
              import openwakeword
          except ImportError:
              raise ImportError(
                  "openwakeword is required for wake word detection. "
                  "Install with: pip install openwakeword"
              )

          try:
              from openwakeword.model import Model as OWWModel
              openwakeword.utils.download_models()
              self._model = OWWModel(
                  wakeword_models=[model_name],
                  inference_framework="onnx",
              )
              logger.info("Wake word model loaded: %s (threshold=%.2f)", model_name, threshold)
          except Exception as e:
              from voiceagent.errors import VoiceAgentError
              raise VoiceAgentError(
                  f"Failed to load wake word model '{model_name}'. "
                  f"What: openwakeword model initialization failed. "
                  f"Why: {e}. "
                  f"Fix: check network connectivity, ensure model name is valid "
                  f"(try 'hey_jarvis', 'alexa', 'hey_mycroft'), "
                  f"or download manually from https://github.com/dscripka/openWakeWord"
              ) from e

      def detect(self, audio_chunk: np.ndarray) -> bool:
          """Detect wake word in audio chunk.

          Args:
              audio_chunk: 16kHz int16 numpy array, ~1280 samples (80ms).

          Returns:
              True if wake word detected with confidence above threshold.
          """
          if not isinstance(audio_chunk, np.ndarray):
              logger.error(
                  "detect() received %s instead of np.ndarray. "
                  "Why: caller passed wrong type. "
                  "Fix: pass numpy array e.g. np.zeros(1280, dtype=np.int16)",
                  type(audio_chunk).__name__,
              )
              return False

          if audio_chunk.size == 0:
              logger.warning("detect() received empty audio array, returning False")
              return False

          # Ensure int16 dtype
          if audio_chunk.dtype != np.int16:
              logger.warning(
                  "detect() received dtype %s, expected int16. Converting.",
                  audio_chunk.dtype,
              )
              audio_chunk = audio_chunk.astype(np.int16)

          prediction = self._model.predict(audio_chunk)
          detected = any(score > self.threshold for score in prediction.values())
          if detected:
              logger.info("Wake word '%s' detected! Scores: %s", self.model_name, prediction)
          return detected

tests/voiceagent/test_wake_word.py:
  """Tests for wake word detector -- uses REAL openwakeword model, NO MOCKS."""
  import numpy as np
  import pytest

  # Skip entire module if openwakeword not installed
  openwakeword = pytest.importorskip("openwakeword", reason="openwakeword not installed")

  from voiceagent.activation.wake_word import WakeWordDetector

  @pytest.fixture(scope="module")
  def detector():
      """Create detector once for all tests (model download is slow)."""
      return WakeWordDetector(model_name="hey_jarvis", threshold=0.6)

  def test_detector_instantiates(detector):
      assert detector is not None
      assert detector.model_name == "hey_jarvis"
      assert detector.threshold == 0.6

  def test_detect_silence_returns_false(detector):
      """Silence (all zeros) should not trigger wake word."""
      silence = np.zeros(1280, dtype=np.int16)
      result = detector.detect(silence)
      assert result is False
      assert isinstance(result, bool)

  def test_detect_random_noise_returns_false(detector):
      """Random noise should not trigger wake word."""
      rng = np.random.default_rng(42)
      noise = rng.integers(-1000, 1000, size=1280, dtype=np.int16)
      result = detector.detect(noise)
      assert result is False
      assert isinstance(result, bool)

  def test_detect_empty_audio_returns_false(detector):
      """Empty array should return False, not crash."""
      empty = np.array([], dtype=np.int16)
      result = detector.detect(empty)
      assert result is False

  def test_detect_returns_bool_type(detector):
      """Return type must always be bool."""
      audio = np.zeros(1280, dtype=np.int16)
      result = detector.detect(audio)
      assert type(result) is bool

  def test_detect_wrong_dtype_still_works(detector):
      """Float32 audio should be auto-converted, not crash."""
      audio = np.zeros(1280, dtype=np.float32)
      result = detector.detect(audio)
      assert isinstance(result, bool)

  def test_detect_multiple_chunks_sequential(detector):
      """Multiple sequential detections should not accumulate false state."""
      silence = np.zeros(1280, dtype=np.int16)
      for _ in range(10):
          result = detector.detect(silence)
          assert result is False

  def test_missing_openwakeword_import_error():
      """Verify the error message tells user how to install."""
      # This test validates the error path exists in the source code.
      # We can't actually test it with openwakeword installed, but we verify
      # the class constructor has the ImportError handler.
      import inspect
      source = inspect.getsource(WakeWordDetector.__init__)
      assert "pip install openwakeword" in source
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/activation/wake_word.py">WakeWordDetector class</file>
  <file path="tests/voiceagent/test_wake_word.py">Unit tests with real openwakeword model</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<full_state_verification>
  <source_of_truth>
    Boolean return value from detector.detect(audio_chunk).
    This is the ONLY output. True = wake word detected. False = not detected.
  </source_of_truth>

  <execute_and_inspect>
    Step 1: Create WakeWordDetector (this downloads model on first use).
    Step 2: Call detect() with known audio input.
    Step 3: Read the boolean return value.
    Step 4: Verify it matches expected output.
    Never assume "no error" means "correct detection". Always check the return value.
  </execute_and_inspect>

  <edge_case_audit>
    <case name="empty_audio">
      <before>detector ready, audio = np.array([], dtype=np.int16)</before>
      <action>detector.detect(audio)</action>
      <after>Returns False, logs warning "empty audio array"</after>
    </case>
    <case name="wrong_sample_rate">
      <before>detector ready, audio at 8kHz instead of 16kHz</before>
      <action>detector.detect(audio_8khz)</action>
      <after>Returns False (openwakeword expects 16kHz, mismatched audio won't match). No crash.</after>
    </case>
    <case name="model_download_fails">
      <before>No network, openwakeword installed but models not cached</before>
      <action>WakeWordDetector()</action>
      <after>VoiceAgentError raised with message containing "check network connectivity" and download URL</after>
    </case>
    <case name="wrong_dtype_input">
      <before>detector ready, audio = np.zeros(1280, dtype=np.float32)</before>
      <action>detector.detect(audio)</action>
      <after>Auto-converts to int16, returns False for silence. Logs warning about dtype.</after>
    </case>
  </edge_case_audit>

  <evidence_of_success>
    cd /home/cabdru/clipcannon

    PYTHONPATH=src python -c "
from voiceagent.activation.wake_word import WakeWordDetector
import numpy as np
d = WakeWordDetector()
print('Model loaded:', d.model_name)
silence = np.zeros(1280, dtype=np.int16)
result = d.detect(silence)
print('Silence detection:', result)
assert result is False, 'Silence should not trigger wake word'
print('PASS')
"

    PYTHONPATH=src python -m pytest tests/voiceagent/test_wake_word.py -v --tb=short
    # All tests must pass
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  <test name="silence_not_detected">
    <input>np.zeros(1280, dtype=np.int16)  # 80ms of silence at 16kHz</input>
    <expected>False</expected>
  </test>
  <test name="noise_not_detected">
    <input>np.random.default_rng(42).integers(-1000, 1000, size=1280, dtype=np.int16)</input>
    <expected>False</expected>
  </test>
  <test name="empty_array">
    <input>np.array([], dtype=np.int16)</input>
    <expected>False (no crash)</expected>
  </test>
  <test name="float32_input">
    <input>np.zeros(1280, dtype=np.float32)</input>
    <expected>False (auto-converted to int16, no crash)</expected>
  </test>
</synthetic_test_data>

<manual_verification>
  <step>1. cd /home/cabdru/clipcannon</step>
  <step>2. Verify openwakeword installed: python3 -c "import openwakeword; print(openwakeword.__version__)"</step>
  <step>3. Verify file exists: ls -la src/voiceagent/activation/wake_word.py</step>
  <step>4. Verify import works: PYTHONPATH=src python -c "from voiceagent.activation.wake_word import WakeWordDetector; print('PASS')"</step>
  <step>5. Verify model loads: PYTHONPATH=src python -c "from voiceagent.activation.wake_word import WakeWordDetector; d = WakeWordDetector(); print('Model:', d.model_name)"</step>
  <step>6. Verify silence detection: PYTHONPATH=src python -c "
import numpy as np
from voiceagent.activation.wake_word import WakeWordDetector
d = WakeWordDetector()
assert d.detect(np.zeros(1280, dtype=np.int16)) is False
print('PASS: silence not detected')
"</step>
  <step>7. Run tests: PYTHONPATH=src python -m pytest tests/voiceagent/test_wake_word.py -v --tb=short</step>
  <step>8. Verify NO mocks: grep -c "mock\|Mock\|MagicMock\|patch" tests/voiceagent/test_wake_word.py  # Should be 0</step>
</manual_verification>

<validation_criteria>
  <criterion>WakeWordDetector loads real openwakeword model on construction</criterion>
  <criterion>detect() returns bool type always</criterion>
  <criterion>Silence audio returns False</criterion>
  <criterion>Random noise returns False</criterion>
  <criterion>Empty audio returns False (no crash)</criterion>
  <criterion>Wrong dtype auto-converts (no crash)</criterion>
  <criterion>Missing openwakeword raises ImportError with install instructions</criterion>
  <criterion>Model download failure raises VoiceAgentError with URL and fix instructions</criterion>
  <criterion>All tests use real openwakeword model, NO mocks</criterion>
  <criterion>All tests pass</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -m pytest tests/voiceagent/test_wake_word.py -v --tb=short</command>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -c "from voiceagent.activation.wake_word import WakeWordDetector; import numpy as np; d = WakeWordDetector(); print('detect silence:', d.detect(np.zeros(1280, dtype=np.int16)))"</command>
</test_commands>
</task_spec>
```
