#!/usr/bin/env bash
# Point this checkout at the tracked hooks in .githooks/ and read the setting back.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
chmod +x .githooks/pre-commit .githooks/pre-push
git config core.hooksPath .githooks
actual="$(git config --get core.hooksPath)"
if [[ "$actual" != ".githooks" ]]; then
  printf '{"ok":false,"code":"CLIPCANNON_HOOKS_NOT_INSTALLED","message":"core.hooksPath is %s"}\n' "$actual" >&2
  exit 1
fi
printf '{"ok":true,"core.hooksPath":"%s"}\n' "$actual"
