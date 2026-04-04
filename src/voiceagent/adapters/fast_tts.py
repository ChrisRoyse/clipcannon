"""Fast TTS adapter using faster-qwen3-tts (0.6B) with CUDA graphs.

Purpose-built for real-time voice agent conversations:
  - ~100-150ms TTFB (streaming with chunk_size=2 on RTX 5090)
  - Streaming chunk-by-chunk synthesis (yields ~167ms audio per chunk)
  - CUDA graph capture for 4-5x speedup over vanilla Qwen3-TTS
  - Full ICL mode with ref_text for accurate accent/cadence cloning
  - Runtime voice switching between pre-loaded profiles
  - 0.6B model (vs 1.7B for ClipCannon video generation)

This adapter is SEPARATE from ClipCannonAdapter which uses the full
1.7B model for high-quality video generation. The voice agent uses
this fast adapter; ClipCannon tools are unaffected.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import numpy as np
import torch

from voiceagent.errors import TTSError

logger = logging.getLogger(__name__)

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
SAMPLE_RATE = 24000


# Streaming chunk size in codec tokens. Each token = ~83ms audio.
# 2 = ~167ms (fast TTFB but metallic artifacts at chunk boundaries)
# 4 = ~333ms (smooth audio quality, still fast TTFB)
# 12 = ~1000ms (original default, too slow for real-time)
# chunk_size=4 is the sweet spot: natural voice quality without
# audible chunk-boundary artifacts while maintaining <400ms TTFB.
STREAMING_CHUNK_SIZE = 4


class FastTTSAdapter:
    """Real-time voice synthesis via faster-qwen3-tts with CUDA graphs.

    Uses the 0.6B Qwen3-TTS model with CUDA graph capture for
    ~100-150ms TTFB streaming synthesis. Supports runtime voice
    switching between loaded profiles.
    """

    PROJECTS_DIR: str = "~/.clipcannon/projects"
    VOICE_DATA_DIR: str = "~/.clipcannon/voice_data"
    DEFAULT_DB: str = "~/.clipcannon/voice_profiles.db"

    # Best reference clips per voice (manually curated for quality).
    # Falls through to voice_data/<name>/wavs/ if override path is missing.
    REAL_MIC_OVERRIDES: dict[str, str] = {
        "boris": "~/.clipcannon/voice_data/boris/wavs/clip_ac0b9f40.wav",
        "taylor": "~/.clipcannon/voice_data/taylor/wavs/clip_77702bd4_trimmed.wav",
        "santa": "~/.clipcannon/voice_data/santa/wavs/santa_best_ref.wav",
    }

    def __init__(
        self,
        voice_name: str = "boris",
        db_path: str | None = None,
        model_id: str = MODEL_ID,
    ) -> None:
        self._voice_name = voice_name
        self._model_id = model_id
        self._engine = None
        self._ref_audio: str | None = None
        self._ref_text: str | None = None  # For Full ICL mode
        self._sample_rate = SAMPLE_RATE
        self._warmed_up = False
        self._loaded_voices: dict[str, dict[str, str | None]] = {}

        # Find reference audio
        self._ref_audio, self._ref_text = self._find_reference_with_text(
            voice_name, db_path,
        )
        if self._ref_audio:
            logger.info("FastTTS ref: %s", Path(self._ref_audio).name)
            # Cache this voice
            self._loaded_voices[voice_name] = {
                "ref_audio": self._ref_audio,
                "ref_text": self._ref_text,
            }

    def switch_voice(self, voice_name: str) -> None:
        """Switch the active voice at runtime.

        If the voice was previously loaded, switches instantly.
        Otherwise loads the voice profile first.

        Args:
            voice_name: Name of the voice to switch to.

        Raises:
            TTSError: If no reference audio exists for the voice.
        """
        if voice_name == self._voice_name:
            return

        if voice_name in self._loaded_voices:
            voice = self._loaded_voices[voice_name]
            self._ref_audio = voice["ref_audio"]
            self._ref_text = voice["ref_text"]
            self._voice_name = voice_name
            logger.info("Switched to voice: %s (cached)", voice_name)
            return

        # Load new voice
        ref_audio, ref_text = self._find_reference_with_text(voice_name)
        if not ref_audio:
            raise TTSError(
                f"No reference audio for voice '{voice_name}'. "
                f"Create a voice profile with reference recordings first."
            )
        self._ref_audio = ref_audio
        self._ref_text = ref_text
        self._voice_name = voice_name
        self._loaded_voices[voice_name] = {
            "ref_audio": ref_audio,
            "ref_text": ref_text,
        }
        logger.info("Switched to voice: %s (newly loaded)", voice_name)

    @property
    def active_voice(self) -> str:
        """Currently active voice name."""
        return self._voice_name

    @property
    def available_voices(self) -> list[str]:
        """List of loaded voice names."""
        return list(self._loaded_voices.keys())

    def preload_voice(self, voice_name: str) -> None:
        """Pre-load a voice so switching is instant.

        Args:
            voice_name: Voice to pre-load from profiles DB.
        """
        if voice_name in self._loaded_voices:
            return
        ref_audio, ref_text = self._find_reference_with_text(voice_name)
        if ref_audio:
            self._loaded_voices[voice_name] = {
                "ref_audio": ref_audio,
                "ref_text": ref_text,
            }
            logger.info("Pre-loaded voice: %s", voice_name)

    def _find_reference_with_text(
        self,
        voice_name: str,
        db_path: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Find reference audio and transcribe for Full ICL mode.

        Returns:
            Tuple of (ref_audio_path, ref_text). ref_text may be None
            if transcription fails, in which case xvec_only mode is used.
        """
        # 1. Check real mic overrides (much better than Demucs clips)
        override = self.REAL_MIC_OVERRIDES.get(voice_name)
        if override:
            expanded = str(Path(override).expanduser())
            if Path(expanded).exists():
                logger.info("Using real mic override for %s", voice_name)
                ref_text = self._transcribe(expanded)
                return expanded, ref_text

        # 2. Try voice profiles DB for training project vocals
        db = str(Path(db_path or self.DEFAULT_DB).expanduser())
        try:
            from clipcannon.voice.profiles import get_voice_profile
            profile = get_voice_profile(db, voice_name)
        except (ImportError, OSError, KeyError) as e:
            logger.debug("Voice profile lookup failed for %s: %s", voice_name, e)
            profile = None

        if profile:
            training_raw = profile.get("training_projects", "[]")
            try:
                if isinstance(training_raw, str):
                    proj_ids = json.loads(training_raw)
                elif isinstance(training_raw, list):
                    proj_ids = training_raw
                else:
                    proj_ids = []
            except (json.JSONDecodeError, TypeError):
                proj_ids = []

            projects_dir = Path(self.PROJECTS_DIR).expanduser()
            for pid in proj_ids:
                vocals = projects_dir / pid / "stems" / "vocals.wav"
                if vocals.exists():
                    ref_text = self._transcribe(str(vocals))
                    return str(vocals), ref_text

        # 3. Fallback: first clip from voice_data
        wavs_dir = (
            Path(self.VOICE_DATA_DIR).expanduser()
            / voice_name / "wavs"
        )
        if wavs_dir.is_dir():
            clips = sorted(wavs_dir.glob("*.wav"))
            if clips:
                ref_text = self._transcribe(str(clips[0]))
                return str(clips[0]), ref_text

        return None, None

    @staticmethod
    def _transcribe(audio_path: str) -> str | None:
        """Transcribe reference audio for Full ICL ref_text."""
        try:
            from faster_whisper import WhisperModel
            whisper = WhisperModel("base", device="cpu", compute_type="int8")
            segs, _ = whisper.transcribe(audio_path, language="en")
            text = " ".join(s.text.strip() for s in segs)
            logger.info("Transcribed ref (%d chars): %s...", len(text), text[:60])
            return text if text.strip() else None
        except (ImportError, OSError, RuntimeError) as e:
            logger.warning("Transcription failed for %s: %s", audio_path, e)
            return None

    def _ensure_engine(self) -> object:
        """Lazy-load the faster-qwen3-tts engine."""
        if self._engine is not None:
            return self._engine

        try:
            from faster_qwen3_tts import FasterQwen3TTS
        except ImportError as e:
            raise TTSError(
                "faster-qwen3-tts required. "
                "Install: pip install faster-qwen3-tts"
            ) from e

        logger.info("Loading faster-qwen3-tts (%s)...", self._model_id)
        self._engine = FasterQwen3TTS.from_pretrained(
            self._model_id,
            device="cuda",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        logger.info("faster-qwen3-tts loaded")
        return self._engine

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate max TTS tokens from character count.

        At 12Hz token rate, 1 token = ~83ms of audio.
        English speech averages 14-16 characters per second.
        Formula: (chars / 14) * 12 tokens/sec * 1.3 headroom.
        """
        chars = len(text.strip())
        tokens = int(chars / 14.0 * 12.0 * 1.3)
        # Min 12 tokens (1s) for prosodic closure, max 360 (30s)
        return max(12, min(tokens, 360))

    def _clone_kwargs(
        self, text: str, max_new_tokens: int | None = None,
    ) -> dict:
        """Build kwargs for generate_voice_clone.

        Uses Full ICL when ref_text is available (better accent/cadence),
        falls back to xvec_only when only ref_audio is available.
        Scales temperature down for short utterances to make EOS
        prediction more reliable (prevents runaway generation).

        Raises:
            TTSError: If no reference audio is loaded.
        """
        if self._ref_audio is None:
            raise TTSError(
                f"No reference audio for voice '{self._voice_name}'. "
                f"Provide a voice profile or place WAV files in "
                f"{self.VOICE_DATA_DIR}/{self._voice_name}/wavs/"
            )
        if max_new_tokens is None:
            max_new_tokens = self._estimate_tokens(text)

        # Lower temperature for short text = more reliable EOS detection
        text_len = len(text.strip())
        temperature = 0.3 if text_len < 30 else 0.5
        top_p = 0.7 if text_len < 30 else 0.85

        kwargs: dict = {
            "text": text,
            "language": "English",
            "ref_audio": self._ref_audio,
            "temperature": temperature,
            "top_p": top_p,
            "max_new_tokens": max_new_tokens,
            "repetition_penalty": 1.2,
        }
        if self._ref_text:
            kwargs["ref_text"] = self._ref_text
            kwargs["xvec_only"] = False
        else:
            kwargs["xvec_only"] = True
        return kwargs

    def _warmup(self) -> None:
        """Warm up CUDA graphs at multiple sequence lengths.

        Three passes at short/medium/long to populate graph caches
        for varying input sizes, preventing recompilation during use.
        """
        if self._warmed_up:
            return
        engine = self._ensure_engine()
        logger.info("Warming up CUDA graphs (3 passes)...")
        warmup_cases = [
            ("Hi.", 12),
            ("I'm ready to help you today.", 36),
            ("The quick brown fox jumps over the lazy dog near the river bank.", 96),
        ]
        for text, tokens in warmup_cases:
            engine.generate_voice_clone(
                **self._clone_kwargs(text, max_new_tokens=tokens),
            )
        self._warmed_up = True
        logger.info("CUDA graphs ready (mode=%s)", "ICL" if self._ref_text else "xvec")

    @staticmethod
    def _trim_silence(audio: np.ndarray, sr: int = 24000) -> np.ndarray:
        """Trim trailing silence and degraded audio from TTS output.

        Two-pass trimming:
        1. Forward pass: find where speech energy drops significantly
           compared to the peak energy (catches garbled/degraded tail)
        2. Backward pass: find last non-silent window (catches silence)

        This prevents both:
        - Silence padding (model generates tokens past EOS)
        - Voice quality degradation (model output becomes generic/garbled)
        """
        if len(audio) == 0:
            return audio

        window = int(sr * 0.1)  # 100ms windows
        silence_threshold = 0.003

        # Forward pass: compute energy per window, find where it drops
        energies = []
        for i in range(0, len(audio) - window, window):
            chunk = audio[i : i + window]
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            energies.append(rms)

        if not energies:
            return audio

        # Find the peak energy in the first half (where real speech is)
        half = max(1, len(energies) // 2)
        peak_energy = max(energies[:half]) if any(e > 0 for e in energies[:half]) else 0.01

        # Find where energy drops below 10% of peak for 3+ consecutive windows
        # This catches the transition from real speech to garbled/degraded output
        cutoff_window = len(energies)
        consecutive_low = 0
        for i, e in enumerate(energies):
            if e < peak_energy * 0.1:
                consecutive_low += 1
                if consecutive_low >= 3:
                    cutoff_window = i - 2  # Back up to start of low region
                    break
            else:
                consecutive_low = 0

        # Backward pass: from cutoff, find last non-silent window
        last_speech = cutoff_window * window
        for i in range(min(cutoff_window, len(energies)) - 1, -1, -1):
            if energies[i] > silence_threshold:
                last_speech = (i + 1) * window + int(sr * 0.15)  # 150ms pad
                break

        last_speech = min(last_speech, len(audio))
        if last_speech < len(audio):
            audio = audio[:last_speech]
            # Gentle 50ms fade-out
            fade_len = min(int(sr * 0.05), len(audio))
            if fade_len > 0:
                fade = np.linspace(1.0, 0.0, fade_len)
                audio[-fade_len:] *= fade

        return audio

    async def synthesize(self, text: str) -> np.ndarray:
        """Synthesize text to float32 audio array (non-streaming).

        Returns complete audio after full generation, with trailing
        silence trimmed. ~500-900ms for short sentences after warmup.
        """
        if not text or not text.strip():
            raise TTSError("Cannot synthesize empty text.")

        def _generate() -> np.ndarray:
            self._warmup()
            engine = self._ensure_engine()
            wavs, sr = engine.generate_voice_clone(**self._clone_kwargs(text))
            self._sample_rate = sr
            wav = wavs[0]
            if not isinstance(wav, np.ndarray):
                wav = wav.cpu().numpy()
            wav = wav.astype(np.float32)
            return self._trim_silence(wav, sr)

        return await asyncio.to_thread(_generate)

    async def synthesize_streaming(
        self,
        text: str,
    ) -> AsyncIterator[np.ndarray]:
        """Stream audio chunks as they are generated.

        Yields numpy arrays of float32 audio at 24kHz.
        First chunk arrives in ~500ms (TTFB).

        Uses a thread + queue so chunks are yielded as soon as the
        TTS engine produces them, rather than waiting for all chunks.
        """
        if not text or not text.strip():
            raise TTSError("Cannot synthesize empty text.")

        import queue as queue_mod
        import threading

        q: queue_mod.Queue[np.ndarray | None] = queue_mod.Queue()

        def _generate() -> None:
            try:
                self._warmup()
                engine = self._ensure_engine()
                kwargs = self._clone_kwargs(text, max_new_tokens=256)
                kwargs["chunk_size"] = STREAMING_CHUNK_SIZE
                for chunk_audio, sr, _info in engine.generate_voice_clone_streaming(**kwargs):
                    self._sample_rate = sr
                    q.put(chunk_audio.astype(np.float32))
            except (TTSError, RuntimeError, OSError) as e:
                logger.error("TTS streaming error: %s", e)
            finally:
                q.put(None)  # sentinel

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()

        loop = asyncio.get_event_loop()
        while True:
            chunk = await loop.run_in_executor(None, q.get)
            if chunk is None:
                break
            yield chunk

    @property
    def sample_rate(self) -> int:
        """Output sample rate (24000 Hz)."""
        return self._sample_rate

    def release(self) -> None:
        """Free GPU resources."""
        if self._engine is not None:
            del self._engine
            self._engine = None
            self._warmed_up = False
            import gc
            gc.collect()
            torch.cuda.empty_cache()
            logger.info("FastTTS released")
