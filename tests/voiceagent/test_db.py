"""Tests for voiceagent.db module."""
import sqlite3
import uuid

import pytest

from voiceagent.db.connection import get_connection
from voiceagent.db.schema import init_db


def test_init_db_creates_all_three_tables(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    tables = sorted(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    )
    conn.close()
    assert "conversations" in tables
    assert "turns" in tables
    assert "metrics" in tables


def test_init_db_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    init_db(db_path)  # second call must not error


def test_get_connection_enables_wal(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_get_connection_enables_foreign_keys(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.close()
    assert fk == 1


def test_get_connection_row_factory(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    assert conn.row_factory == sqlite3.Row
    conn.close()


def test_get_connection_creates_parent_dirs(tmp_path):
    db_path = tmp_path / "deep" / "nested" / "dir" / "test.db"
    conn = get_connection(db_path)
    conn.close()
    assert db_path.exists()


def test_insert_and_select_conversation(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conv_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO conversations (id, started_at) VALUES (?, ?)",
        (conv_id, "2026-03-28T10:00:00Z"),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    assert row["id"] == conv_id
    assert row["started_at"] == "2026-03-28T10:00:00Z"
    assert row["voice_profile"] == "boris"
    assert row["turn_count"] == 0
    assert row["ended_at"] is None
    conn.close()


def test_insert_and_select_turn(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conv_id = str(uuid.uuid4())
    turn_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO conversations (id, started_at) VALUES (?, ?)",
        (conv_id, "2026-03-28T10:00:00Z"),
    )
    conn.execute(
        "INSERT INTO turns (id, conversation_id, role, text, started_at, asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (turn_id, conv_id, "user", "Hello agent", "2026-03-28T10:00:01Z", 120.5, 85.3, 45.1, 250.9),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    assert row["id"] == turn_id
    assert row["conversation_id"] == conv_id
    assert row["role"] == "user"
    assert row["text"] == "Hello agent"
    assert row["asr_ms"] == 120.5
    assert row["total_ms"] == 250.9
    conn.close()


def test_turn_fk_constraint_rejects_invalid_conversation_id(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO turns (id, conversation_id, role, text, started_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "nonexistent-conv-id", "user", "test", "2026-03-28T10:00:00Z"),
        )
    conn.close()


def test_turn_check_constraint_rejects_invalid_role(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    conv_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO conversations (id, started_at) VALUES (?, ?)",
        (conv_id, "2026-03-28T10:00:00Z"),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO turns (id, conversation_id, role, text, started_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), conv_id, "system", "invalid role", "2026-03-28T10:00:00Z"),
        )
    conn.close()


def test_insert_and_select_metric(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = get_connection(db_path)
    metric_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO metrics (id, timestamp, metric_name, value, metadata) VALUES (?, ?, ?, ?, ?)",
        (metric_id, "2026-03-28T10:00:00Z", "asr_latency_ms", 120.5, '{"model": "whisper"}'),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM metrics WHERE id = ?", (metric_id,)).fetchone()
    assert row["id"] == metric_id
    assert row["metric_name"] == "asr_latency_ms"
    assert row["value"] == 120.5
    assert row["metadata"] == '{"model": "whisper"}'
    conn.close()
