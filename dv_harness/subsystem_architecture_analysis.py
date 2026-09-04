"""SYS-5 and SYS-6 of the System-Level Verification Integration workflow: one
INDEPENDENT analysis workflow per selected subsystem, and the per-subsystem
verification-architecture report each of them produces.

  SYS-5  "Open an independent workflow for every selected subsystem. Parallel
          analysis is allowed when safe. Do not contaminate local evidence
          before each subsystem analysis is complete. Cross-subsystem
          synthesis happens afterward."
  SYS-6  "Determine DUT hierarchy, UVM top/env, agents, VIPs, active/passive
          mode, sequencers, drivers, monitors, virtual sequencers, scoreboards,
          reference models, predictors, coverage collectors, assertions/
          checkers, config objects, virtual interfaces, clock/reset,
          interrupts, DMA, firmware interaction, register model, memory model,
          address map, build/run/regression/waveform/fsdbreport flows.
          Use source/config evidence, not documentation alone."

WHY A NEW MODULE. Both requirements operate on MANY subsystems at once and
have no single-subsystem home. env_manifest.py is, and stays, the sole writer
of ONE environment's env.manifest.json; run_profile.py is, and stays, the IR
of ONE Makefile. Neither knows what a subsystem is, neither can be handed a
set of them, and neither could host SYS-5's isolation rule -- which is a
property OF a set. This module IMPORTS both and composes them; it re-derives
nothing either of them already computes, and it never writes to either's
artifacts.

  env_manifest.load_env_manifest()      -> hierarchy / VIPs / registers /
                                           address map / clock-reset / RTL
  run_profile.load_run_profile()        -> build / run / regression /
                                           waveform / fsdbreport flows
  reference_pattern_audit (SYS-7)       -> command.txt grammar + interrupt
                                           waits + DMA + firmware evidence
  subsystem_command_contract (SYS-8)    -> the contracts and cross-subsystem
                                           conflicts the synthesis reports
  subsystem_discovery (SYS-1..4)        -> the candidate rows an analysis is
                                           opened FOR, and one definition of
                                           what a command.txt is named

SEMANTIC COMPONENT ROLES, AND THEIR HONESTY LIMIT. SYS-6 asks which component
is a scoreboard, which is a predictor, which is a coverage collector. A real
`+ENV_TOPOLOGY_DUMP_PATH` capture records `type_name` -- the environment
author's own class name -- and nothing else that bears on role. So
`classify_component_roles()` is a NAME-TOKEN classifier and says so on every
row: the matched token and the field it matched in are carried as the basis, a
component matching nothing is UNCLASSIFIED rather than assigned a plausible
role, and `is_active` is never inferred from a name because the dump already
carries the real `get_is_active()` value. A project may declare exact role
assignments, which beat the tokens entirely.

WHAT THIS MODULE DOES NOT DO. Discovery/analysis/planning/reporting only, per
the master prompt's own SYS-39 stop condition. It reads a subsystem's
artifacts and writes a report; it generates no System-Level UVM source, no
System command.txt, no System Virtual Sequencer and no command routing. That
is SYS-40 and requires a separate explicit human approval.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import reference_pattern_audit as rpa
from . import subsystem_command_contract as scc
from . import subsystem_discovery as sd

# SYS-6's field list, verbatim and in its own order. Held to the analyzer's own
# output keys by a test, so a field cannot be quietly dropped from the report.
SYS6_FIELDS: tuple = (
    "dut_hierarchy",
    "uvm_top_env",
    "agents",
    "vips",
    "active_passive_mode",
    "sequencers",
    "drivers",
    "monitors",
    "virtual_sequencers",
    "scoreboards",
    "reference_models",
    "predictors",
    "coverage_collectors",
    "assertions_checkers",
    "config_objects",
    "virtual_interfaces",
    "clock_reset",
    "interrupts",
    "dma",
    "firmware_interaction",
    "register_model",
    "memory_model",
    "address_map",
    "build_run_regression_waveform_fsdbreport_flows",
)

# Per-field evidence status. DERIVED means real artifacts answered it;
# NOT_AVAILABLE means the artifact that would answer it was not captured (and
# the reason names the real command that produces it); NOT_APPLICABLE means
# the artifact WAS captured and genuinely contains none of this thing. The
# third is the one that is usually collapsed into the second, and the two are
# opposite findings: "nobody looked" versus "we looked and there are none".
DERIVED = "DERIVED"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
FIELD_STATUSES: tuple = (DERIVED, NOT_AVAILABLE, NOT_APPLICABLE)

# UVM component role tokens, most specific first -- "virtual_sequencer" must be
# tested before "sequencer" or every virtual sequencer is classified as a plain
# one. Tokens are matched against the component's type_name first and its
# full_name second, and the matched token AND field are recorded as the basis.
COMPONENT_ROLE_TOKENS: tuple = (
    ("virtual_sequencer", ("virtual_sequencer", "vsequencer", "v_sequencer", "vseqr", "virt_seqr")),
    ("coverage_collector", ("coverage_collector", "covergroup", "coverage", "_cov", "subscriber")),
    ("reference_model", ("reference_model", "ref_model", "refmodel", "golden_model", "_refm")),
    ("predictor", ("predictor", "_pred")),
    ("scoreboard", ("scoreboard", "_scbd", "_sb")),
    ("assertions_checker", ("checker", "assertion", "_chk", "_assert")),
    ("sequencer", ("sequencer", "seqr")),
    ("driver", ("driver", "_drv")),
    ("monitor", ("monitor", "_mon")),
    ("agent", ("agent", "_agt")),
    ("config_object", ("_config", "_cfg", "config_object")),
    ("env", ("_env", "environment")),
)
COMPONENT_ROLES: tuple = tuple(role for role, _ in COMPONENT_ROLE_TOKENS) + ("UNCLASSIFIED",)

INTERRUPT_PORT_TOKENS: tuple = ("irq", "intr", "interrupt", "_int_", "int_o", "eint")
DMA_PORT_TOKENS: tuple = ("dma", "descriptor", "_axi_", "scatter")
VIRTUAL_INTERFACE_TOKENS: tuple = ("vif", "virtual_interface", "virtual ")
FIRMWARE_TOKENS: tuple = ("fw", "firmware", "branch_fw", "fillmem", "readmem")


class CrossContaminationError(RuntimeError):
    """Raised when one subsystem's analysis read a path belonging to another
    selected subsystem's environment tree. SYS-5's isolation rule is the
    reason this is an exception and not a warning: an analysis that has
    already read a neighbour's evidence cannot be un-contaminated after the
    fact, so the run must stop rather than produce a synthesis nobody can
    trust."""


@dataclass
class SubsystemAnalysisInputs:
    """Everything ONE subsystem's independent analysis is allowed to read.

    Building this list up front, per subsystem, is what makes SYS-5's
    isolation checkable: the analyzer reads only from here, records every path
    it actually opened, and `assert_no_cross_contamination()` compares those
    reads against the OTHER subsystems' roots."""
    subsystem_id: str
    environment_root: str = ""
    env_manifest_path: str = ""
    run_profile_path: str = ""
    hierarchy_path: str = ""
    command_files: List[str] = field(default_factory=list)
    declared_component_roles: Dict[str, str] = field(default_factory=dict)
    region_clock_map: Dict[str, str] = field(default_factory=dict)


def discover_command_files(env_root, limit: int = 64) -> List[str]:
    """Every command.txt-shaped file under one environment tree.

    Reuses `subsystem_discovery.ARTIFACT_GLOBS["command_txt"]` and its bounded
    walk rather than restating what a command.txt is named -- two definitions
    of that in one codebase is how the SYS-2 existence probe and the SYS-7
    analyzer would come to disagree about whether a subsystem has one."""
    import fnmatch
    if not env_root:
        return []
    walk = sd._walk_relative_paths(Path(env_root))
    if not walk["readable"]:
        return []
    globs = sd.ARTIFACT_GLOBS["command_txt"]
    hits = [rel for rel in walk["paths"] if any(fnmatch.fnmatch(rel, g) for g in globs)]
    return [str(Path(env_root) / rel) for rel in sorted(hits)[:limit]]


def inputs_from_discovery_row(row: Mapping[str, Any], *,
                              declared: Optional[Mapping[str, Any]] = None,
                              ) -> SubsystemAnalysisInputs:
    """Build one subsystem's analysis inputs from its SYS-1 discovery row.

    A project may declare exact paths (`declared`), which beat the
    conventions; otherwise the conventional per-environment locations are
    used, and a path that does not exist is simply left empty so the field it
    would have answered reports NOT_AVAILABLE with a real reason."""
    declared = dict(declared or {})
    env_root = str(row.get("environment_path") or "")
    root = Path(env_root) if env_root else None

    def conventional(*relatives) -> str:
        if root is None:
            return ""
        for rel in relatives:
            candidate = root / rel
            if candidate.is_file():
                return str(candidate)
        return ""

    return SubsystemAnalysisInputs(
        subsystem_id=str(row.get("subsystem") or ""),
        environment_root=env_root,
        env_manifest_path=str(declared.get("env_manifest_path")
                              or conventional(".dv-harness/env.manifest.json",
                                              "env.manifest.json")),
        run_profile_path=str(declared.get("run_profile_path")
                             or conventional(".dv-harness/run_profile.json",
                                             "run_profile.json")),
        hierarchy_path=str(declared.get("hierarchy_path")
                           or conventional(".dv-workflow/hierarchy.json",
                                           "hierarchy.json")),
        command_files=[str(p) for p in (declared.get("command_files")
                                        or discover_command_files(env_root))],
        declared_component_roles=dict(declared.get("component_roles") or {}),
        region_clock_map=dict(declared.get("region_clock_map") or {}),
    )


# --- SYS-6 semantic component roles ------------------------------------------

def classify_component_roles(components: Sequence[Mapping[str, Any]],
                             declared: Optional[Mapping[str, str]] = None,
                             ) -> List[Dict[str, Any]]:
    """Assign a UVM ROLE to each captured component, citing what decided it.

    The only role-bearing evidence a topology dump carries is the author's own
    class name, so this is a name-token classifier and every row says so. A
    declared assignment (`declared`, keyed by full_name) beats the tokens
    entirely. `is_active` is copied from the dump's real `get_is_active()`
    value and is never inferred -- inferring active/passive from a name is
    exactly the guess env_manifest.schema.json already refuses to make."""
    declared = {str(k): str(v) for k, v in (declared or {}).items()}
    out: List[Dict[str, Any]] = []
    for component in components:
        full_name = str(component.get("full_name") or "")
        type_name = str(component.get("type_name") or "")
        role, basis, token = "UNCLASSIFIED", "NO_ROLE_TOKEN_MATCH", ""
        if full_name in declared:
            role, basis, token = declared[full_name], "DECLARED_BY_PROJECT", ""
        else:
            for candidate_role, tokens in COMPONENT_ROLE_TOKENS:
                hit = next((t for t in tokens if t in type_name.lower()), "")
                if hit:
                    role, basis, token = candidate_role, "TYPE_NAME_TOKEN_MATCH", hit
                    break
                hit = next((t for t in tokens if t in full_name.lower()), "")
                if hit:
                    role, basis, token = candidate_role, "FULL_NAME_TOKEN_MATCH", hit
                    break
        out.append({
            "full_name": full_name,
            "type_name": type_name,
            "role": role,
            "role_basis": basis,
            "matched_token": token,
            "is_active": component.get("is_active"),
            "is_active_basis": "TOPOLOGY_DUMP_get_is_active",
        })
    return out


def _field(status: str, *, source: str, reason: str = "", **payload) -> Dict[str, Any]:
    return dict({"status": status, "source": source, "reason": reason}, **payload)


def _unavailable(source: str, reason: str, **payload) -> Dict[str, Any]:
    return _field(NOT_AVAILABLE, source=source, reason=reason, **payload)


def _rtl_ports_matching(rtl_layer: Mapping[str, Any], tokens: Sequence[str]) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for file_entry in rtl_layer.get("files") or []:
        for module in file_entry.get("modules") or []:
            for port in module.get("ports") or []:
                name = str(port.get("name") or "")
                matched = [t for t in tokens if t in name.lower()]
                if matched:
                    hits.append({
                        "module": module.get("name"),
                        "port": name,
                        "direction": port.get("direction"),
                        "matched_tokens": matched,
                        "evidence": f"{file_entry.get('file_path')} (sha256 "
                                    f"{str(file_entry.get('source_sha256'))[:12]})",
                    })
    return hits


def analyze_subsystem_architecture(inputs: SubsystemAnalysisInputs) -> Dict[str, Any]:
    """SYS-6 for ONE subsystem. Every field of SYS-6's own list gets a verdict.

    Read-only over every artifact it opens, and every opened path is recorded
    in `read_paths` so SYS-5's isolation rule is checkable after the fact
    rather than merely asserted.
    """
    read_paths: List[str] = []
    started = time.time()

    manifest: Dict[str, Any] = {}
    manifest_error = ""
    if inputs.env_manifest_path:
        try:
            from . import env_manifest
            manifest = env_manifest.load_env_manifest(inputs.env_manifest_path)
            read_paths.append(str(inputs.env_manifest_path))
        except Exception as exc:  # a real artifact that will not load is a real finding
            manifest_error = f"{type(exc).__name__}: {exc}"

    profile: Dict[str, Any] = {}
    profile_error = ""
    if inputs.run_profile_path:
        try:
            from .uvm_generator import run_profile
            profile = run_profile.load_run_profile(Path(inputs.run_profile_path))
            read_paths.append(str(inputs.run_profile_path))
        except Exception as exc:
            profile_error = f"{type(exc).__name__}: {exc}"

    hierarchy_doc: Dict[str, Any] = {}
    hierarchy_error = ""
    if inputs.hierarchy_path:
        try:
            hierarchy_doc = json.loads(Path(inputs.hierarchy_path).read_text(encoding="utf-8"))
            read_paths.append(str(inputs.hierarchy_path))
        except Exception as exc:
            hierarchy_error = f"{type(exc).__name__}: {exc}"

    command_analyses: List[Dict[str, Any]] = []
    for command_file in inputs.command_files:
        try:
            command_analyses.append(rpa.analyze_command_file(Path(command_file)))
            read_paths.append(str(command_file))
        except OSError:
            continue

    vip_config = manifest.get("vip_config") or {}
    dut_facts = manifest.get("dut_facts") or {}
    env_topology = manifest.get("env_topology") or {}
    component_layer = env_topology.get("component_hierarchy") or {}
    components = component_layer.get("components") or []
    roles = classify_component_roles(components, inputs.declared_component_roles)
    by_role: Dict[str, List[Dict[str, Any]]] = {}
    for entry in roles:
        by_role.setdefault(entry["role"], []).append(entry)

    manifest_missing_reason = (
        manifest_error or
        ("no env.manifest.json supplied for this subsystem -- produce one with "
         "`dv-harness env-manifest generate` against this environment"
         if not inputs.env_manifest_path else ""))
    topology_missing_reason = (
        manifest_missing_reason or component_layer.get("reason") or
        "component_hierarchy layer carries no components")

    def role_field(role: str) -> Dict[str, Any]:
        if not components:
            return _unavailable("env.manifest.json env_topology.component_hierarchy",
                                topology_missing_reason, components=[])
        hits = by_role.get(role, [])
        return _field(DERIVED if hits else NOT_APPLICABLE,
                      source="env.manifest.json env_topology.component_hierarchy",
                      reason=("" if hits else
                              f"{len(components)} component(s) captured, none classified "
                              f"{role}; classification is a name-token match and its limits "
                              f"are recorded per component"),
                      components=hits)

    fields: Dict[str, Any] = {}

    # --- DUT hierarchy: two independent sources, both reported ---------------
    rtl_layer = dut_facts.get("rtl") or {}
    rtl_modules = [{"module": m.get("name"), "file": f.get("file_path"),
                    "instances": len(m.get("instances") or []),
                    "ports": len(m.get("ports") or [])}
                   for f in (rtl_layer.get("files") or [])
                   for m in (f.get("modules") or [])]
    hierarchy_nodes = (hierarchy_doc.get("nodes") or hierarchy_doc.get("hierarchy") or [])
    if rtl_modules or hierarchy_nodes:
        fields["dut_hierarchy"] = _field(
            DERIVED, source="env.manifest.json dut_facts.rtl (verible) + .dv-workflow/hierarchy.json",
            rtl_modules=rtl_modules[:64], rtl_module_count=len(rtl_modules),
            hierarchy_json_nodes=len(hierarchy_nodes) if isinstance(hierarchy_nodes, list) else 0,
            hierarchy_json_path=inputs.hierarchy_path)
    else:
        fields["dut_hierarchy"] = _unavailable(
            "env.manifest.json dut_facts.rtl + .dv-workflow/hierarchy.json",
            hierarchy_error or manifest_missing_reason or
            "no RTL parse and no hierarchy.json for this subsystem "
            "(hierarchy.json's declared producer is the CORE/hierarchy-discovery skill; "
            "there is no non-agent extractor for it)",
            rtl_modules=[], rtl_module_count=0)

    # --- UVM top/env ----------------------------------------------------------
    env_components = by_role.get("env", [])
    # Top-level = a captured full_name with no parent path segment. A
    # structural fact from the dump, not a name guess about which one is "the"
    # top: an environment may legitimately have more than one root component.
    tops = [c for c in roles if "." not in c["full_name"]]
    fields["uvm_top_env"] = (
        _field(DERIVED, source="env.manifest.json env_topology.component_hierarchy",
               env_components=env_components, top_level_components=tops[:16])
        if components else
        _unavailable("env.manifest.json env_topology.component_hierarchy",
                     topology_missing_reason, env_components=[], top_level_components=[]))

    # --- agents / VIPs / active-passive ---------------------------------------
    fields["agents"] = role_field("agent")
    vip_instances = vip_config.get("vip_instances") or []
    fields["vips"] = (
        _field(DERIVED, source="env.manifest.json vip_config.vip_instances "
                               "(live zero-time config dump)",
               instances=[{"instance_path": v.get("instance_path"),
                           "vip_type": v.get("vip_type"),
                           "config_field_count": len(v.get("config_fields") or {})}
                          for v in vip_instances],
               releases=[p.get("name") for p in
                         ((vip_config.get("vip_release") or {}).get("packages") or [])])
        if vip_instances else
        _unavailable("env.manifest.json vip_config.vip_instances",
                     manifest_missing_reason or (vip_config.get("reason") or
                                                 "no VIP instances captured"),
                     instances=[], releases=[]))
    # Three-valued, exactly as the manifest records it: UVM_ACTIVE /
    # UVM_PASSIVE / NOT_APPLICABLE. The third is not a missing answer -- it is
    # a component with no active/passive concept at all -- and folding it into
    # "passive" would assert something the dump never said.
    active = [c for c in roles if c["is_active"] == "UVM_ACTIVE"]
    passive = [c for c in roles if c["is_active"] == "UVM_PASSIVE"]
    not_applicable = [c for c in roles if c["is_active"] == "NOT_APPLICABLE"]
    fields["active_passive_mode"] = (
        _field(DERIVED, source="env.manifest.json env_topology.component_hierarchy is_active "
                               "(real get_is_active(), never a name guess)",
               active=[c["full_name"] for c in active][:64],
               passive=[c["full_name"] for c in passive][:64],
               not_applicable=[c["full_name"] for c in not_applicable][:64],
               active_count=len(active), passive_count=len(passive),
               not_applicable_count=len(not_applicable))
        if components else
        _unavailable("env.manifest.json env_topology.component_hierarchy",
                     topology_missing_reason, active=[], passive=[],
                     not_applicable=[], active_count=0, passive_count=0,
                     not_applicable_count=0))

    for sys6_field, role in (("sequencers", "sequencer"), ("drivers", "driver"),
                             ("monitors", "monitor"),
                             ("virtual_sequencers", "virtual_sequencer"),
                             ("scoreboards", "scoreboard"),
                             ("reference_models", "reference_model"),
                             ("predictors", "predictor"),
                             ("coverage_collectors", "coverage_collector"),
                             ("assertions_checkers", "assertions_checker"),
                             ("config_objects", "config_object")):
        fields[sys6_field] = role_field(role)

    # --- virtual interfaces ---------------------------------------------------
    trace_layer = env_topology.get("config_db_trace") or {}
    trace_entries = trace_layer.get("entries") or []
    vif_hits = [{"reporter": e.get("reporter"), "id": e.get("id"),
                 "message": str(e.get("message"))[:160],
                 "matched_tokens": [t for t in VIRTUAL_INTERFACE_TOKENS
                                    if t in str(e.get("message", "")).lower()]}
                for e in trace_entries
                if any(t in str(e.get("message", "")).lower() for t in VIRTUAL_INTERFACE_TOKENS)]
    if not trace_entries:
        fields["virtual_interfaces"] = _unavailable(
            "env.manifest.json env_topology.config_db_trace",
            manifest_missing_reason or (trace_layer.get("reason") or
                                        "no +UVM_CONFIG_DB_TRACE log captured for this "
                                        "environment; a virtual interface is set through "
                                        "config_db and leaves no other mechanical trace"),
            interfaces=[])
    else:
        fields["virtual_interfaces"] = _field(
            DERIVED if vif_hits else NOT_APPLICABLE,
            source="env.manifest.json env_topology.config_db_trace (message body is "
                   "deliberately opaque; this is a token match over it, not a parse)",
            reason="" if vif_hits else
                   f"{len(trace_entries)} config_db trace entries captured, none naming "
                   f"{list(VIRTUAL_INTERFACE_TOKENS)}",
            interfaces=vif_hits[:32],
            basis="NAME_TOKEN_MATCH_IN_CONFIG_DB_TRACE_MESSAGE")

    # --- clock/reset, register model, address map -----------------------------
    clock_reset = dut_facts.get("clock_reset") or {}
    fields["clock_reset"] = (
        _field(DERIVED, source="env.manifest.json dut_facts.clock_reset "
                               "(soc_arch_map input contract)",
               clocks=clock_reset.get("clocks") or [],
               resets=clock_reset.get("resets") or [])
        if clock_reset.get("status") == "LOADED" else
        _unavailable("env.manifest.json dut_facts.clock_reset",
                     manifest_missing_reason or (clock_reset.get("reason") or
                                                 "clock_reset layer NOT_AVAILABLE"),
                     clocks=[], resets=[]))

    registers = dut_facts.get("registers") or {}
    fields["register_model"] = (
        _field(DERIVED, source="env.manifest.json dut_facts.registers "
                               "(register_map input contract)",
               blocks=[{"name": b.get("name"), "base_address": b.get("base_address"),
                        "register_count": len(b.get("registers") or [])}
                       for b in (registers.get("blocks") or [])])
        if registers.get("status") == "LOADED" else
        _unavailable("env.manifest.json dut_facts.registers",
                     manifest_missing_reason or (registers.get("reason") or
                                                 "registers layer NOT_AVAILABLE"),
                     blocks=[]))

    address_map = dut_facts.get("address_map") or {}
    fields["address_map"] = (
        _field(DERIVED, source="env.manifest.json dut_facts.address_map "
                               "(soc_arch_map input contract, cross-checked against "
                               "dut_facts.registers)",
               entries=address_map.get("entries") or [],
               disagreement_count=address_map.get("disagreement_count", 0))
        if address_map.get("status") == "LOADED" else
        _unavailable("env.manifest.json dut_facts.address_map",
                     manifest_missing_reason or (address_map.get("reason") or
                                                 "address_map layer NOT_AVAILABLE"),
                     entries=[], disagreement_count=0))

    # --- interrupts / DMA / firmware / memory model ----------------------------
    # Two independent evidence axes each: the RTL port table and the real
    # command.txt. Either alone is thin; reporting both, separately, lets a
    # reader see which one actually carried the finding.
    interrupt_ports = _rtl_ports_matching(rtl_layer, INTERRUPT_PORT_TOKENS)
    interrupt_waits = [w for a in command_analyses
                       for w in a["interrupt_waits"]["interrupt_waits"]]
    if not rtl_layer.get("files") and not command_analyses:
        fields["interrupts"] = _unavailable(
            "env.manifest.json dut_facts.rtl ports + command.txt interrupt waits",
            manifest_missing_reason or "no RTL parse and no command.txt for this subsystem",
            rtl_ports=[], command_txt_waits=[])
    else:
        fields["interrupts"] = _field(
            DERIVED if (interrupt_ports or interrupt_waits) else NOT_APPLICABLE,
            source="env.manifest.json dut_facts.rtl ports + command.txt interrupt waits "
                   "(reference_pattern_audit.classify_wait)",
            reason="" if (interrupt_ports or interrupt_waits) else
                   f"RTL ports and command.txt statements were searched for "
                   f"{list(INTERRUPT_PORT_TOKENS)} / {list(rpa.INTERRUPT_NAME_TOKENS)}; none matched",
            rtl_ports=interrupt_ports[:32], command_txt_waits=interrupt_waits[:32],
            basis="NAME_TOKEN_MATCH_ON_RTL_PORTS_AND_ON_WAIT_CONDITIONS")

    dma_ports = _rtl_ports_matching(rtl_layer, DMA_PORT_TOKENS)
    dma_statements = [s for a in command_analyses
                      for s in a["dma_operations"]["dma_statements"]]
    if not rtl_layer.get("files") and not command_analyses:
        fields["dma"] = _unavailable(
            "env.manifest.json dut_facts.rtl ports + command.txt DMA statements",
            manifest_missing_reason or "no RTL parse and no command.txt for this subsystem",
            rtl_ports=[], command_txt_statements=[])
    else:
        fields["dma"] = _field(
            DERIVED if (dma_ports or dma_statements) else NOT_APPLICABLE,
            source="env.manifest.json dut_facts.rtl ports + command.txt DMA statements",
            reason="" if (dma_ports or dma_statements) else
                   f"searched for {list(DMA_PORT_TOKENS)} / {list(rpa.DMA_NAME_TOKENS)}; none matched",
            rtl_ports=dma_ports[:32], command_txt_statements=dma_statements[:32],
            basis="NAME_TOKEN_MATCH_ON_RTL_PORTS_AND_ON_COMMAND_STATEMENTS")

    fw_calls = [t for a in command_analyses for t in a["roles"]["target_vip_sequences"]]
    fw_backdoor = [s for a in command_analyses for s in a["statements"]
                   if s["category"] == rpa.C_MEMORY_BACKDOOR]
    fw_components = [c for c in roles
                     if any(t in c["full_name"].lower() or t in c["type_name"].lower()
                            for t in FIRMWARE_TOKENS)]
    if not command_analyses and not components:
        fields["firmware_interaction"] = _unavailable(
            "command.txt model/VIP task calls + memory backdoor loads + component hierarchy",
            "no command.txt and no component hierarchy for this subsystem",
            model_task_calls=[], backdoor_loads=[], components=[])
    else:
        found = bool(fw_calls or fw_backdoor or fw_components)
        fields["firmware_interaction"] = _field(
            DERIVED if found else NOT_APPLICABLE,
            source="command.txt model/VIP task calls + memory backdoor loads "
                   "(reference_pattern_audit) + component hierarchy",
            reason="" if found else
                   "no model/VIP task call, memory backdoor load or firmware-named "
                   "component was found in the captured evidence",
            model_task_calls=fw_calls[:16],
            backdoor_loads=[{"line": s["line"], "statement": s["text"][:120],
                             "file": s["file"]} for s in fw_backdoor[:16]],
            components=fw_components[:16])

    # Memory MODEL instances named by the command.txt itself, from the SYS-7
    # role table (already computed above -- never a second parse of the file).
    memory_models = [t for a in command_analyses
                     for t in a["roles"]["target_vip_sequences"]
                     if rpa._matched_tokens(t["target_vip"], rpa.MEMORY_MODEL_NAME_TOKENS)]
    memory_components = [c for c in roles
                         if any(t in c["type_name"].lower()
                                for t in rpa.MEMORY_MODEL_NAME_TOKENS)]
    memory_regions = [e for e in (address_map.get("entries") or [])
                      if any(t in str(e.get("name", "")).lower() or
                             t in str(e.get("target", "")).lower()
                             for t in rpa.MEMORY_MODEL_NAME_TOKENS)]
    if not command_analyses and not components and not memory_regions:
        fields["memory_model"] = _unavailable(
            "command.txt model instances + component hierarchy + address map",
            "no command.txt, component hierarchy or address map for this subsystem",
            command_txt_models=[], components=[], address_regions=[])
    else:
        found = bool(memory_models or memory_components or memory_regions)
        fields["memory_model"] = _field(
            DERIVED if found else NOT_APPLICABLE,
            source="command.txt model instances (subsystem_command_contract MEMORY_MODEL "
                   "resources) + component hierarchy + address map",
            reason="" if found else
                   f"searched for {list(rpa.MEMORY_MODEL_NAME_TOKENS)}; none matched. This "
                   f"is the memory MODEL, distinct from the register model reported above",
            command_txt_models=sorted({m["target_vip"] for m in memory_models}),
            components=memory_components[:16],
            address_regions=[e.get("name") for e in memory_regions][:16])

    # --- build/run/regression/waveform/fsdbreport flows -----------------------
    if profile:
        # run_profile.json's own real shape -- compile_time_params /
        # runtime_params / targets, per dv_harness/schemas/run_profile.schema.json.
        # `targets` is "the only verbs an agent may invoke", so it is the
        # build/run/regression flow inventory SYS-6 asks for; the param names
        # are what selects waveform and regression behaviour within them.
        names = [str(p.get("name")) for group in ("compile_time_params", "runtime_params")
                 for p in (profile.get(group) or []) if isinstance(p, dict)]
        targets = [str(t.get("name")) for t in (profile.get("targets") or [])
                   if isinstance(t, dict)]
        fields["build_run_regression_waveform_fsdbreport_flows"] = _field(
            DERIVED, source="run_profile.json (mechanically extracted from the real "
                            "Makefile by makefile_to_run_profile.py -- never an invented "
                            "plusarg)",
            run_profile_path=inputs.run_profile_path,
            source_kind=(profile.get("source") or {}).get("kind"),
            source_path=(profile.get("source") or {}).get("path"),
            targets=sorted(targets),
            parameter_count=len(names), parameters=sorted(names)[:64],
            waveform_parameters=sorted(n for n in names
                                       if any(t in n.upper()
                                              for t in ("WAVE", "FSDB", "VERDI", "DUMP"))),
            regression_parameters=sorted(n for n in names
                                         if any(t in n.upper()
                                                for t in ("REGRESS", "RECORD", "SEED", "LIST"))))
    else:
        fields["build_run_regression_waveform_fsdbreport_flows"] = _unavailable(
            "run_profile.json",
            profile_error or
            ("no run_profile.json supplied for this subsystem -- produce one from the "
             "environment's real Makefile with "
             "dv_harness.uvm_generator.makefile_to_run_profile"),
            run_profile_path=inputs.run_profile_path, parameters=[], parameter_count=0,
            targets=[])

    missing = [f for f in SYS6_FIELDS if f not in fields]
    if missing:  # a structural bug, not a data condition -- fail loudly
        raise RuntimeError(f"SYS-6 analyzer produced no verdict for {missing}")

    derived = [f for f in SYS6_FIELDS if fields[f]["status"] == DERIVED]
    return {
        "subsystem_id": inputs.subsystem_id,
        "environment_root": inputs.environment_root,
        "analysis_status": "COMPLETE",
        "fields": {f: fields[f] for f in SYS6_FIELDS},
        "component_roles": roles,
        "command_analyses": command_analyses,
        "read_paths": sorted(set(read_paths)),
        "inputs": asdict(inputs),
        "coverage": {
            "fields_total": len(SYS6_FIELDS),
            "derived": len(derived),
            "not_available": sum(1 for f in SYS6_FIELDS
                                 if fields[f]["status"] == NOT_AVAILABLE),
            "not_applicable": sum(1 for f in SYS6_FIELDS
                                  if fields[f]["status"] == NOT_APPLICABLE),
            "derived_fields": derived,
        },
        "elapsed_seconds": round(time.time() - started, 3),
        "artifacts_modified": False,
    }


# --- SYS-5: one independent workflow per selected subsystem -------------------

def assert_no_cross_contamination(results: Sequence[Mapping[str, Any]]) -> None:
    """SYS-5's isolation rule, enforced against what each analysis ACTUALLY
    read rather than trusted from its inputs.

    Each analysis records every path it opened. If any of those paths lies
    under a DIFFERENT selected subsystem's environment root, the analyses were
    not independent and the cross-subsystem synthesis built on them would be
    unsound. Raises rather than warns: a contaminated analysis cannot be
    repaired after the fact."""
    roots: Dict[str, Path] = {}
    for result in results:
        root = str(result.get("environment_root") or "")
        if root:
            try:
                roots[str(result["subsystem_id"])] = Path(root).resolve()
            except OSError:
                continue
    violations: List[str] = []
    for result in results:
        me = str(result.get("subsystem_id"))
        for read in result.get("read_paths") or []:
            try:
                resolved = Path(read).resolve()
            except OSError:
                continue
            for other, other_root in roots.items():
                if other == me:
                    continue
                if other_root == resolved or other_root in resolved.parents:
                    violations.append(
                        f"{me} read {read}, which lies under {other}'s environment "
                        f"root {other_root}")
    if violations:
        raise CrossContaminationError(
            "SYS-5 isolation violated -- one subsystem's analysis read another's "
            "evidence:\n  " + "\n  ".join(sorted(set(violations))))


def run_per_subsystem_analyses(inputs: Sequence[SubsystemAnalysisInputs],
                               *, max_workers: Optional[int] = None,
                               ) -> List[Dict[str, Any]]:
    """SYS-5: open ONE independent analysis workflow per selected subsystem,
    run them in parallel when there is more than one, and only then check
    isolation.

    Parallelism is safe here for a structural reason, not a hopeful one: an
    analysis is a pure read over its own declared input list and writes
    nothing anywhere -- `artifacts_modified: False` is a property of
    `analyze_subsystem_architecture()`, which has no write path. The isolation
    check runs on the collected results BEFORE any synthesis touches them, so
    a contaminated run stops here and never reaches SYS-9 onward.
    """
    inputs = list(inputs)
    if not inputs:
        return []
    if len(inputs) == 1:
        results = [analyze_subsystem_architecture(inputs[0])]
    else:
        with ThreadPoolExecutor(max_workers=max_workers or min(8, len(inputs))) as pool:
            results = list(pool.map(analyze_subsystem_architecture, inputs))
    results.sort(key=lambda r: r["subsystem_id"])
    assert_no_cross_contamination(results)
    return results


def synthesize_subsystem_analyses(results: Sequence[Mapping[str, Any]],
                                  *,
                                  address_maps: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
                                  region_clock_maps: Optional[Mapping[str, Mapping[str, str]]] = None,
                                  inventory_overlay_path=None,
                                  ) -> Dict[str, Any]:
    """SYS-5's "cross-subsystem synthesis happens afterward", as a real
    precondition rather than an ordering convention.

    Refuses to synthesize while any analysis is not COMPLETE, and re-runs the
    isolation check on the exact result set it is about to combine -- so a
    caller cannot reach the synthesis with a hand-assembled list that skipped
    `run_per_subsystem_analyses()`.

    The synthesis itself is the SYS-8 contract set built across every
    subsystem at once, which is the first point at which a cross-subsystem
    conflict can exist at all.
    """
    results = list(results)
    incomplete = [r["subsystem_id"] for r in results
                  if r.get("analysis_status") != "COMPLETE"]
    if incomplete:
        raise RuntimeError(
            "SYS-5: cross-subsystem synthesis attempted while these per-subsystem "
            f"analyses are not COMPLETE: {sorted(incomplete)}")
    assert_no_cross_contamination(results)

    per_subsystem_files = {
        r["subsystem_id"]: [a["command_file"] for a in (r.get("command_analyses") or [])]
        for r in results}
    resolved_maps = dict(address_maps or {})
    for result in results:
        field_block = (result.get("fields") or {}).get("address_map") or {}
        if result["subsystem_id"] not in resolved_maps and field_block.get("entries"):
            resolved_maps[result["subsystem_id"]] = field_block["entries"]
    resolved_clocks = dict(region_clock_maps or {})
    for result in results:
        declared = ((result.get("inputs") or {}).get("region_clock_map")) or {}
        if declared and result["subsystem_id"] not in resolved_clocks:
            resolved_clocks[result["subsystem_id"]] = declared

    contract_set = scc.build_contract_set(
        per_subsystem_files, address_maps=resolved_maps,
        region_clock_maps=resolved_clocks,
        inventory_overlay_path=inventory_overlay_path)

    return {
        "subsystems": [r["subsystem_id"] for r in results],
        "per_subsystem": results,
        "contract_set": contract_set,
        "summary": {
            "subsystem_count": len(results),
            "sys6_fields_derived": {r["subsystem_id"]: r["coverage"]["derived"]
                                    for r in results},
            "command_files": {r["subsystem_id"]: len(r.get("command_analyses") or [])
                              for r in results},
            "cross_subsystem_conflicts": contract_set["summary"]["conflict_count"],
            "duplicate_active_drivers": contract_set["summary"]["duplicate_active_drivers"],
        },
        "isolation": {
            "checked": True,
            "rule": "SYS-5 -- no subsystem's analysis may read another selected "
                    "subsystem's environment tree before its own analysis completes",
        },
        "artifacts_modified": False,
        "phase_boundary": (
            "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-5..SYS-8 analysis only. "
            "No System-Level environment, System command.txt, System Virtual Sequencer "
            "or command routing is generated; that is SYS-40 and requires a separate "
            "explicit human approval."),
    }


def analyze_selected_subsystems(root, selected: Sequence[str], *,
                                declared: Optional[Mapping[str, Any]] = None,
                                knowledge_center_client: Any = None,
                                max_workers: Optional[int] = None,
                                inventory_overlay_path=None,
                                ) -> Dict[str, Any]:
    """Front door: SYS-1 discovery -> SYS-5 per-subsystem analyses -> SYS-6
    reports -> SYS-7/SYS-8 synthesis, for an explicitly selected subsystem set.

    The selection is REQUIRED and comes through
    `subsystem_discovery.require_explicit_selection()` -- the same refusal
    SYS-1 already enforces. This function never picks the set itself."""
    selection = sd.require_explicit_selection(
        Path(root), selected, knowledge_center_client=knowledge_center_client)
    declared = dict(declared or {})
    inputs = [inputs_from_discovery_row(row, declared=declared.get(row["subsystem"]))
              for row in selection["selected_rows"]]
    results = run_per_subsystem_analyses(inputs, max_workers=max_workers)
    synthesis = synthesize_subsystem_analyses(
        results, inventory_overlay_path=inventory_overlay_path)
    return {"selection": selection, "synthesis": synthesis}


# --- reporting ----------------------------------------------------------------

def render_architecture_table(result: Mapping[str, Any]) -> str:
    """SYS-6's field list as a markdown table for ONE subsystem."""
    lines = ["| SYS-6 FIELD | STATUS | SOURCE | DETAIL |", "|---|---|---|---|"]
    for name in SYS6_FIELDS:
        block = result["fields"][name]
        detail = block.get("reason") or ""
        if block["status"] == DERIVED:
            counts = [f"{k}={len(v)}" for k, v in block.items()
                      if isinstance(v, list) and v]
            detail = ", ".join(counts) or "derived"
        lines.append("| {} | {} | {} | {} |".format(
            name, block["status"], block["source"], detail.replace("\n", " ")[:160]))
    return "\n".join(lines)


def format_analysis_report(synthesis: Mapping[str, Any]) -> str:
    """The SYS-5..SYS-8 deliverable: per-subsystem architecture reports, then
    the cross-subsystem synthesis. Reporting only."""
    out = ["# PER-SUBSYSTEM VERIFICATION ARCHITECTURE ANALYSIS (SYS-5..SYS-8)", "",
           f"- subsystems analyzed independently: {synthesis['subsystems']}",
           f"- SYS-5 isolation checked: {synthesis['isolation']['checked']}",
           f"- cross-subsystem conflicts: {synthesis['summary']['cross_subsystem_conflicts']} "
           f"({synthesis['summary']['duplicate_active_drivers']} duplicate active driver(s))",
           ""]
    for result in synthesis["per_subsystem"]:
        coverage = result["coverage"]
        out += [f"## {result['subsystem_id']} -- SYS-6 VERIFICATION ARCHITECTURE", "",
                f"- environment root: {result['environment_root'] or '(none)'}",
                f"- fields derived from real artifacts: {coverage['derived']}/"
                f"{coverage['fields_total']} "
                f"({coverage['not_available']} NOT_AVAILABLE, "
                f"{coverage['not_applicable']} NOT_APPLICABLE)",
                f"- artifacts read: {len(result['read_paths'])}", "",
                render_architecture_table(result), ""]
        for analysis in result.get("command_analyses") or []:
            out += ["### SYS-7 command.txt analysis", "", "```",
                    rpa.format_command_analysis(analysis), "```", ""]
    out += ["## SYS-8 SUBSYSTEM COMMAND CONTRACTS", "",
            scc.format_contract_report(synthesis["contract_set"]), "",
            "## PHASE BOUNDARY", "", synthesis["phase_boundary"]]
    return "\n".join(out)
