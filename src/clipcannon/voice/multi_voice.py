"""Multi-voice synthesis for conversational scenarios.

Enables Jarvis to swap between multiple voice profiles mid-conversation,
supporting scenarios like two people talking back and forth.

Usage:
    mv = MultiVoiceSynth()
    mv.load_voice("boris", ref_audio=Path("chris_ref.wav"), ref_text="...")
    mv.load_voice("taylor", ref_audio=Path("taylor_ref.wav"), ref_text="...")

    # Generate a conversation
    script = [
        ("boris", "Hey Taylor, what do you think about this?"),
        ("taylor", "I think it's absolutely amazing!"),
        ("boris", "I knew you'd love it."),
    ]
    output = mv.generate_conversation(script, output_path)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

logger = logging.getLogger(__name__)


@dataclass
class VoiceProfile:
    """Loaded voice with cached prompt for fast switching."""

    name: str
    prompt: object  # VoiceClonePromptItem
    ref_text: str
    ref_audio: Path


@dataclass
class ConversationResult:
    """Result of a multi-voice conversation generation."""

    audio_path: Path
    duration_ms: int
    sample_rate: int
    lines_generated: int
    voices_used: list[str]
    elapsed_s: float


class MultiVoiceSynth:
    """Multi-voice synthesizer with instant voice swapping.

    Loads all voice prompts at init time so switching between
    voices during generation is instant (no model reloading).
    """

    def __init__(self) -> None:
        self._voices: dict[str, VoiceProfile] = {}
        self._engine: object | None = None

    def _ensure_engine(self) -> object:
        if self._engine is not None:
            return self._engine

        from clipcannon.voice.inference import VoiceSynthesizer
        synth = VoiceSynthesizer()
        self._engine = synth._ensure_engine()
        return self._engine

    def load_voice(
        self,
        name: str,
        ref_audio: Path,
        ref_text: str,
    ) -> None:
        """Load a voice profile for use in conversations.

        Args:
            name: Voice name (e.g., "boris", "taylor").
            ref_audio: Path to reference recording (5-15s).
            ref_text: Transcript of the reference audio.
        """
        from clipcannon.voice.inference import _trim_reference

        engine = self._ensure_engine()
        ref_path = _trim_reference(ref_audio)

        prompt = engine.create_voice_clone_prompt(
            ref_audio=str(ref_path),
            ref_text=ref_text,
            x_vector_only_mode=False,
        )

        self._voices[name] = VoiceProfile(
            name=name,
            prompt=prompt,
            ref_text=ref_text,
            ref_audio=ref_audio,
        )
        logger.info("Loaded voice: %s (ref: %s)", name, ref_audio.name)

    def load_voice_from_profile(
        self, profile_name: str, ref_audio_override: Path | None = None,
    ) -> None:
        """Load a voice from the ClipCannon voice profiles database.

        Automatically selects the best reference clip and transcribes it.
        For best results, provide a real mic recording via ref_audio_override
        instead of using Demucs-processed training clips.

        Args:
            profile_name: Name in voice_profiles table (e.g., "boris", "taylor").
            ref_audio_override: Optional path to a real mic recording to use
                as the ICL reference. Produces much better clones than
                source-separated training clips.
        """
        from clipcannon.voice.profiles import get_voice_profile

        db_path = Path.home() / ".clipcannon" / "voice_profiles.db"
        profile = get_voice_profile(db_path, profile_name)
        if profile is None:
            raise ValueError(f"Voice profile not found: {profile_name}")

        if ref_audio_override is not None:
            best_ref = ref_audio_override
        else:
            from clipcannon.voice.optimize import select_best_reference
            from clipcannon.voice.verify import VoiceVerifier

            ref_emb = np.frombuffer(
                profile["reference_embedding"], dtype=np.float32,
            ).copy()

            # Find best reference clip from training data
            voice_data = Path.home() / ".clipcannon" / "voice_data" / profile_name / "wavs"
            clips = sorted(voice_data.glob("*.wav"))
            if not clips:
                raise ValueError(f"No voice clips found for {profile_name}")

            verifier = VoiceVerifier(ref_emb, threshold=0.50)
            _, best_ref = select_best_reference(clips, verifier, max_candidates=20)
            verifier.release()

        # Transcribe the reference for Full ICL
        from faster_whisper import WhisperModel
        whisper = WhisperModel("base", device="cpu", compute_type="int8")
        segs, _ = whisper.transcribe(str(best_ref), language="en")
        ref_text = " ".join(s.text.strip() for s in segs)

        self.load_voice(profile_name, best_ref, ref_text)

    def speak(
        self,
        voice_name: str,
        text: str,
        output_path: Path,
        temperature: float = 0.5,
        seed: int | None = None,
    ) -> tuple[np.ndarray, int]:
        """Generate speech in a specific voice.

        Args:
            voice_name: Which voice to use.
            text: Text to synthesize.
            output_path: Where to save the WAV.
            temperature: Sampling temperature.
            seed: Random seed (None for random).

        Returns:
            Tuple of (wav_numpy, sample_rate).
        """
        if voice_name not in self._voices:
            raise ValueError(
                f"Voice '{voice_name}' not loaded. "
                f"Available: {list(self._voices.keys())}"
            )

        engine = self._ensure_engine()
        voice = self._voices[voice_name]

        if seed is not None:
            torch.manual_seed(seed)
        else:
            torch.manual_seed(int(torch.randint(0, 2**31, (1,)).item()))

        wavs, sr = engine.generate_voice_clone(
            text=text,
            language="English",
            voice_clone_prompt=voice.prompt,
            max_new_tokens=2048,
            temperature=temperature,
            top_p=0.85,
            repetition_penalty=1.05,
        )

        wav_np = wavs[0] if isinstance(wavs[0], np.ndarray) else wavs[0].cpu().numpy()
        sf.write(str(output_path), wav_np, sr)
        return wav_np, sr

    def generate_conversation(
        self,
        script: list[tuple[str, str]],
        output_path: Path,
        pause_between_lines_ms: int = 500,
        temperature: float = 0.5,
    ) -> ConversationResult:
        """Generate a multi-voice conversation from a script.

        Args:
            script: List of (voice_name, text) tuples.
            output_path: Where to save the combined WAV.
            pause_between_lines_ms: Silence between lines (ms).
            temperature: Sampling temperature.

        Returns:
            ConversationResult with combined audio details.
        """
        start = time.monotonic()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        all_segments: list[np.ndarray] = []
        sr = 24000  # Qwen3-TTS output rate
        pause_samples = int(pause_between_lines_ms / 1000 * sr)
        silence = np.zeros(pause_samples, dtype=np.float32)

        voices_used = set()

        for i, (voice_name, text) in enumerate(script):
            logger.info(
                "[%d/%d] %s: %s",
                i + 1, len(script), voice_name, text[:50],
            )

            tmp_path = output_path.parent / f"_conv_line_{i}.wav"
            wav_np, line_sr = self.speak(
                voice_name, text, tmp_path, temperature=temperature,
            )

            # Resample if needed (shouldn't happen, but safety)
            if line_sr != sr:
                wav_t = torch.from_numpy(wav_np).float().unsqueeze(0)
                wav_t = torchaudio.functional.resample(wav_t, line_sr, sr)
                wav_np = wav_t.squeeze().numpy()

            all_segments.append(wav_np)
            if i < len(script) - 1:
                all_segments.append(silence)

            voices_used.add(voice_name)
            tmp_path.unlink(missing_ok=True)

        # Concatenate all segments
        combined = np.concatenate(all_segments)
        sf.write(str(output_path), combined, sr)

        elapsed = time.monotonic() - start
        duration_ms = int(len(combined) / sr * 1000)

        logger.info(
            "Conversation generated: %d lines, %d voices, %.1fs audio, %.1fs elapsed",
            len(script), len(voices_used), duration_ms / 1000, elapsed,
        )

        return ConversationResult(
            audio_path=output_path,
            duration_ms=duration_ms,
            sample_rate=sr,
            lines_generated=len(script),
            voices_used=sorted(voices_used),
            elapsed_s=round(elapsed, 2),
        )

    def release(self) -> None:
        """Release GPU memory."""
        import gc
        self._voices.clear()
        if self._engine is not None:
            del self._engine
            self._engine = None
        gc.collect()
        torch.cuda.empty_cache()
        logger.info("MultiVoiceSynth released")
