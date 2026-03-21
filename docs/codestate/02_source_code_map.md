# ClipCannon Source Code Map

## File Tree

```
src/
    clipcannon/
        __init__.py                         # Package root. Exports __version__ = "0.1.0"
        server.py                           # MCP server entry point. Creates Server, registers tools, runs stdio transport
        config.py                           # Config loading from ~/.clipcannon/config.json with Pydantic validation and dot-notation access
        exceptions.py                       # Exception hierarchy: ClipCannonError, PipelineError, BillingError, ProvenanceError, DatabaseError, ConfigError, GPUError

        db/
            __init__.py                     # Re-exports get_connection, execute, fetch_one, fetch_all, batch_insert, create_project_db, init_project_directory
            connection.py                   # SQLite connection factory with WAL mode, pragmas, sqlite-vec extension loading, dict row factory
            schema.py                       # Full DDL for 22 core tables + 4 vector tables + indexes. Project directory initialization. PIPELINE_STREAMS list (16 streams). Schema version 1
            queries.py                      # Parameterized query helpers: fetch_one, fetch_all, execute, execute_returning_id, batch_insert, transaction context manager, table_exists, count_rows

        gpu/
            __init__.py                     # Re-exports GPUHealthReport, ModelManager, PRECISION_MAP, auto_detect_precision, get_compute_capability
            precision.py                    # GPU precision auto-detection from CUDA compute capability. PRECISION_MAP dict. validate_gpu_for_pipeline function
            manager.py                      # ModelManager class: LRU model lifecycle, VRAM monitoring, concurrent vs sequential mode, GPUHealthReport dataclass

        provenance/
            __init__.py                     # Re-exports all public API: hashing functions, chain functions, recording functions, Pydantic models
            hasher.py                       # SHA-256 utilities: sha256_file (streaming 8KB chunks), sha256_bytes, sha256_string, sha256_table_content (deterministic row hashing), verify_file_hash
            chain.py                        # Tamper-evident hash chain: compute_chain_hash, verify_chain (walks all records), get_chain_from_genesis, ChainVerificationResult, GENESIS_HASH sentinel
            recorder.py                     # Provenance record CRUD: record_provenance (auto-generates prov_001 IDs), get_provenance_records, get_provenance_record, get_provenance_timeline. Pydantic models: InputInfo, OutputInfo, ModelInfo, ExecutionInfo, ProvenanceRecord

        billing/
            __init__.py                     # Re-exports CREDIT_RATES, CREDIT_PACKAGES, LicenseClient, BalanceInfo, ChargeResult, RefundResult, TransactionRecord, HMAC functions
            credits.py                      # Credit rate definitions (analyze=10, render=2, metadata=1, publish=1), credit packages (starter/creator/pro/studio), estimate_cost, validate_spending_limit, check_spending_warning
            hmac_integrity.py               # HMAC-SHA256 balance signing using machine-derived key. get_machine_id, sign_balance, verify_balance, verify_balance_or_raise
            license_client.py               # Async HTTP client for license server on port 3100. LicenseClient class, BalanceInfo, ChargeResult, RefundResult, TransactionRecord models

        tools/
            __init__.py                     # Tool registry. Combines all tool definitions (27 total) and dispatcher functions from 6 modules into ALL_TOOL_DEFINITIONS and TOOL_DISPATCHERS
            project.py                      # 5 project tools: create, open, list, status, delete. Handles ffprobe, SHA-256 hashing, directory creation, provenance recording
            provenance_tools.py             # 4 provenance tools: verify, query, chain, timeline. Wraps provenance module functions as MCP tools
            disk.py                         # 2 disk tools: status, cleanup. Three-tier file classification (sacred/regenerable/ephemeral). Cleanup deletes ephemeral first, then regenerable largest-first
            config_tools.py                 # 3 config tools: get, set, list. Dot-notation access to config values with Pydantic validation on set
            billing_tools.py                # 4 billing tools: credits_balance, credits_history, credits_estimate, spending_limit. Uses LicenseClient to communicate with license server
            understanding.py                # 4 understanding tools: ingest, get_vud_summary, get_analytics, get_transcript. Pipeline orchestration entry point. Shared helpers used by sibling modules
            understanding_visual.py         # 4 visual tools: get_frame, get_frame_strip, get_storyboard, get_segment_detail. Frame lookup, grid composition via Pillow, moment context aggregation
            understanding_search.py         # 1 search tool: search_content. Semantic search via sqlite-vec + Nomic embeddings (sentence-transformers), text search fallback via SQL LIKE
            video_probe.py                  # FFprobe wrapper: run_ffprobe, extract_video_metadata, detect_vfr, SUPPORTED_FORMATS set

        pipeline/
            __init__.py                     # Re-exports PipelineOrchestrator, PipelineResult, PipelineStage, StageResult, and 11 stage run functions
            orchestrator.py                 # DAG-based pipeline runner. Resolves dependencies via topological sort, runs stages, tracks timing, writes stream_status. StageResult, PipelineResult models
            dag.py                          # Topological sort (Kahn's algorithm) for dependency resolution. update_stream_status helper for stream_status table
            registry.py                     # Builds the full pipeline DAG with all 20 stages and their dependencies. build_pipeline function returns configured PipelineOrchestrator
            probe.py                        # Stage: FFprobe metadata extraction and VFR detection
            vfr_normalize.py                # Stage: Variable frame rate normalization to constant frame rate via FFmpeg
            audio_extract.py                # Stage: Audio track extraction from source video via FFmpeg
            source_separation.py            # Stage: Audio source separation into vocal/music stems via Demucs
            frame_extract.py                # Stage: Frame extraction at configured FPS via FFmpeg
            visual_embed.py                 # Stage: Visual embeddings from frames via SigLIP model (float[1152])
            ocr.py                          # Stage: On-screen text detection via PaddleOCR
            quality.py                      # Stage: Frame quality assessment (blur, exposure, noise scoring)
            shot_type.py                    # Stage: Shot type classification from scene key frames
            transcribe.py                   # Stage: Speech-to-text via WhisperX with forced alignment and speaker diarization
            semantic_embed.py               # Stage: Semantic embeddings from transcript via Nomic Embed (float[768])
            emotion_embed.py                # Stage: Emotion embeddings from vocal stem via Wav2Vec2 (float[1024])
            speaker_embed.py                # Stage: Speaker embeddings from vocal stem via WavLM (float[512])
            reactions.py                    # Stage: Reaction detection (laughter, applause, etc.) from vocal stem via SenseVoice
            acoustic.py                     # Stage: Acoustic analysis (volume, dynamic range, silence detection)
            chronemic.py                    # Stage: Pacing/chronemic analysis (words per minute, pause ratios, speaker changes)
            profanity.py                    # Stage: Profanity detection and content safety rating from transcript
            highlights.py                   # Stage: Multi-signal highlight scoring (emotion, reaction, semantic, visual, quality, speaker, narrative)
            storyboard.py                   # Stage: Storyboard grid generation from extracted frames
            finalize.py                     # Stage: Final status update, marks project as ready
            source_resolution.py            # Helpers: resolve_source_path (original or CFR), resolve_audio_input (extracted audio path)

        dashboard/
            __init__.py                     # Re-exports create_app
            app.py                          # FastAPI application factory for dashboard on port 3200. CORS middleware, static file serving, route registration
            auth.py                         # JWT-based dev-mode authentication. Dev-login auto-auth endpoint, HTTP-only session cookie, 30-day TTL. CLIPCANNON_JWT_SECRET env var
            routes/
                __init__.py                 # Re-exports home_router, credits_router, projects_router, provenance_router
                home.py                     # Dashboard home and health check endpoints
                credits.py                  # Credit balance and history API endpoints
                projects.py                 # Project listing and status API endpoints
                provenance.py               # Provenance chain and timeline API endpoints

    license_server/
        __init__.py                         # Package docstring. License server for credit billing and HMAC integrity
        server.py                           # FastAPI app on port 3100. SQLite-backed credit balance with HMAC integrity. Endpoints: charge, refund, balance, history, spending_limit. Dev mode starts with 100 credits
        stripe_webhooks.py                  # Stripe checkout.session.completed webhook handler. Manual credit add endpoint for dev testing. STRIPE_WEBHOOK_SECRET env var
        d1_sync.py                          # Cloudflare D1 sync stub. Phase 1 is local-only. Interface designed for future D1 integration. CLIPCANNON_D1_API_URL and CLIPCANNON_D1_API_TOKEN env vars
```

## Module Dependency Graph

The arrows indicate "imports from" relationships between ClipCannon's own modules.

```
server.py
    -> clipcannon.__init__ (__version__)
    -> clipcannon.tools (ALL_TOOL_DEFINITIONS, TOOL_DISPATCHERS)

clipcannon.tools.__init__
    -> clipcannon.tools.billing_tools
    -> clipcannon.tools.config_tools
    -> clipcannon.tools.disk
    -> clipcannon.tools.project
    -> clipcannon.tools.provenance_tools
    -> clipcannon.tools.understanding
    -> clipcannon.tools.understanding_search
    -> clipcannon.tools.understanding_visual

clipcannon.tools.project
    -> clipcannon.config (ClipCannonConfig)
    -> clipcannon.db.connection (get_connection)
    -> clipcannon.db.queries (execute, fetch_all, fetch_one)
    -> clipcannon.db.schema (PIPELINE_STREAMS, init_project_directory)
    -> clipcannon.exceptions (ClipCannonError)
    -> clipcannon.provenance (ExecutionInfo, InputInfo, OutputInfo, record_provenance, sha256_file)
    -> clipcannon.tools.video_probe (SUPPORTED_FORMATS, detect_vfr, extract_video_metadata, run_ffprobe)

clipcannon.tools.understanding
    -> clipcannon.config (ClipCannonConfig)
    -> clipcannon.db.connection (get_connection)
    -> clipcannon.db.queries (execute, fetch_all, fetch_one)
    -> clipcannon.exceptions (ClipCannonError)
    -> clipcannon.pipeline.registry (build_pipeline)  [lazy import inside clipcannon_ingest]

clipcannon.tools.understanding_visual
    -> clipcannon.db.connection (get_connection)
    -> clipcannon.db.queries (fetch_all, fetch_one)
    -> clipcannon.tools.understanding (_db_path, _error, _project_dir, _validate_project)

clipcannon.tools.understanding_search
    -> clipcannon.db.connection (get_connection)
    -> clipcannon.db.queries (fetch_all, fetch_one)
    -> clipcannon.tools.understanding (_db_path, _error, _validate_project)

clipcannon.tools.billing_tools
    -> clipcannon.billing.credits (CREDIT_RATES, check_spending_warning, estimate_cost)
    -> clipcannon.billing.license_client (LicenseClient)

clipcannon.tools.config_tools
    -> clipcannon.config (ClipCannonConfig, ConfigValue)
    -> clipcannon.exceptions (ConfigError)

clipcannon.tools.disk
    -> clipcannon.config (ClipCannonConfig)
    -> clipcannon.exceptions (ClipCannonError)

clipcannon.tools.provenance_tools
    -> clipcannon.config (ClipCannonConfig)
    -> clipcannon.exceptions (ClipCannonError)
    -> clipcannon.provenance (get_chain_from_genesis, get_provenance_records, get_provenance_timeline, verify_chain)

clipcannon.config
    -> clipcannon.exceptions (ConfigError)

clipcannon.db.connection
    -> clipcannon.exceptions (DatabaseError)

clipcannon.db.schema
    -> clipcannon.db.connection (get_connection)
    -> clipcannon.exceptions (DatabaseError)

clipcannon.db.queries
    -> clipcannon.exceptions (DatabaseError)

clipcannon.provenance.hasher
    -> clipcannon.exceptions (ProvenanceError)

clipcannon.provenance.chain
    -> clipcannon.db.connection (get_connection)
    -> clipcannon.db.queries (fetch_all, fetch_one)
    -> clipcannon.exceptions (ProvenanceError)

clipcannon.provenance.recorder
    -> clipcannon.db.connection (get_connection)
    -> clipcannon.db.queries (count_rows, execute, fetch_all, fetch_one)
    -> clipcannon.exceptions (ProvenanceError)
    -> clipcannon.provenance.chain (GENESIS_HASH, compute_chain_hash)

clipcannon.gpu.precision
    -> clipcannon.exceptions (GPUError)

clipcannon.gpu.manager
    -> clipcannon.exceptions (GPUError)
    -> clipcannon.gpu.precision (auto_detect_precision, get_compute_capability)

clipcannon.billing.credits
    -> clipcannon.exceptions (BillingError)

clipcannon.billing.hmac_integrity
    -> clipcannon.exceptions (BillingError)

clipcannon.billing.license_client
    -> clipcannon.billing.credits (estimate_cost)
    -> clipcannon.billing.hmac_integrity (get_machine_id)

clipcannon.pipeline.orchestrator
    -> clipcannon.config (ClipCannonConfig)
    -> clipcannon.exceptions (PipelineError)
    -> clipcannon.pipeline.dag (topological_sort, update_stream_status)

clipcannon.pipeline.dag
    -> clipcannon.db.connection (get_connection)
    -> clipcannon.db.queries (execute, fetch_one)
    -> clipcannon.exceptions (PipelineError)

clipcannon.pipeline.registry
    -> clipcannon.pipeline.orchestrator (PipelineOrchestrator, PipelineStage)
    -> clipcannon.pipeline.* (all 20 stage run functions)

clipcannon.dashboard.app
    -> clipcannon.__init__ (__version__)
    -> clipcannon.dashboard.auth (is_dev_mode)
    -> clipcannon.dashboard.routes (all 4 routers)

clipcannon.dashboard.auth
    -> (no clipcannon imports, uses jose for JWT)

license_server.server
    -> clipcannon.billing.hmac_integrity (get_machine_id, sign_balance, verify_balance_or_raise)
    -> clipcannon.exceptions (BillingError)

license_server.stripe_webhooks
    -> clipcannon.billing.hmac_integrity (sign_balance)

license_server.d1_sync
    -> (no clipcannon imports, environment variable checks only)
```

## Entry Points

### Console Script: `clipcannon`

Defined in `pyproject.toml` under `[project.scripts]`:

```
clipcannon = "clipcannon.server:main"
```

Calls `server.main()` which sets up structured JSON logging to stderr, creates the MCP Server with all 27 tools registered, and runs it on stdio transport via `asyncio.run(run_stdio())`.

### License Server

```
uvicorn license_server.server:app --port 3100
```

The `license_server.server` module defines a FastAPI `app` object. It creates `~/.clipcannon/license.db` on first run, initializes the balance table with 100 credits in dev mode, and exposes REST endpoints for charges, refunds, balance queries, history, and spending limits. All balance reads and writes are HMAC-verified.

### Dashboard

```
uvicorn clipcannon.dashboard.app:app --port 3200
```

The `clipcannon.dashboard.app` module defines a FastAPI application with CORS middleware, static file serving from `dashboard/static/`, and four route groups: home, credits, projects, provenance. Authentication uses a dev-mode JWT auto-login flow.

## Wheel Build Targets

From `pyproject.toml`:

```
[tool.hatch.build.targets.wheel]
packages = ["src/clipcannon", "src/license_server"]
```

Both `clipcannon` and `license_server` packages are included in the built wheel.
