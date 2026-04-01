"""Pipecat-based voice agent with local Ollama LLM + faster-qwen3-tts.

All local, no cloud APIs:
  - ASR: faster-whisper (Whisper Large v3, float16, CUDA)
  - LLM: Ollama serving Qwen3-14B locally (GGUF, ~120 tok/s)
  - TTS: faster-qwen3-tts (Qwen3-TTS 0.6B with CUDA graphs)
  - VAD: Silero VAD
  - AEC: NLMS adaptive filter (pyroomacoustics) + mic gating
  - Transport: PyAudio local mic/speaker

Pipecat handles:
  - Streaming LLM -> TTS (sentence-level chunking)
  - Turn-taking (Silero VAD)
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
    """Verify Ollama is running and has qwen3:14b loaded."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            if not any("qwen3" in m for m in models):
                logger.error(
                    "Ollama has no qwen3 model. Run: ollama pull qwen3:14b"
                    " then create nothink variant"
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
    from voiceagent.audio.voice_command_detector import (
        SleepCommandDetector,
        VoiceCommandDetector,
    )
    from voiceagent.pipecat_tts import FastQwen3TTSService

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
                    confidence=0.7,    # Default confidence
                    start_secs=0.2,    # Require 200ms of speech to trigger
                    stop_secs=0.5,     # Require 500ms silence to end turn
                    min_volume=0.01,   # Low threshold -- AEC handles echo, not volume gating
                ),
            ),
            audio_out_sample_rate=24000,
            audio_in_sample_rate=16000,
        ),
    )

    # --- ASR: local Whisper (beam_size=1 for ~2x faster transcription) ---
    stt = WhisperSTTService(
        model="large-v3",
        device="cuda",
        compute_type="float16",
        no_speech_prob=0.4,
    )

    # --- LLM: local Ollama (qwen3:14b, thinking disabled) ---
    llm = OLLamaLLMService(
        model="qwen3:14b-nothink",
        base_url="http://localhost:11434/v1",
        settings=OllamaLLMSettings(
            max_tokens=512,
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

    # --- Pipeline ---
    # Voice command detector sits between STT and LLM context aggregator.
    # It intercepts switch commands (detected via embeddings) and blocks
    # them from reaching the LLM. Normal speech passes through.
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
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
        ),
    )

    runner = PipelineRunner()

    print("\n=== Voice Agent (Pipecat + AEC) ===")
    print(f"Voice: {voice_name}")
    print("LLM: Ollama qwen3:14b-nothink (local, ~120 tok/s)")
    print("ASR: Whisper Large v3 (local, float16)")
    print("TTS: faster-qwen3-tts 0.6B (local, CUDA graphs)")
    print("AEC: NLMS adaptive filter (pyroomacoustics)")
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
