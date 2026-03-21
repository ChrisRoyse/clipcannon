# ClipCannon Testing Guide

> How to write fast, reliable, and meaningful tests for the ClipCannon video understanding pipeline.

This guide documents the testing patterns, fixture strategies, and performance optimizations used across the ClipCannon test suite. Every example is drawn from actual test code in the repository.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Core Principles](#2-core-principles)
3. [Fixture Patterns](#3-fixture-patterns)
4. [Testing Pipeline Stages](#4-testing-pipeline-stages)
5. [Testing MCP Tools](#5-testing-mcp-tools)
6. [Testing Provenance](#6-testing-provenance)
7. [Testing Billing](#7-testing-billing)
8. [Testing Dashboard](#8-testing-dashboard)
9. [Performance Optimization Rules](#9-performance-optimization-rules)
10. [Anti-Patterns](#10-anti-patterns)
11. [Cookbook](#11-cookbook)

---

## 1. Architecture Overview

### Directory Structure

```
tests/
    test_pipeline_stages.py      # FFmpeg-dependent pipeline stages (probe, audio, frames)
    test_derived_stages.py       # Stages using synthetic DB data (profanity, chronemic, highlights)
    test_provenance_integration.py  # Provenance chain recording and verification
    test_billing.py              # HMAC integrity, credit rates, license server API
    test_understanding_tools.py  # MCP tool functions with synthetic data
    test_visual_pipeline.py      # PIL-based synthetic frame generation, storyboard, quality
    integration/
        test_full_pipeline.py    # Full pipeline end-to-end on a real video
    dashboard/
        test_dashboard.py        # Dashboard FastAPI endpoints
```

### pytest Configuration

The test suite is configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
pythonpath = ["src"]
```

**Key settings:**

- **`pythonpath = ["src"]`** -- Allows direct imports like `from clipcannon.pipeline.probe import run_probe` without installing the package in development mode.
- **`asyncio_mode = "auto"`** -- All `async def test_*` methods are automatically treated as async tests. You do not need `@pytest.mark.asyncio` in most cases, though the codebase uses it explicitly in some files for clarity.

### Required Plugins

- **`pytest-asyncio>=0.23.0`** -- Async test support for pipeline stages and MCP tool functions.
- **`pytest>=8.0`** -- Core test framework with `tmp_path`, `tmp_path_factory`, and `monkeypatch` fixtures.

### Key Source Modules Used in Tests

| Module | What It Provides |
|--------|-----------------|
| `clipcannon.db.schema.create_project_db` | Creates a fresh SQLite database with all tables |
| `clipcannon.db.connection.get_connection` | Returns a configured SQLite connection (WAL mode, pragmas, dict rows) |
| `clipcannon.db.queries` | `fetch_one`, `fetch_all`, `execute`, `batch_insert` |
| `clipcannon.config.ClipCannonConfig` | Configuration loader with pydantic validation |
| `clipcannon.pipeline.orchestrator.StageResult` | Pydantic model returned by every pipeline stage |
| `clipcannon.provenance.chain.verify_chain` | Verifies provenance hash chain integrity |
| `clipcannon.provenance.recorder.record_provenance` | Records a provenance entry with chain hashing |

---

## 2. Core Principles

### Verify Sources of Truth, Not Return Values Alone

Every test that writes data should read it back from the database or filesystem and verify the physical state. Do not trust return values as the sole assertion.

From `tests/test_pipeline_stages.py`:

```python
def test_probe_extracts_metadata(self, probed_project):
    project_id, db_path, project_dir, config, result = probed_project

    # Assert on the return value
    assert result.success is True
    assert result.operation == "probe"

    # But ALSO verify the actual database state
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT * FROM project WHERE project_id = ?",
            (project_id,),
        )
    finally:
        conn.close()

    assert row is not None
    assert int(row["duration_ms"]) > 200000
    assert row["resolution"] == "2560x1440"
    assert float(row["fps"]) == 60.0
    assert row["codec"] == "h264"
    assert row["source_sha256"] != "pending"
    assert row["status"] == "probed"
```

### Use Real or Synthetic Data -- Never Mock Core Logic

ClipCannon tests avoid `mock.patch` for pipeline logic, database operations, or provenance chains. Instead they use:

- **Real video files** for FFmpeg-dependent stages (probe, audio extract, frame extract).
- **Synthetic database records** for derived stages (profanity, chronemic, highlights) that only need data in tables.
- **PIL-generated frames** for visual pipeline tests (storyboard, quality assessment).

### Fail Fast with Meaningful Messages

Pipeline tests chain dependencies explicitly. If probe fails, audio extraction should not attempt to run. From `tests/test_pipeline_stages.py`:

```python
@pytest.fixture(scope="module")
def audio_extracted_project(probed_project):
    project_id, db_path, project_dir, config, probe_result = probed_project
    assert probe_result.success, f"Probe must succeed first: {probe_result.error_message}"
    result = asyncio.run(run_audio_extract(project_id, db_path, project_dir, config))
    return project_id, db_path, project_dir, config, result
```

### Always Verify Provenance

Every pipeline stage writes a provenance record. Every test should verify that the record exists and has the expected fields. From `tests/test_pipeline_stages.py`:

```python
def test_probe_writes_provenance(self, probed_project):
    project_id, db_path, project_dir, config, result = probed_project

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT * FROM provenance WHERE project_id = ? AND operation = 'probe'",
            (project_id,),
        )
    finally:
        conn.close()

    assert len(rows) >= 1
    prov = rows[0]
    assert prov["operation"] == "probe"
    assert prov["input_sha256"] is not None
    assert prov["chain_hash"] is not None
```

---

## 3. Fixture Patterns

### Module-Scoped Fixtures for Expensive Operations

FFmpeg operations (probe, audio extraction, frame extraction) take seconds to run. Use `scope="module"` so they execute only once per test file, then share the results across all test methods.

From `tests/test_pipeline_stages.py`:

```python
@pytest.fixture(scope="module")
def shared_project_dir(tmp_path_factory) -> Path:
    """Create a single temp directory shared across the entire module."""
    return tmp_path_factory.mktemp("pipeline_stages")


@pytest.fixture(scope="module")
def shared_config() -> ClipCannonConfig:
    """Load config once for the module."""
    return ClipCannonConfig.load()


@pytest.fixture(scope="module")
def probed_project(shared_project_dir: Path, shared_config: ClipCannonConfig):
    """Run probe once and share the result across all tests that need it."""
    if not TEST_VIDEO.exists():
        pytest.skip(f"Test video not found at {TEST_VIDEO}")

    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = shared_project_dir / project_id
    project_dir.mkdir(parents=True)

    db_path = create_project_db(project_id, base_dir=shared_project_dir)

    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        execute(
            conn,
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, "Test Project", str(TEST_VIDEO),
                "pending", 0, "0x0", 0.0, "unknown", "created",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = asyncio.run(run_probe(project_id, db_path, project_dir, shared_config))
    return project_id, db_path, project_dir, shared_config, result
```

**Important:** Module-scoped fixtures cannot use the `tmp_path` fixture (which is function-scoped). Use `tmp_path_factory.mktemp()` instead.

### Chaining Module-Scoped Fixtures

Later stages depend on earlier stages. Express this as fixture dependencies:

```python
@pytest.fixture(scope="module")
def audio_extracted_project(probed_project):
    """Run audio extraction once (depends on probe), share the result."""
    project_id, db_path, project_dir, config, probe_result = probed_project
    assert probe_result.success, f"Probe must succeed first: {probe_result.error_message}"
    result = asyncio.run(run_audio_extract(project_id, db_path, project_dir, config))
    return project_id, db_path, project_dir, config, result


@pytest.fixture(scope="module")
def frames_extracted_project(probed_project):
    """Run frame extraction once (depends on probe), share the result."""
    project_id, db_path, project_dir, config, probe_result = probed_project
    assert probe_result.success, f"Probe must succeed first: {probe_result.error_message}"
    result = asyncio.run(run_frame_extract(project_id, db_path, project_dir, config))
    return project_id, db_path, project_dir, config, result
```

### Function-Scoped Fixtures for Lightweight Setup

When a test only needs a database with synthetic data and no FFmpeg, use `tmp_path` directly. Each test gets a fresh copy.

From `tests/test_derived_stages.py`:

```python
@pytest.fixture
def mock_project(tmp_path: Path):
    """Set up a project with mock transcript/acoustic data for testing."""
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    db_path = create_project_db(project_id, base_dir=tmp_path)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        execute(conn, """INSERT INTO project (...) VALUES (?, ?, ...)""",
                (project_id, "Test Video", "/tmp/test.mp4", "abc123",
                 180000, "1920x1080", 30.0, "h264", "probed"))

        # Insert synthetic data: speakers, transcript segments, words, etc.
        batch_insert(conn, "transcript_segments",
                     ["project_id", "start_ms", "end_ms", "text", "speaker_id",
                      "language", "word_count"],
                     segments_data)
        # ... more synthetic data ...

        conn.commit()
    finally:
        conn.close()

    config = ClipCannonConfig.load()
    return project_id, db_path, project_dir, config
```

### How to Create a Test Project (Step by Step)

Every test project follows this pattern:

1. **Create the database** with `create_project_db(project_id, base_dir=tmp_path)`.
2. **Create subdirectories**: `source/`, `stems/`, `frames/`, `storyboards/`.
3. **Insert a project row** with required fields (`project_id`, `name`, `source_path`, `source_sha256`, `duration_ms`, `resolution`, `fps`, `codec`, `status`).
4. **Insert any additional data** the stage under test needs (transcript segments, emotion curves, etc.).
5. **Commit the connection** and close it.
6. **Load config** with `ClipCannonConfig.load()`.

### When to Use Each Fixture Scope

| Scope | When to Use | Example |
|-------|------------|---------|
| `function` (default) | Database-only tests, each test needs fresh state | `mock_project`, `project_db` |
| `module` | FFmpeg operations, ML model loading, anything >1 second | `probed_project`, `pipeline_project` |
| `session` | Shared config, test video validation | `shared_config` |

---

## 4. Testing Pipeline Stages

### The StageResult Contract

Every pipeline stage returns a `StageResult`:

```python
class StageResult(BaseModel):
    success: bool
    operation: str
    error_message: str | None = None
    duration_ms: int = 0
    provenance_record_id: str | None = None
```

All stage tests should verify at minimum:

```python
assert result.success is True
assert result.operation == "expected_operation_name"
assert result.provenance_record_id is not None
```

### Testing Required Stages (Probe, Audio, Frames)

Required stages need a real video file. They use module-scoped fixtures to avoid re-running FFmpeg.

```python
TEST_VIDEO = Path("/home/cabdru/clipcannon/testdata/2026-03-20 14-43-20.mp4")

@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestProbeStage:
    def test_probe_extracts_metadata(self, probed_project):
        project_id, db_path, project_dir, config, result = probed_project
        assert result.success is True
        # ... verify database state ...
```

**Key patterns:**

- Use `@pytest.mark.skipif` to skip gracefully when the test video is missing.
- Group tests in a class that shares the skip condition.
- Never re-run the stage in individual tests -- read the shared fixture result.

### Testing Derived Stages (Profanity, Chronemic, Highlights)

Derived stages operate on data already in the database. They do not need real video, only synthetic rows in the transcript, emotion, and speaker tables.

From `tests/test_derived_stages.py`:

```python
class TestProfanityStage:
    def test_profanity_detection(self, mock_project):
        project_id, db_path, project_dir, config = mock_project
        result = asyncio.run(
            run_profanity(project_id, db_path, project_dir, config),
        )

        assert result.success is True
        assert result.operation == "profanity_detection"
        assert result.provenance_record_id is not None

        # Verify the actual database records
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            events = fetch_all(
                conn,
                "SELECT * FROM profanity_events WHERE project_id = ?",
                (project_id,),
            )
            assert len(events) >= 3
            words_found = [str(e["word"]).lower().strip(".,") for e in events]
            assert any(w in words_found for w in ["damn", "shit", "crap", "sucks"])

            safety = fetch_one(
                conn,
                "SELECT * FROM content_safety WHERE project_id = ?",
                (project_id,),
            )
            assert safety is not None
            assert int(safety["profanity_count"]) >= 3
            assert safety["content_rating"] in ("mild", "moderate", "explicit")
        finally:
            conn.close()
```

### Testing Stages with Optional ML Dependencies

Some stages depend on models (SigLIP, WhisperX) that may not be installed. Test helper functions and constants directly, and verify that the module imports correctly.

From `tests/test_visual_pipeline.py`:

```python
class TestModuleImports:
    """Verify all visual pipeline modules import correctly."""

    def test_import_visual_embed(self) -> None:
        from clipcannon.pipeline.visual_embed import (
            OPERATION, STAGE, run_visual_embed,
        )
        assert OPERATION == "visual_embedding"
        assert callable(run_visual_embed)

class TestVisualEmbedHelpers:
    """Unit tests for visual embedding helper functions."""

    def test_cosine_similarity_identical(self) -> None:
        from clipcannon.pipeline.visual_embed import _cosine_similarity
        vec = [1.0, 2.0, 3.0, 4.0]
        sim = _cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6
```

### Testing Pure Logic (No I/O)

For pure functions like topological sort, content rating, or timestamp formatting, use simple function-scoped tests with no fixtures.

```python
class TestContentRating:
    def test_clean(self):
        assert _compute_content_rating(0) == "clean"

    def test_mild(self):
        assert _compute_content_rating(1) == "mild"
        assert _compute_content_rating(3) == "mild"

    def test_moderate(self):
        assert _compute_content_rating(4) == "moderate"
        assert _compute_content_rating(10) == "moderate"

    def test_explicit(self):
        assert _compute_content_rating(11) == "explicit"
```

---

## 5. Testing MCP Tools

MCP tools are async functions that return dictionaries. Tests call them directly (not through the MCP server) and verify the response structure.

### Setting Up a Ready Project

MCP tool tests need a project in `"ready"` status with fully populated analysis data. The fixture is more comprehensive than pipeline stage fixtures because the tools expect all streams to be complete.

From `tests/test_understanding_tools.py`:

```python
@pytest.fixture
def ready_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a project in 'ready' status with synthetic analysis data."""
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    # Create a synthetic frame file
    frame_path = project_dir / "frames" / "frame_000001.jpg"
    frame_path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    db_path = create_project_db(project_id, base_dir=tmp_path)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        # Insert project row with status='ready'
        execute(conn, """INSERT INTO project (...) VALUES (...)""",
                (project_id, "Test Video", ..., "ready"))

        # Insert ALL required data: speakers, segments, topics, highlights,
        # reactions, emotion_curve, beats, content_safety, stream_status,
        # pacing, silence_gaps, scenes, storyboard_grids, provenance
        # ...

        conn.commit()
    finally:
        conn.close()

    # Monkeypatch the projects directory to use tmp_path
    import clipcannon.tools.understanding as und_mod
    monkeypatch.setattr(und_mod, "_projects_dir", lambda: tmp_path)

    return {
        "project_id": project_id,
        "db_path": db_path,
        "project_dir": project_dir,
        "tmp_path": tmp_path,
    }
```

**Critical detail:** Use `monkeypatch.setattr` to redirect the tool's project directory resolution to `tmp_path`. Without this, the tool tries to find the project in `~/.clipcannon/projects/`.

### Calling Async Tool Functions

```python
class TestGetVudSummary:
    @pytest.mark.asyncio
    async def test_returns_summary(self, ready_project):
        pid = str(ready_project["project_id"])
        result = await clipcannon_get_vud_summary(pid)

        assert "error" not in result
        assert result["project_id"] == pid
        assert result["name"] == "Test Video"
        assert result["duration_ms"] == 120000
        assert result["status"] == "ready"

        # Verify nested structure
        assert isinstance(result["speakers"], dict)
        assert result["speakers"]["count"] == 2
        assert len(result["top_highlights"]) == 2
```

### Testing Error Cases

Every tool should handle missing projects, invalid parameters, and wrong project states. Test all of these.

```python
class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_vud_summary_not_found(self, ready_project):
        result = await clipcannon_get_vud_summary("proj_does_not_exist")
        assert result["error"]["code"] == "PROJECT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_wrong_status(self, ready_project):
        """Returns INVALID_STATE when project is not ready."""
        pid = str(ready_project["project_id"])
        db = Path(str(ready_project["db_path"]))
        # Change status to 'created'
        conn = get_connection(db, enable_vec=False, dict_rows=False)
        try:
            execute(conn,
                    "UPDATE project SET status = 'created' WHERE project_id = ?",
                    (pid,))
            conn.commit()
        finally:
            conn.close()

        result = await clipcannon_get_vud_summary(pid)
        assert "error" in result
        assert result["error"]["code"] == "INVALID_STATE"

    @pytest.mark.asyncio
    async def test_invalid_section(self, ready_project):
        pid = str(ready_project["project_id"])
        result = await clipcannon_get_analytics(pid, sections=["invalid_section"])
        assert "error" in result
        assert result["error"]["code"] == "INVALID_PARAMETER"
```

### Testing Response Size Constraints

MCP responses should stay within token limits. Verify this with a size assertion.

```python
@pytest.mark.asyncio
async def test_response_size_under_8k_tokens(self, ready_project):
    pid = str(ready_project["project_id"])
    result = await clipcannon_get_vud_summary(pid)
    json_str = json.dumps(result, default=str)
    # 8K tokens ~ 32KB of JSON
    assert len(json_str) < 32_000, f"Response too large: {len(json_str)} bytes"
```

---

## 6. Testing Provenance

### Creating a Chain of Records

Use `record_provenance()` to build a chain. Each record references its parent by `parent_record_id`.

From `tests/test_provenance_integration.py`:

```python
@pytest.fixture()
def project_db(tmp_path: Path) -> Path:
    """Create a temporary project database with a project row."""
    db_path = create_project_db("test_project", base_dir=tmp_path)
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    conn.execute(
        """INSERT INTO project (
            project_id, name, source_path, source_sha256,
            duration_ms, resolution, fps, codec
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("test_project", "Test Project", "/tmp/test.mp4", "abc123def456",
         60000, "1920x1080", 30.0, "h264"),
    )
    conn.commit()
    conn.close()
    return db_path


def test_record_chain_of_3_and_verify(self, project_db: Path):
    project_id = "test_project"

    # Record 1: Genesis (no parent)
    r1 = record_provenance(
        db_path=project_db,
        project_id=project_id,
        operation="ingest",
        stage="source",
        input_info=InputInfo(file_path="/tmp/video.mp4", sha256="aaa111",
                             size_bytes=1000000),
        output_info=OutputInfo(file_path="/tmp/output1.db", sha256="bbb222",
                               size_bytes=5000),
        model_info=None,
        execution_info=ExecutionInfo(duration_ms=500),
        parent_record_id=None,
        description="Ingest source video",
    )
    assert r1 == "prov_001"

    # Record 2: child of record 1
    r2 = record_provenance(
        db_path=project_db,
        project_id=project_id,
        operation="transcription",
        stage="whisperx",
        input_info=InputInfo(file_path="/tmp/audio.wav", sha256="ccc333",
                             size_bytes=2000000),
        output_info=OutputInfo(sha256="ddd444", record_count=150),
        model_info=ModelInfo(name="whisperx", version="3.1",
                             quantization="fp16",
                             parameters={"beam_size": 5, "language": "en"}),
        execution_info=ExecutionInfo(duration_ms=15000, gpu_device="cuda:0",
                                     vram_peak_mb=4096.5),
        parent_record_id=r1,
    )
    assert r2 == "prov_002"

    # Record 3: child of record 2
    r3 = record_provenance(
        db_path=project_db,
        project_id=project_id,
        operation="emotion",
        stage="wav2vec2",
        input_info=InputInfo(sha256="eee555"),
        output_info=OutputInfo(sha256="fff666", record_count=300),
        model_info=ModelInfo(name="wav2vec2-emotion", version="1.0",
                             parameters={"window_ms": 500}),
        execution_info=ExecutionInfo(duration_ms=8000, gpu_device="cuda:0"),
        parent_record_id=r2,
    )
    assert r3 == "prov_003"

    # Verify the entire chain
    result = verify_chain(project_id, project_db)
    assert result.verified is True
    assert result.total_records == 3
```

### Verifying Chain Integrity

`verify_chain()` walks all records in timestamp order, recomputes each `chain_hash`, and compares it to the stored value.

```python
from clipcannon.provenance.chain import verify_chain, ChainVerificationResult

result = verify_chain(project_id, db_path)
assert result.verified is True
assert result.total_records == expected_count
assert result.broken_at is None
assert result.issue is None
```

### Testing Tamper Detection

To verify tamper detection, modify a field that participates in the chain hash computation, then re-verify. The chain should break at the tampered record.

From `tests/test_provenance_integration.py`:

```python
def test_tampered_chain_detected(self, project_db: Path):
    project_id = "test_project"

    # Build a chain of 3 records
    r1 = record_provenance(...)
    r2 = record_provenance(..., parent_record_id=r1)
    r3 = record_provenance(..., parent_record_id=r2)

    # Tamper with record 2's input_sha256
    conn = get_connection(project_db, enable_vec=False, dict_rows=False)
    conn.execute(
        "UPDATE provenance SET input_sha256 = ? WHERE record_id = ?",
        ("TAMPERED", r2),
    )
    conn.commit()
    conn.close()

    # Verify should fail at record 2
    result = verify_chain(project_id, project_db)
    assert result.verified is False
    assert result.broken_at == r2
    assert "mismatch" in (result.issue or "").lower()
```

**Fields used in chain hash computation:** `parent_hash`, `input_sha256`, `output_sha256`, `operation`, `model_name`, `model_version`, `model_parameters`. Tampering with any of these breaks the chain.

### Deterministic Hashing in Tests

Use `sha256_string` for predictable hash values in test assertions:

```python
from clipcannon.provenance.hasher import sha256_string, sha256_bytes

# Known SHA-256 for "hello"
assert sha256_bytes(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

# String and bytes produce the same hash
assert sha256_string("hello") == sha256_bytes(b"hello")
```

---

## 7. Testing Billing

### License Server with FastAPI TestClient

The license server tests use a temporary database patched into the server module. This avoids touching the real `license.db`.

From `tests/test_billing.py`:

```python
class TestLicenseServer:
    @pytest.fixture(autouse=True)
    def setup_temp_db(self, tmp_path: Path) -> None:
        """Set up a temporary database for each test."""
        import license_server.server as srv_mod

        self.db_path = tmp_path / "license.db"
        self.db_dir = tmp_path

        # Patch DB_DIR and DB_PATH in the server module
        self._patches = [
            patch.object(srv_mod, "DB_DIR", tmp_path),
            patch.object(srv_mod, "DB_PATH", self.db_path),
        ]
        for p in self._patches:
            p.start()

        # Initialize the database
        srv_mod._init_db()

    def teardown_method(self) -> None:
        for p in self._patches:
            p.stop()

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from license_server.server import app
        return TestClient(app)
```

**Why `autouse=True`:** Every test in the class needs a fresh database. The `setup_temp_db` fixture runs automatically before each test method.

### Testing HMAC Sign/Verify/Tamper

```python
class TestHmacSigning:
    def test_sign_same_balance_is_deterministic(self):
        mid = get_machine_id()
        sig1 = sign_balance(100, mid)
        sig2 = sign_balance(100, mid)
        assert sig1 == sig2

    def test_verify_valid_balance(self):
        mid = get_machine_id()
        sig = sign_balance(500, mid)
        assert verify_balance(500, sig, mid) is True

    def test_verify_tampered_balance(self):
        mid = get_machine_id()
        sig = sign_balance(500, mid)
        # Tamper: change balance from 500 to 9999
        assert verify_balance(9999, sig, mid) is False

    def test_verify_or_raise_raises_on_tamper(self):
        mid = get_machine_id()
        sig = sign_balance(100, mid)
        with pytest.raises(BillingError) as exc_info:
            verify_balance_or_raise(999, sig, mid)
        assert "BALANCE_TAMPERED" in str(exc_info.value.details.get("code", ""))
```

### Testing Idempotency Keys

```python
def test_idempotency_prevents_double_charge(self, client):
    mid = get_machine_id()
    idem_key = str(uuid.uuid4())

    # First charge
    resp1 = client.post("/v1/charge", json={
        "machine_id": mid, "operation": "analyze", "credits": 10,
        "project_id": "proj_test", "idempotency_key": idem_key,
    })
    assert resp1.json()["balance_after"] == 90

    # Second charge with same key
    resp2 = client.post("/v1/charge", json={
        "machine_id": mid, "operation": "analyze", "credits": 10,
        "project_id": "proj_test", "idempotency_key": idem_key,
    })
    assert resp2.json()["balance_after"] == 90  # Not 80! Idempotent.
    assert resp2.json().get("idempotent_replay") is True

    # Verify balance is still 90
    bal = client.get("/v1/balance").json()
    assert bal["balance"] == 90
```

### Testing Database Tamper Detection

```python
def test_tamper_detection(self, client):
    """Tampered database balance is detected on read."""
    # Directly modify the balance in SQLite without updating HMAC
    conn = sqlite3.connect(str(self.db_path))
    conn.execute("UPDATE balance SET balance = 99999 WHERE id = 1")
    conn.commit()
    conn.close()

    # Next balance read should detect tampering
    resp = client.get("/v1/balance")
    assert resp.status_code == 403
    data = resp.json()
    assert data["error"] == "BALANCE_TAMPERED"
```

### Verifying Physical DB State

After charge/refund operations, always verify the database state directly, not just the API response:

```python
def test_charge_credits(self, client):
    mid = get_machine_id()
    resp = client.post("/v1/charge", json={...})
    assert resp.json()["balance_after"] == 90

    # Also verify via separate endpoint
    bal = client.get("/v1/balance").json()
    assert bal["balance"] == 90
```

---

## 8. Testing Dashboard

### Dashboard TestClient Setup

The dashboard uses `create_app()` to build the FastAPI application:

```python
from clipcannon.dashboard.app import create_app
from fastapi.testclient import TestClient

@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app)
```

### Testing API Endpoints

From `tests/dashboard/test_dashboard.py`:

```python
class TestHealth:
    def test_health_returns_ok(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert data["service"] == "clipcannon-dashboard"
```

### Testing Auth Flows

```python
class TestAuth:
    def test_dev_login_sets_cookie(self, client: TestClient):
        resp = client.get("/auth/dev-login")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "user_id" in data
        assert "clipcannon_session" in resp.cookies

    def test_token_roundtrip(self):
        """JWT token creation and verification round-trip."""
        token = create_session_token("user-123", "user@test.com")
        payload = verify_session_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["email"] == "user@test.com"

    def test_invalid_token_returns_none(self):
        result = verify_session_token("invalid-token-string")
        assert result is None
```

### Testing Not-Found Cases

```python
class TestProjects:
    def test_project_detail_not_found(self, client: TestClient):
        resp = client.get("/api/projects/nonexistent-project-xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False
```

---

## 9. Performance Optimization Rules

### Rule 1: NEVER Re-run FFmpeg in Function-Scoped Fixtures

FFmpeg operations (probe, audio extraction, frame extraction) take 2-30 seconds each. Running them per-test is unacceptable. Always use `scope="module"` and share the result.

**Wrong:**
```python
@pytest.fixture  # function scope = runs every test
def probed_project(tmp_path):
    result = asyncio.run(run_probe(...))  # 3 seconds per test!
    return result
```

**Right:**
```python
@pytest.fixture(scope="module")
def probed_project(tmp_path_factory):
    base = tmp_path_factory.mktemp("probe")
    result = asyncio.run(run_probe(...))  # 3 seconds total for all tests
    return result
```

### Rule 2: NEVER Reload ML Models Between Tests

If you test a stage that loads a model, use `scope="module"` or `scope="session"` so the model loads once.

### Rule 3: Use Synthetic Data When You Don't Need Real Video

If a stage only reads from database tables (profanity, chronemic, highlights, finalize), use synthetic database records instead of running the full upstream pipeline.

### Rule 4: Create PIL Images Instead of Extracting Real Frames

From `tests/test_visual_pipeline.py`:

```python
num_frames = 20
for i in range(1, num_frames + 1):
    frame_path = frames_dir / f"frame_{i:06d}.jpg"
    if i <= 5:
        color = (255, 0, 0)      # Red scene
    elif i <= 10:
        color = (0, 255, 0)      # Green scene
    elif i <= 15:
        color = (0, 0, 255)      # Blue scene
    else:
        color = (255, 255, 0)    # Yellow scene

    img = Image.new("RGB", (640, 480), color=color)
    # Add variation within scenes
    for x in range(0, 640, 64):
        for y in range(0, 480, 64):
            variation = ((i * 17 + x * 3 + y * 7) % 50) - 25
            r = max(0, min(255, color[0] + variation))
            g = max(0, min(255, color[1] + variation))
            b = max(0, min(255, color[2] + variation))
            img.putpixel((x, y), (r, g, b))

    img.save(str(frame_path), "JPEG", quality=80)
```

This creates 20 distinct frames across 4 "scenes" in milliseconds, compared to extracting real frames which takes seconds.

### Rule 5: Share DB State Across Tests in Same Module

When multiple tests in the same class read from the database without modifying it, use a shared fixture.

From `tests/test_pipeline_stages.py`, both `test_probe_extracts_metadata` and `test_probe_writes_provenance` share the same `probed_project` fixture. They both read from the database but neither modifies it.

### Rule 6: Skip Expensive Tests When Resources Are Missing

```python
@pytest.mark.skipif(
    not TEST_VIDEO.exists(),
    reason=f"Test video not found at {TEST_VIDEO}",
)
class TestProbeStage:
    ...
```

Or inside a fixture:

```python
def _skip_if_no_video():
    if not TEST_VIDEO.exists():
        pytest.skip(f"Test video not found: {TEST_VIDEO}")
```

---

## 10. Anti-Patterns

### Do Not Use `mock.patch` for Core Logic

`mock.patch` is acceptable for **environment configuration** (patching DB paths, module-level constants) but not for pipeline logic, database operations, or provenance chains.

**Acceptable:** Patching `DB_DIR` and `DB_PATH` in the license server to use a temp directory.

```python
self._patches = [
    patch.object(srv_mod, "DB_DIR", tmp_path),
    patch.object(srv_mod, "DB_PATH", self.db_path),
]
```

**Not acceptable:** Patching `run_probe` to return a fake result. If probe needs testing, use a real video or skip the test.

### Do Not Create Temp Directories Per-Test When Module-Scope Works

If five tests all verify different aspects of the same probe result, creating five separate temp directories with five separate probes wastes 15 seconds.

### Do Not Test ML Model Inference in Unit Tests

Save inference tests for `tests/integration/`. Unit tests should test helper functions (cosine similarity, region classification, timestamp formatting) and import correctness.

### Do Not Assert on Exact Floating Point Values

```python
# Wrong
assert score == 0.85

# Right
assert abs(score - 0.85) < 1e-6
# Or use pytest.approx
assert score == pytest.approx(0.85, abs=1e-6)
```

### Do Not Ignore Cleanup

Always use `tmp_path` or `tmp_path_factory` for test files. If you must create temp directories manually, clean them up in `teardown_method`:

```python
def setup_method(self):
    self.tmp_dir = Path(tempfile.mkdtemp())

def teardown_method(self):
    shutil.rmtree(self.tmp_dir, ignore_errors=True)
```

### Do Not Forget to Close Database Connections

Always use try/finally when working with database connections in tests:

```python
conn = get_connection(db_path, enable_vec=False, dict_rows=True)
try:
    row = fetch_one(conn, "SELECT * FROM project WHERE project_id = ?", (pid,))
finally:
    conn.close()
```

### Do Not Combine Multiple Pipeline Stage Runs in a Single Test

Each `test_*` method should verify one stage or one aspect. Use a shared fixture for the execution, separate tests for the verification.

---

## 11. Cookbook

### Template: Testing a New Pipeline Stage

```python
"""Tests for the new_stage pipeline stage."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, execute, fetch_all, fetch_one
from clipcannon.db.schema import create_project_db
from clipcannon.pipeline.new_stage import run_new_stage
from clipcannon.pipeline.orchestrator import StageResult


@pytest.fixture
def project_with_data(tmp_path: Path):
    """Create a project with the data this stage needs."""
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    db_path = create_project_db(project_id, base_dir=tmp_path)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        # 1. Insert project row
        execute(
            conn,
            """INSERT INTO project (
                project_id, name, source_path, source_sha256,
                duration_ms, resolution, fps, codec, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, "Test Video", "/tmp/test.mp4", "abc123",
             120000, "1920x1080", 30.0, "h264", "probed"),
        )

        # 2. Insert whatever upstream data this stage reads from
        # batch_insert(conn, "table_name", ["col1", "col2"], [...])

        conn.commit()
    finally:
        conn.close()

    config = ClipCannonConfig.load()
    return project_id, db_path, project_dir, config


class TestNewStage:
    """Tests for run_new_stage."""

    def test_stage_succeeds(self, project_with_data):
        project_id, db_path, project_dir, config = project_with_data
        result = asyncio.run(
            run_new_stage(project_id, db_path, project_dir, config),
        )

        assert result.success is True
        assert result.operation == "new_stage_operation"
        assert result.provenance_record_id is not None

    def test_stage_writes_expected_data(self, project_with_data):
        project_id, db_path, project_dir, config = project_with_data
        asyncio.run(run_new_stage(project_id, db_path, project_dir, config))

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT * FROM output_table WHERE project_id = ?",
                (project_id,),
            )
            assert len(rows) > 0
            # Verify specific field values
        finally:
            conn.close()

    def test_stage_writes_provenance(self, project_with_data):
        project_id, db_path, project_dir, config = project_with_data
        result = asyncio.run(
            run_new_stage(project_id, db_path, project_dir, config),
        )

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT * FROM provenance WHERE project_id = ? AND operation = ?",
                (project_id, "new_stage_operation"),
            )
            assert row is not None
            assert row["chain_hash"] is not None
            assert len(str(row["chain_hash"])) == 64
        finally:
            conn.close()
```

### Template: Testing a New MCP Tool

```python
"""Tests for the new MCP tool."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, execute
from clipcannon.db.schema import create_project_db
from clipcannon.tools.new_tool import clipcannon_new_tool


@pytest.fixture
def ready_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a project in 'ready' status."""
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True)

    for subdir in ["source", "stems", "frames", "storyboards"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    db_path = create_project_db(project_id, base_dir=tmp_path)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        execute(conn, """INSERT INTO project (...) VALUES (...)""",
                (project_id, ..., "ready"))
        # Insert whatever data the tool reads
        conn.commit()
    finally:
        conn.close()

    # Redirect project lookup to tmp_path
    import clipcannon.tools.new_tool as tool_mod
    monkeypatch.setattr(tool_mod, "_projects_dir", lambda: tmp_path)

    return {"project_id": project_id, "db_path": db_path, "tmp_path": tmp_path}


class TestNewTool:
    @pytest.mark.asyncio
    async def test_returns_expected_data(self, ready_project):
        pid = str(ready_project["project_id"])
        result = await clipcannon_new_tool(pid)

        assert "error" not in result
        assert result["project_id"] == pid
        # Verify response structure and values

    @pytest.mark.asyncio
    async def test_not_found(self, ready_project):
        result = await clipcannon_new_tool("nonexistent_project")
        assert "error" in result
        assert result["error"]["code"] == "PROJECT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_invalid_params(self, ready_project):
        pid = str(ready_project["project_id"])
        result = await clipcannon_new_tool(pid, invalid_param="bad")
        assert "error" in result
        assert result["error"]["code"] == "INVALID_PARAMETER"

    @pytest.mark.asyncio
    async def test_response_size(self, ready_project):
        pid = str(ready_project["project_id"])
        result = await clipcannon_new_tool(pid)
        json_str = json.dumps(result, default=str)
        assert len(json_str) < 32_000
```

### Template: Testing a Provenance Chain

```python
"""Tests for provenance chain operations."""
from __future__ import annotations

from pathlib import Path

import pytest

from clipcannon.db.connection import get_connection
from clipcannon.db.schema import create_project_db
from clipcannon.provenance.chain import verify_chain, GENESIS_HASH, compute_chain_hash
from clipcannon.provenance.recorder import (
    ExecutionInfo, InputInfo, ModelInfo, OutputInfo,
    record_provenance, get_provenance_record,
)


@pytest.fixture()
def project_db(tmp_path: Path) -> Path:
    db_path = create_project_db("test_proj", base_dir=tmp_path)
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    conn.execute(
        """INSERT INTO project (
            project_id, name, source_path, source_sha256,
            duration_ms, resolution, fps, codec
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("test_proj", "Test", "/tmp/v.mp4", "hash", 60000, "1920x1080", 30.0, "h264"),
    )
    conn.commit()
    conn.close()
    return db_path


class TestProvenanceChain:
    def test_build_and_verify(self, project_db):
        r1 = record_provenance(
            db_path=project_db, project_id="test_proj",
            operation="ingest", stage="source",
            input_info=InputInfo(sha256="in1"),
            output_info=OutputInfo(sha256="out1"),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=100),
            parent_record_id=None,
        )
        r2 = record_provenance(
            db_path=project_db, project_id="test_proj",
            operation="transcription", stage="whisperx",
            input_info=InputInfo(sha256="in2"),
            output_info=OutputInfo(sha256="out2"),
            model_info=ModelInfo(name="whisperx", version="3.1"),
            execution_info=ExecutionInfo(duration_ms=200),
            parent_record_id=r1,
        )

        result = verify_chain("test_proj", project_db)
        assert result.verified is True
        assert result.total_records == 2

    def test_tamper_breaks_chain(self, project_db):
        r1 = record_provenance(...)
        r2 = record_provenance(..., parent_record_id=r1)

        # Tamper
        conn = get_connection(project_db, enable_vec=False, dict_rows=False)
        conn.execute(
            "UPDATE provenance SET output_sha256 = 'TAMPERED' WHERE record_id = ?",
            (r1,),
        )
        conn.commit()
        conn.close()

        result = verify_chain("test_proj", project_db)
        assert result.verified is False
        assert result.broken_at == r1
```

### Template: Full State Verification Test

This template verifies the complete state of a project after running a pipeline. Use it for integration tests.

```python
"""Full state verification after pipeline execution."""
from __future__ import annotations

from pathlib import Path

import pytest

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.db.schema import PIPELINE_STREAMS
from clipcannon.provenance import verify_chain


class TestFullStateVerification:
    def test_complete_project_state(self, pipeline_project, full_pipeline_results):
        """Verify every aspect of the final project state."""
        p = pipeline_project

        # 1. All stages succeeded
        for stage_name, result in full_pipeline_results.items():
            assert result.success, f"{stage_name} failed: {result.error_message}"

        conn = get_connection(p["db_path"], enable_vec=False, dict_rows=True)
        try:
            # 2. Project status is 'ready'
            proj = fetch_one(conn, "SELECT * FROM project WHERE project_id = ?",
                             (p["project_id"],))
            assert proj["status"] == "ready"

            # 3. All streams completed
            streams = fetch_all(conn,
                "SELECT * FROM stream_status WHERE project_id = ?",
                (p["project_id"],))
            stream_map = {str(s["stream_name"]): str(s["status"]) for s in streams}
            for stream in PIPELINE_STREAMS:
                assert stream_map.get(stream) in ("completed", "skipped"), \
                    f"Stream {stream} is {stream_map.get(stream)}"

            # 4. Provenance records exist with valid hashes
            provenance = fetch_all(conn,
                "SELECT * FROM provenance WHERE project_id = ?",
                (p["project_id"],))
            assert len(provenance) > 0
            for prov in provenance:
                assert prov["chain_hash"] is not None
                assert len(str(prov["chain_hash"])) == 64

            # 5. Content safety is populated
            safety = fetch_one(conn,
                "SELECT * FROM content_safety WHERE project_id = ?",
                (p["project_id"],))
            assert safety is not None
            assert safety["content_rating"] is not None

            # 6. Highlights are scored
            highlights = fetch_all(conn,
                "SELECT * FROM highlights WHERE project_id = ? ORDER BY score DESC",
                (p["project_id"],))
            assert len(highlights) > 0
            for h in highlights:
                assert float(h["score"]) >= 0
                assert h["type"] is not None
                assert h["reason"] is not None

        finally:
            conn.close()

        # 7. Provenance chain integrity
        chain_result = verify_chain(p["project_id"], p["db_path"])
        assert chain_result.verified, (
            f"Provenance chain broken at {chain_result.broken_at}: "
            f"{chain_result.issue}"
        )

        # 8. Files on disk
        stems_dir = p["project_dir"] / "stems"
        assert (stems_dir / "audio_16k.wav").exists()
        assert (stems_dir / "audio_original.wav").exists()

        frames = sorted((p["project_dir"] / "frames").glob("frame_*.jpg"))
        assert len(frames) > 0

        grids = sorted((p["project_dir"] / "storyboards").glob("grid_*.jpg"))
        assert len(grids) > 0
```

---

## Quick Reference

### Running Tests

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_derived_stages.py

# Run a specific test class
pytest tests/test_billing.py::TestHmacSigning

# Run a specific test method
pytest tests/test_billing.py::TestHmacSigning::test_verify_tampered_balance

# Run with verbose output
pytest -v

# Run only tests that don't need the test video
pytest tests/test_derived_stages.py tests/test_billing.py tests/test_understanding_tools.py

# Run integration tests (requires test video)
pytest tests/integration/
```

### Common Imports

```python
# Database
from clipcannon.db.schema import create_project_db
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_one, fetch_all, execute, batch_insert

# Config
from clipcannon.config import ClipCannonConfig

# Pipeline
from clipcannon.pipeline.orchestrator import StageResult, PipelineStage

# Provenance
from clipcannon.provenance.chain import verify_chain, compute_chain_hash, GENESIS_HASH
from clipcannon.provenance.recorder import (
    record_provenance, InputInfo, OutputInfo, ModelInfo, ExecutionInfo,
)
from clipcannon.provenance.hasher import sha256_string, sha256_file

# Exceptions
from clipcannon.exceptions import PipelineError, BillingError, ProvenanceError
```

### Database Connection Patterns

```python
# Read-only query (most common in tests)
conn = get_connection(db_path, enable_vec=False, dict_rows=True)
try:
    row = fetch_one(conn, "SELECT * FROM table WHERE id = ?", (value,))
finally:
    conn.close()

# Write operation
conn = get_connection(db_path, enable_vec=False, dict_rows=False)
try:
    execute(conn, "INSERT INTO table (...) VALUES (...)", (...))
    conn.commit()
finally:
    conn.close()
```

**Note:** Always pass `enable_vec=False` in test connections unless you are specifically testing vector search. The sqlite-vec extension may not be available in all environments.
