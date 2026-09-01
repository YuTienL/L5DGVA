#!/usr/bin/env python3
"""tools/verification_flow/regression_selection_completeness_gate.py

BUG FIX (2026-09-02, RE_AUDIT-precondition audit follow-up): the real gate
that proves "target test was FAIL before the fix, PASS after" (this same
FAIL/PASS shape, see fix_regression_non_regression_gate.py) previously only
ran POST-HOC, at RE_AUDIT -- AFTER the full REGRESSION -> REGRESSION_MONITOR
-> COVERAGE_CLOSURE chain (see main_graph.json's edge sequence) had already
submitted and counted a full regression run for a fix that had never been
single-test-reverified at all. This stage (REGRESSION_SELECT) is the last
gate before REGRESSION submits jobs, so it is the right place for a REAL
precondition: when this selection follows a FAILURE_RECOVERY/RE_AUDIT fix
cycle (`fix_cycle_id` set), a `single_test_reverify_evidence` block with the
same target_pre_fix_result=="FAIL"/target_post_fix_result=="PASS" shape must
already be attached, or the full regression must not be allowed to submit at
all. This is additive/belt-and-suspenders -- it does not replace
fix_regression_non_regression_gate.py's own RE_AUDIT check, which still runs.
"""
import argparse, json, pathlib, sys

CATEGORIES = ["targeted_tests", "dependency_tests", "safety_tests", "mandatory_signoff_tests"]


def _single_test_reverify_satisfied(reverify):
    return (isinstance(reverify, dict)
            and reverify.get("target_pre_fix_result") == "FAIL"
            and reverify.get("target_post_fix_result") == "PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.selection).read_text())

    for cat in CATEGORIES:
        tests = d.get(cat, [])
        if not tests and not d.get(cat + "_empty_reason"):
            print(json.dumps({"status": "FAIL", "reason": "EMPTY_SELECTION_CATEGORY_WITHOUT_REASON",
                               "category": cat})); return 2

    src = d.get("selection_source", {})
    if not src.get("change_impact_evidence_id"):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_CHANGE_IMPACT_LINK"})); return 3

    # Precondition addition (see module docstring): a regression selection
    # that itself declares it follows a fix cycle must already carry a real
    # single-test reverify block BEFORE the full regression it is selecting
    # tests for is allowed to submit -- not just prove it after the fact at
    # RE_AUDIT once the whole chain has already run.
    fix_cycle_id = d.get("fix_cycle_id")
    if fix_cycle_id and not _single_test_reverify_satisfied(d.get("single_test_reverify_evidence")):
        print(json.dumps({"status": "FAIL",
                           "reason": "SINGLE_TEST_REVERIFY_MISSING_BEFORE_FULL_REGRESSION",
                           "fix_cycle_id": fix_cycle_id})); return 4

    print(json.dumps({"status": "PASS",
                       "counts": {c: len(d.get(c, [])) for c in CATEGORIES}}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
