"""dv_harness/lifecycle.py -- the persistent project lifecycle model of the
Standard Flow (INTAKE_FIRST -> ... -> COMPLETE).

Why a separate model. `models.Status` is the per-STAGE verdict vocabulary and
`loop_contract.py` maps every Status member to a LoopState; a new Status value
falls through every `if status in (...)` chain. The 16 project milestones below
describe how far the WHOLE PROJECT has progressed, which is a different
question, so they live here, in `.dv-harness/lifecycle.json`, and never in
`Status`. `test_lifecycle.py` guards that the two vocabularies stay disjoint.

What is recorded. Every accepted transition is appended to `history` with
from_state / to_state / trigger / evidence / producer / consumer / timestamp /
result and is also emitted through `event_sink` (the engine passes
`StateStore.event`, so it lands in events.jsonl as `LIFECYCLE_TRANSITION`).
`state.json`'s single overwritten `last_transition` is not the audit trail.

Transition rules. Forward moves follow `_FORWARD` only, so intake cannot be
skipped on the way to generation. Any move to an EARLIER milestone is a REWIND
(a new gap found, a failed run, a V2 regeneration) and is always allowed and
always recorded. A refused transition raises `LifecycleError` and writes nothing.

Bypasses. An advanced/manual command that goes around the intake-first gate is
recorded with `record_bypass()`; it never moves the milestone.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

LIFECYCLE_FILE = "lifecycle.json"
SCHEMA_VERSION = 1

EVENT_TRANSITION = "LIFECYCLE_TRANSITION"
EVENT_BYPASS = "LIFECYCLE_BYPASS"


class LifecycleError(Exception):
    """A lifecycle file is missing/corrupt, or a transition is not legal."""


class Milestone(str, Enum):
    INTAKE_CREATED = "INTAKE_CREATED"
    USER_INPUT_REQUIRED = "USER_INPUT_REQUIRED"
    INTAKE_LOADED = "INTAKE_LOADED"
    INTAKE_PARTIAL = "INTAKE_PARTIAL"
    INTAKE_READY = "INTAKE_READY"
    OPENSPEC_READY = "OPENSPEC_READY"
    PLAN_READY = "PLAN_READY"
    GENERATED = "GENERATED"
    BUILD_PASS = "BUILD_PASS"
    SIM_PASS = "SIM_PASS"
    REGRESSION_PASS = "REGRESSION_PASS"
    COVERAGE_READY = "COVERAGE_READY"
    SIGNOFF_READY = "SIGNOFF_READY"
    QUALIFICATION_COMPARE = "QUALIFICATION_COMPARE"
    KC_LEARNING = "KC_LEARNING"
    COMPLETE = "COMPLETE"


_ORDER: List[Milestone] = list(Milestone)

# Legal FORWARD moves. Anything to an earlier milestone is a rewind instead.
_FORWARD: Dict[Milestone, frozenset] = {
    Milestone.INTAKE_CREATED: frozenset({
        Milestone.USER_INPUT_REQUIRED, Milestone.INTAKE_LOADED,
        Milestone.INTAKE_PARTIAL, Milestone.INTAKE_READY}),
    Milestone.USER_INPUT_REQUIRED: frozenset({
        Milestone.INTAKE_LOADED, Milestone.INTAKE_PARTIAL, Milestone.INTAKE_READY}),
    Milestone.INTAKE_LOADED: frozenset({Milestone.INTAKE_PARTIAL, Milestone.INTAKE_READY}),
    Milestone.INTAKE_PARTIAL: frozenset({Milestone.INTAKE_READY}),
    Milestone.INTAKE_READY: frozenset({Milestone.OPENSPEC_READY}),
    Milestone.OPENSPEC_READY: frozenset({Milestone.PLAN_READY}),
    Milestone.PLAN_READY: frozenset({Milestone.GENERATED}),
    Milestone.GENERATED: frozenset({Milestone.BUILD_PASS}),
    Milestone.BUILD_PASS: frozenset({Milestone.SIM_PASS}),
    Milestone.SIM_PASS: frozenset({Milestone.REGRESSION_PASS}),
    # Coverage is off by default, so signoff may follow regression directly.
    Milestone.REGRESSION_PASS: frozenset({Milestone.COVERAGE_READY, Milestone.SIGNOFF_READY}),
    Milestone.COVERAGE_READY: frozenset({Milestone.SIGNOFF_READY}),
    Milestone.SIGNOFF_READY: frozenset({Milestone.QUALIFICATION_COMPARE, Milestone.COMPLETE}),
    Milestone.QUALIFICATION_COMPARE: frozenset({Milestone.KC_LEARNING}),
    Milestone.KC_LEARNING: frozenset({Milestone.COMPLETE}),
    Milestone.COMPLETE: frozenset(),
}

# Facts the lifecycle carries beside the milestone. Anything else is refused so
# a typo cannot silently create a field nothing reads.
_FACT_KEYS = frozenset({
    "verification_level", "level_source", "protocols", "subsystems",
    "environment_mode", "protocol_route", "goal", "resume_stage",
    "adopted_from_legacy", "level_question_id", "protocol_source",
    "intake_package", "intake_clarification_ids",
    # GAP-V2-002 remediation (CAP-M6-GAPV2002-001): which role the DUT
    # plays in the protocol a generation request targets (host/device,
    # RC/EP, TX/RX, ...) -- see generation_field_controls.py's own
    # ROLE_FIELD_ID for the real Field Resolution wiring this persists.
    "role",
})

EventSink = Callable[[str, Dict[str, Any]], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_milestone(value: Any) -> Milestone:
    try:
        return Milestone(value.value if isinstance(value, Milestone) else value)
    except ValueError as exc:
        raise LifecycleError(
            f"unknown lifecycle milestone {value!r}; valid values: "
            f"{[m.value for m in Milestone]}") from exc


class LifecycleStore:
    """Reads/writes `<root>/.dv-harness/lifecycle.json` atomically."""

    def __init__(self, root: Path, *, event_sink: Optional[EventSink] = None):
        self.root = Path(root)
        self.path = self.root / ".dv-harness" / LIFECYCLE_FILE
        self._sink = event_sink

    # ------------------------------------------------------------------ io
    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> Dict[str, Any]:
        if not self.exists():
            raise LifecycleError(
                f"no lifecycle at {self.path}; a new project is created by "
                f"`dv-harness start` (INTAKE_FIRST)")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LifecycleError(f"lifecycle file {self.path} is unreadable: {exc}") from exc
        _as_milestone(data.get("milestone"))
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".lifecycle-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _emit(self, name: str, payload: Dict[str, Any]) -> None:
        if self._sink is not None:
            self._sink(name, dict(payload))

    # -------------------------------------------------------------- reading
    @property
    def milestone(self) -> Milestone:
        return _as_milestone(self.load().get("milestone"))

    # -------------------------------------------------------------- writing
    @staticmethod
    def _record(from_state: Optional[str], to_state: str, trigger: str, producer: str,
                consumer: str, evidence: Iterable[str], result: str) -> Dict[str, Any]:
        return {
            "from_state": from_state,
            "to_state": to_state,
            "trigger": trigger,
            "evidence": [str(e) for e in evidence],
            "producer": producer,
            "consumer": consumer,
            "timestamp": _now(),
            "result": result,
        }

    def create(self, *, trigger: str, producer: str, consumer: str = "",
               evidence: Iterable[str] = (), **facts: Any) -> Dict[str, Any]:
        if self.exists():
            raise LifecycleError(
                f"lifecycle already exists at {self.path}; refusing to reset its history")
        if not trigger or not producer:
            raise ValueError("create() needs a non-empty trigger and producer")
        self._check_facts(facts)
        rec = self._record(None, Milestone.INTAKE_CREATED.value, trigger, producer,
                           consumer, evidence, "CREATED")
        data: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "milestone": Milestone.INTAKE_CREATED.value,
            "history": [rec],
            "bypasses": [],
        }
        data.update(facts)
        self._write(data)
        self._emit(EVENT_TRANSITION, rec)
        return data

    def transition(self, to: Any, *, trigger: str, producer: str, consumer: str = "",
                   evidence: Iterable[str] = ()) -> Dict[str, Any]:
        if not trigger or not producer:
            raise ValueError("a lifecycle transition needs a non-empty trigger and producer")
        target = _as_milestone(to)
        data = self.load()
        current = _as_milestone(data["milestone"])
        if _ORDER.index(target) < _ORDER.index(current):
            result = "REWOUND"
        elif target in _FORWARD[current]:
            result = "ADVANCED"
        else:
            raise LifecycleError(
                f"illegal lifecycle transition {current.value} -> {target.value}; "
                f"legal forward moves from {current.value}: "
                f"{sorted(m.value for m in _FORWARD[current])}")
        rec = self._record(current.value, target.value, trigger, producer, consumer,
                           evidence, result)
        data["milestone"] = target.value
        data["history"].append(rec)
        self._write(data)
        self._emit(EVENT_TRANSITION, rec)
        return rec

    def update_facts(self, **facts: Any) -> Dict[str, Any]:
        self._check_facts(facts)
        data = self.load()
        data.update(facts)
        self._write(data)
        return data

    def record_bypass(self, command: str, *, from_stage: str, to_stage: str,
                      reason: str) -> Dict[str, Any]:
        data = self.load()
        entry = {
            "command": command, "from_stage": from_stage, "to_stage": to_stage,
            "reason": reason, "milestone": data["milestone"], "timestamp": _now(),
        }
        data.setdefault("bypasses", []).append(entry)
        self._write(data)
        self._emit(EVENT_BYPASS, entry)
        return entry

    @staticmethod
    def _check_facts(facts: Dict[str, Any]) -> None:
        unknown = sorted(set(facts) - _FACT_KEYS)
        if unknown:
            raise LifecycleError(
                f"unknown lifecycle fact(s) {unknown}; allowed: {sorted(_FACT_KEYS)}")
