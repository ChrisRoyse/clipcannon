"""Tests for the clone/constellation MCP tools: identity resolution,
per-identity prompt config, and the per-output identity guard."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import types

import pytest

from clipcannon.tools import constellation as ct


@pytest.fixture()
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "MODELS_DIR", tmp_path)
    monkeypatch.delenv("CLIPCANNON_CLONE_PERSON", raising=False)
    return tmp_path


def _make_identity(models_dir, name):
    d = models_dir / name
    d.mkdir()
    (d / "flame_params.npz").write_bytes(b"")
    return d


# --- identity resolution ---------------------------------------------------

def test_explicit_person_wins(models_dir):
    _make_identity(models_dir, "alice")
    assert ct._resolve_person({"person": "bob"}) == "bob"


def test_env_var_used_when_no_argument(models_dir, monkeypatch):
    monkeypatch.setenv("CLIPCANNON_CLONE_PERSON", "carol")
    assert ct._resolve_person({}) == "carol"


def test_single_trained_identity_is_default(models_dir):
    _make_identity(models_dir, "alice")
    (models_dir / "not_a_clone").mkdir()  # no flame_params -> ignored
    assert ct._resolve_person({}) == "alice"


def test_ambiguous_identity_fails_loud(models_dir):
    _make_identity(models_dir, "alice")
    _make_identity(models_dir, "bob")
    with pytest.raises(ValueError, match="alice.*bob"):
        ct._resolve_person({})


@pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "a b", "-x", ""])
def test_unsafe_person_names_rejected(models_dir, bad):
    _make_identity(models_dir, "a1")
    _make_identity(models_dir, "a2")  # so "" can't fall back to a sole identity
    with pytest.raises(ValueError):
        ct._resolve_person({"person": bad})


def test_handler_returns_error_instead_of_raising(models_dir):
    out = asyncio.run(ct._handle_list_skills({"person": "../x"}))
    assert out["error"]["code"] == "INVALID_PERSON"


# --- clone.json ------------------------------------------------------------

def test_clone_config_optional(models_dir):
    _make_identity(models_dir, "alice")
    assert ct._load_clone_config("alice") == {}


def test_clone_config_loaded(models_dir):
    d = _make_identity(models_dir, "alice")
    (d / "clone.json").write_text(json.dumps({"trigger_word": "ALC", "scene_prompt": "Studio."}))
    assert ct._load_clone_config("alice")["trigger_word"] == "ALC"


# --- clone_video prompt + guard -------------------------------------------

@pytest.fixture()
def clone_env(models_dir, tmp_path, monkeypatch):
    """A fake trained identity, fake EchoMimic, fake skill library."""
    person_dir = _make_identity(models_dir, "alice")
    (person_dir / "echov3_lora" / "final").mkdir(parents=True)
    (person_dir / "reference").mkdir()
    ref = person_dir / "reference" / "alice_portrait.jpg"
    ref.write_bytes(b"jpg")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"wav")

    monkeypatch.setattr(ct, "LORA_PATH", models_dir / "{person}" / "echov3_lora" / "final")
    monkeypatch.setattr(ct, "REF_IMAGE_PATH", models_dir / "{person}" / "reference" / "{person}_portrait.jpg")
    monkeypatch.setattr(ct, "_get_skill_library", lambda person: object())

    class FakeController:
        def __init__(self, lib): pass
        def set_emotional_state(self, c, i): pass
        def get_prompt_for_frame(self, i): return "warm smile."

    fake_mod = types.ModuleType("phoenix.video.constellation_controller")
    fake_mod.ConstellationController = FakeController
    monkeypatch.setitem(sys.modules, "phoenix.video.constellation_controller", fake_mod)

    import clipcannon.paths as paths
    monkeypatch.setattr(paths, "resolve_external_dir", lambda *a, **k: tmp_path)

    calls = {}

    def fake_run(cmd, **kw):
        calls["prompt"] = cmd[cmd.index("--prompt") + 1]
        save = cmd[cmd.index("--save_path") + 1]
        (ct.Path(save) / "alice_portrait_output.mp4").write_bytes(b"mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ct.subprocess, "run", fake_run)
    return {"audio": str(audio), "calls": calls, "out": str(tmp_path / "out.mp4"), "dir": person_dir}


def _clone(env, **extra):
    args = {"audio_path": env["audio"], "output_path": env["out"], **extra}
    return asyncio.run(ct._handle_generate_video(args))


def test_prompt_uses_person_not_hardcoded_identity(clone_env, monkeypatch):
    monkeypatch.setattr(ct, "_guard_check_video", lambda p, v: {"status": "checked", "passed": True})
    out = _clone(clone_env)
    assert out["person"] == "alice"
    prompt = clone_env["calls"]["prompt"]
    assert prompt.startswith("ALICE warm smile.")
    assert "SANTA" not in prompt and "Wood paneling" not in prompt


def test_prompt_honours_clone_json(clone_env, monkeypatch):
    monkeypatch.setattr(ct, "_guard_check_video", lambda p, v: {"status": "checked", "passed": True})
    (clone_env["dir"] / "clone.json").write_text(
        json.dumps({"trigger_word": "SANTA", "scene_prompt": "Wood paneling background."}))
    _clone(clone_env)
    assert clone_env["calls"]["prompt"] == "SANTA warm smile. Wood paneling background."


def test_guard_pass_is_reported(clone_env, monkeypatch):
    monkeypatch.setattr(ct, "_guard_check_video",
                        lambda p, v: {"status": "checked", "passed": True, "frames_checked": 16})
    out = _clone(clone_env)
    assert out["identity_guard"]["passed"] is True


def test_guard_rejection_returns_error_and_keeps_video(clone_env, monkeypatch):
    monkeypatch.setattr(ct, "_guard_check_video", lambda p, v: {
        "status": "checked", "passed": False, "frames_checked": 16, "frames_rejected": 3})
    out = _clone(clone_env)
    assert out["error"]["code"] == "IDENTITY_GUARD_REJECTED"
    assert out["error"]["details"]["output_path"] == clone_env["out"]
    assert ct.Path(clone_env["out"]).exists()


def test_guard_that_cannot_run_is_reported_not_hidden(clone_env, monkeypatch):
    def boom(p, v):
        raise RuntimeError("SigLIP not cached")
    monkeypatch.setattr(ct, "_guard_check_video", boom)
    out = _clone(clone_env)
    assert out["identity_guard"] == {"status": "error", "passed": False, "error": "SigLIP not cached"}


def test_guard_can_be_skipped(clone_env, monkeypatch):
    def never(p, v):
        raise AssertionError("guard should not run")
    monkeypatch.setattr(ct, "_guard_check_video", never)
    out = _clone(clone_env, identity_guard=False)
    assert out["identity_guard"]["status"] == "skipped"
