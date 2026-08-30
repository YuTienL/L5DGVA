#!/usr/bin/env python3
# subsystem_environment_registration_gate (SIGNOFF) -- added 2026-08-28
# (plan-subsystem-registry design pass): the "Subsystem Environment Registry"
# concept (a central registry of BASELINE_READY subsystem environments that
# SYSTEM_LEVEL composition can select from) previously had an empty template
# file (.dv-harness/soc-composer/subsystem_environment_registry_template.json
# -- {"subsystems": []}) and zero code that ever wrote to it. This gate
# validates the SIGNOFF-time evidence that, on PASS, dv_harness/engine.py's
# _persist_subsystem_registry_entry() writes into the real runtime registry
# file (.dv-harness/soc-composer/subsystem_environment_registry.json,
# deliberately separate from the template above). Same escape-hatch
# convention as system_level_traceability_gate/system_level_validator/
# system_level_subsystem_set_completeness_gate: an explicit, justified
# decline is a legitimate PASS-equivalent (SKIPPED_NOT_APPLICABLE), not a
# forced FAIL for genuinely non-subsystem-reusable signoffs.
import argparse, json, pathlib, sys

REQUIRED = [
    "name",
    "environment_manifest",
    "release_sha",
    "qualification_state",
    "interface_compatibility",
    "clock_reset_compatibility",
]

# Same canonical 3-value enum already enforced by system_level_composition_gate.py
# and protocol_qualification_status_gate.py -- this gate does not invent a new one.
QUALIFICATION_STATES = {"SMOKE_QUALIFIED", "REGRESSION_QUALIFIED", "PRODUCTION_QUALIFIED"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", required=True)
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.entry).read_text())

    if d.get("registration_applicable") is False:
        reason = d.get("registration_not_applicable_reason")
        if not reason:
            print(json.dumps({"status": "FAIL", "reason": "NOT_APPLICABLE_WITHOUT_JUSTIFICATION"}))
            return 4
        print(json.dumps({"status": "SKIPPED_NOT_APPLICABLE", "reason": reason}))
        return 0

    missing = [k for k in REQUIRED if not d.get(k)]
    if missing:
        print(json.dumps({"status": "FAIL", "reason": "MISSING_REQUIRED_FIELDS", "missing": missing}))
        return 2

    if d.get("qualification_state") not in QUALIFICATION_STATES:
        print(json.dumps({"status": "FAIL", "reason": "INVALID_QUALIFICATION_STATE",
                           "value": d.get("qualification_state"),
                           "allowed": sorted(QUALIFICATION_STATES)}))
        return 3

    if d.get("interface_compatibility") != "PASS":
        print(json.dumps({"status": "FAIL", "reason": "INTERFACE_COMPATIBILITY_NOT_PASS",
                           "value": d.get("interface_compatibility")}))
        return 5

    if d.get("clock_reset_compatibility") != "PASS":
        print(json.dumps({"status": "FAIL", "reason": "CLOCK_RESET_COMPATIBILITY_NOT_PASS",
                           "value": d.get("clock_reset_compatibility")}))
        return 6

    print(json.dumps({"status": "PASS", "name": d.get("name")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
