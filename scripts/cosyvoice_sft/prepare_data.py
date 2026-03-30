"""Prepare boris voice data for CosyVoice3 SFT (Speaker Fine-Tuning).

Pipeline:
  1. Read boris train.jsonl (has audio paths + English transcripts)
  2. Extract CAMPPlus speaker embeddings (192-dim, CosyVoice's native encoder)
  3. Extract speech tokens via CosyVoice's speech tokenizer
  4. Package into parquet format for training
  5. Generate spk2embedding.pt (speaker centroid)

Usage:
  cd /home/cabdru/clipcannon
  PYTHONPATH=src python scripts/cosyvoice_sft/prepare_data.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
VOICE_DIR = Path.home() / ".clipcannon" / "voice_data" / "boris"
WAVS_DIR = VOICE_DIR / "wavs"
TRAIN_JSONL = VOICE_DIR / "train.jsonl"
MODEL_DIR = Path.home() / ".cache" / "cosyvoice3"
OUTPUT_DIR = Path.home() / ".clipcannon" / "voices" / "boris" / "cosyvoice_sft"

# CosyVoice repo
COSYVOICE_DIR = Path.home() / "CosyVoice"
sys.path.insert(0, str(COSYVOICE_DIR))
sys.path.insert(
    0, str(COSYVOICE_DIR / "third_party" / "Matcha-TTS"),
)


def load_train_manifest() -> list[dict]:
    """Load boris training data with English transcripts."""
    entries = []
    with TRAIN_JSONL.open() as f:
        for line in f:
            entry = json.loads(line.strip())
            audio_path = Path(entry["audio"])
            if audio_path.exists():
                entries.append({
                    "audio": str(audio_path),
                    "text": entry["text"],
                    "speaker": "boris",
                })
    logger.info("Loaded %d training entries from %s", len(entries), TRAIN_JSONL)
    return entries


def extract_embeddings(
    entries: list[dict],
    campplus_path: Path,
) -> tuple[dict[str, torch.Tensor], torch.Tensor]:
    """Extract CAMPPlus speaker embeddings for each utterance.

    Returns:
        utt2embedding: dict mapping utterance key to 192-dim embedding
        spk_centroid: averaged centroid embedding for boris
    """
    import onnxruntime as ort

    logger.info("Loading CAMPPlus from %s", campplus_path)
    session = ort.InferenceSession(
        str(campplus_path),
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )

    utt2embedding: dict[str, torch.Tensor] = {}
    all_embeddings = []

    import torchaudio.compliance.kaldi as kaldi

    for i, entry in enumerate(entries):
        wav, sr = torchaudio.load(entry["audio"])
        if sr != 16000:
            wav = torchaudio.functional.resample(wav, sr, 16000)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)

        if wav.shape[1] < 1600:  # skip very short clips
            continue

        # CAMPPlus expects [batch, seq_len, 80] fbank features
        feat = kaldi.fbank(
            wav, num_mel_bins=80, dither=0, sample_frequency=16000,
        )
        feat = feat - feat.mean(dim=0, keepdim=True)

        input_name = session.get_inputs()[0].name
        result = session.run(
            None,
            {input_name: feat.unsqueeze(0).numpy()},
        )
        emb = torch.from_numpy(result[0].squeeze())

        # L2 normalize
        emb = emb / emb.norm()

        utt_key = Path(entry["audio"]).stem
        utt2embedding[utt_key] = emb
        all_embeddings.append(emb)

        if (i + 1) % 50 == 0:
            logger.info("Extracted %d/%d embeddings", i + 1, len(entries))

    # Compute speaker centroid
    centroid = torch.stack(all_embeddings).mean(dim=0)
    centroid = centroid / centroid.norm()

    logger.info(
        "Extracted %d embeddings, centroid shape=%s",
        len(utt2embedding), centroid.shape,
    )
    return utt2embedding, centroid


def extract_speech_tokens(
    entries: list[dict],
    tokenizer_path: Path,
) -> dict[str, list[int]]:
    """Extract discrete speech tokens via CosyVoice's speech tokenizer.

    Uses whisper.log_mel_spectrogram for 128-dim mel features,
    then runs the ONNX speech tokenizer.
    """
    import onnxruntime as ort
    import whisper

    logger.info("Loading speech tokenizer from %s", tokenizer_path)
    option = ort.SessionOptions()
    option.graph_optimization_level = (
        ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    )
    option.intra_op_num_threads = 1
    session = ort.InferenceSession(
        str(tokenizer_path),
        sess_options=option,
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )

    utt2tokens: dict[str, list[int]] = {}

    for i, entry in enumerate(entries):
        wav, sr = torchaudio.load(entry["audio"])
        if sr != 16000:
            wav = torchaudio.functional.resample(wav, sr, 16000)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)

        # Skip clips > 30s
        if wav.shape[1] / 16000 > 30:
            logger.warning("Skipping %s (>30s)", entry["audio"])
            continue

        try:
            feat = whisper.log_mel_spectrogram(wav, n_mels=128)
            feats_input = feat.detach().cpu().numpy()
            length_input = np.array(
                [feat.shape[2]], dtype=np.int32,
            )
            result = session.run(
                None,
                {
                    session.get_inputs()[0].name: feats_input,
                    session.get_inputs()[1].name: length_input,
                },
            )
            tokens = result[0].flatten().tolist()
            utt_key = Path(entry["audio"]).stem
            utt2tokens[utt_key] = tokens
        except Exception as e:
            logger.warning(
                "Failed to tokenize %s: %s", entry["audio"], e,
            )

        if (i + 1) % 50 == 0:
            logger.info("Tokenized %d/%d clips", i + 1, len(entries))

    logger.info("Extracted tokens for %d clips", len(utt2tokens))
    return utt2tokens


def build_wav_scp_and_text(
    entries: list[dict],
    out_dir: Path,
) -> None:
    """Create wav.scp, text, utt2spk, spk2utt files."""
    out_dir.mkdir(parents=True, exist_ok=True)

    wav_scp = out_dir / "wav.scp"
    text_file = out_dir / "text"
    utt2spk = out_dir / "utt2spk"
    spk2utt = out_dir / "spk2utt"

    utt_keys = []
    with (
        wav_scp.open("w") as f_wav,
        text_file.open("w") as f_text,
        utt2spk.open("w") as f_u2s,
    ):
        for entry in entries:
            utt_key = Path(entry["audio"]).stem
            f_wav.write(f"{utt_key} {entry['audio']}\n")
            f_text.write(f"{utt_key} {entry['text']}\n")
            f_u2s.write(f"{utt_key} boris\n")
            utt_keys.append(utt_key)

    with spk2utt.open("w") as f:
        f.write(f"boris {' '.join(utt_keys)}\n")

    logger.info(
        "Created wav.scp (%d entries), text, utt2spk, spk2utt at %s",
        len(utt_keys), out_dir,
    )


def main() -> None:
    t0 = time.perf_counter()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check model files exist
    campplus_path = MODEL_DIR / "campplus.onnx"
    tokenizer_path = MODEL_DIR / "speech_tokenizer_v3.onnx"

    if not campplus_path.exists():
        logger.error(
            "CAMPPlus model not found at %s. "
            "Download CosyVoice3 model first.",
            campplus_path,
        )
        sys.exit(1)

    if not tokenizer_path.exists():
        logger.error(
            "Speech tokenizer not found at %s.",
            tokenizer_path,
        )
        sys.exit(1)

    # Step 1: Load training manifest
    entries = load_train_manifest()

    # Step 2: Create wav.scp, text, utt2spk, spk2utt
    data_dir = OUTPUT_DIR / "data"
    build_wav_scp_and_text(entries, data_dir)

    # Step 3: Extract CAMPPlus speaker embeddings
    utt2embedding, centroid = extract_embeddings(entries, campplus_path)
    torch.save(utt2embedding, data_dir / "utt2embedding.pt")
    torch.save({"boris": centroid}, data_dir / "spk2embedding.pt")
    logger.info("Saved utt2embedding.pt and spk2embedding.pt")

    # Step 4: Extract speech tokens
    utt2tokens = extract_speech_tokens(entries, tokenizer_path)
    torch.save(utt2tokens, data_dir / "utt2speech_token.pt")
    logger.info("Saved utt2speech_token.pt")

    elapsed = time.perf_counter() - t0
    logger.info(
        "Data preparation complete in %.1fs. "
        "Output at %s",
        elapsed, OUTPUT_DIR,
    )
    logger.info(
        "Next: run the SFT training script to fine-tune CosyVoice3",
    )


if __name__ == "__main__":
    main()
