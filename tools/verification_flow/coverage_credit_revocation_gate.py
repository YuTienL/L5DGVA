#!/usr/bin/env python3
import argparse,json,pathlib,sys

REVOKE={"CHECKER_DISABLED","ASSERTION_DISABLED","STALE_EVIDENCE","FAILED_RERUN","INVALID_WAIVER","TEST_QUARANTINED"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--coverage",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.coverage).read_text())
    for c in d.get("items",[]):
        triggers=set(c.get("revocation_triggers",[]))
        if c.get("credit") and triggers & REVOKE:
            print(json.dumps({"status":"FAIL","reason":"COVERAGE_CREDIT_MUST_BE_REVOKED",
                              "coverage_id":c.get("coverage_id"),
                              "triggers":sorted(triggers & REVOKE)})); return 2
    print(json.dumps({"status":"PASS"})); return 0
if __name__=="__main__":
    sys.exit(main())
