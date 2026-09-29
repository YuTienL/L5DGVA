#!/usr/bin/env python3
"""assertion_placeholder_closure_gate.py -- STAGE_GATES["VERIFICATION_ARCHITECTURE"]
gate closing the observability_sufficiency_gate.py gap the checker-sva-
generator design report names explicitly: observability_sufficiency_gate.py
already requires every non-waived vPlan requirement to NAME an
ASSERTION/CHECKER evidence_point, but it never distinguishes "real
DSL-generated" from "still-a-placeholder". A requirement can satisfy that
gate today by pointing at an ASSERTION mechanism whose compiled SV is
nothing but `1'b1; // TODO: replace with evidence-backed temporal property`
(tools/observability/generate_observability_plan.py's ASSERTION branch,
before the state_machine_checks DSL wiring this task adds) -- observability
that only LOOKS closed.

This gate reads `implementation_manifest.json` (produced by
generate_observability_plan.py -- see that script's own "assertion_entries"
field, added by this same task) and FAILs the moment any assertion entry
whose planner-assigned "classification" is "PROTOCOL_STATE_MACHINE_LEGALITY"
(the design report's own "Q1: fully decidable from a finite, currently-
enumerable set of legal values/states plus a legality relation" verdict --
see the OBSERVABILITY/semantic-checker-planner, assertion-placement-planner,
scoreboard-checker-assertion-analyzer SKILL.md files' 3-question decision
procedure) STILL shows "generation_method": "placeholder" -- i.e. a
requirement the planner itself judged mechanically decidable via the
state_machine_checks DSL, but that never actually got compiled through it.

An entry with no "classification" (Q2/Q3/hand-authored territory, or a plan
predating this task) is never flagged -- this gate closes exactly the one
gap the design report scopes it to, not a general "every assertion must be
DSL-generated" policy (Q2/INTERRUPT_RESPONSE_SEMANTIC and Q3/
CROSS_CYCLE_TEMPORAL_INVARIANT requirements are explicitly still allowed to
be hand-authored placeholders/scaffolds per that same report's scope
boundary).

Same file shape as observability_sufficiency_gate.py (argparse, one JSON
arg, one JSON status line to stdout, a non-zero process exit code on
FAIL) -- reused deliberately, per the design report's own instruction to
mirror that gate's shape.
"""
import argparse
import json
import pathlib
import sys


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--implementation", required=True)
    a = ap.parse_args(argv)

    d = json.loads(pathlib.Path(a.implementation).read_text())
    entries = d.get("assertion_entries") or []

    unresolved = [
        e for e in entries
        if e.get("classification") == "PROTOCOL_STATE_MACHINE_LEGALITY"
        and e.get("generation_method") == "placeholder"
    ]
    if unresolved:
        print(json.dumps({
            "status": "FAIL",
            "reason": "STATE_MACHINE_LEGALITY_ASSERTION_STILL_PLACEHOLDER",
            "unresolved_target_ids": [e.get("target_id") for e in unresolved],
        }))
        return 2

    print(json.dumps({
        "status": "PASS",
        "assertion_entries_checked": len(entries),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
