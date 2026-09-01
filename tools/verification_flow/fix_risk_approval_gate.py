#!/usr/bin/env python3
# HARDENING (2026-09-02, RE_AUDIT/FAILURE_RECOVERY approval-gate audit): a
# HIGH risk_level / DUT_BUG classification fix used to need only
# "approved_for_modify":true to PASS -- JSON the SAME agent proposing the
# fix writes in its own reply, never checked against any real human action.
# This now additionally cross-checks the real, human-writable
# .dv-harness/control.json Human Control Plane state (the same file
# dv_harness/control_plane.py's ControlPlane.approve()/get_approval() read
# and write, and dv_harness/engine.py's run_stage() reads for its own
# PROMOTION_READINESS/SIGNOFF hard-stop) for a real RE_AUDIT approval
# record. Read directly off disk rather than importing dv_harness --
# self-contained, same "a subprocess gate script that imports dv_harness
# breaks the moment it's copied standalone into a project without a full
# dv_harness/ package alongside it" ruling documented in
# environment_mode_selection_gate.py. TB_BUG / non-HIGH-risk fixes are
# deliberately unaffected by this cross-check -- scoped to the DUT-RTL-risk
# case, not every routine testbench fix.
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.plan).read_text())
for k in ("root_cause_id","fix_plan","risk_assessment","affected_scope","regression_plan","rollback_plan"):
 if not d.get(k): print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_FIX_RISK_PLAN","field":k})); sys.exit(2)
if d.get("root_cause_confidence") not in ("HIGH","VERIFIED"):
 print(json.dumps({"status":"FAIL","reason":"FIX_WITHOUT_HIGH_CONFIDENCE_RCA"})); sys.exit(3)
if d.get("risk_level")=="HIGH" and d.get("high_risk_reviewed") is not True:
 print(json.dumps({"status":"FAIL","reason":"HIGH_RISK_FIX_NOT_REVIEWED"})); sys.exit(4)
if d.get("approved_for_modify") is not True:
 print(json.dumps({"status":"FAIL","reason":"FIX_NOT_APPROVED_FOR_MODIFICATION"})); sys.exit(5)
if d.get("risk_level")=="HIGH" or d.get("classification")=="DUT_BUG":
 control={}
 control_path=pathlib.Path(".dv-harness")/"control.json"
 if control_path.is_file():
  try: control=json.loads(control_path.read_text(encoding="utf-8"))
  except Exception: control={}
 if not (control.get("approvals") or {}).get("RE_AUDIT"):
  print(json.dumps({"status":"FAIL","reason":"HIGH_RISK_FIX_WITHOUT_CONTROL_PLANE_APPROVAL"})); sys.exit(6)
print(json.dumps({"status":"PASS"}))
