"""SYS-18..SYS-22 of the System-Level Verification Integration workflow: the
SYSTEM-LEVEL ARCHITECTURE report, the SYSTEM command.txt reuse/routing PLAN,
the BACKWARD COMPATIBILITY assessment, the SYSTEM COMMAND IR, and COMMAND
COLLISION DETECTION.

WHAT THIS MODULE IS NOT
-----------------------
It is the single most important boundary in this layer, so it is stated
before anything else. Nothing here emits a System command.txt, a System
Command Parser/Router, a System Scenario Planner, a System Virtual Sequencer,
a command adapter or any System-Level UVM source. SYS-18's tree is a
DESCRIPTION of a preferred structure; SYS-19's routing plan is a TABLE saying
which existing subsystem parser each System-level command name would route
to; SYS-20's adapter plan NAMES an adapter that does not exist. Building any
of them is SYS-40, which the workflow's own SYS-39 stop condition gates on a
separate explicit human approval. `assert_no_emitted_artifacts()` is the
runtime check of that, and tests assert it rather than trusting this
paragraph.

WHY A NEW MODULE RATHER THAN AN EXTENSION
-----------------------------------------
`subsystem_command_contract.py` (SYS-8) was the obvious "extend" candidate
and is the wrong granularity in a specific, checkable way. A
`SubsystemCommandContract` is one SUBSYSTEM's command as that subsystem's own
command.txt states it, and its fields are deliberately subsystem-local:
`command_name` is "the macro name as it is actually written in the file,
never a normalised or invented name", and `source_command_file` is one real
file. SYS-21's IR is a different object: one SYSTEM-level command, whose
`system_command_id` is namespaced across subsystems and whose
`parallel_group` / `serialization_group` / `priority` are SYSTEM SCHEDULING
properties that no single subsystem's file can state. Adding those to the
contract would make a subsystem-local record carry system-level scheduling
and break SYS-20's own guarantee that a subsystem's representation is
unchanged by System-level activity.

So this module follows exactly the precedent `system_resource_registry.py`
(SYS-15..17) set: a new module at the new granularity that IMPORTS and
COMPOSES the layer below and re-derives none of it.

  * `subsystem_command_contract` (SYS-7/SYS-8) supplies EVERY command fact:
    category, arguments, target agent/VIP/sequence, required resources,
    pre/postconditions, ordering constraints, interrupt/reset/address
    dependencies, and the cross-subsystem `parallel_safe` verdict. No second
    command parser, no second grammar, no second concurrency resolver.
  * `scc.detect_contract_conflicts()` supplies the resource/address joins
    SYS-22 refines. This module REFINES that output into SYS-22's own 12-value
    vocabulary; it does not recompute which subsystems touch which resource.
    A second copy of that arithmetic is the duplicate-mechanism failure this
    project has been bitten by before.
  * `system_resource_registry` (SYS-15..17) supplies SYS-18's Shared SoC
    Resources from the real registry, so the architecture tree and the
    registry cannot disagree about what the System owns.
  * `subsystem_discovery` (SYS-1..4) supplies the selection. SYS-18's
    "Instantiate only selected subsystems" is enforced against that selection,
    never against everything discovered.
  * `source_authority.escalate_conflict()` is the escalation channel for every
    collision. Not a second conflict resolver -- see the note on SYS-22 below.

WHY SYS-22 ESCALATES THROUGH `source_authority` BUT DOES NOT CLASSIFY THROUGH IT
-------------------------------------------------------------------------------
`source_authority.resolve_conflict()` answers "two sources state DIFFERENT
things about one fact -- which is true". SYS-22 asks a different question:
two commands that are each equally real, equally authoritative and both
genuinely present independently try to do the same physical thing. There is
no stale-vs-correct axis, so the 9-level order has nothing to rank -- two
subsystems' own command.txt files are both tier-2 `reference_command_txt` and
`resolve_conflict()` lands on UNDECIDABLE_SAME_AUTHORITY every time. The
order therefore cannot decide WHICH command wins, and this module never asks
it to; classifying the collision TYPE is genuinely new domain logic here.

What IS reused, wholesale, is `escalate_conflict()`: the same function
`reference_pattern_audit.py` and `address_map_verifier.py` already escalate
through. UNDECIDABLE_SAME_AUTHORITY is exactly the verdict it is built to
file -- it carries both evidence paths, runs
`assert_both_evidence_paths_present()` before persisting, derives an
idempotent Q-ID from the finding so a re-run re-mints the same id instead of
growing the queue, and routes the owner through `question_queue.route_owner`.
Writing a second escalation path beside it would be the duplicate mechanism
this codebase already refuses elsewhere. A collision spanning more than two
subsystems is split into PAIRWISE questions, which is what
`escalate_conflict()`'s own docstring prescribes for a wider conflict
(the queue schema allows 2-3 options and truncating would drop an evidence
path).
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from . import reference_pattern_audit as rpa
from . import subsystem_command_contract as scc
from . import system_resource_inventory as sri
from . import system_resource_registry as srr

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "system_command_plan.schema.json"
SCHEMA_VERSION = "1.0"


# ===========================================================================
# SYS-18 vocabulary
# ===========================================================================

#: SYS-18's "System Control" children, verbatim and in the requirement's own
#: order. Every one of them is an implementation artifact: a parser/router, a
#: planner and a virtual sequencer are code. SYS-18 states a PREFERRED
#: STRUCTURE, and describing a structure is Phase 1; building it is SYS-40.
SYS18_SYSTEM_CONTROL: tuple = (
    "System Command Parser/Router",
    "System Scenario Planner",
    "System Virtual Sequencer",
)

#: SYS-18's "Shared SoC Resources" children, verbatim and in its own order.
SYS18_SHARED_SOC_RESOURCES: tuple = (
    "CPU AXI Master",
    "APB Master",
    "AHB Master",
    "Clock/Reset",
    "Interrupt",
    "Memory/Register Access",
)

#: Which SYS-9 resource types populate which SYS-18 shared-resource category.
#: Deliberately NOT total over `sri.RESOURCE_TYPES`: SYS-14 says
#: "Keep subsystem-specific VIP within its subsystem where possible ... Only
#: shared SoC infrastructure should be promoted", so a VIP agent, a
#: scoreboard, a reference model or a virtual sequencer has no shared-resource
#: category to be hoisted into, by design rather than by omission. A registry
#: entry of an unmapped type stays a subsystem leaf's resource.
SYS18_CATEGORY_BY_RESOURCE_TYPE: Dict[str, str] = {
    sri.RT_CPU_BUS_MASTER: "CPU AXI Master",
    sri.RT_AXI_MASTER: "CPU AXI Master",
    sri.RT_APB_MASTER: "APB Master",
    sri.RT_AHB_MASTER: "AHB Master",
    sri.RT_CLOCK_RESET_AGENT: "Clock/Reset",
    sri.RT_INTERRUPT_AGENT: "Interrupt",
    sri.RT_MEMORY_MODEL: "Memory/Register Access",
    sri.RT_REGISTER_ACCESS_AGENT: "Memory/Register Access",
}

#: Node status vocabulary for the SYS-18 tree.
NODE_PLANNED_NOT_IMPLEMENTED = "PLANNED_NOT_IMPLEMENTED"
NODE_PROPOSED_FROM_REGISTRY = "PROPOSED_FROM_REGISTRY"
NODE_BLOCKED_PENDING_OWNERSHIP = "BLOCKED_PENDING_OWNERSHIP"
NODE_NOT_PRESENT_IN_SELECTION = "NOT_PRESENT_IN_SELECTION"
NODE_SELECTED_SUBSYSTEM_ENV = "SELECTED_SUBSYSTEM_ENV"
NODE_STATUSES: tuple = (
    NODE_PLANNED_NOT_IMPLEMENTED, NODE_PROPOSED_FROM_REGISTRY,
    NODE_BLOCKED_PENDING_OWNERSHIP, NODE_NOT_PRESENT_IN_SELECTION,
    NODE_SELECTED_SUBSYSTEM_ENV,
)

SYSTEM_ROOT = "System-Level Verification Environment"


# ===========================================================================
# SYS-19 / SYS-20 vocabulary
# ===========================================================================

#: The System-level namespace separator. `::` and not `.`, because `.` is
#: already load-bearing inside real command names: a model task call is
#: written `` `SMEMMODEL.FILLMEM `` and a namespace built with `.` would
#: produce `SUBSYS_A.SMEMMODEL.FILLMEM`, in which no reader (and no adapter)
#: can tell where the namespace ends. `::` is also what
#: `scc.contract_id()` already uses to join subsystem/file/command, so this
#: codebase has one separator convention rather than two.
NAMESPACE_SEPARATOR = "::"

#: SYS-19's routing verdicts.
ROUTE_REUSES_SUBSYSTEM_SEMANTICS = "REUSES_SUBSYSTEM_SEMANTICS"
ROUTE_AMBIGUOUS_NAMESPACE = "AMBIGUOUS_NAMESPACE"
ROUTE_TARGET_UNRESOLVED = "TARGET_UNRESOLVED"
ROUTE_VERDICTS: tuple = (ROUTE_REUSES_SUBSYSTEM_SEMANTICS,
                         ROUTE_AMBIGUOUS_NAMESPACE, ROUTE_TARGET_UNRESOLVED)

#: SYS-20's per-subsystem compatibility verdicts.
COMPAT_PRESERVED = "SUBSYSTEM_MODE_PRESERVED"
COMPAT_AT_RISK = "SUBSYSTEM_MODE_AT_RISK"
COMPAT_VERDICTS: tuple = (COMPAT_PRESERVED, COMPAT_AT_RISK)


# ===========================================================================
# SYS-21 vocabulary
# ===========================================================================

#: SYS-21's own field list, verbatim and in its own order:
#: "system_command_id, source_subsystem, source_command, command_category,
#:  target_resource, target_sequence, arguments, dependencies, preconditions,
#:  postconditions, parallel_group, serialization_group, shared_resource,
#:  priority, timeout, completion_condition, evidence."
#: Seventeen fields. Held to the requirement text by a test, so neither the
#: code nor a summary of it can drift away from the document.
SYS21_FIELDS: tuple = (
    "system_command_id",
    "source_subsystem",
    "source_command",
    "command_category",
    "target_resource",
    "target_sequence",
    "arguments",
    "dependencies",
    "preconditions",
    "postconditions",
    "parallel_group",
    "serialization_group",
    "shared_resource",
    "priority",
    "timeout",
    "completion_condition",
    "evidence",
)

#: `priority` is UNASSIGNED and stays UNASSIGNED at Phase 1. Nothing in a
#: subsystem's command.txt states a System-level priority -- priority is a
#: scheduling decision across subsystems (SYS-24's shared-resource
#: scheduling), and deriving one here from, say, category order would be this
#: module inventing a verification parameter and presenting it as derived.
PRIORITY_UNASSIGNED = "UNASSIGNED_PENDING_SYSTEM_SCHEDULING_DECISION"

#: Same for `timeout`. A `#100` delay is a delay, and a `wait(...)` in a real
#: command.txt has no bound at all; reporting either as a timeout would state
#: a limit the source does not contain.
TIMEOUT_NOT_SPECIFIED = "NOT_SPECIFIED_IN_SOURCE_COMMAND_TXT"

#: `completion_condition` values. These ARE derivable, from the contract's own
#: interrupt/postcondition evidence rather than from a naming convention.
COMPLETION_INTERRUPT = "INTERRUPT_HANDSHAKE"
COMPLETION_CONDITION_WAIT = "CONDITION_WAIT"
COMPLETION_IMMEDIATE = "IMMEDIATE_ON_COMMAND_RETURN"
COMPLETION_TERMINATES_FILE = "TERMINATES_THE_SEQUENCE"
COMPLETION_UNKNOWN = "UNKNOWN"

#: `parallel_group` / `serialization_group` sentinels.
GROUP_NONE = ""
PARALLEL_GROUP_UNDECIDABLE = "UNDECIDABLE_SINGLE_SUBSYSTEM_SET"


# ===========================================================================
# SYS-22 vocabulary
# ===========================================================================

#: SYS-22's collision classes, read off its own sentence: "Detect duplicate
#: initialization/reset/clock setup/CPU configuration/APB programming/memory
#: init, conflicting register writes/address setup, competing active VIP
#: traffic, incompatible mode setup, ordering conflicts, shared-resource
#: contention." Twelve classes. A test holds this tuple to that sentence.
DUPLICATE_INITIALIZATION = "DUPLICATE_INITIALIZATION"
DUPLICATE_RESET_SETUP = "DUPLICATE_RESET_SETUP"
DUPLICATE_CLOCK_SETUP = "DUPLICATE_CLOCK_SETUP"
DUPLICATE_CPU_CONFIGURATION = "DUPLICATE_CPU_CONFIGURATION"
DUPLICATE_APB_PROGRAMMING = "DUPLICATE_APB_PROGRAMMING"
DUPLICATE_MEMORY_INIT = "DUPLICATE_MEMORY_INIT"
CONFLICTING_REGISTER_WRITE = "CONFLICTING_REGISTER_WRITE"
CONFLICTING_ADDRESS_SETUP = "CONFLICTING_ADDRESS_SETUP"
COMPETING_ACTIVE_VIP_TRAFFIC = "COMPETING_ACTIVE_VIP_TRAFFIC"
INCOMPATIBLE_MODE_SETUP = "INCOMPATIBLE_MODE_SETUP"
ORDERING_CONFLICT = "ORDERING_CONFLICT"
SHARED_RESOURCE_CONTENTION = "SHARED_RESOURCE_CONTENTION"

SYS22_COLLISION_TYPES: tuple = (
    DUPLICATE_INITIALIZATION, DUPLICATE_RESET_SETUP, DUPLICATE_CLOCK_SETUP,
    DUPLICATE_CPU_CONFIGURATION, DUPLICATE_APB_PROGRAMMING, DUPLICATE_MEMORY_INIT,
    CONFLICTING_REGISTER_WRITE, CONFLICTING_ADDRESS_SETUP,
    COMPETING_ACTIVE_VIP_TRAFFIC, INCOMPATIBLE_MODE_SETUP,
    ORDERING_CONFLICT, SHARED_RESOURCE_CONTENTION,
)

#: Severity, used ONLY for ordering the report and for the exit code. It never
#: decides anything: SYS-22's own last sentence is "Report all collisions; do
#: not silently choose", so no collision is ever dropped, merged away or
#: auto-resolved, and a lower severity still appears in full.
COLLISION_SEVERITY: Dict[str, int] = {
    COMPETING_ACTIVE_VIP_TRAFFIC: 0,
    CONFLICTING_REGISTER_WRITE: 1,
    INCOMPATIBLE_MODE_SETUP: 2,
    ORDERING_CONFLICT: 3,
    CONFLICTING_ADDRESS_SETUP: 4,
    SHARED_RESOURCE_CONTENTION: 5,
    DUPLICATE_RESET_SETUP: 6,
    DUPLICATE_CLOCK_SETUP: 7,
    DUPLICATE_CPU_CONFIGURATION: 8,
    DUPLICATE_APB_PROGRAMMING: 9,
    DUPLICATE_MEMORY_INIT: 10,
    DUPLICATE_INITIALIZATION: 11,
}

#: Collision classes that must stop automatic System-Level integration of the
#: thing they name. A duplicate initialization is a REPORT (SYS-23 decides
#: what to do with it, and its own rule is "Do not remove commands without
#: evidence"); two subsystems actively driving one interface is SYS-12's stop.
BLOCKING_COLLISIONS: frozenset = frozenset({
    COMPETING_ACTIVE_VIP_TRAFFIC, CONFLICTING_REGISTER_WRITE,
    INCOMPATIBLE_MODE_SETUP, ORDERING_CONFLICT,
})

#: RESOURCE-ID tokens, taken from `system_resource_inventory`'s own
#: classification vocabulary rather than respelled, so "what makes a resource
#: a CPU master" is written down in exactly one place in this codebase.
_SRI_TOKENS: Dict[str, tuple] = {t: tokens for t, tokens in sri.RESOURCE_TYPE_TOKENS}

#: COMMAND-VERB tokens. A second table is correct here and is not a duplicate
#: mechanism: `sri.RESOURCE_TYPE_TOKENS` describes UVM INSTANCE names
#: (`cpu_axi_master`, `apb_mst`), and a command.txt macro is a different
#: naming domain entirely (`CPUWRITE4B`, `APBWRITE`, `SMEMMODEL.FILLMEM`).
#: Matching instance-name tokens against a macro name would classify nothing,
#: and widening the instance table with macro spellings would corrupt SYS-9's
#: resource typing for every other caller. This is the same reason
#: `rpa.RESET_NAME_TOKENS` already exists separately from sri's clock/reset
#: instance tokens. Resource-id evidence is consulted FIRST wherever it
#: exists, because it is structural; these only decide the residual.
#: Only the three types SYS-22 actually names a duplicate class for ("CPU
#: configuration", "APB programming", "memory init"). There is deliberately no
#: AHB entry: SYS-22's sentence does not name an AHB duplicate class, and
#: adding one would invent a thirteenth collision type.
_COMMAND_VERB_TOKENS: Dict[str, tuple] = {
    sri.RT_APB_MASTER: ("apb",),
    sri.RT_CPU_BUS_MASTER: ("cpu", "host", "soc"),
    sri.RT_MEMORY_MODEL: ("mem", "ddr", "sram", "fillmem"),
}

PHASE_BOUNDARY = (
    "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-18..SYS-22 are the "
    "architecture REPORT, the System command.txt routing/namespacing PLAN, the "
    "backward-compatibility assessment, the System Command IR and the collision "
    "report. No System command.txt is emitted, no System Command Parser/Router, "
    "Scenario Planner, Virtual Sequencer or command adapter is generated, no "
    "System-Level UVM source is written, and no subsystem's own command.txt is "
    "read anything but read-only. Every routing entry and every adapter named "
    "here is a RECOMMENDATION for a human. Building any of it is SYS-40 and "
    "requires a separate explicit human approval.")


class SystemCommandPlanError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


# ===========================================================================
# SYS-18 -- SYSTEM-LEVEL ARCHITECTURE
# ===========================================================================

def _selected_subsystems(selection: Optional[Mapping[str, Any]],
                         contract_set: Optional[Mapping[str, Any]],
                         registry: Optional[Mapping[str, Any]]) -> List[str]:
    """The subsystems SYS-18 may instantiate a leaf for.

    The SYS-1 selection is authoritative when present, because SYS-18's
    "Instantiate only selected subsystems" is about the USER's selection and
    not about what a downstream artifact happens to mention. Falling back to
    the contract set / registry is for a caller that built a plan directly
    from analysis objects; it is never a way to widen an explicit selection.
    """
    if selection is not None and "selected" in selection:
        # An EXPLICIT empty selection means empty. Falling back to what the
        # contracts happen to mention would compose a set the user did not
        # choose, which is SYS-1's own refusal being bypassed one layer up.
        return sorted({str(s) for s in (selection.get("selected") or [])})
    names: Set[str] = set()
    for contract in ((contract_set or {}).get("contracts") or []):
        names.add(str(contract["subsystem_id"]))
    for entry in ((registry or {}).get("entries") or []):
        names.update(str(s) for s in entry.get("consumer_subsystems") or [])
    return sorted(names)


def build_system_architecture(integration_plan: Mapping[str, Any],
                              *,
                              selection: Optional[Mapping[str, Any]] = None,
                              contract_set: Optional[Mapping[str, Any]] = None,
                              ) -> Dict[str, Any]:
    """SYS-18's preferred logical structure, as a DESCRIPTOR over real data.

    Three groups of nodes, each with a different honest status:

      * System Control's three components are PLANNED_NOT_IMPLEMENTED, always.
        They are code, and code is SYS-40. Reporting them as present would be
        the single failure this whole layer exists to prevent.
      * Shared SoC Resources come from the SYS-15 registry: a category is
        PROPOSED_FROM_REGISTRY when a registry entry of a mapped resource type
        is shared across subsystems with an actionable reuse decision,
        BLOCKED_PENDING_OWNERSHIP when that entry is BLOCKED (SYS-12 stopped
        it), and NOT_PRESENT_IN_SELECTION when the selection produced no such
        resource at all. That last value is deliberately not silence: SYS-18
        NAMES six categories, and a tree that simply omitted the four this
        selection has no evidence for would read as a claim that the structure
        was fully realised.
      * One leaf per SELECTED subsystem, and no others.
    """
    registry = integration_plan.get("system_resource_registry") or {}
    entries = list(registry.get("entries") or [])
    selected = _selected_subsystems(selection, contract_set, registry)

    nodes: List[Dict[str, Any]] = []

    for name in SYS18_SYSTEM_CONTROL:
        nodes.append({
            "path": [SYSTEM_ROOT, "System Control", name],
            "kind": "SYSTEM_CONTROL",
            "name": name,
            "status": NODE_PLANNED_NOT_IMPLEMENTED,
            "basis": ("SYS-18 names this component of the preferred structure. It is "
                      "an implementation artifact and this workflow is bounded to "
                      "SYS-39; creating it is SYS-40."),
            "backing_resources": [],
            "evidence": [],
        })

    by_category: Dict[str, List[Mapping[str, Any]]] = {c: [] for c in SYS18_SHARED_SOC_RESOURCES}
    for entry in entries:
        category = SYS18_CATEGORY_BY_RESOURCE_TYPE.get(entry.get("resource_type"))
        if category is None:
            continue
        if entry.get("shared") != srr.SHARED_ACROSS_SUBSYSTEMS:
            # SYS-14: a resource only one subsystem consumes stays that
            # subsystem's, even when its TYPE is shareable infrastructure.
            continue
        by_category[category].append(entry)

    for category in SYS18_SHARED_SOC_RESOURCES:
        backing = by_category[category]
        if not backing:
            status = NODE_NOT_PRESENT_IN_SELECTION
            basis = ("No SYS-15 registry entry of a resource type mapped to this "
                     "category is shared across the selected subsystems. This is an "
                     "absence in the evidence, not a decision that the System does "
                     "not need one.")
        elif any(e.get("reuse_decision") == srr.BLOCKED for e in backing):
            status = NODE_BLOCKED_PENDING_OWNERSHIP
            basis = ("A SYS-15 entry backing this category is BLOCKED -- SYS-12 "
                     "stopped automatic integration of that resource until ownership "
                     "is resolved.")
        else:
            status = NODE_PROPOSED_FROM_REGISTRY
            basis = ("Backed by SYS-15 registry entries shared across more than one "
                     "selected subsystem. The System owner is PROPOSED; assigning "
                     "one means creating the shared agent, which is SYS-40.")
        nodes.append({
            "path": [SYSTEM_ROOT, "Shared SoC Resources", category],
            "kind": "SHARED_SOC_RESOURCE",
            "name": category,
            "status": status,
            "basis": basis,
            "backing_resources": [e["resource_id"] for e in backing],
            "evidence": sorted({ev for e in backing for ev in (e.get("evidence") or [])})[:6],
        })

    contracts_by_subsystem: Dict[str, int] = {}
    for contract in ((contract_set or {}).get("contracts") or []):
        sid = str(contract["subsystem_id"])
        contracts_by_subsystem[sid] = contracts_by_subsystem.get(sid, 0) + 1

    for name in selected:
        owned = [e["resource_id"] for e in entries
                 if name in (e.get("consumer_subsystems") or [])
                 and e.get("shared") != srr.SHARED_ACROSS_SUBSYSTEMS]
        nodes.append({
            "path": [SYSTEM_ROOT, f"Selected {name} Env"],
            "kind": "SUBSYSTEM_ENV",
            "name": name,
            "status": NODE_SELECTED_SUBSYSTEM_ENV,
            "basis": ("A selected subsystem's own existing environment, reused as-is. "
                      "SYS-18: do not rebuild known-good subsystem internals unless "
                      "integration requires it."),
            "backing_resources": sorted(owned),
            "evidence": [],
            "command_count": contracts_by_subsystem.get(name, 0),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "root": SYSTEM_ROOT,
        "selected_subsystems": selected,
        "nodes": nodes,
        "summary": {
            "system_control_components": len(SYS18_SYSTEM_CONTROL),
            "system_control_implemented": 0,
            "shared_resource_categories": len(SYS18_SHARED_SOC_RESOURCES),
            "shared_categories_proposed": sum(
                1 for n in nodes if n["status"] == NODE_PROPOSED_FROM_REGISTRY),
            "shared_categories_blocked": sum(
                1 for n in nodes if n["status"] == NODE_BLOCKED_PENDING_OWNERSHIP),
            "shared_categories_absent": sum(
                1 for n in nodes if n["status"] == NODE_NOT_PRESENT_IN_SELECTION),
            "subsystem_leaves": len(selected),
        },
    }


def render_architecture_tree(architecture: Mapping[str, Any]) -> str:
    """The SYS-18 tree as text, in the requirement's own shape. Text, not
    SystemVerilog: this renders a description of a structure."""
    lines = [architecture["root"]]
    control = [n for n in architecture["nodes"] if n["kind"] == "SYSTEM_CONTROL"]
    shared = [n for n in architecture["nodes"] if n["kind"] == "SHARED_SOC_RESOURCE"]
    leaves = [n for n in architecture["nodes"] if n["kind"] == "SUBSYSTEM_ENV"]

    groups: List[Tuple[str, List[Mapping[str, Any]]]] = []
    if control:
        groups.append(("System Control", control))
    if shared:
        groups.append(("Shared SoC Resources", shared))

    for gi, (title, members) in enumerate(groups):
        last_group = (gi == len(groups) - 1) and not leaves
        lines.append(("`-- " if last_group else "|-- ") + title)
        pad = "    " if last_group else "|   "
        for mi, node in enumerate(members):
            branch = "`-- " if mi == len(members) - 1 else "|-- "
            lines.append(f"{pad}{branch}{node['name']}  [{node['status']}]")
    for li, node in enumerate(leaves):
        branch = "`-- " if li == len(leaves) - 1 else "|-- "
        lines.append(f"{branch}Selected {node['name']} Env  [{node['status']}]")
    if not leaves:
        lines.append("`-- (no subsystem selected -- nothing is instantiated)")
    return "\n".join(lines)


# ===========================================================================
# SYS-19 -- SYSTEM command.txt: REUSE, DO NOT REINVENT
# ===========================================================================

def system_command_id(contract: Mapping[str, Any]) -> str:
    """The namespaced System-level name for one subsystem command.

    Namespacing is SYS-19's own prescription ("Prefer routing/namespacing to
    existing parsers/sequences"), and it is what makes SYS-20 possible: the
    adapter strips the prefix and the subsystem's own parser sees the byte-
    identical token it sees in subsystem mode.
    """
    return f"{contract['subsystem_id']}{NAMESPACE_SEPARATOR}{contract['command_name']}"


def plan_system_command_reuse(contract_set: Mapping[str, Any]) -> Dict[str, Any]:
    """SYS-19's routing/namespacing PLAN. Emits no command.txt.

    One row per subsystem command, saying which EXISTING subsystem parser /
    agent / VIP sequence a System-level command of that name would route to.
    Every row's target comes from the SYS-8 contract; nothing here invents a
    command, a syntax or a sequence, which is SYS-19's entire point ("Do not
    invent an unrelated command language when existing semantics can be
    reused").

    Two verdicts are not the happy path and both are real:

      AMBIGUOUS_NAMESPACE   the subsystem's own command name already contains
                            the namespace separator, so the namespaced name
                            cannot be split back apart unambiguously and the
                            round-trip SYS-20 depends on is not guaranteed.
      TARGET_UNRESOLVED     the contract resolved no target agent, VIP or
                            sequence. Routing a command to a target nobody
                            identified would be inventing the mapping this
                            requirement forbids inventing, so it is reported
                            unresolved instead.
    """
    rows: List[Dict[str, Any]] = []
    name_owners: Dict[str, List[str]] = {}
    for contract in (contract_set.get("contracts") or []):
        name_owners.setdefault(str(contract["command_name"]), []).append(
            str(contract["subsystem_id"]))

    for contract in (contract_set.get("contracts") or []):
        sid = str(contract["subsystem_id"])
        name = str(contract["command_name"])
        agent = contract.get("target_agent") or "UNKNOWN"
        vip = contract.get("target_vip") or "UNKNOWN"
        sequence = contract.get("target_sequence") or ""
        resolved = [v for v in (agent, vip, sequence) if v and v != "UNKNOWN"]

        if NAMESPACE_SEPARATOR in name:
            verdict = ROUTE_AMBIGUOUS_NAMESPACE
            reason = (f"the subsystem's own command name already contains "
                      f"{NAMESPACE_SEPARATOR!r}, so "
                      f"{system_command_id(contract)!r} cannot be split back into "
                      "(subsystem, command) unambiguously; a human must choose the "
                      "System-level name for this command")
        elif not resolved:
            verdict = ROUTE_TARGET_UNRESOLVED
            reason = ("the SYS-8 contract resolved no target agent, VIP or sequence "
                      "for this command, so there is no existing parser/sequence to "
                      "route to; naming one would be inventing the mapping SYS-19 "
                      "forbids inventing")
        else:
            verdict = ROUTE_REUSES_SUBSYSTEM_SEMANTICS
            reason = ("routes to the subsystem's own existing target; the System "
                      "level adds a namespace prefix and no new command semantics")

        rows.append({
            "system_command": system_command_id(contract),
            "source_subsystem": sid,
            "source_command": name,
            "source_command_file": contract.get("source_command_file", ""),
            "command_category": contract.get("command_category", ""),
            "routes_to_agent": agent,
            "routes_to_vip": vip,
            "routes_to_sequence": sequence,
            "route_verdict": verdict,
            "route_reason": reason,
            # A name used by more than one subsystem is NOT a defect: it is
            # exactly what the namespace is for, and saying so beside the row
            # keeps a reader from reading the shared name as a collision. A
            # collision of EFFECT is SYS-22's question and is answered there.
            "name_shared_with": sorted(set(name_owners.get(name, [])) - {sid}),
            "evidence": list(contract.get("evidence") or [])[:4],
        })

    rows.sort(key=lambda r: r["system_command"])
    by_verdict = {v: sum(1 for r in rows if r["route_verdict"] == v) for v in ROUTE_VERDICTS}
    return {
        "schema_version": SCHEMA_VERSION,
        "namespace_separator": NAMESPACE_SEPARATOR,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "by_route_verdict": by_verdict,
            "namespaced_names_are_unique": len({r["system_command"] for r in rows}) == len(rows),
            "reuse_rate_denominator": len(rows),
        },
        # The load-bearing field of this whole document.
        "system_command_txt_emitted": False,
        "system_command_txt_path": None,
    }


# ===========================================================================
# SYS-20 -- BACKWARD COMPATIBILITY
# ===========================================================================

def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def assess_backward_compatibility(contract_set: Mapping[str, Any],
                                  routing_plan: Mapping[str, Any],
                                  ) -> Dict[str, Any]:
    """SYS-20, in its two independent halves.

    HALF ONE -- "Existing subsystem command.txt must continue to work in
    subsystem mode". This is verified structurally, not asserted: every
    source_command_file's sha256 is recorded here, and nothing in this module
    or the SYS-7/SYS-8 layer beneath it opens a command.txt for writing (SYS-7's
    own rule is "Do not modify command.txt during discovery", and SYS-8's is
    "Keep original command.txt intact"). The digests make that checkable by a
    caller rather than trusted.

    HALF TWO -- "route existing subsystem commands through a System Command
    Router/adapter without forcing wholesale rewrites". The adapter is PLANNED
    and named; it is not built. What the plan states is the round-trip
    property that makes "without wholesale rewrites" true: the adapter strips
    the namespace prefix and hands the subsystem's own parser the byte-
    identical token it already handles. A subsystem holding even one
    AMBIGUOUS_NAMESPACE command cannot state that property, so it is reported
    SUBSYSTEM_MODE_AT_RISK rather than folded into a clean total.
    """
    rows_by_subsystem: Dict[str, List[Mapping[str, Any]]] = {}
    for row in routing_plan.get("rows") or []:
        rows_by_subsystem.setdefault(row["source_subsystem"], []).append(row)

    files_by_subsystem: Dict[str, Set[str]] = {}
    for contract in (contract_set.get("contracts") or []):
        files_by_subsystem.setdefault(str(contract["subsystem_id"]), set()).add(
            str(contract.get("source_command_file") or ""))

    subsystems: List[Dict[str, Any]] = []
    for sid in sorted(set(rows_by_subsystem) | set(files_by_subsystem)):
        rows = rows_by_subsystem.get(sid, [])
        ambiguous = [r["system_command"] for r in rows
                     if r["route_verdict"] == ROUTE_AMBIGUOUS_NAMESPACE]
        unresolved = [r["system_command"] for r in rows
                      if r["route_verdict"] == ROUTE_TARGET_UNRESOLVED]
        files = sorted(f for f in files_by_subsystem.get(sid, set()) if f)
        digests = [{"path": f, "sha256": _sha256(Path(f))} for f in files]

        if ambiguous:
            verdict = COMPAT_AT_RISK
            reason = (f"{len(ambiguous)} command name(s) already contain "
                      f"{NAMESPACE_SEPARATOR!r}, so the namespace prefix cannot be "
                      "stripped back off unambiguously and a byte-identical round "
                      "trip to this subsystem's own parser is not guaranteed: "
                      + ", ".join(ambiguous[:4]))
        else:
            verdict = COMPAT_PRESERVED
            reason = ("every command of this subsystem round-trips: prefix "
                      f"{sid}{NAMESPACE_SEPARATOR} stripped by the adapter leaves the "
                      "byte-identical token this subsystem's own parser already "
                      "handles, so subsystem mode needs no rewrite")

        subsystems.append({
            "subsystem_id": sid,
            "compatibility_verdict": verdict,
            "reason": reason,
            "command_txt_files": digests,
            "command_txt_modified": False,
            "commands_routed": len(rows),
            "ambiguous_commands": ambiguous,
            "unresolved_targets": unresolved,
            # The adapter this subsystem WOULD need. A description, not a build.
            "adapter_plan": {
                "adapter_name": f"{sid}_command_adapter",
                "status": NODE_PLANNED_NOT_IMPLEMENTED,
                "mechanism": (f"strip the leading '{sid}{NAMESPACE_SEPARATOR}' namespace "
                              "prefix, then dispatch the remaining token to this "
                              "subsystem's existing parser/sequence unchanged"),
                "reuses_existing_parser": True,
                "rewrites_required_in_subsystem": [],
                "generated": False,
            },
        })

    at_risk = [s["subsystem_id"] for s in subsystems
               if s["compatibility_verdict"] == COMPAT_AT_RISK]
    return {
        "schema_version": SCHEMA_VERSION,
        "subsystems": subsystems,
        "summary": {
            "subsystem_count": len(subsystems),
            "preserved": sum(1 for s in subsystems
                             if s["compatibility_verdict"] == COMPAT_PRESERVED),
            "at_risk": at_risk,
            "all_subsystem_modes_preserved": not at_risk,
            "any_command_txt_modified": False,
            "adapters_generated": 0,
        },
    }


# ===========================================================================
# SYS-21 -- SYSTEM COMMAND IR
# ===========================================================================

def _completion_condition(contract: Mapping[str, Any]) -> Dict[str, Any]:
    """Derived from the contract's own interrupt/postcondition evidence.

    Order matters and follows how strong the evidence is: an interrupt
    handshake the SYS-7 wait classifier actually classified beats a bare
    following wait, which beats "the command returns and the next statement
    runs". Nothing here reads a command NAME.
    """
    interrupt = contract.get("interrupt_dependency") or {}
    if interrupt.get("depends_on_interrupt"):
        waits = interrupt.get("waits") or []
        return {"condition": COMPLETION_INTERRUPT,
                "detail": (waits[0].get("matched_token") if waits and isinstance(waits[0], dict)
                           else "") or "interrupt-classified wait",
                "basis": interrupt.get("basis", "")}
    for post in (contract.get("postconditions") or []):
        if post.get("kind") == "IMMEDIATELY_FOLLOWING_WAIT":
            return {"condition": COMPLETION_CONDITION_WAIT,
                    "detail": str(post.get("detail") or "")[:160],
                    "basis": f"postcondition cited at {post.get('evidence', '')}"}
    for post in (contract.get("postconditions") or []):
        if post.get("kind") == "FILE_TERMINATES_AFTER":
            return {"condition": COMPLETION_TERMINATES_FILE,
                    "detail": str(post.get("detail") or "")[:160],
                    "basis": f"postcondition cited at {post.get('evidence', '')}"}
    if contract.get("command_category") == rpa.C_TERMINATION:
        return {"condition": COMPLETION_TERMINATES_FILE,
                "detail": str(contract.get("command_name") or ""),
                "basis": "the command's own SYS-7 category is TERMINATION"}
    return {"condition": COMPLETION_IMMEDIATE,
            "detail": "",
            "basis": ("no interrupt-classified wait and no following wait was found "
                      "beside any invocation of this command")}


def _groups_for(contract: Mapping[str, Any]) -> Tuple[str, str, str]:
    """(parallel_group, serialization_group, reason), from the contract's own
    SYS-8 `parallel_safe` verdict.

    No second concurrency classifier: `resolve_cross_subsystem_concurrency()`
    already decided this over the whole contract set, and re-deciding it here
    from the same inputs would be two answers to one question. What this adds
    is only the NAMING of the groups the verdict implies -- a serialization
    group is named after the resource that forced it, so two commands
    contending on one resource land in the same group by construction.
    """
    verdict = contract.get("parallel_safe")
    reason = str(contract.get("parallel_safety_reason") or "")
    if verdict == scc.PARALLEL_SAFE:
        return (f"PARALLEL{NAMESPACE_SEPARATOR}{contract['subsystem_id']}",
                GROUP_NONE, reason)
    if verdict == scc.NOT_PARALLEL_SAFE:
        contended = sorted({s["resource_id"]
                            for s in (contract.get("shared_resource_dependency") or [])
                            if s.get("contention") != "READ_ONLY_SHARING"})
        group = (f"SERIALIZE{NAMESPACE_SEPARATOR}" + "+".join(contended)) if contended else \
                f"SERIALIZE{NAMESPACE_SEPARATOR}{contract['subsystem_id']}"
        return (GROUP_NONE, group, reason)
    return (PARALLEL_GROUP_UNDECIDABLE, GROUP_NONE,
            reason or "cross-subsystem parallel safety was not decidable from this set")


def build_system_command_ir(contract_set: Mapping[str, Any],
                            routing_plan: Optional[Mapping[str, Any]] = None,
                            ) -> Dict[str, Any]:
    """SYS-21's IR, DERIVED from the SYS-8 contracts.

    SYS-21's own closing sentence is "Users should not have to write this IR
    manually", so every one of the 17 fields is computed from a contract and
    none is an input. Two fields are honestly unfilled rather than guessed --
    `priority` and `timeout` -- and each carries a sentinel naming what would
    decide it; see PRIORITY_UNASSIGNED / TIMEOUT_NOT_SPECIFIED.

    SYS-21 also opens with "Only if no equivalent exists". The equivalent that
    exists is `SubsystemCommandContract`, and it is the INPUT here rather than
    a thing re-implemented: every command fact in an IR entry is copied from
    the contract, and the fields the IR adds (`system_command_id`,
    `parallel_group`, `serialization_group`, `priority`) are precisely the
    system-level scheduling properties a subsystem-scoped record cannot carry.
    """
    routing_by_id: Dict[str, Mapping[str, Any]] = {
        r["system_command"]: r for r in ((routing_plan or {}).get("rows") or [])}

    entries: List[Dict[str, Any]] = []
    for contract in (contract_set.get("contracts") or []):
        cid = system_command_id(contract)
        route = routing_by_id.get(cid, {})
        parallel_group, serialization_group, group_reason = _groups_for(contract)
        completion = _completion_condition(contract)

        target_resource = sorted({r["resource_id"]
                                  for r in (contract.get("required_resources") or [])})
        entry = {
            "system_command_id": cid,
            "source_subsystem": str(contract["subsystem_id"]),
            "source_command": str(contract["command_name"]),
            "command_category": str(contract.get("command_category") or ""),
            "target_resource": target_resource,
            "target_sequence": str(contract.get("target_sequence") or ""),
            "arguments": list(contract.get("arguments") or []),
            "dependencies": list(contract.get("ordering_constraints") or []),
            "preconditions": list(contract.get("preconditions") or []),
            "postconditions": list(contract.get("postconditions") or []),
            "parallel_group": parallel_group,
            "serialization_group": serialization_group,
            "shared_resource": sorted({s["resource_id"] for s in
                                       (contract.get("shared_resource_dependency") or [])}),
            "priority": PRIORITY_UNASSIGNED,
            "timeout": TIMEOUT_NOT_SPECIFIED,
            "completion_condition": completion["condition"],
            "evidence": list(contract.get("evidence") or []),
            # Beside the 17, never inside them: a derived field whose BASIS is
            # not recorded next to it cannot be checked by the reader.
            "derivation": {
                "grouping_reason": group_reason,
                "completion_detail": completion["detail"],
                "completion_basis": completion["basis"],
                "priority_reason": ("nothing in a subsystem command.txt states a "
                                    "System-level priority; it is a SYS-24 scheduling "
                                    "decision across subsystems"),
                "timeout_reason": ("the source command.txt states no bound on this "
                                   "command; a delay is not a timeout and an unbounded "
                                   "wait has none"),
                "route_verdict": route.get("route_verdict", ""),
                "source_command_file": str(contract.get("source_command_file") or ""),
                "address_dependency": list(contract.get("address_dependency") or []),
                "shared_resource_dependency": list(
                    contract.get("shared_resource_dependency") or []),
                "reset_dependency": dict(contract.get("reset_dependency") or {}),
                "interrupt_dependency": dict(contract.get("interrupt_dependency") or {}),
                # Carried for SYS-25's CLOCK_DOMAIN_DEPENDENT relationship,
                # which needs both sides' resolved domain to compare and has no
                # other source: the 17 mandated IR fields have no clock field,
                # and re-resolving the domain in the SYS-25 layer would be a
                # second answer to a question `_clock_domain()` answers once.
                # Copied verbatim, including its own UNRESOLVED/NOT_APPLICABLE
                # status, so an unresolved domain stays unresolved rather than
                # becoming an empty-looking agreement.
                "clock_domain": dict(contract.get("clock_domain") or {}),
            },
        }
        entries.append(entry)

    entries.sort(key=lambda e: e["system_command_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "fields": list(SYS21_FIELDS),
        "entries": entries,
        "summary": {
            "entry_count": len(entries),
            "subsystems": sorted({e["source_subsystem"] for e in entries}),
            "parallel_groups": sorted({e["parallel_group"] for e in entries
                                       if e["parallel_group"]}),
            "serialization_groups": sorted({e["serialization_group"] for e in entries
                                            if e["serialization_group"]}),
            "authored_by_user": False,
        },
    }


# ===========================================================================
# SYS-22 -- COMMAND COLLISION DETECTION
# ===========================================================================

def _duplicate_class(entries: Sequence[Mapping[str, Any]]) -> str:
    """Which of SYS-22's six duplicate-SETUP classes a same-named command
    shared by two subsystems falls into.

    Decided from the contract-derived evidence carried on the IR entry, in the
    order of how specific the evidence is: a reset-name token beats a clock
    one, a memory model target beats a CPU one, and the residual is the
    generic DUPLICATE_INITIALIZATION rather than a guess at a more specific
    class.
    """
    resource_ids = [t for e in entries for t in e.get("target_resource") or []]
    command_names = [str(e.get("source_command", "")) for e in entries]
    resource_blob = " ".join(resource_ids)
    name_blob = " ".join(command_names)

    def structural(resource_type: str) -> bool:
        return bool(rpa._matched_tokens(resource_blob, _SRI_TOKENS.get(resource_type, ())))

    def by_verb(resource_type: str) -> bool:
        return bool(rpa._matched_tokens(name_blob, _COMMAND_VERB_TOKENS.get(resource_type, ())))

    # Reset first: it is the most specific claim and the only one with a
    # dedicated contract field behind it rather than a name match.
    if any((e.get("derivation") or {}).get("reset_dependency", {}).get("touches_reset")
           for e in entries):
        return DUPLICATE_RESET_SETUP
    if rpa._matched_tokens(resource_blob + " " + name_blob, rpa.RESET_NAME_TOKENS):
        return DUPLICATE_RESET_SETUP
    if rpa._matched_tokens(resource_blob + " " + name_blob, ("clk", "clock", "pll", "xtal")):
        return DUPLICATE_CLOCK_SETUP
    # A MEMORY_MODEL resource id is structural evidence from the SYS-8
    # contract's own resource kind, not a name match.
    if any(t.startswith(f"{scc.R_MEMORY_MODEL}:") for t in resource_ids):
        return DUPLICATE_MEMORY_INIT
    if structural(sri.RT_MEMORY_MODEL) or by_verb(sri.RT_MEMORY_MODEL):
        return DUPLICATE_MEMORY_INIT
    if structural(sri.RT_APB_MASTER) or by_verb(sri.RT_APB_MASTER):
        return DUPLICATE_APB_PROGRAMMING
    if structural(sri.RT_CPU_BUS_MASTER) or by_verb(sri.RT_CPU_BUS_MASTER):
        return DUPLICATE_CPU_CONFIGURATION
    # The residual is the GENERIC class, never a guess at a more specific one.
    return DUPLICATE_INITIALIZATION


def _refine_contract_conflict(conflict: Mapping[str, Any],
                              ir_by_id: Mapping[str, Mapping[str, Any]],
                              ) -> Optional[Dict[str, Any]]:
    """Map ONE `scc.detect_contract_conflicts()` finding onto SYS-22's own
    vocabulary. The subsystem/resource/address joins are that function's
    output and are not recomputed -- this only classifies them more finely,
    which is the part SYS-22 adds and SYS-8 does not have.
    """
    kind = conflict["conflict_type"]
    contracts = [ir_by_id[c] for c in conflict.get("contracts", []) if c in ir_by_id]

    if kind == "DUPLICATE_ACTIVE_DRIVER":
        # Two subsystems both actively driving one BFM / model / forced
        # hierarchy. If both are INITIALIZATION-category, the specific finding
        # is a duplicated setup of that resource; otherwise it is competing
        # traffic on a shared active agent.
        if contracts and all(c.get("command_category") == rpa.C_INITIALIZATION
                             for c in contracts):
            collision_type = _duplicate_class(contracts)
        else:
            collision_type = COMPETING_ACTIVE_VIP_TRAFFIC
        subject = conflict["resource_id"]
    elif kind == "SHARED_RESOURCE_CONTENTION":
        collision_type = SHARED_RESOURCE_CONTENTION
        subject = conflict["resource_id"]
    elif kind == "ADDRESS_WRITE_COLLISION":
        # Deliberately DEFERRED to `_address_value_collisions()`, which is a
        # strict superset: it performs the same join over the same
        # `address_dependency` records AND compares the values written. Emitting
        # this one too would label a same-value duplicate a "conflicting address
        # setup", which is the misleading finding the value comparison exists to
        # prevent. Nothing is lost -- every address this branch would report is
        # reported there, with more information.
        return None
    else:
        return None

    return {
        "collision_type": collision_type,
        "subject": subject,
        "subsystems": list(conflict["subsystems"]),
        "commands": list(conflict.get("contracts") or []),
        "detail": conflict.get("detail", ""),
        "evidence": list(conflict.get("evidence") or []),
        "derived_from": f"subsystem_command_contract.detect_contract_conflicts:{kind}",
    }


def _address_value_collisions(ir: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Address-level findings that need the per-address VALUE pairing.

    This is where SYS-22's "conflicting register writes" and "incompatible
    mode setup" are separated from a plain address collision, and where a
    same-value duplicate is separated from all three. `scc` reports that two
    subsystems write one address; only the values say whether that is a
    conflict (different values, last writer wins, and nothing decided which
    should) or a duplicated initialization (same value written twice).
    """
    per_address: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for entry in ir.get("entries") or []:
        sid = entry["source_subsystem"]
        for dep in (entry.get("derivation") or {}).get("address_dependency") or []:
            if dep.get("access") != "WRITE":
                continue
            slot = per_address.setdefault(dep["address"], {}).setdefault(
                sid, {"values": set(), "commands": set(), "categories": set(),
                      "evidence": []})
            slot["values"].update(dep.get("written_values") or [])
            slot["commands"].add(entry["system_command_id"])
            slot["categories"].add(entry["command_category"])
            for ev in dep.get("evidence") or []:
                if ev not in slot["evidence"]:
                    slot["evidence"].append(ev)

    findings: List[Dict[str, Any]] = []
    for address, by_subsystem in sorted(per_address.items()):
        if len(by_subsystem) < 2:
            continue
        value_sets = [s["values"] for s in by_subsystem.values()]
        all_values = sorted(set().union(*value_sets)) if value_sets else []
        comparable = all(s for s in value_sets)
        categories = set().union(*(s["categories"] for s in by_subsystem.values()))

        if not comparable:
            collision_type = CONFLICTING_ADDRESS_SETUP
            detail = (f"{len(by_subsystem)} subsystems write {address}; at least one "
                      "wrote a non-literal value, so the values cannot be compared "
                      "and whether they agree is UNDETERMINED")
        elif len(all_values) > 1:
            initialization_only = categories <= {rpa.C_INITIALIZATION}
            collision_type = (INCOMPATIBLE_MODE_SETUP if initialization_only
                              else CONFLICTING_REGISTER_WRITE)
            detail = (f"{len(by_subsystem)} subsystems write DIFFERENT values to "
                      f"{address}: " + "; ".join(
                          f"{sid}={sorted(slot['values'])}"
                          for sid, slot in sorted(by_subsystem.items())))
        else:
            collision_type = _duplicate_class(
                [e for e in ir.get("entries") or []
                 if e["system_command_id"] in
                 set().union(*(s["commands"] for s in by_subsystem.values()))])
            detail = (f"{len(by_subsystem)} subsystems write the SAME value "
                      f"{all_values[0]} to {address} -- a duplicated setup, not a "
                      "conflicting write. SYS-23 decides what to do with it; its own "
                      "rule is that a command is not removed without evidence")

        findings.append({
            "collision_type": collision_type,
            "subject": address,
            "subsystems": sorted(by_subsystem),
            "commands": sorted(c for s in by_subsystem.values() for c in s["commands"]),
            "detail": detail,
            "evidence": sorted({e for s in by_subsystem.values() for e in s["evidence"]})[:8],
            "written_values": {sid: sorted(slot["values"])
                               for sid, slot in sorted(by_subsystem.items())},
            "derived_from": "system_command_ir.address_dependency.written_values",
        })
    return findings


def _duplicate_command_collisions(ir: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The same command name invoked by two or more subsystems.

    This is the shape SYS-22's duplicate-setup list is written for and the one
    `scc.detect_contract_conflicts()` structurally cannot see: two subsystems
    each calling `` `GMODEL.GLOBAL_INIT `` collide on the ACT, whether or not
    that act happens to touch a resource both contracts named. Only
    non-REPEATABLE-looking categories qualify -- a plain register read shared
    by two subsystems is not a duplicated system setup, and reporting it as
    one would drown the real findings.
    """
    setup_categories = {rpa.C_INITIALIZATION, rpa.C_MEMORY_BACKDOOR, rpa.C_MODEL_TASK}
    by_name: Dict[str, Dict[str, List[Mapping[str, Any]]]] = {}
    for entry in ir.get("entries") or []:
        if entry["command_category"] not in setup_categories:
            continue
        by_name.setdefault(entry["source_command"], {}).setdefault(
            entry["source_subsystem"], []).append(entry)

    findings: List[Dict[str, Any]] = []
    for name, by_subsystem in sorted(by_name.items()):
        if len(by_subsystem) < 2:
            continue
        entries = [e for group in by_subsystem.values() for e in group]
        findings.append({
            "collision_type": _duplicate_class(entries),
            "subject": name,
            "subsystems": sorted(by_subsystem),
            "commands": sorted(e["system_command_id"] for e in entries),
            "detail": (f"{len(by_subsystem)} subsystems each invoke {name} "
                       f"(category {entries[0]['command_category']}). At System level "
                       "these are one act performed more than once unless evidence "
                       "shows they target different physical resources"),
            "evidence": sorted({ev for e in entries for ev in e["evidence"]})[:8],
            "derived_from": "system_command_ir.source_command",
        })
    return findings


def _ordering_collisions(ir: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """SYS-22's "ordering conflicts", defined so it is computable and real.

    One subsystem establishes a resource as a PRECONDITION -- something its
    SYS-8 contract records as holding before every invocation -- while a
    DIFFERENT subsystem WRITES that same resource as ordinary traffic. The
    second subsystem's write can land after the first's precondition was
    established and invalidate it, and nothing in either file orders the two.
    That is an ordering conflict in the exact sense SYS-22 means: neither
    command is wrong, and their relative order is unspecified and matters.

    Deliberately NOT reported: a precondition and a write inside ONE
    subsystem. A command.txt is sequential by construction, so its own order
    is stated, and flagging it would make every single-subsystem set noisy.
    """
    # Which subsystems invoke each command name, and what each command writes.
    invokers: Dict[str, Set[str]] = {}
    writes_by_subsystem: Dict[str, Set[str]] = {}
    for entry in ir.get("entries") or []:
        invokers.setdefault(entry["source_command"], set()).add(entry["source_subsystem"])
        for dep in (entry.get("derivation") or {}).get("shared_resource_dependency") or []:
            if dep.get("this_access") == "WRITE":
                writes_by_subsystem.setdefault(
                    entry["source_subsystem"], set()).add(dep["resource_id"])

    # What each command name targets, so "another subsystem writes the resource
    # my precondition was established through" is answerable.
    targets_of: Dict[str, Set[str]] = {}
    for entry in ir.get("entries") or []:
        targets_of.setdefault(entry["source_command"], set()).update(
            entry.get("target_resource") or [])

    findings: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for entry in ir.get("entries") or []:
        sid = entry["source_subsystem"]
        for pre in entry.get("preconditions") or []:
            if pre.get("kind") != "PRECEDING_INITIALIZATION":
                continue
            init_command = str(pre.get("detail") or "")
            if not init_command:
                continue
            # The finding is only real when ANOTHER subsystem can disturb the
            # thing this precondition established. Two ways, both evidenced:
            # it invokes the same initialization again, or it writes a resource
            # that initialization targets.
            disturbers: Dict[str, str] = {}
            for other in sorted(invokers.get(init_command, set()) - {sid}):
                disturbers[other] = f"also invokes {init_command}"
            for other, written in sorted(writes_by_subsystem.items()):
                if other == sid or other in disturbers:
                    continue
                overlap = sorted(written & targets_of.get(init_command, set()))
                if overlap:
                    disturbers[other] = f"writes {', '.join(overlap[:3])}, which {init_command} targets"
            if not disturbers:
                continue
            # ONE finding per (initialization, subsystem pair) -- not one per
            # command that happens to depend on it. Every REGISTER_ACCESS
            # command in a file shares the same preceding initialization, so
            # per-command rows would restate one finding N times and bury the
            # collisions that are genuinely distinct.
            for other, why in disturbers.items():
                key = (init_command, *sorted((sid, other)))
                record = findings.setdefault(key, {
                    "collision_type": ORDERING_CONFLICT,
                    "subject": f"initialization {init_command}",
                    "subsystems": sorted({sid, other}),
                    "commands": [],
                    "detail": (
                        f"{sid} requires {init_command} to have run before its "
                        f"commands, and {other} {why}. Neither file states an order "
                        "between the two subsystems, so the second can re-run or "
                        "overwrite that initialization after the first established "
                        "it and depended on it"),
                    "evidence": [],
                    "derived_from": "system_command_ir.preconditions x source_command",
                })
                for cmd in (entry["system_command_id"],):
                    if cmd not in record["commands"]:
                        record["commands"].append(cmd)
                ev = str(pre.get("evidence") or "")
                if ev and ev not in record["evidence"]:
                    record["evidence"].append(ev)

    out = list(findings.values())
    for record in out:
        record["commands"] = sorted(record["commands"])
        record["evidence"] = sorted(record["evidence"])[:8]
    return out


def _collision_key(finding: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (finding["collision_type"], str(finding["subject"]),
            ",".join(sorted(finding["subsystems"])))


def detect_command_collisions(ir: Mapping[str, Any],
                              contract_set: Optional[Mapping[str, Any]] = None,
                              ) -> Dict[str, Any]:
    """SYS-22 over one System Command IR. Reports; never chooses.

    Four sources feed it, and the first is REFINED existing output rather than
    a re-derivation: `scc.detect_contract_conflicts()`'s resource/address
    joins, the per-address value comparison the IR carries, the same-command
    duplicate-setup detector, and the cross-subsystem ordering detector.

    Every finding survives. Two detectors reaching the same (type, subject,
    subsystems) triple are merged into one finding that cites BOTH derivations
    -- that is deduplication of a REPORT, not of a collision, and the merged
    record names both sources so nothing is quietly dropped. A collision
    reached by only one detector is never suppressed by another's silence,
    because SYS-22's closing rule is "Report all collisions; do not silently
    choose".
    """
    ir_by_id = {e["system_command_id"]: e for e in (ir.get("entries") or [])}
    contract_id_to_system_id = {}
    for entry in ir.get("entries") or []:
        contract_id_to_system_id[
            f"{entry['source_subsystem']}::"
            f"{Path((entry.get('derivation') or {}).get('source_command_file') or '').name}::"
            f"{entry['source_command']}"] = entry["system_command_id"]

    raw: List[Dict[str, Any]] = []
    for conflict in ((contract_set or {}).get("conflicts") or []):
        remapped = dict(conflict)
        remapped["contracts"] = [contract_id_to_system_id.get(c, c)
                                 for c in conflict.get("contracts") or []]
        refined = _refine_contract_conflict(remapped, ir_by_id)
        if refined is not None:
            raw.append(refined)
    raw.extend(_address_value_collisions(ir))
    raw.extend(_duplicate_command_collisions(ir))
    raw.extend(_ordering_collisions(ir))

    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for finding in raw:
        # Every detector names its commands by whatever id its own source used;
        # remap once, here, so a reader never meets two id spellings for one
        # command in one report.
        finding["commands"] = sorted({contract_id_to_system_id.get(c, c)
                                      for c in finding.get("commands") or []})
        key = _collision_key(finding)
        if key in merged:
            existing = merged[key]
            existing["derived_from"] = "; ".join(sorted(
                set(existing["derived_from"].split("; ")) | {finding["derived_from"]}))
            existing["commands"] = sorted(set(existing["commands"]) | set(finding["commands"]))
            existing["evidence"] = sorted(set(existing["evidence"]) | set(finding["evidence"]))[:8]
            continue
        record = dict(finding)
        record["severity"] = COLLISION_SEVERITY[record["collision_type"]]
        record["blocks_integration"] = record["collision_type"] in BLOCKING_COLLISIONS
        record["resolution"] = (
            "STOP_AUTOMATIC_SYSTEM_INTEGRATION_UNTIL_A_HUMAN_DECIDES"
            if record["blocks_integration"] else
            "REPORT_FOR_HUMAN_REVIEW -- no command is removed, merged or reordered here")
        record["collision_id"] = "SYSCOL-" + hashlib.sha256(
            "|".join(_collision_key(record)).encode("utf-8")).hexdigest()[:10].upper()
        merged[key] = record

    # Per-SIDE evidence, attributed centrally so every detector's findings carry
    # it in the same shape. SYS-22's escalation needs one real citation PER
    # subsystem: `source_authority.assert_both_evidence_paths_present()` refuses
    # a conflict question that names a disagreement without citing where both
    # halves of it live, and a single shared evidence list cannot supply that.
    for record in merged.values():
        by_subsystem: Dict[str, List[str]] = {}
        for command in record["commands"]:
            entry = ir_by_id.get(command)
            if entry is None:
                continue
            paths = by_subsystem.setdefault(entry["source_subsystem"], [])
            source_file = (entry.get("derivation") or {}).get("source_command_file") or ""
            for citation in entry.get("evidence") or []:
                # An `evidence` citation is 'name:line'; prefixing the real
                # source file makes it locatable from the report alone.
                located = (f"{source_file}:{citation.rsplit(':', 1)[-1]}"
                           if source_file and ":" in citation else citation)
                if located not in paths and len(paths) < 4:
                    paths.append(located)
        for sid in record["subsystems"]:
            if not by_subsystem.get(sid):
                by_subsystem[sid] = [
                    f"{sid}: no per-command citation resolved for this finding; "
                    f"see {record['collision_id']} evidence {record['evidence'][:2]}"]
        record["evidence_by_subsystem"] = {k: by_subsystem[k] for k in sorted(by_subsystem)}

    findings = sorted(merged.values(),
                      key=lambda f: (f["severity"], f["subject"], f["collision_id"]))
    by_type = {t: sum(1 for f in findings if f["collision_type"] == t)
               for t in SYS22_COLLISION_TYPES}
    return {
        "schema_version": SCHEMA_VERSION,
        "collisions": findings,
        "summary": {
            "collision_count": len(findings),
            "by_collision_type": by_type,
            "blocking": sum(1 for f in findings if f["blocks_integration"]),
            "subsystems": sorted({s for f in findings for s in f["subsystems"]}),
            "no_collision_silently_resolved": True,
        },
    }


def escalate_command_collisions(store, collisions: Mapping[str, Any],
                                *, now=None) -> List[dict]:
    """File every collision into the REAL question queue through
    `source_authority.escalate_conflict()`, and return the persisted records.

    Both sides of a collision are a subsystem's own reference command.txt --
    tier 2, `reference_command_txt`, the SAME tier. `resolve_conflict()`
    therefore returns UNDECIDABLE_SAME_AUTHORITY, which is the correct and
    intended answer here: the authority order cannot say which of two equally
    real commands should own a resource, and this module never asks it to.
    Escalating is then mandatory rather than advisory, exactly as it is for
    `reference_pattern_audit`'s host/DUT asymmetry, whose two sides are also
    both tier 2.

    A collision spanning N > 2 subsystems is filed as PAIRWISE questions --
    `escalate_conflict()` refuses more than 3 sides rather than truncating,
    because dropping a side would drop its evidence path with it, and its own
    docstring prescribes the pairwise split.

    `domain="env"`: which of two subsystems owns a shared resource at System
    level is an environment-composition question, not a DUT or VIP question.
    Idempotent, because the Q-ID derives from the collision's own subject and
    evidence.
    """
    from . import source_authority as sa

    records: List[dict] = []
    for finding in collisions.get("collisions") or []:
        subsystems = list(finding["subsystems"])
        pairs = [(a, b) for i, a in enumerate(subsystems) for b in subsystems[i + 1:]]
        for a, b in pairs:
            claims = []
            for sid in (a, b):
                cmds = [c for c in finding["commands"]
                        if c.startswith(f"{sid}{NAMESPACE_SEPARATOR}")]
                paths = (finding.get("evidence_by_subsystem") or {}).get(sid) or []
                claims.append(sa.SourceClaim(
                    source="reference_command_txt",
                    claim=(f"{sid} owns {finding['subject']} via "
                           f"{', '.join(cmds[:3]) or 'its own command.txt'}"),
                    # Each side cites its OWN command.txt lines, never the
                    # other's and never a merged list -- that is what makes the
                    # question answerable by the person who receives it.
                    evidence_path="; ".join(paths[:3]) or f"{sid}'s own command.txt",
                ))
            conflict = sa.resolve_conflict(claims)
            record = sa.escalate_conflict(
                store, conflict, domain="env",
                subject=(f"System-level ownership of {finding['subject']} "
                         f"({finding['collision_type']}, {finding['collision_id']})"),
                context_path=f"{finding['collision_id']}:{a}:{b}",
                extra_context={"affects_spec_intent": True,
                               "system_level_collision": finding["collision_type"]},
                now=now)
            if record is not None:
                records.append(record)
    return records


# ===========================================================================
# Front door
# ===========================================================================

def assert_no_emitted_artifacts(document: Mapping[str, Any]) -> None:
    """The SYS-39/SYS-40 boundary, as a runtime check rather than a comment.

    Raises unless the document states, on its own face, that no System
    command.txt was written, no adapter was generated and no System Control
    component was implemented. A planning document that could not answer these
    questions about itself would be exactly the artifact a reader might mistake
    for the real thing.
    """
    routing = document.get("system_command_routing_plan") or {}
    compat = document.get("backward_compatibility") or {}
    architecture = document.get("system_architecture") or {}
    if routing.get("system_command_txt_emitted") is not False:
        raise SystemCommandPlanError("SYSTEM_COMMAND_TXT_EMITTED", {
            "hint": "SYS-19/SYS-40: emitting a System command.txt needs explicit approval."})
    if routing.get("system_command_txt_path") is not None:
        raise SystemCommandPlanError("SYSTEM_COMMAND_TXT_PATH_SET", {
            "path": routing.get("system_command_txt_path")})
    if (compat.get("summary") or {}).get("adapters_generated") not in (0, None):
        raise SystemCommandPlanError("COMMAND_ADAPTER_GENERATED", {})
    if (compat.get("summary") or {}).get("any_command_txt_modified"):
        raise SystemCommandPlanError("SUBSYSTEM_COMMAND_TXT_MODIFIED", {})
    for node in architecture.get("nodes") or []:
        if node["kind"] == "SYSTEM_CONTROL" and node["status"] != NODE_PLANNED_NOT_IMPLEMENTED:
            raise SystemCommandPlanError("SYSTEM_CONTROL_COMPONENT_IMPLEMENTED", {
                "node": node["name"], "status": node["status"]})


def build_system_command_plan(integration_plan: Mapping[str, Any],
                              contract_set: Mapping[str, Any],
                              *,
                              selection: Optional[Mapping[str, Any]] = None,
                              ) -> Dict[str, Any]:
    """SYS-18 -> SYS-19 -> SYS-20 -> SYS-21 -> SYS-22 over one SYS-15..17
    integration plan and one SYS-8 contract set. Reads only; writes nothing."""
    architecture = build_system_architecture(
        integration_plan, selection=selection, contract_set=contract_set)
    routing = plan_system_command_reuse(contract_set)
    compatibility = assess_backward_compatibility(contract_set, routing)
    ir = build_system_command_ir(contract_set, routing)
    collisions = detect_command_collisions(ir, contract_set)

    document = {
        "schema_version": SCHEMA_VERSION,
        "system_architecture": architecture,
        "system_command_routing_plan": routing,
        "backward_compatibility": compatibility,
        "system_command_ir": ir,
        "command_collisions": collisions,
        "summary": {
            "selected_subsystems": architecture["selected_subsystems"],
            "system_commands": routing["summary"]["row_count"],
            "routes_reusing_subsystem_semantics": routing["summary"][
                "by_route_verdict"][ROUTE_REUSES_SUBSYSTEM_SEMANTICS],
            "ir_entries": ir["summary"]["entry_count"],
            "collisions": collisions["summary"]["collision_count"],
            "blocking_collisions": collisions["summary"]["blocking"],
            "subsystem_modes_preserved": compatibility["summary"][
                "all_subsystem_modes_preserved"],
            "command_plan_clean": (
                collisions["summary"]["blocking"] == 0
                and compatibility["summary"]["all_subsystem_modes_preserved"]
                and routing["summary"]["by_route_verdict"][ROUTE_AMBIGUOUS_NAMESPACE] == 0),
        },
        "artifacts_generated": [],
        "phase_boundary": PHASE_BOUNDARY,
    }
    assert_no_emitted_artifacts(document)
    return document


def plan_system_commands(root, selected: Sequence[str], *,
                         declared: Optional[Mapping[str, Any]] = None,
                         knowledge_center_client: Any = None,
                         inventory_overlay_path=None,
                         ) -> Dict[str, Any]:
    """Front door: SYS-1 selection -> SYS-5..8 analysis -> SYS-9..14 resources
    -> SYS-15..17 registry/matrices -> SYS-18..22 architecture, command plan,
    IR and collisions.

    The whole lower stack is reused through
    `system_resource_registry.plan_system_integration()`, which itself goes
    through `subsystem_discovery.require_explicit_selection()` -- so SYS-1's
    refusal to compose a set the user did not choose is not bypassed by adding
    a verb on top of it.
    """
    result = srr.plan_system_integration(
        root, selected, declared=declared,
        knowledge_center_client=knowledge_center_client,
        inventory_overlay_path=inventory_overlay_path)
    command_plan = build_system_command_plan(
        result["integration_plan"],
        result["synthesis"].get("contract_set") or {"contracts": [], "conflicts": []},
        selection=result["selection"])
    return {**result, "command_plan": command_plan}


# ===========================================================================
# Reporting
# ===========================================================================

def validate_system_command_plan(document: Mapping[str, Any]) -> None:
    """Validate a `build_system_command_plan()` document against the real JSON
    schema. Raises jsonschema.ValidationError on a violation."""
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


def _cell(value: Any) -> str:
    """Markdown cell text with pipes escaped -- a value containing `|` must not
    silently gain a column."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_routing_table(routing_plan: Mapping[str, Any]) -> str:
    columns = ["SYSTEM COMMAND", "SOURCE SUBSYSTEM", "SOURCE COMMAND", "CATEGORY",
               "ROUTES TO AGENT", "ROUTES TO SEQUENCE", "VERDICT"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in routing_plan.get("rows") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["system_command"], row["source_subsystem"], row["source_command"],
            row["command_category"], row["routes_to_agent"],
            row["routes_to_sequence"] or "-", row["route_verdict"],
        )) + " |")
    if len(lines) == 2:
        lines.append("| _(no subsystem command was analysed)_ |" + " - |" * (len(columns) - 1))
    return "\n".join(lines)


def render_command_ir_table(ir: Mapping[str, Any]) -> str:
    columns = ["SYSTEM_COMMAND_ID", "CATEGORY", "TARGET_RESOURCE", "PARALLEL_GROUP",
               "SERIALIZATION_GROUP", "SHARED_RESOURCE", "PRIORITY", "TIMEOUT",
               "COMPLETION_CONDITION"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for entry in ir.get("entries") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            entry["system_command_id"], entry["command_category"],
            ",".join(entry["target_resource"][:3]) or "-",
            entry["parallel_group"] or "-", entry["serialization_group"] or "-",
            ",".join(entry["shared_resource"][:3]) or "-",
            entry["priority"], entry["timeout"], entry["completion_condition"],
        )) + " |")
    if len(lines) == 2:
        lines.append("| _(no IR entry derived)_ |" + " - |" * (len(columns) - 1))
    return "\n".join(lines)


def render_collision_table(collisions: Mapping[str, Any]) -> str:
    columns = ["ID", "COLLISION TYPE", "SUBJECT", "SUBSYSTEMS", "BLOCKS INTEGRATION"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for finding in collisions.get("collisions") or []:
        lines.append("| " + " | ".join(_cell(v) for v in (
            finding["collision_id"], finding["collision_type"], finding["subject"],
            ",".join(finding["subsystems"]),
            "YES" if finding["blocks_integration"] else "no",
        )) + " |")
    if len(lines) == 2:
        lines.append("| _(no collision detected in this command set)_ |"
                     + " - |" * (len(columns) - 1))
    return "\n".join(lines)


def format_system_command_plan_report(document: Mapping[str, Any]) -> str:
    """The SYS-18..SYS-22 deliverable. Reporting only -- this function emits no
    SystemVerilog, no command.txt and no adapter source."""
    summary = document["summary"]
    architecture = document["system_architecture"]
    routing = document["system_command_routing_plan"]
    compatibility = document["backward_compatibility"]
    ir = document["system_command_ir"]
    collisions = document["command_collisions"]

    out = ["# SYSTEM ARCHITECTURE AND SYSTEM command.txt PLAN (SYS-18..SYS-22)", "",
           f"- selected subsystems: {summary['selected_subsystems']}",
           f"- System-level commands planned: {summary['system_commands']} "
           f"({summary['routes_reusing_subsystem_semantics']} reuse an existing "
           "subsystem target)",
           f"- System Command IR entries: {summary['ir_entries']} (all derived; "
           "none authored by hand)",
           f"- collisions: {summary['collisions']} "
           f"({summary['blocking_collisions']} blocking)",
           f"- subsystem modes preserved: {summary['subsystem_modes_preserved']}",
           f"- command plan clean: {summary['command_plan_clean']}", "",
           "## SYS-18 SYSTEM-LEVEL ARCHITECTURE", "",
           "```", render_architecture_tree(architecture), "```", "",
           "System Control's three components are PLANNED_NOT_IMPLEMENTED, and stay "
           "that way through this whole workflow: a parser/router, a scenario planner "
           "and a virtual sequencer are code, and code is SYS-40. A shared-resource "
           "category reading NOT_PRESENT_IN_SELECTION is an absence in the evidence, "
           "not a decision that the System does not need one.", ""]

    blocked_nodes = [n for n in architecture["nodes"]
                     if n["status"] == NODE_BLOCKED_PENDING_OWNERSHIP]
    if blocked_nodes:
        out += ["### Shared resources blocked pending ownership", ""]
        for node in blocked_nodes:
            out.append(f"- {node['name']}: {node['backing_resources']} -- {node['basis']}")
        out.append("")

    out += ["## SYS-19 SYSTEM command.txt REUSE / ROUTING PLAN", "",
            f"Namespace separator: `{routing['namespace_separator']}`. Each row says "
            "which EXISTING subsystem parser/agent/sequence a System-level command of "
            "that name would route to. No System command.txt is emitted by this plan "
            f"(`system_command_txt_emitted: {routing['system_command_txt_emitted']}`).",
            "", render_routing_table(routing), ""]

    ambiguous = [r for r in routing["rows"]
                 if r["route_verdict"] != ROUTE_REUSES_SUBSYSTEM_SEMANTICS]
    if ambiguous:
        out += ["### Rows a human must resolve", ""]
        for row in ambiguous:
            out.append(f"- [{row['route_verdict']}] {row['system_command']}: "
                       f"{row['route_reason']}")
        out.append("")

    out += ["## SYS-20 BACKWARD COMPATIBILITY", "",
            "| SUBSYSTEM | VERDICT | COMMANDS ROUTED | command.txt MODIFIED | "
            "ADAPTER | ADAPTER STATUS |",
            "|---|---|---|---|---|---|"]
    for sub in compatibility["subsystems"]:
        out.append("| {} | {} | {} | {} | {} | {} |".format(
            _cell(sub["subsystem_id"]), _cell(sub["compatibility_verdict"]),
            sub["commands_routed"], sub["command_txt_modified"],
            _cell(sub["adapter_plan"]["adapter_name"]),
            _cell(sub["adapter_plan"]["status"])))
    if not compatibility["subsystems"]:
        out.append("| _(no subsystem analysed)_ | - | - | - | - | - |")
    out += ["", "Every subsystem's own command.txt is recorded with its sha256 and was "
            "opened read-only. The adapter named per subsystem does not exist: its "
            "mechanism is to strip the namespace prefix and hand the subsystem's own "
            "parser the byte-identical token it already handles, so subsystem mode "
            "needs no rewrite. Building it is SYS-40.", ""]

    at_risk = compatibility["summary"]["at_risk"]
    if at_risk:
        out += ["### Subsystem modes at risk", ""]
        for sub in compatibility["subsystems"]:
            if sub["compatibility_verdict"] == COMPAT_AT_RISK:
                out.append(f"- {sub['subsystem_id']}: {sub['reason']}")
        out.append("")

    out += ["## SYS-21 SYSTEM COMMAND IR", "",
            f"Seventeen fields: {', '.join(SYS21_FIELDS)}.", "",
            render_command_ir_table(ir), "",
            f"`priority` is {PRIORITY_UNASSIGNED} and `timeout` is "
            f"{TIMEOUT_NOT_SPECIFIED} for every entry: nothing in a subsystem's own "
            "command.txt states either, and deriving one anyway would present an "
            "invented verification parameter as evidence. Every other field is "
            "computed from the SYS-8 contract -- SYS-21's own rule is that users "
            "should not have to write this IR manually.", ""]

    out += ["## SYS-22 COMMAND COLLISION DETECTION", "",
            render_collision_table(collisions), "",
            f"Collision classes: {', '.join(SYS22_COLLISION_TYPES)}.",
            "Every collision is reported. None is removed, merged away, reordered or "
            "auto-resolved -- SYS-22's own closing rule is \"Report all collisions; do "
            "not silently choose\".", ""]

    if collisions["collisions"]:
        out += ["### Detail", ""]
        for finding in collisions["collisions"]:
            out.append(f"- **{finding['collision_type']}** ({finding['collision_id']}) "
                       f"{finding['subject']}: {finding['detail']}")
            out.append(f"  - subsystems: {finding['subsystems']}; "
                       f"commands: {finding['commands'][:4]}")
            out.append(f"  - evidence: {finding['evidence'][:3]}")
            out.append(f"  - {finding['resolution']}")
        out.append("")

    out += ["## PHASE BOUNDARY", "", document["phase_boundary"]]
    return "\n".join(out)
