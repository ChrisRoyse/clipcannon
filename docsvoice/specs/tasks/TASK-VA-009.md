```xml
<task_spec id="TASK-VA-009" version="2.0">
<metadata>
  <title>Context Window Manager -- Token Counting, History Truncation, Message Building</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>9</sequence>
  <implements>
    <item ref="PHASE1-CONTEXT">ContextManager with build_messages() and token budgeting</item>
    <item ref="PHASE1-VERIFY-10">Context window doesn't overflow after 50 turns (verification #10)</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-002</task_ref>
    <task_ref>TASK-VA-007</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Manages the 32K token context window for Qwen3-14B. The ContextManager builds the
message list for the LLM by: (1) reserving tokens for the system prompt, (2) reserving
tokens for the max response, (3) filling the remaining budget with conversation history
from most-recent to oldest, dropping OLDEST turns first when over budget. Uses the
model's tokenizer (transformers.AutoTokenizer) for accurate token counting.

The ConversationManager (TASK-VA-013) calls build_messages() before each LLM call.

IMPORTANT: src/voiceagent/ does NOT exist yet. This is 100% greenfield code.
All Python imports need PYTHONPATH=src from the repo root.
</context>

<input_context_files>
  <file purpose="context_spec">docsvoice/01_phase1_core_pipeline.md#section-3.3</file>
  <file purpose="config">src/voiceagent/config.py (does not exist yet -- created by TASK-VA-002)</file>
  <file purpose="llm_brain">src/voiceagent/brain/llm.py (does not exist yet -- created by TASK-VA-007)</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-002 complete (config available at src/voiceagent/config.py)</check>
  <check>TASK-VA-007 complete (LLMBrain with tokenizer available at src/voiceagent/brain/llm.py)</check>
  <check>Python 3.12+ available</check>
  <check>transformers package installed (pip install transformers)</check>
</prerequisites>

<scope>
  <in_scope>
    - ContextManager class in src/voiceagent/brain/context.py
    - build_messages(system_prompt, conversation_history, user_input) -> list[dict]
    - _count_tokens(text) using transformers.AutoTokenizer.from_pretrained(model_path)
    - Token budget constants: MAX_TOKENS=32000, SYSTEM_RESERVE=2000, RESPONSE_RESERVE=512
    - HISTORY_BUDGET = 32000 - 2000 - 512 = 29488
    - History truncation: drops OLDEST turns first when over budget
    - Unit tests with deterministic token counting
  </in_scope>
  <out_of_scope>
    - Memory retrieval injection (Phase 3+)
    - Tool result injection (Phase 4+)
    - Dynamic token budget adjustment
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/brain/context.py">
      class ContextManager:
          MAX_TOKENS: int = 32000
          SYSTEM_RESERVE: int = 2000
          RESPONSE_RESERVE: int = 512
          HISTORY_BUDGET: int = 29488  # MAX_TOKENS - SYSTEM_RESERVE - RESPONSE_RESERVE

          def __init__(self, tokenizer_path: str | None = None) -> None: ...
          def build_messages(
              self,
              system_prompt: str,
              conversation_history: list[dict[str, str]],
              user_input: str,
          ) -> list[dict[str, str]]: ...
          def _count_tokens(self, text: str) -> int: ...
    </signature>
  </signatures>

  <constraints>
    - HISTORY_BUDGET = MAX_TOKENS - SYSTEM_RESERVE - RESPONSE_RESERVE = 29488
    - build_messages returns: [system_msg, ...history_msgs, user_msg]
    - History added in chronological order -- oldest first, newest last
    - When over budget: drop OLDEST turns first (iterate from oldest, skip until remaining fits)
    - _count_tokens uses transformers.AutoTokenizer.from_pretrained(tokenizer_path) for accurate counting
    - If tokenizer_path is None or load fails, fall back to len(text) // 4 (approx 1 token per 4 chars)
    - Empty history returns just [system_msg, user_msg]
    - Never exceeds MAX_TOKENS total output tokens (system + history + user + response reserve)
    - system_prompt always included (even if over SYSTEM_RESERVE -- it's a soft reserve)
    - user_input always included -- never dropped
    - Each message in conversation_history is {"role": "user"|"assistant", "content": "..."}
  </constraints>

  <verification>
    - build_messages with empty history returns exactly 2 messages (system + user)
    - build_messages with short history includes ALL turns
    - build_messages with long history truncates oldest turns
    - Total token count of returned messages never exceeds MAX_TOKENS - RESPONSE_RESERVE
    - _count_tokens returns positive integer for non-empty text
    - Message order is always: system, then history (oldest to newest), then user
    - pytest tests/voiceagent/test_context.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/brain/context.py:
  """Context window manager for LLM token budgeting."""
  from __future__ import annotations
  import logging

  logger = logging.getLogger(__name__)

  class ContextManager:
      MAX_TOKENS = 32000
      SYSTEM_RESERVE = 2000
      RESPONSE_RESERVE = 512
      HISTORY_BUDGET = MAX_TOKENS - SYSTEM_RESERVE - RESPONSE_RESERVE  # 29488

      def __init__(self, tokenizer_path: str | None = None):
          self._tokenizer = None
          if tokenizer_path:
              try:
                  from transformers import AutoTokenizer
                  self._tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
                  logger.info("Loaded tokenizer from %s", tokenizer_path)
              except Exception as exc:
                  logger.warning(
                      "Failed to load tokenizer from '%s': %s. "
                      "Falling back to char-based estimation (1 token ~ 4 chars).",
                      tokenizer_path, exc,
                  )

      def _count_tokens(self, text: str) -> int:
          """Count tokens in text. Uses real tokenizer if available, else ~4 chars/token."""
          if not text:
              return 0
          if self._tokenizer:
              return len(self._tokenizer.encode(text))
          return max(1, len(text) // 4)

      def build_messages(
          self,
          system_prompt: str,
          conversation_history: list[dict[str, str]],
          user_input: str,
      ) -> list[dict[str, str]]:
          """Build the message list for the LLM, respecting token budget.

          Returns [system_msg, ...history_msgs, user_msg].
          Drops OLDEST history turns first when over budget.
          """
          system_msg = {"role": "system", "content": system_prompt}
          user_msg = {"role": "user", "content": user_input}

          system_tokens = self._count_tokens(system_prompt)
          user_tokens = self._count_tokens(user_input)

          # Budget available for history = total - system - user - response reserve
          budget = self.MAX_TOKENS - system_tokens - user_tokens - self.RESPONSE_RESERVE
          if budget < 0:
              # System + user already exceed budget -- return without history
              logger.warning(
                  "System prompt (%d tokens) + user input (%d tokens) + response reserve (%d) "
                  "exceeds MAX_TOKENS (%d). Returning without history.",
                  system_tokens, user_tokens, self.RESPONSE_RESERVE, self.MAX_TOKENS,
              )
              return [system_msg, user_msg]

          # Walk history from OLDEST to NEWEST, accumulate token counts.
          # Then find the cutoff point: drop oldest turns that don't fit.
          turn_tokens = []
          for turn in conversation_history:
              turn_tokens.append(self._count_tokens(turn["content"]))

          total_history_tokens = sum(turn_tokens)

          if total_history_tokens <= budget:
              # Everything fits
              return [system_msg] + list(conversation_history) + [user_msg]

          # Over budget: drop oldest turns first
          # Walk from oldest (index 0) and skip until remaining fits
          included_start = 0
          running_total = total_history_tokens
          while included_start < len(conversation_history) and running_total > budget:
              running_total -= turn_tokens[included_start]
              included_start += 1

          included = conversation_history[included_start:]

          dropped = included_start
          if dropped > 0:
              logger.info(
                  "Dropped %d oldest history turns to fit token budget "
                  "(budget=%d, used=%d).",
                  dropped, budget, running_total,
              )

          return [system_msg] + list(included) + [user_msg]

tests/voiceagent/test_context.py:
  """Tests for ContextManager."""
  import pytest
  from voiceagent.brain.context import ContextManager

  def test_build_messages_empty_history():
      cm = ContextManager()  # no tokenizer -- uses fallback
      msgs = cm.build_messages("You are helpful.", [], "Hello")
      assert len(msgs) == 2
      assert msgs[0]["role"] == "system"
      assert msgs[1]["role"] == "user"
      assert msgs[1]["content"] == "Hello"

  def test_build_messages_short_history_all_included():
      cm = ContextManager()
      history = [
          {"role": "user", "content": "Hi there"},
          {"role": "assistant", "content": "Hello! How can I help?"},
          {"role": "user", "content": "Tell me a joke"},
          {"role": "assistant", "content": "Why did the chicken cross the road?"},
      ]
      msgs = cm.build_messages("System prompt", history, "Another question")
      # All 4 history + system + user = 6
      assert len(msgs) == 6
      assert msgs[0]["role"] == "system"
      assert msgs[-1]["role"] == "user"
      assert msgs[-1]["content"] == "Another question"
      # History order preserved (oldest first)
      assert msgs[1]["content"] == "Hi there"
      assert msgs[4]["content"] == "Why did the chicken cross the road?"

  def test_build_messages_truncates_oldest():
      cm = ContextManager()
      # Fallback tokenizer: 1 token per 4 chars
      # HISTORY_BUDGET = 29488 tokens (with fallback, that's ~117,952 chars of budget)
      # But we need to account for system + user tokens being subtracted from MAX_TOKENS
      # Create history that exceeds budget
      # Each turn: 600 chars = 150 tokens (fallback)
      # System: "test" = 1 token, user: "Hi" = 1 token
      # Budget for history = 32000 - 1 - 1 - 512 = 31486 tokens
      # 210 turns * 150 tokens = 31500 tokens (just over budget)
      long_turn = "A" * 600  # 150 tokens in fallback mode
      history = [
          {"role": "user" if i % 2 == 0 else "assistant", "content": long_turn}
          for i in range(210)
      ]
      msgs = cm.build_messages("test", history, "Hi")
      # Some oldest turns should be dropped
      assert len(msgs) < 210 + 2  # less than all history + system + user
      assert len(msgs) >= 3  # at minimum: system + 1 history + user
      assert msgs[0]["role"] == "system"
      assert msgs[-1]["role"] == "user"
      assert msgs[-1]["content"] == "Hi"

  def test_build_messages_50_turns_fit():
      """Verify 50 short turns don't overflow (verification #10)."""
      cm = ContextManager()
      # 50 turns of "Hello" = ~2 tokens each (fallback: 5 chars / 4 = 1)
      history = [
          {"role": "user" if i % 2 == 0 else "assistant", "content": "Hello"}
          for i in range(50)
      ]
      msgs = cm.build_messages("You are a helpful voice assistant.", history, "Hi")
      # All 50 should fit -- total tokens is tiny
      assert len(msgs) == 52  # system + 50 history + user

  def test_build_messages_200_short_turns():
      """Synthetic test: 200 turns of 'Hello' (~250 tokens each with ~1000 char content)."""
      cm = ContextManager()
      # 200 turns * ~250 tokens each = 50000 tokens -> should exceed budget -> drops some
      content = "Hello world this is a test message " * 30  # ~1020 chars = ~255 tokens
      history = [
          {"role": "user" if i % 2 == 0 else "assistant", "content": content}
          for i in range(200)
      ]
      msgs = cm.build_messages("test", history, "Hi")
      assert len(msgs) < 200 + 2  # some history dropped
      assert msgs[0]["role"] == "system"
      assert msgs[-1]["role"] == "user"

  def test_count_tokens_fallback():
      cm = ContextManager()  # no tokenizer
      assert cm._count_tokens("") == 0
      assert cm._count_tokens("test") == 1  # 4 chars / 4 = 1
      assert cm._count_tokens("a" * 100) == 25  # 100 / 4

  def test_count_tokens_positive_for_nonempty():
      cm = ContextManager()
      assert cm._count_tokens("x") >= 1

  def test_message_order_correct():
      cm = ContextManager()
      history = [
          {"role": "user", "content": "First"},
          {"role": "assistant", "content": "Second"},
          {"role": "user", "content": "Third"},
      ]
      msgs = cm.build_messages("sys", history, "Fourth")
      assert msgs[0] == {"role": "system", "content": "sys"}
      assert msgs[1] == {"role": "user", "content": "First"}
      assert msgs[2] == {"role": "assistant", "content": "Second"}
      assert msgs[3] == {"role": "user", "content": "Third"}
      assert msgs[4] == {"role": "user", "content": "Fourth"}

  def test_empty_history_edge_case():
      cm = ContextManager()
      msgs = cm.build_messages("system", [], "user input")
      assert len(msgs) == 2

  def test_single_turn_exceeds_budget():
      """Edge case: one history turn that alone exceeds the budget."""
      cm = ContextManager()
      # Budget ~ 32000 - 1 - 1 - 512 = 31486 tokens (fallback)
      # One turn of 200000 chars = 50000 tokens -> exceeds budget
      huge_turn = "X" * 200000
      history = [{"role": "assistant", "content": huge_turn}]
      msgs = cm.build_messages("a", history, "b")
      # The huge turn should be dropped
      assert len(msgs) == 2  # just system + user
      assert msgs[0]["role"] == "system"
      assert msgs[1]["role"] == "user"

  def test_history_with_very_long_single_message():
      """Edge case: history has one very long message among short ones."""
      cm = ContextManager()
      history = [
          {"role": "user", "content": "short"},
          {"role": "assistant", "content": "Y" * 130000},  # ~32500 tokens, exceeds budget
          {"role": "user", "content": "also short"},
      ]
      msgs = cm.build_messages("sys", history, "input")
      # The long message and everything before it should be dropped
      # Only "also short" might remain (or nothing if cumulative still over)
      assert msgs[0]["role"] == "system"
      assert msgs[-1]["role"] == "user"
      assert msgs[-1]["content"] == "input"
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/brain/context.py">ContextManager class</file>
  <file path="tests/voiceagent/test_context.py">Unit tests for context management</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>build_messages returns correct message structure: [system, ...history, user]</criterion>
  <criterion>History truncation respects token budget -- drops OLDEST first</criterion>
  <criterion>Most recent turns preserved when truncating</criterion>
  <criterion>Tokenizer loaded via transformers.AutoTokenizer.from_pretrained(path)</criterion>
  <criterion>Fallback token counting works without tokenizer (len(text) // 4)</criterion>
  <criterion>50 short turns fit without truncation</criterion>
  <criterion>200 turns with ~250 tokens each causes truncation</criterion>
  <criterion>All tests pass</criterion>
</validation_criteria>

<full_state_verification>
  <source_of_truth>The list[dict] returned by build_messages() -- specifically its length and content order</source_of_truth>
  <execute_and_inspect>
    1. Call build_messages() with known inputs
    2. SEPARATELY inspect the returned list: check len(), check each message role/content
    3. Verify token count of returned messages does not exceed MAX_TOKENS - RESPONSE_RESERVE
  </execute_and_inspect>
  <edge_case_audit>
    EDGE CASE 1: Empty history
      BEFORE: conversation_history=[], system_prompt="test", user_input="hi"
      AFTER: returned list has exactly 2 items: [{"role":"system","content":"test"}, {"role":"user","content":"hi"}]

    EDGE CASE 2: Single turn that exceeds entire budget
      BEFORE: history=[{"role":"assistant","content":"X"*200000}], system="a", user="b"
      AFTER: returned list has 2 items (huge turn dropped): [system_msg, user_msg]
      Print: len(msgs)=2, msgs[0]["role"]="system", msgs[1]["role"]="user"

    EDGE CASE 3: History with one very long message among short ones
      BEFORE: history=[short, HUGE(130000 chars), short], system="sys", user="input"
      AFTER: oldest turns dropped until budget fits. Print len(msgs) and verify order.

    EDGE CASE 4: Exactly at budget boundary
      BEFORE: history tokens == budget exactly
      AFTER: all history included, len(msgs) == len(history) + 2
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_context.py -v
    # All tests pass

    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.brain.context import ContextManager
    cm = ContextManager()
    # Test 1: empty history
    msgs = cm.build_messages('system', [], 'hello')
    print(f'Empty history: {len(msgs)} messages')
    assert len(msgs) == 2

    # Test 2: 50 turns fit
    history = [{'role': 'user', 'content': 'Hello'} for _ in range(50)]
    msgs = cm.build_messages('system', history, 'hi')
    print(f'50 turns: {len(msgs)} messages (expected 52)')
    assert len(msgs) == 52

    # Test 3: 200 turns with long content -- some dropped
    content = 'Hello world test ' * 60
    history = [{'role': 'user', 'content': content} for _ in range(200)]
    msgs = cm.build_messages('test', history, 'hi')
    print(f'200 long turns: {len(msgs)} messages (should be < 202)')
    assert len(msgs) < 202
    print('ALL CHECKS PASSED')
    "
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  TEST 1 -- Empty history:
    Input:  system_prompt="test", conversation_history=[], user_input="Hi"
    Output: [{"role":"system","content":"test"}, {"role":"user","content":"Hi"}]
    Length: 2

  TEST 2 -- 50 short turns (all fit):
    Input:  system="test" (1 token), history=50 x {"role":"user","content":"Hello"} (~1 token each), user="Hi"
    Output: 52 messages (system + 50 history + user)
    No truncation.

  TEST 3 -- 200 turns with ~250 tokens each (truncation):
    Input:  system="test", history=200 x ~1000 chars (~250 tokens), user="Hi"
    Budget for history: 32000 - 1 - 1 - 512 = 31486 tokens (fallback)
    200 * 250 = 50000 tokens > 31486 -> must drop oldest
    Expected: ~125 turns kept (31486/250), so ~127 messages total
    Verify: len(output) < 202

  TEST 4 -- Single huge turn:
    Input:  system="a", history=[{"role":"assistant","content":"X"*200000}], user="b"
    200000 chars / 4 = 50000 tokens > budget
    Output: [system, user] -- history entirely dropped
    Length: 2
</synthetic_test_data>

<manual_verification>
  STEP 1: Create files
    - Create src/voiceagent/brain/context.py with ContextManager
    - Create tests/voiceagent/test_context.py with all tests
    - Ensure src/voiceagent/brain/__init__.py exists (may need to create)

  STEP 2: Run tests
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_context.py -v
    Expected: ALL PASS

  STEP 3: Verify constants
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.brain.context import ContextManager
    cm = ContextManager()
    assert cm.MAX_TOKENS == 32000
    assert cm.SYSTEM_RESERVE == 2000
    assert cm.RESPONSE_RESERVE == 512
    assert cm.HISTORY_BUDGET == 29488
    print('Constants correct')
    "

  STEP 4: Verify truncation direction (oldest dropped, newest kept)
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.brain.context import ContextManager
    cm = ContextManager()
    # Create history where only last few fit
    history = [{'role': 'user', 'content': f'Turn {i}: ' + 'X'*600} for i in range(210)]
    msgs = cm.build_messages('test', history, 'end')
    # Verify the LAST history entries are kept, not the first
    history_msgs = msgs[1:-1]  # exclude system and user
    last_content = history_msgs[-1]['content']
    assert 'Turn 209' in last_content, f'Expected Turn 209, got: {last_content[:30]}'
    first_content = history_msgs[0]['content']
    # First kept turn should NOT be Turn 0
    assert 'Turn 0' not in first_content, 'Turn 0 should have been dropped!'
    print(f'Kept {len(history_msgs)} turns. First kept: {first_content[:20]}, Last: {last_content[:20]}')
    print('Truncation direction CORRECT: oldest dropped, newest kept')
    "

  STEP 5: Verify with real tokenizer (if model available)
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
    from voiceagent.brain.context import ContextManager
    # Try loading real tokenizer -- will fall back gracefully if model not downloaded
    cm = ContextManager(tokenizer_path='Qwen/Qwen3-14B')
    msgs = cm.build_messages('You are a helpful assistant.', [], 'Hello')
    print(f'With tokenizer: {len(msgs)} messages')
    " || echo "Tokenizer test skipped (model not available)"
</manual_verification>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_context.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.brain.context import ContextManager; cm = ContextManager(); msgs = cm.build_messages('system', [], 'hello'); print(len(msgs), 'messages'); assert len(msgs) == 2"</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.brain.context import ContextManager
cm = ContextManager()
assert cm.HISTORY_BUDGET == 29488
history = [{'role': 'user', 'content': 'Hello'} for _ in range(50)]
msgs = cm.build_messages('system', history, 'hi')
assert len(msgs) == 52, f'Expected 52, got {len(msgs)}'
print('50-turn test PASSED')
"</command>
</test_commands>
</task_spec>
```
