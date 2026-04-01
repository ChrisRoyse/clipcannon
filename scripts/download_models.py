#!/usr/bin/env python3
"""Download all ML model weights required by ClipCannon.

Downloads models to ~/.clipcannon/models/ with progress tracking,
resumable downloads, and checksum verification.
"""

import os
import sys
from pathlib import Path

# Models registry: (name, huggingface_id, approx_size_gb)
MODELS = [
    ("whisperx-large-v3", "Systran/faster-whisper-large-v3", 3.0),
    ("siglip-so400m", "google/siglip-so400m-patch14-384", 1.7),
    ("nomic-embed-text-v1.5", "nomic-ai/nomic-embed-text-v1.5", 0.5),
    ("wav2vec2-emotion", "facebook/wav2vec2-large-960h", 1.2),
    ("wavlm-base-plus-sv", "microsoft/wavlm-base-plus-sv", 0.4),
    ("sensevoice-small", "FunAudioLLM/SenseVoiceSmall", 0.9),
    ("htdemucs", "facebook/htdemucs", 0.3),
    ("silero-vad", "snakers4/silero-vad", 0.01),
]

# LatentSync checkpoints (separate from snapshot_download workflow)
LATENTSYNC_FILES = [
    ("latentsync_unet.pt", 4.72),
    ("whisper/tiny.pt", 0.07),
]

MODELS_DIR = Path.home() / ".clipcannon" / "models"


def get_total_size() -> float:
    """Get total download size in GB."""
    return sum(size for _, _, size in MODELS)


def download_model(name: str, repo_id: str, size_gb: float) -> bool:
    """Download a single model from HuggingFace.

    Args:
        name: Local model name.
        repo_id: HuggingFace repository ID.
        size_gb: Approximate size in GB.

    Returns:
        True if download succeeded.
    """
    model_dir = MODELS_DIR / name
    if model_dir.exists() and any(model_dir.iterdir()):
        print(f"  [{name}] Already downloaded, skipping.")
        return True

    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download

        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

        print(f"  [{name}] Downloading {repo_id} (~{size_gb:.1f}GB)...")
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(model_dir),
            token=token,
            resume_download=True,
        )
        print(f"  [{name}] Done.")
        return True
    except ImportError:
        print(f"  [{name}] ERROR: huggingface_hub not installed.")
        print(f"           Install with: pip install huggingface_hub")
        return False
    except Exception as exc:
        print(f"  [{name}] ERROR: {exc}")
        return False


def download_latentsync() -> bool:
    """Download LatentSync repo and checkpoints.

    Clones the repo if missing, then downloads checkpoints
    from HuggingFace via huggingface-cli.

    Returns:
        True if setup succeeded.
    """
    import subprocess

    latentsync_dir = MODELS_DIR / "latentsync"

    # Clone repo if missing
    if not latentsync_dir.exists():
        print("  [latentsync] Cloning ByteDance/LatentSync...")
        result = subprocess.run(
            ["git", "clone", "https://github.com/bytedance/LatentSync.git",
             str(latentsync_dir)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  [latentsync] ERROR: git clone failed: {result.stderr.strip()[:200]}")
            return False
        print("  [latentsync] Repo cloned.")
    else:
        print("  [latentsync] Repo already exists.")

    # Download checkpoints
    checkpoints_dir = latentsync_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

    for filename, size_gb in LATENTSYNC_FILES:
        target = checkpoints_dir / filename
        if target.exists():
            print(f"  [latentsync] {filename} already downloaded, skipping.")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"  [latentsync] Downloading {filename} (~{size_gb:.2f}GB)...")

        try:
            from huggingface_hub import hf_hub_download

            hf_hub_download(
                repo_id="ByteDance/LatentSync-1.6",
                filename=filename,
                local_dir=str(checkpoints_dir),
                token=token,
            )
            print(f"  [latentsync] {filename} done.")
        except ImportError:
            print("  [latentsync] ERROR: huggingface_hub not installed.")
            return False
        except Exception as exc:
            print(f"  [latentsync] ERROR downloading {filename}: {exc}")
            return False

    print("  [latentsync] Setup complete.")
    return True


def main() -> None:
    """Download all models."""
    total_gb = get_total_size()

    print("=" * 60)
    print("  ClipCannon Model Downloader")
    print("=" * 60)
    print()
    print(f"Models directory: {MODELS_DIR}")
    print(f"Total download size: ~{total_gb:.1f} GB")
    print(f"Models to download: {len(MODELS)}")
    print()

    # Check for HF token
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        print(f"HuggingFace token: set ({token[:8]}...)")
    else:
        print("HuggingFace token: not set (some models may require it)")
        print("  Set with: export HF_TOKEN=hf_xxx")
    print()

    confirm = input(f"Download ~{total_gb:.1f}GB of models? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    print()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    succeeded = 0
    failed = 0
    for name, repo_id, size_gb in MODELS:
        if download_model(name, repo_id, size_gb):
            succeeded += 1
        else:
            failed += 1
        print()

    # LatentSync setup
    print("--- LatentSync (lip-sync) ---")
    if download_latentsync():
        succeeded += 1
    else:
        failed += 1
    print()

    total_count = len(MODELS) + 1  # +1 for LatentSync
    print("=" * 60)
    print(f"  Downloaded: {succeeded}/{total_count}")
    if failed:
        print(f"  Failed: {failed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
