"""Meeting audio capture via PulseAudio monitor source.

Captures system audio output (what all meeting participants say) in real-time.
Audio is delivered as PCM 16-bit mono 16kHz chunks to a callback function.

Uses PyAudio to read from the PulseAudio monitor source. On WSL2, the
PULSE_SERVER env var must point to the Windows PulseAudio TCP bridge.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from voiceagent.meeting.config import AudioCaptureConfig
from voiceagent.meeting.errors import MeetingAudioError

logger = logging.getLogger(__name__)

CHUNK_FRAMES = 1024  # frames per read (~64ms at 16kHz)
SAMPLE_WIDTH = 2     # 16-bit = 2 bytes
CHANNELS = 1         # mono


class MeetingAudioCapture:
    """Capture meeting audio from PulseAudio monitor source.

    Runs in a background thread. Delivers PCM chunks to a callback.
    The callback receives numpy float32 arrays normalized to [-1, 1].

    Args:
        config: Audio capture configuration.
        on_audio: Callback receiving (audio_chunk: np.ndarray, sample_rate: int).
    """

    def __init__(
        self,
        config: AudioCaptureConfig,
        on_audio: Callable[[np.ndarray, int], None],
    ) -> None:
        self._config = config
        self._on_audio = on_audio
        self._running = False
        self._thread: threading.Thread | None = None
        self._pa: object | None = None  # PyAudio instance
        self._stream: object | None = None
        self._ensure_pulse_server()

    def _ensure_pulse_server(self) -> None:
        """Set PULSE_SERVER for WSL2 if not already set.

        Mirrors the logic in pipecat_agent.py: detects WSL2 via the
        WSLInterop binfmt_misc entry, then reads the default gateway
        IP from ``ip route`` to construct the tcp: PULSE_SERVER address.
        """
        if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists():
            current = os.environ.get("PULSE_SERVER", "")
            if not current.startswith("tcp:"):
                try:
                    result = subprocess.run(
                        ["ip", "route", "show", "default"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    parts = result.stdout.strip().split()
                    if len(parts) >= 3:
                        os.environ["PULSE_SERVER"] = f"tcp:{parts[2]}"
                        logger.info(
                            "WSL2 PULSE_SERVER set to tcp:%s", parts[2],
                        )
                except (OSError, subprocess.TimeoutExpired) as e:
                    logger.debug("WSL2 PulseAudio detection failed: %s", e)

    def _find_monitor_device(self) -> int:
        """Find the PulseAudio monitor source device index.

        Iterates over all PyAudio devices looking for one whose name
        contains "monitor" or matches the configured source name. Falls
        back to the default input device if no monitor is found.

        Returns:
            PyAudio device index for the monitor source.

        Raises:
            MeetingAudioError: If no suitable input device is found or
                if PyAudio cannot initialise (e.g. PulseAudio not running).
        """
        try:
            import pyaudio
        except ImportError as exc:
            raise MeetingAudioError(
                "pyaudio is required for audio capture. "
                "Install: pip install pyaudio"
            ) from exc

        try:
            pa = pyaudio.PyAudio()
        except Exception as exc:
            raise MeetingAudioError(
                "Failed to initialise PyAudio. Ensure PulseAudio is running "
                "and PULSE_SERVER is set correctly for WSL2. "
                f"Error: {exc}"
            ) from exc

        self._pa = pa
        source_name = self._config.source  # e.g. "default.monitor"

        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            name = info.get("name", "")
            max_input = info.get("maxInputChannels", 0)
            if max_input > 0 and (
                "monitor" in name.lower() or source_name in name
            ):
                logger.info("Found monitor device %d: %s", i, name)
                return i

        # If specific source not found, try any input device
        try:
            default_input = pa.get_default_input_device_info()
        except Exception:
            default_input = None

        if default_input:
            logger.warning(
                "Monitor source '%s' not found, using default input: %s",
                source_name,
                default_input.get("name"),
            )
            return default_input["index"]

        raise MeetingAudioError(
            f"No PulseAudio monitor source found matching '{source_name}'. "
            f"Ensure PulseAudio is running and PULSE_SERVER is set correctly. "
            f"Available devices: check 'pactl list sources short'"
        )

    def start(self) -> None:
        """Start capturing audio in a background thread.

        Opens the PulseAudio monitor source and spawns a daemon thread
        that reads audio chunks and delivers them to the callback.

        Raises:
            MeetingAudioError: If capture is already running or if the
                audio device cannot be opened.
        """
        if self._running:
            raise MeetingAudioError("Audio capture already running")

        device_idx = self._find_monitor_device()

        import pyaudio

        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=self._config.sample_rate,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=CHUNK_FRAMES,
            )
        except Exception as exc:
            self._cleanup_pa()
            raise MeetingAudioError(
                f"Failed to open audio stream on device {device_idx}: {exc}"
            ) from exc

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="meeting-audio-capture",
        )
        self._thread.start()
        logger.info(
            "Audio capture started (device=%d, rate=%d)",
            device_idx,
            self._config.sample_rate,
        )

    def _capture_loop(self) -> None:
        """Background thread: read audio chunks and deliver to callback.

        Converts int16 PCM bytes to float32 arrays normalised to [-1, 1]
        before invoking the callback. Exits cleanly when ``_running`` is
        set to False or on unrecoverable read errors.
        """
        while self._running:
            try:
                data = self._stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                # Convert int16 bytes to float32 [-1, 1]
                audio = (
                    np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                )
                self._on_audio(audio, self._config.sample_rate)
            except Exception as exc:
                if self._running:
                    logger.error("Audio capture error: %s", exc)
                break

    def _cleanup_pa(self) -> None:
        """Release PyAudio stream and instance resources."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def stop(self) -> None:
        """Stop capturing audio and release all resources.

        Safe to call multiple times. Joins the capture thread with a
        2-second timeout to avoid hanging on exit.
        """
        self._running = False
        self._cleanup_pa()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Audio capture stopped")

    @property
    def is_running(self) -> bool:
        """Whether the capture loop is currently active."""
        return self._running
