"""LLM-driven MIDI planning via Qwen3-8B.

Translates natural language music descriptions into structured MIDI
parameters. Uses Qwen3-8B via subprocess (matching the pattern in
``pipeline.narrative_llm``) with a keyword-based fallback.

Example:
    plan = plan_midi_from_keywords("calm ambient background music")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MODEL_DIR = (
    "/home/cabdru/.clipcannon/models/qwen3-8b-hf/"
    "models--Qwen--Qwen3-8B/snapshots/"
    "b968826d9c46dd6066d109eabc6255188de91218"
)


@dataclass
class MidiSection:
    """A single section within a composition plan."""
    name: str
    bars: int
    dynamics: tuple[int, int]


@dataclass
class MidiPlan:
    """Structured MIDI parameters derived from a description."""
    tempo_bpm: int
    key: str
    time_sig: tuple[int, int]
    preset: str
    energy: str  # low, medium, high
    sections: list[MidiSection] = field(default_factory=list)


# Keyword -> (presets, tempo_range, energy, key)
# Specific multi-word matches first, then broader single-word matches.
_KW: list[tuple[list[str], list[str], tuple[int, int], str, str]] = [
    (["lofi", "lo-fi", "lo fi"], ["lofi_chill"], (60, 80), "low", "C"),
    (["cinematic epic", "epic cinematic", "cinematic_epic"], ["cinematic_epic"], (95, 125), "high", "C"),
    (["inspiring", "inspirational", "uplifting"], ["cinematic_epic"], (100, 130), "high", "C"),
    (["calm", "ambient", "relaxing"], ["ambient_pad"], (60, 80), "low", "C"),
    (["chill", "mellow"], ["lofi_chill"], (60, 80), "low", "C"),
    (["upbeat", "happy", "energetic", "pop"], ["upbeat_pop"], (120, 140), "high", "C"),
    (["corporate", "professional", "business"], ["corporate", "tech_corporate"], (90, 110), "medium", "C"),
    (["epic", "cinematic"], ["cinematic_epic"], (95, 125), "high", "C"),
    (["dramatic", "intense", "tension"], ["dramatic"], (90, 120), "high", "C"),
    (["piano", "minimal", "simple"], ["minimal_piano"], (70, 90), "low", "C"),
    (["jazz", "smooth", "cool"], ["jazz_smooth"], (100, 120), "medium", "C"),
    (["folk", "acoustic"], ["acoustic_folk"], (90, 110), "medium", "G"),
    (["synth", "electronic", "wave"], ["synth_wave"], (110, 130), "high", "F"),
]


def _default_sections(energy: str) -> list[MidiSection]:
    """Generate default sections based on energy level."""
    S = MidiSection
    if energy == "low":
        return [S("intro", 4, (30, 50)), S("verse", 8, (40, 65)),
                S("chorus", 8, (50, 70)), S("outro", 4, (30, 50))]
    if energy == "high":
        return [S("intro", 4, (50, 75)), S("verse", 8, (65, 90)),
                S("chorus", 8, (80, 110)), S("bridge", 4, (60, 85)),
                S("outro", 4, (50, 75))]
    return [S("intro", 4, (40, 60)), S("verse", 8, (55, 75)),
            S("chorus", 8, (65, 85)), S("outro", 4, (40, 60))]


def plan_midi_from_keywords(description: str) -> MidiPlan:
    """Map keywords in a description to structured MIDI parameters.

    Args:
        description: Natural language music description.

    Returns:
        A fully populated ``MidiPlan``.
    """
    desc_lower = description.lower()
    presets, tempo_range, energy, key = ["corporate"], (95, 105), "medium", "C"
    for kws, p, tr, e, k in _KW:
        if any(kw in desc_lower for kw in kws):
            presets, tempo_range, energy, key = p, tr, e, k
            break

    preset = presets[0]
    tempo = (tempo_range[0] + tempo_range[1]) // 2
    sections = _default_sections(energy)

    logger.info(
        "Keyword MIDI plan: preset=%s, tempo=%d, key=%s, energy=%s, "
        "sections=%d (desc='%s')",
        preset, tempo, key, energy, len(sections), description[:80],
    )
    return MidiPlan(tempo, key, (4, 4), preset, energy, sections)


# LLM worker script (Qwen3-8B subprocess)
_WORKER_SCRIPT = r'''
import json, sys, os, re
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
MODEL_DIR, prompt_path = sys.argv[1], sys.argv[2]
with open(prompt_path, "r") as f:
    user_prompt = f.read()
tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_DIR, torch_dtype=torch.float16, device_map="cuda:0", local_files_only=True)
messages = [{"role": "user", "content": user_prompt}]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(text, return_tensors="pt").to("cuda:0")
with torch.no_grad():
    output = model.generate(**inputs, max_new_tokens=600, temperature=0.3,
                            do_sample=True, repetition_penalty=1.1)
response = tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
json_match = re.search(r'\{[\s\S]*\}', response)
if json_match:
    try:
        print(json.dumps(json.loads(json_match.group())))
    except json.JSONDecodeError:
        print(json.dumps({"error": "JSON parse failed", "raw": response[:500]}))
else:
    print(json.dumps({"error": "No JSON in response", "raw": response[:500]}))
del model, tokenizer
torch.cuda.empty_cache()
'''

_ALL_PRESETS = (
    "ambient_pad, upbeat_pop, corporate, dramatic, minimal_piano, "
    "intro_jingle, lofi_chill, cinematic_epic, tech_corporate, "
    "acoustic_folk, synth_wave, jazz_smooth"
)


def _build_llm_prompt(description: str) -> str:
    """Build the prompt sent to Qwen3-8B for MIDI planning."""
    return (
        "You are a music composition planner. Output ONLY valid JSON.\n\n"
        f"DESCRIPTION: {description}\n\n"
        "Return this exact JSON structure:\n"
        '{"tempo_bpm": <int 60-160>, "key": "<note>", '
        f'"preset": "<one of: {_ALL_PRESETS}>", '
        '"energy": "<low|medium|high>", '
        '"sections": [{"name": "<name>", "bars": <int>, '
        '"dynamics": [<vel_min>, <vel_max>]}]}'
    )


def _parse_llm_response(raw: dict[str, object]) -> MidiPlan:
    """Parse and validate LLM JSON response into a MidiPlan."""
    if "error" in raw:
        raise ValueError(f"LLM returned error: {raw['error']}")

    tempo = int(raw.get("tempo_bpm", 0))
    if not 30 <= tempo <= 300:
        raise ValueError(f"Invalid tempo_bpm: {tempo}")

    key = str(raw.get("key", "C"))
    preset = str(raw.get("preset", "corporate"))
    energy = str(raw.get("energy", "medium"))
    if energy not in ("low", "medium", "high"):
        energy = "medium"

    sections: list[MidiSection] = []
    for s in (raw.get("sections") or []):
        if not isinstance(s, dict):
            continue
        dyn = s.get("dynamics", [50, 80])
        dynamics = (int(dyn[0]), int(dyn[1])) if isinstance(dyn, (list, tuple)) and len(dyn) >= 2 else (50, 80)
        sections.append(MidiSection(str(s.get("name", "verse")), int(s.get("bars", 4)), dynamics))

    if not sections:
        sections = _default_sections(energy)
    return MidiPlan(tempo, key, (4, 4), preset, energy, sections)


async def plan_midi_from_prompt(description: str) -> MidiPlan:
    """Translate a natural language description into a MidiPlan via LLM.

    Calls Qwen3-8B in a subprocess. Falls back to keyword heuristics
    if the LLM is unavailable or returns invalid output.

    Args:
        description: Natural language music description.

    Returns:
        A fully populated ``MidiPlan``.
    """
    if not os.path.isdir(MODEL_DIR):
        logger.warning("Qwen3-8B not found at %s; keyword fallback", MODEL_DIR)
        return plan_midi_from_keywords(description)

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write(_build_llm_prompt(description))
            prompt_path = tmp.name

        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"

        logger.info("Starting Qwen3-8B subprocess for MIDI planning")
        proc = await asyncio.to_thread(
            lambda: subprocess.run(
                ["python3", "-c", _WORKER_SCRIPT, MODEL_DIR, prompt_path],
                env=env, capture_output=True, text=True, timeout=300,
            )
        )
        os.unlink(prompt_path)

        if proc.returncode != 0:
            logger.warning("Qwen3-8B failed (exit %d); keyword fallback", proc.returncode)
            return plan_midi_from_keywords(description)

        stdout = proc.stdout.strip()
        if not stdout:
            logger.warning("Qwen3-8B empty output; keyword fallback")
            return plan_midi_from_keywords(description)

        # Take last non-empty line (model may print warnings)
        last_line = [ln.strip() for ln in stdout.split("\n") if ln.strip()][-1]
        plan = _parse_llm_response(json.loads(last_line))

        logger.info(
            "LLM MIDI plan: preset=%s, tempo=%d, key=%s, energy=%s, sections=%d",
            plan.preset, plan.tempo_bpm, plan.key, plan.energy, len(plan.sections),
        )
        return plan

    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("LLM parse failed (%s); keyword fallback", exc)
        return plan_midi_from_keywords(description)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("LLM subprocess error (%s); keyword fallback", exc)
        return plan_midi_from_keywords(description)
