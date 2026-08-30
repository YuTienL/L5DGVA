#!/usr/bin/env python3
"""system_level_subsystem_set_completeness_gate

Closes a gap none of the three existing SYSTEM_LEVEL gates cover: whether the
SET of subsystems selected for system-level composition is itself complete.

- system_level_subsystem_verdict_gate  -> a declared system PASS never masks
  a real per-subsystem FAIL.
- system_level_traceability_gate       -> every SCENARIO spans >=2 subsystems
  and traces to requirements/mechanisms/coverage; every system_requirement_id
  is covered by some scenario.
- system_level_validator               -> every subsystem *entry that exists
  in the registry* carries its 5 required metadata fields.

None of the above ever asks "does the registry/scenario set even contain
every subsystem the DUT actually has?". A subsystem silently left out of
`selected_subsystems` entirely -- never registered, never scenario'd, never
mentioned -- passes all three gates above with no complaint. This gate is the
one that catches that silent omission. It deliberately does NOT re-check
scenario-internal requirement/mechanism/coverage tracing (traceability gate's
job), per-subsystem metadata completeness (validator's job), or verdict
masking (verdict gate's job) -- only subsystem-SET completeness.

Deterministic structural checks only: list/set completeness, duplicate/
unknown-id detection, waiver-approval presence. No RTL/system-behavior
semantic judgment.
"""
import argparse, json, pathlib, sys

VALID_WAIVER_STATUSES = {"WAIVED", "NOT_APPLICABLE"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subsystem-set", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.subsystem_set).read_text())

    # ---- applicability escape hatch (same pattern as fabric_topology_completeness_gate) ----
    if d.get("system_level_applicable") is False:
        reason = d.get("system_level_not_applicable_reason")
        if not reason:
            print(json.dumps({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}))
            return 2
        print(json.dumps({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}))
        return 0

    required_top = ["required_subsystems", "selected_subsystems", "subsystem_scenario_participation"]
    missing = [k for k in required_top if k not in d]
    if missing:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_FIELDS", "missing": missing}))
        return 3

    required = d.get("required_subsystems") or []
    selected = d.get("selected_subsystems") or []
    waivers = d.get("subsystem_waivers") or []
    scenarios = d.get("subsystem_scenario_participation") or []

    if not required:
        print(json.dumps({"status": "FAIL", "reason": "NO_REQUIRED_SUBSYSTEMS"}))
        return 4

    if len(set(required)) != len(required):
        dup = sorted({s for s in required if required.count(s) > 1})
        print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_REQUIRED_SUBSYSTEM", "duplicates": dup}))
        return 5

    if len(set(selected)) != len(selected):
        dup = sorted({s for s in selected if selected.count(s) > 1})
        print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_SELECTED_SUBSYSTEM", "duplicates": dup}))
        return 6

    required_set = set(required)
    selected_set = set(selected)

    unknown_selected = sorted(selected_set - required_set)
    if unknown_selected:
        print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_SELECTED_SUBSYSTEM",
                          "unknown": unknown_selected}))
        return 7

    # ---- per-subsystem waivers ----
    waived = {}
    seen_waiver_subsystems = set()
    for i, w in enumerate(waivers):
        name = w.get("subsystem")
        if name not in required_set:
            print(json.dumps({"status": "FAIL", "reason": "UNKNOWN_WAIVER_SUBSYSTEM",
                              "index": i, "subsystem": name}))
            return 8
        if name in seen_waiver_subsystems:
            print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_WAIVER_ENTRY", "subsystem": name}))
            return 9
        seen_waiver_subsystems.add(name)
        status = w.get("status")
        if status not in VALID_WAIVER_STATUSES:
            print(json.dumps({"status": "FAIL", "reason": "INVALID_WAIVER_STATUS",
                              "subsystem": name, "status": status}))
            return 10
        if not (w.get("waiver_approved") and w.get("waiver_evidence")):
            print(json.dumps({"status": "FAIL", "reason": "UNAPPROVED_SUBSYSTEM_WAIVER",
                              "subsystem": name}))
            return 11
        waived[name] = status

    # ---- every required, non-waived subsystem must be in selected_subsystems ----
    unselected = sorted((required_set - waived.keys()) - selected_set)
    if unselected:
        print(json.dumps({"status": "FAIL", "reason": "SUBSYSTEM_OMITTED_FROM_SELECTION",
                          "subsystems": unselected}))
        return 12

    # ---- scenario participation shape + unknown-id detection ----
    known_names = required_set | selected_set
    participation = {}  # subsystem -> set of scenario_ids it appears in
    seen_scenario_ids = set()
    for i, sc in enumerate(scenarios):
        sid = sc.get("scenario_id")
        if not sid:
            print(json.dumps({"status": "FAIL", "reason": "SCENARIO_MISSING_ID", "index": i}))
            return 13
        if sid in seen_scenario_ids:
            print(json.dumps({"status": "FAIL", "reason": "DUPLICATE_SCENARIO_ID", "scenario_id": sid}))
            return 14
        seen_scenario_ids.add(sid)
        parts = sc.get("participating_subsystems") or []
        unknown = sorted(set(parts) - known_names)
        if unknown:
            print(json.dumps({"status": "FAIL", "reason": "SCENARIO_UNKNOWN_SUBSYSTEM",
                              "scenario_id": sid, "unknown": unknown}))
            return 15
        for name in parts:
            participation.setdefault(name, set()).add(sid)

    # ---- core check: every required, non-waived subsystem participates in >=1 scenario ----
    unparticipating = sorted(
        s for s in required_set if s not in waived and not participation.get(s)
    )
    if unparticipating:
        print(json.dumps({"status": "FAIL", "reason": "SUBSYSTEM_MISSING_SCENARIO_PARTICIPATION",
                          "subsystems": unparticipating}))
        return 16

    print(json.dumps({
        "status": "PASS",
        "required_subsystem_count": len(required_set),
        "selected_subsystem_count": len(selected_set),
        "waived_subsystem_count": len(waived),
        "scenario_count": len(seen_scenario_ids),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
