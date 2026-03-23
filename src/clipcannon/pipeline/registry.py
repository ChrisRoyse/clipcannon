"""Pipeline stage registry for ClipCannon.

Builds and registers all pipeline stages with correct DAG dependencies
so the orchestrator can resolve execution order via topological sort.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipcannon.pipeline.acoustic import run_acoustic
from clipcannon.pipeline.audio_extract import run_audio_extract
from clipcannon.pipeline.chronemic import run_chronemic
from clipcannon.pipeline.emotion_embed import run_emotion_embed
from clipcannon.pipeline.finalize import run_finalize
from clipcannon.pipeline.frame_extract import run_frame_extract
from clipcannon.pipeline.highlights import run_highlights
from clipcannon.pipeline.ocr import run_ocr
from clipcannon.pipeline.orchestrator import PipelineOrchestrator, PipelineStage
from clipcannon.pipeline.probe import run_probe
from clipcannon.pipeline.profanity import run_profanity
from clipcannon.pipeline.quality import run_quality
from clipcannon.pipeline.reactions import run_reactions
from clipcannon.pipeline.scene_analysis import run_scene_analysis
from clipcannon.pipeline.semantic_embed import run_semantic_embed
from clipcannon.pipeline.shot_type import run_shot_type
from clipcannon.pipeline.source_separation import run_source_separation
from clipcannon.pipeline.speaker_embed import run_speaker_embed
from clipcannon.pipeline.storyboard import run_storyboard
from clipcannon.pipeline.transcribe import run_transcribe
from clipcannon.pipeline.vfr_normalize import run_vfr_normalize
from clipcannon.pipeline.visual_embed import run_visual_embed

if TYPE_CHECKING:
    from clipcannon.config import ClipCannonConfig

# Stage definitions with DAG dependencies.
# Level 0 (no deps): probe
# Level 1: vfr_normalize -> depends on probe
# Level 2: audio_extract, frame_extract -> depend on vfr_normalize
# Level 3: source_separation -> audio_extract
#           visual_embed, ocr, quality, storyboard -> frame_extract
#           transcribe -> audio_extract
# Level 4: shot_type -> frame_extract, visual_embed (needs scenes table)
#           scene_analysis -> frame_extract, transcribe
#           semantic_embed, speaker_embed -> transcribe
#           emotion_embed, reactions, acoustic -> audio_extract
# Level 5: profanity -> transcribe
#           chronemic -> transcribe, speaker_embed
# Level 6: highlights -> emotion, reactions, semantic, visual, quality,
#                         speaker, chronemic
# Level 7: finalize -> all

_STAGES: list[PipelineStage] = [
    PipelineStage(
        name="probe", operation="probe", required=True,
        depends_on=[], run=run_probe, timeout_s=120,
    ),
    PipelineStage(
        name="vfr_normalize", operation="vfr_normalize", required=True,
        depends_on=["probe"], run=run_vfr_normalize, timeout_s=1800,
    ),
    PipelineStage(
        name="audio_extract", operation="audio_extract", required=True,
        depends_on=["vfr_normalize"], run=run_audio_extract, timeout_s=300,
    ),
    PipelineStage(
        name="frame_extract", operation="frame_extract", required=True,
        depends_on=["vfr_normalize"], run=run_frame_extract, timeout_s=600,
    ),
    PipelineStage(
        name="source_separation", operation="source_separation", required=False,
        depends_on=["audio_extract"], run=run_source_separation, timeout_s=600,
    ),
    PipelineStage(
        name="visual_embed", operation="visual_embedding", required=False,
        depends_on=["frame_extract"], run=run_visual_embed, timeout_s=600,
    ),
    PipelineStage(
        name="ocr", operation="ocr_extraction", required=False,
        depends_on=["frame_extract"], run=run_ocr, timeout_s=600,
    ),
    PipelineStage(
        name="quality", operation="quality_assessment", required=False,
        depends_on=["frame_extract"], run=run_quality, timeout_s=600,
    ),
    PipelineStage(
        name="shot_type", operation="shot_type_classification", required=False,
        depends_on=["frame_extract", "visual_embed"], run=run_shot_type, timeout_s=300,
    ),
    PipelineStage(
        name="transcribe", operation="transcription", required=True,
        depends_on=["audio_extract"], run=run_transcribe, timeout_s=600,
    ),
    PipelineStage(
        name="storyboard", operation="storyboard_generation", required=False,
        depends_on=["frame_extract"], run=run_storyboard, timeout_s=300,
    ),
    PipelineStage(
        name="scene_analysis", operation="scene_analysis", required=False,
        depends_on=["frame_extract", "transcribe"], run=run_scene_analysis, timeout_s=300,
    ),
    PipelineStage(
        name="semantic_embed", operation="semantic_embedding", required=False,
        depends_on=["transcribe"], run=run_semantic_embed, timeout_s=300,
    ),
    PipelineStage(
        name="speaker_embed", operation="speaker_diarization", required=False,
        depends_on=["audio_extract", "transcribe"], run=run_speaker_embed, timeout_s=300,
    ),
    PipelineStage(
        name="emotion_embed", operation="emotion_analysis", required=False,
        depends_on=["audio_extract"], run=run_emotion_embed, timeout_s=300,
    ),
    PipelineStage(
        name="reactions", operation="reaction_detection", required=False,
        depends_on=["audio_extract"], run=run_reactions, timeout_s=300,
    ),
    PipelineStage(
        name="acoustic", operation="acoustic_analysis", required=False,
        depends_on=["audio_extract"], run=run_acoustic, timeout_s=300,
    ),
    PipelineStage(
        name="profanity", operation="profanity_detection", required=False,
        depends_on=["transcribe"], run=run_profanity, timeout_s=120,
    ),
    PipelineStage(
        name="chronemic", operation="chronemic_analysis", required=False,
        depends_on=["transcribe", "speaker_embed"], run=run_chronemic, timeout_s=120,
    ),
    PipelineStage(
        name="highlights", operation="highlight_scoring", required=False,
        depends_on=[
            "emotion_embed", "reactions", "semantic_embed",
            "visual_embed", "quality", "speaker_embed", "chronemic",
        ],
        run=run_highlights, timeout_s=120,
    ),
    PipelineStage(
        name="finalize", operation="finalize", required=True,
        depends_on=[
            "transcribe", "visual_embed", "ocr", "quality",
            "shot_type", "storyboard", "semantic_embed", "speaker_embed",
            "emotion_embed", "reactions", "acoustic", "profanity",
            "chronemic", "highlights",
        ],
        run=run_finalize, timeout_s=120,
    ),
]


def build_pipeline(config: ClipCannonConfig) -> PipelineOrchestrator:
    """Build a PipelineOrchestrator with all stages registered.

    Registers every pipeline stage in the correct DAG dependency order
    so the orchestrator can resolve and execute them.

    Args:
        config: ClipCannon configuration instance.

    Returns:
        Fully configured PipelineOrchestrator.
    """
    orchestrator = PipelineOrchestrator(config)
    for stage in _STAGES:
        orchestrator.register_stage(stage)
    return orchestrator
