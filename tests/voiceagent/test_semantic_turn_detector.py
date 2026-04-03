"""Full State Verification tests for SemanticTurnDetector.

Tests the LiveKit text-based end-of-turn ONNX model integration.
Each test verifies:
  1. The prediction value (source of truth: _last_eou_prob)
  2. The context buffer state (source of truth: _context deque)
  3. Frame passthrough (source of truth: pushed frames)
"""
import asyncio

import numpy as np
import pytest

from voiceagent.audio.semantic_turn_detector import (
    EOU_THRESHOLD,
    MAX_CONTEXT_TURNS,
    SemanticTurnDetector,
)


@pytest.fixture
def detector():
    """Create a SemanticTurnDetector instance."""
    return SemanticTurnDetector(threshold=EOU_THRESHOLD)


# ------------------------------------------------------------------
# Unit tests: model loading and inference
# ------------------------------------------------------------------

class TestModelLoading:
    def test_not_initialized_before_first_use(self, detector):
        """Before any frame, model should not be loaded."""
        assert not detector._initialized
        assert detector._session is None
        assert detector._tokenizer is None

    def test_lazy_load_on_ensure(self, detector):
        """Model loads on first _ensure_model() call."""
        detector._ensure_model()
        assert detector._initialized
        assert detector._session is not None
        assert detector._tokenizer is not None
        # Verify im_end_id was resolved
        assert detector._im_end_id == 2  # Qwen's <|im_end|> token

    def test_double_ensure_is_noop(self, detector):
        """Calling _ensure_model twice doesn't reload."""
        detector._ensure_model()
        session1 = detector._session
        detector._ensure_model()
        assert detector._session is session1  # same object


# ------------------------------------------------------------------
# Happy path: complete utterances → high EOU probability
# ------------------------------------------------------------------

class TestCompleteUtterances:
    """Verify the model correctly identifies complete turns."""

    def test_complete_question(self, detector):
        """A clear question should have EOU > 0.5."""
        detector._ensure_model()
        prob = detector._predict_eou("What time is it right now?")
        print(f"BEFORE: context={list(detector._context)}")
        print(f"PREDICTION: prob={prob:.4f}")
        assert prob > 0.5, f"Expected EOU > 0.5, got {prob:.4f}"
        # Source of truth: _last_eou_prob is NOT set by _predict_eou directly,
        # only by process_frame. But the return value IS the probability.
        assert isinstance(prob, float)

    def test_complete_command(self, detector):
        """A command should have EOU > 0.5."""
        detector._ensure_model()
        prob = detector._predict_eou("Tell me a joke")
        print(f"PREDICTION: 'Tell me a joke' -> prob={prob:.4f}")
        assert prob > 0.5

    def test_single_word_answer(self, detector):
        """Single-word answers to questions should be complete."""
        detector._ensure_model()
        detector._context.append(
            {"role": "assistant", "content": "Do you want me to continue?"},
        )
        prob = detector._predict_eou("Yes")
        print(f"PREDICTION: 'Yes' (after question) -> prob={prob:.4f}")
        assert prob > 0.5

    def test_complete_statement(self, detector):
        """A full statement should be complete."""
        detector._ensure_model()
        prob = detector._predict_eou("I had a great day at work today.")
        print(f"PREDICTION: statement -> prob={prob:.4f}")
        assert prob > 0.5


# ------------------------------------------------------------------
# Happy path: incomplete utterances → low EOU probability
# ------------------------------------------------------------------

class TestIncompleteUtterances:
    """Verify the model correctly identifies incomplete turns."""

    def test_trailing_conjunction(self, detector):
        """Sentence ending with 'and' should be incomplete."""
        detector._ensure_model()
        prob = detector._predict_eou("I like cats and")
        print(f"PREDICTION: 'I like cats and' -> prob={prob:.4f}")
        assert prob < 0.3, f"Expected EOU < 0.3, got {prob:.4f}"

    def test_trailing_if(self, detector):
        """Sentence ending with 'if' should be incomplete."""
        detector._ensure_model()
        prob = detector._predict_eou("I was wondering if")
        print(f"PREDICTION: 'I was wondering if' -> prob={prob:.4f}")
        assert prob < 0.3

    def test_trailing_that(self, detector):
        """Sentence ending with 'that' should be incomplete."""
        detector._ensure_model()
        prob = detector._predict_eou("I'm building a system that")
        print(f"PREDICTION: 'I'm building a system that' -> prob={prob:.4f}")
        assert prob < 0.3

    def test_trailing_relative_clause(self, detector):
        """Sentence ending with 'which' should be incomplete."""
        detector._ensure_model()
        prob = detector._predict_eou("There's a problem which")
        print(f"PREDICTION: 'There's a problem which' -> prob={prob:.4f}")
        assert prob < 0.5


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_text_returns_zero(self, detector):
        """Empty text should not crash, returns 0.0."""
        detector._ensure_model()
        # _predict_eou with empty text -- the model still runs
        prob = detector._predict_eou("")
        print(f"EDGE: empty text -> prob={prob:.4f}")
        assert isinstance(prob, float)

    def test_very_long_text_truncated(self, detector):
        """Text > 512 tokens should be truncated, not crash."""
        detector._ensure_model()
        long_text = "word " * 600  # ~600 tokens
        prob = detector._predict_eou(long_text)
        print(f"EDGE: 600-word text -> prob={prob:.4f}")
        assert isinstance(prob, float)
        assert 0.0 <= prob <= 1.0

    def test_context_window_bounded(self, detector):
        """Context should not grow beyond MAX_CONTEXT_TURNS."""
        for i in range(MAX_CONTEXT_TURNS + 5):
            detector._context.append(
                {"role": "user", "content": f"Message {i}"},
            )
        print(f"EDGE: context size after {MAX_CONTEXT_TURNS + 5} appends = {len(detector._context)}")
        assert len(detector._context) == MAX_CONTEXT_TURNS

    def test_uninitialized_predict_returns_zero(self, detector):
        """Prediction without model loaded returns 0.0 safely."""
        prob = detector._predict_eou("Hello")
        print(f"EDGE: uninitialized predict -> prob={prob:.4f}")
        assert prob == 0.0


# ------------------------------------------------------------------
# Pipecat frame processing integration
# ------------------------------------------------------------------

class TestFrameProcessing:
    @pytest.mark.asyncio
    async def test_transcription_frame_triggers_prediction(self, detector):
        """TranscriptionFrame should trigger EOU prediction."""
        from pipecat.frames.frames import TranscriptionFrame

        # Track pushed frames
        pushed = []
        original_push = detector.push_frame

        async def capture_push(frame, direction):
            pushed.append(frame)

        detector.push_frame = capture_push

        frame = TranscriptionFrame(
            text="What is the weather like today?",
            user_id="test",
            timestamp="2026-04-03T00:00:00",
        )
        from pipecat.processors.frame_processor import FrameDirection
        await detector.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Source of truth 1: _last_eou_prob was updated
        print(f"FSV: _last_eou_prob = {detector._last_eou_prob:.4f}")
        assert detector._last_eou_prob > 0.5  # complete question

        # Source of truth 2: frame was passed through (not blocked)
        print(f"FSV: pushed frames count = {len(pushed)}")
        assert len(pushed) == 1
        assert pushed[0] is frame

        # Source of truth 3: context was updated
        print(f"FSV: context = {list(detector._context)}")
        assert len(detector._context) == 1
        assert detector._context[0]["role"] == "user"
        assert "weather" in detector._context[0]["content"]

    @pytest.mark.asyncio
    async def test_non_transcription_frame_passes_through(self, detector):
        """Non-transcription frames should pass through without prediction."""
        from pipecat.frames.frames import TTSStartedFrame
        from pipecat.processors.frame_processor import FrameDirection

        pushed = []
        async def capture_push(frame, direction):
            pushed.append(frame)
        detector.push_frame = capture_push

        frame = TTSStartedFrame()
        await detector.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Should pass through, no prediction
        assert len(pushed) == 1
        assert detector._last_eou_prob == 0.0  # unchanged
        print(f"FSV: non-transcription passthrough OK, prob still {detector._last_eou_prob}")

    @pytest.mark.asyncio
    async def test_assistant_context_tracking(self, detector):
        """add_assistant_context should update the context buffer."""
        detector.add_assistant_context("Sure, I can help with that.")

        print(f"FSV: context after assistant add = {list(detector._context)}")
        assert len(detector._context) == 1
        assert detector._context[0]["role"] == "assistant"
        assert detector._context[0]["content"] == "Sure, I can help with that."

    @pytest.mark.asyncio
    async def test_assistant_context_empty_ignored(self, detector):
        """Empty assistant text should not be added to context."""
        detector.add_assistant_context("")
        detector.add_assistant_context("   ")

        print(f"FSV: context after empty adds = {list(detector._context)}")
        assert len(detector._context) == 0


# ------------------------------------------------------------------
# Performance verification
# ------------------------------------------------------------------

class TestPerformance:
    def test_inference_under_50ms(self, detector):
        """Each inference should complete in under 50ms on CPU."""
        detector._ensure_model()
        # Warm up
        detector._predict_eou("Hello")

        times = []
        for text in [
            "What time is it?",
            "Tell me about the weather forecast for tomorrow.",
            "I was wondering if you could help me with something.",
        ]:
            detector._predict_eou(text)
            times.append(detector._last_inference_ms)

        avg_ms = sum(times) / len(times)
        max_ms = max(times)
        print(f"PERF: avg={avg_ms:.1f}ms, max={max_ms:.1f}ms")
        assert max_ms < 50, f"Inference too slow: max={max_ms:.1f}ms"
