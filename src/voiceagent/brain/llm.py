"""LLM Brain -- Qwen3-14B-FP8 reasoning engine.

Loads Qwen3-14B-FP8 via vLLM (preferred) or transformers (fallback).
Provides streaming token generation for the voice agent conversation loop.
"""
from __future__ import annotations

import gc
import logging
from collections.abc import AsyncIterator

from voiceagent.errors import LLMError

logger = logging.getLogger(__name__)


class LLMBrain:
    def __init__(self, config) -> None:
        """Load LLM model.

        Args:
            config: LLMConfig with model_path, quantization, gpu_memory_utilization,
                    max_model_len, max_tokens.

        Raises:
            LLMError: If model fails to load.
        """
        self._config = config
        self._backend: str = "none"
        self._tokenizer = None

        # Try vLLM first
        try:
            from vllm import LLM, SamplingParams
            self._llm = LLM(
                model=config.model_path,
                quantization=config.quantization,
                gpu_memory_utilization=config.gpu_memory_utilization,
                max_model_len=config.max_model_len,
            )
            self._SamplingParams = SamplingParams
            self._backend = "vllm"
            logger.info("LLMBrain loaded via vLLM: %s", config.model_path)
        except ImportError:
            logger.warning(
                "vLLM not available, falling back to transformers. "
                "Performance will be degraded. Install vllm for optimal inference."
            )
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer
                self._hf_tokenizer = AutoTokenizer.from_pretrained(config.model_path)
                self._hf_model = AutoModelForCausalLM.from_pretrained(
                    config.model_path,
                    torch_dtype=torch.float16,
                    device_map="auto",
                )
                self._backend = "transformers"
                logger.info("LLMBrain loaded via transformers (fallback): %s", config.model_path)
            except Exception as e:
                raise LLMError(
                    f"Failed to load LLM via transformers fallback: {e}. "
                    f"Model path: {config.model_path}. "
                    f"Ensure model exists and GPU has enough VRAM."
                ) from e
        except Exception as e:
            raise LLMError(
                f"Failed to load LLM via vLLM: {e}. "
                f"Model path: {config.model_path}."
            ) from e

        # Load tokenizer for chat template
        if self._backend == "vllm":
            try:
                from transformers import AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(config.model_path)
            except Exception as e:
                raise LLMError(f"Failed to load tokenizer: {e}") from e
        elif self._backend == "transformers":
            self._tokenizer = self._hf_tokenizer

    def _build_chat_prompt(self, messages: list[dict[str, str]]) -> str:
        if not messages:
            raise LLMError("Empty messages list. Provide at least one message.")
        return self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

    async def generate_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Stream tokens from the LLM."""
        prompt = self._build_chat_prompt(messages)

        if self._backend == "vllm":
            params = self._SamplingParams(
                max_tokens=self._config.max_tokens,
                temperature=0.7,
                top_p=0.9,
            )
            outputs = self._llm.generate([prompt], params)
            for output in outputs:
                for completion in output.outputs:
                    yield completion.text

        elif self._backend == "transformers":
            import torch
            inputs = self._tokenizer(prompt, return_tensors="pt").to(self._hf_model.device)
            with torch.no_grad():
                output_ids = self._hf_model.generate(
                    **inputs,
                    max_new_tokens=self._config.max_tokens,
                    temperature=0.7,
                    top_p=0.9,
                    do_sample=True,
                )
            new_tokens = output_ids[0][inputs["input_ids"].shape[1]:]
            text = self._tokenizer.decode(new_tokens, skip_special_tokens=True)
            yield text

        else:
            raise LLMError(f"No backend loaded. State: {self._backend}")

    def release(self) -> None:
        """Free GPU memory."""
        if self._backend == "vllm" and hasattr(self, "_llm"):
            del self._llm
        elif self._backend == "transformers" and hasattr(self, "_hf_model"):
            del self._hf_model
            if hasattr(self, "_hf_tokenizer"):
                del self._hf_tokenizer
        if hasattr(self, "_tokenizer"):
            del self._tokenizer
        self._backend = "released"
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
            logger.info("LLMBrain released. VRAM: %.1f MB", torch.cuda.memory_allocated() / 1024 / 1024)
        except ImportError:
            pass
