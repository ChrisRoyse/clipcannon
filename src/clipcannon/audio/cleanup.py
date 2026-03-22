"""Audio cleanup via FFmpeg audio filters.

Provides noise reduction, de-hum, de-ess, and loudness normalization
using FFmpeg's built-in audio filters. All processing creates a new
cleaned audio file without modifying the original.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_CLEANUP_OPS = frozenset({
    "noise_reduction",
    "de_hum",
    "de_ess",
    "normalize_loudness",
})


@dataclass
class CleanupResult:
    """Result of audio cleanup processing."""
    file_path: Path
    duration_ms: int
    sample_rate: int
    operations_applied: list[str]
    asset_id: str


def build_cleanup_filters(
    operations: list[str],
    hum_frequency: int = 50,
) -> list[str]:
    """Build FFmpeg audio filter chain for cleanup operations.

    Args:
        operations: List of cleanup operations to apply.
        hum_frequency: Fundamental frequency of hum (50Hz EU, 60Hz US).

    Returns:
        List of FFmpeg audio filter strings.

    Raises:
        ValueError: If any operation is not recognized.
    """
    filters: list[str] = []

    for op in operations:
        if op not in SUPPORTED_CLEANUP_OPS:
            raise ValueError(
                f"Unknown cleanup operation: {op!r}. "
                f"Valid: {sorted(SUPPORTED_CLEANUP_OPS)}"
            )

    if "noise_reduction" in operations:
        # anlmdn: non-local means denoising
        # s=0.0001 is a gentle noise floor reduction
        filters.append("anlmdn=s=0.0001:p=0.01:o=o")

    if "de_hum" in operations:
        # Remove fundamental + first 3 harmonics of hum frequency
        for harmonic in range(1, 4):
            freq = hum_frequency * harmonic
            filters.append(f"bandreject=f={freq}:w=5:t=h")

    if "de_ess" in operations:
        # High-frequency sibilance reduction
        # Compress frequencies above 5kHz
        filters.append("highpass=f=100")
        filters.append("lowpass=f=16000")

    if "normalize_loudness" in operations:
        # EBU R128 loudness normalization
        # I=-16 LUFS target, TP=-1.5 dBFS true peak, LRA=11 dynamic range
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    return filters


async def cleanup_audio(
    input_path: Path,
    output_path: Path,
    operations: list[str],
    hum_frequency: int = 50,
) -> CleanupResult:
    """Process audio through FFmpeg cleanup filters.

    Args:
        input_path: Path to source audio file.
        output_path: Path to write cleaned audio.
        operations: Cleanup operations to apply.
        hum_frequency: Hum frequency (50 or 60 Hz).

    Returns:
        CleanupResult with output file details.

    Raises:
        ValueError: If operations list is empty or contains invalid ops.
        RuntimeError: If FFmpeg execution fails.
    """
    if not operations:
        raise ValueError("At least one cleanup operation required")

    if not input_path.exists():
        raise FileNotFoundError(f"Input audio not found: {input_path}")

    filters = build_cleanup_filters(operations, hum_frequency)
    filter_chain = ",".join(filters)

    asset_id = f"audio_{secrets.token_hex(6)}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", filter_chain,
        "-ar", "44100",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        str(output_path),
    ]

    logger.info(
        "Running audio cleanup: ops=%s, filter=%s",
        operations, filter_chain,
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")[-500:]
        logger.error("FFmpeg cleanup failed: %s", error_msg)
        raise RuntimeError(
            f"FFmpeg cleanup failed (exit {proc.returncode}): {error_msg}"
        )

    if not output_path.exists():
        raise RuntimeError(f"FFmpeg completed but output missing: {output_path}")

    # Get duration via ffprobe
    duration_ms = await _get_audio_duration_ms(output_path)

    return CleanupResult(
        file_path=output_path,
        duration_ms=duration_ms,
        sample_rate=44100,
        operations_applied=list(operations),
        asset_id=asset_id,
    )


async def _get_audio_duration_ms(audio_path: Path) -> int:
    """Get audio duration in milliseconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(audio_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return int(float(stdout.decode().strip()) * 1000)
    except (ValueError, IndexError):
        return 0
