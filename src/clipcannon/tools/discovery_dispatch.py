"""Dispatch for the discovery MCP tools."""

from __future__ import annotations

from clipcannon.tools.discovery_common import _error
from clipcannon.tools.discovery_cuts import clipcannon_find_cut_points
from clipcannon.tools.discovery_moments import clipcannon_find_best_moments
from clipcannon.tools.discovery_narrative import clipcannon_get_narrative_flow
from clipcannon.tools.discovery_safe_cuts import clipcannon_find_safe_cuts


# ============================================================
# DISPATCH
# ============================================================
async def dispatch_discovery_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch a discovery tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_find_best_moments":
        return await clipcannon_find_best_moments(
            project_id=str(arguments["project_id"]),
            purpose=str(arguments["purpose"]),
            target_duration_s=int(arguments.get("target_duration_s", 30)),  # type: ignore[arg-type]
            count=int(arguments.get("count", 5)),  # type: ignore[arg-type]
        )
    if name == "clipcannon_find_cut_points":
        return await clipcannon_find_cut_points(
            project_id=str(arguments["project_id"]),
            around_ms=int(arguments["around_ms"]),  # type: ignore[arg-type]
            search_range_ms=int(arguments.get("search_range_ms", 5000)),  # type: ignore[arg-type]
        )
    if name == "clipcannon_get_narrative_flow":
        raw_segs = arguments.get("segments", [])
        segs: list[dict[str, int]] = [
            {
                "start_ms": int(s["start_ms"]),  # type: ignore[arg-type, index]
                "end_ms": int(s["end_ms"]),  # type: ignore[arg-type, index]
            }
            for s in raw_segs  # type: ignore[union-attr]
        ]
        return await clipcannon_get_narrative_flow(
            project_id=str(arguments["project_id"]),
            segments=segs,
        )
    if name == "clipcannon_find_safe_cuts":
        return await clipcannon_find_safe_cuts(
            project_id=str(arguments["project_id"]),
            min_silence_ms=int(arguments.get("min_silence_ms", 400)),  # type: ignore[arg-type]
        )

    return _error(
        "INTERNAL_ERROR",
        f"Unknown discovery tool: {name}",
        {"tool": name},
    )
