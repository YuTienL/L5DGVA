#!/usr/bin/env python3
"""assertion_generation_gate.py -- STANDALONE gate checking that every
`AssertionIR` record in a `dv_harness.verification_architecture` assembled
document is complete BEFORE assertion (SVA) generation may proceed.

Standalone -- not registered in `dv_harness/gates.py`'s `STAGE_GATES` (see
this task's returned `gates_py_entry_snippet` for the integrator). Reads
the `assertion` array of an assembled verification-architecture JSON
document and FAILs when any record's `clock_domain_match` or
`reset_domain_match` is `false` (the declared domain is not among this
DUT's real declared clock/reset domains -- `env_manifest.
build_dut_facts_clock_reset()`'s own evidence, not a guess), or when a
record is not `status: RESOLVED`. Generating SVA against a clock/reset
domain the DUT does not have would compile silently and assert on the
wrong edge forever -- exactly the failure this gate exists to catch before
it costs a compile+sim cycle.

Same file shape as `assertion_placeholder_closure_gate.py`.
"""
import argparse
import json
import pathlib
import sys


def evaluate(doc: dict) -> dict:
    assertions = doc.get("assertion") or []
    if not assertions:
        return {"status": "FAIL", "reason": "NO_ASSERTION_RECORDS",
                "detail": "the assertion array is empty -- nothing to generate from"}

    wrong_clock = [a.get("assertion_id") for a in assertions if a.get("clock_domain_match") is False]
    wrong_reset = [a.get("assertion_id") for a in assertions if a.get("reset_domain_match") is False]
    not_resolved = [a.get("assertion_id") for a in assertions if a.get("status") != "RESOLVED"]

    if wrong_clock or wrong_reset or not_resolved:
        return {
            "status": "FAIL",
            "reason": "ASSERTION_IR_NOT_GENERATION_READY",
            "wrong_clock_domain_assertion_ids": wrong_clock,
            "wrong_reset_domain_assertion_ids": wrong_reset,
            "not_resolved_assertion_ids": not_resolved,
        }
    return {"status": "PASS", "assertion_records_checked": len(assertions)}


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
