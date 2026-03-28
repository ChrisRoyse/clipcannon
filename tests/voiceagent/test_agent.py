"""Tests for VoiceAgent orchestrator -- config/DB only, no GPU loading."""


from voiceagent.agent import AgentLifecycle, VoiceAgent
from voiceagent.config import VoiceAgentConfig


def test_agent_creates_with_defaults():
    agent = VoiceAgent()
    assert agent.config is not None
    assert agent.config.tts.voice_name == "boris"
    assert agent._initialized is False


def test_agent_creates_with_custom_config():
    config = VoiceAgentConfig()
    agent = VoiceAgent(config=config)
    assert agent.config is config


def test_agent_not_initialized_on_create():
    agent = VoiceAgent()
    assert agent._brain is None
    assert agent._asr is None
    assert agent._tts_adapter is None
    assert agent._db_conn is None
    assert agent._initialized is False


def test_start_conversation_creates_db_record(tmp_path):
    from voiceagent.db.connection import get_connection
    from voiceagent.db.schema import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    agent = VoiceAgent()
    agent._db_conn = get_connection(db_path)

    conv_id = agent.start_conversation()
    assert conv_id is not None
    assert len(conv_id) == 36  # UUID format

    row = agent._db_conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    assert row is not None
    assert row["id"] == conv_id
    assert row["voice_profile"] == "boris"
    assert row["turn_count"] == 0
    agent._db_conn.close()


def test_log_turn_creates_db_record(tmp_path):
    from voiceagent.db.connection import get_connection
    from voiceagent.db.schema import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    agent = VoiceAgent()
    agent._db_conn = get_connection(db_path)

    conv_id = agent.start_conversation()
    turn_id = agent.log_turn(conv_id, "user", "Hello agent", asr_ms=120.5, total_ms=250.0)

    turn_row = agent._db_conn.execute(
        "SELECT * FROM turns WHERE id = ?", (turn_id,)
    ).fetchone()
    assert turn_row is not None
    assert turn_row["conversation_id"] == conv_id
    assert turn_row["role"] == "user"
    assert turn_row["text"] == "Hello agent"
    assert turn_row["asr_ms"] == 120.5
    assert turn_row["total_ms"] == 250.0

    conv_row = agent._db_conn.execute(
        "SELECT turn_count FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    assert conv_row["turn_count"] == 1
    agent._db_conn.close()


def test_log_multiple_turns_increments_count(tmp_path):
    from voiceagent.db.connection import get_connection
    from voiceagent.db.schema import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    agent = VoiceAgent()
    agent._db_conn = get_connection(db_path)

    conv_id = agent.start_conversation()
    agent.log_turn(conv_id, "user", "Hello")
    agent.log_turn(conv_id, "assistant", "Hi there!")
    agent.log_turn(conv_id, "user", "How are you?")

    row = agent._db_conn.execute(
        "SELECT turn_count FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    assert row["turn_count"] == 3
    agent._db_conn.close()


def test_shutdown_is_safe_without_init():
    agent = VoiceAgent()
    agent.shutdown()  # Should not raise
    assert agent._initialized is False


def test_shutdown_clears_all_refs():
    agent = VoiceAgent()
    agent.shutdown()
    assert agent._brain is None
    assert agent._asr is None
    assert agent._tts_adapter is None
    assert agent._db_conn is None
    assert agent._conversation is None


def test_agent_starts_dormant():
    agent = VoiceAgent()
    assert agent._lifecycle == AgentLifecycle.DORMANT


def test_lifecycle_enum_values():
    assert len(AgentLifecycle) == 4
    assert set(s.value for s in AgentLifecycle) == {
        "dormant", "loading", "active", "unloading",
    }


def test_shutdown_returns_to_dormant():
    agent = VoiceAgent()
    agent.shutdown()
    assert agent._lifecycle == AgentLifecycle.DORMANT
