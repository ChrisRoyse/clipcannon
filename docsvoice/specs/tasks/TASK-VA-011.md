```xml
<task_spec id="TASK-VA-011" version="2.0">
<metadata>
  <title>Sentence Chunker -- extract_sentence() with Boundary Detection</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>11</sequence>
  <implements>
    <item ref="PHASE1-CHUNKER">SentenceChunker with extract_sentence() for TTS pipelining</item>
    <item ref="PHASE1-VERIFY-9">Sentence chunker splits correctly (verification #9)</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-001</task_ref>
  </depends_on>
  <estimated_complexity>low</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Implements sentence boundary detection for streaming TTS. As LLM tokens arrive,
they accumulate in a text buffer. The SentenceChunker extracts complete sentences
(terminated by ". " or "! " or "? " or ".\n" "!\n" "?\n") or long clauses (>60 chars
at comma/semicolon/colon) so each chunk can be sent to ClipCannon for synthesis while
the LLM continues generating. This enables overlapped LLM generation and TTS synthesis
for lower perceived latency. The StreamingTTS (TASK-VA-012) uses this chunker.

This is pure logic -- no GPU, no model loading, no external dependencies.
MIN_WORDS = 3 (minimum words for a chunk to be returned).
MAX_WORDS = 50 (force-split at word boundary if exceeded).

IMPORTANT: src/voiceagent/ does NOT exist yet. This is 100% greenfield code.
All Python imports need PYTHONPATH=src from the repo root.
</context>

<input_context_files>
  <file purpose="chunker_spec">docsvoice/01_phase1_core_pipeline.md#section-4.2</file>
  <file purpose="package_structure">src/voiceagent/tts/__init__.py (created by TASK-VA-001)</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-001 complete (tts subpackage exists at src/voiceagent/tts/)</check>
</prerequisites>

<scope>
  <in_scope>
    - SentenceChunker class in src/voiceagent/tts/chunker.py
    - extract_sentence(buffer) returns a complete sentence or None
    - Sentence boundaries: ". " "! " "? " ".\n" "!\n" "?\n"
    - Long clause fallback: >60 chars at ", " "; " ": "
    - MIN_WORDS = 3 minimum words for a chunk
    - MAX_WORDS = 50 maximum words for a chunk (force-split at last space)
    - Comprehensive unit tests (NO external dependencies, NO GPU)
  </in_scope>
  <out_of_scope>
    - Token buffer management (StreamingTTS handles this)
    - TTS synthesis (TASK-VA-012)
    - NLP-based sentence detection (simple string matching is sufficient)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/tts/chunker.py">
      class SentenceChunker:
          MIN_WORDS: int = 3
          MAX_WORDS: int = 50

          def extract_sentence(self, buffer: str) -> str | None: ...
    </signature>
  </signatures>

  <constraints>
    - extract_sentence(buffer) scans buffer for the FIRST sentence boundary
    - Returns the extracted sentence string (stripped of trailing whitespace) if found
    - Returns None if no valid boundary found
    - A valid extraction must have >= MIN_WORDS words
    - Sentence boundaries checked FIRST: ". " "! " "? " ".\n" "!\n" "?\n"
    - If no sentence boundary: check for long clause (buffer[:idx] > 60 chars) at ", " "; " ": "
    - If clause >= MIN_WORDS and buffer[:idx] > 60 chars, return clause (up to and including the punctuation char, stripped)
    - MAX_WORDS: if no boundary found but buffer has > MAX_WORDS words, force-split at last space before MAX_WORDS
    - Does NOT modify the buffer -- caller is responsible for advancing past the returned text
    - No external dependencies -- pure string operations only
    - The caller uses len(returned_string) to know how far to advance the buffer, plus any trailing whitespace
  </constraints>

  <verification>
    - "Hello. How are you? " -> first call extracts "Hello. How are you?" (MIN_WORDS=3, "Hello." alone is only 1 word, so it scans further -- but actually, the FIRST boundary found is at "Hello. ", so "Hello." is checked. It has 1 word < MIN_WORDS, so it's skipped. Next boundary: "you? " -> "Hello. How are you?" has 5 words >= 3 -> extracted)

    CORRECTION: extract_sentence finds the FIRST boundary. "Hello. " is at index 5. The candidate "Hello." has 1 word < MIN_WORDS=3, so this boundary is SKIPPED. Next boundary "? " is at index 19. Candidate "Hello. How are you?" has 5 words >= 3 -> EXTRACTED.

    - "Hi" -> returns None (no sentence end, no clause boundary)
    - "This is a test. " -> "This is a test." (4 words >= 3) -> extracted
    - "Hello! " -> 1 word < 3 -> None (boundary found but too few words)
    - "This is a very long clause that exceeds sixty characters in total, and more" -> candidate at comma is "This is a very long clause that exceeds sixty characters in total," which is >60 chars and has enough words -> extracted
    - "Short, text" -> comma at idx 5, buffer[:5]="Short" is 5 chars < 60 -> None
    - "" -> None
    - "No punctuation here" -> None (no boundary at all)
    - pytest tests/voiceagent/test_chunker.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/tts/chunker.py:
  """Sentence boundary detection for streaming TTS.

  Extracts complete sentences from a text buffer as tokens arrive from the LLM.
  The StreamingTTS (TASK-VA-012) feeds tokens into a buffer and calls
  extract_sentence() to get sendable chunks for TTS synthesis.
  """

  class SentenceChunker:
      MIN_WORDS = 3
      MAX_WORDS = 50

      # Sentence-ending boundaries (checked first, in order)
      SENTENCE_ENDS = [". ", "! ", "? ", ".\n", "!\n", "?\n"]
      # Clause boundaries for long-clause fallback
      CLAUSE_SEPS = [", ", "; ", ": "]

      def extract_sentence(self, buffer: str) -> str | None:
          """Extract a complete sentence from the token buffer.

          Scans buffer for sentence-ending punctuation (. ! ?) followed by space/newline.
          If none found, falls back to clause boundaries (, ; :) for segments >60 chars.
          If still none found, force-splits at MAX_WORDS.

          Returns the sentence/clause string (stripped) if found, None otherwise.
          The caller must advance the buffer past the returned text + any trailing whitespace.
          """
          if not buffer:
              return None

          # 1. Check sentence-ending punctuation
          # Find ALL sentence boundaries and check each from earliest to latest
          best = self._find_sentence_boundary(buffer)
          if best is not None:
              return best

          # 2. Fallback: long clause at comma/semicolon/colon (>60 chars)
          best = self._find_clause_boundary(buffer)
          if best is not None:
              return best

          # 3. Force-split at MAX_WORDS if buffer is very long
          words = buffer.split()
          if len(words) > self.MAX_WORDS:
              # Find character position of MAX_WORDS-th word boundary
              chunk_words = words[:self.MAX_WORDS]
              chunk = " ".join(chunk_words)
              return chunk

          return None

      def _find_sentence_boundary(self, buffer: str) -> str | None:
          """Find earliest sentence boundary that meets MIN_WORDS."""
          # Collect all boundary positions
          candidates = []
          for end in self.SENTENCE_ENDS:
              idx = buffer.find(end)
              if idx >= 0:
                  # Candidate includes the punctuation char but not the trailing space/newline
                  candidate = buffer[:idx + 1].strip()
                  candidates.append((idx, candidate))

          # Sort by position (earliest first)
          candidates.sort(key=lambda x: x[0])

          # Try each from earliest -- but if < MIN_WORDS, skip and try next
          for idx, candidate in candidates:
              if len(candidate.split()) >= self.MIN_WORDS:
                  return candidate

          return None

      def _find_clause_boundary(self, buffer: str) -> str | None:
          """Find clause boundary for long segments (>60 chars)."""
          candidates = []
          for sep in self.CLAUSE_SEPS:
              idx = buffer.find(sep)
              if idx >= 0 and idx > 60:
                  # Include the punctuation char (comma/semicolon/colon) but not trailing space
                  candidate = buffer[:idx + 1].strip()
                  candidates.append((idx, candidate))

          candidates.sort(key=lambda x: x[0])

          for idx, candidate in candidates:
              if len(candidate.split()) >= self.MIN_WORDS:
                  return candidate

          return None

tests/voiceagent/test_chunker.py:
  """Tests for SentenceChunker."""
  import pytest
  from voiceagent.tts.chunker import SentenceChunker

  @pytest.fixture
  def chunker():
      return SentenceChunker()

  # --- Sentence boundary tests ---

  def test_extract_simple_sentence(chunker):
      result = chunker.extract_sentence("This is a test. More text follows.")
      assert result == "This is a test."

  def test_extract_question(chunker):
      result = chunker.extract_sentence("How are you doing today? I am fine.")
      assert result == "How are you doing today?"

  def test_extract_exclamation(chunker):
      result = chunker.extract_sentence("What a great day it is! Let's go.")
      assert result == "What a great day it is!"

  def test_newline_sentence_end(chunker):
      result = chunker.extract_sentence("This is a sentence.\nNew paragraph.")
      assert result == "This is a sentence."

  # --- MIN_WORDS enforcement ---

  def test_single_word_sentence_skipped(chunker):
      """'Hello! ' has 1 word < MIN_WORDS=3 -> skip to next boundary or None."""
      result = chunker.extract_sentence("Hello! ")
      assert result is None

  def test_two_word_sentence_skipped(chunker):
      result = chunker.extract_sentence("Hi there! ")
      assert result is None

  def test_three_word_sentence_extracted(chunker):
      result = chunker.extract_sentence("One two three. ")
      assert result == "One two three."

  # --- PRD example: "Hello. How are you?" ---

  def test_prd_example_hello_how_are_you(chunker):
      """From PRD: 'Hello. How are you?' should extract properly.

      'Hello.' is 1 word < MIN_WORDS=3 -> skip that boundary.
      'Hello. How are you?' at the '? ' boundary has 5 words >= 3 -> extracted.
      """
      buf = "Hello. How are you? "
      result = chunker.extract_sentence(buf)
      assert result == "Hello. How are you?"

  def test_prd_example_second_call(chunker):
      """After extracting 'Hello. How are you?', remaining buffer is empty."""
      buf = "Hello. How are you? "
      s1 = chunker.extract_sentence(buf)
      assert s1 == "Hello. How are you?"
      # Caller advances buffer past s1 + trailing whitespace
      remaining = buf[len(s1):].lstrip()
      assert remaining == ""
      s2 = chunker.extract_sentence(remaining)
      assert s2 is None

  # --- Long clause fallback ---

  def test_long_clause_at_comma(chunker):
      text = "This is a very long clause that keeps going on and on and exceeds sixty characters, and then continues"
      result = chunker.extract_sentence(text)
      assert result == "This is a very long clause that keeps going on and on and exceeds sixty characters,"

  def test_long_clause_at_semicolon(chunker):
      text = "This is another very long clause that keeps going on and on past sixty characters; then more"
      result = chunker.extract_sentence(text)
      assert result == "This is another very long clause that keeps going on and on past sixty characters;"

  def test_short_clause_not_extracted(chunker):
      """Clause at comma but < 60 chars -> not extracted."""
      result = chunker.extract_sentence("Short, text here")
      assert result is None

  # --- Edge cases ---

  def test_empty_buffer_returns_none(chunker):
      assert chunker.extract_sentence("") is None

  def test_no_punctuation_returns_none(chunker):
      assert chunker.extract_sentence("no punctuation here at all") is None

  def test_only_punctuation_returns_none(chunker):
      """Just punctuation, no words meeting MIN_WORDS."""
      assert chunker.extract_sentence("! ") is None

  def test_multiple_sentences_extracts_first_valid(chunker):
      result = chunker.extract_sentence("I am good. You are too. Great!")
      assert result == "I am good."

  def test_buffer_without_trailing_space(chunker):
      """No trailing space after period -> no boundary detected."""
      result = chunker.extract_sentence("This is a test.")
      # "." without trailing space/newline is NOT a boundary
      assert result is None

  def test_max_words_force_split(chunker):
      """Buffer with >MAX_WORDS words and no punctuation -> force-split."""
      words = " ".join(f"word{i}" for i in range(60))
      result = chunker.extract_sentence(words)
      assert result is not None
      assert len(result.split()) == 50  # MAX_WORDS

  def test_sentence_preferred_over_clause(chunker):
      """Sentence boundary at '.' should be found before clause boundary at ','."""
      text = "This is a sentence. This is a very long clause that goes on, with more"
      result = chunker.extract_sentence(text)
      assert result == "This is a sentence."

  # --- Synthetic test data ---

  def test_synthetic_hello_dot_space(chunker):
      """Input: 'Hello. ' -> 1 word < MIN_WORDS -> None."""
      assert chunker.extract_sentence("Hello. ") is None

  def test_synthetic_hi_no_boundary(chunker):
      """Input: 'Hi' -> no boundary -> None."""
      assert chunker.extract_sentence("Hi") is None

  def test_synthetic_three_words(chunker):
      """Input: 'One two three. ' -> 3 words >= MIN_WORDS -> extracted."""
      assert chunker.extract_sentence("One two three. ") == "One two three."

  def test_synthetic_short_comma(chunker):
      """Input: 'Short, text' -> comma at <60 chars -> None."""
      assert chunker.extract_sentence("Short, text") is None
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/tts/chunker.py">SentenceChunker class</file>
  <file path="tests/voiceagent/test_chunker.py">Comprehensive unit tests for sentence chunker</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>extract_sentence finds sentence-ending punctuation followed by space/newline</criterion>
  <criterion>Minimum word count (MIN_WORDS=3) enforced -- short sentences skipped</criterion>
  <criterion>Long clause fallback works for >60 char segments at comma/semicolon/colon</criterion>
  <criterion>MAX_WORDS force-split works for very long buffers without punctuation</criterion>
  <criterion>Returns None when no suitable boundary found</criterion>
  <criterion>Does not modify input buffer</criterion>
  <criterion>No external dependencies -- pure string operations</criterion>
  <criterion>All tests pass</criterion>
</validation_criteria>

<full_state_verification>
  <source_of_truth>The string (or None) returned by extract_sentence()</source_of_truth>
  <execute_and_inspect>
    1. Call extract_sentence(buffer) with known input
    2. SEPARATELY print the returned value and compare to expected
    3. Verify the buffer string is unmodified after the call
  </execute_and_inspect>
  <edge_case_audit>
    EDGE CASE 1: Empty string
      BEFORE: buffer=""
      AFTER: returns None
      Print: repr(result) -> "None"

    EDGE CASE 2: String with no punctuation
      BEFORE: buffer="no punctuation here at all"
      AFTER: returns None
      Print: repr(result) -> "None"

    EDGE CASE 3: String with only punctuation (no words)
      BEFORE: buffer="! "
      AFTER: returns None (0 words < MIN_WORDS)
      Print: repr(result) -> "None"

    EDGE CASE 4: Period without trailing space
      BEFORE: buffer="This is a test."
      AFTER: returns None (". " not found, ".\n" not found)
      Print: repr(result) -> "None"

    EDGE CASE 5: Very long buffer with no boundaries
      BEFORE: buffer="word0 word1 word2 ... word59" (60 words, no punctuation)
      AFTER: returns first 50 words joined by spaces (MAX_WORDS force-split)
      Print: len(result.split()) -> 50
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_chunker.py -v
    # All tests pass

    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.tts.chunker import SentenceChunker
    c = SentenceChunker()

    # Test 1: PRD example
    r = c.extract_sentence('Hello. How are you? ')
    print(f'PRD example: {repr(r)}')
    assert r == 'Hello. How are you?'

    # Test 2: Simple sentence
    r = c.extract_sentence('This is a test. More text.')
    print(f'Simple: {repr(r)}')
    assert r == 'This is a test.'

    # Test 3: Too few words
    r = c.extract_sentence('Hello. ')
    print(f'Too few words: {repr(r)}')
    assert r is None

    # Test 4: Empty
    r = c.extract_sentence('')
    print(f'Empty: {repr(r)}')
    assert r is None

    # Test 5: Long clause
    text = 'This is a very long clause that keeps going on and on and exceeds sixty characters, and continues'
    r = c.extract_sentence(text)
    print(f'Long clause: {repr(r)}')
    assert r is not None and r.endswith(',')

    print('ALL CHECKS PASSED')
    "
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  TEST 1:
    Input:  "Hello. "
    Output: None (1 word < MIN_WORDS=3)

  TEST 2:
    Input:  "Hi"
    Output: None (no boundary)

  TEST 3:
    Input:  "One two three. "
    Output: "One two three." (3 words >= MIN_WORDS)

  TEST 4:
    Input:  "Short, text"
    Output: None (clause < 60 chars)

  TEST 5:
    Input:  "Hello. How are you? "
    Output: "Hello. How are you?" (skips "Hello." at 1 word, takes full span at "? " with 5 words)

  TEST 6:
    Input:  "This is a very long clause that keeps going on and on and exceeds sixty characters, and more"
    Output: "This is a very long clause that keeps going on and on and exceeds sixty characters,"

  TEST 7:
    Input:  "" (empty)
    Output: None

  TEST 8:
    Input:  "word0 word1 ... word59" (60 words, no punctuation)
    Output: "word0 word1 ... word49" (first 50 words, MAX_WORDS force-split)
</synthetic_test_data>

<manual_verification>
  STEP 1: Create files
    - Create src/voiceagent/tts/chunker.py with SentenceChunker
    - Create tests/voiceagent/test_chunker.py with all tests
    - Ensure src/voiceagent/tts/__init__.py exists

  STEP 2: Run tests
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_chunker.py -v
    Expected: ALL PASS

  STEP 3: Verify constants
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.tts.chunker import SentenceChunker
    c = SentenceChunker()
    assert c.MIN_WORDS == 3
    assert c.MAX_WORDS == 50
    print('Constants correct')
    "

  STEP 4: Run all synthetic test data manually
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.tts.chunker import SentenceChunker
    c = SentenceChunker()

    tests = [
        ('Hello. ', None),
        ('Hi', None),
        ('One two three. ', 'One two three.'),
        ('Short, text', None),
        ('Hello. How are you? ', 'Hello. How are you?'),
        ('', None),
    ]
    for buf, expected in tests:
        result = c.extract_sentence(buf)
        status = 'PASS' if result == expected else 'FAIL'
        print(f'{status}: extract_sentence({repr(buf)}) -> {repr(result)} (expected {repr(expected)})')
        assert result == expected, f'FAILED: got {repr(result)}'
    print('ALL SYNTHETIC TESTS PASSED')
    "

  STEP 5: Verify buffer is not modified
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.tts.chunker import SentenceChunker
    c = SentenceChunker()
    buf = 'This is a test. More text.'
    original = buf
    c.extract_sentence(buf)
    assert buf == original, 'Buffer was modified!'
    print('Buffer immutability VERIFIED')
    "
</manual_verification>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_chunker.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.tts.chunker import SentenceChunker; c = SentenceChunker(); print(c.extract_sentence('This is a test. More text.'))"</command>
</test_commands>
</task_spec>
```
