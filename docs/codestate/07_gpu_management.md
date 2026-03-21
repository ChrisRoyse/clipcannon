# GPU Management -- Current Code State

This document describes the GPU management system as implemented in `src/clipcannon/gpu/`. Every statement below is derived from the source code at the time of writing.

## Precision Auto-Detection

### File: `gpu/precision.py`

The precision system maps GPU hardware generations (identified by CUDA compute capability) to optimal quantization formats.

### PRECISION_MAP

```python
PRECISION_MAP: dict[str, str] = {
    "12.0": "nvfp4",   # Blackwell
    "8.9":  "int8",    # Ada Lovelace
    "8.6":  "int8",    # Ampere
    "7.5":  "fp16",    # Turing
}
```

Default for CPU (no GPU detected): `"fp32"` (`DEFAULT_CPU_PRECISION`).

### auto_detect_precision()

`auto_detect_precision(device_index: int = 0) -> str`

Detection logic, executed in order:

1. Calls `get_compute_capability(device_index)` to get the GPU's compute capability string (e.g., `"8.9"`).
2. If no GPU is detected (returns `None`), returns `"fp32"` with a warning log.
3. Looks up the compute capability in `PRECISION_MAP` for an exact match.
4. If no exact match, attempts a prefix-based match: iterates `PRECISION_MAP` entries (sorted descending) looking for any entry whose key starts with the same major version (e.g., `"8."` for CC 8.7).
5. If still no match, applies a numeric fallback:
   - CC >= 8.0 -> `"int8"`
   - CC >= 7.0 -> `"fp16"`
   - CC < 7.0 -> `"fp32"`
6. Logs the selected precision and returns it.

### get_compute_capability()

`get_compute_capability(device_index: int = 0) -> str | None`

1. Checks `_is_cuda_available()` (which itself checks `_is_torch_available()` first).
2. If CUDA is available, calls `torch.cuda.get_device_capability(device_index)` and returns `"{major}.{minor}"`.
3. Returns `None` if no CUDA GPU is available or if the query fails.

### Helper Functions

- `_is_torch_available() -> bool`: Tries `import torch`, returns True/False.
- `_is_cuda_available() -> bool`: Calls `_is_torch_available()` then `torch.cuda.is_available()`.

## ModelManager Class

### File: `gpu/manager.py`

The `ModelManager` manages ML model loading, unloading, and VRAM lifecycle. It determines whether models run concurrently (kept in memory) or sequentially (one at a time).

### Initialization

`ModelManager.__init__(self, device: str = "cuda:0", max_vram_bytes: int | None = None)`

Initialization sequence:

1. Sets defaults: `cpu_only=False`, `precision="fp32"`, `concurrent=False`, `_vram_total=0`.
2. If `device == "cpu"`, sets `cpu_only=True` and returns immediately.
3. Attempts `import torch`. If PyTorch is not installed, sets `cpu_only=True`, `device="cpu"`, and returns.
4. Checks `torch.cuda.is_available()`. If False, sets `cpu_only=True`, `device="cpu"`, and returns.
5. Parses the device index from the device string (e.g., `"cuda:0"` -> `0`) via `_parse_device_index()`.
6. Calls `auto_detect_precision(device_index)` to set `self.precision`.
7. Queries `torch.cuda.get_device_properties(device_index)` to get `total_memory`.
   - If `max_vram_bytes` is provided (for testing), uses that value instead.
   - Stores as `self._vram_total`.
8. Sets `self.concurrent = self._vram_total > CONCURRENT_VRAM_THRESHOLD_BYTES`.
9. If GPU property query fails, falls back to CPU mode.

### VRAM Threshold for Concurrent Mode

```python
CONCURRENT_VRAM_THRESHOLD_BYTES = 16 * 1024**3  # 16 GB
```

- **> 16 GB VRAM**: `concurrent = True`. Models are kept loaded simultaneously. LRU eviction frees VRAM only when a new model cannot fit.
- **<= 16 GB VRAM**: `concurrent = False`. Before loading a new model, all currently loaded models are unloaded first (sequential mode).

### Model Load/Unload Lifecycle

#### load()

`load(self, model_name: str, loader_fn: object | None = None, vram_estimate_bytes: int = 0) -> object`

1. If `model_name` is already in `_loaded_models`, moves it to the end of the LRU queue (most recently used) and returns the cached model object.
2. If `loader_fn` is `None` and the model is not loaded, raises `GPUError`.
3. **Sequential mode** (`concurrent=False`): Unloads all currently loaded models before proceeding.
4. **Concurrent mode** (`concurrent=True`): If `vram_estimate_bytes > 0` and available VRAM is insufficient, calls `_evict_lru()` to free space.
5. Calls `loader_fn()` to create the model. If the call raises, wraps the exception in `GPUError`.
6. Creates a `_ModelEntry` and stores it in `_loaded_models` (an `OrderedDict` for LRU tracking).
7. Returns the loaded model object.

#### unload()

`unload(self, model_name: str) -> None`

1. Removes the model entry from `_loaded_models` via `.pop()`.
2. Deletes the `model` attribute and the entry object to release references.
3. If not in CPU-only mode, calls `torch.cuda.empty_cache()` to return freed GPU memory to the CUDA allocator.

#### unload_all()

Iterates all loaded model names and calls `unload()` on each.

### LRU Eviction Strategy

The `_loaded_models` field is an `OrderedDict[str, _ModelEntry]`. The LRU (Least Recently Used) eviction strategy works as follows:

1. **Access tracking**: When a model is accessed via `load()` and is already loaded, `OrderedDict.move_to_end()` moves it to the MRU (most recently used) position.
2. **Eviction**: `_evict_lru(needed_bytes)` iterates `_loaded_models` from the front (oldest/least recently used). It accumulates `vram_estimate_bytes` from each entry until the accumulated total meets or exceeds `needed_bytes`, then unloads those models.
3. **Eviction triggers**: Only in concurrent mode. Called when `_get_vram_free() < vram_estimate_bytes` for a new model being loaded.
4. **Sequential mode override**: In sequential mode, eviction is not needed because all models are unloaded before loading a new one.

### _ModelEntry Dataclass

Internal record for a loaded model:

| Field                 | Type      | Default             | Description                        |
|-----------------------|-----------|---------------------|------------------------------------|
| `name`                | `str`     | --                  | Model identifier                   |
| `model`               | `object`  | --                  | The loaded model object            |
| `vram_estimate_bytes` | `int`     | --                  | Estimated VRAM consumption         |
| `loaded_at`           | `float`   | `time.time()`       | Timestamp when the model was loaded|

## GPU Health Reporting

### GPUHealthReport Dataclass

Defined in `gpu/manager.py`:

| Field                | Type          | Default | Description                                  |
|----------------------|---------------|---------|----------------------------------------------|
| `device_name`        | `str`         | --      | GPU model name (e.g., "NVIDIA GeForce RTX 5090") |
| `compute_capability` | `str`         | --      | CUDA compute capability string               |
| `vram_total_bytes`   | `int`         | --      | Total VRAM in bytes                          |
| `vram_used_bytes`    | `int`         | --      | Currently allocated VRAM in bytes            |
| `vram_free_bytes`    | `int`         | --      | Available VRAM in bytes                      |
| `precision`          | `str`         | --      | Selected precision format                    |
| `concurrent_mode`    | `bool`        | --      | Whether models can run concurrently          |
| `loaded_models`      | `list[str]`   | --      | List of currently loaded model names         |
| `cpu_only`           | `bool`        | `False` | Whether running in CPU-only mode             |

### Computed Properties

| Property          | Type    | Computation                                      |
|-------------------|---------|--------------------------------------------------|
| `vram_total_gb`   | `float` | `vram_total_bytes / (1024**3)`                   |
| `vram_used_gb`    | `float` | `vram_used_bytes / (1024**3)`                    |
| `vram_free_gb`    | `float` | `vram_free_bytes / (1024**3)`                    |
| `vram_usage_pct`  | `float` | `(vram_used_bytes / vram_total_bytes) * 100.0`   |

### to_dict() Method

Serializes the health report to a dictionary with the following keys: `device_name`, `compute_capability`, `vram_total_gb`, `vram_used_gb`, `vram_free_gb`, `vram_usage_pct`, `precision`, `concurrent_mode`, `loaded_models`, `cpu_only`. Numeric values are rounded to 1-2 decimal places.

### get_health()

`ModelManager.get_health() -> GPUHealthReport`

- In CPU-only mode: Returns a report with `device_name="CPU"`, `compute_capability="N/A"`, all VRAM values at 0, `cpu_only=True`.
- In GPU mode: Queries `torch.cuda.get_device_properties()` for `device_name`, calls `get_compute_capability()` for CC, reads `_get_vram_used()` for current allocation, computes free VRAM from `_vram_total - vram_used`.

## CPU-Only Fallback Mode

The system falls back to CPU-only mode in any of the following scenarios:

1. `device="cpu"` is passed explicitly to `ModelManager.__init__()`.
2. PyTorch is not installed (`import torch` fails).
3. CUDA is not available (`torch.cuda.is_available()` returns False).
4. GPU property query fails (`torch.cuda.get_device_properties()` raises an exception).

In CPU-only mode:

- `ModelManager.cpu_only` is `True`.
- `ModelManager.device` is `"cpu"`.
- `ModelManager.precision` is `"fp32"`.
- `ModelManager.concurrent` is `False`.
- VRAM tracking returns 0 for all values.
- Models are still loaded and unloaded through the same `load()`/`unload()` API, but VRAM eviction logic is bypassed.
- `get_health()` returns a report with `device_name="CPU"` and `cpu_only=True`.

## GPU Validation Function

### validate_gpu_for_pipeline()

`validate_gpu_for_pipeline(device_index: int = 0) -> dict[str, str | int | float | bool]`

Defined in `gpu/precision.py`. Returns a dictionary with GPU validation results for pipeline readiness.

**Return dictionary fields**:

| Key                    | Type    | Description                                          |
|------------------------|---------|------------------------------------------------------|
| `torch_available`      | `bool`  | Whether PyTorch can be imported                      |
| `cuda_available`       | `bool`  | Whether CUDA is available                            |
| `cpu_only`             | `bool`  | True if running without GPU                          |
| `warning`              | `str`   | Warning message if degraded (optional)               |
| `device_name`          | `str`   | GPU name from device properties (GPU mode only)      |
| `compute_capability`   | `str`   | CC string like "8.9" (GPU mode only)                 |
| `vram_total_gb`        | `float` | Total VRAM in GB, rounded to 2 decimal places (GPU mode only) |
| `precision`            | `str`   | Auto-detected precision string (GPU mode only)       |
| `meets_minimum`        | `bool`  | True if VRAM >= 8.0 GB (GPU mode only)               |

**Validation logic**:

1. If PyTorch is not installed, returns `cpu_only=True` with a warning.
2. If CUDA is not available, returns `cpu_only=True` with a warning.
3. If CUDA is available, queries device properties and checks:
   - VRAM >= 8.0 GB is the minimum recommendation. Below this threshold, `meets_minimum=False` and a warning is included.
4. Raises `GPUError` if `torch.cuda.get_device_properties()` fails with an exception.

## VRAM Management Across Pipeline Stages

The pipeline stages themselves manage GPU memory independently from `ModelManager`. Most stages follow this pattern:

1. Import the model libraries (torch, transformers, etc.) inside the run function or a helper.
2. Load the model to the configured device (`config.get("gpu.device")`).
3. Run inference.
4. Delete the model reference (`del model`).
5. Call `torch.cuda.empty_cache()` if CUDA is available.

This per-stage cleanup pattern is implemented in: `source_separation`, `transcribe`, `visual_embed`, `emotion_embed`, `speaker_embed`, and `shot_type`.

The `ModelManager` class provides a centralized alternative for managing model lifecycle, but the current pipeline stage implementations load and unload models directly rather than going through `ModelManager`.
