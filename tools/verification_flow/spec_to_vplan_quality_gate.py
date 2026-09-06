#!/usr/bin/env python3
"""Spec-to-vPlan quality gate.

Standalone STAGE_GATES script, same fenced ```dv-harness-evidence:<gate_id>```
convention every other script in this directory uses: `gates.run_gate()`
extracts the agent's evidence block, JSON-dumps it to one temp file, and
invokes this script with a single CLI flag naming that file (see
`spec_to_vplan_requirement_quality_gate.py` in this same directory for the
identical one-flag contract this follows).

This gate is deliberately NOT `spec_to_vplan_requirement_quality_gate.py` and
does not replace it. That gate checks PER-REQUIREMENT completeness (five
required fields on one requirement record at a time, plus its own
`contract_schema_version` layer). This gate checks the SPEC-TO-VPLAN
TRANSFORM as a whole -- whether the set of vPlan items the agent produced
from a spec actually covers that spec, and whether every contradiction/
ambiguity the agent itself flagged while doing that transform was actually
closed rather than quietly left open. Four rules, matching the task's own
naming order (most severe first, so a run carrying several kinds of defect
still reports its worst one as `reason`, while `findings` always carries
every kind found in one pass rather than only the first):

1. **zero-critical-omission** -- every `spec_items[]` entry whose
   `criticality` is in `CRITICAL_TIERS` (P0/BLOCKER/CRITICAL) must be the
   target of at least one `vplan_items[].traces_to` entry. A critical spec
   requirement with no vPlan item tracing to it is CRITICAL_OMISSION, not a
   softer traceability gap -- the whole point of flagging criticality is
   that this one is not allowed to merely be noticed later.
2. **zero-unresolved-contradiction** -- every `contradictions[]` entry the
   agent filed must carry `resolved: true`, or a real `resolution`, or a
   named `open_question` for a human. One filed and never closed (the exact
   "quietly stop mentioning it" failure mode) is UNRESOLVED_CONTRADICTION.
   This gate never decides WHICH side of a contradiction is correct --
   arbitration is a human/source-authority decision (see
   `dv_harness/source_authority.py`'s own "not here" boundary for the
   general form of this same rule) -- it only refuses to let one pass
   silently unaddressed.
3. **zero-unresolved-ambiguity** -- identical shape, over `ambiguities[]`
   (the same "resolution/open_question, or FAIL" discipline
   `spec_to_vplan_requirement_quality_gate.py` already applies per-
   requirement, applied here across the whole vPlan).
4. **zero-traceability-gap** -- every remaining case where the spec<->vplan
   mapping does not close: a non-critical spec item nobody traced to, a
   vPlan item that traces to nothing, or a vPlan item's trace target naming
   a `spec_id` that does not exist in `spec_items[]` at all (a dangling
   reference -- evidence the agent typed a spec id that was never really
   supplied, never trusted as a real link).

This is a pure structural/consistency check over the fields the agent
supplies, exactly like every sibling script in this directory (e.g.
`coverage_quality_gate.py`) -- it proves the SET is internally coherent, not
that any individual spec/vplan claim is true against a real specification
document. No spec text, requirement content, or VIP/RTL behavior is invented
or read here.

Evidence shape (all four keys optional; an absent key reads as empty):
{
  "spec_items": [{"spec_id": "SPEC-1", "criticality": "P0", "text": "..."}],
  "vplan_items": [{"vplan_id": "VP-1", "traces_to": ["SPEC-1"]}],
  "contradictions": [{"contradiction_id": "C1", "description": "...",
                       "resolved": false, "resolution": "...",
                       "open_question": "Q-104"}],
  "ambiguities": [{"ambiguity_id": "A1", "description": "...",
                    "resolved": false, "resolution": "...",
                    "open_question": "Q-105"}]
}

Exit codes: 0 PASS, 2 NO_SPEC_ITEMS, 3 CRITICAL_OMISSION,
4 UNRESOLVED_CONTRADICTION, 5 UNRESOLVED_AMBIGUITY, 6 TRACEABILITY_GAP.
"""
import argparse
import json
import pathlib
import sys

CRITICAL_TIERS = {"P0", "BLOCKER", "CRITICAL"}

# Priority order matches the task's own four rule names, most severe first --
# a run carrying more than one kind of defect reports its worst one as
# `reason`, while `findings` still names every kind found in this one pass.
_PRIORITY = (
    ("critical_omission", "CRITICAL_OMISSION", 3),
    ("unresolved_contradiction", "UNRESOLVED_CONTRADICTION", 4),
    ("unresolved_ambiguity", "UNRESOLVED_AMBIGUITY", 5),
    ("traceability_gap", "TRACEABILITY_GAP", 6),
)


def _addressed(entry):
    """A contradiction/ambiguity entry counts as closed if it says so
    explicitly (resolved: true), carries real resolution text, or names a
    real open question filed for a human -- never on absence alone."""
    if not isinstance(entry, dict):
        return False
    if entry.get("resolved") is True:
        return True
    for key in ("resolution", "resolution_or_question", "open_question"):
        if entry.get(key):
            return True
    return False


def analyze(payload):
    """Pure function over the evidence dict. Returns (result_dict, exit_code)."""
    spec_items = payload.get("spec_items") or []
    vplan_items = payload.get("vplan_items") or []
    contradictions = payload.get("contradictions") or []
    ambiguities = payload.get("ambiguities") or []

    if not spec_items:
        return {"status": "FAIL", "reason": "NO_SPEC_ITEMS"}, 2

    spec_ids = {s.get("spec_id") for s in spec_items
                if isinstance(s, dict) and s.get("spec_id")}

    findings = {k: [] for k, _, _ in _PRIORITY}

    traced_spec_ids = set()
    for v in vplan_items:
        if not isinstance(v, dict):
            continue
        vid = v.get("vplan_id")
        traces = v.get("traces_to") or []
        if not traces:
            findings["traceability_gap"].append(
                {"vplan_id": vid, "reason": "VPLAN_ITEM_NOT_TRACED_TO_SPEC"})
            continue
        for t in traces:
            if t in spec_ids:
                traced_spec_ids.add(t)
            else:
                findings["traceability_gap"].append(
                    {"vplan_id": vid, "dangling_spec_ref": t,
                     "reason": "VPLAN_TRACE_TARGETS_UNKNOWN_SPEC_ID"})

    for s in spec_items:
        if not isinstance(s, dict):
            continue
        sid = s.get("spec_id")
        if not sid or sid in traced_spec_ids:
            continue
        if s.get("criticality") in CRITICAL_TIERS:
            findings["critical_omission"].append(
                {"spec_id": sid, "criticality": s.get("criticality")})
        else:
            findings["traceability_gap"].append(
                {"spec_id": sid, "reason": "SPEC_ITEM_NOT_TRACED"})

    for c in contradictions:
        if isinstance(c, dict) and not _addressed(c):
            findings["unresolved_contradiction"].append(
                {"contradiction_id": c.get("contradiction_id"),
                 "description": c.get("description")})

    for a in ambiguities:
        if isinstance(a, dict) and not _addressed(a):
            findings["unresolved_ambiguity"].append(
                {"ambiguity_id": a.get("ambiguity_id"),
                 "description": a.get("description")})

    non_empty = {k: v for k, v in findings.items() if v}
    for key, reason, code in _PRIORITY:
        if findings[key]:
            return {"status": "FAIL", "reason": reason, "findings": non_empty}, code

    return {"status": "PASS", "spec_items": len(spec_items),
            "vplan_items": len(vplan_items)}, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vplan-quality", required=True)
    a = ap.parse_args()
    payload = json.loads(pathlib.Path(a.vplan_quality).read_text())
    result, code = analyze(payload)
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
