"""Provenance hash chain computation and verification for ClipCannon.

Implements a tamper-evident hash chain where each provenance record's
chain_hash depends on its parent's chain_hash and its own content fields.
Any modification to a record or its ancestors is detectable by recomputing
and comparing chain hashes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from pydantic import BaseModel

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.exceptions import ProvenanceError

logger = logging.getLogger(__name__)

# Sentinel value used as parent_hash for the first record in a chain
GENESIS_HASH = "GENESIS"


class ChainVerificationResult(BaseModel):
    """Result of verifying a provenance chain.

    Attributes:
        verified: True if the entire chain is valid.
        total_records: Number of records examined.
        broken_at: Record ID where the chain broke, if any.
        issue: Human-readable description of the problem, if any.
    """

    verified: bool
    total_records: int
    broken_at: str | None = None
    issue: str | None = None


class ProvenanceChainRecord(BaseModel):
    """Lightweight record used during chain traversal.

    Attributes:
        record_id: Unique provenance record identifier.
        project_id: Project this record belongs to.
        timestamp_utc: ISO-8601 UTC timestamp of the record.
        operation: Pipeline operation name.
        stage: Pipeline stage name.
        description: Optional human-readable description.
        input_file_path: Path to the input file, if applicable.
        input_sha256: SHA-256 of the input, if applicable.
        input_size_bytes: Size of input in bytes, if applicable.
        parent_record_id: ID of the parent record, if any.
        output_file_path: Path to the output file, if applicable.
        output_sha256: SHA-256 of the output, if applicable.
        output_size_bytes: Size of output in bytes, if applicable.
        output_record_count: Number of output records, if applicable.
        model_name: Name of the ML model used, if applicable.
        model_version: Version of the ML model, if applicable.
        model_quantization: Quantization level, if applicable.
        model_parameters: JSON-encoded model parameters, if applicable.
        execution_duration_ms: Execution time in milliseconds, if applicable.
        execution_gpu_device: GPU device used, if applicable.
        execution_vram_peak_mb: Peak VRAM usage in MB, if applicable.
        chain_hash: The stored chain hash for this record.
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
    chain_hash: str = ""


def compute_chain_hash(
    parent_hash: str,
    input_sha256: str,
    output_sha256: str,
    operation: str,
    model_name: str,
    model_version: str,
    model_params: dict[str, str | int | float | bool | None],
) -> str:
    """Compute a chain hash linking a record to its parent.

    The chain hash is computed as:
        SHA256(f"{parent_hash}|{input_sha256}|{output_sha256}|{operation}|
               {model_name}|{model_version}|{json.dumps(model_params, sort_keys=True)}")

    For the first record in a chain (genesis), use parent_hash="GENESIS".

    Args:
        parent_hash: Chain hash of the parent record, or "GENESIS".
        input_sha256: SHA-256 hash of the input data.
        output_sha256: SHA-256 hash of the output data.
        operation: Pipeline operation name.
        model_name: Name of the ML model used.
        model_version: Version of the ML model.
        model_params: Dictionary of model parameters.

    Returns:
        Lowercase hex digest of the computed chain hash.

    Raises:
        ProvenanceError: If hash computation fails.
    """
    try:
        params_json = json.dumps(model_params, sort_keys=True)
        preimage = (
            f"{parent_hash}|{input_sha256}|{output_sha256}|"
            f"{operation}|{model_name}|{model_version}|{params_json}"
        )
        digest = hashlib.sha256(preimage.encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(
            f"Failed to compute chain hash: {exc}",
            details={"operation": operation, "error": str(exc)},
        ) from exc

    logger.debug("Computed chain hash for %s: %s", operation, digest)
    return digest


def _row_to_chain_record(row: dict[str, object]) -> ProvenanceChainRecord:
    """Convert a database row dict to a ProvenanceChainRecord.

    Args:
        row: Dictionary from fetch_one/fetch_all with dict row factory.

    Returns:
        ProvenanceChainRecord instance.
    """
    return ProvenanceChainRecord(
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


def _recompute_chain_hash_for_record(
    record: ProvenanceChainRecord,
    parent_chain_hash: str,
) -> str:
    """Recompute chain hash for a record given the parent's chain hash.

    Args:
        record: The provenance record to recompute for.
        parent_chain_hash: Chain hash of the parent record, or "GENESIS".

    Returns:
        The recomputed chain hash.
    """
    model_params: dict[str, str | int | float | bool | None] = {}
    if record.model_parameters:
        try:
            model_params = json.loads(record.model_parameters)
        except (json.JSONDecodeError, TypeError):
            model_params = {}

    return compute_chain_hash(
        parent_hash=parent_chain_hash,
        input_sha256=record.input_sha256 or "",
        output_sha256=record.output_sha256 or "",
        operation=record.operation,
        model_name=record.model_name or "",
        model_version=record.model_version or "",
        model_params=model_params,
    )


def verify_chain(project_id: str, db_path: Path) -> ChainVerificationResult:
    """Verify the integrity of the entire provenance chain for a project.

    Walks all provenance records in timestamp order, recomputes each
    record's chain_hash from its stored fields and its parent's chain_hash,
    and compares against the stored chain_hash. Any mismatch indicates
    tampering.

    Args:
        project_id: Project whose chain to verify.
        db_path: Path to the project database.

    Returns:
        ChainVerificationResult with verification outcome.

    Raises:
        ProvenanceError: If the database cannot be accessed.
    """
    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to open database for chain verification: {exc}",
            details={"db_path": str(db_path), "project_id": project_id},
        ) from exc

    try:
        rows = fetch_all(
            conn,
            "SELECT * FROM provenance WHERE project_id = ? ORDER BY timestamp_utc ASC, record_id ASC",
            (project_id,),
        )

        if not rows:
            logger.info("No provenance records found for project %s", project_id)
            return ChainVerificationResult(verified=True, total_records=0)

        # Build a lookup of record_id -> chain_hash for parent resolution
        record_hash_map: dict[str, str] = {}
        records = [_row_to_chain_record(row) for row in rows]

        for record in records:
            # Determine parent chain hash
            if record.parent_record_id is None:
                parent_chain_hash = GENESIS_HASH
            else:
                parent_chain_hash = record_hash_map.get(record.parent_record_id, "")
                if not parent_chain_hash:
                    return ChainVerificationResult(
                        verified=False,
                        total_records=len(records),
                        broken_at=record.record_id,
                        issue=(
                            f"Parent record {record.parent_record_id} not found "
                            f"or not yet processed for record {record.record_id}"
                        ),
                    )

            expected_hash = _recompute_chain_hash_for_record(record, parent_chain_hash)

            if expected_hash != record.chain_hash:
                logger.warning(
                    "Chain hash mismatch at record %s: expected=%s, stored=%s",
                    record.record_id,
                    expected_hash,
                    record.chain_hash,
                )
                return ChainVerificationResult(
                    verified=False,
                    total_records=len(records),
                    broken_at=record.record_id,
                    issue=(
                        f"Chain hash mismatch at record {record.record_id}: "
                        f"expected {expected_hash}, stored {record.chain_hash}"
                    ),
                )

            # Store this record's verified chain hash for children to reference
            record_hash_map[record.record_id] = record.chain_hash

        logger.info(
            "Provenance chain verified for project %s: %d records OK",
            project_id,
            len(records),
        )
        return ChainVerificationResult(verified=True, total_records=len(records))

    finally:
        conn.close()


def get_chain_from_genesis(
    project_id: str,
    record_id: str,
    db_path: Path,
) -> list[ProvenanceChainRecord]:
    """Walk from a target record back to genesis via parent links.

    Returns the chain ordered from genesis (first) to the target (last).

    Args:
        project_id: Project the record belongs to.
        record_id: ID of the target record to trace back from.
        db_path: Path to the project database.

    Returns:
        Ordered list of records from genesis to the target.

    Raises:
        ProvenanceError: If the database cannot be accessed or the
            record is not found.
    """
    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to open database for chain traversal: {exc}",
            details={"db_path": str(db_path), "project_id": project_id},
        ) from exc

    try:
        chain: list[ProvenanceChainRecord] = []
        current_id: str | None = record_id
        visited: set[str] = set()

        while current_id is not None:
            if current_id in visited:
                raise ProvenanceError(
                    f"Circular reference detected in provenance chain at {current_id}",
                    details={
                        "project_id": project_id,
                        "record_id": record_id,
                        "cycle_at": current_id,
                    },
                )
            visited.add(current_id)

            row = fetch_one(
                conn,
                "SELECT * FROM provenance WHERE project_id = ? AND record_id = ?",
                (project_id, current_id),
            )

            if row is None:
                if current_id == record_id:
                    raise ProvenanceError(
                        f"Provenance record not found: {record_id}",
                        details={
                            "project_id": project_id,
                            "record_id": record_id,
                        },
                    )
                raise ProvenanceError(
                    f"Broken chain: parent record {current_id} not found",
                    details={
                        "project_id": project_id,
                        "missing_record": current_id,
                        "target_record": record_id,
                    },
                )

            record = _row_to_chain_record(row)
            chain.append(record)
            current_id = record.parent_record_id

        # Reverse to get genesis-first ordering
        chain.reverse()

        logger.debug(
            "Chain from genesis to %s: %d records",
            record_id,
            len(chain),
        )
        return chain

    finally:
        conn.close()
