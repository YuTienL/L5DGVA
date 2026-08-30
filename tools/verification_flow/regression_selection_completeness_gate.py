#!/usr/bin/env python3
import argparse, json, pathlib, sys

CATEGORIES = ["targeted_tests", "dependency_tests", "safety_tests", "mandatory_signoff_tests"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.selection).read_text())

    for cat in CATEGORIES:
        tests = d.get(cat, [])
        if not tests and not d.get(cat + "_empty_reason"):
            print(json.dumps({"status": "FAIL", "reason": "EMPTY_SELECTION_CATEGORY_WITHOUT_REASON",
                               "category": cat})); return 2

    src = d.get("selection_source", {})
    if not src.get("change_impact_evidence_id"):
        print(json.dumps({"status": "FAIL", "reason": "MISSING_CHANGE_IMPACT_LINK"})); return 3

    print(json.dumps({"status": "PASS",
                       "counts": {c: len(d.get(c, [])) for c in CATEGORIES}}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
