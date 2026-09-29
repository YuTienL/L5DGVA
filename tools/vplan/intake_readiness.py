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

# BUG FIX (2026-09-01, commandtxt-vip-intake-gate-implementation): command.txt
# and VIP-reference material are two of the "Five Source Discovery" evidence
# categories CLAUDE.md/dashboard.py's real upload UI (_UPLOAD_CATEGORIES:
# spec/rtl/command_txt/vip_reference/de_sim) already collect real files for,
# and .dv-harness/vplan/intake_request.schema.json's "required_artifacts"
# already declares both as arrays of real file references -- but until now
# this gate never checked either key at all, so a SUBSYSTEM intake could
# reach READY_FOR_VPLAN with no command.txt/VIP-reference evidence supplied,
# or with a bare `true` attestation that named no real file. Unlike the
# boolean-attested fields above (protocol_spec, dut_design_spec, ...), the
# schema calls for these two to be real file paths, so `empty()` alone isn't
# enough: a non-empty value must also be well-formed (non-empty string(s))
# and name a file that actually exists on disk. cwd is the project root for
# every real invocation (see gates.run_gate's subprocess.run(..., cwd=str(root))),
# so a bare relative path here resolves exactly like focused_wave_debug_
# window_gate.py's existing bare-relative-path convention already does.
def _artifact_paths(value):
    """Normalizes a command_txt/vip_reference required_artifacts entry into
    a list of candidate path strings, or None if it isn't shaped as a
    string or a list at all."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    return None

def _artifact_path_evidence_missing(value):
    """True when `value` (already confirmed non-empty by empty()) is not
    well-formed, on-disk file evidence: every entry must be a non-empty
    string naming a file that actually exists."""
    paths = _artifact_paths(value)
    if not paths:
        return True
    for p in paths:
        if not isinstance(p, str) or not p.strip():
            return True
        if not pathlib.Path(p).exists():
            return True
    return False

if mode=="SUBSYSTEM":
    if not d.get("target_name"): missing.append("target_name")
    if not d.get("protocols"): missing.append("protocols")
    if empty("protocol_spec"): missing.append("protocol_spec")
    if empty("dut_design_spec"): missing.append("dut_design_spec")
    if empty("clock_reset_spec") and empty("phy_interface_spec") and empty("rtl_top_or_interface_files"):
        missing.append("interface_or_clock_reset_evidence")
    if empty("command_txt"):
        missing.append("command_txt")
    elif _artifact_path_evidence_missing(art.get("command_txt")):
        missing.append("command_txt_path_not_found")
    if empty("vip_reference"):
        missing.append("vip_reference")
    elif _artifact_path_evidence_missing(art.get("vip_reference")):
        missing.append("vip_reference_path_not_found")
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
