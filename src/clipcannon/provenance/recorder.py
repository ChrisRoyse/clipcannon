"""Provenance record creation and retrieval for ClipCannon.

Provides pydantic models for structured provenance data and functions
to write and query provenance records in the project database. Each
record is linked to its parent via chain hashing for tamper detection.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import count_rows, execute, fetch_all, fetch_one
from clipcannon.exceptions import ProvenanceError
from clipcannon.provenance.chain import GENESIS_HASH, compute_chain_hash

logger = logging.getLogger(__name__)


# ============================================================
# PYDANTIC MODELS
# ============================================================


class InputInfo(BaseModel):
    """Information about the input to a pipeline operation.

    Attributes:
        file_path: Path to the input file, if applicable.
        sha256: SHA-256 hash of the input data.
        size_bytes: Size of the input in bytes, if applicable.
    """

    file_path: str | None = None
    sha256: str = ""
    size_bytes: int | None = None


class OutputInfo(BaseModel):
    """Information about the output of a pipeline operation.

    Attributes:
        file_path: Path to the output file, if applicable.
        sha256: SHA-256 hash of the output data.
        size_bytes: Size of the output in bytes, if applicable.
        record_count: Number of records produced, if applicable.
    """

    file_path: str | None = None
    sha256: str = ""
    size_bytes: int | None = None
    record_count: int | None = None


class ModelInfo(BaseModel):
    """Information about the ML model used in a pipeline operation.

    Attributes:
        name: Model name (e.g., "whisperx", "siglip").
        version: Model version string.
        quantization: Quantization level (e.g., "fp16", "int8").
        parameters: Model-specific parameters as a dictionary.
    """

    name: str = ""
    version: str = ""
    quantization: str | None = None
    parameters: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
    )


class ExecutionInfo(BaseModel):
    """Information about the execution environment.

    Attributes:
        duration_ms: Execution time in milliseconds.
        gpu_device: GPU device used (e.g., "cuda:0").
        vram_peak_mb: Peak VRAM usage in megabytes.
    """

    duration_ms: int | None = None
    gpu_device: str | None = None
    vram_peak_mb: float | None = None


class ProvenanceRecord(BaseModel):
    """Complete provenance record matching the database schema.

    Attributes:
        record_id: Unique provenance record identifier (prov_001 format).
        project_id: Project this record belongs to.
        timestamp_utc: ISO-8601 UTC timestamp.
        operation: Pipeline operation name.
        stage: Pipeline stage name.
        description: Human-readable description of the operation.
        input_file_path: Path to the input file.
        input_sha256: SHA-256 of the input.
        input_size_bytes: Input size in bytes.
        parent_record_id: ID of the parent provenance record.
        output_file_path: Path to the output file.
        output_sha256: SHA-256 of the output.
        output_size_bytes: Output size in bytes.
        output_record_count: Number of output records.
        model_name: ML model name.
        model_version: ML model version.
        model_quantization: Quantization level.
        model_parameters: JSON-encoded model parameters.
        execution_duration_ms: Execution time in milliseconds.
        execution_gpu_device: GPU device identifier.
        execution_vram_peak_mb: Peak VRAM in megabytes.
        chain_hash: Computed chain hash linking to parent.
    """

    record_id: str
    project_id: str
    timestamp_utc: str
    operation: str
    stage: str
    description: str | None = None
    input_file_path: str | None = None
    input_sha256: str | None = None
    input_size_bytes: int | None = None
    parent_record_id: str | None = None
    output_file_path: str | None = None
    output_sha256: str | None = None
    output_size_bytes: int | None = None
    output_record_count: int | None = None
    model_name: str | None = None
    model_version: str | None = None
    model_quantization: str | None = None
    model_parameters: str | None = None
    execution_duration_ms: int | None = None
    execution_gpu_device: str | None = None
    execution_vram_peak_mb: float | None = None
    chain_hash: str


def _row_to_provenance_record(row: dict[str, object]) -> ProvenanceRecord:
    """Convert a database row dict to a ProvenanceRecord.

    Args:
        row: Dictionary from fetch_one/fetch_all with dict row factory.

    Returns:
        ProvenanceRecord instance.
    """
    return ProvenanceRecord(
        record_id=str(row["record_id"]),
        project_id=str(row["project_id"]),
        timestamp_utc=str(row["timestamp_utc"]),
        operation=str(row["operation"]),
        stage=str(row["stage"]),
        description=str(row["description"]) if row.get("description") else None,
        input_file_path=str(row["input_file_path"]) if row.get("input_file_path") else None,
        input_sha256=str(row["input_sha256"]) if row.get("input_sha256") else None,
        input_size_bytes=int(row["input_size_bytes"]) if row.get("input_size_bytes") is not None else None,
        parent_record_id=str(row["parent_record_id"]) if row.get("parent_record_id") else None,
        output_file_path=str(row["output_file_path"]) if row.get("output_file_path") else None,
        output_sha256=str(row["output_sha256"]) if row.get("output_sha256") else None,
        output_size_bytes=int(row["output_size_bytes"]) if row.get("output_size_bytes") is not None else None,
        output_record_count=int(row["output_record_count"]) if row.get("output_record_count") is not None else None,
        model_name=str(row["model_name"]) if row.get("model_name") else None,
        model_version=str(row["model_version"]) if row.get("model_version") else None,
        model_quantization=str(row["model_quantization"]) if row.get("model_quantization") else None,
        model_parameters=str(row["model_parameters"]) if row.get("model_parameters") else None,
        execution_duration_ms=int(row["execution_duration_ms"]) if row.get("execution_duration_ms") is not None else None,
        execution_gpu_device=str(row["execution_gpu_device"]) if row.get("execution_gpu_device") else None,
        execution_vram_peak_mb=float(row["execution_vram_peak_mb"]) if row.get("execution_vram_peak_mb") is not None else None,
        chain_hash=str(row["chain_hash"]),
    )


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

    chain_hash = row.get("chain_hash") if isinstance(row, dict) else None
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
    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to open database for provenance recording: {exc}",
            details={"db_path": str(db_path), "project_id": project_id},
        ) from exc

    try:
        # Generate record ID
        sequence = _get_next_sequence(conn, project_id)
        record_id = f"prov_{sequence:03d}"

        # Look up parent chain hash
        parent_chain_hash = _lookup_parent_chain_hash(
            conn, project_id, parent_record_id,
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
        timestamp_utc = datetime.now(timezone.utc).isoformat()

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

    except ProvenanceError:
        raise
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to record provenance: {exc}",
            details={
                "project_id": project_id,
                "operation": operation,
                "stage": stage,
                "error": str(exc),
            },
        ) from exc
    finally:
        conn.close()


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
    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to open database for provenance query: {exc}",
            details={"db_path": str(db_path), "project_id": project_id},
        ) from exc

    try:
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

    except ProvenanceError:
        raise
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to query provenance records: {exc}",
            details={
                "project_id": project_id,
                "operation": operation,
                "stage": stage,
                "error": str(exc),
            },
        ) from exc
    finally:
        conn.close()


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
    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to open database for provenance query: {exc}",
            details={"db_path": str(db_path), "project_id": project_id},
        ) from exc

    try:
        row = fetch_one(
            conn,
            "SELECT * FROM provenance WHERE project_id = ? AND record_id = ?",
            (project_id, record_id),
        )

        if row is None:
            return None

        return _row_to_provenance_record(row)

    except ProvenanceError:
        raise
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to query provenance record: {exc}",
            details={
                "project_id": project_id,
                "record_id": record_id,
                "error": str(exc),
            },
        ) from exc
    finally:
        conn.close()


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
