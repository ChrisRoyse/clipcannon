```xml
<task_spec id="TASK-VA-004" version="2.0">
<metadata>
  <title>ASR Types -- ASREvent Dataclass, AudioBuffer Class, and ASRConfig Reference</title>
  <status>ready</status>
  <layer>foundation</layer>
  <sequence>4</sequence>
  <implements>
    <item ref="PHASE1-ASR-TYPES">ASREvent, AudioBuffer data types for the ASR pipeline</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-001</task_ref>
  </depends_on>
  <estimated_complexity>low</estimated_complexity>
  <estimated_files>2 files (types.py + test_asr_types.py)</estimated_files>
</metadata>

<context>
Defines the core data types used by the ASR subsystem. ASREvent represents a
transcription event (partial or final). AudioBuffer accumulates PCM audio chunks
for batch transcription. These types are consumed by SileroVAD (TASK-VA-005),
StreamingASR (TASK-VA-006), and the ConversationManager (TASK-VA-013). Pure data
types with no external dependencies beyond numpy.

IMPORTANT CONTEXT:
- Working directory: /home/cabdru/clipcannon
- src/voiceagent/ is created by TASK-VA-001 (must be complete first)
- All import/run commands MUST use PYTHONPATH=src:
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "..."
- Python 3.12+ required (NOT 3.11)
- src/voiceagent/asr/__init__.py already exists (empty, from TASK-VA-001)
- numpy IS a required dependency for this task (audio processing)
- ASRConfig is defined in src/voiceagent/config.py (TASK-VA-002) -- this task does NOT
  redefine it. The ASR types module references it for documentation but does not import it.
- AudioBuffer operates on 16kHz mono PCM audio (float32 numpy arrays)
- duration_s() returns SECONDS (float), NOT milliseconds
</context>

<input_context_files>
  <file purpose="package_structure">src/voiceagent/asr/__init__.py -- empty init from TASK-VA-001</file>
  <file purpose="asr_config">src/voiceagent/config.py -- ASRConfig with model_name, vad_threshold, endpoint_silence_ms, chunk_ms, sample_rate</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-001 complete: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "import voiceagent.asr; print('OK')"</check>
  <check>numpy installed: python -c "import numpy; print(numpy.__version__)"</check>
  <check>Python 3.12+ available: python3 --version must show 3.12 or higher</check>
</prerequisites>

<scope>
  <in_scope>
    - src/voiceagent/asr/types.py with ASREvent dataclass and AudioBuffer class
    - ASREvent: text (str), final (bool), timestamp (float, default time.time())
    - AudioBuffer: append(chunk), get_audio() -> np.ndarray, clear(), has_audio() -> bool, duration_s() -> float
    - AudioBuffer.SAMPLE_RATE = 16000 (class constant)
    - tests/voiceagent/test_asr_types.py with comprehensive tests
  </in_scope>
  <out_of_scope>
    - ASRConfig (defined in TASK-VA-002 config.py, NOT here)
    - VAD logic (TASK-VA-005)
    - Whisper model loading (TASK-VA-006)
    - Endpoint detection logic (TASK-VA-006)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/asr/types.py">
      """ASR data types for the voice agent.

      ASREvent: Represents a transcription result (partial or final).
      AudioBuffer: Accumulates PCM audio chunks for batch processing.

      Audio format: 16kHz mono float32 PCM.
      """
      from dataclasses import dataclass, field
      import time
      import numpy as np

      @dataclass
      class ASREvent:
          """A single transcription event from the ASR engine.

          Attributes:
              text: The transcribed text.
              final: True if this is a final (committed) transcription, False if partial.
              timestamp: Unix timestamp (seconds since epoch) when this event was created.
          """
          text: str
          final: bool
          timestamp: float = field(default_factory=time.time)

      class AudioBuffer:
          """Accumulates PCM audio chunks for batch ASR processing.

          Audio format: 16kHz mono float32 numpy arrays.

          Usage:
              buf = AudioBuffer()
              buf.append(chunk1)  # np.ndarray of float32
              buf.append(chunk2)
              audio = buf.get_audio()  # concatenated array
              print(buf.duration_s())  # duration in seconds
              buf.clear()
          """
          SAMPLE_RATE: int = 16000

          def __init__(self) -> None: ...
          def append(self, chunk: np.ndarray) -> None: ...
          def get_audio(self) -> np.ndarray: ...
          def clear(self) -> None: ...
          def has_audio(self) -> bool: ...
          def duration_s(self) -> float: ...
    </signature>
  </signatures>

  <constraints>
    - AudioBuffer stores 16kHz mono float32 PCM audio
    - append(chunk) accepts np.ndarray -- does NOT copy the array (stores reference)
    - get_audio() returns np.concatenate of all appended chunks
    - get_audio() on empty buffer returns np.array([], dtype=np.float32) -- NOT None
    - duration_s() returns float in SECONDS: total_samples / SAMPLE_RATE
    - clear() resets buffer to empty state (removes all chunk references)
    - has_audio() returns True if any chunks have been appended, False otherwise
    - has_audio() returns False after clear()
    - ASREvent.timestamp defaults to current time via time.time()
    - ASREvent is a dataclass (not frozen -- may be updated by ASR engine)
    - Only depends on numpy and stdlib (time, dataclasses)
    - NO try/except that silently swallows errors
  </constraints>

  <verification>
    - AudioBuffer: append 3 chunks of known sizes, get_audio returns correct concatenation
    - AudioBuffer: clear then has_audio returns False
    - AudioBuffer: duration_s matches expected value (samples / 16000)
    - AudioBuffer: empty buffer get_audio returns empty float32 array
    - ASREvent: instantiates with text and final, has auto-generated timestamp
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_asr_types.py -v passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/asr/types.py:
  """ASR data types for the voice agent.

  ASREvent: Represents a transcription result (partial or final).
  AudioBuffer: Accumulates PCM audio chunks for batch processing.

  Audio format: 16kHz mono float32 PCM.
  """
  from dataclasses import dataclass, field
  import time
  import numpy as np

  @dataclass
  class ASREvent:
      """A single transcription event from the ASR engine."""
      text: str
      final: bool
      timestamp: float = field(default_factory=time.time)

  class AudioBuffer:
      """Accumulates PCM audio chunks for batch ASR processing.

      Audio format: 16kHz mono float32 numpy arrays.
      """
      SAMPLE_RATE: int = 16000

      def __init__(self) -> None:
          self._chunks: list[np.ndarray] = []

      def append(self, chunk: np.ndarray) -> None:
          """Append a PCM audio chunk to the buffer."""
          self._chunks.append(chunk)

      def get_audio(self) -> np.ndarray:
          """Return all buffered audio as a single concatenated array.

          Returns empty float32 array if no audio has been appended.
          """
          if not self._chunks:
              return np.array([], dtype=np.float32)
          return np.concatenate(self._chunks)

      def clear(self) -> None:
          """Remove all buffered audio chunks."""
          self._chunks.clear()

      def has_audio(self) -> bool:
          """Return True if any audio chunks have been appended."""
          return len(self._chunks) > 0

      def duration_s(self) -> float:
          """Return the total duration of buffered audio in seconds."""
          total_samples = sum(len(c) for c in self._chunks)
          return total_samples / self.SAMPLE_RATE

tests/voiceagent/test_asr_types.py:
  """Tests for voiceagent.asr.types module."""
  import time
  import numpy as np
  import pytest
  from voiceagent.asr.types import ASREvent, AudioBuffer

  def test_asr_event_creation():
      event = ASREvent(text="hello world", final=True)
      assert event.text == "hello world"
      assert event.final is True
      assert isinstance(event.timestamp, float)

  def test_asr_event_partial():
      event = ASREvent(text="hel", final=False)
      assert event.final is False

  def test_asr_event_default_timestamp():
      before = time.time()
      event = ASREvent(text="test", final=True)
      after = time.time()
      assert before <= event.timestamp <= after

  def test_asr_event_custom_timestamp():
      event = ASREvent(text="test", final=True, timestamp=1234567890.0)
      assert event.timestamp == 1234567890.0

  def test_audio_buffer_empty():
      buf = AudioBuffer()
      assert buf.has_audio() is False
      assert buf.duration_s() == 0.0
      audio = buf.get_audio()
      assert isinstance(audio, np.ndarray)
      assert audio.dtype == np.float32
      assert len(audio) == 0

  def test_audio_buffer_append_and_get():
      buf = AudioBuffer()
      chunk1 = np.ones(1600, dtype=np.float32)
      chunk2 = np.zeros(1600, dtype=np.float32)
      chunk3 = np.full(1600, 0.5, dtype=np.float32)
      buf.append(chunk1)
      buf.append(chunk2)
      buf.append(chunk3)
      audio = buf.get_audio()
      assert len(audio) == 4800
      assert np.array_equal(audio[:1600], chunk1)
      assert np.array_equal(audio[1600:3200], chunk2)
      assert np.array_equal(audio[3200:4800], chunk3)

  def test_audio_buffer_has_audio():
      buf = AudioBuffer()
      assert buf.has_audio() is False
      buf.append(np.zeros(100, dtype=np.float32))
      assert buf.has_audio() is True

  def test_audio_buffer_clear():
      buf = AudioBuffer()
      buf.append(np.zeros(1600, dtype=np.float32))
      assert buf.has_audio() is True
      buf.clear()
      assert buf.has_audio() is False
      assert buf.duration_s() == 0.0
      assert len(buf.get_audio()) == 0

  def test_audio_buffer_duration_s_200ms():
      """3200 samples at 16kHz = 0.2 seconds."""
      buf = AudioBuffer()
      buf.append(np.zeros(3200, dtype=np.float32))
      assert buf.duration_s() == pytest.approx(0.2)

  def test_audio_buffer_duration_s_1s():
      """16000 samples at 16kHz = 1.0 seconds."""
      buf = AudioBuffer()
      buf.append(np.zeros(16000, dtype=np.float32))
      assert buf.duration_s() == pytest.approx(1.0)

  def test_audio_buffer_duration_s_multiple_chunks():
      """Multiple chunks: total samples / 16000."""
      buf = AudioBuffer()
      buf.append(np.zeros(8000, dtype=np.float32))  # 0.5s
      buf.append(np.zeros(4000, dtype=np.float32))  # 0.25s
      assert buf.duration_s() == pytest.approx(0.75)

  def test_audio_buffer_sample_rate():
      assert AudioBuffer.SAMPLE_RATE == 16000
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/asr/types.py">ASREvent dataclass and AudioBuffer class</file>
  <file path="tests/voiceagent/test_asr_types.py">Unit tests for ASR types</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>ASREvent instantiates with text, final, and auto-generated timestamp</criterion>
  <criterion>ASREvent timestamp defaults to time.time()</criterion>
  <criterion>AudioBuffer accumulates and concatenates chunks correctly</criterion>
  <criterion>AudioBuffer.get_audio() on empty buffer returns empty float32 array</criterion>
  <criterion>AudioBuffer.duration_s() returns correct seconds (3200 samples = 0.2s)</criterion>
  <criterion>AudioBuffer.clear() resets state completely</criterion>
  <criterion>AudioBuffer.has_audio() returns False after clear()</criterion>
  <criterion>AudioBuffer.SAMPLE_RATE == 16000</criterion>
  <criterion>All tests pass with: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_asr_types.py -v</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_asr_types.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import ASREvent, AudioBuffer
import numpy as np

# Test ASREvent
e = ASREvent(text='hello', final=True)
print(f'ASREvent: text={e.text!r}, final={e.final}, timestamp={e.timestamp:.1f}')

# Test AudioBuffer with 3200 samples (200ms at 16kHz)
buf = AudioBuffer()
buf.append(np.zeros(3200, dtype=np.float32))
print(f'AudioBuffer: duration_s={buf.duration_s()}, has_audio={buf.has_audio()}')
assert buf.duration_s() == 0.2, f'Expected 0.2, got {buf.duration_s()}'
print('All ASR types OK')
"</command>
</test_commands>

<full_state_verification>
  <source_of_truth>
    The importable Python types at voiceagent.asr.types.ASREvent and
    voiceagent.asr.types.AudioBuffer are the source of truth.
    Files on disk:
      /home/cabdru/clipcannon/src/voiceagent/asr/types.py
      /home/cabdru/clipcannon/tests/voiceagent/test_asr_types.py
  </source_of_truth>

  <execute_and_inspect>
    Step 1: Create src/voiceagent/asr/types.py with ASREvent and AudioBuffer.
    Step 2: Create tests/voiceagent/test_asr_types.py with all tests.
    Step 3: Run `ls -la /home/cabdru/clipcannon/src/voiceagent/asr/types.py` to prove it exists.
    Step 4: Run `cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.asr.types import ASREvent, AudioBuffer; print('Import OK')"` to prove imports work.
    Step 5: Run `cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_asr_types.py -v` to prove all tests pass.
    Step 6: Run the synthetic test (3200 samples = 0.2s) to verify AudioBuffer math.
  </execute_and_inspect>

  <edge_case_audit>
    Edge case 1: Empty buffer get_audio returns empty float32 array, not None
      Command: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import AudioBuffer
import numpy as np
buf = AudioBuffer()
audio = buf.get_audio()
print(f'type={type(audio).__name__}, dtype={audio.dtype}, len={len(audio)}')
assert isinstance(audio, np.ndarray)
assert audio.dtype == np.float32
assert len(audio) == 0
print('Empty buffer OK')
"
      Expected: type=ndarray, dtype=float32, len=0

    Edge case 2: duration_s after clear is 0.0
      Command: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import AudioBuffer
import numpy as np
buf = AudioBuffer()
buf.append(np.zeros(16000, dtype=np.float32))
print(f'BEFORE clear: duration_s={buf.duration_s()}')
buf.clear()
print(f'AFTER clear: duration_s={buf.duration_s()}')
"
      Expected: BEFORE clear: duration_s=1.0, AFTER clear: duration_s=0.0

    Edge case 3: ASREvent with empty string text
      Command: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import ASREvent
e = ASREvent(text='', final=False)
print(f'text={e.text!r}, final={e.final}')
"
      Expected: text='', final=False (empty string is valid -- partial transcript can be empty)

    Edge case 4: AudioBuffer with single-sample chunk
      Command: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import AudioBuffer
import numpy as np
buf = AudioBuffer()
buf.append(np.array([0.5], dtype=np.float32))
print(f'duration_s={buf.duration_s()}, samples={len(buf.get_audio())}')
"
      Expected: duration_s=6.25e-05, samples=1 (1 sample / 16000 Hz)
  </edge_case_audit>

  <evidence_of_success>
    Command 1: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import ASREvent, AudioBuffer
import numpy as np
# Verify ASREvent
e = ASREvent(text='hello', final=True)
assert e.text == 'hello'
assert e.final is True
assert isinstance(e.timestamp, float)
# Verify AudioBuffer with known data: 3200 samples = 0.2 seconds
buf = AudioBuffer()
buf.append(np.zeros(3200, dtype=np.float32))
assert buf.duration_s() == 0.2
assert buf.has_audio() is True
buf.clear()
assert buf.has_audio() is False
assert buf.duration_s() == 0.0
print('All ASR types verified')
"
    Must print: All ASR types verified

    Command 2: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_asr_types.py -v
    Must show: all tests PASSED, 0 failures

    Command 3: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import AudioBuffer
print(f'SAMPLE_RATE={AudioBuffer.SAMPLE_RATE}')
"
    Must print: SAMPLE_RATE=16000
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  Test 1: AudioBuffer with 3200 samples (200ms at 16kHz)
    Input: np.zeros(3200, dtype=np.float32)
    Expected: duration_s() == 0.2
    Expected: has_audio() == True
    Expected: len(get_audio()) == 3200

  Test 2: AudioBuffer with 16000 samples (1.0s at 16kHz)
    Input: np.zeros(16000, dtype=np.float32)
    Expected: duration_s() == 1.0

  Test 3: AudioBuffer with multiple chunks (0.5s + 0.25s = 0.75s)
    Input: np.zeros(8000) then np.zeros(4000)
    Expected: duration_s() == 0.75
    Expected: len(get_audio()) == 12000

  Test 4: AudioBuffer empty
    Input: (nothing appended)
    Expected: duration_s() == 0.0
    Expected: has_audio() == False
    Expected: get_audio() returns np.array([], dtype=np.float32)

  Test 5: ASREvent creation
    Input: ASREvent(text="hello world", final=True)
    Expected: text == "hello world", final == True, timestamp is a float close to time.time()

  Test 6: ASREvent partial
    Input: ASREvent(text="hel", final=False)
    Expected: final == False
</synthetic_test_data>

<manual_verification>
  The implementing agent MUST perform these checks AFTER creating all files:

  1. Run: ls -la /home/cabdru/clipcannon/src/voiceagent/asr/types.py
     Verify: File exists, non-zero size

  2. Run: ls -la /home/cabdru/clipcannon/tests/voiceagent/test_asr_types.py
     Verify: File exists, non-zero size

  3. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import ASREvent, AudioBuffer
print('Import OK')
"
     Verify: "Import OK" printed

  4. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import AudioBuffer
import numpy as np
buf = AudioBuffer()
buf.append(np.zeros(3200, dtype=np.float32))
d = buf.duration_s()
print(f'duration_s={d}')
assert d == 0.2, f'Expected 0.2, got {d}'
print('200ms test PASSED')
"
     Verify: "200ms test PASSED" printed

  5. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.asr.types import ASREvent
import time
before = time.time()
e = ASREvent(text='test', final=True)
after = time.time()
assert before <= e.timestamp <= after
print(f'Timestamp OK: {e.timestamp:.3f}')
"
     Verify: "Timestamp OK" printed with a reasonable Unix timestamp

  6. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_asr_types.py -v
     Verify: All tests PASSED
</manual_verification>
</task_spec>
```
