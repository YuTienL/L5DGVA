#!/usr/bin/env python3
import argparse, json, os, pathlib, sys

# M8 Cohort H (GAP-M8-010): this gate's own EXPERIENCE_READY corroboration
# check moved into dv_harness/promotion_evidence.py, the one real, shared
# implementation its sibling gate (closed_loop_promotion_gate.py) now also
# imports -- Connect Before Expand, never two independently-maintained
# copies of the same trust check. Same DV_HARNESS_PACKAGE_ROOT pattern
# several other tools/verification_flow/*.py scripts already use (e.g.
# qualification_matrix_consistency_gate.py).
_env_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
_ROOT = pathlib.Path(_env_root) if _env_root else pathlib.Path(__file__).resolve().parents[2]  # dogfooding/legacy fallback
sys.path.insert(0, str(_ROOT))
from dv_harness.promotion_evidence import project_root_from_env, real_promotion_event_exists  # noqa: E402

ORDER = [
    "INTAKE_READY",
    "VPLAN_READY",
    "ARCHITECTURE_READY",
    "MECHANISM_READY",
    "TESTS_READY",
    "TRACEABILITY_READY",
    "EXECUTION_EVIDENCE_READY",
    "COVERAGE_QUALITY_READY",
    "RCA_READY",
    "RERUN_READY",
    "EXPERT_REVIEW_READY",
    "EXPERIENCE_READY",
    "PROMOTABLE"
]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.audit).read_text())
    events=d.get("events",[])
    if not events:
        print(json.dumps({"status":"FAIL","reason":"NO_EVENTS"})); return 2

    seen=[]
    names=set()
    for e in events:
        stage=e.get("stage")
        if stage not in ORDER:
            print(json.dumps({"status":"FAIL","reason":"UNKNOWN_STAGE","stage":stage})); return 3
        if stage in names:
            print(json.dumps({"status":"FAIL","reason":"DUPLICATE_STAGE","stage":stage})); return 4
        if not e.get("evidence"):
            print(json.dumps({"status":"FAIL","reason":"STAGE_WITHOUT_EVIDENCE","stage":stage})); return 5
        names.add(stage)
        seen.append(stage)

    # Enforce monotonic order
    idx=[ORDER.index(x) for x in seen]
    if idx != sorted(idx):
        print(json.dumps({"status":"FAIL","reason":"NON_MONOTONIC_PROMOTION_CHAIN","events":seen})); return 6

    # PROMOTABLE requires all mandatory stages before it, RCA/RERUN may be omitted only if no failure
    failure=d.get("failure_detected", False)
    mandatory = ORDER[:8] + ["EXPERT_REVIEW_READY","EXPERIENCE_READY","PROMOTABLE"]
    if failure:
        mandatory = ORDER
    missing=[x for x in mandatory if x not in names]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_PROMOTION_STAGES","missing":missing})); return 7

    # GAP-M8-001 (M8 Cohort 1): EXPERIENCE_READY is an agent-self-attested
    # stage name in this same --audit JSON, checked structurally above like
    # every other stage but never previously corroborated against anything
    # real. Require a real backing promotion event now.
    if "EXPERIENCE_READY" in names and not real_promotion_event_exists(project_root_from_env()):
        print(json.dumps({
            "status": "FAIL", "reason": "EXPERIENCE_READY_NOT_VERIFIED",
            "detail": ("EXPERIENCE_READY was self-attested but no real promotion event "
                       "(EXPERIENCE_KNOWLEDGE_PROMOTED or a sibling route_and_store() "
                       "event) with a real, non-failed destination was found in this "
                       "project's .dv-harness/events.jsonl"),
        }))
        return 8

    print(json.dumps({"status":"PASS","stages":seen,"failure_detected":failure}))
    return 0

if __name__=="__main__":
    sys.exit(main())
