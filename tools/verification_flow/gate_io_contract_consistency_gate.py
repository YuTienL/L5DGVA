#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--contracts", required=True)
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.contracts).read_text())

    for g in d.get("gates",[]):
        gid=g.get("gate_id")
        if not g.get("input_schema"):
            print(json.dumps({"status":"FAIL","reason":"GATE_WITHOUT_INPUT_SCHEMA","gate_id":gid})); return 2
        if not g.get("output_contract"):
            print(json.dumps({"status":"FAIL","reason":"GATE_WITHOUT_OUTPUT_CONTRACT","gate_id":gid})); return 3
        required=set(g.get("required_input_fields",[]))
        schema_fields=set(g.get("input_schema_fields",[]))
        if not required.issubset(schema_fields):
            print(json.dumps({"status":"FAIL","reason":"INPUT_SCHEMA_MISSING_REQUIRED_FIELDS",
                              "gate_id":gid,"missing":sorted(required-schema_fields)})); return 4
        allowed=set(g.get("allowed_statuses",[]))
        emitted=set(g.get("emitted_statuses",[]))
        if not emitted.issubset(allowed):
            print(json.dumps({"status":"FAIL","reason":"UNDECLARED_GATE_STATUS",
                              "gate_id":gid,"statuses":sorted(emitted-allowed)})); return 5

    print(json.dumps({"status":"PASS","gates":len(d.get("gates",[]))}))
    return 0

if __name__=="__main__":
    sys.exit(main())
