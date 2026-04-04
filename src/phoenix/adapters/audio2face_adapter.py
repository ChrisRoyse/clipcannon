"""Audio2Face adapters: NIM gRPC client and local signal-processing fallback.

Maps audio waveform chunks to 52 ARKit blendshape coefficients in real time.
The NIM adapter connects to NVIDIA Audio2Face-3D running as a Docker
microservice. The local adapter uses F0, RMS energy, spectral centroid,
and zero-crossing rate to approximate blendshapes without the NIM.

Both adapters produce BlendshapeFrame instances with temporal EMA smoothing.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from phoenix.adapters.blendshape_types import (
    ARKIT_BLENDSHAPE_NAMES,
    BLENDSHAPE_INDEX,
    NUM_ARKIT_BLENDSHAPES,
    NUM_FLAME_EXPRESSIONS,
    Audio2FaceAdapter,
    BlendshapeFrame,
    BlendshapeToFLAME,
    clamp,
)
from phoenix.errors import ExpressionError

logger = logging.getLogger(__name__)

# Re-export everything from blendshape_types for backward compatibility
__all__ = [
    "ARKIT_BLENDSHAPE_NAMES",
    "Audio2FaceAdapter",
    "Audio2FaceLocal",
    "Audio2FaceNIM",
    "BLENDSHAPE_INDEX",
    "BlendshapeFrame",
    "BlendshapeToFLAME",
    "NUM_ARKIT_BLENDSHAPES",
    "NUM_FLAME_EXPRESSIONS",
    "clamp",
]

# Keep private alias used in tests via old import path
_clamp = clamp


# ---------------------------------------------------------------------------
# Audio2FaceNIM: gRPC client to NVIDIA Audio2Face-3D NIM
# ---------------------------------------------------------------------------

class Audio2FaceNIM(Audio2FaceAdapter):
    """gRPC client to NVIDIA Audio2Face-3D NIM container.

    Falls back to Audio2FaceLocal on connection failure.

    Args:
        host: NIM container hostname or IP.
        port: gRPC port (default 50051).
        timeout_s: gRPC call timeout in seconds.
        fallback: Optional Audio2FaceLocal instance for fallback.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 50051,
        timeout_s: float = 2.0,
        fallback: Audio2FaceLocal | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout_s
        self._fallback = fallback or Audio2FaceLocal()
        self._channel: Any = None
        self._stub: Any = None
        self._connected = False

    @property
    def connected(self) -> bool:
        """Whether the gRPC channel is currently connected."""
        return self._connected

    def connect(self) -> bool:
        """Establish gRPC connection to NIM container.

        Returns:
            True if connection succeeded, False otherwise.
        """
        try:
            import grpc
            from nvidia_audio2face_3d import (  # type: ignore[import-untyped]
                audio2face_pb2_grpc,
            )

            target = f"{self._host}:{self._port}"
            self._channel = grpc.insecure_channel(target)
            self._stub = audio2face_pb2_grpc.Audio2FaceServiceStub(
                self._channel,
            )
            self._connected = True
            logger.info("Connected to Audio2Face NIM at %s", target)
            return True
        except (ImportError, Exception) as exc:
            logger.warning(
                "Failed to connect to Audio2Face NIM: %s. "
                "Using local fallback.", exc,
            )
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Close the gRPC channel."""
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass
        self._channel = None
        self._stub = None
        self._connected = False

    def process_audio_chunk(
        self, audio: np.ndarray, sr: int,
    ) -> BlendshapeFrame:
        """Send audio to NIM and receive blendshapes.

        Falls back to local adapter on any gRPC error.
        """
        if not self._connected:
            if not self.connect():
                return self._fallback.process_audio_chunk(audio, sr)
        try:
            return self._grpc_infer(audio, sr)
        except Exception as exc:
            logger.warning(
                "Audio2Face NIM inference failed: %s. Using fallback.", exc,
            )
            self._connected = False
            return self._fallback.process_audio_chunk(audio, sr)

    def _grpc_infer(self, audio: np.ndarray, sr: int) -> BlendshapeFrame:
        """Perform gRPC inference call."""
        from nvidia_audio2face_3d import (  # type: ignore[import-untyped]
            audio2face_pb2,
        )
        request = audio2face_pb2.Audio2FaceRequest(
            audio_data=audio.astype(np.float32).tobytes(),
            sample_rate=sr,
        )
        t0 = time.perf_counter()
        response = self._stub.ProcessAudio(request, timeout=self._timeout)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        raw = np.array(response.blendshapes, dtype=np.float32)
        if raw.shape[0] < NUM_ARKIT_BLENDSHAPES:
            raise ExpressionError(
                f"NIM returned {raw.shape[0]} blendshapes, "
                f"expected {NUM_ARKIT_BLENDSHAPES}",
                {"got": raw.shape[0]},
            )
        coeffs = np.clip(raw[:NUM_ARKIT_BLENDSHAPES], 0.0, 1.0)
        return BlendshapeFrame(
            coefficients=coeffs,
            timestamp=time.monotonic(),
            duration_ms=elapsed_ms,
        )

    def reset(self) -> None:
        """Reset connection and fallback state."""
        self.disconnect()
        self._fallback.reset()


# ---------------------------------------------------------------------------
# Audio2FaceLocal: signal-processing fallback
# ---------------------------------------------------------------------------

class Audio2FaceLocal(Audio2FaceAdapter):
    """Local audio-to-blendshape using signal processing (no NIM).

    Extracts F0 (pitch), RMS energy, spectral centroid, and zero-crossing
    rate from audio and maps them to ARKit blendshapes. Uses EMA temporal
    smoothing to prevent jitter.

    Args:
        ema_alpha: EMA smoothing factor (0, 1]. Higher = more responsive.
        silence_threshold: RMS below this is considered silence.
        f0_range: Tuple of (min_hz, max_hz) for expected F0 range.
    """

    def __init__(
        self,
        ema_alpha: float = 0.4,
        silence_threshold: float = 0.015,
        f0_range: tuple[float, float] = (80.0, 400.0),
    ) -> None:
        if not (0.0 < ema_alpha <= 1.0):
            raise ExpressionError(
                "ema_alpha must be in (0, 1]", {"ema_alpha": ema_alpha},
            )
        self._alpha = ema_alpha
        self._silence_threshold = silence_threshold
        self._f0_lo, self._f0_hi = f0_range
        self._prev_coeffs: np.ndarray | None = None

    def reset(self) -> None:
        """Reset EMA smoothing state."""
        self._prev_coeffs = None

    def process_audio_chunk(
        self, audio: np.ndarray, sr: int,
    ) -> BlendshapeFrame:
        """Convert audio chunk to blendshapes via signal processing."""
        t0 = time.perf_counter()
        audio = self._validate_audio(audio, sr)

        rms = self._compute_rms(audio)
        is_silence = rms < self._silence_threshold

        if is_silence:
            coeffs = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        else:
            f0 = self._estimate_f0(audio, sr)
            centroid = self._spectral_centroid(audio, sr)
            zcr = self._zero_crossing_rate(audio)
            coeffs = self._map_features(rms, f0, centroid, zcr, sr)

        coeffs = self._apply_ema(coeffs)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return BlendshapeFrame(
            coefficients=coeffs,
            timestamp=time.monotonic(),
            duration_ms=elapsed_ms,
        )

    # -- Validation ----------------------------------------------------------

    @staticmethod
    def _validate_audio(audio: np.ndarray, sr: int) -> np.ndarray:
        """Validate and prepare audio for processing."""
        if audio.size == 0:
            raise ExpressionError("Audio chunk is empty", {"size": 0})
        if np.any(np.isnan(audio)):
            raise ExpressionError(
                "Audio chunk contains NaN values",
                {"nan_count": int(np.sum(np.isnan(audio)))},
            )
        if sr <= 0:
            raise ExpressionError(
                "Sample rate must be positive", {"sr": sr},
            )
        if audio.ndim != 1:
            audio = audio.flatten()
        return audio.astype(np.float32)

    # -- Feature extraction --------------------------------------------------

    @staticmethod
    def _compute_rms(audio: np.ndarray) -> float:
        """Compute RMS energy of audio chunk."""
        return float(np.sqrt(np.mean(audio ** 2)))

    @staticmethod
    def _estimate_f0(audio: np.ndarray, sr: int) -> float:
        """Estimate F0 via autocorrelation. Returns 0.0 if unvoiced."""
        if len(audio) < 64:
            return 0.0
        n = len(audio)
        centered = audio - np.mean(audio)
        fft_size = 1
        while fft_size < 2 * n:
            fft_size *= 2
        fft_audio = np.fft.rfft(centered, fft_size)
        acf = np.fft.irfft(fft_audio * np.conj(fft_audio))[:n]
        if acf[0] > 0:
            acf = acf / acf[0]
        else:
            return 0.0

        min_lag = max(2, sr // 500)
        max_lag = min(n - 1, sr // 60)
        if min_lag >= max_lag or max_lag >= len(acf):
            return 0.0
        segment = acf[min_lag:max_lag + 1]
        if len(segment) == 0:
            return 0.0
        peak_idx = int(np.argmax(segment))
        if segment[peak_idx] < 0.2:
            return 0.0
        lag = min_lag + peak_idx
        return float(sr / lag) if lag > 0 else 0.0

    @staticmethod
    def _spectral_centroid(audio: np.ndarray, sr: int) -> float:
        """Compute spectral centroid (brightness) in Hz."""
        magnitude = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), d=1.0 / sr)
        total = np.sum(magnitude)
        if total < 1e-10:
            return 0.0
        return float(np.sum(freqs * magnitude) / total)

    @staticmethod
    def _zero_crossing_rate(audio: np.ndarray) -> float:
        """Compute zero-crossing rate in [0, 1]."""
        if len(audio) < 2:
            return 0.0
        signs = np.sign(audio)
        crossings = np.sum(np.abs(np.diff(signs)) > 0)
        return float(crossings / (len(audio) - 1))

    # -- Feature-to-blendshape mapping ---------------------------------------

    def _map_features(
        self, rms: float, f0: float, centroid: float,
        zcr: float, sr: int,
    ) -> np.ndarray:
        """Map audio features to 52 ARKit blendshape coefficients."""
        c = np.zeros(NUM_ARKIT_BLENDSHAPES, dtype=np.float32)
        idx = BLENDSHAPE_INDEX

        rms_n = clamp(rms / 0.25)
        f0_n = 0.0
        if f0 > 0:
            f0_n = clamp(
                (f0 - self._f0_lo) / (self._f0_hi - self._f0_lo),
            )
        cent_n = clamp(centroid / (sr * 0.25))

        # Jaw / Mouth
        jaw = clamp(rms_n * 0.85)
        c[idx["jawOpen"]] = jaw
        c[idx["mouthClose"]] = clamp((1.0 - jaw) * 0.3)
        c[idx["mouthFunnel"]] = clamp(rms_n * 0.4 * (1.0 - zcr))
        c[idx["mouthPucker"]] = clamp((1.0 - cent_n) * rms_n * 0.35)
        c[idx["mouthLowerDownLeft"]] = clamp(jaw * 0.6)
        c[idx["mouthLowerDownRight"]] = clamp(jaw * 0.6)
        c[idx["mouthUpperUpLeft"]] = clamp(jaw * 0.25)
        c[idx["mouthUpperUpRight"]] = clamp(jaw * 0.25)

        # Smile / Frown
        smile = clamp(cent_n * 0.6)
        frown = clamp((1.0 - cent_n) * 0.3 * rms_n)
        c[idx["mouthSmileLeft"]] = smile
        c[idx["mouthSmileRight"]] = smile
        c[idx["mouthFrownLeft"]] = frown
        c[idx["mouthFrownRight"]] = frown

        # Mouth stretch (fricatives)
        c[idx["mouthStretchLeft"]] = clamp(zcr * rms_n * 0.5)
        c[idx["mouthStretchRight"]] = clamp(zcr * rms_n * 0.5)

        # Brows
        brow_up = clamp(f0_n * 0.5)
        c[idx["browInnerUp"]] = brow_up
        c[idx["browOuterUpLeft"]] = clamp(brow_up * 0.7)
        c[idx["browOuterUpRight"]] = clamp(brow_up * 0.7)
        if f0_n < 0.3 and rms_n > 0.5:
            bd = clamp((0.3 - f0_n) * rms_n * 1.5)
            c[idx["browDownLeft"]] = bd
            c[idx["browDownRight"]] = bd

        # Eyes
        c[idx["eyeBlinkLeft"]] = clamp((1.0 - rms_n) * 0.05)
        c[idx["eyeBlinkRight"]] = clamp((1.0 - rms_n) * 0.05)
        if f0_n > 0.7:
            ew = clamp((f0_n - 0.7) * 1.5)
            c[idx["eyeWideLeft"]] = ew
            c[idx["eyeWideRight"]] = ew

        # Cheek squint with smile
        c[idx["cheekSquintLeft"]] = clamp(smile * 0.4)
        c[idx["cheekSquintRight"]] = clamp(smile * 0.4)

        return c

    def _apply_ema(self, coeffs: np.ndarray) -> np.ndarray:
        """Apply exponential moving average smoothing."""
        if self._prev_coeffs is None:
            self._prev_coeffs = coeffs.copy()
            return coeffs
        smoothed = (
            self._alpha * coeffs
            + (1.0 - self._alpha) * self._prev_coeffs
        )
        smoothed = np.clip(smoothed, 0.0, 1.0).astype(np.float32)
        self._prev_coeffs = smoothed.copy()
        return smoothed
