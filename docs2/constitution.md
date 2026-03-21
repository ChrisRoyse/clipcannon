# ClipCannon Constitution

> **Level 1 Specification — Immutable Rules**
> All code, specs, tasks, and agent behavior MUST comply with this document.
> Violations require explicit exception approval and documentation in the decision log.

```xml
<constitution version="1.0">
<metadata>
  <project_name>ClipCannon</project_name>
  <spec_version>1.0.0</spec_version>
  <created>2026-03-21</created>
  <description>AI-native video editing MCP server — local GPU, 12-stream multimodal understanding, platform-ready output</description>
  <target_hardware>NVIDIA RTX 5090 (32GB GDDR7, CUDA 13.2) — degrades gracefully to RTX 2000+</target_hardware>
</metadata>

<!-- ============================================================ -->
<!-- TECH STACK                                                    -->
<!-- ============================================================ -->
<tech_stack>

  <!-- Runtime -->
  <language version="3.12+">Python</language>
  <framework version="latest">FastMCP (mcp-python-sdk)</framework>
  <database>SQLite 3.45+ (WAL mode, per-project analysis.db)</database>
  <vector_database version="0.1+">sqlite-vec (4 isolated vector tables)</vector_database>
  <video_engine version="7.x">FFmpeg (NVENC/NVDEC hardware acceleration)</video_engine>
  <edl_builder version="3.0+">typed-ffmpeg (type-safe FFmpeg command builder)</edl_builder>
  <gpu_framework version="2.3+">PyTorch (CUDA 13.2)</gpu_framework>
  <web_framework version="0.110+">FastAPI (dashboard on port 3200)</web_framework>
  <container>Docker (NVIDIA Container Toolkit, GPU passthrough)</container>

  <!-- ML Models — Understanding Pipeline -->
  <required_models>
    <model name="htdemucs" version="v4" vram_nvfp4="2.0GB" license="MIT">Source separation — 4 stems</model>
    <model name="whisperx" version="large-v3" vram_nvfp4="1.5GB" license="BSD-4-Clause">Transcription — mandatory wav2vec2 forced alignment</model>
    <model name="siglip" version="SO400M-patch14-384" vram_nvfp4="0.6GB" license="Apache-2.0">Visual embedding — 1152-dim</model>
    <model name="paddleocr" version="PP-OCRv5" vram_nvfp4="0.75GB" license="Apache-2.0">On-screen text detection</model>
    <model name="pyiqa-brisque" version="latest" vram_nvfp4="0.3GB" license="Public-Domain">Frame quality scoring (GPU)</model>
    <model name="dover-mobile" version="latest" vram_nvfp4="0.45GB" license="MIT">Aesthetic quality scoring (GPU)</model>
    <model name="resnet50-shottype" version="MovieShots" vram_nvfp4="0.2GB" license="MIT">Shot type classification</model>
    <model name="nomic-embed-text" version="v1.5" vram_nvfp4="0.25GB" license="Apache-2.0">Semantic embedding — 768-dim</model>
    <model name="wav2vec2-emotion" version="large" vram_nvfp4="0.75GB" license="MIT">Emotion/energy analysis — 1024-dim</model>
    <model name="wavlm-base-plus-sv" version="latest" vram_nvfp4="0.2GB" license="MIT">Speaker diarization — 512-dim</model>
    <model name="sensevoice-small" version="latest" vram_nvfp4="0.55GB" license="Apache-2.0">Reaction detection (laughter, applause)</model>
    <model name="beat-this" version="latest" vram_nvfp4="0.5GB" license="Open-Source">Beat/downbeat detection (GPU Transformer)</model>
    <model name="silero-vad" version="5.0" vram_nvfp4="0GB" license="MIT">Voice activity detection (CPU only)</model>
  </required_models>

  <!-- ML Models — Audio Generation (Phase 2+, loaded on demand) -->
  <optional_models>
    <model name="ace-step" version="v1.5-turbo-rl" vram_nvfp4="4.0GB" license="MIT">AI music generation</model>
  </optional_models>

  <!-- Core Libraries -->
  <required_libraries>
    <library version="1.26+">numpy</library>
    <library version="1.12+">scipy</library>
    <library version="13.0+">cupy-cuda12x</library>
    <library version="10.0+">Pillow</library>
    <library version="2.0+">pydantic</library>
    <library version="0.25+">httpx</library>
    <library version="8.0+">stripe</library>
    <library version="3.3+">python-jose (JWT)</library>
  </required_libraries>

  <!-- Phase 2+ Libraries -->
  <deferred_libraries>
    <library version="latest" phase="2">pydub (audio mixing)</library>
    <library version="latest" phase="2">pedalboard (audio effects, GPLv3)</library>
    <library version="latest" phase="2">MIDIUtil (MIDI composition)</library>
    <library version="latest" phase="2">music21 (music theory)</library>
    <library version="latest" phase="2">pyfluidsynth (MIDI rendering)</library>
    <library version="latest" phase="3">pycairo (vector graphics)</library>
    <library version="latest" phase="3">rlottie-python (Lottie rendering)</library>
  </deferred_libraries>

</tech_stack>

<!-- ============================================================ -->
<!-- DIRECTORY STRUCTURE                                            -->
<!-- ============================================================ -->
<directory_structure>
clipcannon/
├── src/
│   └── clipcannon/
│       ├── __init__.py
│       ├── server.py                  # MCP server entry (FastMCP)
│       ├── config.py                  # Configuration management
│       ├── tools/                     # MCP tool definitions (60+ tools)
│       │   ├── __init__.py
│       │   ├── project.py             # Project CRUD
│       │   ├── understanding.py       # Ingest, VUD, transcript, frame tools
│       │   ├── editing.py             # EDL, edit creation (Phase 2)
│       │   ├── rendering.py           # Render, batch render (Phase 2)
│       │   ├── audio.py               # Music gen, SFX (Phase 2)
│       │   ├── animation.py           # Lower thirds, Lottie (Phase 3)
│       │   ├── publishing.py          # Platform publish (Phase 3)
│       │   ├── provenance.py          # Provenance query/verify
│       │   ├── disk.py                # Disk management
│       │   └── config_tools.py        # Configuration tools
│       ├── pipeline/                  # Processing pipeline stages
│       │   ├── __init__.py
│       │   ├── orchestrator.py        # DAG-based pipeline runner
│       │   ├── probe.py
│       │   ├── vfr_normalize.py
│       │   ├── audio_extract.py
│       │   ├── source_separation.py   # HTDemucs
│       │   ├── frame_extract.py
│       │   ├── transcribe.py          # WhisperX
│       │   ├── visual_embed.py        # SigLIP + scene detection
│       │   ├── ocr.py                 # PaddleOCR
│       │   ├── quality.py             # BRISQUE + DOVER
│       │   ├── shot_type.py           # ResNet-50
│       │   ├── semantic_embed.py      # Nomic + topics
│       │   ├── emotion_embed.py       # Wav2Vec2
│       │   ├── speaker_embed.py       # WavLM
│       │   ├── reactions.py           # SenseVoice
│       │   ├── acoustic.py            # cuFFT + Beat This!
│       │   ├── profanity.py
│       │   ├── chronemic.py
│       │   ├── highlights.py
│       │   ├── storyboard.py
│       │   └── finalize.py
│       ├── editing/                   # Edit decision engine (Phase 2)
│       ├── rendering/                 # FFmpeg rendering (Phase 2)
│       ├── audio/                     # Audio generation (Phase 2)
│       ├── animation/                 # Motion graphics (Phase 3)
│       ├── publishing/                # Platform APIs (Phase 3)
│       ├── billing/                   # Credit system
│       │   ├── __init__.py
│       │   ├── license_client.py
│       │   ├── credits.py
│       │   └── hmac_integrity.py
│       ├── provenance/                # Hash chain system
│       │   ├── __init__.py
│       │   ├── hasher.py
│       │   ├── chain.py
│       │   └── recorder.py
│       ├── db/                        # Database layer
│       │   ├── __init__.py
│       │   ├── schema.py
│       │   ├── connection.py
│       │   └── queries.py
│       ├── gpu/                       # GPU management
│       │   ├── __init__.py
│       │   ├── manager.py
│       │   └── precision.py
│       └── dashboard/                 # Web dashboard
│           ├── __init__.py
│           ├── app.py
│           ├── auth.py
│           ├── routes/
│           ├── static/
│           └── templates/
├── src/license_server/                # Standalone license server
│   ├── __init__.py
│   ├── server.py
│   ├── d1_sync.py
│   └── stripe_webhooks.py
├── tests/
│   ├── unit/                          # Unit tests mirror src/ structure
│   │   ├── test_pipeline/
│   │   ├── test_provenance/
│   │   ├── test_billing/
│   │   └── test_db/
│   ├── integration/
│   │   ├── test_full_pipeline.py
│   │   ├── test_render_workflow.py
│   │   └── test_publish_workflow.py
│   └── fixtures/
│       ├── sample_video_10s.mp4
│       └── sample_audio_10s.wav
├── config/
│   ├── default_config.json
│   ├── platform_profiles.json
│   └── docker-compose.yml
├── scripts/
│   ├── setup.sh
│   ├── download_models.py
│   └── validate_gpu.py
├── assets/
│   ├── lottie/                        # 28 shipped Lottie animations (Phase 3)
│   ├── webm/                          # 20 pre-rendered WebM effects (Phase 3)
│   ├── transitions/                   # 60+ GL Transition expressions (Phase 3)
│   ├── fonts/                         # Bundled fonts (Montserrat, Inter)
│   ├── soundfonts/                    # GeneralUser_GS.sf2 (Phase 2)
│   └── profanity/                     # Profanity word list
├── specs/                             # Specification hierarchy
│   ├── constitution.md                # THIS FILE (immutable rules)
│   ├── functional/
│   ├── technical/
│   └── tasks/
├── .ai/                               # AI agent memory
│   ├── activeContext.md
│   ├── decisionLog.md
│   └── progress.md
├── docs2/                             # PRD and planning documents
├── Dockerfile
├── pyproject.toml
└── CLAUDE.md
</directory_structure>

<!-- ============================================================ -->
<!-- CODING STANDARDS                                              -->
<!-- ============================================================ -->
<coding_standards>

  <naming_conventions>
    <files>snake_case for all Python files (e.g., visual_embed.py, license_client.py)</files>
    <directories>snake_case for directories (e.g., pipeline/, license_server/)</directories>
    <classes>PascalCase for classes (e.g., ModelManager, PipelineOrchestrator, LicenseClient)</classes>
    <functions>snake_case for functions and methods (e.g., compute_chain_hash, get_vud_summary)</functions>
    <variables>snake_case for variables and parameters (e.g., project_id, frame_count)</variables>
    <constants>SCREAMING_SNAKE_CASE for constants (e.g., SCENE_THRESHOLD, SAMPLE_RATE, MAX_TOKEN_RESPONSE)</constants>
    <mcp_tools>snake_case prefixed with clipcannon_ (e.g., clipcannon_get_vud_summary, clipcannon_ingest)</mcp_tools>
    <db_tables>snake_case for table names (e.g., transcript_segments, emotion_curve)</db_tables>
    <db_columns>snake_case for column names (e.g., start_ms, chain_hash)</db_columns>
    <project_ids>Prefixed: proj_ + 8 hex chars (e.g., proj_a1b2c3d4)</project_ids>
    <provenance_ids>Prefixed: prov_ + 3-digit sequence (e.g., prov_001, prov_019)</provenance_ids>
  </naming_conventions>

  <type_annotations>
    <rule>ALL public functions MUST have full type annotations (parameters + return)</rule>
    <rule>Use pydantic BaseModel for all MCP tool parameters and responses</rule>
    <rule>Use dataclasses for internal data structures where pydantic is overkill</rule>
    <rule>Use TypedDict for simple dict shapes</rule>
    <rule>NEVER use Any — use Union, Optional, or a specific type</rule>
    <rule>Use Literal for string enums with fixed values (e.g., Literal["created", "analyzing", "ready", "error"])</rule>
  </type_annotations>

  <file_organization>
    <rule>One module per pipeline stage (e.g., transcribe.py contains only WhisperX logic)</rule>
    <rule>One file per MCP tool domain (e.g., tools/understanding.py contains all understanding tools)</rule>
    <rule>Maximum 500 lines per file — split into sub-modules if exceeded</rule>
    <rule>Co-locate unit tests: tests/unit/test_pipeline/test_transcribe.py for pipeline/transcribe.py</rule>
    <rule>Shared utilities go in a utils/ module, not duplicated across files</rule>
    <rule>All imports at file top, stdlib first, then third-party, then local</rule>
    <rule>Circular imports are forbidden — restructure with dependency injection or interfaces</rule>
  </file_organization>

  <docstrings>
    <rule>All public classes and functions MUST have docstrings</rule>
    <rule>Use Google-style docstrings (Args, Returns, Raises sections)</rule>
    <rule>Pipeline stages must document: model used, VRAM requirement, input/output, fallback behavior</rule>
    <rule>MCP tools must document: parameter constraints, response token budget, error codes</rule>
  </docstrings>

  <error_handling>
    <rule>All pipeline stages MUST catch and handle exceptions — never let model inference crash the server</rule>
    <rule>Optional pipeline stages: catch Exception, log error, set stream_status="failed", insert fallback values</rule>
    <rule>Required pipeline stages: catch Exception, log error, set stream_status="failed", stop pipeline, refund credits</rule>
    <rule>MCP tools: return structured error JSON, never raise unhandled exceptions</rule>
    <rule>Log errors with full context (project_id, stage name, model name, stack trace) before handling</rule>
    <rule>Use custom exception hierarchy: ClipCannonError → PipelineError, BillingError, ProvenanceError, etc.</rule>
    <rule>NEVER silently swallow exceptions — always log at minimum</rule>
  </error_handling>

  <async_patterns>
    <rule>MCP tools are async (FastMCP requirement)</rule>
    <rule>Pipeline orchestrator uses asyncio for parallel stage execution</rule>
    <rule>GPU model inference runs in thread executor to avoid blocking event loop</rule>
    <rule>License server HTTP calls are async via httpx</rule>
    <rule>Database writes are synchronous (SQLite limitation) — wrapped in run_in_executor if called from async</rule>
  </async_patterns>

</coding_standards>

<!-- ============================================================ -->
<!-- ARCHITECTURE RULES                                            -->
<!-- ============================================================ -->
<architecture_rules>

  <data_architecture>
    <rule id="ARCH-01">ONE SQLite database per project (analysis.db) — contains ALL structured data, embeddings, provenance</rule>
    <rule id="ARCH-02">Binary media (video, audio, frames, renders) stored as files on disk, referenced by path in DB</rule>
    <rule id="ARCH-03">sqlite-vec virtual tables for vector storage — 4 isolated tables, NEVER cross-space comparison</rule>
    <rule id="ARCH-04">WAL journal mode on every SQLite connection — enables concurrent reads during pipeline writes</rule>
    <rule id="ARCH-05">All timestamps in milliseconds (INTEGER) — unified timeline across all streams</rule>
    <rule id="ARCH-06">Embedding vectors NEVER sent to AI via MCP — only derived scalars (energy, quality, similarity)</rule>
  </data_architecture>

  <pipeline_architecture>
    <rule id="ARCH-10">DAG-based execution — stages declare dependencies, orchestrator resolves execution order</rule>
    <rule id="ARCH-11">Required stages stop pipeline on failure; optional stages degrade gracefully with fallback values</rule>
    <rule id="ARCH-12">HTDemucs source separation runs BEFORE all audio analysis — clean stems are force multiplier</rule>
    <rule id="ARCH-13">WhisperX with wav2vec2 forced alignment is MANDATORY — base Whisper timestamps drift 200-500ms</rule>
    <rule id="ARCH-14">Every pipeline stage writes a provenance record with SHA-256 hashes of input and output</rule>
    <rule id="ARCH-15">Ephemeral temp files are deleted after their consumer stage completes</rule>
  </pipeline_architecture>

  <mcp_architecture>
    <rule id="ARCH-20">Every MCP tool response MUST be under 25,000 tokens — Claude truncates beyond this</rule>
    <rule id="ARCH-21">Large data (VUD, transcript, storyboards) delivered progressively through paginated tool calls</rule>
    <rule id="ARCH-22">Stateless tool calls, stateful project data — no in-memory state between tool calls</rule>
    <rule id="ARCH-23">All MCP responses are JSON with consistent error format: {error: {code, message, details}}</rule>
    <rule id="ARCH-24">Frame images delivered inline for multimodal AI consumption (JPEG via image content type)</rule>
  </mcp_architecture>

  <rendering_architecture>
    <rule id="ARCH-30">FFmpeg is the ONLY renderer — AI produces EDL JSON, typed-ffmpeg builds FFmpeg commands</rule>
    <rule id="ARCH-31">Immutable source reference: every EDL contains source_file_sha256, renderer verifies before executing</rule>
    <rule id="ARCH-32">Renderer REFUSES to open any file from renders/ directory as source input — prevents generation loss</rule>
    <rule id="ARCH-33">Single-pass rendering: multi-segment EDLs become ONE FFmpeg filter_complex, no intermediate re-encodes</rule>
    <rule id="ARCH-34">Re-render = new render from original source, never from previous render output</rule>
  </rendering_architecture>

  <billing_architecture>
    <rule id="ARCH-40">Three-layer trust: Cloudflare D1 (truth) → License Server (cache) → HMAC integrity (tamper detection)</rule>
    <rule id="ARCH-41">Credits charged BEFORE operation begins, refunded on failure</rule>
    <rule id="ARCH-42">HMAC-SHA256 signs every balance mutation — tampered balance = fatal server exit</rule>
    <rule id="ARCH-43">Machine ID derived deterministically from hardware — same machine always gets same key</rule>
  </billing_architecture>

  <gpu_architecture>
    <rule id="ARCH-50">Precision auto-selection: NVFP4 (Blackwell CC 12.0), INT8 (Ada/Ampere CC 7.5+), FP16 (Turing CC 7.5)</rule>
    <rule id="ARCH-51">All understanding models fit in VRAM concurrently at NVFP4 (~10.6GB on RTX 5090)</rule>
    <rule id="ARCH-52">Audio generation models (ACE-Step) loaded on demand AFTER understanding models unloaded</rule>
    <rule id="ARCH-53">On GPUs with less than 16GB VRAM: sequential model loading — load, infer, unload per stage</rule>
    <rule id="ARCH-54">NVENC operates on dedicated silicon — does not consume CUDA cores or interfere with inference</rule>
  </gpu_architecture>

</architecture_rules>

<!-- ============================================================ -->
<!-- ANTI-PATTERNS (FORBIDDEN)                                     -->
<!-- ============================================================ -->
<anti_patterns>
  <forbidden>
    <!-- Data & Embeddings -->
    <item reason="Mathematically meaningless">NEVER compare embeddings across different vector tables (e.g., SigLIP vs Nomic) — cross-stream correlation is done via timestamp JOINs only</item>
    <item reason="AI cannot process raw vectors">NEVER send raw embedding vectors to AI via MCP — send derived scalars and labels only</item>
    <item reason="Data corruption risk">NEVER modify the original source video file — it is read-only (Sacred tier)</item>
    <item reason="Generation loss">NEVER use a previously rendered output as source input for a new render — always render from original source</item>

    <!-- MCP -->
    <item reason="Truncation by Claude">NEVER return more than 25K tokens in a single MCP response — paginate large data</item>
    <item reason="Context overflow">NEVER send the entire VUD as one blob — use progressive delivery (summary → analytics → transcript → frames)</item>

    <!-- Pipeline -->
    <item reason="200-500ms timestamp drift">NEVER use base Whisper timestamps without wav2vec2 forced alignment — WhisperX is mandatory</item>
    <item reason="Dramatically worse audio analysis quality">NEVER feed mixed audio directly to emotion/speaker/reaction models if HTDemucs is available — always use clean vocal stem</item>
    <item reason="Data loss">NEVER skip provenance recording on any pipeline stage — every transformation must be hash-tracked</item>

    <!-- Security -->
    <item reason="Security">NEVER hardcode API keys, secrets, tokens, or credentials in source files — use environment variables</item>
    <item reason="Security">NEVER store OAuth tokens in plaintext config files — use OS keychain (keyring library)</item>
    <item reason="Security">NEVER log sensitive data (tokens, passwords, credit card numbers, full profanity words in MCP responses)</item>
    <item reason="Security">NEVER commit .env files or files containing secrets to version control</item>

    <!-- Code Quality -->
    <item reason="Maintainability">NEVER use magic numbers — define named constants (SCENE_THRESHOLD = 0.75, MAX_TOKEN_RESPONSE = 25000)</item>
    <item reason="Type safety">NEVER use 'Any' type annotation — use specific types, Union, or Optional</item>
    <item reason="Testability">NEVER put test fixture data inline — store in tests/fixtures/</item>
    <item reason="Architecture">NEVER call model inference directly from MCP tools — tools call pipeline stages or service functions</item>
    <item reason="Architecture">NEVER write raw SQL in MCP tools — use query helpers from db/queries.py</item>
    <item reason="Architecture">NEVER construct FFmpeg commands as strings — use typed-ffmpeg for type-safe command building</item>
    <item reason="Concurrency">NEVER run synchronous model inference on the async event loop — use run_in_executor</item>
    <item reason="File size">NEVER let a single file exceed 500 lines — split into sub-modules</item>
  </forbidden>
</anti_patterns>

<!-- ============================================================ -->
<!-- SECURITY REQUIREMENTS                                         -->
<!-- ============================================================ -->
<security_requirements>
  <rule id="SEC-01">ALL processing is local — no video data, transcripts, or embeddings leave the machine</rule>
  <rule id="SEC-02">Source video files are NEVER modified — read-only access enforced</rule>
  <rule id="SEC-03">Platform API credentials stored in OS keychain (keyring library), never plaintext</rule>
  <rule id="SEC-04">Dashboard session tokens: HTTP-only cookies, 30-day TTL, magic link auth (JWT 10-min expiry)</rule>
  <rule id="SEC-05">Dashboard runs with whitelisted env vars only — cannot access license signing keys or Stripe secrets</rule>
  <rule id="SEC-06">HMAC-SHA256 balance integrity — tampered balance = immediate fatal exit with logged alert</rule>
  <rule id="SEC-07">Stripe webhook signature verification required — reject unsigned webhook calls</rule>
  <rule id="SEC-08">Profanity words are REDACTED in all MCP tool responses — stored in DB but shown as [REDACTED]</rule>
  <rule id="SEC-09">File path inputs validated and sanitized — prevent directory traversal in all MCP tools accepting paths</rule>
  <rule id="SEC-10">Rate limiting on license server endpoints — prevent credit exhaustion attacks</rule>
  <rule id="SEC-11">Machine ID derived from hardware characteristics — not user-configurable, not stored in plaintext</rule>
  <rule id="SEC-12">Provenance chain hashes detect any unauthorized modification of pipeline outputs</rule>
</security_requirements>

<!-- ============================================================ -->
<!-- PERFORMANCE BUDGETS                                           -->
<!-- ============================================================ -->
<performance_budgets>
  <!-- Pipeline Performance (RTX 5090 targets) -->
  <metric name="ingestion_1hr_1080p" target="< 5 minutes" gpu="RTX 5090">Full 12-stream pipeline for 1-hour 1080p source</metric>
  <metric name="ingestion_1hr_4090" target="< 8 minutes" gpu="RTX 4090">Same on RTX 4090 (INT8)</metric>
  <metric name="render_per_clip" target="< 30 seconds">Single clip render including audio + animations</metric>
  <metric name="music_gen_per_minute" target="< 5 seconds">ACE-Step music generation per minute of output</metric>
  <metric name="sfx_gen_per_effect" target="< 100 milliseconds">DSP sound effect generation</metric>

  <!-- Accuracy -->
  <metric name="transcript_wer" target="< 5%">Word Error Rate on English content</metric>
  <metric name="word_timestamp_precision" target="< 50ms drift">WhisperX wav2vec2 forced alignment precision</metric>
  <metric name="scene_detection_recall" target="> 90%">Scene boundary detection completeness</metric>
  <metric name="caption_sync" target="< 100ms drift">Caption display timing accuracy</metric>

  <!-- MCP Response -->
  <metric name="mcp_response_size" target="< 25,000 tokens">Every MCP tool response</metric>
  <metric name="vud_summary_size" target="~8,000 tokens">clipcannon_get_vud_summary response</metric>
  <metric name="analytics_size" target="~18,000 tokens">clipcannon_get_analytics response</metric>
  <metric name="transcript_page_size" target="~12,000 tokens">clipcannon_get_transcript per 15-min page</metric>
  <metric name="storyboard_batch_size" target="~24,000 tokens">clipcannon_get_storyboard per 12-grid batch</metric>

  <!-- Database -->
  <metric name="sqlite_vec_knn" target="< 15 milliseconds">KNN search on 28,000 vectors</metric>
  <metric name="db_query_p95" target="< 50 milliseconds">95th percentile for standard queries</metric>

  <!-- Resource -->
  <metric name="vram_peak_5090" target="< 12 GB">Peak VRAM during understanding pipeline (NVFP4)</metric>
  <metric name="vram_peak_4090" target="< 22 GB">Peak VRAM during understanding pipeline (INT8)</metric>
  <metric name="human_review_time" target="< 2 minutes">Per clip batch in dashboard</metric>
</performance_budgets>

<!-- ============================================================ -->
<!-- TESTING REQUIREMENTS                                          -->
<!-- ============================================================ -->
<testing_requirements>

  <coverage_minimum>80% line coverage for src/clipcannon/ (excluding dashboard templates)</coverage_minimum>

  <required_tests>
    <test_type scope="pipeline">Test for every pipeline stage — use real video for required stages, synthetic data for derived stages</test_type>
    <test_type scope="provenance">Test hash computation, chain verification, and tamper detection with real chain records</test_type>
    <test_type scope="billing">Test credit charge, refund, insufficient balance, HMAC sign/verify/tamper, idempotency keys</test_type>
    <test_type scope="mcp_tools">Test every MCP tool — verify response format, error handling, DB state after operation</test_type>
    <test_type scope="db">Test schema creation, query helpers, sqlite-vec vector operations (correct + wrong dimensions)</test_type>
    <test_type scope="integration">Integration test: real video through full pipeline → verify every DB table + file on disk</test_type>
    <test_type scope="integration">Integration test: billing workflow — charge → process → verify OR charge → fail → refund</test_type>
    <test_type scope="e2e">E2E test: full workflow from ingest to VUD delivery via MCP tools</test_type>
    <test_type scope="performance">Benchmark: pipeline time, VRAM peak, MCP response sizes, sqlite-vec search time</test_type>
  </required_tests>

  <test_data_policy>
    <rule>NO mock data — use real video files or synthetic data (PIL-generated frames, programmatic DB inserts)</rule>
    <rule>NO mock.patch on core logic — only mock external services (Stripe, Cloudflare D1) and unavailable ML models</rule>
    <rule>Tests must verify Sources of Truth directly — open the database with raw sqlite3 or check files with os.path.exists</rule>
    <rule>Do NOT rely solely on function return values — independently verify the side effects (DB rows, files, HMAC state)</rule>
    <rule>For edge cases, print BEFORE and AFTER state to prove the outcome</rule>
  </test_data_policy>

  <fixture_optimization>
    <!-- CRITICAL: These rules prevent the test suite from becoming slow -->
    <rule id="TEST-OPT-01">NEVER re-run FFmpeg operations in function-scoped fixtures — use module scope for probe, audio extract, frame extract</rule>
    <rule id="TEST-OPT-02">NEVER reload ML models between tests — load once per module or session, share across tests</rule>
    <rule id="TEST-OPT-03">Use module-scoped fixtures for any operation taking more than 1 second</rule>
    <rule id="TEST-OPT-04">Use function-scoped fixtures only for lightweight setup (empty DB creation, synthetic data insertion)</rule>
    <rule id="TEST-OPT-05">Create PIL Images programmatically instead of extracting real frames when testing non-FFmpeg logic</rule>
    <rule id="TEST-OPT-06">Share DB state across tests in the same module when tests are read-only (assertions only, no mutations)</rule>
    <rule id="TEST-OPT-07">Use tmp_path_factory.mktemp() in module-scoped fixtures (not tmp_path which is function-scoped)</rule>
    <rule id="TEST-OPT-08">Chain expensive fixtures: probed_project → audio_extracted_project → frames_extracted_project — each runs once, downstream tests share the result</rule>
  </fixture_optimization>

  <fixture_scope_guide>
    <!-- When to use each scope -->
    <scope name="session">ML model loading, GPU initialization — load once for entire test run</scope>
    <scope name="module">FFmpeg operations (probe, audio extract, frame extract), full pipeline runs — shared by all tests in one file</scope>
    <scope name="function">Fresh databases, synthetic data, isolated mutation tests — each test gets its own</scope>
  </fixture_scope_guide>

  <test_patterns>
    <rule>Tests ship WITH implementation, not as separate tasks</rule>
    <rule>Use pytest as test runner with pytest-asyncio (asyncio_mode = "auto")</rule>
    <rule>Fixture data stored in tests/fixtures/ — never inline in test files</rule>
    <rule>MCP tool tests must assert response format matches spec (error codes, JSON structure)</rule>
    <rule>Provenance tests must include tamper-then-verify scenarios (modify field → verify_chain detects exact record)</rule>
    <rule>Billing tests must verify physical DB state after every charge/refund (not just API response)</rule>
    <rule>Pipeline stage tests must verify: StageResult.success, provenance record written, DB rows inserted, files created</rule>
    <rule>Break monolithic test methods into focused assertions — one test per verification concern</rule>
  </test_patterns>

  <test_structure>
    <!-- Actual test file layout -->
    tests/
    ├── test_pipeline_stages.py      # Module-scoped: real video, FFmpeg ops run once
    ├── test_visual_pipeline.py      # Function-scoped: synthetic PIL frames, no FFmpeg
    ├── test_derived_stages.py       # Function-scoped: synthetic DB data, no models
    ├── test_understanding_tools.py  # Function-scoped: synthetic DB data, tool response format
    ├── test_provenance_integration.py  # Function-scoped: fresh DB per chain test
    ├── test_billing.py              # Function-scoped: FastAPI TestClient, HMAC tests
    ├── dashboard/
    │   └── test_dashboard.py        # Function-scoped: FastAPI TestClient, API endpoints
    └── integration/
        ├── test_full_pipeline.py    # Module-scoped: full pipeline on real video, 15+ assertions
        └── manual_verify.py         # Standalone: prints physical proof of every table and file
  </test_structure>

  <test_commands>
    <command purpose="all_tests">pytest tests/ -v</command>
    <command purpose="quick_check">pytest tests/ -q --tb=short</command>
    <command purpose="integration">pytest tests/integration/ -v</command>
    <command purpose="coverage">pytest tests/ --cov=src/clipcannon --cov-report=term-missing</command>
    <command purpose="type_check">pyright src/</command>
    <command purpose="lint">ruff check src/ tests/</command>
    <command purpose="format">ruff format src/ tests/</command>
    <command purpose="manual_verify">python tests/integration/manual_verify.py</command>
  </test_commands>

  <full_guide>See docs2/Testing_Guide.md for the complete testing guide with code examples, templates, and cookbook recipes.</full_guide>

</testing_requirements>

<!-- ============================================================ -->
<!-- PROVENANCE RULES                                              -->
<!-- ============================================================ -->
<provenance_rules>
  <rule id="PROV-01">Every data transformation MUST produce a provenance record with SHA-256 hashes</rule>
  <rule id="PROV-02">Chain hash = SHA256(parent_hash | input_sha256 | output_sha256 | operation | model_name | model_version | model_params_json)</rule>
  <rule id="PROV-03">Genesis record (probe) has parent_hash = "GENESIS"</rule>
  <rule id="PROV-04">Chain verification: if any record is tampered, all downstream chain hashes become invalid</rule>
  <rule id="PROV-05">File hasher uses streaming (8KB chunks) for large files (>1GB video files)</rule>
  <rule id="PROV-06">Table content hashing: serialize query results deterministically (sorted keys) then hash</rule>
  <rule id="PROV-07">19 provenance points per full Phase 1 pipeline run (probe through finalize)</rule>
  <rule id="PROV-08">Phase 2+ adds: EDL create, music gen, SFX gen, audio mix, animation render, video render, publish (7 more)</rule>
  <rule id="PROV-09">clipcannon_provenance_verify MUST pass on every completed project before status = "ready"</rule>
</provenance_rules>

<!-- ============================================================ -->
<!-- DISK MANAGEMENT RULES                                         -->
<!-- ============================================================ -->
<disk_management>
  <tier name="Sacred" auto_delete="never">
    <file>Original source video</file>
    <file>analysis.db (all structured data + vectors + provenance)</file>
    <file>Final rendered output clips (Phase 2+)</file>
    <file>EDL JSON files (Phase 2+)</file>
  </tier>
  <tier name="Regenerable" auto_delete="when disk space needed">
    <file>CFR-normalized source copy</file>
    <file>Audio stems (vocals.wav, music.wav, drums.wav, other.wav)</file>
    <file>Extracted frames (JPEGs at 2fps)</file>
    <file>Storyboard grid JPEGs</file>
  </tier>
  <tier name="Ephemeral" auto_delete="after consumer stage completes">
    <file>Intermediate render segments</file>
    <file>Temp audio chunks</file>
    <file>Animation frame sequences (PNGs)</file>
    <file>Preview renders</file>
  </tier>
  <rule>Proactive cleanup: ephemeral files deleted automatically as each pipeline step completes</rule>
  <rule>Warn when disk space falls below 20GB free</rule>
  <rule>clipcannon_disk_cleanup deletes ephemeral first, then regenerable (largest first)</rule>
</disk_management>

<!-- ============================================================ -->
<!-- EMBEDDING SPACE ISOLATION                                     -->
<!-- ============================================================ -->
<embedding_isolation>
  <rule>4 vector tables, 4 separate mathematical spaces — NEVER compared across tables</rule>
  <table name="vec_frames" model="SigLIP" dimensions="1152" comparable_with="vec_frames only"/>
  <table name="vec_semantic" model="Nomic" dimensions="768" comparable_with="vec_semantic only"/>
  <table name="vec_emotion" model="Wav2Vec2" dimensions="1024" comparable_with="vec_emotion only"/>
  <table name="vec_speakers" model="WavLM" dimensions="512" comparable_with="vec_speakers only"/>
  <rule>sqlite-vec enforces dimension matching per table — mismatched dimension queries error</rule>
  <rule>Cross-stream correlation uses timestamp JOINs, not vector comparison</rule>
  <rule>Derived scalars (energy 0-1, quality 0-100, similarity 0-1) ARE comparable across streams</rule>
</embedding_isolation>

<!-- ============================================================ -->
<!-- GRACEFUL DEGRADATION                                          -->
<!-- ============================================================ -->
<graceful_degradation>
  <required_stages fail_behavior="stop pipeline, refund credits">
    <stage>probe</stage>
    <stage>vfr_normalize (if VFR detected)</stage>
    <stage>audio_extract</stage>
    <stage>frame_extract</stage>
    <stage>transcribe (WhisperX)</stage>
    <stage>finalize</stage>
  </required_stages>
  <optional_stages fail_behavior="insert fallback values, mark as failed, continue pipeline">
    <stage fallback="feed mixed audio to all audio models">source_separation</stage>
    <stage fallback="no scene detection, no visual similarity">visual_embed</stage>
    <stage fallback="empty on_screen_text[]">ocr</stage>
    <stage fallback="all scenes quality 'unknown'">quality</stage>
    <stage fallback="all scenes shot_type 'unknown'">shot_type</stage>
    <stage fallback="no topic segmentation">semantic_embed</stage>
    <stage fallback="flat energy 0.5 everywhere">emotion_embed</stage>
    <stage fallback="single 'speaker_0' for all segments">speaker_embed</stage>
    <stage fallback="empty reactions[]">reactions</stage>
    <stage fallback="no silence gaps, no beats">acoustic</stage>
    <stage fallback="content rated 'unknown'">profanity</stage>
    <stage fallback="no pacing data">chronemic</stage>
    <stage fallback="highlights from available data only">highlights</stage>
    <stage fallback="AI requests frames via get_frame instead">storyboard</stage>
  </optional_stages>
  <rule>VUD marks failed streams explicitly in stream_status and degradation_note</rule>
  <rule>AI reads degradation_note and adjusts editing strategy — it works with what it has</rule>
</graceful_degradation>

<!-- ============================================================ -->
<!-- PHASED DELIVERY SCOPE                                         -->
<!-- ============================================================ -->
<phased_delivery>
  <phase number="1" name="Foundation">
    <scope>MCP server, 12-stream understanding pipeline, billing, provenance, basic dashboard</scope>
    <creates>src/clipcannon/server.py, tools/{project,understanding,provenance,disk,config_tools}.py, pipeline/*, db/*, gpu/*, provenance/*, billing/*, dashboard/app.py</creates>
  </phase>
  <phase number="2" name="Editing Engine">
    <scope>EDL format, rendering pipeline, AI audio generation, captions, smart cropping, full dashboard</scope>
    <creates>editing/*, rendering/*, audio/*, tools/{editing,rendering,audio}.py, dashboard full</creates>
  </phase>
  <phase number="3" name="Motion Graphics &amp; Publishing">
    <scope>4-tier animation engine, platform OAuth, publishing APIs, complete dashboard</scope>
    <creates>animation/*, publishing/*, tools/{animation,publishing}.py</creates>
  </phase>
  <phase number="4" name="Intelligence &amp; Growth">
    <scope>Feedback loops, A/B testing, templates, multi-language, marketplace, agency tier</scope>
  </phase>
  <rule>Each phase builds on prior phases — no forward references to unbuilt code</rule>
  <rule>Do not create placeholder files for future phases — only build what is in the current phase scope</rule>
</phased_delivery>

<!-- ============================================================ -->
<!-- PLATFORM CONSTRAINTS                                          -->
<!-- ============================================================ -->
<platform_constraints>
  <platform name="TikTok">
    <resolution>1080x1920</resolution>
    <aspect>9:16</aspect>
    <duration>15-60s</duration>
    <codec>H.264</codec>
    <fps>30</fps>
    <audio>AAC 44.1kHz stereo</audio>
    <bitrate>8 Mbps</bitrate>
  </platform>
  <platform name="Instagram Reels">
    <resolution>1080x1920</resolution>
    <aspect>9:16</aspect>
    <duration>15-60s</duration>
    <codec>H.264</codec>
    <fps>30</fps>
    <audio>AAC 44.1kHz</audio>
    <bitrate>6 Mbps</bitrate>
  </platform>
  <platform name="YouTube Standard">
    <resolution>1920x1080 or 3840x2160</resolution>
    <aspect>16:9</aspect>
    <duration>3-20 minutes</duration>
    <codec>H.264</codec>
    <fps>30</fps>
    <audio>AAC-LC 48kHz stereo</audio>
    <bitrate>12 Mbps (1080p), 40 Mbps (4K)</bitrate>
  </platform>
  <platform name="YouTube Shorts">
    <resolution>1080x1920</resolution>
    <aspect>9:16</aspect>
    <duration>up to 3 minutes</duration>
    <codec>H.264</codec>
    <fps>30</fps>
    <audio>AAC 48kHz stereo</audio>
    <bitrate>8 Mbps</bitrate>
  </platform>
  <platform name="Facebook Reels">
    <resolution>1080x1920</resolution>
    <aspect>9:16</aspect>
    <duration>15-60s</duration>
    <codec>H.264</codec>
    <fps>30</fps>
    <audio>AAC stereo 128kbps+</audio>
    <bitrate>6 Mbps</bitrate>
  </platform>
  <platform name="LinkedIn">
    <resolution>1080x1080</resolution>
    <aspect>1:1</aspect>
    <duration>30s-3 minutes</duration>
    <codec>H.264</codec>
    <fps>30</fps>
    <audio>AAC 44.1kHz</audio>
    <bitrate>5 Mbps</bitrate>
  </platform>
</platform_constraints>

<!-- ============================================================ -->
<!-- CREDIT SYSTEM                                                 -->
<!-- ============================================================ -->
<credit_system>
  <operation name="video_analysis" credits="10">Full 12-stream understanding pipeline</operation>
  <operation name="clip_render" credits="2">Per output clip (includes audio + animations)</operation>
  <operation name="metadata_generation" credits="1">Per clip per platform (title + description + hashtags)</operation>
  <operation name="platform_publish" credits="1">Per post (API call + upload + tracking)</operation>
  <operation name="ai_music_generation" credits="0">Included in clip render cost</operation>
  <rule>Credits charged BEFORE operation begins</rule>
  <rule>Failed operations receive automatic full refund</rule>
  <rule>Monthly spending cap: $5-$500 (user-configurable, warn at 80%)</rule>
</credit_system>

</constitution>
```

---

*End of Constitution — Level 1 Immutable Rules for ClipCannon*
