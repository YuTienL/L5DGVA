#!/usr/bin/env python3
import argparse,json,pathlib,sys
REQ={
"INTERACTIVE_INTAKE","SPEC_RTL_DISCOVERY","COMMAND_ANALYSIS","REFERENCE_UVM",
"DE_BASELINE","VPLAN","VERIFICATION_ARCHITECTURE","OBSERVABILITY",
"SCOREBOARD_CHECKER_ASSERTION","TEST_GENERATION","NEGATIVE_TEST",
"LOCAL_SIM","SEMANTIC_TRUE_PASS","FALSE_PASS_RESISTANCE","LSF_REGRESSION",
"REMOTE","RCA","DUT_TB_BUG_CLASSIFICATION","COVERAGE_CLOSURE",
"SYSTEM_LEVEL","EXPERT_FEEDBACK","SIGNOFF","FEATURE_CONTINUITY"
}
ap=argparse.ArgumentParser(); ap.add_argument("--catalog",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.catalog).read_text())
present={x.get("capability_id") for x in d.get("capabilities",[]) if x.get("implemented") and x.get("test_evidence")}
missing=sorted(REQ-present)
if missing:
    print(json.dumps({"status":"FAIL","reason":"PLATFORM_CAPABILITY_INCOMPLETE","missing":missing})); sys.exit(2)
print(json.dumps({"status":"PASS","capabilities":len(present)}))
