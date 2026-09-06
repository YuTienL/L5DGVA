#!/usr/bin/env python3
"""scoreboard_generation_gate.py -- STANDALONE gate checking that every
`ScoreboardIR` record in a `dv_harness.verification_architecture` assembled
document is complete BEFORE scoreboard generation may proceed.

Standalone -- not registered in `dv_harness/gates.py`'s `STAGE_GATES` (see
this task's returned `gates_py_entry_snippet` for the integrator). Reads
the `scoreboard` array of an assembled verification-architecture JSON
document and FAILs when any record still carries an unfilled field
(`connectivity.SCOREBOARD_PLAN_FIELDS` sentinel, surfaced here as
`unfilled_fields`), is not `status: RESOLVED`, or is `comparable: false`
(real `phy_boundary`-derived boundary evidence for its two endpoints
disagrees) -- any of which means generating a scoreboard class from this
record would compile a comparator that either has a hole a human never
filled in, or compares two endpoints that structurally cannot agree.

Same file shape as `assertion_placeholder_closure_gate.py`.
"""
import argparse
import json
import pathlib
import sys


def evaluate(doc: dict) -> dict:
    scoreboards = doc.get("scoreboard") or []
    if not scoreboards:
        return {"status": "FAIL", "reason": "NO_SCOREBOARD_RECORDS",
                "detail": "the scoreboard array is empty -- nothing to generate from"}

    not_comparable = [s.get("scoreboard_id") for s in scoreboards if s.get("comparable") is False]
    unfilled = {s.get("scoreboard_id"): s.get("unfilled_fields")
                for s in scoreboards if s.get("unfilled_fields")}
    not_resolved = [s.get("scoreboard_id") for s in scoreboards if s.get("status") != "RESOLVED"]

    if not_comparable or unfilled or not_resolved:
        return {
            "status": "FAIL",
            "reason": "SCOREBOARD_IR_NOT_GENERATION_READY",
            "not_comparable_scoreboard_ids": not_comparable,
            "unfilled_fields_by_scoreboard_id": unfilled,
            "not_resolved_scoreboard_ids": not_resolved,
        }
    return {"status": "PASS", "scoreboard_records_checked": len(scoreboards)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--architecture", required=True,
                    help="path to a dv_harness.verification_architecture assembled JSON document")
    a = ap.parse_args(argv)

    doc = json.loads(pathlib.Path(a.architecture).read_text(encoding="utf-8"))
    result = evaluate(doc)
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
