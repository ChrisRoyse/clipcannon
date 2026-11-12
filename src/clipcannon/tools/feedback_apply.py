"""Resolve edit feedback into a validated FeedbackPlan, in priority order.

1. ``operations`` supplied by the caller (the agent already produced typed ops;
   nothing to parse).
2. Free-text ``feedback`` planned by the client's model via MCP sampling.

There is no keyword fallback: when no planner is available, or it declines or
answers invalidly, the call fails closed with a typed code and changes nothing.
Whatever the source, the plan is validated by pydantic before it can touch
the EDL, and the response records which planner produced it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from clipcannon.editing.feedback_ops import FeedbackPlan
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

    details = {**diagnostics, "remediation": _REMEDIATION}
    if not sampling_info.get("available"):
        raise PlanError(
            "FEEDBACK_PLANNER_UNAVAILABLE",
            "Free-text feedback is planned by the client's model through MCP sampling, "
            f"which is unavailable here ({sampling_info.get('reason')}). Nothing was changed.",
            details,
        )
    if "declined" in sampling_info:
        raise PlanError(
            "FEEDBACK_NOT_EXPRESSIBLE",
            "The planner found no edit operation for this feedback: "
            f"{sampling_info['declined']!r}. Nothing was changed.",
            details,
        )
    raise PlanError(
        "FEEDBACK_PLAN_INVALID",
        f"The planner's reply did not validate after {sampling_info.get('attempts')} "
        "attempts. Nothing was changed.",
        details,
    )


_REMEDIATION = (
    "Pass typed 'operations' (schema in this tool's definition), e.g. "
    '[{"op": "captions", "font_size_delta": 16, "position": "center"}, '
    '{"op": "framing", "segment_ids": [2], "focus_x": 0.3}]'
)
