#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.sync).read_text())

    expected = d.get("expected_sha")
    actual = d.get("server_head_sha")
    if not expected or not actual:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_SHA"})); return 2
    if expected != actual:
        print(json.dumps({"status": "FAIL", "reason": "SERVER_HEAD_SHA_MISMATCH",
                           "expected_sha": expected, "server_head_sha": actual})); return 3

    for sm in d.get("submodules", []):
        name = sm.get("name")
        if not sm.get("expected_sha") or not sm.get("server_sha"):
            print(json.dumps({"status": "FAIL", "reason": "SUBMODULE_MISSING_SHA", "submodule": name})); return 4
        if sm.get("expected_sha") != sm.get("server_sha"):
            print(json.dumps({"status": "FAIL", "reason": "SUBMODULE_SHA_MISMATCH", "submodule": name,
                               "expected_sha": sm.get("expected_sha"), "server_sha": sm.get("server_sha")})); return 5

    print(json.dumps({"status": "PASS", "head_sha": actual, "submodules": len(d.get("submodules", []))}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
