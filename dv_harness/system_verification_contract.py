"""dv_harness/system_verification_contract.py -- ONE authoritative
`SystemVerificationContract` record, ASSEMBLED, never re-derived.

THE GAP THIS CLOSES
-------------------
`subsystem_contract.py` already assembles ONE subsystem's verification truth --
spec/DUT/TB identity, protocols/interfaces, requirements, vPlan/test/coverage
correspondence, regression, signoff, evidence, waivers -- into one record. A
SYSTEM composed of several subsystems needs the SIBLING rollup: N subsystem
contracts, plus the real cross-subsystem facts `system_topology_analysis.py`
(address/interrupt/clock-reset reconciliation, scenario planning) and
`system_resource_inventory.py` (SYS-9..14 shared-resource/active-driver-
conflict analysis) and `system_command_plan.py` (SYS-18..22 command routing/
collision analysis) already compute -- into ONE record. Without it, "is this
system verified" required a human to open four different documents and
manually cross-reference them, and two audits of the same system could
describe its verification contract differently even from identical facts.

WHAT THIS MODULE IS NOT
-----------------------
  * It is not a NEW evidence source and it performs NO cross-subsystem
    analysis of its own. `system_topology_analysis.py` already decides
    address/interrupt/clock-reset conflicts; `system_resource_inventory.py`
    already decides ACTIVE_DRIVER_CONFLICT and shared-resource relationships;
    `system_command_plan.py` already decides command routing/collisions.
    This module never re-derives any of that -- it reads what those readers
    already produced and reports it verbatim, or `NOT_AVAILABLE` with the
    real reason when a caller did not supply it.
  * It DECIDES, ARBITRATES and WRITES NO GOVERNANCE STATE. No stage runs, no
    gate script is invoked, no build/regression/LSF submission starts, no
    approval is minted, and no ownership conflict is resolved -- a recorded
    `preferred_model`/`blocking_decisions` finding is carried through as text
    for a human to arbitrate, exactly as `system_resource_inventory.py`'s own
    `_blocked_detail()` already states. There is deliberately no stage gate: a
    gate that passed because a contract record existed, or failed because one
    did not, would be worse than none.
  * `assemble_system_verification_contract()` is READ-ONLY -- it constructs no
    store and mints no `.dv-harness/` tree. Persisting the assembled record to
    `.dv-harness/system_verification_contract.json` is a SEPARATE, explicit
    act (`write_system_verification_contract()` / the `snapshot` verb) --
    assembling and reading a system's own truth must never itself become new
    truth about that system.

STRICT FILE-SAFETY SCOPE: NO CROSS-IMPORTS
-------------------------------------------
This module never imports `subsystem_contract.py`, `system_topology_
analysis.py`, `system_resource_inventory.py`, or `system_command_plan.py` --
it accepts their real output SHAPES as generic/duck-typed parameters instead
(a list of subsystem-contract-shaped dicts; a topology-shaped dict; a
resource-registry-shaped dict matching `system_resource_inventory.
real_cross_subsystem_findings()`'s own `CROSSCHECK_AVAILABLE`/
`CROSSCHECK_UNAVAILABLE` vocabulary, restated here as plain string literals
rather than imported names; a command-registry-shaped dict matching
`system_command_plan.build_system_command_plan()`'s own `summary` block).
This is deliberate, not an oversight: it means this module is independently
testable against synthetic fixtures and does not assume any of those four
modules ran in this same process, or ran at all -- a caller who has only
SOME of the four inputs on hand still gets an honest, partial rollup rather
than an import-time failure.

WHAT EACH SECTION REUSES, AND WHY NOT SOMETHING ELSE
-----------------------------------------------------
  * `subsystem_contracts` -- each entry is read exactly the way
    `subsystem_contract.py`'s own `assemble_subsystem_contract()` shapes a
    record: `entry["completeness"]` (COMPLETE/PARTIAL/NOT_AVAILABLE, that
    module's own vocabulary), `entry["subsystem"]["resolved_name"]`/
    `["requested"]`, `entry["unknowns"]` (a list -- its length is carried
    through, never its content re-interpreted), and the real
    `spec_version`/`dut_sha`/`tb_sha`/`signoff.stage.stage_status` field
    statuses. A caller who never ran subsystem_contract.py at all may still
    pass a plain list of dicts shaped like its own output; this module never
    calls back into that module to validate the shape, it reads what it can
    and reports `UNKNOWN_SHAPE` for what it cannot.
  * `system_topology` -- `system_topology_analysis.build_system_topology_
    analysis()`'s own `summary` block verbatim (address_regions/overlaps/
    conflicts, shared_memory_windows, interrupt_lines/shared_interrupt_lines,
    clock_reset_conflicts, cdc_boundaries, duplicate_clock_reset_agents,
    scenarios_planned, topology_clean) plus `selected_subsystems`.
  * `system_resource_registry` -- `system_resource_inventory.
    real_cross_subsystem_findings()`'s own flattened shape: `driver_conflicts`,
    `automatic_integration_allowed`, `stopped_resource_ids`/`held_
    resource_ids`, `blocking_decisions`, `shared_resource_ids`,
    `preferred_model` (SYS-12's own text for a human, carried through
    unchanged -- this module never picks a winner). A `CROSSCHECK_UNAVAILABLE`
    status is reported `NOT_AVAILABLE` citing that reader's own real reason
    (e.g. `FEWER_THAN_TWO_SUBSYSTEMS_TO_COMPARE`) -- never silently read as
    "clear".
  * `system_command_registry` -- `system_command_plan.
    build_system_command_plan()`'s own `summary` block verbatim
    (system_commands, routes_reusing_subsystem_semantics, ir_entries,
    collisions/blocking_collisions, subsystem_modes_preserved,
    command_plan_clean).

`unknowns` IS THE HONESTY SURFACE. Every one of the four tracked aspects this
module could not assemble from real caller-supplied evidence lands there as
`{"field", "reason"}` -- never silently dropped from the record and never
defaulted to an empty-but-present value. An individual subsystem contract
that itself reports `NOT_AVAILABLE` or an unrecognizable shape also counts,
named by its own subsystem name, in `subsystem_contracts.completeness_rollup`
and folds into that ONE tracked aspect's own reason -- it never inflates the
tracked-aspect count past the fixed four this module always scores against.
A subsystem contract that is merely `PARTIAL` (a real, already-visible fact
about that subsystem, not an absence this module failed to assemble) is
never treated as an "unknown" here -- only `NOT_AVAILABLE`/unrecognizable
shapes are, the same distinction `subsystem_contract.py` itself draws between
a field it could not assemble and one whose real value happens to be
incomplete.

`completeness` is `COMPLETE` (zero unknowns), `NOT_AVAILABLE` (every one of
the four tracked aspects unknown -- a bare/uninitialized rollup), or
`PARTIAL` (anything between), scored against the fixed `TRACKED_ASPECTS`
denominator so the count itself cannot silently grow or shrink.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"

STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_PRESENT = "PRESENT"

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
NOT_AVAILABLE_OVERALL = "NOT_AVAILABLE"
COMPLETENESS_CLASSES: Tuple[str, ...] = (COMPLETE, PARTIAL, NOT_AVAILABLE_OVERALL)

#: A subsystem-contract entry's own completeness value, plus this module's
#: own honest label for an entry it could not interpret at all.
SUBSYSTEM_UNKNOWN_SHAPE = "UNKNOWN_SHAPE"
SUBSYSTEM_COMPLETENESS_VALUES: Tuple[str, ...] = (COMPLETE, PARTIAL, NOT_AVAILABLE_OVERALL)

#: `system_resource_inventory.real_cross_subsystem_findings()`'s own real
#: status vocabulary -- restated as plain string literals (never imported,
#: per this module's strict no-cross-import scope).
RESOURCE_REGISTRY_STATUS_AVAILABLE = "CROSSCHECK_AVAILABLE"
RESOURCE_REGISTRY_STATUS_UNAVAILABLE = "CROSSCHECK_UNAVAILABLE"

#: Every aspect this contract tracks, in assembly order. A fixed denominator
#: for `completeness` scoring -- never a list a caller can silently widen or
#: narrow by adding/removing an `unknowns` entry elsewhere.
TRACKED_ASPECTS: Tuple[str, ...] = (
    "subsystem_contracts", "system_topology", "system_resource_registry",
    "system_command_registry",
)


class SystemVerificationContractError(Exception):
    """Base for every refusal in this module."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unavailable(reason: str, **detail: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"status": STATUS_NOT_AVAILABLE, "reason": reason}
    out.update(detail)
    return out


# ---------------------------------------------------------------------------
# subsystem_contracts -- N subsystem_contract.py-shaped records, duck-typed
# ---------------------------------------------------------------------------

def _subsystem_entry_summary(entry: Any, index: int) -> Dict[str, Any]:
    """(name, completeness, reason, ...) for ONE caller-supplied entry.

    Never raises on a malformed entry -- an entry this module cannot
    interpret is reported `UNKNOWN_SHAPE` with a real, specific reason,
    exactly the honesty this whole module exists to guarantee for its own
    input, not only for what it reads downstream."""
    if not isinstance(entry, Mapping):
        return {
            "index": index, "subsystem_name": f"subsystem_contracts[{index}]",
            "completeness": SUBSYSTEM_UNKNOWN_SHAPE,
            "reason": (f"subsystem_contracts[{index}] is not a mapping "
                      f"(got {type(entry).__name__})"),
            "unknown_count": None, "spec_version_status": None,
            "dut_sha_status": None, "tb_sha_status": None,
            "signoff_stage_status": None,
        }

    subsystem_block = entry.get("subsystem")
    name = None
    if isinstance(subsystem_block, Mapping):
        name = subsystem_block.get("resolved_name") or subsystem_block.get("requested")
    name = name or entry.get("subsystem_name") or f"subsystem_contracts[{index}]"

    completeness = entry.get("completeness")
    reason: Optional[str] = None
    if completeness not in SUBSYSTEM_COMPLETENESS_VALUES:
        reason = (f"subsystem_contracts[{index}] ({name}) carries no recognizable "
                  f"'completeness' field (subsystem_contract.py's own "
                  f"COMPLETE/PARTIAL/NOT_AVAILABLE vocabulary) -- got {completeness!r}")
        completeness = SUBSYSTEM_UNKNOWN_SHAPE
    elif completeness == NOT_AVAILABLE_OVERALL:
        reason = f"subsystem_contracts[{index}] ({name}) itself reports NOT_AVAILABLE"

    unknowns = entry.get("unknowns")
    unknown_count = len(unknowns) if isinstance(unknowns, list) else None

    def _field_status(block_name: str) -> Optional[str]:
        block = entry.get(block_name)
        return block.get("status") if isinstance(block, Mapping) else None

    stage_status = None
    signoff = entry.get("signoff")
    if isinstance(signoff, Mapping):
        stage = signoff.get("stage")
        if isinstance(stage, Mapping):
            stage_status = stage.get("stage_status")

    return {
        "index": index, "subsystem_name": name, "completeness": completeness,
        "reason": reason, "unknown_count": unknown_count,
        "spec_version_status": _field_status("spec_version"),
        "dut_sha_status": _field_status("dut_sha"),
        "tb_sha_status": _field_status("tb_sha"),
        "signoff_stage_status": stage_status,
    }


def _subsystem_contracts_section(subsystem_contracts: Optional[Sequence[Any]]
                                 ) -> Tuple[Dict[str, Any], Optional[str]]:
    """(section, unknown_reason_or_None). An empty/absent list is reported
    NOT_AVAILABLE naming exactly what was expected; a non-empty list is
    always PRESENT (this aspect exists), with any NOT_AVAILABLE/UNKNOWN_SHAPE
    entries surfaced by name in the section's own reason -- an aggregate over
    partially-broken subsystem contracts is still a real aggregate, not an
    absent one."""
    if not subsystem_contracts:
        reason = ("no subsystem_contracts supplied -- pass a list of "
                  "subsystem_contract.py-shaped records (one per subsystem)")
        return _unavailable(reason, entries=[], count=0), reason

    entries = [_subsystem_entry_summary(e, i) for i, e in enumerate(subsystem_contracts)]
    rollup: Dict[str, int] = {v: 0 for v in (*SUBSYSTEM_COMPLETENESS_VALUES, SUBSYSTEM_UNKNOWN_SHAPE)}
    for e in entries:
        rollup[e["completeness"]] = rollup.get(e["completeness"], 0) + 1

    broken = [e for e in entries
              if e["completeness"] in (NOT_AVAILABLE_OVERALL, SUBSYSTEM_UNKNOWN_SHAPE)]
    section = {
        "status": STATUS_PRESENT, "count": len(entries), "entries": entries,
        "completeness_rollup": rollup,
    }
    reason: Optional[str] = None
    if broken:
        names = ", ".join(str(e["subsystem_name"]) for e in broken)
        reason = (f"{len(broken)} of {len(entries)} subsystem contract(s) are "
                  f"NOT_AVAILABLE/UNKNOWN_SHAPE: {names}")
    return section, reason


# ---------------------------------------------------------------------------
# system_topology -- system_topology_analysis.py's own document, duck-typed
# ---------------------------------------------------------------------------

def _system_topology_section(system_topology: Optional[Any]
                             ) -> Tuple[Dict[str, Any], Optional[str]]:
    if not system_topology:
        reason = ("no system_topology supplied -- pass a "
                  "system_topology_analysis.build_system_topology_analysis()-shaped document")
        return _unavailable(reason), reason
    if not isinstance(system_topology, Mapping):
        reason = f"system_topology is not a mapping (got {type(system_topology).__name__})"
        return _unavailable(reason), reason

    summary = system_topology.get("summary")
    if not isinstance(summary, Mapping):
        reason = ("system_topology carries no 'summary' block "
                  "(system_topology_analysis.py's own rollup)")
        return _unavailable(
            reason, selected_subsystems=system_topology.get("selected_subsystems")), reason

    section = {
        "status": STATUS_PRESENT,
        "selected_subsystems": system_topology.get("selected_subsystems"),
        "address_regions": summary.get("address_regions"),
        "address_overlaps": summary.get("address_overlaps"),
        "address_conflicts": summary.get("address_conflicts"),
        "shared_memory_windows": summary.get("shared_memory_windows"),
        "interrupt_lines": summary.get("interrupt_lines"),
        "shared_interrupt_lines": summary.get("shared_interrupt_lines"),
        "clock_reset_conflicts": summary.get("clock_reset_conflicts"),
        "cdc_boundaries": summary.get("cdc_boundaries"),
        "duplicate_clock_reset_agents": summary.get("duplicate_clock_reset_agents"),
        "scenarios_planned": summary.get("scenarios_planned"),
        "topology_clean": summary.get("topology_clean"),
    }
    return section, None


# ---------------------------------------------------------------------------
# system_resource_registry -- real_cross_subsystem_findings()'s own shape
# ---------------------------------------------------------------------------

def _system_resource_registry_section(system_resource_registry: Optional[Any]
                                      ) -> Tuple[Dict[str, Any], Optional[str]]:
    if not system_resource_registry:
        reason = ("no system_resource_registry supplied -- pass a "
                  "system_resource_inventory.real_cross_subsystem_findings()-shaped record")
        return _unavailable(reason), reason
    if not isinstance(system_resource_registry, Mapping):
        reason = (f"system_resource_registry is not a mapping "
                  f"(got {type(system_resource_registry).__name__})")
        return _unavailable(reason), reason

    status = system_resource_registry.get("status")
    if status == RESOURCE_REGISTRY_STATUS_UNAVAILABLE:
        reason = (system_resource_registry.get("reason")
                  or "system_resource_registry reported CROSSCHECK_UNAVAILABLE with no reason")
        return _unavailable(
            reason, subsystems=system_resource_registry.get("subsystems")), reason
    if status != RESOURCE_REGISTRY_STATUS_AVAILABLE:
        reason = (f"system_resource_registry carries an unrecognized status {status!r} "
                  f"(expected {RESOURCE_REGISTRY_STATUS_AVAILABLE!r}/"
                  f"{RESOURCE_REGISTRY_STATUS_UNAVAILABLE!r})")
        return _unavailable(reason), reason

    section = {
        "status": STATUS_PRESENT,
        "subsystems": system_resource_registry.get("subsystems"),
        "resource_count": system_resource_registry.get("resource_count"),
        "driver_conflicts": system_resource_registry.get("driver_conflicts"),
        "automatic_integration_allowed": system_resource_registry.get(
            "automatic_integration_allowed"),
        "stopped_resource_ids": system_resource_registry.get("stopped_resource_ids"),
        "held_resource_ids": system_resource_registry.get("held_resource_ids"),
        "blocking_decisions": system_resource_registry.get("blocking_decisions"),
        "shared_resource_ids": system_resource_registry.get("shared_resource_ids"),
        "preferred_model": system_resource_registry.get("preferred_model"),
    }
    return section, None


# ---------------------------------------------------------------------------
# system_command_registry -- system_command_plan.py's own document, duck-typed
# ---------------------------------------------------------------------------

def _system_command_registry_section(system_command_registry: Optional[Any]
                                     ) -> Tuple[Dict[str, Any], Optional[str]]:
    if not system_command_registry:
        reason = ("no system_command_registry supplied -- pass a "
                  "system_command_plan.build_system_command_plan()-shaped document")
        return _unavailable(reason), reason
    if not isinstance(system_command_registry, Mapping):
        reason = (f"system_command_registry is not a mapping "
                  f"(got {type(system_command_registry).__name__})")
        return _unavailable(reason), reason

    summary = system_command_registry.get("summary")
    if not isinstance(summary, Mapping):
        reason = ("system_command_registry carries no 'summary' block "
                  "(system_command_plan.py's own rollup)")
        return _unavailable(reason), reason

    section = {
        "status": STATUS_PRESENT,
        "selected_subsystems": summary.get("selected_subsystems"),
        "system_commands": summary.get("system_commands"),
        "routes_reusing_subsystem_semantics": summary.get(
            "routes_reusing_subsystem_semantics"),
        "ir_entries": summary.get("ir_entries"),
        "collisions": summary.get("collisions"),
        "blocking_collisions": summary.get("blocking_collisions"),
        "subsystem_modes_preserved": summary.get("subsystem_modes_preserved"),
        "command_plan_clean": summary.get("command_plan_clean"),
    }
    return section, None


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble_system_verification_contract(
        subsystem_contracts: Optional[Sequence[Any]] = None,
        system_topology: Optional[Any] = None,
        system_resource_registry: Optional[Any] = None,
        system_command_registry: Optional[Any] = None,
        *, system_name: Optional[str] = None) -> Dict[str, Any]:
    """Assemble ONE SystemVerificationContract record over caller-supplied
    facts. Read-only: no store, state file or `.dv-harness/` tree is created
    to answer any field. Every section either carries real content read
    verbatim from a caller-supplied, real-shaped input, or is `NOT_AVAILABLE`
    with a real reason recorded in that section AND in `unknowns` -- never
    silently omitted and never defaulted to a fabricated pass.

    None of `subsystem_contracts`/`system_topology`/`system_resource_
    registry`/`system_command_registry` is imported from anywhere; each is
    accepted purely as the generic/duck-typed shape its real producer
    (`subsystem_contract.py`, `system_topology_analysis.py`,
    `system_resource_inventory.py`, `system_command_plan.py`, respectively)
    already emits, so this module never assumes any of those four ran in
    this same process."""
    unknowns: List[Dict[str, str]] = []

    def _note(field: str, reason: Optional[str]) -> None:
        unknowns.append({"field": field, "reason": reason or f"{field} not available"})

    subsystem_section, subsystem_reason = _subsystem_contracts_section(subsystem_contracts)
    if subsystem_reason:
        _note("subsystem_contracts", subsystem_reason)

    topology_section, topology_reason = _system_topology_section(system_topology)
    if topology_reason:
        _note("system_topology", topology_reason)

    resource_section, resource_reason = _system_resource_registry_section(
        system_resource_registry)
    if resource_reason:
        _note("system_resource_registry", resource_reason)

    command_section, command_reason = _system_command_registry_section(
        system_command_registry)
    if command_reason:
        _note("system_command_registry", command_reason)

    tracked_total = len(TRACKED_ASPECTS)
    unavailable_count = len(unknowns)
    if unavailable_count == 0:
        completeness = COMPLETE
    elif unavailable_count >= tracked_total:
        completeness = NOT_AVAILABLE_OVERALL
    else:
        completeness = PARTIAL

    return {
        "schema_version": SCHEMA_VERSION,
        "assembled_at": _now_iso(),
        "system_name": system_name,
        "subsystem_contracts": subsystem_section,
        "system_topology": topology_section,
        "system_resource_registry": resource_section,
        "system_command_registry": command_section,
        "unknowns": unknowns,
        "tracked_aspect_count": tracked_total,
        "unavailable_aspect_count": unavailable_count,
        "completeness": completeness,
    }


CONTRACT_RELPATH = Path(".dv-harness") / "system_verification_contract.json"


def write_system_verification_contract(root, record: Dict[str, Any]) -> Path:
    """Persist `record` to `<root>/.dv-harness/system_verification_contract.json`.

    Only when called on a real project root: `root` itself must already
    exist. This is a separate, explicit write --
    `assemble_system_verification_contract()` never calls it, so reading a
    system's contract never mutates the project."""
    root = Path(root)
    if not root.is_dir():
        raise SystemVerificationContractError(
            f"not a real project root (does not exist): {root}")
    out_path = root / CONTRACT_RELPATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Rendering + shared front door (execute_verb -> `assemble`/`snapshot`)
# ---------------------------------------------------------------------------

def render_contract_text(record: Dict[str, Any]) -> str:
    sc = record["subsystem_contracts"]
    rollup = sc.get("completeness_rollup") or {}
    header = f"SYSTEM VERIFICATION CONTRACT: {record['completeness']}"
    if record.get("system_name"):
        header += f"  ({record['system_name']})"
    lines = [
        header,
        f"  subsystem_contracts: {sc.get('status')}  count={sc.get('count', 0)}  "
        f"rollup={rollup}",
        f"  system_topology: {record['system_topology'].get('status')}",
        f"  system_resource_registry: {record['system_resource_registry'].get('status')}  "
        f"driver_conflicts={record['system_resource_registry'].get('driver_conflicts')}",
        f"  system_command_registry: {record['system_command_registry'].get('status')}  "
        f"blocking_collisions={record['system_command_registry'].get('blocking_collisions')}",
        "",
    ]
    if record["unknowns"]:
        lines.append(f"UNKNOWNS ({len(record['unknowns'])}):")
        for u in record["unknowns"]:
            lines.append(f"  - {u['field']}: {u['reason']}")
    else:
        lines.append("no unknowns -- every tracked aspect was assembled from real "
                     "caller-supplied evidence")
    if record.get("written_to"):
        lines.append(f"\nwritten to {record['written_to']}")
    return "\n".join(lines)


_EXIT_CODES = {COMPLETE: 0, PARTIAL: 1, NOT_AVAILABLE_OVERALL: 2}


def _load_json_optional(path: Optional[str]) -> Optional[Any]:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise SystemVerificationContractError(f"not a real file: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemVerificationContractError(f"{p} is not valid JSON: {exc}") from exc


def _load_subsystem_contracts(path: Optional[str]) -> List[Any]:
    data = _load_json_optional(path)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping) and isinstance(data.get("subsystem_contracts"), list):
        return data["subsystem_contracts"]
    raise SystemVerificationContractError(
        f"{path} must contain a JSON array or {{'subsystem_contracts': [...]}}, "
        f"got {type(data).__name__}")


def execute_verb(verb: str, *, root,
                  subsystem_contracts_path: Optional[str] = None,
                  topology_path: Optional[str] = None,
                  resource_registry_path: Optional[str] = None,
                  command_registry_path: Optional[str] = None,
                  system_name: Optional[str] = None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.system_verification_
    contract assemble|snapshot`. Returns (text, exit_code): 0 COMPLETE,
    1 PARTIAL, 2 NOT_AVAILABLE (a bare/uninitialized rollup) or a usage
    error. `assemble` reads only; `snapshot` additionally writes
    `.dv-harness/system_verification_contract.json`."""
    if verb not in ("assemble", "snapshot"):
        msg = (f"unknown system-verification-contract verb {verb!r} "
              f"(expected assemble|snapshot)")
        return (json.dumps({"status": "NOT_AVAILABLE", "reason": msg}) if as_json else msg), 2

    subsystem_contracts = _load_subsystem_contracts(subsystem_contracts_path)
    system_topology = _load_json_optional(topology_path)
    system_resource_registry = _load_json_optional(resource_registry_path)
    system_command_registry = _load_json_optional(command_registry_path)

    record = assemble_system_verification_contract(
        subsystem_contracts=subsystem_contracts,
        system_topology=system_topology,
        system_resource_registry=system_resource_registry,
        system_command_registry=system_command_registry,
        system_name=system_name)

    if verb == "snapshot":
        written = write_system_verification_contract(root, record)
        record["written_to"] = str(written)

    code = _EXIT_CODES[record["completeness"]]
    text = json.dumps(record, indent=2) if as_json else render_contract_text(record)
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.system_verification_contract",
        description="Assemble one authoritative SystemVerificationContract record from "
                    "N caller-supplied subsystem_contract.py-shaped records plus a "
                    "system_topology_analysis.py-shaped document, a "
                    "system_resource_inventory.real_cross_subsystem_findings()-shaped "
                    "record and a system_command_plan.py-shaped document. 'assemble' "
                    "reads only; 'snapshot' additionally writes "
                    ".dv-harness/system_verification_contract.json.")
    ap.add_argument("verb", choices=("assemble", "snapshot"))
    ap.add_argument("--root", default=".")
    ap.add_argument("--subsystem-contracts", default=None, dest="subsystem_contracts_path",
                    help="JSON file: a bare array, or {'subsystem_contracts': [...]}, of "
                         "subsystem_contract.py-shaped records.")
    ap.add_argument("--topology", default=None, dest="topology_path",
                    help="JSON file: a system_topology_analysis.py-shaped document.")
    ap.add_argument("--resource-registry", default=None, dest="resource_registry_path",
                    help="JSON file: a system_resource_inventory."
                         "real_cross_subsystem_findings()-shaped record.")
    ap.add_argument("--command-registry", default=None, dest="command_registry_path",
                    help="JSON file: a system_command_plan.py-shaped document.")
    ap.add_argument("--system-name", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        text, code = execute_verb(
            a.verb, root=a.root, subsystem_contracts_path=a.subsystem_contracts_path,
            topology_path=a.topology_path, resource_registry_path=a.resource_registry_path,
            command_registry_path=a.command_registry_path, system_name=a.system_name,
            as_json=a.json)
    except SystemVerificationContractError as exc:
        print(f"{type(exc).__name__}: {exc}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
