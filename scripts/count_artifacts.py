#!/usr/bin/env python3
"""Authoritative counts of ClipCannon's tools, pipeline stages, and instruments.

Single source of truth for the numbers quoted in README / whitepaper (GitHub
issue #62). Run it; the docs must match its output. The FSV test
``tests/test_doc_counts_fsv.py`` enforces that they stay in sync.

Usage:
    python scripts/count_artifacts.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def tool_counts() -> tuple[int, dict[str, int]]:
    """Introspect the live MCP tool registry."""
    from clipcannon.tools import (  # noqa: PLC0415
        ALL_TOOL_DEFINITIONS,
        AUDIO_TOOL_DEFINITIONS,
        AVATAR_TOOL_DEFINITIONS,
        CONFIG_TOOL_DEFINITIONS,
        CONSTELLATION_TOOL_DEFINITIONS,
        DISCOVERY_TOOL_DEFINITIONS,
        DISK_TOOL_DEFINITIONS,
        EDITING_TOOL_DEFINITIONS,
        GENERATE_TOOL_DEFINITIONS,
        PROJECT_TOOL_DEFINITIONS,
        PROVENANCE_TOOL_DEFINITIONS,
        RENDERING_TOOL_DEFINITIONS,
        UNDERSTANDING_TOOL_DEFINITIONS,
        VOICE_TOOL_DEFINITIONS,
    )

    cats = {
        "Project": len(PROJECT_TOOL_DEFINITIONS),
        "Understanding": len(UNDERSTANDING_TOOL_DEFINITIONS),
        "Discovery": len(DISCOVERY_TOOL_DEFINITIONS),
        "Editing": len(EDITING_TOOL_DEFINITIONS),
        "Rendering": len(RENDERING_TOOL_DEFINITIONS),
        "Audio": len(AUDIO_TOOL_DEFINITIONS),
        "Voice": len(VOICE_TOOL_DEFINITIONS),
        "Avatar": len(AVATAR_TOOL_DEFINITIONS),
        "Video generation": len(GENERATE_TOOL_DEFINITIONS),
        "Constellation": len(CONSTELLATION_TOOL_DEFINITIONS),
        "Disk": len(DISK_TOOL_DEFINITIONS),
        "Config": len(CONFIG_TOOL_DEFINITIONS),
        "Provenance (internal)": len(PROVENANCE_TOOL_DEFINITIONS),
    }
    return len(ALL_TOOL_DEFINITIONS), cats


def stage_count() -> tuple[int, list[str]]:
    """AST-count the pipeline `_STAGES` registry (avoids importing cv2/torch)."""
    src = (ROOT / "src/clipcannon/pipeline/registry.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == "_STAGES"
            and isinstance(node.value, ast.List)
        ):
            names = []
            for el in node.value.elts:
                if isinstance(el, ast.Call):
                    nm = None
                    for kw in el.keywords:
                        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                            nm = kw.value.value
                    if nm is None and el.args and isinstance(el.args[0], ast.Constant):
                        nm = el.args[0].value
                    names.append(nm)
            return len(names), names
    raise RuntimeError("_STAGES not found in pipeline/registry.py")


# The frozen-embedder instrument panel (architecture; see the Calculus-of-
# Association paper, N=7). 5 of these are persisted as sqlite-vec KNN spaces;
# voice-identity (ECAPA) lives in the separate voice_profiles DB.
INSTRUMENTS = [
    ("visual", "SigLIP-SO400M", 1152, "vec_frames"),
    ("semantic", "Nomic-embed-v1.5", 768, "vec_semantic"),
    ("emotion", "wav2vec2-MSP-dim", 1024, "vec_emotion"),
    ("speaker", "WavLM", 512, "vec_speakers"),
    ("prosody", "custom F0/energy/rate", 12, "prosody_segments"),
    ("sentiment", "MiniLM-L6", 384, "(narrative)"),
    ("voice", "ECAPA-TDNN", 192, "voice_profiles.db"),
]


def main() -> dict:
    n_tools, cats = tool_counts()
    n_stages, stage_names = stage_count()
    counts = {"tools": n_tools, "stages": n_stages, "instruments": len(INSTRUMENTS)}
    print(f"TOOLS:        {n_tools}")
    for name, n in cats.items():
        print(f"    {name:24s} {n}")
    print(f"STAGES:       {n_stages}")
    print(f"    {stage_names}")
    print(f"INSTRUMENTS:  {len(INSTRUMENTS)} (panel N; 5 persisted as sqlite-vec spaces)")
    for key, model, dim, store in INSTRUMENTS:
        print(f"    {key:10s} {model:22s} {dim:>5}d  -> {store}")
    return counts


if __name__ == "__main__":
    main()
