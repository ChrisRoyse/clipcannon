"""Always-on wake word listener for the voice agent.

Lightweight process that continuously listens for "Hey Jarvis" using:
  - Silero VAD for speech detection (~1% CPU when idle)
  - faster-whisper tiny model on CPU for transcription (~50ms per segment)
  - Sentence embedding similarity for wake phrase matching

When the wake phrase is detected, launches the full Pipecat voice agent
as a subprocess. When the agent exits (via "go to sleep"), resumes
listening for the wake phrase.

Lifecycle:
  LISTENING -> (wake detected) -> AGENT_ACTIVE -> (agent exits) -> LISTENING
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Wake phrases and their variations
WAKE_PHRASES = [
    "hey jarvis",
    "hey boris",
    "ok jarvis",
    "ok boris",
    "jarvis",
    "wake up",
    "wake up jarvis",
]

SIMILARITY_THRESHOLD = 0.72
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512  # Silero VAD v5 requires exactly 512 samples per call
SPEECH_PAD_MS = 300  # Padding around detected speech


def _ensure_pulse_server() -> None:
    """Set PULSE_SERVER for WSL2."""
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
            except (OSError, subprocess.TimeoutExpired) as e:
                logger.debug("WSL2 PulseAudio detection failed: %s", e)


class WakeWordListener:
    """Lightweight always-on wake word detector."""

    def __init__(
        self,
        voice_name: str = "boris",
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        self._voice_name = voice_name
        self._threshold = threshold
        self._running = False

        # Lazy-loaded components
        self._vad_model = None
        self._whisper = None
        self._embedder = None
        self._wake_embeddings: np.ndarray | None = None
        self._pyaudio = None
        self._stream = None

    def _load_vad(self) -> object:
        """Load Silero VAD (lightweight, CPU)."""
        if self._vad_model is not None:
            return self._vad_model
        import torch
        model, _utils = torch.hub.load(
            "snakers4/silero-vad", "silero_vad",
            trust_repo=True, verbose=False,
        )
        self._vad_model = model
        logger.info("Wake listener: Silero VAD loaded")
        return model

    def _load_whisper(self) -> object:
        """Load tiny Whisper model (CPU, fast)."""
        if self._whisper is not None:
            return self._whisper
        from faster_whisper import WhisperModel
        self._whisper = WhisperModel(
            "tiny", device="cpu", compute_type="int8",
        )
        logger.info("Wake listener: Whisper tiny loaded (CPU)")
        return self._whisper

    def _load_embedder(self) -> None:
        """Load sentence embeddings and pre-compute wake phrase vectors."""
        if self._embedder is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._embedder = SentenceTransformer(
            "all-MiniLM-L6-v2", device="cpu",
        )
        self._wake_embeddings = self._embedder.encode(
            WAKE_PHRASES, normalize_embeddings=True,
        )
        logger.info(
            "Wake listener: %d wake phrases embedded", len(WAKE_PHRASES),
        )

    def _is_wake_phrase(self, text: str) -> bool:
        """Check if transcribed text matches a wake phrase."""
        text_lower = text.lower().strip().rstrip(".")

        # Fast exact match
        if text_lower in WAKE_PHRASES:
            return True

        # Embedding similarity for fuzzy matching
        self._load_embedder()
        query = self._embedder.encode(
            [text_lower], normalize_embeddings=True,
        )[0]
        best = max(float(np.dot(query, e)) for e in self._wake_embeddings)
        if best >= self._threshold:
            logger.info(
                "Wake phrase matched (%.3f): '%s'", best, text_lower,
            )
            return True
        return False

    def _start_mic(self) -> None:
        """Open mic stream via PyAudio."""
        import pyaudio
        self._pyaudio = pyaudio.PyAudio()
        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES,
        )

    def _stop_mic(self) -> None:
        """Close mic stream."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

    def _collect_speech(self) -> np.ndarray | None:
        """Use VAD to collect a speech segment from the mic.

        Returns float32 audio array if speech detected, None if silence.
        """
        import torch

        vad = self._load_vad()
        chunk_ms = CHUNK_SAMPLES / SAMPLE_RATE * 1000  # ~32ms per chunk
        pad_chunks = int(SPEECH_PAD_MS / chunk_ms)

        # Ring buffer for pre-speech padding
        pre_buffer: deque[bytes] = deque(maxlen=pad_chunks)
        speech_chunks: list[bytes] = []
        is_speaking = False
        silence_count = 0
        max_silence = int(500 / chunk_ms)  # 500ms silence = end
        max_speech_chunks = int(5000 / chunk_ms)  # 5s max

        for _ in range(int(10000 / chunk_ms)):  # 10s timeout
            try:
                data = self._stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            except OSError:
                continue

            # Convert to float for VAD (Silero v5 needs flat 512-sample tensor)
            audio_int16 = np.frombuffer(data, dtype=np.int16)
            audio_float = torch.from_numpy(
                audio_int16.astype(np.float32) / 32768.0,
            )

            # Run VAD
            confidence = vad(audio_float, SAMPLE_RATE).item()

            if confidence > 0.5:
                if not is_speaking:
                    is_speaking = True
                    # Include pre-speech padding
                    speech_chunks.extend(pre_buffer)
                speech_chunks.append(data)
                silence_count = 0
            else:
                if is_speaking:
                    silence_count += 1
                    speech_chunks.append(data)
                    if silence_count >= max_silence:
                        break
                else:
                    pre_buffer.append(data)

            if len(speech_chunks) >= max_speech_chunks:
                break

        if not speech_chunks:
            return None

        # Concatenate and convert to float32
        audio_bytes = b"".join(speech_chunks)
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        audio /= 32768.0
        return audio

    def _transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio using tiny Whisper."""
        whisper = self._load_whisper()
        segments, _ = whisper.transcribe(
            audio, language="en", beam_size=1,
            vad_filter=False,  # Already VAD-filtered
        )
        text = " ".join(s.text.strip() for s in segments)
        return text

    @staticmethod
    def _warm_ollama() -> None:
        """Send a throwaway request to Ollama to warm the model into VRAM."""
        import json
        import urllib.error
        import urllib.request

        try:
            data = json.dumps({
                "model": "qwen3:14b-nothink",
                "prompt": "Hi",
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            logger.info("Ollama warmed up")
        except (urllib.error.URLError, OSError) as e:
            logger.warning("Ollama warmup failed: %s", e)

    def _play_confirmation(self) -> None:
        """Play a short confirmation tone to acknowledge wake word."""
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16, channels=1,
                rate=24000, output=True, frames_per_buffer=1024,
            )
            # 100ms 880Hz tone (A5) with 20ms fade-out
            t = np.linspace(0, 0.1, int(24000 * 0.1))
            tone = np.sin(2 * np.pi * 880 * t)
            # Fade out last 20ms
            fade_len = int(24000 * 0.02)
            tone[-fade_len:] *= np.linspace(1.0, 0.0, fade_len)
            audio = (tone * 12000).astype(np.int16)
            stream.write(audio.tobytes())
            stream.stop_stream()
            stream.close()
            pa.terminate()
        except (ImportError, OSError) as e:
            logger.debug("Could not play confirmation tone: %s", e)

    def _launch_agent(self) -> None:
        """Launch the full Pipecat voice agent as a subprocess."""
        # Immediate audio feedback -- user hears the ding before anything loads
        self._play_confirmation()
        # Pre-warm Ollama so LLM TTFB is fast on first request
        self._warm_ollama()
        logger.info("Launching voice agent (voice=%s)...", self._voice_name)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(
            Path(__file__).resolve().parent.parent.parent,
        )
        env["PYTHONUNBUFFERED"] = "1"

        proc = subprocess.Popen(
            [
                sys.executable, "-m", "voiceagent", "talk",
                "--voice", self._voice_name,
            ],
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        logger.info("Voice agent running (PID %d)", proc.pid)

        # Wait for agent to exit (either "go to sleep" or Ctrl+C)
        try:
            returncode = proc.wait()
            if returncode in (-signal.SIGTERM, 143):
                logger.info("Voice agent went to sleep (SIGTERM)")
            elif returncode == 0:
                logger.info("Voice agent exited cleanly")
            else:
                logger.warning(
                    "Voice agent exited with code %d", returncode,
                )
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait(timeout=5)
            raise

    def run(self) -> None:
        """Main loop: listen for wake word, launch agent, repeat."""
        _ensure_pulse_server()
        self._running = True

        print("\n=== Voice Agent Wake Listener ===")
        print(f"Wake phrase: 'Hey Jarvis' (or 'Hey Boris')")
        print(f"Voice: {self._voice_name}")
        print("Listening... Say 'Hey Jarvis' to activate.")
        print("Press Ctrl+C to quit.")
        print("=" * 33 + "\n")

        # Pre-load models on startup
        self._load_vad()
        self._load_whisper()
        self._load_embedder()

        while self._running:
            try:
                self._start_mic()

                while self._running:
                    audio = self._collect_speech()
                    if audio is None:
                        continue

                    # Transcribe the speech segment
                    text = self._transcribe(audio)
                    if not text.strip():
                        continue

                    logger.info("Heard: '%s'", text.strip())

                    # Check for wake phrase
                    if self._is_wake_phrase(text):
                        print(f"\n>>> Wake word detected! Activating...\n")
                        self._stop_mic()

                        # Launch full agent
                        self._launch_agent()

                        # Agent exited -- resume listening
                        print(
                            "\n>>> Agent sleeping. "
                            "Say 'Hey Jarvis' to wake up.\n"
                        )
                        break  # Break inner loop to restart mic

            except KeyboardInterrupt:
                print("\nShutting down wake listener...")
                self._running = False
            except OSError as e:
                logger.error("Wake listener error: %s", e)
                time.sleep(1)
            finally:
                self._stop_mic()


def main() -> None:
    """Entry point for the wake word listener."""
    import click

    @click.command()
    @click.option(
        "--voice", default="boris", show_default=True,
        help="Default voice profile",
    )
    @click.option(
        "--threshold", default=SIMILARITY_THRESHOLD, show_default=True,
        help="Wake phrase similarity threshold",
    )
    def cli(voice: str, threshold: float) -> None:
        """Always-on wake word listener for the voice agent."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
            stream=sys.stderr,
        )
        listener = WakeWordListener(
            voice_name=voice, threshold=threshold,
        )
        listener.run()

    cli()


if __name__ == "__main__":
    main()
