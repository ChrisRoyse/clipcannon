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
            schema.py                       # Full DDL for 29 core tables + 4 vector tables + indexes. Phase 2/3 migrations. PROJECT_SUBDIRS includes edits/ and renders/
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

        editing/                            # Edit Decision List engine
            __init__.py                     # Re-exports EDL models, PLATFORM_ASPECTS, caption/crop functions
            edl.py                          # EDL Pydantic models: EditDecisionList, SegmentSpec, TransitionSpec, CaptionSpec, CropSpec, AudioSpec, SplitScreenSpec, PipSpec, CanvasSpec, MetadataSpec, MotionSpec, OverlaySpec, ColorSpec, RenderSettingsSpec. validate_edl, compute_total_duration
            captions.py                     # Adaptive caption chunking: chunk_transcript_words (max 3 words, punctuation breaks, speech rate adaptation), fetch_words_for_segments, remap_timestamps
            caption_render.py               # ASS subtitle file generation (4 styles: bold_centered, word_highlight, subtitle_bar, karaoke) and FFmpeg drawtext filter generation
            smart_crop.py                   # Content-aware cropping: detect_faces (MediaPipe/InsightFace), compute_crop_region, smooth_crop_positions, compute_split_screen_layout, compute_pip_layout, fit_mode scaling
            metadata_gen.py                 # Platform-specific metadata generation: generate_metadata produces title, description, hashtags, thumbnail_timestamp_ms from VUD data
            auto_trim.py                    # Automated filler word and pause removal: analyzes transcript to generate clean segments
            measure_layout.py               # Face detection + layout coordinate computation: computes precise canvas regions for layouts A/B/C/D
            motion.py                       # Motion effects: zoom_in, zoom_out, pan_left/right/up/down, ken_burns with configurable easing
            overlays.py                     # Visual overlays: lower_third, title_card, logo, watermark, cta with position, timing, animation
            subject_extraction.py           # AI background removal via rembg: extract_subject generates alpha mask frames

        rendering/                          # Video rendering engine
            __init__.py                     # Re-exports RenderEngine, RenderResult, EncodingProfile, generate_thumbnail, get_profile, list_profiles
            renderer.py                     # RenderEngine class: async render pipeline (source validation, caption write, crop compute, FFmpeg execution, thumbnail, provenance, DB update)
            ffmpeg_cmd.py                   # FFmpeg command builder: build_ffmpeg_cmd (dispatches to standard/split_screen/pip/canvas builders), build_encoding_args, xfade transitions, per-segment canvas compositing, animated zoom, fit_mode scaling, blur background, delogo region removal
            profiles.py                     # 7 encoding profiles (tiktok_vertical, instagram_reels, youtube_shorts, youtube_standard, youtube_4k, facebook, linkedin), get_software_fallback
            thumbnail.py                    # generate_thumbnail: extract JPEG frame at timestamp with optional crop
            inspector.py                    # Render inspection: extract frames at 5 key timestamps, probe metadata, run quality checks
            preview.py                      # Preview generation: low-quality 540p preview clips, canvas layout preview frames, segment previews

        audio/                              # Audio generation engine
            __init__.py                     # Re-exports MidiResult, MixResult, MusicResult, SfxResult, CleanupResult, PRESETS, SAMPLE_RATE, SUPPORTED_EFFECTS, SUPPORTED_CLEANUP_OPS, SUPPORTED_SFX_TYPES, all generation functions
            effects.py                      # Audio effects chain via pedalboard: reverb, compression, eq_low_cut, eq_high_cut, limiter. apply_effects function
            midi_compose.py                 # MIDI composition from 6 presets with theory-correct chord progressions, melody patterns, optional drums. compose_midi function, PresetConfig, MidiResult
            midi_render.py                  # MIDI-to-WAV rendering via FluidSynth/SoundFont. render_midi_to_wav async function
            mixer.py                        # Audio mixing with speech-aware ducking: mix_audio layers music+speech+SFX with RMS-based speech detection, peak normalization. MixResult
            music_gen.py                    # AI music generation via ACE-Step v1.5 diffusion model. generate_music async function, MusicResult
            sfx.py                          # 9 DSP sound effects (whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger). generate_sfx function, SfxResult
            cleanup.py                      # Audio cleanup: noise reduction, normalization, silence trimming, EQ adjustment. cleanup_audio function, CleanupResult, SUPPORTED_CLEANUP_OPS

        voice/                              # Voice cloning engine (Phase 3)
            __init__.py                     # Package docstring
            data_prep.py                    # Voice training data preparation: silence-boundary splitting, transcript matching, phonemization, train/val manifests
            inference.py                    # VoiceSynthesizer class: Qwen3-TTS integration with iterative verification loop, reference audio/embedding support, SpeakResult
            verify.py                       # Multi-gate voice verification: VoiceVerifier with sanity (duration/clipping/SNR/silence), intelligibility (WER via Whisper), identity (SECS via ECAPA-VOXCELEB)
            optimize.py                     # SECS-optimized synthesis: best-of-N candidate selection, reference clip scoring, OptimizedSpeakResult
            profiles.py                     # Voice profile SQLite CRUD: create/get/list/update/delete profiles in ~/.clipcannon/voice_profiles.db

        avatar/                             # Avatar / lip-sync engine (Phase 3)
            lip_sync.py                     # LipSyncEngine: LatentSync 1.6 (ByteDance) diffusion pipeline, VAE + UNet3D + DDIM scheduler, 512x512 output, LipSyncResult

        tools/
            __init__.py                     # Tool registry. Combines all tool definitions (51 total) and dispatcher functions from 13 modules into ALL_TOOL_DEFINITIONS and TOOL_DISPATCHERS
            project.py                      # 5 project tools: create, open, list, status, delete
            provenance_tools.py             # Provenance tools (definitions exported but currently empty list; provenance accessed via dashboard/direct DB)
            disk.py                         # 2 disk tools: status, cleanup
            config_tools.py                 # 3 config tools: get, set, list
            billing_tools.py                # 4 billing tools: credits_balance, credits_history, credits_estimate, spending_limit
            understanding.py                # 2 understanding tools: ingest, get_transcript
            understanding_visual.py         # 1 visual tool: get_frame
            understanding_search.py         # 1 search tool: search_content
            video_probe.py                  # FFprobe wrapper: run_ffprobe, extract_video_metadata, detect_vfr, SUPPORTED_FORMATS
            editing.py                      # 11 editing tools: create_edit, modify_edit, auto_trim, color_adjust, add_motion, add_overlay, edit_history, revert_edit, apply_feedback, branch_edit, list_branches. dispatch_editing_tool
            editing_defs.py                 # JSON schema definitions for 11 editing MCP tools
            editing_helpers.py              # Builder functions for EDL construction (build_segments, build_caption_spec, build_crop_spec, etc.), DB storage helpers
            rendering.py                    # 8 rendering tools: render, get_editing_context, analyze_frame, preview_clip, inspect_render, preview_layout, get_scene_map, preview_segment. dispatch_rendering_tool
            rendering_defs.py               # JSON schema definitions for 8 rendering MCP tools
            audio.py                        # 4 audio tools: generate_music, compose_midi, generate_sfx, audio_cleanup. dispatch_audio_tool
            discovery.py                    # 4 discovery tools: find_best_moments, find_cut_points, get_narrative_flow, find_safe_cuts. dispatch_discovery_tool
            discovery_defs.py               # JSON schema definitions for 4 discovery MCP tools
            voice.py                        # 4 voice tools: prepare_voice_data, voice_profiles, speak, speak_optimized. dispatch_voice_tool
            voice_defs.py                   # JSON schema definitions for 4 voice MCP tools
            avatar.py                       # 1 avatar tool: lip_sync. dispatch_avatar_tool
            avatar_defs.py                  # JSON schema definition for lip_sync tool
            generate_video.py               # 1 generate tool: generate_video (end-to-end voice + lip-sync). dispatch_generate_tool
            generate_defs.py                # JSON schema definition for generate_video tool
            storyboard.py                   # Contact sheet generation: build_contact_sheet creates grid of all frames with timestamps

        pipeline/
            __init__.py                     # Re-exports PipelineOrchestrator, PipelineResult, PipelineStage, StageResult, and stage run functions
            orchestrator.py                 # DAG-based pipeline runner. Resolves dependencies via topological sort, runs stages, tracks timing, writes stream_status
            dag.py                          # Topological sort (Kahn's algorithm) for dependency resolution. update_stream_status helper
            registry.py                     # Builds the full pipeline DAG with all 21 stages and their dependencies
            probe.py                        # Stage: FFprobe metadata extraction and VFR detection
            vfr_normalize.py                # Stage: Variable frame rate normalization to constant frame rate via FFmpeg
            audio_extract.py                # Stage: Audio track extraction from source video via FFmpeg
            source_separation.py            # Stage: Audio source separation into vocal/music stems via Demucs
            frame_extract.py                # Stage: Frame extraction at configured FPS via FFmpeg
            visual_embed.py                 # Stage: Visual embeddings from frames via SigLIP model (float[1152]), scene detection
            ocr.py                          # Stage: On-screen text detection via PaddleOCR with inline image support
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
            scene_analysis.py               # Stage: Scene boundary detection, face/webcam/content region analysis, canvas region pre-computation for layouts A/B/C/D. Creates scene_map table.
            screen_layout.py                # Screen layout detection: identifies webcam overlay, content area, browser chrome regions
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
                editing.py                  # Edit CRUD, listing with status filter
                review.py                   # Review queue, batch approve/reject workflow
                timeline.py                 # Visual timeline with scenes, speakers, emotion, topics, highlights

    license_server/
        __init__.py                         # Package docstring
        server.py                           # FastAPI app on port 3100. SQLite-backed credit balance with HMAC integrity
        stripe_webhooks.py                  # Stripe checkout.session.completed webhook handler
        d1_sync.py                          # Cloudflare D1 sync stub (local-only)
```

## Module Dependency Graph

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
    -> clipcannon.tools.editing
    -> clipcannon.tools.editing_defs
    -> clipcannon.tools.rendering
    -> clipcannon.tools.rendering_defs
    -> clipcannon.tools.audio
    -> clipcannon.tools.discovery
    -> clipcannon.tools.discovery_defs
    -> clipcannon.tools.voice
    -> clipcannon.tools.voice_defs
    -> clipcannon.tools.avatar
    -> clipcannon.tools.avatar_defs
    -> clipcannon.tools.generate_video
    -> clipcannon.tools.generate_defs

clipcannon.tools.editing
    -> clipcannon.editing.edl (EditDecisionList, CanvasSpec, ColorSpec, MotionSpec, OverlaySpec, RenderSettingsSpec, validate_edl, compute_total_duration)
    -> clipcannon.editing.captions (chunk_transcript_words, fetch_words_for_segments, remap_timestamps)
    -> clipcannon.editing.metadata_gen (generate_metadata)
    -> clipcannon.editing.auto_trim (auto_trim_segments)
    -> clipcannon.editing.motion (apply_motion_to_edl)
    -> clipcannon.editing.overlays (apply_overlay_to_edl)
    -> clipcannon.editing.subject_extraction (extract_subject, replace_background)
    -> clipcannon.tools.editing_helpers (builders, validators, DB storage)
    -> clipcannon.tools.editing_defs (EDITING_TOOL_DEFINITIONS)

clipcannon.tools.rendering
    -> clipcannon.rendering.renderer (RenderEngine)
    -> clipcannon.rendering.profiles (get_profile)
    -> clipcannon.rendering.inspector (inspect_render)
    -> clipcannon.rendering.preview (preview_clip, preview_layout_frame, preview_segment)
    -> clipcannon.editing.measure_layout (measure_layout_regions)
    -> clipcannon.tools.storyboard (build_contact_sheet)
    -> clipcannon.pipeline.scene_analysis (get_scene_map)
    -> clipcannon.billing.license_client (LicenseClient)
    -> clipcannon.tools.rendering_defs (RENDERING_TOOL_DEFINITIONS)

clipcannon.tools.audio
    -> clipcannon.audio.music_gen (generate_music)
    -> clipcannon.audio.midi_compose (compose_midi)
    -> clipcannon.audio.midi_render (render_midi_to_wav)
    -> clipcannon.audio.sfx (generate_sfx)
    -> clipcannon.audio.cleanup (cleanup_audio)

clipcannon.tools.voice
    -> clipcannon.voice.data_prep (prepare_voice_training_data)
    -> clipcannon.voice.profiles (create/get/list/update/delete_voice_profile)
    -> clipcannon.voice.inference (VoiceSynthesizer)
    -> clipcannon.voice.optimize (optimized_speak)
    -> clipcannon.voice.verify (VoiceVerifier, build_reference_embedding)

clipcannon.tools.avatar
    -> clipcannon.avatar.lip_sync (get_engine, LipSyncEngine)

clipcannon.tools.generate_video
    -> clipcannon.tools.voice (_handle_speak)
    -> clipcannon.tools.avatar (_handle_lip_sync)

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

clipcannon.pipeline.registry
    -> clipcannon.pipeline.orchestrator (PipelineOrchestrator, PipelineStage)
    -> clipcannon.pipeline.scene_analysis (run_scene_analysis)
    -> clipcannon.pipeline.* (all 21 stage run functions)

clipcannon.dashboard.app
    -> clipcannon.__init__ (__version__)
    -> clipcannon.dashboard.auth (is_dev_mode)
    -> clipcannon.dashboard.routes (all 7 routers)
```

## Entry Points

### Console Script: `clipcannon`

Defined in `pyproject.toml` under `[project.scripts]`:

```
clipcannon = "clipcannon.server:main"
```

Calls `server.main()` which sets up structured JSON logging to stderr, creates the MCP Server with all 51 tools registered, and runs it on stdio transport via `asyncio.run(run_stdio())`.

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
