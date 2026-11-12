"""Reaction post-processing, storage and the run_reactions entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.reactions_detect import (
    ENERGY_REACTION_THRESHOLD,
    OPERATION,
    STAGE,
    STRIDE_S,
    WINDOW_S,
    _check_sensevoice_funasr,
    _detect_reactions_energy,
    _detect_reactions_funasr,
    _load_audio,
)
from clipcannon.pipeline.source_resolution import resolve_audio_input
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)


def _attach_context_transcripts(
    db_path: Path,
    project_id: str,
    reactions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach nearest transcript text as context for each reaction.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        reactions: List of reaction dicts.

    Returns:
        Updated reaction dicts with context_transcript field.
    """
    if not reactions:
        return reactions

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        segments = fetch_all(
            conn,
            "SELECT start_ms, end_ms, text FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
    finally:
        conn.close()

    if not segments:
        return reactions

    for reaction in reactions:
        r_mid = (int(reaction["start_ms"]) + int(reaction["end_ms"])) // 2
        best_text = ""
        best_dist = float("inf")

        for seg in segments:
            seg_mid = (int(seg["start_ms"]) + int(seg["end_ms"])) // 2
            dist = abs(r_mid - seg_mid)
            if dist < best_dist:
                best_dist = dist
                best_text = str(seg.get("text", ""))

        reaction["context_transcript"] = best_text[:200]

    return reactions


def _merge_overlapping_reactions(
    reactions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Merge overlapping reactions of the same type.

    Args:
        reactions: List of reaction dicts, possibly overlapping.

    Returns:
        Merged reactions list.
    """
    if not reactions:
        return reactions

    sorted_reactions = sorted(reactions, key=lambda r: (str(r["type"]), int(r["start_ms"])))
    merged: list[dict[str, object]] = []

    current = dict(sorted_reactions[0])
    for r in sorted_reactions[1:]:
        if str(r["type"]) == str(current["type"]) and int(r["start_ms"]) <= int(current["end_ms"]):
            current["end_ms"] = max(int(current["end_ms"]), int(r["end_ms"]))
            current["duration_ms"] = int(current["end_ms"]) - int(current["start_ms"])
            current["confidence"] = max(
                float(current.get("confidence", 0)),
                float(r.get("confidence", 0)),
            )
        else:
            merged.append(current)
            current = dict(r)

    merged.append(current)
    return merged


def _insert_reactions(
    db_path: Path,
    project_id: str,
    reactions: list[dict[str, object]],
) -> int:
    """Insert reactions into the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        reactions: List of reaction dicts.

    Returns:
        Number of reactions inserted.
    """
    if not reactions:
        return 0

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        rows: list[tuple[object, ...]] = [
            (
                project_id,
                int(r["start_ms"]),
                int(r["end_ms"]),
                str(r["type"]),
                float(r.get("confidence", 0.0)),
                int(r.get("duration_ms", 0)),
                str(r.get("intensity", "moderate")),
                str(r.get("context_transcript", ""))[:200],
            )
            for r in reactions
        ]
        batch_insert(
            conn,
            "reactions",
            [
                "project_id",
                "start_ms",
                "end_ms",
                "type",
                "confidence",
                "duration_ms",
                "intensity",
                "context_transcript",
            ],
            rows,
        )
        conn.commit()
        return len(rows)
    except Exception as exc:
        conn.rollback()
        raise PipelineError(
            f"Failed to insert reactions: {exc}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
    finally:
        conn.close()


async def run_reactions(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the reaction detection pipeline stage.

    Tries SenseVoice (FunASR) first, then falls back to energy-based
    reaction detection for laughter and applause events.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    start_time = time.monotonic()

    try:
        audio_path = resolve_audio_input(project_dir)
        logger.info("Reaction detection starting: %s", audio_path)

        audio, sample_rate = await asyncio.to_thread(_load_audio, audio_path)
        logger.info(
            "Audio loaded: %.1f seconds",
            len(audio) / sample_rate,
        )

        backend_name = "energy_fallback"

        # Try FunASR SenseVoice
        if _check_sensevoice_funasr():
            try:
                reactions = await asyncio.to_thread(
                    _detect_reactions_funasr,
                    audio,
                    sample_rate,
                )
                backend_name = "sensevoice_funasr"
                logger.info("SenseVoice detected %d reactions", len(reactions))
            except Exception as sv_err:
                # SenseVoice is installed and failed: refuse (#68) instead of
                # answering with a different instrument (energy heuristic).
                raise RuntimeError(f"SenseVoice reaction detection failed: {sv_err}") from sv_err
        else:
            logger.info(
                "SenseVoice not available, using energy-based detection",
            )
            reactions = await asyncio.to_thread(
                _detect_reactions_energy,
                audio,
                sample_rate,
            )

        # Merge overlapping reactions
        reactions = _merge_overlapping_reactions(reactions)

        # Attach context transcripts
        reactions = await asyncio.to_thread(
            _attach_context_transcripts,
            db_path,
            project_id,
            reactions,
        )

        # Insert
        count = await asyncio.to_thread(
            _insert_reactions,
            db_path,
            project_id,
            reactions,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Provenance
        input_sha = await asyncio.to_thread(sha256_file, audio_path)
        reaction_summary = json.dumps(
            [{"t": r["type"], "s": r["start_ms"]} for r in reactions],
            sort_keys=True,
        )
        output_sha = sha256_string(reaction_summary)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(audio_path),
                sha256=input_sha,
                size_bytes=audio_path.stat().st_size,
            ),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=count,
            ),
            model_info=ModelInfo(
                name=backend_name,
                version="1.0",
                parameters={
                    "window_s": WINDOW_S,
                    "stride_s": STRIDE_S,
                    "energy_threshold": ENERGY_REACTION_THRESHOLD,
                },
            ),
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Reaction detection ({backend_name}): {count} reactions "
                f"({', '.join(str(r['type']) for r in reactions[:5])})"
            ),
        )

        logger.info(
            "Reaction detection complete in %d ms: %d reactions (%s)",
            elapsed_ms,
            count,
            backend_name,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except PipelineError:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Reaction detection failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
