#!/usr/bin/env python3
import argparse,json,pathlib,sys
REQ={
"STEP_BY_STEP_INTERACTIVE","FIVE_CORE_INPUTS","SPEC","COMMAND_TXT","USB_STANDARD_REFERENCE",
"REFERENCE_UVM","RTL_FIRST_ARCH_DISCOVERY","DE_LOCAL_SIM_BASELINE","VPLAN_FIRST",
"VERIFICATION_ARCHITECTURE","SCOREBOARD_CHECKER_ASSERTION","TEST_GENERATION",
"NEGATIVE_TEST","LOCAL_SIM","COMMAND_SIMLOG_SEMANTIC","FALSE_PASS_DEFENSE",
"DUT_TB_BUG_CLASSIFICATION","WAVEFORM_RCA","PROTOCOL_CORNER_CASE",
"LSF_REGRESSION","PER_JOB_MONITOR","REMOTE","COVERAGE_CLOSURE","SYSTEM_LEVEL",
"EXPERT_FEEDBACK","SIGNOFF","FEATURE_CONTINUITY","EVIDENCE_PROVENANCE"
}
ap=argparse.ArgumentParser(); ap.add_argument("--matrix",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.matrix).read_text())
present={x.get("requirement_id") for x in d.get("requirements",[])
         if x.get("implemented") and x.get("pytest_evidence") and x.get("hard_gate")}
missing=sorted(REQ-present)
if missing:
    print(json.dumps({"status":"FAIL","reason":"MASTER_REQUIREMENT_INCOMPLETE","missing":missing})); sys.exit(2)
print(json.dumps({"status":"PASS","requirements":len(present)}))
