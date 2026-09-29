#!/usr/bin/env python3
"""tools/verification_flow/coverage_hole_regeneration_gate.py

Every non-waived coverage hole must be classified AND actually remediated --
recording a classification and stopping there is not closure.

BUG FIX (2026-09-04, Section 3 item 3b "seed strategy differentiation"): this
gate previously forced ALL THREE classifications
(MISSING_TEST / INSUFFICIENT_CONSTRAINT / UNREACHABLE_STIMULUS) down the SAME
remediation -- `regenerated_testcase_ids` + `rerun_evidence`, or FAIL. That
made the enum decorative: UNREACHABLE_STIMULUS means "the stimulus is
structurally incapable of reaching this bin", and demanding yet another
regenerated testcase for it is demanding the one action that provably cannot
work. It also actively suppressed the correct action (ask the design owner),
so the taxonomy that looked like the spec's required differentiation was
working against it.

The remediation is now differentiated per class, and each branch's
requirement is the action that can actually close THAT class:

  MISSING_TEST / INSUFFICIENT_CONSTRAINT
      unchanged -- regenerated_testcase_ids + rerun_evidence.
  INSUFFICIENT_SEED_ATTEMPTS   (new class)
      the bin has not been sampled enough for any structural verdict yet:
      requires `added_seed_evidence` (which seeds were added, and the rerun
      that used them). Requiring a NEW TESTCASE here would be wrong -- the
      test already exists, it just has not been run enough.
  UNREACHABLE_STIMULUS
      requires a REAL escalation to the question queue, not a testcase.
      Satisfied by an `escalation_question_id` naming a question that
      genuinely exists in this project's own
      `.dv-harness/question_queue/questions.json`, or -- when that store is
      unreadable/absent, e.g. a direct invocation outside a project -- by the
      declared id alone. `dv_harness.coverage_analysis.
      escalate_unreachable_holes()` is what creates that question for real;
      `dv_harness.engine` calls it before this gate runs, so an agent that
      classifies a hole UNREACHABLE_STIMULUS gets the escalation performed
      on its behalf and this gate then verifies it landed.

An unrecognised classification string is now a hard FAIL
(UNKNOWN_COVERAGE_HOLE_CLASSIFICATION) rather than silently passing through
unremediated, which is what the old `in (...)` membership test did.
"""
import argparse, json, pathlib, sys

CLASSES_REQUIRING_TEST_REGENERATION = ("MISSING_TEST", "INSUFFICIENT_CONSTRAINT")
CLASSES_REQUIRING_MORE_SEEDS = ("INSUFFICIENT_SEED_ATTEMPTS",)
CLASSES_REQUIRING_HUMAN_ESCALATION = ("UNREACHABLE_STIMULUS",)
KNOWN_CLASSES = (CLASSES_REQUIRING_TEST_REGENERATION
                 + CLASSES_REQUIRING_MORE_SEEDS
                 + CLASSES_REQUIRING_HUMAN_ESCALATION)

QUESTIONS_REL = pathlib.Path(".dv-harness") / "question_queue" / "questions.json"


def _known_question_ids(root):
    """Question ids really present in this project's queue, or None when the
    store cannot be read at all. None means "cannot verify", which this gate
    treats as "accept the declared id" -- an infrastructure gap must not fail
    a stage for something the agent did correctly."""
    p = pathlib.Path(root) / QUESTIONS_REL
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {str(q.get("id")) for q in (data.get("questions") or []) if isinstance(q, dict)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holes", required=True)
    ap.add_argument("--project-root", default=".",
                    help="Where to look for .dv-harness/question_queue/questions.json. "
                         "Defaults to the CWD, which gates.run_gate() always sets to the "
                         "project root; exposed as a flag only for direct invocation/tests.")
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.holes).read_text())

    holes = d.get("coverage_holes", [])
    known_ids = _known_question_ids(a.project_root)

    for h in holes:
        hid = h.get("coverage_id")
        if h.get("waived"):
            if not (h.get("waiver_approved") and h.get("waiver_evidence")):
                print(json.dumps({"status": "FAIL", "reason": "INVALID_COVERAGE_HOLE_WAIVER",
                                   "coverage_id": hid})); return 2
            continue

        cls = h.get("root_cause_classification")
        if not cls:
            print(json.dumps({"status": "FAIL", "reason": "UNCLASSIFIED_COVERAGE_HOLE",
                               "coverage_id": hid})); return 3

        if cls in CLASSES_REQUIRING_TEST_REGENERATION:
            if not h.get("regenerated_testcase_ids"):
                print(json.dumps({"status": "FAIL", "reason": "COVERAGE_HOLE_WITHOUT_TEST_REGENERATION",
                                   "coverage_id": hid, "root_cause_classification": cls})); return 4
            if not h.get("rerun_evidence"):
                print(json.dumps({"status": "FAIL", "reason": "REGENERATED_TEST_WITHOUT_RERUN",
                                   "coverage_id": hid, "root_cause_classification": cls})); return 5

        elif cls in CLASSES_REQUIRING_MORE_SEEDS:
            if not h.get("added_seed_evidence"):
                print(json.dumps({"status": "FAIL", "reason": "INSUFFICIENT_SEEDS_WITHOUT_ADDED_SEED_EVIDENCE",
                                   "coverage_id": hid, "root_cause_classification": cls,
                                   "note": "this class needs MORE SEEDS on the existing test, not a new testcase"}))
                return 6

        elif cls in CLASSES_REQUIRING_HUMAN_ESCALATION:
            qid = h.get("escalation_question_id")
            if not qid:
                print(json.dumps({"status": "FAIL", "reason": "UNREACHABLE_STIMULUS_WITHOUT_HUMAN_ESCALATION",
                                   "coverage_id": hid, "root_cause_classification": cls,
                                   "note": "an unreachable-stimulus bin must be confirmed by the design "
                                           "owner through the question queue; a regenerated testcase "
                                           "cannot close it"}))
                return 7
            if known_ids is not None and str(qid) not in known_ids:
                print(json.dumps({"status": "FAIL", "reason": "ESCALATION_QUESTION_ID_NOT_IN_QUEUE",
                                   "coverage_id": hid, "escalation_question_id": qid})); return 8

        else:
            print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_COVERAGE_HOLE_CLASSIFICATION",
                               "coverage_id": hid, "root_cause_classification": cls,
                               "known_classes": list(KNOWN_CLASSES)})); return 9

    print(json.dumps({"status": "PASS", "holes": len(holes),
                       "question_queue_checked": known_ids is not None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
