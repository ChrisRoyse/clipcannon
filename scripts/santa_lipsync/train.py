"""Phase 2: viseme-weighted dataset and mouth-weighted LoRA training loop."""
import logging
import os
import time
from collections import Counter
from pathlib import Path

import torch
import torch.nn.functional as F  # noqa: N812
from omegaconf import OmegaConf
from peft import LoraConfig, get_peft_model
from safetensors.torch import load_file
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from .config import (
    COND_DIR,
    CONFIG_PATH,
    MODEL_PATH,
    MOUTH_WEIGHT,
    OUTPUT_DIR,
    TRANSFORMER_PATH,
)
from .data import preflight_check

log = logging.getLogger("lipsync")


# ============================================================
#  Phase 2: Training with mouth-weighted loss + viseme-weighted sampler
# ============================================================

class VisemeWeightedDataset(Dataset):
    """Dataset with per-clip viseme rarity weights for sampler."""

    def __init__(self, cond_dir: Path):
        self.cond_dir = cond_dir
        self.files = sorted(cond_dir.glob("*.pt"))
        if not self.files:
            raise ValueError(f"No conditioning files in {cond_dir}")

        # Read viseme sequences to compute rarity weights
        log.info("Computing viseme rarity weights from %d clips...", len(self.files))
        viseme_global_counts = Counter()
        clip_visemes = []
        for f in self.files:
            data = torch.load(f, weights_only=False, map_location="cpu")
            seq = data["viseme_sequence"]
            clip_visemes.append(seq)
            viseme_global_counts.update(seq)

        # Per-clip weight = sum of (1 / global_count) for each unique viseme in clip
        # Clips with rare visemes get higher weight
        total = sum(viseme_global_counts.values())
        viseme_rarity = {
            v: total / (count * len(viseme_global_counts))
            for v, count in viseme_global_counts.items()
        }

        self.sample_weights = []
        for seq in clip_visemes:
            # Weight of a clip = mean rarity of its unique visemes
            unique_v = set(seq)
            w = sum(viseme_rarity[v] for v in unique_v) / max(1, len(unique_v))
            self.sample_weights.append(w)

        self.sample_weights = torch.tensor(self.sample_weights, dtype=torch.double)
        log.info("Viseme rarity weights: min=%.3f max=%.3f mean=%.3f",
                 float(self.sample_weights.min()),
                 float(self.sample_weights.max()),
                 float(self.sample_weights.mean()))

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        return torch.load(self.files[idx], weights_only=False, map_location="cpu")


def train_lipsync(steps=3000, rank=128, lr=1e-4, save_every=500):
    """Train lipsync LoRA with all fixes applied."""
    preflight_check()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cond_files = list(COND_DIR.glob("*.pt"))
    if not cond_files:
        raise RuntimeError(f"No conditioning files in {COND_DIR}. Run --phase encode first.")
    log.info("Training on %d conditioning files", len(cond_files))

    device = torch.device("cuda")
    config = OmegaConf.load(CONFIG_PATH)

    # --- Load transformer ---
    log.info("Loading transformer...")
    from src.wan_transformer3d_audio_2512 import WanTransformerAudioMask3DModel as WanTransformer
    transformer = WanTransformer.from_pretrained(
        os.path.join(MODEL_PATH, config["transformer_additional_kwargs"].get("transformer_subpath", "./")),
        transformer_additional_kwargs=OmegaConf.to_container(config["transformer_additional_kwargs"]),
        torch_dtype=torch.bfloat16,
    )
    transformer.load_state_dict(load_file(TRANSFORMER_PATH), strict=False)
    transformer = transformer.to(device)
    transformer.gradient_checkpointing = True
    log.info("Transformer: %.1fGB", torch.cuda.memory_allocated() / 1e9)

    # --- LoRA config ---
    # BLOCKER 4 FIX: q_audio is dead upstream (overwritten immediately after q_audio(q) call).
    # Target only the live modules: k_audio, v_audio (audio cross-attention K/V), plus
    # k_img, v_img (image cross-attention K/V) for identity, and q,k,v,o for self-attention.
    # Identity is trained from scratch since v2 LoRA path was deleted in cleanup.
    lipsync_lora_config = LoraConfig(
        r=rank,
        lora_alpha=rank * 2,
        target_modules=["q", "k", "v", "o", "k_audio", "v_audio", "k_img", "v_img"],
        lora_dropout=0.0,
    )
    transformer = get_peft_model(transformer, lipsync_lora_config)
    trainable = sum(p.numel() for p in transformer.parameters() if p.requires_grad)
    total = sum(p.numel() for p in transformer.parameters())
    log.info("LoRA rank=%d: %d trainable (%.2f%% of %d)",
             rank, trainable, 100 * trainable / total, total)

    # --- Dataset with viseme-weighted sampler ---
    dataset = VisemeWeightedDataset(COND_DIR)
    sampler = WeightedRandomSampler(
        weights=dataset.sample_weights,
        num_samples=steps * 2,   # enough for all training steps (with some headroom)
        replacement=True,
    )
    loader = DataLoader(
        dataset, batch_size=1, sampler=sampler, num_workers=0,
        collate_fn=lambda x: x[0],
    )

    # --- Optimizer ---
    optimizer = torch.optim.AdamW(
        [p for p in transformer.parameters() if p.requires_grad],
        lr=lr, weight_decay=1e-2,
    )
    lr_sched = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=steps)

    log.info("Training: %d steps, rank=%d, lr=%.1e, mouth_weight=%.0f",
             steps, rank, lr, MOUTH_WEIGHT)
    transformer.train()

    step = 0
    best_loss = float("inf")
    loss_accum = 0.0
    mouth_loss_accum = 0.0
    t0 = time.time()

    for sample in loader:
        if step >= steps:
            break

        latent = sample["latent"].to(device, dtype=torch.bfloat16)
        ref_latent = sample["ref_latent"].to(device, dtype=torch.bfloat16)
        clip_fea = sample["clip_fea"].to(device, dtype=torch.bfloat16)
        audio_emb = sample["audio_emb"].to(device, dtype=torch.bfloat16)
        mouth_mask = sample["mouth_mask"].to(device, dtype=torch.bfloat16)
        latent_t = sample["latent_t"]

        B, C, T, H, W = latent.shape

        # Flow matching noise
        noise = torch.randn_like(latent)
        t_idx = torch.randint(0, 1000, (1,)).item()
        sigma = t_idx / 1000.0
        noisy = (1 - sigma) * latent + sigma * noise

        # Inpainting condition: frame 0 visible as reference, rest masked
        mask_cond = torch.ones(B, 4, T, H, W, device=device, dtype=torch.bfloat16)
        mask_cond[:, :, 0, :, :] = 0
        masked_lat = torch.zeros(B, C, T, H, W, device=device, dtype=torch.bfloat16)
        masked_lat[:, :, 0:1, :, :] = ref_latent
        y = torch.cat([mask_cond, masked_lat], dim=1)

        text_ctx = [t.to(device, dtype=torch.bfloat16) for t in sample["text_context"]]
        context_tuple = (text_ctx, audio_emb, latent_t, None)
        seq_len = T * H * W // 4

        with torch.amp.autocast("cuda", dtype=torch.bfloat16):
            output = transformer(
                x=noisy,
                t=torch.tensor([t_idx], device=device, dtype=torch.int64),
                context=context_tuple,
                seq_len=seq_len,
                clip_fea=clip_fea,
                y=y,
            )
        if isinstance(output, tuple):
            output = output[0]

        # BLOCKER 3 FIX: flow matching target is (noise - latent), not (latent - noise).
        # The scheduler expects velocity dx/dt pointing from latent toward noise.
        target = noise - latent

        per_token_loss = F.mse_loss(output.float(), target.float(), reduction="none")
        # mouth_mask: (1,1,T,H,W) broadcasts over channel dim of per_token_loss (1,C,T,H,W)
        weighted = per_token_loss * mouth_mask.float()
        avg_weight = mouth_mask.float().mean().clamp_min(1.0)
        loss = weighted.mean() / avg_weight / 2

        # Track mouth-specific loss for monitoring
        mouth_region_mask = (mouth_mask.float() >= MOUTH_WEIGHT - 0.1).float()
        mouth_denom = mouth_region_mask.sum().clamp_min(1.0)
        mouth_only_loss = (per_token_loss * mouth_region_mask).sum() / mouth_denom

        loss.backward()
        loss_accum += loss.item()
        mouth_loss_accum += mouth_only_loss.item()

        if (step + 1) % 2 == 0:
            torch.nn.utils.clip_grad_norm_(
                [p for p in transformer.parameters() if p.requires_grad], 1.0
            )
            optimizer.step()
            lr_sched.step()
            optimizer.zero_grad()

        step += 1
        if step % 25 == 0:
            avg = loss_accum / 25 * 2
            mouth_avg = mouth_loss_accum / 25
            if avg < best_loss:
                best_loss = avg
            log.info(
                "Step %d/%d | loss=%.4f mouth_loss=%.4f | lr=%.2e | %.0fs | VRAM=%.1f/%.1fGB",
                step, steps, avg, mouth_avg, lr_sched.get_last_lr()[0],
                time.time() - t0,
                torch.cuda.memory_allocated() / 1e9,
                torch.cuda.max_memory_allocated() / 1e9,
            )
            loss_accum = 0.0
            mouth_loss_accum = 0.0

        if step % save_every == 0:
            ckpt_dir = OUTPUT_DIR / f"checkpoint-{step}"
            transformer.save_pretrained(str(ckpt_dir))
            log.info("Checkpoint saved: %s", ckpt_dir)

    final_dir = OUTPUT_DIR / "final"
    transformer.save_pretrained(str(final_dir))
    log.info("Done: %d steps in %.1f min | best_loss=%.4f | saved %s",
             steps, (time.time() - t0) / 60, best_loss, final_dir)
