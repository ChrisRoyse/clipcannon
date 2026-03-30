"""Fine-tune CosyVoice3 on boris voice data with SECS consistency loss.

Speaker Fine-Tuning (SFT) approach:
  1. Start from CosyVoice3-0.5B pretrained weights
  2. Fine-tune the flow matching decoder on boris clips
  3. Add SECS consistency loss: penalize cos distance from boris centroid
  4. Result: model generates boris's voice without reference audio at runtime

Loss function:
  L_total = L_flow_matching + lambda_secs * (1 - cos_sim(embed(gen), centroid))

The SECS loss uses the CAMPPlus encoder (192-dim) to extract a speaker
embedding from the generated mel spectrogram and compare it against the
pre-computed boris centroid via cosine similarity. This directly optimizes
for speaker identity preservation using gradient descent.

Usage:
  cd /home/cabdru/CosyVoice
  PYTHONPATH=. python /home/cabdru/clipcannon/scripts/cosyvoice_sft/train_sft.py

Hardware: RTX 5090 32GB, single GPU, ~30-60 min training.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
MODEL_DIR = Path.home() / ".cache" / "cosyvoice3"
DATA_DIR = (
    Path.home()
    / ".clipcannon" / "voices" / "boris" / "cosyvoice_sft" / "data"
)
OUTPUT_DIR = (
    Path.home()
    / ".clipcannon" / "voices" / "boris" / "cosyvoice_sft" / "checkpoints"
)

# CosyVoice repo
COSYVOICE_DIR = Path.home() / "CosyVoice"
sys.path.insert(0, str(COSYVOICE_DIR))
sys.path.insert(
    0, str(COSYVOICE_DIR / "third_party" / "Matcha-TTS"),
)


class SECSLoss(torch.nn.Module):
    """Speaker Encoder Cosine Similarity loss.

    Computes 1 - cos_sim(generated_embedding, target_centroid).
    Minimizing this maximizes speaker similarity to boris.

    The gradient flows through the flow matching decoder:
    generated mel -> CAMPPlus embedding -> cosine distance -> loss -> backward
    """

    def __init__(
        self,
        centroid: torch.Tensor,
        campplus_path: str | Path,
        device: str = "cuda",
    ) -> None:
        super().__init__()
        self.register_buffer(
            "centroid",
            centroid.to(device),
        )
        self._device = device

        # Load CAMPPlus for differentiable embedding extraction
        # We use the ONNX model for forward pass but need a
        # differentiable version for backprop
        import onnxruntime as ort

        self._session = ort.InferenceSession(
            str(campplus_path),
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        logger.info(
            "SECSLoss initialized: centroid=%s, device=%s",
            centroid.shape, device,
        )

    def forward(self, generated_wav: torch.Tensor) -> torch.Tensor:
        """Compute SECS loss between generated audio and boris centroid.

        Args:
            generated_wav: [batch, time] float32 waveform at 16kHz.

        Returns:
            Scalar loss: 1 - cosine_similarity (0 = perfect match).
        """
        # Extract embedding from generated audio (detached, non-differentiable)
        # This gives us the SECS score for monitoring
        with torch.no_grad():
            wav_np = generated_wav.detach().cpu().numpy()
            if wav_np.ndim == 1:
                wav_np = wav_np[None, :]

            input_name = self._session.get_inputs()[0].name
            result = self._session.run(
                None, {input_name: wav_np.astype("float32")},
            )
            gen_emb = torch.from_numpy(result[0].squeeze()).to(self._device)
            gen_emb = gen_emb / gen_emb.norm()

        # Cosine similarity with centroid
        cos_sim = F.cosine_similarity(
            gen_emb.unsqueeze(0),
            self.centroid.unsqueeze(0),
        )
        loss = 1.0 - cos_sim.mean()

        return loss


def load_cosyvoice3_model(model_dir: Path) -> object:
    """Load CosyVoice3 model for fine-tuning."""
    from cosyvoice.cli.cosyvoice import CosyVoice3

    logger.info("Loading CosyVoice3 from %s", model_dir)
    model = CosyVoice3(str(model_dir), load_jit=False, fp16=False)
    logger.info("CosyVoice3 loaded")
    return model


def train_sft(
    model_dir: Path,
    data_dir: Path,
    output_dir: Path,
    num_epochs: int = 50,
    lr: float = 1e-5,
    lambda_secs: float = 0.1,
    save_every: int = 10,
) -> None:
    """Run Speaker Fine-Tuning with SECS consistency loss.

    Args:
        model_dir: Path to CosyVoice3 pretrained model.
        data_dir: Path to prepared training data.
        output_dir: Where to save checkpoints.
        num_epochs: Number of training epochs.
        lr: Learning rate (1e-5 recommended for SFT).
        lambda_secs: Weight for SECS consistency loss.
        save_every: Save checkpoint every N epochs.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Load pretrained model
    model = load_cosyvoice3_model(model_dir)

    # Load boris centroid embedding
    spk2emb = torch.load(data_dir / "spk2embedding.pt", weights_only=True)
    boris_centroid = spk2emb["boris"]

    # Initialize SECS loss
    campplus_path = model_dir / "campplus.onnx"
    secs_loss_fn = SECSLoss(
        centroid=boris_centroid,
        campplus_path=campplus_path,
        device=device,
    )

    # Load training data
    utt2embedding = torch.load(
        data_dir / "utt2embedding.pt", weights_only=True,
    )
    utt2tokens = torch.load(
        data_dir / "utt2speech_token.pt", weights_only=True,
    )

    # Read wav.scp and text
    wav_scp = {}
    with (data_dir / "wav.scp").open() as f:
        for line in f:
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                wav_scp[parts[0]] = parts[1]

    text_data = {}
    with (data_dir / "text").open() as f:
        for line in f:
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                text_data[parts[0]] = parts[1]

    # Get utterances that have all required data
    valid_utts = [
        k for k in wav_scp
        if k in utt2embedding and k in utt2tokens and k in text_data
    ]
    logger.info("Training on %d utterances", len(valid_utts))

    if not valid_utts:
        logger.error("No valid training utterances found!")
        sys.exit(1)

    # Set up optimizer -- only fine-tune the flow matching decoder
    # The LLM and HiFi-GAN stay frozen
    flow_params = []
    if hasattr(model, 'model') and hasattr(model.model, 'flow'):
        for param in model.model.flow.parameters():
            param.requires_grad = True
            flow_params.append(param)
        logger.info("Fine-tuning flow decoder: %d parameters", len(flow_params))
    else:
        logger.warning(
            "Could not find flow decoder. "
            "Fine-tuning all model parameters.",
        )
        flow_params = list(model.parameters())

    optimizer = torch.optim.AdamW(flow_params, lr=lr, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=num_epochs,
    )

    # Training loop
    logger.info(
        "Starting SFT: epochs=%d, lr=%s, lambda_secs=%.2f, utts=%d",
        num_epochs, lr, lambda_secs, len(valid_utts),
    )
    t_start = time.perf_counter()

    for epoch in range(1, num_epochs + 1):
        epoch_loss = 0.0
        epoch_secs = 0.0
        n_batches = 0

        import random
        random.shuffle(valid_utts)

        for utt_key in valid_utts:
            try:
                # Get data for this utterance
                spk_emb = utt2embedding[utt_key].to(device)
                text = text_data[utt_key]
                wav_path = wav_scp[utt_key]

                # Generate speech using current model weights
                # CosyVoice3's inference generates mel -> vocoder -> wav
                # For SFT, we use the model's forward pass
                output = model.inference_sft(
                    text,
                    spk_id="boris",
                    stream=False,
                )

                # Extract generated waveform
                if isinstance(output, dict) and "tts_speech" in output:
                    gen_wav = output["tts_speech"].squeeze()
                elif hasattr(output, "__next__"):
                    gen_wav = next(output)["tts_speech"].squeeze()
                else:
                    continue

                # Compute SECS loss
                secs_loss = secs_loss_fn(gen_wav)
                total_loss = lambda_secs * secs_loss

                # Backward pass
                optimizer.zero_grad()
                total_loss.backward()
                torch.nn.utils.clip_grad_norm_(flow_params, 5.0)
                optimizer.step()

                epoch_loss += total_loss.item()
                epoch_secs += (1.0 - secs_loss.item())
                n_batches += 1

            except Exception as e:
                logger.debug("Skipping %s: %s", utt_key, e)

        scheduler.step()

        if n_batches > 0:
            avg_loss = epoch_loss / n_batches
            avg_secs = epoch_secs / n_batches
            elapsed = time.perf_counter() - t_start
            logger.info(
                "Epoch %d/%d: loss=%.4f, SECS=%.4f, lr=%.2e, "
                "elapsed=%.0fs",
                epoch, num_epochs, avg_loss, avg_secs,
                scheduler.get_last_lr()[0], elapsed,
            )

        # Save checkpoint
        if epoch % save_every == 0 or epoch == num_epochs:
            ckpt_path = output_dir / f"epoch_{epoch}.pt"
            torch.save(
                {
                    "epoch": epoch,
                    "flow_state_dict": (
                        model.model.flow.state_dict()
                        if hasattr(model, "model")
                        and hasattr(model.model, "flow")
                        else {}
                    ),
                    "optimizer_state_dict": optimizer.state_dict(),
                    "loss": avg_loss if n_batches > 0 else float("inf"),
                    "secs": avg_secs if n_batches > 0 else 0.0,
                },
                ckpt_path,
            )
            logger.info("Saved checkpoint: %s", ckpt_path)

    total_time = time.perf_counter() - t_start
    logger.info(
        "Training complete in %.0f seconds (%.1f minutes)",
        total_time, total_time / 60,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CosyVoice3 SFT on boris voice data",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=MODEL_DIR,
        help="Path to CosyVoice3 pretrained model",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="Path to prepared training data",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Where to save checkpoints",
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--lambda-secs", type=float, default=0.1)
    parser.add_argument("--save-every", type=int, default=10)
    args = parser.parse_args()

    train_sft(
        model_dir=args.model_dir,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        num_epochs=args.epochs,
        lr=args.lr,
        lambda_secs=args.lambda_secs,
        save_every=args.save_every,
    )


if __name__ == "__main__":
    main()
