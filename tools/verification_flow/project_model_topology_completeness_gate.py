#!/usr/bin/env python3
import argparse, json, pathlib, sys

BRANCHES = {"BLOCK", "BRANCH_A_DUT", "BRANCH_FW", "BRANCH_B_VIP"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
READINESS = {"READY", "NOT_READY", "BLOCKED", "PARTIAL"}
# "BLOCKED" accepted as a synonym of "NOT_READY": dv-workflow's SKILL.md documents the
# general tri-state readiness vocabulary as READY/PARTIAL/BLOCKED, but this gate's field
# predates that and only recognized NOT_READY. Accepting both avoids rejecting a value an
# agent following the documented methodology would legitimately produce.

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.model).read_text())

    if not d.get("verification_boundary"):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_VERIFICATION_BOUNDARY"})); return 2

    vip = d.get("vip_topology", [])
    if not vip and not d.get("vip_topology_not_applicable_reason"):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_VIP_TOPOLOGY"})); return 3
    for v in vip:
        if not v.get("bound_interface"):
            print(json.dumps({"status": "FAIL", "reason": "VIP_TOPOLOGY_UNBOUND",
                               "vip_id": v.get("vip_id")})); return 4

    blocks = d.get("blocks", [])
    if not blocks:
        print(json.dumps({"status": "FAIL", "reason": "NO_BLOCKS_DECLARED"})); return 5
    for b in blocks:
        if b.get("branch") not in BRANCHES:
            print(json.dumps({"status": "FAIL", "reason": "BLOCK_WITHOUT_BRANCH_CLASSIFICATION",
                               "block_id": b.get("block_id")})); return 6

    if d.get("model_confidence") not in CONFIDENCE:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_CONFIDENCE"})); return 7
    if not d.get("confidence_basis"):
        print(json.dumps({"status": "FAIL", "reason": "CONFIDENCE_WITHOUT_BASIS"})); return 8

    if d.get("dv_readiness") not in READINESS:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_DV_READINESS"})); return 9
    if not d.get("dv_readiness_basis"):
        print(json.dumps({"status": "FAIL", "reason": "DV_READINESS_WITHOUT_BASIS"})); return 10

    if not d.get("architecture_evidence_db_ref"):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_ARCHITECTURE_EVIDENCE_DB_LINK"})); return 11

    print(json.dumps({"status": "PASS", "blocks": len(blocks), "confidence": d.get("model_confidence"),
                       "dv_readiness": d.get("dv_readiness")}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
