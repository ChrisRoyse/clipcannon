"""Local audio transport -- mic capture + speaker playback via sounddevice.

Implements TransportProtocol for local interactive voice conversations.
No network, no WebSocket -- audio goes directly to/from hardware devices.

Audio formats:
  Input:  16kHz, mono, float32 (sounddevice) -> converted to int16 for ASR
  Output: 24kHz, mono, float32 (from TTS) -> played through speakers

On WSL2, automatically detects and configures the PulseAudio TCP bridge
to the Windows host for proper mic input and speaker output.
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from voiceagent.errors import TransportError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


def _ensure_wsl2_pulse_tcp() -> None:
    """On WSL2, switch PULSE_SERVER to the Windows host TCP bridge.

    The default WSLg PulseAudio (unix:/mnt/wslg/PulseServer) routes
    speaker output but returns near-silence from the microphone.
    The Windows PulseAudio TCP bridge provides real mic input.
    """
    # Only apply on WSL2
    if not Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists():
        return

    current = os.environ.get("PULSE_SERVER", "")
    if current.startswith("tcp:"):
        return  # Already using TCP

    # Get Windows host IP from default route
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5,
        )
        parts = result.stdout.strip().split()
        win_ip = parts[2] if len(parts) >= 3 else None
    except Exception:
        win_ip = None

    if not win_ip:
        logger.warning("Could not detect Windows host IP for PulseAudio TCP")
        return

    # Ensure Windows PulseAudio is running before trying to connect
    if shutil.which("tasklist.exe"):
        try:
            tasklist = subprocess.run(
                ["tasklist.exe"], capture_output=True, text=True, timeout=5,
            )
            if "pulseaudio.exe" not in tasklist.stdout.lower():
                logger.info("Starting Windows PulseAudio...")
                subprocess.Popen(
                    ["powershell.exe", "-Command",
                     "Start-Process -FilePath "
                     r"'C:\Program Files (x86)\PulseAudio\bin\pulseaudio.exe' "
                     "-ArgumentList '--exit-idle-time=-1','--daemonize=no' "
                     "-WindowStyle Hidden"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                import time; time.sleep(3)
        except Exception:
            pass

    # Verify TCP connection works before switching
    tcp_server = f"tcp:{win_ip}"
    try:
        check = subprocess.run(
            ["pactl", "info"],
            capture_output=True, text=True, timeout=3,
            env={**os.environ, "PULSE_SERVER": tcp_server},
        )
        if check.returncode != 0:
            logger.warning(
                "PulseAudio TCP at %s not available. "
                "Using WSLg (mic may not work). "
                "Fix: enable module-native-protocol-tcp in Windows PulseAudio.",
                tcp_server,
            )
            return
    except Exception:
        return

    os.environ["PULSE_SERVER"] = tcp_server
    logger.info("WSL2: switched PULSE_SERVER to %s for real mic/speaker", tcp_server)

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000


class LocalAudioTransport:
    """Local audio I/O via sounddevice for interactive voice conversations.

    Captures microphone input and plays TTS audio through speakers.
    Implements TransportProtocol (send_audio, send_event).
    """

    def __init__(
        self,
        input_device: int | str | None = None,
        output_device: int | str | None = None,
        chunk_ms: int = 200,
    ) -> None:
        # Auto-configure PulseAudio TCP on WSL2 before opening any streams
        _ensure_wsl2_pulse_tcp()

        try:
            import sounddevice as sd
            self._sd = sd
        except (ImportError, OSError) as e:
            raise TransportError(
                f"sounddevice not available: {e}. "
                f"Install with: pip install sounddevice. "
                f"Also needs libportaudio2: sudo apt install libportaudio2"
            ) from e

        self._input_device = input_device
        self._output_device = output_device
        self._chunk_samples = int(INPUT_SAMPLE_RATE * chunk_ms / 1000)
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._input_stream = None
        self._output_stream = None
        self._on_audio: Callable[[np.ndarray], Awaitable[None]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._events: list[dict] = []

    async def start(
        self,
        on_audio: Callable[[np.ndarray], Awaitable[None]],
        on_control: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Start mic capture and speaker output.

        Args:
            on_audio: Async callback for each mic audio chunk (int16 ndarray).
            on_control: Async callback for control messages (unused in local mode).
        """
        self._on_audio = on_audio
        self._loop = asyncio.get_running_loop()
        self._running = True

        # Verify devices exist
        devices = self._sd.query_devices()
        if len(devices) == 0:
            raise TransportError(
                "No audio devices found. In WSL2, install PulseAudio: "
                "sudo apt install pulseaudio && pulseaudio --start. "
                "Then set PULSE_SERVER=tcp:localhost in your shell."
            )

        # Start output (speaker) stream
        self._output_stream = self._sd.OutputStream(
            samplerate=OUTPUT_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=self._output_device,
            blocksize=2400,  # 100ms at 24kHz
        )
        self._output_stream.start()
        logger.info("Speaker output started (24kHz, mono, float32)")

        # Start input (mic) stream with callback
        self._input_stream = self._sd.InputStream(
            samplerate=INPUT_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=self._input_device,
            blocksize=self._chunk_samples,
            callback=self._mic_callback,
        )
        self._input_stream.start()
        logger.info(
            "Mic capture started (16kHz, mono, %d samples/chunk)",
            self._chunk_samples,
        )

        # Process mic chunks on the asyncio event loop
        try:
            while self._running:
                try:
                    chunk = self._audio_queue.get_nowait()
                    await on_audio(chunk)
                except queue.Empty:
                    await asyncio.sleep(0.01)
        finally:
            self._cleanup()

    def _mic_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        """Called by sounddevice from audio thread for each mic chunk."""
        if status:
            logger.warning("Mic input status: %s", status)
        if not self._running:
            return
        # Convert float32 mono to int16 for ASR pipeline
        mono = indata[:, 0].copy()
        audio_int16 = (mono * 32767).astype(np.int16)
        self._audio_queue.put_nowait(audio_int16)

    async def send_audio(self, audio: np.ndarray) -> None:
        """Play audio through speakers. Called by ConversationManager for TTS output."""
        if self._output_stream is None or not self._output_stream.active:
            return
        # Audio from TTS is 24kHz float32 mono
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)
        try:
            self._output_stream.write(audio)
        except Exception as e:
            logger.warning("Speaker write failed: %s", e)

    async def send_event(self, event: dict) -> None:
        """Log events locally (no network in local mode)."""
        self._events.append(event)
        event_type = event.get("type", "?")
        if event_type == "state":
            logger.info("State -> %s", event.get("state", "?"))

    async def stop(self) -> None:
        """Stop mic capture and speaker output."""
        self._running = False
        self._cleanup()

    def _cleanup(self) -> None:
        """Release audio streams."""
        if self._input_stream is not None:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None

        if self._output_stream is not None:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None

        logger.info("Local audio transport stopped")
