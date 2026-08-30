import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--closure",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.closure).read_text()); req=["rca_id","attribution","reproducer_hash","fix_commit_hash","rerun_evidence_hash"]
miss=[k for k in req if not d.get(k)]
if miss: print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_RCA_FIX_CLOSURE","missing":miss})); sys.exit(2)
if d.get("replay_equivalent") is not True: print(json.dumps({"status":"FAIL","reason":"FIX_RERUN_NOT_REPLAY_EQUIVALENT"})); sys.exit(3)
if d.get("pre_fix_result")!="FAIL" or d.get("post_fix_result")!="PASS": print(json.dumps({"status":"FAIL","reason":"FIX_EFFECTIVENESS_NOT_PROVEN"})); sys.exit(4)
if d.get("attribution_confidence") not in ("HIGH","VERIFIED"): print(json.dumps({"status":"FAIL","reason":"RCA_CONFIDENCE_TOO_LOW_FOR_CLOSURE"})); sys.exit(5)

# Optional cross-check: if a boundary_trace (same shape as failure_attribution.py's
# input) is supplied, independently re-derive TB_BUG/DUT_BUG/UNKNOWN via the same
# positional rule instead of accepting "attribution" as an unvalidated free string.
# Absent boundary_trace, behavior is identical to before this check existed.
bt=d.get("boundary_trace")
if bt:
    try:
        first=None
        for s in bt:
            if s.get("expected") != s.get("observed"): first=s; break
        derived="UNKNOWN"
        if first:
            st=first.get("stage")
            if st in ("SEQUENCE","DRIVER","MONITOR","CHECKER","SCOREBOARD"): derived="TB_BUG"
            elif st in ("DUT_INTERNAL","INTERFACE_OUT"): derived="DUT_BUG"
            elif st=="INTERFACE_IN": derived="UNKNOWN"
        if derived in ("TB_BUG","DUT_BUG") and d.get("attribution") != derived:
            print(json.dumps({"status":"FAIL","reason":"ATTRIBUTION_CONTRADICTS_BOUNDARY_TRACE",
                              "derived_classification":derived,"stated_attribution":d.get("attribution")})); sys.exit(6)
    except AttributeError:
        print(json.dumps({"status":"FAIL","reason":"MALFORMED_BOUNDARY_TRACE"})); sys.exit(7)

print(json.dumps({"status":"PASS"}))
