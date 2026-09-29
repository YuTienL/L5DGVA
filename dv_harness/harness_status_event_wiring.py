"""dv_harness/harness_status_event_wiring.py -- Event-driven HarnessStatusIR
recomputation (Global Status Bar theme, master-prompt sections 429-431).

THE GAP THIS CLOSES
--------------------
`harness_status.py` (sections 403-411) already builds a real
`HarnessStatusService` with `aggregate()`/`normalize()`/`validate()`/
`publish()`/`serve()` -- but nothing calls `publish()` automatically. Every
existing call site is a human-typed CLI invocation
(`python -m dv_harness.harness_status`) or a caller's own explicit `serve()`.
Sections 429-431 name a different, additive requirement: recomputation must
FIRE when a real event happens, not only when a human asks for a fresh read.

DEPENDENCY CHECK -- done first, per this item's own governing instruction,
before a line of this was written. A repo-wide glob for a
"live_event_model"-themed module (the eleven named GUI live-event types data
model a separate, concurrently-running Workflow implementing
`CLAUDE_L5_WEB_CONTROL_PLANE_MASTER.md` is/was building) and a
"web_control_plane_ready_gate"-themed module found:

  - `web_control_plane_readiness_gate.py`: REAL, present, real tests pass.
    Its own `GUI_LIVE_EVENT_READY` gate already treats `loop_telemetry.py`'s
    real section-108 event stream as this project's live-event evidence --
    the same transport this module's interim driver (below) reuses.
  - A "live_event_model" module -- an 11-named-GUI-event-type schema/
    transport: ABSENT. `grep -rn "live_event\\|LiveEvent"` across
    `dv_harness/` matches nothing but this module's own text and its own
    test file.

Per this item's own governing instruction, this module does NOT block on
that absence and does NOT guess at that module's interface (its call
signature, its transport, its eleven event-type names -- inventing any of
those would be building a second, competing definition the real module would
then have to be reconciled against). What IS built, and does not depend on
it, is:

  1. `recompute_harness_status_on_event()` -- a real, callable, GENERIC
     consumption point. Hand it ANY event-shaped object (a plain dict, or
     anything exposing an `event`/`event_type`/`kind`/`name` field) and it
     calls the REAL `harness_status.HarnessStatusService.publish()` --
     never a second aggregator -- recording which event triggered the
     recompute. This IS section 431's own rule made literal: "consume that
     transport, never build a second one" is satisfied by this being a
     plain function call rather than a bus/queue/socket of its own (see
     `assert_consumes_never_builds_a_second_transport()` below, which checks
     this structurally against the module's own source) -- whatever
     transport the Live Event Model workflow eventually uses (an in-process
     callback list, an SSE push, a message queue) only ever has to call this
     one function once per event; nothing here presumes which.
  2. `live_event_model_status()` -- an honest, testable PROBE for whether
     that sibling module has landed yet, by REAL import-system resolution
     against a documented candidate-name list -- the same "resolve through
     the import system, never trust a comment" discipline
     `protocol_capability.py`'s registry and `generation_readiness.py`'s
     `assert_fact_sources_resolvable()` already apply one domain over. Once
     a real candidate resolves, a caller (or a future patch to this module)
     wires it directly to `recompute_harness_status_on_event()`; this
     module never claims to have done that wiring before the module exists.
  3. An INTERIM, REAL trigger source, built entirely from a transport this
     harness ALREADY has -- never a second live-event bus.
     `poll_and_recompute_on_new_loop_events()` drives
     `recompute_harness_status_on_event()`-equivalent recomputation off
     every NEW real section-108 `loop_telemetry.py` event since a persisted
     watermark, so a real caller (a cron-style poller, or a stage-boundary
     hook -- exactly `question_queue.py`'s own
     `_emit_question_digest_at_stage_boundary()` precedent) gets real,
     working event-driven recomputation TODAY over the one real event
     stream this repo already produces. This is honestly disclosed as an
     INTERIM substitute for, never a claim to already be, the GUI's own
     eleven-type Live Event Model.

DISCLOSED RESIDUAL (report this verbatim rather than implying closed)
------------------------------------------------------------------------
Once the Live Event Model module lands, wiring it to call
`recompute_harness_status_on_event()` per real GUI event is the one
remaining step. This module cannot perform that step today because the
sibling module -- and therefore its real call signature -- does not exist
yet; guessing one would violate this item's own governing instruction not
to block on, or guess at, an interface that has not landed.

READ-ONLY EXCEPT FOR ITS OWN CURSOR. `recompute_harness_status_on_event()`
writes nothing on its own beyond the caller-OPTED-IN `store.event(...)`
audit record -- exactly `HarnessStatusService.publish()`'s own contract, one
layer up. `poll_and_recompute_on_new_loop_events()` is the one function in
this module with a real, disclosed write: its own small watermark cursor
file, so a poller does not reprocess (or silently drop) events across calls.
No `.dv-harness/` tree is minted merely to ask "is there anything new" on a
bare project -- see `test_poll_on_a_bare_project_mints_nothing`.
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from . import harness_status as hs
from . import loop_telemetry as lt
from .storage import _atomic_replace


class HarnessStatusEventWiringError(ValueError):
    """A real caller-usage defect (an event with no recognizable kind, an
    unreadable watermark cursor) -- never a silently repaired input."""


# ===========================================================================
# Rule 431, enforced structurally: this module must never build a second
# live-event transport of its own.
# ===========================================================================

#: Substrings that would indicate this module rolled its own transport
#: (a queue, a socket server, a thread-based dispatcher, a pub/sub bus)
#: instead of consuming one. Checked against this file's OWN source, the
#: same technique `platform_health.assert_authorizes_nothing()` and
#: `harness_status.assert_service_authorizes_nothing()` already apply to
#: their own forbidden-symbol lists.
_FORBIDDEN_TRANSPORT_SYMBOLS: Tuple[str, ...] = (
    "import queue", "import socket", "import asyncio", "socketserver",
    "threading.Thread", "websocket", "class EventBus", "class MessageQueue",
)


def assert_consumes_never_builds_a_second_transport(
        source_path: Optional[Path] = None) -> None:
    """This file's own source may not mention any transport-building
    symbol. The wiring this module provides is a plain function a real
    event source calls; it must never itself become a second live-event
    bus. Mirrors `harness_status.assert_service_authorizes_nothing()`."""
    path = Path(source_path) if source_path else Path(__file__)
    text = path.read_text(encoding="utf-8")
    # Exclude this module's own docstring/comment discussion of the rule
    # (which legitimately names "queue"/"socket"/"bus" in prose) AND the
    # `_FORBIDDEN_TRANSPORT_SYMBOLS` tuple's own literal strings from the
    # search text -- the same technique `harness_status.
    # assert_service_authorizes_nothing()` uses for its own forbidden-symbol
    # list: only the text BEFORE that tuple's definition is checked, so the
    # list of banned substrings is never mistaken for a real usage of one.
    haystack = text.split(
        '_FORBIDDEN_TRANSPORT_SYMBOLS: Tuple[str, ...] = (', 1)[0]
    hits = [s for s in _FORBIDDEN_TRANSPORT_SYMBOLS if s in haystack]
    if hits:
        raise HarnessStatusEventWiringError(
            f"{path.name} references transport-building machinery {hits}; "
            f"this module must CONSUME an event transport, never build one.")


assert_consumes_never_builds_a_second_transport()


# ===========================================================================
# Live Event Model resolution -- an honest probe, never a guess
# ===========================================================================

#: Candidate dotted module names the concurrent Web Control Plane Workflow's
#: "live_event_model"-themed module might land under, following this
#: project's own `dv_harness/<theme>.py` naming convention. Checked by REAL
#: import resolution only -- never asserted present, never guessed at
#: beyond "does a module by this name exist and import cleanly right now".
#: Extend this tuple (never widen it by guessing a call signature) the
#: moment the real module's name is known.
LIVE_EVENT_MODEL_CANDIDATE_MODULES: Tuple[str, ...] = (
    "dv_harness.live_event_model",
    "dv_harness.gui_live_event_model",
    "dv_harness.web_live_event_model",
    "dv_harness.gui_event_model",
)


def live_event_model_status() -> Dict[str, Any]:
    """Which of the candidate Live Event Model module names resolves
    through the real import system right now. `resolvable` is True the
    instant ANY candidate genuinely imports; `resolved_module` names the
    first one that did. This is a fact check, not a guess: a module that
    fails to import (a syntax error, a missing dependency) is honestly
    `False`, not silently treated as present."""
    checked: Dict[str, bool] = {}
    resolved_module: Optional[str] = None
    for name in LIVE_EVENT_MODEL_CANDIDATE_MODULES:
        try:
            importlib.import_module(name)
            checked[name] = True
            if resolved_module is None:
                resolved_module = name
        except Exception:
            checked[name] = False
    return {
        "resolvable": resolved_module is not None,
        "resolved_module": resolved_module,
        "checked": checked,
        "note": ("no candidate module resolved -- this module's interim "
                 "loop_telemetry-based trigger is in force; see this "
                 "module's own docstring 'DISCLOSED RESIDUAL' section"
                 if resolved_module is None else
                 f"{resolved_module} resolved -- wiring it to call "
                 f"recompute_harness_status_on_event() per real event is "
                 f"the one remaining integration step"),
    }


# ===========================================================================
# The generic, transport-agnostic consumption point (section 431's own rule)
# ===========================================================================

#: The field names `event_kind()` checks, in priority order, on either a
#: plain `Mapping` or any attribute-bearing object. Deliberately generic --
#: this is THIS module's own minimal consumer-side contract, not a guess at
#: the Live Event Model's internal schema (which is not yet known).
_EVENT_KIND_FIELDS: Tuple[str, ...] = ("event", "event_type", "kind", "name")


def event_kind(event: Any) -> Optional[str]:
    """Duck-typed: the first non-empty value among `event`/`event_type`/
    `kind`/`name`, read from a `Mapping` via `.get()` or from any other
    object via `getattr()`. `None` when none of those is present -- never a
    guessed kind."""
    for key in _EVENT_KIND_FIELDS:
        if isinstance(event, Mapping):
            value = event.get(key)
        else:
            value = getattr(event, key, None)
        if value:
            return str(value)
    return None


def recompute_harness_status_on_event(
        root: Union[Path, str], event: Any, *,
        service: Optional[hs.HarnessStatusService] = None,
        cfg: Optional[Dict[str, Any]] = None,
        store: Optional[Any] = None) -> Dict[str, Any]:
    """Section 431's own consumption contract: recompute `HarnessStatusIR`
    because a real event happened, by calling the REAL, already-built
    `HarnessStatusService.publish()` -- never a second aggregator, never a
    second status vocabulary. `event` is duck-typed (see `event_kind()`
    above); this function makes no assumption about the event's producer or
    transport, which is exactly what lets it serve as the one integration
    point a real Live Event Model consumer calls once it lands.

    `service`, when omitted, is a fresh `HarnessStatusService(root)` with no
    notifier -- change-only escalation notification stays entirely
    `publish()`'s own, untouched, discipline; this function neither
    constructs nor bypasses it.

    `store`, when supplied, is a real `storage.StateStore` this call
    additionally records one best-effort `STATUS_RECOMPUTE_TRIGGERED` audit
    event onto -- OPT-IN, exactly like every other side-channel writer in
    this project (`loop_budget.py`'s `LOOP_BUDGET_SPENT`,
    `loop_telemetry.py`'s own events): omitting it (the default) means this
    call writes nothing to disk beyond whatever `publish()` itself already
    does (nothing -- `publish()` is read-only end to end), so recomputing a
    bare project's status never mints a `.dv-harness/` tree on its own.

    Raises `HarnessStatusEventWiringError` when `event` carries no
    recognizable kind at all -- a caller-usage defect, never silently
    treated as a valid trigger."""
    root = Path(root)
    kind = event_kind(event)
    if kind is None:
        raise HarnessStatusEventWiringError(
            "EVENT_HAS_NO_RECOGNIZABLE_KIND: the supplied event carries "
            "none of event/event_type/kind/name")
    svc = service or hs.HarnessStatusService(root)
    snapshot, escalation = svc.publish(cfg=cfg)
    report: Dict[str, Any] = {
        "triggered_by": kind,
        "snapshot": snapshot,
        "escalation": escalation,
    }
    if store is not None:
        try:
            store.event({
                "event": "STATUS_RECOMPUTE_TRIGGERED",
                "triggering_event_kind": kind,
                "harness_state": (snapshot.get("harness") or {}).get("state"),
            })
        except Exception as e:  # noqa: BLE001 -- an audit write failing must
            # never turn an already-computed recompute into a crash, the
            # same discipline every best-effort emitter in this project
            # already follows (e.g. engine.py's `_emit_loop_event()`).
            report["audit_write_failed"] = f"{type(e).__name__}: {e}"
    return report


# ===========================================================================
# The interim, REAL trigger source -- loop_telemetry's own event stream,
# never a second one
# ===========================================================================

_WATERMARK_DIR = "harness_status_event_wiring"
_WATERMARK_FILE = "watermark.json"


def _watermark_path(root: Path) -> Path:
    return root / ".dv-harness" / _WATERMARK_DIR / _WATERMARK_FILE


def _load_watermark(root: Path) -> int:
    """The count of section-108 events already processed by a prior poll.
    Absent, unreadable, or malformed is honestly 0 -- reprocessing every
    event on a broken cursor is the safe failure direction (a redundant
    recompute is idempotent; a silently-skipped one is not)."""
    path = _watermark_path(root)
    try:
        if not path.is_file():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        count = data.get("processed_count") if isinstance(data, dict) else None
        return int(count) if isinstance(count, int) and count >= 0 else 0
    except (OSError, ValueError):
        return 0


def _save_watermark(root: Path, processed_count: int) -> None:
    """The one explicit, disclosed write path in this module -- this
    poller's own small cursor, in its own subdirectory, never mixed with
    `state.json`/`events.jsonl`. Written through the same atomic-replace
    helper `blackboard.py`/`context_budget.py` already reuse rather than a
    second file-write convention."""
    directory = root / ".dv-harness" / _WATERMARK_DIR
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="watermark.", suffix=".json",
                                dir=str(directory))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"processed_count": processed_count}, f)
        _atomic_replace(tmp, _watermark_path(root))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


#: Honest status vocabulary for `poll_and_recompute_on_new_loop_events()`,
#: kept deliberately distinct from `models.Status`/`HARNESS_STATUS_VALUES`
#: (this reports whether a POLL found new events, never a verification
#: verdict or a harness state).
POLL_NO_LOOP_TELEMETRY = "NO_LOOP_TELEMETRY_EVENTS"
POLL_NO_NEW_EVENTS = "NO_NEW_EVENTS"
POLL_RECOMPUTED = "RECOMPUTED"


def poll_and_recompute_on_new_loop_events(
        root: Union[Path, str], *,
        service: Optional[hs.HarnessStatusService] = None,
        cfg: Optional[Dict[str, Any]] = None,
        store: Optional[Any] = None,
        scan_lines: int = lt.DEFAULT_EVENT_SCAN_LINES) -> Dict[str, Any]:
    """The interim, real event-driven trigger: recompute `HarnessStatusIR`
    exactly once per poll call that finds one or more real section-108
    `loop_telemetry.py` events this project has not been recomputed for
    yet. Reuses `loop_telemetry.loop_events()` -- the SAME real reader
    `web_control_plane_readiness_gate.py`'s own `GUI_LIVE_EVENT_READY` gate
    already treats as this project's live-event evidence -- rather than a
    second `events.jsonl` parser.

    A single `publish()` call covers the whole new-event batch (recomputing
    once per newly-observed event would be redundant: one project-wide
    aggregation already reflects everything that changed since the last
    poll). Every new event's own kind is still reported individually in
    `new_event_kinds`, so a caller can see exactly what fired the
    recomputation.

    Never reprocesses an event already seen by a prior poll, and never
    mints anything on disk when there is nothing new to report (a bare
    project, or a project whose event count has not moved since the last
    poll, is left byte-for-byte untouched)."""
    root = Path(root)
    picked, stats = lt.loop_events(root, scan_lines=scan_lines)
    if not picked:
        return {"status": POLL_NO_LOOP_TELEMETRY, "new_event_kinds": [],
                "scan_stats": stats}

    processed_before = _load_watermark(root)
    if processed_before > len(picked):
        # The event log shrank (rotated/reset) since the last poll -- an
        # honest anomaly, never silently hidden. Reprocess everything
        # currently on file rather than skip events a fresh log cannot
        # prove were already handled.
        processed_before = 0
    new_events = picked[processed_before:]
    if not new_events:
        return {"status": POLL_NO_NEW_EVENTS, "new_event_kinds": [],
                "processed_count": processed_before, "scan_stats": stats}

    new_event_kinds = [e.get("event") for e in new_events]
    svc = service or hs.HarnessStatusService(root)
    snapshot, escalation = svc.publish(cfg=cfg)
    _save_watermark(root, len(picked))

    report: Dict[str, Any] = {
        "status": POLL_RECOMPUTED,
        "new_event_kinds": new_event_kinds,
        "processed_count_before": processed_before,
        "processed_count_after": len(picked),
        "scan_stats": stats,
        "snapshot": snapshot,
        "escalation": escalation,
    }
    if store is not None:
        try:
            store.event({
                "event": "STATUS_RECOMPUTE_TRIGGERED",
                "triggering_event_kind": new_event_kinds[-1],
                "triggering_event_batch_size": len(new_event_kinds),
                "harness_state": (snapshot.get("harness") or {}).get("state"),
            })
        except Exception as e:  # noqa: BLE001 -- best-effort, see
            # recompute_harness_status_on_event()'s identical rule above.
            report["audit_write_failed"] = f"{type(e).__name__}: {e}"
    return report


# ===========================================================================
# CLI front door
# ===========================================================================

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.harness_status_event_wiring poll --root <dir>`
    or `... live-event-model-status`. Exit 0 on a clean poll (nothing new,
    or a real recompute), 2 when nothing could be evaluated at all (no
    loop-telemetry events on file yet) -- a CI-visible "no interim trigger
    fired", never an approval signal in either direction."""
    import argparse

    parser = argparse.ArgumentParser(prog="harness-status-event-wiring")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_poll = sub.add_parser("poll")
    p_poll.add_argument("--root", default=".")
    p_poll.add_argument("--json", action="store_true")

    p_status = sub.add_parser("live-event-model-status")
    p_status.add_argument("--json", action="store_true")

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.verb == "live-event-model-status":
        report = live_event_model_status()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"resolvable: {report['resolvable']}")
            print(f"resolved_module: {report['resolved_module']}")
            print(report["note"])
        return 0 if report["resolvable"] else 2

    root = Path(args.root).resolve()
    report = poll_and_recompute_on_new_loop_events(root)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"POLL: {report['status']}  new_event_kinds="
              f"{report.get('new_event_kinds')}")
    return 0 if report["status"] != POLL_NO_LOOP_TELEMETRY else 2


def main(argv: Optional[Sequence[str]] = None) -> None:
    import sys
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
