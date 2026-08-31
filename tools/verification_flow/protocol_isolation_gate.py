#!/usr/bin/env python3
"""protocol_isolation_gate.py -- CLAUDE.md's "No Golden-Reference Content
Mining" rule was prompt-only until this gate (2026-08-31 full-harness
wiring audit, finding B1): nothing at code level stopped an agent from
citing content out of a reference environment (e.g. USB_UVM_Handoff) as if
it were a primary VIP/DUT source. This gate reads the same evidence-ref
shape manual_lookup_before_edit_gate.py already consumes and FAILs if any
cited path resolves into a forbidden reference tree. It never blocks
absence of evidence (that gate's job) -- only a confident, real citation
into a forbidden tree, which is worse than an honest absence.
"""
import argparse, json, pathlib, sys

# Path segments (not substrings) that mark a reference-environment tree an
# agent must never cite as if it were a primary source. Tuple, not a single
# string, so future projects' reference environments can be added without
# restructuring the check.
FORBIDDEN_REFERENCE_TREES = ("USB_UVM_Handoff",)


def _cites_forbidden_tree(path_str):
    parts = pathlib.Path(path_str).resolve().parts
    for forbidden in FORBIDDEN_REFERENCE_TREES:
        if forbidden in parts:
            return forbidden
    return None


def _check_refs(refs):
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("path"):
            continue
        forbidden = _cites_forbidden_tree(ref["path"])
        if forbidden:
            return forbidden, ref["path"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edit", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.edit).read_text())

    # COUPLING NOTE (2026-08-31 final-review Critical fix): these 2 keys are
    # hardcoded to match manual_lookup_before_edit_gate.py's REAL evidence-ref
    # field names byte-for-byte -- that script's own `_verify_evidence_refs()`
    # now ALSO runs this same forbidden-tree check (imported from this module)
    # against the refs an agent is actually forced to supply for a VIP/DUT
    # edit, which is what actually closes B1 (this gate's own evidence block
    # is a separate, agent-optional block that PASSes empty by design -- see
    # this file's module docstring). If manual_lookup_before_edit_gate.py
    # ever grows a THIRD evidence-ref field, add it here too, or a citation
    # through that new field silently escapes both checks.
    for key in ("vip_evidence_refs", "dut_rtl_evidence_refs"):
        hit = _check_refs(d.get(key))
        if hit:
            forbidden, path = hit
            print(json.dumps({
                "status": "FAIL", "reason": "REFERENCE_TREE_CITATION_FORBIDDEN",
                "field": key, "path": path, "forbidden_tree": forbidden,
            }))
            return 2

    print(json.dumps({"status": "PASS"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
