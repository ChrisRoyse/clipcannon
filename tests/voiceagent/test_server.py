"""Tests for the FastAPI server."""
import sqlite3

import numpy as np
from fastapi.testclient import TestClient

from voiceagent.server import create_app


def test_health_endpoint():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert isinstance(body["uptime_s"], float)
    assert body["uptime_s"] >= 0.0


def test_health_response_keys():
    app = create_app()
    client = TestClient(app)
    body = client.get("/health").json()
    assert set(body.keys()) == {"status", "version", "uptime_s"}


def test_websocket_connect():
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws") as _ws:
        pass


def test_websocket_receives_audio():
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
    app = create_app()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id TEXT, started_at TEXT, ended_at TEXT, voice_profile TEXT, turn_count INTEGER)"
    )
    app.state.db_conn = conn
    client = TestClient(app)
    resp = client.get("/conversations/nonexistent-id")
    assert resp.status_code == 404


def test_conversation_found():
    app = create_app()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id TEXT, started_at TEXT, ended_at TEXT, voice_profile TEXT, turn_count INTEGER)"
    )
    conn.execute(
        "INSERT INTO conversations VALUES ('abc-123', '2026-03-28T10:00:00', NULL, 'boris', 0)"
    )
    conn.commit()
    app.state.db_conn = conn
    client = TestClient(app)
    resp = client.get("/conversations/abc-123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "abc-123"
    assert body["voice_profile"] == "boris"


def test_conversation_db_not_initialized():
    app = create_app()
    app.state.db_conn = None
    client = TestClient(app)
    resp = client.get("/conversations/any-id")
    assert resp.status_code == 503
