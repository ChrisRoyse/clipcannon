"""Batch rendering with concurrency control for ClipCannon.

Renders multiple EDLs concurrently using an asyncio semaphore
to limit the number of parallel FFmpeg/NVENC sessions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from clipcannon.rendering.renderer import RenderEngine, RenderResult

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig
    from clipcannon.editing.edl import EditDecisionList

logger = logging.getLogger(__name__)


async def render_batch(
    edl_list: list[EditDecisionList],
    project_dir: Path,
    db_path: Path,
    config: ClipCannonConfig,
    max_concurrent: int = 3,
) -> list[RenderResult]:
    """Render multiple EDLs concurrently with a concurrency limit.

    Uses asyncio.Semaphore to cap the number of simultaneous
    FFmpeg render processes, defaulting to the configured
    max_parallel_renders value.

    Args:
        edl_list: List of EDLs to render.
        project_dir: Path to the project directory.
        db_path: Path to the project SQLite database.
        config: ClipCannon configuration instance.
        max_concurrent: Maximum concurrent renders. Defaults to
            config.rendering.max_parallel_renders if not specified.

    Returns:
        List of RenderResult in the same order as edl_list.
    """
    if not edl_list:
        return []

    # Use config default if caller passed the default value
    effective_max = config.validated.rendering.max_parallel_renders
    if max_concurrent != 3:
        effective_max = max_concurrent

    semaphore = asyncio.Semaphore(effective_max)
    engine = RenderEngine(config)

    logger.info(
        "Starting batch render of %d EDLs (max concurrent: %d)",
        len(edl_list),
        effective_max,
    )

    async def _render_with_limit(
        edl: EditDecisionList,
        index: int,
    ) -> RenderResult:
        """Render a single EDL within the semaphore limit.

        Args:
            edl: EDL to render.
            index: Position in the batch for logging.

        Returns:
            RenderResult for this EDL.
        """
        async with semaphore:
            logger.info(
                "Batch render [%d/%d]: starting edit %s",
                index + 1,
                len(edl_list),
                edl.edit_id,
            )
            try:
                result = await engine.render(edl, project_dir, db_path)
            except Exception as exc:
                logger.error(
                    "Batch render [%d/%d]: edit %s failed: %s",
                    index + 1,
                    len(edl_list),
                    edl.edit_id,
                    exc,
                )
                result = RenderResult(
                    render_id="",
                    success=False,
                    error_message=str(exc),
                )
            return result

    tasks = [
        _render_with_limit(edl, i)
        for i, edl in enumerate(edl_list)
    ]
    results = await asyncio.gather(*tasks)

    succeeded = sum(1 for r in results if r.success)
    failed = len(results) - succeeded
    logger.info(
        "Batch render complete: %d succeeded, %d failed",
        succeeded,
        failed,
    )

    return list(results)
