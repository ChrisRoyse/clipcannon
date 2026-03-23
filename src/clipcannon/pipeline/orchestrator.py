"""DAG-based pipeline orchestrator for ClipCannon.

Resolves stage dependencies into an execution order, runs stages
respecting the dependency graph, tracks timing, and writes
stream_status records for each stage. Required stages abort the
pipeline on failure; optional stages log errors and continue.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from clipcannon.config import ClipCannonConfig
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.dag import topological_sort, update_stream_status

logger = logging.getLogger(__name__)

# Type alias for stage run functions
StageRunFn = Callable[
    [str, Path, Path, ClipCannonConfig],
    Awaitable["StageResult"],
]


class StageResult(BaseModel):
    """Result from executing a single pipeline stage.

    Attributes:
        success: Whether the stage completed without error.
        operation: Provenance operation identifier.
        error_message: Error description if the stage failed.
        duration_ms: Wall-clock execution time in milliseconds.
        provenance_record_id: ID of the provenance record created.
    """

    success: bool
    operation: str
    error_message: str | None = None
    duration_ms: int = 0
    provenance_record_id: str | None = None


class PipelineResult(BaseModel):
    """Aggregate result from a full pipeline run.

    Attributes:
        project_id: Project that was processed.
        success: True if all required stages succeeded.
        total_duration_ms: Total wall-clock time for the pipeline.
        stage_results: Mapping of stage name to its result.
        failed_required: List of required stages that failed.
        failed_optional: List of optional stages that failed.
    """

    project_id: str
    success: bool
    total_duration_ms: int = 0
    stage_results: dict[str, StageResult] = {}
    failed_required: list[str] = []
    failed_optional: list[str] = []


@dataclass
class PipelineStage:
    """Definition of a single pipeline stage.

    Attributes:
        name: Unique stage identifier.
        operation: Provenance operation ID for this stage.
        required: If True, failure stops the entire pipeline.
        depends_on: Stage names that must complete successfully first.
        run: Async function implementing the stage logic.
        fallback_values: Values to record if an optional stage fails.
        timeout_s: Maximum seconds before the stage is killed. Default 600.
    """

    name: str
    operation: str
    required: bool
    depends_on: list[str] = field(default_factory=list)
    run: StageRunFn | None = None
    fallback_values: dict[str, object] | None = None
    timeout_s: int = 600


# Re-export for backward compatibility with tests
_topological_sort = topological_sort


class PipelineOrchestrator:
    """DAG-based pipeline runner for ClipCannon video analysis.

    Resolves stage dependencies via topological sort, executes
    stages level-by-level with asyncio.gather for concurrency
    within each level, and tracks status in the stream_status table.

    Attributes:
        stages: Registered pipeline stages.
        config: ClipCannon configuration.
    """

    def __init__(self, config: ClipCannonConfig) -> None:
        """Initialize the orchestrator.

        Args:
            config: ClipCannon configuration instance.
        """
        self.stages: list[PipelineStage] = []
        self.config = config
        self._completed: set[str] = set()
        self._failed: set[str] = set()

    def register_stage(self, stage: PipelineStage) -> None:
        """Register a pipeline stage.

        Args:
            stage: Stage definition to register.

        Raises:
            PipelineError: If a stage with the same name is already registered.
        """
        existing_names = {s.name for s in self.stages}
        if stage.name in existing_names:
            raise PipelineError(
                f"Stage '{stage.name}' is already registered",
                stage_name=stage.name,
                operation=stage.operation,
            )
        self.stages.append(stage)
        logger.debug("Registered stage: %s (required=%s)", stage.name, stage.required)

    async def run(
        self,
        project_id: str,
        db_path: Path,
        project_dir: Path,
    ) -> PipelineResult:
        """Execute all registered stages respecting the dependency graph.

        Args:
            project_id: Project to process.
            db_path: Path to the project database.
            project_dir: Path to the project directory.

        Returns:
            PipelineResult with all stage outcomes.

        Raises:
            PipelineError: If dependency resolution fails.
        """
        pipeline_start = time.monotonic()
        self._completed = set()
        self._failed = set()
        stage_results: dict[str, StageResult] = {}
        failed_required: list[str] = []
        failed_optional: list[str] = []

        levels = topological_sort(self.stages)
        stage_map = {s.name: s for s in self.stages}

        logger.info(
            "Pipeline starting for project %s: %d stages in %d levels",
            project_id,
            len(self.stages),
            len(levels),
        )

        pipeline_aborted = False

        for level_idx, level in enumerate(levels):
            if pipeline_aborted:
                self._skip_level(level, stage_results, db_path, project_id)
                continue

            runnable, skipped = self._filter_runnable(level, stage_map)
            for stage, result in skipped:
                stage_results[stage.name] = result
                self._failed.add(stage.name)
                if stage.required:
                    failed_required.append(stage.name)
                else:
                    failed_optional.append(stage.name)
                update_stream_status(
                    db_path,
                    project_id,
                    stage.name,
                    "skipped",
                    error_message=result.error_message,
                )

            if not runnable:
                continue

            logger.info(
                "Level %d: running %d stages: %s",
                level_idx,
                len(runnable),
                [s.name for s in runnable],
            )

            tasks = [self._run_stage(stage, project_id, db_path, project_dir) for stage in runnable]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for stage, result in zip(runnable, results, strict=False):
                if isinstance(result, BaseException):
                    error_msg = f"Unexpected error: {result}"
                    sr = StageResult(
                        success=False,
                        operation=stage.operation,
                        error_message=error_msg,
                    )
                    stage_results[stage.name] = sr
                    self._failed.add(stage.name)
                    update_stream_status(
                        db_path,
                        project_id,
                        stage.name,
                        "failed",
                        error_message=error_msg,
                    )
                    if stage.required:
                        failed_required.append(stage.name)
                        pipeline_aborted = True
                    else:
                        failed_optional.append(stage.name)
                else:
                    stage_results[stage.name] = result
                    if result.success:
                        self._completed.add(stage.name)
                    else:
                        self._failed.add(stage.name)
                        if stage.required:
                            failed_required.append(stage.name)
                            pipeline_aborted = True
                        else:
                            failed_optional.append(stage.name)

        total_ms = int((time.monotonic() - pipeline_start) * 1000)
        success = len(failed_required) == 0

        logger.info(
            "Pipeline %s for project %s in %d ms. "
            "Completed: %d, Failed required: %d, Failed optional: %d",
            "completed" if success else "FAILED",
            project_id,
            total_ms,
            len(self._completed),
            len(failed_required),
            len(failed_optional),
        )

        return PipelineResult(
            project_id=project_id,
            success=success,
            total_duration_ms=total_ms,
            stage_results=stage_results,
            failed_required=failed_required,
            failed_optional=failed_optional,
        )

    def _skip_level(
        self,
        level: list[PipelineStage],
        stage_results: dict[str, StageResult],
        db_path: Path,
        project_id: str,
    ) -> None:
        """Mark all stages in a level as skipped."""
        for stage in level:
            result = StageResult(
                success=False,
                operation=stage.operation,
                error_message="Skipped: pipeline aborted due to required stage failure",
            )
            stage_results[stage.name] = result
            update_stream_status(
                db_path,
                project_id,
                stage.name,
                "skipped",
                error_message=result.error_message,
            )

    def _filter_runnable(
        self,
        level: list[PipelineStage],
        stage_map: dict[str, PipelineStage],
    ) -> tuple[list[PipelineStage], list[tuple[PipelineStage, StageResult]]]:
        """Filter stages by whether their dependencies are met."""
        runnable: list[PipelineStage] = []
        skipped: list[tuple[PipelineStage, StageResult]] = []

        for stage in level:
            deps_met = True
            for dep_name in stage.depends_on:
                if dep_name not in stage_map:
                    continue
                dep_stage = stage_map[dep_name]
                if dep_name in self._failed and dep_stage.required:
                    deps_met = False
                    break
                if dep_name not in self._completed and dep_name not in self._failed:
                    deps_met = False
                    break

            if deps_met:
                runnable.append(stage)
            else:
                result = StageResult(
                    success=False,
                    operation=stage.operation,
                    error_message="Skipped: dependency not met",
                )
                skipped.append((stage, result))

        return runnable, skipped

    async def _run_stage(
        self,
        stage: PipelineStage,
        project_id: str,
        db_path: Path,
        project_dir: Path,
    ) -> StageResult:
        """Execute a single stage with timing and status tracking."""
        logger.info("Starting stage: %s", stage.name)
        update_stream_status(db_path, project_id, stage.name, "running")
        start = time.monotonic()

        try:
            if stage.run is None:
                raise PipelineError(
                    f"Stage '{stage.name}' has no run function",
                    stage_name=stage.name,
                    operation=stage.operation,
                )

            result = await asyncio.wait_for(
                stage.run(project_id, db_path, project_dir, self.config),
                timeout=stage.timeout_s,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            result.duration_ms = elapsed_ms

            status = "completed" if result.success else "failed"
            update_stream_status(
                db_path,
                project_id,
                stage.name,
                status,
                error_message=result.error_message,
                duration_ms=elapsed_ms,
            )
            log_fn = logger.info if result.success else logger.warning
            log_fn(
                "Stage %s %s in %d ms%s",
                stage.name,
                status,
                elapsed_ms,
                f": {result.error_message}" if result.error_message else "",
            )
            return result

        except asyncio.TimeoutError:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            error_msg = (
                f"Stage '{stage.name}' timed out after {stage.timeout_s}s"
            )
            logger.error(error_msg)
            update_stream_status(
                db_path,
                project_id,
                stage.name,
                "failed",
                error_message=error_msg,
                duration_ms=elapsed_ms,
            )

            if stage.required:
                raise PipelineError(
                    error_msg,
                    stage_name=stage.name,
                    operation=stage.operation,
                )

            return StageResult(
                success=False,
                operation=stage.operation,
                error_message=error_msg,
                duration_ms=elapsed_ms,
            )

        except PipelineError:
            raise
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error("Stage %s raised exception: %s", stage.name, error_msg)
            update_stream_status(
                db_path,
                project_id,
                stage.name,
                "failed",
                error_message=error_msg,
                duration_ms=elapsed_ms,
            )

            if stage.required:
                raise PipelineError(
                    f"Required stage '{stage.name}' failed: {error_msg}",
                    stage_name=stage.name,
                    operation=stage.operation,
                ) from exc

            return StageResult(
                success=False,
                operation=stage.operation,
                error_message=error_msg,
                duration_ms=elapsed_ms,
            )
