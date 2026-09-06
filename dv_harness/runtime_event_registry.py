"""dv_harness/runtime_event_registry.py -- a registry of NAMED RUNTIME EVENTS
with dependency-graph stop-on-failure propagation.

GAP THIS CLOSES. A generated pattern's task composition (`.claude/skills/CORE/
pattern-architecture/SKILL.md`'s `block`/`branch_a*`/`branch_fw`/`branch_b*`
five-layer shape) and its interrupt-driven service loop
(`interrupt-event-dispatch/SKILL.md`'s ARM/WAIT/WAKE/DECODE/CLEAR loop) both
produce and consume NAMED RUNTIME EVENTS -- a global bring-up completing, a
per-port DUT+PHY init finishing, an interrupt being seen and then serviced, a
branch_b* VIP scenario finishing its check. Nothing in this repo tracked those
events as a first-class registry with a dependency graph: `blackboard.py`
stores free-form named TOPICS, not typed events with a producer/consumer/
timeout/scope; `loop_contract.py`/`loop_budget.py` track the HARNESS's own
loop state, not a generated environment's runtime event flow; `connectivity.py`
tracks structural bind confidence, not runtime event occurrence. A repo-wide
search for "event registry" / "REQUIRES" / "stop-on-failure" over `dv_harness/`
found no dependency-graph propagation mechanism for this at all -- an upstream
event that failed or timed out left every downstream event that depended on it
silently PENDING forever, with nothing distinguishing "still waiting" from
"can never happen because its prerequisite already failed".

WHAT THIS IS. `event_name`/`producer`/`consumer`/`payload`/`timeout`/`scope`/
`status` is the record shape (spec-declared), read over a caller-declared
EVENT SET plus a caller-declared set of RELATIONS between events
(REQUIRES/WAITS_FOR/TRIGGERS/UNBLOCKS -- see "Relation semantics" below). The
event set is NEVER hardcoded here: GLOBAL_READY/DUT_READY/VIP_STARTED/
IRQ_SEEN/IRQ_SERVICED/CHECK_DONE below are illustrative names only, matching
this repo's own `block`(GLOBAL_READY)/`branch_a*`(DUT_READY per port)/
`branch_fw`(IRQ_SEEN/IRQ_SERVICED)/`branch_b*`(VIP_STARTED)/verdict
(CHECK_DONE) vocabulary -- a different project's real event names (a
different protocol's real interrupt/handshake names) are declared by its
caller, exactly as `config_variant_coverage.py`'s dimensions are declared, not
guessed by this module.

WHAT THIS IS NOT. It does not parse a sim.log, does not decide whether an
event "really" occurred, and does not invent a timeout value or an interrupt
priority scheme. `sim_log_analysis.py` is the real sim.log parser in this
repo and stays the sole one; an event's OBSERVED status here is a fact the
caller supplies together with a real evidence citation (a sim.log line, an
`evidence_db` record id, a waveform offset) -- exactly like
`config_variant_coverage.CriticalCombination.reason` and
`waiver_store`'s revocation discipline, which also require a caller to name
real evidence rather than accept a bare claim. `loop_budget.py`'s
`FailureType` (why a *harness stage attempt* failed, retryable or not) is a
DIFFERENT, coarser vocabulary answering a different question and is
deliberately not reused or merged here -- this module's five-value STATUS
vocabulary is a per-runtime-event outcome, not a per-harness-stage-attempt
classification, and `assert_no_status_vocabulary_collision()` below checks the
two never share a token.

RELATION SEMANTICS (from_event, relation, to_event), read in the natural
direction of each verb -- REQUIRES/WAITS_FOR read dependent -> prerequisite
("B REQUIRES A" = B depends on A having already fired), TRIGGERS/UNBLOCKS
read cause -> effect ("A TRIGGERS B" = A firing causes B):
  - REQUIRES: a HARD dependency. If B REQUIRES A and A's status is
    FAILED/TIMEOUT (or itself BLOCKED_BY_DEPENDENCY), B is marked
    BLOCKED_BY_DEPENDENCY by `propagate()` -- the stop-on-failure propagation
    this module exists for -- unless an UNBLOCKS edge overrides it (below).
    Only an event whose OWN raw status is still PENDING (no real observation
    yet) can be overwritten this way; an event a caller has genuinely
    observed to have FIRED/FAILED/TIMED OUT keeps that real evidence, because
    overwriting an observed fact with a computed one would itself be a
    fabrication.
  - UNBLOCKS: a RECOVERY override. If C UNBLOCKS B and C's status is FIRED,
    B is NOT marked BLOCKED_BY_DEPENDENCY even if one of its REQUIRES
    prerequisites failed -- e.g. a documented recovery/retry event that
    genuinely supplies what the failed prerequisite would have. This is the
    one relation type consumed by the hard propagation rule besides REQUIRES.
  - WAITS_FOR: a SOFT temporal ordering, reported as an AT_RISK finding
    (an event waiting on a failed/blocked upstream) but never changes status
    -- e.g. `branch_fw`'s WAIT step waiting on an interrupt that a prior
    stage's failure makes unlikely, which is worth flagging without asserting
    it can never occur.
  - TRIGGERS: a forward causal edge, reported as an ORPHANED_TRIGGER finding
    when an event's only declared cause has failed/blocked and it has no
    REQUIRES prerequisite of its own -- informational, never a status change.

STOP-ON-FAILURE PROPAGATION, precisely. `propagate()` is a fixed-point over
the REQUIRES sub-graph (validated acyclic at construction -- a REQUIRES cycle
is a contradiction in the declaration, refused up front, the same discipline
`config_variant_coverage.ConfigSpace` applies to a critical combination its
own constraints forbid). An event flips PENDING -> BLOCKED_BY_DEPENDENCY only
when (a) its own raw status is still PENDING, (b) at least one REQUIRES
prerequisite is FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY, and (c) no UNBLOCKS
recovery event has FIRED. This is the section this module exists for: a
downstream event no longer sits silently PENDING forever once its
prerequisite has genuinely failed -- it carries an honest, distinct status
naming why.

CLI: `python -m dv_harness.runtime_event_registry graph|status --registry
<file.json> [--json]` -- one shared `execute_verb()`. `graph` prints the
declared events/relations only (no propagation); `status` runs `propagate()`
and prints the effective status + findings table. Exit 0 nothing
FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY, 1 at least one is, 2 NOT_AVAILABLE or a
usage/declaration error.

LIMITS, disclosed rather than implied closed:
  1. It DECIDES nothing beyond reporting: no gate, no build, no job, no
     approval. There is deliberately no stage gate.
  2. It does not observe anything itself. Whether GLOBAL_READY "really" FIRED
     is decided by the caller from real sim.log/waveform/evidence-db evidence
     BEFORE calling this module; a non-PENDING status with no `evidence`
     citation is refused rather than silently accepted.
  3. `timeout` is a caller-declared budget (from real project policy/RTL
     programming-guide evidence), never computed or defaulted by this module
     -- a missing timeout means "no declared budget", not "immediate".
  4. UNBLOCKS is the only recovery mechanism modelled; there is no notion of
     a partially-satisfied REQUIRES set (any-of vs. all-of) beyond "at least
     one failed prerequisite blocks, unless recovered" -- a project needing
     OR-semantics across several alternative prerequisites declares them via
     UNBLOCKS rather than a second REQUIRES flavor this module does not have.
  5. The fixed-point loop is O(events x relations) per iteration, bounded by
     the acyclic REQUIRES graph's own longest chain -- adequate for a
     pattern's real event count (tens, not thousands); it is not built for a
     whole-farm event stream.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dv_harness.connectivity import render_markdown_table

SCHEMA_VERSION = "1.0"

REGISTRY_REPORT_PARTS = (".dv-harness", "runtime_events", "propagation_report.json")


def _now() -> str:
    """Same UTC-ISO stamp `regression_tiers._now()`/`config_variant_coverage._now()`
    already use -- duplicated as a 2-line local helper for the same reason: this
    module stays importable by a gate subprocess without pulling the engine in."""
    return datetime.now(timezone.utc).isoformat()


class EventRegistryError(ValueError):
    """A declared event set/relation set/observation that cannot be honoured
    as written: a duplicate event name, a relation naming an unknown event, a
    self-referential relation, a REQUIRES cycle, a non-PENDING status with no
    evidence citation, or a caller trying to directly assert the COMPUTED-ONLY
    BLOCKED_BY_DEPENDENCY status. Every one of these is a contradiction in the
    caller's own declaration and is surfaced, never silently resolved."""


class EventStatus(str, Enum):
    """Five values. PENDING: declared, not yet observed. FIRED: observed to
    have occurred (a success outcome for that event). FAILED: observed to
    have occurred as an error/mismatch. TIMEOUT: observed to have NOT
    occurred within its declared timeout budget. BLOCKED_BY_DEPENDENCY:
    COMPUTED ONLY by `propagate()` -- never a caller-declared observation --
    naming that this event can no longer meaningfully be waited on because a
    hard (REQUIRES) prerequisite already failed or timed out."""

    PENDING = "PENDING"
    FIRED = "FIRED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    BLOCKED_BY_DEPENDENCY = "BLOCKED_BY_DEPENDENCY"


#: Statuses a caller may declare as an initial OBSERVATION. BLOCKED_BY_DEPENDENCY
#: is deliberately excluded -- it is `propagate()`'s own conclusion, and a
#: caller asserting it directly would be asserting a propagation result nobody
#: computed, exactly the kind of invented verdict the Evidence Truth Rule
#: forbids.
OBSERVABLE_STATUSES: Tuple[EventStatus, ...] = (
    EventStatus.PENDING, EventStatus.FIRED, EventStatus.FAILED, EventStatus.TIMEOUT,
)

#: Statuses that make a downstream REQUIRES-dependent event unable to
#: meaningfully proceed. BLOCKED_BY_DEPENDENCY is included so the propagation
#: is transitive (a chain of REQUIRES edges cascades).
BLOCKING_STATUSES: Tuple[EventStatus, ...] = (
    EventStatus.FAILED, EventStatus.TIMEOUT, EventStatus.BLOCKED_BY_DEPENDENCY,
)


class EventRelationType(str, Enum):
    """See the module docstring's "Relation semantics" for the direction
    convention and exactly which relation types the propagation rule
    consumes (REQUIRES + UNBLOCKS) vs. which are informational-only
    (WAITS_FOR, TRIGGERS)."""

    REQUIRES = "REQUIRES"
    WAITS_FOR = "WAITS_FOR"
    TRIGGERS = "TRIGGERS"
    UNBLOCKS = "UNBLOCKS"


RELATION_TYPE_VALUES: Tuple[str, ...] = tuple(r.value for r in EventRelationType)


def assert_no_status_vocabulary_collision() -> None:
    """`loop_budget.FailureType` answers "why did a harness STAGE ATTEMPT
    fail" (retryable or not); `EventStatus` answers "what happened to one
    RUNTIME EVENT" -- deliberately different, non-merged vocabularies per the
    module docstring. Import is local and best-effort: `loop_budget` is a
    large, unrelated module and this module must not fail to import if it is
    ever moved/renamed -- the check simply does not run in that case, and a
    real collision introduced later would still be caught whenever
    `loop_budget` IS importable (this project's own test suite always has
    it)."""
    try:
        from dv_harness.loop_budget import FailureType  # noqa: PLC0415
    except Exception:
        return
    failure_values = {t.value for t in FailureType}
    status_values = {s.value for s in EventStatus}
    overlap = failure_values & status_values
    if overlap:
        raise AssertionError(
            f"EventStatus shares token(s) {sorted(overlap)!r} with loop_budget.FailureType -- "
            "these are two deliberately separate vocabularies (see module docstring); a shared "
            "token means a reader could mistake one for the other.")


assert_no_status_vocabulary_collision()


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class RuntimeEventDef:
    """One declared runtime event: `event_name`/`producer`/`consumer`/
    `payload`/`timeout`/`scope`, per this module's own record shape.
    `producer`/`consumer` are free-text component identifiers (e.g. "block",
    "branch_a0", "branch_fw_port1", "vip_host_agent0") -- this module does
    not know or enforce any particular project's `block`/`branch_a*`/
    `branch_fw`/`branch_b*` naming, it only carries whatever the caller
    declares. `source` is the real evidence citation for WHY this event is
    declared (an interrupt-event-dispatch ARM/WAIT/WAKE/DECODE/CLEAR loop
    reference, a controller programming-guide section, a real prior sim.log
    line) -- required-in-spirit and carried through, never enforced non-empty
    here (an event's existence claim is weaker than an observation's, which
    IS enforced -- see RuntimeEventObservation)."""

    event_name: str
    producer: str
    consumer: Tuple[str, ...]
    payload: Mapping[str, Any] = field(default_factory=dict)
    timeout: Optional[float] = None
    scope: str = "GLOBAL"
    source: str = ""

    def __post_init__(self) -> None:
        if not _is_nonempty_str(self.event_name):
            raise EventRegistryError("a runtime event needs a non-empty event_name")
        if not _is_nonempty_str(self.producer):
            raise EventRegistryError(f"event {self.event_name!r} declares no producer")
        if not self.consumer or not all(_is_nonempty_str(c) for c in self.consumer):
            raise EventRegistryError(
                f"event {self.event_name!r} declares no consumer, or a blank one -- an event "
                "nobody consumes cannot participate in any dependency relation")
        if not isinstance(self.payload, Mapping):
            raise EventRegistryError(
                f"event {self.event_name!r} payload must be a JSON object, got {type(self.payload).__name__}")
        if self.timeout is not None:
            if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool):
                raise EventRegistryError(
                    f"event {self.event_name!r} timeout must be a number of seconds or null, "
                    f"got {self.timeout!r}")
            if self.timeout <= 0:
                raise EventRegistryError(
                    f"event {self.event_name!r} timeout must be > 0 (or null for 'no declared "
                    f"budget'), got {self.timeout!r}")
        if not _is_nonempty_str(self.scope):
            raise EventRegistryError(f"event {self.event_name!r} declares an empty scope")

    def to_dict(self) -> dict:
        return {
            "event_name": self.event_name,
            "producer": self.producer,
            "consumer": list(self.consumer),
            "payload": dict(self.payload),
            "timeout": self.timeout,
            "scope": self.scope,
            "source": self.source,
        }


@dataclass(frozen=True)
class RuntimeEventObservation:
    """A caller-supplied REAL observation of one event. `evidence` is
    required for every status but PENDING -- "no evidence yet" IS what
    PENDING means, so a FIRED/FAILED/TIMEOUT with an empty `evidence` is a
    contradiction in the declaration (an unsupported claim), refused rather
    than accepted, mirroring `waiver_store`'s "a waiver record missing its
    section-237 fields is UNKNOWN, never VALID" discipline for the same
    Evidence Truth Rule reason."""

    status: EventStatus
    evidence: str = ""
    observed_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in OBSERVABLE_STATUSES:
            raise EventRegistryError(
                f"status {self.status!r} may not be declared as an observation -- "
                f"BLOCKED_BY_DEPENDENCY is computed only by propagate(), never asserted directly "
                f"(asserting it would be asserting a propagation conclusion nobody computed)")
        if self.status != EventStatus.PENDING and not _is_nonempty_str(self.evidence):
            raise EventRegistryError(
                f"an observation of status {self.status.value} requires a non-empty `evidence` "
                "citation (a sim.log line, an evidence_db record id, a waveform offset) -- a "
                "status with no cited evidence is an unsupported claim, not a fact")

    def to_dict(self) -> dict:
        return {"status": self.status.value, "evidence": self.evidence, "observed_at": self.observed_at}


@dataclass(frozen=True)
class EventRelationDecl:
    """One declared relation `from_event <relation> to_event`. See the
    module docstring's "Relation semantics" for the direction convention.
    `reason` is carried through for review, same discipline as
    `config_variant_coverage.Constraint.reason`."""

    from_event: str
    relation: EventRelationType
    to_event: str
    reason: str = ""

    def __post_init__(self) -> None:
        if not _is_nonempty_str(self.from_event) or not _is_nonempty_str(self.to_event):
            raise EventRegistryError("a relation needs non-empty from_event and to_event")
        if self.from_event == self.to_event:
            raise EventRegistryError(
                f"relation {self.relation!r} on {self.from_event!r} is self-referential -- an "
                "event cannot depend on, trigger, wait for, or unblock itself")
        if not isinstance(self.relation, EventRelationType):
            raise EventRegistryError(
                f"relation {self.relation!r} is not one of {RELATION_TYPE_VALUES!r}")

    def to_dict(self) -> dict:
        return {"from_event": self.from_event, "relation": self.relation.value,
                "to_event": self.to_event, "reason": self.reason}


@dataclass
class RuntimeEventRegistry:
    """A declared event set + relation set + (optional) real observations.
    Construction validates structural integrity; `propagate()` computes the
    stop-on-failure propagation described in the module docstring."""

    registry_id: str
    events: Tuple[RuntimeEventDef, ...]
    relations: Tuple[EventRelationDecl, ...] = ()
    observations: Dict[str, RuntimeEventObservation] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if not _is_nonempty_str(self.registry_id):
            raise EventRegistryError("a runtime event registry needs a non-empty registry_id")
        if not self.events:
            raise EventRegistryError(f"registry {self.registry_id!r} declares no events")
        names = [e.event_name for e in self.events]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise EventRegistryError(f"registry {self.registry_id!r} declares duplicate event name(s): {dupes}")
        self._by_name: Dict[str, RuntimeEventDef] = {e.event_name: e for e in self.events}

        for rel in self.relations:
            if rel.from_event not in self._by_name:
                raise EventRegistryError(
                    f"relation {rel.relation.value} names unknown from_event {rel.from_event!r}")
            if rel.to_event not in self._by_name:
                raise EventRegistryError(
                    f"relation {rel.relation.value} names unknown to_event {rel.to_event!r}")

        for name in self.observations:
            if name not in self._by_name:
                raise EventRegistryError(f"observation names unknown event {name!r}")

        self._assert_requires_acyclic()

    # -- lookups ------------------------------------------------------------

    def event(self, name: str) -> RuntimeEventDef:
        try:
            return self._by_name[name]
        except KeyError:
            raise EventRegistryError(f"unknown event {name!r}") from None

    def raw_status(self, name: str) -> EventStatus:
        """The caller's own observed status, never overwritten by
        propagation -- PENDING when nothing has been observed yet."""
        self.event(name)
        obs = self.observations.get(name)
        return obs.status if obs else EventStatus.PENDING

    def _relations_of(self, relation: EventRelationType) -> List[EventRelationDecl]:
        return [r for r in self.relations if r.relation is relation]

    def requires_of(self, name: str) -> Tuple[str, ...]:
        """Prerequisite events `name` REQUIRES (name is the dependent)."""
        self.event(name)
        return tuple(r.to_event for r in self._relations_of(EventRelationType.REQUIRES) if r.from_event == name)

    def required_by(self, name: str) -> Tuple[str, ...]:
        """Dependent events that REQUIRE `name` (name is the prerequisite)."""
        self.event(name)
        return tuple(r.from_event for r in self._relations_of(EventRelationType.REQUIRES) if r.to_event == name)

    def waits_for_of(self, name: str) -> Tuple[str, ...]:
        self.event(name)
        return tuple(r.to_event for r in self._relations_of(EventRelationType.WAITS_FOR) if r.from_event == name)

    def triggered_by(self, name: str) -> Tuple[str, ...]:
        """Upstream events that declare a TRIGGERS edge into `name`."""
        self.event(name)
        return tuple(r.from_event for r in self._relations_of(EventRelationType.TRIGGERS) if r.to_event == name)

    def unblocked_by(self, name: str) -> Tuple[str, ...]:
        """Recovery events with an UNBLOCKS edge into `name`."""
        self.event(name)
        return tuple(r.from_event for r in self._relations_of(EventRelationType.UNBLOCKS) if r.to_event == name)

    # -- structural validation -----------------------------------------------

    def _assert_requires_acyclic(self) -> None:
        """A REQUIRES cycle (A requires B requires A) is a contradiction in
        the declaration, not something `propagate()` may silently resolve --
        refused up front, the same discipline
        `config_variant_coverage.ConfigSpace` applies to a critical
        combination its own constraints forbid."""
        graph: Dict[str, List[str]] = {e.event_name: [] for e in self.events}
        for r in self._relations_of(EventRelationType.REQUIRES):
            graph[r.from_event].append(r.to_event)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in graph}
        stack_path: List[str] = []

        def visit(node: str) -> None:
            color[node] = GRAY
            stack_path.append(node)
            for nxt in graph[node]:
                if color[nxt] == GRAY:
                    cycle = stack_path[stack_path.index(nxt):] + [nxt]
                    raise EventRegistryError(
                        f"registry {self.registry_id!r} has a REQUIRES cycle: {' -> '.join(cycle)} "
                        "-- an event cannot (transitively) require itself")
                if color[nxt] == WHITE:
                    visit(nxt)
            stack_path.pop()
            color[node] = BLACK

        for n in graph:
            if color[n] == WHITE:
                visit(n)

    # -- propagation ----------------------------------------------------------

    def propagate(self) -> "PropagationReport":
        """The stop-on-failure propagation described in the module
        docstring. Returns a PropagationReport carrying every event's
        effective status plus BLOCKED_BY_DEPENDENCY/AT_RISK/ORPHANED_TRIGGER
        findings, never mutating this registry's own recorded observations
        (raw evidence stays exactly what the caller supplied)."""
        raw = {name: self.raw_status(name) for name in self._by_name}
        effective: Dict[str, EventStatus] = dict(raw)
        blocking_cause: Dict[str, Tuple[str, ...]] = {}

        changed = True
        while changed:
            changed = False
            for name in self._by_name:
                if raw[name] != EventStatus.PENDING:
                    continue  # a real observation is never overwritten
                if effective[name] == EventStatus.BLOCKED_BY_DEPENDENCY:
                    continue  # already settled this round
                prereqs = self.requires_of(name)
                if not prereqs:
                    continue
                failed = tuple(p for p in prereqs if effective[p] in BLOCKING_STATUSES)
                if not failed:
                    continue
                recovered_by = tuple(u for u in self.unblocked_by(name) if effective.get(u) == EventStatus.FIRED)
                if recovered_by:
                    continue  # UNBLOCKS override: a recovery event genuinely fired
                effective[name] = EventStatus.BLOCKED_BY_DEPENDENCY
                blocking_cause[name] = failed
                changed = True

        findings: List[Dict[str, Any]] = []
        for name, causes in blocking_cause.items():
            findings.append({
                "finding": "BLOCKED_BY_DEPENDENCY",
                "event": name,
                "related_events": list(causes),
                "reason": f"{name} REQUIRES {', '.join(causes)}, which "
                          f"{'is' if len(causes) == 1 else 'are'} "
                          f"{'/'.join(sorted({effective[c].value for c in causes}))} and no UNBLOCKS "
                          "recovery event has FIRED",
            })

        for name in self._by_name:
            if raw[name] != EventStatus.PENDING or effective[name] == EventStatus.BLOCKED_BY_DEPENDENCY:
                continue
            at_risk_on = tuple(t for t in self.waits_for_of(name) if effective[t] in BLOCKING_STATUSES)
            if at_risk_on:
                findings.append({
                    "finding": "AT_RISK_WAITS_FOR_FAILED_UPSTREAM",
                    "event": name,
                    "related_events": list(at_risk_on),
                    "reason": f"{name} WAITS_FOR {', '.join(at_risk_on)}, currently "
                              f"{'/'.join(sorted({effective[t].value for t in at_risk_on}))} -- not blocked "
                              "(WAITS_FOR is a soft ordering), but unlikely to occur",
                })

        for name in self._by_name:
            if raw[name] != EventStatus.PENDING:
                continue
            causes = self.triggered_by(name)
            if not causes or self.requires_of(name):
                continue  # has its own hard prerequisite path, or no declared TRIGGERS cause at all
            if all(effective[c] in BLOCKING_STATUSES for c in causes):
                findings.append({
                    "finding": "ORPHANED_TRIGGER",
                    "event": name,
                    "related_events": list(causes),
                    "reason": f"{name}'s only declared TRIGGERS source(s) {', '.join(causes)} "
                              f"{'is' if len(causes) == 1 else 'are'} "
                              f"{'/'.join(sorted({effective[c].value for c in causes}))} -- no other "
                              "known cause remains for this event",
                })

        return PropagationReport(
            registry_id=self.registry_id,
            generated_at=_now(),
            raw_status={k: v.value for k, v in raw.items()},
            effective_status={k: v.value for k, v in effective.items()},
            findings=findings,
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "registry_id": self.registry_id,
            "description": self.description,
            "events": [e.to_dict() for e in self.events],
            "relations": [r.to_dict() for r in self.relations],
            "observations": {k: v.to_dict() for k, v in self.observations.items()},
        }


@dataclass
class PropagationReport:
    registry_id: str
    generated_at: str
    raw_status: Dict[str, str]
    effective_status: Dict[str, str]
    findings: List[Dict[str, Any]]

    def blocked_events(self) -> Tuple[str, ...]:
        return tuple(sorted(n for n, s in self.effective_status.items() if s == EventStatus.BLOCKED_BY_DEPENDENCY.value))

    def failed_or_timeout_events(self) -> Tuple[str, ...]:
        return tuple(sorted(n for n, s in self.raw_status.items()
                             if s in (EventStatus.FAILED.value, EventStatus.TIMEOUT.value)))

    def has_blocking_outcome(self) -> bool:
        return bool(self.blocked_events() or self.failed_or_timeout_events())

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "registry_id": self.registry_id,
            "generated_at": self.generated_at,
            "raw_status": dict(self.raw_status),
            "effective_status": dict(self.effective_status),
            "findings": list(self.findings),
        }


# ------------------------------------------------------------------------
# loading from a declared JSON shape
# ------------------------------------------------------------------------

def _relation_type_from_str(value: Any, *, where: str) -> EventRelationType:
    if isinstance(value, EventRelationType):
        return value
    try:
        return EventRelationType(str(value))
    except ValueError:
        raise EventRegistryError(
            f"{where}: unknown relation type {value!r}, expected one of {RELATION_TYPE_VALUES!r}") from None


def _status_from_str(value: Any, *, where: str) -> EventStatus:
    if isinstance(value, EventStatus):
        return value
    try:
        return EventStatus(str(value))
    except ValueError:
        raise EventRegistryError(
            f"{where}: unknown status {value!r}, expected one of "
            f"{[s.value for s in OBSERVABLE_STATUSES]!r}") from None


def registry_from_dict(data: Mapping[str, Any]) -> RuntimeEventRegistry:
    """Load a runtime event registry from its JSON shape. Every structural
    problem raises EventRegistryError naming the offending declaration --
    nothing is silently defaulted, because a mistyped event name that quietly
    became a new event would compute propagation over the wrong graph."""
    if not isinstance(data, Mapping):
        raise EventRegistryError("registry declaration must be a JSON object")

    registry_id = data.get("registry_id")
    if not _is_nonempty_str(registry_id):
        raise EventRegistryError("registry declaration needs a non-empty registry_id")

    raw_events = data.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise EventRegistryError(f"registry {registry_id!r} declares no 'events' list")
    events = []
    for i, e in enumerate(raw_events):
        if not isinstance(e, Mapping):
            raise EventRegistryError(f"events[{i}] must be a JSON object")
        consumer = e.get("consumer", [])
        if isinstance(consumer, str):
            consumer = [consumer]
        events.append(RuntimeEventDef(
            event_name=e.get("event_name", ""),
            producer=e.get("producer", ""),
            consumer=tuple(consumer),
            payload=e.get("payload", {}) or {},
            timeout=e.get("timeout"),
            scope=e.get("scope", "GLOBAL"),
            source=e.get("source", ""),
        ))

    raw_relations = data.get("relations", []) or []
    if not isinstance(raw_relations, list):
        raise EventRegistryError(f"registry {registry_id!r}: 'relations' must be a list")
    relations = []
    for i, r in enumerate(raw_relations):
        if not isinstance(r, Mapping):
            raise EventRegistryError(f"relations[{i}] must be a JSON object")
        relations.append(EventRelationDecl(
            from_event=r.get("from_event", ""),
            relation=_relation_type_from_str(r.get("relation"), where=f"relations[{i}]"),
            to_event=r.get("to_event", ""),
            reason=r.get("reason", ""),
        ))

    raw_observations = data.get("observations", {}) or {}
    if not isinstance(raw_observations, Mapping):
        raise EventRegistryError(f"registry {registry_id!r}: 'observations' must be a JSON object")
    observations: Dict[str, RuntimeEventObservation] = {}
    for name, o in raw_observations.items():
        if not isinstance(o, Mapping):
            raise EventRegistryError(f"observations[{name!r}] must be a JSON object")
        observations[name] = RuntimeEventObservation(
            status=_status_from_str(o.get("status"), where=f"observations[{name!r}]"),
            evidence=o.get("evidence", ""),
            observed_at=o.get("observed_at"),
        )

    return RuntimeEventRegistry(
        registry_id=registry_id,
        events=tuple(events),
        relations=tuple(relations),
        observations=observations,
        description=data.get("description", ""),
    )


def load_registry(path: Any) -> RuntimeEventRegistry:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EventRegistryError(f"registry file not found: {p}") from None
    except json.JSONDecodeError as e:
        raise EventRegistryError(f"registry file {p} is not valid JSON: {e}") from None
    return registry_from_dict(data)


# ------------------------------------------------------------------------
# rendering (reuses connectivity.render_markdown_table -- the repo's one
# parameterized table renderer -- rather than a second hand-rolled one)
# ------------------------------------------------------------------------

def render_graph(registry: RuntimeEventRegistry) -> str:
    event_rows = [e.to_dict() for e in registry.events]
    for row in event_rows:
        row["consumer"] = ", ".join(row["consumer"])
        row["payload"] = json.dumps(row["payload"]) if row["payload"] else ""
        row["timeout"] = "" if row["timeout"] is None else row["timeout"]
        row["raw_status"] = registry.raw_status(row["event_name"]).value
    events_table = render_markdown_table(
        [("event_name", "Event"), ("producer", "Producer"), ("consumer", "Consumer"),
         ("scope", "Scope"), ("timeout", "Timeout"), ("raw_status", "Status")],
        event_rows, empty_note="(no events declared)")

    rel_rows = [r.to_dict() for r in registry.relations]
    relations_table = render_markdown_table(
        [("from_event", "From"), ("relation", "Relation"), ("to_event", "To"), ("reason", "Reason")],
        rel_rows, empty_note="(no relations declared)")

    return (f"# Runtime Event Registry: {registry.registry_id}\n\n"
            f"{registry.description}\n\n## Events\n\n{events_table}\n\n## Relations\n\n{relations_table}\n")


def render_status(report: PropagationReport) -> str:
    status_rows = [{"event_name": n, "raw_status": report.raw_status[n], "effective_status": s}
                   for n, s in sorted(report.effective_status.items())]
    status_table = render_markdown_table(
        [("event_name", "Event"), ("raw_status", "Observed"), ("effective_status", "Effective (post-propagation)")],
        status_rows, empty_note="(no events)")
    findings_table = render_markdown_table(
        [("finding", "Finding"), ("event", "Event"), ("related_events", "Related"), ("reason", "Reason")],
        [{**f, "related_events": ", ".join(f["related_events"])} for f in report.findings],
        empty_note="(no findings -- nothing blocked, at risk, or orphaned)")
    return (f"# Runtime Event Propagation: {report.registry_id}\n\n"
            f"generated_at: {report.generated_at}\n\n## Status\n\n{status_table}\n\n"
            f"## Findings\n\n{findings_table}\n\n"
            "NOTE: this report is a computed propagation over a declared event graph. It runs no "
            "build, submits no job, and gates nothing.\n")


def report_path(root: Any) -> Path:
    return Path(root).joinpath(*REGISTRY_REPORT_PARTS)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Same write-temp-then-replace convention `change_impact._atomic_write_json()`
    / `config_variant_coverage._atomic_write_json()` use, so a crashed run
    never leaves a half-written report on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_report(root: Any, report: PropagationReport, *, path: Any = None) -> Path:
    out = Path(path) if path else report_path(root)
    _atomic_write_json(out, report.to_dict())
    return out


# ------------------------------------------------------------------------
# CLI (shared by `python -m dv_harness.runtime_event_registry`; see the
# structured-output snippet for the `dv-harness runtime-events` cli.py wire)
# ------------------------------------------------------------------------

def execute_verb(verb: str, *, root: Any = ".", registry_path: Optional[str] = None,
                 out_path: Optional[str] = None, as_json: bool = False) -> Tuple[str, int]:
    """Shared implementation for `dv-harness runtime-events <verb>` and
    `python -m dv_harness.runtime_event_registry <verb>`. Returns (text,
    exit_code): 0 nothing FAILED/TIMEOUT/BLOCKED_BY_DEPENDENCY, 1 at least one
    is, 2 NOT_AVAILABLE or a usage/declaration error."""
    if not registry_path:
        return ("runtime-events requires --registry <events.json>", 2)
    try:
        registry = load_registry(registry_path)
    except EventRegistryError as e:
        return (f"EventRegistryError: {e}", 2)

    if verb == "graph":
        text = json.dumps(registry.to_dict(), indent=2) if as_json else render_graph(registry)
        return text, 0

    if verb == "status":
        report = registry.propagate()
        written = None
        if out_path:
            written = write_report(root, report, path=out_path)
        text = json.dumps(report.to_dict(), indent=2) if as_json else render_status(report)
        if written is not None and not as_json:
            text += f"\n  written to: {written}"
        return text, (1 if report.has_blocking_outcome() else 0)

    return (f"unknown runtime-events verb {verb!r}", 2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.runtime_event_registry",
        description="Runtime event registry: event_name/producer/consumer/payload/timeout/"
                    "scope/status over a declared event set, with REQUIRES/WAITS_FOR/TRIGGERS/"
                    "UNBLOCKS dependency-graph stop-on-failure propagation. Reports only -- runs "
                    "no build, submits no job, gates nothing.")
    ap.add_argument("verb", choices=("graph", "status"))
    ap.add_argument("--registry", required=True, help="Runtime event registry JSON file.")
    ap.add_argument("--out", default=None, help="status: also write the propagation report JSON here.")
    ap.add_argument("--root", default=".", help="Project root (used for the default report path).")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)
    text, code = execute_verb(a.verb, root=a.root, registry_path=a.registry, out_path=a.out, as_json=a.json)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
