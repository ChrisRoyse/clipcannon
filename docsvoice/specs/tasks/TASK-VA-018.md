```xml
<task_spec id="TASK-VA-018" version="2.0">
<metadata>
  <title>VoiceAgent Orchestrator -- Component Wiring and Lifecycle Management</title>
  <status>ready</status>
  <layer>surface</layer>
  <sequence>18</sequence>
  <implements>
    <item ref="PHASE1-AGENT">VoiceAgent class wiring all Phase 1 components</item>
    <item ref="PHASE1-LIFECYCLE">Startup, shutdown, and resource cleanup</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-003</task_ref>
    <task_ref>TASK-VA-006</task_ref>
    <task_ref>TASK-VA-007</task_ref>
    <task_ref>TASK-VA-008</task_ref>
    <task_ref>TASK-VA-009</task_ref>
    <task_ref>TASK-VA-010</task_ref>
    <task_ref>TASK-VA-011</task_ref>
    <task_ref>TASK-VA-012</task_ref>
    <task_ref>TASK-VA-013</task_ref>
    <task_ref>TASK-VA-014</task_ref>
    <task_ref>TASK-VA-015</task_ref>
    <task_ref>TASK-VA-016</task_ref>
    <task_ref>TASK-VA-017</task_ref>
  </depends_on>
  <estimated_complexity>high</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
The VoiceAgent is the top-level orchestrator that wires all Phase 1 components together
and manages the agent lifecycle. It is NOT the FastAPI server (TASK-VA-017) -- the server
is a separate thin HTTP/WS layer that the orchestrator configures and starts.

VoiceAgent wires: config -> DB -> ASR -> LLM -> TTS -> ConversationManager -> Transport -> Activation

Key lifecycle:
- __init__(config=None) -- loads config, does NOT load GPU models yet (lazy init)
- _init_components() -- initializes ALL components, loads GPU models onto the RTX 5090
- start() -- calls _init_components() then starts the WebSocket server via uvicorn
- talk_interactive() -- local mic mode using sounddevice for capture
- shutdown() -- releases ALL GPU resources (LLM, ASR, TTS), closes DB connection
- _log_turn() -- writes a turn record to the SQLite turns table

NO MOCKS in tests. REAL integration test with all components:
1. Create VoiceAgent with test config
2. Call _init_components() -- this loads real GPU models onto the RTX 5090
3. Verify DB was created: sqlite3 agent.db ".tables" shows conversations, turns, metrics
4. Create a conversation: verify row in conversations table
5. Log a turn: verify row in turns table with correct fields
6. Shutdown: verify GPU memory freed (torch.cuda.memory_allocated() less than 1GB)

Hardware context:
- RTX 5090 GPU (32GB GDDR7), CUDA 13.1/13.2
- Qwen3-14B at /home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/
- vLLM with quantization="fp8", gpu_memory_utilization=0.45, max_model_len=32768
- Python 3.12+, src/voiceagent/ is greenfield (does not exist yet)
- All imports: PYTHONPATH=src python -c "from voiceagent.agent import VoiceAgent"
- ClipCannon voice API (read-only):
  - clipcannon.voice.profiles.get_voice_profile(db_path, name) -> dict | None
  - clipcannon.voice.inference.VoiceSynthesizer -- speak(text, output_path, ...) -> SpeakResult
  - SpeakResult: audio_path, duration_ms, sample_rate, verification, attempts
  - NO enhance param on speak() -- enhancement via separate enhance_speech()
  - Voice profile DB: ~/.clipcannon/voice_profiles.db
  - Default voice: "boris" (Chris Royse's cloned voice, 0.975 SECS)
</context>

<input_context_files>
  <file purpose="agent_spec">docsvoice/01_phase1_core_pipeline.md</file>
  <file purpose="config">src/voiceagent/config.py</file>
  <file purpose="errors">src/voiceagent/errors.py</file>
  <file purpose="db_schema">src/voiceagent/db/schema.py</file>
  <file purpose="db_connection">src/voiceagent/db/connection.py</file>
  <file purpose="vad">src/voiceagent/asr/vad.py</file>
  <file purpose="streaming_asr">src/voiceagent/asr/streaming.py</file>
  <file purpose="llm">src/voiceagent/brain/llm.py</file>
  <file purpose="prompts">src/voiceagent/brain/prompts.py</file>
  <file purpose="context">src/voiceagent/brain/context.py</file>
  <file purpose="adapter">src/voiceagent/adapters/clipcannon.py</file>
  <file purpose="chunker">src/voiceagent/tts/chunker.py</file>
  <file purpose="streaming_tts">src/voiceagent/tts/streaming.py</file>
  <file purpose="conv_state">src/voiceagent/conversation/state.py</file>
  <file purpose="conv_manager">src/voiceagent/conversation/manager.py</file>
  <file purpose="wake_word">src/voiceagent/activation/wake_word.py</file>
  <file purpose="hotkey">src/voiceagent/activation/hotkey.py</file>
  <file purpose="transport">src/voiceagent/transport/websocket.py</file>
  <file purpose="server">src/voiceagent/server.py</file>
</input_context_files>

<prerequisites>
  <check>All logic layer tasks (TASK-VA-005 through TASK-VA-015) complete</check>
  <check>TASK-VA-003 complete (database schema at src/voiceagent/db/schema.py)</check>
  <check>TASK-VA-016 complete (WebSocket transport at src/voiceagent/transport/websocket.py)</check>
  <check>TASK-VA-017 complete (FastAPI server at src/voiceagent/server.py)</check>
  <check>RTX 5090 GPU available with CUDA 13.1/13.2</check>
  <check>Qwen3-14B-FP8 model downloaded at the path specified in context</check>
  <check>pip install sounddevice uvicorn -- both must be in the environment</check>
</prerequisites>

<scope>
  <in_scope>
    - VoiceAgent class in src/voiceagent/agent.py
    - __init__(config=None) -- loads config only, NO GPU model loading
    - _init_components() -- initializes ALL components, loads GPU models
    - start() -- calls _init_components() then starts FastAPI/WebSocket server via uvicorn
    - talk_interactive() -- runs local mic-based conversation using sounddevice
    - shutdown() -- releases ALL GPU resources, closes DB connection
    - _log_turn() -- writes turn record to SQLite turns table
    - Database logging: record conversations and turns in SQLite
    - Wire wake word and hotkey to conversation manager
    - REAL integration tests (NO MOCKS) that load GPU models and verify DB state
  </in_scope>
  <out_of_scope>
    - CLI argument parsing (TASK-VA-019)
    - Full end-to-end integration test (TASK-VA-020)
    - Hot reload
    - Multi-user support
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/agent.py">
      class VoiceAgent:
          def __init__(self, config: VoiceAgentConfig | None = None) -> None:
              """Load config. Do NOT load GPU models yet."""
              ...

          def _init_components(self) -> None:
              """Initialize ALL components: DB, ASR, LLM, TTS, transport, activation.
              This is where GPU models are loaded onto the RTX 5090."""
              ...

          async def start(self) -> None:
              """Call _init_components() then start the WebSocket server."""
              ...

          async def talk_interactive(self) -> None:
              """Interactive local mic conversation using sounddevice."""
              ...

          async def shutdown(self) -> None:
              """Release ALL GPU resources and close DB connection."""
              ...

          def _log_turn(self, conversation_id: str, role: str, text: str, timing: dict | None = None) -> None:
              """Write a turn record to the SQLite turns table."""
              ...
    </signature>
  </signatures>

  <constraints>
    - Config loaded from default path if not provided; missing config file creates default
    - __init__ ONLY loads config -- does NOT touch GPU or DB
    - _init_components() initializes all subsystems and loads GPU models
    - Database initialized via init_db() on startup
    - New conversation record created in conversations table on start
    - Each turn logged to turns table with timing metrics (asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms)
    - shutdown() calls release() on LLM brain and TTS adapter
    - shutdown() closes database connection
    - shutdown() called twice must not raise (idempotent)
    - Uses asyncio for all async operations
    - Catches and logs component initialization errors with WHAT failed, WHY, and HOW to fix
    - talk_interactive uses sounddevice for local mic capture
    - start() uses uvicorn.run() to serve the FastAPI app from TASK-VA-017
  </constraints>

  <verification>
    - VoiceAgent(config) instantiates without loading GPU models (torch.cuda.memory_allocated() unchanged)
    - _init_components() initializes all subsystems and GPU memory increases
    - DB was created: sqlite3 agent.db ".tables" shows conversations, turns, metrics
    - Conversation record exists in conversations table after _init_components()
    - _log_turn() writes to turns table; SELECT confirms row with correct fields
    - shutdown() releases GPU memory: torch.cuda.memory_allocated() less than 1GB
    - shutdown() called twice does not raise
    - pytest tests/voiceagent/test_agent.py passes with 0 failures
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/agent.py:
  """VoiceAgent -- top-level orchestrator for the voice pipeline."""
  import asyncio
  import logging
  import uuid
  from datetime import datetime
  from pathlib import Path
  from voiceagent.config import VoiceAgentConfig, load_config
  from voiceagent.db.schema import init_db
  from voiceagent.db.connection import get_connection
  from voiceagent.errors import VoiceAgentError

  logger = logging.getLogger(__name__)

  class VoiceAgent:
      def __init__(self, config=None):
          """Load config only. Do NOT load GPU models."""
          self._config = config or load_config()
          self._conversation_id = None
          self._db_conn = None
          self._components_ready = False
          # All component refs start as None
          self._asr = None
          self._brain = None
          self._tts = None
          self._transport = None
          self._conversation = None
          self._wake_word = None
          self._hotkey = None
          self._context = None

      def _init_components(self):
          """Initialize ALL pipeline components. Loads GPU models."""
          logger.info("Initializing voice agent components...")
          data_dir = Path(self._config.data_dir).expanduser()
          data_dir.mkdir(parents=True, exist_ok=True)
          db_path = data_dir / "agent.db"

          # Database
          try:
              init_db(db_path)
              self._db_conn = get_connection(db_path)
              logger.info("Database initialized at %s", db_path)
          except Exception as e:
              raise VoiceAgentError(
                  f"Database init failed: {e}. "
                  f"Check write permissions on {data_dir} and SQLite availability."
              ) from e

          # ASR (loads Whisper model to GPU)
          try:
              from voiceagent.asr.vad import SileroVAD
              from voiceagent.asr.streaming import StreamingASR
              vad = SileroVAD(threshold=self._config.asr.vad_threshold)
              self._asr = StreamingASR(self._config.asr, vad=vad)
              logger.info("ASR initialized (VAD threshold=%.2f)", self._config.asr.vad_threshold)
          except Exception as e:
              raise VoiceAgentError(
                  f"ASR init failed: {e}. "
                  f"Check that Whisper model is available and CUDA is working. "
                  f"Run: python -c 'import torch; print(torch.cuda.is_available())'"
              ) from e

          # LLM (loads Qwen3-14B-FP8 to GPU via vLLM)
          try:
              from voiceagent.brain.llm import LLMBrain
              from voiceagent.brain.prompts import build_system_prompt
              from voiceagent.brain.context import ContextManager
              self._brain = LLMBrain(self._config.llm)
              self._system_prompt = build_system_prompt(self._config.tts.voice_name)
              self._context = ContextManager(tokenizer_path=self._config.llm.model_path)
              logger.info("LLM initialized (model=%s)", self._config.llm.model_path)
          except Exception as e:
              raise VoiceAgentError(
                  f"LLM init failed: {e}. "
                  f"Check that Qwen3-14B-FP8 exists at {self._config.llm.model_path} "
                  f"and vLLM is installed: pip install vllm"
              ) from e

          # TTS (loads ClipCannon adapter)
          try:
              from voiceagent.adapters.clipcannon import ClipCannonAdapter
              from voiceagent.tts.chunker import SentenceChunker
              from voiceagent.tts.streaming import StreamingTTS
              adapter = ClipCannonAdapter(voice_name=self._config.tts.voice_name)
              chunker = SentenceChunker()
              self._tts = StreamingTTS(adapter=adapter, chunker=chunker)
              logger.info("TTS initialized (voice=%s)", self._config.tts.voice_name)
          except Exception as e:
              raise VoiceAgentError(
                  f"TTS init failed: {e}. "
                  f"Check ClipCannon voice profile '{self._config.tts.voice_name}' exists: "
                  f"python -c \"from clipcannon.voice.profiles import get_voice_profile; "
                  f"print(get_voice_profile('~/.clipcannon/voice_profiles.db', '{self._config.tts.voice_name}'))\""
              ) from e

          # Transport
          try:
              from voiceagent.transport.websocket import WebSocketTransport
              self._transport = WebSocketTransport(
                  host=self._config.transport.host,
                  port=self._config.transport.port,
              )
              logger.info("Transport initialized (ws://%s:%d/ws)", self._config.transport.host, self._config.transport.port)
          except Exception as e:
              raise VoiceAgentError(f"Transport init failed: {e}") from e

          # Conversation manager
          try:
              from voiceagent.conversation.manager import ConversationManager
              self._conversation = ConversationManager(
                  asr=self._asr, brain=self._brain, tts=self._tts,
                  transport=self._transport, context_manager=self._context,
                  system_prompt=self._system_prompt,
              )
              logger.info("Conversation manager initialized")
          except Exception as e:
              raise VoiceAgentError(f"Conversation manager init failed: {e}") from e

          # Activation
          from voiceagent.activation.wake_word import WakeWordDetector
          from voiceagent.activation.hotkey import HotkeyActivator
          try:
              self._wake_word = WakeWordDetector()
              logger.info("Wake word detector initialized")
          except Exception:
              logger.warning("Wake word detector unavailable -- hotkey-only activation")
              self._wake_word = None
          self._hotkey = HotkeyActivator(callback=self._on_hotkey)

          # Create conversation record in DB
          self._conversation_id = str(uuid.uuid4())
          self._db_conn.execute(
              "INSERT INTO conversations (id, started_at, voice_profile, turn_count) VALUES (?, ?, ?, ?)",
              (self._conversation_id, datetime.now().isoformat(), self._config.tts.voice_name, 0)
          )
          self._db_conn.commit()
          self._components_ready = True
          logger.info("All components initialized. Conversation ID: %s", self._conversation_id)

      def _on_hotkey(self):
          """Handle hotkey press -- toggle listening state."""
          if self._conversation:
              self._conversation.toggle_listening()

      def _log_turn(self, conversation_id, role, text, timing=None):
          """Write a turn record to the SQLite turns table."""
          if self._db_conn is None:
              logger.error("Cannot log turn: DB connection is None")
              return
          timing = timing or {}
          self._db_conn.execute(
              "INSERT INTO turns (id, conversation_id, role, text, started_at, asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (str(uuid.uuid4()), conversation_id, role, text, datetime.now().isoformat(),
               timing.get("asr_ms"), timing.get("llm_ttft_ms"),
               timing.get("tts_ttfb_ms"), timing.get("total_ms"))
          )
          self._db_conn.commit()

      async def start(self):
          """Start the voice agent server."""
          self._init_components()

          # Create FastAPI app and wire callbacks
          from voiceagent.server import create_app
          app = create_app()
          app.state.on_audio = self._conversation.handle_audio_chunk
          app.state.on_control = self._on_control
          app.state.db_conn = self._db_conn

          self._hotkey.start()
          logger.info("Voice Agent started (conversation: %s)", self._conversation_id)

          import uvicorn
          config = uvicorn.Config(
              app,
              host=self._config.transport.host,
              port=self._config.transport.port,
              log_level="info",
          )
          server = uvicorn.Server(config)
          await server.serve()

      async def _on_control(self, data):
          """Handle control messages from WebSocket clients."""
          action = data.get("action")
          if action == "start_listening":
              if self._conversation:
                  self._conversation.toggle_listening()
          elif action == "stop":
              await self.shutdown()

      async def talk_interactive(self):
          """Run interactive voice conversation using local microphone."""
          self._init_components()
          logger.info("Starting interactive voice conversation (voice=%s)", self._config.tts.voice_name)
          logger.info("Press Ctrl+C to stop")

          import sounddevice as sd
          import numpy as np

          sample_rate = 16000
          block_size = int(sample_rate * 0.02)  # 20ms chunks

          def audio_callback(indata, frames, time_info, status):
              if status:
                  logger.warning("Audio input status: %s", status)
              audio_chunk = indata[:, 0].copy()  # mono
              audio_int16 = (audio_chunk * 32767).astype(np.int16)
              asyncio.get_event_loop().call_soon_threadsafe(
                  asyncio.ensure_future,
                  self._conversation.handle_audio_chunk(audio_int16)
              )

          with sd.InputStream(
              samplerate=sample_rate,
              blocksize=block_size,
              channels=1,
              dtype="float32",
              callback=audio_callback,
          ):
              try:
                  while True:
                      await asyncio.sleep(0.1)
              except asyncio.CancelledError:
                  pass

      async def shutdown(self):
          """Release ALL resources: GPU memory, DB connection, activation listeners."""
          logger.info("Shutting down Voice Agent...")

          # Stop activation listeners
          if self._hotkey is not None:
              try:
                  self._hotkey.stop()
              except Exception:
                  pass

          # Release LLM (frees GPU memory)
          if self._brain is not None:
              try:
                  self._brain.release()
                  logger.info("LLM brain released")
              except Exception as e:
                  logger.warning("Error releasing LLM brain: %s", e)
              self._brain = None

          # Release TTS adapter (frees GPU memory if applicable)
          if self._tts is not None:
              try:
                  if hasattr(self._tts, 'adapter') and self._tts.adapter is not None:
                      self._tts.adapter.release()
                      logger.info("TTS adapter released")
              except Exception as e:
                  logger.warning("Error releasing TTS adapter: %s", e)
              self._tts = None

          # Release ASR (frees GPU memory)
          if self._asr is not None:
              try:
                  if hasattr(self._asr, 'release'):
                      self._asr.release()
                      logger.info("ASR released")
              except Exception as e:
                  logger.warning("Error releasing ASR: %s", e)
              self._asr = None

          # Close DB connection
          if self._db_conn is not None:
              try:
                  self._db_conn.close()
                  logger.info("Database connection closed")
              except Exception as e:
                  logger.warning("Error closing DB: %s", e)
              self._db_conn = None

          self._components_ready = False
          logger.info("Voice Agent shutdown complete")

tests/voiceagent/test_agent.py:
  """REAL integration tests for VoiceAgent -- NO MOCKS.
  These tests load actual GPU models and verify real DB state."""
  import pytest
  import sqlite3
  import torch
  from pathlib import Path
  from voiceagent.agent import VoiceAgent
  from voiceagent.config import VoiceAgentConfig, load_config

  @pytest.fixture
  def test_config(tmp_path):
      """Create a test config pointing to a temporary data directory."""
      config = load_config()
      config.data_dir = str(tmp_path / "voiceagent_test")
      return config

  def test_agent_instantiates_without_loading_models(test_config):
      """VoiceAgent.__init__ loads config only -- GPU memory should not change."""
      mem_before = torch.cuda.memory_allocated()
      agent = VoiceAgent(config=test_config)
      mem_after = torch.cuda.memory_allocated()
      assert agent._config is not None
      assert agent._components_ready is False
      assert agent._brain is None
      assert agent._asr is None
      # GPU memory should not have increased significantly (tolerance: 1MB)
      assert abs(mem_after - mem_before) < 1_000_000, (
          f"GPU memory changed by {mem_after - mem_before} bytes during __init__ -- "
          f"models should NOT be loaded in __init__"
      )

  def test_init_components_creates_db(test_config):
      """_init_components() creates agent.db with conversations, turns, metrics tables."""
      agent = VoiceAgent(config=test_config)
      agent._init_components()
      try:
          db_path = Path(test_config.data_dir) / "agent.db"
          assert db_path.exists(), f"Database not found at {db_path}"
          conn = sqlite3.connect(str(db_path))
          cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
          tables = sorted([row[0] for row in cursor.fetchall()])
          conn.close()
          assert "conversations" in tables, f"conversations table missing. Found: {tables}"
          assert "turns" in tables, f"turns table missing. Found: {tables}"
          assert "metrics" in tables, f"metrics table missing. Found: {tables}"
      finally:
          import asyncio
          asyncio.get_event_loop().run_until_complete(agent.shutdown())

  def test_init_components_creates_conversation_record(test_config):
      """After _init_components(), a conversation row exists in the DB."""
      agent = VoiceAgent(config=test_config)
      agent._init_components()
      try:
          assert agent._conversation_id is not None
          cursor = agent._db_conn.execute(
              "SELECT id, voice_profile FROM conversations WHERE id = ?",
              (agent._conversation_id,)
          )
          row = cursor.fetchone()
          assert row is not None, "Conversation record not found in DB"
          assert row[0] == agent._conversation_id
          assert row[1] == test_config.tts.voice_name
      finally:
          import asyncio
          asyncio.get_event_loop().run_until_complete(agent.shutdown())

  def test_log_turn_writes_to_db(test_config):
      """_log_turn() inserts a row into the turns table with correct fields."""
      agent = VoiceAgent(config=test_config)
      agent._init_components()
      try:
          agent._log_turn(
              conversation_id=agent._conversation_id,
              role="user",
              text="Hello, how are you?",
              timing={"asr_ms": 45.2, "llm_ttft_ms": 120.0, "tts_ttfb_ms": 80.5, "total_ms": 310.0}
          )
          cursor = agent._db_conn.execute(
              "SELECT role, text, asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms FROM turns WHERE conversation_id = ?",
              (agent._conversation_id,)
          )
          row = cursor.fetchone()
          assert row is not None, "Turn record not found in DB"
          assert row[0] == "user"
          assert row[1] == "Hello, how are you?"
          assert row[2] == 45.2  # asr_ms
          assert row[3] == 120.0  # llm_ttft_ms
          assert row[4] == 80.5  # tts_ttfb_ms
          assert row[5] == 310.0  # total_ms
      finally:
          import asyncio
          asyncio.get_event_loop().run_until_complete(agent.shutdown())

  def test_shutdown_releases_gpu_memory(test_config):
      """After shutdown(), GPU memory allocated should be less than 1GB."""
      agent = VoiceAgent(config=test_config)
      agent._init_components()
      import asyncio
      asyncio.get_event_loop().run_until_complete(agent.shutdown())
      gpu_mem = torch.cuda.memory_allocated()
      assert gpu_mem < 1_000_000_000, (
          f"GPU memory after shutdown: {gpu_mem / 1e9:.2f} GB -- "
          f"expected less than 1 GB. Models not properly released."
      )

  def test_shutdown_idempotent(test_config):
      """Calling shutdown() twice does not raise an exception."""
      agent = VoiceAgent(config=test_config)
      agent._init_components()
      import asyncio
      asyncio.get_event_loop().run_until_complete(agent.shutdown())
      # Second call should not raise
      asyncio.get_event_loop().run_until_complete(agent.shutdown())

  def test_config_missing_creates_default():
      """VoiceAgent() with no config arg loads default config without error."""
      agent = VoiceAgent()
      assert agent._config is not None
      assert agent._components_ready is False

  def test_db_already_exists_is_idempotent(test_config):
      """If agent.db already exists, _init_components() does not fail."""
      # First agent creates the DB
      agent1 = VoiceAgent(config=test_config)
      agent1._init_components()
      import asyncio
      asyncio.get_event_loop().run_until_complete(agent1.shutdown())
      # Second agent reuses the same data_dir
      agent2 = VoiceAgent(config=test_config)
      agent2._init_components()
      try:
          assert agent2._components_ready is True
          # Both conversations should exist
          cursor = agent2._db_conn.execute("SELECT COUNT(*) FROM conversations")
          count = cursor.fetchone()[0]
          assert count == 2, f"Expected 2 conversation records, got {count}"
      finally:
          asyncio.get_event_loop().run_until_complete(agent2.shutdown())
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/agent.py">VoiceAgent orchestrator class</file>
  <file path="tests/voiceagent/test_agent.py">REAL integration tests with GPU models and SQLite verification</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>VoiceAgent() instantiates without loading GPU models</criterion>
  <criterion>_init_components() initializes all subsystems and loads GPU models</criterion>
  <criterion>Database created at data_dir/agent.db with conversations, turns, metrics tables</criterion>
  <criterion>Conversation record created in DB after _init_components()</criterion>
  <criterion>_log_turn() writes to turns table with correct timing fields</criterion>
  <criterion>shutdown() releases GPU memory to below 1GB</criterion>
  <criterion>shutdown() is idempotent (calling twice does not raise)</criterion>
  <criterion>DB already existing does not cause failure (idempotent init)</criterion>
  <criterion>Missing config file creates default config</criterion>
  <criterion>All tests pass with 0 failures</criterion>
</validation_criteria>

<full_state_verification>
  <source_of_truth>SQLite database (agent.db) AND GPU memory state (torch.cuda.memory_allocated())</source_of_truth>
  <execute_and_inspect>
    1. Create VoiceAgent with test config -- verify _components_ready is False
    2. Record torch.cuda.memory_allocated() BEFORE _init_components()
    3. Call _init_components() -- verify _components_ready is True
    4. Record torch.cuda.memory_allocated() AFTER -- must be significantly higher
    5. SEPARATELY read agent.db: sqlite3 agent.db ".tables" must show conversations, turns, metrics
    6. SEPARATELY query: SELECT * FROM conversations -- must have 1 row with correct conversation_id
    7. Call _log_turn() then SEPARATELY query: SELECT * FROM turns -- must have 1 row
    8. Call shutdown() then SEPARATELY check torch.cuda.memory_allocated() -- must be below 1GB
  </execute_and_inspect>
  <edge_case_audit>
    <case name="config_file_missing">
      <before>No config file at default path (~/.voiceagent/config.json)</before>
      <after>VoiceAgent() creates and uses a default config without error</after>
    </case>
    <case name="db_already_exists">
      <before>agent.db exists from a previous run with tables already created</before>
      <after>_init_components() succeeds idempotently, new conversation row added alongside old ones</after>
    </case>
    <case name="shutdown_called_twice">
      <before>First shutdown() releases all resources, sets refs to None</before>
      <after>Second shutdown() completes without raising any exception</after>
    </case>
    <case name="component_init_failure">
      <before>Whisper model path is invalid</before>
      <after>VoiceAgentError raised with message containing WHAT failed, WHY, and HOW to fix</after>
    </case>
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon
    PYTHONPATH=src python -m pytest tests/voiceagent/test_agent.py -v 2>&amp;1 | grep -E "PASSED|FAILED|ERROR"
    # Expected: all lines show PASSED, 0 FAILED, 0 ERROR

    PYTHONPATH=src python -c "
import torch
from voiceagent.agent import VoiceAgent
mem_before = torch.cuda.memory_allocated()
agent = VoiceAgent()
mem_after_init = torch.cuda.memory_allocated()
print(f'After __init__: GPU delta = {(mem_after_init - mem_before) / 1e6:.1f} MB (should be ~0)')
agent._init_components()
mem_after_components = torch.cuda.memory_allocated()
print(f'After _init_components: GPU = {mem_after_components / 1e9:.2f} GB (should be > 5 GB)')
import asyncio
asyncio.run(agent.shutdown())
mem_after_shutdown = torch.cuda.memory_allocated()
print(f'After shutdown: GPU = {mem_after_shutdown / 1e9:.2f} GB (should be < 1 GB)')
"
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  <test name="instantiate_no_gpu">
    <input>VoiceAgent(config=test_config)</input>
    <expected_output>_components_ready == False, _brain == None, GPU delta &lt; 1MB</expected_output>
  </test>
  <test name="init_creates_db">
    <input>agent._init_components()</input>
    <expected_output>agent.db exists, tables = [conversations, metrics, turns]</expected_output>
  </test>
  <test name="conversation_record">
    <input>SELECT id, voice_profile FROM conversations WHERE id = {conversation_id}</input>
    <expected_output>1 row: (conversation_id, "boris")</expected_output>
  </test>
  <test name="log_turn">
    <input>_log_turn(conv_id, "user", "Hello", {"asr_ms": 45.2, "total_ms": 310.0})</input>
    <expected_output>SELECT role, text, asr_ms, total_ms FROM turns -> ("user", "Hello", 45.2, 310.0)</expected_output>
  </test>
  <test name="shutdown_gpu">
    <input>await agent.shutdown()</input>
    <expected_output>torch.cuda.memory_allocated() &lt; 1_000_000_000</expected_output>
  </test>
</synthetic_test_data>

<manual_verification>
  1. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_agent.py -v
     Verify: all tests PASSED, exit code 0
  2. Run: PYTHONPATH=src python -c "from voiceagent.agent import VoiceAgent; a = VoiceAgent(); print('OK:', a._components_ready)"
     Verify: output is "OK: False"
  3. Run: PYTHONPATH=src python -c "
import torch
from voiceagent.agent import VoiceAgent
a = VoiceAgent()
a._init_components()
print('DB conn:', a._db_conn is not None)
print('Conv ID:', a._conversation_id)
print('GPU MB:', torch.cuda.memory_allocated() / 1e6)
import asyncio; asyncio.run(a.shutdown())
print('Post-shutdown GPU MB:', torch.cuda.memory_allocated() / 1e6)
"
     Verify: DB conn is True, Conv ID is a UUID, GPU MB is significant after init, low after shutdown
  4. Run: sqlite3 /tmp/test_voiceagent/agent.db ".tables"
     Verify: output contains "conversations  metrics  turns"
</manual_verification>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_agent.py -v</command>
</test_commands>
</task_spec>
```
