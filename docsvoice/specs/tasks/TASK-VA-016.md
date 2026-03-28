```xml
<task_spec id="TASK-VA-016" version="2.0">
<metadata>
  <title>WebSocket Transport -- Bidirectional Audio and JSON Control Messages</title>
  <status>ready</status>
  <layer>surface</layer>
  <sequence>16</sequence>
  <implements>
    <item ref="PHASE1-WS-TRANSPORT">WebSocketTransport for bidirectional audio streaming</item>
    <item ref="PHASE1-VERIFY-5">WebSocket connects (verification #5)</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-001</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>2 files</estimated_files>
</metadata>

<context>
Implements the WebSocket transport layer for bidirectional audio streaming between the
voice agent and clients. Binary messages carry PCM audio (16kHz inbound from client,
24kHz outbound from server) and text messages carry JSON control events (state changes,
errors, metadata). The transport receives audio from the client and dispatches it to
callbacks. It sends audio and events back to the client. The VoiceAgent orchestrator
(TASK-VA-018) wires this to the ConversationManager.

This is 100% greenfield -- src/voiceagent/ does not exist yet. The implementing agent
must create all directories and files from scratch. Python 3.12+.

IMPORTANT: Uses the "websockets" library (NOT websocket-client). Install with:
pip install websockets
</context>

<input_context_files>
  <file purpose="ws_spec">docsvoice/01_phase1_core_pipeline.md#section-6</file>
  <file purpose="errors">src/voiceagent/errors.py (create if not exists)</file>
  <file purpose="package_structure">src/voiceagent/transport/__init__.py (create if not exists)</file>
</input_context_files>

<prerequisites>
  <check>Python 3.12+ available: python3 --version</check>
  <check>numpy installed: python3 -c "import numpy; print(numpy.__version__)"</check>
  <check>websockets installed: python3 -c "import websockets; print(websockets.__version__)"</check>
  <check>If websockets missing: pip install websockets</check>
  <check>If dirs missing, create: mkdir -p src/voiceagent/transport &amp;&amp; touch src/voiceagent/__init__.py src/voiceagent/transport/__init__.py</check>
</prerequisites>

<scope>
  <in_scope>
    - WebSocketTransport class in src/voiceagent/transport/websocket.py
    - __init__(host="0.0.0.0", port=8765) configures server
    - async start(on_audio, on_control) starts WebSocket server
    - async send_audio(audio: np.ndarray) sends 24kHz 16-bit mono PCM to client
    - async send_event(event: dict) sends JSON text to client
    - Binary messages from client: 16kHz 16-bit mono PCM, decoded as np.int16
    - Text messages from client: JSON control messages ({"type": "start"}, etc.)
    - Integration tests with real websockets client (NO MOCKS)
  </in_scope>
  <out_of_scope>
    - FastAPI integration (TASK-VA-017)
    - Authentication/authorization
    - Multiple simultaneous clients (Phase 5+)
    - Audio format negotiation
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/transport/websocket.py">
      from typing import Callable, Awaitable
      import numpy as np

      class WebSocketTransport:
          def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None: ...
          async def start(
              self,
              on_audio: Callable[[np.ndarray], Awaitable[None]],
              on_control: Callable[[dict], Awaitable[None]],
          ) -> None: ...
          async def send_audio(self, audio: np.ndarray) -> None: ...
          async def send_event(self, event: dict) -> None: ...
          async def stop(self) -> None: ...
    </signature>
  </signatures>

  <constraints>
    - Binary WebSocket messages = PCM audio (numpy int16 &lt;-&gt; bytes)
    - Text WebSocket messages = JSON control messages
    - Inbound audio: 16kHz 16-bit mono PCM -- np.frombuffer(message, dtype=np.int16)
    - Outbound audio: 24kHz 16-bit mono PCM -- audio.astype(np.int16).tobytes()
    - on_audio callback receives numpy array of shape (N,) dtype int16
    - on_control callback receives parsed JSON dict
    - Tracks current WebSocket connection for send operations
    - send_audio and send_event are no-ops when no client connected (no crash)
    - Graceful handling of client disconnection (no crash, log info)
    - Graceful handling of malformed JSON (log error, do not crash)
    - Graceful handling of unexpected binary message size (still process, log warning)
    - TransportError raised on server start failure (port in use, etc.)
    - All errors logged with what/why/how-to-fix pattern
  </constraints>

  <verification>
    - WebSocket server starts on configured port
    - Client can connect (101 Switching Protocols)
    - Client sends binary audio -> on_audio callback receives np.ndarray
    - Client sends JSON text -> on_control callback receives dict
    - Server sends audio -> client receives binary bytes
    - Server sends event -> client receives JSON text
    - Client disconnect handled without crash
    - send_audio with no client is no-op
    - send_event with no client is no-op
    - Malformed JSON logged, not crashed
    - pytest tests/voiceagent/test_websocket.py passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/transport/websocket.py:
  """WebSocket transport for bidirectional audio and control messages.

  Binary messages: PCM audio (16kHz int16 inbound, 24kHz int16 outbound).
  Text messages: JSON control events.

  Uses the `websockets` library (NOT websocket-client).
  Install: pip install websockets
  """
  import asyncio
  import json
  import logging
  import numpy as np

  logger = logging.getLogger(__name__)

  class TransportError(Exception):
      """WebSocket transport error."""
      pass

  class WebSocketTransport:
      """WebSocket server for bidirectional audio and control messages.

      Args:
          host: Bind address (default "0.0.0.0").
          port: Bind port (default 8765).
      """

      def __init__(self, host: str = "0.0.0.0", port: int = 8765):
          try:
              import websockets  # noqa: F401
          except ImportError:
              raise ImportError(
                  "websockets is required for WebSocket transport. "
                  "Install with: pip install websockets  "
                  "(NOT websocket-client)"
              )
          self.host = host
          self.port = port
          self._ws = None  # Current active WebSocket connection
          self._server = None  # websockets server instance

      async def start(self, on_audio, on_control):
          """Start WebSocket server and listen for connections.

          Args:
              on_audio: Async callback receiving np.ndarray (int16) for each binary message.
              on_control: Async callback receiving dict for each JSON text message.

          Raises:
              TransportError: If server fails to start (e.g., port in use).
          """
          import websockets

          try:
              self._server = await websockets.serve(
                  lambda ws: self._handle(ws, on_audio, on_control),
                  self.host,
                  self.port,
              )
              logger.info("WebSocket server listening on ws://%s:%d", self.host, self.port)
              await asyncio.Future()  # Run forever until cancelled
          except OSError as e:
              raise TransportError(
                  f"Failed to start WebSocket server on {self.host}:{self.port}. "
                  f"What: socket bind failed. "
                  f"Why: {e}. "
                  f"Fix: check if port {self.port} is already in use "
                  f"(lsof -i :{self.port}), or choose a different port."
              ) from e

      async def _handle(self, ws, on_audio, on_control):
          """Handle a single WebSocket connection."""
          self._ws = ws
          remote = ws.remote_address
          logger.info("Client connected: %s", remote)
          try:
              async for message in ws:
                  if isinstance(message, bytes):
                      # Binary message = PCM audio (16kHz int16)
                      if len(message) == 0:
                          logger.warning(
                              "Received empty binary message from %s. Ignoring.", remote
                          )
                          continue
                      if len(message) % 2 != 0:
                          logger.warning(
                              "Received binary message with odd byte count (%d) from %s. "
                              "Why: int16 samples require even byte count. "
                              "Fix: ensure client sends 16-bit PCM audio. "
                              "Processing anyway (truncating last byte).",
                              len(message), remote,
                          )
                          message = message[:len(message) - 1]
                      audio = np.frombuffer(message, dtype=np.int16)
                      await on_audio(audio)
                  else:
                      # Text message = JSON control
                      try:
                          data = json.loads(message)
                          await on_control(data)
                      except json.JSONDecodeError as e:
                          logger.error(
                              "Malformed JSON from %s: %s. "
                              "What: JSON parse failed. "
                              "Why: %s. "
                              "Fix: send valid JSON, e.g. {\"type\": \"start\"}",
                              remote, message[:100], e,
                          )
          except Exception as e:
              # websockets.exceptions.ConnectionClosed or other
              logger.info("Client disconnected: %s (%s)", remote, type(e).__name__)
          finally:
              if self._ws is ws:
                  self._ws = None

      async def send_audio(self, audio: np.ndarray) -> None:
          """Send PCM audio to connected client (24kHz int16).

          No-op if no client is connected.
          """
          if self._ws is None:
              return
          try:
              await self._ws.send(audio.astype(np.int16).tobytes())
          except Exception as e:
              logger.warning(
                  "Failed to send audio to client: %s. "
                  "Why: %s. "
                  "Fix: client may have disconnected.",
                  type(e).__name__, e,
              )

      async def send_event(self, event: dict) -> None:
          """Send JSON event to connected client.

          No-op if no client is connected.
          """
          if self._ws is None:
              return
          try:
              await self._ws.send(json.dumps(event))
          except Exception as e:
              logger.warning(
                  "Failed to send event to client: %s. "
                  "Why: %s. "
                  "Fix: client may have disconnected.",
                  type(e).__name__, e,
              )

      async def stop(self) -> None:
          """Stop the WebSocket server."""
          if self._server is not None:
              self._server.close()
              await self._server.wait_closed()
              self._server = None
              logger.info("WebSocket server stopped")

tests/voiceagent/test_websocket.py:
  """Tests for WebSocket transport -- uses REAL websockets connections, NO MOCKS."""
  import asyncio
  import json
  import numpy as np
  import pytest
  import websockets

  from voiceagent.transport.websocket import WebSocketTransport, TransportError

  @pytest.fixture
  async def transport_and_port():
      """Start a WebSocketTransport on a random available port."""
      # Use port 0 to get a random available port
      transport = WebSocketTransport(host="127.0.0.1", port=0)
      audio_received = []
      control_received = []

      async def on_audio(audio):
          audio_received.append(audio)

      async def on_control(data):
          control_received.append(data)

      # Start server -- we need to find the actual port
      # Start with a known port range for testing
      import socket
      sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      sock.bind(('127.0.0.1', 0))
      port = sock.getsockname()[1]
      sock.close()

      transport = WebSocketTransport(host="127.0.0.1", port=port)
      server_task = asyncio.create_task(transport.start(on_audio, on_control))

      # Give server time to start
      await asyncio.sleep(0.1)

      yield transport, port, audio_received, control_received, server_task

      # Cleanup
      await transport.stop()
      server_task.cancel()
      try:
          await server_task
      except (asyncio.CancelledError, Exception):
          pass

  @pytest.mark.asyncio
  async def test_transport_instantiates():
      transport = WebSocketTransport(host="127.0.0.1", port=9999)
      assert transport.host == "127.0.0.1"
      assert transport.port == 9999
      assert transport._ws is None

  @pytest.mark.asyncio
  async def test_send_audio_no_connection():
      """send_audio with no client should be a no-op, not crash."""
      transport = WebSocketTransport()
      await transport.send_audio(np.zeros(100, dtype=np.int16))  # no-op

  @pytest.mark.asyncio
  async def test_send_event_no_connection():
      """send_event with no client should be a no-op, not crash."""
      transport = WebSocketTransport()
      await transport.send_event({"type": "state", "state": "idle"})  # no-op

  @pytest.mark.asyncio
  async def test_client_sends_binary_audio(transport_and_port):
      """Client sends binary PCM audio, server receives numpy array via on_audio."""
      transport, port, audio_received, _, _ = transport_and_port
      uri = f"ws://127.0.0.1:{port}"

      async with websockets.connect(uri) as ws:
          # Send 3200 bytes = 1600 samples of int16 = 100ms at 16kHz
          silence = np.zeros(1600, dtype=np.int16)
          await ws.send(silence.tobytes())
          await asyncio.sleep(0.1)

      assert len(audio_received) == 1
      assert audio_received[0].dtype == np.int16
      assert audio_received[0].shape == (1600,)
      assert np.all(audio_received[0] == 0)

  @pytest.mark.asyncio
  async def test_client_sends_json_control(transport_and_port):
      """Client sends JSON text, server receives dict via on_control."""
      transport, port, _, control_received, _ = transport_and_port
      uri = f"ws://127.0.0.1:{port}"

      async with websockets.connect(uri) as ws:
          await ws.send(json.dumps({"type": "start"}))
          await asyncio.sleep(0.1)

      assert len(control_received) == 1
      assert control_received[0] == {"type": "start"}

  @pytest.mark.asyncio
  async def test_server_sends_audio_to_client(transport_and_port):
      """Server sends audio, client receives binary bytes."""
      transport, port, _, _, _ = transport_and_port
      uri = f"ws://127.0.0.1:{port}"

      async with websockets.connect(uri) as ws:
          await asyncio.sleep(0.05)  # Let _handle set self._ws

          audio_out = np.ones(800, dtype=np.int16) * 42
          await transport.send_audio(audio_out)

          response = await asyncio.wait_for(ws.recv(), timeout=2.0)
          assert isinstance(response, bytes)
          received = np.frombuffer(response, dtype=np.int16)
          assert received.shape == (800,)
          assert np.all(received == 42)

  @pytest.mark.asyncio
  async def test_server_sends_event_to_client(transport_and_port):
      """Server sends JSON event, client receives text."""
      transport, port, _, _, _ = transport_and_port
      uri = f"ws://127.0.0.1:{port}"

      async with websockets.connect(uri) as ws:
          await asyncio.sleep(0.05)

          await transport.send_event({"type": "state", "state": "listening"})

          response = await asyncio.wait_for(ws.recv(), timeout=2.0)
          data = json.loads(response)
          assert data == {"type": "state", "state": "listening"}

  @pytest.mark.asyncio
  async def test_client_disconnect_no_crash(transport_and_port):
      """Client disconnecting should not crash the server."""
      transport, port, _, _, _ = transport_and_port
      uri = f"ws://127.0.0.1:{port}"

      async with websockets.connect(uri) as ws:
          await ws.send(b"\x00\x00")  # 1 sample of silence
          await asyncio.sleep(0.05)

      # Client disconnected. Server should still work.
      await asyncio.sleep(0.1)
      assert transport._ws is None  # Connection cleaned up

      # send_audio after disconnect should be no-op
      await transport.send_audio(np.zeros(100, dtype=np.int16))

  @pytest.mark.asyncio
  async def test_malformed_json_no_crash(transport_and_port):
      """Malformed JSON should be logged, not crash the server."""
      transport, port, _, control_received, _ = transport_and_port
      uri = f"ws://127.0.0.1:{port}"

      async with websockets.connect(uri) as ws:
          await ws.send("this is not json {{{")
          await asyncio.sleep(0.1)
          # Send valid JSON after to prove server still works
          await ws.send(json.dumps({"type": "ping"}))
          await asyncio.sleep(0.1)

      assert len(control_received) == 1  # Only the valid one
      assert control_received[0] == {"type": "ping"}

  @pytest.mark.asyncio
  async def test_synthetic_3200_bytes():
      """Synthetic test: send 3200 bytes of zeros (200ms silence at 16kHz),
      verify callback receives numpy array of shape (1600,) dtype int16."""
      transport = WebSocketTransport(host="127.0.0.1", port=0)
      audio_received = []

      import socket
      sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      sock.bind(('127.0.0.1', 0))
      port = sock.getsockname()[1]
      sock.close()

      transport = WebSocketTransport(host="127.0.0.1", port=port)

      async def on_audio(audio):
          audio_received.append(audio)

      async def on_control(data):
          pass

      server_task = asyncio.create_task(transport.start(on_audio, on_control))
      await asyncio.sleep(0.1)

      try:
          uri = f"ws://127.0.0.1:{port}"
          async with websockets.connect(uri) as ws:
              # 3200 bytes = 1600 int16 samples = 100ms at 16kHz
              raw_bytes = b"\x00" * 3200
              await ws.send(raw_bytes)
              await asyncio.sleep(0.1)

          assert len(audio_received) == 1
          assert audio_received[0].dtype == np.int16
          assert audio_received[0].shape == (1600,)
          assert np.all(audio_received[0] == 0)
      finally:
          await transport.stop()
          server_task.cancel()
          try:
              await server_task
          except (asyncio.CancelledError, Exception):
              pass
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/transport/websocket.py">WebSocketTransport class</file>
  <file path="tests/voiceagent/test_websocket.py">Integration tests with real websockets client</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<full_state_verification>
  <source_of_truth>
    1. WebSocket connection status: HTTP 101 Switching Protocols on connect.
    2. transport._ws: None means no client, non-None means client connected.
    3. Callback invocation: on_audio receives np.ndarray, on_control receives dict.
    4. Client-received messages: binary bytes for audio, text for JSON.
  </source_of_truth>

  <execute_and_inspect>
    Step 1: Start WebSocketTransport on a known port.
    Step 2: Connect with websockets.connect().
    Step 3: Send binary data, verify on_audio callback received np.ndarray.
    Step 4: Send JSON text, verify on_control callback received dict.
    Step 5: Call send_audio from server, verify client receives bytes.
    Step 6: Call send_event from server, verify client receives JSON.
    Step 7: Disconnect client, verify transport._ws becomes None.
    Step 8: Call send_audio/send_event with no client, verify no crash.
  </execute_and_inspect>

  <edge_case_audit>
    <case name="client_disconnects_mid_send">
      <before>transport._ws is connected</before>
      <action>Client closes connection, then server calls send_audio()</action>
      <after>Warning logged "Failed to send audio", no crash, _ws set to None</after>
    </case>
    <case name="malformed_json">
      <before>Server listening, client connected</before>
      <action>Client sends text "not json {{"</action>
      <after>Error logged "Malformed JSON", connection stays open, on_control NOT called</after>
    </case>
    <case name="odd_byte_binary">
      <before>Server listening, client connected</before>
      <action>Client sends 3201 bytes (odd count, not aligned to int16)</action>
      <after>Warning logged about odd byte count, last byte truncated, on_audio called with (1600,) array</after>
    </case>
    <case name="concurrent_connections">
      <before>Client A connected (transport._ws = wsA)</before>
      <action>Client B connects</action>
      <after>transport._ws = wsB (overwrites). When B disconnects, _ws = None. This is expected single-client behavior.</after>
    </case>
    <case name="send_with_no_client">
      <before>transport._ws is None (no client)</before>
      <action>await transport.send_audio(audio)</action>
      <after>Returns immediately (no-op), no error, no log</after>
    </case>
  </edge_case_audit>

  <evidence_of_success>
    cd /home/cabdru/clipcannon

    PYTHONPATH=src python -c "
from voiceagent.transport.websocket import WebSocketTransport
t = WebSocketTransport(host='127.0.0.1', port=8765)
print('Created OK, host:', t.host, 'port:', t.port)
print('Has start:', hasattr(t, 'start'))
print('Has send_audio:', hasattr(t, 'send_audio'))
print('Has send_event:', hasattr(t, 'send_event'))
print('Has stop:', hasattr(t, 'stop'))
"

    PYTHONPATH=src python -c "
import asyncio, numpy as np
from voiceagent.transport.websocket import WebSocketTransport
t = WebSocketTransport()
asyncio.run(t.send_audio(np.zeros(100, dtype=np.int16)))  # no-op
asyncio.run(t.send_event({'type': 'test'}))  # no-op
print('PASS: no-ops work')
"

    PYTHONPATH=src python -m pytest tests/voiceagent/test_websocket.py -v --tb=short
    # All tests must pass
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  <test name="send_3200_bytes_receive_1600_samples">
    <input>Client sends 3200 bytes of zeros over WebSocket binary</input>
    <expected>on_audio receives np.ndarray, shape=(1600,), dtype=int16, all zeros</expected>
  </test>
  <test name="send_json_start">
    <input>Client sends text: {"type": "start"}</input>
    <expected>on_control receives {"type": "start"}</expected>
  </test>
  <test name="server_sends_audio">
    <input>Server calls send_audio(np.ones(800, dtype=np.int16) * 42)</input>
    <expected>Client receives 1600 bytes, np.frombuffer gives (800,) array of 42s</expected>
  </test>
  <test name="server_sends_event">
    <input>Server calls send_event({"type": "state", "state": "listening"})</input>
    <expected>Client receives JSON text: {"type": "state", "state": "listening"}</expected>
  </test>
</synthetic_test_data>

<manual_verification>
  <step>1. cd /home/cabdru/clipcannon</step>
  <step>2. Verify websockets installed: python3 -c "import websockets; print(websockets.__version__)"</step>
  <step>3. Verify file exists: ls -la src/voiceagent/transport/websocket.py</step>
  <step>4. Verify import works: PYTHONPATH=src python -c "from voiceagent.transport.websocket import WebSocketTransport; print('PASS')"</step>
  <step>5. Verify no-op sends: PYTHONPATH=src python -c "
import asyncio, numpy as np
from voiceagent.transport.websocket import WebSocketTransport
t = WebSocketTransport()
asyncio.run(t.send_audio(np.zeros(100, dtype=np.int16)))
asyncio.run(t.send_event({'type': 'test'}))
print('PASS: no-ops')
"</step>
  <step>6. Run tests: PYTHONPATH=src python -m pytest tests/voiceagent/test_websocket.py -v --tb=short</step>
  <step>7. Verify test count: at least 8 tests, all passing</step>
  <step>8. Verify NO mocks: grep -c "mock\|Mock\|MagicMock\|patch" tests/voiceagent/test_websocket.py  # Should be 0</step>
  <step>9. Manual integration test (optional):
    Terminal 1: PYTHONPATH=src python -c "
import asyncio, numpy as np
from voiceagent.transport.websocket import WebSocketTransport
async def main():
    t = WebSocketTransport(port=8765)
    async def on_audio(a): print('Audio:', a.shape, a.dtype)
    async def on_control(d): print('Control:', d)
    await t.start(on_audio, on_control)
asyncio.run(main())
"
    Terminal 2: python3 -c "
import asyncio, websockets, numpy as np
async def main():
    async with websockets.connect('ws://127.0.0.1:8765') as ws:
        await ws.send(np.zeros(1600, dtype=np.int16).tobytes())
        await ws.send('{\"type\": \"start\"}')
        print('Sent audio + control')
asyncio.run(main())
"
    Verify Terminal 1 prints: Audio: (1600,) int16 and Control: {'type': 'start'}
  </step>
</manual_verification>

<validation_criteria>
  <criterion>WebSocket server starts and accepts connections (101 Switching Protocols)</criterion>
  <criterion>Binary messages dispatched to on_audio callback as np.ndarray int16</criterion>
  <criterion>Text messages dispatched to on_control callback as parsed dict</criterion>
  <criterion>send_audio sends PCM bytes to client</criterion>
  <criterion>send_event sends JSON text to client</criterion>
  <criterion>No crash on client disconnect</criterion>
  <criterion>No crash on malformed JSON (error logged)</criterion>
  <criterion>No crash on odd-byte binary message (warning logged)</criterion>
  <criterion>send_audio/send_event are no-ops with no client</criterion>
  <criterion>Missing websockets raises ImportError with install instructions</criterion>
  <criterion>Port-in-use raises TransportError with diagnostic instructions</criterion>
  <criterion>All tests use real websockets connections, NO mocks</criterion>
  <criterion>All tests pass</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -m pytest tests/voiceagent/test_websocket.py -v --tb=short</command>
  <command>cd /home/cabdru/clipcannon &amp;&amp; PYTHONPATH=src python -c "from voiceagent.transport.websocket import WebSocketTransport; print('OK')"</command>
</test_commands>
</task_spec>
```
