# Phase 4: Dream State + Persistent Memory + Conversation Intelligence

**Timeline**: Weeks 8-9
**Exit Criteria**: VAQI score >70, facts persist across restarts, dream state runs successfully.
**Predecessor**: Phase 3 (OCR Provenance integration working)

---

## What Gets Built

Three major capabilities: (1) the 3 AM dream state that batch-OCRs screenshots and consolidates data, (2) cross-session persistent memory so the agent remembers facts about you, (3) full-duplex conversation intelligence with barge-in and backchanneling.

---

## 1. Dream State (`memory/dream.py`)

### 1.1 Scheduler

```python
import schedule
import time

class DreamScheduler:
    def __init__(self, config, ocr: OCRProvClient, llm: LLMBrain, gpu: GPUCoordinator):
        self.config = config
        self.ocr = ocr
        self.llm = llm
        self.gpu = gpu
        schedule.every().day.at("03:00").do(self.run_dream_state)

    def run_loop(self):
        while True:
            schedule.run_pending()
            time.sleep(60)
```

### 1.2 Dream Pipeline

```python
class DreamState:
    MAX_OCR_MINUTES = 110
    HARD_DEADLINE = "05:00"

    def run(self):
        start = datetime.now()
        log.info("DREAM STATE START")
        report = {"started_at": start.isoformat()}

        try:
            # Step 0: Pre-flight — count and budget
            pending = self._count_pending_captures()
            budget = self._compute_budget(pending)
            report["pending"] = pending
            report["budgeted"] = budget

            # Step 1: Unload all voice models
            self.gpu.unload_all()  # ASR, TTS, LLM off GPU

            # Step 2: Batch OCR (the main event)
            processed = self._batch_ocr(budget)
            report["processed"] = processed

            # Step 3: Cleanup processed captures
            cleaned = self._cleanup_captures()
            report["files_deleted"] = cleaned

            # Step 4: Deduplication
            dupes = self._deduplicate_all_dbs()
            report["duplicates_removed"] = dupes

            # Step 5: Reload Qwen3-14B (for digest + knowledge)
            self.gpu.load_llm()

            # Step 6: Daily digest
            digest_id = self._generate_digest()
            report["digest_doc_id"] = digest_id

            # Step 7: Knowledge extraction
            facts = self._extract_knowledge()
            report["facts_extracted"] = facts

            # Step 8: Retention enforcement
            expired = self._enforce_retention()
            report["docs_expired"] = expired

            # Step 9: Stats + health
            self._health_check_all_dbs()

            # Step 10: Reload voice models
            self.gpu.load_asr_tts()

        except Exception as e:
            log.error(f"DREAM STATE FAILED: {e}")
            report["error"] = str(e)
            # Always try to reload voice models
            self.gpu.load_all()
            raise

        report["duration_s"] = (datetime.now() - start).total_seconds()
        self._save_report(report)
        log.info(f"DREAM STATE END — {report['duration_s']:.0f}s")

    def _batch_ocr(self, file_list: list[Path]) -> int:
        """Ingest screenshots through OCR Provenance Marker pipeline."""
        self.ocr.select_db("va_screen_captures")
        processed = 0

        for i, png_path in enumerate(file_list):
            if datetime.now().strftime("%H:%M") >= "04:50":
                log.warning(f"Deadline approaching, stopping at {i}/{len(file_list)}")
                break

            sidecar = self._read_sidecar(png_path)
            result = self.ocr.ingest(
                [str(png_path)],
                disable_images=True
            )

            # Tag and add metadata from sidecar
            doc_id = self._extract_doc_id(result)
            if doc_id and sidecar:
                self.ocr.tag_document(doc_id, sidecar.get("category", "other"))
                self.ocr.tag_document(doc_id, f"monitor:{sidecar.get('monitor', 0)}")
                self.ocr.update_metadata(
                    doc_id,
                    title=sidecar.get("title", ""),
                    subject=sidecar.get("app", "")
                )

            # Mark sidecar as processed
            sidecar["processed"] = True
            self._write_sidecar(png_path, sidecar)
            processed += 1

            if i % 10 == 0:
                elapsed = (datetime.now() - self._batch_start).total_seconds()
                log.info(f"OCR progress: {i}/{len(file_list)}, {elapsed:.0f}s elapsed")

        return processed

    def _generate_digest(self) -> str | None:
        """Summarize yesterday's activity into a single searchable document."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        # Get metadata sidecars for activity timeline
        activities = self.activity_tracker.get_activity(
            self.captures_dir, yesterday, 0, 24
        )
        if not activities:
            return None

        # Build summary prompt
        activity_text = "\n".join(
            f"[{a['time']}] {a['app']}: {a['title']}"
            for a in activities[:200]  # cap at 200 entries
        )

        prompt = f"""Summarize what the user did on {yesterday} based on this activity log.
Group by activity type (coding, browsing, meetings, etc.). Keep it under 500 words.

Activity log:
{activity_text}"""

        digest = self.llm.generate_sync(prompt)

        # Save as document in va_conversations
        txt_path = self.tmp_dir / f"digest_{yesterday}.txt"
        txt_path.write_text(f"# Daily Digest — {yesterday}\n\n{digest}")
        self.ocr.select_db("va_conversations")
        result = self.ocr.ingest([str(txt_path)], disable_images=True)
        doc_id = self._extract_doc_id(result)
        if doc_id:
            self.ocr.tag_document(doc_id, "digest")
            self.ocr.tag_document(doc_id, f"date:{yesterday}")
        txt_path.unlink()
        return doc_id

    def _extract_knowledge(self) -> int:
        """Mine yesterday's voice conversations for durable facts."""
        # Query turns table for yesterday's conversations
        yesterday_turns = self.db.fetch_all(
            "SELECT text FROM turns WHERE role='user' AND date(started_at)=?",
            ((datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),)
        )
        if not yesterday_turns:
            return 0

        all_text = "\n".join(t["text"] for t in yesterday_turns)
        prompt = f"""Extract any durable facts the user stated about themselves.
Include: preferences, appointments, contacts, project details, opinions.
Return as JSON array: [{{"fact": "...", "category": "preference|appointment|contact|project|other"}}]
Only include facts that would be useful to remember in future conversations.
If no facts found, return [].

User's statements:
{all_text}"""

        response = self.llm.generate_sync(prompt)
        facts = json.loads(response)  # fail fast if not valid JSON

        stored = 0
        for fact in facts:
            txt_path = self.tmp_dir / f"fact_{stored}.txt"
            txt_path.write_text(f"[{fact['category']}] {fact['fact']}")
            self.ocr.select_db("va_user_knowledge")
            self.ocr.ingest([str(txt_path)], disable_images=True)
            txt_path.unlink()
            stored += 1
        return stored

    def _enforce_retention(self) -> int:
        """Delete documents older than retention policy."""
        total_deleted = 0
        for db_name, info in MANAGED_DATABASES.items():
            if info["retention_days"] is None:
                continue
            cutoff = (datetime.now() - timedelta(days=info["retention_days"])).isoformat()
            self.ocr.select_db(db_name)
            # List old documents
            docs = self.ocr._call("ocr_document_list", {"limit": 1000})
            for doc in docs.get("documents", []):
                if doc.get("created_at", "") < cutoff:
                    self.ocr.delete_document(doc["id"])
                    total_deleted += 1
            self.ocr.vacuum()
        return total_deleted
```

---

## 2. Cross-Session Persistent Memory (`memory/knowledge.py`)

### 2.1 Knowledge Store

```python
class KnowledgeStore:
    def __init__(self, ocr: OCRProvClient):
        self.ocr = ocr

    def remember(self, fact: str, category: str) -> str:
        """Store a fact. Called by LLM tool 'remember_fact'."""
        txt_path = Path(tempfile.mktemp(suffix=".txt"))
        txt_path.write_text(f"[{category}] {fact}")
        self.ocr.select_db("va_user_knowledge")
        result = self.ocr.ingest([str(txt_path)], disable_images=True)
        txt_path.unlink()
        return self._extract_doc_id(result)

    def recall(self, query: str, limit: int = 10) -> list[str]:
        """Search knowledge base. Called on startup to load relevant facts."""
        self.ocr.select_db("va_user_knowledge")
        results = self.ocr.search(query)
        return [r.get("text", "") for r in results.get("results", [])[:limit]]

    def load_startup_context(self) -> str:
        """Load recent user facts into system prompt on startup."""
        facts = self.recall("user preferences and important information", limit=20)
        if not facts:
            return ""
        return "## Known facts about the user:\n" + "\n".join(f"- {f}" for f in facts)
```

### 2.2 Session Restoration (`memory/session.py`)

```python
class SessionManager:
    SESSION_PATH = Path("/data/agent/session.json")  # Docker path

    def checkpoint(self, summary: str, conversation_id: str):
        state = {
            "session_id": conversation_id,
            "last_checkpoint": datetime.now().isoformat(),
            "conversation_summary": summary,
        }
        self.SESSION_PATH.write_text(json.dumps(state, indent=2))

    def restore(self) -> str | None:
        if not self.SESSION_PATH.exists():
            return None
        state = json.loads(self.SESSION_PATH.read_text())
        hours_ago = (datetime.now() - datetime.fromisoformat(state["last_checkpoint"])).total_seconds() / 3600
        return f"Resuming from {hours_ago:.1f} hours ago. Last session: {state['conversation_summary']}"
```

---

## 3. Full-Duplex Conversation Intelligence

### 3.1 Barge-In Detection (`conversation/barge_in.py`)

```python
class BargeInDetector:
    THRESHOLD_MS = 300
    DB_THRESHOLD = -30

    def __init__(self):
        self.speech_start = None

    def check(self, audio: np.ndarray, agent_is_speaking: bool) -> bool:
        """Returns True if user is interrupting the agent."""
        if not agent_is_speaking:
            return False

        rms_db = 20 * np.log10(np.sqrt(np.mean(audio.astype(float)**2)) + 1e-10)
        if rms_db > self.DB_THRESHOLD:
            if self.speech_start is None:
                self.speech_start = time.time()
            elif (time.time() - self.speech_start) * 1000 > self.THRESHOLD_MS:
                self.speech_start = None
                return True  # User has been speaking >300ms — interrupt
        else:
            self.speech_start = None
        return False
```

### 3.2 Backchannel Generation (`conversation/backchannel.py`)

```python
class BackchannelGenerator:
    INTERVAL_S = 3
    PHRASES = ["mm-hmm", "right", "I see", "okay", "got it"]

    def __init__(self, tts_adapter):
        self.tts = tts_adapter
        self.last_backchannel = 0
        self._cache = {}  # pre-rendered audio for each phrase

    async def warmup(self):
        """Pre-render backchannel phrases at startup."""
        for phrase in self.PHRASES:
            self._cache[phrase] = await self.tts.synthesize(phrase)

    def should_emit(self, continuous_speech_s: float) -> np.ndarray | None:
        if continuous_speech_s > self.INTERVAL_S:
            if time.time() - self.last_backchannel > self.INTERVAL_S:
                self.last_backchannel = time.time()
                phrase = random.choice(self.PHRASES)
                return self._cache.get(phrase)
        return None
```

### 3.3 Updated Conversation Manager

```python
class ConversationManager:
    # ... extends Phase 1 manager ...

    async def handle_audio_chunk(self, audio: np.ndarray):
        # Check barge-in during SPEAKING
        if self.state == ConversationState.SPEAKING:
            if self.barge_in.check(audio, agent_is_speaking=True):
                await self._handle_barge_in()
                return

        # Check backchannel during LISTENING
        if self.state == ConversationState.LISTENING:
            bc_audio = self.backchannel.should_emit(self.continuous_speech_s)
            if bc_audio is not None:
                await self.transport.send_audio(bc_audio)  # doesn't interrupt state

        # Pause companion capture during conversation
        if self.state != ConversationState.IDLE:
            if not self._companion_paused:
                await self._pause_companion()
        elif self._companion_paused and self._idle_duration() > 5:
            await self._resume_companion()

        # ... rest of audio handling from Phase 1 ...

    async def _handle_barge_in(self):
        """User interrupted — stop speaking, listen to them."""
        self.tts_queue.clear()
        await self.transport.fade_out(50)  # 50ms fade, not hard cut
        self.state = ConversationState.LISTENING
        self.history[-1]["content"] += " [interrupted]"
        log.info("Barge-in detected, switched to LISTENING")

    async def _pause_companion(self):
        """Mute companion capture during conversation (prevents self-capture)."""
        try:
            httpx.post("http://localhost:8770/pause", timeout=2)
            self._companion_paused = True
        except Exception:
            pass  # companion might be unreachable, not critical

    async def _resume_companion(self):
        try:
            httpx.post("http://localhost:8770/resume", timeout=2)
            self._companion_paused = False
        except Exception:
            pass
```

---

## 4. Voice Profile Selection

The user's primary voice is "boris" (trained on Chris Royse's speech). Additional voices can be created in ClipCannon and swapped at any time.

```python
# In VoiceAgent.start() or via voice command:
def switch_voice(self, voice_name: str):
    """Switch TTS voice. Fails fast if profile doesn't exist."""
    profile = get_voice_profile(voice_name)
    if not profile:
        raise ValueError(f"Voice profile '{voice_name}' not found. "
                        f"Available: {list_voice_profiles()}")
    self.tts_adapter = ClipCannonAdapter(voice_name)
    self.config.tts.default_voice = voice_name
    log.info(f"Switched voice to: {voice_name}")
```

The LLM has a tool for this:
```python
{
    "name": "switch_voice",
    "description": "Change the voice the agent speaks with. Default is 'boris' (Chris's voice). List available voices first if unsure.",
    "parameters": {
        "voice_name": {"type": "string", "description": "Name of the ClipCannon voice profile"}
    }
},
{
    "name": "list_voices",
    "description": "List all available ClipCannon voice profiles.",
    "parameters": {}
}
```

---

## 5. Verification Checklist

| # | Test | Source of Truth | Expected |
|---|------|----------------|----------|
| 1 | Dream state completes | `~/.voiceagent/logs/dream_*.json` | Report with all steps succeeded |
| 2 | Screenshots OCR'd | `ocr_db_stats("va_screen_captures")` | document_count matches processed count |
| 3 | Captures deleted after OCR | `~/.voiceagent/captures/` dir | Processed PNGs gone |
| 4 | Daily digest created | `ocr_search("digest", "va_conversations")` | Document with yesterday's summary |
| 5 | Knowledge extracted | `ocr_db_stats("va_user_knowledge")` | document_count > 0 |
| 6 | Retention enforced | Old doc count in va_clipboard | Docs older than 7 days gone |
| 7 | "Remember" tool works | Say "remember I prefer dark mode" then restart | Agent knows preference |
| 8 | Session restoration | Kill and restart agent | Agent says "Resuming from X hours ago" |
| 9 | Barge-in works | Speak while agent is talking | Agent stops within 200ms |
| 10 | Backchannel works | Speak for >5 seconds | Hear "mm-hmm" from agent |
| 11 | Companion paused during convo | Start conversation, check companion /status | `"paused": true` |
| 12 | Companion resumes after convo | End conversation, wait 5s | `"paused": false` |
| 13 | Voice switch | Say "switch to voice sarah" | Next response uses different voice |
| 14 | Voice list | Say "what voices do I have?" | Agent lists available profiles |
