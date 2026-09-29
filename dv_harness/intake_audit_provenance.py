"""dv_harness/intake_audit_provenance.py -- a structured per-intake-fact
PROVENANCE record (who / what / when established it), built over an
already-computed `intake_state.IntakeState`.

REUSE OVER REINVENT, confirmed by direct reading before writing a line of
this. `intake_state.py` already carries `source`/`confidence`/`owner` per
field -- reused here VERBATIM as the base, per this task's own scope --
but its own `IntakeFieldRecord` throws away exactly the WHO/WHAT/WHEN detail
a real human decision already carries: `_apply_decision_overlay()` reads a
`question_queue.QuestionQueueStore.find_decision()` result's real
`current.decided_by` / `current.decided_at` / `current.source` /
`current.basis` / `current.question_id_of_answer` fields, and its full
`history` list of every prior decision for that question_key, then
compresses all of it into one human-readable `reason` STRING and an
overwritten `owner` field. Once that happens, a caller holding only the
resulting `IntakeState` has no structured way to recover WHO decided it,
WHEN, on what BASIS, under what real Q-ID, or whether an earlier Tier-2
auto-assumption was later overturned by a human -- only prose.

This module recovers that structure WITHOUT touching `intake_state.py` and
without re-implementing any of its overlay/resolution logic: it calls the
exact same ONE sanctioned read `intake_state.py` itself is restricted to,
`question_queue.QuestionQueueStore.find_decision()` (never `add_question()`/
`answer_question()` -- this module files no question and decides nothing),
using the SAME `question_store` + `field_question_keys` a caller already
built for `intake_state.build_intake_state()`, and folds the real decision
record it gets back together with the real `IntakeFieldRecord` it already
has for that field. There is no second decision store and no second
overlay algorithm here -- only a second, more structured READ of the one
real decision `intake_state.py` already consulted (or, for a field it was
never given a `question_store`/key for at all, an honest report that WHO
established it could not be verified beyond the base module's own
`owner`/`status` vocabulary).

WHAT "ESTABLISHED" MEANS, derived from `intake_state.py`'s OWN documented
status vocabulary rather than re-defined here: a field is ESTABLISHED
whenever its status is anything other than MISSING ("no evidence was
supplied at all") or UNKNOWN ("evidence was supplied but is inconclusive")
-- i.e. AUTO_RESOLVED / USER_CONFIRMED / PARTIAL / CONTRADICTED / BLOCKED /
NOT_APPLICABLE all mean *something* concrete was determined, even when that
determination is "blocked" or "conflicting". A field that was never
established gets `established_by = None` and `established_by_status =
NOT_ESTABLISHED` -- never a guessed owner or a fabricated timestamp.

WHO ESTABLISHED IT -- a closed, five-value `established_by_status`, never a
guess:
  - `HUMAN` -- a real decision was found (or the field's own status is
    USER_CONFIRMED, which `intake_state.py`'s own docstring guarantees means
    a real human decision is on file) whose `current.source` is
    `question_queue.HUMAN_DECISION_SOURCE`.
  - `TIER2_ASSUMPTION` -- a real decision was found whose `current.source`
    is `question_queue.TIER2_AUTO_ASSUMPTION_SOURCE` -- a harness-side
    guess, explicitly NOT attributed to a human.
  - `SYSTEM_COMPUTED` -- established directly from a real producer
    (env_manifest / connectivity / phy_boundary / a Gate-1 result / a
    caller-supplied list) with no question_queue decision involved at all.
  - `UNVERIFIABLE` -- the field's status (CONTRADICTED) could, per
    `intake_state.py`'s own vocabulary, come from EITHER two disagreeing
    computed sources OR a human disagreeing with a computed value, and no
    `question_store` was supplied to this module to tell the two apart.
    Reported honestly rather than defaulted either way -- the Evidence
    Truth Rule applies to this module's own output as much as to the facts
    it reads.
  - `NOT_ESTABLISHED` -- the field is MISSING/UNKNOWN; nothing was
    established for anyone to have established it.

WHAT established it (`established_via`) is `record.source` (reused
verbatim) plus, only when a real decision was actually found, the real
question_queue mechanism and Q-ID that confirmed/contradicted/strengthened
it. WHEN (`established_at`) is the decision's own real `decided_at` when
found, else the base record's own `last_validated` when the base module set
one, else `None` with `established_at_status = "UNKNOWN"` -- never
back-filled from the batch's own `generated_at`, which is a fact about when
this REPORT was built, not about when any one fact was established, and
conflating the two would misrepresent a computed fact with no timestamp
evidence as though it had one.

Deliberately bounded, and stated rather than implied closed. (1) This module
JOINS AND REPORTS ONLY -- exactly `intake_state.py`'s own restraint,
restated: it files no question, answers no question, runs no gate, and
writes no state/blackboard/approval record of its own. (2) It recovers
provenance for a field ONLY as precisely as the caller's own
`question_store`/`field_question_keys` inputs allow -- omitting either
(the same opt-in shape `intake_state.build_intake_state()` itself uses)
narrows `HUMAN`/`TIER2_ASSUMPTION` down to the honest `UNVERIFIABLE`/
`SYSTEM_COMPUTED` split described above rather than silently guessing.
(3) It mints no `.dv-harness/` event of its own -- `intake_events.py`'s
eighteen-event taxonomy is a fixed, closed vocabulary this module does not
widen; a provenance report is a read-time artifact, not an audit event.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field as _dc_field
from typing import Any, Dict, List, Optional

from . import question_queue
from .intake_state import IntakeFieldRecord, IntakeFieldStatus, IntakeState

SCHEMA_VERSION = "1.0"

#: Statuses `intake_state.py`'s own docstring defines as "nothing was
#: actually established" -- MISSING ("no evidence was supplied at all") and
#: UNKNOWN ("evidence was supplied but is inconclusive"). Every other status
#: means a real determination happened, even a blocking or conflicting one.
_NOT_ESTABLISHED_STATUSES = frozenset({
    IntakeFieldStatus.MISSING.value,
    IntakeFieldStatus.UNKNOWN.value,
})

#: The closed, five-value WHO vocabulary. Never widened by a guess.
ESTABLISHED_BY_HUMAN = "HUMAN"
ESTABLISHED_BY_TIER2_ASSUMPTION = "TIER2_ASSUMPTION"
ESTABLISHED_BY_SYSTEM_COMPUTED = "SYSTEM_COMPUTED"
ESTABLISHED_BY_UNVERIFIABLE = "UNVERIFIABLE"
ESTABLISHED_BY_NOT_ESTABLISHED = "NOT_ESTABLISHED"

ESTABLISHED_BY_STATUSES = frozenset({
    ESTABLISHED_BY_HUMAN,
    ESTABLISHED_BY_TIER2_ASSUMPTION,
    ESTABLISHED_BY_SYSTEM_COMPUTED,
    ESTABLISHED_BY_UNVERIFIABLE,
    ESTABLISHED_BY_NOT_ESTABLISHED,
})

#: WHEN precision -- never a fabricated third value standing in for a real
#: timestamp nobody recorded.
ESTABLISHED_AT_EXACT = "EXACT"
ESTABLISHED_AT_UNKNOWN = "UNKNOWN"

#: The verb `established_via` uses to describe how a real decision relates
#: to the field's own status -- never the same word for two different
#: relationships.
_DECISION_VERB_BY_STATUS: Dict[str, str] = {
    IntakeFieldStatus.USER_CONFIRMED.value: "confirmed_by",
    IntakeFieldStatus.CONTRADICTED.value: "contradicted_by",
    IntakeFieldStatus.AUTO_RESOLVED.value: "strengthened_by",
}


@dataclass
class IntakeProvenanceRecord:
    """One field's structured provenance -- who/what/when established its
    CURRENT value, reusing `IntakeFieldRecord`'s own `source`/`confidence`/
    `owner` verbatim as `source`/`confidence`/`responsible_owner`."""
    field: str
    category: str
    status: str
    confidence: str
    source: str
    responsible_owner: Optional[str]
    established: bool
    established_by: Optional[str]
    established_by_status: str
    established_via: Optional[str]
    established_at: Optional[str]
    established_at_status: str
    basis: str
    establishment_history: List[dict] = _dc_field(default_factory=list)
    overturned: Optional[bool] = None
    ever_tier2_assumed: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.established_by_status not in ESTABLISHED_BY_STATUSES:
            raise ValueError(
                f"unknown established_by_status {self.established_by_status!r} "
                f"for field {self.field!r}; must be one of {sorted(ESTABLISHED_BY_STATUSES)}")
        if self.established_at_status not in (ESTABLISHED_AT_EXACT, ESTABLISHED_AT_UNKNOWN):
            raise ValueError(
                f"unknown established_at_status {self.established_at_status!r} "
                f"for field {self.field!r}")

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "category": self.category,
            "status": self.status,
            "confidence": self.confidence,
            "source": self.source,
            "responsible_owner": self.responsible_owner,
            "established": self.established,
            "established_by": self.established_by,
            "established_by_status": self.established_by_status,
            "established_via": self.established_via,
            "established_at": self.established_at,
            "established_at_status": self.established_at_status,
            "basis": self.basis,
            "establishment_history": list(self.establishment_history),
            "overturned": self.overturned,
            "ever_tier2_assumed": self.ever_tier2_assumed,
        }


class IntakeAuditProvenance:
    """One project's joined provenance report -- one `IntakeProvenanceRecord`
    per real `IntakeFieldRecord` this run's `IntakeState` carries."""

    def __init__(self, records: List[IntakeProvenanceRecord], *, state_generated_at: Optional[str] = None):
        self.records = list(records)
        #: The BATCH's own generation timestamp -- a fact about when this
        #: `IntakeState` was built, deliberately kept separate from any one
        #: field's own `established_at` so the two can never be conflated.
        self.state_generated_at = state_generated_at
        self._by_field: Dict[str, IntakeProvenanceRecord] = {r.field: r for r in self.records}

    def get(self, field_name: str) -> Optional[IntakeProvenanceRecord]:
        return self._by_field.get(field_name)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "state_generated_at": self.state_generated_at,
            "records": [r.to_dict() for r in self.records],
        }


def _find_decision_for(
    field_name: str,
    *,
    question_store: Optional["question_queue.QuestionQueueStore"],
    field_question_keys: Optional[Dict[str, str]],
) -> Optional[dict]:
    """The ONE read this module performs beyond what `intake_state.py`
    already did -- `find_decision()`, never a write. Returns `None`
    (lookup genuinely unavailable or nothing on file) rather than raising,
    so a caller who omits either input still gets an honest, narrower
    report rather than a crash."""
    if question_store is None or not field_question_keys:
        return None
    key = field_question_keys.get(field_name)
    if not key:
        return None
    return question_store.find_decision(key)


def _provenance_for_record(
    record: IntakeFieldRecord,
    *,
    question_store: Optional["question_queue.QuestionQueueStore"],
    field_question_keys: Optional[Dict[str, str]],
    lookup_supplied: bool,
) -> IntakeProvenanceRecord:
    established = record.status not in _NOT_ESTABLISHED_STATUSES

    if not established:
        return IntakeProvenanceRecord(
            field=record.field, category=record.category, status=record.status,
            confidence=record.confidence, source=record.source,
            responsible_owner=record.owner, established=False, established_by=None,
            established_by_status=ESTABLISHED_BY_NOT_ESTABLISHED, established_via=None,
            established_at=None, established_at_status=ESTABLISHED_AT_UNKNOWN,
            basis=record.reason,
        )

    decision = _find_decision_for(
        record.field, question_store=question_store, field_question_keys=field_question_keys)

    if decision:
        current = decision.get("current") or {}
        src = current.get("source")
        if src == question_queue.HUMAN_DECISION_SOURCE:
            by_status = ESTABLISHED_BY_HUMAN
        elif src == question_queue.TIER2_AUTO_ASSUMPTION_SOURCE:
            by_status = ESTABLISHED_BY_TIER2_ASSUMPTION
        else:
            # A decision was found but names a source this module does not
            # recognize -- never guessed into HUMAN or TIER2_ASSUMPTION.
            by_status = ESTABLISHED_BY_UNVERIFIABLE
        verb = _DECISION_VERB_BY_STATUS.get(record.status, "recorded_by")
        qid = current.get("question_id_of_answer")
        established_via = f"{record.source} {verb}=question_queue:{src}(question_id={qid})"
        established_at = current.get("decided_at")
        return IntakeProvenanceRecord(
            field=record.field, category=record.category, status=record.status,
            confidence=record.confidence, source=record.source,
            responsible_owner=record.owner, established=True,
            established_by=current.get("decided_by") or record.owner,
            established_by_status=by_status, established_via=established_via,
            established_at=established_at,
            established_at_status=ESTABLISHED_AT_EXACT if established_at else ESTABLISHED_AT_UNKNOWN,
            basis=current.get("basis") or record.reason,
            establishment_history=list(decision.get("history") or []),
            overturned=decision.get("overturned"),
            ever_tier2_assumed=decision.get("ever_tier2_assumed"),
        )

    # No decision found for this field (or none looked up at all).
    if record.status == IntakeFieldStatus.USER_CONFIRMED.value:
        # intake_state.py's own vocabulary guarantees USER_CONFIRMED means a
        # real human decision is on file, even without re-fetching it here.
        by_status = ESTABLISHED_BY_HUMAN
    elif record.status == IntakeFieldStatus.CONTRADICTED.value:
        # Ambiguous by intake_state.py's own design: a CONTRADICTED field can
        # come from two disagreeing COMPUTED sources, or from a human
        # disagreeing with a computed value. Only a real lookup that found
        # nothing rules the second case out; no lookup at all cannot.
        by_status = ESTABLISHED_BY_SYSTEM_COMPUTED if lookup_supplied else ESTABLISHED_BY_UNVERIFIABLE
    else:
        by_status = ESTABLISHED_BY_SYSTEM_COMPUTED

    established_at = record.last_validated
    return IntakeProvenanceRecord(
        field=record.field, category=record.category, status=record.status,
        confidence=record.confidence, source=record.source,
        responsible_owner=record.owner, established=True,
        established_by=record.owner if by_status != ESTABLISHED_BY_UNVERIFIABLE else None,
        established_by_status=by_status, established_via=record.source,
        established_at=established_at,
        established_at_status=ESTABLISHED_AT_EXACT if established_at else ESTABLISHED_AT_UNKNOWN,
        basis=record.reason,
    )


def build_intake_audit_provenance(
    intake_state: IntakeState,
    *,
    question_store: Optional["question_queue.QuestionQueueStore"] = None,
    field_question_keys: Optional[Dict[str, str]] = None,
) -> IntakeAuditProvenance:
    """Build one `IntakeAuditProvenance` report over an already-built
    `IntakeState`. `question_store` + `field_question_keys` should be the
    SAME two inputs a caller already passed to
    `intake_state.build_intake_state()` -- passing them here lets this
    module recover the real per-decision WHO/WHEN/basis/history a human (or
    Tier-2 auto-assumption) decision carries; omitting them (the default)
    still produces a report, honestly narrowed per field per this module's
    own `established_by_status` vocabulary rather than guessed."""
    lookup_supplied = question_store is not None and bool(field_question_keys)
    records = [
        _provenance_for_record(
            r, question_store=question_store, field_question_keys=field_question_keys,
            lookup_supplied=lookup_supplied,
        )
        for r in intake_state.records
    ]
    return IntakeAuditProvenance(records, state_generated_at=intake_state.generated_at)


# ---------------------------------------------------------------------------
# Ad hoc front door -- no `dv-harness` CLI verb: this project's own house
# style skips CLI wiring when it would touch a large, concurrently-edited
# file for a module whose real callers are other Python code, not a human
# typing a command (`intake_state.py`/`intake_events.py`, the two modules
# this one directly extends, made the identical choice). `python -m` is the
# sanctioned fallback used throughout this codebase.
# ---------------------------------------------------------------------------

def execute_verb(intake_state_obj: IntakeState, verb: str, **kwargs: Any):
    """`execute_verb()` shim matching this project's shared convention
    (`loop_contract`/`loop_budget`/`intake_events`, ...). `verb` is currently
    only `"build"`; `**kwargs` forwards `question_store`/`field_question_keys`."""
    if verb == "build":
        report = build_intake_audit_provenance(intake_state_obj, **kwargs)
        return 0, report.to_dict()
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb, "known": ["build"]}
