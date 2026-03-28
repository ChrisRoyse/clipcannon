```xml
<task_spec id="TASK-VA-017" version="2.0">
<metadata>
  <title>FastAPI Server -- Health Endpoint and WebSocket Route</title>
  <status>ready</status>
  <layer>surface</layer>
  <sequence>17</sequence>
  <implements>
    <item ref="PHASE1-SERVER">FastAPI server with health check, REST endpoints, and WebSocket endpoint</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-002</task_ref>
    <task_ref>TASK-VA-016</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Creates the FastAPI HTTP server that exposes the voice agent over HTTP and WebSocket.
The server is SEPARATE from the VoiceAgent orchestrator (TASK-VA-018) -- the server
hosts the network interface, while the orchestrator manages the pipeline lifecycle.

The server provides:
- GET /health -- monitoring endpoint returning status, version, and uptime
- GET /conversations/{id} -- retrieve conversation details from the database
- WebSocket ws://localhost:8765/ws -- bidirectional audio/control channel

The server is started by the CLI (TASK-VA-019) via uvicorn. The orchestrator
(TASK-VA-018) wires its callbacks into the app after creation.

Hardware context:
- RTX 5090 GPU (32GB GDDR7), CUDA 13.1/13.2
- Python 3.12+, src/voiceagent/ is greenfield (does not exist yet)
- All imports: PYTHONPATH=src python -c "from voiceagent.server import create_app"
</context>

<input_context_files>
  <file purpose="server_spec">docsvoice/01_phase1_core_pipeline.md#section-8</file>
  <file purpose="config">src/voiceagent/config.py</file>
  <file purpose="transport">src/voiceagent/transport/websocket.py</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-002 complete (config available at src/voiceagent/config.py)</check>
  <check>TASK-VA-016 complete (WebSocketTransport available at src/voiceagent/transport/websocket.py)</check>
  <check>pip install fastapi uvicorn httpx websockets -- all must be in the environment</check>
</prerequisites>

<scope>
  <in_scope>
    - FastAPI app creation in src/voiceagent/server.py
    - GET /health endpoint returning {"status": "ok", "version": "0.1.0", "uptime_s": float}
    - GET /conversations/{id} endpoint returning conversation data from SQLite
    - WebSocket /ws route at ws://localhost:8765/ws for bidirectional audio streaming
    - create_app() factory function
    - Server tracks startup time for uptime calculation
    - Tests using httpx + fastapi.testclient.TestClient for REST, websockets for WS
  </in_scope>
  <out_of_scope>
    - VoiceAgent lifecycle management (TASK-VA-018)
    - CLI entry point (TASK-VA-019)
    - CORS configuration
    - Authentication
    - Database creation (TASK-VA-003 handles schema; orchestrator handles init)
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/server.py">
      import time
      from fastapi import FastAPI, WebSocket, WebSocketDisconnect
      from voiceagent import __version__

      def create_app() -> FastAPI:
          """Factory that returns a configured FastAPI instance.

          Endpoints:
            GET  /health              -> {"status": "ok", "version": "0.1.0", "uptime_s": float}
            GET  /conversations/{id}  -> conversation JSON from SQLite
            WS   /ws                  -> bidirectional audio + JSON control
          """
          ...
    </signature>
  </signatures>

  <constraints>
    - create_app() returns a FastAPI instance (factory pattern)
    - /health returns JSON {"status": "ok", "version": __version__, "uptime_s": float}
    - uptime_s is computed as time.monotonic() - app.state.start_time
    - /conversations/{id} queries the SQLite database via app.state.db_conn (set by orchestrator)
    - /ws WebSocket endpoint accepts connections and dispatches to callbacks
    - App stores references for on_audio and on_control callbacks on app.state (set by orchestrator)
    - Version imported from voiceagent.__init__ (__version__ = "0.1.0")
    - No global state -- app state stored on app.state
    - Server does NOT manage VoiceAgent lifecycle -- it is a thin HTTP/WS layer
  </constraints>

  <verification>
    - GET /health returns 200 with {"status": "ok", "version": "0.1.0", "uptime_s": <positive float>}
    - GET /conversations/{id} returns 200 with conversation data (or 404 if not found)
    - WebSocket /ws accepts connection (101 Switching Protocols)
    - create_app() returns FastAPI instance
    - pytest tests/voiceagent/test_server.py passes with 0 failures
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/server.py:
  """FastAPI server for the voice agent."""
  import json
  import logging
  import time
  import numpy as np
  from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
  from voiceagent import __version__

  logger = logging.getLogger(__name__)

  def create_app() -> FastAPI:
      app = FastAPI(title="VoiceAgent", version=__version__)

      # Track startup time for uptime calculation
      app.state.start_time = time.monotonic()

      # Callbacks to be set by orchestrator (TASK-VA-018)
      app.state.on_audio = None
      app.state.on_control = None
      app.state.active_ws = None
      app.state.db_conn = None  # Set by orchestrator after DB init

      @app.get("/health")
      async def health():
          uptime_s = round(time.monotonic() - app.state.start_time, 3)
          return {"status": "ok", "version": __version__, "uptime_s": uptime_s}

      @app.get("/conversations/{conversation_id}")
      async def get_conversation(conversation_id: str):
          if app.state.db_conn is None:
              raise HTTPException(status_code=503, detail="Database not initialized")
          cursor = app.state.db_conn.execute(
              "SELECT id, started_at, ended_at, voice_profile, turn_count FROM conversations WHERE id = ?",
              (conversation_id,)
          )
          row = cursor.fetchone()
          if row is None:
              raise HTTPException(status_code=404, detail="Conversation not found")
          return {
              "id": row[0], "started_at": row[1], "ended_at": row[2],
              "voice_profile": row[3], "turn_count": row[4]
          }

      @app.websocket("/ws")
      async def websocket_endpoint(ws: WebSocket):
          await ws.accept()
          app.state.active_ws = ws
          logger.info("WebSocket client connected")
          try:
              while True:
                  message = await ws.receive()
                  if "bytes" in message and message["bytes"]:
                      audio = np.frombuffer(message["bytes"], dtype=np.int16)
                      if app.state.on_audio:
                          await app.state.on_audio(audio)
                  elif "text" in message and message["text"]:
                      data = json.loads(message["text"])
                      if app.state.on_control:
                          await app.state.on_control(data)
          except WebSocketDisconnect:
              logger.info("WebSocket client disconnected")
          finally:
              app.state.active_ws = None

      return app

tests/voiceagent/test_server.py:
  """Tests for the FastAPI server. Uses httpx + TestClient (REST) and websockets (WS)."""
  import pytest
  from fastapi.testclient import TestClient
  import numpy as np
  from voiceagent.server import create_app

  def test_health_endpoint():
      """GET /health returns 200 with status 'ok', version '0.1.0', and uptime_s > 0."""
      app = create_app()
      client = TestClient(app)
      resp = client.get("/health")
      assert resp.status_code == 200
      body = resp.json()
      assert body["status"] == "ok"
      assert body["version"] == "0.1.0"
      assert isinstance(body["uptime_s"], float)
      assert body["uptime_s"] >= 0.0

  def test_health_response_structure():
      """GET /health returns exactly 3 keys: status, version, uptime_s."""
      app = create_app()
      client = TestClient(app)
      resp = client.get("/health")
      body = resp.json()
      assert set(body.keys()) == {"status", "version", "uptime_s"}

  def test_websocket_connect():
      """WebSocket /ws accepts connection (101 upgrade)."""
      app = create_app()
      client = TestClient(app)
      with client.websocket_connect("/ws") as ws:
          pass  # Connection established and closed cleanly

  def test_websocket_receives_audio():
      """Binary messages on /ws are dispatched to app.state.on_audio callback."""
      app = create_app()
      received = []
      async def on_audio(audio):
          received.append(audio)
      app.state.on_audio = on_audio
      client = TestClient(app)
      with client.websocket_connect("/ws") as ws:
          ws.send_bytes(np.zeros(160, dtype=np.int16).tobytes())
      assert len(received) == 1
      assert received[0].shape == (160,)

  def test_websocket_receives_control():
      """Text JSON messages on /ws are dispatched to app.state.on_control callback."""
      app = create_app()
      received = []
      async def on_control(data):
          received.append(data)
      app.state.on_control = on_control
      client = TestClient(app)
      with client.websocket_connect("/ws") as ws:
          ws.send_json({"action": "start_listening"})
      assert len(received) == 1
      assert received[0]["action"] == "start_listening"

  def test_conversation_not_found():
      """GET /conversations/{id} returns 404 when DB has no matching row."""
      import sqlite3
      app = create_app()
      conn = sqlite3.connect(":memory:")
      conn.execute("CREATE TABLE conversations (id TEXT, started_at TEXT, ended_at TEXT, voice_profile TEXT, turn_count INTEGER)")
      app.state.db_conn = conn
      client = TestClient(app)
      resp = client.get("/conversations/nonexistent-id")
      assert resp.status_code == 404

  def test_conversation_found():
      """GET /conversations/{id} returns 200 with conversation data when row exists."""
      import sqlite3
      app = create_app()
      conn = sqlite3.connect(":memory:")
      conn.execute("CREATE TABLE conversations (id TEXT, started_at TEXT, ended_at TEXT, voice_profile TEXT, turn_count INTEGER)")
      conn.execute("INSERT INTO conversations VALUES ('abc-123', '2026-03-28T10:00:00', NULL, 'boris', 0)")
      conn.commit()
      app.state.db_conn = conn
      client = TestClient(app)
      resp = client.get("/conversations/abc-123")
      assert resp.status_code == 200
      body = resp.json()
      assert body["id"] == "abc-123"
      assert body["voice_profile"] == "boris"

  def test_conversation_db_not_initialized():
      """GET /conversations/{id} returns 503 when db_conn is None."""
      app = create_app()
      app.state.db_conn = None
      client = TestClient(app)
      resp = client.get("/conversations/any-id")
      assert resp.status_code == 503
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/server.py">FastAPI app with health, conversations, and WebSocket endpoints</file>
  <file path="tests/voiceagent/test_server.py">Tests using httpx/TestClient for REST and websockets for WS</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>GET /health returns 200 with {"status": "ok", "version": "0.1.0", "uptime_s": positive_float}</criterion>
  <criterion>GET /conversations/{id} returns 200 with conversation data or 404 if not found</criterion>
  <criterion>GET /conversations/{id} returns 503 if db_conn is None</criterion>
  <criterion>WebSocket /ws accepts connection (101 Switching Protocols)</criterion>
  <criterion>Binary messages dispatched to on_audio callback as np.int16 array</criterion>
  <criterion>Text JSON messages dispatched to on_control callback as dict</criterion>
  <criterion>create_app() returns FastAPI instance</criterion>
  <criterion>All tests pass with 0 failures</criterion>
</validation_criteria>

<full_state_verification>
  <source_of_truth>HTTP response codes and response bodies from the FastAPI server</source_of_truth>
  <execute_and_inspect>
    1. Run the FastAPI app via TestClient
    2. Issue GET /health and inspect the JSON body: must contain exactly {status, version, uptime_s}
    3. Issue GET /conversations/{id} and inspect the response code (200 or 404)
    4. Open WebSocket /ws and verify connection is accepted (no exception on connect)
    5. SEPARATELY read the response body and assert field values match expected
  </execute_and_inspect>
  <edge_case_audit>
    <case name="uptime_s_increases_over_time">
      <before>App just created, uptime_s ~0.0</before>
      <after>After 100ms sleep, uptime_s > 0.05</after>
    </case>
    <case name="conversation_not_found">
      <before>Empty conversations table in SQLite</before>
      <after>GET /conversations/missing-id returns 404 with detail "Conversation not found"</after>
    </case>
    <case name="db_not_initialized">
      <before>app.state.db_conn is None (orchestrator has not set it yet)</before>
      <after>GET /conversations/any-id returns 503 with detail "Database not initialized"</after>
    </case>
    <case name="websocket_disconnect_cleanup">
      <before>app.state.active_ws points to connected WebSocket</before>
      <after>After client disconnects, app.state.active_ws is None</after>
    </case>
  </edge_case_audit>
  <evidence_of_success>
    cd /home/cabdru/clipcannon
    PYTHONPATH=src python -m pytest tests/voiceagent/test_server.py -v 2>&amp;1 | grep -E "PASSED|FAILED|ERROR"
    # Expected: all lines show PASSED, 0 FAILED, 0 ERROR
    PYTHONPATH=src python -c "
from voiceagent.server import create_app
app = create_app()
print('App title:', app.title)
print('App version:', app.version)
print('Routes:', [r.path for r in app.routes])
"
    # Expected output:
    # App title: VoiceAgent
    # App version: 0.1.0
    # Routes: ['/health', '/conversations/{conversation_id}', '/ws']
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  <test name="health_check">
    <input>GET /health</input>
    <expected_output>{"status": "ok", "version": "0.1.0", "uptime_s": 0.001}</expected_output>
    <note>uptime_s will vary but must be a positive float</note>
  </test>
  <test name="conversation_found">
    <input>GET /conversations/abc-123 (with row in DB)</input>
    <expected_output>{"id": "abc-123", "started_at": "2026-03-28T10:00:00", "ended_at": null, "voice_profile": "boris", "turn_count": 0}</expected_output>
  </test>
  <test name="conversation_missing">
    <input>GET /conversations/nonexistent</input>
    <expected_output>HTTP 404 {"detail": "Conversation not found"}</expected_output>
  </test>
  <test name="websocket_connect">
    <input>WebSocket UPGRADE to /ws</input>
    <expected_output>101 Switching Protocols, connection accepted</expected_output>
  </test>
</synthetic_test_data>

<manual_verification>
  1. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_server.py -v
     Verify: all tests PASSED, exit code 0
  2. Run: PYTHONPATH=src python -c "from voiceagent.server import create_app; app = create_app(); print(type(app))"
     Verify: output is &lt;class 'fastapi.applications.FastAPI'&gt;
  3. Run: PYTHONPATH=src python -c "
from fastapi.testclient import TestClient
from voiceagent.server import create_app
app = create_app()
client = TestClient(app)
r = client.get('/health')
print('Status:', r.status_code)
print('Body:', r.json())
assert r.json()['status'] == 'ok'
assert r.json()['version'] == '0.1.0'
assert r.json()['uptime_s'] >= 0
print('HEALTH CHECK PASSED')
"
     Verify: output ends with "HEALTH CHECK PASSED"
  4. Run: PYTHONPATH=src python -c "
from fastapi.testclient import TestClient
from voiceagent.server import create_app
app = create_app()
client = TestClient(app)
with client.websocket_connect('/ws') as ws:
    print('WebSocket connected successfully')
print('WebSocket disconnected cleanly')
"
     Verify: both print statements appear, no exception
</manual_verification>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_server.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.server import create_app; app = create_app(); print(app.title, app.version)"</command>
</test_commands>
</task_spec>
```
