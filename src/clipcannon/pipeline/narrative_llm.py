"""Narrative structure analysis via Qwen3-8B LLM pipeline stage.

Runs Qwen3-8B in a subprocess to analyze video transcripts for
narrative structure: story beats, open loops, chapter boundaries,
key moments, and narrative summary.

The model is loaded from local cache only (HF_HUB_OFFLINE=1) and
runs on CUDA with FP16 precision. A subprocess is used for clean
GPU memory management, matching the pattern used by SigLIP and
PaddleOCR stages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "narrative_analysis"
STAGE = "qwen3_8b"
MODEL_DIR = "/home/cabdru/.clipcannon/models/qwen3-8b-hf/models--Qwen--Qwen3-8B/snapshots/b968826d9c46dd6066d109eabc6255188de91218"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS narrative_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    analysis_json TEXT NOT NULL,
    model_name TEXT NOT NULL DEFAULT 'Qwen3-8B',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
)"""

_WORKER_SCRIPT = r'''
import json, sys, os, re

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_DIR = sys.argv[1]
transcript_path = sys.argv[2]

with open(transcript_path, "r") as f:
    transcript = f.read()

tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_DIR, torch_dtype=torch.float16, device_map="cuda:0", local_files_only=True,
)

prompt = f"""Analyze this video transcript for editing. Return JSON only.

TRANSCRIPT:
{transcript}

Analyze and return this exact JSON structure:
{{
  "story_beats": [
    {{"start_text": "first few words...", "type": "hook|setup|argument|demo|result|cta", "summary": "one sentence description"}}
  ],
  "open_loops": [
    {{"text": "the promise made", "opened_at": "first few words where promise is made", "closed_at": "first few words where promise is fulfilled or null if not fulfilled"}}
  ],
  "chapter_boundaries": [
    {{"transition_text": "words where topic changes", "from_topic": "previous topic", "to_topic": "new topic"}}
  ],
  "key_moments": [
    {{"text": "the key statement", "type": "bold_claim|demonstration|proof|emotional_peak|call_to_action", "why_important": "one sentence"}}
  ],
  "narrative_summary": "2-3 sentence summary of the video's story arc"
}}"""

messages = [{"role": "user", "content": prompt}]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(text, return_tensors="pt").to("cuda:0")

with torch.no_grad():
    output = model.generate(
        **inputs, max_new_tokens=2000, temperature=0.3, do_sample=True,
        repetition_penalty=1.1,
    )

response = tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

# Extract JSON from response (may be wrapped in ```json blocks or thinking tags)
json_match = re.search(r'\{[\s\S]*\}', response)
if json_match:
    try:
        result = json.loads(json_match.group())
        print(json.dumps(result))
    except json.JSONDecodeError:
        print(json.dumps({"error": "Failed to parse JSON from model response", "raw": response[:500]}))
else:
    print(json.dumps({"error": "No JSON found in model response", "raw": response[:500]}))

del model, tokenizer
torch.cuda.empty_cache()
'''


def _ensure_narrative_table(db_path: Path) -> None:
    """Create the narrative_analysis table if it does not exist."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_narrative_project "
            "ON narrative_analysis(project_id)"
        )
        conn.commit()
    finally:
        conn.close()


def _get_transcript_text(db_path: Path, project_id: str) -> str:
    """Concatenate all transcript segments into timestamped text.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        Full transcript with timestamps formatted as
        "[MM:SS-MM:SS] text" per segment.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT start_ms, end_ms, text FROM transcript_segments "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return ""

    lines: list[str] = []
    for r in rows:
        start_ms = int(r["start_ms"])
        end_ms = int(r["end_ms"])
        text = str(r["text"]).strip()
        if not text:
            continue
        start_m, start_s = divmod(start_ms // 1000, 60)
        end_m, end_s = divmod(end_ms // 1000, 60)
        lines.append(f"[{start_m:02d}:{start_s:02d}-{end_m:02d}:{end_s:02d}] {text}")

    return "\n".join(lines)


def _run_qwen_subprocess(transcript_path: str) -> dict[str, object]:
    """Run Qwen3-8B in a subprocess for narrative analysis.

    Args:
        transcript_path: Path to the transcript temp file.

    Returns:
        Parsed JSON analysis from the model.

    Raises:
        RuntimeError: If the subprocess fails or returns invalid output.
    """
    import os
    import subprocess

    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"

    logger.info(
        "Starting Qwen3-8B subprocess for narrative analysis (model=%s)",
        MODEL_DIR,
    )

    proc = subprocess.run(
        ["python3", "-c", _WORKER_SCRIPT, MODEL_DIR, transcript_path],
        env=env,
        capture_output=True,
        text=True,
        timeout=580,  # Just under the 600s stage timeout
    )

    if proc.returncode != 0:
        stderr_tail = proc.stderr[-500:] if proc.stderr else ""
        raise RuntimeError(
            f"Qwen3-8B subprocess failed (exit {proc.returncode}): {stderr_tail}"
        )

    stdout = proc.stdout.strip()
    if not stdout:
        raise RuntimeError("Qwen3-8B subprocess produced no output")

    # The worker prints a single JSON line as the last output
    # Take the last non-empty line (model may print warnings to stdout)
    last_line = ""
    for line in stdout.split("\n"):
        stripped = line.strip()
        if stripped:
            last_line = stripped

    try:
        result = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Qwen3-8B subprocess returned invalid JSON: {exc}. "
            f"stdout tail: {stdout[-200:]}"
        ) from exc

    return result


def _store_analysis(
    db_path: Path,
    project_id: str,
    analysis: dict[str, object],
) -> None:
    """Store narrative analysis in the database.

    Clears any existing analysis for the project before inserting.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        analysis: Parsed JSON analysis from the model.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "DELETE FROM narrative_analysis WHERE project_id = ?",
            (project_id,),
        )
        conn.execute(
            "INSERT INTO narrative_analysis (project_id, analysis_json, model_name) "
            "VALUES (?, ?, ?)",
            (project_id, json.dumps(analysis), "Qwen3-8B"),
        )
        conn.commit()
    finally:
        conn.close()


async def run_narrative_llm(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the narrative LLM analysis pipeline stage.

    Reads the full transcript, sends it to Qwen3-8B via a subprocess
    for narrative structure analysis, and stores the result in the
    narrative_analysis table.

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
        # Check model directory exists
        model_path = Path(MODEL_DIR)
        if not model_path.exists():
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message=(
                    f"Qwen3-8B model not found at {MODEL_DIR}. "
                    "Download the model to enable narrative analysis."
                ),
            )

        # Ensure table exists
        _ensure_narrative_table(db_path)

        # Get transcript text
        transcript_text = _get_transcript_text(db_path, project_id)
        if not transcript_text:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No transcript segments found for narrative analysis",
            )

        # Write transcript to temp file for subprocess
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False,
        ) as tmp:
            tmp.write(transcript_text)
            transcript_path = tmp.name

        try:
            # Run subprocess (blocking I/O in thread)
            analysis = await asyncio.to_thread(
                _run_qwen_subprocess, transcript_path,
            )
        finally:
            Path(transcript_path).unlink(missing_ok=True)

        # Check for model errors
        if "error" in analysis:
            error_msg = str(analysis.get("error", "Unknown model error"))
            raw = str(analysis.get("raw", ""))[:200]
            logger.warning(
                "Qwen3-8B returned error: %s (raw: %s)", error_msg, raw,
            )
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message=f"Model error: {error_msg}",
            )

        # Store in database
        _store_analysis(db_path, project_id, analysis)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Count results for logging
        story_beats = len(analysis.get("story_beats", []))
        open_loops = len(analysis.get("open_loops", []))
        chapters = len(analysis.get("chapter_boundaries", []))
        key_moments = len(analysis.get("key_moments", []))

        logger.info(
            "Narrative analysis complete: %d beats, %d loops, "
            "%d chapters, %d key moments (%d ms)",
            story_beats, open_loops, chapters, key_moments, elapsed_ms,
        )

        # Provenance
        analysis_hash = sha256_string(json.dumps(analysis, sort_keys=True))
        transcript_hash = sha256_string(transcript_text)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path="transcript_segments",
                sha256=transcript_hash,
            ),
            output_info=OutputInfo(
                sha256=analysis_hash,
                record_count=1,
            ),
            model_info=ModelInfo(
                name="Qwen3-8B",
                version="qwen3-8b-hf",
                quantization="float16",
                parameters={
                    "max_new_tokens": 2000,
                    "temperature": 0.3,
                    "repetition_penalty": 1.1,
                    "story_beats": story_beats,
                    "open_loops": open_loops,
                    "chapter_boundaries": chapters,
                    "key_moments": key_moments,
                },
            ),
            execution_info=ExecutionInfo(
                duration_ms=elapsed_ms,
                gpu_device="cuda:0",
            ),
            parent_record_id=None,
            description=(
                f"Narrative analysis (Qwen3-8B): {story_beats} beats, "
                f"{open_loops} loops, {chapters} chapters, "
                f"{key_moments} key moments"
            ),
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error(
            "Narrative analysis failed after %d ms: %s", elapsed_ms, error_msg,
        )
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
