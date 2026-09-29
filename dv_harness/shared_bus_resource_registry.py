"""Intra-subsystem shared-bus-resource registry: branch_fw-vs-branch_a*
concurrent-programming race detection over the AMBA M x N arbitration prose
this module operationalizes (`.claude/skills/CORE/branch-mapper/SKILL.md`'s
"AMBA M x N Mapping" section and its Initialization Task Hierarchy item 4;
`.claude/skills/CORE/pattern-architecture/SKILL.md` section 3.1's "two
independent task groups can hold conflicting locks on a shared bus
sequencer" trap class).

WHY THIS IS A DIFFERENT SCOPE FROM THE TWO NEAREST-LOOKING MODULES
-------------------------------------------------------------------
`system_resource_inventory.py` (SYS-9..14) is CROSS-SUBSYSTEM / SoC-level: it
collapses two different ENVIRONMENTS' resource records into one when SYS-11
establishes physical identity, and its DRIVER_CONFLICT is "two subsystems'
VIP agents both drive one interface". `ip_ownership_conflict.py` is
single-subsystem but a different axis again: "is a real VIP agent AND a
legacy hand-written BFM/driver both ACTIVE on the same interface" -- an
IDENTITY/ownership question about WHO drives a port, decided once, not a
question about WHEN two task groups reach the bus.

This module is INTRA-subsystem bus ARBITRATION: within ONE environment's own
generated pattern, `block`'s one-shot global init, each per-port
`branch_a{i}`'s DUT+PHY bring-up (launched non-blocking, per
`pattern-architecture` section 1) and the single shared `branch_fw` service
loop (launched immediately after, specifically so it can respond "while
[a sibling] port's bring-up is still running" -- the same section, same
citation) are all live and able to issue register writes AT THE SAME TIME.
`branch-mapper`'s Initialization Task Hierarchy item 4 states the rule this
operationalizes directly: a `branch_a{i}` touching a resource shared with
other `branch_a*` "需遵循...arbitration policy" from real RTL evidence, never
an assumption; `pattern-architecture` 3.1 gives the concrete failure mode --
two task groups reaching one physical bus sequencer through two DIFFERENT
named locks/semaphores can be interleaved by the arbitration layer in an
order neither author controls, silently overwriting one side's write. Where
those two sections illustrate the DUT-driven-group-vs-VIP-driven-group case
(`block`/`branch_a*` vs `branch_b*`), the identical class of race applies to
`branch_fw` vs `branch_a*`: `branch_fw`'s own per-port event-service loop
frequently must itself write shared registers (e.g. acknowledge/clear an
INTERRUPT_CONTROLLER bit that is genuinely shared across ports) while a
SIBLING port's `branch_a{i}` per-port bring-up is still writing a different
shared resource (a common PHY config block, a shared reset controller, a
shared APB/AXI master's arbitrated slave) -- exactly the concurrency window
`pattern-architecture`'s own USB illustration names ("port 0 can attach and
need a responder while port 1's bring-up is still running").

Neither `system_resource_inventory.py` nor `ip_ownership_conflict.py` models
a NAMED LOCK/semaphore at all, and neither asks whether two TASK GROUPS
within one running pattern can reach one resource concurrently -- both
answer a question about static topology/ownership, not about runtime
task-composition concurrency. That is the gap this module closes, and
nothing else.

EVIDENCE, HONESTLY
-------------------
No producer in this codebase extracts "which named lock a `branch_a{i}` or
`branch_fw` task holds while writing register X" from a real `command.txt`
pattern file or RTL -- there is no SystemVerilog pattern-body parser anywhere
in `dv_harness/` (patterns are agent-authored per `pattern-architecture`'s own
checklist). Per the same honesty this codebase already applies to
`ip_ownership_conflict.py`'s `legacy_bfm_declarations` and
`system_resource_inventory.SubsystemResourceSources.declared_physical_
interfaces`, WHICH task group programs WHICH resource under WHICH named lock
is therefore a CALLER-DECLARED fact (`resource_declarations`), never inferred
or guessed here -- and every declared programmer record REQUIRES a real
`evidence` citation (a pattern file:line, or the RTL/PHY doc line the
branch-mapper/interrupt-event-dispatch sourcing rules already require for any
branch_a/branch_fw content). A declaration with no evidence, or naming a
`task_group` outside the canonical `block`/`branch_a{i}`/`branch_fw`/
`branch_b{i}` vocabulary (per CLAUDE.md's Architecture-conformance audit
rule), is marked invalid and never silently treated as clear -- see
`CONFLICT_UNKNOWN` below. No timing value, interrupt-priority scheme, or
arbitration outcome is invented: this module never claims WHICH branch's
write wins an interleave, only THAT two branches can reach the resource
without a common named lock serializing them.

`connectivity_rows` is an OPTIONAL second input -- real
`connectivity.build_connectivity_matrix()` rows for the SAME subsystem --
used only to attach each declared resource's real `bind_target`/
`dut_instance` hierarchy path when one resolves, exactly the enrichment
`ip_ownership_conflict._vip_active_passive_from_connectivity()` performs the
other direction. Omitting it never invents a hierarchy path.

SCOPE BOUNDARY -- DETECTION ONLY
---------------------------------
This module names a race for a human to resolve (align the two task groups
onto one shared named lock, or serialize them, per real RTL/pattern
evidence). It never picks a winner, never edits a pattern file, never
assigns or invents a lock name, and never touches any approval/governance
mechanism -- the identical boundary `system_resource_inventory.py` and
`ip_ownership_conflict.py` both state for themselves.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import connectivity as conn

# ---------------------------------------------------------------------------
# Report-level vocabulary (NEW, intra-subsystem-bus-arbitration-scoped;
# distinct from SYS-11's relationship classes, `ip_ownership_conflict`'s
# report vocabulary, and `models.Status`)
# ---------------------------------------------------------------------------

STATUS_CONTENTION = "CONTENTION"
STATUS_CLEAR = "CLEAR"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_UNKNOWN = "UNKNOWN"
REPORT_STATUSES: Tuple[str, ...] = (
    STATUS_CONTENTION, STATUS_CLEAR, STATUS_NOT_APPLICABLE, STATUS_UNKNOWN,
)

# ---------------------------------------------------------------------------
# Per-resource-entry conflict_status
# ---------------------------------------------------------------------------

CONFLICT_FW_A_RACE = "FW_A_RACE"
CONFLICT_NONE = "NO_CONFLICT"
CONFLICT_NOT_APPLICABLE = "NOT_APPLICABLE"
CONFLICT_UNKNOWN = "UNKNOWN_INSUFFICIENT_EVIDENCE"
ENTRY_CONFLICT_STATUSES: Tuple[str, ...] = (
    CONFLICT_FW_A_RACE, CONFLICT_NONE, CONFLICT_NOT_APPLICABLE, CONFLICT_UNKNOWN,
)

# ---------------------------------------------------------------------------
# lock_policy -- what the declared programmer set says about arbitration
# discipline on this resource, independent of whether a branch_fw/branch_a
# pair happens to be present at all.
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
# resource_type -- the task's own four named classes, plus an honest
# fallback. Caller-declared, never inferred: this module has no RTL/register
# classifier of its own, and guessing a resource's type from its id would be
# exactly the name-derived guess CLAUDE.md's Architecture-conformance rule
# and SYS-10's own "do not decide by names alone" principle both forbid.
# ---------------------------------------------------------------------------

RT_BUS_MASTER = "APB_AXI_MASTER"
RT_INTERRUPT_CONTROLLER = "INTERRUPT_CONTROLLER"
RT_SHARED_RESET = "SHARED_RESET"
RT_SHARED_PHY_CONFIG = "SHARED_PHY_CONFIG"
RT_UNCLASSIFIED = "UNCLASSIFIED"
RESOURCE_TYPES: Tuple[str, ...] = (
    RT_BUS_MASTER, RT_INTERRUPT_CONTROLLER, RT_SHARED_RESET, RT_SHARED_PHY_CONFIG,
    RT_UNCLASSIFIED,
)

# ---------------------------------------------------------------------------
# Canonical task-group vocabulary, from `branch-mapper`/`pattern-architecture`
# (`block` / `branch_a{i}` / `branch_fw` / `branch_b{i}`, underscore,
# 0-indexed). A declared `task_group` outside this shape is legacy/invalid
# naming per CLAUDE.md's Architecture-conformance audit rule and is never
# silently accepted.
# ---------------------------------------------------------------------------

TG_BLOCK = "BLOCK"
TG_BRANCH_A = "BRANCH_A"
TG_BRANCH_FW = "BRANCH_FW"
TG_BRANCH_B = "BRANCH_B"
TG_INVALID = "INVALID_TASK_GROUP_NAME"

_BRANCH_A_RE = re.compile(r"^branch_a\d+$")
_BRANCH_B_RE = re.compile(r"^branch_b\d+$")


def classify_task_group(task_group: Any) -> str:
    """Classify one declared `task_group` string against the canonical
    `block`/`branch_a{i}`/`branch_fw`/`branch_b{i}` vocabulary. Anything else
    (a legacy non-underscore form, a missing index, camelCase, an empty
    string) is `TG_INVALID` -- never guessed into the nearest-looking family."""
    name = str(task_group or "").strip()
    if name == "block":
        return TG_BLOCK
    if name == "branch_fw":
        return TG_BRANCH_FW
    if _BRANCH_A_RE.match(name):
        return TG_BRANCH_A
    if _BRANCH_B_RE.match(name):
        return TG_BRANCH_B
    return TG_INVALID


class SharedBusResourceRegistryError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = dict(detail or {})


# ===========================================================================
# Programmer normalization
# ===========================================================================

def _normalize_lock_name(raw: Any) -> Optional[str]:
    """A declared lock/semaphore name, or None for "no lock declared". Two
    programmers that BOTH declare no lock are NOT treated as agreeing with
    each other -- neither holds anything that would serialize them, which is
    the worse case, not a safe one -- so `None` never compares equal to
    `None` in `_locks_agree()` below."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _locks_agree(lock_a: Optional[str], lock_b: Optional[str]) -> bool:
    """Two programmers are serialized against each other ONLY when both name
    the SAME real lock. An absent lock on either side never agrees with
    anything, including another absent lock -- see `_normalize_lock_name`."""
    return lock_a is not None and lock_a == lock_b


def normalize_programmers(programmers: Optional[Sequence[Mapping[str, Any]]]
                          ) -> List[Dict[str, Any]]:
    """Normalize one resource's declared `programmers` list. Each output
    record carries the RAW declared `task_group` (`branch_id`, for display),
    its classified `task_group_family`, the normalized `lock_name`, the
    caller-supplied `evidence` citation, and a `valid` flag. `valid` is False
    when the declared task_group is outside the canonical vocabulary OR the
    required evidence citation is empty -- either defect means this specific
    declaration cannot be trusted as a real per-branch access record, and it
    is EXCLUDED from the race comparison rather than silently treated as
    agreeing or conflicting (see `derive_conflict_status()`)."""
    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(programmers or []):
        entry = raw or {}
        task_group = str(entry.get("task_group") or "")
        branch_id = task_group or f"programmers[{i}]"
        family = classify_task_group(task_group)
        evidence = str(entry.get("evidence") or "").strip()
        lock_name = _normalize_lock_name(entry.get("lock_name"))
        invalid_reasons = []
        if family == TG_INVALID:
            invalid_reasons.append(
                f"task_group {task_group!r} is not one of the canonical "
                "block/branch_a{i}/branch_fw/branch_b{i} forms")
        if not evidence:
            invalid_reasons.append(
                "no evidence citation was declared for this programmer record")
        out.append({
            "branch_id": branch_id,
            "task_group_family": family,
            "lock_name": lock_name,
            "evidence": evidence or None,
            "valid": not invalid_reasons,
            "invalid_reasons": invalid_reasons,
        })
    return out


def derive_lock_policy(programmers: Sequence[Mapping[str, Any]]) -> str:
    """SYS-9-style single decision function: one declared programmer set maps
    onto exactly one `lock_policy`. Judged over ALL declared programmers on
    the resource (not only a branch_fw/branch_a subset), because lock
    discipline is a property of the resource's whole access set."""
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
    """The branch_fw-vs-branch_a* race check for ONE resource's normalized
    programmer set.

    Precedence:
      1. Fewer than two DECLARED programmers at all -> NOT_APPLICABLE:
         nothing concurrent to arbitrate.
      2. No programmer is RECOGNIZED as `branch_fw`, or none as `branch_a*`,
         AND no programmer on this resource carries a non-canonical
         (`TG_INVALID`) task_group name either -> NO_CONFLICT. This module's
         detection scope is specifically the branch_fw-vs-branch_a* pair (per
         the module docstring); a resource shared only among several
         `branch_a*` (or only ever touched by `branch_b*`) reports
         NO_CONFLICT here rather than a fabricated verdict about a pairing
         this module was not asked to judge -- `pattern-architecture` 3.1's
         own DUT-vs-VIP-group illustration and branch-mapper's cross-
         `branch_a*` arbitration rule are different, already-documented
         cases.
      2b. One side (`branch_fw` or `branch_a*`) is recognized as genuinely
         ABSENT, but at least one OTHER programmer on this resource carries a
         non-canonical task_group name -> UNKNOWN_INSUFFICIENT_EVIDENCE. A
         name outside the canonical vocabulary is not evidence that a
         `branch_fw`/`branch_a*` role is absent -- it is evidence that this
         specific declaration's role cannot be classified at all, so "no
         such pair" cannot be asserted with confidence. Reporting NO_CONFLICT
         here would let a bare naming defect silently clear a real race.
      3. Every branch_fw or branch_a* declaration that IS recognized is
         invalid (no evidence citation) -> UNKNOWN_INSUFFICIENT_EVIDENCE:
         a pair is NAMED but neither side can be trusted, so this module
         reports its own ignorance rather than guessing CLEAR or CONTENTION.
      4. At least one valid branch_fw/branch_a* pair exists. If EVERY such
         pair shares one real named lock -> NO_CONFLICT (properly
         serialized). If ANY pair does not share a real named lock (either
         side declares none, or the two differ) -> FW_A_RACE, naming every
         non-agreeing pair as a conflicting owner with both branches' real
         evidence citations.
    """
    if len(programmers) < 2:
        return {"conflict_status": CONFLICT_NOT_APPLICABLE, "conflicting_owners": [],
                "reason": "fewer than two programmers were declared on this resource -- "
                          "nothing concurrent to arbitrate"}

    fw_all = [p for p in programmers if p["task_group_family"] == TG_BRANCH_FW]
    a_all = [p for p in programmers if p["task_group_family"] == TG_BRANCH_A]
    unclassifiable = [p for p in programmers if p["task_group_family"] == TG_INVALID]
    if not fw_all or not a_all:
        missing = "branch_fw" if not fw_all else "branch_a*"
        if unclassifiable:
            names = sorted({p["branch_id"] for p in unclassifiable})
            return {"conflict_status": CONFLICT_UNKNOWN, "conflicting_owners": [],
                    "reason": (f"no programmer was RECOGNIZED as {missing} on this resource, "
                               f"but {names} carr{'ies' if len(names) == 1 else 'y'} a "
                               "task_group name outside the canonical block/branch_a{i}/"
                               "branch_fw/branch_b{i} vocabulary -- that is not evidence a "
                               f"{missing} role is absent, only that this declaration's role "
                               "cannot be classified, so 'no such pair' cannot be asserted")}
        return {"conflict_status": CONFLICT_NONE, "conflicting_owners": [],
                "reason": f"no {missing} programmer was declared on this resource -- this "
                          "module's detection scope is specifically a branch_fw-vs-branch_a* "
                          "pair, so there is no such pair here to judge"}

    fw_valid = [p for p in fw_all if p["valid"]]
    a_valid = [p for p in a_all if p["valid"]]
    if not fw_valid or not a_valid:
        invalid = [p for p in (fw_all + a_all) if not p["valid"]]
        return {"conflict_status": CONFLICT_UNKNOWN, "conflicting_owners": [],
                "reason": ("a branch_fw/branch_a* pair is declared on this resource, but every "
                           "declaration on at least one side is invalid ("
                           + "; ".join(f"{p['branch_id']}: {', '.join(p['invalid_reasons'])}"
                                       for p in invalid) + ") -- ownership cannot be judged "
                           "without a trustworthy declaration on both sides")}

    conflicting: List[Dict[str, Any]] = []
    for fw in fw_valid:
        for a in a_valid:
            if not _locks_agree(fw["lock_name"], a["lock_name"]):
                conflicting.append({
                    "fw_branch": fw["branch_id"], "fw_lock": fw["lock_name"] or "NONE_DECLARED",
                    "fw_evidence": fw["evidence"],
                    "a_branch": a["branch_id"], "a_lock": a["lock_name"] or "NONE_DECLARED",
                    "a_evidence": a["evidence"],
                })
    if conflicting:
        return {"conflict_status": CONFLICT_FW_A_RACE, "conflicting_owners": conflicting,
                "reason": (f"{len(conflicting)} branch_fw-vs-branch_a* pair(s) reach this "
                           "resource without a shared real named lock -- the arbitration layer "
                           "between them can interleave their transactions in an order neither "
                           "branch's author controls (pattern-architecture SKILL.md section "
                           "3.1); see 'conflicting_owners' for the real branches and evidence")}
    return {"conflict_status": CONFLICT_NONE, "conflicting_owners": [],
            "reason": (f"every declared branch_fw-vs-branch_a* pair on this resource shares one "
                       "real named lock -- properly serialized")}


# ===========================================================================
# Connectivity enrichment (optional)
# ===========================================================================

def _hierarchy_from_connectivity(bind_target: str,
                                 connectivity_rows: Optional[Sequence[Mapping[str, Any]]],
                                 ) -> Optional[str]:
    """Resolve a declared `bind_target` to a real matrix row's `dut_instance`
    hierarchy path, using the identical bind_target-first match convention
    `ip_ownership_conflict._vip_active_passive_from_connectivity()` already
    applies the other direction. Returns None (never a guess) when no real
    row resolves it or no rows were supplied."""
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

def analyze_shared_bus_resource_registry(
        resource_declarations: Optional[Sequence[Mapping[str, Any]]] = None, *,
        connectivity_rows: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """The intra-subsystem shared-bus-resource registry.

    `resource_declarations`: caller-declared records, one per shared
    resource this SINGLE subsystem's pattern suite genuinely programs from
    more than one task group --
    `[{"resource_id", "resource_type"(optional), "bind_target"(optional),
       "programmers": [{"task_group", "lock_name"(optional), "evidence"}]}]`.
    See the module docstring for why this is honestly caller-declared rather
    than extracted: no pattern-body parser exists in this codebase.
    Empty/omitted -> NOT_APPLICABLE.

    `connectivity_rows`: optional real connectivity-matrix rows for this SAME
    subsystem, used only to attach a resolved hierarchy path (never
    required, never invented when absent).

    Returns a dict with `status` (one of REPORT_STATUSES), `reason`, and
    `entries` -- one per declared resource, each carrying `lock_policy`,
    `conflict_status` and (when `FW_A_RACE`) `conflicting_owners` naming the
    real branch ids and evidence on both sides.
    """
    declarations = list(resource_declarations or [])
    if not declarations:
        return {
            "status": STATUS_NOT_APPLICABLE,
            "reason": "no resource_declarations were supplied -- there is no shared-resource "
                      "programming to check for a branch_fw-vs-branch_a* race",
            "resource_count": 0,
            "entries": [],
        }

    entries: List[Dict[str, Any]] = []
    seen_ids: Dict[str, int] = {}
    for i, raw in enumerate(declarations):
        entry = raw or {}
        resource_id = str(entry.get("resource_id") or "") or f"resource_declarations[{i}]"
        seen_ids[resource_id] = seen_ids.get(resource_id, 0) + 1
        raw_type = str(entry.get("resource_type") or "") or RT_UNCLASSIFIED
        resource_type = raw_type if raw_type in RESOURCE_TYPES else raw_type
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
        raise SharedBusResourceRegistryError("DUPLICATE_RESOURCE_ID", {
            "resource_ids": duplicate_ids,
            "hint": "each shared resource must be declared exactly once; two declarations "
                    "under one resource_id would silently merge two different programmer sets"})

    entries.sort(key=lambda e: e["resource_id"])
    racing = [e for e in entries if e["conflict_status"] == CONFLICT_FW_A_RACE]
    unknown = [e for e in entries if e["conflict_status"] == CONFLICT_UNKNOWN]
    not_applicable = [e for e in entries if e["conflict_status"] == CONFLICT_NOT_APPLICABLE]

    if racing:
        status = STATUS_CONTENTION
        owners = sorted({f"{o['fw_branch']} vs {o['a_branch']}"
                         for e in racing for o in e["conflicting_owners"]})
        reason = (f"{len(racing)} shared resource(s) carry an unlocked or differently-locked "
                  f"branch_fw-vs-branch_a* pair: {owners} -- see 'entries' for full evidence")
    elif unknown:
        status = STATUS_UNKNOWN
        reason = (f"{len(unknown)} shared resource(s) declare a branch_fw/branch_a* pair whose "
                  "ownership cannot be judged -- see 'entries' for the invalid declaration(s)")
    elif len(not_applicable) == len(entries):
        status = STATUS_NOT_APPLICABLE
        reason = (f"all {len(entries)} declared resource(s) have fewer than two programmers -- "
                  "nothing concurrent to arbitrate")
    else:
        status = STATUS_CLEAR
        reason = (f"{len(entries)} declared shared resource(s) checked; no branch_fw-vs-"
                  "branch_a* race found")

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
    """SYS-16/SYS-17-style mandatory table, rendered through the repo's one
    parameterized markdown table renderer (`connectivity.render_markdown_table`)
    rather than a fourth hand-rolled `"| " + " | ".join(...)` loop."""
    columns = [
        ("resource_id", "Resource"), ("resource_type", "Type"),
        ("programmer_count", "Programmers"), ("lock_policy", "Lock Policy"),
        ("conflict_status", "Conflict Status"), ("owners_cell", "Conflicting Owners"),
    ]
    rows = []
    for e in report.get("entries") or []:
        owners = e.get("conflicting_owners") or []
        owners_cell = "; ".join(f"{o['fw_branch']}(lock={o['fw_lock']}) vs "
                                f"{o['a_branch']}(lock={o['a_lock']})" for o in owners) or "-"
        row = dict(e)
        row["owners_cell"] = owners_cell
        rows.append(row)
    return conn.render_markdown_table(columns, rows,
                                      empty_note="(no shared resources declared)")


def format_report(report: Mapping[str, Any]) -> str:
    lines = [f"SHARED BUS RESOURCE REGISTRY (branch_fw vs branch_a* race): {report['status']}",
              ""]
    lines.append(report["reason"])
    lines.append("")
    lines.append(f"  resources declared        : {report.get('resource_count', 0)}")
    lines.append(f"  connectivity rows given   : {report.get('connectivity_rows_supplied', False)}")
    lines.append("")
    lines.append(render_registry_table(report))
    lines.append("")
    lines.append("SCOPE: intra-subsystem bus arbitration, detection only. Different scope from")
    lines.append("system_resource_inventory.py (cross-subsystem SoC-level resource identity) and")
    lines.append("ip_ownership_conflict.py (VIP-vs-legacy-BFM active/active ownership). This")
    lines.append("module never picks a lock, never edits a pattern file, and never invents a")
    lines.append("timing value or arbitration outcome -- a human aligns the conflicting branches")
    lines.append("onto one real named lock, from real RTL/pattern evidence.")
    return "\n".join(lines)


def _load_json(path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def execute_verb(resource_declarations_path=None, *, connectivity_rows_path=None,
                  as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for
    `python -m dv_harness.shared_bus_resource_registry` (no `dv-harness` CLI
    verb was wired -- `cli.py`'s argparse tree was out of scope for this
    task; the ad hoc front door below is the sanctioned fallback the house
    style already uses for `ip_ownership_conflict.py` and several other
    recent modules). Returns (text, exit_code): 0 CLEAR, 1 CONTENTION,
    2 NOT_APPLICABLE or UNKNOWN."""
    declarations = _load_json(resource_declarations_path) if resource_declarations_path else None
    connectivity_rows = (_load_json(connectivity_rows_path) if connectivity_rows_path else None)
    report = analyze_shared_bus_resource_registry(
        declarations, connectivity_rows=connectivity_rows)
    text = json.dumps(report, indent=2) if as_json else format_report(report)
    code = {STATUS_CONTENTION: 1, STATUS_CLEAR: 0,
            STATUS_NOT_APPLICABLE: 2, STATUS_UNKNOWN: 2}[report["status"]]
    return text, code


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.shared_bus_resource_registry",
        description="Intra-subsystem shared-bus-resource registry: does a real branch_fw "
                    "programmer and a real branch_a* programmer reach the same shared resource "
                    "(APB/AXI master, interrupt controller, shared reset, shared PHY config) "
                    "without a common real named lock? Detection only -- never picks a lock.")
    ap.add_argument("--resource-declarations", dest="resource_declarations_path",
                    help="Path to a JSON array of caller-declared shared-resource records "
                         "({\"resource_id\", \"resource_type\", \"bind_target\", "
                         "\"programmers\": [{\"task_group\", \"lock_name\", \"evidence\"}]}).")
    ap.add_argument("--connectivity-rows", dest="connectivity_rows_path",
                    help="Path to a JSON array of real connectivity-matrix rows for this SAME "
                         "subsystem, used only to resolve each resource's real hierarchy path.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(
        a.resource_declarations_path, connectivity_rows_path=a.connectivity_rows_path,
        as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
