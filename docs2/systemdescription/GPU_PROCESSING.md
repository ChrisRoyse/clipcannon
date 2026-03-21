# GPU Processing & Python Workers

## Overview

All AI processing runs on local GPU hardware — zero cloud APIs. Three persistent daemon workers keep models loaded in VRAM to avoid expensive reloads. Additional per-call workers handle reranking, image extraction, clustering, and spreadsheet preprocessing.

## Worker Summary

| Worker | Model | VRAM | Mode | Concurrency |
|--------|-------|------|------|-------------|
| **OCR** | Marker-pdf v1.10.2 | 8-10 GB | Daemon | 2 (max 8) |
| **VLM** | Chandra v0.1.8 | ~18 GB | Daemon | 1 (serialized) |
| **Embedding** | nomic-embed-text-v1.5 | 2-3 GB | Daemon | Unlimited |
| **Reranker** | cross-encoder/ms-marco-MiniLM-L-12-v2 | ~1 GB (GPU or CPU fallback) | Per-call | Unlimited |
| **Image Extract** | PyMuPDF + PIL | CPU | Per-call | Unlimited |
| **Clustering** | scikit-learn | CPU | Per-call | Unlimited |
| **Spreadsheet Prep** | openpyxl + xlrd | CPU | Per-call | Unlimited |

## GPU Device Detection

```python
# gpu_utils.py: startup_gpu()
1. Read TORCH_DEVICE env var (default: "auto")
2. Resolve: auto → detect_best_device()
3. Priority: CUDA > MPS (Apple Silicon) > CPU
4. Set os.environ["TORCH_DEVICE"] = resolved device
5. Configure CUDA memory pool:
   PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True,
     garbage_collection_threshold:0.8,max_split_size_mb:512"
6. Validate device available, log VRAM info
```

## Daemon Protocol

All three GPU workers use the same protocol: **JSON lines on stdin/stdout**.

```
TypeScript                              Python Daemon
    │                                       │
    ├── spawn(python worker.py --daemon) ──▶│
    │                                       │
    │◀── {"status":"ready","device":"cuda:0",│
    │     "load_time_ms":5000}              │
    │                                       │
    ├── {"action":"process","file":...} ───▶│
    │                                       │
    │◀── {"success":true,"text":"..."}      │
    │                                       │
    ├── {"action":"shutdown"} ──────────────▶│
    │                                       ✕
```

**Concurrency**: TypeScript uses a mutex lock per daemon — requests are serialized.

## OCR Worker (Marker-pdf)

**File**: `python/ocr_worker_local.py`

**Input**: File path + options (max_pages, mode, page_range)
**Output**: Markdown text + JSON blocks + page offsets + images + metadata

**Capabilities**: PDF, DOCX, PPTX, XLSX, XLS, HTML, EPUB
**Text passthrough**: TXT, CSV, MD files skip OCR — text extracted directly
**Spreadsheet optimization**: XLSX/XLS files are processed for text extraction only — image extraction and VLM analysis are skipped (tabular data, not visual documents). Requires `openpyxl` and `xlrd` Python packages.
**GPU**: Full CUDA support, reads `TORCH_DEVICE`

**Error Classes**:
- `OCRFileError` — file not found, invalid format → permanent failure
- `OCRModelError` — model/inference failure → transient (always transient, env-level not per-document)
- `OCRGPUError` — CUDA OOM → transient (retry)

## VLM Worker (Chandra)

**File**: `python/vlm_worker_local.py`

**Input**: Image path + method (hf/vllm) + max_tokens
**Output**: Structured JSON analysis

```json
{
  "imageType": "photograph|diagram|chart|table|form|...",
  "primarySubject": "...",
  "paragraph1": "4-5 sentences",
  "paragraph2": "6-8 sentences",
  "paragraph3": "4-5 sentences",
  "extractedText": ["text found in image"],
  "dates": [], "names": [], "numbers": [],
  "confidence": 0.85
}
```

**Methods**: `hf` (HuggingFace transformers) or `vllm` (vLLM backend)
**BF16**: Auto-detects CUDA BF16 support for optimal inference

## Embedding Worker (nomic-embed-text-v1.5)

**File**: `python/embedding_worker.py`

**Input**: Text chunks array + batch_size
**Output**: Array of 768-dim float32 vectors

**Task Prefixes** (required by model):
- Documents: `"search_document: " + chunk_text`
- Queries: `"search_query: " + query_text`

**Batch Processing**:
- Auto-tuned batch size by VRAM (512 for 24GB, 256 for 16GB, etc.)
- OOM recovery: halves batch size, retries
- Sub-batch vector storage: flushes every 50 embeddings to SQLite

## Reranker Worker (cross-encoder)

**File**: `python/reranker_worker.py`

**Model**: `cross-encoder/ms-marco-MiniLM-L-12-v2` (~129 MB)
**Input**: Query + candidate passages array
**Output**: Re-scored passages with cross-encoder relevance scores
**Default**: Enabled (`rerank=true` in search tools since v1.2.62)

**CPU Fallback**: If GPU is unavailable, the reranker gracefully falls back to CPU:
1. Attempt `startup_gpu()` for CUDA device
2. On `GPUNotAvailableError`, set `TORCH_DEVICE=cpu`
3. Load model on CPU (~50ms latency for 20 passages)

**Configuration**: `RERANKER_MODEL_PATH` env var overrides model path.

**Error Handling**: `localRerank()` returns structured error objects (not null) with `error_type` and `message`, surfaced through search tools as `reranker_error_message`.

## Spreadsheet Preparation Worker

**File**: `python/spreadsheet_prepare.py`

**Purpose**: Pre-process spreadsheet files for PDF conversion in the document viewer. Without preprocessing, LibreOffice defaults to A4 portrait which cuts off wide columns.

**Input**: XLSX/XLS file path + output directory
**Output**: Preprocessed copy with landscape orientation and fit-to-width page layout on all sheets

**Dependencies**: `openpyxl` (XLSX), `xlrd` (XLS)

**Used by**: Document viewer API (`/api/viewer/prepare/`) when converting spreadsheet files to PDF via LibreOffice.

## Model Cache Locations

```
Docker container:
  /opt/models/chandra/                    # Chandra VLM (~18 GB)
  /opt/models/nomic-embed-text-v1.5/     # Nomic embedding (~523 MB)
  /opt/models/surya/                      # Surya/Marker OCR (~3.3 GB)
  /opt/models/ms-marco-MiniLM-L-12-v2/  # Reranker cross-encoder (~129 MB)

Host cache:
  ~/.cache/datalab/models/marker_pdfs_v1/
  ~/.cache/datalab/models/surya_models/
```

All models pre-cached in Docker image — zero network downloads at runtime.
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` enforce this.

## GPU Memory Management

**Loading**: Models loaded on first request, cached in Python globals
**VRAM Monitoring**: `get_vram_usage()` returns allocated/reserved/free/total
**OOM Recovery**: `torch.cuda.empty_cache()` + halve batch size
**Cleanup**: After batch processing, all daemons killed to free VRAM

```python
# After processing batch:
killAllEmbeddingWorkers()  # Kill embedding daemon
killAllVLMWorkers()         # Kill VLM daemon
# Marker daemon also killed
# Small delay for CUDA driver to reclaim VRAM
```

## Performance Characteristics

| Task | Input | Time | VRAM |
|------|-------|------|------|
| OCR (10-page PDF) | PDF file | 15-30s | 8-10 GB |
| OCR (160-page PDF) | PDF file | ~287s | 8-10 GB |
| VLM image analysis | Single image | 3-5s | ~18 GB |
| Embed 100 chunks | Text array | 200-400ms | 2-3 GB |
| Rerank 20 passages | Query + passages | ~50ms (GPU), ~50ms (CPU) | ~1 GB / 0 |
| Model cold start (Marker) | — | 5-15s | — |
| Model cold start (Chandra) | — | 30-45s | — |
| Model cold start (nomic) | — | 3-8s | — |

## Python Files

```
python/
├── __init__.py                 # Package exports
├── gpu_utils.py               # GPU detection, VRAM monitoring, startup
├── ocr_worker_local.py        # Marker-pdf OCR daemon
├── vlm_worker_local.py        # Chandra VLM daemon
├── embedding_worker.py        # nomic-embed-text-v1.5 daemon
├── reranker_worker.py         # Cross-encoder reranking (per-call, GPU with CPU fallback)
├── image_extractor.py         # PDF image extraction (PyMuPDF)
├── image_optimizer.py         # Image relevance filtering + resizing
├── docx_image_extractor.py    # DOCX image extraction
├── clustering_worker.py       # HDBSCAN/agglomerative/k-means
├── spreadsheet_prepare.py     # Spreadsheet page layout preprocessing for viewer
├── pyproject.toml             # Python config (ruff, mypy)
└── requirements.txt           # Dependencies
```

## Key Dependencies

```
# GPU/ML
torch>=2.6.0 (CUDA 13.2)
sentence-transformers>=2.7.0
transformers>=4.57.1

# OCR & VLM (installed separately in Dockerfile)
marker-pdf
chandra-ocr

# Spreadsheet Support
openpyxl    # XLSX reading
xlrd        # XLS reading

# Image Processing
PyMuPDF>=1.24.0
Pillow>=10.3.0

# Clustering
scikit-learn>=1.3.0
scipy>=1.12.0
```
