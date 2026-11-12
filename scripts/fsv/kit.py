"""Evidence recorder for Full State Verification probes (AGENTS.md).

A probe runs the real path, reads the persisted source of truth back through a
different code path, and records each boundary with before/action/after state.
This module only records; it decides nothing. The agent reads the report and the
bytes it points at. A probe's exit code is not acceptance.

    run = Run("render-paths", issue=67, claim="...", corpus="...", why_minimal="...")
    run.check("speed_plain", ok, before=..., after=...)
    run.refuses("speed_out_of_range", lambda: ..., "ValidationError")
    sys.exit(run.finish(limitations=[...]))

Evidence lands in ~/.clipcannon/evidence/fsv/<issue>/<UTC-run>-<name>/ unless
--out is given: report.json plus SHA256.json over every file in the run dir.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

REPO = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = Path.home() / ".clipcannon" / "evidence" / "fsv"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                              text=True, check=False).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def error_code(exc: BaseException) -> str:
    """The code a refusal carries: a `code` attribute, else the exception type."""
    return str(getattr(exc, "code", None) or type(exc).__name__)


class Run:
    """One probe run: a claim, its corpus, and the boundaries audited."""

    def __init__(self, name: str, *, issue: int | str, claim: str, corpus: str,
                 why_minimal: str, source_of_truth: str) -> None:
        parser = argparse.ArgumentParser(description=claim)
        parser.add_argument("--out", type=Path, default=None,
                            help="evidence dir (must not exist)")
        self.args, _ = parser.parse_known_args()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.dir = self.args.out or EVIDENCE_ROOT / str(issue) / f"{stamp}-{name}"
        self.dir.mkdir(parents=True, exist_ok=False)
        self.meta = {"probe": name, "issue": issue, "claim": claim, "corpus": corpus,
                     "minimum_sufficient_corpus": why_minimal,
                     "source_of_truth": source_of_truth, "started_utc": stamp,
                     "host": platform.node(), "git": git_state()}
        self.checks: list[dict[str, Any]] = []
        self.t0 = time.monotonic()

    def path(self, name: str) -> Path:
        return self.dir / name

    def check(self, boundary: str, ok: bool, **state: Any) -> bool:
        """Record one boundary. Put before/action/after in `state`."""
        self.checks.append({"boundary": boundary, "pass": bool(ok), **state})
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {boundary}", flush=True)
        return bool(ok)

    def refuses(self, boundary: str, fn: Callable[[], Any], code: str,
                **state: Any) -> bool:
        """Negative control: `fn` must raise (or return an error dict) with `code`."""
        got: str | None = None
        detail: Any = None
        try:
            result = fn()
            if isinstance(result, dict) and isinstance(result.get("error"), dict):
                got, detail = result["error"].get("code"), result["error"]
        except Exception as exc:  # noqa: BLE001 - the refusal IS the evidence
            got, detail = error_code(exc), str(exc)[:500]
        return self.check(boundary, got == code, expected_code=code, got_code=got,
                          detail=detail, **state)

    def finish(self, *, limitations: list[str]) -> int:
        failed = [c["boundary"] for c in self.checks if not c["pass"]]
        report = {**self.meta, "acceptance": "author-checked",
                  "seconds": round(time.monotonic() - self.t0, 3),
                  "passed": len(self.checks) - len(failed), "failed": len(failed),
                  "failed_boundaries": failed, "checks": self.checks,
                  "limitations": limitations}
        self.path("report.json").write_text(json.dumps(report, indent=1, default=str))
        hashes = {str(p.relative_to(self.dir)): sha256_file(p)
                  for p in sorted(self.dir.rglob("*")) if p.is_file()}
        self.path("SHA256.json").write_text(json.dumps(hashes, indent=1))
        print(json.dumps({"evidence": str(self.dir), "passed": report["passed"],
                          "failed": failed}), flush=True)
        return int(bool(failed))


def ffprobe(path: Path) -> dict[str, Any]:
    """Stream/format facts read straight from the container bytes."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height,duration,r_frame_rate,nb_frames:"
         "format=duration,size", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def stream(info: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(s for s in info["streams"] if s["codec_type"] == kind)


def require_tools(*names: str) -> None:
    import shutil
    missing = [n for n in names if shutil.which(n) is None]
    if missing:
        raise SystemExit(json.dumps({"ok": False, "code": "FSV_TOOL_MISSING",
                                     "message": f"not on PATH: {missing}",
                                     "remediation": "install them; no probe runs without"}))


if str(REPO / "src") not in sys.path:  # probes import the real package from src/
    sys.path.insert(0, str(REPO / "src"))
