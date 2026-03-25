# ClipCannon Configuration Reference

## Config File Locations

| File | Purpose |
|------|---------|
| `config/default_config.json` | Bundled defaults shipped with the package. Read-only. Located at `<package_root>/config/default_config.json`. |
| `~/.clipcannon/config.json` | User overrides. Created when `config.save()` is called. Deep-merged on top of defaults. |

The config system loads defaults first, then deep-merges the user config on top. Missing keys in the user config fall back to defaults. The resolved path is computed as `Path(__file__).parent.parent.parent / "config" / "default_config.json"` relative to `config.py`.

## Configuration Loading

The `ClipCannonConfig.load()` classmethod:

1. Loads `config/default_config.json` (raises `ConfigError` if missing or invalid JSON).
2. If `~/.clipcannon/config.json` exists, loads and deep-merges it on top of defaults.
3. If the user config contains invalid JSON, logs a warning and uses defaults only.
4. Validates the merged result against the `FullConfig` Pydantic model.
5. Returns a `ClipCannonConfig` instance with `.data` (raw dict), `.validated` (Pydantic model), and `.config_path`.

## Pydantic Validation Models

### FullConfig

The top-level model. All sub-models use `Field(default_factory=...)` so they can be omitted from the config file.

```python
class FullConfig(BaseModel):
    version: str = "1.0"
    directories: DirectoriesConfig
    processing: ProcessingConfig
    rendering: RenderingConfig
    publishing: PublishingConfig
    gpu: GPUConfig
    audio: AudioConfig          # Phase 2
```

### DirectoriesConfig

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `directories.projects` | `str` | `"~/.clipcannon/projects"` | Base directory for project data. Each project gets a subdirectory. |
| `directories.models` | `str` | `"~/.clipcannon/models"` | Directory for downloaded ML model weights. |
| `directories.temp` | `str` | `"~/.clipcannon/tmp"` | Directory for temporary processing files. |

All path values support `~` expansion. Use `config.resolve_path("directories.projects")` to get an absolute `Path`.

### ProcessingConfig

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `processing.frame_extraction_fps` | `int` | `2` | Frames per second to extract from source video. At 2 FPS, one frame is extracted every 500ms. |
| `processing.whisper_model` | `str` | `"large-v3"` | Whisper model size for transcription. Options: tiny, base, small, medium, large-v2, large-v3. |
| `processing.whisper_compute_type` | `str` | `"int8"` | Quantization for Whisper model. Options: int8, fp16, fp32. |
| `processing.batch_size_visual` | `int` | `64` | Batch size for visual model inference (SigLIP embeddings). |
| `processing.scene_change_threshold` | `float` | `0.75` | Cosine similarity threshold for scene boundary detection. Lower values detect more scene changes. |
| `processing.highlight_count_default` | `int` | `20` | Default number of highlights to score and return. |
| `processing.min_clip_duration_ms` | `int` | `5000` | Minimum clip duration in milliseconds (5 seconds). |
| `processing.max_clip_duration_ms` | `int` | `600000` | Maximum clip duration in milliseconds (10 minutes). |

### RenderingConfig

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `rendering.default_profile` | `str` | `"youtube_standard"` | Default render profile name. |
| `rendering.use_nvenc` | `bool` | `true` | Use NVIDIA hardware encoder (NVENC) for rendering. |
| `rendering.nvenc_preset` | `str` | `"p4"` | NVENC encoder preset. p1 (fastest) to p7 (best quality). |
| `rendering.max_parallel_renders` | `int` | `3` | Maximum concurrent render jobs in batch mode. |
| `rendering.caption_default_style` | `str` | `"bold_centered"` | Default caption style for rendered clips. |
| `rendering.thumbnail_format` | `str` | `"jpg"` | Output format for thumbnails. |
| `rendering.thumbnail_quality` | `int` | `95` | JPEG quality for thumbnails (1-100). |

### AudioConfig (Phase 2)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `audio.music_model` | `str` | `"ace-step"` | AI music generation model. Currently only ACE-Step v1.5 supported. |
| `audio.music_guidance_scale` | `float` | `3.5` | Guidance scale for music diffusion model. Higher = more adherent to prompt. |
| `audio.music_default_volume_db` | `float` | `-12` | Default volume level for generated music in dB. |
| `audio.duck_under_speech` | `bool` | `true` | Automatically reduce music volume during speech regions. |
| `audio.sfx_on_transitions` | `bool` | `true` | Auto-insert sound effects on segment transitions. |
| `audio.normalize_output` | `bool` | `true` | Peak-normalize final audio mix to -1 dBFS. |

### PublishingConfig

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `publishing.require_approval` | `bool` | `true` | Whether to require manual approval before publishing. |
| `publishing.max_daily_posts_per_platform` | `int` | `5` | Maximum posts per day per platform. |

### GPUConfig

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `gpu.device` | `str` | `"cuda:0"` | CUDA device identifier. Use `"cpu"` for CPU-only mode. |
| `gpu.max_vram_usage_gb` | `int` | `24` | Maximum VRAM to use in gigabytes. |
| `gpu.concurrent_models` | `bool` | `true` | Allow multiple models to be loaded simultaneously. Automatically disabled on GPUs with <=16 GB VRAM. |

## Default Config File

The complete `config/default_config.json`:

```json
{
  "version": "1.0",
  "directories": {
    "projects": "~/.clipcannon/projects",
    "models": "~/.clipcannon/models",
    "temp": "~/.clipcannon/tmp"
  },
  "processing": {
    "frame_extraction_fps": 2,
    "whisper_model": "large-v3",
    "whisper_compute_type": "int8",
    "batch_size_visual": 64,
    "scene_change_threshold": 0.75,
    "highlight_count_default": 20,
    "min_clip_duration_ms": 5000,
    "max_clip_duration_ms": 600000
  },
  "rendering": {
    "default_profile": "youtube_standard",
    "use_nvenc": true,
    "nvenc_preset": "p4",
    "max_parallel_renders": 3,
    "caption_default_style": "bold_centered",
    "thumbnail_format": "jpg",
    "thumbnail_quality": 95
  },
  "audio": {
    "music_model": "ace-step",
    "music_guidance_scale": 3.5,
    "music_default_volume_db": -12,
    "duck_under_speech": true,
    "sfx_on_transitions": true,
    "normalize_output": true
  },
  "publishing": {
    "require_approval": true,
    "max_daily_posts_per_platform": 5
  },
  "gpu": {
    "device": "cuda:0",
    "max_vram_usage_gb": 24,
    "concurrent_models": true
  }
}
```

## Dot-Notation Access

The `ClipCannonConfig` class supports dot-notation for getting and setting nested values:

```python
config = ClipCannonConfig.load()

# Read
model = config.get("processing.whisper_model")       # "large-v3"
fps = config.get("processing.frame_extraction_fps")   # 2
device = config.get("gpu.device")                     # "cuda:0"
duck = config.get("audio.duck_under_speech")          # True

# Write (re-validates against Pydantic model, raises ConfigError on invalid values)
config.set("gpu.max_vram_usage_gb", 16)
config.save()  # Persists to ~/.clipcannon/config.json

# Resolve paths (expands ~ to home directory)
projects_path = config.resolve_path("directories.projects")  # Path("/home/user/.clipcannon/projects")
```

## Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `CLIPCANNON_DEV_MODE` | Docker Compose | When `"true"`, enables dev mode (auto-auth in dashboard, 100 initial credits) |
| `CLIPCANNON_JWT_SECRET` | `dashboard/auth.py` | Secret key for JWT signing. Defaults to `"clipcannon-dev-secret-not-for-production"` |
| `HF_TOKEN` | Docker Compose | Hugging Face API token for downloading gated models |
| `STRIPE_PUBLISHABLE_KEY` | Docker Compose | Stripe publishable key for client-side credit purchases |
| `STRIPE_WEBHOOK_SECRET` | `license_server/stripe_webhooks.py` | Stripe webhook signature verification secret. Without it, unsigned payloads are accepted (dev mode) |
| `CLIPCANNON_D1_API_URL` | `license_server/d1_sync.py` | Cloudflare D1 API URL for remote sync (not currently active) |
| `CLIPCANNON_D1_API_TOKEN` | `license_server/d1_sync.py` | Cloudflare D1 API token for remote sync (not currently active) |
| `VIDEO_DIR` | Docker Compose | Host directory to mount as `/videos:ro` in the container. Defaults to `./videos` |

## Docker Compose Service Definitions

File: `config/docker-compose.yml`

### clipcannon service

```yaml
services:
  clipcannon:
    build:
      context: ..
      dockerfile: Dockerfile
    container_name: clipcannon
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility,video
      - CLIPCANNON_DEV_MODE=true
      - HF_TOKEN=${HF_TOKEN:-}
      - STRIPE_PUBLISHABLE_KEY=${STRIPE_PUBLISHABLE_KEY:-}
    ports:
      - "3100:3100"   # License server
      - "3200:3200"   # Dashboard
    volumes:
      - clipcannon-data:/root/.clipcannon
      - ${VIDEO_DIR:-./videos}:/videos:ro
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3200/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

## License Server Database

The license server stores its data in `~/.clipcannon/license.db`, separate from project databases. See [09_billing_system.md](09_billing_system.md) for full schema.

## SQLite Connection Pragmas

Every database connection applies these pragmas:

| Pragma | Value | Purpose |
|--------|-------|---------|
| `journal_mode` | `WAL` | Write-Ahead Logging for concurrent read/write access |
| `synchronous` | `NORMAL` | Balance between safety and performance |
| `cache_size` | `-64000` | 64 MB page cache (negative value = kilobytes) |
| `foreign_keys` | `ON` | Enforce foreign key constraints |
| `temp_store` | `MEMORY` | Store temporary tables and indexes in memory |
