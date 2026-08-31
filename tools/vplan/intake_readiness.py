#!/usr/bin/env python3
# NOTICE (corrected 2026-08-28): the original NOTICE below claimed this
# module was "NOT invoked by any executing code path" -- that is now STALE,
# per CLAUDE.md's own Evidence Truth Rule ("current evidence wins and this
# file must be updated"). This script is wired into dv_harness/gates.py's
# STAGE_GATES["INTAKE"]. Original NOTICE text, now superseded: "this module
# is NOT invoked by any executing code path in dv_harness/ or
# .claude/agents/*.md as of this audit -- it is standalone/orphaned code."
import argparse,json,pathlib,sys
ap=argparse.ArgumentParser(); ap.add_argument('--intake',required=True); a=ap.parse_args()
d=json.loads(pathlib.Path(a.intake).read_text())
mode=d.get("mode"); art=d.get("required_artifacts",{})
missing=[]
def empty(k): return not art.get(k)
if mode=="SUBSYSTEM":
    if not d.get("target_name"): missing.append("target_name")
    if not d.get("protocols"): missing.append("protocols")
    if empty("protocol_spec"): missing.append("protocol_spec")
    if empty("dut_design_spec"): missing.append("dut_design_spec")
    if empty("clock_reset_spec") and empty("phy_interface_spec") and empty("rtl_top_or_interface_files"):
        missing.append("interface_or_clock_reset_evidence")
    protocols_lower = {str(p).lower() for p in (d.get("protocols") or [])}
    if protocols_lower & {
        "amba", "amba4-soc", "axi", "ahb", "apb",
        "apb2", "apb3", "ahb-lite", "axi3", "axi4", "ace-lite", "axi-stream",
    }:
        if empty("fabric_topology_spec"):
            missing.append("fabric_topology_evidence")
    if protocols_lower & {"sd", "sdio", "sd-sdio"}:
        if empty("uhs_tuning_spec"):
            missing.append("uhs_tuning_evidence")
elif mode=="SYSTEM_LEVEL":
    if not d.get("target_name"): missing.append("target_name")
    if not d.get("selected_subsystems"): missing.append("selected_subsystems")
    if empty("system_level_use_cases"): missing.append("system_level_use_cases")
    # identities can be supplied through existing env/manifests in this simplified local gate
    if empty("existing_uvm_env"): missing.append("subsystem_identity_or_manifest")
else:
    missing.append("valid_mode")
out={"mode":mode,"readiness":"READY_FOR_VPLAN" if not missing else "COLLECTING","missing":missing}
print(json.dumps(out,indent=2))
sys.exit(0 if not missing else 3)
