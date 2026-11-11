"""Tests for typed feedback operations, the sampling parser and the regex
fallback (replacement for single-intent regex parsing)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from clipcannon.editing.caption_render import generate_ass_file
from clipcannon.editing.edl import (
    CaptionChunk,
    CaptionSpec,
    CaptionWord,
    EditDecisionList,
    SegmentSpec,
)
from clipcannon.editing.feedback_ops import FeedbackPlan, OpError, ops_to_changes
from clipcannon.tools.feedback import regex_plan
from clipcannon.tools.feedback_apply import PlanError, resolve_plan
from clipcannon.tools.feedback_sampling import plan_via_sampling


def _edl() -> EditDecisionList:
    chunk = CaptionChunk(chunk_id=1, text="hello world", start_ms=0, end_ms=900,
                         words=[CaptionWord(word="hello", start_ms=0, end_ms=400),
                                CaptionWord(word="world", start_ms=400, end_ms=900)])
    return EditDecisionList(
        edit_id="edit_test", project_id="proj_test", name="t",
        target_platform="youtube_shorts", source_sha256="0" * 64,
        segments=[
            SegmentSpec(segment_id=1, source_start_ms=10_000, source_end_ms=20_000,
                        output_start_ms=0),
            SegmentSpec(segment_id=2, source_start_ms=30_000, source_end_ms=45_000,
                        output_start_ms=10_000),
        ],
        captions=CaptionSpec(font_size=48, chunks=[chunk]),
    )


# ---------------------------------------------------------------- validation
class TestPlanValidation:
    def test_unknown_op_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackPlan.model_validate({"ops": [{"op": "teleport"}]})

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackPlan.model_validate({"ops": [{"op": "captions", "font_sz": 60}]})

    def test_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackPlan.model_validate({"ops": [{"op": "speed", "speed": 9.0}]})

    def test_speed_requires_exactly_one_of_speed_or_delta(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackPlan.model_validate({"ops": [{"op": "speed"}]})
        with pytest.raises(ValidationError):
            FeedbackPlan.model_validate({"ops": [{"op": "speed", "speed": 1.2, "delta": 0.1}]})

    def test_empty_plan_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackPlan.model_validate({"ops": []})


# ---------------------------------------------------------------- ops -> changes
class TestOpsToChanges:
    def test_caption_change_merges_and_keeps_chunks(self) -> None:
        plan = FeedbackPlan.model_validate(
            {"ops": [{"op": "captions", "font_size_delta": 16, "position": "center"}]})
        changes, special = ops_to_changes(plan, _edl())
        assert changes["captions"]["font_size"] == 64
        assert changes["captions"]["position"] == "center"
        assert changes["captions"]["chunks"], "caption chunks must be preserved"
        assert "segments" not in changes
        assert special == []

    def test_multiple_ops_combine(self) -> None:
        plan = FeedbackPlan.model_validate({"ops": [
            {"op": "captions", "font_size": 72},
            {"op": "speed", "segment_ids": [2], "delta": 0.25},
            {"op": "trim", "segment_id": 1, "start_delta_ms": 1500},
            {"op": "audio", "delta_db": -3},
        ]})
        changes, _ = ops_to_changes(plan, _edl())
        segs = changes["segments"]
        assert changes["captions"]["font_size"] == 72
        assert segs[0]["source_start_ms"] == 11_500 and segs[0]["speed"] == 1.0
        assert segs[1]["speed"] == 1.25
        assert changes["audio"]["source_volume_db"] == -3.0

    def test_unknown_segment_is_an_error(self) -> None:
        plan = FeedbackPlan.model_validate({"ops": [{"op": "remove_segments", "segment_ids": [7]}]})
        with pytest.raises(OpError, match="unknown segment"):
            ops_to_changes(plan, _edl())

    def test_trim_cannot_collapse_segment(self) -> None:
        plan = FeedbackPlan.model_validate(
            {"ops": [{"op": "trim", "segment_id": 1, "end_delta_ms": -9_800}]})
        with pytest.raises(OpError, match="500 ms"):
            ops_to_changes(plan, _edl())

    def test_cannot_remove_every_segment(self) -> None:
        plan = FeedbackPlan.model_validate(
            {"ops": [{"op": "remove_segments", "segment_ids": [1, 2]}]})
        with pytest.raises(OpError, match="every segment"):
            ops_to_changes(plan, _edl())

    def test_framing_crops_a_vertical_window_around_the_subject(self) -> None:
        plan = FeedbackPlan.model_validate(
            {"ops": [{"op": "framing", "segment_ids": [2], "focus_x": 0.3}]})
        changes, _ = ops_to_changes(plan, _edl(), source_size=(1920, 1080),
                                    canvas_size=(1080, 1920))
        segs = changes["segments"]
        assert "canvas" not in segs[0]
        region = segs[1]["canvas"]["regions"][0]
        # 1080 tall source window at 9:16 -> 608 wide, centered on x = 576.
        assert region["source_height"] == 1080
        assert region["source_width"] == 608
        assert region["source_x"] == 272
        assert (region["output_width"], region["output_height"]) == (1080, 1920)

    def test_framing_clamps_at_frame_edge(self) -> None:
        plan = FeedbackPlan.model_validate({"ops": [{"op": "framing", "focus_x": 0.0}]})
        changes, _ = ops_to_changes(plan, _edl())
        for seg in changes["segments"]:
            assert seg["canvas"]["regions"][0]["source_x"] == 0

    def test_color_resolves_to_absolute_values(self) -> None:
        plan = FeedbackPlan.model_validate({"ops": [{"op": "color", "saturation_delta": 0.2}]})
        changes, special = ops_to_changes(plan, _edl())
        assert changes == {}
        assert special[0]["action"] == "clipcannon_color_adjust"
        assert special[0]["parameters"]["saturation"] == 1.2


# ---------------------------------------------------------------- regex fallback
class TestRegexFallback:
    @pytest.mark.parametrize("text", [
        "bigger captions",
        "captions are too small",
        "the subtitles are tiny",
        "make the captions bigger",
    ])
    def test_caption_growth_phrasings(self, text: str) -> None:
        plan = regex_plan(text, _edl())
        assert plan is not None, text
        assert plan.ops[0].op == "captions"
        assert plan.ops[0].font_size_delta > 0

    def test_multiple_intents_in_one_sentence(self) -> None:
        plan = regex_plan(
            "captions are too small, make them much bigger and move them up "
            "out of the bottom of the frame", _edl())
        assert plan is not None
        kinds = [(o.op, o.font_size_delta, o.position) for o in plan.ops]
        assert ("captions", 16, None) in kinds
        assert any(o.op == "captions" and o.position == "center" for o in plan.ops)

    def test_unrelated_text_gives_none(self) -> None:
        assert regex_plan("I really like this video a lot", _edl()) is None


# ---------------------------------------------------------------- sampling
class _FakeSession:
    def __init__(self, replies: list[str], *, capable: bool = True) -> None:
        self.replies = replies
        self.capable = capable
        self.calls: list[dict[str, object]] = []

    def check_client_capability(self, _caps: object) -> bool:
        return self.capable

    async def create_message(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        text = self.replies[len(self.calls) - 1]
        return SimpleNamespace(content=SimpleNamespace(type="text", text=text), model="fake")


@pytest.fixture()
def fake_ctx():  # noqa: ANN201
    """Install a fake MCP request context for the current test.

    pytest-asyncio runs each test in its own copy of the context, so the value
    never leaks into other tests and needs no reset.
    """
    from mcp.server.lowlevel.server import request_ctx

    def _install(session: _FakeSession) -> None:
        request_ctx.set(SimpleNamespace(session=session, request_id=1))

    return _install


class TestSampling:
    @pytest.mark.asyncio()
    async def test_no_request_context_means_unavailable(self) -> None:
        plan, info = await plan_via_sampling("bigger captions", _edl())
        assert plan is None
        assert info["available"] is False

    @pytest.mark.asyncio()
    async def test_client_without_sampling_capability(self, fake_ctx) -> None:  # noqa: ANN001
        fake_ctx(_FakeSession([], capable=False))
        plan, info = await plan_via_sampling("bigger captions", _edl())
        assert plan is None and "sampling capability" in info["reason"]

    @pytest.mark.asyncio()
    async def test_valid_reply_in_fences(self, fake_ctx) -> None:  # noqa: ANN001
        reply = "```json\n" + json.dumps({"ops": [
            {"op": "captions", "font_size_delta": 20, "position": "center"},
            {"op": "framing", "segment_ids": [2], "focus_x": 0.3},
        ], "summary": "bigger, centered captions; keep speaker in frame"}) + "\n```"
        session = _FakeSession([reply])
        fake_ctx(session)
        plan, info = await plan_via_sampling("bigger captions, keep Reid in shot", _edl())
        assert plan is not None and len(plan.ops) == 2
        assert info["attempts"] == 1
        sent = session.calls[0]
        assert "FeedbackPlan" in str(sent["system_prompt"]) or "ops" in str(sent["system_prompt"])

    @pytest.mark.asyncio()
    async def test_invalid_reply_is_retried_with_the_error(self, fake_ctx) -> None:  # noqa: ANN001
        bad = json.dumps({"ops": [{"op": "captions", "font_size": 999}]})
        good = json.dumps({"ops": [{"op": "captions", "font_size": 80}]})
        session = _FakeSession([bad, good])
        fake_ctx(session)
        plan, info = await plan_via_sampling("huge captions", _edl())
        assert plan is not None and plan.ops[0].font_size == 80
        assert info["attempts"] == 2
        retry_msgs = session.calls[1]["messages"]
        assert "did not validate" in retry_msgs[-1].content.text

    @pytest.mark.asyncio()
    async def test_model_can_decline(self, fake_ctx) -> None:  # noqa: ANN001
        fake_ctx(_FakeSession([json.dumps({"ops": [], "summary": "not an edit request"})]))
        plan, info = await plan_via_sampling("I love this", _edl())
        assert plan is None and info["declined"] == "not an edit request"


# ---------------------------------------------------------------- resolution order
class TestResolvePlan:
    @pytest.mark.asyncio()
    async def test_operations_win_without_parsing(self) -> None:
        plan, parser, _ = await resolve_plan(
            _edl(), "ignored text", [{"op": "captions", "font_size": 70}])
        assert parser == "operations" and plan.ops[0].font_size == 70

    @pytest.mark.asyncio()
    async def test_invalid_operations_raise(self) -> None:
        with pytest.raises(PlanError) as exc:
            await resolve_plan(_edl(), None, [{"op": "captions", "font_size": 1}])
        assert exc.value.code == "INVALID_OPERATIONS"

    @pytest.mark.asyncio()
    async def test_sampling_before_regex(self, fake_ctx) -> None:  # noqa: ANN001
        fake_ctx(_FakeSession([json.dumps({"ops": [{"op": "audio", "delta_db": -6}]})]))
        _, parser, diag = await resolve_plan(_edl(), "bigger captions", None)
        assert parser == "sampling" and diag["sampling"]["attempts"] == 1

    @pytest.mark.asyncio()
    async def test_regex_when_sampling_unavailable(self) -> None:
        _, parser, diag = await resolve_plan(_edl(), "bigger captions", None)
        assert parser == "regex" and diag["sampling"]["available"] is False

    @pytest.mark.asyncio()
    async def test_low_confidence_when_nothing_parses(self) -> None:
        with pytest.raises(PlanError) as exc:
            await resolve_plan(_edl(), "I really like this video a lot", None)
        assert exc.value.code == "LOW_CONFIDENCE"


# ---------------------------------------------------------------- caption render
class TestCaptionRenderHonorsSpec:
    def _style_line(self, ass: str) -> list[str]:
        line = next(ln for ln in ass.splitlines() if ln.startswith("Style: "))
        return line[len("Style: "):].split(",")

    def test_font_size_is_used(self) -> None:
        edl = _edl()
        ass = generate_ass_file(edl.captions.chunks, "word_highlight", 1080, 1920, font_size=80)
        assert self._style_line(ass)[2] == "80"

    def test_default_style_size_without_override(self) -> None:
        ass = generate_ass_file(_edl().captions.chunks, "word_highlight", 1080, 1920)
        assert self._style_line(ass)[2] == "44"

    @pytest.mark.parametrize(("position", "alignment", "margin_v"), [
        ("bottom", "2", str(int(1920 * 0.22))),
        ("center", "5", "0"),
        ("top", "8", str(int(1920 * 0.12))),
    ])
    def test_position_maps_to_alignment(self, position: str, alignment: str, margin_v: str) -> None:
        f = self._style_line(generate_ass_file(
            _edl().captions.chunks, "word_highlight", 1080, 1920, position=position))
        assert (f[18], f[21]) == (alignment, margin_v)
