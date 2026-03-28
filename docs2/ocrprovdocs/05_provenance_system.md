# Provenance System

Current state of the ClipCannon provenance subsystem as implemented in
`src/clipcannon/provenance/`. This system produces a tamper-evident hash
chain that records every pipeline operation performed on a project, linking
each step to its predecessor so that any modification to historical records
is detectable.

**Source files covered:**

- `src/clipcannon/provenance/hasher.py` -- SHA-256 hashing utilities
- `src/clipcannon/provenance/chain.py` -- chain hash computation and verification
- `src/clipcannon/provenance/recorder.py` -- record creation, retrieval, and timeline queries

---

## 1. SHA-256 Hasher

`src/clipcannon/provenance/hasher.py` provides four hashing functions and
one verification function. All return lowercase 64-character hex digest
strings. All raise `ProvenanceError` on failure.

### `sha256_file(path) -> str`

Streams the file in 8 KB chunks (`_CHUNK_SIZE = 8192`) to handle files
larger than available memory (10 GB+ source videos). Validates that the path
exists and is a regular file before reading.

### `sha256_bytes(data) -> str`

Computes SHA-256 of raw `bytes` in a single call.

### `sha256_string(data) -> str`

Encodes the string as UTF-8 and computes SHA-256.

### `sha256_table_content(conn, table_name, project_id) -> str`

Produces a repeatable hash of all rows in a table for a given project:

1. Validates `table_name` contains only alphanumeric characters and
   underscores (prevents SQL injection).
2. Queries all rows: `SELECT * FROM {table_name} WHERE project_id = ? ORDER BY rowid`.
3. If rows are dictionaries (dict row factory), sorts them by their
   JSON-serialized form (`json.dumps(r, sort_keys=True, default=str)`).
4. Serializes the sorted list to JSON with `sort_keys=True, default=str`.
5. Passes the serialized string to `sha256_string`.

The deterministic sort and serialization ensure the same data produces the
same hash regardless of insertion order.

### `verify_file_hash(path, expected_hash) -> bool`

Computes `sha256_file(path)` and compares it (case-insensitive) to
`expected_hash`. Returns `True` on match, `False` on mismatch. Logs a
warning on mismatch.

---

## 2. Chain Hash Computation

### 2.1 Formula

The chain hash links a provenance record to its parent via this preimage:

```
SHA256("{parent_hash}|{input_sha256}|{output_sha256}|{operation}|{model_name}|{model_version}|{json.dumps(model_params, sort_keys=True)}")
```

The preimage is a pipe-delimited string of seven fields. The
`model_params` dictionary is serialized with `json.dumps(sort_keys=True)`
for determinism. The preimage is UTF-8 encoded before hashing.

**Function signature:**

```python
def compute_chain_hash(
    parent_hash: str,
    input_sha256: str,
    output_sha256: str,
    operation: str,
    model_name: str,
    model_version: str,
    model_params: dict[str, str | int | float | bool | None],
) -> str
```

### 2.2 Genesis Hash

The sentinel constant `GENESIS_HASH = "GENESIS"` is used as
`parent_hash` for the first record in a project's chain. When a record has
`parent_record_id = None`, the chain hash computation uses the literal
string `"GENESIS"` as the parent hash value.

---

## 3. Provenance Record Schema

Each provenance record has 22 columns in the `provenance` table. The full
column listing:

| # | Column | Type | Required | Description |
|---|--------|------|----------|-------------|
| 1 | `record_id` | TEXT | PK | Auto-generated ID in `prov_NNN` format |
| 2 | `project_id` | TEXT | NOT NULL, FK | Owning project |
| 3 | `timestamp_utc` | TEXT | NOT NULL | ISO-8601 UTC timestamp, generated at insert time |
| 4 | `operation` | TEXT | NOT NULL | Pipeline operation name (e.g., "transcription") |
| 5 | `stage` | TEXT | NOT NULL | Pipeline stage name (e.g., "whisperx") |
| 6 | `description` | TEXT | | Human-readable description of the operation |
| 7 | `input_file_path` | TEXT | | Path to the input file |
| 8 | `input_sha256` | TEXT | | SHA-256 hash of the input data |
| 9 | `input_size_bytes` | INTEGER | | Input size in bytes |
| 10 | `parent_record_id` | TEXT | FK | ID of the parent provenance record, or NULL for genesis |
| 11 | `output_file_path` | TEXT | | Path to the output file |
| 12 | `output_sha256` | TEXT | | SHA-256 hash of the output data |
| 13 | `output_size_bytes` | INTEGER | | Output size in bytes |
| 14 | `output_record_count` | INTEGER | | Number of database records produced |
| 15 | `model_name` | TEXT | | ML model name (e.g., "whisperx", "siglip") |
| 16 | `model_version` | TEXT | | Model version string |
| 17 | `model_quantization` | TEXT | | Quantization level (e.g., "fp16", "int8") |
| 18 | `model_parameters` | TEXT | | JSON-encoded model parameters dictionary |
| 19 | `execution_duration_ms` | INTEGER | | Execution time in milliseconds |
| 20 | `execution_gpu_device` | TEXT | | GPU device identifier (e.g., "cuda:0") |
| 21 | `execution_vram_peak_mb` | REAL | | Peak VRAM usage in megabytes |
| 22 | `chain_hash` | TEXT | NOT NULL | Tamper-evident hash linking to parent |

---

## 4. Provenance Recorder

`src/clipcannon/provenance/recorder.py` handles record creation and
retrieval. It defines four Pydantic models for structured input and one
Pydantic model for the complete record.

### 4.1 Input Models

**`InputInfo`** -- describes the input to a pipeline operation:
- `file_path: str | None` -- path to the input file
- `sha256: str` -- SHA-256 hash (defaults to empty string)
- `size_bytes: int | None` -- input size in bytes

**`OutputInfo`** -- describes the output:
- `file_path: str | None` -- path to the output file
- `sha256: str` -- SHA-256 hash (defaults to empty string)
- `size_bytes: int | None` -- output size in bytes
- `record_count: int | None` -- number of records produced

**`ModelInfo`** -- describes the ML model used:
- `name: str` -- model name (defaults to empty string)
- `version: str` -- model version (defaults to empty string)
- `quantization: str | None` -- quantization level
- `parameters: dict` -- model-specific parameters (defaults to empty dict)

**`ExecutionInfo`** -- describes the execution environment:
- `duration_ms: int | None` -- execution time in milliseconds
- `gpu_device: str | None` -- GPU device (e.g., "cuda:0")
- `vram_peak_mb: float | None` -- peak VRAM in megabytes

### 4.2 Record ID Generation

Record IDs follow the format `prov_NNN` where `NNN` is a zero-padded
three-digit sequence number. The sequence is computed by counting existing
provenance records for the project and adding 1:

```python
count = count_rows(conn, "provenance", "project_id = ?", (project_id,))
sequence = count + 1
record_id = f"prov_{sequence:03d}"
```

The first record in a project gets `prov_001`, the second `prov_002`, and
so on.

### 4.3 Recording Flow

`record_provenance(db_path, project_id, operation, stage, input_info,
output_info, model_info, execution_info, parent_record_id, description)`
performs these steps:

1. Opens a database connection with `enable_vec=False, dict_rows=True`.
2. Generates the next `record_id` via `_get_next_sequence`.
3. Looks up the parent's `chain_hash`:
   - If `parent_record_id` is `None`, uses `GENESIS_HASH` ("GENESIS").
   - Otherwise, queries the `provenance` table for the parent's
     `chain_hash`. Raises `ProvenanceError` if the parent record does not
     exist.
4. Extracts model fields from `model_info` (or uses empty defaults if
   `model_info` is `None`).
5. Calls `compute_chain_hash(parent_hash, input_sha256, output_sha256,
   operation, model_name, model_version, model_params)`.
6. Generates `timestamp_utc` as `datetime.now(UTC).isoformat()`.
7. Inserts a row into the `provenance` table with all 22 columns.
8. Commits and closes the connection.
9. Returns the generated `record_id`.

### 4.4 Chain Linking

Each record references its parent through two mechanisms:

- **`parent_record_id`** (foreign key) -- the explicit record-to-record
  link stored in the database.
- **`chain_hash`** -- the cryptographic link computed from the parent's
  chain hash and the current record's content fields. This makes the link
  tamper-evident: changing any field in any ancestor record invalidates all
  downstream chain hashes.

---

## 5. Chain Verification

`verify_chain(project_id, db_path)` walks the entire chain and
checks every record.

### 5.1 Algorithm

1. Query all provenance records for the project, ordered by
   `timestamp_utc ASC, record_id ASC`.
2. If no records exist, return `verified=True, total_records=0`.
3. Build a `record_hash_map: dict[str, str]` mapping `record_id` to
   verified `chain_hash`.
4. For each record in order:
   a. Determine the parent chain hash:
      - If `parent_record_id` is `None`, use `GENESIS_HASH`.
      - Otherwise, look up `parent_record_id` in `record_hash_map`. If
        not found, return a failure result (parent not yet processed or
        missing).
   b. Deserialize `model_parameters` from JSON (empty dict on parse
      failure).
   c. Recompute the chain hash using `compute_chain_hash` with:
      - `parent_hash` = resolved parent chain hash
      - `input_sha256` = `record.input_sha256 or ""`
      - `output_sha256` = `record.output_sha256 or ""`
      - `operation` = `record.operation`
      - `model_name` = `record.model_name or ""`
      - `model_version` = `record.model_version or ""`
      - `model_params` = deserialized parameters
   d. Compare recomputed hash to stored `chain_hash`. If they differ,
      return a failure result identifying the broken record.
   e. Store the verified chain hash in `record_hash_map` for child
      records to reference.
5. If all records pass, return `verified=True, total_records=N`.

### 5.2 Return Type

`ChainVerificationResult` (Pydantic model):

| Field | Type | Description |
|-------|------|-------------|
| `verified` | `bool` | `True` if the entire chain is valid |
| `total_records` | `int` | Number of records examined |
| `broken_at` | `str \| None` | Record ID where the chain broke |
| `issue` | `str \| None` | Human-readable description of the problem |

---

## 6. Chain Traversal

`get_chain_from_genesis(project_id, record_id, db_path)` walks
backward from a target record to the genesis record via `parent_record_id`
links, then reverses the list to return genesis-first ordering.

### 6.1 Algorithm

1. Start with `current_id = record_id`.
2. Maintain a `visited: set[str]` to detect circular references.
3. While `current_id` is not `None`:
   a. If `current_id` is in `visited`, raise `ProvenanceError` (circular
      reference detected).
   b. Add `current_id` to `visited`.
   c. Query the record: `SELECT * FROM provenance WHERE project_id = ?
      AND record_id = ?`.
   d. If not found and this is the target record, raise `ProvenanceError`
      (record not found). If not found and this is a parent, raise
      `ProvenanceError` (broken chain).
   e. Append the record to `chain`.
   f. Set `current_id = record.parent_record_id`.
4. Reverse `chain` so genesis is first.
5. Return the ordered list.

### 6.2 Return Type

`list[ProvenanceChainRecord]` -- ordered from genesis (index 0) to the
target record (last index).

`ProvenanceChainRecord` is a Pydantic model with the same 22 fields as the
database row, used during chain traversal and verification.

---

## 7. Tamper Detection Mechanism

The provenance system detects tampering through the chain hash dependency
graph:

```
Record prov_001 (genesis):
  chain_hash = SHA256("GENESIS|{input}|{output}|{op}|{model}|{ver}|{params}")

Record prov_002:
  chain_hash = SHA256("{prov_001.chain_hash}|{input}|{output}|{op}|{model}|{ver}|{params}")

Record prov_003:
  chain_hash = SHA256("{prov_002.chain_hash}|{input}|{output}|{op}|{model}|{ver}|{params}")
```

**What triggers detection:**

- Modifying any content field (input hash, output hash, operation, model
  name, model version, or model parameters) in any record causes that
  record's recomputed chain hash to differ from its stored chain hash.
- Modifying a record's chain hash directly causes all child records'
  recomputed hashes to differ, because they include the parent hash in
  their preimage.
- Deleting a record breaks the parent lookup for its children.
- Inserting a record with a fabricated chain hash fails verification
  because the hash will not match the recomputation from its stated parent.

**What is not covered:**

- The chain does not use digital signatures. An attacker with write access
  to the database could recompute the entire chain from genesis with
  modified data, producing a valid but falsified chain. The system detects
  accidental corruption and unauthorized partial edits, not a full chain
  rewrite by a privileged actor.

---

## 8. Record Retrieval Functions

### `get_provenance_records(db_path, project_id, operation=None, stage=None)`

Retrieves provenance records with optional filtering by `operation` and/or
`stage`. Returns a list of `ProvenanceRecord` instances ordered by
`timestamp_utc ASC`. Builds the WHERE clause dynamically from the provided
filters.

### `get_provenance_record(db_path, project_id, record_id)`

Retrieves a single provenance record by its `record_id`. Returns a
`ProvenanceRecord` or `None` if not found.

### `get_provenance_timeline(db_path, project_id)`

Returns the full chronological provenance timeline for a project. This is a
convenience wrapper that calls `get_provenance_records` with no operation
or stage filters.
