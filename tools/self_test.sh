#!/bin/sh
# Thin convenience wrapper -- the real logic lives in
# tools/testing/self_test.py (a plain script, not a `dv-harness` subcommand;
# see that file's own docstring and .work/harness-self-test-ci-report.md for
# why). Runnable by a developer or a scheduled task with no GitHub Actions
# runner involved: `sh tools/self_test.sh` from the repo root, or
# `tools/self_test.sh` directly once marked executable. Confirmed sh.exe
# (Git for Windows) is present on this machine, same as justfile's own
# `set windows-shell` note.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
exec python "$REPO_ROOT/tools/testing/self_test.py" "$@"
