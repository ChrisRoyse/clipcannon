"""Profanity detection pipeline stage for ClipCannon.

Matches transcript words against a severity-rated word list to detect
profanity, compute content ratings, and populate the content_safety
table. This is an optional stage -- failure does not abort the pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, execute, fetch_all
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "profanity_detection"
STAGE = "profanity"

# Path to the bundled word list, relative to the repo root.
# Resolved at runtime via _resolve_wordlist_path().
_WORDLIST_RELATIVE = Path("assets") / "profanity" / "wordlist.txt"


def _resolve_wordlist_path() -> Path:
    """Locate the profanity word list file.

    Searches upward from this file's location to find the repository
    root containing the assets/ directory.

    Returns:
        Resolved path to the word list file.
    """
    # Walk up from src/clipcannon/pipeline/ to find repo root
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / _WORDLIST_RELATIVE
        if candidate.exists():
            return candidate
        current = current.parent
    # Fallback: assume CWD-based
    return Path.cwd() / _WORDLIST_RELATIVE


def _load_wordlist(path: Path) -> dict[str, str]:
    """Load the profanity word list from a tab-separated file.

    Each line: word<TAB>severity  (severe | moderate | mild).

    Args:
        path: Path to the word list file.

    Returns:
        Mapping of lowercase word to severity level.
    """
    words: dict[str, str] = {}
    if not path.exists():
        logger.warning("Profanity word list not found at %s", path)
        return words

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                word = parts[0].strip().lower()
                severity = parts[1].strip().lower()
                if severity not in ("severe", "moderate", "mild"):
                    severity = "mild"
                words[word] = severity

    logger.info("Loaded %d profanity words from %s", len(words), path)
    return words


def _match_transcript_words(
    db_path: Path,
    project_id: str,
    wordlist: dict[str, str],
) -> list[dict[str, str | int]]:
    """Match transcript words against the profanity word list.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        wordlist: Mapping of lowercase word to severity.

    Returns:
        List of profanity match dicts with word, start_ms, end_ms, severity.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        rows = fetch_all(
            conn,
            "SELECT tw.word, tw.start_ms, tw.end_ms "
            "FROM transcript_words tw "
            "JOIN transcript_segments ts ON tw.segment_id = ts.segment_id "
            "WHERE ts.project_id = ? "
            "ORDER BY tw.start_ms",
            (project_id,),
        )
    finally:
        conn.close()

    matches: list[dict[str, str | int]] = []
    for row in rows:
        raw_word = str(row["word"]).strip()
        # Strip punctuation for matching
        clean = raw_word.lower().strip(".,!?;:\"'-()[]{}#@")
        if clean in wordlist:
            matches.append(
                {
                    "word": raw_word,
                    "start_ms": int(row["start_ms"]),
                    "end_ms": int(row["end_ms"]),
                    "severity": wordlist[clean],
                }
            )

    return matches


def _compute_content_rating(count: int) -> str:
    """Determine content rating based on profanity count.

    Thresholds:
        clean:    0 matches
        mild:     1-3 matches
        moderate: 4-10 matches
        explicit: >10 matches

    Args:
        count: Number of profanity matches found.

    Returns:
        Content rating string.
    """
    if count == 0:
        return "clean"
    if count <= 3:
        return "mild"
    if count <= 10:
        return "moderate"
    return "explicit"


def _insert_profanity_results(
    db_path: Path,
    project_id: str,
    matches: list[dict[str, str | int]],
    duration_ms: int,
) -> tuple[int, str]:
    """Insert profanity events and content safety record.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        matches: Profanity match dicts.
        duration_ms: Total video duration in milliseconds.

    Returns:
        Tuple of (profanity_count, content_rating).
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        # Insert profanity_events
        if matches:
            event_rows: list[tuple[object, ...]] = [
                (
                    project_id,
                    str(m["word"]),
                    int(m["start_ms"]),
                    int(m["end_ms"]),
                    str(m["severity"]),
                )
                for m in matches
            ]
            batch_insert(
                conn,
                "profanity_events",
                ["project_id", "word", "start_ms", "end_ms", "severity"],
                event_rows,
            )

        profanity_count = len(matches)
        # Density: profanity per minute of content
        duration_min = max(duration_ms / 60_000.0, 0.001)
        profanity_density = round(profanity_count / duration_min, 4)
        content_rating = _compute_content_rating(profanity_count)

        execute(
            conn,
            "INSERT INTO content_safety "
            "(project_id, profanity_count, profanity_density, content_rating) "
            "VALUES (?, ?, ?, ?)",
            (project_id, profanity_count, profanity_density, content_rating),
        )

        conn.commit()
        return profanity_count, content_rating
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_duration_ms(db_path: Path, project_id: str) -> int:
    """Fetch project duration from the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        Duration in milliseconds, or 1 if not found.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        row = fetch_all(
            conn,
            "SELECT duration_ms FROM project WHERE project_id = ?",
            (project_id,),
        )
        if row and int(row[0].get("duration_ms", 0)) > 0:
            return int(row[0]["duration_ms"])
        return 1
    finally:
        conn.close()


async def run_profanity(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the profanity detection pipeline stage.

    Loads the profanity word list, matches transcript words, inserts
    profanity_events and content_safety records, and writes provenance.

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
        wordlist_path = _resolve_wordlist_path()
        wordlist = await asyncio.to_thread(_load_wordlist, wordlist_path)

        if not wordlist:
            logger.warning("Empty profanity word list, recording clean result")

        # Match transcript words
        matches = await asyncio.to_thread(
            _match_transcript_words,
            db_path,
            project_id,
            wordlist,
        )

        # Get duration for density calculation
        duration_ms = await asyncio.to_thread(
            _get_duration_ms,
            db_path,
            project_id,
        )

        # Insert results
        profanity_count, content_rating = await asyncio.to_thread(
            _insert_profanity_results,
            db_path,
            project_id,
            matches,
            duration_ms,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build provenance summary
        severity_counts: dict[str, int] = {}
        for m in matches:
            sev = str(m["severity"])
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        summary = (
            f"{profanity_count} matches (severe={severity_counts.get('severe', 0)}, "
            f"moderate={severity_counts.get('moderate', 0)}, "
            f"mild={severity_counts.get('mild', 0)}), rating={content_rating}"
        )
        output_sha = sha256_string(summary)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(sha256=sha256_string(str(wordlist_path))),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=profanity_count,
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=f"Profanity detection: {summary}",
        )

        logger.info(
            "Profanity detection complete in %d ms: %s",
            elapsed_ms,
            summary,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Profanity detection failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
