"""Acoustic Echo Cancellation filter for Pipecat voice agent.

Two-layer echo suppression for speaker playback without headphones:
  Layer 1: Mic gating -- silence mic while bot is speaking + echo tail
  Layer 2: Spectral suppression -- attenuate frequencies matching echo

Designed for WSL2/PulseAudio where the bot's audio plays through
speakers and the mic picks it up. Since we know exactly when the bot
is speaking (from the pipeline), mic gating handles 95% of cases.
The spectral suppression catches residual echo in the tail.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np
from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
from pipecat.frames.frames import FilterControlFrame

logger = logging.getLogger(__name__)

# Echo tail duration after bot stops speaking (ms)
ECHO_TAIL_MS = 800
# Fade-in duration after echo tail ends (ms) -- gradual unmute
FADE_IN_MS = 200
# Spectral suppression factor during echo tail (0=full suppress, 1=passthrough)
SPECTRAL_FLOOR = 0.05


class AECFilter(BaseAudioFilter):
    """Acoustic Echo Cancellation for local speaker playback.

    Layer 1 (mic gating): While the bot is speaking, returns silence.
    After the bot stops, returns silence for ECHO_TAIL_MS to let the
    room echo decay. Then fades in over FADE_IN_MS.

    Layer 2 (spectral suppression): During the fade-in window, applies
    spectral suppression using the last reference signal's spectral
    profile to attenuate echo-matching frequencies.

    This is deliberately simple and robust -- no adaptive filter that
    can diverge. The mic gating approach works because we have perfect
    knowledge of when the bot is speaking.
    """

    def __init__(
        self,
        echo_tail_ms: int = ECHO_TAIL_MS,
        fade_in_ms: int = FADE_IN_MS,
        **_kwargs: object,
    ) -> None:
        self._echo_tail_ms = echo_tail_ms
        self._fade_in_ms = fade_in_ms
        self._sample_rate = 16000

        # State
        self._bot_speaking = False
        self._bot_stop_time: float = 0.0
        self._lock = threading.Lock()

        # Reference spectral profile for suppression
        self._ref_spectrum: np.ndarray | None = None
        self._initialized = False

    async def start(self, sample_rate: int) -> None:
        """Initialize the AEC filter."""
        self._sample_rate = sample_rate
        self._initialized = True
        logger.info(
            "AEC filter started (tail=%dms, fade=%dms, rate=%d)",
            self._echo_tail_ms, self._fade_in_ms, sample_rate,
        )

    async def stop(self) -> None:
        """Clean up the AEC filter."""
        self._initialized = False
        logger.info("AEC filter stopped")

    async def process_frame(self, frame: FilterControlFrame) -> None:
        """Handle control frames (unused)."""
        pass

    def set_bot_speaking(self, speaking: bool) -> None:
        """Called by the echo reference processor when bot starts/stops."""
        with self._lock:
            self._bot_speaking = speaking
            if not speaking:
                self._bot_stop_time = time.monotonic()

    def feed_reference(self, audio_bytes: bytes, sample_rate: int) -> None:
        """Feed speaker output to build spectral profile for suppression."""
        try:
            samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float64)
            if len(samples) > 0:
                spectrum = np.abs(np.fft.rfft(samples))
                # Exponential moving average of reference spectrum
                with self._lock:
                    if self._ref_spectrum is None or len(self._ref_spectrum) != len(spectrum):
                        self._ref_spectrum = spectrum
                    else:
                        self._ref_spectrum = 0.7 * self._ref_spectrum + 0.3 * spectrum
        except (ValueError, TypeError) as e:
            logger.debug("AEC feed_reference skipped: %s", e)

    async def filter(self, audio: bytes) -> bytes:
        """Apply echo cancellation to mic audio."""
        if not self._initialized:
            return audio

        with self._lock:
            bot_speaking = self._bot_speaking
            bot_stop_time = self._bot_stop_time

        # Layer 1: Heavy attenuation during bot speech (not full mute)
        # Allows very loud deliberate speech ("go to sleep") to break through
        if bot_speaking:
            mic = np.frombuffer(audio, dtype=np.int16).astype(np.float64)
            mic *= 0.1  # 90% attenuation -- echo mostly suppressed, shouts get through
            return np.clip(mic, -32768, 32767).astype(np.int16).tobytes()

        # Time since bot stopped speaking
        if bot_stop_time == 0:
            return audio  # Bot hasn't spoken yet

        elapsed_ms = (time.monotonic() - bot_stop_time) * 1000

        # Still in echo tail -- return silence
        if elapsed_ms < self._echo_tail_ms:
            return b"\x00" * len(audio)

        # Fade-in window after echo tail
        fade_elapsed = elapsed_ms - self._echo_tail_ms
        if fade_elapsed < self._fade_in_ms:
            # Gradual fade from silence to full volume
            gain = fade_elapsed / self._fade_in_ms

            mic = np.frombuffer(audio, dtype=np.int16).astype(np.float64)

            # Layer 2: Spectral suppression during fade-in
            with self._lock:
                ref_spec = self._ref_spectrum

            if ref_spec is not None and len(mic) > 0:
                mic_fft = np.fft.rfft(mic)
                mic_spec = np.abs(mic_fft)

                # Resize reference spectrum to match mic chunk
                if len(ref_spec) != len(mic_spec):
                    ref_spec = np.interp(
                        np.linspace(0, 1, len(mic_spec)),
                        np.linspace(0, 1, len(ref_spec)),
                        ref_spec,
                    )

                # Suppress frequencies where echo is strong relative to mic
                ref_norm = ref_spec / (np.max(ref_spec) + 1e-10)
                suppression = 1.0 - ref_norm * (1.0 - SPECTRAL_FLOOR)
                suppression = np.clip(suppression, SPECTRAL_FLOOR, 1.0)

                mic_fft *= suppression
                mic = np.fft.irfft(mic_fft, n=len(mic))

            mic *= gain
            out = np.clip(mic, -32768, 32767).astype(np.int16)
            return out.tobytes()

        # Past fade-in window -- normal passthrough
        return audio
