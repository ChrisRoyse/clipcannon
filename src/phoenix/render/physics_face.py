"""Physics-based face animation from audio signal properties.

Computes face deformation directly from acoustic physics -- no training
data needed, works for ANY voice in ANY language.

The relationship between audio and face shape is governed by physics:
  - Formant F1 (300-800 Hz) -> jaw opening (higher F1 = more open)
  - Formant F2 (800-2500 Hz) -> tongue front/back -> lip spread vs round
  - Formant F3 (2500-3500 Hz) -> lip rounding refinement
  - F0 (pitch) -> larynx height -> chin/neck tension
  - Energy envelope -> overall facial tension/effort
  - Zero-crossing rate -> fricative vs vowel -> teeth visibility

These are deterministic articulatory-acoustic mappings.

Usage:
    physics = PhysicsFaceEngine(sample_rate=24000, fps=30)
    face = physics.process_audio_chunk(audio_chunk)
    blendshapes = face.to_blendshapes()    # 52 ARKit blendshapes
    exp, jaw = face.to_flame_params()       # FLAME expression + jaw
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

import numpy as np

from phoenix.render.audio_features import (
    clamp as _clamp,
    extract_f0_yin as _extract_f0_yin,
    extract_formants_lpc as _extract_formants_lpc,
    zero_crossing_rate as _zero_crossing_rate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FaceState
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class FaceState:
    """Complete face state derived from audio physics.

    All values are normalized to [0, 1] unless noted otherwise.
    """
    jaw_open: float = 0.0
    lip_spread: float = 0.0
    lip_round: float = 0.0
    lip_pucker: float = 0.0
    tongue_front: float = 0.0
    teeth_visible: float = 0.0
    chin_tension: float = 0.0
    effort: float = 0.0
    brow_raise: float = 0.0
    squint: float = 0.0
    head_nod: float = 0.0
    is_silence: bool = True
    # Raw features (debugging / downstream)
    _f0: float = 0.0
    _f1: float = 0.0
    _f2: float = 0.0
    _f3: float = 0.0
    _energy: float = 0.0
    _zcr: float = 0.0

    def to_blendshapes(self) -> dict[str, float]:
        """Convert to ARKit-compatible blendshapes (52 channels)."""
        bs: dict[str, float] = {}
        smile = self.lip_spread * 0.5

        # Jaw
        bs["jawOpen"] = self.jaw_open
        bs["jawForward"] = self.effort * 0.3
        bs["jawLeft"] = 0.0
        bs["jawRight"] = 0.0

        # Mouth shape
        bs["mouthSmileLeft"] = smile
        bs["mouthSmileRight"] = smile
        bs["mouthPucker"] = self.lip_pucker
        bs["mouthFunnel"] = self.lip_round
        bs["mouthClose"] = _clamp(1.0 - self.jaw_open) if self.is_silence else 0.0
        bs["mouthStretchLeft"] = self.lip_spread * 0.3
        bs["mouthStretchRight"] = self.lip_spread * 0.3
        bs["mouthUpperUpLeft"] = self.jaw_open * 0.3
        bs["mouthUpperUpRight"] = self.jaw_open * 0.3
        bs["mouthLowerDownLeft"] = self.jaw_open * 0.5
        bs["mouthLowerDownRight"] = self.jaw_open * 0.5
        bs["mouthShrugUpper"] = self.effort * 0.2
        bs["mouthShrugLower"] = self.effort * 0.15
        bs["mouthRollUpper"] = self.lip_round * 0.2
        bs["mouthRollLower"] = self.lip_round * 0.15
        bs["mouthPressLeft"] = self.effort * 0.1
        bs["mouthPressRight"] = self.effort * 0.1
        bs["mouthDimpleLeft"] = smile * 0.2
        bs["mouthDimpleRight"] = smile * 0.2
        bs["mouthFrownLeft"] = 0.0
        bs["mouthFrownRight"] = 0.0
        bs["mouthLeft"] = 0.0
        bs["mouthRight"] = 0.0

        # Teeth: fricatives drive subtle mouth open
        bs["jawOpen"] = max(bs["jawOpen"], self.teeth_visible * 0.15)

        # Brow
        bs["browInnerUp"] = self.brow_raise
        bs["browOuterUpLeft"] = self.brow_raise * 0.5
        bs["browOuterUpRight"] = self.brow_raise * 0.5
        bs["browDownLeft"] = 0.0
        bs["browDownRight"] = 0.0

        # Eyes
        bs["eyeSquintLeft"] = self.squint
        bs["eyeSquintRight"] = self.squint
        bs["eyeBlinkLeft"] = 0.0
        bs["eyeBlinkRight"] = 0.0
        bs["eyeWideLeft"] = self.brow_raise * 0.3
        bs["eyeWideRight"] = self.brow_raise * 0.3
        bs["eyeLookUpLeft"] = 0.0
        bs["eyeLookUpRight"] = 0.0
        bs["eyeLookDownLeft"] = 0.0
        bs["eyeLookDownRight"] = 0.0
        bs["eyeLookInLeft"] = 0.0
        bs["eyeLookInRight"] = 0.0
        bs["eyeLookOutLeft"] = 0.0
        bs["eyeLookOutRight"] = 0.0

        # Cheek / nose
        bs["cheekPuff"] = self.lip_round * 0.1
        bs["cheekSquintLeft"] = self.squint * 0.3
        bs["cheekSquintRight"] = self.squint * 0.3
        bs["noseSneerLeft"] = self.effort * 0.15
        bs["noseSneerRight"] = self.effort * 0.15

        for k in bs:
            bs[k] = _clamp(bs[k])
        return bs

    def to_flame_params(self) -> tuple[Any, Any]:
        """Convert to FLAME expression (100-dim) + jaw_pose (3-dim).

        Returns numpy arrays: expression (100,) float32, jaw (3,) float32.
        """
        exp = np.zeros(100, dtype=np.float32)
        exp[0] = self.jaw_open * 5.0       # jaw drop
        exp[1] = self.lip_spread * 3.0     # lip stretch
        exp[2] = self.lip_pucker * 4.0 - self.lip_spread * 2.0
        exp[3] = self.jaw_open * 1.5       # upper lip raise
        exp[4] = self.jaw_open * 2.0       # lower lip depress
        exp[5] = self.brow_raise * 3.0
        exp[6] = self.squint * 2.0
        exp[7] = self.effort * 2.5
        exp[8] = self.lip_round * 1.5      # lip roll
        exp[9] = self.chin_tension * 2.0

        jaw = np.zeros(3, dtype=np.float32)
        jaw[0] = self.jaw_open * 0.4       # X rotation (open/close)
        return exp, jaw

    def to_flame_params_torch(self, device: str = "cuda") -> tuple[Any, Any]:
        """Like to_flame_params but returns torch tensors on device."""
        import torch
        exp_np, jaw_np = self.to_flame_params()
        return (
            torch.from_numpy(exp_np).to(device),
            torch.from_numpy(jaw_np).to(device),
        )


# ---------------------------------------------------------------------------
# PhysicsFaceEngine
# ---------------------------------------------------------------------------

class PhysicsFaceEngine:
    """Deterministic audio-to-face engine based on articulatory acoustics.

    Maps audio signal properties (formants, F0, energy, ZCR) to face
    parameters using the known physics of speech production.  No ML
    models, no training data.  Works for any voice, any language.

    Args:
        sample_rate: Audio sample rate in Hz (default 24000).
        fps: Target video frame rate (default 30).
        smoothing_alpha: EMA smoothing factor (0 = no smooth, 1 = instant).
        lpc_order: LPC analysis order for formant extraction.
        silence_threshold: RMS energy below this = silence.
    """

    def __init__(
        self,
        sample_rate: int = 24000,
        fps: int = 30,
        smoothing_alpha: float = 0.55,
        lpc_order: int = 12,
        silence_threshold: float = 0.01,
    ) -> None:
        self._sr = sample_rate
        self._fps = fps
        self._alpha = smoothing_alpha
        self._lpc_order = lpc_order
        self._silence_threshold = silence_threshold
        self._spf = sample_rate // fps

        # EMA state
        self._prev = FaceState()
        self._prev_f0 = 0.0

        # Adaptive energy normalization
        self._max_energy = 0.05
        self._energy_decay = 0.999

        # Temporal histories
        self._f0_history: list[float] = []
        self._f0_history_max = 10
        self._energy_history: list[float] = []
        self._energy_history_max = 15

        logger.debug(
            "PhysicsFaceEngine: sr=%d fps=%d lpc=%d alpha=%.2f",
            sample_rate, fps, lpc_order, smoothing_alpha,
        )

    def reset(self) -> None:
        """Reset all temporal state between utterances."""
        self._prev = FaceState()
        self._prev_f0 = 0.0
        self._f0_history.clear()
        self._energy_history.clear()

    @property
    def samples_per_frame(self) -> int:
        """Number of audio samples expected per frame."""
        return self._spf

    def process_audio_chunk(self, audio: np.ndarray) -> FaceState:
        """Process one frame's worth of audio and return face state.

        Args:
            audio: Float32 mono audio chunk.

        Returns:
            FaceState with all face parameters for this frame.
        """
        if audio.ndim != 1:
            audio = audio.flatten()

        # RMS energy
        energy = float(np.sqrt(np.mean(audio ** 2))) if len(audio) > 0 else 0.0

        # Adaptive max energy
        if energy > self._max_energy:
            self._max_energy = energy
        else:
            self._max_energy *= self._energy_decay

        if energy < self._silence_threshold:
            return self._smooth(self._make_silence_state())

        # Feature extraction
        f1, f2, f3 = _extract_formants_lpc(audio, self._sr, self._lpc_order)
        f0 = _extract_f0_yin(audio, self._sr)
        zcr = _zero_crossing_rate(audio, self._sr)

        # Articulatory-acoustic mapping
        max_e = max(self._max_energy, 0.01)
        jaw_open = _clamp((f1 - 300) / 500) if f1 > 0 else energy / max_e
        lip_spread = _clamp((f2 - 800) / 1700) if f2 > 0 else 0.0
        lip_round = _clamp(1.0 - lip_spread)
        lip_pucker = _clamp((2500 - f2) / 1000) if f2 > 0 else 0.0
        teeth_visible = _clamp(zcr / 5000) if zcr > 2000 else 0.0
        chin_tension = _clamp(f0 / 300) if f0 > 0 else 0.0
        effort = _clamp(energy / max_e)

        # Brow raise from energy peaks
        self._energy_history.append(energy)
        if len(self._energy_history) > self._energy_history_max:
            self._energy_history.pop(0)
        if len(self._energy_history) >= 3:
            mean_e = float(np.mean(self._energy_history[:-1]))
            brow_raise = _clamp((energy - mean_e) / max(mean_e, 0.01) * 0.5)
        else:
            brow_raise = 0.0

        squint = _clamp(effort - 0.6) * 0.5

        # Head nod from F0 slope
        self._f0_history.append(f0 if f0 > 0 else self._prev_f0)
        if len(self._f0_history) > self._f0_history_max:
            self._f0_history.pop(0)
        if len(self._f0_history) >= 3:
            recent = self._f0_history[-3:]
            slope = (recent[-1] - recent[0]) / (len(recent) / self._fps)
            head_nod = _clamp(slope / 200 + 0.5)
        else:
            head_nod = 0.5

        self._prev_f0 = f0 if f0 > 0 else self._prev_f0

        state = FaceState(
            jaw_open=jaw_open, lip_spread=lip_spread, lip_round=lip_round,
            lip_pucker=lip_pucker, tongue_front=lip_spread,
            teeth_visible=teeth_visible, chin_tension=chin_tension,
            effort=effort, brow_raise=brow_raise, squint=squint,
            head_nod=head_nod, is_silence=False,
            _f0=f0, _f1=f1, _f2=f2, _f3=f3, _energy=energy, _zcr=zcr,
        )
        return self._smooth(state)

    def process_audio_batch(self, audio: np.ndarray) -> list[FaceState]:
        """Process a full audio clip, one FaceState per frame."""
        if audio.ndim != 1:
            audio = audio.flatten()
        n_frames = max(1, len(audio) // self._spf)
        return [
            self.process_audio_chunk(audio[i * self._spf:(i + 1) * self._spf])
            for i in range(n_frames)
        ]

    def _make_silence_state(self) -> FaceState:
        return FaceState(
            tongue_front=0.5, head_nod=0.5, is_silence=True,
        )

    def _smooth(self, state: FaceState) -> FaceState:
        """EMA temporal smoothing with per-region rates."""
        a_fast = self._alpha
        a_med = self._alpha * 0.7
        a_slow = self._alpha * 0.4

        def ema(new: float, old: float, a: float) -> float:
            return a * new + (1 - a) * old

        p = self._prev
        smoothed = FaceState(
            jaw_open=ema(state.jaw_open, p.jaw_open, a_fast),
            lip_spread=ema(state.lip_spread, p.lip_spread, a_fast),
            lip_round=ema(state.lip_round, p.lip_round, a_fast),
            lip_pucker=ema(state.lip_pucker, p.lip_pucker, a_fast),
            tongue_front=ema(state.tongue_front, p.tongue_front, a_fast),
            teeth_visible=ema(state.teeth_visible, p.teeth_visible, a_fast),
            chin_tension=ema(state.chin_tension, p.chin_tension, a_fast),
            effort=ema(state.effort, p.effort, a_fast),
            brow_raise=ema(state.brow_raise, p.brow_raise, a_med),
            squint=ema(state.squint, p.squint, a_med),
            head_nod=ema(state.head_nod, p.head_nod, a_slow),
            is_silence=state.is_silence,
            _f0=state._f0, _f1=state._f1, _f2=state._f2, _f3=state._f3,
            _energy=state._energy, _zcr=state._zcr,
        )
        self._prev = smoothed
        return smoothed
