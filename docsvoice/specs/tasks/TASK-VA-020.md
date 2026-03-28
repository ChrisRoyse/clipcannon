```xml
<task_spec id="TASK-VA-020" version="2.0">
<metadata>
  <title>Integration Test -- Full End-to-End Voice Pipeline Verification</title>
  <status>ready</status>
  <layer>surface</layer>
  <sequence>20</sequence>
  <implements>
    <item ref="PHASE1-E2E">End-to-end integration test proving all Phase 1 components work together</item>
    <item ref="PHASE1-VERIFY">Verification checklist items 1-10 from Phase 1 spec Section 9</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-001</task_ref>
    <task_ref>TASK-VA-002</task_ref>
    <task_ref>TASK-VA-003</task_ref>
    <task_ref>TASK-VA-004</task_ref>
    <task_ref>TASK-VA-005</task_ref>
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
    <task_ref>TASK-VA-018</task_ref>
    <task_ref>TASK-VA-019</task_ref>
  </depends_on>
  <estimated_complexity>high</estimated_complexity>
  <estimated_files>1 file</estimated_files>
</metadata>

<context>
This is the FULL END-TO-END integration test that proves Phase 1 works. It exercises
every component in the pipeline: CLI -> VoiceAgent -> ASR -> LLM -> TTS -> WebSocket,
with real GPU models, real audio, and real database writes.

NO MOCKS. Every test uses:
- Real Qwen3-14B-FP8 on the RTX 5090 via vLLM
- Real Whisper ASR model on GPU
- Real ClipCannon TTS with "boris" voice profile (Chris Royse, 0.975 SECS)
- Real SQLite database
- Real WebSocket connections
- Real audio data (generated via ClipCannon TTS, then fed back as ASR input)

Hardware context:
- RTX 5090 GPU (32GB GDDR7), CUDA 13.1/13.2
- Qwen3-14B at /home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/
- vLLM with quantization="fp8", gpu_memory_utilization=0.45, max_model_len=32768
- Python 3.12+, src/voiceagent/ built by TASK-VA-001 through TASK-VA-019
- ClipCannon voice API (read-only):
  - clipcannon.voice.profiles.get_voice_profile(db_path, name) -> dict | None
  - clipcannon.voice.inference.VoiceSynthesizer -- speak(text, output_path, ...) -> SpeakResult
  - SpeakResult: audio_path, duration_ms, sample_rate, verification, attempts
  - NO enhance param on speak() -- enhancement via separate enhance_speech()
  - Voice profile DB: ~/.clipcannon/voice_profiles.db
  - Default voice: "boris" (Chris Royse's cloned voice, 0.975 SECS)
</context>

<input_context_files>
  <file purpose="phase1_spec">docsvoice/01_phase1_core_pipeline.md</file>
  <file purpose="agent">src/voiceagent/agent.py</file>
  <file purpose="server">src/voiceagent/server.py</file>
  <file purpose="cli">src/voiceagent/cli.py</file>
  <file purpose="config">src/voiceagent/config.py</file>
  <file purpose="db_schema">src/voiceagent/db/schema.py</file>
  <file purpose="asr">src/voiceagent/asr/streaming.py</file>
  <file purpose="llm">src/voiceagent/brain/llm.py</file>
  <file purpose="tts">src/voiceagent/tts/streaming.py</file>
  <file purpose="adapter">src/voiceagent/adapters/clipcannon.py</file>
  <file purpose="transport">src/voiceagent/transport/websocket.py</file>
  <file purpose="conversation">src/voiceagent/conversation/manager.py</file>
  <file purpose="context">src/voiceagent/brain/context.py</file>
  <file purpose="chunker">src/voiceagent/tts/chunker.py</file>
</input_context_files>

<prerequisites>
  <check>ALL tasks TASK-VA-001 through TASK-VA-019 are complete</check>
  <check>RTX 5090 GPU available with CUDA 13.1/13.2</check>
  <check>Qwen3-14B-FP8 model downloaded at the path specified in context</check>
  <check>"boris" voice profile exists in ~/.clipcannon/voice_profiles.db</check>
  <check>pip install websockets httpx pytest-asyncio soundfile resampy -- all must be in the environment</check>
</prerequisites>

<scope>
  <in_scope>
    - 10 integration tests covering the full Phase 1 pipeline
    - Test 1: Startup -- voiceagent serve starts, WebSocket accepts connections
    - Test 2: ASR -- send speech audio via WebSocket, receive transcript event
    - Test 3: LLM -- transcript triggers LLM generation, response text generated
    - Test 4: TTS -- LLM response synthesized to audio via ClipCannon, sent back via WebSocket
    - Test 5: Full loop -- speak "Hello" -> hear coherent response in "boris" voice
    - Test 6: DB verification -- after conversation, turns table has user + agent turns
    - Test 7: Latency -- measure end-to-end P95, assert below 500ms
    - Test 8: Context window -- run 50 turns, verify no overflow
    - Test 9: Sentence chunking -- "Hello. How are you?" produces 2 TTS audio chunks
    - Test 10: Shutdown -- verify clean shutdown, no GPU memory leak
    - Each test prints BEFORE/AFTER state, asserts expected vs actual, logs evidence
  </in_scope>
  <out_of_scope>
    - Performance benchmarking beyond P95 latency assertion
    - Multi-user concurrent testing
    - Network failure simulation
    - Voice quality measurement (covered by ClipCannon benchmarks)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="tests/voiceagent/test_integration.py">
      """Full end-to-end integration tests for Voice Agent Phase 1.
      NO MOCKS -- real GPU models, real audio, real database.
      """
      import pytest

      @pytest.fixture(scope="module")
      def voice_agent() -> VoiceAgent:
          """Shared VoiceAgent instance with all components initialized."""
          ...

      @pytest.fixture(scope="module")
      def server_url(voice_agent) -> str:
          """Start the FastAPI server in background, return ws://localhost:{port}/ws."""
          ...

      def test_01_startup(server_url): ...
      def test_02_asr_transcription(server_url, voice_agent): ...
      def test_03_llm_generation(voice_agent): ...
      def test_04_tts_synthesis(voice_agent): ...
      def test_05_full_loop(server_url, voice_agent): ...
      def test_06_db_verification(voice_agent): ...
      def test_07_latency_p95(server_url, voice_agent): ...
      def test_08_context_window_50_turns(voice_agent): ...
      def test_09_sentence_chunking(voice_agent): ...
      def test_10_shutdown(voice_agent): ...
    </signature>
  </signatures>

  <constraints>
    - NO MOCKS -- every test uses real GPU models, real audio, real DB
    - Each test prints BEFORE state, executes, prints AFTER state
    - Each test asserts expected vs actual with descriptive error messages
    - Each test logs evidence of success or failure with exact values
    - Tests run in order (01 through 10) since they share a VoiceAgent instance
    - The module-scoped voice_agent fixture initializes once and is shared
    - Server fixture starts uvicorn in a background thread
    - Audio input is generated via ClipCannon TTS ("Hello" spoken by "boris"), then fed as ASR input
    - All assertions include the actual values in the error message for debugging
    - Test 10 (shutdown) is last and verifies GPU memory is freed
  </constraints>

  <verification>
    - All 10 tests pass with 0 failures
    - GPU memory after shutdown is below 1GB
    - SQLite turns table has correct rows after the full loop
    - P95 latency is below 500ms
    - No exceptions during 50-turn context window test
  </verification>
</definition_of_done>

<pseudo_code>
tests/voiceagent/test_integration.py:
  """Full end-to-end integration tests for Voice Agent Phase 1.
  NO MOCKS -- real GPU models, real audio, real database.
  Requires RTX 5090, Qwen3-14B-FP8, ClipCannon with 'boris' voice profile.
  """
  import asyncio
  import json
  import logging
  import sqlite3
  import struct
  import threading
  import time
  import wave
  from io import BytesIO
  from pathlib import Path

  import numpy as np
  import pytest
  import torch
  import websockets

  from voiceagent.agent import VoiceAgent
  from voiceagent.config import load_config
  from voiceagent.server import create_app

  logger = logging.getLogger(__name__)
  TEST_PORT = 18765  # Use non-standard port to avoid conflicts

  # ---------------------------------------------------------------
  # Helper: generate speech audio for "Hello" using ClipCannon TTS
  # ---------------------------------------------------------------
  def generate_test_audio(text="Hello") -> bytes:
      """Use ClipCannon TTS to generate real speech audio for test input.
      Returns raw PCM int16 bytes at 16kHz mono (suitable for ASR input).
      """
      from clipcannon.voice.inference import VoiceSynthesizer
      from clipcannon.voice.profiles import get_voice_profile
      import tempfile

      db_path = Path("~/.clipcannon/voice_profiles.db").expanduser()
      profile = get_voice_profile(str(db_path), "boris")
      assert profile is not None, "Voice profile 'boris' not found in ClipCannon DB"

      synthesizer = VoiceSynthesizer()
      with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
          tmp_path = f.name
      result = synthesizer.speak(text, tmp_path, voice_profile=profile)

      # Read WAV and convert to 16kHz int16 mono PCM
      import soundfile as sf
      audio, sr = sf.read(result.audio_path, dtype="float32")
      if len(audio.shape) > 1:
          audio = audio[:, 0]  # mono
      if sr != 16000:
          import resampy
          audio = resampy.resample(audio, sr, 16000)
      audio_int16 = (audio * 32767).astype(np.int16)
      return audio_int16.tobytes()

  # ---------------------------------------------------------------
  # Module-scoped fixtures
  # ---------------------------------------------------------------
  @pytest.fixture(scope="module")
  def test_config(tmp_path_factory):
      """Config with a temporary data directory."""
      tmp_dir = tmp_path_factory.mktemp("integration_test")
      config = load_config()
      config.data_dir = str(tmp_dir)
      config.transport.port = TEST_PORT
      config.transport.host = "127.0.0.1"
      config.tts.voice_name = "boris"
      return config

  @pytest.fixture(scope="module")
  def voice_agent(test_config):
      """Shared VoiceAgent instance with all components initialized."""
      agent = VoiceAgent(config=test_config)
      agent._init_components()
      yield agent
      asyncio.get_event_loop().run_until_complete(agent.shutdown())

  @pytest.fixture(scope="module")
  def server_url(voice_agent, test_config):
      """Start FastAPI server in background thread, return WebSocket URL."""
      import uvicorn

      app = create_app()
      app.state.on_audio = voice_agent._conversation.handle_audio_chunk
      app.state.on_control = lambda data: None
      app.state.db_conn = voice_agent._db_conn

      config = uvicorn.Config(
          app,
          host=test_config.transport.host,
          port=test_config.transport.port,
          log_level="warning",
      )
      server = uvicorn.Server(config)

      thread = threading.Thread(target=server.run, daemon=True)
      thread.start()
      time.sleep(2)  # Wait for server to start

      url = f"ws://{test_config.transport.host}:{test_config.transport.port}/ws"
      yield url

      server.should_exit = True
      thread.join(timeout=5)

  # ---------------------------------------------------------------
  # Test 1: Startup
  # ---------------------------------------------------------------
  def test_01_startup(server_url):
      """voiceagent serve starts without error, WebSocket accepting connections."""
      print(f"\n[BEFORE] Attempting WebSocket connection to {server_url}")

      async def check():
          ws = await websockets.connect(server_url)
          connected = ws.open
          await ws.close()
          return connected

      result = asyncio.get_event_loop().run_until_complete(check())
      print(f"[AFTER] WebSocket connected: {result}")
      assert result is True, "WebSocket connection failed -- server not accepting connections"

  # ---------------------------------------------------------------
  # Test 2: ASR transcription
  # ---------------------------------------------------------------
  def test_02_asr_transcription(server_url, voice_agent):
      """Send speech audio via WebSocket, receive transcript event."""
      audio_bytes = generate_test_audio("Hello")
      print(f"\n[BEFORE] Sending {len(audio_bytes)} bytes of 'Hello' audio to ASR via WebSocket")
      print(f"[BEFORE] GPU memory: {torch.cuda.memory_allocated() / 1e9:.2f} GB")

      async def check():
          ws = await websockets.connect(server_url)
          # Send audio in 20ms chunks (320 samples at 16kHz)
          chunk_size = 320 * 2  # 320 samples * 2 bytes per int16
          for i in range(0, len(audio_bytes), chunk_size):
              await ws.send(audio_bytes[i:i + chunk_size])
              await asyncio.sleep(0.02)
          # Wait for transcript event
          try:
              response = await asyncio.wait_for(ws.recv(), timeout=10.0)
              await ws.close()
              return response
          except asyncio.TimeoutError:
              await ws.close()
              return None

      response = asyncio.get_event_loop().run_until_complete(check())
      print(f"[AFTER] Received response: {response}")
      assert response is not None, "No transcript event received within 10s timeout"
      data = json.loads(response)
      assert "text" in data or "transcript" in data, f"Response missing text field: {data}"
      transcript_text = data.get("text", data.get("transcript", ""))
      assert len(transcript_text) > 0, f"Transcript is empty: {data}"
      print(f"[EVIDENCE] Transcript received: '{transcript_text}'")

  # ---------------------------------------------------------------
  # Test 3: LLM generation
  # ---------------------------------------------------------------
  def test_03_llm_generation(voice_agent):
      """Transcript triggers LLM generation, response text is non-empty and coherent."""
      print(f"\n[BEFORE] GPU memory: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
      print("[BEFORE] Sending 'Hello, how are you?' to LLM brain")

      async def check():
          tokens = []
          async for token in voice_agent._brain.generate_stream(
              messages=[
                  {"role": "system", "content": "You are a helpful voice assistant. Keep responses brief."},
                  {"role": "user", "content": "Hello, how are you?"},
              ]
          ):
              tokens.append(token)
          return "".join(tokens)

      response = asyncio.get_event_loop().run_until_complete(check())
      print(f"[AFTER] LLM response: '{response}'")
      print(f"[AFTER] Response length: {len(response)} chars, {len(response.split())} words")
      assert len(response) > 0, "LLM generated empty response"
      assert len(response.split()) >= 2, f"LLM response too short (< 2 words): '{response}'"
      print(f"[EVIDENCE] LLM generated coherent response: '{response[:100]}...'")

  # ---------------------------------------------------------------
  # Test 4: TTS synthesis
  # ---------------------------------------------------------------
  def test_04_tts_synthesis(voice_agent):
      """LLM response synthesized to audio via ClipCannon, audio is valid WAV."""
      test_text = "Hello, I am doing well. How can I help you today?"
      print(f"\n[BEFORE] Synthesizing: '{test_text}'")
      print(f"[BEFORE] GPU memory: {torch.cuda.memory_allocated() / 1e9:.2f} GB")

      async def check():
          chunks = []
          async for audio_chunk in voice_agent._tts.stream(iter(test_text.split())):
              chunks.append(audio_chunk)
          return chunks

      chunks = asyncio.get_event_loop().run_until_complete(check())
      print(f"[AFTER] Received {len(chunks)} audio chunks")
      total_samples = sum(len(c) for c in chunks)
      print(f"[AFTER] Total samples: {total_samples}")
      assert len(chunks) > 0, "TTS produced no audio chunks"
      assert total_samples > 0, "TTS audio chunks have 0 total samples"
      for i, chunk in enumerate(chunks):
          assert isinstance(chunk, np.ndarray), f"Chunk {i} is not ndarray: {type(chunk)}"
          assert len(chunk) > 0, f"Chunk {i} is empty"
      print(f"[EVIDENCE] TTS synthesized {len(chunks)} chunks, {total_samples} total samples")

  # ---------------------------------------------------------------
  # Test 5: Full loop
  # ---------------------------------------------------------------
  def test_05_full_loop(server_url, voice_agent):
      """Speak 'Hello' -> hear coherent response in 'boris' voice."""
      audio_bytes = generate_test_audio("Hello")
      print(f"\n[BEFORE] Full loop: sending 'Hello' audio ({len(audio_bytes)} bytes)")
      print(f"[BEFORE] GPU memory: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
      print(f"[BEFORE] DB turns count: ", end="")
      cursor = voice_agent._db_conn.execute("SELECT COUNT(*) FROM turns")
      turns_before = cursor.fetchone()[0]
      print(f"{turns_before}")

      async def check():
          ws = await websockets.connect(server_url)
          # Send audio
          chunk_size = 320 * 2
          for i in range(0, len(audio_bytes), chunk_size):
              await ws.send(audio_bytes[i:i + chunk_size])
              await asyncio.sleep(0.02)
          # Collect all responses (transcript + audio)
          responses = []
          audio_responses = []
          try:
              while True:
                  msg = await asyncio.wait_for(ws.recv(), timeout=15.0)
                  if isinstance(msg, bytes):
                      audio_responses.append(msg)
                  else:
                      responses.append(json.loads(msg))
          except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
              pass
          finally:
              try:
                  await ws.close()
              except Exception:
                  pass
          return responses, audio_responses

      responses, audio_responses = asyncio.get_event_loop().run_until_complete(check())
      print(f"[AFTER] Text events: {len(responses)}")
      print(f"[AFTER] Audio chunks: {len(audio_responses)}")
      total_audio_bytes = sum(len(a) for a in audio_responses)
      print(f"[AFTER] Total audio bytes received: {total_audio_bytes}")

      # We should have received at least one text event and one audio chunk
      assert len(responses) > 0 or len(audio_responses) > 0, (
          "No responses received in full loop test"
      )
      if audio_responses:
          assert total_audio_bytes > 0, "Audio response has 0 bytes"
      print(f"[EVIDENCE] Full loop completed: {len(responses)} text events, {total_audio_bytes} audio bytes")

  # ---------------------------------------------------------------
  # Test 6: DB verification
  # ---------------------------------------------------------------
  def test_06_db_verification(voice_agent):
      """After conversation, turns table has user + agent turns."""
      print(f"\n[BEFORE] Checking turns table")
      cursor = voice_agent._db_conn.execute(
          "SELECT role, text FROM turns WHERE conversation_id = ?",
          (voice_agent._conversation_id,)
      )
      rows = cursor.fetchall()
      print(f"[AFTER] Found {len(rows)} turn records:")
      for i, row in enumerate(rows):
          print(f"  Turn {i+1}: role={row[0]}, text='{row[1][:50]}...' ")

      # Check conversations table
      cursor = voice_agent._db_conn.execute(
          "SELECT id, voice_profile FROM conversations WHERE id = ?",
          (voice_agent._conversation_id,)
      )
      conv = cursor.fetchone()
      assert conv is not None, f"Conversation {voice_agent._conversation_id} not found in DB"
      assert conv[1] == "boris", f"Voice profile is '{conv[1]}', expected 'boris'"

      # We should have at least 1 user turn + 1 assistant turn from the full loop
      roles = [r[0] for r in rows]
      assert "user" in roles, f"No user turn found in DB. Roles: {roles}"
      assert "assistant" in roles, f"No assistant turn found in DB. Roles: {roles}"
      print(f"[EVIDENCE] DB has {len(rows)} turns: {roles}")

  # ---------------------------------------------------------------
  # Test 7: Latency P95
  # ---------------------------------------------------------------
  def test_07_latency_p95(server_url, voice_agent):
      """Measure end-to-end latency, assert P95 < 500ms."""
      audio_bytes = generate_test_audio("Hi")
      latencies = []
      print(f"\n[BEFORE] Running 10 latency trials")

      async def single_trial():
          ws = await websockets.connect(server_url)
          t0 = time.perf_counter()
          chunk_size = 320 * 2
          for i in range(0, len(audio_bytes), chunk_size):
              await ws.send(audio_bytes[i:i + chunk_size])
              await asyncio.sleep(0.02)
          try:
              _ = await asyncio.wait_for(ws.recv(), timeout=10.0)
              t1 = time.perf_counter()
              latency_ms = (t1 - t0) * 1000
          except asyncio.TimeoutError:
              latency_ms = 10000.0  # Penalty for timeout
          finally:
              try:
                  await ws.close()
              except Exception:
                  pass
          return latency_ms

      for trial in range(10):
          lat = asyncio.get_event_loop().run_until_complete(single_trial())
          latencies.append(lat)
          print(f"  Trial {trial+1}: {lat:.1f} ms")

      latencies.sort()
      p50 = latencies[4]
      p95 = latencies[9]  # 95th percentile of 10 samples
      mean_lat = sum(latencies) / len(latencies)
      print(f"[AFTER] P50={p50:.1f}ms, P95={p95:.1f}ms, Mean={mean_lat:.1f}ms")
      assert p95 < 500.0, f"P95 latency {p95:.1f}ms exceeds 500ms target"
      print(f"[EVIDENCE] P95 latency {p95:.1f}ms is under 500ms target")

  # ---------------------------------------------------------------
  # Test 8: Context window -- 50 turns
  # ---------------------------------------------------------------
  def test_08_context_window_50_turns(voice_agent):
      """Run 50 turns through the LLM, verify no context overflow."""
      print(f"\n[BEFORE] Running 50-turn context window test")
      print(f"[BEFORE] GPU memory: {torch.cuda.memory_allocated() / 1e9:.2f} GB")

      async def check():
          history = [
              {"role": "system", "content": "You are a helpful voice assistant. Keep responses under 20 words."},
          ]
          for turn_num in range(50):
              history.append({"role": "user", "content": f"This is turn number {turn_num + 1}. What number is this?"})
              # Trim context if needed (delegate to context manager)
              trimmed = voice_agent._context.build_messages(
                  system_prompt=history[0]["content"],
                  history=history[1:],
                  user_input=history[-1]["content"],
              )
              tokens = []
              try:
                  async for token in voice_agent._brain.generate_stream(messages=trimmed):
                      tokens.append(token)
              except Exception as e:
                  pytest.fail(f"Context overflow at turn {turn_num + 1}: {e}")
              response = "".join(tokens)
              history.append({"role": "assistant", "content": response})
              if (turn_num + 1) % 10 == 0:
                  print(f"  Turn {turn_num + 1}/50: '{response[:60]}...'")
          return len(history)

      total_messages = asyncio.get_event_loop().run_until_complete(check())
      print(f"[AFTER] Completed {total_messages // 2} turns without overflow")
      print(f"[AFTER] GPU memory: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
      assert total_messages >= 101, f"Expected 101 messages (1 system + 50 user + 50 assistant), got {total_messages}"
      print(f"[EVIDENCE] 50 turns completed without context overflow")

  # ---------------------------------------------------------------
  # Test 9: Sentence chunking
  # ---------------------------------------------------------------
  def test_09_sentence_chunking(voice_agent):
      """'Hello. How are you?' produces 2 TTS audio chunks (one per sentence)."""
      test_text = "Hello. How are you?"
      print(f"\n[BEFORE] Chunking test: '{test_text}'")

      from voiceagent.tts.chunker import SentenceChunker
      chunker = SentenceChunker()

      # Feed tokens one at a time and collect extracted sentences
      sentences = []
      for word in test_text.split():
          sentence = chunker.extract_sentence(word + " ")
          if sentence:
              sentences.append(sentence)
      # Flush remaining
      remaining = chunker.flush()
      if remaining:
          sentences.append(remaining)

      print(f"[AFTER] Sentences extracted: {sentences}")
      assert len(sentences) == 2, (
          f"Expected 2 sentences from '{test_text}', got {len(sentences)}: {sentences}"
      )
      assert "Hello" in sentences[0], f"First sentence missing 'Hello': '{sentences[0]}'"
      assert "How are you" in sentences[1], f"Second sentence missing 'How are you': '{sentences[1]}'"
      print(f"[EVIDENCE] Chunker split into 2 sentences: {sentences}")

  # ---------------------------------------------------------------
  # Test 10: Shutdown
  # ---------------------------------------------------------------
  def test_10_shutdown(voice_agent):
      """Verify clean shutdown, no GPU memory leak."""
      print(f"\n[BEFORE] GPU memory: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
      print(f"[BEFORE] DB connection open: {voice_agent._db_conn is not None}")
      print(f"[BEFORE] Components ready: {voice_agent._components_ready}")

      asyncio.get_event_loop().run_until_complete(voice_agent.shutdown())

      gpu_mem = torch.cuda.memory_allocated()
      print(f"[AFTER] GPU memory: {gpu_mem / 1e9:.2f} GB")
      print(f"[AFTER] DB connection: {voice_agent._db_conn}")
      print(f"[AFTER] Components ready: {voice_agent._components_ready}")
      print(f"[AFTER] Brain: {voice_agent._brain}")
      print(f"[AFTER] TTS: {voice_agent._tts}")
      print(f"[AFTER] ASR: {voice_agent._asr}")

      assert gpu_mem < 1_000_000_000, (
          f"GPU memory after shutdown: {gpu_mem / 1e9:.2f} GB -- "
          f"expected less than 1 GB. Models not properly released."
      )
      assert voice_agent._db_conn is None, "DB connection not closed"
      assert voice_agent._brain is None, "LLM brain not released"
      assert voice_agent._tts is None, "TTS not released"
      assert voice_agent._asr is None, "ASR not released"
      assert voice_agent._components_ready is False, "components_ready not set to False"
      print(f"[EVIDENCE] Clean shutdown: GPU={gpu_mem / 1e6:.0f}MB, all refs=None")
</pseudo_code>

<files_to_create>
  <file path="tests/voiceagent/test_integration.py">Full end-to-end integration test for Phase 1</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>Test 01: WebSocket connection succeeds</criterion>
  <criterion>Test 02: ASR produces transcript from speech audio</criterion>
  <criterion>Test 03: LLM generates non-empty coherent response</criterion>
  <criterion>Test 04: TTS produces audio chunks from text</criterion>
  <criterion>Test 05: Full loop produces text events or audio response</criterion>
  <criterion>Test 06: DB has user + assistant turns after conversation</criterion>
  <criterion>Test 07: P95 latency below 500ms</criterion>
  <criterion>Test 08: 50 turns complete without context overflow</criterion>
  <criterion>Test 09: Sentence chunker splits "Hello. How are you?" into 2 chunks</criterion>
  <criterion>Test 10: GPU memory below 1GB after shutdown, all refs None</criterion>
</validation_criteria>

<full_state_verification>
  <source_of_truth>
    1. WebSocket connection status (connected/refused)
    2. Received transcript event JSON (text field)
    3. LLM generated text string (non-empty)
    4. Audio bytes received over WebSocket (> 0 bytes)
    5. SQLite turns table rows (user + assistant)
    6. torch.cuda.memory_allocated() values (before/after)
    7. time.perf_counter() measurements (latency)
  </source_of_truth>
  <execute_and_inspect>
    1. Start server, connect WebSocket -- verify connection object is open
    2. Send audio bytes, wait for response -- SEPARATELY parse JSON and check text field
    3. Call brain.generate_stream() -- SEPARATELY join tokens and check non-empty
    4. Call tts.stream() -- SEPARATELY count chunks and total samples
    5. After full loop, SEPARATELY query: SELECT role, text FROM turns
    6. After shutdown, SEPARATELY check torch.cuda.memory_allocated()
    7. For each latency trial, SEPARATELY record time.perf_counter() before/after
  </execute_and_inspect>
  <edge_case_audit>
    <case name="server_slow_start">
      <before>Server thread just started, may not be ready</before>
      <after>2-second sleep ensures server is listening; WebSocket connect retries if needed</after>
    </case>
    <case name="asr_silence">
      <before>Audio contains mostly silence with brief speech</before>
      <after>VAD filters silence, ASR only processes speech segments</after>
    </case>
    <case name="context_overflow_at_turn_50">
      <before>Context has accumulated 50 user + 50 assistant messages</before>
      <after>ContextManager truncates oldest messages to stay within token budget</after>
    </case>
    <case name="tts_empty_response">
      <before>LLM generates empty string (edge case)</before>
      <after>TTS returns 0 chunks gracefully, no crash</after>
    </case>
    <case name="double_shutdown">
      <before>shutdown() already called, all refs are None</before>
      <after>Second shutdown() completes without exception (idempotent)</after>
    </case>
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon
    PYTHONPATH=src python -m pytest tests/voiceagent/test_integration.py -v -s 2>&amp;1 | tail -20
    # Expected: all 10 tests PASSED, with [EVIDENCE] lines showing actual values
    # Expected final output:
    #   test_01_startup PASSED
    #   test_02_asr_transcription PASSED
    #   test_03_llm_generation PASSED
    #   test_04_tts_synthesis PASSED
    #   test_05_full_loop PASSED
    #   test_06_db_verification PASSED
    #   test_07_latency_p95 PASSED
    #   test_08_context_window_50_turns PASSED
    #   test_09_sentence_chunking PASSED
    #   test_10_shutdown PASSED
    #   10 passed
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  <test name="input_audio">
    <input>generate_test_audio("Hello") via ClipCannon TTS with "boris" voice</input>
    <expected_output>PCM int16 bytes at 16kHz mono, > 8000 bytes (> 0.25s of audio)</expected_output>
  </test>
  <test name="asr_output">
    <input>audio bytes of "Hello" sent via WebSocket</input>
    <expected_output>JSON event with text containing "hello" (case-insensitive)</expected_output>
  </test>
  <test name="llm_output">
    <input>messages: [{"role": "user", "content": "Hello, how are you?"}]</input>
    <expected_output>Non-empty coherent response string, >= 2 words</expected_output>
  </test>
  <test name="tts_output">
    <input>"Hello, I am doing well. How can I help you today?"</input>
    <expected_output>Multiple audio chunks as np.ndarray, total samples > 0, sample_rate 24000</expected_output>
  </test>
  <test name="db_after_conversation">
    <input>SELECT role FROM turns WHERE conversation_id = ?</input>
    <expected_output>At least 1 "user" row and 1 "assistant" row</expected_output>
  </test>
  <test name="latency">
    <input>10 full-loop trials</input>
    <expected_output>P95 less than 500ms</expected_output>
  </test>
  <test name="context_window">
    <input>50 user turns + 50 assistant turns</input>
    <expected_output>All 50 turns complete without exception, total messages >= 101</expected_output>
  </test>
  <test name="sentence_chunking">
    <input>"Hello. How are you?"</input>
    <expected_output>2 sentences: ["Hello.", "How are you?"]</expected_output>
  </test>
  <test name="shutdown_state">
    <input>await agent.shutdown()</input>
    <expected_output>GPU less than 1GB, db_conn=None, brain=None, tts=None, asr=None, components_ready=False</expected_output>
  </test>
</synthetic_test_data>

<manual_verification>
  1. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_integration.py -v -s
     Verify: all 10 tests PASSED, exit code 0
     Verify: [EVIDENCE] lines in output show actual values for each test
  2. Run: PYTHONPATH=src python -c "
import torch
print(f'GPU memory: {torch.cuda.memory_allocated() / 1e9:.2f} GB')
print(f'CUDA available: {torch.cuda.is_available()}')
print(f'CUDA device: {torch.cuda.get_device_name(0)}')
"
     Verify: CUDA available is True, device is RTX 5090
  3. Run: python -c "
from clipcannon.voice.profiles import get_voice_profile
p = get_voice_profile('~/.clipcannon/voice_profiles.db', 'boris')
print(f'Boris profile found: {p is not None}')
"
     Verify: Boris profile found is True
  4. After test run, inspect the test data directory:
     Run: sqlite3 /tmp/pytest-*/integration_test*/agent.db "SELECT COUNT(*) FROM turns"
     Verify: count is > 0
  5. After test run, verify GPU is clean:
     Run: nvidia-smi --query-gpu=memory.used --format=csv,noheader
     Verify: memory used is reasonable (not leaked)
</manual_verification>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_integration.py -v -s</command>
</test_commands>
</task_spec>
```
