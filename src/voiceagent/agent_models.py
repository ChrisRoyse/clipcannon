"""On-demand GPU model loading / unloading for the VoiceAgent.

Split out of ``voiceagent.agent`` (pure move): the ``AgentLifecycle`` enum
and the ``_load_models`` / ``_unload_models`` methods that ``VoiceAgent``
inherits from ``_ModelLifecycleMixin``.
"""

from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class AgentLifecycle(Enum):
    DORMANT = "dormant"
    LOADING = "loading"
    ACTIVE = "active"
    UNLOADING = "unloading"


class _ModelLifecycleMixin:
    """ASR / LLM / TTS model loading and unloading for ``VoiceAgent``."""

    # ------------------------------------------------------------------
    #  GPU model loading / unloading
    # ------------------------------------------------------------------

    def _load_models(self) -> None:
        """Load ASR + LLM + TTS models onto GPU with VRAM budgeting.

        VRAM budget (RTX 5090 32GB):
          Whisper Large v3 float32:  ~6 GB
          Qwen3-14B FP16:          ~15 GB
          faster-qwen3-tts 0.6B:    ~4 GB
          KV caches + activations:  ~5 GB headroom
          Total target:            ~30 GB (leave 2GB free)

        Models are loaded sequentially with GC between each to
        prevent fragmentation. Memory fraction capped at 93%.
        """
        if self._initialized:
            return
        self._lifecycle = AgentLifecycle.LOADING
        logger.info("Loading GPU models...")

        import gc

        import torch

        # Pause other GPU workers to free VRAM for voice agent
        from voiceagent.gpu_manager import (
            force_free_gpu_memory,
            pause_gpu_workers,
        )
        self._paused_worker_pids = pause_gpu_workers()
        force_free_gpu_memory()

        # Cap VRAM at 93% to prevent OOM thrashing
        torch.cuda.set_per_process_memory_fraction(0.93)
        torch.cuda.empty_cache()

        vram_before = torch.cuda.memory_allocated()

        def _log_vram(label: str) -> None:
            used = torch.cuda.memory_allocated() / (1024**3)
            reserved = torch.cuda.memory_reserved() / (1024**3)
            logger.info(
                "%s: allocated=%.1fGB, reserved=%.1fGB",
                label, used, reserved,
            )

        # 1. ASR (VAD on CPU + Whisper on GPU)
        from voiceagent.asr.streaming import StreamingASR
        self._asr = StreamingASR(self.config.asr)
        gc.collect()
        torch.cuda.empty_cache()
        _log_vram("After ASR")

        # 2. LLM Brain (biggest model, load after ASR is settled)
        from voiceagent.brain.llm import LLMBrain
        self._brain = LLMBrain(self.config.llm)
        gc.collect()
        torch.cuda.empty_cache()
        _log_vram("After LLM")

        # 3. TTS (0.6B model + CUDA graph capture)
        from voiceagent.adapters.fast_tts import FastTTSAdapter
        from voiceagent.tts.chunker import SentenceChunker
        from voiceagent.tts.streaming import StreamingTTS
        self._tts_adapter = FastTTSAdapter(
            voice_name=self.config.tts.voice_name,
        )
        self._tts = StreamingTTS(self._tts_adapter, SentenceChunker())
        gc.collect()
        torch.cuda.empty_cache()
        _log_vram("After TTS")

        # 4. Context + prompt (no GPU, just tokenizer on CPU)
        from voiceagent.brain.context import ContextManager
        from voiceagent.brain.prompts import build_system_prompt
        self._system_prompt = build_system_prompt(
            self.config.tts.voice_name,
        )
        self._context = ContextManager(
            tokenizer_path=self.config.llm.model_path,
        )

        vram_after = torch.cuda.memory_allocated()
        total_gb = (vram_after - vram_before) / (1024**3)
        free_gb = (
            torch.cuda.get_device_properties(0).total_memory
            - torch.cuda.memory_reserved()
        ) / (1024**3)
        logger.info(
            "All models loaded: %.1fGB used, %.1fGB free",
            total_gb, free_gb,
        )
        self._initialized = True

    def _unload_models(self) -> None:
        """Unload ALL GPU models and aggressively free VRAM.

        Releases each model explicitly, runs GC, and clears both
        the PyTorch cache and CUDA IPC to prevent leaked tensors.
        """
        self._lifecycle = AgentLifecycle.UNLOADING
        logger.info("Unloading GPU models...")

        import gc

        import torch

        # Release in reverse load order (TTS -> LLM -> ASR)
        if self._tts_adapter:
            self._tts_adapter.release()
            self._tts_adapter = None
        self._tts = None

        if self._brain:
            self._brain.release()
            self._brain = None

        # ASR holds Whisper model -- delete explicitly
        if self._asr:
            if hasattr(self._asr, 'model'):
                del self._asr.model
            if hasattr(self._asr, 'vad') and hasattr(self._asr.vad, 'model'):
                del self._asr.vad.model
            self._asr = None

        self._conversation = None
        self._context = None
        self._initialized = False

        # Aggressive VRAM cleanup
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

        vram = torch.cuda.memory_allocated() / (1024**3)
        reserved = torch.cuda.memory_reserved() / (1024**3)
        logger.info(
            "Models unloaded. allocated=%.2fGB, reserved=%.2fGB",
            vram, reserved,
        )

        # Resume paused GPU workers now that VRAM is free
        if self._paused_worker_pids:
            from voiceagent.gpu_manager import resume_gpu_workers
            resume_gpu_workers(self._paused_worker_pids)
            self._paused_worker_pids = []

        self._lifecycle = AgentLifecycle.DORMANT
        logger.info("Agent is DORMANT")
