"""Santa clone meeting bot — full quality pipeline with OCR Provenance RAG.

Architecture:
  Audio Routing (zero feedback):
    Meeting participants' audio -> PulseAudio output sink -> output.monitor -> parec -> Whisper
    Bot TTS -> JS AudioContext -> Chrome audio -> PULSE_SINK=bot_output (null sink, discarded)
    Bot TTS NEVER reaches output.monitor. Whisper hears ONLY meeting participants.

  Intelligence (RAG):
    Question -> OCR Provenance search (past meetings) -> Ollama 14B -> response
    Transcript segments ingested into OCR Provenance in near-real-time
    AI can search all meeting history to produce informed answers

  Voice Quality:
    Full ICL mode + real Santa reference recording
    Real laugh clips from expression library (not TTS-generated)
    [LAUGH] tags in LLM prompt -> replaced with real audio clips
    Prosody-aware: system prompt demands full vocal variation

  Memory Management:
    Whisper model loaded ONCE at startup
    TTS adapter loaded ONCE at startup
    Audio buffers capped at 2x window size
    Transcript segments capped in memory, overflow flushed to OCR Provenance
    gc.collect() after each response cycle
"""
# Implementation lives in the sibling package scripts/santa_bot/ (split for the
# 500-line file limit). This file is the unchanged entry point and re-exports every
# top-level name of the original script. Mutable singletons/avatar state are owned by
# santa_bot.models / santa_bot.avatar; the copies re-exported here are import-time values.
# The original import-time setup (logging, PulseAudio, CUDA env) runs in santa_bot.config,
# which every santa_bot module imports before anything else.
import asyncio
import gc
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from santa_bot.app import main
from santa_bot.avatar import (
    _face_warper,
    _load_identity_embeddings,
    _physics_face,
    _semantic_emo_identity,
    _semantic_model,
    _semantic_sem_identity,
    _semantic_sent_identity,
    _semantic_spk_identity,
    _semantic_vis_identity,
    _semantic_voice_identity,
    init_face_warper,
    init_physics_face,
    init_semantic_model,
    speak,
)
from santa_bot.browser import launch_browser
from santa_bot.config import (
    _GPU_VRAM_WARNING_GB,
    _MAX_TRANSCRIPT_SEGMENTS,
    _PROSODY_STYLE_KEYWORDS,
    AUDIO_SINK,
    CAPTURE_DEVICE,
    CHUNK_BYTES,
    ENERGY_THRESHOLD,
    IDLE_Y4M,
    LAUGH_CLIPS,
    LLM_MODEL,
    MEET_URL,
    MIN_SPEECH_BYTES,
    OCR_DB_NAME,
    OCR_PROVENANCE_URL,
    REFS_DIR,
    SAMPLE_RATE,
    SANTA_IDLE_VIDEO,
    SESSION_DIR,
    SILENCE_TIMEOUT_S,
    VOICE_NAME,
    WHISPER_MODEL,
    Y4M_PIPE,
    _default_ref,
    _json,
    _laugh_idx,
    _ref_map_path,
    _ref_mapping,
    _transcript_segments,
    _y4m_writer,
    logger,
    select_prosody_ref,
)
from santa_bot.dialogue import process, respond, transcribe
from santa_bot.listen import audio_loop
from santa_bot.models import (
    _ocr_client,
    _tts_adapter,
    _whisper_model,
    get_ocr_client,
    get_tts,
    get_whisper,
    gpu_cleanup,
    gpu_health_check,
    ingest_transcript,
    log_gpu_state,
    release_models,
    search_meeting_history,
)

__all__ = [
    "asyncio", "gc", "json", "logging", "os", "re", "signal", "subprocess", "sys", "time",
    "Path", "cv2", "np", "MEET_URL", "SESSION_DIR", "VOICE_NAME", "LLM_MODEL", "WHISPER_MODEL",
    "OCR_PROVENANCE_URL", "OCR_DB_NAME", "Y4M_PIPE", "SANTA_IDLE_VIDEO", "IDLE_Y4M",
    "_y4m_writer", "CAPTURE_DEVICE", "AUDIO_SINK", "SAMPLE_RATE", "CHUNK_BYTES",
    "ENERGY_THRESHOLD", "SILENCE_TIMEOUT_S", "MIN_SPEECH_BYTES", "LAUGH_CLIPS", "_laugh_idx",
    "REFS_DIR", "_ref_mapping", "_default_ref", "_json", "_ref_map_path",
    "_PROSODY_STYLE_KEYWORDS", "select_prosody_ref", "_transcript_segments",
    "_MAX_TRANSCRIPT_SEGMENTS", "_GPU_VRAM_WARNING_GB", "logger", "gpu_cleanup",
    "gpu_health_check", "log_gpu_state", "_whisper_model", "_tts_adapter", "_ocr_client",
    "get_whisper", "get_tts", "release_models", "get_ocr_client", "search_meeting_history",
    "ingest_transcript", "_face_warper", "_physics_face", "_semantic_model",
    "_semantic_vis_identity", "_semantic_emo_identity", "_semantic_sem_identity",
    "_semantic_spk_identity", "_semantic_sent_identity", "_semantic_voice_identity",
    "init_face_warper", "init_physics_face", "init_semantic_model", "_load_identity_embeddings",
    "speak", "main", "launch_browser", "process", "respond", "transcribe", "audio_loop",
]


if __name__ == "__main__":
    asyncio.run(main())
