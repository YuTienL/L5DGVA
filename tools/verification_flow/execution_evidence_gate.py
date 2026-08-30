#!/usr/bin/env python3
import argparse, json, pathlib, sys

VALID_STATES={"VERIFIED","WAIVED","NOT_APPLICABLE"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--closure", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.closure).read_text())

    reqs=d.get("requirements",[])
    if not reqs:
        print(json.dumps({"status":"FAIL","reason":"NO_REQUIREMENTS"})); return 2

    failures=[]
    for r in reqs:
        rid=r.get("req_id")
        state=r.get("status")
        if state not in VALID_STATES:
            failures.append({"req_id":rid,"reason":"NOT_CLOSED","status":state})
            continue

        evidence=r.get("execution_evidence",[])
        mechanisms=r.get("mechanism_ids",[])
        w=r.get("waiver",{})
        has_verified_evidence=bool(evidence) and bool(mechanisms or r.get("approved_alternate_verification_method"))
        has_valid_waiver=bool(r.get("support_status")=="UNSUPPORTED_BY_DUT" and w.get("approved") and w.get("evidence"))
        has_na_evidence=bool(r.get("not_applicable_evidence"))

        if state=="VERIFIED":
            if not evidence:
                failures.append({"req_id":rid,"reason":"VERIFIED_WITHOUT_EXECUTION_EVIDENCE"})
            if not mechanisms and not r.get("approved_alternate_verification_method"):
                failures.append({"req_id":rid,"reason":"VERIFIED_WITHOUT_VERIFICATION_MECHANISM"})

        elif state=="WAIVED":
            if not has_valid_waiver:
                failures.append({"req_id":rid,"reason":"INVALID_WAIVER"})

        elif state=="NOT_APPLICABLE":
            if not has_na_evidence:
                failures.append({"req_id":rid,"reason":"NOT_APPLICABLE_WITHOUT_EVIDENCE"})

        # Cross-check: the declared status must match the evidence class that
        # is actually populated -- catches a status that disagrees with which
        # kind of evidence the requirement actually carries (e.g. declared
        # VERIFIED while only a waiver was ever filled in).
        populated=[s for s,ok in (("VERIFIED",has_verified_evidence),
                                   ("WAIVED",has_valid_waiver),
                                   ("NOT_APPLICABLE",has_na_evidence)) if ok]
        if populated and state not in populated:
            failures.append({"req_id":rid,"reason":"STATUS_EVIDENCE_MISMATCH",
                             "declared":state,"evidence_supports":populated})

    if failures:
        print(json.dumps({"status":"FAIL","failures":failures},indent=2)); return 3

    print(json.dumps({"status":"READY_FOR_CLOSURE","requirements":len(reqs)},indent=2))
    return 0

if __name__=="__main__":
    sys.exit(main())
