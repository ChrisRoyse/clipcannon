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
            change_classifier.py            # Change classification for iterative editing: classifies EDL modifications by type and scope
            measure_layout.py               # Face detection + layout coordinate computation: computes precise canvas regions for layouts A/B/C/D
            motion.py                       # Motion effects: zoom_in, zoom_out, pan_left/right/up/down, ken_burns with configurable easing
            overlays.py                     # Visual overlays: lower_third, title_card, logo, watermark, cta with position, timing, animation
            subject_extraction.py           # AI background removal via rembg: extract_subject generates alpha mask frames

        rendering/                          # Video rendering engine
            __init__.py                     # Re-exports RenderEngine, RenderResult, EncodingProfile, generate_thumbnail, get_profile, list_profiles
            renderer.py                     # RenderEngine class: async render pipeline (source validation, caption write, crop compute, FFmpeg execution, thumbnail, provenance, DB update)
            ffmpeg_cmd.py                   # FFmpeg command builder: build_ffmpeg_cmd (dispatches to standard/split_screen/pip/canvas builders), build_encoding_args, xfade transitions, per-segment canvas compositing, animated zoom, fit_mode scaling, blur background, delogo region removal
            profiles.py                     # 7 encoding profiles (tiktok_vertical, instagram_reels, youtube_shorts, youtube_standard, youtube_4k, facebook, linkedin), get_software_fallback
            batch.py                        # Batch rendering with asyncio semaphore concurrency control: render_batch for multiple EDLs
            segment_hash.py                 # Deterministic content hashing for segment render cache: compute_segment_hash from source SHA, segment spec, profile, canvas, color, overlays
            thumbnail.py                    # generate_thumbnail: extract JPEG frame at timestamp with optional crop
            inspector.py                    # Render inspection: extract frames at 5 key timestamps, probe metadata, run quality checks
            preview.py                      # Preview generation: low-quality 540p preview clips, canvas layout preview frames, segment previews

        audio/                              # Audio generation engine
            __init__.py                     # Re-exports MidiResult, MidiPlan, MidiSection, MixResult, MusicResult, MusicBrief, SfxResult, CleanupResult, PRESETS, SAMPLE_RATE, SUPPORTED_EFFECTS, SUPPORTED_CLEANUP_OPS, SUPPORTED_SFX_TYPES, all generation functions
            effects.py                      # Audio effects chain via pedalboard: reverb, compression, eq_low_cut, eq_high_cut, limiter. apply_effects function
            midi_compose.py                 # MIDI composition from 12 presets with theory-correct chord progressions, melody patterns, optional drums. compose_midi, compose_midi_sectioned functions, PresetConfig, MidiResult
            midi_render.py                  # MIDI-to-WAV rendering via FluidSynth/SoundFont. render_midi_to_wav async function
            midi_ai.py                      # LLM-driven MIDI planning: plan_midi_from_keywords (keyword matching), plan_midi_from_prompt (Qwen3-8B subprocess). MidiPlan, MidiSection
            mixer.py                        # Audio mixing with speech-aware ducking: mix_audio layers music+speech+SFX with RMS-based speech detection, peak normalization. MixResult
            music_gen.py                    # AI music generation via ACE-Step v1.5 diffusion model. generate_music async function, MusicResult
            musicgen.py                     # AI music generation via Meta AudioCraft MusicGen (small/medium/large). generate_music_musicgen async function, windowed generation for >30s
            music_planner.py                # Video-aware music planning: MusicPlanner.plan_for_edit reads emotion/pacing/beats data to auto-generate MusicBrief (mood, tempo, key, preset, ACE-Step prompt)
            sfx.py                          # 13 DSP sound effects (whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger, ambient_drone, ambient_texture, pad_swell, nature_bed). generate_sfx function, SfxResult
            cleanup.py                      # Audio cleanup: noise reduction, de-hum, de-ess, loudness normalization. cleanup_audio function, CleanupResult, SUPPORTED_CLEANUP_OPS

        voice/                              # Voice cloning engine (Phase 3)
            __init__.py                     # Package docstring
            data_prep.py                    # Voice training data preparation: silence-boundary splitting, transcript matching, phonemization, train/val manifests
            inference.py                    # VoiceSynthesizer class: Qwen3-TTS integration with iterative verification loop, reference audio/embedding support, SpeakResult
            verify.py                       # Multi-gate voice verification: VoiceVerifier with Qwen3-TTS ECAPA-TDNN 2048-dim speaker encoder, sanity (duration/clipping/SNR/silence), intelligibility (WER via Whisper, punctuation-stripped), identity (SECS)
            optimize.py                     # SECS-optimized synthesis: best-of-N candidate selection, reference clip scoring, OptimizedSpeakResult
            profiles.py                     # Voice profile SQLite CRUD: create/get/list/update/delete profiles in ~/.clipcannon/voice_profiles.db
            enhance.py                      # Resemble Enhance post-processing: denoise + latent flow matching, upsamples 24kHz TTS output to 44.1kHz broadcast quality
            multi_voice.py                  # MultiVoiceSynth: instant voice swapping for multi-speaker conversation generation, loads voice prompts once, concatenates segments with configurable pause

        avatar/                             # Avatar / lip-sync engine (Phase 3)
            __init__.py                     # Package docstring
            lip_sync.py                     # LipSyncEngine: LatentSync 1.6 (ByteDance) diffusion pipeline, VAE + UNet3D + DDIM scheduler, 512x512 output, LipSyncResult

        tools/
            __init__.py                     # Tool registry. Combines all tool definitions (53 total) and dispatcher functions from 13 modules into ALL_TOOL_DEFINITIONS and TOOL_DISPATCHERS
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
            audio.py                        # 6 audio tools: generate_music, compose_midi, generate_sfx, audio_cleanup, auto_music, compose_music. dispatch_audio_tool
            audio_defs.py                   # JSON schema definitions for 6 audio MCP tools (separated from audio.py to keep under 500 lines)
            audio_cleanup.py                # Audio cleanup tool implementation: source audio discovery, FFmpeg extraction fallback, cleanup execution
            audio_smart.py                  # Smart music tool implementations: clipcannon_auto_music (video-aware), clipcannon_compose_music (NL description)
            discovery.py                    # 4 discovery tools: find_best_moments, find_cut_points, get_narrative_flow, find_safe_cuts. dispatch_discovery_tool
            discovery_defs.py               # JSON schema definitions for 4 discovery MCP tools
            feedback.py                     # Feedback intent parser: translates natural language feedback into structured EDL changes via regex + keyword detection
            voice.py                        # 4 voice tools: prepare_voice_data, voice_profiles, speak, speak_optimized. dispatch_voice_tool
            voice_defs.py                   # JSON schema definitions for 4 voice MCP tools
            avatar.py                       # 1 avatar tool: lip_sync. dispatch_avatar_tool
            avatar_defs.py                  # JSON schema definition for lip_sync tool
            generate_video.py               # 1 generate tool: generate_video (end-to-end voice + lip-sync). dispatch_generate_tool
            generate_defs.py                # JSON schema definition for generate_video tool
            storyboard.py                   # Contact sheet generation: build_contact_sheet creates grid of all frames with timestamps

        pipeline/
            __init__.py                     # Re-exports PipelineOrchestrator, PipelineResult, PipelineStage, StageResult, and stage run functions
            orchestrator.py                 # DAG-based pipeline runner. Resolves dependencies via topological sort, runs stages with per-stage timeouts, tracks timing, writes stream_status
            dag.py                          # Topological sort (Kahn's algorithm) for dependency resolution. update_stream_status helper
            registry.py                     # Builds the full pipeline DAG with all 22 stages and their dependencies
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
            narrative_llm.py                # Stage: Qwen3-8B narrative structure analysis (story beats, open loops, chapters, key moments). Creates narrative_analysis table.
            storyboard.py                   # Stage: Storyboard grid generation from extracted frames
            scene_analysis.py               # Stage: Scene boundary detection, face/webcam/content region analysis, canvas region pre-computation for layouts A/B/C/D. Creates scene_map table.
            screen_layout.py                # Screen layout detection: identifies webcam overlay, content area, browser chrome regions
            frame_utils.py                  # Shared frame utilities: frame_timestamp_ms computes timestamp from frame filename and extraction FPS
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

    voiceagent/                             # Voice Agent -- real-time conversational AI (separate from ClipCannon)
        __init__.py                         # Package root. Exports __version__ = "0.1.0"
        __main__.py                         # python -m voiceagent entry point -> cli()
        agent.py                            # VoiceAgent orchestrator: lifecycle (DORMANT/LOADING/ACTIVE/UNLOADING), on-demand GPU load/unload, talk_interactive + serve modes
        cli.py                              # Click CLI: serve (WebSocket server), talk (Pipecat + Ollama), talk-legacy (custom vLLM pipeline)
        config.py                           # Frozen dataclass config: LLMConfig, ASRConfig, TTSConfig, ConversationConfig, TransportConfig, GPUConfig. Loads from ~/.voiceagent/config.json
        errors.py                           # Exception hierarchy: VoiceAgentError, ASRError, TTSError, LLMError, ConfigError, DatabaseError, TransportError
        gpu_manager.py                      # GPU worker management: pause_gpu_workers (SIGSTOP), resume_gpu_workers (SIGCONT), force_free_gpu_memory
        pipecat_agent.py                    # Pipecat-based pipeline: Whisper ASR + Ollama LLM + faster-qwen3-tts + Silero VAD + PyAudio transport. All local, no cloud APIs
        pipecat_tts.py                      # Pipecat TTS service wrapping FastTTSAdapter for frame-based streaming
        server.py                           # FastAPI app for WebSocket voice agent server
        wake_listener.py                    # Always-on wake word listener: Silero VAD + faster-whisper tiny (CPU) + sentence embedding similarity. Launches Pipecat agent as subprocess on wake detection

        activation/
            __init__.py                     # Re-exports WakeWordDetector, HotkeyActivator
            wake_word.py                    # "Hey Jarvis" wake word detector using openWakeWord with Silero VAD pre-filter
            hotkey.py                       # Ctrl+Space hotkey activation via pynput

        adapters/
            __init__.py                     # Re-exports
            clipcannon.py                   # ClipCannonAdapter: bridges voice agent TTS to ClipCannon's 1.7B voice engine
            fast_tts.py                     # FastTTSAdapter: faster-qwen3-tts 0.6B with CUDA graphs (~500ms TTFB), runtime voice switching, Full ICL mode

        audio/
            __init__.py                     # Re-exports
            aec_filter.py                   # Acoustic Echo Cancellation filter for Pipecat: mic gating during bot speech + spectral suppression for residual echo
            echo_ref_processor.py           # Pipecat processor: captures speaker output audio as AEC reference signal, tracks bot speaking state
            voice_command_detector.py        # Voice command detector using sentence embedding similarity: intercepts switch commands between STT and LLM

        asr/
            __init__.py                     # Re-exports StreamingASR, VADFilter
            streaming.py                    # StreamingASR: faster-whisper + Silero VAD, chunk-based processing, endpoint detection
            endpointing.py                  # Speech endpoint detection with configurable silence threshold
            types.py                        # ASREvent, ASRConfig types
            vad.py                          # VADFilter: Silero VAD wrapper with configurable threshold

        brain/
            __init__.py                     # Re-exports LLMBrain, ContextManager
            llm.py                          # LLMBrain: vLLM-based Qwen3-14B FP8 local inference with streaming token generation
            context.py                      # ContextManager: sliding window context with token counting, system prompt management
            prompts.py                      # System prompt builder for Jarvis personality, voice-profile-aware prompting

        conversation/
            __init__.py                     # Re-exports ConversationManager
            manager.py                      # ConversationManager: wires ASR -> Brain -> TTS with state transitions, turn logging, echo suppression coordination
            state.py                        # ConversationState enum: IDLE, LISTENING, THINKING, SPEAKING

        db/
            __init__.py                     # Re-exports get_connection, init_db
            connection.py                   # SQLite connection factory with WAL mode for voice agent database
            schema.py                       # DDL: conversations, turns, metrics tables. init_db() idempotent

        transport/
            __init__.py                     # Re-exports
            local_audio.py                  # LocalAudioTransport: PyAudio mic/speaker with echo suppression (bot_speaking gate + post-speech guard window)
            websocket.py                    # WebSocketTransport: FastAPI WebSocket endpoint for remote voice agent clients

        tts/
            __init__.py                     # Re-exports StreamingTTS, SentenceChunker
            chunker.py                      # SentenceChunker: splits LLM output into sentence-sized chunks for streaming TTS
            streaming.py                    # StreamingTTS: chunk-by-chunk synthesis with adapter pattern (FastTTSAdapter or ClipCannonAdapter)
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
    -> clipcannon.audio.musicgen (generate_music_musicgen)
    -> clipcannon.audio.midi_compose (compose_midi, compose_midi_sectioned)
    -> clipcannon.audio.midi_render (render_midi_to_wav)
    -> clipcannon.audio.midi_ai (plan_midi_from_keywords, plan_midi_from_prompt)
    -> clipcannon.audio.music_planner (MusicPlanner)
    -> clipcannon.audio.sfx (generate_sfx)
    -> clipcannon.audio.cleanup (cleanup_audio)
    -> clipcannon.tools.audio_defs (AUDIO_TOOL_DEFINITIONS)
    -> clipcannon.tools.audio_cleanup (run_audio_cleanup)
    -> clipcannon.tools.audio_smart (clipcannon_auto_music, clipcannon_compose_music)

clipcannon.tools.voice
    -> clipcannon.voice.data_prep (prepare_voice_training_data)
    -> clipcannon.voice.profiles (create/get/list/update/delete_voice_profile)
    -> clipcannon.voice.inference (VoiceSynthesizer)
    -> clipcannon.voice.optimize (optimized_speak)
    -> clipcannon.voice.verify (VoiceVerifier, build_reference_embedding)
    -> clipcannon.voice.enhance (enhance_speech)  [post-processing in speak/speak_optimized]

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
    -> clipcannon.pipeline.narrative_llm (run_narrative_llm)
    -> clipcannon.pipeline.* (all 22 stage run functions)

clipcannon.dashboard.app
    -> clipcannon.__init__ (__version__)
    -> clipcannon.dashboard.auth (is_dev_mode)
    -> clipcannon.dashboard.routes (all 7 routers)

voiceagent.__main__
    -> voiceagent.cli (cli)

voiceagent.cli
    -> voiceagent.agent (VoiceAgent)
    -> voiceagent.config (VoiceAgentConfig, TTSConfig, TransportConfig)
    -> voiceagent.pipecat_agent (run_agent)

voiceagent.agent
    -> voiceagent.config (VoiceAgentConfig, load_config)
    -> voiceagent.db.connection (get_connection)
    -> voiceagent.db.schema (init_db)
    -> voiceagent.gpu_manager (pause_gpu_workers, resume_gpu_workers, force_free_gpu_memory)
    -> voiceagent.asr.streaming (StreamingASR)
    -> voiceagent.brain.llm (LLMBrain)
    -> voiceagent.brain.context (ContextManager)
    -> voiceagent.brain.prompts (build_system_prompt)
    -> voiceagent.adapters.fast_tts (FastTTSAdapter)
    -> voiceagent.tts.chunker (SentenceChunker)
    -> voiceagent.tts.streaming (StreamingTTS)
    -> voiceagent.conversation.manager (ConversationManager)
    -> voiceagent.activation.wake_word (WakeWordDetector)
    -> voiceagent.activation.hotkey (HotkeyActivator)
    -> voiceagent.transport.local_audio (LocalAudioTransport)
    -> voiceagent.transport.websocket (WebSocketTransport)
    -> voiceagent.server (create_app)

voiceagent.adapters.fast_tts
    -> clipcannon.voice.profiles (get_voice_profile)  [reads voice profile DB]
    -> clipcannon.voice.inference (VoiceSynthesizer)   [for reference embedding]

voiceagent.pipecat_agent
    -> voiceagent.adapters.fast_tts (FastTTSAdapter)
    -> voiceagent.pipecat_tts (PipecatTTSService)
```

## Entry Points

### Console Script: `clipcannon`

Defined in `pyproject.toml` under `[project.scripts]`:

```
clipcannon = "clipcannon.server:main"
```

Calls `server.main()` which sets up structured JSON logging to stderr, creates the MCP Server with all 53 tools registered, and runs it on stdio transport via `asyncio.run(run_stdio())`.

### Narrative LLM stage dependencies

```
clipcannon.pipeline.narrative_llm
    -> clipcannon.pipeline.orchestrator (StageResult)
    -> clipcannon.provenance (ExecutionInfo, InputInfo, ModelInfo, OutputInfo, record_provenance)
```

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

Both `clipcannon` and `license_server` packages are included in the built wheel. The `voiceagent` package is NOT included in the wheel -- it is run directly via `python -m voiceagent` and has its own dependency set.
