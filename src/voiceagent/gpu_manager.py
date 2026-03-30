"""GPU resource manager -- pauses other GPU processes when voice agent activates.

Sequential GPU sharing: voice agent has priority. When activated, it
sends SIGSTOP to GPU-consuming processes (OCR workers, embedding workers,
reranker). When deactivated, it sends SIGCONT to resume them.

This prevents VRAM contention on the RTX 5090 (32GB) between the voice
agent (~22GB) and background workers (~13GB).
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess

logger = logging.getLogger(__name__)

# Processes to pause/resume (matched by command substring)
GPU_WORKER_PATTERNS = [
    "ocr_worker_local.py",
    "embedding_worker.py",
    "reranker_worker.py",
]


def _find_gpu_worker_pids() -> list[int]:
    """Find PIDs of GPU worker processes."""
    pids: list[int] = []
    my_pid = os.getpid()
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if any(pat in line for pat in GPU_WORKER_PATTERNS):
                parts = line.split()
                if len(parts) >= 2:
                    pid = int(parts[1])
                    if pid != my_pid:
                        pids.append(pid)
    except Exception as e:
        logger.warning("Failed to find GPU workers: %s", e)
    return pids


def pause_gpu_workers() -> list[int]:
    """Send SIGSTOP to all GPU worker processes.

    Returns list of paused PIDs (to resume later).
    """
    pids = _find_gpu_worker_pids()
    paused: list[int] = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGSTOP)
            paused.append(pid)
            logger.info("Paused GPU worker PID %d", pid)
        except ProcessLookupError:
            pass
        except PermissionError:
            logger.warning("Cannot pause PID %d (permission denied)", pid)

    if paused:
        logger.info("Paused %d GPU workers, freeing VRAM", len(paused))
    else:
        logger.info("No GPU workers found to pause")

    return paused


def resume_gpu_workers(pids: list[int]) -> None:
    """Send SIGCONT to previously paused GPU worker processes."""
    resumed = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGCONT)
            resumed += 1
            logger.info("Resumed GPU worker PID %d", pid)
        except ProcessLookupError:
            logger.debug("PID %d no longer exists", pid)
        except PermissionError:
            logger.warning("Cannot resume PID %d (permission denied)", pid)

    if resumed:
        logger.info("Resumed %d GPU workers", resumed)


def force_free_gpu_memory() -> None:
    """Force-free GPU memory from stopped processes.

    After SIGSTOP, the processes still hold VRAM. We need to wait
    for them to be swapped out or force a CUDA context reset.
    For now, just clear PyTorch's cache.
    """
    try:
        import gc

        import torch
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
        vram_mb = torch.cuda.memory_allocated() / (1024**2)
        logger.info("GPU memory after cleanup: %.0f MB", vram_mb)
    except Exception as e:
        logger.warning("GPU cleanup failed: %s", e)
