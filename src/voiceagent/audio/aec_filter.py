"""Acoustic Echo Cancellation filter for Pipecat voice agent.

Three-layer echo suppression:
  Layer 1: Mic gating -- silence mic while bot is actively speaking
  Layer 2: NLMS adaptive filter -- cancels echo tail after bot stops
  Layer 3: Residual suppression -- spectral gating on remaining echo

Uses pyroomacoustics NLMS for the adaptive filter (3ms per 20ms chunk).
Designed for speaker playback without headphones on WSL2/PulseAudio.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np
from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
from pipecat.frames.frames import FilterControlFrame

logger = logging.getLogger(__name__)

# Echo tail duration after bot stops speaking (ms)
ECHO_TAIL_MS = 600
# NLMS filter length in samples (at 16kHz, 4800 = 300ms room impulse)
FILTER_TAPS = 4800
# NLMS step size (0.0-1.0, higher = faster adaptation, more noise)
MU = 0.4
# Minimum energy ratio (echo vs clean) to apply suppression
SUPPRESS_THRESHOLD = 0.02


class AECFilter(BaseAudioFilter):
    """Acoustic Echo Cancellation for local speaker playback.

    Integrates with Pipecat as an audio_in_filter, processing mic audio
    before it reaches VAD and STT. Three layers of protection:

    1. **Mic gating**: While the bot is speaking, returns silence.
       This prevents any echo from reaching VAD during active playback.

    2. **NLMS adaptive filter**: After the bot stops, runs for ECHO_TAIL_MS
       to cancel the decaying echo tail. Uses the speaker output as
       reference signal to model the speaker-to-mic transfer function.

    3. **Energy gate**: If residual energy after NLMS is still high
       relative to the reference, suppresses the frame.
    """

    def __init__(
        self,
        filter_taps: int = FILTER_TAPS,
        mu: float = MU,
        echo_tail_ms: int = ECHO_TAIL_MS,
    ) -> None:
        self._filter_taps = filter_taps
        self._mu = mu
        self._echo_tail_ms = echo_tail_ms
        self._sample_rate = 16000
        self._out_sample_rate = 24000

        # State
        self._bot_speaking = False
        self._bot_stop_time: float = 0.0
        self._lock = threading.Lock()

        # Reference signal ring buffer (speaker output, resampled to mic rate)
        self._ref_buffer: deque[float] = deque(maxlen=filter_taps)

        # NLMS filter (initialized in start())
        self._nlms = None
        self._initialized = False

    async def start(self, sample_rate: int) -> None:
        """Initialize the AEC filter."""
        from pyroomacoustics.adaptive import NLMS

        self._sample_rate = sample_rate
        self._nlms = NLMS(self._filter_taps, mu=self._mu)
        self._ref_buffer = deque(
            [0.0] * self._filter_taps, maxlen=self._filter_taps,
        )
        self._initialized = True
        logger.info(
            "AEC filter started (taps=%d, mu=%.2f, tail=%dms, rate=%d)",
            self._filter_taps, self._mu, self._echo_tail_ms, sample_rate,
        )

    async def stop(self) -> None:
        """Clean up the AEC filter."""
        self._nlms = None
        self._initialized = False
        logger.info("AEC filter stopped")

    async def process_frame(self, frame: FilterControlFrame) -> None:
        """Handle control frames (unused for now)."""
        pass

    def set_bot_speaking(self, speaking: bool) -> None:
        """Called by the echo reference processor when bot starts/stops.

        Args:
            speaking: True when bot starts speaking, False when it stops.
        """
        with self._lock:
            self._bot_speaking = speaking
            if not speaking:
                self._bot_stop_time = time.monotonic()
                logger.debug("AEC: bot stopped, echo tail active for %dms", self._echo_tail_ms)

    def feed_reference(self, audio_bytes: bytes, sample_rate: int) -> None:
        """Feed speaker output as the echo reference signal.

        The reference is resampled to match mic sample rate and stored
        in a ring buffer for the NLMS filter.

        Args:
            audio_bytes: Raw int16 PCM audio from the speaker output.
            sample_rate: Sample rate of the speaker audio.
        """
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float64)
        samples /= 32768.0

        # Resample if speaker rate differs from mic rate
        if sample_rate != self._sample_rate and sample_rate > 0:
            ratio = self._sample_rate / sample_rate
            if abs(ratio - 1.0) > 0.01:
                n_out = int(len(samples) * ratio)
                indices = np.linspace(0, len(samples) - 1, n_out)
                samples = np.interp(indices, np.arange(len(samples)), samples)

        with self._lock:
            for s in samples:
                self._ref_buffer.append(s)

    async def filter(self, audio: bytes) -> bytes:
        """Apply echo cancellation to mic audio.

        Called by Pipecat's input transport before VAD processing.
        """
        if not self._initialized:
            return audio

        with self._lock:
            bot_speaking = self._bot_speaking
            bot_stop_time = self._bot_stop_time

        # Layer 1: Mic gating during bot speech
        if bot_speaking:
            return b"\x00" * len(audio)

        # Check if we're in the echo tail window
        elapsed_ms = (time.monotonic() - bot_stop_time) * 1000
        in_echo_tail = elapsed_ms < self._echo_tail_ms and bot_stop_time > 0

        if not in_echo_tail:
            # No echo expected, pass through unchanged
            return audio

        # Layer 2: NLMS adaptive filter during echo tail
        mic = np.frombuffer(audio, dtype=np.int16).astype(np.float64)
        mic /= 32768.0

        output = np.zeros(len(mic))
        ref_array = np.array(self._ref_buffer)

        for i in range(len(mic)):
            # Feed sample to NLMS: x_n = reference, d_n = mic (desired = clean + echo)
            # The filter learns to predict the echo from the reference
            self._nlms.update(ref_array[-1], mic[i])
            # Estimate echo
            echo_est = np.dot(self._nlms.w, ref_array)
            # Subtract estimated echo from mic
            output[i] = mic[i] - echo_est

            # Shift reference buffer (no new reference during tail)
            with self._lock:
                self._ref_buffer.append(0.0)
                ref_array = np.array(self._ref_buffer)

        # Layer 3: Energy gate -- if output still has high energy
        # relative to reference, it might be residual echo
        mic_energy = np.mean(mic ** 2)
        out_energy = np.mean(output ** 2)

        if mic_energy > 0 and out_energy / max(mic_energy, 1e-10) > 0.8:
            # Output is almost as loud as input = mostly echo, suppress
            fade = max(0.0, 1.0 - (elapsed_ms / self._echo_tail_ms))
            output *= fade
            logger.debug("AEC: energy gate applied (fade=%.2f)", fade)

        out_int16 = np.clip(output * 32768.0, -32768, 32767).astype(np.int16)
        return out_int16.tobytes()
