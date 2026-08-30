#!/usr/bin/env python3
import argparse,json,pathlib,sys

def _diff(before, after):
    keys=set(before) | set(after)
    deltas=[]
    for k in sorted(keys, key=str):
        bv=before.get(k); av=after.get(k)
        if bv!=av:
            deltas.append({"field":k,"before":bv,"after":av})
    return deltas

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--calibration",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.calibration).read_text())

    before=d.get("architecture_before",{})
    after=d.get("architecture_after",{})
    if not before or not after:
        print(json.dumps({"status":"FAIL","reason":"MISSING_ARCHITECTURE_SNAPSHOTS"})); return 2

    # Derive the delta list from the two snapshots directly rather than
    # trusting an agent-supplied detected_deltas that is never cross-checked
    # against them at all -- an agent-claimed delta with no corresponding
    # before/after difference is a fabrication, not evidence.
    deltas=_diff(before, after)
    if d.get("detected_deltas") and not deltas:
        print(json.dumps({"status":"FAIL","reason":"DETECTED_DELTAS_NOT_SUBSTANTIATED_BY_SNAPSHOTS"})); return 6

    if deltas:
        if not d.get("impact_analysis_completed"):
            print(json.dumps({"status":"FAIL","reason":"ARCH_DELTA_WITHOUT_IMPACT_ANALYSIS"})); return 3
        if not d.get("affected_artifacts_updated"):
            print(json.dumps({"status":"FAIL","reason":"ARCH_DELTA_WITHOUT_ENV_UPDATE"})); return 4
        if not d.get("rerun_evidence"):
            print(json.dumps({"status":"FAIL","reason":"ARCH_DELTA_WITHOUT_RERUN"})); return 5

    print(json.dumps({"status":"PASS","delta_count":len(deltas)})); return 0
if __name__=="__main__":
    sys.exit(main())
