```xml
<task_spec id="TASK-VA-003" version="2.0">
<metadata>
  <title>Database Schema -- SQLite Tables and Connection Factory</title>
  <status>ready</status>
  <layer>foundation</layer>
  <sequence>3</sequence>
  <implements>
    <item ref="PHASE1-DB-SCHEMA">conversations, turns, metrics tables</item>
    <item ref="PHASE1-DB-CONN">Connection factory with path configuration</item>
    <item ref="PHASE1-DB-INIT">Schema initialization function (idempotent)</item>
  </implements>
  <depends_on>
    <task_ref>TASK-VA-001</task_ref>
  </depends_on>
  <estimated_complexity>medium</estimated_complexity>
  <estimated_files>3 files (schema.py, connection.py, test_db.py)</estimated_files>
</metadata>

<context>
Creates the SQLite database layer for the voice agent. Three tables store conversation
data and performance metrics: conversations (session tracking), turns (individual
user/assistant utterances with latency metrics), and metrics (arbitrary named metrics
for monitoring). The connection factory manages database path resolution and schema
initialization. The VoiceAgent orchestrator (TASK-VA-018) will use this to log
conversations.

IMPORTANT CONTEXT:
- Working directory: /home/cabdru/clipcannon
- src/voiceagent/ is created by TASK-VA-001 (must be complete first)
- All import/run commands MUST use PYTHONPATH=src:
    cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "..."
- Python 3.12+ required (NOT 3.11)
- DB path: ~/.voiceagent/agent.db (in Docker: /data/agent/agent.db)
- Use sqlite3 module DIRECTLY -- NO SQLAlchemy, NO ORM, NO third-party DB libraries
- src/voiceagent/errors.py already exists with DatabaseError class
- src/voiceagent/db/__init__.py already exists (empty, from TASK-VA-001)
- init_db(path) MUST be idempotent (CREATE TABLE IF NOT EXISTS)
- get_connection(path) MUST return sqlite3.Connection with row_factory = sqlite3.Row
</context>

<input_context_files>
  <file purpose="package_structure">src/voiceagent/__init__.py</file>
  <file purpose="error_types">src/voiceagent/errors.py -- contains DatabaseError</file>
  <file purpose="db_package">src/voiceagent/db/__init__.py -- empty init from TASK-VA-001</file>
</input_context_files>

<prerequisites>
  <check>TASK-VA-001 complete: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "from voiceagent.errors import DatabaseError; print('OK')"</check>
  <check>db subpackage exists: ls /home/cabdru/clipcannon/src/voiceagent/db/__init__.py</check>
  <check>Python 3.12+ available: python3 --version must show 3.12 or higher</check>
</prerequisites>

<scope>
  <in_scope>
    - src/voiceagent/db/schema.py with DDL constants and init_db() function
    - src/voiceagent/db/connection.py with get_connection() factory
    - conversations table: id (TEXT PK, UUID), started_at (TEXT, ISO 8601), ended_at (TEXT, nullable), voice_profile (TEXT, default 'boris'), turn_count (INTEGER, default 0)
    - turns table: id (TEXT PK, UUID), conversation_id (TEXT FK), role (TEXT, CHECK user/assistant), text (TEXT), started_at (TEXT), ended_at (TEXT, nullable), asr_ms (REAL, nullable), llm_ttft_ms (REAL, nullable), tts_ttfb_ms (REAL, nullable), total_ms (REAL, nullable)
    - metrics table: id (TEXT PK, UUID), timestamp (TEXT, ISO 8601), metric_name (TEXT), value (REAL), metadata (TEXT, nullable JSON string)
    - Unit tests verifying table creation, idempotency, CRUD, constraints
  </in_scope>
  <out_of_scope>
    - Higher-level query helpers (handled in TASK-VA-018 orchestrator)
    - Migration system (Phase 1 uses init_db() directly)
    - Memory/knowledge tables (Phase 3+)
    - SQLAlchemy or any ORM
  </out_of_scope>
</scope>

<definition_of_done>
  <signatures>
    <signature file="src/voiceagent/db/schema.py">
      """Voice agent database schema definitions.

      Three tables: conversations, turns, metrics.
      init_db() is idempotent -- safe to call multiple times.
      """
      from pathlib import Path
      from voiceagent.errors import DatabaseError

      CONVERSATIONS_DDL: str   # CREATE TABLE IF NOT EXISTS conversations ...
      TURNS_DDL: str            # CREATE TABLE IF NOT EXISTS turns ...
      METRICS_DDL: str          # CREATE TABLE IF NOT EXISTS metrics ...

      def init_db(db_path: str | Path) -> None:
          """Create all tables if they do not exist. Idempotent.

          Args:
              db_path: Path to SQLite database file. Parent dirs created automatically.

          Raises:
              DatabaseError: If schema creation fails.
          """
          ...
    </signature>
    <signature file="src/voiceagent/db/connection.py">
      """Database connection factory.

      get_connection() returns a sqlite3.Connection with WAL mode, foreign keys enabled,
      and row_factory = sqlite3.Row.
      """
      import sqlite3
      from pathlib import Path
      from voiceagent.errors import DatabaseError

      def get_connection(db_path: str | Path) -> sqlite3.Connection:
          """Get a SQLite connection with WAL mode, FK enforcement, and Row factory.

          Args:
              db_path: Path to SQLite database file. Parent dirs created automatically.

          Returns:
              sqlite3.Connection configured for the voice agent.

          Raises:
              DatabaseError: If connection fails.
          """
          ...
    </signature>
  </signatures>

  <constraints>
    - conversations.id is TEXT PRIMARY KEY (UUID format, caller generates UUID)
    - turns.role has CHECK constraint: IN ('user', 'assistant')
    - turns.conversation_id has FOREIGN KEY reference to conversations(id)
    - metrics.metadata is TEXT (JSON string, nullable)
    - All timestamp fields use ISO 8601 TEXT format (e.g., "2026-03-28T10:30:00Z")
    - get_connection() enables WAL mode: PRAGMA journal_mode=WAL
    - get_connection() enables foreign keys: PRAGMA foreign_keys=ON
    - get_connection() sets row_factory = sqlite3.Row
    - get_connection() creates parent directories if they do not exist
    - init_db() is idempotent: CREATE TABLE IF NOT EXISTS
    - init_db() calls get_connection() internally
    - Use pathlib.Path for file operations
    - Raise DatabaseError from voiceagent.errors on ANY failure -- never silently swallow errors
    - Use sqlite3 module DIRECTLY -- no ORM, no SQLAlchemy
    - Only stdlib dependencies
  </constraints>

  <verification>
    - init_db creates all 3 tables in a fresh database
    - init_db is idempotent (running twice does not error)
    - get_connection returns a connection with WAL mode and foreign keys enabled
    - INSERT/SELECT on all tables works correctly
    - FK constraint enforced: inserting turn with nonexistent conversation_id MUST fail
    - CHECK constraint enforced: inserting turn with role='system' MUST fail
    - cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_db.py -v passes
  </verification>
</definition_of_done>

<pseudo_code>
src/voiceagent/db/connection.py:
  """Database connection factory."""
  import sqlite3
  from pathlib import Path
  from voiceagent.errors import DatabaseError

  def get_connection(db_path: str | Path) -> sqlite3.Connection:
      """Get a SQLite connection with WAL mode, FK enforcement, and Row factory."""
      path = Path(db_path).expanduser()
      path.parent.mkdir(parents=True, exist_ok=True)
      try:
          conn = sqlite3.connect(str(path))
          conn.execute("PRAGMA journal_mode=WAL")
          conn.execute("PRAGMA foreign_keys=ON")
          conn.row_factory = sqlite3.Row
          return conn
      except sqlite3.Error as e:
          raise DatabaseError(f"Failed to connect to {path}: {e}") from e

src/voiceagent/db/schema.py:
  """Voice agent database schema definitions."""
  from pathlib import Path
  from voiceagent.errors import DatabaseError
  from voiceagent.db.connection import get_connection

  CONVERSATIONS_DDL = """
  CREATE TABLE IF NOT EXISTS conversations (
      id TEXT PRIMARY KEY,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      voice_profile TEXT NOT NULL DEFAULT 'boris',
      turn_count INTEGER NOT NULL DEFAULT 0
  );"""

  TURNS_DDL = """
  CREATE TABLE IF NOT EXISTS turns (
      id TEXT PRIMARY KEY,
      conversation_id TEXT NOT NULL REFERENCES conversations(id),
      role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
      text TEXT NOT NULL,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      asr_ms REAL,
      llm_ttft_ms REAL,
      tts_ttfb_ms REAL,
      total_ms REAL
  );"""

  METRICS_DDL = """
  CREATE TABLE IF NOT EXISTS metrics (
      id TEXT PRIMARY KEY,
      timestamp TEXT NOT NULL,
      metric_name TEXT NOT NULL,
      value REAL NOT NULL,
      metadata TEXT
  );"""

  def init_db(db_path: str | Path) -> None:
      """Create all tables if they do not exist. Idempotent."""
      conn = get_connection(db_path)
      try:
          conn.executescript(CONVERSATIONS_DDL + TURNS_DDL + METRICS_DDL)
          conn.commit()
      except Exception as e:
          raise DatabaseError(f"Failed to initialize database at {db_path}: {e}") from e
      finally:
          conn.close()

tests/voiceagent/test_db.py:
  """Tests for voiceagent.db module."""
  import sqlite3
  import uuid
  import pytest
  from voiceagent.db.schema import init_db, CONVERSATIONS_DDL, TURNS_DDL, METRICS_DDL
  from voiceagent.db.connection import get_connection
  from voiceagent.errors import DatabaseError

  def test_init_db_creates_all_three_tables(tmp_path):
      db_path = tmp_path / "test.db"
      init_db(db_path)
      conn = get_connection(db_path)
      tables = [row[0] for row in conn.execute(
          "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
      ).fetchall()]
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
      assert row["llm_ttft_ms"] == 85.3
      assert row["tts_ttfb_ms"] == 45.1
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
</pseudo_code>

<files_to_create>
  <file path="src/voiceagent/db/connection.py">get_connection() factory with WAL, FK, Row factory</file>
  <file path="src/voiceagent/db/schema.py">DDL constants and init_db() function</file>
  <file path="tests/voiceagent/test_db.py">Unit tests for database schema, connection, CRUD, constraints</file>
</files_to_create>

<files_to_modify>
  <!-- None -->
</files_to_modify>

<validation_criteria>
  <criterion>All 3 tables created with correct columns and constraints</criterion>
  <criterion>Foreign key constraint on turns.conversation_id enforced</criterion>
  <criterion>CHECK constraint on turns.role enforced (only 'user' and 'assistant')</criterion>
  <criterion>WAL journal mode enabled</criterion>
  <criterion>Foreign keys PRAGMA enabled</criterion>
  <criterion>row_factory = sqlite3.Row set</criterion>
  <criterion>init_db is idempotent (calling twice does not error)</criterion>
  <criterion>get_connection creates parent directories</criterion>
  <criterion>All tests pass with: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_db.py -v</criterion>
</validation_criteria>

<test_commands>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_db.py -v</command>
  <command>cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import tempfile, os
from voiceagent.db.schema import init_db
from voiceagent.db.connection import get_connection
db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
init_db(db_path)
conn = get_connection(db_path)
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()]
print(f'Tables: {tables}')
assert 'conversations' in tables
assert 'turns' in tables
assert 'metrics' in tables
print('DB init OK')
conn.close()
"</command>
</test_commands>

<full_state_verification>
  <source_of_truth>
    The SQLite database file created by init_db(). The schema of that database
    (visible via `sqlite3 <path> ".schema"`) is the source of truth.
    Files on disk:
      /home/cabdru/clipcannon/src/voiceagent/db/connection.py
      /home/cabdru/clipcannon/src/voiceagent/db/schema.py
      /home/cabdru/clipcannon/tests/voiceagent/test_db.py
  </source_of_truth>

  <execute_and_inspect>
    Step 1: Create src/voiceagent/db/connection.py and src/voiceagent/db/schema.py.
    Step 2: Create tests/voiceagent/test_db.py.
    Step 3: Run `ls -la /home/cabdru/clipcannon/src/voiceagent/db/connection.py` to prove it exists.
    Step 4: Run `ls -la /home/cabdru/clipcannon/src/voiceagent/db/schema.py` to prove it exists.
    Step 5: Create a temp DB and run init_db(), then run:
      sqlite3 /tmp/test_verify.db ".schema"
      This must show all 3 CREATE TABLE statements.
    Step 6: Run `cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_db.py -v`
    Step 7: Verify all tests pass.
  </execute_and_inspect>

  <edge_case_audit>
    Edge case 1: init_db called twice on same file
      Command: init_db(path); init_db(path)
      Expected: No error (idempotent via IF NOT EXISTS)
      BEFORE: DB file does not exist
      AFTER: DB file exists with all 3 tables, second call is a no-op

    Edge case 2: Insert turn with nonexistent conversation_id
      Command: INSERT INTO turns ... with conversation_id = 'fake'
      Expected: sqlite3.IntegrityError (FK violation)
      BEFORE: conversations table empty
      AFTER: IntegrityError raised, turn NOT inserted

    Edge case 3: Insert turn with role='system' (invalid)
      Command: INSERT INTO turns ... with role = 'system'
      Expected: sqlite3.IntegrityError (CHECK violation)
      BEFORE: valid conversation exists
      AFTER: IntegrityError raised, turn NOT inserted

    Edge case 4: get_connection with deeply nested nonexistent path
      Command: get_connection("/tmp/a/b/c/d/test.db")
      Expected: All parent dirs created, connection returned
      BEFORE: /tmp/a/ does not exist
      AFTER: /tmp/a/b/c/d/ exists, test.db created
  </edge_case_audit>

  <evidence_of_success>
    Command 1: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import tempfile, os, sqlite3
from voiceagent.db.schema import init_db
db_path = os.path.join(tempfile.mkdtemp(), 'verify.db')
init_db(db_path)
conn = sqlite3.connect(db_path)
schema = conn.execute('SELECT sql FROM sqlite_master WHERE type=\"table\" ORDER BY name').fetchall()
for row in schema:
    print(row[0])
conn.close()
"
    Must print: 3 CREATE TABLE statements for conversations, metrics, turns

    Command 2: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import tempfile, os, uuid
from voiceagent.db.schema import init_db
from voiceagent.db.connection import get_connection
db_path = os.path.join(tempfile.mkdtemp(), 'verify.db')
init_db(db_path)
conn = get_connection(db_path)
conv_id = str(uuid.uuid4())
conn.execute('INSERT INTO conversations (id, started_at) VALUES (?, ?)', (conv_id, '2026-03-28T10:00:00Z'))
conn.commit()
row = conn.execute('SELECT * FROM conversations WHERE id=?', (conv_id,)).fetchone()
print(f'id={row[\"id\"]}, voice_profile={row[\"voice_profile\"]}, turn_count={row[\"turn_count\"]}')
conn.close()
"
    Must print: id=<uuid>, voice_profile=boris, turn_count=0

    Command 3: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_db.py -v
    Must show: all tests PASSED, 0 failures
  </evidence_of_success>
</full_state_verification>

<synthetic_test_data>
  Test conversation record:
    id: "550e8400-e29b-41d4-a716-446655440000"
    started_at: "2026-03-28T10:00:00Z"
    ended_at: null
    voice_profile: "boris" (default)
    turn_count: 0 (default)

  Test turn record:
    id: "550e8400-e29b-41d4-a716-446655440001"
    conversation_id: "550e8400-e29b-41d4-a716-446655440000"
    role: "user"
    text: "Hello agent"
    started_at: "2026-03-28T10:00:01Z"
    ended_at: "2026-03-28T10:00:02Z"
    asr_ms: 120.5
    llm_ttft_ms: 85.3
    tts_ttfb_ms: 45.1
    total_ms: 250.9

  Test metric record:
    id: "550e8400-e29b-41d4-a716-446655440002"
    timestamp: "2026-03-28T10:00:00Z"
    metric_name: "asr_latency_ms"
    value: 120.5
    metadata: '{"model": "whisper"}'

  Expected after inserting all 3 records:
    SELECT count(*) FROM conversations -> 1
    SELECT count(*) FROM turns -> 1
    SELECT count(*) FROM metrics -> 1

  Invalid insert (FK violation):
    INSERT INTO turns with conversation_id = "nonexistent"
    Expected: sqlite3.IntegrityError

  Invalid insert (CHECK violation):
    INSERT INTO turns with role = "system"
    Expected: sqlite3.IntegrityError
</synthetic_test_data>

<manual_verification>
  The implementing agent MUST perform these checks AFTER creating all files:

  1. Run: ls -la /home/cabdru/clipcannon/src/voiceagent/db/connection.py
     Verify: File exists, non-zero size

  2. Run: ls -la /home/cabdru/clipcannon/src/voiceagent/db/schema.py
     Verify: File exists, non-zero size

  3. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
from voiceagent.db.schema import init_db, CONVERSATIONS_DDL, TURNS_DDL, METRICS_DDL
from voiceagent.db.connection import get_connection
print('All imports OK')
"
     Verify: "All imports OK" printed

  4. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import tempfile, os, sqlite3
from voiceagent.db.schema import init_db
db_path = os.path.join(tempfile.mkdtemp(), 'manual_verify.db')
init_db(db_path)
conn = sqlite3.connect(db_path)
tables = sorted([r[0] for r in conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()])
print(f'Tables: {tables}')
conn.close()
"
     Verify: Tables: ['conversations', 'metrics', 'turns']

  5. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import tempfile, os
from voiceagent.db.connection import get_connection
db_path = os.path.join(tempfile.mkdtemp(), 'wal_verify.db')
conn = get_connection(db_path)
mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
fk = conn.execute('PRAGMA foreign_keys').fetchone()[0]
print(f'WAL={mode}, FK={fk}, row_factory={conn.row_factory}')
conn.close()
"
     Verify: WAL=wal, FK=1, row_factory=<class 'sqlite3.Row'>

  6. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -m pytest tests/voiceagent/test_db.py -v
     Verify: All tests PASSED

  7. Run: cd /home/cabdru/clipcannon && PYTHONPATH=src python -c "
import tempfile, os, sqlite3, uuid
from voiceagent.db.schema import init_db
from voiceagent.db.connection import get_connection
db_path = os.path.join(tempfile.mkdtemp(), 'fk_verify.db')
init_db(db_path)
conn = get_connection(db_path)
try:
    conn.execute('INSERT INTO turns (id, conversation_id, role, text, started_at) VALUES (?, ?, ?, ?, ?)',
        (str(uuid.uuid4()), 'fake', 'user', 'test', '2026-03-28T10:00:00Z'))
    print('FAIL: FK constraint not enforced')
except sqlite3.IntegrityError as e:
    print(f'FK constraint OK: {e}')
conn.close()
"
     Verify: "FK constraint OK" printed
</manual_verification>
</task_spec>
```
