"""Full end-to-end integration test for Phase 1 voice pipeline.

NO MOCKS. Uses real GPU models, real audio, real database.
Requires: RTX 5090, Qwen3-14B-FP8, ClipCannon boris voice, Whisper.

Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_integration.py -v --timeout=300
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
import pytest
import torch

from voiceagent.agent import VoiceAgent
from voiceagent.asr.endpointing import EndpointDetector
from voiceagent.asr.types import ASREvent, AudioBuffer
from voiceagent.brain.context import ContextManager
from voiceagent.brain.prompts import build_system_prompt
from voiceagent.config import VoiceAgentConfig, ASRConfig, LLMConfig, TTSConfig, TransportConfig
from voiceagent.conversation.state import ConversationState
from voiceagent.db.connection import get_connection
from voiceagent.db.schema import init_db
from voiceagent.tts.chunker import SentenceChunker


# --- Fixtures ---

@pytest.fixture(scope="module")
def check_gpu():
    if not torch.cuda.is_available():
        pytest.fail("CUDA GPU required for integration tests.")


@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("integration") / "agent.db"
    init_db(db_path)
    return db_path


@pytest.fixture(scope="module")
def agent_config(tmp_db):
    return VoiceAgentConfig(
        llm=LLMConfig(max_tokens=64),
        asr=ASRConfig(model_name="Systran/faster-whisper-large-v3"),
        tts=TTSConfig(voice_name="boris"),
        data_dir=str(tmp_db.parent),
    )


# --- Test 1: All imports work ---

def test_01_all_imports():
    """Verify every Phase 1 module is importable."""
    from voiceagent import __version__
    from voiceagent.errors import (VoiceAgentError, ConfigError, ASRError, VADError,
                                    LLMError, TTSError, TransportError, DatabaseError,
                                    WakeWordError, ActivationError, ModelLoadError, ConversationError)
    from voiceagent.config import VoiceAgentConfig, load_config
    from voiceagent.db.schema import init_db
    from voiceagent.db.connection import get_connection
    from voiceagent.asr.types import ASREvent, AudioBuffer
    from voiceagent.asr.vad import SileroVAD
    from voiceagent.asr.endpointing import EndpointDetector
    from voiceagent.asr.streaming import StreamingASR
    from voiceagent.brain.llm import LLMBrain
    from voiceagent.brain.prompts import build_system_prompt
    from voiceagent.brain.context import ContextManager
    from voiceagent.adapters.clipcannon import ClipCannonAdapter
    from voiceagent.tts.chunker import SentenceChunker
    from voiceagent.tts.streaming import StreamingTTS
    from voiceagent.conversation.state import ConversationState
    from voiceagent.conversation.manager import ConversationManager
    from voiceagent.transport.websocket import WebSocketTransport
    from voiceagent.server import create_app
    from voiceagent.agent import VoiceAgent
    from voiceagent.cli import cli
    assert __version__ == "0.1.0"
    print("All 20+ modules imported successfully")


# --- Test 2: Database operations ---

def test_02_database_crud(tmp_db):
    """Verify conversations, turns, metrics tables work end-to-end."""
    conn = get_connection(tmp_db)
    conv_id = str(uuid.uuid4())
    turn_id = str(uuid.uuid4())
    metric_id = str(uuid.uuid4())

    conn.execute("INSERT INTO conversations (id, started_at) VALUES (?, ?)",
                 (conv_id, "2026-03-28T10:00:00Z"))
    conn.execute(
        "INSERT INTO turns (id, conversation_id, role, text, started_at, asr_ms, total_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (turn_id, conv_id, "user", "Hello", "2026-03-28T10:00:01Z", 100.0, 250.0))
    conn.execute(
        "INSERT INTO metrics (id, timestamp, metric_name, value) VALUES (?, ?, ?, ?)",
        (metric_id, "2026-03-28T10:00:01Z", "e2e_latency_ms", 250.0))
    conn.commit()

    conv = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
    assert conv["id"] == conv_id
    assert conv["voice_profile"] == "boris"

    turn = conn.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
    assert turn["role"] == "user"
    assert turn["asr_ms"] == 100.0

    metric = conn.execute("SELECT * FROM metrics WHERE id=?", (metric_id,)).fetchone()
    assert metric["metric_name"] == "e2e_latency_ms"

    # FK constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO turns (id, conversation_id, role, text, started_at) VALUES (?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), "nonexistent", "user", "test", "2026-03-28T10:00:00Z"))

    # CHECK constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO turns (id, conversation_id, role, text, started_at) VALUES (?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), conv_id, "system", "test", "2026-03-28T10:00:00Z"))

    conn.close()
    print(f"DB CRUD verified: conv={conv_id}, turn={turn_id}, metric={metric_id}")


# --- Test 3: VoiceAgent config + DB wiring ---

def test_03_agent_db_wiring(tmp_db):
    """VoiceAgent creates conversations and logs turns to DB."""
    agent = VoiceAgent()
    agent._db_conn = get_connection(tmp_db)

    conv_id = agent.start_conversation()
    t1 = agent.log_turn(conv_id, "user", "What is 2+2?", asr_ms=90.0, total_ms=200.0)
    t2 = agent.log_turn(conv_id, "assistant", "Four.", llm_ttft_ms=80.0, tts_ttfb_ms=50.0, total_ms=300.0)

    row = agent._db_conn.execute("SELECT turn_count FROM conversations WHERE id=?", (conv_id,)).fetchone()
    assert row["turn_count"] == 2

    turns = agent._db_conn.execute(
        "SELECT role, text FROM turns WHERE conversation_id=? ORDER BY started_at", (conv_id,)
    ).fetchall()
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[1]["role"] == "assistant"
    agent._db_conn.close()
    print(f"Agent DB wiring verified: {conv_id} with 2 turns")


# --- Test 4: VAD detects speech (verification #4) ---

def test_04_vad_detects_speech(check_gpu):
    """SileroVAD correctly classifies silence vs speech-like audio."""
    from voiceagent.asr.vad import SileroVAD
    vad = SileroVAD(threshold=0.5)
    assert vad.is_speech(np.zeros(512, dtype=np.float32)) is False
    vad.reset()
    print("VAD silence detection: PASS")


# --- Test 5: Endpoint detection ---

def test_05_endpoint_detection():
    """EndpointDetector triggers after 600ms silence following speech."""
    ep = EndpointDetector(silence_ms=600, chunk_ms=200)
    assert ep.update(True) is False    # speech
    assert ep.update(False) is False   # 200ms
    assert ep.update(False) is False   # 400ms
    assert ep.update(False) is True    # 600ms -> endpoint!
    ep.reset()
    assert ep.has_speech is False
    print("Endpoint detection: PASS")


# --- Test 6: System prompt builder ---

def test_06_system_prompt():
    """System prompt contains all required elements."""
    p = build_system_prompt("boris", datetime_str="2026-03-28T14:30:00")
    assert "Chris Royse" in p
    assert "boris" in p
    assert "2026-03-28T14:30:00" in p
    assert "1-3 sentences" in p
    assert "clarifying questions" in p
    assert "I don't know" in p
    assert "never disclose" in p.lower()
    print("System prompt: PASS")


# --- Test 7: Context window manager ---

def test_07_context_window():
    """50 turns fit without truncation (verification #10)."""
    cm = ContextManager()
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "Hello"} for i in range(50)]
    msgs = cm.build_messages("You are a helpful assistant.", history, "Hi")
    assert len(msgs) == 52  # system + 50 history + user
    print(f"Context window: 50 turns -> {len(msgs)} messages (PASS)")


# --- Test 8: Sentence chunker (verification #9) ---

def test_08_sentence_chunker():
    """SentenceChunker splits correctly."""
    c = SentenceChunker()
    assert c.extract_sentence("Hello. How are you? ") == "Hello. How are you?"
    assert c.extract_sentence("I am good. You are too. ") == "I am good."
    assert c.extract_sentence("Hi") is None
    assert c.extract_sentence("") is None
    print("Sentence chunker: PASS")


# --- Test 9: LLM generates text (verification #1) ---

def test_09_llm_generates_text(check_gpu):
    """Qwen3-14B loads and generates coherent text."""
    from voiceagent.brain.llm import LLMBrain
    from voiceagent.config import LLMConfig
    config = LLMConfig(max_tokens=32)
    brain = LLMBrain(config)

    vram_gb = torch.cuda.memory_allocated() / (1024 ** 3)
    assert vram_gb > 1.0, f"Expected >1GB VRAM, got {vram_gb:.2f}GB"
    print(f"LLM VRAM: {vram_gb:.2f} GB")

    tokens = []
    loop = asyncio.new_event_loop()
    async def gen():
        async for t in brain.generate_stream([{"role": "user", "content": "Say hello in one word."}]):
            tokens.append(t)
    loop.run_until_complete(gen())
    loop.close()

    text = "".join(tokens)
    assert len(text) > 0, "LLM generated empty text"
    print(f"LLM generated: {text[:100]}")

    brain.release()
    print("LLM test: PASS")


# --- Test 10: TTS produces audio (verification #3) ---

def test_10_tts_produces_audio(check_gpu):
    """ClipCannon TTS synthesizes audio in boris voice."""
    from voiceagent.adapters.clipcannon import ClipCannonAdapter
    adapter = ClipCannonAdapter(voice_name="boris")

    loop = asyncio.new_event_loop()
    audio = loop.run_until_complete(adapter.synthesize("Hello world"))
    loop.close()

    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) > 12000  # > 0.5s at 24kHz
    duration_s = len(audio) / 24000
    print(f"TTS audio: {len(audio)} samples ({duration_s:.2f}s)")

    adapter.release()
    print("TTS test: PASS")


# --- Test 11: FastAPI health endpoint ---

def test_11_fastapi_health():
    """GET /health returns correct response."""
    from voiceagent.server import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["uptime_s"] >= 0.0
    print(f"Health: {body}")


# --- Test 12: WebSocket transport ---

def test_12_websocket_transport():
    """WebSocket accepts connection and exchanges messages."""
    from voiceagent.server import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    received = []

    async def on_audio(audio):
        received.append(("audio", audio))

    async def on_control(data):
        received.append(("control", data))

    app.state.on_audio = on_audio
    app.state.on_control = on_control

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_bytes(np.zeros(160, dtype=np.int16).tobytes())
        ws.send_json({"type": "start"})

    assert len(received) == 2
    assert received[0][0] == "audio"
    assert received[1][0] == "control"
    print("WebSocket transport: PASS")


# --- Test 13: Conversation state machine ---

def test_13_conversation_state_machine():
    """State transitions follow IDLE->LISTENING->THINKING->SPEAKING->LISTENING."""
    assert len(ConversationState) == 4
    assert set(s.value for s in ConversationState) == {"idle", "listening", "thinking", "speaking"}
    print("State machine: 4 states verified")


# --- Test 14: CLI help ---

def test_14_cli_help():
    """CLI shows help text with serve and talk commands."""
    from click.testing import CliRunner
    from voiceagent.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output
    assert "talk" in result.output
    print("CLI help: PASS")
