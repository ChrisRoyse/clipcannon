"""Phase 1: pre-encode per-clip conditioning tensors to disk (lip-sync training)."""
import gc
import json
import logging
import os

import numpy as np
import torch
from omegaconf import OmegaConf
from PIL import Image

from .config import (
    COND_DIR,
    CONFIG_PATH,
    LABELS_FILE,
    LATENT_SPATIAL,
    LATENT_T,
    MODEL_PATH,
    REFERENCE_IMAGE,
    RESOLUTION,
    SOURCE_VIDEO,
    VIDEO_LENGTH,
    VOCALS_WAV,
    WAV2VEC_DIR,
)
from .data import (
    compute_latent_mouth_mask,
    extract_audio_features,
    extract_clip_frames_ffmpeg,
    preflight_check,
)

log = logging.getLogger("lipsync")


# ============================================================
#  Phase 1: Pre-encoding
#  FIX: audio features stream to disk per-clip (not dict accumulation)
# ============================================================

def pre_encode_all():
    """Pre-encode all conditioning tensors per clip.

    Encoding order: T5 (once), CLIP (once), Wav2Vec+VAE per-clip.
    Each clip's conditioning is saved immediately to disk to avoid
    accumulating tens of GB in RAM.
    """
    preflight_check()
    COND_DIR.mkdir(parents=True, exist_ok=True)

    labels_data = json.loads(LABELS_FILE.read_text())
    clips = labels_data["clips"]
    log.info("Encoding %d clips", len(clips))

    config = OmegaConf.load(CONFIG_PATH)
    device = torch.device("cuda")

    base_prompt = (
        "SANTA An older man dressed as Santa Claus with a white beard, "
        "round glasses, and red suit is speaking naturally during an interview."
    )

    # --- T5 (shared prompt) ---
    from src.wan_text_encoder import WanT5EncoderModel
    from transformers import AutoTokenizer
    log.info("Loading T5...")
    tokenizer = AutoTokenizer.from_pretrained(
        os.path.join(MODEL_PATH, config["text_encoder_kwargs"].get("tokenizer_subpath", "tokenizer"))
    )
    text_encoder = WanT5EncoderModel.from_pretrained(
        os.path.join(MODEL_PATH, config["text_encoder_kwargs"].get("text_encoder_subpath", "text_encoder")),
        additional_kwargs=OmegaConf.to_container(config["text_encoder_kwargs"]),
        torch_dtype=torch.bfloat16,
    ).to(device).eval()

    text_inputs = tokenizer(base_prompt, return_tensors="pt", padding="max_length",
                            max_length=512, truncation=True)
    seq_lens = text_inputs.attention_mask.sum(dim=1).tolist()
    with torch.no_grad():
        prompt_embeds = text_encoder(
            text_inputs.input_ids.to(device),
            attention_mask=text_inputs.attention_mask.to(device),
        )[0]
    text_context_cpu = [prompt_embeds[0, : seq_lens[0]].cpu()]
    del text_encoder, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    log.info("T5 done")

    # --- CLIP (shared reference image) ---
    import torchvision.transforms.functional as TF
    from src.wan_image_encoder import CLIPModel
    log.info("Loading CLIP...")
    clip_encoder = CLIPModel.from_pretrained(
        os.path.join(MODEL_PATH, config["image_encoder_kwargs"].get("image_encoder_subpath", "image_encoder")),
    ).to(torch.bfloat16).to(device).eval()

    ref_img = Image.open(REFERENCE_IMAGE).convert("RGB").resize((RESOLUTION, RESOLUTION))
    clip_image = TF.to_tensor(ref_img).sub_(0.5).div_(0.5).to(device, dtype=torch.bfloat16)
    with torch.no_grad():
        clip_fea_cpu = clip_encoder([clip_image[:, None, :, :]]).cpu()
    del clip_encoder
    gc.collect()
    torch.cuda.empty_cache()
    log.info("CLIP done: %s", tuple(clip_fea_cpu.shape))

    # --- Wav2Vec (loaded once, used per-clip) ---
    from src.wav2vec2 import Wav2Vec2Model
    from transformers import Wav2Vec2FeatureExtractor
    log.info("Loading Wav2Vec...")
    audio_encoder = Wav2Vec2Model.from_pretrained(
        WAV2VEC_DIR, local_files_only=True
    ).to(device).eval()
    wav2vec_fe = Wav2Vec2FeatureExtractor.from_pretrained(
        WAV2VEC_DIR, local_files_only=True
    )
    log.info("Wav2Vec loaded")

    # --- VAE (FP32 for WSL2 stability) ---
    from src.wan_vae import AutoencoderKLWan
    log.info("Loading VAE (FP32)...")
    vae = AutoencoderKLWan.from_pretrained(
        os.path.join(MODEL_PATH, config["vae_kwargs"].get("vae_subpath", "vae")),
        additional_kwargs=OmegaConf.to_container(config["vae_kwargs"]),
    ).to(torch.float32).to(device)

    # Reference image latent (shared)
    ref_tensor = torch.from_numpy(np.array(ref_img)).permute(2, 0, 1).float() / 127.5 - 1.0
    ref_tensor = ref_tensor.unsqueeze(0).unsqueeze(2).to(device)
    with torch.no_grad():
        ref_latent_cpu = vae.encode(ref_tensor).latent_dist.sample().cpu()
    log.info("Reference latent: %s", tuple(ref_latent_cpu.shape))

    # Encode each clip: audio + video + mouth mask → save to disk
    log.info("Encoding per-clip conditioning (streaming to disk)...")
    failed = 0
    for idx, clip in enumerate(clips):
        clip_id = clip["clip_id"]
        out_path = COND_DIR / f"{clip_id}.pt"
        if out_path.exists():
            continue  # resume support

        try:
            # Audio features (stay on GPU briefly, move to CPU immediately)
            audio_emb = extract_audio_features(
                VOCALS_WAV, clip["start_ms"],
                audio_encoder, wav2vec_fe, VIDEO_LENGTH, device,
            )

            # Video tensor via FFmpeg (25fps guaranteed)
            video = extract_clip_frames_ffmpeg(
                SOURCE_VIDEO, clip["start_ms"], VIDEO_LENGTH, RESOLUTION
            ).to(device)
            with torch.no_grad():
                latent_cpu = vae.encode(video).latent_dist.sample().cpu()
            del video

            # Mouth mask in latent space
            mouth_mask = compute_latent_mouth_mask(
                clip, LATENT_T, LATENT_SPATIAL, RESOLUTION
            )

            torch.save({
                "text_context": text_context_cpu,
                "clip_fea": clip_fea_cpu,
                "audio_emb": audio_emb,
                "latent": latent_cpu,
                "ref_latent": ref_latent_cpu,
                "mouth_mask": mouth_mask,
                "latent_t": LATENT_T,
                "video_length": VIDEO_LENGTH,
                "clip_id": clip_id,
                "viseme_sequence": clip["viseme_sequence"],
                "clip_category": clip["clip_category"],
                "has_speech": clip["has_speech"],
                "prosody_energy_level": clip["prosody_energy_level"],
            }, out_path)

        except Exception as e:
            log.error("Failed clip %s: %s", clip_id, e)
            failed += 1
            continue

        if (idx + 1) % 100 == 0:
            log.info("  %d/%d | VRAM=%.1fGB | failed=%d",
                     idx + 1, len(clips),
                     torch.cuda.memory_allocated() / 1e9, failed)

    del vae, audio_encoder, wav2vec_fe
    gc.collect()
    torch.cuda.empty_cache()

    saved = len(list(COND_DIR.glob("*.pt")))
    log.info("Pre-encoding complete: %d saved, %d failed", saved, failed)
    if failed > 0:
        log.warning("%d clips failed encoding", failed)
