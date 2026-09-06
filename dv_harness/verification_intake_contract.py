"""dv_harness/verification_intake_contract.py -- the whole-project
VerificationIntakeContract: one lifecycle state machine over ALL sub-domain
intake data, and one INTAKE_READY conjunction over caller-named critical
conditions.

THE GAP THIS CLOSES
-------------------
This project already has several real per-DOMAIN intake mechanisms --
`env_manifest.py`'s 3-layer manifest, `question_queue.py`'s ask/decide
lifecycle, `connectivity.py`'s bind-tier gate, `requirement_contract.py`'s
per-requirement status, `golden_scenario.py`'s per-test freshness,
`waiver_store.py`'s per-waiver status -- and each answers its own narrow
question well. Nothing sits one level above them and answers the CAPSTONE
question a human actually has to ask before generation or signoff can begin:
"across every domain intake touches, where is THIS PROJECT's intake right
now, and is it actually ready?" A repo-wide grep for
`VerificationIntakeContract`/`INTAKE_READY`/`intake_contract` before writing
this module matched nothing executable anywhere in `dv_harness/`.

Two separate things are missing, and this module is exactly those two things,
nothing more:

  1. A LIFECYCLE STATE MACHINE for the contract AS A WHOLE. Individual
     domains already carry their own local state (a `question_queue` decision
     is OPEN/ANSWERED; a `waiver_store` record is VALID/EXPIRED/...), but
     nothing named the states the WHOLE INTAKE EFFORT itself moves through --
     discovery, correlation across domains, waiting on a human, re-validating
     after an answer, a real disagreement between two domains, sitting ready
     for a human's review, being baselined, and going stale again afterward.
  2. An INTAKE_READY BOOLEAN over an explicit, caller-supplied list of named
     critical conditions, combined with NO AVERAGING -- the same worst-wins
     discipline `golden_flow_readiness.combine_readiness()` already applies
     one row at a time ("BLOCKED is worse than UNKNOWN on purpose... must not
     be averaged away"), generalized here to an arbitrary, caller-declared
     set of conditions rather than this module's own fixed twenty rows.

REUSE, NOT REINVENTION -- AND WHY THIS FILE IMPORTS NOTHING ELSE IN THIS BATCH
-------------------------------------------------------------------------------
This is the CAPSTONE task of a batch in which many sibling modules
(`intake_state.py`, `requirement_contract.py`, `golden_scenario.py`,
`waiver_store.py`, `vip_learning_gate.py`, and others) are being built or
extended concurrently, several of which are on this batch's own "never touch"
list. Per this task's explicit scope, this module NEVER imports any of them
-- not `intake_state.py`, not `question_queue.py`, not `env_manifest.py`, not
any other module this batch is building or forbids editing. Every sub-domain
fact this module would otherwise read is instead accepted as a plain,
duck-typed parameter: a dict, a list of dicts, or a list of condition records
-- the exact shape a caller who HAS run one of those real modules would
already be holding, handed in rather than fetched. This module never
re-derives what a real per-domain module already decided; it only assembles
and sequences what the caller supplies. Where this project's own precedent
for "reuse a discipline, not a specific function" applies -- the worst-wins,
no-averaging rule -- it is followed exactly, because that rule is a design
principle stated in prose (`golden_flow_readiness.py`'s own module docstring:
"BLOCKED is worse than UNKNOWN on purpose"), not a function this module could
import without also importing that module's twenty hardcoded rows, which
would be the wrong reuse for a capstone that must not hardcode which
conditions exist.

THE LIFECYCLE, AND WHY EVERY STATE HAS A REAL WAY OUT
-------------------------------------------------------
Thirteen states, in the order the task names them:
`CREATED -> DISCOVERING -> CORRELATING -> QUESTION_PENDING ->
USER_INPUT_RECEIVED -> VALIDATING -> CONFLICT -> PARTIAL -> BLOCKED ->
READY_FOR_REVIEW -> BASELINED -> STALE -> REVALIDATING`. That ordering names
the states, not a single straight-line path: real intake loops back
constantly (a validation finding a CONFLICT sends the contract back to ask a
human or re-correlate; a PARTIAL result sends it back to discover more; a
human reviewing a READY_FOR_REVIEW contract can send it to any earlier stage
rather than only forward to BASELINED). `TRANSITIONS` is the actual legal
edge set below, and `assert_legal_transition()` is enforced on every state
change this module makes -- an illegal jump (e.g. `CREATED` straight to
`VALIDATING`, skipping discovery and correlation entirely) is refused with
the caller's own attempted edge and the real legal next states named, never
silently allowed or silently corrected.

**`READY_FOR_REVIEW` is explicitly NON-TERMINAL, per this task's own
instruction, and it is enforced as an ordinary consequence of the transition
table rather than as a special case: it carries FIVE outgoing edges (three of
them back to earlier work -- `DISCOVERING`, `CORRELATING`, `VALIDATING` --
plus `QUESTION_PENDING` for a fresh question a human raises while reviewing,
plus `BASELINED` for approval).** A human sending a reviewed contract back to
`CORRELATING` is exactly as legal a move as approving it forward to
`BASELINED`; nothing in this module treats "reached READY_FOR_REVIEW" as
"done".

Generalizing that same idea rather than special-casing only the one state the
task names: `assert_no_absorbing_state()` checks at import time that EVERY
state in this machine has at least one real outgoing edge -- there is no
state a contract can enter and never leave through this module's own
transition function. Even `BASELINED` (the closest thing to a finished state)
has a real edge to `STALE`, because a baselined contract can be invalidated by
a later spec/RTL/config change exactly the way `signoff_export.py`'s frozen
baseline can (that module's own `evaluate_freeze_invalidation()` is the real
mechanism a caller would run to DECIDE whether a baselined contract has gone
stale; this module does not re-implement that decision, it only accepts the
caller's resulting STALE transition once made).

INTAKE_READY: A CONJUNCTION, NEVER AN AVERAGE
-----------------------------------------------
The task is explicit that the set of critical conditions is NOT hardcoded
here -- other, still-building modules in this batch (env manifest layers,
requirement contract completeness, connectivity bind-tier clearance, golden
scenario freshness, waiver validity, VIP API provability, and others not yet
built at all) each produce their own real verdict, and a caller assembles
whichever of those apply to this project into one flat list of
`{"name", "status"}` records and hands it to `evaluate_intake_readiness()`.
Four statuses, borrowed rather than re-invented where a borrow was available:
`MET` (this condition is satisfied), `NOT_APPLICABLE` (a caller-declared "this
condition does not apply to this project" -- never inferred from silence,
the same discipline `intake_state.py`'s own `NOT_APPLICABLE` status states in
its own docstring: "nothing in this module infers it automatically"),
`UNMET` (checked, and it failed), `UNKNOWN` (checked, and it could not be
resolved). `MET` and `NOT_APPLICABLE` are the only two CLEAR statuses;
`UNMET` and `UNKNOWN` both BLOCK, deliberately treated identically here --
"we know this failed" and "we do not know" are both reasons a human must not
be told the project is ready. `INTAKE_READY` is `True` if and only if the
`blocking` list is empty: not an average, not a majority, not a weighted
score -- one single blocking condition among a hundred clean ones still reads
`False`, and the report names that one condition rather than a percentage.
An empty condition list is never silently `True` (nothing was measured, so
nothing can be reported ready) and reports `NOT_AVAILABLE` instead of
`READY`/`NOT_READY`, the same "an empty input is UNKNOWN, never READY" rule
`golden_flow_readiness.combine_readiness()` already states for its own fold.

WHAT THIS MODULE DOES NOT DO
------------------------------
It runs no stage, invokes no gate script, submits no build/regression/LSF
job, and writes no approval or governance record -- `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()` and the PR-only
main/master governance are untouched and unreferenced (asserted against this
module's own source by a test). It also does not decide what a CONFLICT
between two domains actually means or which side wins -- exactly like
`requirement_contract.py`'s own boundary ("ARBITRATION IS NOT HERE"), a
`CONFLICT` state is a real, honestly-reported STOP, not something this module
resolves. It persists nothing to disk on its own: `VerificationIntakeContract`
is a plain in-memory record a caller may serialize however their own project
convention calls for; this module mints no `.dv-harness/` state of its own.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field as _dc_field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = "1.0"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class IntakeContractError(ValueError):
    """Raised for an illegal state transition, an unrecognized state or
    condition status, or a malformed condition record. Carries `reason` (a
    short machine-checkable token) and `detail` (a dict naming exactly what
    was wrong), the same convention `GoldenFlowReadinessError` and
    `IntakeFieldRecord`'s own validation already use in this codebase."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Lifecycle vocabulary
# ===========================================================================

class IntakeContractState(str, Enum):
    CREATED = "CREATED"
    DISCOVERING = "DISCOVERING"
    CORRELATING = "CORRELATING"
    QUESTION_PENDING = "QUESTION_PENDING"
    USER_INPUT_RECEIVED = "USER_INPUT_RECEIVED"
    VALIDATING = "VALIDATING"
    CONFLICT = "CONFLICT"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    BASELINED = "BASELINED"
    STALE = "STALE"
    REVALIDATING = "REVALIDATING"


#: The exact 13 states, in the order the task itself names them -- transcribed
#: once so `_assert_states_match_task_order()` can compare the enum against
#: this list rather than against itself, the same "compare against the
#: specification's own list" discipline `golden_flow_readiness.py`'s
#: `SECTION_47_ROW_LABELS` already applies to its twenty rows.
TASK_ORDERED_STATES: Tuple[str, ...] = (
    "CREATED", "DISCOVERING", "CORRELATING", "QUESTION_PENDING",
    "USER_INPUT_RECEIVED", "VALIDATING", "CONFLICT", "PARTIAL", "BLOCKED",
    "READY_FOR_REVIEW", "BASELINED", "STALE", "REVALIDATING",
)

#: The legal transition graph: state -> the real, allowed next states.
#: Total over `IntakeContractState` (every state is a key), asserted below.
#: Every value is non-empty (`assert_no_absorbing_state()`), so no state is a
#: dead end a contract can enter and never leave through this module's own
#: transition function -- generalizing "READY_FOR_REVIEW is non-terminal" to
#: the whole machine rather than special-casing only that one state.
TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    IntakeContractState.CREATED.value: (
        IntakeContractState.DISCOVERING.value,
    ),
    IntakeContractState.DISCOVERING.value: (
        IntakeContractState.CORRELATING.value,
        IntakeContractState.QUESTION_PENDING.value,
    ),
    IntakeContractState.CORRELATING.value: (
        IntakeContractState.QUESTION_PENDING.value,
        IntakeContractState.VALIDATING.value,
        IntakeContractState.DISCOVERING.value,
    ),
    IntakeContractState.QUESTION_PENDING.value: (
        IntakeContractState.USER_INPUT_RECEIVED.value,
    ),
    IntakeContractState.USER_INPUT_RECEIVED.value: (
        IntakeContractState.CORRELATING.value,
        IntakeContractState.VALIDATING.value,
    ),
    IntakeContractState.VALIDATING.value: (
        IntakeContractState.CONFLICT.value,
        IntakeContractState.PARTIAL.value,
        IntakeContractState.BLOCKED.value,
        IntakeContractState.READY_FOR_REVIEW.value,
    ),
    IntakeContractState.CONFLICT.value: (
        IntakeContractState.QUESTION_PENDING.value,
        IntakeContractState.CORRELATING.value,
    ),
    IntakeContractState.PARTIAL.value: (
        IntakeContractState.DISCOVERING.value,
        IntakeContractState.QUESTION_PENDING.value,
        IntakeContractState.VALIDATING.value,
    ),
    IntakeContractState.BLOCKED.value: (
        IntakeContractState.QUESTION_PENDING.value,
        IntakeContractState.DISCOVERING.value,
    ),
    IntakeContractState.READY_FOR_REVIEW.value: (
        # Non-terminal, per this task's own explicit instruction: a human may
        # approve forward to BASELINED, or send the contract back to any of
        # three earlier stages, or raise a fresh question.
        IntakeContractState.BASELINED.value,
        IntakeContractState.DISCOVERING.value,
        IntakeContractState.CORRELATING.value,
        IntakeContractState.VALIDATING.value,
        IntakeContractState.QUESTION_PENDING.value,
    ),
    IntakeContractState.BASELINED.value: (
        IntakeContractState.STALE.value,
    ),
    IntakeContractState.STALE.value: (
        IntakeContractState.REVALIDATING.value,
    ),
    IntakeContractState.REVALIDATING.value: (
        IntakeContractState.VALIDATING.value,
        IntakeContractState.BASELINED.value,
        IntakeContractState.READY_FOR_REVIEW.value,
    ),
}


def _assert_states_match_task_order() -> None:
    declared = tuple(s.value for s in IntakeContractState)
    if declared != TASK_ORDERED_STATES:
        raise IntakeContractError("STATE_SET_CHANGED", {
            "declared": list(declared), "task_specified": list(TASK_ORDERED_STATES),
            "missing": [s for s in TASK_ORDERED_STATES if s not in declared],
            "unexpected": [s for s in declared if s not in TASK_ORDERED_STATES]})


def assert_transition_table_total() -> None:
    """Import-time guard: every `IntakeContractState` member is a key in
    `TRANSITIONS`, and every state named as a target is itself a real member.
    Without this, a state added later would have no legal outgoing edge at
    all and every transition into or out of it would silently look like a
    caller mistake rather than a real gap in this table."""
    known = {s.value for s in IntakeContractState}
    missing_keys = sorted(known - set(TRANSITIONS))
    if missing_keys:
        raise IntakeContractError("TRANSITION_TABLE_INCOMPLETE", {
            "states_with_no_row": missing_keys})
    unknown_keys = sorted(set(TRANSITIONS) - known)
    if unknown_keys:
        raise IntakeContractError("TRANSITION_TABLE_HAS_UNKNOWN_STATE", {
            "unknown_states": unknown_keys})
    bad_targets: Dict[str, List[str]] = {}
    for state, targets in TRANSITIONS.items():
        bad = [t for t in targets if t not in known]
        if bad:
            bad_targets[state] = bad
    if bad_targets:
        raise IntakeContractError("TRANSITION_TABLE_TARGETS_UNKNOWN_STATE", {
            "bad_targets": bad_targets})


def assert_no_absorbing_state() -> None:
    """Import-time guard: every state has at least one real outgoing edge.
    Generalizes "READY_FOR_REVIEW is non-terminal" -- checked against the
    whole table rather than trusted for one state alone."""
    dead_ends = [s for s, targets in TRANSITIONS.items() if not targets]
    if dead_ends:
        raise IntakeContractError("ABSORBING_STATE_FOUND", {"states": dead_ends})


_assert_states_match_task_order()
assert_transition_table_total()
assert_no_absorbing_state()


def legal_next_states(state: str) -> Tuple[str, ...]:
    """The real legal next states for `state`. Raises on an unrecognized
    state rather than returning an empty tuple, which would read as a
    (nonexistent) absorbing state."""
    if state not in TRANSITIONS:
        raise IntakeContractError("UNKNOWN_INTAKE_CONTRACT_STATE", {
            "state": state, "known_states": sorted(TRANSITIONS)})
    return TRANSITIONS[state]


def assert_legal_transition(from_state: str, to_state: str) -> None:
    """Raises `IntakeContractError("ILLEGAL_STATE_TRANSITION", ...)` unless
    `to_state` is a real, declared legal next state of `from_state`. This is
    the enforcement point every state change in this module goes through --
    there is no other code path that changes a contract's `state`."""
    legal = legal_next_states(from_state)
    if to_state not in TRANSITIONS:
        raise IntakeContractError("UNKNOWN_INTAKE_CONTRACT_STATE", {
            "state": to_state, "known_states": sorted(TRANSITIONS)})
    if to_state not in legal:
        raise IntakeContractError("ILLEGAL_STATE_TRANSITION", {
            "from": from_state, "to": to_state, "legal_next_states": list(legal)})


# ===========================================================================
# The contract itself
# ===========================================================================

@dataclass
class VerificationIntakeContract:
    """One project's whole-intake record: its current lifecycle state, the
    full history of how it got there, and a bucket of sub-domain intake data
    this module never interprets -- each entry is whatever shape that real
    domain module produces, handed in by the caller and stored verbatim.

    `sub_domains` is intentionally a flat `Dict[str, Any]`: this module does
    not know, and per its own scope must not assume, which domains exist or
    what shape any one of them takes -- see the module docstring's "REUSE,
    NOT REINVENTION" section for why."""
    contract_id: str
    state: str
    sub_domains: Dict[str, Any] = _dc_field(default_factory=dict)
    state_history: List[Dict[str, Any]] = _dc_field(default_factory=list)
    created_at: str = _dc_field(default_factory=_utcnow_iso)
    updated_at: str = _dc_field(default_factory=_utcnow_iso)

    def __post_init__(self) -> None:
        if self.state not in TRANSITIONS:
            raise IntakeContractError("UNKNOWN_INTAKE_CONTRACT_STATE", {
                "state": self.state, "known_states": sorted(TRANSITIONS)})

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "contract_id": self.contract_id,
            "state": self.state,
            "sub_domains": self.sub_domains,
            "state_history": self.state_history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def create_contract(
    contract_id: str,
    *,
    sub_domain_data: Optional[Mapping[str, Any]] = None,
    now: Optional[str] = None,
) -> VerificationIntakeContract:
    """A fresh contract at `CREATED`, optionally seeded with whatever
    sub-domain data a caller already has on hand (e.g. an already-generated
    `env.manifest.json` dict, an already-computed list of question_queue
    decisions) -- accepted and stored as-is, never inspected for shape."""
    if not contract_id or not str(contract_id).strip():
        raise IntakeContractError("EMPTY_CONTRACT_ID", {})
    ts = now or _utcnow_iso()
    return VerificationIntakeContract(
        contract_id=str(contract_id),
        state=IntakeContractState.CREATED.value,
        sub_domains=dict(sub_domain_data or {}),
        state_history=[{
            "from": None, "to": IntakeContractState.CREATED.value,
            "reason": "contract created", "by": None, "at": ts,
        }],
        created_at=ts, updated_at=ts,
    )


def transition_contract(
    contract: VerificationIntakeContract,
    to_state: str,
    *,
    reason: str,
    by: Optional[str] = None,
    now: Optional[str] = None,
    sub_domain_data: Optional[Mapping[str, Any]] = None,
    require_intake_ready: bool = False,
    readiness: "Optional[IntakeReadinessResult]" = None,
) -> VerificationIntakeContract:
    """Returns a NEW `VerificationIntakeContract` moved to `to_state`, never
    mutating the one passed in (the same `dataclasses.replace`-style
    immutability `intake_state.py`'s own decision overlay already uses in
    this codebase). Raises `IntakeContractError("ILLEGAL_STATE_TRANSITION",
    ...)` for any edge not in `TRANSITIONS`, and never silently allows or
    silently substitutes a different legal state.

    `sub_domain_data`, if supplied, is MERGED into the existing `sub_domains`
    bucket (new keys added, existing keys overwritten) -- the ordinary way a
    later step of intake would attach a newly-available domain's data (e.g.
    a question_queue decision that just arrived) without discarding earlier
    domains' data.

    `require_intake_ready` is the disclosed-default opt-in this project's
    style already uses elsewhere (`require_tier`, `require_phy_boundary`,
    `enforce_do_not_ask`): when True and `to_state` is `READY_FOR_REVIEW`,
    the caller MUST also pass a `readiness` result (from
    `evaluate_intake_readiness()`) whose `.ready` is True, or the transition
    is refused with `INTAKE_NOT_READY_FOR_REVIEW`. Default False keeps every
    existing caller's behavior unchanged: a caller not yet using the
    INTAKE_READY conjunction can still drive the state machine on its own."""
    assert_legal_transition(contract.state, to_state)
    if (require_intake_ready and to_state == IntakeContractState.READY_FOR_REVIEW.value):
        if readiness is None or not getattr(readiness, "ready", False):
            raise IntakeContractError("INTAKE_NOT_READY_FOR_REVIEW", {
                "readiness": readiness.to_dict() if readiness is not None else None,
                "hint": "evaluate_intake_readiness() must report ready=True before a "
                        "contract may enter READY_FOR_REVIEW under require_intake_ready",
            })
    ts = now or _utcnow_iso()
    merged = dict(contract.sub_domains)
    if sub_domain_data:
        merged.update(sub_domain_data)
    new_history = list(contract.state_history) + [{
        "from": contract.state, "to": to_state, "reason": reason, "by": by, "at": ts,
    }]
    return dataclasses.replace(
        contract, state=to_state, sub_domains=merged, state_history=new_history,
        updated_at=ts,
    )


# ===========================================================================
# INTAKE_READY: a conjunction of named critical conditions, no averaging
# ===========================================================================

#: Four statuses a caller-declared condition may carry. `MET`/`NOT_APPLICABLE`
#: are the only CLEAR values; `UNMET`/`UNKNOWN` both BLOCK, deliberately
#: undistinguished by this module -- "this failed" and "we could not tell"
#: are both reasons a human must not be told the project is ready.
CONDITION_STATUSES: frozenset = frozenset({"MET", "UNMET", "UNKNOWN", "NOT_APPLICABLE"})
CLEAR_CONDITION_STATUSES: frozenset = frozenset({"MET", "NOT_APPLICABLE"})
BLOCKING_CONDITION_STATUSES: frozenset = frozenset({"UNMET", "UNKNOWN"})

#: `evaluate_intake_readiness()`'s own report status -- deliberately a
#: DIFFERENT, non-overlapping vocabulary from `CONDITION_STATUSES` (a
#: condition's own per-item status) and from `IntakeContractState` (the
#: contract's lifecycle state), so neither can be confused with the other.
READY = "READY"
NOT_READY = "NOT_READY"
NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass
class IntakeReadinessResult:
    ready: bool
    status: str
    evaluated_count: int
    blocking: List[Dict[str, Any]]
    clear: List[Dict[str, Any]]
    checked_at: str

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "status": self.status,
            "evaluated_count": self.evaluated_count,
            "blocking": self.blocking,
            "clear": self.clear,
            "checked_at": self.checked_at,
        }


def evaluate_intake_readiness(
    conditions: Optional[Sequence[Mapping[str, Any]]],
    *,
    now: Optional[str] = None,
) -> IntakeReadinessResult:
    """The INTAKE_READY conjunction. `conditions` is a caller-assembled,
    caller-named list -- this module hardcodes NONE of them, since which
    critical conditions exist depends on which sub-domain modules a given
    project actually has wired (env manifest completeness, requirement
    contract completeness, connectivity bind-tier clearance, golden scenario
    freshness, waiver validity, VIP API provability, and others not yet
    built). Each entry is `{"name": <str>, "status": <one of
    CONDITION_STATUSES>, "reason": <str, optional>}`.

    NO AVERAGING: `ready` is `True` only when `blocking` is empty. One single
    `UNMET`/`UNKNOWN` condition among any number of clean ones makes `ready`
    `False` and is named in `blocking` -- never diluted into a percentage or
    a majority vote. This is the same worst-wins discipline
    `golden_flow_readiness.combine_readiness()` already applies one row at a
    time, generalized here over an open-ended, caller-declared condition set
    rather than a fixed twenty rows.

    An absent or empty `conditions` list reports `NOT_AVAILABLE` (nothing was
    measured) with `ready=False` -- never a vacuous `READY` over zero
    conditions, the same "an empty input is UNKNOWN, never READY" rule
    `combine_readiness()` already states for its own fold. A condition
    carrying an unrecognized `status`, a missing `name`/`status` key, or a
    `name` repeated by an earlier condition in the same list all raise
    `IntakeContractError` rather than being silently dropped or silently
    resolved by picking one -- an ambiguous input must read as an error, per
    the Evidence Truth Rule, never as a confident guess about which of two
    same-named conditions is the real one."""
    ts = now or _utcnow_iso()
    if not conditions:
        return IntakeReadinessResult(
            ready=False, status=NOT_AVAILABLE, evaluated_count=0,
            blocking=[], clear=[], checked_at=ts)

    seen_names: set = set()
    normalized: List[Dict[str, Any]] = []
    for i, c in enumerate(conditions):
        if not isinstance(c, Mapping) or "name" not in c or "status" not in c:
            raise IntakeContractError("MALFORMED_CONDITION_RECORD", {
                "index": i, "record": dict(c) if isinstance(c, Mapping) else c,
                "hint": "each condition needs both a 'name' and a 'status' key"})
        name = c["name"]
        status = c["status"]
        if status not in CONDITION_STATUSES:
            raise IntakeContractError("UNKNOWN_CONDITION_STATUS", {
                "name": name, "status": status, "known_statuses": sorted(CONDITION_STATUSES)})
        if name in seen_names:
            raise IntakeContractError("DUPLICATE_CONDITION_NAME", {
                "name": name,
                "hint": "two conditions sharing one name could silently hide whichever one "
                        "actually blocks readiness -- name each critical condition once"})
        seen_names.add(name)
        normalized.append({
            "name": name, "status": status, "reason": c.get("reason", ""),
        })

    blocking = [c for c in normalized if c["status"] in BLOCKING_CONDITION_STATUSES]
    clear = [c for c in normalized if c["status"] in CLEAR_CONDITION_STATUSES]
    ready = not blocking
    return IntakeReadinessResult(
        ready=ready, status=(READY if ready else NOT_READY),
        evaluated_count=len(normalized), blocking=blocking, clear=clear, checked_at=ts)


# ===========================================================================
# Ad hoc front door -- no `dv-harness` CLI verb per this task's own scope
# (`cli.py` is on this batch's never-touch list; `python -m` is the
# sanctioned fallback several sibling modules in this same house style use).
# ===========================================================================

def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_readiness_report(result: IntakeReadinessResult) -> str:
    lines = [f"INTAKE_READY: {result.status} (evaluated {result.evaluated_count} condition(s))"]
    if result.blocking:
        lines.append("Blocking:")
        for c in result.blocking:
            reason = f" -- {c['reason']}" if c.get("reason") else ""
            lines.append(f"  - {c['name']}: {c['status']}{reason}")
    if result.clear:
        lines.append(f"Clear: {', '.join(c['name'] for c in result.clear)}")
    return "\n".join(lines)


def execute_verb(verb: str, *, conditions_path: Optional[str] = None,
                  state: Optional[str] = None, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `python -m dv_harness.verification_intake_contract`.
    Returns (text, exit_code): 0 clean/ready, 1 not ready / a real finding,
    2 nothing to report or a usage error."""
    if verb == "states":
        text = (json.dumps(list(TASK_ORDERED_STATES), indent=2) if as_json
                else "\n".join(TASK_ORDERED_STATES))
        return text, 0
    if verb == "transitions":
        if not state:
            return "transitions requires --state", 2
        try:
            legal = legal_next_states(state)
        except IntakeContractError as e:
            return f"{e.reason}: {json.dumps(e.detail)}", 2
        text = json.dumps(list(legal), indent=2) if as_json else "\n".join(legal)
        return text, 0
    if verb == "evaluate":
        if not conditions_path:
            return "evaluate requires --conditions", 2
        try:
            conditions = _load_json(conditions_path)
            result = evaluate_intake_readiness(conditions)
        except IntakeContractError as e:
            return f"{e.reason}: {json.dumps(e.detail)}", 2
        text = json.dumps(result.to_dict(), indent=2) if as_json else format_readiness_report(result)
        code = {READY: 0, NOT_READY: 1, NOT_AVAILABLE: 2}[result.status]
        return text, code
    return f"unknown verb: {verb!r} (expected states|transitions|evaluate)", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.verification_intake_contract",
        description="The whole-project VerificationIntakeContract lifecycle and the "
                    "INTAKE_READY conjunction over caller-named critical conditions.")
    ap.add_argument("verb", choices=("states", "transitions", "evaluate"))
    ap.add_argument("--state", help="For 'transitions': the current state to list legal "
                                     "next states for.")
    ap.add_argument("--conditions", dest="conditions_path",
                    help="For 'evaluate': path to a JSON list of "
                         "{\"name\", \"status\", \"reason\"} condition records.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable form.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, conditions_path=a.conditions_path, state=a.state,
                              as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
