#!/usr/bin/env python3
"""SYSTEM_LEVEL composition gate.

Two layers, in this order:

1. The original agent-evidence shape check (unchanged behaviour, unchanged
   exit codes 2..10): >=2 subsystems, complete per-subsystem identity, no
   duplicate names, a valid qualification_state, interface/clock-reset
   compatibility both "PASS", and at least one genuinely cross-subsystem
   scenario over the named subsystems.

2. A REAL cross-subsystem cross-check (added 2026-09-05). Layer 1's
   `"interface_compatibility": "PASS"` / `"clock_reset_compatibility": "PASS"`
   are strings the agent writing the evidence block types itself, so a
   composition could pass this gate on a hand-typed claim while dv_harness's
   real SYS-9..SYS-14 analysis, run over the same subsystems, found two ACTIVE
   agents driving one physical interface. Layer 2 runs that real analysis
   (`system_resource_inventory.real_cross_subsystem_findings()` ->
   `analyze_selected_subsystem_resources()`) over the subsystems THIS
   composition names, and FAILs when an unresolved active-driver ownership
   conflict contradicts the claim that the set is composable.

   The conflict stops here at BLOCKED and requires a HUMAN to arbitrate
   ownership -- this gate never picks a winner between two conflicting drivers.

   `--project-root` defaults to the CWD, which dv_harness/gates.py's
   run_gate() already sets to the real project root for every gate subprocess
   (`cwd=str(root)`). When the real analysis cannot be run over real evidence
   (no registry, environments not on disk, or the analysis outran
   GATE_CROSSCHECK_BUDGET_SECONDS -- run_gate() kills a gate at 30s and does
   not catch the resulting TimeoutExpired), layer 2 reports
   SKIPPED_ANALYSIS_UNAVAILABLE with the concrete reason and changes no
   verdict -- an explicit "not checked", never a silent "clear".
"""
import argparse, json, os, pathlib, sys

REQUIRED_SUBSYSTEM_FIELDS = [
    "name","environment_manifest","release_sha","qualification_state",
    "interface_compatibility","clock_reset_compatibility"
]


def _crosscheck(composition, project_root):
    """Layer 2. Import failures degrade to an explicit unavailable result
    rather than crashing the gate -- same convention
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
    names = [str(s.get("name")) for s in (composition.get("selected_subsystems") or [])
             if isinstance(s, dict) and s.get("name")]
    findings = sri.real_cross_subsystem_findings(
        project_root, names, budget_seconds=sri.GATE_CROSSCHECK_BUDGET_SECONDS)
    return sri.crosscheck_declared_composition(composition, findings)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--composition", required=True)
    ap.add_argument("--project-root", default=None,
                    help="Project root holding .dv-harness/soc-composer/. Defaults to the "
                         "CWD, which run_gate() already sets to the real project root.")
    a=ap.parse_args()
    d=json.loads(pathlib.Path(a.composition).read_text())

    subs=d.get("selected_subsystems",[])
    if len(subs) < 2:
        print(json.dumps({"status":"FAIL","reason":"NEED_AT_LEAST_TWO_SUBSYSTEMS"}))
        return 2

    names=set()
    for s in subs:
        missing=[k for k in REQUIRED_SUBSYSTEM_FIELDS if not s.get(k)]
        if missing:
            print(json.dumps({"status":"FAIL","reason":"INCOMPLETE_SUBSYSTEM_IDENTITY","subsystem":s.get("name"),"missing":missing}))
            return 3
        if s["name"] in names:
            print(json.dumps({"status":"FAIL","reason":"DUPLICATE_SUBSYSTEM","subsystem":s["name"]}))
            return 4
        names.add(s["name"])
        if s["qualification_state"] not in ("REGRESSION_QUALIFIED","PRODUCTION_QUALIFIED","SMOKE_QUALIFIED"):
            print(json.dumps({"status":"FAIL","reason":"INVALID_QUALIFICATION_STATE","subsystem":s["name"]}))
            return 5
        if s["interface_compatibility"] != "PASS" or s["clock_reset_compatibility"] != "PASS":
            print(json.dumps({"status":"FAIL","reason":"SUBSYSTEM_COMPATIBILITY_FAIL","subsystem":s["name"]}))
            return 6

    scenarios=d.get("system_level_scenarios",[])
    if not scenarios:
        print(json.dumps({"status":"FAIL","reason":"NO_SYSTEM_LEVEL_SCENARIOS"}))
        return 7

    for sc in scenarios:
        participants=set(sc.get("participating_subsystems",[]))
        if not participants:
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_WITHOUT_PARTICIPANTS","scenario":sc.get("scenario_id")}))
            return 8
        unknown=participants-names
        if unknown:
            print(json.dumps({"status":"FAIL","reason":"SCENARIO_UNKNOWN_SUBSYSTEM","scenario":sc.get("scenario_id"),"unknown":sorted(unknown)}))
            return 9
        if len(participants) < 2:
            print(json.dumps({"status":"FAIL","reason":"NOT_CROSS_SUBSYSTEM_SCENARIO","scenario":sc.get("scenario_id")}))
            return 10

    crosscheck = _crosscheck(d, a.project_root or pathlib.Path.cwd())
    if crosscheck.get("status") == "FAIL":
        print(json.dumps({"status":"FAIL","reason":crosscheck["reason"],
                          "cross_subsystem_crosscheck":crosscheck}))
        return 11

    print(json.dumps({"status":"READY_FOR_SYSTEM_LEVEL","subsystem_count":len(subs),
                      "scenario_count":len(scenarios),
                      "cross_subsystem_crosscheck":crosscheck}))
    return 0

if __name__=="__main__":
    sys.exit(main())
