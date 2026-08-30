#!/usr/bin/env python3
import argparse, json, pathlib, sys

ALLOWED_STRATEGIES = {"FETCH_ONLY", "MERGE", "REBASE", "FAST_FORWARD"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.sync).read_text())

    if not d.get("fetch_output"):
        print(json.dumps({"status": "FAIL", "reason": "NO_FETCH_EVIDENCE"})); return 2

    strategy = d.get("sync_strategy")
    if strategy not in ALLOWED_STRATEGIES:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_SYNC_STRATEGY", "strategy": strategy})); return 3

    if d.get("destructive_command_used"):
        print(json.dumps({"status": "FAIL", "reason": "DESTRUCTIVE_GIT_COMMAND_USED"})); return 4

    pre_dirty = set(d.get("pre_sync_dirty_paths", []))
    accounted = d.get("accounted_paths", {})
    covered = set(accounted.get("stashed", [])) | set(accounted.get("committed", [])) | set(accounted.get("preserved_untouched", []))
    unaccounted = sorted(pre_dirty - covered)
    if unaccounted:
        print(json.dumps({"status": "FAIL", "reason": "UNRELATED_CHANGE_UNACCOUNTED", "paths": unaccounted})); return 5

    print(json.dumps({"status": "PASS", "strategy": strategy, "pre_sync_dirty_count": len(pre_dirty)}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
