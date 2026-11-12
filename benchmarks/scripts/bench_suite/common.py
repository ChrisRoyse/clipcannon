"""Shared encoders, similarity, TTS generation and denoise helpers for the benchmarks."""
import logging
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

from .config import BENCH_DIR, GENERATED_DIR

logger = logging.getLogger(__name__)


def load_speechbrain_encoder():
    """Load SpeechBrain ECAPA-TDNN (192-dim, independent from our pipeline)."""
    from speechbrain.inference.speaker import SpeakerRecognition
    model_dir = BENCH_DIR / "models" / "speechbrain-ecapa"
    model_dir.mkdir(parents=True, exist_ok=True)
    model = SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(model_dir),
    )
    logger.info("SpeechBrain ECAPA-TDNN loaded (192-dim, independent encoder)")
    return model


def extract_sb_embedding(model, audio_path: Path) -> np.ndarray:
    """Extract 192-dim embedding using SpeechBrain (independent encoder)."""
    wav, sr = torchaudio.load(str(audio_path))
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)
    return model.encode_batch(wav).squeeze().cpu().numpy().astype(np.float32)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm > 1e-12 else 0.0


def generate_single(engine, text: str, ref_path: Path, ref_text: str,
                     temperature: float = 0.5, use_icl: bool = True) -> np.ndarray:
    """Generate a single TTS clip."""
    from clipcannon.voice.inference import _trim_reference
    trimmed = _trim_reference(ref_path)
    prompt = engine.create_voice_clone_prompt(
        ref_audio=str(trimmed),
        ref_text=ref_text if use_icl else None,
        x_vector_only_mode=not use_icl,
    )
    wavs, sr = engine.generate_voice_clone(
        text=text, language="English", voice_clone_prompt=prompt,
        max_new_tokens=2048, temperature=temperature,
        top_p=0.85, repetition_penalty=1.05,
    )
    wav_np = wavs[0] if isinstance(wavs[0], np.ndarray) else wavs[0].cpu().numpy()
    return wav_np, sr


def generate_best_of_n(engine, text: str, ref_path: Path, ref_text: str,
                        real_emb: np.ndarray, n: int = 8) -> tuple:
    """Generate N candidates, return best by SECS against real voice."""
    from clipcannon.voice.verify import _extract_embedding
    best_secs, best_wav, best_sr = -1, None, 24000
    for i in range(n):
        torch.manual_seed(int(torch.randint(0, 2**31, (1,)).item()))
        wav_np, sr = generate_single(engine, text, ref_path, ref_text)
        tmp = GENERATED_DIR / "_tmp_bench.wav"
        sf.write(str(tmp), wav_np, sr)
        cand_emb = _extract_embedding(tmp)
        norm = np.linalg.norm(real_emb) * np.linalg.norm(cand_emb)
        secs = float(np.dot(real_emb, cand_emb) / norm)
        if secs > best_secs:
            best_secs, best_wav, best_sr = secs, wav_np, sr
        tmp.unlink(missing_ok=True)
    return best_wav, best_sr, best_secs


def denoise_audio(input_path: Path, output_path: Path) -> Path:
    """Apply Resemble Enhance denoise."""
    from resemble_enhance.enhancer.inference import denoise
    dwav, sr = torchaudio.load(str(input_path))
    dwav = dwav.mean(dim=0).float()
    dwav, sr = denoise(dwav, sr, "cuda")
    torchaudio.save(str(output_path), dwav.unsqueeze(0).cpu(), sr)
    return output_path
