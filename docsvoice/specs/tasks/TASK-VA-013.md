```xml
<task_spec id="TASK-VA-013" version="2.0">
<metadata>
  <title>Conversation State Machine -- ConversationState Enum and ConversationManager</title>
  <status>ready</status>
  <layer>logic</layer>
  <sequence>13</sequence>
  <implements>
    <item ref="PHASE1-CONV-STATE">ConversationState enum (IDLE/LISTENING/THINKING/SPEAKING)</item>
    <item ref="PHASE1-CONV-MANAGER">ConversationManager with handle_audio_chunk and _generate_response</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-001</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>3 files</estimated_files>
</metadata>

<context>
Implements the conversation state machine that orchestrates the ASR-LLM-TTS pipeline.
The ConversationManager tracks conversation state (IDLE, LISTENING, THINKING, SPEAKING)
and routes audio chunks through the pipeline. It receives audio from the transport
layer, processes it through ASR, sends transcriptions to the LLM, and streams responses
through TTS back to the transport. The state machine ensures clean transitions and
prevents overlapping operations (e.g., no new ASR while speaking).

This is 100% greenfield -- src/voiceagent/ does not exist yet. The implementing agent
must create all directories and files from scratch. Python 3.12+, RTX 5090 GPU.

This task creates the state machine and manager with abstract component interfaces.
The VoiceAgent orchestrator (TASK-VA-018) wires in the concrete implementations.
</context>

<input_context_files>
  <file purpose="conversation_spec">docsvoice/01_phase1_core_pipeline.md#section-5</file>
  <file purpose="errors">src/voiceagent/errors.py (create if not exists)</file>
  <file purpose="package_structure">src/voiceagent/conversation/__init__.py (create if not exists)</file>
</input_context_files>

<prerequisites>
  <check>Python 3.12+ available: python3 --version</check>
  <check>numpy installed: python3 -c "import numpy; print(numpy.__version__)"</check>
  <check>TASK-VA-001 complete (conversation subpackage exists), OR create dirs manually</check>
  <check>If dirs missing, create: mkdir -p src/voiceagent/conversation &amp;&amp; touch src/voiceagent/__init__.py src/voiceagent/conversation/__init__.py</check>
</prerequisites>

<scope>
  <in_scope>
    - ConversationState enum in src/voiceagent/conversation/state.py
    - ConversationManager class in src/voiceagent/conversation/manager.py
    - ConversationError in src/voiceagent/errors.py (create if not exists)
    - async handle_audio_chunk(audio: np.ndarray) -- main audio processing loop
    - async _generate_response(user_text: str) -- LLM + TTS pipeline
    - State transitions:
        IDLE -> LISTENING (on VAD speech detected or wake word)
        LISTENING -> THINKING (on ASR final transcript after 600ms silence)
        THINKING -> SPEAKING (first TTS audio chunk ready)
        SPEAKING -> LISTENING (all TTS audio sent)
        Any state -> IDLE (on dismiss keyword or timeout)
    - Maintains conversation history: list[dict] with role/content
    - Unit tests with REAL state machine logic (NO MOCKS of the state machine itself)
  </in_scope>
  <out_of_scope>
    - Concrete ASR/LLM/TTS implementations (injected via constructor)
    - Database logging (TASK-VA-018 adds this)
    - Barge-in / interruption (Phase 4+)
    - Wake word check in IDLE state (TASK-VA-018 integrates this)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/conversation/state.py">
      from enum import Enum

      class ConversationState(Enum):
          IDLE = "idle"
          LISTENING = "listening"
          THINKING = "thinking"
          SPEAKING = "speaking"
    </signature>
    <signature file="src/voiceagent/errors.py">
      class VoiceAgentError(Exception):
          """Base error for voice agent."""
          pass

      class ConversationError(VoiceAgentError):
          """Invalid conversation state transition."""
          pass
    </signature>
    <signature file="src/voiceagent/conversation/manager.py">
      from typing import Protocol, runtime_checkable, Callable, Awaitable
      import numpy as np
      from collections.abc import AsyncIterator

      @runtime_checkable
      class ASRProtocol(Protocol):
          async def process_chunk(self, audio: np.ndarray) -> ASREvent | None: ...
          @property
          def vad(self) -> ...: ...

      @runtime_checkable
      class BrainProtocol(Protocol):
          async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...

      @runtime_checkable
      class TTSProtocol(Protocol):
          async def stream(self, token_stream: AsyncIterator[str]) -> AsyncIterator[np.ndarray]: ...

      @runtime_checkable
      class TransportProtocol(Protocol):
          async def send_audio(self, audio: np.ndarray) -> None: ...
          async def send_event(self, event: dict) -> None: ...

      class ConversationManager:
          def __init__(
              self,
              asr: ASRProtocol,
              brain: BrainProtocol,
              tts: TTSProtocol,
              transport: TransportProtocol,
              context_manager: ...,
              system_prompt: str,
          ) -> None: ...

          @property
          def state(self) -> ConversationState: ...
          @property
          def history(self) -> list[dict[str, str]]: ...

          async def handle_audio_chunk(self, audio: np.ndarray) -> None: ...
          async def _generate_response(self, user_text: str) -> None: ...
          async def dismiss(self) -> None: ...
    </signature>
  </signatures>

  <constraints>
    - State starts as IDLE
    - IDLE + speech detected (via ASR VAD) -> LISTENING
    - LISTENING + final ASREvent (600ms silence triggers finality) -> THINKING
    - THINKING + first TTS chunk ready -> SPEAKING
    - SPEAKING + all TTS audio sent -> LISTENING (ready for next turn)
    - Any state + dismiss keyword or timeout -> IDLE
    - handle_audio_chunk while THINKING or SPEAKING: buffer/ignore audio, do NOT crash
    - Invalid explicit state transitions raise ConversationError
    - history is a list of {"role": "user"|"assistant", "content": "..."} dicts
    - Uses Protocol classes (not concrete types) for dependency injection
    - send_event called on state transitions with {"type": "state", "state": "..."}
    - Accumulate full assistant response text for history
    - All errors logged with what/why/how-to-fix pattern
  </constraints>

  <verification>
    - ConversationState has exactly 4 values
    - ConversationManager starts in IDLE state
    - handle_audio_chunk transitions IDLE->LISTENING on speech
    - LISTENING->THINKING on final ASR transcript
    - THINKING->SPEAKING on first TTS chunk
    - SPEAKING->LISTENING after all TTS audio sent
    - dismiss() transitions any state to IDLE
    - handle_audio_chunk during THINKING does NOT crash (buffered/ignored)
    - handle_audio_chunk during SPEAKING does NOT crash (buffered/ignored)
    - Invalid transitions raise ConversationError
    - History appended correctly after each exchange
    - pytest tests/voiceagent/test_conversation.py passes
    - PYTHONPATH=src python -c "from voiceagent.conversation.state import ConversationState; print(list(ConversationState))"
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/errors.py:
  """Voice agent error hierarchy."""

  class VoiceAgentError(Exception):
      """Base error for voice agent."""
      pass

  class ConversationError(VoiceAgentError):
      """Invalid conversation state transition or conversation logic error."""
      pass

src/voiceagent/conversation/state.py:
  """Conversation state enum."""
  from enum import Enum

  class ConversationState(Enum):
      IDLE = "idle"
      LISTENING = "listening"
      THINKING = "thinking"
      SPEAKING = "speaking"

src/voiceagent/conversation/manager.py:
  """Conversation state machine and manager."""
  import logging
  import numpy as np
  from voiceagent.conversation.state import ConversationState
  from voiceagent.errors import ConversationError

  logger = logging.getLogger(__name__)

  # Valid state transitions map: current_state -> set of allowed next states
  VALID_TRANSITIONS = {
      ConversationState.IDLE: {ConversationState.LISTENING},
      ConversationState.LISTENING: {ConversationState.THINKING, ConversationState.IDLE},
      ConversationState.THINKING: {ConversationState.SPEAKING, ConversationState.IDLE},
      ConversationState.SPEAKING: {ConversationState.LISTENING, ConversationState.IDLE},
  }

  class ConversationManager:
      def __init__(self, asr, brain, tts, transport, context_manager, system_prompt):
          self._state = ConversationState.IDLE
          self._asr = asr
          self._brain = brain
          self._tts = tts
          self._transport = transport
          self._context = context_manager
          self._system_prompt = system_prompt
          self._history: list[dict[str, str]] = []

      @property
      def state(self) -> ConversationState:
          return self._state

      @property
      def history(self) -> list[dict[str, str]]:
          return list(self._history)

      async def _set_state(self, new_state: ConversationState) -> None:
          """Transition to new state with validation."""
          if new_state not in VALID_TRANSITIONS.get(self._state, set()):
              raise ConversationError(
                  f"Invalid state transition: {self._state.value} -> {new_state.value}. "
                  f"Allowed transitions from {self._state.value}: "
                  f"{[s.value for s in VALID_TRANSITIONS.get(self._state, set())]}. "
                  f"Fix: ensure the pipeline follows IDLE->LISTENING->THINKING->SPEAKING->LISTENING."
              )
          old_state = self._state
          self._state = new_state
          await self._transport.send_event({"type": "state", "state": new_state.value})
          logger.info("State %s -> %s", old_state.value, new_state.value)

      async def handle_audio_chunk(self, audio: np.ndarray) -> None:
          """Main audio processing loop.

          Routes audio based on current state:
          - IDLE: check VAD for speech, transition to LISTENING if detected
          - LISTENING: feed audio to ASR, transition to THINKING on final transcript
          - THINKING: ignore audio (LLM is generating)
          - SPEAKING: ignore audio (TTS is playing)
          """
          if not isinstance(audio, np.ndarray):
              logger.error(
                  "handle_audio_chunk received %s instead of np.ndarray. "
                  "Why: caller passed wrong type. "
                  "Fix: pass numpy array e.g. np.zeros(1600, dtype=np.int16)",
                  type(audio).__name__,
              )
              return

          if audio.size == 0:
              logger.warning("handle_audio_chunk received empty audio array, ignoring")
              return

          if self._state == ConversationState.THINKING:
              logger.debug("Audio chunk ignored: state is THINKING")
              return

          if self._state == ConversationState.SPEAKING:
              logger.debug("Audio chunk ignored: state is SPEAKING")
              return

          if self._state == ConversationState.IDLE:
              if self._asr.vad.is_speech(audio):
                  await self._set_state(ConversationState.LISTENING)
              else:
                  return  # No speech, stay IDLE

          if self._state == ConversationState.LISTENING:
              event = await self._asr.process_chunk(audio)
              if event is not None and event.final:
                  await self._set_state(ConversationState.THINKING)
                  await self._generate_response(event.text)

      async def _generate_response(self, user_text: str) -> None:
          """LLM + TTS pipeline. Called when ASR produces final transcript.

          1. Append user text to history
          2. Build messages with context manager
          3. Stream LLM tokens through TTS
          4. Send TTS audio chunks to transport
          5. Append assistant response to history
          6. Transition SPEAKING -> LISTENING
          """
          self._history.append({"role": "user", "content": user_text})
          messages = self._context.build_messages(
              self._system_prompt, self._history, user_text
          )

          full_response = ""
          first_chunk = True
          async for token in self._brain.generate_stream(messages):
              full_response += token

          # Transition to SPEAKING when we start sending audio
          await self._set_state(ConversationState.SPEAKING)

          async for audio_chunk in self._tts.stream(self._iter_text(full_response)):
              await self._transport.send_audio(audio_chunk)

          self._history.append({"role": "assistant", "content": full_response or "[empty response]"})
          await self._set_state(ConversationState.LISTENING)

      async def dismiss(self) -> None:
          """Transition any state back to IDLE (dismiss keyword or timeout)."""
          if self._state == ConversationState.IDLE:
              return  # Already idle
          old = self._state
          self._state = ConversationState.IDLE
          await self._transport.send_event({"type": "state", "state": "idle"})
          logger.info("Dismissed: %s -> IDLE", old.value)

      @staticmethod
      async def _iter_text(text: str):
          """Helper: yield text as a single chunk for TTS streaming."""
          yield text

tests/voiceagent/test_conversation.py:
  """Tests for conversation state machine -- NO MOCKS of the state machine itself.
  Uses lightweight stub objects for ASR/Brain/TTS/Transport protocols."""
  import asyncio
  import numpy as np
  import pytest
  from voiceagent.conversation.state import ConversationState
  from voiceagent.conversation.manager import ConversationManager, VALID_TRANSITIONS
  from voiceagent.errors import ConversationError

  # --- Stub classes (minimal real objects, NOT mocks) ---

  class StubASREvent:
      def __init__(self, text, final=False):
          self.text = text
          self.final = final

  class StubVAD:
      def __init__(self, speech=False):
          self._speech = speech
      def is_speech(self, audio):
          return self._speech

  class StubASR:
      def __init__(self, vad, events=None):
          self._vad = vad
          self._events = events or []
          self._idx = 0
      @property
      def vad(self):
          return self._vad
      async def process_chunk(self, audio):
          if self._idx < len(self._events):
              evt = self._events[self._idx]
              self._idx += 1
              return evt
          return None

  class StubBrain:
      def __init__(self, response="Hello"):
          self._response = response
      async def generate_stream(self, messages):
          for word in self._response.split():
              yield word + " "

  class StubTTS:
      async def stream(self, token_stream):
          text = ""
          async for t in token_stream:
              text += t
          yield np.zeros(1600, dtype=np.int16)

  class StubTransport:
      def __init__(self):
          self.events = []
          self.audio_chunks = []
      async def send_event(self, event):
          self.events.append(event)
      async def send_audio(self, audio):
          self.audio_chunks.append(audio)

  class StubContext:
      def build_messages(self, system_prompt, history, user_text):
          return [{"role": "system", "content": system_prompt}] + history

  # --- Tests ---

  def test_initial_state_is_idle():
      vad = StubVAD()
      asr = StubASR(vad)
      mgr = ConversationManager(asr, StubBrain(), StubTTS(), StubTransport(), StubContext(), "You are helpful.")
      assert mgr.state == ConversationState.IDLE

  @pytest.mark.asyncio
  async def test_idle_to_listening_on_speech():
      vad = StubVAD(speech=True)
      asr = StubASR(vad, events=[StubASREvent("", final=False)])
      transport = StubTransport()
      mgr = ConversationManager(asr, StubBrain(), StubTTS(), transport, StubContext(), "sys")
      audio = np.zeros(1600, dtype=np.int16)
      await mgr.handle_audio_chunk(audio)
      assert mgr.state == ConversationState.LISTENING
      assert {"type": "state", "state": "listening"} in transport.events

  @pytest.mark.asyncio
  async def test_listening_to_thinking_on_final_transcript():
      vad = StubVAD(speech=True)
      asr = StubASR(vad, events=[
          StubASREvent("", final=False),
          StubASREvent("hello world", final=True),
      ])
      transport = StubTransport()
      brain = StubBrain("Hi there")
      mgr = ConversationManager(asr, brain, StubTTS(), transport, StubContext(), "sys")
      audio = np.zeros(1600, dtype=np.int16)
      # First chunk: IDLE -> LISTENING (speech detected, non-final ASR)
      await mgr.handle_audio_chunk(audio)
      assert mgr.state == ConversationState.LISTENING
      # Second chunk: LISTENING -> THINKING -> SPEAKING -> LISTENING (full pipeline)
      await mgr.handle_audio_chunk(audio)
      assert mgr.state == ConversationState.LISTENING  # Pipeline complete

  @pytest.mark.asyncio
  async def test_handle_audio_chunk_while_thinking_is_ignored():
      """Audio during THINKING state should be silently ignored, not crash."""
      vad = StubVAD(speech=True)
      asr = StubASR(vad)
      transport = StubTransport()
      mgr = ConversationManager(asr, StubBrain(), StubTTS(), transport, StubContext(), "sys")
      # Force state to THINKING
      mgr._state = ConversationState.THINKING
      audio = np.zeros(1600, dtype=np.int16)
      await mgr.handle_audio_chunk(audio)  # Should NOT crash
      assert mgr.state == ConversationState.THINKING  # State unchanged

  @pytest.mark.asyncio
  async def test_handle_audio_chunk_while_speaking_is_ignored():
      """Audio during SPEAKING state should be silently ignored, not crash."""
      vad = StubVAD(speech=True)
      asr = StubASR(vad)
      transport = StubTransport()
      mgr = ConversationManager(asr, StubBrain(), StubTTS(), transport, StubContext(), "sys")
      mgr._state = ConversationState.SPEAKING
      audio = np.zeros(1600, dtype=np.int16)
      await mgr.handle_audio_chunk(audio)
      assert mgr.state == ConversationState.SPEAKING

  @pytest.mark.asyncio
  async def test_handle_audio_chunk_empty_audio():
      vad = StubVAD()
      asr = StubASR(vad)
      mgr = ConversationManager(asr, StubBrain(), StubTTS(), StubTransport(), StubContext(), "sys")
      empty = np.array([], dtype=np.int16)
      await mgr.handle_audio_chunk(empty)
      assert mgr.state == ConversationState.IDLE

  @pytest.mark.asyncio
  async def test_invalid_state_transition_raises_conversation_error():
      vad = StubVAD()
      asr = StubASR(vad)
      transport = StubTransport()
      mgr = ConversationManager(asr, StubBrain(), StubTTS(), transport, StubContext(), "sys")
      assert mgr.state == ConversationState.IDLE
      with pytest.raises(ConversationError, match="Invalid state transition"):
          await mgr._set_state(ConversationState.SPEAKING)  # IDLE -> SPEAKING is invalid

  @pytest.mark.asyncio
  async def test_dismiss_returns_to_idle_from_any_state():
      vad = StubVAD()
      asr = StubASR(vad)
      transport = StubTransport()
      mgr = ConversationManager(asr, StubBrain(), StubTTS(), transport, StubContext(), "sys")
      for state in [ConversationState.LISTENING, ConversationState.THINKING, ConversationState.SPEAKING]:
          mgr._state = state
          await mgr.dismiss()
          assert mgr.state == ConversationState.IDLE

  @pytest.mark.asyncio
  async def test_dismiss_while_idle_is_noop():
      vad = StubVAD()
      asr = StubASR(vad)
      transport = StubTransport()
      mgr = ConversationManager(asr, StubBrain(), StubTTS(), transport, StubContext(), "sys")
      await mgr.dismiss()
      assert mgr.state == ConversationState.IDLE
      assert len(transport.events) == 0  # No event sent

  @pytest.mark.asyncio
  async def test_history_tracks_user_and_assistant():
      vad = StubVAD(speech=True)
      asr = StubASR(vad, events=[
          StubASREvent("", final=False),
          StubASREvent("What is 2+2?", final=True),
      ])
      brain = StubBrain("Four")
      transport = StubTransport()
      mgr = ConversationManager(asr, brain, StubTTS(), transport, StubContext(), "sys")
      audio = np.zeros(1600, dtype=np.int16)
      await mgr.handle_audio_chunk(audio)  # IDLE -> LISTENING
      await mgr.handle_audio_chunk(audio)  # LISTENING -> full pipeline
      history = mgr.history
      assert len(history) == 2
      assert history[0]["role"] == "user"
      assert history[0]["content"] == "What is 2+2?"
      assert history[1]["role"] == "assistant"
      assert len(history[1]["content"]) > 0

  def test_conversation_state_enum_has_4_values():
      assert len(ConversationState) == 4
      assert set(s.value for s in ConversationState) == {"idle", "listening", "thinking", "speaking"}
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/errors.py">VoiceAgentError and ConversationError</file>
  <file path="src/voiceagent/conversation/state.py">ConversationState enum</file>
  <file path="src/voiceagent/conversation/manager.py">ConversationManager class with protocols</file>
  <file path="tests/voiceagent/test_conversation.py">Unit tests for state machine with real logic</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<full_state_verification>
  <source_of_truth>
    manager.state attribute (ConversationState enum value).
    manager.history property (list of {"role": str, "content": str} dicts).
    These are the ONLY places to check conversation state. Do NOT infer state from logs.
  </source_of_truth>

  <execute_and_inspect>
    Step 1: Run the state machine logic (e.g., handle_audio_chunk).
    Step 2: SEPARATELY read manager.state and manager.history.
    Step 3: Compare actual values to expected values.
    Never trust that "no error" means "correct state". Always read state explicitly.
  </execute_and_inspect>

  <edge_case_audit>
    <case name="audio_while_thinking">
      <before>manager.state == ConversationState.THINKING</before>
      <action>await manager.handle_audio_chunk(np.zeros(1600, dtype=np.int16))</action>
      <after>manager.state == ConversationState.THINKING (unchanged, audio ignored)</after>
    </case>
    <case name="double_state_transition">
      <before>manager.state == ConversationState.IDLE</before>
      <action>await manager._set_state(ConversationState.SPEAKING)  # skip LISTENING</action>
      <after>ConversationError raised with message including "Invalid state transition"</after>
    </case>
    <case name="empty_audio">
      <before>manager.state == ConversationState.IDLE</before>
      <action>await manager.handle_audio_chunk(np.array([], dtype=np.int16))</action>
      <after>manager.state == ConversationState.IDLE (empty audio ignored)</after>
    </case>
    <case name="dismiss_from_speaking">
      <before>manager.state == ConversationState.SPEAKING</before>
      <action>await manager.dismiss()</action>
      <after>manager.state == ConversationState.IDLE</after>
    </case>
  </edge_case_audit>

  <evidence_of_success>
    cd /home/cabdru/clipcannon
    PYTHONPATH=src python -c "from voiceagent.conversation.state import ConversationState; print(list(ConversationState))"
    # Expected: [ConversationState.IDLE, ConversationState.LISTENING, ConversationState.THINKING, ConversationState.SPEAKING]

    PYTHONPATH=src python -c "
from voiceagent.conversation.manager import ConversationManager
print('ConversationManager imported OK')
print('Has handle_audio_chunk:', hasattr(ConversationManager, 'handle_audio_chunk'))
print('Has _generate_response:', hasattr(ConversationManager, '_generate_response'))
print('Has dismiss:', hasattr(ConversationManager, 'dismiss'))
"

    PYTHONPATH=src python -c "
from voiceagent.errors import ConversationError, VoiceAgentError
print('ConversationError is subclass of VoiceAgentError:', issubclass(ConversationError, VoiceAgentError))
"

    PYTHONPATH=src python -m pytest tests/voiceagent/test_conversation.py -v
    # All tests must pass
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  <test name="idle_to_listening">
    <input>ConversationManager in IDLE state, handle_audio_chunk(speech_audio) where VAD returns True</input>
    <expected>manager.state == ConversationState.LISTENING</expected>
  </test>
  <test name="full_pipeline">
    <input>ConversationManager in IDLE state, two handle_audio_chunk calls: first with speech (non-final ASR), second with speech (final ASR "hello")</input>
    <expected>manager.state == ConversationState.LISTENING (pipeline completed full cycle), manager.history has 2 entries (user + assistant)</expected>
  </test>
  <test name="invalid_transition">
    <input>ConversationManager in IDLE state, _set_state(ConversationState.SPEAKING)</input>
    <expected>ConversationError raised</expected>
  </test>
  <test name="dismiss_from_any">
    <input>ConversationManager in SPEAKING state, dismiss()</input>
    <expected>manager.state == ConversationState.IDLE</expected>
  </test>
</synthetic_test_data>

<manual_verification>
  <step>1. cd /home/cabdru/clipcannon</step>
  <step>2. Verify directories exist: ls -la src/voiceagent/conversation/</step>
  <step>3. Verify state enum: PYTHONPATH=src python -c "from voiceagent.conversation.state import ConversationState; assert len(ConversationState) == 4; print('PASS: 4 states')"</step>
  <step>4. Verify error hierarchy: PYTHONPATH=src python -c "from voiceagent.errors import ConversationError, VoiceAgentError; assert issubclass(ConversationError, VoiceAgentError); print('PASS: error hierarchy')"</step>
  <step>5. Verify manager imports: PYTHONPATH=src python -c "from voiceagent.conversation.manager import ConversationManager, VALID_TRANSITIONS; print('PASS: manager imports')"</step>
  <step>6. Run all tests: PYTHONPATH=src python -m pytest tests/voiceagent/test_conversation.py -v --tb=short</step>
  <step>7. Verify test count: at least 10 tests, all passing</step>
  <step>8. Verify no mock usage in tests: grep -c "mock\|Mock\|MagicMock\|patch" tests/voiceagent/test_conversation.py  # Should be 0</step>
</manual_verification>

<validation_criteria>
  <criterion>ConversationState enum has IDLE, LISTENING, THINKING, SPEAKING</criterion>
  <criterion>ConversationError is subclass of VoiceAgentError</criterion>
  <criterion>State transitions follow VALID_TRANSITIONS map</criterion>
  <criterion>Invalid transitions raise ConversationError with descriptive message</criterion>
  <criterion>handle_audio_chunk is no-op in THINKING/SPEAKING (no crash, no state change)</criterion>
  <criterion>handle_audio_chunk ignores empty audio</criterion>
  <criterion>dismiss() transitions any state to IDLE</criterion>
  <criterion>History correctly tracks user and assistant turns</criterion>
  <criterion>Protocol interfaces defined for dependency injection</criterion>
  <criterion>All tests use real state machine logic, NO mocks</criterion>
  <criterion>All tests pass</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -m pytest tests/voiceagent/test_conversation.py -v --tb=short</command>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -c "from voiceagent.conversation.state import ConversationState; print(list(ConversationState))"</command>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -c "from voiceagent.conversation.manager import ConversationManager; print('OK')"</command>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -c "from voiceagent.errors import ConversationError; raise ConversationError('test')" 2>&amp;1 | head -5</command>
</test_commands>
</task_spec>
```
