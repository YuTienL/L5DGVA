"""LOOP_ENGINEERING sections 107 + 108: the loop telemetry event taxonomy and
the Loop Engineering Center's row/drill-down model.

WHAT WAS MISSING, verified on 2026-09-05 before a line of this was written.
Section 108 names nineteen logical loop events. A repo-wide grep for each of
them as a string literal returned **0 hits for all nineteen** -- the real
`.dv-harness/events.jsonl` producers emitted `LOOP_STATE_OBSERVED` /
`LOOP_STATE_OBSERVE_FAILED` (LOOP-1) and `LOOP_BUDGET_SPENT` /
`LOOP_RETRY_REFUSED` (LOOP-3) and nothing else, which LOOP-1's own disclosed
residual states plainly ("the other nineteen names have no producer"). Section
107's `Loop | State | Iteration | Verified Gain | Budget | Plateau |
Oscillation | Next Action` table had no surface either: `dashboard.py`'s only
`loop` hits were the pre-existing single-run/continuous-run start toggle.

WHAT THIS MODULE IS. Two halves and nothing else:

  * the WRITER half -- the section-108 vocabulary plus `emit()`, which writes
    through the SAME `storage.StateStore.event()` every other subsystem in this
    harness writes to. There is no second event file, no second audit trail and
    no second serializer; `dv-harness audit`, `GET /api/audit` and
    `_tail_events()` all see these events the day they are emitted.
  * the READER half -- `read_loop_telemetry()`, which folds those events back
    into section 107's eight columns plus its fourteen drill-down fields.

WHAT THIS MODULE DELIBERATELY DOES NOT DO.

  * It does not DERIVE any loop fact. Every number a row carries was computed
    by the mechanism that owns it -- `loop_contract.derive_loop_state()` for
    the state, `loop_convergence.classify_loop_convergence()` for the
    plateau/oscillation verdict, `loop_budget.BudgetEngine` for the ledger,
    `gates.evaluate_stage_evidence()` (through the stage status the engine
    persisted) for the verified gain -- and reached this module only as the
    payload of a real event. A reader that recomputed any of them would be a
    second opinion about a fact that already has an owner.
  * It does not INVENT a row. A loop that never fired an event has no row, and
    `read_loop_telemetry()` reports `available: false` naming the file it read
    and the real producer that would populate it. An honest empty state, never
    a fabricated one.
  * It writes nothing but events, and it authorizes nothing. Reading loop
    telemetry is not a mutating act: no approval, no question, no Blackboard
    topic, no state file.

WHY A SEPARATE MODULE RATHER THAN MORE OF `loop_contract.py`. `loop_contract`
owns the CONTRACT and the STATE VOCABULARY (section 85/86) and is imported by
`engine.py`, `loop_budget.py`, `loop_convergence.py` and
`golden_flow_readiness.py` for exactly that. Section 108's event names are a
third vocabulary with a different consumer (an append-only log and a GUI), and
this module IMPORTS `loop_contract` for the one bridge between them
(`LOOP_STATE_TO_EVENT`, held total by `assert_loop_state_mapping_total()`)
rather than restating a single state name.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import Stage, Status
from .loop_contract import (
    LOOP_STATE_VALUES,
    LoopState,
    VERIFICATION_CLOSURE_LOOP,
)

# --------------------------------------------------------------------------
# Section 108: the event taxonomy, verbatim
# --------------------------------------------------------------------------
#: The nineteen names section 108 lists, in the order it lists them. This tuple
#: IS the vocabulary: `emit()` refuses anything outside it, so a typo cannot
#: quietly become a twentieth event nobody reads.
LOOP_TELEMETRY_EVENTS: Tuple[str, ...] = (
    "LOOP_CREATED",
    "LOOP_STARTED",
    "LOOP_ITERATION_STARTED",
    "LOOP_ACTION_SELECTED",
    "LOOP_VERIFY_COMPLETED",
    "LOOP_PROGRESS_UPDATED",
    "LOOP_CONVERGING",
    "LOOP_PLATEAU_DETECTED",
    "LOOP_OSCILLATION_DETECTED",
    "LOOP_NO_PROGRESS",
    "LOOP_RETRY_SCHEDULED",
    "LOOP_BUDGET_WARNING",
    "LOOP_BUDGET_EXHAUSTED",
    "LOOP_BLOCKED",
    "LOOP_HUMAN_GATE_REQUIRED",
    "LOOP_RESUMED",
    "LOOP_SUCCESS",
    "LOOP_FAILED",
    "LOOP_STOPPED",
)

#: A transcription of section 108's own comma-separated list, kept SEPARATE
#: from the tuple above so the two can be compared. Same technique
#: `golden_flow_readiness._assert_rows_match_section_47()` uses: a list checked
#: only against itself is not checked.
_SECTION_108_LIST = (
    "LOOP_CREATED, LOOP_STARTED, LOOP_ITERATION_STARTED, LOOP_ACTION_SELECTED, "
    "LOOP_VERIFY_COMPLETED, LOOP_PROGRESS_UPDATED, LOOP_CONVERGING, "
    "LOOP_PLATEAU_DETECTED, LOOP_OSCILLATION_DETECTED, LOOP_NO_PROGRESS, "
    "LOOP_RETRY_SCHEDULED, LOOP_BUDGET_WARNING, LOOP_BUDGET_EXHAUSTED, "
    "LOOP_BLOCKED, LOOP_HUMAN_GATE_REQUIRED, LOOP_RESUMED, LOOP_SUCCESS, "
    "LOOP_FAILED, LOOP_STOPPED"
)


def assert_events_match_section_108() -> None:
    """`LOOP_TELEMETRY_EVENTS` must be section 108's list, in its order,
    complete and with nothing added."""
    declared = tuple(n.strip() for n in _SECTION_108_LIST.split(",") if n.strip())
    if declared != LOOP_TELEMETRY_EVENTS:
        missing = [n for n in declared if n not in LOOP_TELEMETRY_EVENTS]
        extra = [n for n in LOOP_TELEMETRY_EVENTS if n not in declared]
        raise AssertionError(
            f"LOOP_TELEMETRY_EVENTS does not match section 108's list. "
            f"missing={missing} extra={extra} "
            f"(order differs: {declared != LOOP_TELEMETRY_EVENTS and not missing and not extra})")


#: Exactly one of these is emitted per loop SESSION, on every `loop()` return
#: path. Kept as data so a test can hold the engine to it rather than a comment
#: claiming it.
TERMINAL_LOOP_EVENTS: Tuple[str, ...] = (
    "LOOP_SUCCESS", "LOOP_FAILED", "LOOP_BLOCKED", "LOOP_STOPPED",
)


class LoopTelemetryEventError(ValueError):
    """Raised by `emit()` for a name outside section 108's nineteen."""


# --------------------------------------------------------------------------
# The one LoopState <-> event bridge
# --------------------------------------------------------------------------
#: Which section-108 event names a section-86 `LoopState`, and -- for the five
#: states that name none -- WHY. `None` here is a decision with a reason, never
#: an omission: the reason strings are read back by
#: `loop_state_event_reason()` and rendered in the GUI drill-down, so a state
#: that produces no event is visible as such instead of looking like a state
#: nothing ever reached.
LOOP_STATE_TO_EVENT: Dict[str, Optional[str]] = {
    LoopState.CREATED.value: "LOOP_CREATED",
    LoopState.READY.value: None,
    LoopState.RUNNING.value: "LOOP_STARTED",
    LoopState.VERIFYING.value: None,
    LoopState.CONVERGING.value: "LOOP_CONVERGING",
    LoopState.PLATEAU.value: "LOOP_PLATEAU_DETECTED",
    LoopState.OSCILLATING.value: "LOOP_OSCILLATION_DETECTED",
    LoopState.RETRY_WAIT.value: "LOOP_RETRY_SCHEDULED",
    LoopState.BLOCKED.value: "LOOP_BLOCKED",
    LoopState.HUMAN_GATE.value: "LOOP_HUMAN_GATE_REQUIRED",
    LoopState.SUCCESS.value: "LOOP_SUCCESS",
    LoopState.FAILED.value: "LOOP_FAILED",
    LoopState.BUDGET_EXHAUSTED.value: "LOOP_BUDGET_EXHAUSTED",
    LoopState.STOPPED.value: "LOOP_STOPPED",
    LoopState.CANCELLED.value: None,
    LoopState.RESUMING.value: "LOOP_RESUMED",
    LoopState.STALE.value: None,
}

#: The honest reason each `None` above is a `None`.
LOOP_STATE_WITHOUT_EVENT_REASON: Dict[str, str] = {
    LoopState.READY.value:
        "section 108 names no READY event; a session's readiness is bracketed by "
        "LOOP_CREATED and LOOP_STARTED, which are emitted around it.",
    LoopState.VERIFYING.value:
        "LOOP_VERIFY_COMPLETED is emitted when verification FINISHES and carries the "
        "gate verdict; there is no section-108 event for verification being in flight, "
        "and emitting one carrying no verdict would add a row with nothing in it.",
    LoopState.CANCELLED.value:
        "section 108 names no cancellation event, and this harness has no cancel path: "
        "loop_contract.derive_loop_state() never returns CANCELLED, so nothing could "
        "emit one honestly.",
    LoopState.STALE.value:
        "section 108 names no staleness event -- STALE is a section-86 STATE, and "
        "section 108's nineteen names are a fixed, closed vocabulary this module "
        "refuses to widen. Section 97's stale detection DOES have a real producer "
        "since 2026-09-06 (dv_harness.loop_stale_detection.detect_loop_staleness(), "
        "wired into loop_contract.derive_loop_state()'s own `stale` parameter), so a "
        "session really can reach STALE now -- what is still missing is only a "
        "dedicated event NAME for it in this file's own fixed taxonomy.",
}


def assert_loop_state_mapping_total() -> None:
    """Every `loop_contract.LoopState` member must have a decided event meaning
    -- a section-108 name, or `None` WITH a reason -- and the mapping must name
    no event outside section 108. A new LoopState added without a decision here
    fails the tests rather than silently producing no telemetry."""
    missing = [s for s in LOOP_STATE_VALUES if s not in LOOP_STATE_TO_EVENT]
    if missing:
        raise AssertionError(
            f"LoopState members with no telemetry meaning decided: {missing}. "
            f"Add them to LOOP_STATE_TO_EVENT (and, for a None, a reason in "
            f"LOOP_STATE_WITHOUT_EVENT_REASON).")
    unknown = [k for k in LOOP_STATE_TO_EVENT if k not in LOOP_STATE_VALUES]
    if unknown:
        raise AssertionError(f"LOOP_STATE_TO_EVENT names non-LoopState keys: {unknown}")
    bad = [f"{k}->{v}" for k, v in LOOP_STATE_TO_EVENT.items()
           if v is not None and v not in LOOP_TELEMETRY_EVENTS]
    if bad:
        raise AssertionError(
            f"LOOP_STATE_TO_EVENT names events outside section 108: {bad}")
    unreasoned = [k for k, v in LOOP_STATE_TO_EVENT.items()
                  if v is None and not LOOP_STATE_WITHOUT_EVENT_REASON.get(k)]
    if unreasoned:
        raise AssertionError(
            f"LoopState members mapped to no event with no stated reason: {unreasoned}. "
            f"A None with no reason reads to a human as an oversight.")


def event_for_loop_state(state: str) -> Optional[str]:
    """The section-108 event naming `state`, or None when section 108 names
    none. Raises on a state outside `LoopState` rather than guessing."""
    if state not in LOOP_STATE_TO_EVENT:
        raise KeyError(
            f"unknown loop state {state!r}; must be one of {list(LOOP_STATE_VALUES)}")
    return LOOP_STATE_TO_EVENT[state]


def loop_state_event_reason(state: str) -> str:
    """Why `state` names no event. Empty string when it does name one."""
    return LOOP_STATE_WITHOUT_EVENT_REASON.get(state, "")


# --------------------------------------------------------------------------
# Verified gain -- the ONE definition, shared with the dashboard
# --------------------------------------------------------------------------
#: The progress metric section 107's "Verified Gain" column reports for the
#: Verification Closure Loop.
#:
#: WHY THIS METRIC AND NOT COVERAGE. The coverage curve is a CROSS-RUN series
#: (`loop_convergence`'s, from the evidence database via
#: `trend_analysis.daily_rollup()`) and moves on a nightly cadence, not on a
#: loop iteration -- reporting it per iteration would show a flat line that
#: says nothing about whether THIS iteration achieved anything. What this
#: engine really verifies per iteration is a stage gate: a stage reaches PASS
#: only after `gates.evaluate_stage_evidence()` accepted its evidence, which is
#: exactly section 110's LOOP-AT-26 sense of "verified gain" as opposed to
#: artifact churn. Both metrics are reported; every event carries `metric` so a
#: reader always knows which one produced the number.
GATE_VERIFIED_STAGE_METRIC = "gate_verified_stages"

#: The coverage series metric, named here only so the GUI can label a
#: cross-run verdict without importing loop_convergence.
COVERAGE_SERIES_METRIC = "coverage_percent"

#: The two stage statuses that mean "this stage's gate accepted its evidence".
#: CLOSED is included because `loop()` sets `overall_status` CLOSED on a run
#: that ran out of graph, and a stage may carry it after a signoff.
GATE_VERIFIED_STAGE_STATUSES = (Status.PASS.value, Status.CLOSED.value)


def gate_verified_stage_count(stages: Optional[Dict[str, Any]]) -> Tuple[int, int]:
    """(gate-verified stages, total canonical stages) for one `state.json`.

    The denominator is `len(Stage)` -- the canonical stage count -- and NOT
    `len(stages)`: an on-disk state.json can predate later `Stage` enum
    additions and would silently understate the true denominator.
    `dashboard._overall_progress()` delegates here, so the progress bar at the
    top of the page and the Verified Gain column of the Loop Engineering
    Center cannot disagree about which stages count."""
    stages = stages or {}
    done = sum(1 for s in Stage
               if (stages.get(s.value) or {}).get("status") in GATE_VERIFIED_STAGE_STATUSES)
    return done, len(Stage)


def verified_gain(stages: Optional[Dict[str, Any]],
                  previous: Optional[int] = None) -> Dict[str, Any]:
    """One `LOOP_PROGRESS_UPDATED` payload, from a real `state.json` stages dict.

    `previous` is the same count at the previous iteration of THIS session --
    `None` on the first iteration, where a delta would be a comparison against
    nothing. The delta is what section 110's LOOP-AT-26 turns on: an iteration
    that produced artifacts and moved this number by zero is no-progress."""
    done, total = gate_verified_stage_count(stages)
    return {
        "metric": GATE_VERIFIED_STAGE_METRIC,
        "value": done,
        "total": total,
        "previous": previous,
        "delta": None if previous is None else done - previous,
        "percent": round(100 * done / total) if total else 0,
    }


# --------------------------------------------------------------------------
# The writer half
# --------------------------------------------------------------------------
def new_run_id(loop_id: str = VERIFICATION_CLOSURE_LOOP) -> str:
    """One id per loop SESSION (one `engine.DVHarness.loop()` invocation).

    UTC timestamp plus the OS pid: two `loop()` sessions in the same second are
    two processes in every real deployment (the CLI is one-shot), and the
    dashboard's background-run thread holds the project's single-run lock, so
    the pair is unique in practice and readable in a log by a human."""
    import os
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{loop_id}:{stamp}:{os.getpid()}"


def emit(store, event: str, *,
         loop_id: str = VERIFICATION_CLOSURE_LOOP,
         run_id: str,
         iteration: Optional[int] = None,
         stage: Optional[str] = None,
         **payload: Any) -> Dict[str, Any]:
    """Write ONE section-108 event through the real `StateStore.event()`.

    `store` is a real `storage.StateStore`; this module has no writer of its
    own and no second audit file. An event name outside section 108's nineteen
    raises rather than being written -- an unrecognized name in
    `.dv-harness/events.jsonl` is worse than no event, because
    `read_loop_telemetry()` would drop it silently and the emitter would look
    like it had reported something."""
    if event not in LOOP_TELEMETRY_EVENTS:
        raise LoopTelemetryEventError(
            f"{event!r} is not one of section 108's loop telemetry events: "
            f"{list(LOOP_TELEMETRY_EVENTS)}")
    from .engine import now  # the one timestamp format every event in this file uses
    record: Dict[str, Any] = {"ts": now(), "event": event,
                              "loop_id": loop_id, "run_id": run_id}
    if iteration is not None:
        record["iteration"] = int(iteration)
    if stage is not None:
        record["stage"] = stage
    record.update(payload)
    store.event(record)
    return record


# --------------------------------------------------------------------------
# The reader half -- section 107's table
# --------------------------------------------------------------------------
#: Section 107's table header, verbatim, as (key, label) pairs. The keys are
#: what `GET /api/loops` returns; the labels are what the GUI prints.
SECTION_107_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("loop", "Loop"),
    ("state", "State"),
    ("iteration", "Iteration"),
    ("verified_gain", "Verified Gain"),
    ("budget", "Budget"),
    ("plateau", "Plateau"),
    ("oscillation", "Oscillation"),
    ("next_action", "Next Action"),
)

#: Section 107's drill-down field list, verbatim and in its order.
SECTION_107_DRILLDOWN_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("loop_id", "Loop ID"),
    ("goal", "Goal"),
    ("trigger", "Trigger"),
    ("state", "State"),
    ("iteration_history", "Iteration History"),
    ("evidence", "Evidence"),
    ("verifier", "Verifier"),
    ("progress_delta", "Progress Delta"),
    ("budget_remaining", "Budget Remaining"),
    ("retry_backoff", "Retry/Backoff"),
    ("next_best_action", "Next-Best-Action"),
    ("human_gate", "Human Gate"),
    ("stop_reason", "Stop Reason"),
    ("resume_condition", "Resume Condition"),
)

_SECTION_107_TABLE_LINE = ("Loop | State | Iteration | Verified Gain | Budget | "
                           "Plateau | Oscillation | Next Action")
_SECTION_107_DRILLDOWN_LINE = (
    "Loop ID, Goal, Trigger, State, Iteration History, Evidence, Verifier, "
    "Progress Delta, Budget Remaining, Retry/Backoff, Next-Best-Action, "
    "Human Gate, Stop Reason and Resume Condition")


def assert_columns_match_section_107() -> None:
    """The eight columns and the fourteen drill-down fields must be section
    107's own, in its order. Compared against transcriptions of the
    specification's two lines rather than against themselves."""
    labels = tuple(l for _, l in SECTION_107_COLUMNS)
    declared = tuple(p.strip() for p in _SECTION_107_TABLE_LINE.split("|"))
    if labels != declared:
        raise AssertionError(
            f"SECTION_107_COLUMNS does not match section 107's table header. "
            f"declared={declared} got={labels}")
    drill = tuple(l for _, l in SECTION_107_DRILLDOWN_FIELDS)
    raw = _SECTION_107_DRILLDOWN_LINE.replace(" and ", ", ")
    declared_drill = tuple(p.strip() for p in raw.split(",") if p.strip())
    if drill != declared_drill:
        raise AssertionError(
            f"SECTION_107_DRILLDOWN_FIELDS does not match section 107's drill-down "
            f"list. declared={declared_drill} got={drill}")


#: How many trailing `events.jsonl` lines `read_loop_telemetry()` reads by
#: default. A cap rather than the whole file because this runs on a dashboard
#: HTTP thread; a truncated scan is reported as `scan_truncated: true` so a
#: partial view is never presented as the complete history.
DEFAULT_EVENT_SCAN_LINES = 20000

#: The honest empty-state reason, naming the real producer.
NO_LOOP_TELEMETRY = "NO_LOOP_TELEMETRY_EVENTS"

#: How many rows of iteration history one drill-down carries.
DEFAULT_ITERATION_HISTORY_LIMIT = 200

NOT_EVALUATED = "NOT_EVALUATED"
NOT_OBSERVED = "NOT_OBSERVED"


def _read_events(root: Path, *, scan_lines: int = DEFAULT_EVENT_SCAN_LINES
                 ) -> Tuple[List[Dict[str, Any]], int, bool]:
    """The trailing `scan_lines` parsed entries of `.dv-harness/events.jsonl`.

    Same append-only file, same tolerance for a torn final line, as
    `dashboard._tail_events()`: a line that will not parse is skipped, never
    fatal. Returns (entries, lines_scanned, truncated)."""
    events_file = Path(root) / ".dv-harness" / "events.jsonl"
    if not events_file.exists():
        return [], 0, False
    try:
        raw = events_file.read_text(encoding="utf-8")
    except Exception:
        return [], 0, False
    lines = [l for l in raw.splitlines() if l.strip()]
    truncated = len(lines) > scan_lines
    out: List[Dict[str, Any]] = []
    for line in lines[-scan_lines:]:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out, len(lines), truncated


#: Public name for the reader above, so a module that needs the SAME trailing
#: window of `.dv-harness/events.jsonl` -- `platform_health.py` reads it for the
#: real EXECUTION_PREFLIGHT_PASS/BLOCKED events and this harness's own `*_FAILED`
#: side-channel failures -- reuses this one parser instead of adding a third
#: events.jsonl reader beside it and `dashboard._tail_events()`.
read_events = _read_events


def loop_events(root: Path, *, scan_lines: int = DEFAULT_EVENT_SCAN_LINES
                ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Only the section-108 entries, oldest first, plus the scan's own stats."""
    entries, scanned, truncated = _read_events(root, scan_lines=scan_lines)
    picked = [e for e in entries if e.get("event") in LOOP_TELEMETRY_EVENTS]
    return picked, {"lines_scanned": scanned, "scan_truncated": truncated,
                    "scan_limit": scan_lines, "loop_events": len(picked)}


def previous_session_summary(root: Path, *,
                             loop_id: str = VERIFICATION_CLOSURE_LOOP,
                             scan_lines: int = DEFAULT_EVENT_SCAN_LINES
                             ) -> Dict[str, Any]:
    """Whether this loop has ever run here, and how the last session ended.

    `engine.DVHarness.loop()` uses exactly this to decide between LOOP_CREATED
    (this loop has no prior session in the log at all) and LOOP_RESUMED (a
    prior session ended in something other than LOOP_SUCCESS, so this one
    continues it). Both are facts read out of the append-only log; neither is
    a flag anybody sets."""
    picked, stats = loop_events(root, scan_lines=scan_lines)
    mine = [e for e in picked if e.get("loop_id") == loop_id]
    runs: List[str] = []
    for e in mine:
        rid = e.get("run_id")
        if rid and rid not in runs:
            runs.append(rid)
    last_terminal = None
    for e in reversed(mine):
        if e.get("event") in TERMINAL_LOOP_EVENTS:
            last_terminal = e
            break
    return {
        "loop_id": loop_id,
        "ever_created": any(e.get("event") == "LOOP_CREATED" for e in mine),
        "prior_run_ids": runs,
        "prior_session_count": len(runs),
        "last_terminal_event": (last_terminal or {}).get("event"),
        "last_terminal_reason": (last_terminal or {}).get("reason"),
        "scan": stats,
    }


# --------------------------------------------------------------------------
# Section 107's Next Action column
# --------------------------------------------------------------------------
#: The Gap -> Next-Best-Action catalog for a loop row, driven through the REAL
#: `inference.next_best_action()` via its `gap_action_catalog` parameter -- the
#: same domain-neutral engine `capability_evolution.py` and
#: `golden_flow_readiness.py` already drive with their own catalogs, and the
#: one section 10 forbids re-implementing. Keyed by the row's current state.
LOOP_NEXT_ACTION_CATALOG: Dict[str, Any] = {
    "source": "loop_telemetry.LOOP_NEXT_ACTION_CATALOG",
    "actions": {
        LoopState.CREATED.value:
            "The loop exists but has not started. Run `dv-harness start --loop \"<goal>\"`.",
        LoopState.READY.value:
            "Preconditions are met and nothing is running. Run "
            "`dv-harness start --loop \"<goal>\"` to begin iterating.",
        LoopState.RUNNING.value:
            "A stage is in flight. Watch `dv-harness status`; no action is owed yet.",
        LoopState.VERIFYING.value:
            "A stage's gates are being evaluated. No action is owed until the verdict lands.",
        LoopState.CONVERGING.value:
            "The loop is making verified gain. Let it continue; re-check the Budget "
            "column so the run does not converge into an exhausted budget.",
        LoopState.PLATEAU.value:
            "STOP expanding seeds blindly. Run `dv-harness loop-contract convergence` "
            "for the per-bin plateau investigation, then act on its own next action "
            "(ADD_SEEDS / stimulus gap / escalate an unreachable bin to a human).",
        LoopState.OSCILLATING.value:
            "The loop is undoing its own work. Stop retrying and change strategy: read "
            "the repeated fingerprint in this row's Evidence, and treat a same-SHA "
            "flip-flop as a flaky test rather than as loop oscillation.",
        LoopState.RETRY_WAIT.value:
            "A retry is scheduled. Check the failure classification on this row before "
            "spending the next attempt -- an identical repeated signature will not fix itself.",
        LoopState.BLOCKED.value:
            "Read this row's Stop Reason. A circuit-breaker block clears only through a "
            "recorded `dv-harness loop-budget breaker-reset --reason ... --by ...`.",
        LoopState.HUMAN_GATE.value:
            "A human decision is owed. Answer the real blocking question "
            "(`dv-harness question-queue list --blocking-only`, then "
            "`dv-harness question-queue answer <Q-ID> ...`) and re-run the loop.",
        LoopState.BUDGET_EXHAUSTED.value:
            "A budget ran out. Read `dv-harness loop-budget status` for which dimension, "
            "then either fix the cause or clear it with a recorded "
            "`dv-harness loop-budget reset --reason ... --by ...`.",
        LoopState.SUCCESS.value:
            "The loop reached its machine-checkable done. No action is owed.",
        LoopState.FAILED.value:
            "The loop stopped with no route forward. Read this row's Stop Reason and the "
            "failing stage's blocking_reason in `dv-harness status`.",
        LoopState.STOPPED.value:
            "The loop was stopped by a human or a pause. Resume it "
            "(`dv-harness resume`, or `dv-harness release-takeover`, then "
            "`dv-harness start --loop`).",
        LoopState.CANCELLED.value:
            "The loop was cancelled. Start a new session when the cancellation reason clears.",
        LoopState.RESUMING.value:
            "The loop is resuming a prior session. Confirm the SHA/environment it resumes "
            "against still matches before trusting its earlier evidence.",
        LoopState.STALE.value:
            "The loop's durable state predates the current SHA/environment. Re-validate "
            "before resuming.",
    },
    "fallback": "No next action is defined for loop state {gap}; read this row's Evidence.",
}


def next_actions_for_states(root: Path, states: List[str]) -> Dict[str, str]:
    """`inference.next_best_action()` over the catalog above -- called, never
    re-implemented. Returns {state: action}."""
    from .inference import next_best_action
    if not states:
        return {}
    results = next_best_action(None, list(states), Path(root),
                               gap_action_catalog=LOOP_NEXT_ACTION_CATALOG)
    out: Dict[str, str] = {}
    for r in results or []:
        gap = r.get("gap")
        if gap:
            # `suggested_action` is that function's own result key -- read, not
            # renamed, so a change there surfaces here instead of silently
            # rendering an empty Next Action column.
            out[gap] = r.get("suggested_action") or ""
    return out


# --------------------------------------------------------------------------
# Folding events into rows
# --------------------------------------------------------------------------
@dataclass
class LoopSession:
    """One loop SESSION folded out of its own events. Every field below was
    carried on a real event; nothing here is recomputed."""
    loop_id: str
    run_id: str
    state: str = NOT_OBSERVED
    iteration: int = 0
    started_at: Optional[str] = None
    last_event_at: Optional[str] = None
    goal: str = ""
    trigger: str = ""
    resumed: bool = False
    terminal_event: Optional[str] = None
    stop_reason: str = ""
    resume_condition: str = ""
    verified_gain: Optional[Dict[str, Any]] = None
    budget: Optional[Dict[str, Any]] = None
    plateau: str = NOT_EVALUATED
    plateau_detail: Optional[Dict[str, Any]] = None
    oscillation: str = NOT_EVALUATED
    oscillation_detail: Optional[Dict[str, Any]] = None
    verifier: Optional[Dict[str, Any]] = None
    human_gate: Optional[Dict[str, Any]] = None
    retry_backoff: Optional[Dict[str, Any]] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    event_counts: Dict[str, int] = field(default_factory=dict)
    iteration_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _fold_session(loop_id: str, run_id: str,
                  events: List[Dict[str, Any]],
                  history_limit: int) -> LoopSession:
    s = LoopSession(loop_id=loop_id, run_id=run_id)
    for e in events:
        name = e.get("event")
        s.event_counts[name] = s.event_counts.get(name, 0) + 1
        s.last_event_at = e.get("ts") or s.last_event_at
        if e.get("iteration") is not None:
            try:
                s.iteration = max(s.iteration, int(e["iteration"]))
            except (TypeError, ValueError):
                pass

        if name == "LOOP_CREATED":
            s.started_at = s.started_at or e.get("ts")
        elif name == "LOOP_STARTED":
            s.started_at = s.started_at or e.get("ts")
            s.goal = e.get("goal") or s.goal
            s.trigger = e.get("trigger") or s.trigger
        elif name == "LOOP_RESUMED":
            s.resumed = True
            s.evidence["resumed_from"] = {
                "prior_session_count": e.get("prior_session_count"),
                "last_terminal_event": e.get("last_terminal_event"),
                "last_terminal_reason": e.get("last_terminal_reason"),
            }
        elif name == "LOOP_ACTION_SELECTED":
            s.evidence["last_action"] = {
                "stage": e.get("stage"), "route": e.get("route"),
                "skills": e.get("skills"), "attempts": e.get("attempts"),
            }
        elif name == "LOOP_VERIFY_COMPLETED":
            s.verifier = {
                "stage": e.get("stage"),
                "gate_ids": e.get("gate_ids"),
                "gate_count": e.get("gate_count"),
                "verdict": e.get("verdict"),
                "status": e.get("status"),
                "verifier": e.get("verifier"),
                "blocking_reason": e.get("blocking_reason"),
            }
        elif name == "LOOP_PROGRESS_UPDATED":
            s.verified_gain = {k: e.get(k) for k in
                               ("metric", "value", "total", "previous", "delta", "percent")}
        elif name == "LOOP_RETRY_SCHEDULED":
            s.retry_backoff = {
                "stage": e.get("stage"), "attempts": e.get("attempts"),
                "max_stage_retries": e.get("max_stage_retries"),
                "attempts_remaining": e.get("attempts_remaining"),
                "failure_type": e.get("failure_type"),
                "failure_signature_repeats": e.get("failure_signature_repeats"),
                "backoff": e.get("backoff"),
            }
        elif name in ("LOOP_BUDGET_WARNING", "LOOP_BUDGET_EXHAUSTED"):
            s.budget = {k: e.get(k) for k in
                        ("stage", "attempts", "max_stage_retries", "attempts_remaining",
                         "dimensions", "exhausted", "loop_state")}
            s.budget["event"] = name
        elif name == "LOOP_PLATEAU_DETECTED":
            s.plateau = e.get("verdict") or LoopState.PLATEAU.value
            s.plateau_detail = e.get("convergence") or e.get("detail")
        elif name == "LOOP_OSCILLATION_DETECTED":
            s.oscillation = e.get("verdict") or LoopState.OSCILLATING.value
            s.oscillation_detail = e.get("oscillation") or e.get("detail")
        elif name == "LOOP_CONVERGING":
            # A cross-run CONVERGING verdict is a real "no plateau today"
            # answer and is recorded as such; a per-iteration one is not --
            # the coverage series is what plateau is measured on.
            if e.get("metric") == COVERAGE_SERIES_METRIC:
                s.plateau = e.get("verdict") or "CONVERGING"
                s.plateau_detail = e.get("convergence") or s.plateau_detail
        elif name == "LOOP_NO_PROGRESS":
            if e.get("metric") == COVERAGE_SERIES_METRIC:
                s.plateau = e.get("verdict") or "NO_PROGRESS"
                s.plateau_detail = e.get("convergence") or s.plateau_detail
            s.evidence["last_no_progress"] = {
                "metric": e.get("metric"), "stage": e.get("stage"),
                "delta": e.get("delta"), "reason": e.get("reason"),
            }
        elif name == "LOOP_HUMAN_GATE_REQUIRED":
            s.human_gate = {"stage": e.get("stage"), "reason": e.get("reason"),
                            "blocking_reason": e.get("blocking_reason"),
                            "resume_condition": e.get("resume_condition")}
        elif name in TERMINAL_LOOP_EVENTS:
            s.terminal_event = name
            s.stop_reason = e.get("reason") or e.get("blocking_reason") or ""
            s.resume_condition = e.get("resume_condition") or ""

        if e.get("loop_state"):
            s.state = e["loop_state"]

        if len(s.iteration_history) < history_limit:
            row = {"ts": e.get("ts"), "event": name,
                   "iteration": e.get("iteration"), "stage": e.get("stage")}
            note = e.get("reason") or e.get("verdict") or e.get("status")
            if note:
                row["note"] = note
            s.iteration_history.append(row)

    if s.state == NOT_OBSERVED and s.terminal_event:
        # A terminal event always names a state through LOOP_STATE_TO_EVENT's
        # inverse; falling back to it means a session that ended is never
        # reported as "state unknown".
        for st, ev in LOOP_STATE_TO_EVENT.items():
            if ev == s.terminal_event:
                s.state = st
                break
    if s.oscillation == NOT_EVALUATED and s.plateau not in (NOT_EVALUATED,):
        # The same cross-run report answers both questions; if it ran and did
        # not find oscillation, that is a real "no", not "never looked".
        s.oscillation = "NOT_DETECTED"
    return s


def read_loop_telemetry(root: Path, *,
                        scan_lines: int = DEFAULT_EVENT_SCAN_LINES,
                        run_id: Optional[str] = None,
                        history_limit: int = DEFAULT_ITERATION_HISTORY_LIMIT
                        ) -> Dict[str, Any]:
    """Section 107's table plus its drill-down, folded out of the REAL
    `.dv-harness/events.jsonl` section-108 events and nothing else.

    A project whose loops have never emitted one reports `available: false`
    with the file it read and the real producer that would populate it -- an
    honest empty state, never a fabricated row. This function reads; it writes
    nothing, runs no stage, evaluates no gate and mints no approval."""
    root = Path(root)
    events_file = root / ".dv-harness" / "events.jsonl"
    picked, stats = loop_events(root, scan_lines=scan_lines)
    if run_id:
        picked = [e for e in picked if e.get("run_id") == run_id]

    base: Dict[str, Any] = {
        "available": False,
        "events_file": str(events_file),
        "event_names": list(LOOP_TELEMETRY_EVENTS),
        "columns": [{"key": k, "label": l} for k, l in SECTION_107_COLUMNS],
        "drilldown_fields": [{"key": k, "label": l}
                             for k, l in SECTION_107_DRILLDOWN_FIELDS],
        "rows": [],
        "sessions": {},
        "scan": stats,
        "reason": "",
    }
    if not picked:
        base["reason"] = (
            f"{NO_LOOP_TELEMETRY}: no section-108 loop telemetry event has been written to "
            f"{events_file}. The real producer is engine.DVHarness.loop() -- run "
            f"`dv-harness start --loop \"<goal>\"` (or Start (loop) on this page); a "
            f"one-shot `dv-harness run-stage` is not a loop and emits none.")
        return base

    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    order: List[Tuple[str, str]] = []
    for e in picked:
        key = (str(e.get("loop_id") or VERIFICATION_CLOSURE_LOOP),
               str(e.get("run_id") or "(no run_id)"))
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(e)

    sessions = [_fold_session(lid, rid, grouped[(lid, rid)], history_limit)
                for lid, rid in order]
    # Newest session first: an operator opening the card wants the run that is
    # happening now, not the first one this project ever had.
    sessions.reverse()

    actions = next_actions_for_states(
        root, sorted({s.state for s in sessions if s.state in LOOP_STATE_TO_EVENT}))

    rows: List[Dict[str, Any]] = []
    detail: Dict[str, Any] = {}
    for s in sessions:
        rows.append({
            "loop": s.loop_id,
            "run_id": s.run_id,
            "state": s.state,
            "iteration": s.iteration,
            "verified_gain": s.verified_gain,
            "budget": s.budget,
            "plateau": s.plateau,
            "oscillation": s.oscillation,
            "next_action": actions.get(s.state, ""),
            "terminal_event": s.terminal_event,
            "started_at": s.started_at,
            "last_event_at": s.last_event_at,
            "resumed": s.resumed,
            "event_counts": s.event_counts,
        })
        detail[s.run_id] = {
            "loop_id": s.loop_id,
            "run_id": s.run_id,
            "goal": s.goal,
            "trigger": s.trigger,
            "state": s.state,
            "iteration_history": s.iteration_history,
            "evidence": s.evidence,
            "verifier": s.verifier,
            "progress_delta": s.verified_gain,
            "budget_remaining": s.budget,
            "retry_backoff": s.retry_backoff,
            "next_best_action": actions.get(s.state, ""),
            "human_gate": s.human_gate,
            "stop_reason": s.stop_reason,
            "resume_condition": s.resume_condition,
            "plateau_detail": s.plateau_detail,
            "oscillation_detail": s.oscillation_detail,
        }

    base["available"] = True
    base["rows"] = rows
    base["sessions"] = detail
    return base


# --------------------------------------------------------------------------
# Front door
# --------------------------------------------------------------------------
def render_rows_text(payload: Dict[str, Any]) -> str:
    """Section 107's table as plain text, for the module CLI."""
    if not payload.get("available"):
        return f"(no loop telemetry) {payload.get('reason', '')}"
    header = " | ".join(l for _, l in SECTION_107_COLUMNS)
    lines = [header, "-" * len(header)]
    for r in payload.get("rows") or []:
        vg = r.get("verified_gain") or {}
        gain = ("-" if not vg else
                f"{vg.get('value')}/{vg.get('total')} {vg.get('metric')}"
                + (f" ({vg.get('delta'):+d})" if isinstance(vg.get("delta"), int) else ""))
        bud = r.get("budget") or {}
        budget = ("-" if not bud else
                  f"{bud.get('attempts')}/{bud.get('max_stage_retries')} attempts"
                  + (f" [{bud.get('event')}]" if bud.get("event") else ""))
        lines.append(" | ".join([
            str(r.get("loop")), str(r.get("state")), str(r.get("iteration")),
            gain, budget, str(r.get("plateau")), str(r.get("oscillation")),
            str(r.get("next_action") or "-")[:80],
        ]))
    return "\n".join(lines)


def execute_verb(root: Path, verb: str, *,
                 run_id: Optional[str] = None,
                 as_json: bool = False) -> Tuple[int, Any]:
    """One implementation behind both `python -m dv_harness.loop_telemetry` and
    any future CLI front door -- the same shared-`execute_verb()` convention
    `loop_contract` and `loop_budget` follow."""
    root = Path(root)
    if verb == "events":
        picked, stats = loop_events(root)
        if run_id:
            picked = [e for e in picked if e.get("run_id") == run_id]
        return (0 if picked else 2), {"events": picked, "scan": stats,
                                      "event_names": list(LOOP_TELEMETRY_EVENTS)}
    if verb == "names":
        return 0, {"event_names": list(LOOP_TELEMETRY_EVENTS),
                   "terminal_events": list(TERMINAL_LOOP_EVENTS),
                   "loop_state_to_event": LOOP_STATE_TO_EVENT,
                   "no_event_reasons": LOOP_STATE_WITHOUT_EVENT_REASON}
    if verb in ("rows", "show"):
        payload = read_loop_telemetry(root, run_id=run_id)
        if verb == "show" and not as_json:
            return (0 if payload.get("available") else 2), render_rows_text(payload)
        return (0 if payload.get("available") else 2), payload
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["names", "events", "rows", "show"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.loop_telemetry",
        description="Section 107's Loop Engineering Center table over section 108's "
                    "real loop telemetry events in .dv-harness/events.jsonl.")
    p.add_argument("verb", choices=["names", "events", "rows", "show"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--run-id", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 run_id=args.run_id, as_json=args.json)
    print(payload if isinstance(payload, str)
          else json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
