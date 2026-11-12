"""Resolve edit feedback into a validated FeedbackPlan, in priority order.

1. ``operations`` supplied by the caller (the agent already produced typed ops;
   nothing to parse).
2. Free-text ``feedback`` parsed by the client's model via MCP sampling.
3. Free-text ``feedback`` parsed by the regex fallback (multi-intent).

Whatever the source, the plan is validated by pydantic before it can touch
the EDL, and the response records which parser produced it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from clipcannon.editing.feedback_ops import FeedbackPlan
from clipcannon.tools.feedback import regex_plan
from clipcannon.tools.feedback_sampling import plan_via_sampling

if TYPE_CHECKING:
    from clipcannon.editing.edl import EditDecisionList


class PlanError(ValueError):
    """Feedback could not be turned into a valid plan."""

    def __init__(self, code: str, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


async def resolve_plan(
    edl: EditDecisionList,
    feedback: str | None,
    operations: list[dict[str, Any]] | None,
) -> tuple[FeedbackPlan, str, dict[str, Any]]:
    """Return (plan, parser_name, diagnostics). Raises PlanError."""
    diagnostics: dict[str, Any] = {}

    if operations:
        try:
            plan = FeedbackPlan.model_validate({"ops": operations, "summary": feedback or ""})
        except ValidationError as exc:
            raise PlanError(
                "INVALID_OPERATIONS", "operations failed validation",
                {"errors": exc.errors(include_url=False, include_input=False)},
            ) from exc
        return plan, "operations", diagnostics

    text = (feedback or "").strip()
    if not text:
        raise PlanError(
            "INVALID_PARAMETER", "Provide 'operations' or non-empty 'feedback'.", {},
        )

    plan, sampling_info = await plan_via_sampling(text, edl)
    diagnostics["sampling"] = sampling_info
    if plan is not None:
        return plan, "sampling", diagnostics

    plan = regex_plan(text, edl)
    if plan is not None:
        return plan, "regex", diagnostics

    raise PlanError(
        "LOW_CONFIDENCE",
        f"Could not turn feedback into edit operations: {text!r}",
        {
            **diagnostics,
            "hint": (
                "Pass typed 'operations' instead of free text, e.g. "
                '[{"op": "captions", "font_size_delta": 16, "position": "center"}, '
                '{"op": "framing", "segment_ids": [2], "focus_x": 0.3}]'
            ),
        },
    )
