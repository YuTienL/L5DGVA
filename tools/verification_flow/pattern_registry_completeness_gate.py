#!/usr/bin/env python3
# BUG FIX (2026-08-29, 9-policy audit / USB regen-fidelity plan Phase 1 item
# 2): validates a persisted pattern registry JSON against the same
# recomputation logic dv_harness/uvm_generator/pattern_registry_generator.py
# uses at generation time -- catching drift when the JSON was hand-edited or
# a pattern was added/removed on disk without regenerating suite_names.
import argparse, json, pathlib, sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from dv_harness.uvm_generator.pattern_registry_generator import compute_suite_names  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.registry).read_text())
    patterns = d.get("patterns", [])

    seen = set()
    for p in patterns:
        name = p.get("name")
        if not name:
            print(json.dumps({"status": "FAIL", "reason": "MALFORMED_PATTERN_ENTRY", "entry": p})); return 2
        if name in seen:
            print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_PATTERN_NAME", "name": name})); return 3
        seen.add(name)
        if not p.get("suite") or not p.get("dir"):
            print(json.dumps({"status": "FAIL", "reason": "MISSING_SUITE_DIR", "name": name})); return 4

    recomputed = compute_suite_names(patterns)
    stored = sorted(d.get("suite_names", []))
    if recomputed != stored:
        print(json.dumps({"status": "FAIL", "reason": "SUITE_NAMES_DRIFT",
                           "recomputed": recomputed, "stored": stored})); return 5

    declared = d.get("declared_suites")
    if declared:
        zero = sorted(s for s in declared if s not in recomputed)
        if zero:
            print(json.dumps({"status": "FAIL", "reason": "SUITE_WITH_ZERO_PATTERNS",
                               "suites": zero})); return 6

    print(json.dumps({"status": "PASS", "pattern_count": len(patterns), "suite_names": recomputed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
