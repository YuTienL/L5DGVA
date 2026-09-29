#!/usr/bin/env python3
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument("--contract",required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.contract).read_text())
required={"SPEC","COMMAND_TXT","PRIMARY_PROTOCOL_REFERENCE","RTL_SOURCE","DE_LOCAL_SIM"}
provided=set(d.get("provided_source_classes",[]))
missing=sorted(required-provided)
if missing:
    print(json.dumps({"status":"FAIL","reason":"MISSING_CORE_INPUT_SOURCE","missing":missing})); sys.exit(2)
if d.get("protocol_input_kind") not in ("PUBLIC_STANDARD_SPEC","OFFICIAL_STANDARD_SPEC"):
    print(json.dumps({"status":"FAIL","reason":"PROTOCOL_INPUT_MUST_BE_STANDARD_SPEC"})); sys.exit(3)
for x in d.get("forbidden_user_prerequisites",[]):
    if x in {"BUILD","REGRESSION","VPLAN","CHECKER","WAVEFORM","LOGS","SYSTEM_LEVEL","HISTORY"}:
        print(json.dumps({"status":"FAIL","reason":"GENERATED_ARTIFACT_WRONGLY_REQUIRED_AS_INPUT","artifact":x})); sys.exit(4)
print(json.dumps({"status":"PASS"}))
