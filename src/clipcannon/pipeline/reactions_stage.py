"""Reaction post-processing, storage and the run_reactions entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_all
from clipcannon.db.schema_migrations import migrate_to_v5
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.reactions_detect import (
    ENERGY,
    ENERGY_REACTION_THRESHOLD,
    OPERATION,
    SENSEVOICE,
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
            # Same instrument per run: both None (SenseVoice) or both scored.
            confs = [c for c in (current.get("confidence"), r.get("confidence")) if c is not None]
            current["confidence"] = max(float(c) for c in confs) if confs else None
        else:
            merged.append(current)
            current = dict(r)

    merged.append(current)
    return merged


def _insert_reactions(
    db_path: Path,
    project_id: str,
    reactions: list[dict[str, object]],
    instrument: str,
) -> int:
    """Replace the project's reactions with this run's, tagged by instrument.

    Deletes and inserts in one transaction, so a project never holds rows
    from two runs (or two instruments).

    Returns:
        Number of reactions inserted.
    """
    migrate_to_v5(db_path)
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        conn.execute("DELETE FROM reactions WHERE project_id = ?", (project_id,))
        rows: list[tuple[object, ...]] = [
            (
                project_id,
                int(r["start_ms"]),
                int(r["end_ms"]),
                str(r["type"]),
                None if r.get("confidence") is None else float(r["confidence"]),  # type: ignore[arg-type]
                int(r["end_ms"]) - int(r["start_ms"]),  # type: ignore[arg-type]
                r.get("intensity"),
                str(r.get("context_transcript", ""))[:200],
                instrument,
            )
            for r in reactions
        ]
        if not rows:
            conn.commit()
            return 0
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
                "instrument",
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

    SenseVoice (FunASR) when installed, otherwise the energy/spectral
    heuristic; each row records which instrument produced it.

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

        # Instrument chosen by installation; an installed SenseVoice that
        # fails fails the stage (#68), it never switches to energy.
        if _check_sensevoice_funasr():
            backend_name = SENSEVOICE
            try:
                reactions = await asyncio.to_thread(_detect_reactions_funasr, audio, sample_rate)
            except Exception as sv_err:
                raise RuntimeError(f"SenseVoice reaction detection failed: {sv_err}") from sv_err
        else:
            backend_name = ENERGY
            logger.info("FunASR not installed: detecting reactions with %s", ENERGY)
            reactions = await asyncio.to_thread(_detect_reactions_energy, audio, sample_rate)
        logger.info("%s detected %d reactions", backend_name, len(reactions))

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
            backend_name,
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
                    "instrument": backend_name,
                    **(
                        {"energy_threshold": ENERGY_REACTION_THRESHOLD}
                        if backend_name == ENERGY
                        else {}
                    ),
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
