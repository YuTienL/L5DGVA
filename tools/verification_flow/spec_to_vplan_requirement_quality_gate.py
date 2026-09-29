#!/usr/bin/env python3
"""REQUIREMENTS_TRACEABILITY requirement-quality gate.

Two layers, in this order:

1. The ORIGINAL agent-evidence shape check (unchanged behaviour, unchanged
   exit codes 2/3/4/5): every requirement must carry spec_ref / feature /
   expected_behavior / verification_method / coverage_goal, a flagged
   ambiguity must carry a resolution or an open question, and an
   UNSUPPORTED_BY_DUT requirement must carry design evidence.

2. A CANONICAL REQUIREMENT CONTRACT check (added 2026-09-06), for records
   that DECLARE themselves in that richer shape by carrying
   `contract_schema_version`. Spec section 184 names fifteen contract fields
   (ID / Source / Feature / Protocol / Configuration / Precondition /
   Stimulus / Expected Result / Observability / Checker / Coverage Intent /
   Priority / Criticality / Confidence / Status) and a five-value status
   vocabulary COMPLETE / PARTIAL / AMBIGUOUS / CONTRADICTORY / UNKNOWN; layer
   1 checks five of the fifteen and has no status vocabulary at all, so a
   contract-shaped record validated only by layer 1 would have its Protocol,
   Configuration, Precondition, Observability, Checker, Priority, Criticality
   and Confidence fields -- and its own status claim -- go entirely unchecked.
   Layer 2 runs `dv_harness.requirement_contract.analyze_requirement_contract_
   set()`, which re-DERIVES the status from the record's own content and FAILs
   a record that says COMPLETE while a field is still TBD, or that steps over
   an unresolved ambiguity/contradiction it filed itself.

   A contract-shaped record is validated by layer 2 INSTEAD of layer 1's
   five-field check, because the two shapes spell the same content
   differently (`req_id`/`expected_behavior` vs `requirement_id`/
   `expected_result`) and running layer 1 over a contract record would fail it
   for fields the contract deliberately renamed. Records in the older shape
   are untouched: a project that has not migrated is never retroactively
   failed by this addition.

   Layer 2 is FAIL-CLOSED on its own unavailability (exit 7). Unlike the
   optional cross-checks in the system_level_* gates, this layer is not
   opportunistic: the record EXPLICITLY asked to be held to the richer
   contract, so silently skipping the check would be the one outcome that
   turns a stricter declaration into a weaker gate.

   A CONTRADICTORY requirement stops here. This gate names the conflicting
   sources and refuses the requirement; it never picks which source wins --
   arbitrating between two disagreeing specification statements is a human
   engineering decision.

Exit codes: 0 PASS, 2 NO_REQUIREMENTS, 3 INCOMPLETE_VPLAN_REQUIREMENT,
4 UNRESOLVED_REQUIREMENT_AMBIGUITY, 5 UNSUPPORTED_WITHOUT_DESIGN_EVIDENCE,
6 REQUIREMENT_CONTRACT_VIOLATION, 7 REQUIREMENT_CONTRACT_VALIDATOR_UNAVAILABLE.
"""
import argparse
import json
import os
import pathlib
import sys


def _contract_layer(items):
    """Layer 2. Returns None when no record declares the contract shape."""
    contract_items = [r for r in items
                      if isinstance(r, dict) and "contract_schema_version" in r]
    if not contract_items:
        return None

    root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
    package_root = pathlib.Path(root) if root else pathlib.Path(__file__).resolve().parents[2]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    try:
        from dv_harness import requirement_contract as rc
    except ImportError as exc:
        return ({"status": "FAIL",
                 "reason": "REQUIREMENT_CONTRACT_VALIDATOR_UNAVAILABLE",
                 "detail": str(exc),
                 "contract_requirements": len(contract_items)}, 7)

    findings = []
    for record in contract_items:
        try:
            rc.validate_requirement_contract(record)
        except rc.RequirementContractValidationError as exc:
            findings.append({"severity": "ERROR", "code": "CONTRACT_SCHEMA_INVALID",
                             "requirement_id": record.get("requirement_id"),
                             "detail": str(exc)})

    result = rc.analyze_requirement_contract_set(contract_items)
    findings.extend(result["findings"])
    errors = [f for f in findings if f.get("severity") == "ERROR"]
    if errors:
        return ({"status": "FAIL", "reason": "REQUIREMENT_CONTRACT_VIOLATION",
                 "contract_requirements": len(contract_items),
                 "status_counts": result["status_counts"],
                 "findings": findings}, 6)
    return ({"status": "PASS", "contract_requirements": len(contract_items),
             "status_counts": result["status_counts"],
             "warnings": findings}, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--requirements', required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.requirements).read_text())
    items = d.get('requirements', [])
    if not items:
        print(json.dumps({'status': 'FAIL', 'reason': 'NO_REQUIREMENTS'}))
        sys.exit(2)

    contract = _contract_layer(items)
    if contract is not None and contract[1] != 0:
        print(json.dumps(contract[0]))
        sys.exit(contract[1])

    legacy = [r for r in items
              if not (isinstance(r, dict) and "contract_schema_version" in r)]
    for r in legacy:
        rid = r.get('req_id')
        for k in ('spec_ref', 'feature', 'expected_behavior', 'verification_method', 'coverage_goal'):
            if not r.get(k):
                print(json.dumps({'status': 'FAIL', 'reason': 'INCOMPLETE_VPLAN_REQUIREMENT',
                                  'req_id': rid, 'missing': k}))
                sys.exit(3)
        if r.get('ambiguity') and not r.get('ambiguity_resolution_or_question'):
            print(json.dumps({'status': 'FAIL', 'reason': 'UNRESOLVED_REQUIREMENT_AMBIGUITY',
                              'req_id': rid}))
            sys.exit(4)
        # waiver_candidate is derived from support_status, not separately self-asserted:
        # UNSUPPORTED_BY_DUT already implies "this is a waiver candidate" by definition.
        if r.get('support_status') == 'UNSUPPORTED_BY_DUT' and not r.get('design_evidence'):
            print(json.dumps({'status': 'FAIL', 'reason': 'UNSUPPORTED_WITHOUT_DESIGN_EVIDENCE',
                              'req_id': rid}))
            sys.exit(5)

    out = {'status': 'PASS', 'requirements': len(items)}
    if contract is not None:
        out['contract_requirements'] = contract[0]['contract_requirements']
        out['status_counts'] = contract[0]['status_counts']
        if contract[0].get('warnings'):
            out['warnings'] = contract[0]['warnings']
    print(json.dumps(out))


if __name__ == '__main__':
    main()
