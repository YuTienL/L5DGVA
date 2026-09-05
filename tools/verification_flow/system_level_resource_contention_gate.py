#!/usr/bin/env python3
"""SYSTEM_LEVEL shared-resource contention gate.

Two layers, in this order:

1. The original agent-evidence shape check (unchanged behaviour, unchanged
   exit codes 2/3): a scenario touching a declared shared resource must carry
   an arbitration/contention policy and non-empty contention testcase ids.

2. A REAL cross-subsystem cross-check (added 2026-09-05). Layer 1 only ever
   read the agent's own JSON, so a hand-typed `"shared_resources": []` passed
   this gate while dv_harness's real SYS-9..SYS-14 analysis, run over the same
   subsystems, found two ACTIVE agents driving one physical interface. Layer 2
   runs that real analysis (`system_resource_inventory.
   real_cross_subsystem_findings()` -> `analyze_selected_subsystem_resources()`)
   and FAILs when it CONTRADICTS the declaration.

   The subsystem set is the REAL registered one
   (.dv-harness/soc-composer/subsystem_environment_registry.json, written only
   by engine.py's _persist_subsystem_registry_entry() on a gate-validated
   SIGNOFF PASS), resolved from the project root -- never from the agent's
   payload. `--project-root` defaults to the CWD, which is what
   dv_harness/gates.py's run_gate() already sets for every gate subprocess
   (`cwd=str(root)`); a plan may narrow the set with an optional
   `"selected_subsystems": [...]` name list.

   A DRIVER_CONFLICT stops here at BLOCKED and requires a HUMAN to arbitrate
   ownership -- this gate never picks a winner between two conflicting drivers.

   When the real analysis cannot be run over real evidence (no registry, fewer
   than two subsystems, environments not on disk, or the analysis outran
   GATE_CROSSCHECK_BUDGET_SECONDS -- run_gate() kills a gate at 30s and does
   not catch the resulting TimeoutExpired), layer 2 reports
   SKIPPED_ANALYSIS_UNAVAILABLE with the concrete reason and changes no
   verdict. That degradation is explicit, never a silent "clear".
"""
import argparse
import json
import os
import pathlib
import sys


def _crosscheck(plan, project_root):
    """Layer 2. Import failures degrade to an explicit
    CROSSCHECK_UNAVAILABLE rather than crashing the gate -- same convention
    tools/real_env/system_level_validator.py's _classify() already uses for
    its own optional dv_harness import."""
    root = os.environ.get("DV_HARNESS_PACKAGE_ROOT")
    package_root = pathlib.Path(root) if root else pathlib.Path(__file__).resolve().parents[2]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    try:
        from dv_harness import system_resource_inventory as sri
    except ImportError as exc:
        return {"status": "SKIPPED_ANALYSIS_UNAVAILABLE",
                "reason": "CROSSCHECK_UNAVAILABLE", "detail": str(exc)}
    selected = plan.get("selected_subsystems") or None
    findings = sri.real_cross_subsystem_findings(
        project_root, selected, budget_seconds=sri.GATE_CROSSCHECK_BUDGET_SECONDS)
    return sri.crosscheck_declared_contention_plan(plan, findings)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--project-root", default=None,
                    help="Project root holding .dv-harness/soc-composer/. Defaults to the "
                         "CWD, which run_gate() already sets to the real project root.")
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.plan).read_text())
    shared = set(d.get("shared_resources", []))

    for sc in d.get("scenarios", []):
        sid = sc.get("scenario_id")
        cont = set(sc.get("resources", [])) & shared
        if cont and not sc.get("arbitration_or_contention_policy"):
            print(json.dumps({"status": "FAIL",
                              "reason": "SHARED_RESOURCE_WITHOUT_CONTENTION_POLICY",
                              "scenario_id": sid}))
            return 2
        if cont and not sc.get("contention_testcase_ids"):
            print(json.dumps({"status": "FAIL", "reason": "NO_CONTENTION_TESTS",
                              "scenario_id": sid}))
            return 3

    crosscheck = _crosscheck(d, a.project_root or pathlib.Path.cwd())
    if crosscheck.get("status") == "FAIL":
        print(json.dumps({"status": "FAIL", "reason": crosscheck["reason"],
                          "cross_subsystem_crosscheck": crosscheck}))
        return 4

    print(json.dumps({"status": "PASS", "cross_subsystem_crosscheck": crosscheck}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
