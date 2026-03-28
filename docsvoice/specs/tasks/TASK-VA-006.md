```xml
<task_spec id="TASK-VA-006" version="2.0">
<metadata>
  <title>Streaming ASR -- process_chunk with VAD, Whisper, and Endpoint Detection</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>6</sequence>
  <implements>
    <item ref="PHASE1-ASR-STREAMING">StreamingASR class with process_chunk()</item>
    <item ref="PHASE1-ASR-ENDPOINT">Silence-based endpoint detection (600ms configurable)</item>
    <item ref="PHASE1-ASR-PARTIAL">Partial transcript emission during speech</item>
    <item ref="PHASE1-VERIFY-2">Whisper transcribes speech (verification #2)</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-004</task_ref>
    <task_ref>TASK-VA-005</task_ref>
  </depends_on>
  <estimated_complexity>high</estimated_complexity>
  <estimated_files>3 files</estimated_files>
</metadata>

<context>
Implements the core streaming ASR pipeline. Takes continuous 200ms audio chunks
(CHUNK_MS=200, meaning 3200 samples at 16kHz), uses the SileroVAD (from TASK-VA-005)
to gate buffering, accumulates speech in an AudioBuffer (from TASK-VA-004), and runs
Distil-Whisper for transcription. Emits partial ASREvents during speech and a final
ASREvent after ENDPOINT_SILENCE_MS (default 600ms) of silence.

CRITICAL DETAILS:
- CHUNK_MS = 200 (3200 samples at 16kHz per process_chunk call)
- ENDPOINT_SILENCE_MS = 600 (configurable)
- SileroVAD (TASK-VA-005) accepts only 256/512/768 sample chunks at 16kHz.
  StreamingASR MUST rechunk the 3200-sample input into sub-chunks (e.g. 6x 512 + 1x 128?
  NO -- use 512-sample chunks: 3200 / 512 = 6.25, so feed 6 chunks of 512 and discard
  the remaining 64 samples OR pad to 768. The simplest approach: split into chunks of 512,
  call is_speech on each, and use majority vote or any-speech-detected logic.
  Recommended: split 3200 into 6 chunks of 512 (=3072 samples) + ignore last 128 samples.
  If ANY sub-chunk returns True from is_speech(), treat the entire 200ms frame as speech.
- Partial transcripts: beam_size=1 (fast, for real-time feedback)
- Final transcript: beam_size=5 (accurate, after endpoint silence detected)
- Whisper model: faster_whisper.WhisperModel("distil-whisper/distil-large-v3", device="cuda", compute_type="int8")
- AudioBuffer from TASK-VA-004
- SileroVAD from TASK-VA-005

Hardware: RTX 5090 (32GB GDDR7), CUDA 13.1/13.2, Python 3.12+
Project state: src/voiceagent/ does NOT exist yet -- 100% greenfield.
All imports require PYTHONPATH=src from repo root.

NO MOCKS for integration tests. Unit tests for EndpointDetector (pure logic, no GPU)
use real data structures. Integration tests for StreamingASR use real Whisper model
and real SileroVAD on GPU.
</context>

<input_context_files>
  <file purpose="asr_spec">docsvoice/01_phase1_core_pipeline.md#section-2.2</file>
  <file purpose="endpoint_spec">docsvoice/01_phase1_core_pipeline.md#section-2.3</file>
  <file purpose="asr_types">src/voiceagent/asr/types.py (from TASK-VA-004: ASREvent, AudioBuffer)</file>
  <file purpose="vad">src/voiceagent/asr/vad.py (from TASK-VA-005: SileroVAD)</file>
  <file purpose="config">src/voiceagent/config.py (from TASK-VA-002: ASRConfig)</file>
  <file purpose="errors">src/voiceagent/errors.py (from TASK-VA-001: ASRError)</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-004 complete (ASREvent, AudioBuffer available in src/voiceagent/asr/types.py)</check>
  <check>TASK-VA-005 complete (SileroVAD available in src/voiceagent/asr/vad.py)</check>
  <check>faster-whisper installed: pip install faster-whisper</check>
  <check>CUDA GPU available (RTX 5090)</check>
  <check>distil-whisper/distil-large-v3 model downloadable (first run downloads ~1.5GB)</check>
</prerequisites>

<scope>
  <in_scope>
    - EndpointDetector class in src/voiceagent/asr/endpointing.py (pure logic, no GPU)
    - StreamingASR class in src/voiceagent/asr/streaming.py
    - VAD rechunking: split 3200-sample frames into 512-sample sub-chunks for SileroVAD
    - process_chunk(audio) -> ASREvent | None
    - VAD-gated buffering: only buffer during speech
    - Partial transcripts during speech (beam_size=1 for speed)
    - Final transcript after endpoint silence (beam_size=5 for accuracy)
    - Configurable endpoint silence via ENDPOINT_SILENCE_MS
    - Unit tests for EndpointDetector (pure logic, real data, no GPU)
    - Integration tests for StreamingASR (real Whisper, real VAD, requires GPU)
  </in_scope>
  <out_of_scope>
    - Microphone input capture (transport layer)
    - Wake word integration (TASK-VA-014)
    - Whisper model fine-tuning
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/asr/endpointing.py">
      class EndpointDetector:
          def __init__(self, silence_ms: int = 600, chunk_ms: int = 200) -> None: ...
          def update(self, is_speech: bool) -> bool: ...
          def reset(self) -> None: ...
          @property
          def has_speech(self) -> bool: ...
    </signature>
    <signature file="src/voiceagent/asr/streaming.py">
      class StreamingASR:
          CHUNK_MS: int = 200
          SAMPLES_PER_CHUNK: int = 3200  # 200ms at 16kHz
          VAD_CHUNK_SIZE: int = 512  # Silero VAD v5 chunk size

          def __init__(self, config: ASRConfig, vad: SileroVAD | None = None) -> None: ...
          async def process_chunk(self, audio: np.ndarray) -> ASREvent | None: ...
          def reset(self) -> None: ...
    </signature>
  </signatures>

  <constraints>
    - StreamingASR uses faster_whisper.WhisperModel for transcription
    - Model: "distil-whisper/distil-large-v3", device="cuda", compute_type="int8"
    - Partial transcripts: beam_size=1 (fast)
    - Final transcripts: beam_size=5 (accurate)
    - EndpointDetector tracks consecutive silence chunks after speech has been detected
    - EndpointDetector.update() returns True when silence_ms >= silence_threshold_ms AND speech was previously detected
    - process_chunk returns None when no event (pure silence with no prior speech, mid-speech without new partial)
    - Buffer cleared after final transcript emitted
    - VAD reset after final transcript
    - Endpoint reset after final transcript
    - Raise ASRError if Whisper model fails to load
    - Raise ASRError if audio chunk is wrong size (not 3200 samples)
    - VAD rechunking: split 3200 samples into sub-chunks of 512 for SileroVAD
    - If ANY sub-chunk triggers VAD, the whole frame is treated as speech
    - NO MOCKS -- EndpointDetector tests use real logic; StreamingASR integration tests use real models
    - FAIL FAST -- no silent error swallowing
    - NO BACKWARDS COMPATIBILITY -- no fallbacks
  </constraints>

  <verification>
    - EndpointDetector: update(False) returns False when no speech seen yet
    - EndpointDetector: update(True) returns False (speech detected, resets silence counter)
    - EndpointDetector: update(True), then 3x update(False) returns True (600ms silence after speech at 200ms chunks)
    - EndpointDetector: reset() clears state
    - StreamingASR: process_chunk(silence_3200) returns None
    - StreamingASR: process_chunk(speech_3200) returns ASREvent with final=False
    - StreamingASR: after speech, 3x process_chunk(silence_3200) returns ASREvent with final=True
    - pytest tests/voiceagent/test_streaming_asr.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/asr/endpointing.py:
  """Silence-based endpoint detection for streaming ASR.

  Tracks consecutive silence after speech has been detected. When silence
  duration exceeds the threshold, signals that the user has finished speaking.

  Usage:
      ep = EndpointDetector(silence_ms=600, chunk_ms=200)
      for chunk in audio_stream:
          is_speech = vad.is_speech(chunk)
          if ep.update(is_speech):
              print("User finished speaking")
              ep.reset()
  """
  import logging

  logger = logging.getLogger(__name__)

  class EndpointDetector:
      def __init__(self, silence_ms: int = 600, chunk_ms: int = 200) -> None:
          self.silence_threshold_ms = silence_ms
          self.chunk_ms = chunk_ms
          self._silence_ms: int = 0
          self._has_speech: bool = False

      @property
      def has_speech(self) -> bool:
          """Whether any speech has been detected since last reset."""
          return self._has_speech

      def update(self, is_speech: bool) -> bool:
          """Update with speech/silence status for one chunk.

          Args:
              is_speech: True if the chunk contains speech.

          Returns:
              True if endpoint reached (enough silence after speech).
          """
          if is_speech:
              self._has_speech = True
              self._silence_ms = 0
              return False
          else:
              if self._has_speech:
                  self._silence_ms += self.chunk_ms
                  if self._silence_ms >= self.silence_threshold_ms:
                      logger.debug(
                          "Endpoint reached: %dms silence after speech",
                          self._silence_ms,
                      )
                      return True
              return False

      def reset(self) -> None:
          """Reset state for next utterance."""
          self._silence_ms = 0
          self._has_speech = False
          logger.debug("EndpointDetector reset")


src/voiceagent/asr/streaming.py:
  """Streaming ASR with VAD-gated Whisper transcription.

  Takes 200ms audio chunks (3200 samples at 16kHz), rechunks them into
  512-sample sub-chunks for SileroVAD, accumulates speech audio in a buffer,
  and transcribes via Distil-Whisper.

  Usage:
      asr = StreamingASR(config)
      event = await asr.process_chunk(audio_3200_samples)
      if event and event.final:
          print("Final transcript:", event.text)
  """
  import logging
  import numpy as np
  from voiceagent.asr.types import ASREvent, AudioBuffer
  from voiceagent.asr.vad import SileroVAD
  from voiceagent.asr.endpointing import EndpointDetector
  from voiceagent.errors import ASRError

  logger = logging.getLogger(__name__)

  class StreamingASR:
      CHUNK_MS: int = 200
      SAMPLES_PER_CHUNK: int = 3200  # 200ms * 16000Hz
      VAD_CHUNK_SIZE: int = 512      # Silero VAD v5 accepted chunk size

      def __init__(self, config, vad: SileroVAD | None = None) -> None:
          """Initialize streaming ASR.

          Args:
              config: ASRConfig with model_name, vad_threshold, endpoint_silence_ms, chunk_ms.
              vad: Optional pre-constructed SileroVAD instance.

          Raises:
              ASRError: If Whisper model fails to load.
          """
          try:
              import faster_whisper
              self.model = faster_whisper.WhisperModel(
                  config.model_name,  # "distil-whisper/distil-large-v3"
                  device="cuda",
                  compute_type="int8",
              )
          except Exception as e:
              raise ASRError(
                  f"Failed to load Whisper model '{config.model_name}': {e}. "
                  f"Ensure faster-whisper is installed and CUDA GPU is available."
              ) from e

          self.vad = vad or SileroVAD(threshold=config.vad_threshold)
          self.buffer = AudioBuffer()
          self.endpoint = EndpointDetector(
              silence_ms=config.endpoint_silence_ms,
              chunk_ms=self.CHUNK_MS,
          )
          logger.info(
              "StreamingASR initialized: model=%s, endpoint_silence=%dms",
              config.model_name,
              config.endpoint_silence_ms,
          )

      def _vad_check(self, audio: np.ndarray) -> bool:
          """Rechunk 3200-sample frame into 512-sample sub-chunks for SileroVAD.

          Splits audio into floor(3200/512) = 6 sub-chunks of 512 samples.
          Remaining 128 samples are discarded (not enough for valid VAD chunk).
          Returns True if ANY sub-chunk contains speech.
          """
          num_subchunks = len(audio) // self.VAD_CHUNK_SIZE
          for i in range(num_subchunks):
              start = i * self.VAD_CHUNK_SIZE
              end = start + self.VAD_CHUNK_SIZE
              sub_chunk = audio[start:end]
              if self.vad.is_speech(sub_chunk):
                  return True
          return False

      async def process_chunk(self, audio: np.ndarray) -> ASREvent | None:
          """Process a 200ms audio chunk (3200 samples at 16kHz).

          Args:
              audio: numpy array of 3200 float32 samples at 16kHz.

          Returns:
              ASREvent with final=False for partial transcripts during speech.
              ASREvent with final=True when endpoint silence detected after speech.
              None when no event (silence with no prior speech, or no new text).

          Raises:
              ASRError: If audio chunk is wrong size.
          """
          if audio.shape[0] != self.SAMPLES_PER_CHUNK:
              raise ASRError(
                  f"Expected {self.SAMPLES_PER_CHUNK} samples (200ms at 16kHz), "
                  f"got {audio.shape[0]}."
              )

          is_speech = self._vad_check(audio)
          endpoint_reached = self.endpoint.update(is_speech)

          if is_speech:
              self.buffer.append(audio)
              # Partial transcript with beam_size=1 for speed
              buffered_audio = self.buffer.get_audio()
              segments, _ = self.model.transcribe(
                  buffered_audio,
                  beam_size=1,
                  language="en",
              )
              text = " ".join(s.text for s in segments).strip()
              if text:
                  return ASREvent(text=text, final=False)

          elif endpoint_reached and self.buffer.has_audio():
              # Final transcript with beam_size=5 for accuracy
              buffered_audio = self.buffer.get_audio()
              segments, _ = self.model.transcribe(
                  buffered_audio,
                  beam_size=5,
                  language="en",
              )
              text = " ".join(s.text for s in segments).strip()
              self.buffer.clear()
              self.endpoint.reset()
              self.vad.reset()
              if text:
                  logger.info("Final transcript: '%s'", text)
                  return ASREvent(text=text, final=True)
              else:
                  logger.warning("Endpoint reached but transcription was empty")
                  return None

          return None

      def reset(self) -> None:
          """Reset all state for a new conversation turn."""
          self.buffer.clear()
          self.endpoint.reset()
          self.vad.reset()
          logger.debug("StreamingASR reset")


tests/voiceagent/test_streaming_asr.py:
  """Tests for EndpointDetector and StreamingASR.

  EndpointDetector tests: pure logic, no GPU, no mocks, real data structures.
  StreamingASR tests: require CUDA GPU, real Whisper model, real SileroVAD.

  Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_asr.py -v
  """
  import numpy as np
  import pytest
  from voiceagent.asr.endpointing import EndpointDetector

  # --- EndpointDetector tests (pure logic, no GPU needed) ---

  def test_endpoint_no_speech_no_endpoint() -> None:
      """Silence without prior speech should never trigger endpoint."""
      ep = EndpointDetector(silence_ms=600, chunk_ms=200)
      for _ in range(10):
          assert ep.update(is_speech=False) is False
      assert ep.has_speech is False

  def test_endpoint_speech_resets_silence() -> None:
      """Speech chunks should reset the silence counter."""
      ep = EndpointDetector(silence_ms=600, chunk_ms=200)
      ep.update(is_speech=True)
      assert ep.has_speech is True
      assert ep.update(is_speech=False) is False  # 200ms silence
      ep.update(is_speech=True)  # speech again, resets silence
      assert ep.update(is_speech=False) is False  # only 200ms since last speech

  def test_endpoint_speech_then_silence_triggers() -> None:
      """600ms of silence after speech should trigger endpoint."""
      ep = EndpointDetector(silence_ms=600, chunk_ms=200)
      ep.update(is_speech=True)  # speech detected
      assert ep.update(is_speech=False) is False   # 200ms silence
      assert ep.update(is_speech=False) is False   # 400ms silence
      assert ep.update(is_speech=False) is True    # 600ms silence -> endpoint!

  def test_endpoint_exact_threshold() -> None:
      """Endpoint fires at exactly silence_threshold_ms, not before."""
      ep = EndpointDetector(silence_ms=400, chunk_ms=200)
      ep.update(is_speech=True)
      assert ep.update(is_speech=False) is False   # 200ms
      assert ep.update(is_speech=False) is True    # 400ms = threshold

  def test_endpoint_reset_clears_state() -> None:
      """After reset, detector should be in initial state."""
      ep = EndpointDetector(silence_ms=600, chunk_ms=200)
      ep.update(is_speech=True)
      ep.reset()
      assert ep.has_speech is False
      # Silence after reset should not trigger endpoint
      for _ in range(10):
          assert ep.update(is_speech=False) is False

  # --- StreamingASR integration tests (require GPU) ---
  # These tests use real Whisper model and real SileroVAD.
  # They are marked with pytest.mark.gpu and will ERROR (not silently pass) if GPU unavailable.

  @pytest.fixture(scope="module")
  def check_gpu():
      """Verify CUDA GPU is available. ERROR if not -- do not silently skip."""
      import torch
      if not torch.cuda.is_available():
          pytest.fail(
              "CUDA GPU required for StreamingASR integration tests. "
              "No GPU detected. This test must ERROR, not silently pass."
          )

  @pytest.fixture(scope="module")
  def streaming_asr(check_gpu):
      """Create StreamingASR with real models. Expensive -- shared across module."""
      from voiceagent.asr.streaming import StreamingASR
      # Create a minimal config object
      class ASRConfig:
          model_name = "distil-whisper/distil-large-v3"
          vad_threshold = 0.5
          endpoint_silence_ms = 600
          chunk_ms = 200
      return StreamingASR(ASRConfig())

  @pytest.mark.asyncio
  async def test_streaming_silence_returns_none(streaming_asr) -> None:
      """3200 samples of silence should return None (no speech detected)."""
      silence = np.zeros(3200, dtype=np.float32)
      result = await streaming_asr.process_chunk(silence)
      assert result is None

  @pytest.mark.asyncio
  async def test_streaming_wrong_chunk_size_raises(streaming_asr) -> None:
      """Chunk size != 3200 should raise ASRError."""
      from voiceagent.errors import ASRError
      bad_chunk = np.zeros(1600, dtype=np.float32)
      with pytest.raises(ASRError, match="Expected 3200 samples"):
          await streaming_asr.process_chunk(bad_chunk)

  @pytest.mark.asyncio
  async def test_streaming_reset_clears_state(streaming_asr) -> None:
      """reset() should clear buffer, endpoint, and VAD state."""
      streaming_asr.reset()
      assert not streaming_asr.buffer.has_audio()
      assert not streaming_asr.endpoint.has_speech
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/asr/endpointing.py">EndpointDetector class</file>
  <file path="src/voiceagent/asr/streaming.py">StreamingASR class with VAD rechunking</file>
  <file path="tests/voiceagent/test_streaming_asr.py">Unit tests (EndpointDetector) + integration tests (StreamingASR)</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>EndpointDetector correctly ignores silence when no speech has been detected</criterion>
  <criterion>EndpointDetector returns True after silence_ms of silence following speech</criterion>
  <criterion>EndpointDetector.reset() clears all state</criterion>
  <criterion>StreamingASR rechunks 3200 samples into 512-sample sub-chunks for VAD</criterion>
  <criterion>StreamingASR returns None for silence-only input</criterion>
  <criterion>StreamingASR returns partial ASREvent (final=False) during speech</criterion>
  <criterion>StreamingASR returns final ASREvent (final=True) after endpoint silence</criterion>
  <criterion>Buffer, endpoint, and VAD all cleared after final event</criterion>
  <criterion>ASRError raised for wrong chunk size</criterion>
  <criterion>ASRError raised if Whisper model fails to load</criterion>
  <criterion>All EndpointDetector tests pass (no GPU needed)</criterion>
  <criterion>StreamingASR integration tests ERROR (not skip) if GPU unavailable</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_asr.py -v -k "endpoint"</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_asr.py -v</command>
</test_commands>

<full_state_verification>
  <source_of_truth>
    EndpointDetector: the `_has_speech` and `_silence_ms` internal state, and the bool
    return from update(). StreamingASR: the ASREvent returned from process_chunk() --
    specifically event.text (str) and event.final (bool). The AudioBuffer contents after
    processing (should be empty after final event).
  </source_of_truth>
  <execute_and_inspect>
    1. EndpointDetector:
       ep = EndpointDetector(silence_ms=600, chunk_ms=200)
       assert ep.update(False) is False  # no speech yet
       assert ep.update(True) is False   # speech, no endpoint
       assert ep.update(False) is False  # 200ms silence
       assert ep.update(False) is False  # 400ms silence
       assert ep.update(False) is True   # 600ms silence -> endpoint
       ep.reset()
       assert ep.has_speech is False

    2. StreamingASR (requires GPU):
       asr = StreamingASR(config)
       silence = np.zeros(3200, dtype=np.float32)
       result = await asr.process_chunk(silence)
       assert result is None
       asr.reset()
       assert not asr.buffer.has_audio()
  </execute_and_inspect>
  <edge_case_audit>
    Edge Case 1: Silence only (no speech ever detected)
      BEFORE: 10 consecutive silence chunks fed to process_chunk
      AFTER:  All return None. EndpointDetector.has_speech remains False. Buffer empty.

    Edge Case 2: Very long audio (>60s of continuous speech)
      BEFORE: 300+ consecutive speech chunks (60s at 200ms each) fed to process_chunk
      AFTER:  Each returns ASREvent(final=False) with partial transcript of growing length.
              Buffer grows. No endpoint triggered. Memory usage should be monitored.

    Edge Case 3: Audio with wrong sample rate (8kHz data in 16kHz-sized chunk)
      BEFORE: 3200 samples but actually 8kHz audio (sounds like 400ms at wrong rate)
      AFTER:  VAD may produce incorrect results. Whisper may transcribe incorrectly.
              No error raised (sample rate is not validated at this layer -- caller's
              responsibility). The process_chunk still returns normally.

    Edge Case 4: Wrong chunk size (1600 samples instead of 3200)
      BEFORE: audio = np.zeros(1600, dtype=np.float32)
      AFTER:  ASRError raised: "Expected 3200 samples (200ms at 16kHz), got 1600."
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.asr.endpointing import EndpointDetector

    ep = EndpointDetector(silence_ms=600, chunk_ms=200)
    print('No speech, silence:', ep.update(False))  # False
    print('Speech:', ep.update(True))                # False
    print('Silence 200ms:', ep.update(False))        # False
    print('Silence 400ms:', ep.update(False))        # False
    print('Silence 600ms:', ep.update(False))        # True (endpoint!)
    ep.reset()
    print('After reset, has_speech:', ep.has_speech)  # False
    print('EndpointDetector OK')
    "

    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    import asyncio
    import numpy as np
    from voiceagent.asr.streaming import StreamingASR

    class Cfg:
        model_name = 'distil-whisper/distil-large-v3'
        vad_threshold = 0.5
        endpoint_silence_ms = 600
        chunk_ms = 200

    async def main():
        asr = StreamingASR(Cfg())
        silence = np.zeros(3200, dtype=np.float32)
        result = await asr.process_chunk(silence)
        print('Silence result:', result)  # None
        asr.reset()
        print('Buffer empty after reset:', not asr.buffer.has_audio())  # True
        print('StreamingASR OK')

    asyncio.run(main())
    "
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  EndpointDetector inputs and expected outputs:
    Sequence: [True, False, False, False]  with silence_ms=600, chunk_ms=200
    Expected: [False, False, False, True]  (endpoint on 4th call)

    Sequence: [False, False, False, False]  (silence only, no prior speech)
    Expected: [False, False, False, False]  (never triggers)

    Sequence: [True, False, True, False, False, False]
    Expected: [False, False, False, False, False, True]
    (speech resets silence counter, endpoint after 600ms from last speech)

  StreamingASR inputs and expected outputs:
    Input: np.zeros(3200, dtype=np.float32)  (silence)
    Expected: None

    Input: np.zeros(1600, dtype=np.float32)  (wrong size)
    Expected: ASRError raised

    Input: [speech_chunk, silence, silence, silence]  (speech then 600ms silence)
    Expected: [ASREvent(final=False), None, None, ASREvent(final=True)]
    (Note: actual behavior depends on VAD detection of speech chunk)
</synthetic_test_data>

<manual_verification>
  Step 1: Verify EndpointDetector logic (no GPU needed)
    Run: PYTHONPATH=src python -c "
    from voiceagent.asr.endpointing import EndpointDetector
    ep = EndpointDetector(silence_ms=600, chunk_ms=200)
    results = []
    for speech in [True, False, False, False]:
        results.append(ep.update(speech))
    print('Results:', results)
    assert results == [False, False, False, True], f'Expected [F,F,F,T], got {results}'
    print('EndpointDetector PASS')
    "
    Expected: Prints "EndpointDetector PASS"

  Step 2: Verify EndpointDetector reset
    Run: PYTHONPATH=src python -c "
    from voiceagent.asr.endpointing import EndpointDetector
    ep = EndpointDetector()
    ep.update(True)
    ep.reset()
    print('has_speech after reset:', ep.has_speech)
    assert ep.has_speech is False
    print('Reset PASS')
    "
    Expected: Prints "Reset PASS"

  Step 3: Verify StreamingASR loads (requires GPU)
    Run: PYTHONPATH=src python -c "
    from voiceagent.asr.streaming import StreamingASR
    class C:
        model_name='distil-whisper/distil-large-v3'
        vad_threshold=0.5
        endpoint_silence_ms=600
        chunk_ms=200
    asr = StreamingASR(C())
    print('StreamingASR loaded successfully')
    "
    Expected: Prints "StreamingASR loaded successfully"

  Step 4: Verify silence returns None (requires GPU)
    Run: PYTHONPATH=src python -c "
    import asyncio, numpy as np
    from voiceagent.asr.streaming import StreamingASR
    class C:
        model_name='distil-whisper/distil-large-v3'
        vad_threshold=0.5
        endpoint_silence_ms=600
        chunk_ms=200
    async def main():
        asr = StreamingASR(C())
        r = await asr.process_chunk(np.zeros(3200, dtype=np.float32))
        print('Silence result:', r)
        assert r is None
        print('Silence PASS')
    asyncio.run(main())
    "
    Expected: Prints "Silence PASS"

  Step 5: Run full test suite
    Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_asr.py -v
    Expected: All tests pass (EndpointDetector tests always, StreamingASR tests if GPU available)
</manual_verification>
</task_spec>
```
