"""Audio-driven lip sync: maps audio waveform to per-frame mouth parameters.

Extracts amplitude envelope from audio at video frame rate and maps
it to mouth openness values for the face warper. No ML model needed —
uses pure signal processing (RMS energy per frame window).

Usage:
    sync = LipSync(fps=25, sample_rate=24000)
    params = sync.from_audio(audio_float32)  # -> list of LipFrame
    # Each LipFrame has: mouth_open (0-1), energy, frame_idx
"""
from __future__ import annotations

import dataclasses

import numpy as np


@dataclasses.dataclass(frozen=True)
class LipFrame:
    """Lip parameters for a single video frame."""
    frame_idx: int
    mouth_open: float     # 0.0 = closed, 1.0 = wide open
    energy: float         # Raw RMS energy for this frame window
    is_silence: bool      # True if energy below silence threshold


class LipSync:
    """Extract per-frame lip sync parameters from audio.

    Args:
        fps: Video frame rate (default 25).
        sample_rate: Audio sample rate (default 24000).
        silence_threshold: RMS below this = silence (mouth closed).
        smoothing: EMA alpha for temporal smoothing (0=no smooth, 1=instant).
        max_open: Maximum mouth_open value (caps extreme peaks).
    """

    def __init__(
        self,
        fps: int = 25,
        sample_rate: int = 24000,
        silence_threshold: float = 0.02,
        smoothing: float = 0.6,
        max_open: float = 0.85,
    ) -> None:
        self._fps = fps
        self._sr = sample_rate
        self._silence = silence_threshold
        self._smoothing = smoothing
        self._max_open = max_open
        self._samples_per_frame = sample_rate // fps
        self._prev_open = 0.0  # For EMA smoothing

    def reset(self) -> None:
        """Reset smoothing state between utterances."""
        self._prev_open = 0.0

    def from_audio(self, audio: np.ndarray) -> list[LipFrame]:
        """Convert an entire audio clip to per-frame lip parameters.

        Args:
            audio: Float32 audio array, mono, at self._sr sample rate.

        Returns:
            List of LipFrame, one per video frame covering the audio duration.
        """
        if audio.ndim != 1:
            audio = audio.flatten()

        n_frames = max(1, len(audio) // self._samples_per_frame)
        spf = self._samples_per_frame

        # Compute RMS energy per frame window
        energies = np.array([
            float(np.sqrt(np.mean(audio[i * spf:(i + 1) * spf] ** 2)))
            for i in range(n_frames)
        ])

        # Normalize energies to 0-1 range based on clip's dynamic range
        peak = np.max(energies)
        if peak > 0:
            norm = energies / peak
        else:
            norm = energies

        # Apply non-linear mapping: sqrt gives more movement at lower volumes
        # (speech is mostly mid-energy, not extreme peaks)
        mapped = np.sqrt(norm) * self._max_open

        # Temporal smoothing via EMA
        self._prev_open = 0.0
        frames: list[LipFrame] = []
        for i in range(n_frames):
            raw_open = float(mapped[i])
            is_silent = energies[i] < self._silence

            if is_silent:
                target = 0.0
            else:
                target = raw_open

            # EMA: blend toward target
            smoothed = self._smoothing * target + (1 - self._smoothing) * self._prev_open
            self._prev_open = smoothed

            frames.append(LipFrame(
                frame_idx=i,
                mouth_open=smoothed,
                energy=float(energies[i]),
                is_silence=is_silent,
            ))

        return frames

    def from_audio_realtime(self, chunk: np.ndarray) -> LipFrame:
        """Process a single frame's worth of audio for real-time lip sync.

        Call this at frame rate (e.g., every 40ms for 25fps) with
        the corresponding audio chunk.

        Args:
            chunk: Float32 audio chunk (~samples_per_frame samples).

        Returns:
            Single LipFrame for this instant.
        """
        energy = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) > 0 else 0.0
        is_silent = energy < self._silence

        if is_silent:
            target = 0.0
        else:
            # Map energy to mouth openness
            # Typical speech RMS is 0.02-0.3; scale accordingly
            normalized = min(energy / 0.25, 1.0)
            target = float(np.sqrt(normalized)) * self._max_open

        smoothed = self._smoothing * target + (1 - self._smoothing) * self._prev_open
        self._prev_open = smoothed

        return LipFrame(
            frame_idx=-1,  # Real-time, no index
            mouth_open=smoothed,
            energy=energy,
            is_silence=is_silent,
        )
