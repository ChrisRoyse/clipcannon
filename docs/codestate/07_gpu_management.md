# GPU Management

Source: `src/clipcannon/gpu/`

## Precision Auto-Detection (`gpu/precision.py`)

### PRECISION_MAP

| Compute Capability | Precision | GPU Generation |
|---|---|---|
| 12.0 | nvfp4 | Blackwell |
| 8.9 | int8 | Ada Lovelace |
| 8.6 | int8 | Ampere |
| 7.5 | fp16 | Turing |
| CPU (no GPU) | fp32 | -- |

### auto_detect_precision(device_index=0) -> str

1. Query compute capability via `torch.cuda.get_device_capability()`
2. If no GPU: return `fp32` with warning
3. Exact match in `PRECISION_MAP` -> return
4. Prefix match (same major version, sorted descending) -> return
5. Numeric fallback: CC >= 8.0 -> `int8`, >= 7.0 -> `fp16`, else `fp32`

### validate_gpu_for_pipeline(device_index=0) -> dict

Returns: `torch_available`, `cuda_available`, `cpu_only`, `device_name`, `compute_capability`, `vram_total_gb`, `precision`, `meets_minimum` (VRAM >= 8 GB), `warning`.

## ModelManager (`gpu/manager.py`)

### Init: `ModelManager(device="cuda:0", max_vram_bytes=None)`

Falls back to CPU-only mode if: `device="cpu"`, PyTorch not installed, CUDA unavailable, or GPU property query fails. In CPU mode: `precision="fp32"`, `concurrent=False`, all VRAM values 0.

### Concurrent vs Sequential Mode

- **> 16 GB VRAM** (`CONCURRENT_VRAM_THRESHOLD_BYTES = 16 * 1024^3`): Concurrent mode. Models kept loaded; LRU eviction frees VRAM when needed.
- **<= 16 GB**: Sequential mode. All models unloaded before loading a new one.

### load(model_name, loader_fn=None, vram_estimate_bytes=0) -> object

1. Already loaded -> move to MRU end, return cached
2. No `loader_fn` and not loaded -> raise `GPUError`
3. Sequential: unload all first. Concurrent: evict LRU if insufficient VRAM
4. Call `loader_fn()`, store in `_loaded_models` (OrderedDict for LRU)

### unload(model_name)

Remove from `_loaded_models`, delete references, call `torch.cuda.empty_cache()`.

### GPUHealthReport

Fields: `device_name`, `compute_capability`, `vram_total_bytes`, `vram_used_bytes`, `vram_free_bytes`, `precision`, `concurrent_mode`, `loaded_models`, `cpu_only`. Properties: `vram_total_gb`, `vram_used_gb`, `vram_free_gb`, `vram_usage_pct`. Serializable via `to_dict()`.

## Per-Stage GPU Memory Pattern

Pipeline stages manage GPU memory independently from ModelManager. Each stage: import model libraries -> load to device -> run inference -> `del model` -> `torch.cuda.empty_cache()`. Used by: source_separation, transcribe, visual_embed, emotion_embed, speaker_embed, shot_type.

## Voice Agent GPU Lifecycle (`src/voiceagent/agent.py`, `src/voiceagent/gpu_manager.py`)

The voice agent manages GPU memory with an on-demand lifecycle that is independent of ClipCannon's ModelManager.

### VRAM Budget (RTX 5090 32GB target)

| Component | VRAM Estimate |
|-----------|---------------|
| Whisper Large v3 float32 | ~6 GB |
| Qwen3-14B FP8 (vLLM) | ~15 GB |
| faster-qwen3-tts 0.6B | ~4 GB |
| KV caches + activations | ~5 GB headroom |
| **Total** | **~30 GB** (leaves 2GB free) |

### Lifecycle States

| State | GPU Usage | Description |
|-------|-----------|-------------|
| DORMANT | Zero | Only wake word detector runs on CPU |
| LOADING | Growing | Models loaded sequentially with GC between each |
| ACTIVE | Full | All 3 models resident, conversation active |
| UNLOADING | Shrinking | Models released in reverse order (TTS -> LLM -> ASR), aggressive cleanup |

### GPU Worker Management (`gpu_manager.py`)

- `pause_gpu_workers()`: Sends SIGSTOP to other GPU-using processes (e.g., ClipCannon pipeline stages) to free VRAM for voice agent. Returns list of paused PIDs.
- `resume_gpu_workers(pids)`: Sends SIGCONT to restore paused processes.
- `force_free_gpu_memory()`: Aggressively clears CUDA cache and IPC.
- Memory fraction capped at 93% via `torch.cuda.set_per_process_memory_fraction(0.93)` to prevent OOM thrashing.
