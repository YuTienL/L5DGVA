#!/usr/bin/env python3
"""waiver_revision_freshness_gate.py -- a waiver approved against one
spec_revision/rtl_hash must not be sailed on forever after the design moved.

Since 2026-09-06 the waiver records judged here come from the project's
durable waiver ledger (dv_harness/waiver_store.py, .dv-harness/waivers/
waivers.json) whenever that ledger EXISTS -- see waiver_revalidation_gate.py's
header for why a self-attested waiver was the gap. The `current`
spec_revision/rtl_hash still come from the evidence block: those are
current-RUN facts the ledger cannot know, and they are what the ledger's
recorded revalidation triggers are checked against.

EXPIRY is deliberately NOT decided here (this script's argparse takes only
--state, so run_gate() supplies it no harness-clock --now ContextFlag the way
it does for waiver_revalidation_gate). waiver_revalidation_gate runs in the
SAME stage and owns that check; waiver_store.GATE_STATUS_CONTEXT records the
split and assert_trigger_coverage() holds it.

A project with no ledger keeps the original behaviour and exit codes
byte-identically.

Exit codes: 2 STALE_WAIVER_AFTER_REVISION_CHANGE, 3 EXPIRED_WAIVER,
5 WAIVER_REVALIDATION_REQUIRED, 6 WAIVER_REVOKED, 7 WAIVER_STATUS_UNKNOWN,
8 WAIVER_NOT_IN_STORE, 9 WAIVER_STORE_UNAVAILABLE.
"""
import argparse,json,os,pathlib,sys

_pkg_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
sys.path.insert(0, str(pathlib.Path(_pkg_root) if _pkg_root else pathlib.Path(__file__).resolve().parents[2]))
try:
    from dv_harness import waiver_store as _waiver_store
except Exception:  # pragma: no cover - broken/partial deployment
    _waiver_store = None

GATE_ID = "waiver_revision_freshness_gate"

a=argparse.ArgumentParser(); a.add_argument("--state",required=True); x=a.parse_args()
d=json.loads(pathlib.Path(x.state).read_text()); cur=d.get("current",{})
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
    waivers=_waiver_store.gate_records(root,GATE_ID,current=cur)
    source="waiver_store"
else:
    waivers=declared
    source="agent_evidence_block"

for w in waivers:
    wid=w.get("waiver_id")
    derived=w.get("waiver_status")
    if derived and derived!="VALID":
        reason=_waiver_store.STATUS_FAIL_REASONS[derived]
        code={"WAIVER_REVALIDATION_REQUIRED":5,"WAIVER_REVOKED":6,
              "WAIVER_STATUS_UNKNOWN":7,"WAIVER_EXPIRED":3}[reason]
        print(json.dumps({"status":"FAIL","reason":reason,"waiver_id":wid,
                          "waiver_status":derived,
                          "detail":w.get("waiver_status_reason"),
                          "source":source})); sys.exit(code)
    if w.get("spec_revision")!=cur.get("spec_revision") or w.get("rtl_hash")!=cur.get("rtl_hash"):
        if not (w.get("revalidated") and w.get("revalidation_evidence_hash")):
            print(json.dumps({"status":"FAIL","reason":"STALE_WAIVER_AFTER_REVISION_CHANGE","waiver_id":wid,"source":source})); sys.exit(2)
    if w.get("expired") is True:
        print(json.dumps({"status":"FAIL","reason":"EXPIRED_WAIVER","waiver_id":wid,"source":source})); sys.exit(3)
print(json.dumps({"status":"PASS","waivers":len(waivers),"source":source}))
