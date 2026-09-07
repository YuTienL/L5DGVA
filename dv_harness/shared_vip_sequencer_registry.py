"""Intra-subsystem shared-VIP-sequencer registry: branch_b*-vs-branch_b*
concurrent-programming race detection over the AMBA M x N arbitration prose
this module operationalizes (the same `.claude/skills/CORE/branch-mapper/
SKILL.md` "AMBA M x N Mapping" section and `.claude/skills/CORE/
pattern-architecture/SKILL.md` section 3.1 trap class that
`shared_bus_resource_registry.py` already operationalizes for the
branch_fw-vs-branch_a* pair).

WHY THIS IS A DIFFERENT SCOPE FROM `shared_bus_resource_registry.py`
----------------------------------------------------------------------
`shared_bus_resource_registry.py` implements exactly ONE conflict type:
`branch_fw` (the shared per-port FW/event-service loop) racing a
`branch_a{i}` (a per-port DUT+PHY bring-up task) over one shared BUS
resource (an APB/AXI master, an interrupt controller, a shared reset
controller, a shared PHY config block) with no common named lock. That
module's own docstring states its detection scope is specifically that one
pair, and its own `derive_conflict_status()` deliberately reports
`NO_CONFLICT` for a resource shared only among several `branch_a*` (or only
ever touched by `branch_b*`) -- calling those OUT of its own scope, not
uncovered.

This module is the sibling `pattern-architecture` 3.1 itself illustrates
with its own worked example: `block`/`branch_a*` (DUT-driven) vs
`branch_b*` (VIP-driven). Concretely, TWO DIFFERENT `branch_b{i}` bodies --
e.g. `branch_b0`'s and `branch_b1`'s own VIP-driven parallel scenario tasks,
per `branch-mapper`'s Initialization Task Hierarchy item 1 -- can both reach
ONE shared VIP agent/sequencer instance (a single physical VIP agent
representing a bus/interface multiple port branches legitimately drive, or
one shared error-injection/monitor sequencer instance several `branch_b*`
scenarios are wired to) AT THE SAME TIME, through two DIFFERENT named
locks/sequencer-ownership tokens the arbitration layer can then interleave
in an order neither branch's author controls -- the identical failure mode,
one task-group pair over. Neither `shared_bus_resource_registry.py` nor
`system_resource_inventory.py`/`ip_ownership_conflict.py` (the two modules
that module's own docstring already distinguishes itself from) models a
`branch_b*`-vs-`branch_b*` pair at all: this module closes exactly, and
only, that gap.

EVIDENCE, HONESTLY
-------------------
Exactly the same honesty this codebase already applies to
`shared_bus_resource_registry.py`'s own `resource_declarations`: no
producer in this codebase extracts "which named lock/sequencer-ownership
token a `branch_b{i}` task holds while driving VIP agent/sequencer X" from
a real `command.txt` pattern file or VIP source -- there is no
SystemVerilog pattern-body parser anywhere in `dv_harness/` (patterns are
agent-authored per `pattern-architecture`'s own checklist). WHICH
`branch_b{i}` body programs WHICH shared VIP agent/sequencer under WHICH
named lock/ownership token is therefore a CALLER-DECLARED fact
(`sequencer_declarations`), never inferred or guessed here -- and every
declared programmer record REQUIRES a real `evidence` citation (a pattern
file:line, or the VIP examples/user-manual/source/class-reference line the
`vip-scenario-branch` sourcing rules already require for any `branch_b*`
content, per the Engineering Discipline Rules' "branch-B / VIP pattern
changes" rule). A declaration with no evidence, or naming a `task_group`
outside the canonical `block`/`branch_a{i}`/`branch_fw`/`branch_b{i}`
vocabulary (per CLAUDE.md's Architecture-conformance audit rule), is marked
invalid and never silently treated as clear -- see `CONFLICT_UNKNOWN`
below.

`connectivity_rows` is an OPTIONAL second input -- real
`connectivity.build_connectivity_matrix()` rows for the SAME subsystem --
used only to attach each declared shared VIP agent/sequencer's real
`bind_target`/`dut_instance` hierarchy path when one resolves, exactly the
enrichment `shared_bus_resource_registry._hierarchy_from_connectivity()`
already performs the identical way. Omitting it never invents a hierarchy
path.

SCOPE BOUNDARY -- DETECTION ONLY
---------------------------------
This module names a race for a human to resolve (align the two `branch_b*`
bodies onto one shared named lock/sequencer-ownership token, or serialize
them, per real VIP/pattern evidence). It never picks a winner, never edits
a pattern file, never assigns or invents a lock name, and never touches any
approval/governance mechanism -- the identical boundary
`shared_bus_resource_registry.py` and `ip_ownership_conflict.py` both state
for themselves.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import connectivity as conn
from .shared_bus_resource_registry import (
    TG_BRANCH_B,
    TG_INVALID,
    classify_task_group,
    normalize_programmers,
)

# ---------------------------------------------------------------------------
# Report-level vocabulary (NEW, intra-subsystem branch_b*-vs-branch_b*
# race-scoped; distinct from shared_bus_resource_registry.py's own
# STATUS_*/CONFLICT_*/LOCK_POLICY_* vocabulary -- a different task-group
# pairing, never merged with that module's own values).
# ---------------------------------------------------------------------------

STATUS_CONTENTION = "CONTENTION"
STATUS_CLEAR = "CLEAR"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_UNKNOWN = "UNKNOWN"
REPORT_STATUSES: Tuple[str, ...] = (
    STATUS_CONTENTION, STATUS_CLEAR, STATUS_NOT_APPLICABLE, STATUS_UNKNOWN,
)

# ---------------------------------------------------------------------------
# Per-VIP-sequencer-entry conflict_status
# ---------------------------------------------------------------------------

CONFLICT_B_B_RACE = "BRANCH_B_RACE"
CONFLICT_NONE = "NO_CONFLICT"
CONFLICT_NOT_APPLICABLE = "NOT_APPLICABLE"
CONFLICT_UNKNOWN = "UNKNOWN_INSUFFICIENT_EVIDENCE"
ENTRY_CONFLICT_STATUSES: Tuple[str, ...] = (
    CONFLICT_B_B_RACE, CONFLICT_NONE, CONFLICT_NOT_APPLICABLE, CONFLICT_UNKNOWN,
)

# ---------------------------------------------------------------------------
# lock_policy -- what the declared programmer set says about arbitration
# discipline on this shared VIP agent/sequencer, independent of whether a
# genuine branch_b-vs-branch_b pair happens to be present at all. Reuses
# the exact same 5-value vocabulary shared_bus_resource_registry.py
# already defines for the identical concept over a different resource
# class -- restated here (not imported) since that module's own
# LOCK_POLICY_* constants are specifically scoped to its own module-level
# docstring/report text, and this module's own report text (below) speaks
# of a "shared VIP agent/sequencer" rather than a "shared bus resource".
# ---------------------------------------------------------------------------

LOCK_POLICY_SINGLE_SHARED = "SINGLE_SHARED_LOCK"
LOCK_POLICY_DISTINCT = "DISTINCT_LOCKS_PER_TASK_GROUP"
LOCK_POLICY_NONE_DECLARED = "NO_LOCK_DECLARED"
LOCK_POLICY_PARTIAL = "PARTIAL_LOCK_DECLARATION"
LOCK_POLICY_SINGLE_PROGRAMMER = "SINGLE_PROGRAMMER_NO_ARBITRATION_NEEDED"
LOCK_POLICIES: Tuple[str, ...] = (
    LOCK_POLICY_SINGLE_SHARED, LOCK_POLICY_DISTINCT, LOCK_POLICY_NONE_DECLARED,
    LOCK_POLICY_PARTIAL, LOCK_POLICY_SINGLE_PROGRAMMER,
)

# ---------------------------------------------------------------------------
# resource_type -- what KIND of shared VIP construct this is. Caller-
# declared, never inferred: this module has no VIP-source classifier of
# its own (that stays vip_symbol_index.py/vip_capability_extraction.py's
# job), and guessing a construct's type from its id would be exactly the
# name-derived guess CLAUDE.md's Architecture-conformance rule forbids.
# ---------------------------------------------------------------------------

RT_VIP_AGENT = "VIP_AGENT"
RT_VIP_SEQUENCER = "VIP_SEQUENCER"
RT_VIP_VIRTUAL_SEQUENCER = "VIP_VIRTUAL_SEQUENCER"
RT_UNCLASSIFIED = "UNCLASSIFIED"
RESOURCE_TYPES: Tuple[str, ...] = (
    RT_VIP_AGENT, RT_VIP_SEQUENCER, RT_VIP_VIRTUAL_SEQUENCER, RT_UNCLASSIFIED,
)


class SharedVipSequencerRegistryError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


# ===========================================================================
# branch_b*-vs-branch_b* race derivation
#
# normalize_programmers()/classify_task_group() are REUSED verbatim from
# shared_bus_resource_registry.py -- they are generic over the whole
# block/branch_a{i}/branch_fw/branch_b{i} vocabulary, not FW/A-specific,
# so reusing them here is genuine reuse rather than a coincidental name
# match. _locks_agree()/_normalize_lock_name() are NOT imported (they are
# module-private in shared_bus_resource_registry.py); the identical, tiny
# "two programmers are serialized against each other only when both name
# the SAME real lock; an absent lock never agrees with anything, including
# another absent lock" rule is restated here as its own small function so
# this module carries no dependency on that module's private surface.
# ===========================================================================

def _locks_agree(lock_a: Optional[str], lock_b: Optional[str]) -> bool:
    """Two programmers are serialized against each other ONLY when both name
    the SAME real lock/sequencer-ownership token. An absent lock on either
    side never agrees with anything, including another absent lock -- the
    identical rule shared_bus_resource_registry._locks_agree() already
    applies for the branch_fw-vs-branch_a* pair, restated here since that
    function is module-private there."""
    return lock_a is not None and lock_a == lock_b


def derive_lock_policy(programmers: Sequence[Mapping[str, Any]]) -> str:
    """One declared programmer set maps onto exactly one `lock_policy`,
    judged over ALL declared programmers on the shared VIP construct (not
    only a branch_b-vs-branch_b subset), because lock discipline is a
    property of the construct's whole access set -- the identical
    single-decision-function shape
    shared_bus_resource_registry.derive_lock_policy() already applies."""
    if len(programmers) < 2:
        return LOCK_POLICY_SINGLE_PROGRAMMER
    locks = [p["lock_name"] for p in programmers]
    declared = [l for l in locks if l is not None]
    if not declared:
        return LOCK_POLICY_NONE_DECLARED
    if len(declared) < len(locks):
        return LOCK_POLICY_PARTIAL
    if len(set(declared)) == 1:
        return LOCK_POLICY_SINGLE_SHARED
    return LOCK_POLICY_DISTINCT


def derive_conflict_status(programmers: Sequence[Mapping[str, Any]],
                           ) -> Dict[str, Any]:
    """The branch_b*-vs-branch_b* race check for ONE shared VIP agent/
    sequencer's normalized programmer set.

    Precedence, mirroring shared_bus_resource_registry.derive_conflict_
    status()'s own shape but comparing TWO DIFFERENT branch_b bodies
    against each other rather than a branch_fw/branch_a* cross-family
    pair:

      1. Fewer than two DECLARED programmers at all -> NOT_APPLICABLE:
         nothing concurrent to arbitrate.
      2. Fewer than two DISTINCT branch_b{i} indices are RECOGNIZED among
         the declared programmers (zero, or all declarations naming the
         same one branch_b index -- e.g. two records both for branch_b0,
         which is not a race between two DIFFERENT bodies), AND no
         programmer on this construct carries a non-canonical (TG_INVALID)
         task_group name either -> NO_CONFLICT. This module's detection
         scope is specifically two DIFFERENT branch_b{i} bodies (per the
         module docstring); a construct declared by only one branch_b
         index (however many times), or touched only by block/branch_a*/
         branch_fw programmers, reports NO_CONFLICT here rather than a
         fabricated verdict about a pairing this module was not asked to
         judge -- shared_bus_resource_registry.py's own branch_fw-vs-
         branch_a* pair, and branch-mapper's cross-branch_a* arbitration
         rule, are different, already-covered cases.
      2b. Fewer than two distinct branch_b indices are recognized, but at
         least one OTHER programmer on this construct carries a non-
         canonical task_group name -> UNKNOWN_INSUFFICIENT_EVIDENCE. A
         name outside the canonical vocabulary is not evidence that a
         second branch_b body is ABSENT -- it is evidence that this
         specific declaration's role cannot be classified at all, so "no
         such second body" cannot be asserted with confidence.
      3. At least two distinct branch_b indices ARE recognized, but fewer
         than two of them have at least one VALID (evidenced, canonically
         named) declaration -> UNKNOWN_INSUFFICIENT_EVIDENCE: a pair of
         bodies is NAMED but ownership cannot be trusted, so this module
         reports its own ignorance rather than guessing CLEAR or
         CONTENTION.
      4. At least two distinct branch_b indices each have at least one
         valid declaration. If EVERY cross-index pair of valid
         declarations shares one real named lock -> NO_CONFLICT (properly
         serialized). If ANY cross-index pair does not share a real named
         lock (either side declares none, or the two differ) -> race,
         naming every non-agreeing pair as a conflicting owner with both
         branches' real evidence citations. Two declarations for the SAME
         branch_b index are never compared against each other (that is
         not a branch_b-vs-branch_b race, it is the same body reusing its
         own sequencer, or a duplicate declaration).
    """
    if len(programmers) < 2:
        return {"conflict_status": CONFLICT_NOT_APPLICABLE, "conflicting_owners": [],
                "reason": "fewer than two programmers were declared on this shared VIP "
                          "agent/sequencer -- nothing concurrent to arbitrate"}

    b_all = [p for p in programmers if p["task_group_family"] == TG_BRANCH_B]
    unclassifiable = [p for p in programmers if p["task_group_family"] == TG_INVALID]
    distinct_indices_all = sorted({p["branch_id"] for p in b_all})

    if len(distinct_indices_all) < 2:
        if unclassifiable:
            names = sorted({p["branch_id"] for p in unclassifiable})
            return {"conflict_status": CONFLICT_UNKNOWN, "conflicting_owners": [],
                    "reason": (f"fewer than two DIFFERENT branch_b{{i}} bodies were RECOGNIZED "
                               f"on this shared VIP construct, but {names} carr"
                               f"{'ies' if len(names) == 1 else 'y'} a task_group name outside "
                               "the canonical block/branch_a{i}/branch_fw/branch_b{i} "
                               "vocabulary -- that is not evidence a second branch_b body is "
                               "absent, only that this declaration's role cannot be "
                               "classified, so 'no such second body' cannot be asserted")}
        return {"conflict_status": CONFLICT_NONE, "conflicting_owners": [],
                "reason": "fewer than two DIFFERENT branch_b{i} bodies were declared on this "
                          "shared VIP construct -- this module's detection scope is "
                          "specifically a branch_b*-vs-branch_b* pair of DIFFERENT bodies, so "
                          "there is no such pair here to judge"}

    by_index: Dict[str, List[Dict[str, Any]]] = {}
    for p in b_all:
        by_index.setdefault(p["branch_id"], []).append(p)
    valid_by_index = {idx: [p for p in ps if p["valid"]] for idx, ps in by_index.items()}
    indices_with_valid = sorted(idx for idx, ps in valid_by_index.items() if ps)

    if len(indices_with_valid) < 2:
        invalid = [p for ps in by_index.values() for p in ps if not p["valid"]]
        return {"conflict_status": CONFLICT_UNKNOWN, "conflicting_owners": [],
                "reason": ("two or more DIFFERENT branch_b{i} bodies are declared on this "
                           "shared VIP construct, but fewer than two of them carry a "
                           "trustworthy (evidenced, canonically named) declaration ("
                           + "; ".join(f"{p['branch_id']}: {', '.join(p['invalid_reasons'])}"
                                       for p in invalid) + ") -- ownership cannot be judged "
                           "between two bodies without a trustworthy declaration on both")}

    conflicting: List[Dict[str, Any]] = []
    for i, idx_a in enumerate(indices_with_valid):
        for idx_b in indices_with_valid[i + 1:]:
            for a in valid_by_index[idx_a]:
                for b in valid_by_index[idx_b]:
                    if not _locks_agree(a["lock_name"], b["lock_name"]):
                        conflicting.append({
                            "a_branch": a["branch_id"], "a_lock": a["lock_name"] or "NONE_DECLARED",
                            "a_evidence": a["evidence"],
                            "b_branch": b["branch_id"], "b_lock": b["lock_name"] or "NONE_DECLARED",
                            "b_evidence": b["evidence"],
                        })
    if conflicting:
        return {"conflict_status": CONFLICT_B_B_RACE, "conflicting_owners": conflicting,
                "reason": (f"{len(conflicting)} branch_b*-vs-branch_b* pair(s) reach this "
                           "shared VIP agent/sequencer without a shared real named lock -- "
                           "the arbitration layer between them can interleave their "
                           "transactions in an order neither branch's author controls "
                           "(pattern-architecture SKILL.md section 3.1); see "
                           "'conflicting_owners' for the real branches and evidence")}
    return {"conflict_status": CONFLICT_NONE, "conflicting_owners": [],
            "reason": (f"every declared branch_b*-vs-branch_b* pair on this shared VIP "
                       "construct shares one real named lock -- properly serialized")}


# ===========================================================================
# Connectivity enrichment (optional)
# ===========================================================================

def _hierarchy_from_connectivity(bind_target: str,
                                 connectivity_rows: Optional[Sequence[Mapping[str, Any]]],
                                 ) -> Optional[str]:
    """Resolve a declared `bind_target` to a real matrix row's `dut_instance`
    hierarchy path, using the identical bind_target-first match convention
    shared_bus_resource_registry._hierarchy_from_connectivity() already
    applies. Returns None (never a guess) when no real row resolves it or
    no rows were supplied."""
    if not bind_target or not connectivity_rows:
        return None
    matrix = conn.build_connectivity_matrix(list(connectivity_rows))
    for row in matrix:
        if str(row.get("bind_target") or "") == bind_target:
            return str(row.get("dut_instance") or "") or None
    return None


# ===========================================================================
# The registry itself
# ===========================================================================

def analyze_shared_vip_sequencer_registry(
        sequencer_declarations: Optional[Sequence[Mapping[str, Any]]] = None, *,
        connectivity_rows: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """The intra-subsystem shared-VIP-sequencer registry.

    `sequencer_declarations`: caller-declared records, one per shared VIP
    agent/sequencer this SINGLE subsystem's pattern suite genuinely
    programs from more than one `branch_b{i}` body --
    `[{"resource_id", "resource_type"(optional), "bind_target"(optional),
       "programmers": [{"task_group", "lock_name"(optional), "evidence"}]}]`.
    See the module docstring for why this is honestly caller-declared
    rather than extracted: no pattern-body parser exists in this codebase.
    Empty/omitted -> NOT_APPLICABLE.

    `connectivity_rows`: optional real connectivity-matrix rows for this
    SAME subsystem, used only to attach a resolved hierarchy path (never
    required, never invented when absent).

    Returns a dict with `status` (one of REPORT_STATUSES), `reason`, and
    `entries` -- one per declared shared VIP construct, each carrying
    `lock_policy`, `conflict_status` and (when `BRANCH_B_RACE`)
    `conflicting_owners` naming the real branch ids and evidence on both
    sides.
    """
    declarations = list(sequencer_declarations or [])
    if not declarations:
        return {
            "status": STATUS_NOT_APPLICABLE,
            "reason": "no sequencer_declarations were supplied -- there is no shared VIP "
                      "agent/sequencer programming to check for a branch_b*-vs-branch_b* race",
            "resource_count": 0,
            "entries": [],
        }

    entries: List[Dict[str, Any]] = []
    seen_ids: Dict[str, int] = {}
    for i, raw in enumerate(declarations):
        entry = raw or {}
        resource_id = str(entry.get("resource_id") or "") or f"sequencer_declarations[{i}]"
        seen_ids[resource_id] = seen_ids.get(resource_id, 0) + 1
        raw_type = str(entry.get("resource_type") or "") or RT_UNCLASSIFIED
        resource_type = raw_type
        bind_target = str(entry.get("bind_target") or "")
        programmers = normalize_programmers(entry.get("programmers"))
        lock_policy = derive_lock_policy(programmers)
        conflict = derive_conflict_status(programmers)
        hierarchy = _hierarchy_from_connectivity(bind_target, connectivity_rows)

        entries.append({
            "resource_id": resource_id,
            "resource_type": resource_type,
            "resource_type_recognized": raw_type in RESOURCE_TYPES,
            "bind_target": bind_target or None,
            "physical_hierarchy": hierarchy,
            "programmer_count": len(programmers),
            "programmers": programmers,
            "lock_policy": lock_policy,
            "conflict_status": conflict["conflict_status"],
            "conflicting_owners": conflict["conflicting_owners"],
            "reason": conflict["reason"],
        })

    duplicate_ids = sorted(r for r, c in seen_ids.items() if c > 1)
    if duplicate_ids:
        raise SharedVipSequencerRegistryError("DUPLICATE_RESOURCE_ID", {
            "resource_ids": duplicate_ids,
            "hint": "each shared VIP agent/sequencer must be declared exactly once; two "
                    "declarations under one resource_id would silently merge two different "
                    "programmer sets"})

    entries.sort(key=lambda e: e["resource_id"])
    racing = [e for e in entries if e["conflict_status"] == CONFLICT_B_B_RACE]
    unknown = [e for e in entries if e["conflict_status"] == CONFLICT_UNKNOWN]
    not_applicable = [e for e in entries if e["conflict_status"] == CONFLICT_NOT_APPLICABLE]

    if racing:
        status = STATUS_CONTENTION
        owners = sorted({f"{o['a_branch']} vs {o['b_branch']}"
                         for e in racing for o in e["conflicting_owners"]})
        reason = (f"{len(racing)} shared VIP agent/sequencer(s) carry an unlocked or "
                  f"differently-locked branch_b*-vs-branch_b* pair: {owners} -- see "
                  "'entries' for full evidence")
    elif unknown:
        status = STATUS_UNKNOWN
        reason = (f"{len(unknown)} shared VIP agent/sequencer(s) declare a branch_b*-vs-"
                  "branch_b* pair whose ownership cannot be judged -- see 'entries' for the "
                  "invalid declaration(s)")
    elif len(not_applicable) == len(entries):
        status = STATUS_NOT_APPLICABLE
        reason = (f"all {len(entries)} declared shared VIP construct(s) have fewer than two "
                  "programmers -- nothing concurrent to arbitrate")
    else:
        status = STATUS_CLEAR
        reason = (f"{len(entries)} declared shared VIP agent/sequencer(s) checked; no "
                  "branch_b*-vs-branch_b* race found")

    by_conflict = {c: 0 for c in ENTRY_CONFLICT_STATUSES}
    for e in entries:
        by_conflict[e["conflict_status"]] += 1
    by_lock_policy = {p: 0 for p in LOCK_POLICIES}
    for e in entries:
        by_lock_policy[e["lock_policy"]] += 1

    return {
        "status": status,
        "reason": reason,
        "resource_count": len(entries),
        "connectivity_rows_supplied": bool(connectivity_rows),
        "entries": entries,
        "summary": {
            "entries_by_conflict_status": by_conflict,
            "entries_by_lock_policy": by_lock_policy,
        },
        "recommendation_only": True,
    }


# ===========================================================================
# Rendering + shared CLI front door
# ===========================================================================

def render_registry_table(report: Mapping[str, Any]) -> str:
    """Mandatory table, rendered through the repo's one parameterized
    markdown table renderer (`connectivity.render_markdown_table`) rather
    than a hand-rolled `"| " + " | ".join(...)` loop -- the same rendering
    reuse shared_bus_resource_registry.render_registry_table() already
    applies."""
    columns = [
        ("resource_id", "Shared VIP Construct"), ("resource_type", "Type"),
        ("programmer_count", "Programmers"), ("lock_policy", "Lock Policy"),
        ("conflict_status", "Conflict Status"), ("owners_cell", "Conflicting Owners"),
    ]
    rows = []
    for e in report.get("entries") or []:
        owners = e.get("conflicting_owners") or []
        owners_cell = "; ".join(f"{o['a_branch']}(lock={o['a_lock']}) vs "
                                f"{o['b_branch']}(lock={o['b_lock']})" for o in owners) or "-"
        row = dict(e)
        row["owners_cell"] = owners_cell
        rows.append(row)
    return conn.render_markdown_table(columns, rows,
                                      empty_note="(no shared VIP agents/sequencers declared)")


def format_report(report: Mapping[str, Any]) -> str:
    lines = [f"SHARED VIP SEQUENCER REGISTRY (branch_b* vs branch_b* race): {report['status']}",
              ""]
    lines.append(report["reason"])
    lines.append("")
    lines.append(f"  shared VIP constructs declared : {report.get('resource_count', 0)}")
    lines.append(f"  connectivity rows given         : {report.get('connectivity_rows_supplied', False)}")
    lines.append("")
    lines.append(render_registry_table(report))
    lines.append("")
    lines.append("SCOPE: intra-subsystem bus arbitration, detection only -- the branch_b*-vs-")
    lines.append("branch_b* sibling of shared_bus_resource_registry.py's own branch_fw-vs-")
    lines.append("branch_a* race detector. Never picks a lock, never edits a pattern file, and")
    lines.append("never invents a timing value or arbitration outcome -- a human aligns the")
    lines.append("conflicting branch_b bodies onto one real named lock, from real VIP/pattern")
    lines.append("evidence.")
    return "\n".join(lines)


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(sequencer_declarations_path=None, *, connectivity_rows_path=None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for
    `python -m dv_harness.shared_vip_sequencer_registry` (no `dv-harness`
    CLI verb wired -- this batch's instructions explicitly forbid editing
    `dv_harness/cli.py`/`gates.py` in this pass, several concurrent
    Workflows being actively edited them; the ad hoc front door below is
    the sanctioned fallback the house style already uses for
    `shared_bus_resource_registry.py` and several other recent modules).
    Returns (text, exit_code): 0 CLEAR, 1 CONTENTION, 2 NOT_APPLICABLE or
    UNKNOWN."""
    declarations = _load_json(sequencer_declarations_path) if sequencer_declarations_path else None
    connectivity_rows = (_load_json(connectivity_rows_path) if connectivity_rows_path else None)
    report = analyze_shared_vip_sequencer_registry(
        declarations, connectivity_rows=connectivity_rows)
    text = json.dumps(report, indent=2) if as_json else format_report(report)
    code = {STATUS_CONTENTION: 1, STATUS_CLEAR: 0,
            STATUS_NOT_APPLICABLE: 2, STATUS_UNKNOWN: 2}[report["status"]]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.shared_vip_sequencer_registry",
        description="Intra-subsystem shared-VIP-sequencer registry: do two DIFFERENT real "
                    "branch_b* bodies reach the same shared VIP agent/sequencer without a "
                    "common real named lock? The branch_b*-vs-branch_b* sibling of "
                    "shared_bus_resource_registry.py's own branch_fw-vs-branch_a* detector. "
                    "Detection only -- never picks a lock.")
    ap.add_argument("--sequencer-declarations", dest="sequencer_declarations_path",
                    help="Path to a JSON array of caller-declared shared-VIP-construct records "
                         "({\"resource_id\", \"resource_type\", \"bind_target\", "
                         "\"programmers\": [{\"task_group\", \"lock_name\", \"evidence\"}]}).")
    ap.add_argument("--connectivity-rows", dest="connectivity_rows_path",
                    help="Path to a JSON array of real connectivity-matrix rows for this SAME "
                         "subsystem, used only to resolve each construct's real hierarchy path.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.sequencer_declarations_path, connectivity_rows_path=a.connectivity_rows_path,
        as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
