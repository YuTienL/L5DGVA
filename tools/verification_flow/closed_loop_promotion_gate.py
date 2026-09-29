#!/usr/bin/env python3
import argparse, json, os, pathlib, sys

# M8 Cohort H (GAP-M8-010): same DV_HARNESS_PACKAGE_ROOT pattern several
# other tools/verification_flow/*.py scripts already use (e.g.
# qualification_matrix_consistency_gate.py) to reach the real dv_harness
# package from this standalone-script context, and the SAME shared
# corroboration check promotion_chain_audit_gate.py's own EXPERIENCE_READY
# fix (M8 Cohort 1 / GAP-M8-001) already uses -- Connect Before Expand,
# never a second, independently-maintained trust framework.
_env_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
_ROOT = pathlib.Path(_env_root) if _env_root else pathlib.Path(__file__).resolve().parents[2]  # dogfooding/legacy fallback
sys.path.insert(0, str(_ROOT))
from dv_harness.promotion_evidence import project_root_from_env, real_promotion_event_exists  # noqa: E402

REQUIRED_STAGES = [
    "INTAKE_READY",
    "VPLAN_READY",
    "ARCHITECTURE_READY",
    "MECHANISM_READY",
    "TESTS_READY",
    "EXECUTION_EVIDENCE_READY",
    "COVERAGE_QUALITY_READY",
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.state).read_text())

    passed=set(d.get("passed_stages",[]))
    missing=[x for x in REQUIRED_STAGES if x not in passed]
    if missing:
        print(json.dumps({"status":"FAIL","reason":"MISSING_STAGES","missing":missing},indent=2))
        return 2

    if d.get("failure_detected"):
        rca=d.get("root_cause",{})
        required=["classification","first_bad_event","causal_chain","supporting_evidence","counter_evidence","confidence"]
        miss=[x for x in required if not rca.get(x)]
        if miss:
            print(json.dumps({"status":"FAIL","reason":"FAILURE_WITHOUT_VALID_RCA","missing":miss},indent=2))
            return 3
        if not d.get("calibration_or_fix_applied"):
            print(json.dumps({"status":"FAIL","reason":"FAILURE_WITHOUT_FIX_OR_CALIBRATION"}))
            return 4
        if not d.get("rerun_evidence"):
            print(json.dumps({"status":"FAIL","reason":"FIX_WITHOUT_RERUN_EVIDENCE"}))
            return 5

    if not d.get("expert_feedback_reviewed"):
        print(json.dumps({"status":"FAIL","reason":"NO_EXPERT_FEEDBACK_REVIEW"}))
        return 6

    experience_capture_status = d.get("experience_capture_status")
    if experience_capture_status not in ("CAPTURED","NOT_APPLICABLE"):
        print(json.dumps({"status":"FAIL","reason":"EXPERIENCE_LOOP_NOT_CLOSED"}))
        return 7

    # M8 Cohort H (GAP-M8-010): experience_capture_status was a bare
    # agent-typed string, structurally checked above (one of two allowed
    # values) but never corroborated against anything real -- the identical
    # self-attestation loophole GAP-M8-001 closed for the sibling
    # promotion_chain_audit_gate's own EXPERIENCE_READY stage.
    # NOT_APPLICABLE is left exempt: it is a legitimate, non-suspicious
    # claim ("no experience capture was expected this run"), not a claim
    # of a real promotion having occurred -- only "CAPTURED" asserts a
    # real event exists, so only "CAPTURED" requires one.
    if experience_capture_status == "CAPTURED" and not real_promotion_event_exists(project_root_from_env()):
        print(json.dumps({
            "status": "FAIL", "reason": "EXPERIENCE_CAPTURE_NOT_VERIFIED",
            "detail": ("experience_capture_status=CAPTURED was self-attested but no real "
                       "promotion event (EXPERIENCE_KNOWLEDGE_PROMOTED or a sibling "
                       "route_and_store() event) with a real, non-failed destination was "
                       "found in this project's .dv-harness/events.jsonl"),
        }))
        return 8

    print(json.dumps({"status":"PROMOTABLE","passed_stages":sorted(passed)},indent=2))
    return 0

if __name__=="__main__":
    sys.exit(main())
