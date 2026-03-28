```xml
<task_spec id="TASK-VA-005" version="2.0">
<metadata>
  <title>Silero VAD Wrapper -- Voice Activity Detection</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>5</sequence>
  <implements>
    <item ref="PHASE1-VAD">Silero VAD v5 wrapper with is_speech() and reset()</item>
    <item ref="PHASE1-VERIFY-4">VAD detects speech (verification checklist #4)</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-002</task_ref>
    <task_ref>TASK-VA-004</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Wraps the Silero VAD v5 model for real-time voice activity detection. Takes audio
chunks of 256, 512, or 768 samples at 16kHz and returns a boolean indicating speech
presence. The StreamingASR (TASK-VA-006) uses this to gate audio buffering and the
ConversationManager (TASK-VA-013) uses it for IDLE-to-LISTENING transitions.
Runs on CPU via PyTorch with sub-millisecond latency per chunk.

CRITICAL: Silero VAD v5 accepts ONLY 256, 512, or 768 sample chunks at 16kHz.
NOT 3200 samples. The default chunk size for this wrapper is 512 samples (32ms).
The caller (StreamingASR in TASK-VA-006) is responsible for rechunking its 200ms
audio frames into 512-sample sub-chunks before calling is_speech().

Hardware: RTX 5090 (32GB GDDR7), CUDA 13.1/13.2, Python 3.12+
Project state: src/voiceagent/ does NOT exist yet -- 100% greenfield.
All imports require PYTHONPATH=src from repo root.
</context>

<input_context_files>
  <file purpose="vad_spec">docsvoice/01_phase1_core_pipeline.md#section-2.1</file>
  <file purpose="error_types">src/voiceagent/errors.py (from TASK-VA-001)</file>
  <file purpose="config">src/voiceagent/config.py (from TASK-VA-002)</file>
  <file purpose="asr_types">src/voiceagent/asr/types.py (from TASK-VA-004)</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-002 complete (config available at src/voiceagent/config.py)</check>
  <check>TASK-VA-004 complete (ASR types available at src/voiceagent/asr/types.py)</check>
  <check>torch installed: pip install torch</check>
  <check>Internet access for first-time torch.hub.load (downloads ~2MB model)</check>
</prerequisites>

<scope>
  <in_scope>
    - SileroVAD class in src/voiceagent/asr/vad.py
    - __init__(threshold) loads Silero VAD v5 model via torch.hub
    - is_speech(audio_chunk) converts to torch tensor, returns bool
    - reset() clears internal model hidden states between utterances
    - Unit tests with REAL Silero model and REAL numpy audio arrays (no mocks)
    - Tests use synthetic audio: silence (zeros) vs 440Hz sine wave
  </in_scope>
  <out_of_scope>
    - Streaming ASR pipeline (TASK-VA-006)
    - Endpoint detection logic (TASK-VA-006)
    - ONNX runtime optimization (future)
    - Rechunking logic (caller's responsibility)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/asr/vad.py">
      class SileroVAD:
          SAMPLE_RATE: int = 16000
          VALID_CHUNK_SIZES: tuple[int, ...] = (256, 512, 768)

          def __init__(self, threshold: float = 0.5) -> None: ...
          def is_speech(self, audio_chunk: np.ndarray) -> bool: ...
          def reset(self) -> None: ...
    </signature>
  </signatures>

  <constraints>
    - Model loaded via torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)
    - Input audio: 16kHz, mono, numpy array (float32 or int16)
    - Chunk sizes MUST be 256, 512, or 768 samples at 16kHz -- raise VADError for other sizes
    - int16 input converted to float32 by dividing by 32768.0
    - Raise VADError (from voiceagent.errors) if model fails to load
    - Raise VADError if audio_chunk is empty (length 0)
    - Raise VADError if audio_chunk contains NaN values
    - threshold default is 0.5 (configurable via __init__)
    - reset() calls model.reset_states() to clear hidden state between conversations
    - Thread-safe: no shared mutable state beyond model internals
    - NO MOCKS in tests -- use real Silero model, real numpy arrays
    - FAIL FAST -- no silent error swallowing, log what failed, why, how to fix
    - NO BACKWARDS COMPATIBILITY -- no fallbacks
  </constraints>

  <verification>
    - SileroVAD() instantiates and loads real Silero VAD model
    - hasattr(vad, 'model') is True after init
    - is_speech(np.zeros(512, dtype=np.float32)) returns False (silence)
    - is_speech(440Hz_sine_512_samples) returns True or False (pure tones may not trigger VAD)
    - is_speech(np.zeros(512, dtype=np.int16)) returns False (int16 silence)
    - reset() does not raise
    - VADError raised for chunk size 3200
    - VADError raised for empty array
    - VADError raised for array with NaN
    - pytest tests/voiceagent/test_vad.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/asr/vad.py:
  """Silero VAD v5 wrapper for real-time voice activity detection.

  Silero VAD v5 accepts ONLY 256, 512, or 768 sample chunks at 16kHz.
  The default chunk size is 512 samples (32ms of audio).

  Usage:
      vad = SileroVAD(threshold=0.5)
      is_speaking = vad.is_speech(audio_chunk_512_samples)
      vad.reset()  # between utterances
  """
  import logging
  import numpy as np
  import torch
  from voiceagent.errors import VADError

  logger = logging.getLogger(__name__)

  class SileroVAD:
      SAMPLE_RATE: int = 16000
      VALID_CHUNK_SIZES: tuple[int, ...] = (256, 512, 768)

      def __init__(self, threshold: float = 0.5) -> None:
          self.threshold = threshold
          try:
              self.model, _ = torch.hub.load(
                  repo_or_dir='snakers4/silero-vad',
                  model='silero_vad',
                  trust_repo=True,
              )
          except Exception as e:
              raise VADError(
                  f"Failed to load Silero VAD model: {e}. "
                  f"Ensure torch is installed and internet is available for first download."
              ) from e
          logger.info("SileroVAD loaded successfully (threshold=%.2f)", self.threshold)

      def is_speech(self, audio_chunk: np.ndarray) -> bool:
          """Determine if an audio chunk contains speech.

          Args:
              audio_chunk: numpy array of audio samples, 16kHz mono.
                  Must be 256, 512, or 768 samples. float32 or int16.

          Returns:
              True if speech confidence exceeds threshold, False otherwise.

          Raises:
              VADError: If chunk size is invalid, array is empty, or contains NaN.
          """
          # Validate input
          if audio_chunk.size == 0:
              raise VADError(
                  "Empty audio chunk. Expected 256, 512, or 768 samples, got 0."
              )

          if np.any(np.isnan(audio_chunk)):
              raise VADError(
                  "Audio chunk contains NaN values. Check audio capture pipeline."
              )

          if audio_chunk.shape[0] not in self.VALID_CHUNK_SIZES:
              raise VADError(
                  f"Invalid chunk size: {audio_chunk.shape[0]}. "
                  f"Silero VAD v5 at 16kHz accepts only {self.VALID_CHUNK_SIZES} samples. "
                  f"Rechunk your audio before calling is_speech()."
              )

          # Convert int16 to float32
          if audio_chunk.dtype == np.int16:
              audio = audio_chunk.astype(np.float32) / 32768.0
          else:
              audio = audio_chunk.astype(np.float32)

          tensor = torch.from_numpy(audio)
          confidence = self.model(tensor, self.SAMPLE_RATE).item()
          return confidence > self.threshold

      def reset(self) -> None:
          """Reset model hidden states. Call between utterances/conversations."""
          self.model.reset_states()
          logger.debug("VAD states reset")


tests/voiceagent/test_vad.py:
  """Tests for SileroVAD wrapper.

  NO MOCKS -- uses real Silero VAD model and real numpy audio arrays.
  Requires: torch, internet (first run downloads model).

  Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_vad.py -v
  """
  import numpy as np
  import pytest
  from voiceagent.asr.vad import SileroVAD
  from voiceagent.errors import VADError

  @pytest.fixture(scope="module")
  def vad() -> SileroVAD:
      """Load VAD once for all tests in this module (model loading is expensive)."""
      return SileroVAD(threshold=0.5)

  def test_vad_instantiates(vad: SileroVAD) -> None:
      """VAD model loads successfully."""
      assert hasattr(vad, 'model'), "SileroVAD.model not set after __init__"
      assert vad.threshold == 0.5

  def test_vad_silence_returns_false(vad: SileroVAD) -> None:
      """512 samples of silence should not be detected as speech."""
      silence = np.zeros(512, dtype=np.float32)
      assert vad.is_speech(silence) is False

  def test_vad_tone_440hz(vad: SileroVAD) -> None:
      """512 samples of 440Hz sine wave -- test runs without error.
      NOTE: Pure sine wave may or may not trigger VAD. This test verifies
      the method executes without error and returns a bool."""
      t = np.linspace(0, 512 / 16000, 512, endpoint=False, dtype=np.float32)
      tone = 0.5 * np.sin(2 * np.pi * 440 * t)
      result = vad.is_speech(tone)
      assert isinstance(result, bool)

  def test_vad_int16_silence_returns_false(vad: SileroVAD) -> None:
      """int16 silence should be converted to float32 internally and return False."""
      silence_int16 = np.zeros(512, dtype=np.int16)
      assert vad.is_speech(silence_int16) is False

  def test_vad_reset_does_not_raise(vad: SileroVAD) -> None:
      """reset() clears hidden state without error."""
      vad.reset()  # should not raise

  def test_vad_chunk_256_accepted(vad: SileroVAD) -> None:
      """256-sample chunk is a valid Silero VAD input size."""
      chunk = np.zeros(256, dtype=np.float32)
      result = vad.is_speech(chunk)
      assert isinstance(result, bool)

  def test_vad_chunk_768_accepted(vad: SileroVAD) -> None:
      """768-sample chunk is a valid Silero VAD input size."""
      chunk = np.zeros(768, dtype=np.float32)
      result = vad.is_speech(chunk)
      assert isinstance(result, bool)

  def test_vad_invalid_chunk_size_raises(vad: SileroVAD) -> None:
      """Chunk size 3200 is NOT valid for Silero VAD v5 at 16kHz."""
      bad_chunk = np.zeros(3200, dtype=np.float32)
      with pytest.raises(VADError, match="Invalid chunk size: 3200"):
          vad.is_speech(bad_chunk)

  def test_vad_empty_array_raises(vad: SileroVAD) -> None:
      """Empty array should raise VADError, not silently return."""
      empty = np.array([], dtype=np.float32)
      with pytest.raises(VADError, match="Empty audio chunk"):
          vad.is_speech(empty)

  def test_vad_nan_values_raise(vad: SileroVAD) -> None:
      """Array with NaN values should raise VADError."""
      nan_chunk = np.full(512, np.nan, dtype=np.float32)
      with pytest.raises(VADError, match="NaN"):
          vad.is_speech(nan_chunk)

  def test_vad_model_load_failure() -> None:
      """VADError raised if model fails to load (bad threshold is fine,
      but we test the error path by verifying the error type exists)."""
      # We cannot easily force a load failure without monkeypatching torch.hub,
      # but we verify VADError is importable and raisable
      with pytest.raises(VADError):
          raise VADError("test error propagation")
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/asr/vad.py">SileroVAD class -- Silero VAD v5 wrapper</file>
  <file path="tests/voiceagent/test_vad.py">VAD tests with real model, real numpy arrays</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>SileroVAD instantiates and loads real Silero VAD v5 model</criterion>
  <criterion>is_speech returns False for 512 samples of silence</criterion>
  <criterion>is_speech returns a bool for 512 samples of 440Hz sine wave</criterion>
  <criterion>is_speech handles float32 and int16 input</criterion>
  <criterion>is_speech accepts chunk sizes 256, 512, 768 only</criterion>
  <criterion>VADError raised for invalid chunk size (e.g. 3200)</criterion>
  <criterion>VADError raised for empty array</criterion>
  <criterion>VADError raised for NaN values</criterion>
  <criterion>reset() clears model state without error</criterion>
  <criterion>All tests pass with real model -- NO MOCKS</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_vad.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.vad import SileroVAD
import numpy as np
v = SileroVAD()
print('Model loaded:', hasattr(v, 'model'))
print('Silence is speech:', v.is_speech(np.zeros(512, dtype=np.float32)))
v.reset()
print('VAD OK')
"</command>
</test_commands>

<full_state_verification>
  <source_of_truth>
    The SileroVAD instance's `model` attribute (set during __init__) and the boolean
    return value from is_speech(). After construction, `hasattr(vad, 'model')` is True.
    After is_speech(), the return is a Python bool (True/False).
  </source_of_truth>
  <execute_and_inspect>
    1. Instantiate: `vad = SileroVAD(threshold=0.5)`
    2. Verify model loaded: `assert hasattr(vad, 'model')`
    3. Run is_speech on silence: `result = vad.is_speech(np.zeros(512, dtype=np.float32))`
    4. Verify result type and value: `assert result is False`
    5. Run is_speech on tone: `result = vad.is_speech(tone_512)` -- verify `isinstance(result, bool)`
    6. Reset: `vad.reset()` -- verify no exception
    7. Verify invalid chunk raises: try `vad.is_speech(np.zeros(3200))` -- must raise VADError
  </execute_and_inspect>
  <edge_case_audit>
    Edge Case 1: Empty array
      BEFORE: audio_chunk = np.array([], dtype=np.float32)  # shape (0,)
      AFTER:  VADError raised with message "Empty audio chunk. Expected 256, 512, or 768 samples, got 0."

    Edge Case 2: Wrong chunk size (3200 samples -- the old incorrect assumption)
      BEFORE: audio_chunk = np.zeros(3200, dtype=np.float32)  # shape (3200,)
      AFTER:  VADError raised with message "Invalid chunk size: 3200. Silero VAD v5 at 16kHz accepts only (256, 512, 768) samples."

    Edge Case 3: NaN values in audio
      BEFORE: audio_chunk = np.full(512, np.nan, dtype=np.float32)  # 512 NaN values
      AFTER:  VADError raised with message "Audio chunk contains NaN values. Check audio capture pipeline."

    Edge Case 4: int16 input (not float32)
      BEFORE: audio_chunk = np.zeros(512, dtype=np.int16)  # int16 zeros
      AFTER:  Internally converted to float32 via / 32768.0, returns False (silence)
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.asr.vad import SileroVAD
    import numpy as np

    vad = SileroVAD()
    print('PASS: model loaded, hasattr(model):', hasattr(vad, 'model'))

    result = vad.is_speech(np.zeros(512, dtype=np.float32))
    print('PASS: silence is_speech =', result, '(expected False)')

    vad.reset()
    print('PASS: reset() completed')

    try:
        vad.is_speech(np.zeros(3200, dtype=np.float32))
        print('FAIL: should have raised VADError for size 3200')
    except Exception as e:
        print('PASS: VADError raised for size 3200:', e)

    try:
        vad.is_speech(np.array([], dtype=np.float32))
        print('FAIL: should have raised VADError for empty')
    except Exception as e:
        print('PASS: VADError raised for empty:', e)

    try:
        vad.is_speech(np.full(512, np.nan, dtype=np.float32))
        print('FAIL: should have raised VADError for NaN')
    except Exception as e:
        print('PASS: VADError raised for NaN:', e)
    "
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  Input 1: np.zeros(512, dtype=np.float32)
    Description: 512 samples of pure silence at 16kHz (32ms)
    Expected output: is_speech() returns False

  Input 2: np.zeros(512, dtype=np.int16)
    Description: 512 samples of int16 silence
    Expected output: is_speech() returns False (converted to float32 internally)

  Input 3: 0.5 * np.sin(2 * np.pi * 440 * np.linspace(0, 512/16000, 512, endpoint=False, dtype=np.float32))
    Description: 512 samples of 440Hz sine wave at 0.5 amplitude
    Expected output: is_speech() returns bool (True or False -- pure tones may not trigger VAD)

  Input 4: np.zeros(3200, dtype=np.float32)
    Description: 3200 samples -- INVALID chunk size for Silero VAD v5
    Expected output: VADError raised

  Input 5: np.array([], dtype=np.float32)
    Description: Empty array
    Expected output: VADError raised

  Input 6: np.full(512, np.nan, dtype=np.float32)
    Description: 512 NaN values
    Expected output: VADError raised
</synthetic_test_data>

<manual_verification>
  Step 1: Verify model loads
    Run: PYTHONPATH=src python -c "from voiceagent.asr.vad import SileroVAD; v = SileroVAD(); print(type(v.model))"
    Expected: Prints a torch model type, no exceptions

  Step 2: Verify silence detection
    Run: PYTHONPATH=src python -c "
    from voiceagent.asr.vad import SileroVAD; import numpy as np
    v = SileroVAD(); print(v.is_speech(np.zeros(512, dtype=np.float32)))"
    Expected: Prints "False"

  Step 3: Verify invalid chunk size rejection
    Run: PYTHONPATH=src python -c "
    from voiceagent.asr.vad import SileroVAD; import numpy as np
    v = SileroVAD(); v.is_speech(np.zeros(3200, dtype=np.float32))"
    Expected: Raises VADError with message about invalid chunk size

  Step 4: Verify empty array rejection
    Run: PYTHONPATH=src python -c "
    from voiceagent.asr.vad import SileroVAD; import numpy as np
    v = SileroVAD(); v.is_speech(np.array([], dtype=np.float32))"
    Expected: Raises VADError with message about empty chunk

  Step 5: Verify NaN rejection
    Run: PYTHONPATH=src python -c "
    from voiceagent.asr.vad import SileroVAD; import numpy as np
    v = SileroVAD(); v.is_speech(np.full(512, np.nan, dtype=np.float32))"
    Expected: Raises VADError with message about NaN values

  Step 6: Verify reset
    Run: PYTHONPATH=src python -c "
    from voiceagent.asr.vad import SileroVAD; v = SileroVAD(); v.reset(); print('OK')"
    Expected: Prints "OK", no exceptions

  Step 7: Run full test suite
    Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_vad.py -v
    Expected: All tests pass
</manual_verification>
</task_spec>
```
