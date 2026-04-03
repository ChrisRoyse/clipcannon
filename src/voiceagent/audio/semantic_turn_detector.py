"""Semantic end-of-turn detector using LiveKit's text-based ONNX model.

Complements Pipecat's audio-based Smart Turn V3 with a text-based
signal. Analyzes the conversation transcript to predict whether the
user has finished their utterance based on semantic content — catches
cases where audio analysis is ambiguous but the text is clearly
complete (e.g., "What time is it?" with a short pause).

The model is a fine-tuned Qwen2.5-0.5B (INT8 quantized ONNX) that
predicts the probability of the <|im_end|> token at the end of the
user's message. ~12ms per inference on CPU, no GPU needed.

Model: livekit/turn-detector (HuggingFace)
Architecture: Qwen2.5-0.5B-Instruct, knowledge-distilled from 7B teacher
Runtime: ONNX Runtime on CPU (~12ms per inference)
Memory: ~165MB for the quantized model
"""
from __future__ import annotations

import logging
import time
from collections import deque

import numpy as np
from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

# Default threshold: probability above which we consider the turn complete.
# The model outputs 0.98+ for clear completions and <0.05 for incomplete.
# 0.5 is a safe default; can be tuned based on observed behavior.
EOU_THRESHOLD = 0.5

# Maximum conversation turns to keep in context (model window is 512 tokens)
MAX_CONTEXT_TURNS = 6


class SemanticTurnDetector(FrameProcessor):
    """Text-based end-of-turn predictor using LiveKit's ONNX model.

    Sits in the pipeline after STT. On each transcription frame, runs
    the LiveKit model to predict whether the user has finished speaking.
    Emits a log with the EOU probability. Does NOT block frames —
    all frames pass through. The probability is available for the
    pipeline to use in conjunction with audio-based turn detection.

    The detector maintains a sliding window of recent conversation turns
    for context. Assistant turns are tracked via on_assistant_response().
    """

    def __init__(
        self,
        threshold: float = EOU_THRESHOLD,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._threshold = threshold
        self._session = None
        self._tokenizer = None
        self._im_end_id: int = 2  # Default for Qwen tokenizer
        self._context: deque[dict[str, str]] = deque(maxlen=MAX_CONTEXT_TURNS)
        self._initialized = False
        self._last_eou_prob: float = 0.0
        self._last_inference_ms: float = 0.0

    def _ensure_model(self) -> None:
        """Lazy-load the ONNX model and tokenizer on first use."""
        if self._initialized:
            return

        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            from transformers import AutoTokenizer
        except ImportError as e:
            logger.warning(
                "SemanticTurnDetector requires onnxruntime, "
                "huggingface_hub, and transformers: %s", e,
            )
            return

        logger.info("Loading LiveKit turn detector model...")
        t0 = time.perf_counter()

        model_path = hf_hub_download(
            "livekit/turn-detector", "model_quantized.onnx",
        )
        self._tokenizer = AutoTokenizer.from_pretrained("livekit/turn-detector")
        self._im_end_id = self._tokenizer.convert_tokens_to_ids("<|im_end|>")

        so = ort.SessionOptions()
        so.inter_op_num_threads = 1
        so.intra_op_num_threads = 2
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            model_path, sess_options=so,
            providers=["CPUExecutionProvider"],
        )

        elapsed = (time.perf_counter() - t0) * 1000
        self._initialized = True
        logger.info(
            "LiveKit turn detector loaded (%.0fms, im_end_id=%d)",
            elapsed, self._im_end_id,
        )

    def _predict_eou(self, user_text: str) -> float:
        """Predict end-of-utterance probability from conversation context.

        Args:
            user_text: The current user transcription text.

        Returns:
            Probability (0-1) that the user has finished their turn.
        """
        if not self._initialized or self._session is None:
            return 0.0

        # Build messages with context + current user text
        messages = list(self._context)
        messages.append({"role": "user", "content": user_text})

        # Apply Qwen chat template
        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False,
        )
        # Strip trailing <|im_end|> so model predicts its probability
        if text.endswith("<|im_end|>\n"):
            text = text[: -len("<|im_end|>\n")]
        elif text.endswith("<|im_end|>"):
            text = text[: -len("<|im_end|>")]

        input_ids = self._tokenizer(
            text, return_tensors="np", truncation=True, max_length=512,
        )["input_ids"].astype(np.int64)

        t0 = time.perf_counter()
        outputs = self._session.run(None, {"input_ids": input_ids})
        self._last_inference_ms = (time.perf_counter() - t0) * 1000

        logits = outputs[0]  # [batch, seq_len, vocab_size]
        last_logits = logits[0, -1, :]

        # Stable softmax
        max_logit = np.max(last_logits)
        exp_logits = np.exp(last_logits - max_logit)
        probs = exp_logits / np.sum(exp_logits)

        return float(probs[self._im_end_id])

    def add_assistant_context(self, text: str) -> None:
        """Record an assistant response for conversation context.

        Call this when the assistant finishes a response so the
        turn detector has full conversation context.

        Args:
            text: The assistant's response text.
        """
        if text and text.strip():
            self._context.append({"role": "assistant", "content": text.strip()})

    @property
    def last_eou_probability(self) -> float:
        """The most recent end-of-utterance probability."""
        return self._last_eou_prob

    @property
    def last_inference_ms(self) -> float:
        """Inference time for the most recent prediction."""
        return self._last_inference_ms

    async def process_frame(
        self, frame: Frame, direction: FrameDirection,
    ) -> None:
        """Process frames, computing EOU probability on transcriptions."""
        await super().process_frame(frame, direction)

        if (
            direction == FrameDirection.DOWNSTREAM
            and isinstance(frame, TranscriptionFrame)
            and frame.text
            and frame.text.strip()
        ):
            self._ensure_model()
            eou_prob = self._predict_eou(frame.text)
            self._last_eou_prob = eou_prob

            decision = "COMPLETE" if eou_prob > self._threshold else "INCOMPLETE"
            logger.info(
                "SemanticTurn: '%s' -> EOU=%.3f (%s, %.1fms)",
                frame.text[:60], eou_prob, decision,
                self._last_inference_ms,
            )

            # Record this user turn in context
            self._context.append({"role": "user", "content": frame.text.strip()})

        # Always pass all frames through — this is purely observational
        await self.push_frame(frame, direction)
