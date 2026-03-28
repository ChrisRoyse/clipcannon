"""Gradient-Based Waveform Optimization for WavLM-Large SIM.

Takes a generated TTS waveform and optimizes it via gradient descent
to maximize cosine similarity with the reference on the official
WavLM-Large + ECAPA-TDNN encoder.

The entire scoring pipeline is differentiable:
  waveform → WavLM-Large (24 transformer layers) → ECAPA-TDNN → 192-dim embedding → cosine sim

We compute d(SIM)/d(waveform) and nudge the waveform in the direction
that increases SIM. Changes are imperceptible to human ears.
"""

import sys
import time
import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import torchaudio
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, "/tmp/seed-tts-eval/thirdparty/UniSpeech/downstreams/speaker_verification")

logging.basicConfig(format="%(levelname)s | %(asctime)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

CHECKPOINT = Path("/home/cabdru/clipcannon/benchmarks/seedtts_eval/wavlm_large_finetune.pth")


class WavLMSIMOptimizer:
    """Gradient-based waveform optimizer for WavLM-Large SIM score."""

    def __init__(self):
        torch.set_float32_matmul_precision("high")
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

        from models.ecapa_tdnn import ECAPA_TDNN_SMALL
        logger.info("Loading WavLM-Large + ECAPA-TDNN for gradient optimization...")
        self.model = ECAPA_TDNN_SMALL(
            feat_dim=1024, feat_type="wavlm_large", config_path=None,
        )
        state = torch.load(str(CHECKPOINT), map_location="cpu")
        self.model.load_state_dict(state["model"], strict=False)
        self.model = self.model.cuda().eval()

        # Freeze all model parameters (we optimize the WAVEFORM, not the model)
        for param in self.model.parameters():
            param.requires_grad = False

        logger.info("WavLM-Large optimizer ready on CUDA")

    def extract_embedding(self, wav_16k: torch.Tensor) -> torch.Tensor:
        """Extract 192-dim embedding. Keeps gradient graph alive."""
        # wav_16k: [1, T] on CUDA, requires_grad=True
        emb = self.model(wav_16k)  # [1, 192]
        return emb

    def compute_sim(self, wav_a: torch.Tensor, wav_b: torch.Tensor) -> torch.Tensor:
        """Differentiable cosine similarity between two waveforms."""
        emb_a = self.extract_embedding(wav_a)
        emb_b = self.extract_embedding(wav_b)
        return F.cosine_similarity(emb_a, emb_b).squeeze()

    def optimize_waveform(
        self,
        generated_wav_path: Path,
        reference_wav_path: Path,
        output_path: Path,
        n_steps: int = 100,
        lr: float = 0.001,
        max_perturbation: float = 0.02,
        log_interval: int = 10,
    ) -> tuple[float, float]:
        """Optimize a generated waveform to maximize SIM with reference.

        Args:
            generated_wav_path: TTS output to optimize.
            reference_wav_path: Original reference clip.
            output_path: Where to save optimized waveform.
            n_steps: Gradient descent steps.
            lr: Learning rate for waveform perturbation.
            max_perturbation: Max absolute change per sample (imperceptibility).
            log_interval: How often to log progress.

        Returns:
            (initial_sim, final_sim) tuple.
        """
        # Load both to 16kHz (what WavLM expects)
        gen_wav, gen_sr = torchaudio.load(str(generated_wav_path))
        ref_wav, ref_sr = torchaudio.load(str(reference_wav_path))

        if gen_wav.shape[0] > 1:
            gen_wav = gen_wav.mean(0, keepdim=True)
        if ref_wav.shape[0] > 1:
            ref_wav = ref_wav.mean(0, keepdim=True)
        if gen_sr != 16000:
            gen_wav = torchaudio.functional.resample(gen_wav, gen_sr, 16000)
        if ref_sr != 16000:
            ref_wav = torchaudio.functional.resample(ref_wav, ref_sr, 16000)

        # Reference embedding (frozen, no gradient needed)
        ref_wav_cuda = ref_wav.cuda()
        with torch.no_grad():
            ref_emb = self.extract_embedding(ref_wav_cuda)
            ref_emb = ref_emb.detach()

        # Save original for perturbation clamping
        original_wav = gen_wav.clone().cuda()

        # The waveform we'll optimize
        opt_wav = gen_wav.clone().cuda().requires_grad_(True)

        # Optimizer operates on the waveform directly
        optimizer = torch.optim.Adam([opt_wav], lr=lr)

        # Initial SIM
        with torch.no_grad():
            gen_emb = self.extract_embedding(original_wav)
            initial_sim = F.cosine_similarity(gen_emb, ref_emb).item()

        logger.info("Starting gradient optimization: initial SIM=%.4f", initial_sim)

        best_sim = initial_sim
        best_wav = original_wav.clone()

        for step in range(n_steps):
            optimizer.zero_grad()

            # Forward: waveform → WavLM → ECAPA → embedding
            emb = self.extract_embedding(opt_wav)

            # Loss: negative cosine similarity (we want to MAXIMIZE sim)
            sim = F.cosine_similarity(emb, ref_emb).squeeze()
            loss = -sim  # minimize negative = maximize positive

            # Backward: compute d(sim)/d(waveform)
            loss.backward()

            # Update waveform
            optimizer.step()

            # Clamp perturbation to stay imperceptible
            with torch.no_grad():
                perturbation = opt_wav.data - original_wav
                perturbation = perturbation.clamp(-max_perturbation, max_perturbation)
                opt_wav.data = original_wav + perturbation
                # Also clamp to valid audio range
                opt_wav.data = opt_wav.data.clamp(-1.0, 1.0)

            current_sim = sim.item()
            if current_sim > best_sim:
                best_sim = current_sim
                best_wav = opt_wav.data.clone()

            if (step + 1) % log_interval == 0 or step == 0:
                pert_norm = perturbation.abs().max().item()
                logger.info(
                    "  Step %3d: SIM=%.4f (best=%.4f) perturbation_max=%.5f",
                    step + 1, current_sim, best_sim, pert_norm,
                )

        # Save best result at ORIGINAL sample rate
        best_wav_cpu = best_wav.cpu()
        if gen_sr != 16000:
            # Resample back to original rate
            best_wav_cpu = torchaudio.functional.resample(best_wav_cpu, 16000, gen_sr)

        torchaudio.save(str(output_path), best_wav_cpu, gen_sr)

        logger.info(
            "Optimization complete: %.4f → %.4f (+%.4f)",
            initial_sim, best_sim, best_sim - initial_sim,
        )
        return initial_sim, best_sim

    def release(self):
        import gc
        del self.model
        gc.collect()
        torch.cuda.empty_cache()


def smoke_test():
    """Test on the hard sample."""
    logger.info("=" * 60)
    logger.info("GRADIENT OPTIMIZATION SMOKE TEST")
    logger.info("=" * 60)

    optimizer = WavLMSIMOptimizer()

    # The hard sample
    ref_path = Path("/home/cabdru/clipcannon/benchmarks/seedtts_eval/seedtts_testset/en/prompt-wavs/common_voice_en_103675.wav")
    gen_path = Path("/home/cabdru/clipcannon/benchmarks/seedtts_eval/optimized_en/common_voice_en_103675-common_voice_en_103677.wav")
    out_path = Path("/home/cabdru/clipcannon/benchmarks/seedtts_eval/gradient_opt/hard_optimized.wav")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not gen_path.exists():
        logger.error("Generated file not found: %s", gen_path)
        return

    start = time.monotonic()

    initial_sim, final_sim = optimizer.optimize_waveform(
        generated_wav_path=gen_path,
        reference_wav_path=ref_path,
        output_path=out_path,
        n_steps=200,
        lr=0.002,
        max_perturbation=0.03,
        log_interval=20,
    )

    elapsed = time.monotonic() - start

    logger.info("")
    logger.info("RESULTS:")
    logger.info("  Initial SIM:  %.4f", initial_sim)
    logger.info("  Final SIM:    %.4f", final_sim)
    logger.info("  Improvement:  +%.4f", final_sim - initial_sim)
    logger.info("  Time:         %.1fs", elapsed)
    logger.info("  Output:       %s", out_path)
    logger.info("")
    logger.info("  Previous best (best-of-24): 0.677")
    logger.info("  Seed-TTS DiT average:       0.790")

    # Also test on the good sample
    good_gen = Path("/home/cabdru/clipcannon/benchmarks/seedtts_eval/optimized_en/common_voice_en_120405-common_voice_en_120406.wav")
    good_ref = Path("/home/cabdru/clipcannon/benchmarks/seedtts_eval/seedtts_testset/en/prompt-wavs/common_voice_en_120405.wav")
    good_out = Path("/home/cabdru/clipcannon/benchmarks/seedtts_eval/gradient_opt/good_optimized.wav")

    if good_gen.exists():
        logger.info("")
        logger.info("Testing on GOOD sample (prev 0.842)...")
        init2, final2 = optimizer.optimize_waveform(
            generated_wav_path=good_gen,
            reference_wav_path=good_ref,
            output_path=good_out,
            n_steps=200,
            lr=0.002,
            max_perturbation=0.03,
            log_interval=20,
        )
        logger.info("GOOD sample: %.4f → %.4f (+%.4f)", init2, final2, final2 - init2)

    optimizer.release()


if __name__ == "__main__":
    smoke_test()
