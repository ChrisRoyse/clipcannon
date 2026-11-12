"""Provenance record creation and retrieval for ClipCannon.

Provides pydantic models for structured provenance data and functions
to write and query provenance records in the project database. Each
record is linked to its parent via chain hashing for tamper detection.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel as BaseModel
from pydantic import Field as Field

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import count_rows, execute, fetch_all, fetch_one
from clipcannon.exceptions import ProvenanceError
from clipcannon.provenance.chain import GENESIS_HASH, compute_chain_hash
from clipcannon.provenance.recorder_models import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    ProvenanceRecord,
    _row_to_provenance_record,
)
from clipcannon.provenance.recorder_models import _opt_float as _opt_float
from clipcannon.provenance.recorder_models import _opt_int as _opt_int
from clipcannon.provenance.recorder_models import _opt_str as _opt_str

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Generator
    from pathlib import Path

logger = logging.getLogger(__name__)


@contextmanager
def _provenance_conn(
    db_path: Path, project_id: str, action: str
) -> Generator[sqlite3.Connection, None, None]:
    """Open a database connection for provenance operations.

    Wraps the common open/close/error-handling pattern shared by all
    public provenance functions.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier (used in error details).
        action: Human-readable action name for error messages.

    Yields:
        An open SQLite connection.

    Raises:
        ProvenanceError: If the connection cannot be opened or the
            body raises a non-ProvenanceError exception.
    """
    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to open database for provenance {action}: {exc}",
            details={"db_path": str(db_path), "project_id": project_id},
        ) from exc

    try:
        yield conn
    except ProvenanceError:
        raise
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to {action}: {exc}",
            details={"project_id": project_id, "error": str(exc)},
        ) from exc
    finally:
        conn.close()


def _get_next_sequence(conn: sqlite3.Connection, project_id: str) -> int:
    """Get the next sequence number for a provenance record.

    Args:
        conn: SQLite connection.
        project_id: Project to count existing records for.

    Returns:
        Next sequence number (1-based).

    Raises:
        ProvenanceError: If the count query fails.
    """
    try:
        count = count_rows(conn, "provenance", "project_id = ?", (project_id,))
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to count provenance records: {exc}",
            details={"project_id": project_id, "error": str(exc)},
        ) from exc

    return count + 1


def _lookup_parent_chain_hash(
    conn: sqlite3.Connection,
    project_id: str,
    parent_record_id: str | None,
) -> str:
    """Look up the chain hash of a parent record.

    Args:
        conn: SQLite connection.
        project_id: Project the parent belongs to.
        parent_record_id: ID of the parent record, or None for genesis.

    Returns:
        Parent's chain hash, or GENESIS_HASH if no parent.

    Raises:
        ProvenanceError: If the parent record does not exist.
    """
    if parent_record_id is None:
        return GENESIS_HASH

    row = fetch_one(
        conn,
        "SELECT chain_hash FROM provenance WHERE project_id = ? AND record_id = ?",
        (project_id, parent_record_id),
    )

    if row is None:
        raise ProvenanceError(
            f"Parent provenance record not found: {parent_record_id}",
            details={
                "project_id": project_id,
                "parent_record_id": parent_record_id,
            },
        )

    chain_hash = row.get("chain_hash")
    if chain_hash is None:
        raise ProvenanceError(
            f"Parent record {parent_record_id} has no chain_hash",
            details={
                "project_id": project_id,
                "parent_record_id": parent_record_id,
            },
        )

    return str(chain_hash)


def record_provenance(
    db_path: Path,
    project_id: str,
    operation: str,
    stage: str,
    input_info: InputInfo,
    output_info: OutputInfo,
    model_info: ModelInfo | None,
    execution_info: ExecutionInfo,
    parent_record_id: str | None,
    description: str | None = None,
) -> str:
    """Record a provenance entry in the project database.

    Auto-generates a record_id in the format prov_001, prov_002, etc.
    Computes the chain_hash by looking up the parent's chain_hash
    (or using "GENESIS" if no parent) and combining it with the
    record's content fields.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        operation: Pipeline operation name (e.g., "transcription").
        stage: Pipeline stage name (e.g., "whisperx").
        input_info: Information about the input data.
        output_info: Information about the output data.
        model_info: Information about the ML model, or None if no model.
        execution_info: Information about the execution environment.
        parent_record_id: ID of the parent record, or None for genesis.
        description: Optional human-readable description.

    Returns:
        The generated record_id (e.g., "prov_001").

    Raises:
        ProvenanceError: If the record cannot be created.
    """
    with _provenance_conn(db_path, project_id, "record provenance") as conn:
        # Generate record ID
        sequence = _get_next_sequence(conn, project_id)
        record_id = f"prov_{sequence:03d}"

        # Look up parent chain hash
        parent_chain_hash = _lookup_parent_chain_hash(
            conn,
            project_id,
            parent_record_id,
        )

        # Prepare model fields
        model_name = model_info.name if model_info else ""
        model_version = model_info.version if model_info else ""
        model_quantization = model_info.quantization if model_info else None
        model_params = model_info.parameters if model_info else {}
        model_params_json = json.dumps(model_params, sort_keys=True)

        # Compute chain hash
        chain_hash = compute_chain_hash(
            parent_hash=parent_chain_hash,
            input_sha256=input_info.sha256,
            output_sha256=output_info.sha256,
            operation=operation,
            model_name=model_name,
            model_version=model_version,
            model_params=model_params,
        )

        # Generate timestamp
        timestamp_utc = datetime.now(UTC).isoformat()

        # Insert record
        sql = """
            INSERT INTO provenance (
                record_id, project_id, timestamp_utc, operation, stage,
                description, input_file_path, input_sha256, input_size_bytes,
                parent_record_id, output_file_path, output_sha256,
                output_size_bytes, output_record_count, model_name,
                model_version, model_quantization, model_parameters,
                execution_duration_ms, execution_gpu_device,
                execution_vram_peak_mb, chain_hash
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?
            )
        """
        params = (
            record_id,
            project_id,
            timestamp_utc,
            operation,
            stage,
            description,
            input_info.file_path,
            input_info.sha256 or None,
            input_info.size_bytes,
            parent_record_id,
            output_info.file_path,
            output_info.sha256 or None,
            output_info.size_bytes,
            output_info.record_count,
            model_name or None,
            model_version or None,
            model_quantization,
            model_params_json if model_params else None,
            execution_info.duration_ms,
            execution_info.gpu_device,
            execution_info.vram_peak_mb,
            chain_hash,
        )

        execute(conn, sql, params)
        conn.commit()

        logger.info(
            "Recorded provenance %s for project %s: %s/%s",
            record_id,
            project_id,
            operation,
            stage,
        )
        return record_id


def get_provenance_records(
    db_path: Path,
    project_id: str,
    operation: str | None = None,
    stage: str | None = None,
) -> list[ProvenanceRecord]:
    """Retrieve provenance records with optional filtering.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        operation: Optional filter by operation name.
        stage: Optional filter by stage name.

    Returns:
        List of matching ProvenanceRecord instances, ordered by timestamp.

    Raises:
        ProvenanceError: If the query fails.
    """
    with _provenance_conn(db_path, project_id, "query provenance records") as conn:
        conditions = ["project_id = ?"]
        params: list[str] = [project_id]

        if operation is not None:
            conditions.append("operation = ?")
            params.append(operation)

        if stage is not None:
            conditions.append("stage = ?")
            params.append(stage)

        where_clause = " AND ".join(conditions)
        sql = f"SELECT * FROM provenance WHERE {where_clause} ORDER BY timestamp_utc ASC"  # noqa: S608

        rows = fetch_all(conn, sql, tuple(params))
        return [_row_to_provenance_record(row) for row in rows]


def get_provenance_record(
    db_path: Path,
    project_id: str,
    record_id: str,
) -> ProvenanceRecord | None:
    """Retrieve a single provenance record by ID.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        record_id: Provenance record identifier.

    Returns:
        ProvenanceRecord if found, None otherwise.

    Raises:
        ProvenanceError: If the query fails.
    """
    with _provenance_conn(db_path, project_id, "query provenance record") as conn:
        row = fetch_one(
            conn,
            "SELECT * FROM provenance WHERE project_id = ? AND record_id = ?",
            (project_id, record_id),
        )

        if row is None:
            return None

        return _row_to_provenance_record(row)


def get_provenance_timeline(
    db_path: Path,
    project_id: str,
) -> list[ProvenanceRecord]:
    """Retrieve the full provenance timeline for a project.

    Returns all records ordered by timestamp, providing a complete
    chronological view of all operations performed on the project.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        List of ProvenanceRecord instances ordered by timestamp.

    Raises:
        ProvenanceError: If the query fails.
    """
    return get_provenance_records(db_path, project_id)
