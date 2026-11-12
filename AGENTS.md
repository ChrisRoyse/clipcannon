# ClipCannon repository operating boundary

ClipCannon is one of the Royse proven systems (multi-instrument video understanding, the
N=7 constellation). Theory comes only from the Royse corpus (*The Calculus of
Association*, *Bits of Grounded Information*, the Oracle and Kernel papers). This file is
binding; the long form is pinned GitHub issue #65 (Doctrine) and current state is pinned
issue #66 (Context). It inherits the engineering doctrine of `ChrisRoyse/Poly` #1,
`ChrisRoyse/MNLM` #1 and Calyx `DOCTRINE.md`.

- The only source repository and issue tracker is `ChrisRoyse/clipcannon`. Work from
  the WSL checkout `~/clipcannon` on `main`. State lives in GitHub issues: read the
  Doctrine and Context issues before work, claim the owning issue, and close it only with
  physical FSV evidence in a comment. Tracked markdown does not grow: replace text; status
  goes in the owning issue, never in `docs/` or the README.
- Execution host: this workstation (WSL Ubuntu 26.04, RTX 5090 sm_120, CUDA 13.x torch).
  Source of truth per project: `~/.clipcannon/projects/<project_id>/analysis.db` plus the
  bytes under that project dir (source, stems, frames, renders). FSV evidence:
  `~/.clipcannon/evidence/fsv/<issue>/<run>/` with `report.json` and `SHA256.json`.
- **No tests, no CI/CD, ever.** No pytest suites, no test harnesses, no GitHub Actions,
  no hosted runners. Full State Verification replaces them. `ruff check` and
  `python -m compileall` are supporting gates only, never acceptance.
- **Full State Verification** means: name the persisted source of truth, execute the
  real path (MCP tool, pipeline stage, real FFmpeg render), independently read that state
  back through a different code path (sqlite3, ffprobe, decoded frames, file hashes), and
  audit at least three meaningful boundaries with before/action/after evidence and
  negative controls (bad input refused with its error code and no state mutated). Choose
  the minimum sufficient proof corpus first and say why smaller would not prove the claim
  and larger would be waste. Probes live in `scripts/fsv/` and use `scripts/fsv/kit.py`;
  a probe is evidence the agent reads, not a green checkmark. Say **author-checked** for
  your own readback. Return values and probe exit codes alone are never acceptance.
- Every number in an issue, commit, README or report is **measured** (read back from
  persisted bytes, with an evidence pointer) or **projected** (formula and inputs). A
  projection never becomes a result by repetition. Report failures honestly; negative
  results are results.
- **Fail closed** with `{code, message, remediation}`: an MCP tool returns
  `{"error": {...}}` (the server marks it `isError`), a stage raises with a code. No
  fallback success, no mock data, no silent CPU fallback of a GPU model, no
  degraded-substitute path (e.g. text search standing in for semantic search, centre crop
  standing in for requested speaker tracking), no runtime model downloads, no workaround
  that hides broken state. Broad `except Exception` is allowed only to attach a code and
  re-raise or return the typed error, never to continue as if it worked.
- **Pipeline cost is a correctness property** (PC-nn catalogue, `ChrisRoyse/Poly` #1148).
  Before adding, extending or wiring a stage, state its cost function against real N
  (source minutes, frames at the sampling fps, segments, faces) and name what is
  invariant across the loop. `unknown N` is a tracked gap, a guess is not. Never raise a
  stage timeout, budget or lease to make it pass; prove the GPU/CPU bottleneck before adding
  concurrency; never delete a fail-closed verification to go faster (memoize, hoist,
  narrow). Cite `PC-nn` in the issue and the commit.
- **Instruments.** Embed what is latent, encode what is explicit: numbers, timestamps,
  categories and ids get deterministic encoders, never a learned embedder. No-flatten:
  per-instrument slots stay typed and separate end to end. Every model is frozen and
  pinned (revision or sha256); a different runtime or precision is a different instrument.
  An instrument earns its place by measured grounded bits, not by being added.
- **Real data first.** A source, model or API counts only after real bytes were pulled
  through the real path, persisted and read back. Schemas come from received bytes.
- **Code structure.** Every `.py .sh .js .ts .ps1` file under 500 lines (pre-commit hook);
  single responsibility per module; explicit re-exports, never wildcard; no circular
  imports. Over-limit file found: open an issue and split it.
- **Process hygiene.** Stop only PIDs you launched and recorded; never a name-based sweep
  (`pkill -f python`). GPU: check `nvidia-smi` before a GPU job; one heavy GPU job at a time.
- **Secrets** never enter the repo, an issue, a log or a report: names only (`HF_TOKEN`,
  `HUGGINGFACE_TOKEN`). The pre-commit hook refuses key material and token patterns. Never commit
  `.env`. Install the guards once per checkout: `bash scripts/install_git_guards.sh`.
