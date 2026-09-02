#!/usr/bin/env python3
import argparse, json, os, pathlib, sys

# BUG FIX (2026-08-28, plan-qualification-vocab design pass): this gate only
# ever self-checked the narrow 3-value qualification_state against numeric
# evidence counts. It never cross-checked that value against the canonical
# 8-tier qualification vocabulary (dv_harness/qualification.py) at all -- an
# entry could carry an inconsistent or outright invalid canonical status with
# nothing catching it. The optional canonical_qualification_status field
# below is additive: entries that omit it behave exactly as before.
#
# Finding I7 fix (2026-09-02 final-review follow-up): prefer the real
# dv_harness package location run_gate() (dv_harness/gates.py) already knows
# and passes via env -- the parents[2] guess only holds in this repo's own
# dogfooding layout, not in a real deployed project running its own copy of
# tools/verification_flow/. Fall back to the guess only for direct/manual
# invocation outside run_gate().
_env_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
_ROOT = pathlib.Path(_env_root) if _env_root else pathlib.Path(__file__).resolve().parents[2]  # dogfooding/legacy fallback
sys.path.insert(0, str(_ROOT))
from dv_harness import qualification as _q  # noqa: E402

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--matrix",required=True); a=ap.parse_args()
    d=json.loads(pathlib.Path(a.matrix).read_text())
    for p in d.get("protocols",[]):
        name=p.get("protocol")
        state=p.get("qualification_state")
        tests=int(p.get("passing_test_count",0))
        cov=float(p.get("coverage_percent",0))
        evidence=int(p.get("evidence_count",0))
        if state=="PRODUCTION_QUALIFIED":
            if tests<=0 or cov<100 or evidence<=0:
                print(json.dumps({"status":"FAIL","reason":"PRODUCTION_QUALIFICATION_INCONSISTENT",
                                  "protocol":name,"tests":tests,"coverage":cov,"evidence":evidence})); return 2
        elif state=="REGRESSION_QUALIFIED":
            if tests<=0 or cov<=0 or evidence<=0:
                print(json.dumps({"status":"FAIL","reason":"REGRESSION_QUALIFICATION_INCONSISTENT","protocol":name})); return 3
        elif state=="SMOKE_QUALIFIED":
            if tests<=0:
                print(json.dumps({"status":"FAIL","reason":"SMOKE_QUALIFICATION_WITHOUT_PASSING_TEST","protocol":name})); return 4

        canonical = p.get("canonical_qualification_status")
        if canonical is not None:
            if not _q.is_canonical(canonical):
                print(json.dumps({"status":"FAIL","reason":"INVALID_CANONICAL_QUALIFICATION_STATUS",
                                  "protocol":name,"value":canonical,"allowed":list(_q.CANONICAL_LADDER)})); return 5
            try:
                mapped = _q.map_to_system_level_state(canonical)
            except ValueError:
                print(json.dumps({"status":"FAIL","reason":"CANONICAL_STATUS_BELOW_SYSTEM_LEVEL_FLOOR",
                                  "protocol":name,"value":canonical})); return 6
            if mapped != state:
                print(json.dumps({"status":"FAIL","reason":"QUALIFICATION_STATUS_STATE_MISMATCH",
                                  "protocol":name,"canonical_qualification_status":canonical,
                                  "mapped_system_level_state":mapped,"qualification_state":state})); return 7

    print(json.dumps({"status":"PASS"})); return 0

if __name__=="__main__":
    sys.exit(main())
