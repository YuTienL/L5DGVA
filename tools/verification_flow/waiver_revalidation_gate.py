#!/usr/bin/env python3
"""waiver_revalidation_gate.py -- spec section 237 (WAIVER EXPIRATION /
REVALIDATION).

Since 2026-09-06 the waiver records this gate judges come from the project's
durable waiver ledger (dv_harness/waiver_store.py, .dv-harness/waivers/
waivers.json) whenever that ledger EXISTS -- not from the agent's own
```dv-harness-evidence:waiver_revalidation_gate``` block. Before that the
agent supplied both the waiver and the evidence the waiver was still valid,
so an expired waiver stopped being mentioned rather than being re-flagged.

Two things the store makes possible and self-attested evidence could not:
  - a waiver recorded in the ledger is evaluated on EVERY run, so its expiry
    re-flags the item it was waiving whether or not the agent mentions it;
  - a waiver_id the agent CITES that the ledger has no record of FAILs
    WAIVER_NOT_IN_STORE -- nobody approved it, so it exempts nothing.

A project with NO ledger keeps the original agent-attested behaviour and the
original exit codes byte-identically: adopting the store is a project's
decision and an un-migrated project is never retroactively failed.

Exit codes: 2 INVALID_WAIVER, 3 WAIVER_REVISION_STALE, 4 WAIVER_EXPIRED,
5 WAIVER_REVALIDATION_REQUIRED, 6 WAIVER_REVOKED, 7 WAIVER_STATUS_UNKNOWN,
8 WAIVER_NOT_IN_STORE, 9 WAIVER_STORE_UNAVAILABLE.
"""
import argparse,json,os,pathlib,sys,datetime

# Prefer the real dv_harness package location run_gate() already knows and
# passes via env (see dv_harness/gates.py); the parents[2] guess only holds in
# this repo's own dogfooding layout. Same idiom as rtl_write_scope_guard_gate.py.
_pkg_root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
sys.path.insert(0, str(pathlib.Path(_pkg_root) if _pkg_root else pathlib.Path(__file__).resolve().parents[2]))
try:
    from dv_harness import waiver_store as _waiver_store
except Exception:  # pragma: no cover - broken/partial deployment
    _waiver_store = None

GATE_ID = "waiver_revalidation_gate"

def parse(s): return datetime.datetime.fromisoformat(s.replace("Z","+00:00"))

def project_root():
    # run_gate() supplies the real project root; cwd is its fallback because
    # run_gate() also runs every gate with cwd=<project root>.
    return pathlib.Path(os.environ.get("DV_HARNESS_PROJECT_ROOT") or os.getcwd())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--waivers",required=True)
    ap.add_argument("--now",required=True)
    ap.add_argument("--current-revision",required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.waivers).read_text())
    now=parse(a.now)
    root=project_root()

    declared=d.get("waivers",[])
    if _waiver_store is None:
        # Fail closed: we cannot tell whether this project has a ledger, and
        # "we could not check" is never a pass (same choice the requirement-
        # contract layer in spec_to_vplan_requirement_quality_gate.py makes).
        print(json.dumps({"status":"FAIL","reason":"WAIVER_STORE_UNAVAILABLE",
                          "detail":"dv_harness.waiver_store is not importable"})); return 9
    if _waiver_store.store_exists(root):
        unbacked=_waiver_store.unbacked_declared_ids(root,GATE_ID,declared)
        if unbacked:
            print(json.dumps({"status":"FAIL","reason":"WAIVER_NOT_IN_STORE",
                              "waiver_ids":unbacked,
                              "store":str(_waiver_store._store_path(root))})); return 8
        waivers=_waiver_store.gate_records(root,GATE_ID,now=a.now,
                                           current={"revision":a.current_revision})
        source="waiver_store"
    else:
        waivers=declared
        source="agent_evidence_block"

    for w in waivers:
        wid=w.get("waiver_id")
        derived=w.get("waiver_status")
        if derived and derived!="VALID":
            reason=_waiver_store.STATUS_FAIL_REASONS[derived]
            code={"WAIVER_EXPIRED":4,"WAIVER_REVALIDATION_REQUIRED":5,
                  "WAIVER_REVOKED":6,"WAIVER_STATUS_UNKNOWN":7}[reason]
            print(json.dumps({"status":"FAIL","reason":reason,"waiver_id":wid,
                              "waiver_status":derived,
                              "detail":w.get("waiver_status_reason"),
                              "source":source})); return code
        if not (w.get("approved") and w.get("evidence")):
            print(json.dumps({"status":"FAIL","reason":"INVALID_WAIVER","waiver_id":wid,"source":source})); return 2
        if w.get("revision")!=a.current_revision and not w.get("revalidated_for_revision"):
            print(json.dumps({"status":"FAIL","reason":"WAIVER_REVISION_STALE","waiver_id":wid,"source":source})); return 3
        if w.get("expires_at") and now > parse(w["expires_at"]):
            print(json.dumps({"status":"FAIL","reason":"WAIVER_EXPIRED","waiver_id":wid,"source":source})); return 4
        if w.get("trigger_conditions_changed"):
            print(json.dumps({"status":"FAIL","reason":"WAIVER_REVALIDATION_REQUIRED","waiver_id":wid,"source":source})); return 5

    print(json.dumps({"status":"PASS","waivers":len(waivers),"source":source}))
    return 0

if __name__=="__main__":
    sys.exit(main())
