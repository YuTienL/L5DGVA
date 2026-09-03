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

GAP CLOSED (2026-09-04, Section 3 item 3a "test selection by RTL-diff impact
scope"): before this, every field this gate checked was AGENT SELF-REPORT.
The four categories had to be non-empty and `change_impact_evidence_id` had
to be a non-empty string -- but nothing on earth checked that either bore any
relation to a real diff, and the evidence id was unverifiable free text.
`dv_harness/change_impact.py` now COMPUTES the selection from a real
`git diff` + the real `.dv-harness/requirements.csv` traceability registry +
the real `rtl_modules` rows in the evidence DB, and writes it to
`.dv-harness/regression/computed_selection.json` before this stage runs. When
that artifact exists, this gate enforces two additional real rules:

  - NO-SHRINK: every computed test must appear somewhere in the agent's own
    four categories. The agent may ADD (its judgment sees things a registry
    cannot); it may not DROP. That asymmetry is the skill's own rule --
    "必要時擴大 regression, 不得冒險縮小" -- made mechanical.
  - EVIDENCE-ID MATCH: the declared `change_impact_evidence_id` must equal
    the computed one, so the link is to a real analysis of a real commit
    range rather than a plausible-looking string.

BACKWARD COMPATIBLE BY CONSTRUCTION: with no computed artifact on disk (a
project that has not run the computation, or a direct/manual invocation of
this script) the two rules are skipped entirely and this gate behaves
byte-for-byte as it did before. The artifact is located relative to the CWD,
which `dv_harness/gates.run_gate()` always sets to the project root.
"""
import argparse, json, pathlib, sys

CATEGORIES = ["targeted_tests", "dependency_tests", "safety_tests", "mandatory_signoff_tests"]

COMPUTED_SELECTION_REL = pathlib.Path(".dv-harness") / "regression" / "computed_selection.json"


def _single_test_reverify_satisfied(reverify):
    return (isinstance(reverify, dict)
            and reverify.get("target_pre_fix_result") == "FAIL"
            and reverify.get("target_post_fix_result") == "PASS")


def _load_computed(root):
    """The harness-computed selection, or None. Never raises: a missing or
    unreadable artifact must degrade this gate to its pre-existing
    attestation-only behavior, never fail a stage for an infrastructure
    problem the agent cannot fix."""
    p = pathlib.Path(root) / COMPUTED_SELECTION_REL
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("selection"), dict) else None


def _declared_tests(d):
    out = set()
    for cat in CATEGORIES:
        for t in (d.get(cat) or []):
            out.add(str(t))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True)
    ap.add_argument("--project-root", default=".",
                    help="Where to look for .dv-harness/regression/computed_selection.json. "
                         "Defaults to the CWD, which gates.run_gate() always sets to the "
                         "project root; exposed as a flag only for direct invocation/tests.")
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

    # --- computed-selection enforcement (see module docstring) -------------
    computed = _load_computed(a.project_root)
    computed_checked = False
    if computed is not None:
        computed_checked = True
        computed_id = computed.get("change_impact_evidence_id")
        if computed_id and src.get("change_impact_evidence_id") != computed_id:
            print(json.dumps({"status": "FAIL", "reason": "CHANGE_IMPACT_EVIDENCE_ID_MISMATCH",
                               "declared": src.get("change_impact_evidence_id"),
                               "computed": computed_id})); return 5
        sel = computed.get("selection") or {}
        declared = _declared_tests(d)
        dropped = sorted({str(t) for cat in CATEGORIES for t in (sel.get(cat) or [])} - declared)
        if dropped:
            print(json.dumps({"status": "FAIL", "reason": "COMPUTED_SELECTION_TESTS_DROPPED",
                               "dropped": dropped,
                               "change_impact_evidence_id": computed_id,
                               "note": "the harness-computed impact selection may be expanded, never reduced"}))
            return 6

    print(json.dumps({"status": "PASS",
                       "counts": {c: len(d.get(c, [])) for c in CATEGORIES},
                       "computed_selection_checked": computed_checked}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
