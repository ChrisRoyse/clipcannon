"""Tests for WebSocket transport -- real connections, NO MOCKS."""
import asyncio
import json
import socket

import numpy as np
import pytest
import websockets

from voiceagent.transport.websocket import WebSocketTransport


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.asyncio
async def test_instantiates():
    t = WebSocketTransport(host="127.0.0.1", port=9999)
    assert t.host == "127.0.0.1"
    assert t.port == 9999
    assert t._ws is None


@pytest.mark.asyncio
async def test_send_audio_no_connection():
    t = WebSocketTransport()
    await t.send_audio(np.zeros(100, dtype=np.int16))


@pytest.mark.asyncio
async def test_send_event_no_connection():
    t = WebSocketTransport()
    await t.send_event({"type": "test"})


@pytest.fixture
async def server_setup():
    port = _free_port()
    transport = WebSocketTransport(host="127.0.0.1", port=port)
    audio_rx = []
    ctrl_rx = []

    async def on_audio(a):
        audio_rx.append(a)

    async def on_control(d):
        ctrl_rx.append(d)

    task = asyncio.create_task(transport.start(on_audio, on_control))
    await asyncio.sleep(0.15)
    yield transport, port, audio_rx, ctrl_rx, task
    await transport.stop()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


@pytest.mark.asyncio
async def test_client_sends_binary(server_setup):
    transport, port, audio_rx, _, _ = server_setup
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        silence = np.zeros(1600, dtype=np.int16)
        await ws.send(silence.tobytes())
        await asyncio.sleep(0.1)
    assert len(audio_rx) == 1
    assert audio_rx[0].dtype == np.int16
    assert audio_rx[0].shape == (1600,)


@pytest.mark.asyncio
async def test_client_sends_json(server_setup):
    transport, port, _, ctrl_rx, _ = server_setup
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        await ws.send(json.dumps({"type": "start"}))
        await asyncio.sleep(0.1)
    assert len(ctrl_rx) == 1
    assert ctrl_rx[0] == {"type": "start"}


@pytest.mark.asyncio
async def test_server_sends_audio(server_setup):
    transport, port, _, _, _ = server_setup
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        await asyncio.sleep(0.05)
        audio_out = np.ones(800, dtype=np.int16) * 42
        await transport.send_audio(audio_out)
        resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert isinstance(resp, bytes)
        received = np.frombuffer(resp, dtype=np.int16)
        assert np.all(received == 42)


@pytest.mark.asyncio
async def test_server_sends_event(server_setup):
    transport, port, _, _, _ = server_setup
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        await asyncio.sleep(0.05)
        await transport.send_event({"type": "state", "state": "listening"})
        resp = await asyncio.wait_for(ws.recv(), timeout=2.0)
        data = json.loads(resp)
        assert data == {"type": "state", "state": "listening"}


@pytest.mark.asyncio
async def test_client_disconnect_no_crash(server_setup):
    transport, port, _, _, _ = server_setup
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        await ws.send(b"\x00\x00")
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.1)
    assert transport._ws is None
    await transport.send_audio(np.zeros(100, dtype=np.int16))


@pytest.mark.asyncio
async def test_malformed_json_no_crash(server_setup):
    transport, port, _, ctrl_rx, _ = server_setup
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        await ws.send("not json {{{")
        await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "ping"}))
        await asyncio.sleep(0.1)
    assert len(ctrl_rx) == 1
    assert ctrl_rx[0] == {"type": "ping"}
