# Phase 3: OCR Provenance Integration + Memory Retrieval

**Timeline**: Weeks 6-7
**Exit Criteria**: "What was I doing at 3pm?" returns accurate answer from captures with app context.
**Predecessor**: Phase 2 (companion capturing data to shared volume)

---

## What Gets Built

The Docker container reads captures from the shared volume, processes audio through Whisper, ingests everything into OCR Provenance databases, and enables the LLM to search across all stored data to answer questions about your past activity.

---

## 1. OCR Provenance Client (`memory/ocr_client.py`)

HTTP JSON-RPC client for OCR Provenance at `http://ocr-provenance-mcp:3366/mcp` (Docker network).

```python
import httpx

class OCRProvClient:
    def __init__(self, base_url: str = "http://ocr-provenance-mcp:3366"):
        self.base_url = base_url
        self.mcp_url = f"{base_url}/mcp"
        self.upload_url = f"{base_url}/api/upload"
        self.client = httpx.Client(timeout=30)
        self._request_id = 0

    def _call(self, method: str, params: dict) -> dict:
        self._request_id += 1
        resp = self.client.post(self.mcp_url, json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": method, "arguments": params},
            "id": self._request_id
        })
        resp.raise_for_status()
        result = resp.json()
        if "error" in result:
            raise RuntimeError(f"OCR Prov {method} failed: {result['error']}")
        return result.get("result", {})

    # --- Deterministic calls (no LLM needed) ---

    def select_db(self, name: str):
        self._call("ocr_db_select", {"name": name})

    def create_db(self, name: str, description: str):
        self._call("ocr_db_create", {"name": name, "description": description})

    def list_dbs(self) -> list:
        return self._call("ocr_db_list", {})

    def db_stats(self, name: str) -> dict:
        self.select_db(name)
        return self._call("ocr_db_stats", {})

    def ingest(self, file_paths: list[str], disable_images: bool = True) -> dict:
        return self._call("ocr_ingest_files", {
            "file_paths": file_paths,
            "disable_image_extraction": disable_images
        })

    def tag_document(self, doc_id: str, tag: str):
        self._call("ocr_tag_apply", {"entity_type": "document", "entity_id": doc_id, "tag": tag})

    def update_metadata(self, doc_id: str, title: str = None, author: str = None, subject: str = None):
        params = {"document_id": doc_id}
        if title: params["title"] = title
        if author: params["author"] = author
        if subject: params["subject"] = subject
        self._call("ocr_document_update_metadata", params)

    def find_duplicates(self) -> list:
        return self._call("ocr_document_duplicates", {})

    def delete_document(self, doc_id: str):
        self._call("ocr_document_delete", {"document_id": doc_id})

    def vacuum(self):
        self._call("ocr_db_maintenance", {"operation": "vacuum"})

    def health(self) -> bool:
        try:
            resp = self.client.get(f"{self.base_url}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    # --- LLM-called search tools ---

    def search(self, query: str, database: str = None) -> dict:
        if database:
            self.select_db(database)
        return self._call("ocr_search", {"query": query})

    def search_cross_db(self, query: str, databases: list[str]) -> dict:
        return self._call("ocr_search_cross_db", {"query": query, "databases": databases})

    def rag_context(self, query: str) -> dict:
        return self._call("ocr_rag_context", {"query": query})
```

---

## 2. Agent Registry (`memory/registry.py`)

Tracks which OCR Provenance databases the agent manages.

```python
MANAGED_DATABASES = {
    "va_screen_captures":  {"description": "Screenshot OCR text with window metadata", "retention_days": 30},
    "va_ambient_audio":    {"description": "Ambient mic transcriptions", "retention_days": 14},
    "va_system_audio":     {"description": "System audio loopback transcriptions", "retention_days": 14},
    "va_clipboard":        {"description": "Clipboard text snapshots", "retention_days": 7},
    "va_conversations":    {"description": "Voice conversation transcripts", "retention_days": None},
    "va_user_knowledge":   {"description": "Durable facts about the user", "retention_days": None},
    "va_documents":        {"description": "User-requested document storage", "retention_days": None},
}

class AgentRegistry:
    REGISTRY_PATH = Path.home() / ".voiceagent" / "registry.json"  # or /data/agent/registry.json in Docker

    def sync(self, ocr: OCRProvClient):
        """Ensure all managed databases exist in OCR Provenance."""
        existing = {db["name"] for db in ocr.list_dbs().get("databases", [])}
        for name, info in MANAGED_DATABASES.items():
            if name not in existing:
                ocr.create_db(name, info["description"])
                log.info(f"Created database: {name}")
```

---

## 3. Audio Transcription (`memory/ambient_mic.py`)

Processes WAV files from the companion's shared volume. Runs every 15 minutes inside the Docker container.

```python
class AudioTranscriber:
    MIN_SPEECH_S = 0.5

    def __init__(self, asr_model, ocr: OCRProvClient, vad: SileroVAD):
        self.asr = asr_model  # shared Whisper model from Phase 1
        self.ocr = ocr
        self.vad = vad

    def process_segment(self, wav_path: Path, database: str) -> bool:
        """VAD → Whisper → .txt → OCR Prov ingest → delete WAV + txt."""
        audio, sr = load_wav(wav_path)
        speech_s = self.vad.count_speech_seconds(audio, sr)

        if speech_s < self.MIN_SPEECH_S:
            wav_path.unlink()
            return False  # no speech

        segments, _ = self.asr.transcribe(str(wav_path), beam_size=5)
        transcript = self._format_transcript(segments)
        transcript = redact_pii(transcript)  # Presidio

        if is_hallucination(transcript):
            wav_path.unlink()
            return False

        txt_path = wav_path.with_suffix(".txt")
        txt_path.write_text(transcript, encoding="utf-8")
        wav_path.unlink()  # WAV no longer needed

        self.ocr.select_db(database)
        self.ocr.ingest([str(txt_path)], disable_images=True)  # .txt = instant passthrough
        txt_path.unlink()
        return True
```

---

## 4. Clipboard Ingestion

Clipboard .txt files from the companion are ingested directly:

```python
def ingest_clipboard_files(ocr: OCRProvClient, clipboard_dir: Path):
    ocr.select_db("va_clipboard")
    for txt_file in sorted(clipboard_dir.glob("clip_*.txt")):
        ocr.ingest([str(txt_file)], disable_images=True)
        txt_file.unlink()
```

---

## 5. LLM Tool Definitions for Memory Search

Add these to the LLM's tool registry (`brain/tools.py`):

```python
MEMORY_TOOLS = [
    {
        "name": "search_memory",
        "description": "Search across all voice agent databases for information about past activity, conversations, clipboard content, or anything the user has done. Use natural language queries.",
        "parameters": {
            "query": {"type": "string", "description": "Natural language search query"},
            "databases": {"type": "array", "items": {"type": "string"},
                          "description": "Specific databases to search. Default: all va_* databases."}
        },
        "handler": lambda args: ocr.search_cross_db(
            args["query"],
            args.get("databases", list(MANAGED_DATABASES.keys()))
        )
    },
    {
        "name": "search_screen_captures",
        "description": "Search screenshot OCR text. Use when user asks about what was on their screen.",
        "parameters": {
            "query": {"type": "string"},
            "time_filter": {"type": "string", "description": "Optional: ISO date or 'today', 'yesterday'"}
        }
    },
    {
        "name": "search_audio",
        "description": "Search transcribed ambient audio or system audio. Use when user asks about conversations or meetings.",
        "parameters": {
            "query": {"type": "string"},
            "source": {"type": "string", "enum": ["mic", "system", "both"], "default": "both"}
        }
    },
    {
        "name": "get_activity_summary",
        "description": "Get a summary of what apps/windows were active during a time period. Uses metadata sidecars, not OCR.",
        "parameters": {
            "date": {"type": "string", "description": "ISO date, e.g. '2026-03-28'"},
            "start_hour": {"type": "integer"},
            "end_hour": {"type": "integer"}
        }
    },
    {
        "name": "remember_fact",
        "description": "Store a durable fact about the user for future sessions. Use when user says 'remember this' or states a preference.",
        "parameters": {
            "fact": {"type": "string"},
            "category": {"type": "string", "enum": ["preference", "appointment", "contact", "project", "other"]}
        }
    }
]
```

---

## 6. Metadata-Based Activity Queries (Pre-OCR)

Even before dream state OCR processes screenshots, the agent can answer activity questions from sidecar JSONs:

```python
class ActivityTracker:
    def get_activity(self, captures_dir: Path, date: str, start_hour: int, end_hour: int) -> list[dict]:
        """Read sidecar JSONs to build activity timeline."""
        date_dir = captures_dir / date
        if not date_dir.exists():
            return []

        activities = []
        for json_file in sorted(date_dir.glob("*.json")):
            meta = json.loads(json_file.read_text())
            ts = datetime.fromisoformat(meta["timestamp"])
            if start_hour <= ts.hour < end_hour:
                activities.append({
                    "time": meta["timestamp"],
                    "app": meta.get("app", "unknown"),
                    "title": meta.get("title", ""),
                    "category": meta.get("category", "other"),
                    "monitor": meta.get("monitor", 0)
                })
        return activities
```

---

## 7. Verification Checklist

| # | Test | Source of Truth | Expected |
|---|------|----------------|----------|
| 1 | OCR Prov reachable | `ocr.health()` | True |
| 2 | All databases created | `ocr.list_dbs()` | Contains all 7 va_* databases |
| 3 | Screenshot ingest | `ocr.db_stats("va_screen_captures")` | document_count > 0 after ingest |
| 4 | Audio transcription | `ocr.db_stats("va_ambient_audio")` | document_count > 0 after process |
| 5 | Clipboard ingest | `ocr.db_stats("va_clipboard")` | document_count > 0 after ingest |
| 6 | Search returns results | `ocr.search("test query", "va_screen_captures")` | Non-empty results |
| 7 | Cross-db search works | `ocr.search_cross_db("test", all_dbs)` | Results from multiple databases |
| 8 | Activity tracker | `tracker.get_activity(dir, date, 14, 15)` | Returns app/title entries |
| 9 | PII redacted | Search results text | No SSN/CC patterns in stored text |
| 10 | Hallucination filtered | Ingest near-silent audio | No "thank you for watching" in db |
| 11 | .txt passthrough fast | Timer on clipboard ingest | <2 seconds total (no Marker OCR) |
| 12 | Full E2E: ask about activity | Voice: "what apps was I using today?" | Agent lists apps from metadata |

**Edge cases:**
- OCR Provenance container down → `ConnectionError`, surfaced in next conversation
- Empty WAV (15 min silence) → deleted, nothing ingested
- 190 screenshots queued → ingest handles batch without OOM
- Duplicate clipboard text → only 1 entry in va_clipboard
