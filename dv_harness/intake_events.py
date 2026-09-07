"""dv_harness/intake_events.py -- the fixed 18-event INTAKE_* taxonomy, wired
into the SAME `storage.StateStore.event()` every other subsystem in this
harness already writes `.dv-harness/events.jsonl` through -- there is no
second audit file and no second serializer.

WHAT WAS MISSING, verified before a line of this was written. A repo-wide
grep for `INTAKE_[A-Z_]+`, `intake_events_taxonomy`, `Intake Events`, and
"section 34" across this checkout found no in-repo document naming a fixed
INTAKE_* event vocabulary at all -- unlike `loop_telemetry.py`'s section 108,
whose nineteen names could be transcribed from, and checked against, a real
prior specification document, no such external text is discoverable here.
Two real, already-shipped mechanisms answer the whole-intake-lifecycle and
per-field questions this taxonomy needs to cover --
`verification_intake_contract.py`'s 13-state `IntakeContractState` machine
(`CREATED -> DISCOVERING -> CORRELATING -> QUESTION_PENDING ->
USER_INPUT_RECEIVED -> VALIDATING -> CONFLICT -> PARTIAL -> BLOCKED ->
READY_FOR_REVIEW -> BASELINED -> STALE -> REVALIDATING`) and
`intake_state.py`'s per-field `IntakeFieldStatus` resolution plus its
`evaluate_uvm_generation_ready()` refusal gate -- and NEITHER emitted a
single event before this file existed (both modules' own docstrings say so:
"this module mints no `.dv-harness/` state of its own" /
"writes no state/blackboard/approval record"). Rather than invent an event
name for a fact neither module actually produces (exactly the fabrication
the Evidence Truth Rule forbids), this taxonomy's eighteen names are
DERIVED, 1:1, from those two modules' own real surfaces: one event per real
`IntakeContractState` (13, the same total-mapping discipline
`loop_telemetry.LOOP_STATE_TO_EVENT` already applies to `LoopState`) plus
five events over `intake_state.py`'s own real per-run findings -- one
state-built summary, a per-field event for each of the two real, actionable
per-field statuses this module's own vocabulary treats as findings (BLOCKED
and CONTRADICTED, never the five routine ones -- AUTO_RESOLVED/
USER_CONFIRMED/PARTIAL/MISSING/UNKNOWN/NOT_APPLICABLE mint no event of
their own), and the two mutually-exclusive terminal outcomes of
`evaluate_uvm_generation_ready()`. `assert_intake_event_taxonomy_total()`
(run at import) holds all three facts structurally rather than by comment:
the state mapping is total over `IntakeContractState` in both directions,
the eighteen names partition exactly into "one per contract state" (13) and
"one per intake_state.py finding" (5) with no overlap and no orphan, and the
tuple really is eighteen names long with no duplicate.

WHAT THIS MODULE IS. A WRITER half (`emit()`, refusing any name outside the
eighteen -- exactly `loop_telemetry.emit()`'s own contract) plus two
best-effort composite emitters this file's own real callers actually use --
`emit_contract_transition()` (called from `verification_intake_contract.
create_contract()`/`transition_contract()` when a caller supplies a real
`store`) and `emit_intake_state_report()` / `emit_generation_readiness()`
(called from `intake_state.build_intake_state()` and
`evaluate_uvm_generation_ready()`, same condition) -- plus a READER half
that reuses, rather than re-implements, `loop_telemetry.read_events()`, the
same public generic events.jsonl parser `platform_health.py` already reuses
instead of adding a third one.

WHY EMISSION IS OPT-IN (a `store: Any = None` keyword on all three real call
sites, default `None`). Both `verification_intake_contract.py` and
`intake_state.py` are pure, in-memory, no-side-effect modules by explicit
design. `storage.StateStore.__init__()` itself `mkdir()`s `.dv-harness/` the
first time it is constructed, so unconditionally opening one from inside
these two modules would mint a project tree merely because a caller asked a
QUESTION ("is this project's intake ready") -- exactly the fabricated side
effect `golden_flow_readiness.py`/`confidence_calibration.py` already refuse
for the identical reason. A caller who wants the real, persistent audit
trail constructs a real `storage.StateStore` themselves (as `engine.py`
already does for every other subsystem) and passes it in; a caller who does
not is byte-for-byte unaffected -- every pre-existing call site of
`create_contract()`, `transition_contract()`, `build_intake_state()` and
`evaluate_uvm_generation_ready()` in this repo passes no `store` and is
untouched by this change.

Every emitter here is best-effort, matching `engine.py`'s own
`_emit_loop_event()` convention exactly: a real emission failure records
`INTAKE_EVENT_EMIT_FAILED` (deliberately NOT one of the eighteen -- a
failure to observe intake is not one of the eighteen things being observed)
and never turns an already-computed transition/build/readiness result into
a crash.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It does not derive any intake
fact -- every field on every event is read off an already-computed
`VerificationIntakeContract`/`IntakeState`/`UvmGenerationReadiness` object,
never recomputed here. It does not decide whether intake is ready, whether a
transition is legal, or which field is BLOCKED/CONTRADICTED -- those
verdicts belong entirely to `verification_intake_contract.py`/
`intake_state.py`; this module only reports them. It writes nothing but
events, and it authorizes nothing: no approval, no question, no Blackboard
topic, no state file.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .verification_intake_contract import IntakeContractState
from .intake_state import IntakeFieldStatus

SCHEMA_VERSION = "1.0"


class IntakeEventError(ValueError):
    """Raised by `emit()` for a name outside the fixed eighteen, and by
    `assert_intake_event_taxonomy_total()` for a taxonomy that has drifted
    out of total/partitioned/duplicate-free shape."""


# ---------------------------------------------------------------------------
# Section 1: the fixed 18-event taxonomy
# ---------------------------------------------------------------------------

#: One event per real `IntakeContractState` (13) -- named for the state being
#: ENTERED, exactly the convention `loop_telemetry.LOOP_STATE_TO_EVENT`
#: already uses ("a real loop STATE... emitted around it"). Total over
#: `IntakeContractState` in both directions, checked below.
INTAKE_CONTRACT_STATE_TO_EVENT: Dict[str, str] = {
    IntakeContractState.CREATED.value: "INTAKE_CREATED",
    IntakeContractState.DISCOVERING.value: "INTAKE_DISCOVERY_STARTED",
    IntakeContractState.CORRELATING.value: "INTAKE_CORRELATION_STARTED",
    IntakeContractState.QUESTION_PENDING.value: "INTAKE_QUESTION_PENDING",
    IntakeContractState.USER_INPUT_RECEIVED.value: "INTAKE_USER_INPUT_RECEIVED",
    IntakeContractState.VALIDATING.value: "INTAKE_VALIDATION_STARTED",
    IntakeContractState.CONFLICT.value: "INTAKE_CONFLICT_DETECTED",
    IntakeContractState.PARTIAL.value: "INTAKE_PARTIAL_DETECTED",
    IntakeContractState.BLOCKED.value: "INTAKE_BLOCKED",
    IntakeContractState.READY_FOR_REVIEW.value: "INTAKE_READY_FOR_REVIEW",
    IntakeContractState.BASELINED.value: "INTAKE_BASELINED",
    IntakeContractState.STALE.value: "INTAKE_STALE_DETECTED",
    IntakeContractState.REVALIDATING.value: "INTAKE_REVALIDATION_STARTED",
}

#: The five remaining events, over `intake_state.py`'s own real per-run
#: findings -- never a sixth/seventh "routine" status. Only the two genuinely
#: actionable per-field findings (BLOCKED / CONTRADICTED) mint their own
#: event; AUTO_RESOLVED/USER_CONFIRMED/PARTIAL/MISSING/UNKNOWN/NOT_APPLICABLE
#: do not, the same way `loop_telemetry.py` names a real reason for the loop
#: states that mint no section-108 event rather than silently widening the
#: vocabulary.
INTAKE_STATE_BUILT = "INTAKE_STATE_BUILT"
INTAKE_FIELD_BLOCKED = "INTAKE_FIELD_BLOCKED"
INTAKE_FIELD_CONTRADICTED = "INTAKE_FIELD_CONTRADICTED"
INTAKE_GENERATION_READY = "INTAKE_GENERATION_READY"
INTAKE_GENERATION_BLOCKED = "INTAKE_GENERATION_BLOCKED"

INTAKE_STATE_EVENTS: Tuple[str, ...] = (
    INTAKE_STATE_BUILT,
    INTAKE_FIELD_BLOCKED,
    INTAKE_FIELD_CONTRADICTED,
    INTAKE_GENERATION_READY,
    INTAKE_GENERATION_BLOCKED,
)

#: The fixed eighteen, in declaration order -- THIS tuple IS the vocabulary:
#: `emit()` refuses anything outside it, mirroring `loop_telemetry.
#: LOOP_TELEMETRY_EVENTS`'s own "a typo cannot quietly become a twentieth
#: event nobody reads" guarantee.
INTAKE_EVENTS: Tuple[str, ...] = tuple(INTAKE_CONTRACT_STATE_TO_EVENT.values()) + INTAKE_STATE_EVENTS


def assert_intake_event_taxonomy_total() -> None:
    """Import-time guard, holding three facts structurally rather than by
    comment:

      1. `INTAKE_CONTRACT_STATE_TO_EVENT` is total over `IntakeContractState`
         -- every real state maps to exactly one event, and the mapping names
         no key outside that enum -- so a state added to that machine later
         without a decision here fails a test rather than silently emitting
         nothing.
      2. the eighteen names partition exactly into "one per contract state"
         (13) and "one per intake_state.py finding" (5) -- no overlap, no
         orphan name outside either set.
      3. `INTAKE_EVENTS` really is eighteen names long, with no duplicate."""
    known_states = {s.value for s in IntakeContractState}
    mapped_states = set(INTAKE_CONTRACT_STATE_TO_EVENT)
    missing = sorted(known_states - mapped_states)
    if missing:
        raise IntakeEventError(
            f"IntakeContractState members with no mapped event: {missing}")
    extra = sorted(mapped_states - known_states)
    if extra:
        raise IntakeEventError(
            f"INTAKE_CONTRACT_STATE_TO_EVENT names non-IntakeContractState keys: {extra}")
    contract_events = set(INTAKE_CONTRACT_STATE_TO_EVENT.values())
    state_events = set(INTAKE_STATE_EVENTS)
    overlap = sorted(contract_events & state_events)
    if overlap:
        raise IntakeEventError(
            f"contract-state events and intake_state.py events collide: {overlap}")
    if len(INTAKE_EVENTS) != 18:
        raise IntakeEventError(
            f"INTAKE_EVENTS must carry exactly 18 names, has {len(INTAKE_EVENTS)}: "
            f"{list(INTAKE_EVENTS)}")
    if len(set(INTAKE_EVENTS)) != len(INTAKE_EVENTS):
        raise IntakeEventError(f"INTAKE_EVENTS carries a duplicate name: {list(INTAKE_EVENTS)}")


assert_intake_event_taxonomy_total()


def event_for_contract_state(state: str) -> str:
    """The INTAKE_* event naming `state`. Raises on a state outside
    `IntakeContractState` rather than guessing."""
    if state not in INTAKE_CONTRACT_STATE_TO_EVENT:
        raise IntakeEventError(
            f"unknown intake contract state {state!r}; must be one of "
            f"{sorted(INTAKE_CONTRACT_STATE_TO_EVENT)}")
    return INTAKE_CONTRACT_STATE_TO_EVENT[state]


# ---------------------------------------------------------------------------
# Section 2: the writer half
# ---------------------------------------------------------------------------

def emit(store: Any, event: str, **payload: Any) -> Dict[str, Any]:
    """Write ONE INTAKE_* event through the real `storage.StateStore.
    event()` -- there is no second events file, no second audit trail and no
    second serializer. `store` is a real `StateStore` (or any object
    exposing the same `.event(dict)` method, for a test double); this module
    has no writer of its own. An event name outside the fixed eighteen
    raises rather than being written -- an unrecognized name in
    `.dv-harness/events.jsonl` would be dropped silently by
    `read_intake_events()` and the emitter would look like it had reported
    something."""
    if event not in INTAKE_EVENTS:
        raise IntakeEventError(
            f"{event!r} is not one of the eighteen INTAKE_* events: {list(INTAKE_EVENTS)}")
    from .engine import now  # the one timestamp format every event in this file uses
    record: Dict[str, Any] = {"ts": now(), "event": event}
    record.update(payload)
    store.event(record)
    return record


def _emit_failed(store: Any, attempted: Optional[str], exc: Exception,
                  **extra: Any) -> None:
    """Best-effort failure record, mirroring `engine.py`'s own
    `_emit_loop_event()` two-level try/except exactly: a failure to emit a
    real INTAKE_* event is itself recorded, and a failure to record THAT
    never propagates either."""
    try:
        from .engine import now
        store.event({"ts": now(), "event": "INTAKE_EVENT_EMIT_FAILED",
                     "attempted_event": attempted,
                     "error": f"{type(exc).__name__}: {exc}", **extra})
    except Exception:
        pass


def emit_contract_transition(
    store: Any,
    contract: Any,
    *,
    from_state: Optional[str] = None,
    reason: Optional[str] = None,
    by: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Best-effort wrapper called from `verification_intake_contract.
    create_contract()`/`transition_contract()`. Emits the one event that
    names `contract.state` -- the state just entered. Returns `None`
    (writing nothing) when `store` is `None`: emission is opt-in, see the
    module docstring. A real emission failure records
    `INTAKE_EVENT_EMIT_FAILED` and never propagates."""
    if store is None:
        return None
    try:
        event = event_for_contract_state(contract.state)
        return emit(store, event, contract_id=contract.contract_id,
                     from_state=from_state, to_state=contract.state,
                     reason=reason, by=by)
    except Exception as exc:
        _emit_failed(store, getattr(contract, "state", None), exc,
                     contract_id=getattr(contract, "contract_id", None))
        return None


def emit_intake_state_report(store: Any, intake_state: Any) -> List[Dict[str, Any]]:
    """Best-effort wrapper called from `intake_state.build_intake_state()`.
    Emits ONE `INTAKE_STATE_BUILT` summary (field count + a per-status
    count, so "nothing was blocked" is itself a real, recorded fact) plus
    one `INTAKE_FIELD_BLOCKED` / `INTAKE_FIELD_CONTRADICTED` per field that
    actually carries that status -- never for the five routine statuses, and
    never a fabricated finding for a field that carries none. Returns the
    events it wrote (`[]` when `store` is `None`, or on a caught failure)."""
    if store is None:
        return []
    written: List[Dict[str, Any]] = []
    try:
        records = list(getattr(intake_state, "records", None) or [])
        counts: Dict[str, int] = {}
        for r in records:
            counts[r.status] = counts.get(r.status, 0) + 1
        written.append(emit(
            store, INTAKE_STATE_BUILT,
            field_count=len(records), status_counts=counts,
            generated_at=getattr(intake_state, "generated_at", None),
        ))
        for r in records:
            if r.status == IntakeFieldStatus.BLOCKED.value:
                written.append(emit(store, INTAKE_FIELD_BLOCKED,
                                     field=r.field, category=r.category,
                                     owner=r.owner, reason=r.reason))
            elif r.status == IntakeFieldStatus.CONTRADICTED.value:
                written.append(emit(store, INTAKE_FIELD_CONTRADICTED,
                                     field=r.field, category=r.category,
                                     owner=r.owner, reason=r.reason))
    except Exception as exc:
        _emit_failed(store, INTAKE_STATE_BUILT, exc)
    return written


def emit_generation_readiness(store: Any, readiness: Any) -> Optional[Dict[str, Any]]:
    """Best-effort wrapper called from `intake_state.
    evaluate_uvm_generation_ready()`. Emits EXACTLY ONE of
    `INTAKE_GENERATION_READY` / `INTAKE_GENERATION_BLOCKED` -- the two are
    mutually exclusive by `UvmGenerationReadiness.ready`'s own definition,
    the same "exactly one terminal event" guarantee `loop_telemetry.py`
    already holds for `TERMINAL_LOOP_EVENTS` on a loop session. Returns
    `None` (writing nothing) when `store` is `None`."""
    if store is None:
        return None
    try:
        ready = bool(getattr(readiness, "ready", False))
        blocking = getattr(readiness, "blocking", None) or {}
        event = INTAKE_GENERATION_READY if ready else INTAKE_GENERATION_BLOCKED
        return emit(store, event, checked_at=getattr(readiness, "checked_at", None),
                     blocking_categories=sorted(blocking))
    except Exception as exc:
        _emit_failed(store, "INTAKE_GENERATION_READY_OR_BLOCKED", exc)
        return None


# ---------------------------------------------------------------------------
# Section 3: the reader half -- reuses loop_telemetry's shared events.jsonl
# parser rather than adding a third one beside it and `dashboard._tail_events()`.
# ---------------------------------------------------------------------------

def read_intake_events(root: Any, *, scan_lines: Optional[int] = None
                       ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Only the INTAKE_* entries out of `.dv-harness/events.jsonl`, oldest
    first, plus the scan's own stats. Reuses `loop_telemetry.read_events()`
    -- the same public generic parser `platform_health.py` already reuses --
    rather than adding a third events.jsonl reader beside it and
    `dashboard._tail_events()`."""
    from . import loop_telemetry as _lt
    kwargs: Dict[str, Any] = {} if scan_lines is None else {"scan_lines": scan_lines}
    entries, scanned, truncated = _lt.read_events(root, **kwargs)
    picked = [e for e in entries if e.get("event") in INTAKE_EVENTS]
    return picked, {"lines_scanned": scanned, "scan_truncated": truncated,
                    "intake_events": len(picked)}


# ---------------------------------------------------------------------------
# Ad hoc front door -- no `dv-harness` CLI verb: `cli.py` is a large file
# under concurrent edit pressure, the same disclosed choice several recent
# modules in this codebase already make. `python -m` is the sanctioned
# fallback.
# ---------------------------------------------------------------------------

def execute_verb(root: Any, verb: str, *, as_json: bool = False) -> Tuple[int, Any]:
    """One implementation behind `python -m dv_harness.intake_events`, the
    same shared-`execute_verb()` convention `loop_contract`/`loop_budget`/
    `loop_telemetry` follow."""
    if verb == "names":
        payload = {"intake_events": list(INTAKE_EVENTS),
                   "contract_state_to_event": INTAKE_CONTRACT_STATE_TO_EVENT,
                   "state_events": list(INTAKE_STATE_EVENTS)}
        return 0, payload
    if verb == "events":
        picked, stats = read_intake_events(root)
        return (0 if picked else 2), {"events": picked, "scan": stats,
                                      "intake_events": list(INTAKE_EVENTS)}
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["names", "events"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.intake_events",
        description="The fixed 18-event INTAKE_* taxonomy over "
                    ".dv-harness/events.jsonl.")
    p.add_argument("verb", choices=["names", "events"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    code, payload = execute_verb(args.project_root, args.verb, as_json=args.json)
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str)
          if args.json else payload)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
