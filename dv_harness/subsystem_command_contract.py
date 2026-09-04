"""SYS-8 of the System-Level Verification Integration workflow: the
SubsystemCommandContract -- one machine-readable contract per command a
subsystem's command.txt actually invokes, carrying the resource /
dependency / concurrency-safety facts SYS-19..SYS-25 later need in order to
schedule, route and collision-check commands across subsystems.

  SYS-8  "Represent each command.txt as SubsystemCommandContract or extend an
          existing equivalent schema: subsystem_id, source_command_file,
          command_name, command_category, arguments, target_agent, target_vip,
          target_sequence, required_resources, preconditions, postconditions,
          ordering_constraints, clock_domain, reset_dependency,
          interrupt_dependency, address_dependency, shared_resource_dependency,
          parallel_safe, serialization_required, evidence.
          Keep original command.txt intact."

WHY A NEW MODULE AND NOT AN EXTENSION. The two existing analogs were both
checked before this was written and neither is the right home:

  - .dv-workflow/command_inventory.csv (produced by the real
    .claude/skills/CORE/command-inventory skill, 24 real USB entries) is
    command IDENTITY plus producer/handler mapping -- COMMAND_ID, PROTOCOL,
    COMMAND, PARAMETERS, SOURCE, USER_SCOPE, HANDLER, VIP_SEQUENCE, STATUS,
    CONFIDENCE. It carries no dependency, resource, ordering or concurrency
    column at all, and it is an LLM-produced CSV, not a derived artifact a
    scheduler can trust to be complete. It is READ here as a declared
    overlay (`load_command_inventory_overlay()`) so its real HANDLER /
    VIP_SEQUENCE / USER_SCOPE values are reused rather than re-derived --
    never rewritten.
  - reference_pattern_audit.py owns the SYS-7 grammar layer this module is
    built on. It stays per-FILE: it analyzes one command.txt in isolation and
    has no concept of a subsystem, of a second subsystem, or of two
    subsystems contending for one resource. `parallel_safe` is meaningless
    inside one file (a command.txt is sequential by construction) and only
    becomes a real question across subsystems -- which is precisely why the
    contract set, not the file analysis, is where it is computed.

WHAT THIS MODULE DOES NOT DO. Discovery/analysis/planning/reporting only, per
the master prompt's own SYS-39 stop condition. It reads command.txt files and
writes contract JSON; it never modifies a command.txt (SYS-8's own "Keep
original command.txt intact", and SYS-7's "Do not modify command.txt during
discovery"), never emits a System command.txt, a System Virtual Sequencer, a
command router or any System-Level UVM source. `detect_contract_conflicts()`
REPORTS a cross-subsystem contention; resolving one is SYS-11..SYS-13 and
acting on it is SYS-40, which needs its own explicit human approval.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import reference_pattern_audit as rpa

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "subsystem_command_contract.schema.json"
SCHEMA_VERSION = "1.0"

# SYS-8's field list, verbatim and in its own order. Held to the dataclass and
# to the JSON schema by a test, so the requirement, the code and the schema
# cannot drift apart in any direction.
SYS8_FIELDS: tuple = (
    "subsystem_id",
    "source_command_file",
    "command_name",
    "command_category",
    "arguments",
    "target_agent",
    "target_vip",
    "target_sequence",
    "required_resources",
    "preconditions",
    "postconditions",
    "ordering_constraints",
    "clock_domain",
    "reset_dependency",
    "interrupt_dependency",
    "address_dependency",
    "shared_resource_dependency",
    "parallel_safe",
    "serialization_required",
    "evidence",
)

# parallel_safe is three-valued on purpose. "we compared this command against
# other subsystems' commands and found no contention" and "there was no other
# subsystem to compare against" are different facts, and a contract set built
# from ONE subsystem can only honestly report the second.
PARALLEL_SAFE = "PARALLEL_SAFE"
NOT_PARALLEL_SAFE = "NOT_PARALLEL_SAFE"
PARALLEL_SAFETY_UNKNOWN = "UNKNOWN"
PARALLEL_SAFETY_VALUES: tuple = (PARALLEL_SAFE, NOT_PARALLEL_SAFE, PARALLEL_SAFETY_UNKNOWN)

# Resource-id vocabulary. One flat, prefixed namespace so SYS-9's resource
# inventory and SYS-10's duplicate detection can compare two subsystems'
# resource sets by string equality instead of by class name -- SYS-10's own
# rule is "Do not decide duplicates by class names alone".
R_REGISTER_BLOCK = "REGISTER_BLOCK"   # a register base address the command writes/reads
R_BFM = "BFM"                         # the HOST/DUT-side bus-functional-model driver
R_MODEL = "MODEL"                     # a VIP/model instance whose task is invoked
R_MEMORY_MODEL = "MEMORY_MODEL"       # a model instance whose name evidences a memory
R_HIERARCHY = "HIERARCHY"             # a design hierarchy root the command reaches into
RESOURCE_KINDS: tuple = (R_REGISTER_BLOCK, R_BFM, R_MODEL, R_MEMORY_MODEL, R_HIERARCHY)

# Which statement kinds count as WRITING (i.e. actively driving) a resource.
# Only a writing use creates an active-driver contention; two subsystems both
# READING one register block is not a driver conflict, and reporting it as one
# is how a dedup mechanism trains its users to ignore it.
_WRITING_KINDS: frozenset = frozenset({
    rpa.K_REGISTER_WRITE, rpa.K_BACKDOOR_ASSIGN, rpa.K_FORCE, rpa.K_RELEASE,
    rpa.K_MODEL_TASK_CALL, rpa.K_MEMORY_LOAD,
})

# How many distinct literal argument values to keep per argument position. The
# full set of 1300+ literals is the file, not a contract; the point of keeping
# any is that a reader can see the shape and spot-check a citation.
MAX_DISTINCT_ARG_VALUES = 8


@dataclass
class SubsystemCommandContract:
    """One command of one subsystem's command.txt, as SYS-8's own 20 fields.

    Granularity is (source_command_file, command_name) -- the same granularity
    .dv-workflow/command_inventory.csv already uses for a real command, and the
    granularity SYS-19..25 need (they schedule commands, not individual macro
    invocations). Per-invocation detail is not lost: `evidence` cites every
    invocation line, and `address_dependency` carries every distinct address.
    """
    subsystem_id: str
    source_command_file: str
    command_name: str
    command_category: str
    arguments: List[Dict[str, Any]] = field(default_factory=list)
    target_agent: str = "UNKNOWN"
    target_vip: str = "UNKNOWN"
    target_sequence: str = ""
    required_resources: List[Dict[str, Any]] = field(default_factory=list)
    preconditions: List[Dict[str, Any]] = field(default_factory=list)
    postconditions: List[Dict[str, Any]] = field(default_factory=list)
    ordering_constraints: List[Dict[str, Any]] = field(default_factory=list)
    clock_domain: Dict[str, Any] = field(default_factory=dict)
    reset_dependency: Dict[str, Any] = field(default_factory=dict)
    interrupt_dependency: Dict[str, Any] = field(default_factory=dict)
    address_dependency: List[Dict[str, Any]] = field(default_factory=list)
    shared_resource_dependency: List[Dict[str, Any]] = field(default_factory=list)
    parallel_safe: str = PARALLEL_SAFETY_UNKNOWN
    serialization_required: bool = False
    evidence: List[str] = field(default_factory=list)
    # Not one of SYS-8's own 20 fields. `parallel_safe` is a three-valued
    # verdict about a whole contract SET, and a verdict whose basis is not
    # recorded beside it cannot be checked -- particularly the UNKNOWN case,
    # where the reason ("there was no second subsystem") is the entire content.
    parallel_safety_reason: str = ""


def contract_id(contract: Mapping[str, Any]) -> str:
    """Stable id for one contract: subsystem, file, command. Used to name a
    contract in a conflict record without embedding the whole contract."""
    return (f"{contract['subsystem_id']}::"
            f"{Path(contract['source_command_file']).name}::"
            f"{contract['command_name']}")


# --- declared overlays -------------------------------------------------------

def load_command_inventory_overlay(csv_path) -> Dict[str, Dict[str, str]]:
    """Read the REAL .dv-workflow/command_inventory.csv as a declared overlay
    keyed by its COMMAND column, upper-cased.

    That file is the existing, already-populated answer to "who handles this
    command and which VIP sequence does it map to" -- CMD-002's
    `HANDLER=CPUWRITE/HOSTWRITE BFM tasks + SMEMMODEL.FILLMEM`, for instance.
    Re-deriving those from scratch when a project has already recorded them
    would be a second, competing answer to a question the repo has answered
    once. It is read, never written: this module has no writer for it.

    Returns {} for an absent or unreadable file -- an absent overlay is an
    honest "nothing was declared", never a reason to fail.
    """
    path = Path(csv_path)
    if not path.is_file():
        return {}
    overlay: Dict[str, Dict[str, str]] = {}
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                key = (row.get("COMMAND") or "").strip().upper()
                if key:
                    overlay[key] = {k: (v or "").strip() for k, v in row.items() if k}
    except (OSError, csv.Error):
        return {}
    return overlay


# --- per-command derivation --------------------------------------------------

def _argument_profile(statements: Sequence[rpa.CommandStatement]) -> List[Dict[str, Any]]:
    """Positional argument profile across every invocation of one command.

    `role` is derived from the statement kind, not from the value: position 0
    of a register access is the ADDRESS and the last position of a READ is the
    DESTINATION variable, because that is what the macro shape means. Anything
    else is OTHER rather than a guess."""
    width = max((len(s.arguments) for s in statements), default=0)
    profile: List[Dict[str, Any]] = []
    for pos in range(width):
        values: List[str] = []
        for stmt in statements:
            if pos < len(stmt.arguments):
                value = stmt.arguments[pos].strip()
                if value and value not in values:
                    values.append(value)
        kind = statements[0].kind
        if kind in (rpa.K_REGISTER_WRITE, rpa.K_REGISTER_READ) and pos == 0:
            role = "ADDRESS"
        elif kind == rpa.K_REGISTER_WRITE and pos == 1:
            role = "VALUE"
        elif kind == rpa.K_REGISTER_READ and pos == width - 1:
            role = "DESTINATION"
        else:
            role = "OTHER"
        profile.append({
            "position": pos,
            "role": role,
            "distinct_value_count": len(values),
            "distinct_values": sorted(values)[:MAX_DISTINCT_ARG_VALUES],
            "truncated": len(values) > MAX_DISTINCT_ARG_VALUES,
        })
    return profile


def _required_resources(statements: Sequence[rpa.CommandStatement]) -> List[Dict[str, Any]]:
    """Resource ids this command needs, with the access mode and a citation.

    Every entry is derived from a statement, never from the command's name:
    the register block comes from the address literal's own base, the BFM from
    the macro prefix's HOST/DUT convention (the same `_classify_context()` the
    write-symmetry layer uses), the model from the invoked `INST.task`, and a
    hierarchy root from an actual dotted reference in the statement text."""
    resources: Dict[str, Dict[str, Any]] = {}

    def touch(kind: str, name: str, stmt: rpa.CommandStatement, basis: str) -> None:
        rid = f"{kind}:{name}"
        entry = resources.setdefault(rid, {
            "resource_id": rid, "resource_kind": kind, "name": name,
            "access": "READ", "basis": basis, "evidence": []})
        if stmt.kind in _WRITING_KINDS:
            entry["access"] = "WRITE"
        if len(entry["evidence"]) < 4:
            entry["evidence"].append(f"{stmt.file}:{stmt.line}")

    for stmt in statements:
        if stmt.base:
            touch(R_REGISTER_BLOCK, stmt.base, stmt,
                  "address literal base, split at the file's own underscore boundary")
        if stmt.context in ("HOST", "DUT"):
            touch(R_BFM, f"{stmt.context}_SIDE", stmt,
                  "macro prefix HOST/CPU/DEV naming convention")
        if stmt.kind == rpa.K_MODEL_TASK_CALL and "." in stmt.name:
            instance = stmt.name.split(".")[0].lstrip("`")
            kind = (R_MEMORY_MODEL
                    if rpa._matched_tokens(instance, rpa.MEMORY_MODEL_NAME_TOKENS)
                    else R_MODEL)
            touch(kind, instance, stmt, "invoked `<INSTANCE>.<task> call")
        for root in stmt.hierarchy_roots:
            if stmt.kind in (rpa.K_FORCE, rpa.K_RELEASE, rpa.K_BACKDOOR_ASSIGN,
                             rpa.K_WAIT_CONDITION, rpa.K_EVENT_WAIT):
                touch(R_HIERARCHY, root.lstrip("`"), stmt,
                      "dotted hierarchical reference in the statement")
    return sorted(resources.values(), key=lambda r: r["resource_id"])


def _pre_and_post_conditions(statements: Sequence[rpa.CommandStatement],
                             all_statements: Sequence[rpa.CommandStatement],
                             ) -> tuple:
    """Preconditions/postconditions derived from the command's real position in
    the statement stream, not from a naming convention.

    A precondition is something that HOLDS BEFORE EVERY invocation -- an
    initialization call preceding the first one, or a wait immediately before
    one. A postcondition is something observed after an invocation. Both are
    citations to real lines, so the claim is checkable; neither asserts
    causation, only order, which is all a file's own text can support."""
    index = {id(s): i for i, s in enumerate(all_statements)}
    positions = sorted(index[id(s)] for s in statements)
    if not positions:
        return [], []
    pre: List[Dict[str, Any]] = []
    post: List[Dict[str, Any]] = []

    first = positions[0]
    for prior in all_statements[:first]:
        if prior.category == rpa.C_INITIALIZATION:
            pre.append({"kind": "PRECEDING_INITIALIZATION", "detail": prior.name,
                        "evidence": f"{prior.file}:{prior.line}"})
    seen_wait_before: set = set()
    seen_wait_after: set = set()
    for pos in positions:
        prev = all_statements[pos - 1] if pos > 0 else None
        if prev is not None and prev.kind in (rpa.K_WAIT_CONDITION, rpa.K_EVENT_WAIT):
            key = (prev.line, prev.text)
            if key not in seen_wait_before:
                seen_wait_before.add(key)
                pre.append({"kind": "IMMEDIATELY_PRECEDING_WAIT", "detail": prev.text,
                            "evidence": f"{prev.file}:{prev.line}"})
        nxt = all_statements[pos + 1] if pos + 1 < len(all_statements) else None
        if nxt is not None and nxt.kind in (rpa.K_WAIT_CONDITION, rpa.K_EVENT_WAIT):
            key = (nxt.line, nxt.text)
            if key not in seen_wait_after:
                seen_wait_after.add(key)
                post.append({"kind": "IMMEDIATELY_FOLLOWING_WAIT", "detail": nxt.text,
                             "evidence": f"{nxt.file}:{nxt.line}"})
        if nxt is not None and nxt.kind == rpa.K_TERMINATION:
            post.append({"kind": "FILE_TERMINATES_AFTER", "detail": nxt.text,
                         "evidence": f"{nxt.file}:{nxt.line}"})
    return pre, post


def _interrupt_dependency(statements: Sequence[rpa.CommandStatement],
                          all_statements: Sequence[rpa.CommandStatement],
                          ) -> Dict[str, Any]:
    """Whether this command participates in an interrupt handshake, via the
    SYS-7 wait classifier (one interrupt-wait definition in this codebase, not
    two). The matched signal-name token is carried through as the evidence,
    because a name match is the whole basis and the reader must be able to
    judge it."""
    index = {id(s): i for i, s in enumerate(all_statements)}
    positions = sorted(index[id(s)] for s in statements)
    waits: List[Dict[str, Any]] = []
    for pos in positions:
        for neighbour in all_statements[pos + 1:pos + 4]:
            if neighbour.kind in (rpa.K_WAIT_CONDITION, rpa.K_EVENT_WAIT):
                classified = rpa.classify_wait(neighbour)
                if classified["wait_class"] == "INTERRUPT_EVENT_WAIT":
                    if classified not in waits:
                        waits.append(classified)
                break
    return {
        "depends_on_interrupt": bool(waits),
        "basis": "SIGNAL_NAME_TOKEN_MATCH_ON_A_FOLLOWING_WAIT" if waits
                 else "NO_INTERRUPT_CLASSIFIED_WAIT_WITHIN_3_STATEMENTS",
        "waits": waits[:4],
    }


def _reset_dependency(statements: Sequence[rpa.CommandStatement]) -> Dict[str, Any]:
    hits = []
    for stmt in statements:
        tokens = rpa._matched_tokens(stmt.text + " " + stmt.comment, rpa.RESET_NAME_TOKENS)
        if tokens:
            hits.append({"line": stmt.line, "matched_tokens": tokens,
                         "detail": stmt.comment or stmt.text,
                         "evidence": f"{stmt.file}:{stmt.line}"})
    return {
        "touches_reset": bool(hits),
        "basis": "RESET_NAME_TOKEN_IN_STATEMENT_OR_ITS_TRAILING_COMMENT" if hits
                 else "NO_RESET_NAME_TOKEN",
        "statements": hits[:4],
    }


def _address_dependency(statements: Sequence[rpa.CommandStatement]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for stmt in statements:
        if not stmt.address:
            continue
        entry = seen.setdefault(stmt.address, {
            "address": stmt.address, "base": stmt.base, "offset": stmt.offset,
            "access": "READ", "evidence": []})
        if stmt.kind == rpa.K_REGISTER_WRITE:
            entry["access"] = "WRITE"
        if len(entry["evidence"]) < 3:
            entry["evidence"].append(f"{stmt.file}:{stmt.line}")
    return sorted(seen.values(), key=lambda a: a["address"])


def _address_int(literal: str) -> Optional[int]:
    m = re.match(r"^[0-9]*'[hH]([0-9A-Fa-f_]+)$", (literal or "").replace(" ", ""))
    if m:
        return int(m.group(1).replace("_", ""), 16)
    try:
        return int(literal, 0)
    except (TypeError, ValueError):
        return None


def _clock_domain(address_dependency: Sequence[Mapping[str, Any]],
                  address_map: Optional[Sequence[Mapping[str, Any]]],
                  region_clock_map: Optional[Mapping[str, str]],
                  ) -> Dict[str, Any]:
    """Resolve this command's clock domain by locating its addresses in the
    project's REAL address map (env.manifest.json's dut_facts.address_map,
    itself loaded from the project's soc_arch_map input contract) and then
    through a declared region -> clock mapping.

    Two steps, and each can honestly fail on its own. A soc_arch_map's
    address_map entries carry no clock reference of their own, so the second
    step needs a declared mapping; without one this reports UNRESOLVED and
    NAMES the regions it did locate, which is strictly more useful than a
    fabricated domain and is what SYS-29's cross-subsystem clock-domain
    comparison will need as its input."""
    if not address_dependency:
        return {"status": "NOT_APPLICABLE", "clock": "",
                "reason": "this command touches no address literal",
                "address_regions": []}
    if not address_map:
        return {"status": "UNRESOLVED", "clock": "",
                "reason": ("no address map supplied -- see env.manifest.json's "
                           "dut_facts.address_map (input contract: "
                           "dv_harness/schemas/soc_arch_map.schema.json)"),
                "address_regions": []}
    regions: List[str] = []
    unmapped: List[str] = []
    for entry in address_dependency:
        value = _address_int(entry["address"])
        if value is None:
            unmapped.append(entry["address"])
            continue
        hit = None
        for region in address_map:
            base = _address_int(str(region.get("base_address")))
            size = region.get("size_bytes")
            if base is None or not isinstance(size, int):
                continue
            if base <= value < base + size:
                hit = str(region.get("name"))
                break
        if hit is None:
            unmapped.append(entry["address"])
        elif hit not in regions:
            regions.append(hit)
    clocks = sorted({region_clock_map[r] for r in regions
                     if region_clock_map and r in region_clock_map})
    if not regions:
        return {"status": "UNRESOLVED", "clock": "",
                "reason": "no supplied address-map region contains this command's addresses",
                "address_regions": [], "unmapped_addresses": sorted(set(unmapped))[:8]}
    if not clocks:
        return {"status": "UNRESOLVED", "clock": "",
                "reason": ("addresses resolved to address-map region(s), but no declared "
                           "region -> clock mapping covers them; a soc_arch_map address_map "
                           "entry carries no clock of its own"),
                "address_regions": sorted(regions),
                "unmapped_addresses": sorted(set(unmapped))[:8]}
    return {"status": "RESOLVED" if len(clocks) == 1 else "MULTIPLE",
            "clock": clocks[0] if len(clocks) == 1 else "",
            "clocks": clocks,
            "reason": "" if len(clocks) == 1 else
                      "this command's addresses span more than one clock domain",
            "address_regions": sorted(regions),
            "unmapped_addresses": sorted(set(unmapped))[:8]}


def _ordering_constraints_for(command_name: str, edges: Sequence[Mapping[str, Any]],
                              ) -> List[Dict[str, Any]]:
    """The subset of the file's SYS-7 ordering edges that name this command on
    either side. The edges themselves are computed once per file by
    `reference_pattern_audit.build_ordering_constraints()`; this is a view of
    them, never a second derivation."""
    out: List[Dict[str, Any]] = []
    for edge in edges:
        if edge.get("from_command") == command_name:
            out.append({"direction": "PRECEDES", "relation": edge["relation"],
                        "other_command": edge["to_command"], "detail": edge["detail"],
                        "evidence": edge["evidence"]})
        elif edge.get("to_command") == command_name:
            out.append({"direction": "FOLLOWS", "relation": edge["relation"],
                        "other_command": edge["from_command"], "detail": edge["detail"],
                        "evidence": edge["evidence"]})
    # Deduplicate: a file with 1300 accesses produces many identical
    # (direction, relation, other_command) edges, and 900 copies of one fact
    # is not more evidence than 1 copy plus a count.
    collapsed: Dict[tuple, Dict[str, Any]] = {}
    for item in out:
        key = (item["direction"], item["relation"], item["other_command"])
        entry = collapsed.setdefault(key, dict(item, occurrences=0))
        entry["occurrences"] += 1
    return sorted(collapsed.values(),
                  key=lambda i: (i["relation"], i["direction"], i["other_command"]))


def build_subsystem_contracts(subsystem_id: str,
                              command_files: Sequence[Any],
                              *,
                              address_map: Optional[Sequence[Mapping[str, Any]]] = None,
                              region_clock_map: Optional[Mapping[str, str]] = None,
                              inventory_overlay: Optional[Mapping[str, Mapping[str, str]]] = None,
                              ) -> List[Dict[str, Any]]:
    """One subsystem's contracts, from its real command.txt file(s).

    `parallel_safe` / `serialization_required` are deliberately left at their
    UNKNOWN/False defaults here and are decided by
    `resolve_cross_subsystem_concurrency()` over the WHOLE contract set --
    a single subsystem's own file cannot answer whether its commands may run
    beside another subsystem's."""
    contracts: List[Dict[str, Any]] = []
    overlay = inventory_overlay or {}
    for command_file in command_files:
        path = Path(command_file)
        analysis = rpa.analyze_command_file(path)
        statements = rpa.extract_command_statements(path)
        edges = analysis["ordering"]["edges"]

        by_command: Dict[str, List[rpa.CommandStatement]] = {}
        for stmt in statements:
            if stmt.kind in (rpa.K_BLOCK_BEGIN, rpa.K_BLOCK_END, rpa.K_PROCESS,
                             rpa.K_DECLARATION, rpa.K_DIRECTIVE, rpa.K_UNCLASSIFIED):
                continue
            by_command.setdefault(stmt.name or stmt.kind, []).append(stmt)

        for name, stmts in sorted(by_command.items()):
            declared = overlay.get(name.lstrip("`").upper(), {})
            resources = _required_resources(stmts)
            pre, post = _pre_and_post_conditions(stmts, statements)
            addresses = _address_dependency(stmts)
            target_vip = "UNKNOWN"
            target_sequence = declared.get("VIP_SEQUENCE", "")
            target_agent = declared.get("HANDLER", "") or "UNKNOWN"
            if stmts[0].kind == rpa.K_MODEL_TASK_CALL and "." in name:
                target_vip = name.split(".")[0].lstrip("`")
                target_sequence = target_sequence or name.split(".", 1)[1]
                target_agent = target_agent if declared.get("HANDLER") else target_vip
            elif stmts[0].context in ("HOST", "DUT"):
                target_agent = (declared.get("HANDLER")
                                or f"{stmts[0].context}_SIDE_BFM")

            contract = SubsystemCommandContract(
                subsystem_id=subsystem_id,
                source_command_file=str(path),
                command_name=name,
                command_category=stmts[0].category,
                arguments=_argument_profile(stmts),
                target_agent=target_agent,
                target_vip=target_vip,
                target_sequence=target_sequence,
                required_resources=resources,
                preconditions=pre,
                postconditions=post,
                ordering_constraints=_ordering_constraints_for(name, edges),
                clock_domain=_clock_domain(addresses, address_map, region_clock_map),
                reset_dependency=_reset_dependency(stmts),
                interrupt_dependency=_interrupt_dependency(stmts, statements),
                address_dependency=addresses,
                shared_resource_dependency=[],
                parallel_safe=PARALLEL_SAFETY_UNKNOWN,
                serialization_required=False,
                evidence=([f"{s.file}:{s.line}" for s in stmts[:6]]
                          + ([f"... {len(stmts)} invocation(s) total"]
                             if len(stmts) > 6 else [])
                          + ([f"declared overlay: {declared.get('COMMAND_ID')}"]
                             if declared else [])),
            )
            contracts.append(asdict(contract))
    return contracts


# --- cross-subsystem concurrency + conflict detection ------------------------

CONFLICT_TYPES: tuple = (
    "DUPLICATE_ACTIVE_DRIVER",
    "SHARED_RESOURCE_CONTENTION",
    "ADDRESS_WRITE_COLLISION",
)


def resolve_cross_subsystem_concurrency(contracts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fill in `shared_resource_dependency`, `parallel_safe` and
    `serialization_required` across the WHOLE contract set. Mutates and returns
    the contracts (they are plain dicts produced by this module).

    The question `parallel_safe` answers is "may this command run concurrently
    with ANOTHER SUBSYSTEM's commands". Contention inside one subsystem is not
    that question -- a command.txt is sequential by construction, and marking
    every command of a single-subsystem set NOT_PARALLEL_SAFE would make the
    field carry no information at all. A set holding only one subsystem
    therefore reports UNKNOWN, with the reason, rather than a verdict it has no
    second subsystem to support.
    """
    subsystems = {c["subsystem_id"] for c in contracts}
    single = len(subsystems) < 2

    # resource_id -> subsystem_id -> [(contract_id, access)]
    usage: Dict[str, Dict[str, List[tuple]]] = {}
    for contract in contracts:
        cid = contract_id(contract)
        for resource in contract["required_resources"]:
            (usage.setdefault(resource["resource_id"], {})
                  .setdefault(contract["subsystem_id"], [])
                  .append((cid, resource["access"])))

    for contract in contracts:
        cid = contract_id(contract)
        shared: List[Dict[str, Any]] = []
        for resource in contract["required_resources"]:
            others = {s: uses for s, uses in usage[resource["resource_id"]].items()
                      if s != contract["subsystem_id"]}
            if not others:
                continue
            other_writes = any(access == "WRITE"
                               for uses in others.values() for _, access in uses)
            shared.append({
                "resource_id": resource["resource_id"],
                "resource_kind": resource["resource_kind"],
                "this_access": resource["access"],
                "other_subsystems": sorted(others),
                "other_contracts": sorted(c for uses in others.values() for c, _ in uses),
                "contention": ("ACTIVE_DRIVER_CONTENTION"
                               if other_writes and resource["access"] == "WRITE"
                               else "WRITE_VS_READ" if other_writes or resource["access"] == "WRITE"
                               else "READ_ONLY_SHARING"),
                "evidence": resource["evidence"],
            })
        contract["shared_resource_dependency"] = sorted(
            shared, key=lambda s: s["resource_id"])

        forces = [r for r in contract["required_resources"]
                  if r["resource_kind"] == R_HIERARCHY and r["access"] == "WRITE"]
        contended = [s for s in shared if s["contention"] != "READ_ONLY_SHARING"]
        if single:
            contract["parallel_safe"] = PARALLEL_SAFETY_UNKNOWN
            contract["serialization_required"] = False
            contract["parallel_safety_reason"] = (
                "SINGLE_SUBSYSTEM_CONTRACT_SET -- there is no second subsystem in this "
                "set to be concurrent WITH, so cross-subsystem parallel safety is "
                "not decidable from it")
        elif contended:
            contract["parallel_safe"] = NOT_PARALLEL_SAFE
            contract["serialization_required"] = True
            contract["parallel_safety_reason"] = (
                "CROSS_SUBSYSTEM_RESOURCE_CONTENTION on "
                + ", ".join(s["resource_id"] for s in contended[:4]))
        elif forces and any(usage[f["resource_id"]].keys() - {contract["subsystem_id"]}
                            for f in forces):
            contract["parallel_safe"] = NOT_PARALLEL_SAFE
            contract["serialization_required"] = True
            contract["parallel_safety_reason"] = (
                "FORCE_OVERRIDE_ON_A_HIERARCHY_ANOTHER_SUBSYSTEM_ALSO_REFERENCES")
        else:
            contract["parallel_safe"] = PARALLEL_SAFE
            contract["serialization_required"] = False
            contract["parallel_safety_reason"] = (
                "no resource required by this command is required by any other "
                "subsystem's command in this set")
        _ = cid
    return contracts


def detect_contract_conflicts(contracts: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """CROSS-SUBSYSTEM conflicts in a contract set -- reported, never resolved.

    Three types, all requiring two DIFFERENT subsystems (contention inside one
    subsystem's own sequential command.txt is not a conflict):

      DUPLICATE_ACTIVE_DRIVER    two subsystems both WRITE one BFM / model /
                                 forced hierarchy -- the "PCIe and USB both
                                 contain a CPU AXI Master" shape SYS-10/SYS-12
                                 exist for. Two active drivers on one physical
                                 interface is the case SYS-12 says must stop
                                 automatic integration.
      SHARED_RESOURCE_CONTENTION two subsystems use one resource with at least
                                 one writer, where it is not an active-driver
                                 duplicate (e.g. a shared register block).
      ADDRESS_WRITE_COLLISION    two subsystems WRITE the same address literal.

    This is SYS-8's own output feeding SYS-19..SYS-25; deciding what to DO
    about a conflict is SYS-11..SYS-13, and implementing a shared agent is
    SYS-40 and needs a separate explicit human approval.
    """
    by_resource: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    by_address: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    kinds: Dict[str, str] = {}
    for contract in contracts:
        cid = contract_id(contract)
        for resource in contract["required_resources"]:
            kinds[resource["resource_id"]] = resource["resource_kind"]
            (by_resource.setdefault(resource["resource_id"], {})
                        .setdefault(contract["subsystem_id"], [])
                        .append({"contract": cid, "access": resource["access"],
                                 "evidence": resource["evidence"]}))
        for entry in contract["address_dependency"]:
            (by_address.setdefault(entry["address"], {})
                       .setdefault(contract["subsystem_id"], [])
                       .append({"contract": cid, "access": entry["access"],
                                "evidence": entry["evidence"]}))

    conflicts: List[Dict[str, Any]] = []
    for resource_id, per_subsystem in sorted(by_resource.items()):
        if len(per_subsystem) < 2:
            continue
        writers = sorted(s for s, uses in per_subsystem.items()
                         if any(u["access"] == "WRITE" for u in uses))
        if not writers:
            continue
        active_duplicate = (len(writers) >= 2
                            and kinds[resource_id] in (R_BFM, R_MODEL, R_MEMORY_MODEL,
                                                       R_HIERARCHY))
        conflicts.append({
            "conflict_type": ("DUPLICATE_ACTIVE_DRIVER" if active_duplicate
                              else "SHARED_RESOURCE_CONTENTION"),
            "resource_id": resource_id,
            "resource_kind": kinds[resource_id],
            "subsystems": sorted(per_subsystem),
            "writing_subsystems": writers,
            "contracts": sorted(u["contract"] for uses in per_subsystem.values()
                                for u in uses),
            "evidence": sorted({e for uses in per_subsystem.values()
                                for u in uses for e in u["evidence"]})[:8],
            "resolution": ("STOP_AUTOMATIC_INTEGRATION_UNTIL_OWNERSHIP_RESOLVED"
                           if active_duplicate else
                           "REQUIRES_SYSTEM_LEVEL_ARBITRATION_DECISION"),
            "detail": (f"{len(writers)} subsystem(s) actively drive {resource_id}"
                       if active_duplicate else
                       f"{len(per_subsystem)} subsystems share {resource_id}, "
                       f"{len(writers)} of them writing"),
        })

    for address, per_subsystem in sorted(by_address.items()):
        writers = sorted(s for s, uses in per_subsystem.items()
                         if any(u["access"] == "WRITE" for u in uses))
        if len(per_subsystem) < 2 or len(writers) < 2:
            continue
        conflicts.append({
            "conflict_type": "ADDRESS_WRITE_COLLISION",
            "address": address,
            "subsystems": sorted(per_subsystem),
            "writing_subsystems": writers,
            "contracts": sorted(u["contract"] for uses in per_subsystem.values()
                                for u in uses),
            "evidence": sorted({e for uses in per_subsystem.values()
                                for u in uses for e in u["evidence"]})[:8],
            "resolution": "REQUIRES_SYSTEM_LEVEL_ARBITRATION_DECISION",
            "detail": f"{len(writers)} subsystems write {address}",
        })

    conflicts.sort(key=lambda c: (c["conflict_type"],
                                  c.get("resource_id") or c.get("address") or ""))
    return conflicts


def build_contract_set(per_subsystem_command_files: Mapping[str, Sequence[Any]],
                       *,
                       address_maps: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
                       region_clock_maps: Optional[Mapping[str, Mapping[str, str]]] = None,
                       inventory_overlay_path=None,
                       ) -> Dict[str, Any]:
    """The full SYS-8 deliverable for a selected subsystem set: every
    subsystem's contracts, cross-subsystem concurrency resolved, and the
    conflicts reported. Read-only over every command.txt it touches."""
    overlay = load_command_inventory_overlay(inventory_overlay_path) if inventory_overlay_path else {}
    contracts: List[Dict[str, Any]] = []
    for subsystem_id, files in sorted(per_subsystem_command_files.items()):
        contracts.extend(build_subsystem_contracts(
            subsystem_id, files,
            address_map=(address_maps or {}).get(subsystem_id),
            region_clock_map=(region_clock_maps or {}).get(subsystem_id),
            inventory_overlay=overlay))
    resolve_cross_subsystem_concurrency(contracts)
    conflicts = detect_contract_conflicts(contracts)
    return {
        "schema_version": SCHEMA_VERSION,
        "subsystems": sorted(per_subsystem_command_files),
        "contracts": contracts,
        "conflicts": conflicts,
        "summary": {
            "subsystem_count": len(per_subsystem_command_files),
            "contract_count": len(contracts),
            "conflict_count": len(conflicts),
            "not_parallel_safe": sum(1 for c in contracts
                                     if c["parallel_safe"] == NOT_PARALLEL_SAFE),
            "parallel_safety_undecidable": sum(
                1 for c in contracts if c["parallel_safe"] == PARALLEL_SAFETY_UNKNOWN),
            "duplicate_active_drivers": sum(
                1 for c in conflicts if c["conflict_type"] == "DUPLICATE_ACTIVE_DRIVER"),
        },
        "command_txt_modified": False,
        "phase_boundary": (
            "SYSTEM-LEVEL IMPLEMENTATION NOT STARTED -- SYS-8 contracts and SYS-7 "
            "analysis only. No System command.txt, System Virtual Sequencer or command "
            "router is generated; that is SYS-40 and requires a separate explicit "
            "human approval."),
    }


# --- schema validation -------------------------------------------------------

def validate_contract_set(document: Mapping[str, Any]) -> None:
    """Validate a `build_contract_set()` document against the real JSON schema.
    Raises jsonschema.ValidationError on a violation."""
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


def format_contract_report(document: Mapping[str, Any]) -> str:
    """Human-readable SYS-8 report: the contracts, then the conflicts."""
    summary = document["summary"]
    out = ["# SUBSYSTEM COMMAND CONTRACTS (SYS-7 / SYS-8)", "",
           f"- subsystems: {', '.join(document['subsystems']) or '(none)'}",
           f"- contracts: {summary['contract_count']}",
           f"- cross-subsystem conflicts: {summary['conflict_count']} "
           f"({summary['duplicate_active_drivers']} duplicate active driver(s))",
           f"- NOT_PARALLEL_SAFE: {summary['not_parallel_safe']}; "
           f"parallel safety undecidable: {summary['parallel_safety_undecidable']}",
           "", "## CONTRACTS", "",
           "| SUBSYSTEM | COMMAND | CATEGORY | TARGET AGENT | RESOURCES | "
           "PARALLEL SAFE | SERIALIZE |",
           "|---|---|---|---|---|---|---|"]
    for contract in document["contracts"]:
        out.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            contract["subsystem_id"], contract["command_name"],
            contract["command_category"], contract["target_agent"] or "-",
            ", ".join(r["resource_id"] for r in contract["required_resources"][:4]) or "-",
            contract["parallel_safe"],
            "yes" if contract["serialization_required"] else "no"))
    if not document["contracts"]:
        out.append("| _(no contracts derived)_ | - | - | - | - | - | - |")

    out += ["", "## CROSS-SUBSYSTEM CONFLICTS", ""]
    if not document["conflicts"]:
        out.append("_(none detected in this contract set)_")
    for conflict in document["conflicts"]:
        out.append(f"- **{conflict['conflict_type']}** "
                   f"{conflict.get('resource_id') or conflict.get('address')}: "
                   f"{conflict['detail']} -> {conflict['resolution']}")
        out.append(f"  - subsystems: {conflict['subsystems']}; "
                   f"evidence: {conflict['evidence'][:3]}")
    out += ["", "## PHASE BOUNDARY", "", document["phase_boundary"]]
    return "\n".join(out)
