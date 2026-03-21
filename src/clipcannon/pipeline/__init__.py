"""Pipeline orchestration and stage definitions for ClipCannon.

Public API:
    - PipelineOrchestrator: DAG-based pipeline runner
    - PipelineStage: Stage definition dataclass
    - StageResult: Result from a single stage
    - PipelineResult: Aggregate result from a full pipeline run
    - Stage run functions: run_probe, run_vfr_normalize, run_audio_extract,
      run_source_separation, run_frame_extract, run_transcribe,
      run_visual_embed, run_ocr, run_quality, run_shot_type, run_storyboard
    - Source resolution: resolve_source_path, resolve_audio_input
"""

from clipcannon.pipeline.audio_extract import run_audio_extract
from clipcannon.pipeline.frame_extract import run_frame_extract
from clipcannon.pipeline.ocr import run_ocr
from clipcannon.pipeline.orchestrator import (
    PipelineOrchestrator,
    PipelineResult,
    PipelineStage,
    StageResult,
)
from clipcannon.pipeline.probe import run_probe
from clipcannon.pipeline.quality import run_quality
from clipcannon.pipeline.shot_type import run_shot_type
from clipcannon.pipeline.source_resolution import (
    resolve_audio_input,
    resolve_source_path,
)
from clipcannon.pipeline.source_separation import run_source_separation
from clipcannon.pipeline.storyboard import run_storyboard
from clipcannon.pipeline.transcribe import run_transcribe
from clipcannon.pipeline.vfr_normalize import run_vfr_normalize
from clipcannon.pipeline.visual_embed import run_visual_embed

__all__ = [
    "PipelineOrchestrator",
    "PipelineResult",
    "PipelineStage",
    "StageResult",
    "resolve_audio_input",
    "resolve_source_path",
    "run_audio_extract",
    "run_frame_extract",
    "run_ocr",
    "run_probe",
    "run_quality",
    "run_shot_type",
    "run_source_separation",
    "run_storyboard",
    "run_transcribe",
    "run_vfr_normalize",
    "run_visual_embed",
]
