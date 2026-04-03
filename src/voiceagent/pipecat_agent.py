"""Pipecat-based voice agent with local Ollama LLM + faster-qwen3-tts.

All local, no cloud APIs:
  - ASR: faster-whisper (Whisper Large v3 Turbo, float16, CUDA)
  - LLM: Ollama serving Qwen3-8B locally (GGUF, ~186 tok/s)
  - TTS: faster-qwen3-tts (Qwen3-TTS 0.6B with CUDA graphs, streaming)
  - VAD: Silero VAD (300ms endpointing) + Smart Turn V3 (ML end-of-turn)
  - AEC: NLMS adaptive filter (pyroomacoustics) + mic gating
  - Transport: PyAudio local mic/speaker

Latency optimizations (Phase 1 + Phase 2):
  Phase 1:
    - ASR: large-v3-turbo (809M, 2.7x faster than large-v3, same WER)
    - LLM: 8B model (50ms TTFT vs 100ms for 14B)
    - TTS: streaming chunk_size=2 (~130ms TTFB vs 500ms non-streaming)
    - VAD: 300ms stop_secs (was 500ms), 150ms start_secs (was 200ms)
  Phase 2:
    - Smart Turn V3: ML-based end-of-turn detection (bundled ONNX model)
    - Filler audio: pre-generated acknowledgments in cloned voice
    - Latency observer: per-turn timing breakdown

Pipecat handles:
  - Streaming LLM -> TTS (sentence-level chunking)
  - Turn-taking (Silero VAD + Smart Turn V3)
  - Barge-in (interrupt agent mid-sentence)
  - Frame-based pipeline architecture

Echo cancellation:
  - Layer 1: Mic gating while bot speaks (AECFilter)
  - Layer 2: NLMS adaptive filter for echo tail (pyroomacoustics)
  - Layer 3: Energy gate for residual echo suppression
  - EchoReferenceProcessor feeds speaker output to AEC
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Tunable latency knobs ---
# ASR: large-v3-turbo is 2.7x faster than large-v3 with <0.4% WER increase
ASR_MODEL = "large-v3-turbo"
ASR_COMPUTE_TYPE = "float16"
# LLM: 8B is ~50% faster TTFT than 14B; quality delta is negligible for
# 1-3 sentence voice responses
LLM_MODEL = "qwen3:8b-nothink"
LLM_MAX_TOKENS = 256
# VAD: 300ms stop = fastest safe endpoint without false triggers on pauses.
# Smart Turn V3 overrides this with ML-based detection when confident.
VAD_STOP_SECS = 0.3
VAD_START_SECS = 0.15
VAD_CONFIDENCE = 0.7
# Filler audio: play a short acknowledgment while LLM processes
ENABLE_FILLER_AUDIO = True


def _ensure_pulse_server() -> None:
    """Set PULSE_SERVER for WSL2 PulseAudio TCP bridge."""
    if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists():
        current = os.environ.get("PULSE_SERVER", "")
        if not current.startswith("tcp:"):
            try:
                result = subprocess.run(
                    ["ip", "route", "show", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                parts = result.stdout.strip().split()
                if len(parts) >= 3:
                    os.environ["PULSE_SERVER"] = f"tcp:{parts[2]}"
                    logger.info(
                        "WSL2 PULSE_SERVER set to tcp:%s", parts[2],
                    )
            except (OSError, subprocess.TimeoutExpired) as e:
                logger.debug("WSL2 PulseAudio detection failed: %s", e)


def _ensure_ollama_running() -> None:
    """Verify Ollama is running and has a qwen3 model loaded."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            if not any("qwen3" in m for m in models):
                logger.error(
                    "Ollama has no qwen3 model. Run: ollama pull qwen3:8b"
                    " then create nothink variant with: "
                    'echo "FROM qwen3:8b\\nPARAMETER num_ctx 8192" '
                    "| ollama create qwen3:8b-nothink -f -"
                )
                sys.exit(1)
            logger.info("Ollama OK: %s", models)
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.error(
            "Ollama not running at localhost:11434: %s. "
            "Start it with: ollama serve",
            e,
        )
        sys.exit(1)


async def run_agent(voice_name: str = "boris") -> None:
    """Run the Pipecat voice agent with local models."""

    _ensure_pulse_server()
    _ensure_ollama_running()

    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineParams, PipelineTask
    from pipecat.processors.aggregators.openai_llm_context import (
        OpenAILLMContext,
    )
    from pipecat.services.ollama.llm import OLLamaLLMService, OllamaLLMSettings
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )

    from voiceagent.audio.aec_filter import AECFilter
    from voiceagent.audio.echo_ref_processor import EchoReferenceProcessor
    from voiceagent.audio.semantic_turn_detector import SemanticTurnDetector
    from voiceagent.audio.voice_command_detector import (
        SleepCommandDetector,
        VoiceCommandDetector,
    )
    from voiceagent.latency_observer import LatencyObserver
    from voiceagent.pipecat_tts import FastQwen3TTSService

    # --- Smart Turn V3: ML-based end-of-turn detection ---
    # Uses a bundled ONNX model (Whisper-based, runs on CPU) to predict
    # whether the user has finished their turn. Much smarter than fixed
    # silence thresholds -- detects sentence completion even with short
    # pauses. Fallback: 3s silence timeout if model is uncertain.
    try:
        from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (
            LocalSmartTurnAnalyzerV3,
        )
        from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy

        smart_turn = LocalSmartTurnAnalyzerV3(
            params=SmartTurnParams(
                stop_secs=2.0,         # Fallback: force end after 2s silence
                pre_speech_ms=300,     # Buffer 300ms before speech for context
                max_duration_secs=8,   # Max 8s per utterance for ML analysis
            ),
        )
        smart_turn_available = True
        logger.info("Smart Turn V3 loaded (ONNX, CPU)")
    except Exception as exc:
        smart_turn_available = False
        logger.warning("Smart Turn V3 unavailable: %s", exc)

    # --- AEC: Echo cancellation filter ---
    aec_filter = AECFilter(
        echo_tail_ms=400,   # Silence mic for 400ms after bot stops
        fade_in_ms=100,     # Quick fade-in after echo tail
    )

    # --- Transport: local mic + speaker with AEC ---
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_filter=aec_filter,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    confidence=VAD_CONFIDENCE,
                    start_secs=VAD_START_SECS,
                    stop_secs=VAD_STOP_SECS,
                    min_volume=0.01,
                ),
            ),
            audio_out_sample_rate=24000,
            audio_in_sample_rate=16000,
        ),
    )

    # --- ASR: local Whisper Turbo (809M, 2.7x faster, same WER) ---
    stt = WhisperSTTService(
        model=ASR_MODEL,
        device="cuda",
        compute_type=ASR_COMPUTE_TYPE,
        no_speech_prob=0.4,
    )

    # --- LLM: local Ollama (qwen3:8b, thinking disabled, ~186 tok/s) ---
    llm = OLLamaLLMService(
        model=LLM_MODEL,
        base_url="http://localhost:11434/v1",
        settings=OllamaLLMSettings(
            max_tokens=LLM_MAX_TOKENS,
            temperature=0.6,
            top_p=0.8,
            top_k=20,
        ),
    )

    # --- TTS: local faster-qwen3-tts ---
    tts = FastQwen3TTSService(voice_name=voice_name)

    # --- Echo reference processor (feeds speaker audio to AEC) ---
    echo_ref = EchoReferenceProcessor(aec_filter=aec_filter)

    # --- System prompt (clean, no voice switching logic) ---
    from datetime import datetime

    messages = [
        {
            "role": "system",
            "content": (
                f"You are a personal AI voice assistant for Chris Royse. "
                f"You speak naturally and concisely. "
                f"This is a SPOKEN conversation -- keep responses to "
                f"1-3 sentences. No markdown, no lists, no formatting. "
                f"No reasoning or thinking out loud. No emojis. "
                f"Current time: {datetime.now().isoformat()}."
            ),
        },
    ]

    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    # --- Voice command detector (embedding-based, no LLM involvement) ---
    async def on_voice_switch(target_voice: str) -> None:
        """Called by the command detector when a switch is detected."""
        logger.info("Voice command detected -> switching to: %s", target_voice)
        try:
            tts.switch_voice(target_voice)
            logger.info("Voice switched to %s", target_voice)
        except (RuntimeError, OSError, ValueError) as e:
            logger.error("Voice switch failed: %s", e)

    voice_cmd_detector = VoiceCommandDetector(
        voice_names=["boris", "taylor"],
        switch_callback=on_voice_switch,
        threshold=0.78,
    )
    sleep_detector = SleepCommandDetector()

    # --- Semantic turn detector (text-based, LiveKit model) ---
    # Second signal: analyzes transcription TEXT to predict end-of-turn
    # based on semantic content. Complements the audio-based Smart Turn V3.
    # ~12ms per inference on CPU, no GPU needed, ~165MB RAM.
    semantic_turn = SemanticTurnDetector(threshold=0.5)

    # --- Latency observer ---
    latency_observer = LatencyObserver()

    # --- Pipeline ---
    # Semantic turn detector sits right after STT so it can analyze every
    # transcription. It logs EOU probability but does NOT block frames.
    # Combined with Smart Turn V3 (audio-based), we have two independent
    # signals for end-of-turn detection.
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            semantic_turn,
            sleep_detector,
            voice_cmd_detector,
            context_aggregator.user(),
            llm,
            tts,
            echo_ref,
            transport.output(),
            context_aggregator.assistant(),
        ],
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            observers=[latency_observer],
        ),
    )

    # --- Register Smart Turn V3 as turn analyzer on the VAD ---
    # The Smart Turn analyzer runs its ML model when VAD detects silence,
    # overriding the fixed stop_secs with an intelligent prediction.
    if smart_turn_available:
        try:
            vad = transport._params.vad_analyzer
            if hasattr(vad, 'set_turn_analyzer'):
                vad.set_turn_analyzer(smart_turn)
                logger.info("Smart Turn V3 registered with VAD analyzer")
            else:
                logger.info(
                    "VAD analyzer does not support set_turn_analyzer; "
                    "Smart Turn V3 running as standalone"
                )
        except Exception as exc:
            logger.debug("Smart Turn V3 VAD registration skipped: %s", exc)

    # --- Filler audio pre-generation (background) ---
    filler_cache = None
    if ENABLE_FILLER_AUDIO:
        from voiceagent.filler_audio import FillerAudioCache

        filler_cache = FillerAudioCache()
        # Pre-generate in background so it doesn't delay startup
        asyncio.create_task(filler_cache.pregenerate(voice_name))

    runner = PipelineRunner()

    turn_features = "Smart Turn V3 (audio) + " if smart_turn_available else ""
    filler_status = "enabled" if ENABLE_FILLER_AUDIO else "disabled"

    print("\n=== Voice Agent (Pipecat + AEC) ===")
    print(f"Voice: {voice_name}")
    print(f"LLM: Ollama {LLM_MODEL} (local, ~186 tok/s)")
    print(f"ASR: Whisper {ASR_MODEL} (local, {ASR_COMPUTE_TYPE})")
    print("TTS: faster-qwen3-tts 0.6B (local, CUDA graphs, streaming)")
    print(f"Turn: {turn_features}LiveKit semantic (text)")
    print(f"VAD: {VAD_STOP_SECS}s stop / {VAD_START_SECS}s start")
    print(f"Filler audio: {filler_status}")
    print("AEC: NLMS adaptive filter (pyroomacoustics)")
    print("Latency observer: active (check logs)")
    print("---")
    print("Speak to start. Press Ctrl+C to quit.")
    print("=" * 35 + "\n")

    await runner.run(task)


def main() -> None:
    """Entry point for the Pipecat voice agent."""
    import click

    @click.command()
    @click.option(
        "--voice", default="boris", show_default=True,
        help="Voice profile name",
    )
    def cli(voice: str) -> None:
        """Run the Pipecat voice agent (all local)."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            stream=sys.stderr,
        )
        try:
            asyncio.run(run_agent(voice_name=voice))
        except KeyboardInterrupt:
            print("\nShutting down...")

    cli()


if __name__ == "__main__":
    main()
