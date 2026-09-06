"""dv_harness/pattern_runtime_state_machine.py -- the per-PATTERN execution
state machine: CREATED -> PARSED -> VALIDATED -> READY -> RUNNING -> WAITING ->
CHECKING -> PASS/FAIL/TIMEOUT/BLOCKED/CANCELLED, with legal-transition
enforcement (an illegal jump, e.g. CREATED straight to PASS, is refused).

WHAT "A PATTERN'S RUNTIME EXECUTION" MEANS HERE
------------------------------------------------
This tracks ONE `command.txt`/pattern file's own execution lifecycle, at the
granularity `.claude/skills/CORE/pattern-architecture/SKILL.md` describes:
`block` -> `branch_a*` (per-port DUT+PHY bring-up) -> `branch_fw` (per-port FW
service loop) -> fork/join of `branch_b*` (VIP-driven test bodies) ->
verdict/FINAL_CHECK. CREATED/PARSED/VALIDATED/READY are the file's pre-run
states (a `command.txt` on disk, parsed into that four-layer task
composition, structurally validated against it, and staged for dispatch);
RUNNING/WAITING/CHECKING are the in-flight states (the pattern's tasks
executing, a branch_b* fork waiting on its own `join` -- never `join_any`,
per that skill's section 2 -- and the FINAL_CHECK verdict step itself); the
five terminal states are this ONE pattern's own outcome.

WHY THIS IS A DELIBERATELY DISTINCT VOCABULARY FROM `loop_contract.LoopState`,
WITH NO BRIDGE
------------------------------------------------------------------------------
`loop_contract.py` already states its own reason for a SEPARATE enum rather
than extending `models.Status`: two vocabularies answering different
questions must not be merged into one that answers neither honestly.  The
same reasoning applies here one more time, in the OTHER direction from
`LoopState`, and this module deliberately does NOT build a
`STATUS_TO_LOOP_STATE`-style bridge to it:

  * GRANULARITY. `LoopState` answers "where is this LOOP -- the whole
    verification-CLOSURE process across possibly many stages, many patterns,
    many regression cycles -- as a control process, right now" (CREATED /
    READY / RUNNING / VERIFYING / CONVERGING / PLATEAU / OSCILLATING / ... /
    SUCCESS / FAILED / BUDGET_EXHAUSTED / STOPPED / CANCELLED / RESUMING /
    STALE). `PatternRuntimeState` answers "where is THIS ONE PATTERN's OWN
    execution, right now" -- a question meaningful many times *within* a
    single loop iteration (a run can dispatch, wait on, and check dozens of
    patterns before the loop itself reaches VERIFYING once). A pattern
    reaching PASS says nothing about whether the surrounding loop has
    CONVERGED, PLATEAUed, or is about to retry with a materially different
    strategy -- those are the loop's own questions, answered by
    `loop_convergence.py`, not by this module.
  * NO SHARED MEMBER NAMES A SHARED CONCEPT. `PASS`/`FAIL` here are this
    pattern's own concrete FINAL_CHECK/scoreboard verdict, evidence-derived
    from a REAL sim.log (see `derive_observed_terminal_verdict()` below) --
    `LoopState` has no member spelled PASS or FAIL at all (a loop's own
    "done" is SUCCESS/FAILED, deliberately different words, precisely so the
    two questions are never conflated by name). `TIMEOUT` here is a real,
    per-dispatch simulation/job timeout (see `sim_log_analysis`'s own
    `timeout` marker category); `LoopState` has no timeout concept at all --
    `BUDGET_EXHAUSTED` is the nearest loop-level idea and it answers a
    different question (a RETRY budget across many stage attempts, not one
    pattern's own execution hanging).
  * FORCING A MAPPING WOULD MISREPRESENT ONE AS THE OTHER. A bridge table
    requires every member on each side to mean something in terms of the
    other. It does not: nothing about `LoopState.PLATEAU` (a coverage-curve
    property observed across many RUNS) is expressible as any one pattern's
    own execution phase, and nothing about `PatternRuntimeState.WAITING` (one
    pattern's own branch_b* fork sitting on its own `join`) says anything
    about the surrounding loop's state. Per this batch's own instruction:
    build no such bridge here -- these are different concepts at different
    granularity, and a forced mapping would misrepresent one as the other,
    exactly as `loop_contract.py`'s own module docstring warns against for
    `Status` vs. `LoopState`.

WHY THIS IS ALSO A DELIBERATELY DISTINCT, MORE-GRANULAR VOCABULARY FROM
`sim_log_analysis`'s TRIAGE CATEGORIES AND `loop_budget.FailureType`
------------------------------------------------------------------------
`sim_log_analysis.TRIAGE_CATEGORIES` (uvm_fatal/uvm_error/bare_error/
assertion/timeout/scoreboard_mismatch/other) and `loop_budget.FailureType`
classify WHY a dispatch failed, for a retry-vs-stop decision at the LOOP's
own retry-budget granularity -- one classification per stage-attempt.  This
module's states are WHEN, in ONE pattern's OWN lifecycle, execution
currently sits -- a strictly finer-grained, orthogonal axis (a pattern
mid-RUNNING has not failed at all yet; a pattern that reaches FAIL still
needs `sim_log_analysis`'s own category to say *why*). This module therefore
REUSES `sim_log_analysis.parse_epilogue()`/`classify_signatures()` as its
sole evidence reader for terminal-verdict observation (see
`derive_observed_terminal_verdict()`) rather than re-scanning a log with a
second marker vocabulary, and it never imports or extends
`loop_budget.FailureType` -- that taxonomy stays the loop's own retry
classification, untouched and unmerged, exactly as this batch's own
instruction requires.

EVIDENCE TRUTH RULE, APPLIED HERE
----------------------------------
No function in this module ever DEFAULTS an unresolved observation to PASS.
`derive_observed_terminal_verdict()` reads a real sim.log through the real,
existing `sim_log_analysis` parser and reports exactly what THAT log's own
evidence supports: a real FINAL CHECK epilogue's own `VERDICT:` line (this
project's own documented FINAL_CHECK convention) when present; failing that,
a real fatal/error marker (real evidence the run did not pass, whether or
not it ever reached its own verdict block) or a real timeout/deadlock
marker; and, when a log carries NONE of the above -- ends cleanly, with zero
errors, and never states its own verdict -- that is reported as a named
`SILENT_FAILURE_SUSPECTED`, never silently read as PASS. That is precisely
`pattern-architecture/SKILL.md` section 2's own documented `join`-vs-
`join_any` trap ("the run ends cleanly, with zero errors, because nothing
had a chance to fail yet") read back as a runtime-state observation instead
of a fork/join code review finding.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple, Union

from . import sim_log_analysis
from .connectivity import render_markdown_table
from .control_plane import now as _control_plane_now
from .storage import _atomic_replace


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------
class PatternRuntimeState(str, Enum):
    """One pattern's own execution lifecycle. See module docstring for why
    this is a deliberately separate vocabulary from `loop_contract.LoopState`
    (different granularity, no bridge) and from `sim_log_analysis`'s triage
    categories / `loop_budget.FailureType` (different axis: WHEN vs. WHY,
    no merge)."""
    CREATED = "CREATED"
    PARSED = "PARSED"
    VALIDATED = "VALIDATED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    CHECKING = "CHECKING"
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


#: Display/documentation order for the pre-terminal "happy path" backbone
#: only. NEVER used to decide legality -- `LEGAL_TRANSITIONS` below is the
#: sole source of truth for that, exactly the caution `loop_contract.py`
#: applies to its own `TERMINAL_LOOP_STATES` tuple.
PROGRESSION_ORDER: Tuple[PatternRuntimeState, ...] = (
    PatternRuntimeState.CREATED,
    PatternRuntimeState.PARSED,
    PatternRuntimeState.VALIDATED,
    PatternRuntimeState.READY,
    PatternRuntimeState.RUNNING,
    PatternRuntimeState.WAITING,
    PatternRuntimeState.CHECKING,
)

#: States from which no further transition is legal -- this ONE pattern's
#: own outcome is settled. Unlike `loop_contract.RESUMABLE_LOOP_STATES`,
#: there is no resumable terminal state here: a pattern that reached
#: BLOCKED or CANCELLED is re-run as a fresh pattern execution (a new
#: record), not resumed in place, because a pattern's own runtime state --
#: unlike a persistent loop session -- carries no partial progress worth
#: preserving across a restart.
TERMINAL_STATES: FrozenSet[PatternRuntimeState] = frozenset({
    PatternRuntimeState.PASS,
    PatternRuntimeState.FAIL,
    PatternRuntimeState.TIMEOUT,
    PatternRuntimeState.BLOCKED,
    PatternRuntimeState.CANCELLED,
})

#: The complete, TOTAL legal-transition table. Every `PatternRuntimeState`
#: member is a key (checked by `_assert_transitions_total()` below at import,
#: the same defensive-totality technique `loop_contract.
#: assert_status_mapping_total()` uses -- a future added member with no
#: decided edges fails loudly instead of silently falling through).
#:
#: Design, grounded in real evidence producers/skills rather than invented:
#:   * CREATED/PARSED/VALIDATED/READY progress strictly one step at a time
#:     (a pattern file must be parsed before it can be validated, validated
#:     before it is ready to dispatch) or exit early to BLOCKED (a real
#:     structural/lint failure -- e.g. `uvm_structural_lint.py`'s own
#:     findings, or a `pattern-architecture` join/join_any or port-enable
#:     defect a review catches before dispatch) or CANCELLED (an operator
#:     decision, at any pre-terminal point).
#:   * RUNNING may proceed to WAITING (a branch_b* fork sitting on its own
#:     `join`, per pattern-architecture section 2) or straight to CHECKING
#:     (a pattern with no such fork, or one whose branches all completed by
#:     the time CHECKING is reached -- section 4's "whether branch_b* is
#:     split per port at all" varies with test intent, so this edge must not
#:     be forced through WAITING every time). RUNNING may also resolve
#:     directly to TIMEOUT (a real job/simulation hang) or BLOCKED (a real
#:     mid-run resource/arbitration stall) without ever reaching CHECKING.
#:   * WAITING may proceed to CHECKING, or resolve to TIMEOUT/BLOCKED without
#:     reaching it -- but WAITING never returns to RUNNING here: this module
#:     tracks one pattern's OWN execution phase, not `branch_fw`'s internal
#:     ARM/WAIT/WAKE/DECODE/CLEAR cycling (a separate, already-generalized
#:     loop `interrupt-event-dispatch/SKILL.md` owns), so re-entering RUNNING
#:     from WAITING is deliberately not modelled as a legal top-level phase
#:     change.
#:   * CHECKING -- the FINAL_CHECK/verdict step -- is the ONLY state PASS or
#:     FAIL may legally follow, because those two verdicts are exactly what
#:     `derive_observed_terminal_verdict()` requires real FINAL_CHECK-epilogue
#:     or marker evidence to report; nothing may reach them by any other
#:     path (this is precisely what rejects "CREATED straight to PASS").
#:     CHECKING may also resolve to TIMEOUT (the check itself hangs) or
#:     BLOCKED/CANCELLED.
LEGAL_TRANSITIONS: Dict[PatternRuntimeState, FrozenSet[PatternRuntimeState]] = {
    PatternRuntimeState.CREATED: frozenset({
        PatternRuntimeState.PARSED, PatternRuntimeState.BLOCKED, PatternRuntimeState.CANCELLED,
    }),
    PatternRuntimeState.PARSED: frozenset({
        PatternRuntimeState.VALIDATED, PatternRuntimeState.BLOCKED, PatternRuntimeState.CANCELLED,
    }),
    PatternRuntimeState.VALIDATED: frozenset({
        PatternRuntimeState.READY, PatternRuntimeState.BLOCKED, PatternRuntimeState.CANCELLED,
    }),
    PatternRuntimeState.READY: frozenset({
        PatternRuntimeState.RUNNING, PatternRuntimeState.BLOCKED, PatternRuntimeState.CANCELLED,
    }),
    PatternRuntimeState.RUNNING: frozenset({
        PatternRuntimeState.WAITING, PatternRuntimeState.CHECKING,
        PatternRuntimeState.TIMEOUT, PatternRuntimeState.BLOCKED, PatternRuntimeState.CANCELLED,
    }),
    PatternRuntimeState.WAITING: frozenset({
        PatternRuntimeState.CHECKING,
        PatternRuntimeState.TIMEOUT, PatternRuntimeState.BLOCKED, PatternRuntimeState.CANCELLED,
    }),
    PatternRuntimeState.CHECKING: frozenset({
        PatternRuntimeState.PASS, PatternRuntimeState.FAIL,
        PatternRuntimeState.TIMEOUT, PatternRuntimeState.BLOCKED, PatternRuntimeState.CANCELLED,
    }),
    PatternRuntimeState.PASS: frozenset(),
    PatternRuntimeState.FAIL: frozenset(),
    PatternRuntimeState.TIMEOUT: frozenset(),
    PatternRuntimeState.BLOCKED: frozenset(),
    PatternRuntimeState.CANCELLED: frozenset(),
}


def _assert_transitions_total() -> None:
    """`LEGAL_TRANSITIONS` must be a total, internally-consistent map over
    every `PatternRuntimeState` member -- checked at import so a future
    member added to the enum without a decided set of legal edges fails a
    test immediately rather than silently falling through to "no legal
    transition anywhere", the same failure shape
    `loop_contract.assert_status_mapping_total()` guards against."""
    members = set(PatternRuntimeState)
    keys = set(LEGAL_TRANSITIONS.keys())
    if keys != members:
        raise AssertionError(
            "LEGAL_TRANSITIONS is not total over PatternRuntimeState: "
            f"missing={sorted(s.value for s in members - keys)} "
            f"extra={sorted(s.value for s in keys - members)}"
        )
    for state, targets in LEGAL_TRANSITIONS.items():
        if state in TERMINAL_STATES and targets:
            raise AssertionError(
                f"{state.value} is declared terminal in TERMINAL_STATES but "
                f"LEGAL_TRANSITIONS still lists {sorted(s.value for s in targets)} as "
                "reachable from it"
            )
        if state not in TERMINAL_STATES and not targets:
            raise AssertionError(
                f"{state.value} is not declared terminal but has no legal outgoing "
                "transition at all -- it would be a dead end"
            )
        unknown = targets - members
        if unknown:
            raise AssertionError(
                f"{state.value} lists unknown target state(s) "
                f"{sorted(s.value for s in unknown)}"
            )


_assert_transitions_total()


# ---------------------------------------------------------------------------
# Errors -- house style: a short machine-matchable `.reason` code plus a
# `.detail` dict of the exact evidence, matching `connectivity.ConnectivityError`
# / `uvm_generator.bind_mechanism_generator.BindTopologyError`.
# ---------------------------------------------------------------------------
class PatternRuntimeStateError(ValueError):
    def __init__(self, reason: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


class IllegalPatternTransitionError(PatternRuntimeStateError):
    """Raised by `assert_legal_transition()`/`advance_pattern_state()` when a
    requested transition is not in `LEGAL_TRANSITIONS` -- e.g. this batch's
    own named example, CREATED straight to PASS."""


def assert_legal_transition(
    from_state: Optional[Union[str, "PatternRuntimeState"]],
    to_state: Union[str, "PatternRuntimeState"],
) -> PatternRuntimeState:
    """Validate one proposed transition against `LEGAL_TRANSITIONS`.
    `from_state=None` means "this pattern has no runtime record yet" -- the
    only legal target from there is CREATED (there is no edge from no-state
    directly to any other state, so a caller cannot mint a fresh record
    already sitting at, say, RUNNING or PASS).

    Returns the validated `PatternRuntimeState` (never raises on the happy
    path) so a caller can use the coerced enum without a second lookup.
    Raises `IllegalPatternTransitionError` on any of: an unrecognized target
    state, an unrecognized source state, a transition attempted FROM a
    terminal state, or a transition not present in `LEGAL_TRANSITIONS[from_state]`.
    """
    try:
        to_enum = PatternRuntimeState(to_state)
    except ValueError:
        raise IllegalPatternTransitionError("UNKNOWN_TARGET_STATE", {
            "to_state": to_state,
            "legal_values": [s.value for s in PatternRuntimeState],
        })

    if from_state is None:
        if to_enum is not PatternRuntimeState.CREATED:
            raise IllegalPatternTransitionError("ILLEGAL_INITIAL_STATE", {
                "to_state": to_enum.value,
                "reason": (
                    "a pattern's runtime execution begins at CREATED only; there is "
                    "no legal edge from no-state directly to any other state"
                ),
            })
        return to_enum

    try:
        from_enum = PatternRuntimeState(from_state)
    except ValueError:
        raise IllegalPatternTransitionError("UNKNOWN_SOURCE_STATE", {
            "from_state": from_state,
            "legal_values": [s.value for s in PatternRuntimeState],
        })

    if from_enum in TERMINAL_STATES:
        raise IllegalPatternTransitionError("TRANSITION_FROM_TERMINAL_STATE", {
            "from_state": from_enum.value,
            "attempted_to_state": to_enum.value,
            "reason": (
                f"{from_enum.value} is terminal for this pattern's runtime execution; "
                "no further transition is legal (re-run as a fresh pattern record instead)"
            ),
        })

    allowed = LEGAL_TRANSITIONS[from_enum]
    if to_enum not in allowed:
        raise IllegalPatternTransitionError("ILLEGAL_TRANSITION", {
            "from_state": from_enum.value,
            "attempted_to_state": to_enum.value,
            "legal_from_this_state": sorted(s.value for s in allowed),
        })
    return to_enum


# ---------------------------------------------------------------------------
# The record: one pattern's own execution history
# ---------------------------------------------------------------------------
@dataclass
class PatternTransitionEvent:
    from_state: Optional[str]
    to_state: str
    at: str
    reason: str
    evidence_basis: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PatternRuntimeRecord:
    """One pattern file's own runtime execution record: its current state
    plus the full, append-only history of every real transition applied to
    it. `state` is always kept equal to `history[-1]["to_state"]` by
    construction -- every mutation goes through `advance_pattern_state()`,
    never a direct field assignment."""
    pattern_id: str
    protocol: Optional[str] = None
    state: str = PatternRuntimeState.CREATED.value
    created_at: str = field(default_factory=_control_plane_now)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "protocol": self.protocol,
            "state": self.state,
            "created_at": self.created_at,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PatternRuntimeRecord":
        return cls(
            pattern_id=d["pattern_id"],
            protocol=d.get("protocol"),
            state=d.get("state", PatternRuntimeState.CREATED.value),
            created_at=d.get("created_at") or _control_plane_now(),
            history=list(d.get("history", [])),
        )

    @property
    def is_terminal(self) -> bool:
        return PatternRuntimeState(self.state) in TERMINAL_STATES


def create_pattern_record(
    pattern_id: str, *, protocol: Optional[str] = None,
    reason: str = "pattern file created", at: Optional[str] = None,
) -> PatternRuntimeRecord:
    """Mint a new record at CREATED -- the only legal starting state (see
    `assert_legal_transition(None, ...)`)."""
    if not pattern_id or not pattern_id.strip():
        raise PatternRuntimeStateError("EMPTY_PATTERN_ID", {})
    assert_legal_transition(None, PatternRuntimeState.CREATED)
    stamp = at or _control_plane_now()
    record = PatternRuntimeRecord(pattern_id=pattern_id, protocol=protocol, created_at=stamp)
    record.history.append(PatternTransitionEvent(
        from_state=None, to_state=PatternRuntimeState.CREATED.value,
        at=stamp, reason=reason,
    ).to_dict())
    return record


def advance_pattern_state(
    record: PatternRuntimeRecord,
    to_state: Union[str, PatternRuntimeState], *,
    reason: str, evidence_basis: Optional[str] = None, at: Optional[str] = None,
) -> PatternRuntimeRecord:
    """Validate and apply one real transition to `record`, in place.

    Raises `IllegalPatternTransitionError` (record left untouched) on any
    illegal jump -- this is the enforcement the task names: an attempt to go
    straight from CREATED to PASS raises here rather than silently
    succeeding. `reason` is required and non-empty: a transition with no
    stated reason is exactly the un-auditable mutation this record exists to
    prevent.
    """
    if not reason or not reason.strip():
        raise PatternRuntimeStateError("MISSING_TRANSITION_REASON", {
            "pattern_id": record.pattern_id, "attempted_to_state": str(to_state),
        })
    to_enum = assert_legal_transition(record.state, to_state)
    stamp = at or _control_plane_now()
    record.history.append(PatternTransitionEvent(
        from_state=record.state, to_state=to_enum.value,
        at=stamp, reason=reason, evidence_basis=evidence_basis,
    ).to_dict())
    record.state = to_enum.value
    return record


# ---------------------------------------------------------------------------
# Evidence-derived terminal-verdict observation -- reuses sim_log_analysis,
# never a second marker scan. See module docstring's "EVIDENCE TRUTH RULE,
# APPLIED HERE" for the precedence this follows and why.
# ---------------------------------------------------------------------------
#: Distinct honest-absence bases (never a state), matching the task's own
#: named vocabulary (NOT_AVAILABLE / SILENT_FAILURE-suspected).
NOT_AVAILABLE = "NOT_AVAILABLE"
SILENT_FAILURE_SUSPECTED = "SILENT_FAILURE_SUSPECTED"

#: sim_log_analysis.classify_signatures() categories that constitute real
#: failure evidence on their own, even with no FINAL_CHECK epilogue at all --
#: a fatal/error/scoreboard-mismatch/assertion marker having fired is real
#: evidence the run did not pass, whether or not the run ever reached its
#: own verdict block.
_REAL_FAILURE_CATEGORIES = frozenset({
    "uvm_fatal", "uvm_error", "bare_error", "scoreboard_mismatch", "assertion",
})


def derive_observed_terminal_verdict(log_text: Optional[str]) -> Dict[str, Any]:
    """Read one REAL sim.log's text and report, honestly, what terminal
    `PatternRuntimeState` (if any) THIS log's own evidence supports.

    Never returns a fabricated PASS, and never guesses. Precedence:
      1. A real FINAL CHECK epilogue's own `VERDICT: PASSED|FAILED` line
         (`sim_log_analysis.parse_epilogue()`) is authoritative when present.
      2. Absent that, a real fatal/error/scoreboard-mismatch/assertion marker
         (`sim_log_analysis.classify_signatures()`) reports FAIL -- the log
         itself is real evidence the run did not pass, independent of
         whether a verdict block was ever reached.
      3. Absent that, a real timeout/deadlock marker reports TIMEOUT.
      4. A log that ends with NONE of the above -- no epilogue, no fatal/
         error marker, no timeout marker -- is reported `SILENT_FAILURE_
         SUSPECTED` with `observed_state: None`, never defaulted to PASS.
         This is `pattern-architecture/SKILL.md` section 2's own documented
         join/join_any trap ("the run ends cleanly, with zero errors,
         because nothing had a chance to fail yet") read back as a runtime
         observation.
      0. An empty/whitespace-only log reports `NOT_AVAILABLE`.

    Returns:
        {"observed_state": "PASS"|"FAIL"|"TIMEOUT"|None,
         "basis": <short machine-matchable code>,
         "reason": <one-line human explanation citing the real evidence>,
         "evidence": <the real parsed epilogue dict, or the real matched
                      classify_signatures() entry, or None>}
    """
    if log_text is None or not log_text.strip():
        return {
            "observed_state": None, "basis": NOT_AVAILABLE,
            "reason": "log text is empty; no runtime evidence to read",
            "evidence": None,
        }

    epilogue = sim_log_analysis.parse_epilogue(log_text)
    if epilogue is not None and epilogue.get("verdict") in ("PASSED", "FAILED"):
        state = (PatternRuntimeState.PASS if epilogue["verdict"] == "PASSED"
                 else PatternRuntimeState.FAIL)
        return {
            "observed_state": state.value, "basis": "FINAL_CHECK_EPILOGUE_VERDICT",
            "reason": f"FINAL CHECK epilogue reports VERDICT: {epilogue['verdict']}",
            "evidence": epilogue,
        }

    parsed = sim_log_analysis.parse_sim_log(log_text)
    classified = sim_log_analysis.classify_signatures(parsed.get("signatures", {}))

    real_failure = next(
        (c for c in classified if c["category"] in _REAL_FAILURE_CATEGORIES), None,
    )
    if real_failure is not None:
        return {
            "observed_state": PatternRuntimeState.FAIL.value,
            "basis": "REAL_ERROR_MARKER_NO_EPILOGUE",
            "reason": (
                f"no FINAL CHECK epilogue was found, but the log carries a real "
                f"{real_failure['category']} marker ({real_failure['count']}x, first at "
                f"line {real_failure['first_line_no']}) -- reported as FAIL rather than "
                "waiting on a verdict block this run never produced"
            ),
            "evidence": real_failure,
        }

    timeout_hit = next((c for c in classified if c["category"] == "timeout"), None)
    if timeout_hit is not None:
        return {
            "observed_state": PatternRuntimeState.TIMEOUT.value,
            "basis": "TIMEOUT_MARKER_NO_EPILOGUE",
            "reason": (
                f"no FINAL CHECK epilogue was found, and the log carries a real "
                f"timeout/deadlock marker ({timeout_hit['count']}x, first at line "
                f"{timeout_hit['first_line_no']})"
            ),
            "evidence": timeout_hit,
        }

    return {
        "observed_state": None, "basis": SILENT_FAILURE_SUSPECTED,
        "reason": (
            "the log has no FINAL CHECK epilogue and no fatal/error/timeout marker at "
            "all -- it ends without ever stating its own verdict, which is "
            "indistinguishable from a branch completing before the pattern's real "
            "assertions had a chance to run (pattern-architecture/SKILL.md section 2's "
            "join-vs-join_any trap); reported as a suspected silent failure, never "
            "defaulted to PASS"
        ),
        "evidence": None,
    }


def apply_observed_verdict(
    record: PatternRuntimeRecord, observation: Dict[str, Any], *,
    reason_prefix: str = "sim.log evidence",
) -> Tuple[PatternRuntimeRecord, bool]:
    """Advance `record` to the terminal state `observation` (from
    `derive_observed_terminal_verdict()`) actually supports.

    Returns `(record, applied)`. `applied` is False, and `record` is left
    completely untouched, whenever `observation["observed_state"]` is None
    (NOT_AVAILABLE or SILENT_FAILURE_SUSPECTED) -- there is deliberately no
    fallback state applied in that case; a caller must decide for itself
    what a suspected silent failure or missing evidence means for its own
    workflow (e.g. file a question, hold at CHECKING for a human), this
    function will not guess a terminal state on its behalf.

    Still enforces `LEGAL_TRANSITIONS` normally: real terminal evidence for a
    record that has not reached a state from which that terminal state is
    legal (e.g. a PASS verdict read for a record still sitting at CREATED,
    because nobody advanced it through RUNNING/CHECKING first) raises
    `IllegalPatternTransitionError` rather than being silently accepted --
    having sim.log evidence for the END does not excuse skipping the
    recorded MIDDLE.
    """
    observed = observation.get("observed_state")
    if observed is None:
        return record, False
    reason = f"{reason_prefix}: {observation.get('reason', observation.get('basis'))}"
    advance_pattern_state(record, observed, reason=reason,
                          evidence_basis=observation.get("basis"))
    return record, True


# ---------------------------------------------------------------------------
# Rendering -- reuses connectivity.render_markdown_table(), this repo's ONLY
# parameterized table renderer, rather than a second hand-rolled table loop.
# ---------------------------------------------------------------------------
def render_pattern_state_table(records: Sequence[PatternRuntimeRecord]) -> str:
    columns = [
        ("pattern_id", "Pattern"), ("protocol", "Protocol"), ("state", "State"),
        ("terminal", "Terminal?"), ("transitions", "Transitions"),
    ]
    rows = []
    for r in records:
        rows.append({
            "pattern_id": r.pattern_id,
            "protocol": r.protocol or "-",
            "state": r.state,
            "terminal": "yes" if r.is_terminal else "no",
            "transitions": str(len(r.history)),
        })
    return render_markdown_table(columns, rows, empty_note="(no pattern runtime records)")


# ---------------------------------------------------------------------------
# Optional per-project persistence -- one small JSON file, written the same
# atomic-replace way blackboard.py/control_plane.py already write theirs.
# ---------------------------------------------------------------------------
_STORE_RELATIVE_PATH = Path(".dv-harness") / "pattern_runtime" / "records.json"
_STORE_SCHEMA_VERSION = 1


def _store_path(root: Union[str, Path]) -> Path:
    return Path(root) / _STORE_RELATIVE_PATH


def load_records(root: Union[str, Path]) -> Dict[str, PatternRuntimeRecord]:
    """Load every persisted `PatternRuntimeRecord` for `root`. Returns an
    empty dict (never an error) when no store exists yet -- a project that
    has not tracked any pattern's runtime state is a real, honest state, not
    a defect."""
    path = _store_path(root)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise PatternRuntimeStateError("STORE_UNREADABLE", {
            "path": str(path), "error": str(e),
        })
    return {
        pid: PatternRuntimeRecord.from_dict(d)
        for pid, d in raw.get("patterns", {}).items()
    }


def save_records(root: Union[str, Path], records: Dict[str, PatternRuntimeRecord]) -> Path:
    """Persist `records` to `root`'s store atomically -- a reader (this
    process or another) never observes a torn/partial write."""
    path = _store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _STORE_SCHEMA_VERSION,
        "patterns": {pid: r.to_dict() for pid, r in records.items()},
    }
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=".pattern_runtime_", suffix=".json.tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _atomic_replace(tmp, path)
    return path


# ---------------------------------------------------------------------------
# Ad hoc front door: `python -m dv_harness.pattern_runtime_state_machine`.
# There is deliberately no `dv-harness` CLI verb here -- this batch's own
# scope rule forbids editing `cli.py`; a CLAUDE.md-ready snippet for wiring
# one in later is returned separately rather than applied here.
# ---------------------------------------------------------------------------
def execute_verb(
    verb: str, *, root: Union[str, Path] = ".",
    pattern_id: Optional[str] = None, log_file: Optional[str] = None,
    as_json: bool = False,
) -> Tuple[str, int]:
    """Shared implementation for the ad hoc CLI below. Returns (text,
    exit_code). Reading/observing never writes anything; nothing here runs,
    builds, submits or approves anything."""
    if verb == "states":
        rows = [{
            "state": s.value,
            "terminal": "yes" if s in TERMINAL_STATES else "no",
            "legal_transitions": ", ".join(sorted(t.value for t in LEGAL_TRANSITIONS[s])) or "(none -- terminal)",
        } for s in PatternRuntimeState]
        if as_json:
            return json.dumps(rows, indent=2), 0
        table = render_markdown_table(
            [("state", "State"), ("terminal", "Terminal?"), ("legal_transitions", "Legal transitions")],
            rows,
        )
        return table, 0

    if verb == "show":
        if not pattern_id:
            return "show requires --pattern-id", 2
        records = load_records(root)
        record = records.get(pattern_id)
        if record is None:
            return f"no runtime record for pattern {pattern_id!r} under {root}", 2
        if as_json:
            return json.dumps(record.to_dict(), indent=2), 0
        return render_pattern_state_table([record]), 0

    if verb == "list":
        records = list(load_records(root).values())
        if as_json:
            return json.dumps([r.to_dict() for r in records], indent=2), (0 if records else 2)
        return render_pattern_state_table(records), (0 if records else 2)

    if verb == "observe":
        if not log_file:
            return "observe requires --log-file", 2
        log_path = Path(log_file)
        if not log_path.exists():
            return f"no such log file: {log_path}", 2
        text = log_path.read_text(encoding="utf-8", errors="replace")
        observation = derive_observed_terminal_verdict(text)
        if as_json:
            return json.dumps(observation, indent=2), (0 if observation["observed_state"] else 1)
        lines = [
            f"basis: {observation['basis']}",
            f"observed_state: {observation['observed_state'] or '(none)'}",
            f"reason: {observation['reason']}",
        ]
        return "\n".join(lines), (0 if observation["observed_state"] else 1)

    return f"unknown verb: {verb!r} (states|show|list|observe)", 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.pattern_runtime_state_machine",
        description="Per-PATTERN execution state machine: legal-transition "
                    "enforcement plus evidence-derived terminal-verdict observation "
                    "from a real sim.log. Runs nothing.",
    )
    ap.add_argument("verb", choices=("states", "show", "list", "observe"))
    ap.add_argument("--root", default=".", help="Project root (where "
                    ".dv-harness/pattern_runtime/records.json is read from).")
    ap.add_argument("--pattern-id", default=None, help="show: which pattern's record to print.")
    ap.add_argument("--log-file", default=None, help="observe: a real sim.log file to read.")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    text, code = execute_verb(
        args.verb, root=args.root, pattern_id=args.pattern_id,
        log_file=args.log_file, as_json=args.as_json,
    )
    print(text)
    return code


if __name__ == "__main__":
    import sys
    sys.exit(main())
