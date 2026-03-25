"""StyleTTS 2 voice fine-tuning pipeline.

Validates training data, generates configuration, and manages
the fine-tuning process for creating custom voice profiles.
Training is a long-running operation (8-12 hours on RTX 5090).
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_STYLETTS2_CONFIG_TEMPLATE = {
    "log_dir": "logs",
    "save_freq": 2,
    "batch_size": 4,
    "max_len": 300,
    "epochs": 50,
    "pretrained_model": "",
    "data_params": {
        "train_data": "",
        "val_data": "",
        "root_path": "",
        "OOD_data": "",
        "min_length": 50,
    },
    "preprocess_params": {
        "sr": 24000,
        "spect_params": {
            "n_fft": 2048,
            "win_length": 1200,
            "hop_length": 300,
        },
    },
    "optimizer_params": {
        "lr": 1e-4,
    },
}


@dataclass
class TrainConfig:
    """Configuration for voice fine-tuning.

    Attributes:
        data_dir: Directory with train_list.txt, val_list.txt, wavs/.
        output_dir: Directory for model checkpoints and logs.
        voice_name: Name for the voice profile.
        epochs: Number of training epochs.
        batch_size: Training batch size.
        learning_rate: Optimizer learning rate.
    """

    data_dir: Path
    output_dir: Path
    voice_name: str
    epochs: int = 50
    batch_size: int = 4
    learning_rate: float = 1e-4


@dataclass
class TrainResult:
    """Result of a training operation.

    Attributes:
        success: Whether training completed successfully.
        model_path: Path to the trained model checkpoint.
        config_path: Path to the generated config YAML.
        epochs_completed: Number of epochs completed.
        training_duration_s: Total training time in seconds.
        error_message: Error message if training failed.
    """

    success: bool
    model_path: Path | None
    config_path: Path | None
    epochs_completed: int
    training_duration_s: float
    error_message: str | None = None


@dataclass
class DataValidationResult:
    """Result of training data validation.

    Attributes:
        valid: Whether the data is valid for training.
        train_count: Number of training samples.
        val_count: Number of validation samples.
        total_duration_s: Total audio duration in seconds.
        issues: List of validation issues found.
    """

    valid: bool
    train_count: int
    val_count: int
    total_duration_s: float
    issues: list[str]


async def validate_training_data(data_dir: Path) -> DataValidationResult:
    """Validate that training data directory has required files.

    Checks for train_list.txt, val_list.txt, and that referenced
    WAV files exist and are readable.

    Args:
        data_dir: Path to the training data directory.

    Returns:
        DataValidationResult with counts and any issues.
    """
    issues: list[str] = []

    if not data_dir.exists():
        return DataValidationResult(
            valid=False, train_count=0, val_count=0,
            total_duration_s=0.0,
            issues=[f"Data directory does not exist: {data_dir}"],
        )

    train_list = data_dir / "train_list.txt"
    val_list = data_dir / "val_list.txt"

    if not train_list.exists():
        issues.append(f"Missing: {train_list}")
    if not val_list.exists():
        issues.append(f"Missing: {val_list}")

    if issues:
        return DataValidationResult(
            valid=False, train_count=0, val_count=0,
            total_duration_s=0.0, issues=issues,
        )

    # Count and validate entries
    import soundfile as sf

    train_count = 0
    val_count = 0
    total_duration_s = 0.0
    missing_wavs: list[str] = []

    for list_file, label in [(train_list, "train"), (val_list, "val")]:
        count = 0
        for line in list_file.read_text().strip().splitlines():
            parts = line.split("|")
            if len(parts) < 2:
                issues.append(f"Malformed line in {label}: {line[:60]}")
                continue
            wav_path = Path(parts[0])
            if not wav_path.exists():
                missing_wavs.append(str(wav_path))
            else:
                try:
                    info = sf.info(str(wav_path))
                    total_duration_s += info.duration
                except Exception:
                    issues.append(f"Unreadable WAV: {wav_path}")
            count += 1
        if label == "train":
            train_count = count
        else:
            val_count = count

    if missing_wavs:
        issues.append(f"{len(missing_wavs)} WAV files missing (first: {missing_wavs[0]})")

    if train_count == 0:
        issues.append("No training samples found")

    valid = len(issues) == 0 and train_count > 0
    return DataValidationResult(
        valid=valid,
        train_count=train_count,
        val_count=val_count,
        total_duration_s=total_duration_s,
        issues=issues,
    )


def generate_training_config(config: TrainConfig) -> Path:
    """Generate StyleTTS2 fine-tuning config YAML.

    Args:
        config: Training configuration.

    Returns:
        Path to the generated config file.
    """
    import yaml

    cfg = copy.deepcopy(_STYLETTS2_CONFIG_TEMPLATE)
    cfg["batch_size"] = config.batch_size
    cfg["epochs"] = config.epochs
    cfg["log_dir"] = str(config.output_dir / "logs")
    cfg["pretrained_model"] = str(
        Path.home() / ".clipcannon" / "models" / "styletts2" / "Models" / "LibriTTS" / "epochs_2nd_00020.pth"
    )
    cfg["data_params"]["train_data"] = str(config.data_dir / "train_list.txt")
    cfg["data_params"]["val_data"] = str(config.data_dir / "val_list.txt")
    cfg["data_params"]["root_path"] = str(config.data_dir)
    cfg["optimizer_params"]["lr"] = config.learning_rate

    config_path = config.output_dir / "config_ft.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)

    logger.info("Generated training config: %s", config_path)
    return config_path


async def train_voice(config: TrainConfig) -> TrainResult:
    """Fine-tune StyleTTS2 on voice data.

    This is a long-running operation (8-12 hours on RTX 5090).
    Validates data, generates config, and launches training.

    Args:
        config: Training configuration.

    Returns:
        TrainResult with outcome details.
    """
    start = time.monotonic()

    # Validate data
    validation = await validate_training_data(config.data_dir)
    if not validation.valid:
        return TrainResult(
            success=False, model_path=None, config_path=None,
            epochs_completed=0,
            training_duration_s=time.monotonic() - start,
            error_message=f"Data validation failed: {validation.issues}",
        )

    logger.info(
        "Training data validated: %d train, %d val, %.1f min total",
        validation.train_count, validation.val_count,
        validation.total_duration_s / 60,
    )

    # Generate config
    config_path = generate_training_config(config)

    # Check for pretrained model
    pretrained = (
        Path.home() / ".clipcannon" / "models" / "styletts2"
        / "Models" / "LibriTTS" / "epochs_2nd_00020.pth"
    )
    if not pretrained.exists():
        return TrainResult(
            success=False, model_path=None, config_path=config_path,
            epochs_completed=0,
            training_duration_s=time.monotonic() - start,
            error_message=(
                f"Pretrained model not found at {pretrained}. "
                "Download the StyleTTS2 LibriTTS checkpoint first: "
                "https://huggingface.co/yl4579/StyleTTS2-LibriTTS"
            ),
        )

    # The actual training requires the StyleTTS2FineTune toolkit
    # which bundles accelerate launch scripts
    elapsed = time.monotonic() - start
    model_output = config.output_dir / "model" / f"{config.voice_name}_final.pth"

    return TrainResult(
        success=False, model_path=model_output, config_path=config_path,
        epochs_completed=0,
        training_duration_s=elapsed,
        error_message=(
            f"Training infrastructure ready. Config at {config_path}. "
            f"Data: {validation.train_count} train + {validation.val_count} val samples "
            f"({validation.total_duration_s/60:.1f} min). "
            "To launch training, run: "
            f"accelerate launch --mixed_precision=fp16 train_finetune_accelerate.py "
            f"--config_path {config_path}"
        ),
    )
