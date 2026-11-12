"""Parse free-text edit feedback with the *client's* model via MCP sampling.

ClipCannon is driven by an LLM agent, so understanding English should happen
in an LLM, not in server-side regexes. When the MCP client advertises the
``sampling`` capability, the server sends the feedback, a compact view of the
current EDL and the FeedbackPlan JSON schema to the client's model
(``sampling/createMessage``), validates the reply with pydantic, and retries
once with the validation error if the reply does not conform.

No model is loaded on the server; nothing runs when the client does not
support sampling (the caller then refuses with FEEDBACK_PLANNER_UNAVAILABLE).
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from clipcannon.editing.feedback_ops import FeedbackPlan, plan_json_schema

if TYPE_CHECKING:
    from clipcannon.editing.edl import EditDecisionList

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

_SYSTEM_PROMPT = """You translate a video editor's feedback about ONE edit into \
typed edit operations for ClipCannon.

Reply with ONLY a JSON object that validates against this JSON schema \
(no prose, no markdown fences):

{schema}

Rules:
- Use only operations the feedback asks for. Several requests -> several ops.
- Segment ids and times refer to the EDIT shown below. Times the user gives \
("at 0:15") are positions in the OUTPUT clip; map them to the segment whose \
output range contains them.
- Prefer relative changes (font_size_delta, delta, delta_db) for vague \
requests ("bigger", "a bit faster") and absolute values when a number is given.
- "framing": focus_x/focus_y are normalized coordinates in the SOURCE frame of \
the thing to keep centered (e.g. a speaker sitting at the left third -> \
focus_x about 0.3).
- If the feedback cannot be expressed with these operations, reply \
{{"ops": [], "summary": "<why>"}}."""


def describe_edl(edl: EditDecisionList) -> dict[str, Any]:
    """Compact, model-friendly view of the parts of an EDL feedback can touch."""
    return {
        "platform": edl.target_platform,
        "total_duration_ms": sum(s.output_duration_ms for s in edl.segments),
        "segments": [
            {
                "segment_id": s.segment_id,
                "output_ms": [s.output_start_ms, s.output_start_ms + s.output_duration_ms],
                "source_ms": [s.source_start_ms, s.source_end_ms],
                "speed": s.speed,
                "has_custom_framing": s.canvas is not None,
            }
            for s in edl.segments
        ],
        "captions": {
            "enabled": edl.captions.enabled,
            "style": edl.captions.style,
            "font_size": edl.captions.font_size,
            "position": edl.captions.position,
        },
        "audio": {"source_volume_db": edl.audio.source_volume_db},
    }


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a reply, tolerating fences or stray prose."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def _reply_text(result: object) -> str:
    content = getattr(result, "content", None)
    items = content if isinstance(content, list) else [content]
    return "".join(getattr(c, "text", "") or "" for c in items if c is not None)


def client_supports_sampling() -> tuple[Any | None, str]:
    """Return (request_context, reason). request_context is None if unusable."""
    try:
        from mcp import types
        from mcp.server.lowlevel.server import request_ctx
    except ImportError:  # pragma: no cover - mcp is a hard dependency
        return None, "mcp not importable"
    try:
        ctx = request_ctx.get()
    except LookupError:
        return None, "not called inside an MCP request"
    caps = types.ClientCapabilities(sampling=types.SamplingCapability())
    if not ctx.session.check_client_capability(caps):
        return None, "client does not advertise the sampling capability"
    return ctx, "ok"


async def plan_via_sampling(
    feedback: str, edl: EditDecisionList,
) -> tuple[FeedbackPlan | None, dict[str, Any]]:
    """Ask the client's model for a FeedbackPlan.

    Returns:
        (plan or None, info). ``info`` records whether sampling was available,
        how many attempts were made, and the last validation error.
    """
    ctx, reason = client_supports_sampling()
    info: dict[str, Any] = {"available": ctx is not None, "reason": reason, "attempts": 0}
    if ctx is None:
        return None, info

    from mcp import types

    system = _SYSTEM_PROMPT.format(schema=json.dumps(plan_json_schema(), separators=(",", ":")))
    user = (
        "Current edit:\n" + json.dumps(describe_edl(edl), indent=1)
        + "\n\nFeedback:\n" + feedback.strip()
    )
    def _msg(role: str, text: str) -> types.SamplingMessage:
        return types.SamplingMessage(role=role, content=types.TextContent(type="text", text=text))

    messages = [_msg("user", user)]

    for attempt in range(1, MAX_ATTEMPTS + 1):
        info["attempts"] = attempt
        try:
            result = await ctx.session.create_message(
                messages=messages,
                max_tokens=1200,
                system_prompt=system,
                temperature=0.0,
                related_request_id=ctx.request_id,
            )
        except Exception as exc:  # client refused, timed out, user declined
            info["error"] = f"sampling request failed: {exc}"
            logger.warning("Feedback sampling failed: %s", exc)
            return None, info

        reply = _reply_text(result)
        info["model"] = getattr(result, "model", None)
        try:
            data = json.loads(_extract_json(reply))
            if isinstance(data, dict) and data.get("ops") == []:
                info["declined"] = data.get("summary", "")
                return None, info
            return FeedbackPlan.model_validate(data), info
        except (json.JSONDecodeError, ValidationError) as exc:
            info["error"] = str(exc)[:800]
            messages += [
                _msg("assistant", reply),
                _msg("user", f"That reply did not validate:\n{info['error']}\n"
                             "Reply again with ONLY the corrected JSON object."),
            ]
    return None, info
