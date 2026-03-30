"""LLM Brain -- Custom inference harness for Qwen3-14B-FP8.

Purpose-built inference engine with:
- Direct model loading with explicit dtype/device control
- Real token-by-token streaming via TextIteratorStreamer + generation thread
- Custom sampling parameters (temperature, top_p, top_k, repetition_penalty)
- Explicit VRAM tracking and memory management
- No dependency on vLLM -- 100% our own code on top of transformers primitives

This is NOT a generic wrapper. Every decision is optimized for the voice agent
use case: low-latency first-token, streaming output, single-user local inference.
"""
from __future__ import annotations

import gc
import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

from voiceagent.errors import LLMError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerationMetrics:
    """Metrics from a single generation call."""
    prompt_tokens: int
    generated_tokens: int
    time_to_first_token_ms: float
    total_generation_ms: float
    tokens_per_second: float


class LLMBrain:
    """Custom inference harness for Qwen3-14B-FP8.

    Loads the model directly with explicit dtype and device control.
    Streams tokens one-by-one via TextIteratorStreamer running generation
    in a background thread while the caller consumes tokens asynchronously.

    Args:
        config: LLMConfig with model_path, quantization, max_model_len, max_tokens.

    Raises:
        LLMError: If model or tokenizer fails to load.
    """

    def __init__(self, config: object) -> None:
        self._config = config
        self._model = None
        self._tokenizer = None
        self._device: torch.device | None = None
        self._load_time_ms: float = 0.0
        self._last_metrics: GenerationMetrics | None = None

        self._load_model(config)

    def _load_model(self, config: object) -> None:
        """Load model and tokenizer onto GPU with explicit configuration."""
        t0 = time.perf_counter()

        if not torch.cuda.is_available():
            raise LLMError(
                "CUDA GPU required but not available. "
                "Ensure NVIDIA drivers and CUDA toolkit are installed."
            )

        # Resolve device
        self._device = torch.device("cuda:0")

        # Load tokenizer first (lightweight, validates model path)
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                config.model_path,
                trust_remote_code=True,
            )
        except Exception as e:
            raise LLMError(
                f"Failed to load tokenizer from '{config.model_path}': {e}. "
                f"Verify model path exists and contains tokenizer files."
            ) from e

        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        # Load model with explicit dtype
        dtype = self._resolve_dtype(config.quantization)
        vram_before = torch.cuda.memory_allocated(self._device)

        try:
            self._model = AutoModelForCausalLM.from_pretrained(
                config.model_path,
                dtype=dtype,
                device_map="auto",
                trust_remote_code=True,
            )
            self._model.eval()
        except Exception as e:
            raise LLMError(
                f"Failed to load model from '{config.model_path}' with dtype={dtype}: {e}. "
                f"Ensure GPU has sufficient VRAM (need ~15GB for FP8/FP16 14B model)."
            ) from e

        # Compile for reduced-overhead inference
        try:
            self._model = torch.compile(self._model, mode="reduce-overhead")
            logger.info("torch.compile applied (reduce-overhead mode)")
        except Exception as e:
            logger.warning("torch.compile failed (will use eager mode): %s", e)

        vram_after = torch.cuda.memory_allocated(self._device)
        self._load_time_ms = (time.perf_counter() - t0) * 1000
        vram_used_gb = (vram_after - vram_before) / (1024 ** 3)

        logger.info(
            "Model loaded: path=%s, dtype=%s, vram=%.2fGB, time=%.0fms, "
            "vocab_size=%d, max_position=%s",
            config.model_path,
            dtype,
            vram_used_gb,
            self._load_time_ms,
            self._tokenizer.vocab_size,
            getattr(self._model.config, "max_position_embeddings", "unknown"),
        )

    @staticmethod
    def _resolve_dtype(quantization: str) -> torch.dtype:
        """Map quantization string to torch dtype."""
        mapping = {
            "fp8": torch.float16,     # FP8 models load as FP16 via transformers
            "fp16": torch.float16,
            "bf16": torch.bfloat16,
            "fp32": torch.float32,
        }
        dtype = mapping.get(quantization)
        if dtype is None:
            raise LLMError(
                f"Unsupported quantization '{quantization}'. "
                f"Supported: {list(mapping.keys())}."
            )
        return dtype

    def _build_chat_prompt(self, messages: list[dict[str, str]]) -> str:
        """Convert chat messages to model prompt using the tokenizer's chat template.

        Args:
            messages: List of {"role": "system"|"user"|"assistant", "content": "..."}.

        Returns:
            Formatted prompt string.

        Raises:
            LLMError: If messages list is empty.
        """
        if not messages:
            raise LLMError(
                "Empty messages list. Provide at least one message "
                "with 'role' and 'content' keys."
            )
        return self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )

    def _tokenize(self, prompt: str) -> dict:
        """Tokenize prompt and move to model device.

        Returns:
            Dict with input_ids and attention_mask tensors on GPU.

        Raises:
            LLMError: If tokenization fails.
        """
        try:
            inputs = self._tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=self._config.max_model_len,
            )
            return {k: v.to(self._device) for k, v in inputs.items()}
        except Exception as e:
            raise LLMError(f"Tokenization failed: {e}") from e

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        top_p: float = 0.8,
        top_k: int = 20,
        repetition_penalty: float = 1.0,
    ) -> AsyncIterator[str]:
        """Stream tokens one-by-one from the model.

        Uses TextIteratorStreamer + a background generation thread so the caller
        can consume tokens as they're produced without blocking.

        Args:
            messages: Chat message list.
            temperature: Sampling temperature (0.0 = greedy, higher = more random).
            top_p: Nucleus sampling threshold.
            top_k: Top-k sampling limit.
            repetition_penalty: Penalize repeated tokens (1.0 = no penalty).

        Yields:
            String tokens as they are generated.

        Raises:
            LLMError: If messages empty, model not loaded, or generation fails.
        """
        if self._model is None:
            raise LLMError(
                "Model not loaded. Call __init__ first or model was released."
            )

        prompt = self._build_chat_prompt(messages)
        inputs = self._tokenize(prompt)
        prompt_len = inputs["input_ids"].shape[1]

        # Create streamer that yields decoded tokens
        streamer = TextIteratorStreamer(
            self._tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        # Build generation kwargs
        gen_kwargs = {
            **inputs,
            "streamer": streamer,
            "max_new_tokens": self._config.max_tokens,
            "do_sample": temperature > 0,
            "temperature": max(temperature, 1e-7),  # avoid div-by-zero
            "top_p": top_p,
            "top_k": top_k,
            "repetition_penalty": repetition_penalty,
            "cache_implementation": "static",
        }

        # Track metrics
        t_start = time.perf_counter()
        t_first_token: float | None = None
        generated_count = 0
        gen_error: Exception | None = None

        def _generate_thread() -> None:
            nonlocal gen_error
            try:
                with torch.no_grad():
                    self._model.generate(**gen_kwargs)
            except Exception as e:
                gen_error = e
                logger.error("Generation thread error: %s", e)

        # Start generation in background thread
        thread = threading.Thread(target=_generate_thread, daemon=True)
        thread.start()

        # Yield tokens as they arrive from the streamer
        try:
            for token_text in streamer:
                if token_text:
                    if t_first_token is None:
                        t_first_token = time.perf_counter()
                    generated_count += 1
                    yield token_text
        finally:
            thread.join(timeout=30)

        if gen_error is not None:
            raise LLMError(
                f"Generation failed: {gen_error}. "
                f"Prompt length: {prompt_len} tokens."
            ) from gen_error

        # Record metrics
        t_end = time.perf_counter()
        total_ms = (t_end - t_start) * 1000
        ttft_ms = ((t_first_token - t_start) * 1000) if t_first_token else total_ms
        tps = generated_count / (total_ms / 1000) if total_ms > 0 else 0

        self._last_metrics = GenerationMetrics(
            prompt_tokens=prompt_len,
            generated_tokens=generated_count,
            time_to_first_token_ms=round(ttft_ms, 1),
            total_generation_ms=round(total_ms, 1),
            tokens_per_second=round(tps, 1),
        )

        logger.info(
            "Generation complete: prompt=%d tokens, generated=%d tokens, "
            "ttft=%.0fms, total=%.0fms, speed=%.1f tok/s",
            prompt_len, generated_count, ttft_ms, total_ms, tps,
        )

    @property
    def metrics(self) -> GenerationMetrics | None:
        """Metrics from the last generation call."""
        return self._last_metrics

    @property
    def vram_bytes(self) -> int:
        """Current GPU VRAM allocated by PyTorch."""
        if self._device is None:
            return 0
        return torch.cuda.memory_allocated(self._device)

    @property
    def is_loaded(self) -> bool:
        """Whether the model is currently loaded on GPU."""
        return self._model is not None

    def release(self) -> None:
        """Free all GPU memory. After release, generate_stream will fail."""
        vram_before = self.vram_bytes

        if self._model is not None:
            del self._model
            self._model = None

        if self._tokenizer is not None:
            del self._tokenizer
            self._tokenizer = None

        self._device = None
        gc.collect()
        torch.cuda.empty_cache()

        vram_after = torch.cuda.memory_allocated(torch.device("cuda:0"))
        freed_gb = (vram_before - vram_after) / (1024 ** 3)

        logger.info(
            "LLMBrain released: freed=%.2fGB, remaining=%.2fGB",
            freed_gb, vram_after / (1024 ** 3),
        )
