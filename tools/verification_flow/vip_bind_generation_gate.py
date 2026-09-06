#!/usr/bin/env python3
"""vip_bind_generation_gate.py -- STANDALONE gate checking that every
`VipBindIR` record in a `dv_harness.verification_architecture` assembled
document is complete BEFORE bind/hookup generation may proceed.

This is a standalone script, not registered in `dv_harness/gates.py`'s
`STAGE_GATES` (the integrator adds that entry -- see this task's returned
`gates_py_entry_snippet`). It reads the `vip_bind` array of an assembled
verification-architecture JSON document (produced by
`dv_harness.verification_architecture.assemble_verification_architecture()`,
minus its Python-only `_irs` key) and FAILs when any record is not
`status: RESOLVED`, or when a real placement conflict
(`VIP_AFTER_BRIDGE`) names it -- generating a bind file for a target the
architecture layer itself flagged as unresolved or in conflict would
create exactly the "generated a plausible-looking artifact from an
incomplete plan" failure this gate exists to stop before it costs a
compile.

Same file shape as `assertion_placeholder_closure_gate.py` (argparse, one
JSON arg, one JSON status line to stdout, a non-zero process exit code on
FAIL) -- reused deliberately rather than inventing a second gate-script
shape.
"""
import argparse
import json
import pathlib
import sys


def _conflicting_targets(doc: dict) -> set:
    targets = set()
    for f in doc.get("placement_conflicts") or []:
        if f.get("kind") == "VIP_AFTER_BRIDGE":
            t = f.get("target_instance")
            if t:
                targets.add(t)
    return targets


def evaluate(doc: dict) -> dict:
    binds = doc.get("vip_bind") or []
    if not binds:
        return {"status": "FAIL", "reason": "NO_VIP_BIND_RECORDS",
                "detail": "the vip_bind array is empty -- nothing to generate from"}

    conflicting = _conflicting_targets(doc)
    unresolved = [b.get("target_instance") for b in binds if b.get("status") != "RESOLVED"]
    in_conflict = [b.get("target_instance") for b in binds if b.get("target_instance") in conflicting]

    if unresolved or in_conflict:
        return {
            "status": "FAIL",
            "reason": "VIP_BIND_IR_NOT_GENERATION_READY",
            "unresolved_target_instances": unresolved,
            "targets_in_placement_conflict": in_conflict,
        }
    return {"status": "PASS", "vip_bind_records_checked": len(binds)}


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
