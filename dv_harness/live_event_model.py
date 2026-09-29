"""Web Control Plane theme (CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md sections 342-402): the
GUI Live Event Model -- an eleven-name, CLOSED vocabulary of GUI-facing live events, plus
`emit()`/reader functions. Data model + emit/read ONLY. The actual push-to-browser transport
(a WebSocket/SSE server, a browser-side subscriber) is a separate, later item and is
deliberately not built here.

WHAT WAS MISSING, verified before a line of this was written. A repo-wide grep for
`live_event`/`LiveEvent`/`GUI_LIVE_EVENT`/`GuiLiveEvent` across this project (including
`.work/*.md` gap-close reports) returned zero hits outside one forward reference in
`dv_harness/harness_status_event_wiring.py`'s own docstring, which explicitly disclosed this
module as a real, not-yet-landed dependency ("the sibling `live_event_model`-themed module...
has genuinely NOT landed yet in this checkout") and built an interim substitute
(`poll_and_recompute_on_new_loop_events()`, over `loop_telemetry.py`'s real section-108 event
stream) rather than guess at this module's interface. `CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md`
itself -- the document this task's own section ~385 citation refers to -- does not exist
anywhere in this repository checkout (confirmed by `Glob`/`find` before writing this module,
per this project's own "typed filename may not match disk exactly" lesson); it is evidently an
external planning document this session has no access to. So, exactly as
`dv_harness/question_queue.py`'s own `ESCALATION_PACKAGE_FIELDS` docstring discloses for the
identical situation ("this repository checkout does not carry the literal spec-section-32
document text... the field NAMES are this module's own defensible synthesis"), the eleven
event names below are THIS MODULE's OWN DEFENSIBLE SYNTHESIS, not a verbatim transcription of a
document this checkout cannot read. What is NOT a guess, and is enforced rather than merely
narrated: every one of the eleven names is anchored to a REAL, ALREADY-BUILT backend mechanism
this repository ships today (cited on each event's own line below) -- so a GUI subscribing to
this vocabulary is subscribing to facts real modules already produce, never to an invented
signal with no producer.

WHAT THIS MODULE IS. Two halves, mirroring `loop_telemetry.py`'s own nineteen-event pattern
EXACTLY (same writer discipline, same reader discipline, same honesty contract) -- reused as a
PATTERN, never imported as code, because that module's own vocabulary is section-108's loop
telemetry, a different, already-closed domain this module must not silently widen:

  * the WRITER half -- `GUI_LIVE_EVENTS` (the fixed, closed vocabulary) plus `emit()`, which
    writes through the SAME real `storage.StateStore.event()` every other subsystem in this
    harness writes to. There is no second event file, no second audit trail and no second
    serializer; `dv-harness audit`, `GET /api/audit`, `dashboard._tail_events()` and
    `loop_telemetry.read_loop_telemetry()` all see these events the instant they are emitted,
    the identical guarantee `loop_telemetry.py`'s own header already states for its own events.
  * the READER half -- `read_events()` (a thin re-export of `loop_telemetry.read_events`, the
    module's own PUBLIC generic events.jsonl reader, reused rather than a THIRD independent
    parser beside it and `dashboard._tail_events()` -- `loop_telemetry.py`'s own header already
    names this exact reuse discipline: "a module that needs the SAME trailing window of
    `.dv-harness/events.jsonl` reuses this one parser instead of adding a third") and
    `list_gui_live_events()`, which filters that trailing window down to this module's own
    eleven names (optionally further narrowed by a specific event name/set, a `source`, a
    `since_ts` floor and a result `limit`) and reports an honest `available: False` -- naming
    the real file it read and the real producer (the transport/dispatch layer this item's own
    scope excludes) that would populate it -- when nothing has ever been emitted. An honest
    empty state, never a fabricated one; see the module's own negative-control test for this.

WHAT THIS MODULE DELIBERATELY DOES NOT DO.

  * It does not BUILD a transport. No WebSocket server, no Server-Sent-Events endpoint, no
    browser-side subscriber, no polling loop of its own -- `emit()`/`read_events()`/
    `list_gui_live_events()` are library calls a future transport layer invokes, exactly the
    boundary this task's own instruction draws ("the actual push-to-browser transport is a
    separate later item").
  * It does not DERIVE any GUI fact. Every field a GUI_* event carries is the payload the real
    producing subsystem already computed (a stage's own gate verdict, a question-queue record,
    a `ControlPlane` approval, a section-108 loop-telemetry event, a coverage sample, an LSF job
    state, a waiver's derived status, a dashboard control command) -- this module never
    re-derives, re-classifies or re-scores any of it. A caller that wants to emit a GUI_* event
    hands `emit()` the real payload it already has; this module only enforces that the EVENT
    NAME is one of the fixed eleven and that it lands in the one real audit trail.
  * It writes nothing but events, and it authorizes nothing. Emitting/reading a GUI live event
    is not a mutating act on the project's own verification state: no approval, no question, no
    Blackboard topic, no state file, no gate. `ControlPlane.approve()`, `policy.can_signoff()`
    and every human-approval mechanism in this codebase are untouched and unreferenced here.

WHY A SEPARATE MODULE RATHER THAN MORE OF `loop_telemetry.py`. `loop_telemetry.py` owns
section-108's LOOP vocabulary (nineteen names, one `LoopState` bridge, one Loop Engineering
Center reader) -- a different, already-closed domain with its own producer (`engine.loop()`)
and its own consumer (the Loop Engineering Center card). This module's eleven names are a
DIFFERENT, GUI-wide vocabulary (stage/gate/human-gate/question/approval/loop-telemetry-bridge/
coverage/LSF/waiver/control-command) with a different, wider set of real producers across this
whole harness, not just the verification-closure loop. Folding an eleventh vocabulary into
`loop_telemetry.py`'s own fixed nineteen would either silently widen that already-closed
section-108 list (which its own `emit()` refuses to do -- "the module refuses anything outside
it, so a typo cannot quietly become a twentieth event nobody reads") or require a second,
incompatible meaning for the identical function name. A separate module keeps both closed
vocabularies independently checkable, and keeps `LOOP_TELEMETRY_EVENTS`'s own
`assert_events_match_section_108()` self-check meaningful.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import Status

# --------------------------------------------------------------------------
# The eleven-name vocabulary
# --------------------------------------------------------------------------
#: The fixed, CLOSED GUI live-event vocabulary. `emit()` refuses anything outside it, the same
#: closed-vocabulary discipline `loop_telemetry.LOOP_TELEMETRY_EVENTS` already applies to
#: section 108's nineteen names -- a typo here cannot quietly become a twelfth event nobody
#: reads. Each name is anchored, in order, to the REAL backend mechanism this repository ships
#: today that would supply its payload; a GUI subscribing to this vocabulary is never
#: subscribing to an invented signal with no producer.
GUI_LIVE_EVENTS: Tuple[str, ...] = (
    # engine.DVHarness.run_stage()'s own PASS/FAIL/RETRY/... verdict on `state.json`.
    "GUI_STAGE_STATUS_CHANGED",
    # engine.DVHarness.advance()/loop() moving `current_stage` to the next graph node.
    "GUI_STAGE_TRANSITIONED",
    # gates.evaluate_stage_evidence()'s own per-gate PASS/FAIL/BLOCKED verdict.
    "GUI_GATE_VERDICT_RECORDED",
    # loop_contract.LoopState.HUMAN_GATE / a stage reaching Status.WAIT_USER -- a human
    # decision is now owed before the run can continue.
    "GUI_HUMAN_GATE_OPENED",
    # question_queue.QuestionQueueStore.add_question()/answer_question() changing the queue.
    "GUI_QUESTION_QUEUE_UPDATED",
    # control_plane.ControlPlane.approve() recording a real human approval.
    "GUI_APPROVAL_RECORDED",
    # loop_telemetry.emit()'s own section-108 event stream -- the bridge that lets a GUI
    # subscribe to the Loop Engineering Center's real telemetry through this ONE wider
    # vocabulary instead of a second, loop-specific subscription.
    "GUI_LOOP_TELEMETRY_EMITTED",
    # dashboard.append_coverage_history_sample()/evidence_db.insert_coverage_sample() -- a
    # real coverage summary was ingested.
    "GUI_COVERAGE_SAMPLE_INGESTED",
    "GUI_LSF_JOB_STATUS_CHANGED",   # lsf_client.py reconciling a real JobState transition.
    "GUI_WAIVER_STATUS_CHANGED",    # waiver_store.record_waiver()/revoke_waiver() / a waiver's
                                    # own derive_status() moving (e.g. VALID -> EXPIRED).
    "GUI_CONTROL_COMMAND_EXECUTED", # a real dashboard POST /api/control command dispatched
                                    # through dashboard_auth.py's role-gated command map.
)


class GuiLiveEventError(ValueError):
    """Raised by `emit()` for a name outside the fixed eleven, or by a malformed payload."""


def assert_gui_live_events_total() -> None:
    """The vocabulary is exactly eleven names, with no duplicate -- run at import so a future
    edit that silently widens or narrows it fails a test rather than drifting unnoticed."""
    if len(GUI_LIVE_EVENTS) != 11:
        raise AssertionError(
            f"GUI_LIVE_EVENTS must carry exactly 11 names; found {len(GUI_LIVE_EVENTS)}: "
            f"{list(GUI_LIVE_EVENTS)}")
    if len(set(GUI_LIVE_EVENTS)) != len(GUI_LIVE_EVENTS):
        seen: List[str] = []
        dupes = []
        for n in GUI_LIVE_EVENTS:
            (dupes if n in seen else seen).append(n)
        raise AssertionError(f"GUI_LIVE_EVENTS carries duplicate name(s): {dupes}")


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabulary shares no token with `models.Status` -- the same guard
    several sibling modules in this codebase already apply to their own domain vocabularies, so
    a GUI event name can never be mistaken for (or silently collide with) a stage verdict."""
    collisions = set(GUI_LIVE_EVENTS) & {s.value for s in Status}
    if collisions:
        raise AssertionError(
            f"GUI_LIVE_EVENTS collides with dv_harness.models.Status: {sorted(collisions)}")


assert_gui_live_events_total()
assert_no_verification_verdict_vocabulary()


# --------------------------------------------------------------------------
# The writer half
# --------------------------------------------------------------------------
def emit(store, event: str, *,
         source: Optional[str] = None,
         **payload: Any) -> Dict[str, Any]:
    """Write ONE GUI live event through the real `storage.StateStore.event()`.

    `store` is a real `storage.StateStore` (or any object exposing an `.event(dict)` method of
    the identical shape); this module has no writer of its own and no second audit file. An
    event name outside the fixed eleven raises rather than being written -- an unrecognized
    name in `.dv-harness/events.jsonl` is worse than no event, because `list_gui_live_events()`
    would drop it silently and the caller would look like it had reported something.

    `source` names which real backend mechanism produced this event (e.g. `"engine.run_stage"`,
    `"question_queue.answer_question"`, `"dashboard.control_command"`) -- optional, but every
    real caller should supply it, since it is what lets a GUI (or a human reading the audit
    trail) tell two events of the same TYPE apart by their real origin. `**payload` is whatever
    real fields the caller's own already-computed fact carries (a stage name, a gate id, a
    question id, a job id, ...); this function never inspects or validates payload content
    beyond requiring it to be JSON-serializable, since validating a payload's CONTENT is the
    real producing subsystem's own job, not this vocabulary's."""
    if event not in GUI_LIVE_EVENTS:
        raise GuiLiveEventError(
            f"{event!r} is not one of the eleven GUI live events: {list(GUI_LIVE_EVENTS)}")
    from .engine import now  # the one timestamp format every event in this harness uses
    record: Dict[str, Any] = {"ts": now(), "event": event}
    if source is not None:
        record["source"] = str(source)
    record.update(payload)
    try:
        json.dumps(record, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise GuiLiveEventError(f"payload for {event!r} is not JSON-serializable: {e}") from e
    store.event(record)
    return record


# --------------------------------------------------------------------------
# The reader half
# --------------------------------------------------------------------------
#: How many trailing `events.jsonl` lines the reader scans by default -- the same cap
#: `loop_telemetry.DEFAULT_EVENT_SCAN_LINES` uses, reused verbatim rather than a second number
#: that could silently disagree with it.
DEFAULT_EVENT_SCAN_LINES = 20000

#: The honest empty-state reason, naming the real producer this item's own scope excludes.
NO_GUI_LIVE_EVENTS = "NO_GUI_LIVE_EVENTS_RECORDED"


def read_events(root: Path, *, scan_lines: int = DEFAULT_EVENT_SCAN_LINES
                ) -> Tuple[List[Dict[str, Any]], int, bool]:
    """The trailing `scan_lines` parsed entries of `.dv-harness/events.jsonl`.

    A THIN RE-EXPORT of `loop_telemetry.read_events` (that module's own public alias for its
    `_read_events()`), reused rather than a third independent events.jsonl parser beside it and
    `dashboard._tail_events()` -- exactly the reuse discipline `loop_telemetry.py`'s own header
    names for a future module in this exact position. Returns
    `(entries, lines_scanned, truncated)`, unchanged from that function's own contract."""
    from .loop_telemetry import read_events as _shared_read_events
    return _shared_read_events(root, scan_lines=scan_lines)


def gui_live_events(root: Path, *, scan_lines: int = DEFAULT_EVENT_SCAN_LINES,
                    event_names: Optional[Sequence[str]] = None
                    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Only the entries whose `event` is one of `event_names` (default: all eleven), oldest
    first, plus the scan's own stats -- the identical shape `loop_telemetry.loop_events()`
    returns for section 108's own vocabulary."""
    if event_names is None:
        names = set(GUI_LIVE_EVENTS)
    else:
        unknown = [n for n in event_names if n not in GUI_LIVE_EVENTS]
        if unknown:
            raise GuiLiveEventError(
                f"event_names names value(s) outside the eleven GUI live events: {unknown}")
        names = set(event_names)
    entries, scanned, truncated = read_events(root, scan_lines=scan_lines)
    picked = [e for e in entries if e.get("event") in names]
    return picked, {"lines_scanned": scanned, "scan_truncated": truncated,
                    "scan_limit": scan_lines, "gui_live_events": len(picked)}


def list_gui_live_events(root: Path, *,
                         event: Optional[str] = None,
                         events: Optional[Sequence[str]] = None,
                         source: Optional[str] = None,
                         since_ts: Optional[str] = None,
                         limit: Optional[int] = None,
                         scan_lines: int = DEFAULT_EVENT_SCAN_LINES
                         ) -> Dict[str, Any]:
    """List/filter recorded GUI live events over `.dv-harness/events.jsonl`.

    `event` narrows to one specific name; `events` narrows to a set of names (mutually
    exclusive with `event` -- supplying both raises); `source` narrows to one real producer
    string (an exact match against whatever `emit()`'s own caller supplied); `since_ts`
    (inclusive, ISO-8601 string-compared, the same format `engine.now()` produces) drops any
    event whose own `ts` sorts before it; `limit` keeps only the most recent `limit` matches
    (newest last, matching the file's own append order) so a GUI asking "what changed just
    now" does not have to page through a whole project's history.

    A project whose GUI live events have never been emitted -- true of EVERY project today,
    since the transport/dispatch layer that would call `emit()` is this item's own excluded,
    later scope -- reports `available: False` naming the real events.jsonl path and the real
    reason (`NO_GUI_LIVE_EVENTS_RECORDED`), never a fabricated empty-but-clean result. This
    function reads; it writes nothing, files nothing and authorizes nothing."""
    if event is not None and events is not None:
        raise GuiLiveEventError("supply `event` or `events`, never both")
    root = Path(root)
    events_file = root / ".dv-harness" / "events.jsonl"
    name_filter: Optional[Sequence[str]]
    if event is not None:
        if event not in GUI_LIVE_EVENTS:
            raise GuiLiveEventError(
                f"{event!r} is not one of the eleven GUI live events: {list(GUI_LIVE_EVENTS)}")
        name_filter = (event,)
    else:
        name_filter = events

    picked, stats = gui_live_events(root, scan_lines=scan_lines, event_names=name_filter)
    if source is not None:
        picked = [e for e in picked if e.get("source") == source]
    if since_ts is not None:
        picked = [e for e in picked if str(e.get("ts") or "") >= since_ts]
    if limit is not None and limit >= 0:
        picked = picked[-limit:]

    base: Dict[str, Any] = {
        "available": False,
        "events_file": str(events_file),
        "event_names": list(GUI_LIVE_EVENTS),
        "events": [],
        "scan": stats,
        "reason": "",
    }
    if not picked:
        base["reason"] = (
            f"{NO_GUI_LIVE_EVENTS}: no GUI live event has been written to {events_file}. "
            f"This item builds only the data model and emit()/read functions; the real "
            f"producer is the (separate, later) push-to-browser transport/dispatch layer, "
            f"which must call live_event_model.emit(store, <one of the eleven names>, ...) as "
            f"real backend facts occur.")
        return base

    base["available"] = True
    base["events"] = picked
    return base


# --------------------------------------------------------------------------
# Front door
# --------------------------------------------------------------------------
def execute_verb(root: Path, verb: str, *,
                 event: Optional[str] = None,
                 events: Optional[Sequence[str]] = None,
                 source: Optional[str] = None,
                 since_ts: Optional[str] = None,
                 limit: Optional[int] = None,
                 ) -> Tuple[int, Any]:
    """One implementation behind `python -m dv_harness.live_event_model` -- the same shared
    `execute_verb()` convention `loop_contract`/`loop_budget`/`loop_telemetry` already follow.
    No `dv-harness` CLI verb is registered: `cli.py` was under concurrent edit by other parallel
    work in this same session, the same disclosed choice several sibling same-day modules in
    this codebase already make."""
    root = Path(root)
    if verb == "names":
        return 0, {"event_names": list(GUI_LIVE_EVENTS)}
    if verb in ("events", "list"):
        payload = list_gui_live_events(root, event=event, events=events, source=source,
                                       since_ts=since_ts, limit=limit)
        return (0 if payload.get("available") else 2), payload
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["names", "events", "list"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI shim
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m dv_harness.live_event_model",
        description="The GUI Live Event Model's eleven-name vocabulary, and a reader over its "
                    "real .dv-harness/events.jsonl trail.")
    p.add_argument("verb", choices=["names", "events", "list"])
    p.add_argument("--project-root", default=".")
    p.add_argument("--event", default=None)
    p.add_argument("--events", default=None,
                   help="comma-separated subset of the eleven event names")
    p.add_argument("--source", default=None)
    p.add_argument("--since-ts", default=None)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)
    events_arg = args.events.split(",") if args.events else None
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 event=args.event, events=events_arg, source=args.source,
                                 since_ts=args.since_ts, limit=args.limit)
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
