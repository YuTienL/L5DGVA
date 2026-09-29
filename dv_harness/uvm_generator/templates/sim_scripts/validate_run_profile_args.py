#!/usr/bin/env python3
"""Standalone run_profile.json arg validator -- no dependency on the
dv_harness package.

This script is copied into every generated environment alongside its
run_profile.json and justfile (see run_profile_to_justfile.py). It must
stay dependency-free: a delivered UVM environment ships to a DV team that
does not necessarily have the Harness itself installed, so `just compile
SPEED=gen1` must work from stdlib alone, not from an import of
dv_harness.uvm_generator.run_profile.

Usage:
    python3 validate_run_profile_args.py <run_profile.json> <target> [KEY=VALUE ...]

Exits 0 if every KEY=VALUE pair that names a known enum or retired
constraint is satisfied. Exits 1 and prints the source Makefile's own real
error text for any violation. A KEY not present in run_profile.json at all
is not an error here -- an unrecognized variable is make's problem to
reject (or accept, if it is a real Makefile var this profile's extractor
simply never modeled), not this validator's to guess about.
"""
from __future__ import annotations

import json
import sys


def _find_param(profile: dict, name: str) -> dict | None:
    for bucket in ("compile_time_params", "runtime_params"):
        for p in profile.get(bucket, []):
            if p["name"] == name:
                return p
    return None


def _check(profile: dict, values: dict) -> list[str]:
    violations = []
    for c in profile.get("constraints", []):
        if c["kind"] == "enum_membership":
            if not all(p in values for p in c["params"]):
                continue
            for p in c["params"]:
                param = _find_param(profile, p)
                if param and param.get("type") == "enum":
                    if values[p] not in param.get("enum", []):
                        violations.append(f"{p}={values[p]!r}: {c['message']}")
        elif c["kind"] == "retired":
            for p in c["params"]:
                if p in values:
                    violations.append(f"{p}={values[p]!r}: {c['message']}")
    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: validate_run_profile_args.py <run_profile.json> <target> [KEY=VALUE ...]", file=sys.stderr)
        return 2
    profile_path, target = argv[0], argv[1]
    values = {}
    for arg in argv[2:]:
        if "=" not in arg:
            continue
        key, _, val = arg.partition("=")
        if val != "":
            values[key] = val

    with open(profile_path, encoding="utf-8") as f:
        profile = json.load(f)

    violations = _check(profile, values)
    if violations:
        print(f"Rejected args for target '{target}':", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
