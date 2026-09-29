#!/usr/bin/env python3
"""waiver_scope_consistency_gate.py -- a waiver must declare the exact scope
it covers, must not hide an active failure, and must not be applied outside
that scope.

Since 2026-09-06 the waiver records judged here come from the project's
durable waiver ledger (dv_harness/waiver_store.py, .dv-harness/waivers/
waivers.json) whenever that ledger EXISTS, instead of from the agent's own
```dv-harness-evidence:waiver_scope_consistency_gate``` block -- see
waiver_revalidation_gate.py's header for why a self-attested waiver was the
gap. A project with no ledger keeps the original behaviour and the original
exit codes byte-identically.

Exit codes: 2 INCOMPLETE_WAIVER_SCOPE, 3 WAIVER_ATTEMPTS_TO_HIDE_ACTIVE_FAILURE,
4 WAIVER_APPLIED_OUTSIDE_SCOPE, 6 WAIVER_REVOKED, 7 WAIVER_STATUS_UNKNOWN,
8 WAIVER_NOT_IN_STORE, 9 WAIVER_STORE_UNAVAILABLE.
"""
import argparse,json,os,pathlib,sys

_pkg_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
sys.path.insert(0, str(pathlib.Path(_pkg_root) if _pkg_root else pathlib.Path(__file__).resolve().parents[2]))
try:
    from dv_harness import waiver_store as _waiver_store
except Exception:  # pragma: no cover - broken/partial deployment
    _waiver_store = None

GATE_ID = "waiver_scope_consistency_gate"

ap=argparse.ArgumentParser(); ap.add_argument("--waivers",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.waivers).read_text())
root=pathlib.Path(os.environ.get("DV_HARNESS_PROJECT_ROOT") or os.getcwd())
declared=d.get("waivers",[])

if _waiver_store is None:
    print(json.dumps({"status":"FAIL","reason":"WAIVER_STORE_UNAVAILABLE",
                      "detail":"dv_harness.waiver_store is not importable"})); sys.exit(9)
if _waiver_store.store_exists(root):
    unbacked=_waiver_store.unbacked_declared_ids(root,GATE_ID,declared)
    if unbacked:
        print(json.dumps({"status":"FAIL","reason":"WAIVER_NOT_IN_STORE",
                          "waiver_ids":unbacked})); sys.exit(8)
    waivers=_waiver_store.gate_records(root,GATE_ID)
    source="waiver_store"
else:
    waivers=declared
    source="agent_evidence_block"

for w in waivers:
    wid=w.get("waiver_id")
    derived=w.get("waiver_status")
    if derived and derived!="VALID":
        reason=_waiver_store.STATUS_FAIL_REASONS[derived]
        # EXPIRED/REVALIDATION_REQUIRED are decided by the gates that really
        # measure the clock and the revision (waiver_revalidation_gate /
        # waiver_revision_freshness_gate, same stage); this gate never sees
        # them because gate_records() withholds facts it did not observe.
        code={"WAIVER_REVOKED":6,"WAIVER_STATUS_UNKNOWN":7,
              "WAIVER_EXPIRED":6,"WAIVER_REVALIDATION_REQUIRED":6}[reason]
        print(json.dumps({"status":"FAIL","reason":reason,"waiver_id":wid,
                          "waiver_status":derived,
                          "detail":w.get("waiver_status_reason"),
                          "source":source})); sys.exit(code)
    for k in ("requirement_ids","subsystem","spec_revision","design_evidence_hash","approval_id","scope_hash"):
        if not w.get(k):
            print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_WAIVER_SCOPE","waiver_id":wid,"missing":k,"source":source})); sys.exit(2)
    if w.get("active_failure_ids"):
        print(json.dumps({"status":"FAIL","reason":"WAIVER_ATTEMPTS_TO_HIDE_ACTIVE_FAILURE","waiver_id":wid,"source":source})); sys.exit(3)
    if w.get("applied_requirement_ids") and set(w["applied_requirement_ids"])-set(w["requirement_ids"]):
        print(json.dumps({"status":"FAIL","reason":"WAIVER_APPLIED_OUTSIDE_SCOPE","waiver_id":wid,"source":source})); sys.exit(4)
print(json.dumps({"status":"PASS","waivers":len(waivers),"source":source}))
