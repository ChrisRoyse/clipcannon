"""Integration tests for the provenance system.

Tests the full provenance lifecycle: recording chains, verifying integrity,
detecting tampering, file hashing, and table content hashing.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from clipcannon.db.schema import create_project_db
from clipcannon.provenance.chain import (
    GENESIS_HASH,
    ChainVerificationResult,
    compute_chain_hash,
    get_chain_from_genesis,
    verify_chain,
)
from clipcannon.provenance.hasher import (
    sha256_bytes,
    sha256_file,
    sha256_string,
    sha256_table_content,
    verify_file_hash,
)
from clipcannon.provenance.recorder import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    ProvenanceRecord,
    get_provenance_record,
    get_provenance_records,
    get_provenance_timeline,
    record_provenance,
)


@pytest.fixture()
def project_db(tmp_path: Path) -> Path:
    """Create a temporary project database with a project row."""
    db_path = create_project_db("test_project", base_dir=tmp_path)
    # Insert a project row to satisfy foreign key constraints
    from clipcannon.db.connection import get_connection

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


class TestHasher:
    """Tests for the hasher module."""

    def test_sha256_file(self, tmp_path: Path) -> None:
        """Test SHA-256 hashing of a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        digest = sha256_file(test_file)
        assert len(digest) == 64
        assert digest == sha256_string("hello world")

    def test_sha256_file_streaming(self, tmp_path: Path) -> None:
        """Test that streaming hashing works for larger files."""
        test_file = tmp_path / "large.bin"
        # Write 100KB of data
        data = b"x" * (100 * 1024)
        test_file.write_bytes(data)
        digest = sha256_file(test_file)
        assert digest == sha256_bytes(data)

    def test_sha256_bytes(self) -> None:
        """Test SHA-256 hashing of bytes."""
        digest = sha256_bytes(b"hello")
        assert len(digest) == 64
        # Known SHA-256 for "hello"
        assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_sha256_string(self) -> None:
        """Test SHA-256 hashing of a string."""
        digest = sha256_string("hello")
        assert digest == sha256_bytes(b"hello")

    def test_verify_file_hash_match(self, tmp_path: Path) -> None:
        """Test file hash verification with matching hash."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        expected = sha256_file(test_file)
        assert verify_file_hash(test_file, expected) is True

    def test_verify_file_hash_mismatch(self, tmp_path: Path) -> None:
        """Test file hash verification with mismatched hash."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        assert verify_file_hash(test_file, "0" * 64) is False

    def test_sha256_file_not_found(self, tmp_path: Path) -> None:
        """Test that hashing a nonexistent file raises ProvenanceError."""
        from clipcannon.exceptions import ProvenanceError

        with pytest.raises(ProvenanceError, match="File not found"):
            sha256_file(tmp_path / "nonexistent.txt")

    def test_sha256_table_content(self, project_db: Path) -> None:
        """Test hashing of table content."""
        from clipcannon.db.connection import get_connection

        conn = get_connection(project_db, enable_vec=False, dict_rows=True)
        try:
            # Project row already exists from fixture
            digest = sha256_table_content(conn, "project", "test_project")
            assert len(digest) == 64

            # Same content should produce same hash
            digest2 = sha256_table_content(conn, "project", "test_project")
            assert digest == digest2
        finally:
            conn.close()


class TestChain:
    """Tests for the chain module."""

    def test_compute_chain_hash_deterministic(self) -> None:
        """Test that chain hash computation is deterministic."""
        h1 = compute_chain_hash(
            GENESIS_HASH, "input1", "output1", "transcribe",
            "whisperx", "3.1", {"beam_size": 5},
        )
        h2 = compute_chain_hash(
            GENESIS_HASH, "input1", "output1", "transcribe",
            "whisperx", "3.1", {"beam_size": 5},
        )
        assert h1 == h2

    def test_compute_chain_hash_different_parent(self) -> None:
        """Test that different parent hashes produce different chain hashes."""
        h1 = compute_chain_hash(
            GENESIS_HASH, "input1", "output1", "transcribe",
            "whisperx", "3.1", {},
        )
        h2 = compute_chain_hash(
            "different_parent", "input1", "output1", "transcribe",
            "whisperx", "3.1", {},
        )
        assert h1 != h2

    def test_record_chain_of_3_and_verify(self, project_db: Path) -> None:
        """Test recording 3 provenance entries and verifying the chain."""
        project_id = "test_project"

        # Record 1: Genesis (ingest)
        r1 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="ingest",
            stage="source",
            input_info=InputInfo(
                file_path="/tmp/video.mp4",
                sha256="aaa111",
                size_bytes=1000000,
            ),
            output_info=OutputInfo(
                file_path="/tmp/output1.db",
                sha256="bbb222",
                size_bytes=5000,
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=500),
            parent_record_id=None,
            description="Ingest source video",
        )
        assert r1 == "prov_001"

        # Record 2: Transcription (child of 1)
        r2 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="transcription",
            stage="whisperx",
            input_info=InputInfo(
                file_path="/tmp/audio.wav",
                sha256="ccc333",
                size_bytes=2000000,
            ),
            output_info=OutputInfo(
                sha256="ddd444",
                record_count=150,
            ),
            model_info=ModelInfo(
                name="whisperx",
                version="3.1",
                quantization="fp16",
                parameters={"beam_size": 5, "language": "en"},
            ),
            execution_info=ExecutionInfo(
                duration_ms=15000,
                gpu_device="cuda:0",
                vram_peak_mb=4096.5,
            ),
            parent_record_id=r1,
            description="Transcribe audio with WhisperX",
        )
        assert r2 == "prov_002"

        # Record 3: Emotion analysis (child of 2)
        r3 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="emotion",
            stage="wav2vec2",
            input_info=InputInfo(
                file_path="/tmp/vocal.wav",
                sha256="eee555",
                size_bytes=1500000,
            ),
            output_info=OutputInfo(
                sha256="fff666",
                record_count=300,
            ),
            model_info=ModelInfo(
                name="wav2vec2-emotion",
                version="1.0",
                parameters={"window_ms": 500},
            ),
            execution_info=ExecutionInfo(
                duration_ms=8000,
                gpu_device="cuda:0",
                vram_peak_mb=2048.0,
            ),
            parent_record_id=r2,
            description="Emotion curve from vocal stem",
        )
        assert r3 == "prov_003"

        # Verify the chain passes
        result = verify_chain(project_id, project_db)
        assert result.verified is True
        assert result.total_records == 3
        assert result.broken_at is None
        assert result.issue is None

    def test_tampered_chain_detected(self, project_db: Path) -> None:
        """Test that tampering with a record is detected."""
        project_id = "test_project"

        # Record 3 entries
        r1 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="ingest",
            stage="source",
            input_info=InputInfo(sha256="aaa111"),
            output_info=OutputInfo(sha256="bbb222"),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=100),
            parent_record_id=None,
        )
        r2 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="transcription",
            stage="whisperx",
            input_info=InputInfo(sha256="ccc333"),
            output_info=OutputInfo(sha256="ddd444"),
            model_info=ModelInfo(name="whisperx", version="3.1"),
            execution_info=ExecutionInfo(duration_ms=200),
            parent_record_id=r1,
        )
        r3 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="emotion",
            stage="wav2vec2",
            input_info=InputInfo(sha256="eee555"),
            output_info=OutputInfo(sha256="fff666"),
            model_info=ModelInfo(name="wav2vec2", version="1.0"),
            execution_info=ExecutionInfo(duration_ms=300),
            parent_record_id=r2,
        )

        # Tamper with record 2's input_sha256
        from clipcannon.db.connection import get_connection

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

    def test_get_chain_from_genesis(self, project_db: Path) -> None:
        """Test walking chain from genesis to target."""
        project_id = "test_project"

        r1 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="ingest",
            stage="source",
            input_info=InputInfo(sha256="a1"),
            output_info=OutputInfo(sha256="b1"),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id=None,
        )
        r2 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="transcription",
            stage="whisperx",
            input_info=InputInfo(sha256="a2"),
            output_info=OutputInfo(sha256="b2"),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id=r1,
        )
        r3 = record_provenance(
            db_path=project_db,
            project_id=project_id,
            operation="emotion",
            stage="wav2vec2",
            input_info=InputInfo(sha256="a3"),
            output_info=OutputInfo(sha256="b3"),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id=r2,
        )

        chain = get_chain_from_genesis(project_id, r3, project_db)
        assert len(chain) == 3
        assert chain[0].record_id == r1  # Genesis first
        assert chain[1].record_id == r2
        assert chain[2].record_id == r3  # Target last


class TestRecorder:
    """Tests for the recorder module."""

    def test_record_id_format(self, project_db: Path) -> None:
        """Test that record IDs follow prov_NNN format."""
        r1 = record_provenance(
            db_path=project_db,
            project_id="test_project",
            operation="ingest",
            stage="source",
            input_info=InputInfo(sha256="hash1"),
            output_info=OutputInfo(sha256="hash2"),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id=None,
        )
        assert r1 == "prov_001"

    def test_get_provenance_record(self, project_db: Path) -> None:
        """Test retrieving a single record."""
        r1 = record_provenance(
            db_path=project_db,
            project_id="test_project",
            operation="ingest",
            stage="source",
            input_info=InputInfo(sha256="h1", file_path="/tmp/v.mp4"),
            output_info=OutputInfo(sha256="h2"),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=100),
            parent_record_id=None,
            description="Test record",
        )
        record = get_provenance_record(project_db, "test_project", r1)
        assert record is not None
        assert record.record_id == "prov_001"
        assert record.operation == "ingest"
        assert record.stage == "source"
        assert record.description == "Test record"
        assert record.input_sha256 == "h1"
        assert record.output_sha256 == "h2"
        assert record.execution_duration_ms == 100

    def test_get_provenance_record_not_found(self, project_db: Path) -> None:
        """Test that missing record returns None."""
        record = get_provenance_record(project_db, "test_project", "prov_999")
        assert record is None

    def test_get_provenance_records_filter(self, project_db: Path) -> None:
        """Test filtering records by operation and stage."""
        record_provenance(
            db_path=project_db,
            project_id="test_project",
            operation="ingest",
            stage="source",
            input_info=InputInfo(sha256="a"),
            output_info=OutputInfo(sha256="b"),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id=None,
        )
        r2 = record_provenance(
            db_path=project_db,
            project_id="test_project",
            operation="transcription",
            stage="whisperx",
            input_info=InputInfo(sha256="c"),
            output_info=OutputInfo(sha256="d"),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id="prov_001",
        )

        # Filter by operation
        records = get_provenance_records(
            project_db, "test_project", operation="transcription",
        )
        assert len(records) == 1
        assert records[0].record_id == r2

        # All records
        all_records = get_provenance_records(project_db, "test_project")
        assert len(all_records) == 2

    def test_get_provenance_timeline(self, project_db: Path) -> None:
        """Test timeline retrieval."""
        record_provenance(
            db_path=project_db,
            project_id="test_project",
            operation="ingest",
            stage="source",
            input_info=InputInfo(sha256="a"),
            output_info=OutputInfo(sha256="b"),
            model_info=None,
            execution_info=ExecutionInfo(),
            parent_record_id=None,
        )
        timeline = get_provenance_timeline(project_db, "test_project")
        assert len(timeline) == 1
        assert isinstance(timeline[0], ProvenanceRecord)

    def test_empty_chain_verification(self, project_db: Path) -> None:
        """Test that verifying an empty chain succeeds."""
        result = verify_chain("test_project", project_db)
        assert result.verified is True
        assert result.total_records == 0
