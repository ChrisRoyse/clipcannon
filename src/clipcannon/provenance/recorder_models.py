"""Provenance record models and row conversion for ClipCannon.

Split out of ``clipcannon.provenance.recorder`` (pure move): the pydantic
input/output/model/execution/record models and the helpers that turn a
``provenance`` table row into a ``ProvenanceRecord``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

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


def _opt_str(row: dict[str, object], key: str) -> str | None:
    """Return row[key] as str, or None if missing/falsy."""
    val = row.get(key)
    return str(val) if val else None


def _opt_int(row: dict[str, object], key: str) -> int | None:
    """Return row[key] as int, or None if missing/None."""
    val = row.get(key)
    return int(val) if val is not None else None


def _opt_float(row: dict[str, object], key: str) -> float | None:
    """Return row[key] as float, or None if missing/None."""
    val = row.get(key)
    return float(val) if val is not None else None


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
        description=_opt_str(row, "description"),
        input_file_path=_opt_str(row, "input_file_path"),
        input_sha256=_opt_str(row, "input_sha256"),
        input_size_bytes=_opt_int(row, "input_size_bytes"),
        parent_record_id=_opt_str(row, "parent_record_id"),
        output_file_path=_opt_str(row, "output_file_path"),
        output_sha256=_opt_str(row, "output_sha256"),
        output_size_bytes=_opt_int(row, "output_size_bytes"),
        output_record_count=_opt_int(row, "output_record_count"),
        model_name=_opt_str(row, "model_name"),
        model_version=_opt_str(row, "model_version"),
        model_quantization=_opt_str(row, "model_quantization"),
        model_parameters=_opt_str(row, "model_parameters"),
        execution_duration_ms=_opt_int(row, "execution_duration_ms"),
        execution_gpu_device=_opt_str(row, "execution_gpu_device"),
        execution_vram_peak_mb=_opt_float(row, "execution_vram_peak_mb"),
        chain_hash=str(row["chain_hash"]),
    )
