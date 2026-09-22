#!/usr/bin/env python3
"""CLI helper: resolve the current execution profile and print it as
NAME=VALUE lines for replay.ps1 (or any other shell launcher) to set into
its own environment before invoking remote_relay.py.

This is the ONLY place that reads/validates execution-profile JSON on the
replay.ps1 path -- it is a thin wrapper over the real, tested
dv_harness.execution_profile module, never a second implementation of its
required/forbidden-field checks. Never touches VCPW.

Exit code 0: one NAME=VALUE line per resolved env-var override on stdout.
Exit code 1: a single `ERROR: ...` line on stderr (starting with the
condition code, e.g. `ERROR: EXECUTION_PROFILE_REQUIRED: ...` or
`ERROR: WRONG_L5_REPOSITORY: ...`) -- the caller must fail closed on a
non-zero exit and must not parse stdout in that case.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dv_harness import execution_profile as ep  # noqa: E402
from dv_harness import l5dgva_repo  # noqa: E402


def main() -> int:
    try:
        repo_root = l5dgva_repo.discover_repo_root(Path(__file__).resolve().parent, validate=True)
    except l5dgva_repo.L5DGVARepositoryNotFoundError as exc:
        print("ERROR: WRONG_L5_REPOSITORY: %s" % exc, file=sys.stderr)
        return 1

    try:
        profile = ep.load_execution_profile(repo_root)
    except ep.ExecutionProfileRequiredError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1

    overrides = ep.profile_to_env_overrides(profile)
    for name, value in overrides.items():
        print("%s=%s" % (name, value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
