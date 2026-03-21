"""Provenance hash chain tracking for ClipCannon.

Provides SHA-256 hashing, tamper-evident chain computation and
verification, and structured provenance record management.

Public API:
    - Hashing: sha256_file, sha256_bytes, sha256_string,
      sha256_table_content, verify_file_hash
    - Chain: compute_chain_hash, verify_chain, get_chain_from_genesis,
      ChainVerificationResult, GENESIS_HASH
    - Recording: record_provenance, get_provenance_records,
      get_provenance_record, get_provenance_timeline
    - Models: ProvenanceRecord, InputInfo, OutputInfo, ModelInfo,
      ExecutionInfo
"""

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

__all__ = [
    "GENESIS_HASH",
    "ChainVerificationResult",
    "ExecutionInfo",
    "InputInfo",
    "ModelInfo",
    "OutputInfo",
    "ProvenanceRecord",
    "compute_chain_hash",
    "get_chain_from_genesis",
    "get_provenance_record",
    "get_provenance_records",
    "get_provenance_timeline",
    "record_provenance",
    "sha256_bytes",
    "sha256_file",
    "sha256_string",
    "sha256_table_content",
    "verify_chain",
    "verify_file_hash",
]
