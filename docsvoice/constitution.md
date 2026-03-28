# Voice Agent — Constitution

```xml
<constitution version="1.0">
<metadata>
  <project_name>Voice Agent — Personal AI Assistant with Total Recall</project_name>
  <spec_version>1.0.0</spec_version>
  <created_date>2026-03-28</created_date>
  <last_updated>2026-03-28</last_updated>
  <authors>Chris Royse</authors>
  <description>
    Immutable rules governing the Voice Agent project across all 5 phases.
    A voice-first personal AI assistant living at src/voiceagent/ inside the
    ClipCannon monolith repo. Three systems: ClipCannon (voice synthesis,
    read-only), OCR Provenance MCP (document intelligence at localhost:3366,
    153 tools), Qwen3-14B-FP8 (local reasoning engine).
  </description>
  <phases>
    <phase id="1" name="Core Voice Pipeline" timeline="Weeks 1-3" />
    <phase id="2" name="Windows Companion + Capture" timeline="Weeks 4-5" />
    <phase id="3" name="OCR Provenance Integration + Memory" timeline="Weeks 6-7" />
    <phase id="4" name="Dream State + Persistent Memory + Conversation Intelligence" timeline="Weeks 8-9" />
    <phase id="5" name="Production Hardening + Benchmarks" timeline="Week 10" />
  </phases>
</metadata>

<!-- ================================================================== -->
<!--  TECH STACK                                                        -->
<!-- ================================================================== -->

<tech_stack>
  <language version="3.12+">Python</language>
  <framework version="0.115+">FastAPI</framework>
  <database>SQLite (agent.db for conversations/turns/metrics)</database>
  <runtime>
    <primary>Docker with nvidia runtime (WSL2 Linux, voice agent)</primary>
    <secondary>Windows 11 native (companion .exe via PyInstaller)</secondary>
  </runtime>
  <gpu>
    <hardware>NVIDIA RTX 5090 (170 SMs, 32GB GDDR7, Blackwell CC 12.0)</hardware>
    <cuda version="13.1/13.2">CUDA Toolkit</cuda>
    <features>Green Contexts, NVFP4</features>
  </gpu>
  <cpu>AMD Ryzen 9 9950X3D (16C/32T, 5.7GHz, 192MB L3)</cpu>
  <ram>128GB DDR5-3592</ram>

  <required_libraries>
    <!-- ASR -->
    <library version="1.1+" purpose="ASR transcription (Distil-Whisper Large v3, INT8)">faster-whisper</library>
    <library version="5.x" purpose="Voice Activity Detection (ONNX, CPU)">silero-vad</library>
    <library version="0.6+" purpose="Wake word detection (CPU)">openwakeword</library>

    <!-- LLM -->
    <library version="0.8+" purpose="Qwen3-14B-FP8 inference server (primary)">vllm</library>
    <library version="4.48+" purpose="Qwen3-14B fallback loader">transformers</library>
    <library version="2.6+" purpose="GPU tensor operations, model loading">torch</library>

    <!-- TTS -->
    <library purpose="ClipCannon voice synthesis (imported as Python library, read-only)">clipcannon</library>

    <!-- Transport -->
    <library version="14.0+" purpose="WebSocket bidirectional audio transport">websockets</library>

    <!-- PII / Security -->
    <library version="2.2+" purpose="PII detection and redaction">presidio-analyzer</library>
    <library version="2.2+" purpose="PII anonymization">presidio-anonymizer</library>

    <!-- Audio -->
    <library version="0.5.5" purpose="Audio I/O for companion">sounddevice</library>
    <library purpose="Noise suppression (CPU, companion/transport)">rnnoise</library>
    <library purpose="Echo cancellation (transport)">speexdsp</library>

    <!-- Screen Capture / Windows -->
    <library purpose="Screenshot capture via PIL.ImageGrab (companion)">Pillow</library>
    <library purpose="Perceptual hashing for screenshot dedup">imagehash</library>
    <library purpose="Windows API access (companion only)">pywin32</library>
    <library purpose="System tray icon (companion)">pystray</library>

    <!-- HTTP / API -->
    <library purpose="HTTP client for OCR Provenance JSON-RPC">httpx</library>
    <library purpose="ASGI server for FastAPI">uvicorn</library>

    <!-- CLI / Scheduling -->
    <library purpose="CLI entry point">click</library>
    <library purpose="Dream state scheduling">schedule</library>

    <!-- Database -->
    <library purpose="SQLite interface (stdlib)">sqlite3</library>
  </required_libraries>

  <external_systems>
    <system name="ClipCannon" access="read-only Python import" constraint="NEVER modify source or databases" />
    <system name="OCR Provenance MCP" access="HTTP JSON-RPC at localhost:3366/mcp" tools="153" />
    <system name="Qwen3-14B-FP8" access="Local model via vLLM or transformers" location="~/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/" />
  </external_systems>
</tech_stack>

<!-- ================================================================== -->
<!--  DIRECTORY STRUCTURE                                               -->
<!-- ================================================================== -->

<directory_structure>
<![CDATA[
src/voiceagent/
    __init__.py
    agent.py                # Main VoiceAgent class
    config.py               # VoiceAgentConfig dataclass
    errors.py               # All exceptions
    asr/
        __init__.py
        streaming.py        # StreamingASR
        vad.py              # Silero VAD wrapper
        endpointing.py      # Silence-based endpoint detection
        entities.py         # ASR data types
    brain/
        __init__.py
        llm.py              # LLMBrain: Qwen3-14B loader + streaming generation
        prompts.py          # System prompt builder
        tools.py            # Tool registry
        context.py          # Context window manager
    conversation/
        __init__.py
        manager.py          # State machine (IDLE/LISTENING/THINKING/SPEAKING)
        turn_taking.py      # Turn allocation logic
        barge_in.py         # Full-duplex interruption handling
        backchannel.py      # "uh-huh", "go on" generation
        state.py            # ConversationState dataclass
    tts/
        __init__.py
        streaming.py        # StreamingTTS: sentence chunks -> ClipCannon
        chunker.py          # Sentence boundary detection
        warmup.py           # Pre-load voice embeddings
        cache.py            # Utterance caching
    transport/
        __init__.py
        websocket.py        # WebSocket bidirectional audio
        webrtc.py           # WebRTC transport (Phase 5)
        sip.py              # SIP transport (future)
        opus.py             # Opus codec wrapper
        echo_cancel.py      # SpeexDSP echo cancellation
        noise_suppress.py   # RNNoise noise suppression
    memory/
        __init__.py
        ocr_client.py       # HTTP JSON-RPC client for OCR Provenance
        screen_capture.py   # Docker-side capture file reader
        ambient_mic.py      # Ambient microphone transcription
        system_audio.py     # System audio loopback transcription
        clipboard.py        # Voice-controlled clipboard access
        active_window.py    # Window metadata reader
        pii_filter.py       # Presidio PII redaction
        registry.py         # Database registry manager
        retriever.py        # Multi-source memory retrieval
        knowledge.py        # User knowledge extraction + storage
        dream.py            # Dream state batch processor
        scheduler.py        # Dream state scheduler (3 AM)
        session.py          # Cross-session memory persistence
    adapters/
        __init__.py
        clipcannon.py       # ClipCannon voice system adapter (read-only)
    activation/
        __init__.py
        wake_word.py        # OpenWakeWord detection
        hotkey.py           # pynput global hotkey
    eval/
        __init__.py
        tau_voice.py        # Tau-Voice benchmark
        vaqi.py             # VAQI scoring
        latency.py          # Latency benchmark
        task_completion.py  # Task completion benchmark
        conversation_quality.py  # Conversation quality metrics
        benchmark_runner.py # Orchestrates all benchmarks
    db/
        __init__.py
        schema.py           # SQLite schema (conversations, turns, metrics)
        connection.py       # Connection factory
    server.py               # FastAPI REST + WebSocket server
    cli.py                  # CLI entry point (click)

src/companion/              # Windows-native companion (.exe)
    __init__.py
    main.py                 # Entry point, tray icon, main loop
    config.py               # CompanionConfig dataclass
    http_api.py             # FastAPI on :8770 (status, pause/resume)
    capture/
        __init__.py
        screen.py           # PIL.ImageGrab per-monitor + pHash dedup
        window.py           # win32gui active window title + process
        browser_url.py      # Win32 COM Shell.Application for URLs
        clipboard.py        # Voice-controlled clipboard (no polling)
        audio.py            # sounddevice mic + system audio segments
    health/
        __init__.py
        heartbeat.py        # companion_status.json every 30s
        docker_check.py     # Docker container health polling
    tray/
        __init__.py
        icon.py             # pystray system tray (green/yellow/red)
    voiceagent-capture.spec # PyInstaller spec file

tests/
    voiceagent/             # Co-located test files
        test_agent.py
        test_config.py
        test_asr/
        test_brain/
        test_conversation/
        test_tts/
        test_transport/
        test_memory/
        test_adapters/
        test_activation/
        test_eval/
        test_db/
        test_server.py
        test_cli.py
    companion/
        test_capture/
        test_health/

docker/
    voiceagent/
        Dockerfile
    docker-compose.yml
]]>
</directory_structure>

<!-- ================================================================== -->
<!--  CODING STANDARDS                                                  -->
<!-- ================================================================== -->

<coding_standards>
  <naming_conventions>
    <files>snake_case for all Python files (e.g., ocr_client.py, wake_word.py)</files>
    <variables>snake_case for variables and function parameters (e.g., audio_chunk, sample_rate)</variables>
    <constants>SCREAMING_SNAKE_CASE for module-level and class constants (e.g., MAX_OCR_MINUTES, HARD_DEADLINE)</constants>
    <functions>snake_case, verb-first for actions (e.g., process_audio, load_model, get_transcription)</functions>
    <classes>PascalCase for classes (e.g., VoiceAgent, StreamingASR, DreamScheduler)</classes>
    <types>PascalCase for TypedDict and type aliases (e.g., AudioChunk, TranscriptionResult)</types>
  </naming_conventions>

  <file_organization>
    <rule id="FO-01">One major class per file for core components (agent.py, llm.py, streaming.py)</rule>
    <rule id="FO-02">Co-locate tests at tests/voiceagent/test_[module].py mirroring src/ structure</rule>
    <rule id="FO-03">Shared utilities in src/voiceagent/utils/ (if needed); check existing before creating new</rule>
    <rule id="FO-04">All configuration as dataclasses in config.py; never scatter config across modules</rule>
    <rule id="FO-05">All exceptions defined in errors.py; never define exceptions in other modules</rule>
    <rule id="FO-06">Keep files under 500 lines; split into sub-modules if exceeded</rule>
    <rule id="FO-07">All __init__.py files export public API symbols only</rule>
    <rule id="FO-08">Companion code (src/companion/) is entirely separate from voice agent (src/voiceagent/); no cross-imports</rule>
  </file_organization>

  <type_system>
    <rule id="TS-01">Type hints required on ALL public function signatures (arguments and return types)</rule>
    <rule id="TS-02">Use dataclasses for configuration objects and state containers</rule>
    <rule id="TS-03">Use TypedDict for complex dictionary shapes passed between modules</rule>
    <rule id="TS-04">Use type aliases for complex union types (e.g., AudioData = np.ndarray | bytes)</rule>
    <rule id="TS-05">Private methods may omit type hints only when the types are obvious from context</rule>
    <rule id="TS-06">Never use Any as a type hint; use Union, Protocol, or a concrete type instead</rule>
  </type_system>

  <async_model>
    <rule id="AS-01">All I/O-bound operations in src/voiceagent/ MUST be async (asyncio)</rule>
    <rule id="AS-02">Companion (src/companion/) uses synchronous threading, NOT asyncio</rule>
    <rule id="AS-03">GPU model inference runs in asyncio executor (run_in_executor) to avoid blocking the event loop</rule>
    <rule id="AS-04">WebSocket handlers are async; never block the event loop with synchronous I/O</rule>
    <rule id="AS-05">OCR Provenance HTTP calls use httpx.AsyncClient in voice agent, httpx.Client in companion</rule>
  </async_model>

  <error_handling>
    <rule id="EH-01">Never use bare except clauses; always catch specific exception types</rule>
    <rule id="EH-02">Log errors with full context (module, operation, relevant IDs) before re-raising</rule>
    <rule id="EH-03">Fail fast with clear error messages; never silently swallow exceptions</rule>
    <rule id="EH-04">All custom exceptions inherit from VoiceAgentError (defined in errors.py)</rule>
    <rule id="EH-05">GPU OOM errors must trigger model unload + torch.cuda.empty_cache() + retry once</rule>
    <rule id="EH-06">WebSocket disconnects must cleanly release all resources (models, audio streams)</rule>
    <rule id="EH-07">OCR Provenance call failures must include the JSON-RPC method name and error payload in the log</rule>
    <rule id="EH-08">Never use silent fallbacks; if a component fails, propagate the error to the caller</rule>
  </error_handling>

  <documentation>
    <rule id="DOC-01">Docstrings on public methods only; omit for private/internal/obvious methods</rule>
    <rule id="DOC-02">Docstrings use Google style: one-line summary, then Args/Returns/Raises sections</rule>
    <rule id="DOC-03">Module-level docstring in every __init__.py describing the sub-package purpose</rule>
    <rule id="DOC-04">Inline comments only for non-obvious logic (GPU memory math, audio frame calculations)</rule>
    <rule id="DOC-05">No commented-out code checked into version control</rule>
  </documentation>
</coding_standards>

<!-- ================================================================== -->
<!--  ANTI-PATTERNS                                                     -->
<!-- ================================================================== -->

<anti_patterns>
  <forbidden>
    <!-- ClipCannon boundary violations -->
    <item id="AP-01" reason="ClipCannon is read-only; voice agent is a consumer, not a modifier">
      Modify ClipCannon source files, databases, or project directories
    </item>
    <item id="AP-02" reason="ClipCannon owns its data; voice agent reads via the adapter">
      Write to ClipCannon project directories or voice_profiles.db
    </item>

    <!-- Security -->
    <item id="AP-03" reason="Security; use environment variables or config files outside the repo">
      Hardcode API keys, secrets, or credentials in source code
    </item>
    <item id="AP-04" reason="Security; .env files contain secrets that must never enter version control">
      Commit .env files to version control
    </item>
    <item id="AP-05" reason="PII exposure risk; all text must pass through Presidio before storage">
      Store text in OCR Provenance without PII redaction via Presidio
    </item>

    <!-- Windows companion -->
    <item id="AP-06" reason="Fragile and slow; use pywin32 directly for native Windows API calls">
      Use subprocess to invoke Windows commands (PowerShell, CMD) in the companion
    </item>
    <item id="AP-07" reason="Slow and unreliable; PIL.ImageGrab is native and 50ms per monitor">
      Use PowerShell or CMD for screenshot capture
    </item>
    <item id="AP-08" reason="Privacy violation; clipboard is voice-controlled only, never background-polled">
      Poll clipboard in background or on a timer
    </item>
    <item id="AP-09" reason="Privacy; banking, password managers, and blocklisted windows must never be captured">
      Capture screenshots of privacy-blocklisted windows (1Password, banking apps, etc.)
    </item>

    <!-- GPU management -->
    <item id="AP-10" reason="VRAM starvation; models load on wake word and unload on dismiss">
      Load GPU models permanently; models must be on-demand load/unload
    </item>
    <item id="AP-11" reason="Memory leak; always call torch.cuda.empty_cache() after model unload">
      Unload a GPU model without calling torch.cuda.empty_cache()
    </item>
    <item id="AP-12" reason="Dream state owns the full GPU overnight; daytime OCR causes VRAM contention">
      Run OCR processing during daytime hours; OCR is dream state only (3-5 AM)
    </item>

    <!-- OCR Provenance -->
    <item id="AP-13" reason="Image extraction wastes storage and processing; we only need text">
      Call OCR Provenance ingest without disable_image_extraction=true
    </item>

    <!-- Code quality -->
    <item id="AP-14" reason="Maintainability; define as class constants or config values">
      Use magic numbers without named constants
    </item>
    <item id="AP-15" reason="Readability and testability; split into smaller functions">
      Functions exceeding 50 lines
    </item>
    <item id="AP-16" reason="Readability; restructure with early returns or extract helper functions">
      Nesting depth exceeding 4 levels
    </item>
    <item id="AP-17" reason="Code hygiene; delete dead code, do not comment it out">
      Commented-out code checked into version control
    </item>
    <item id="AP-18" reason="Type safety; use Union, Protocol, or a concrete type">
      Using Any in Python type hints
    </item>

    <!-- Testing -->
    <item id="AP-19" reason="Hardware verification requires real GPU execution; mocks hide real failures">
      Use mocks for hardware verification tests (ASR, LLM, TTS on real GPU)
    </item>
    <item id="AP-20" reason="Inline test data becomes stale and untraceable; use tests/fixtures/">
      Inline stub data in test files instead of tests/fixtures/
    </item>

    <!-- Architecture -->
    <item id="AP-21" reason="Companion is sync/threaded Windows-native; voice agent is async Linux/Docker">
      Import between src/companion/ and src/voiceagent/ (no cross-imports)
    </item>
    <item id="AP-22" reason="Errors must be visible; silent fallback masks bugs and degrades quality">
      Silent fallbacks that hide errors from callers
    </item>
    <item id="AP-23" reason="Error swallowing hides bugs; always catch specific exceptions">
      Bare except: clauses
    </item>
    <item id="AP-24" reason="Mutable defaults are shared across calls, causing subtle bugs">
      Mutable default arguments in function signatures
    </item>
    <item id="AP-25" reason="Namespace pollution; import specific names only">
      Wildcard imports (from module import *)
    </item>
  </forbidden>
</anti_patterns>

<!-- ================================================================== -->
<!--  SECURITY REQUIREMENTS                                             -->
<!-- ================================================================== -->

<security_requirements>
  <!-- Input validation -->
  <rule id="SEC-01">Validate and sanitize all user input at system boundaries: WebSocket messages, HTTP API requests, CLI arguments</rule>
  <rule id="SEC-02">Sanitize all file paths to prevent directory traversal (reject paths containing ".." or absolute paths outside allowed directories)</rule>

  <!-- PII and privacy -->
  <rule id="SEC-03">All text MUST pass through Presidio PII redaction before storage in any OCR Provenance database</rule>
  <rule id="SEC-04">Privacy blocklist prevents capture of banking, password manager, and other sensitive windows; blocklist is configurable</rule>
  <rule id="SEC-05">Clipboard access ONLY on explicit voice command; never polled, never background-captured</rule>
  <rule id="SEC-06">PII redaction covers: names, emails, phone numbers, SSNs, credit cards, IP addresses, dates of birth</rule>

  <!-- Secrets management -->
  <rule id="SEC-07">No secrets (API keys, tokens, passwords) in source code, config files checked into repo, or Docker images</rule>
  <rule id="SEC-08">Secrets provided exclusively via environment variables or mounted secret files at runtime</rule>
  <rule id="SEC-09">Never log secrets, tokens, or credentials at any log level</rule>

  <!-- Transport -->
  <rule id="SEC-10">WebSocket transport supports TLS (wss://) for production deployments</rule>
  <rule id="SEC-11">Companion HTTP API (port 8770) binds to localhost only; not exposed to network</rule>

  <!-- Container isolation -->
  <rule id="SEC-12">Docker container runs with minimal privileges (no --privileged, drop unnecessary capabilities)</rule>
  <rule id="SEC-13">Shared volume permissions restrict companion to write-only for capture directories; Docker container has read-write</rule>
  <rule id="SEC-14">Voice agent Docker container has no access to host filesystem outside the shared volume mount</rule>

  <!-- Model isolation -->
  <rule id="SEC-15">Wake word model (OpenWakeWord) runs CPU-only, isolated from network; never sends audio externally</rule>
  <rule id="SEC-16">All LLM inference is local (Qwen3-14B on local GPU); no cloud API calls for reasoning</rule>
  <rule id="SEC-17">ASR inference is local (Distil-Whisper on local GPU); no cloud transcription services</rule>

  <!-- Data retention -->
  <rule id="SEC-18">Enforce retention policies per database: rolling 7/14/30 day auto-delete for ephemeral data; permanent only for conversations and user knowledge</rule>
  <rule id="SEC-19">Processed screenshot PNGs and sidecar JSONs deleted from shared volume after successful OCR ingestion in dream state</rule>
</security_requirements>

<!-- ================================================================== -->
<!--  PERFORMANCE BUDGETS                                               -->
<!-- ================================================================== -->

<performance_budgets>
  <!-- End-to-end voice loop -->
  <metric name="e2e_voice_latency" target="< 500ms P95">
    Full pipeline: speech end detected -> first audio byte of response played back
  </metric>

  <!-- ASR -->
  <metric name="asr_transcription" target="< 100ms per chunk">
    Distil-Whisper transcription of a 200ms audio chunk (INT8, GPU)
  </metric>
  <metric name="vad_inference" target="< 1ms per chunk">
    Silero VAD inference per audio chunk (ONNX, CPU)
  </metric>
  <metric name="wake_word_detection" target="< 5ms per chunk">
    OpenWakeWord detection per audio chunk (CPU)
  </metric>

  <!-- LLM -->
  <metric name="llm_time_to_first_token" target="< 200ms">
    Qwen3-14B-FP8 time from prompt submission to first generated token (vLLM)
  </metric>

  <!-- TTS -->
  <metric name="tts_time_to_first_byte" target="< 150ms">
    ClipCannon voice synthesis time from text input to first audio byte output
  </metric>

  <!-- Transport -->
  <metric name="websocket_round_trip" target="< 10ms">
    WebSocket message send to acknowledgment on localhost
  </metric>

  <!-- Companion -->
  <metric name="screenshot_capture" target="< 50ms per monitor">
    PIL.ImageGrab per-monitor capture latency
  </metric>
  <metric name="phash_comparison" target="< 1ms">
    Perceptual hash comparison for screenshot deduplication
  </metric>
  <metric name="companion_ram" target="< 100MB">
    Total companion process memory footprint
  </metric>
  <metric name="companion_cpu_idle" target="< 5%">
    Companion CPU usage when no capture activity
  </metric>
  <metric name="companion_cpu_capture" target="< 15%">
    Companion CPU usage during active capture cycle
  </metric>

  <!-- GPU VRAM -->
  <metric name="gpu_vram_fp4" target="< 15.5GB total">
    Total GPU VRAM when all voice models loaded in FP4 mode (ASR + LLM + TTS)
  </metric>
  <metric name="gpu_vram_fp8_fallback" target="< 21GB total">
    Total GPU VRAM when using FP8 fallback for LLM
  </metric>

  <!-- Dream state -->
  <metric name="dream_state_duration" target="< 120 minutes">
    Dream state must complete all batch OCR within the 3-5 AM window (110 min OCR + 10 min overhead)
  </metric>
</performance_budgets>

<!-- ================================================================== -->
<!--  GPU MANAGEMENT RULES                                              -->
<!-- ================================================================== -->

<gpu_management>
  <rule id="GPU-01">Models loaded on-demand via wake word activation; unloaded on session dismiss or idle timeout</rule>
  <rule id="GPU-02">Green Contexts partition: Context A (70% SMs, 119 SMs) for active voice pipeline; Context B (30% SMs, 51 SMs) for background tasks</rule>
  <rule id="GPU-03">Dream state (3-5 AM): unload ALL voice models, reclaim full 32GB VRAM for batch OCR</rule>
  <rule id="GPU-04">NVFP4 quantization preferred for Qwen3-14B; fall back to FP8 only if accuracy degrades below VAQI threshold</rule>
  <rule id="GPU-05">Always call torch.cuda.empty_cache() after every model unload to release VRAM fragments</rule>
  <rule id="GPU-06">GPU OOM triggers: (1) unload lowest-priority model, (2) empty cache, (3) retry once; if still OOM, fail with clear error</rule>
  <rule id="GPU-07">Never load more than one LLM simultaneously; ASR + LLM + TTS is the maximum concurrent model set</rule>
  <rule id="GPU-08">Model load/unload operations must be logged with VRAM before/after for debugging memory leaks</rule>
</gpu_management>

<!-- ================================================================== -->
<!--  OCR PROVENANCE INTEGRATION RULES                                  -->
<!-- ================================================================== -->

<ocr_provenance_integration>
  <rule id="OCR-01">All OCR Provenance calls via HTTP JSON-RPC at localhost:3366/mcp; never import OCR Prov code directly</rule>
  <rule id="OCR-02">Always pass disable_image_extraction=true on all ocr_ingest_files calls (we only need extracted text)</rule>
  <rule id="OCR-03">90% of OCR Prov calls are deterministic (db operations, ingest, tag); do NOT route these through the LLM</rule>
  <rule id="OCR-04">LLM involvement only for user-initiated search and recall queries that require reasoning</rule>
  <rule id="OCR-05">7 managed databases with defined retention:
    va_screen_captures (30 days), va_ambient_audio (14 days), va_system_audio (14 days),
    va_clipboard (7 days), va_conversations (permanent), va_user_knowledge (permanent),
    va_documents (permanent)</rule>
  <rule id="OCR-06">Local registry at ~/.voiceagent/registry.json maps database names to purposes, creation dates, and retention policies</rule>
  <rule id="OCR-07">OCR batch processing runs ONLY during dream state (3-5 AM); never during daytime hours</rule>
  <rule id="OCR-08">After successful dream state OCR ingestion, delete processed PNG and JSON sidecar files from shared volume</rule>
  <rule id="OCR-09">PII redaction via Presidio MUST complete before any text is stored in OCR Provenance</rule>
  <rule id="OCR-10">Tag all ingested documents with source metadata: app name, window title, monitor index, capture timestamp</rule>
</ocr_provenance_integration>

<!-- ================================================================== -->
<!--  CLIPCANNON INTEGRATION RULES                                      -->
<!-- ================================================================== -->

<clipcannon_integration>
  <rule id="CC-01">ClipCannon is imported as a read-only Python library for voice synthesis; never modify its source</rule>
  <rule id="CC-02">All ClipCannon access goes through src/voiceagent/adapters/clipcannon.py; no direct imports elsewhere</rule>
  <rule id="CC-03">Voice profile "boris" is the user's cloned voice (0.975 SECS); always use this profile for TTS</rule>
  <rule id="CC-04">ClipCannon databases (voice_profiles.db, etc.) are read-only; never write or modify them</rule>
  <rule id="CC-05">If ClipCannon API changes, update ONLY the adapter; no other module should know ClipCannon internals</rule>
</clipcannon_integration>

<!-- ================================================================== -->
<!--  TESTING REQUIREMENTS                                              -->
<!-- ================================================================== -->

<testing_requirements>
  <coverage_minimum>80% line coverage for business logic (brain/, conversation/, memory/)</coverage_minimum>

  <required_tests>
    <test_type id="TEST-01">Unit: All business logic in brain/, conversation/, memory/ with mocks for external dependencies</test_type>
    <test_type id="TEST-02">Integration (real GPU): ASR transcription with Distil-Whisper on real audio samples</test_type>
    <test_type id="TEST-03">Integration (real GPU): LLM inference with Qwen3-14B on real prompts</test_type>
    <test_type id="TEST-04">Integration (real GPU): TTS synthesis with ClipCannon on real text</test_type>
    <test_type id="TEST-05">Integration: OCR Provenance client against running OCR Prov Docker container</test_type>
    <test_type id="TEST-06">End-to-end: Full voice loop (speak -> transcribe -> reason -> synthesize -> audio output)</test_type>
    <test_type id="TEST-07">Benchmark: Latency measurements for all performance budget metrics</test_type>
    <test_type id="TEST-08">Benchmark: VAQI score > 70</test_type>
    <test_type id="TEST-09">Benchmark: Memory recall accuracy > 90%</test_type>
    <test_type id="TEST-10">Edge case: Silence handling (no speech detected for 30+ seconds)</test_type>
    <test_type id="TEST-11">Edge case: Long utterances (> 60 seconds continuous speech)</test_type>
    <test_type id="TEST-12">Edge case: WebSocket disconnect and reconnect</test_type>
    <test_type id="TEST-13">Edge case: GPU OOM prevention and recovery</test_type>
    <test_type id="TEST-14">Edge case: Concurrent WebSocket connections</test_type>
    <test_type id="TEST-15">Companion: Screenshot capture + pHash dedup on Windows</test_type>
    <test_type id="TEST-16">Companion: Privacy blocklist enforcement</test_type>
    <test_type id="TEST-17">Security: PII redaction coverage (names, emails, phones, SSNs, credit cards)</test_type>
    <test_type id="TEST-18">Dream state: Full batch OCR pipeline (capture -> ingest -> tag -> cleanup)</test_type>
  </required_tests>

  <test_naming>tests/voiceagent/test_[module].py with test functions named test_[behavior]_[scenario] (e.g., test_transcribe_short_utterance, test_vad_detects_silence)</test_naming>

  <test_data>
    <rule id="TD-01">Test audio fixtures in tests/fixtures/audio/ (WAV files, various durations and noise levels)</rule>
    <rule id="TD-02">Test image fixtures in tests/fixtures/images/ (screenshot PNGs for OCR testing)</rule>
    <rule id="TD-03">Never use real user data in tests; use synthetic fixtures only</rule>
    <rule id="TD-04">GPU integration tests marked with @pytest.mark.gpu; skipped when no GPU available</rule>
  </test_data>
</testing_requirements>

<!-- ================================================================== -->
<!--  DEPENDENCY MANAGEMENT                                             -->
<!-- ================================================================== -->

<dependency_management>
  <rule id="DEP-01">Pin all direct dependencies to exact versions in requirements.txt (voice agent) and requirements-companion.txt (companion)</rule>
  <rule id="DEP-02">Separate dependency files: requirements.txt (voice agent, Linux/Docker), requirements-companion.txt (companion, Windows), requirements-dev.txt (test/lint tools)</rule>
  <rule id="DEP-03">No new dependencies without justification; prefer stdlib and existing dependencies first</rule>
  <rule id="DEP-04">GPU libraries (torch, vllm, faster-whisper) pinned to CUDA 13.1+ compatible versions</rule>
  <rule id="DEP-05">Run pip-audit or safety check before adding new dependencies; reject packages with known CVEs</rule>
  <rule id="DEP-06">Companion dependencies must be Windows-compatible and PyInstaller-friendly</rule>
  <rule id="DEP-07">Never depend on ClipCannon internals; only use its public Python API through the adapter</rule>
</dependency_management>

<!-- ================================================================== -->
<!--  GIT WORKFLOW                                                      -->
<!-- ================================================================== -->

<git_workflow>
  <branching_strategy>Feature branches off main; branch naming: voiceagent/[phase]-[feature] (e.g., voiceagent/p1-asr-pipeline, voiceagent/p3-dream-state)</branching_strategy>
  <commit_format>Conventional Commits: type(scope): description. Types: feat, fix, refactor, test, docs, chore. Scope: voiceagent or companion.</commit_format>
  <pr_requirements>
    <rule id="PR-01">All tests pass (unit + integration where applicable)</rule>
    <rule id="PR-02">No new lint warnings (ruff check)</rule>
    <rule id="PR-03">Type checking passes (mypy or pyright)</rule>
    <rule id="PR-04">Performance budgets not regressed (latency benchmarks if applicable)</rule>
    <rule id="PR-05">PR description includes: what changed, why, how to test, phase reference</rule>
  </pr_requirements>
</git_workflow>

<!-- ================================================================== -->
<!--  ENVIRONMENT CONFIGURATION                                         -->
<!-- ================================================================== -->

<environment_configuration>
  <environments>
    <env name="development">
      Local development in WSL2. Voice agent runs directly (not in Docker).
      GPU models loaded locally. OCR Provenance in Docker at localhost:3366.
      Companion runs natively on Windows 11.
      Config: ~/.voiceagent/config.json
    </env>
    <env name="docker">
      Voice agent in Docker container with nvidia runtime.
      Shared volume: /data/agent/ (maps to C:\voiceagent_data\ on Windows host).
      OCR Provenance at ocr-provenance-mcp:3366 (Docker network).
      Companion runs natively on Windows host alongside Docker.
    </env>
    <env name="production">
      docker-compose orchestrates: voice agent container, OCR Provenance container.
      Companion installed as Windows startup app (voiceagent-capture.exe).
      TLS enabled on WebSocket transport.
      Dream state scheduler active (3-5 AM daily).
    </env>
  </environments>

  <secrets_management>
    All secrets via environment variables. Docker: passed via --env-file (not baked into image).
    Companion: reads from %APPDATA%\voiceagent\secrets.env (not checked into repo).
    Required secrets: none for Phase 1-3 (all local models, no cloud APIs).
    Future: any external API keys via ENV only.
  </secrets_management>

  <shared_volume>
    <rule id="VOL-01">Windows path: C:\voiceagent_data\</rule>
    <rule id="VOL-02">Docker mount: /data/agent/</rule>
    <rule id="VOL-03">Subdirectories: captures/ (screenshots + sidecars), audio/ (mic + system segments), clipboard/ (text entries), status/ (heartbeat JSON)</rule>
    <rule id="VOL-04">Companion writes to captures/, audio/, clipboard/; Docker reads and processes</rule>
    <rule id="VOL-05">After dream state processing, Docker deletes processed files from captures/</rule>
  </shared_volume>
</environment_configuration>

<!-- ================================================================== -->
<!--  CONVERSATION ARCHITECTURE RULES                                   -->
<!-- ================================================================== -->

<conversation_architecture>
  <rule id="CONV-01">Conversation state machine: IDLE -> LISTENING -> THINKING -> SPEAKING -> IDLE (or LISTENING for follow-up)</rule>
  <rule id="CONV-02">Barge-in supported: user speech during SPEAKING state interrupts TTS and transitions to LISTENING</rule>
  <rule id="CONV-03">Turn-taking uses VAD silence detection + endpointing; minimum 300ms silence to end a turn</rule>
  <rule id="CONV-04">Backchannel generation ("uh-huh", "I see") during long user turns to signal active listening</rule>
  <rule id="CONV-05">All conversation turns persisted to agent.db with timestamps, speaker, text, and latency metrics</rule>
  <rule id="CONV-06">Context window managed explicitly: system prompt + conversation history + tool results must fit within Qwen3-14B context limit</rule>
  <rule id="CONV-07">Session timeout: auto-dismiss after 5 minutes of no user interaction</rule>
</conversation_architecture>

<!-- ================================================================== -->
<!--  COMPANION ARCHITECTURE RULES                                      -->
<!-- ================================================================== -->

<companion_architecture>
  <rule id="COMP-01">Companion is a Windows-native .exe built with PyInstaller; runs in system tray</rule>
  <rule id="COMP-02">Synchronous threading model (not asyncio); Windows APIs are not async-compatible</rule>
  <rule id="COMP-03">HTTP API on localhost:8770 for status, pause/resume, and voice-triggered capture commands</rule>
  <rule id="COMP-04">Heartbeat: write companion_status.json to shared volume every 30 seconds</rule>
  <rule id="COMP-05">Screen change detection every 5 seconds via pHash comparison; only capture on change</rule>
  <rule id="COMP-06">Per-monitor differential capture: each monitor has its own pHash history; only capture changed monitors</rule>
  <rule id="COMP-07">Audio capture: 15-minute segments for ambient mic and system audio loopback</rule>
  <rule id="COMP-08">Tray icon color: green (healthy), yellow (degraded), red (Docker container unreachable)</rule>
  <rule id="COMP-09">All captures saved with JSON metadata sidecars (timestamp, app, title, URL, monitor index, pHash)</rule>
</companion_architecture>

<!-- ================================================================== -->
<!--  DREAM STATE RULES                                                 -->
<!-- ================================================================== -->

<dream_state>
  <rule id="DREAM-01">Dream state runs daily at 3:00 AM; hard deadline at 5:00 AM (120 minute window)</rule>
  <rule id="DREAM-02">Step 0: Count pending captures, compute time budget (110 min OCR + 10 min overhead)</rule>
  <rule id="DREAM-03">Step 1: Unload ALL voice models from GPU before OCR processing begins</rule>
  <rule id="DREAM-04">Step 2: Batch OCR via OCR Provenance (ocr_ingest_files with disable_image_extraction=true)</rule>
  <rule id="DREAM-05">Step 3: PII redaction on all extracted text via Presidio</rule>
  <rule id="DREAM-06">Step 4: Auto-tag documents by app name from sidecar metadata</rule>
  <rule id="DREAM-07">Step 5: Deduplicate via ocr_document_duplicates; remove near-identical text</rule>
  <rule id="DREAM-08">Step 6: Generate daily digest (Qwen3-14B summarizes the day's captures)</rule>
  <rule id="DREAM-09">Step 7: Delete processed PNGs and JSON sidecars from shared volume</rule>
  <rule id="DREAM-10">Step 8: Reload voice agent models if user has active session</rule>
  <rule id="DREAM-11">If dream state cannot complete by 5:00 AM, save progress and continue next night</rule>
  <rule id="DREAM-12">Dream state failures logged with full detail; never silently fail</rule>
</dream_state>

<!-- ================================================================== -->
<!--  BENCHMARK TARGETS                                                 -->
<!-- ================================================================== -->

<benchmark_targets>
  <metric id="BENCH-01" name="VAQI Score" target="> 70" description="Voice Agent Quality Index composite score" />
  <metric id="BENCH-02" name="Memory Recall" target="> 90%" description="Accuracy of retrieving stored facts from OCR Provenance" />
  <metric id="BENCH-03" name="Task Completion" target="> 85%" description="Percentage of voice commands successfully executed end-to-end" />
  <metric id="BENCH-04" name="Conversation Naturalness" target="> 4.0/5.0 MOS" description="Mean Opinion Score for conversation quality" />
  <metric id="BENCH-05" name="Barge-in Response" target="< 300ms" description="Time from user interruption to TTS stop + ASR activation" />
  <metric id="BENCH-06" name="Wake Word False Accept" target="< 1 per 24h" description="False wake word activations per day" />
  <metric id="BENCH-07" name="Wake Word Miss Rate" target="< 5%" description="Missed wake word detections as percentage of intentional activations" />
  <metric id="BENCH-08" name="PII Redaction Recall" target="> 99%" description="Percentage of PII entities detected and redacted" />
  <metric id="BENCH-09" name="Dream State Completion" target="100% within window" description="Dream state completes all queued work within the 3-5 AM window" />
  <metric id="BENCH-10" name="24h Uptime" target="> 99.5%" description="System runs unattended for 24 hours without crash or hang" />
</benchmark_targets>

<!-- ================================================================== -->
<!--  CHANGE LOG                                                        -->
<!-- ================================================================== -->

<change_log>
  <entry version="1.0.0" date="2026-03-28" author="Chris Royse">
    Initial constitution covering all 5 phases: core pipeline, companion,
    OCR Provenance integration, dream state + memory, production hardening.
  </entry>
</change_log>

</constitution>
```
