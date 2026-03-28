```xml
<task_spec id="TASK-VA-012" version="2.0">
<metadata>
  <title>Streaming TTS -- Token Stream to Audio Chunks via Sentence Chunking</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>12</sequence>
  <implements>
    <item ref="PHASE1-TTS-STREAM">StreamingTTS connecting LLM token output to TTS synthesis</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-010</task_ref>
    <task_ref>TASK-VA-011</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Connects the LLM's streaming token output to ClipCannon TTS synthesis via sentence
chunking. As tokens arrive from generate_stream(), they accumulate in a text buffer.
The SentenceChunker (TASK-VA-011) extracts complete sentences which are then sent to
the ClipCannonAdapter (TASK-VA-010) for synthesis. The result is an async iterator of
audio chunks that can be sent to the client in real-time. This enables the agent to
start speaking before the LLM has finished generating.

Dependencies:
- TASK-VA-010: ClipCannonAdapter with async synthesize(text) -> np.ndarray
- TASK-VA-011: SentenceChunker with extract_sentence(buffer) -> str | None

IMPORTANT: src/voiceagent/ does NOT exist yet. This is 100% greenfield code.
All Python imports need PYTHONPATH=src from the repo root.

Testing note: Mocking the LLM token stream is OK (we're testing orchestration logic,
not the LLM). For integration tests, use the REAL ClipCannonAdapter with "boris" voice.
Do NOT mock ClipCannon.
</context>

<input_context_files>
  <file purpose="tts_spec">docsvoice/01_phase1_core_pipeline.md#section-4.3</file>
  <file purpose="adapter">src/voiceagent/adapters/clipcannon.py (created by TASK-VA-010)</file>
  <file purpose="chunker">src/voiceagent/tts/chunker.py (created by TASK-VA-011)</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-010 complete (ClipCannonAdapter with synthesize(text) -> np.ndarray)</check>
  <check>TASK-VA-011 complete (SentenceChunker with extract_sentence(buffer) -> str|None)</check>
</prerequisites>

<scope>
  <in_scope>
    - StreamingTTS class in src/voiceagent/tts/streaming.py
    - __init__(adapter, chunker) wires dependencies
    - async stream(token_stream) -> AsyncIterator[np.ndarray]
    - Buffer management: accumulate tokens, extract sentences, synthesize each
    - Flush remaining buffer at end of token stream
    - Unit tests with mock token stream (simulating LLM output)
    - Integration tests with REAL ClipCannonAdapter ("boris" voice)
  </in_scope>
  <out_of_scope>
    - ClipCannon adapter implementation (TASK-VA-010)
    - Sentence chunker implementation (TASK-VA-011)
    - Audio playback (transport layer)
    - Warmup/pre-loading voice embeddings (deferred)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/tts/streaming.py">
      from collections.abc import AsyncIterator
      import numpy as np
      from voiceagent.adapters.clipcannon import ClipCannonAdapter
      from voiceagent.tts.chunker import SentenceChunker

      class StreamingTTS:
          def __init__(self, adapter: ClipCannonAdapter, chunker: SentenceChunker) -> None: ...
          async def stream(self, token_stream: AsyncIterator[str]) -> AsyncIterator[np.ndarray]: ...
    </signature>
  </signatures>

  <constraints>
    - token_stream is an async iterator of string tokens (from LLM generate_stream())
    - Each yielded audio chunk is a numpy array (24kHz float32) -- from adapter.synthesize()
    - Tokens accumulate in a string buffer
    - After each token, call chunker.extract_sentence(buffer)
    - If sentence extracted: advance buffer past the sentence + trailing whitespace, then synthesize
    - Buffer advanced by: buffer = buffer[len(sentence):].lstrip()
      NOTE: lstrip() removes leading whitespace from the remainder (the trailing space after the
      sentence-ending punctuation)
    - At end of token stream: flush remaining buffer if non-empty after strip()
    - Empty remaining buffer (whitespace only) is NOT synthesized
    - adapter.synthesize() called once per sentence chunk
    - stream() is an async generator (uses 'yield')
    - Errors from synthesize() should propagate (FAIL FAST, no silent swallowing)
    - Logging: log each sentence sent to synthesize, and each audio chunk yielded
  </constraints>

  <verification>
    - Token stream ["Hello", ".", " How", " are", " you", "?", " "] yields 2 audio chunks
      (sentence 1: chunker skips "Hello." at 1 word, extracts "Hello. How are you?" at 5 words)
      Wait -- the tokens arrive incrementally. Let's trace:
        buffer="" -> "Hello" -> "Hello." -> "Hello. " -> chunker finds ". " at "Hello." (1 word < 3) -> None
        -> "Hello. How" -> "Hello. How " -> no boundary yet
        -> "Hello. How are" -> "Hello. How are " -> no boundary
        -> "Hello. How are you" -> "Hello. How are you?" -> "Hello. How are you? " -> chunker finds "? " -> "Hello. How are you?" (5 words >= 3) -> EXTRACTED
        Remaining buffer: "" (after lstrip)
        Token stream ends -> nothing to flush -> 1 audio chunk total

      ACTUALLY: the tokens are ["Hello", ".", " How", " are", " you", "?", " "]
        buffer: "Hello" -> "Hello." -> "Hello. " -> extract_sentence -> finds ". " -> "Hello." (1 word) -> skip -> no "? " yet -> None
        buffer: "Hello. How" -> "Hello. How" -> extract -> ". " -> "Hello." (1 word) -> skip -> None
        buffer: "Hello. How are" -> extract -> ". " -> "Hello." skip -> None
        buffer: "Hello. How are you" -> extract -> ". " -> "Hello." skip -> None
        buffer: "Hello. How are you?" -> extract -> ". " -> "Hello." skip -> "? " not found (no space after ?) -> None
        buffer: "Hello. How are you? " -> extract -> ". " -> "Hello." skip -> "? " found -> "Hello. How are you?" (5 words) -> EXTRACTED
        Remaining: "" -> flush skipped
        RESULT: 1 audio chunk

      For 2 chunks, use: ["Hello", " world", ".", " How", " are", " you", "?", " "]
        "Hello world. " -> "Hello world." (2 words < 3) -> skip -> hmm, still < 3

      For 2 chunks, use: ["I", " am", " good", ".", " You", " are", " too", ".", " "]
        "I am good. " -> "I am good." (3 words) -> CHUNK 1
        "You are too. " -> "You are too." (3 words) -> CHUNK 2

    - Empty token stream -> 0 audio chunks
    - Single word with no punctuation -> flush at end -> 1 audio chunk (if non-empty)
    - pytest tests/voiceagent/test_streaming_tts.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/tts/streaming.py:
  """Streaming TTS -- sentence-chunked text-to-speech pipeline.

  Accumulates LLM tokens in a buffer, extracts complete sentences via
  SentenceChunker, and synthesizes each sentence via ClipCannonAdapter.
  Yields audio chunks as numpy arrays for real-time playback.
  """
  from __future__ import annotations
  from collections.abc import AsyncIterator
  import logging

  import numpy as np

  from voiceagent.adapters.clipcannon import ClipCannonAdapter
  from voiceagent.tts.chunker import SentenceChunker

  logger = logging.getLogger(__name__)

  class StreamingTTS:
      def __init__(self, adapter: ClipCannonAdapter, chunker: SentenceChunker) -> None:
          self.adapter = adapter
          self.chunker = chunker

      async def stream(self, token_stream: AsyncIterator[str]) -> AsyncIterator[np.ndarray]:
          """Convert an async token stream into an async stream of audio chunks.

          Accumulates tokens in a buffer, extracts sentences via the chunker,
          synthesizes each sentence, and yields the resulting audio arrays.
          Flushes any remaining text at the end of the token stream.

          Args:
              token_stream: Async iterator yielding string tokens from the LLM.

          Yields:
              numpy arrays of float32 audio at 24kHz, one per sentence.
          """
          buffer = ""
          chunks_yielded = 0

          async for token in token_stream:
              buffer += token

              # Try to extract a sentence from the buffer
              while True:
                  sentence = self.chunker.extract_sentence(buffer)
                  if sentence is None:
                      break

                  # Advance buffer past the extracted sentence + trailing whitespace
                  buffer = buffer[len(sentence):].lstrip()

                  logger.info(
                      "Extracted sentence (%d chars): '%s'",
                      len(sentence), sentence[:80],
                  )

                  # Synthesize the sentence
                  audio = await self.adapter.synthesize(sentence)
                  chunks_yielded += 1
                  logger.info(
                      "Yielding audio chunk #%d: %d samples (%.2fs)",
                      chunks_yielded, len(audio), len(audio) / 24000,
                  )
                  yield audio

          # Flush remaining buffer
          remaining = buffer.strip()
          if remaining:
              logger.info(
                  "Flushing remaining buffer (%d chars): '%s'",
                  len(remaining), remaining[:80],
              )
              audio = await self.adapter.synthesize(remaining)
              chunks_yielded += 1
              logger.info(
                  "Yielding final audio chunk #%d: %d samples (%.2fs)",
                  chunks_yielded, len(audio), len(audio) / 24000,
              )
              yield audio

          logger.info("Stream complete: %d total audio chunks", chunks_yielded)

tests/voiceagent/test_streaming_tts.py:
  """Tests for StreamingTTS.

  Unit tests: mock the adapter's synthesize() to return dummy audio.
  This is NOT mocking ClipCannon -- we're mocking at the adapter level to test
  the orchestration logic (buffer management, chunking, flush behavior).

  Integration tests: use the REAL ClipCannonAdapter with "boris" voice.
  """
  import asyncio
  import numpy as np
  import pytest
  from unittest.mock import AsyncMock, MagicMock

  from voiceagent.tts.streaming import StreamingTTS
  from voiceagent.tts.chunker import SentenceChunker

  # --- Helpers ---

  async def make_token_stream(tokens: list[str]):
      """Create an async iterator from a list of token strings."""
      for token in tokens:
          yield token

  def make_dummy_audio(n_samples: int = 2400) -> np.ndarray:
      """Create a dummy float32 audio array."""
      return np.zeros(n_samples, dtype=np.float32)

  async def collect_chunks(stream_iter) -> list[np.ndarray]:
      """Collect all chunks from an async iterator into a list."""
      chunks = []
      async for chunk in stream_iter:
          chunks.append(chunk)
      return chunks

  # --- Unit tests (mocked adapter) ---

  @pytest.fixture
  def mock_adapter():
      adapter = MagicMock()
      adapter.synthesize = AsyncMock(return_value=make_dummy_audio())
      return adapter

  @pytest.fixture
  def chunker():
      return SentenceChunker()

  def test_stream_two_sentences(mock_adapter, chunker):
      """Two complete sentences -> 2 audio chunks."""
      tts = StreamingTTS(mock_adapter, chunker)
      tokens = ["I", " am", " good", ".", " You", " are", " too", ".", " "]
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream(tokens)))
      )
      assert len(chunks) == 2
      assert mock_adapter.synthesize.call_count == 2
      # Verify sentence text passed to synthesize
      calls = [c.args[0] for c in mock_adapter.synthesize.call_args_list]
      assert calls[0] == "I am good."
      assert calls[1] == "You are too."

  def test_stream_flush_remaining(mock_adapter, chunker):
      """Tokens with no sentence boundary -> flush at end."""
      tts = StreamingTTS(mock_adapter, chunker)
      # "Hi there" has no sentence boundary and only 2 words (< MAX_WORDS)
      tokens = ["Hi", " there"]
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream(tokens)))
      )
      assert len(chunks) == 1  # flushed
      mock_adapter.synthesize.assert_called_once_with("Hi there")

  def test_stream_empty_flush_skipped(mock_adapter, chunker):
      """If remaining buffer is whitespace-only, don't synthesize."""
      tts = StreamingTTS(mock_adapter, chunker)
      # "I am good. " -> extracts "I am good.", remaining=" " -> strip -> "" -> skip flush
      tokens = ["I", " am", " good", ".", " "]
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream(tokens)))
      )
      assert len(chunks) == 1  # only the sentence, no flush
      mock_adapter.synthesize.assert_called_once_with("I am good.")

  def test_stream_empty_token_stream(mock_adapter, chunker):
      """Empty token stream -> 0 chunks."""
      tts = StreamingTTS(mock_adapter, chunker)
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream([])))
      )
      assert len(chunks) == 0
      mock_adapter.synthesize.assert_not_called()

  def test_stream_single_word_no_punctuation(mock_adapter, chunker):
      """Single word with no punctuation -> flushed at end."""
      tts = StreamingTTS(mock_adapter, chunker)
      tokens = ["Hello"]
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream(tokens)))
      )
      assert len(chunks) == 1
      mock_adapter.synthesize.assert_called_once_with("Hello")

  def test_stream_very_long_sentence(mock_adapter, chunker):
      """Very long sentence without boundaries -> MAX_WORDS force-split + flush."""
      tts = StreamingTTS(mock_adapter, chunker)
      # 60 words, no punctuation -> force-split at 50 words, flush remaining 10
      tokens = [f"word{i} " for i in range(60)]
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream(tokens)))
      )
      # Should get at least 2 chunks (50-word split + 10-word flush)
      assert len(chunks) >= 2

  def test_stream_yields_numpy_arrays(mock_adapter, chunker):
      """Every yielded chunk is a numpy array."""
      tts = StreamingTTS(mock_adapter, chunker)
      tokens = ["I", " am", " good", ".", " "]
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream(tokens)))
      )
      for chunk in chunks:
          assert isinstance(chunk, np.ndarray)
          assert chunk.dtype == np.float32

  def test_stream_hello_how_are_you(mock_adapter, chunker):
      """PRD example: 'Hello. How are you?' -> 1 chunk (Hello. is 1 word, skipped)."""
      tts = StreamingTTS(mock_adapter, chunker)
      tokens = ["Hello", ".", " How", " are", " you", "?", " "]
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream(tokens)))
      )
      # "Hello." has 1 word < MIN_WORDS -> skipped
      # "Hello. How are you?" has 5 words -> extracted
      assert len(chunks) == 1
      mock_adapter.synthesize.assert_called_once_with("Hello. How are you?")

  # --- Integration test (real adapter) ---
  # Marked as slow -- requires GPU, boris profile, and Qwen3-TTS model

  @pytest.mark.slow
  def test_integration_real_adapter():
      """Integration test with REAL ClipCannonAdapter and 'boris' voice.

      Requires:
      - Voice profile 'boris' in ~/.clipcannon/voice_profiles.db
      - Reference audio at ~/.clipcannon/voice_data/boris/wavs/
      - Qwen3-TTS model (loaded lazily)
      - GPU available
      """
      from voiceagent.adapters.clipcannon import ClipCannonAdapter

      adapter = ClipCannonAdapter("boris")
      chunker_real = SentenceChunker()
      tts = StreamingTTS(adapter, chunker_real)

      tokens = ["I", " am", " good", ".", " You", " are", " too", ".", " "]
      chunks = asyncio.get_event_loop().run_until_complete(
          collect_chunks(tts.stream(make_token_stream(tokens)))
      )

      assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}"
      for i, chunk in enumerate(chunks):
          assert isinstance(chunk, np.ndarray), f"Chunk {i} is not ndarray"
          assert chunk.dtype == np.float32, f"Chunk {i} dtype is {chunk.dtype}"
          assert len(chunk) > 0, f"Chunk {i} is empty"
          print(f"Chunk {i}: {len(chunk)} samples ({len(chunk)/24000:.2f}s)")

      adapter.release()
      print("Integration test PASSED")
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/tts/streaming.py">StreamingTTS class</file>
  <file path="tests/voiceagent/test_streaming_tts.py">Unit + integration tests for streaming TTS</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>stream() yields numpy audio arrays for each extracted sentence</criterion>
  <criterion>Buffer correctly advanced past extracted sentences + trailing whitespace</criterion>
  <criterion>Remaining buffer flushed at end of stream (if non-empty after strip)</criterion>
  <criterion>Empty/whitespace-only buffer NOT synthesized</criterion>
  <criterion>adapter.synthesize() called once per sentence chunk</criterion>
  <criterion>stream() is an async generator yielding np.ndarray</criterion>
  <criterion>Errors from synthesize() propagate (no silent swallowing)</criterion>
  <criterion>Unit tests with mock adapter pass</criterion>
  <criterion>Integration test with real boris adapter passes (marked @pytest.mark.slow)</criterion>
</validation_criteria>

<full_state_verification>
  <source_of_truth>
    1. Count of yielded audio chunks from stream()
    2. Each chunk's numpy array properties: dtype=float32, shape=(N,), N > 0
    3. The text arguments passed to adapter.synthesize() (verifies chunking correctness)
  </source_of_truth>
  <execute_and_inspect>
    1. Create a mock token stream with known tokens
    2. Run stream() and collect all yielded chunks
    3. SEPARATELY verify: len(chunks), each chunk's dtype/shape
    4. Check mock_adapter.synthesize.call_args_list to verify exact text passed
  </execute_and_inspect>
  <edge_case_audit>
    EDGE CASE 1: Empty token stream
      BEFORE: tokens=[]
      AFTER: 0 chunks yielded, synthesize() never called
      Print: len(chunks)=0, adapter.synthesize.call_count=0

    EDGE CASE 2: Single word with no punctuation (flushed)
      BEFORE: tokens=["Hello"]
      AFTER: 1 chunk yielded (flush), synthesize("Hello") called once
      Print: len(chunks)=1, synthesize called with "Hello"

    EDGE CASE 3: Very long sentence (>MAX_WORDS, no boundaries)
      BEFORE: tokens = ["word0 ", "word1 ", ..., "word59 "] (60 words, no punctuation)
      AFTER: force-split at 50 words -> 1 chunk, then flush remaining 10 -> 2nd chunk
      Print: len(chunks)=2, first chunk text has 50 words, second has ~10 words

    EDGE CASE 4: All whitespace tokens
      BEFORE: tokens=[" ", "  ", " "]
      AFTER: buffer="    " -> strip -> "" -> no flush -> 0 chunks
      Print: len(chunks)=0
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_tts.py -v -k "not slow"
    # All unit tests pass

    # Integration test (requires GPU + boris profile):
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_tts.py -v -m slow
    # Integration test passes

    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    import asyncio
    import numpy as np
    from unittest.mock import AsyncMock, MagicMock
    from voiceagent.tts.streaming import StreamingTTS
    from voiceagent.tts.chunker import SentenceChunker

    async def token_stream():
        for t in ['I', ' am', ' good', '.', ' You', ' are', ' too', '.', ' ']:
            yield t

    adapter = MagicMock()
    adapter.synthesize = AsyncMock(return_value=np.zeros(2400, dtype=np.float32))
    tts = StreamingTTS(adapter, SentenceChunker())

    async def run():
        chunks = []
        async for chunk in tts.stream(token_stream()):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())
    print(f'Chunks: {len(chunks)}')
    assert len(chunks) == 2
    calls = [c.args[0] for c in adapter.synthesize.call_args_list]
    print(f'Synthesized: {calls}')
    assert calls == ['I am good.', 'You are too.']
    print('ALL CHECKS PASSED')
    "
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  TEST 1 -- Two sentences:
    Input tokens: ["I", " am", " good", ".", " You", " are", " too", ".", " "]
    Buffer trace:
      "I" -> "I am" -> "I am good" -> "I am good." -> "I am good. " -> extract "I am good." (3 words)
      "You" -> "You are" -> "You are too" -> "You are too." -> "You are too. " -> extract "You are too." (3 words)
    Output: 2 audio chunks
    synthesize calls: ["I am good.", "You are too."]

  TEST 2 -- PRD example:
    Input tokens: ["Hello", ".", " How", " are", " you", "?", " "]
    Buffer trace:
      "Hello" -> "Hello." -> "Hello. " -> extract_sentence: "Hello." (1 word < 3) skip
      "Hello. How" -> "Hello. How are" -> "Hello. How are you" -> "Hello. How are you?" ->
      "Hello. How are you? " -> extract_sentence: "Hello. How are you?" (5 words) -> EXTRACTED
    Output: 1 audio chunk
    synthesize calls: ["Hello. How are you?"]

  TEST 3 -- Empty stream:
    Input tokens: []
    Output: 0 audio chunks

  TEST 4 -- Flush at end:
    Input tokens: ["Hi", " there"]
    Buffer at end: "Hi there" -> strip -> "Hi there" (non-empty) -> flush
    Output: 1 audio chunk
    synthesize calls: ["Hi there"]

  TEST 5 -- Whitespace-only flush skipped:
    Input tokens: ["I", " am", " good", ".", " "]
    After extraction: buffer=" " -> strip -> "" -> skip flush
    Output: 1 audio chunk
    synthesize calls: ["I am good."]
</synthetic_test_data>

<manual_verification>
  STEP 1: Create files
    - Create src/voiceagent/tts/streaming.py with StreamingTTS
    - Create tests/voiceagent/test_streaming_tts.py with all tests

  STEP 2: Run unit tests (no GPU needed)
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_tts.py -v -k "not slow"
    Expected: ALL PASS

  STEP 3: Verify chunk count for two-sentence stream
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    import asyncio
    import numpy as np
    from unittest.mock import AsyncMock, MagicMock
    from voiceagent.tts.streaming import StreamingTTS
    from voiceagent.tts.chunker import SentenceChunker

    async def tokens():
        for t in ['I', ' am', ' good', '.', ' You', ' are', ' too', '.', ' ']:
            yield t

    adapter = MagicMock()
    adapter.synthesize = AsyncMock(return_value=np.zeros(2400, dtype=np.float32))
    tts = StreamingTTS(adapter, SentenceChunker())

    async def run():
        chunks = []
        async for c in tts.stream(tokens()):
            chunks.append(c)
        return chunks

    chunks = asyncio.run(run())
    print(f'Chunks: {len(chunks)} (expected 2)')
    assert len(chunks) == 2
    print('PASSED')
    "

  STEP 4: Verify empty stream produces no chunks
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    import asyncio, numpy as np
    from unittest.mock import AsyncMock, MagicMock
    from voiceagent.tts.streaming import StreamingTTS
    from voiceagent.tts.chunker import SentenceChunker

    async def empty():
        return
        yield  # make it an async generator

    adapter = MagicMock()
    adapter.synthesize = AsyncMock()
    tts = StreamingTTS(adapter, SentenceChunker())

    async def run():
        chunks = []
        async for c in tts.stream(empty()):
            chunks.append(c)
        return chunks

    chunks = asyncio.run(run())
    print(f'Chunks: {len(chunks)} (expected 0)')
    assert len(chunks) == 0
    print('PASSED')
    "

  STEP 5: Run integration test (requires GPU + boris)
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_tts.py -v -m slow
    Expected: PASS (produces real audio from boris voice)
</manual_verification>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_tts.py -v -k "not slow"</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_streaming_tts.py -v -m slow</command>
</test_commands>
</task_spec>
```
