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
            schema.py                       # Full DDL for 26 core tables + 4 vector tables + indexes. Phase 2 migration. PROJECT_SUBDIRS includes edits/ and renders/
            queries.py                      # Parameterized query helpers: fetch_one, fetch_all, execute, execute_returning_id, batch_insert, transaction context manager, table_exists, count_rows

        gpu/
            __init__.py                     # Re-exports GPUHealthReport, ModelManager, PRECISION_MAP, auto_detect_precision, get_compute_capability
            precision.py                    # GPU precision auto-detection from CUDA compute capability. PRECISION_MAP dict. validate_gpu_for_pipeline function
            manager.py                      # ModelManager class: LRU model lifecycle, VRAM monitoring, concurrent vs sequential mode, GPUHealthReport dataclass

        provenance/
            __init__.py                     # Re-exports all public API: hashing functions, chain functions, recording functions, Pydantic models
            hasher.py                       # SHA-256 utilities: sha256_file (streaming 8KB chunks), sha256_bytes, sha256_string, sha256_table_content, verify_file_hash
            chain.py                        # Tamper-evident hash chain: compute_chain_hash, verify_chain, get_chain_from_genesis, ChainVerificationResult, GENESIS_HASH
            recorder.py                     # Provenance record CRUD: record_provenance (auto-generates prov_001 IDs), get_provenance_records, get_provenance_record, get_provenance_timeline

        billing/
            __init__.py                     # Re-exports CREDIT_RATES, CREDIT_PACKAGES, LicenseClient, BalanceInfo, ChargeResult, RefundResult, TransactionRecord, HMAC functions
            credits.py                      # Credit rate definitions (analyze=10, render=2, metadata=1, publish=1), credit packages, estimate_cost, spending limits
            hmac_integrity.py               # HMAC-SHA256 balance signing using machine-derived key. get_machine_id, sign_balance, verify_balance, verify_balance_or_raise
            license_client.py               # Async HTTP client for license server on port 3100. LicenseClient class, BalanceInfo, ChargeResult, RefundResult, TransactionRecord models

        editing/                            # Phase 2: Edit Decision List engine
            __init__.py                     # Re-exports EDL models (EditDecisionList, SegmentSpec, CaptionSpec, CropSpec, AudioSpec), PLATFORM_ASPECTS, caption/crop functions
            edl.py                          # EDL Pydantic models: EditDecisionList, SegmentSpec, TransitionSpec, CaptionSpec, CropSpec, AudioSpec, SplitScreenSpec, PipSpec, CanvasSpec, MetadataSpec. validate_edl, compute_total_duration
            captions.py                     # Adaptive caption chunking: chunk_transcript_words (max 3 words, punctuation breaks, speech rate adaptation), fetch_words_for_segments, remap_timestamps
            caption_render.py               # ASS subtitle file generation (4 styles: bold_centered, word_highlight, subtitle_bar, karaoke) and FFmpeg drawtext filter generation
            smart_crop.py                   # Content-aware cropping: detect_faces (MediaPipe/InsightFace), compute_crop_region, smooth_crop_positions, compute_split_screen_layout, compute_pip_layout
            metadata_gen.py                 # Platform-specific metadata generation: generate_metadata produces title, description, hashtags, thumbnail_timestamp_ms from VUD data

        rendering/                          # Phase 2: Video rendering engine
            __init__.py                     # Re-exports RenderEngine, RenderResult, EncodingProfile, generate_thumbnail, get_profile, list_profiles, render_batch
            renderer.py                     # RenderEngine class: async render pipeline (source validation, caption write, crop compute, FFmpeg execution, thumbnail, provenance, DB update)
            ffmpeg_cmd.py                   # FFmpeg command builder: build_ffmpeg_cmd (dispatches to standard/split_screen/pip/canvas builders), build_encoding_args, xfade transitions
            profiles.py                     # 7 encoding profiles (tiktok_vertical, instagram_reels, youtube_shorts, youtube_standard, youtube_4k, facebook, linkedin), get_software_fallback
            batch.py                        # render_batch: concurrent rendering with asyncio.Semaphore (max_concurrent=3)
            thumbnail.py                    # generate_thumbnail: extract JPEG frame at timestamp with optional crop

        audio/                              # Phase 2: Audio generation engine
            __init__.py                     # Re-exports MidiResult, MixResult, MusicResult, SfxResult, PRESETS, SAMPLE_RATE, SUPPORTED_EFFECTS, SUPPORTED_SFX_TYPES, all generation functions
            effects.py                      # Audio effects chain via pedalboard: reverb, compression, eq_low_cut, eq_high_cut, limiter. apply_effects function
            midi_compose.py                 # MIDI composition from 6 presets with theory-correct chord progressions, melody patterns, optional drums. compose_midi function, PresetConfig, MidiResult
            midi_render.py                  # MIDI-to-WAV rendering via FluidSynth/SoundFont. render_midi_to_wav async function
            mixer.py                        # Audio mixing with speech-aware ducking: mix_audio layers music+speech+SFX with RMS-based speech detection, peak normalization. MixResult
            music_gen.py                    # AI music generation via ACE-Step v1.5 diffusion model. generate_music async function, MusicResult
            sfx.py                          # 9 DSP sound effects (whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger). generate_sfx function, SfxResult

        tools/
            __init__.py                     # Tool registry. Combines all tool definitions (37 total) and dispatcher functions from 9 modules into ALL_TOOL_DEFINITIONS and TOOL_DISPATCHERS
            project.py                      # 5 project tools: create, open, list, status, delete
            provenance_tools.py             # 4 provenance tools: verify, query, chain, timeline
            disk.py                         # 2 disk tools: status, cleanup
            config_tools.py                 # 3 config tools: get, set, list
            billing_tools.py                # 4 billing tools: credits_balance, credits_history, credits_estimate, spending_limit
            understanding.py                # 4 understanding tools: ingest, get_vud_summary, get_analytics, get_transcript
            understanding_visual.py         # 4 visual tools: get_frame, get_frame_strip, get_storyboard, get_segment_detail
            understanding_search.py         # 1 search tool: search_content
            video_probe.py                  # FFprobe wrapper: run_ffprobe, extract_video_metadata, detect_vfr, SUPPORTED_FORMATS
            editing.py                      # Phase 2: 4 editing tools: create_edit, modify_edit, list_edits, generate_metadata. dispatch_editing_tool
            editing_defs.py                 # Phase 2: JSON schema definitions for 4 editing MCP tools
            editing_helpers.py              # Phase 2: Builder functions for EDL construction (build_segments, build_caption_spec, build_crop_spec, etc.), DB storage helpers
            rendering.py                    # Phase 2: 3 rendering tools: render, render_status, render_batch. dispatch_rendering_tool
            rendering_defs.py               # Phase 2: JSON schema definitions for 3 rendering MCP tools
            audio.py                        # Phase 2: 3 audio tools: generate_music, compose_midi, generate_sfx. dispatch_audio_tool with AUDIO_TOOL_DEFINITIONS

        pipeline/
            __init__.py                     # Re-exports PipelineOrchestrator, PipelineResult, PipelineStage, StageResult, and 11 stage run functions
            orchestrator.py                 # DAG-based pipeline runner. Resolves dependencies via topological sort, runs stages, tracks timing, writes stream_status
            dag.py                          # Topological sort (Kahn's algorithm) for dependency resolution. update_stream_status helper
            registry.py                     # Builds the full pipeline DAG with all 20 stages and their dependencies
            probe.py                        # Stage: FFprobe metadata extraction and VFR detection
            vfr_normalize.py                # Stage: Variable frame rate normalization to constant frame rate via FFmpeg
            audio_extract.py                # Stage: Audio track extraction from source video via FFmpeg
            source_separation.py            # Stage: Audio source separation into vocal/music stems via Demucs
            frame_extract.py                # Stage: Frame extraction at configured FPS via FFmpeg
            visual_embed.py                 # Stage: Visual embeddings from frames via SigLIP model (float[1152]), scene detection
            ocr.py                          # Stage: On-screen text detection via PaddleOCR
            quality.py                      # Stage: Frame quality assessment (blur, exposure, noise scoring)
            shot_type.py                    # Stage: Shot type classification (extreme_closeup/closeup/medium/wide/establishing) with crop recommendations
            transcribe.py                   # Stage: Speech-to-text via WhisperX with anti-hallucination filtering (35 known phrases, confidence thresholds, VAD tuning)
            semantic_embed.py               # Stage: Semantic embeddings from transcript via Nomic Embed (float[768])
            emotion_embed.py                # Stage: Emotion embeddings from vocal stem via Wav2Vec2 (float[1024])
            speaker_embed.py                # Stage: Speaker embeddings from vocal stem via WavLM (float[512])
            reactions.py                    # Stage: Reaction detection (laughter, applause) via SenseVoice
            acoustic.py                     # Stage: Acoustic analysis (volume, dynamic range, silence detection)
            chronemic.py                    # Stage: Pacing/chronemic analysis (words per minute, pause ratios, speaker changes)
            profanity.py                    # Stage: Profanity detection and content safety rating from transcript
            highlights.py                   # Stage: Multi-signal highlight scoring (emotion, reaction, semantic, visual, quality, speaker, narrative)
            storyboard.py                   # Stage: Storyboard grid generation from extracted frames
            finalize.py                     # Stage: Final status update, marks project as ready
            source_resolution.py            # Helpers: resolve_source_path, resolve_audio_input

        dashboard/
            __init__.py                     # Re-exports create_app
            app.py                          # FastAPI application factory for dashboard on port 3200. CORS middleware, static file serving, route registration (7 routers)
            auth.py                         # JWT-based dev-mode authentication. Dev-login auto-auth endpoint, HTTP-only session cookie, 30-day TTL
            routes/
                __init__.py                 # Re-exports home_router, credits_router, projects_router, provenance_router, editing_router, review_router, timeline_router
                home.py                     # Dashboard home and health check endpoints
                credits.py                  # Credit balance and history API endpoints
                projects.py                 # Project listing and status API endpoints
                provenance.py               # Provenance chain and timeline API endpoints
                editing.py                  # Phase 2: Edit CRUD, listing with status filter
                review.py                   # Phase 2: Review queue, batch approve/reject workflow
                timeline.py                 # Phase 2: Visual timeline with scenes, speakers, emotion, topics, highlights

    license_server/
        __init__.py                         # Package docstring
        server.py                           # FastAPI app on port 3100. SQLite-backed credit balance with HMAC integrity
        stripe_webhooks.py                  # Stripe checkout.session.completed webhook handler
        d1_sync.py                          # Cloudflare D1 sync stub (local-only in Phase 1)
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
    -> clipcannon.tools.editing          (Phase 2)
    -> clipcannon.tools.editing_defs     (Phase 2)
    -> clipcannon.tools.rendering        (Phase 2)
    -> clipcannon.tools.rendering_defs   (Phase 2)
    -> clipcannon.tools.audio            (Phase 2)

clipcannon.tools.editing
    -> clipcannon.editing.edl (EditDecisionList, validate_edl, compute_total_duration)
    -> clipcannon.editing.captions (chunk_transcript_words, fetch_words_for_segments, remap_timestamps)
    -> clipcannon.editing.metadata_gen (generate_metadata)
    -> clipcannon.tools.editing_helpers (builders, validators, DB storage)
    -> clipcannon.tools.editing_defs (EDITING_TOOL_DEFINITIONS)

clipcannon.tools.rendering
    -> clipcannon.rendering.renderer (RenderEngine)
    -> clipcannon.rendering.profiles (get_profile)
    -> clipcannon.billing.license_client (LicenseClient)
    -> clipcannon.tools.rendering_defs (RENDERING_TOOL_DEFINITIONS)

clipcannon.tools.audio
    -> clipcannon.audio.music_gen (generate_music)
    -> clipcannon.audio.midi_compose (compose_midi)
    -> clipcannon.audio.midi_render (render_midi_to_wav)
    -> clipcannon.audio.sfx (generate_sfx)

clipcannon.rendering.renderer
    -> clipcannon.rendering.ffmpeg_cmd (build_ffmpeg_cmd, build_encoding_args)
    -> clipcannon.rendering.profiles (get_profile, get_software_fallback)
    -> clipcannon.rendering.thumbnail (generate_thumbnail)
    -> clipcannon.editing.caption_render (generate_ass_file)
    -> clipcannon.editing.smart_crop (compute_crop_region, get_crop_for_scene)
    -> clipcannon.provenance (record_provenance, sha256_file)

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

clipcannon.dashboard.app
    -> clipcannon.__init__ (__version__)
    -> clipcannon.dashboard.auth (is_dev_mode)
    -> clipcannon.dashboard.routes (all 7 routers)

clipcannon.pipeline.registry
    -> clipcannon.pipeline.orchestrator (PipelineOrchestrator, PipelineStage)
    -> clipcannon.pipeline.* (all 20 stage run functions)
```

## Entry Points

### Console Script: `clipcannon`

Defined in `pyproject.toml` under `[project.scripts]`:

```
clipcannon = "clipcannon.server:main"
```

Calls `server.main()` which sets up structured JSON logging to stderr, creates the MCP Server with all 37 tools registered, and runs it on stdio transport via `asyncio.run(run_stdio())`.

### License Server

```
uvicorn license_server.server:app --port 3100
```

### Dashboard

```
uvicorn clipcannon.dashboard.app:app --port 3200
```

## Wheel Build Targets

From `pyproject.toml`:

```
[tool.hatch.build.targets.wheel]
packages = ["src/clipcannon", "src/license_server"]
```

Both `clipcannon` and `license_server` packages are included in the built wheel.
