#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--system", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.system).read_text())

    rels={x.get("subsystem"):x for x in d.get("subsystems",[]) if x.get("subsystem")}
    if len(rels)<2:
        print(json.dumps({"status":"FAIL","reason":"INSUFFICIENT_SUBSYSTEM_RELEASES"})); return 2

    for s in rels.values():
        for k in ("release_sha","manifest_hash","qualification_evidence_hash"):
            if not s.get(k):
                print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_SUBSYSTEM_RELEASE_EVIDENCE",
                                  "subsystem":s.get("subsystem"),"missing":k})); return 3

    for sc in d.get("scenarios",[]):
        sid=sc.get("scenario_id")
        participants=sc.get("participating_subsystems",[])
        if len(participants)<2:
            print(json.dumps({"status":"FAIL","reason":"SYSTEM_SCENARIO_NOT_MULTI_SUBSYSTEM","scenario_id":sid})); return 4
        unknown=[x for x in participants if x not in rels]
        if unknown:
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_REFERENCES_UNKNOWN_RELEASE",
                              "scenario_id":sid,"unknown":unknown})); return 5
        snapshot=sc.get("release_snapshot",{})
        for sub in participants:
            if snapshot.get(sub) != rels[sub].get("release_sha"):
                print(json.dumps({"status":"FAIL","reason":"SCENARIO_RELEASE_SNAPSHOT_MISMATCH",
                                  "scenario_id":sid,"subsystem":sub})); return 6
        if not sc.get("evidence_bundle_hash"):
            print(json.dumps({"status":"FAIL","reason":"SYSTEM_SCENARIO_WITHOUT_EVIDENCE_HASH",
                              "scenario_id":sid})); return 7

    print(json.dumps({"status":"PASS","scenarios":len(d.get("scenarios",[]))}))
    return 0

if __name__=="__main__":
    sys.exit(main())
