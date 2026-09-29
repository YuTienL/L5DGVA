"""dv_harness/system_fw_service_registry.py -- a per-SYSTEM (not per-subsystem)
registry of `branch_fw` service-loop OWNERSHIP across the composed subsystems
of one System-Level environment.

WHY A NEW MODULE, AND WHY IT IS NOT A DUPLICATE OF THE TWO NEAREST MODULES
---------------------------------------------------------------------------
`dv_harness/shared_bus_resource_registry.py` already detects a `branch_fw`-vs-
`branch_a*` race, but strictly INTRA-subsystem: it never looks past one
environment's own generated pattern, and it has no concept of a SYSTEM
composed of several subsystems at all.

`dv_harness/system_resource_inventory.py` (SYS-9..14) is CROSS-SUBSYSTEM /
SoC-level, but it has no concept of `branch_fw` either: its resource-type
taxonomy includes `FIRMWARE_AGENT` (a classified VIP/UVM component -- a
firmware MODEL instance seen in a connectivity matrix or env.manifest.json),
which is a completely different thing from `branch_fw` (a `command.txt`
pattern TASK-COMPOSITION role -- the per-port service loop launched once,
non-blocking, never returns, per `pattern-architecture SKILL.md` section 1).
Nothing in `system_resource_inventory.py` validates a branch LABEL against the
`block`/`branch_a*`/`branch_fw`/`branch_b*` ownership rules, and nothing in
`shared_bus_resource_registry.py` reads a cross-subsystem driver-conflict
verdict.

The gap this module closes sits between the two: for a SYSTEM composed of N
subsystems, WHICH subsystem's `branch_fw` service loop legitimately owns which
declared resource, AND does that ownership collide with a resource
`system_resource_inventory.py`'s real cross-subsystem analysis has ALREADY
flagged as system-level driver-conflicted, held, or shared? Answering that
question for the whole composed SYSTEM -- not one subsystem at a time -- has
no existing home.

REUSE OVER REINVENT (per this task's own instruction)
------------------------------------------------------
This module re-derives NEITHER of the two mechanisms it needs:

  * FW classification/validation of a declared `branch_label` (is it the
    canonical, correctly-tiered `branch_fw`?) is
    `dv_harness/branch_ownership_resolver.py`'s
    `validate_branch_assignment()` / `classify_operation_ownership()`,
    imported and called directly -- this module owns no branch-naming regex,
    no operation-kind taxonomy, and no violation table of its own.
  * Cross-subsystem evidence (system-level ACTIVE_DRIVER_CONFLICT,
    STOP_AUTOMATIC_INTEGRATION / HOLD_PENDING_EVIDENCE, and SAME_PHYSICAL /
    SHARED_LOGICAL relationships) is
    `dv_harness/system_resource_inventory.py`'s
    `real_cross_subsystem_findings()` output, consumed VERBATIM through its
    own status vocabulary (`CROSSCHECK_AVAILABLE`/`CROSSCHECK_UNAVAILABLE`,
    imported by name, never restated as a literal). This module never
    re-runs SYS-9..14's analysis and never decides a driver conflict itself.

EVIDENCE, HONESTLY
-------------------
There is no `command.txt`/pattern-body parser anywhere in this codebase (per
the identical honesty `shared_bus_resource_registry.py` and
`ip_ownership_conflict.py` already state for themselves), so WHICH real
`resource_id`(s) a subsystem's `branch_fw` loop writes is a CALLER-DECLARED
fact (`fw_owned_resource_ids`), never inferred here. A subsystem that declares
none is honestly reported `NOT_APPLICABLE_NO_FW_RESOURCES_DECLARED` for the
cross-subsystem check, never a false `CLEAR`. When no
`cross_subsystem_findings` were supplied, or the supplied findings report
`system_resource_inventory.CROSSCHECK_UNAVAILABLE`, every entry's
cross-subsystem status is the honest `UNKNOWN_CROSS_SUBSYSTEM_ANALYSIS_
UNAVAILABLE` -- never silently treated as clear.

WORST-WINS COMPOSITE VERDICT
------------------------------
This module is a per-SYSTEM rollup/gate: the overall `status` is the single
worst entry status across every declared subsystem, never an average or a
majority vote (`_ENTRY_SEVERITY_ORDER` below is the one place severity order
is defined; `_worst_entry_status()` is the one place it is applied). One
subsystem with an invalid `branch_fw` assignment, or one subsystem whose
`branch_fw`-owned resource is system-level driver-conflicted, fails the whole
registry regardless of how many other subsystems are clean.

SCOPE BOUNDARY -- DETECTION/RECORDING ONLY
---------------------------------------------
This module never edits a pattern file, never renames a branch, never
arbitrates a resource-ownership conflict (that stays
`system_resource_inventory.py`'s SYS-11/SYS-12 territory), never retries
anything, and touches no approval/governance mechanism. It performs no file
I/O and no subprocess call in its analysis path -- every input is a plain
dict/list; `find_system_fw_service_registry_for_root()` is the one thin
convenience wrapper that calls the real `system_resource_inventory` front
door for a real project root, and it is exercised only by callers that have
one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import branch_ownership_resolver as bor
from . import connectivity as conn
from . import system_resource_inventory as sri

# ---------------------------------------------------------------------------
# The canonical FW operation kind this registry is about. Referenced from
# `branch_ownership_resolver`'s own recognized-kinds set (never re-typed as an
# unchecked literal) so a rename over there cannot silently desync this
# module's default.
# ---------------------------------------------------------------------------

FW_SERVICE_LOOP_OPERATION_KIND = "FW_EVENT_SERVICE_LOOP"
assert FW_SERVICE_LOOP_OPERATION_KIND in bor.ALL_OPERATION_KINDS, (
    "branch_ownership_resolver no longer recognizes FW_EVENT_SERVICE_LOOP -- "
    "this module's default operation kind must track that module's real "
    "vocabulary, never drift from it")

# ---------------------------------------------------------------------------
# Per-subsystem cross-subsystem-resource status (derived from
# `system_resource_inventory.real_cross_subsystem_findings()`'s own fields,
# never a re-derivation of its analysis).
# ---------------------------------------------------------------------------

CS_BLOCKED = "BLOCKED_ACTIVE_DRIVER_CONFLICT"
CS_HELD = "HELD_PENDING_EQUIVALENCE_EVIDENCE"
CS_SHARED = "SHARED_WITH_OTHER_SUBSYSTEM"
CS_CLEAR = "CLEAR"
CS_NOT_DECLARED = "NOT_APPLICABLE_NO_FW_RESOURCES_DECLARED"
CS_UNKNOWN = "UNKNOWN_CROSS_SUBSYSTEM_ANALYSIS_UNAVAILABLE"

CROSS_SUBSYSTEM_STATUSES: Tuple[str, ...] = (
    CS_BLOCKED, CS_HELD, CS_SHARED, CS_CLEAR, CS_NOT_DECLARED, CS_UNKNOWN,
)

# ---------------------------------------------------------------------------
# Per-subsystem overall entry status -- the worst-wins combination of this
# subsystem's `branch_fw` OWNERSHIP verdict (from branch_ownership_resolver)
# and its cross-subsystem resource status (above).
# ---------------------------------------------------------------------------

ENTRY_BLOCKED_INVALID_OWNERSHIP = "BLOCKED_INVALID_FW_OWNERSHIP"
ENTRY_BLOCKED_RESOURCE_CONFLICT = "BLOCKED_SYSTEM_RESOURCE_CONFLICT"
ENTRY_UNKNOWN = "UNKNOWN"
ENTRY_HELD = "HELD_PENDING_EQUIVALENCE_EVIDENCE"
ENTRY_CLEAR_SHARED = "CLEAR_SHARED_WITH_OTHER_SUBSYSTEM"
ENTRY_CLEAR_NO_RESOURCES = "CLEAR_NO_FW_RESOURCES_DECLARED"
ENTRY_CLEAR = "CLEAR"

#: Worst-first. The single place severity order is defined -- every rollup in
#: this module reads this table rather than re-deciding precedence ad hoc.
_ENTRY_SEVERITY_ORDER: Tuple[str, ...] = (
    ENTRY_BLOCKED_INVALID_OWNERSHIP,
    ENTRY_BLOCKED_RESOURCE_CONFLICT,
    ENTRY_UNKNOWN,
    ENTRY_HELD,
    ENTRY_CLEAR_SHARED,
    ENTRY_CLEAR_NO_RESOURCES,
    ENTRY_CLEAR,
)

# ---------------------------------------------------------------------------
# Registry-level (SYSTEM-wide) status.
# ---------------------------------------------------------------------------

REGISTRY_BLOCKED = "BLOCKED"
REGISTRY_UNKNOWN = "UNKNOWN"
REGISTRY_HELD = "HELD_PENDING_EQUIVALENCE_EVIDENCE"
REGISTRY_CLEAR = "CLEAR"
REGISTRY_NOT_APPLICABLE = "NOT_APPLICABLE"

REGISTRY_STATUSES: Tuple[str, ...] = (
    REGISTRY_BLOCKED, REGISTRY_UNKNOWN, REGISTRY_HELD, REGISTRY_CLEAR,
    REGISTRY_NOT_APPLICABLE,
)

_REGISTRY_STATUS_FOR_ENTRY: Dict[str, str] = {
    ENTRY_BLOCKED_INVALID_OWNERSHIP: REGISTRY_BLOCKED,
    ENTRY_BLOCKED_RESOURCE_CONFLICT: REGISTRY_BLOCKED,
    ENTRY_UNKNOWN: REGISTRY_UNKNOWN,
    ENTRY_HELD: REGISTRY_HELD,
    ENTRY_CLEAR_SHARED: REGISTRY_CLEAR,
    ENTRY_CLEAR_NO_RESOURCES: REGISTRY_CLEAR,
    ENTRY_CLEAR: REGISTRY_CLEAR,
}


class SystemFWServiceRegistryError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


# ===========================================================================
# Cross-subsystem-status derivation -- reads `real_cross_subsystem_findings()`
# output verbatim, never re-derives it.
# ===========================================================================

def _cross_subsystem_status_for_resources(
        fw_owned_resource_ids: Sequence[str],
        cross_subsystem_findings: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """One subsystem's `branch_fw`-owned resource ids against
    `system_resource_inventory.real_cross_subsystem_findings()`'s own fields.

    Precedence (worst first), matching SYS-12's own severity (a STOPPED
    resource is a real, currently-unresolved two-active-driver conflict;
    HELD is merely unproven-but-both-active; SHARED is a real relationship
    that automatic integration was nonetheless ALLOWED to proceed past):

      1. Any declared resource id is in `stopped_resource_ids` -> CS_BLOCKED.
      2. Any declared resource id is in `held_resource_ids` -> CS_HELD.
      3. Any declared resource id is in `shared_resource_ids` -> CS_SHARED.
      4. Otherwise -> CS_CLEAR.

    `cross_subsystem_findings` missing, or reporting
    `system_resource_inventory.CROSSCHECK_UNAVAILABLE`, is the honest
    CS_UNKNOWN -- this function never treats "not checked" as "checked and
    clean". A subsystem with no declared `fw_owned_resource_ids` at all is
    CS_NOT_DECLARED regardless of whether findings are available, since there
    is nothing of this subsystem's to cross-check in the first place.
    """
    ids = sorted({str(r) for r in (fw_owned_resource_ids or []) if str(r).strip()})
    if not ids:
        return {"cross_subsystem_status": CS_NOT_DECLARED, "matched_resource_ids": [],
                "reason": "no fw_owned_resource_ids were declared for this subsystem's "
                          "branch_fw loop -- nothing to cross-check against the real "
                          "system-level analysis"}

    findings = cross_subsystem_findings or {}
    if findings.get("status") != sri.CROSSCHECK_AVAILABLE:
        reason = str(findings.get("reason") or "no cross_subsystem_findings were supplied")
        return {"cross_subsystem_status": CS_UNKNOWN, "matched_resource_ids": ids,
                "reason": ("system_resource_inventory's real cross-subsystem analysis is "
                          f"unavailable ({reason}) -- this subsystem's declared "
                          "branch_fw-owned resource(s) cannot be checked for a system-level "
                          "conflict, so this is honestly UNKNOWN rather than CLEAR")}

    stopped = set(findings.get("stopped_resource_ids") or [])
    held = set(findings.get("held_resource_ids") or [])
    shared = set(findings.get("shared_resource_ids") or [])

    hit_stopped = sorted(set(ids) & stopped)
    if hit_stopped:
        return {"cross_subsystem_status": CS_BLOCKED, "matched_resource_ids": hit_stopped,
                "reason": (f"branch_fw-owned resource(s) {hit_stopped} are in the real "
                          "system-level analysis's stopped_resource_ids -- "
                          "STOP_AUTOMATIC_INTEGRATION_UNTIL_OWNERSHIP_RESOLVED "
                          "(two ACTIVE drivers on one physical interface)")}

    hit_held = sorted(set(ids) & held)
    if hit_held:
        return {"cross_subsystem_status": CS_HELD, "matched_resource_ids": hit_held,
                "reason": (f"branch_fw-owned resource(s) {hit_held} are in the real "
                          "system-level analysis's held_resource_ids -- "
                          "HOLD_PENDING_PHYSICAL_EQUIVALENCE_EVIDENCE")}

    hit_shared = sorted(set(ids) & shared)
    if hit_shared:
        return {"cross_subsystem_status": CS_SHARED, "matched_resource_ids": hit_shared,
                "reason": (f"branch_fw-owned resource(s) {hit_shared} are a real "
                          "SAME_PHYSICAL_RESOURCE/SHARED_LOGICAL_RESOURCE relationship in the "
                          "system-level analysis, but automatic integration was not stopped "
                          "or held for them")}

    return {"cross_subsystem_status": CS_CLEAR, "matched_resource_ids": [],
            "reason": (f"branch_fw-owned resource(s) {ids} do not appear in the real "
                      "system-level analysis's stopped/held/shared resource ids")}


# ===========================================================================
# Per-subsystem branch_fw ownership -- reads branch_ownership_resolver
# verbatim, never re-derives its classification/validation.
# ===========================================================================

def _branch_ownership_for_entry(declaration: Mapping[str, Any]) -> bor.ValidationResult:
    """`branch_ownership_resolver.validate_branch_assignment()`, called with
    this subsystem's declared branch label plus its (optionally declared)
    operation-kind facts, defaulting `operation_kind` to
    `FW_SERVICE_LOOP_OPERATION_KIND` since this registry's whole subject is
    the `branch_fw` role. A caller declaring a DIFFERENT operation_kind is
    honored rather than overridden -- that is precisely how this registry
    catches a subsystem that mislabels a non-FW operation as its `branch_fw`
    entry."""
    return bor.validate_branch_assignment(
        declaration.get("branch_label"),
        declaration.get("operation_kind") or FW_SERVICE_LOOP_OPERATION_KIND,
        per_port=declaration.get("per_port"),
        driven_by=declaration.get("driven_by"),
        arbitration_policy=declaration.get("arbitration_policy"),
    )


def _entry_status(branch_verdict: str, cross_status: str) -> str:
    """Worst-wins combination of one subsystem's two independent facts. See
    `_ENTRY_SEVERITY_ORDER` for the table this must stay consistent with."""
    if branch_verdict == bor.INVALID:
        return ENTRY_BLOCKED_INVALID_OWNERSHIP
    if cross_status == CS_BLOCKED:
        return ENTRY_BLOCKED_RESOURCE_CONFLICT
    if branch_verdict == bor.AMBIGUOUS or cross_status == CS_UNKNOWN:
        return ENTRY_UNKNOWN
    if cross_status == CS_HELD:
        return ENTRY_HELD
    if cross_status == CS_SHARED:
        return ENTRY_CLEAR_SHARED
    if cross_status == CS_NOT_DECLARED:
        return ENTRY_CLEAR_NO_RESOURCES
    return ENTRY_CLEAR


def _worst_entry_status(statuses: Sequence[str]) -> str:
    for candidate in _ENTRY_SEVERITY_ORDER:
        if candidate in statuses:
            return candidate
    # Structural bug, not a data condition: every entry_status this module
    # itself produces is one of _ENTRY_SEVERITY_ORDER's members.
    raise SystemFWServiceRegistryError(
        "UNRECOGNIZED_ENTRY_STATUS", {"statuses": sorted(set(statuses))})


# ===========================================================================
# The registry itself
# ===========================================================================

def build_system_fw_service_registry(
        subsystem_declarations: Optional[Sequence[Mapping[str, Any]]] = None, *,
        cross_subsystem_findings: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the per-SYSTEM `branch_fw` service-loop ownership registry.

    `subsystem_declarations`: one record per subsystem composed into this
    SYSTEM --
    `[{"subsystem_id", "branch_label", "operation_kind"(optional, defaults to
       FW_EVENT_SERVICE_LOOP), "per_port"(optional), "driven_by"(optional),
       "arbitration_policy"(optional), "fw_owned_resource_ids"(optional list
       of str, in system_resource_inventory's own
       "SUBSYS::hierarchy::interface" resource_id convention)}]`.
    Empty/omitted -> NOT_APPLICABLE (nothing composed to register).

    `cross_subsystem_findings`: the real, verbatim output of
    `system_resource_inventory.real_cross_subsystem_findings()` (or an
    equivalent dict carrying the same `status`/`stopped_resource_ids`/
    `held_resource_ids`/`shared_resource_ids` fields) for THIS SAME composed
    system. Omitting it, or a findings dict reporting
    `system_resource_inventory.CROSSCHECK_UNAVAILABLE`, makes every entry's
    cross-subsystem status the honest UNKNOWN -- never CLEAR.

    Returns a dict with `status` (one of REGISTRY_STATUSES), `reason`, and
    `entries` -- one per declared subsystem, each carrying its real
    `branch_ownership` verdict (verbatim from `branch_ownership_resolver`)
    and its `cross_subsystem` status (derived from the real findings above).
    """
    declarations = list(subsystem_declarations or [])
    if not declarations:
        return {
            "status": REGISTRY_NOT_APPLICABLE,
            "reason": "no subsystem_declarations were supplied -- there is no composed "
                      "SYSTEM's branch_fw ownership to register",
            "subsystem_count": 0,
            "cross_subsystem_findings_supplied": cross_subsystem_findings is not None,
            "entries": [],
        }

    ids = [str(d.get("subsystem_id") or "") for d in declarations]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SystemFWServiceRegistryError("DUPLICATE_SUBSYSTEM_ID_IN_DECLARATIONS", {
            "subsystem_ids": duplicates,
            "hint": "one SYSTEM-level branch_fw registry entry per subsystem; two "
                    "declarations sharing a subsystem_id would make its ownership record "
                    "ambiguous"})

    entries: List[Dict[str, Any]] = []
    for i, raw in enumerate(declarations):
        declaration = raw or {}
        subsystem_id = str(declaration.get("subsystem_id") or "") or f"subsystem_declarations[{i}]"
        branch_verdict_obj = _branch_ownership_for_entry(declaration)
        cross = _cross_subsystem_status_for_resources(
            declaration.get("fw_owned_resource_ids") or [], cross_subsystem_findings)
        entry_status = _entry_status(branch_verdict_obj.verdict, cross["cross_subsystem_status"])
        entries.append({
            "subsystem_id": subsystem_id,
            "branch_label": declaration.get("branch_label"),
            "operation_kind": declaration.get("operation_kind") or FW_SERVICE_LOOP_OPERATION_KIND,
            "branch_ownership": branch_verdict_obj.to_dict(),
            "fw_owned_resource_ids": sorted({str(r) for r in
                                             (declaration.get("fw_owned_resource_ids") or [])
                                             if str(r).strip()}),
            "cross_subsystem_status": cross["cross_subsystem_status"],
            "cross_subsystem_matched_resource_ids": cross["matched_resource_ids"],
            "cross_subsystem_reason": cross["reason"],
            "entry_status": entry_status,
        })

    entries.sort(key=lambda e: e["subsystem_id"])
    worst = _worst_entry_status([e["entry_status"] for e in entries])
    status = _REGISTRY_STATUS_FOR_ENTRY[worst]

    blocked = [e for e in entries if e["entry_status"] in
               (ENTRY_BLOCKED_INVALID_OWNERSHIP, ENTRY_BLOCKED_RESOURCE_CONFLICT)]
    unknown = [e for e in entries if e["entry_status"] == ENTRY_UNKNOWN]
    held = [e for e in entries if e["entry_status"] == ENTRY_HELD]

    if status == REGISTRY_BLOCKED:
        names = sorted(e["subsystem_id"] for e in blocked)
        reason = (f"{len(blocked)} subsystem(s) block this SYSTEM's branch_fw registry: "
                  f"{names} -- see 'entries' for the invalid ownership or system-level "
                  "resource-conflict evidence")
    elif status == REGISTRY_UNKNOWN:
        names = sorted(e["subsystem_id"] for e in unknown)
        reason = (f"{len(unknown)} subsystem(s) cannot be judged: {names} -- ambiguous "
                  "branch_fw classification and/or unavailable cross-subsystem analysis")
    elif status == REGISTRY_HELD:
        names = sorted(e["subsystem_id"] for e in held)
        reason = (f"{len(held)} subsystem(s) held pending physical-equivalence evidence: "
                  f"{names}")
    else:
        reason = (f"{len(entries)} composed subsystem(s) checked; every branch_fw "
                  "assignment is VALID and no system-level resource conflict was found")

    by_entry_status = {s: 0 for s in _ENTRY_SEVERITY_ORDER}
    for e in entries:
        by_entry_status[e["entry_status"]] += 1
    by_cross_status = {s: 0 for s in CROSS_SUBSYSTEM_STATUSES}
    for e in entries:
        by_cross_status[e["cross_subsystem_status"]] += 1

    return {
        "status": status,
        "reason": reason,
        "subsystem_count": len(entries),
        "cross_subsystem_findings_supplied": cross_subsystem_findings is not None,
        "cross_subsystem_findings_status": (cross_subsystem_findings or {}).get("status"),
        "entries": entries,
        "summary": {
            "entries_by_entry_status": by_entry_status,
            "entries_by_cross_subsystem_status": by_cross_status,
        },
    }


def find_system_fw_service_registry_for_root(
        root, subsystem_declarations: Optional[Sequence[Mapping[str, Any]]] = None, *,
        selected: Optional[Sequence[str]] = None,
        declared: Optional[Mapping[str, Any]] = None,
        budget_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Convenience wrapper for a real project root: runs
    `system_resource_inventory.real_cross_subsystem_findings()` for real
    (never re-implemented here) and folds the result straight into
    `build_system_fw_service_registry()`. `selected`/`declared`/
    `budget_seconds` are passed straight through to that function -- see its
    own docstring for their meaning."""
    findings = sri.real_cross_subsystem_findings(
        root, selected, declared=declared, budget_seconds=budget_seconds)
    return build_system_fw_service_registry(
        subsystem_declarations, cross_subsystem_findings=findings)


# ===========================================================================
# Rendering + shared CLI front door
# ===========================================================================

def render_registry_table(report: Mapping[str, Any]) -> str:
    """The mandatory registry table, rendered through the repo's one
    parameterized markdown table renderer (`connectivity.render_markdown_
    table`) rather than a hand-rolled table loop."""
    columns = [
        ("subsystem_id", "Subsystem"), ("branch_label", "Branch Label"),
        ("branch_verdict", "Branch Ownership"), ("cross_subsystem_status", "System Resource Status"),
        ("entry_status", "Entry Status"),
    ]
    rows = []
    for e in report.get("entries") or []:
        row = dict(e)
        row["branch_verdict"] = (e.get("branch_ownership") or {}).get("verdict")
        rows.append(row)
    return conn.render_markdown_table(columns, rows,
                                      empty_note="(no subsystems declared)")


def format_report(report: Mapping[str, Any]) -> str:
    lines = [f"SYSTEM FW SERVICE REGISTRY (branch_fw ownership across composed subsystems): "
             f"{report['status']}", ""]
    lines.append(report["reason"])
    lines.append("")
    lines.append(f"  subsystems declared         : {report.get('subsystem_count', 0)}")
    lines.append(f"  cross-subsystem findings     : "
                 f"{report.get('cross_subsystem_findings_status') or 'NOT SUPPLIED'}")
    lines.append("")
    lines.append(render_registry_table(report))
    lines.append("")
    lines.append("SCOPE: per-SYSTEM branch_fw ownership recording, detection only. Reuses")
    lines.append("branch_ownership_resolver.py's FW classification and")
    lines.append("system_resource_inventory.py's real cross-subsystem findings verbatim --")
    lines.append("neither is re-derived here. Never edits a pattern, never renames a branch,")
    lines.append("never arbitrates a resource conflict; a human resolves any BLOCKED entry from")
    lines.append("the real evidence named in it.")
    return "\n".join(lines)


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(input_path=None, *, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for
    `python -m dv_harness.system_fw_service_registry` (no `dv-harness` CLI
    verb was wired -- `cli.py` is out of scope for this task, matching this
    codebase's own recent sanctioned fallback for `shared_bus_resource_
    registry.py` and several other modules). `input_path` names a JSON file
    carrying `{"subsystem_declarations": [...], "cross_subsystem_findings":
    {...}}` (the latter optional). Returns (text, exit_code): 0 CLEAR,
    1 BLOCKED, 2 UNKNOWN/HELD/NOT_APPLICABLE."""
    payload = _load_json(input_path) if input_path else {}
    report = build_system_fw_service_registry(
        payload.get("subsystem_declarations"),
        cross_subsystem_findings=payload.get("cross_subsystem_findings"))
    text = json.dumps(report, indent=2) if as_json else format_report(report)
    code = {REGISTRY_BLOCKED: 1, REGISTRY_CLEAR: 0,
            REGISTRY_UNKNOWN: 2, REGISTRY_HELD: 2, REGISTRY_NOT_APPLICABLE: 2}[report["status"]]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.system_fw_service_registry",
        description="Per-SYSTEM branch_fw service-loop ownership registry across composed "
                    "subsystems. Reuses branch_ownership_resolver.py's FW classification and "
                    "system_resource_inventory.py's real cross-subsystem findings; re-derives "
                    "neither.")
    ap.add_argument("--input", dest="input_path",
                    help="Path to a JSON file: {\"subsystem_declarations\": [{\"subsystem_id\", "
                         "\"branch_label\", \"operation_kind\"(optional), \"per_port\"(optional), "
                         "\"driven_by\"(optional), \"fw_owned_resource_ids\"(optional)}], "
                         "\"cross_subsystem_findings\"(optional, "
                         "system_resource_inventory.real_cross_subsystem_findings()-shaped)}.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.input_path, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
