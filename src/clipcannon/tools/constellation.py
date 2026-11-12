"""Constellation/expression MCP tool dispatch for ClipCannon.

Handles dispatch for micro-expression constellation control and
clone video generation with behavioral state management.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MODELS_DIR = Path.home() / ".clipcannon" / "models"
FLAME_PATH = Path.home() / ".clipcannon" / "models" / "{person}" / "flame_params.npz"
LORA_PATH = Path.home() / ".clipcannon" / "models" / "{person}" / "echov3_lora" / "final"
REF_IMAGE_PATH = Path.home() / ".clipcannon" / "models" / "{person}" / "reference" / "{person}_portrait.jpg"
AUDIO_REF_PATH = Path.home() / ".clipcannon" / "models" / "{person}" / "reference"

# Identity names become directory names, so keep them to a safe charset.
_PERSON_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# Generic scene description. Override per identity in clone.json.
DEFAULT_SCENE_PROMPT = (
    "Natural subtle head movements, genuine facial expressions. "
    "Clear focused eyes. Professional interview framing. Warm lighting."
)

# Cache loaded skill libraries per person
_skill_library_cache: dict[str, object] = {}


def _error(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _trained_identities() -> list[str]:
    """Identities under ~/.clipcannon/models that have FLAME params."""
    if not MODELS_DIR.is_dir():
        return []
    return sorted(
        d.name for d in MODELS_DIR.iterdir()
        if d.is_dir() and (d / "flame_params.npz").exists()
    )


def _resolve_person(arguments: dict) -> str:
    """Pick the clone identity: argument, then env var, then the only one trained.

    Raises ValueError with the available identities when it can't decide.
    """
    person = str(arguments.get("person") or os.environ.get("CLIPCANNON_CLONE_PERSON") or "")
    if not person:
        available = _trained_identities()
        if len(available) == 1:
            person = available[0]
        else:
            raise ValueError(
                "person is required (or set CLIPCANNON_CLONE_PERSON). "
                f"Trained identities found: {available or 'none'}"
            )
    if not _PERSON_RE.match(person) or ".." in person:
        raise ValueError(f"Invalid person name: {person!r}")
    return person


def _load_clone_config(person: str) -> dict:
    """Optional per-identity settings from models/<person>/clone.json.

    Keys: trigger_word (LoRA trigger token, default PERSON upper-cased),
    scene_prompt (appended to every prompt).
    """
    cfg_path = MODELS_DIR / person / "clone.json"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"{cfg_path} must contain a JSON object")
    return cfg


def _guard_check_video(person: str, video_path: str, n_frames: int = 16) -> dict:
    """Run the Teleological Constellation Guard over a generated video.

    Samples n_frames evenly, re-embeds them with frozen SigLIP, and compares
    each to the person's visual centroid. passed=True only if every sampled
    frame clears the visual threshold.
    """
    import cv2

    from phoenix.video.constellation_guard import ConstellationGuard

    embeddings_path = MODELS_DIR / person / "embeddings" / "all_embeddings.npz"
    guard = ConstellationGuard(str(embeddings_path))

    cap = cv2.VideoCapture(video_path)
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            raise RuntimeError(f"Could not read frames from {video_path}")
        n = max(1, min(n_frames, total))
        indices = sorted({int(i * (total - 1) / max(1, n - 1)) for i in range(n)})
        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, bgr = cap.read()
            if ok:
                frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    finally:
        cap.release()
    if not frames:
        raise RuntimeError(f"No frames decoded from {video_path}")

    guard.load_visual_encoder()
    try:
        results = guard.validate_batch(frames)
    finally:
        guard.unload()

    sims = [r.visual_similarity for r in results]
    rejected = sum(1 for r in results if not r.valid)
    return {
        "status": "checked",
        "passed": rejected == 0,
        "frames_checked": len(results),
        "frames_rejected": rejected,
        "visual_similarity_min": round(min(sims), 4),
        "visual_similarity_mean": round(sum(sims) / len(sims), 4),
        "visual_threshold": guard.get_constellation_stats()["thresholds"].get("visual"),
    }


def _get_skill_library(person: str):
    """Load or return cached SkillLibrary for a person."""
    if person in _skill_library_cache:
        return _skill_library_cache[person]

    from phoenix.video.expression_skills import SkillLibrary

    flame_path = str(FLAME_PATH).format(person=person)
    embeddings_path = str(MODELS_DIR / person / "embeddings" / "all_embeddings.npz")

    if not Path(flame_path).exists():
        raise FileNotFoundError(f"FLAME params not found for '{person}' at {flame_path}")
    if not Path(embeddings_path).exists():
        raise FileNotFoundError(f"Embeddings not found for '{person}' at {embeddings_path}")

    library = SkillLibrary()
    library.extract_from_training_data(embeddings_path, flame_path)
    _skill_library_cache[person] = library
    return library


async def _handle_list_constellations(arguments: dict) -> dict:
    try:
        person = _resolve_person(arguments)
    except ValueError as e:
        return _error("INVALID_PERSON", str(e))
    try:
        library = _get_skill_library(person)
        constellations = library.list_constellations()
        result = []
        for name in constellations:
            c = library.get_constellation(name)
            # skill_sequence can be strings or ExpressionSkill objects
            skills = [s if isinstance(s, str) else s.name for s in c.skill_sequence]
            result.append({
                "name": name,
                "emotion": c.emotion,
                "description": c.description,
                "skills": skills,
            })
        return {"person": person, "constellations": result, "count": len(result)}
    except Exception as e:
        return _error("CONSTELLATION_ERROR", str(e))


async def _handle_list_skills(arguments: dict) -> dict:
    try:
        person = _resolve_person(arguments)
    except ValueError as e:
        return _error("INVALID_PERSON", str(e))
    try:
        library = _get_skill_library(person)
        skills = library.list_skills()
        result = []
        for name in skills:
            skill = library.get_skill(name)
            prompt = library.skill_to_prompt(name)
            result.append({
                "name": name,
                "prompt": prompt[:100],
                "phases": len(skill.phases) if hasattr(skill, 'phases') else 0,
            })
        return {"person": person, "skills": result, "count": len(result)}
    except Exception as e:
        return _error("SKILL_ERROR", str(e))


async def _handle_generate_video(arguments: dict) -> dict:
    try:
        person = _resolve_person(arguments)
    except ValueError as e:
        return _error("INVALID_PERSON", str(e))
    audio_path = str(arguments.get("audio_path", ""))
    constellation = str(arguments.get("constellation", "warm_conversational"))
    intensity = float(arguments.get("intensity", 0.8))
    seed = int(arguments.get("seed", 42))
    output_path = str(arguments.get("output_path", ""))
    guard_enabled = bool(arguments.get("identity_guard", True))

    if not audio_path:
        return _error("MISSING_PARAMETER", "audio_path is required")
    if not Path(audio_path).exists():
        return _error("FILE_NOT_FOUND", f"Audio not found: {audio_path}")

    # Check LoRA exists
    lora_path = str(LORA_PATH).format(person=person)
    if not Path(lora_path).exists():
        return _error("MODEL_NOT_FOUND", f"LoRA not found for '{person}' at {lora_path}. Train first.")

    # Check reference image
    ref_path = str(REF_IMAGE_PATH).format(person=person)
    if not Path(ref_path).exists():
        return _error("FILE_NOT_FOUND", f"Reference image not found: {ref_path}")

    # Generate prompt from constellation
    try:
        library = _get_skill_library(person)
        from phoenix.video.constellation_controller import ConstellationController
        controller = ConstellationController(library)
        controller.set_emotional_state(constellation, intensity)
        # Get the initial prompt (the full constellation description)
        prompt = controller.get_prompt_for_frame(0)
    except Exception as e:
        return _error("CONSTELLATION_ERROR", f"Failed to build prompt: {e}")

    # Build full prompt: LoRA trigger word + constellation + scene.
    try:
        clone_cfg = _load_clone_config(person)
    except (OSError, ValueError) as e:
        return _error("CONFIG_ERROR", f"Bad clone.json for '{person}': {e}")
    trigger_word = str(
        arguments.get("trigger_word") or clone_cfg.get("trigger_word") or person.upper()
    )
    scene_prompt = str(
        arguments.get("scene_prompt") or clone_cfg.get("scene_prompt") or DEFAULT_SCENE_PROMPT
    )
    full_prompt = f"{trigger_word} {prompt} {scene_prompt}"

    # Auto output path
    if not output_path:
        demos_dir = Path.home() / ".clipcannon" / "models" / person / "demos"
        demos_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(demos_dir / f"{person}_{constellation}_{seed}.mp4")

    # Build inference command. EchoMimicV3 install dir is resolved from
    # CLIPCANNON_ECHOMIMIC_DIR (default ~/echomimic_v3); fails loud if missing.
    from clipcannon.paths import resolve_external_dir

    echomimic_dir = str(
        resolve_external_dir(
            "CLIPCANNON_ECHOMIMIC_DIR",
            Path.home() / "echomimic_v3",
            must_contain=("infer_flash.py",),
        )
    )
    cmd = [
        "python", f"{echomimic_dir}/infer_flash.py",
        "--image_path", ref_path,
        "--audio_path", audio_path,
        "--prompt", full_prompt,
        "--negative_prompt", "tears, crying, watery eyes, blurry, distorted, deformed",
        "--num_inference_steps", "8",
        "--config_path", f"{echomimic_dir}/config/config.yaml",
        "--model_name", f"{echomimic_dir}/pretrained_weights/Wan2.1-Fun-V1.1-1.3B-InP",
        "--ckpt_idx", "50000",
        "--transformer_path", f"{echomimic_dir}/pretrained_weights/echomimicv3-flash-pro/diffusion_pytorch_model.safetensors",
        "--lora_path", lora_path,
        "--save_path", str(Path(output_path).parent),
        "--wav2vec_model_dir", f"{echomimic_dir}/pretrained_weights/chinese-wav2vec2-base",
        "--sampler_name", "Flow_DPM++",
        "--video_length", "249",
        "--guidance_scale", "7.0",
        "--audio_guidance_scale", "3.5",
        "--seed", str(seed),
        "--enable_teacache",
        "--teacache_threshold", "0.1",
        "--num_skip_start_steps", "5",
        "--weight_dtype", "bfloat16",
        "--sample_size", "480", "480",
        "--fps", "25",
        "--shift", "5.0",
    ]

    env = os.environ.copy()
    env.setdefault("FFMPEG_PATH", "/usr/bin")
    env["PYTORCH_CUDA_ALLOC_CONF"] = ""
    env["PYTHONPATH"] = echomimic_dir

    logger.info("Generating %s video: constellation=%s, seed=%d", person, constellation, seed)
    t0 = time.time()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                cwd=echomimic_dir, env=env)
        elapsed = time.time() - t0

        # Find the output file (EchoMimicV3 names it based on image name)
        ref_stem = Path(ref_path).stem
        expected_output = Path(output_path).parent / f"{ref_stem}_output.mp4"

        if expected_output.exists():
            # Rename to desired output path
            if str(expected_output) != output_path:
                expected_output.rename(output_path)

            response = {
                "output_path": output_path,
                "constellation": constellation,
                "intensity": intensity,
                "duration_s": elapsed,
                "person": person,
                "seed": seed,
            }

            # Per-output identity guard: the clip must still look like this person.
            if guard_enabled:
                try:
                    guard_result = await asyncio.to_thread(_guard_check_video, person, output_path)
                except Exception as e:  # a guard that could not run is a refusal (#68)
                    logger.error("Constellation guard failed to run: %s", e)
                    return _error(
                        "IDENTITY_GUARD_UNAVAILABLE",
                        f"Identity guard could not run: {e}. The video was kept at "
                        f"{output_path} but is unverified.",
                        {**response, "remediation": "Fix the guard error and retry, or "
                         "call with the guard disabled to accept an unverified clip."},
                    )
                response["identity_guard"] = guard_result
                if guard_result.get("status") == "checked" and not guard_result["passed"]:
                    return _error(
                        "IDENTITY_GUARD_REJECTED",
                        f"{guard_result['frames_rejected']}/"
                        f"{guard_result['frames_checked']} sampled "
                        f"frames fell below the visual identity threshold. The video was kept at "
                        f"{output_path} for inspection; try another seed or lower intensity.",
                        response,
                    )
            else:
                response["identity_guard"] = {"status": "skipped", "passed": None}
            return response
        else:
            return _error("GENERATION_FAILED",
                          f"Output not found at {expected_output}",
                          {"stderr": result.stderr[-500:] if result.stderr else ""})
    except subprocess.TimeoutExpired:
        return _error("TIMEOUT", "Video generation timed out after 600s")
    except Exception as e:
        return _error("GENERATION_ERROR", str(e))


async def _handle_expression_sequence(arguments: dict) -> dict:
    try:
        person = _resolve_person(arguments)
    except ValueError as e:
        return _error("INVALID_PERSON", str(e))
    constellation = str(arguments.get("constellation", ""))
    duration_s = float(arguments.get("duration_s", 5.0))
    intensity = float(arguments.get("intensity", 0.8))
    fps = int(arguments.get("fps", 25))

    if not constellation:
        return _error("MISSING_PARAMETER", "constellation is required")

    try:
        library = _get_skill_library(person)
        from phoenix.video.constellation_controller import ConstellationController
        controller = ConstellationController(library)
        controller.set_emotional_state(constellation, intensity)
        sequence = controller.get_prompt_sequence(duration_s, fps)

        # Sample every 25 frames (1 per second) for display
        sampled = [(idx, prompt) for idx, prompt in sequence if idx % fps == 0]

        return {
            "constellation": constellation,
            "intensity": intensity,
            "total_frames": len(sequence),
            "duration_s": duration_s,
            "sample_prompts": [{"frame": idx, "time_s": idx/fps, "prompt": p} for idx, p in sampled],
        }
    except Exception as e:
        return _error("SEQUENCE_ERROR", str(e))


async def dispatch_constellation_tool(name: str, arguments: dict) -> dict:
    """Route constellation tool calls to handlers."""
    handlers = {
        "clipcannon_list_constellations": _handle_list_constellations,
        "clipcannon_list_skills": _handle_list_skills,
        "clipcannon_clone_video": _handle_generate_video,
        "clipcannon_expression_sequence": _handle_expression_sequence,
    }
    handler = handlers.get(name)
    if handler is None:
        return _error("UNKNOWN_TOOL", f"Unknown constellation tool: {name}")
    return await handler(arguments)
