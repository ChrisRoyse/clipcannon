@AGENTS.md

Read `AGENTS.md` above first; it is the binding operating boundary. Then read pinned issues #65 (Doctrine)
and #66 (Context) in `ChrisRoyse/clipcannon` before doing work.

- Verification is Full State Verification with probes in `scripts/fsv/`; there is no
  test suite and no CI. Do not add either.
- Run the guards once per checkout: `bash scripts/install_git_guards.sh`.
- Python for the server and ML stages: `~/clipcannon/.venv/bin/python`.
- Never commit secrets, credentials or `.env` files.
