"""dv_harness/intake_field_resolution.py -- how one intake field gets its
EffectiveValue, and when a human may be asked about it.

PROVENANCE (M5 Cohort 4, CAP-M5-ATL007-001): the semantic MODEL in this file
-- the eight-attribute OpenSpec contract, the SourceKind/Origin/
ValidationState/ConfirmationState split, and the no-precedence
evidence-based resolution algorithm -- is adapted from this project's Parent
source (`D:\\DV\\Task\\DV_Agent_Harness_L5\\dv_harness\\intake_field_resolution.py`),
a real, tested (24/24 passing, independently re-run in Parent's own tree
before being trusted), wired capability there (9 real Parent-side callers:
`intake_contract.py`, `intake_discovery.py`, `intake_interfaces.py`,
`intake_loader.py`, `intake_package.py`, `intake_resume.py`,
`intake_schema.py`, `intake_validation.py`, `intake_workbook.py`). This is
an ADAPTATION, not a blind copy -- see the two deliberate departures below.

FOUNDATION, NOT YET OPERATIONAL IN CANONICAL. Canonical already has its own,
simpler intake-field model (`intake_state.IntakeFieldRecord`/
`IntakeFieldStatus`: one flat record, one combined status enum covering
discovery+validation+confirmation together). This module does not replace,
wire into, or modify that existing system -- reconciling the two (or
routing new intake work through this richer model) is explicitly M6's job,
once `ClarificationService` is built. Per this Cohort's own instruction:
"Cohort 4 only establishes the semantic foundation that M6 will use." This
module has zero canonical callers as of this migration -- it is imported by
its own test file only, exactly the same FOUNDATION status this project's
`CAP-VELM-*` capabilities carry before their own owner wave builds on them.

TWO DELIBERATE DEPARTURES FROM PARENT (never silently propagated):

  1. `OPENSPEC_FIELD_ATTRIBUTES` is defined LOCALLY below, not imported from
     Parent's `irq_openspec_preflight_gate.py` (905 lines, Parent-only, out
     of this Cohort's registered scope -- "do not expand into unrelated
     Parent governance modules"). The 8-tuple value itself is unchanged
     (`declared_value`, `auto_discovered_value`, `derived_value`,
     `effective_value`, `confidence`, `validation_state`,
     `confirmation_state`, `evidence_refs`) -- verified against Parent's
     real constant, not guessed -- but its home authority is now this
     module, for canonical.
  2. Parent's `CLOSED_TECHNICAL_GAPS["STRUCTURED_CLARIFICATION_CONTEXT_
     NOT_PERSISTED"]` claims that gap closed by `intake_clarification.py`
     consumed by `intake_resume.py`. Neither file exists in canonical (both
     belong to Parent's own separate, unrelated "Standard Flow" development
     track) -- so that claim does NOT hold here. It is carried below as an
     OPEN `KNOWN_TECHNICAL_GAPS` entry for canonical instead of a closed
     one: `question_queue.add_question()`'s `context` parameter is accepted
     but the machine-readable structured content (field, reason,
     candidates, evidence, attempted producers, downstream impact) is
     currently rendered into question TEXT only, recoverable by a human
     reader but not by another process without re-parsing prose. Whether
     and how to close this in canonical (build a canonical structured-
     clarification store, or reuse/adapt one) is left to whichever wave
     first needs it -- not decided or implemented by this migration.

The contract does NOT define a precedence between the declared, discovered
and derived values, so none is invented here. Source authority is not value
precedence:

  * every candidate value keeps its provenance, evidence and validation result;
  * one validated source            -> its value is the EffectiveValue (CANDIDATE);
  * several distinct sources agree  -> CONSENSUS (CONFIRMED);
  * sources disagree                -> CONTRADICTED, EffectiveValue unresolved.
    Before asking anyone, this repo's own 9-level `source_authority` order is
    tried on evidence-backed sides (AUTHORIZED_EVIDENCE); a user-declared value
    has no authority rank, so it can only be settled by a human;
  * confidence never picks a winner among conflicting values. A configurable
    threshold only decides which candidates are eligible at all.

Blank means UNRESOLVED_INPUT, not MISSING_USER_INPUT: blank cells trigger
autonomous discovery first, not an immediate user question (preserving
AUTO_DISCOVERY_FIRST / MINIMAL_STRUCTURED_CLARIFICATION -- both required to
stay preserved by this Cohort's own instruction, and neither implemented as
a full ClarificationService here). `resolve_field()` therefore always runs
the field's registered evidence producers in evidence-ladder order and
records every attempt; `evaluate_question_gate()` refuses a question for a
value that never went through discovery, and `file_clarification()` files
the question into the real question queue with the attempted sources,
candidates, conflict, downstream impact and the exact confirmation needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import source_authority
from .question_queue import QuestionQueueStore, make_question_id

#: The contract's own eight per-field OpenSpec attributes, in the contract's
#: order. See the module docstring's "TWO DELIBERATE DEPARTURES" point 1 for
#: why this is defined here rather than imported from a Parent-only module.
OPENSPEC_FIELD_ATTRIBUTES: Tuple[str, ...] = (
    "declared_value",
    "auto_discovered_value",
    "derived_value",
    "effective_value",
    "confidence",
    "validation_state",
    "confirmation_state",
    "evidence_refs",
)

# Evidence ladder (owner-approved order); step 9 is the user question itself.
EVIDENCE_LADDER: Tuple[str, ...] = (
    "existing_files", "rtl_parameters_defines", "uvm_vip_configuration", "tests_sequences",
    "design_documents", "vplan_testcase", "build_regression_scripts", "git_history",
)
QUESTION_DOMAINS = ("dut", "env", "vip")
MAX_QUESTION_OPTIONS = 3  # question_queue's schema: 2-3 pre-researched options


class ValueState(str, Enum):
    UNKNOWN = "UNKNOWN"
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    CONTRADICTED = "CONTRADICTED"


class ResolutionMethod(str, Enum):
    SINGLE_SOURCE = "SINGLE_SOURCE"
    CONSENSUS = "CONSENSUS"
    AUTHORIZED_EVIDENCE = "AUTHORIZED_EVIDENCE"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    UNRESOLVED = "UNRESOLVED"


class SourceKind(str, Enum):
    DECLARED = "DECLARED"
    AUTO_DISCOVERED = "AUTO_DISCOVERED"
    DERIVED = "DERIVED"
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"  # a human answer to a structured clarification (a new candidate)


class ValidationState(str, Enum):
    NOT_VALIDATED = "NOT_VALIDATED"
    VALID = "VALID"
    INVALID = "INVALID"
    CONTRADICTED = "CONTRADICTED"


class ConfirmationState(str, Enum):
    NOT_CONFIRMED = "NOT_CONFIRMED"
    CONFIRMED_BY_EVIDENCE = "CONFIRMED_BY_EVIDENCE"
    CONFIRMED_BY_USER = "CONFIRMED_BY_USER"
    CONFLICT = "CONFLICT"


class Origin(str, Enum):
    """Who ultimately asserted a value. Independent of the contract slot (`SourceKind`):
    a level typed on the command line is read from the lifecycle record (an
    AUTO_DISCOVERED slot) but its origin is HUMAN_EXPLICIT."""
    HUMAN_EXPLICIT = "HUMAN_EXPLICIT"
    AUTO_DISCOVERED = "AUTO_DISCOVERED"
    DERIVED = "DERIVED"
    IMPORTED = "IMPORTED"


_ORIGIN_FROM_KIND = {
    "DECLARED": Origin.HUMAN_EXPLICIT, "AUTO_DISCOVERED": Origin.AUTO_DISCOVERED, "DERIVED": Origin.DERIVED,
    "CLARIFICATION_ANSWER": Origin.HUMAN_EXPLICIT}

# Known technical gaps that must not be lost. Registered where the fix belongs. A gap leaves this dict only
# when real evidence closes it FOR CANONICAL -- Parent's own closure of the same-named gap (via files that
# do not exist in canonical) does not count; see the module docstring's "TWO DELIBERATE DEPARTURES" point 2.
KNOWN_TECHNICAL_GAPS: Dict[str, str] = {
    "STRUCTURED_CLARIFICATION_CONTEXT_NOT_PERSISTED": (
        "question_queue.add_question() accepts a `context` argument but the structured clarification "
        "content (field, reason, candidates, evidence, attempted producers, downstream impact, exact "
        "confirmation) is rendered into question TEXT only here, recoverable by a human reader but not "
        "by another process without re-parsing prose. Closed in Parent by intake_clarification.py "
        "(consumed by intake_resume.py) -- neither exists in canonical (both belong to Parent's own "
        "separate, unrelated development track), so that closure does not carry over. Left open for "
        "whichever canonical wave first needs a structured store."
    ),
}

CLOSED_TECHNICAL_GAPS: Dict[str, Dict[str, Any]] = {}


class Confidence(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


_CONF_RANK = {Confidence.UNKNOWN: 0, Confidence.LOW: 1, Confidence.MEDIUM: 2, Confidence.HIGH: 3}


@dataclass(frozen=True)
class Candidate:
    """One source's proposed value, with everything needed to audit it."""
    value: str
    kind: SourceKind
    source: str
    confidence: Confidence = Confidence.MEDIUM
    evidence_refs: Tuple[str, ...] = ()
    location: str = ""
    authority: Optional[str] = None  # one of source_authority's 9 ids, or None
    validation: ValidationState = ValidationState.NOT_VALIDATED
    validation_note: str = ""
    origin: Optional[Origin] = None  # who asserted it; defaults from `kind`

    def __post_init__(self):
        if self.origin is None:
            object.__setattr__(self, "origin", _ORIGIN_FROM_KIND[self.kind.value])

    @property
    def confirmation_state(self) -> ConfirmationState:
        """Follows the ORIGIN only. ValidationState is a separate dimension: a value the
        user asserted explicitly can still be technically CONTRADICTED."""
        return (ConfirmationState.CONFIRMED_BY_USER if self.origin is Origin.HUMAN_EXPLICIT
                else ConfirmationState.NOT_CONFIRMED)

    def to_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "kind": self.kind.value, "source": self.source,
                "confidence": self.confidence.value, "evidence_refs": list(self.evidence_refs),
                "location": self.location, "authority": self.authority,
                "validation": self.validation.value, "validation_note": self.validation_note,
                "origin": self.origin.value}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Candidate":
        return Candidate(value=d["value"], kind=SourceKind(d["kind"]), source=d["source"],
                         confidence=Confidence(d["confidence"]),
                         evidence_refs=tuple(d.get("evidence_refs") or ()),
                         location=d.get("location", ""), authority=d.get("authority"),
                         validation=ValidationState(d["validation"]),
                         validation_note=d.get("validation_note", ""),
                         origin=Origin(d["origin"]) if d.get("origin") else None)


@dataclass(frozen=True)
class FieldControl:
    """Intake CONTROL metadata for one field (not OpenSpec value attributes)."""
    field_id: str
    required: bool = True
    applicable: bool = True
    notes: str = ""
    domain: str = "env"
    confirmation_required: bool = False
    downstream_consumers: Tuple[str, ...] = ()

    def __post_init__(self):
        if self.domain not in QUESTION_DOMAINS:
            raise ValueError(f"domain {self.domain!r} must be one of {QUESTION_DOMAINS}")


@dataclass(frozen=True)
class DiscoveryAttempt:
    step: str
    producer: str
    outcome: str  # FOUND | NOT_FOUND | ERROR
    note: str = ""


Producer = Callable[[str, Dict[str, Any]], Sequence[Candidate]]


@dataclass(frozen=True)
class EvidenceProducer:
    step: str
    name: str
    fn: Producer

    def __post_init__(self):
        if self.step not in EVIDENCE_LADDER:
            raise ValueError(f"step {self.step!r} is not on the evidence ladder {EVIDENCE_LADDER}")


@dataclass(frozen=True)
class EffectiveValue:
    field_id: str
    value: Optional[str]
    state: ValueState
    confidence: Confidence
    confirmation_state: ConfirmationState
    evidence_refs: Tuple[str, ...]
    candidates: Tuple[Candidate, ...]
    resolution_method: ResolutionMethod
    attempts: Tuple[DiscoveryAttempt, ...] = ()
    notes: str = ""
    discovery_ran: bool = False
    conflict: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()  # (value, sources) per side

    @property
    def origins(self) -> Tuple[str, ...]:
        """Origins of the candidates that support the EffectiveValue (empty when unresolved)."""
        if self.value is None:
            return ()
        seen: List[str] = []
        if self.resolution_method is ResolutionMethod.HUMAN_CONFIRMED:
            seen.append(Origin.HUMAN_EXPLICIT.value)
        for c in self.candidates:
            if c.value.strip() == self.value.strip() and c.validation is not ValidationState.INVALID \
                    and c.origin.value not in seen:
                seen.append(c.origin.value)
        return tuple(seen)

    # ------------------------------------------------------------- OpenSpec view
    def _values_of(self, kind: SourceKind):
        seen: List[str] = []
        for c in self.candidates:
            if c.kind is kind and c.value not in seen:
                seen.append(c.value)
        return None if not seen else (seen[0] if len(seen) == 1 else seen)

    def _validation_state(self) -> str:
        if self.state is ValueState.CONTRADICTED:
            return ValidationState.CONTRADICTED.value
        if self.value is not None:
            return ValidationState.VALID.value
        if self.candidates and all(c.validation is ValidationState.INVALID for c in self.candidates):
            return ValidationState.INVALID.value
        return ValidationState.NOT_VALIDATED.value

    def to_openspec_record(self) -> Dict[str, Any]:
        """Exactly the contract's eight attributes, in the contract's order."""
        rec = {
            "declared_value": self._values_of(SourceKind.DECLARED),
            "auto_discovered_value": self._values_of(SourceKind.AUTO_DISCOVERED),
            "derived_value": self._values_of(SourceKind.DERIVED),
            "effective_value": self.value,
            "confidence": self.confidence.value,
            "validation_state": self._validation_state(),
            "confirmation_state": self.confirmation_state.value,
            "evidence_refs": list(self.evidence_refs),
        }
        assert tuple(rec) == OPENSPEC_FIELD_ATTRIBUTES
        return rec

    # ------------------------------------------------------------ full round trip
    def to_record(self) -> Dict[str, Any]:
        return {
            "field_id": self.field_id,
            "openspec": self.to_openspec_record(),
            "resolution": {
                "state": self.state.value,
                "resolution_method": self.resolution_method.value,
                "candidates": [c.to_dict() for c in self.candidates],
                "attempts": [{"step": a.step, "producer": a.producer, "outcome": a.outcome,
                              "note": a.note} for a in self.attempts],
                "notes": self.notes,
                "discovery_ran": self.discovery_ran,
                "conflict": [{"value": v, "sources": list(s)} for v, s in self.conflict],
            },
        }

    @staticmethod
    def from_record(rec: Dict[str, Any]) -> "EffectiveValue":
        o, r = rec["openspec"], rec["resolution"]
        return EffectiveValue(
            field_id=rec["field_id"], value=o["effective_value"], state=ValueState(r["state"]),
            confidence=Confidence(o["confidence"]),
            confirmation_state=ConfirmationState(o["confirmation_state"]),
            evidence_refs=tuple(o["evidence_refs"]),
            candidates=tuple(Candidate.from_dict(c) for c in r["candidates"]),
            resolution_method=ResolutionMethod(r["resolution_method"]),
            attempts=tuple(DiscoveryAttempt(a["step"], a["producer"], a["outcome"], a.get("note", ""))
                           for a in r["attempts"]),
            notes=r.get("notes", ""), discovery_ran=bool(r.get("discovery_ran")),
            conflict=tuple((c["value"], tuple(c["sources"])) for c in r.get("conflict", [])))


# ----------------------------------------------------------------- resolution

def default_validator(field_id: str, cand: Candidate) -> Tuple[ValidationState, str]:
    """Schema-level only: a non-blank value. Semantic and evidence validation
    are separate, later stages -- a value being present is not it being right."""
    if str(cand.value).strip():
        return ValidationState.VALID, "schema-only: non-blank value"
    return ValidationState.INVALID, "blank value"


def _normalize(value: Any) -> str:
    return str(value).strip()


def unresolved_blank(control: FieldControl) -> EffectiveValue:
    """A blank cell that has NOT been through discovery yet. The question gate
    refuses to ask about it."""
    return EffectiveValue(
        field_id=control.field_id, value=None, state=ValueState.UNKNOWN, confidence=Confidence.UNKNOWN,
        confirmation_state=ConfirmationState.NOT_CONFIRMED, evidence_refs=(), candidates=(),
        resolution_method=ResolutionMethod.UNRESOLVED,
        notes="UNRESOLVED_INPUT: blank cell, autonomous discovery not attempted", discovery_ran=False)


def _union(refs: Iterable[Iterable[str]]) -> Tuple[str, ...]:
    out: List[str] = []
    for group in refs:
        for r in group:
            if r not in out:
                out.append(r)
    return tuple(out)


def _try_authority(groups: Dict[str, List[Candidate]]) -> Optional[Tuple[str, str, List[str]]]:
    """Use the 9-level source-authority order, only when EVERY side has an
    evidence-backed, authority-ranked candidate. Returns (winning value,
    winning authority, losing authorities), or None."""
    claims = []
    best_by_value: Dict[str, Candidate] = {}
    for value, cands in groups.items():
        best = None
        for c in cands:
            if not c.authority or not c.evidence_refs:
                continue
            try:
                rank = source_authority.authority_rank(c.authority)
            except Exception:
                continue
            if best is None or rank < best[0]:
                best = (rank, c)
        if best is None:
            return None
        best_by_value[value] = best[1]
        try:
            claims.append(source_authority.SourceClaim(
                source=best[1].authority, claim=value, evidence_path=best[1].evidence_refs[0]))
        except Exception:
            return None
    verdict = source_authority.resolve_conflict(claims)
    if verdict.get("verdict") != "RESOLVED":
        return None
    winner_value = verdict["winner"]["claim"]
    losers = [best_by_value[v].authority for v in best_by_value if v != winner_value]
    return winner_value, best_by_value[winner_value].authority, losers


_CONTRADICTION_MARK = " || contradicted: "


def _declared_candidate(control: FieldControl, declared: Optional[str]) -> Optional[Candidate]:
    if declared is None or not str(declared).strip():
        return None
    return Candidate(value=str(declared).strip(), kind=SourceKind.DECLARED, source="user_workbook",
                     confidence=Confidence.HIGH, evidence_refs=(f"declared:{control.field_id}",))


def _mark_contradicted(c: Candidate, reason: str) -> Candidate:
    return replace(c, validation=ValidationState.CONTRADICTED,
                   validation_note=c.validation_note + _CONTRADICTION_MARK + reason)


def _reset_contradiction(c: Candidate) -> Candidate:
    """CONTRADICTED is an OUTPUT of a decision, never an input: replaying recorded
    candidates starts from their technical validity again."""
    if c.validation is not ValidationState.CONTRADICTED:
        return c
    return replace(c, validation=ValidationState.VALID,
                   validation_note=c.validation_note.split(_CONTRADICTION_MARK)[0])


def _validated(control: FieldControl, candidates: Sequence[Candidate], validator) -> List[Candidate]:
    out: List[Candidate] = []
    for c in candidates:
        if c.validation is ValidationState.NOT_VALIDATED:
            state, note = validator(control.field_id, c)
            c = replace(c, validation=state, validation_note=note or c.validation_note)
        out.append(c)
    return out


def _decide(control: FieldControl, checked: List[Candidate], attempts: Sequence[DiscoveryAttempt], *,
            min_confidence: Confidence, human_answer: Optional[str], normalize: Callable[[Any], str],
            discovery_ran: bool = True) -> EffectiveValue:
    """The one decision function: resolve_field() and resolve_recorded() both end here."""
    eligible = [c for c in checked if c.validation is ValidationState.VALID
                and _CONF_RANK[c.confidence] >= _CONF_RANK[min_confidence] and str(c.value).strip()]
    groups: Dict[str, List[Candidate]] = {}
    for c in eligible:
        groups.setdefault(normalize(c.value), []).append(c)
    below = [c for c in checked if c.validation is ValidationState.VALID and c not in eligible]
    conflict = tuple((v, tuple(c.source for c in cs)) for v, cs in groups.items())

    def base(cands: Sequence[Candidate]) -> Dict[str, Any]:
        return dict(field_id=control.field_id, candidates=tuple(cands), attempts=tuple(attempts),
                    discovery_ran=discovery_ran)

    if human_answer is not None and str(human_answer).strip():
        return EffectiveValue(
            value=str(human_answer).strip(), state=ValueState.CONFIRMED, confidence=Confidence.HIGH,
            confirmation_state=ConfirmationState.CONFIRMED_BY_USER,
            evidence_refs=("human_answer",) + _union(c.evidence_refs for c in eligible),
            resolution_method=ResolutionMethod.HUMAN_CONFIRMED,
            notes="resolved by human confirmation; all candidates retained",
            conflict=conflict if len(groups) > 1 else (), **base(checked))

    if not groups:
        return EffectiveValue(
            value=None, state=ValueState.UNKNOWN, confidence=Confidence.UNKNOWN,
            confirmation_state=ConfirmationState.NOT_CONFIRMED, evidence_refs=(),
            resolution_method=ResolutionMethod.UNRESOLVED,
            notes="no eligible candidate" + (f" ({len(checked)} ineligible on record)" if checked else ""),
            **base(checked))

    if len(groups) == 1:
        value, supporting = next(iter(groups.items()))
        consensus = len({c.source for c in supporting}) >= 2
        if any(c.origin is Origin.HUMAN_EXPLICIT for c in supporting):
            confirmation = ConfirmationState.CONFIRMED_BY_USER
        elif consensus:
            confirmation = ConfirmationState.CONFIRMED_BY_EVIDENCE
        else:
            confirmation = ConfirmationState.NOT_CONFIRMED
        notes = ""
        if below:
            notes = "lower-confidence candidate(s) on record: " + ", ".join(
                f"{c.source}={c.value}" for c in below)
        return EffectiveValue(
            value=supporting[0].value.strip(), state=ValueState.CONFIRMED if consensus else ValueState.CANDIDATE,
            confidence=max((c.confidence for c in supporting), key=lambda x: _CONF_RANK[x]),
            confirmation_state=confirmation, evidence_refs=_union(c.evidence_refs for c in supporting),
            resolution_method=ResolutionMethod.CONSENSUS if consensus else ResolutionMethod.SINGLE_SOURCE,
            notes=notes, **base(checked))

    authority = _try_authority(groups)
    if authority is not None:
        win_value, win_auth, lose_auth = authority
        supporting = groups[win_value]
        marked = [_mark_contradicted(c, f"outranked by {win_auth}") if c in eligible and c not in supporting else c
                  for c in checked]
        return EffectiveValue(
            value=supporting[0].value.strip(), state=ValueState.CONFIRMED,
            confidence=max((c.confidence for c in supporting), key=lambda x: _CONF_RANK[x]),
            confirmation_state=ConfirmationState.CONFIRMED_BY_EVIDENCE,
            evidence_refs=_union(c.evidence_refs for c in supporting),
            resolution_method=ResolutionMethod.AUTHORIZED_EVIDENCE,
            notes=(f"AUTHORIZED_EVIDENCE: {win_auth} outranks {', '.join(lose_auth)} in the "
                   f"source-authority order; the other candidate(s) stay on record"),
            conflict=conflict, **base(marked))

    marked = [_mark_contradicted(c, "disagrees with " + ", ".join(
        sorted({o.source for o in eligible if normalize(o.value) != normalize(c.value)})))
        if c in eligible else c for c in checked]
    return EffectiveValue(
        value=None, state=ValueState.CONTRADICTED, confidence=Confidence.UNKNOWN,
        confirmation_state=ConfirmationState.CONFLICT,
        evidence_refs=_union(c.evidence_refs for c in eligible),
        resolution_method=ResolutionMethod.UNRESOLVED,
        notes="candidates disagree: " + "; ".join(f"{v!r} from {', '.join(s)}" for v, s in conflict),
        conflict=conflict, **base(marked))


def resolve_field(control: FieldControl, *, declared: Optional[str],
                  producers: Sequence[EvidenceProducer] = (), context: Optional[Dict[str, Any]] = None,
                  validator: Optional[Callable[[str, Candidate], Tuple[ValidationState, str]]] = None,
                  min_confidence: Confidence = Confidence.LOW, human_answer: Optional[str] = None,
                  normalizer: Optional[Callable[[Any], str]] = None) -> EffectiveValue:
    """Resolve one field. Always runs the field's producers (in ladder order)
    unless the field is not applicable; never asks anyone."""
    if not control.applicable:
        return replace(unresolved_blank(control), discovery_ran=True,
                       notes="NOT_APPLICABLE: field does not apply to this project")
    candidates: List[Candidate] = []
    attempts: List[DiscoveryAttempt] = []
    decl = _declared_candidate(control, declared)
    if decl is not None:
        candidates.append(decl)
    ctx = dict(context or {})
    for p in sorted(producers, key=lambda p: EVIDENCE_LADDER.index(p.step)):
        try:
            found = list(p.fn(control.field_id, ctx))
        except Exception as exc:  # a broken scanner must not decide anything
            attempts.append(DiscoveryAttempt(p.step, p.name, "ERROR", f"{type(exc).__name__}: {exc}"))
            continue
        attempts.append(DiscoveryAttempt(p.step, p.name, "FOUND" if found else "NOT_FOUND"))
        candidates.extend(found)
    return _decide(control, _validated(control, candidates, validator or default_validator), attempts,
                   min_confidence=min_confidence, human_answer=human_answer,
                   normalize=normalizer or _normalize)


def resolve_recorded(control: FieldControl, *, declared: Optional[str], recorded: Sequence[Candidate],
                     attempts: Sequence[DiscoveryAttempt] = (), discovery_ran: bool = True,
                     validator: Optional[Callable[[str, Candidate], Tuple[ValidationState, str]]] = None,
                     min_confidence: Confidence = Confidence.LOW, human_answer: Optional[str] = None,
                     normalizer: Optional[Callable[[Any], str]] = None) -> EffectiveValue:
    """Resolve a field from candidates and attempts that were RECORDED earlier (a loaded
    workbook) instead of from live producers. Same decision function as resolve_field();
    recorded DECLARED rows are ignored because the declared cell is the editing surface."""
    if not control.applicable:
        return replace(unresolved_blank(control), discovery_ran=True,
                       notes="NOT_APPLICABLE: field does not apply to this project")
    candidates: List[Candidate] = []
    decl = _declared_candidate(control, declared)
    if decl is not None:
        candidates.append(decl)
    candidates.extend(_reset_contradiction(c) for c in recorded if c.kind is not SourceKind.DECLARED)
    return _decide(control, _validated(control, candidates, validator or default_validator), attempts,
                   min_confidence=min_confidence, human_answer=human_answer,
                   normalize=normalizer or _normalize, discovery_ran=discovery_ran)


# ---------------------------------------------------------------- question gate

@dataclass(frozen=True)
class QuestionDecision:
    ask: bool
    kind: Optional[str]  # CONFLICT | UNKNOWN | CONFIRMATION
    reasons: Tuple[str, ...]


def field_is_sufficient(control: FieldControl, ev: EffectiveValue) -> bool:
    """Optional and non-applicable fields never block READY."""
    if not control.applicable or not control.required:
        return True
    if ev.value is None:
        return False
    return not control.confirmation_required or ev.confirmation_state is ConfirmationState.CONFIRMED_BY_USER


def evaluate_question_gate(control: FieldControl, ev: EffectiveValue, *,
                           execution_path_requires: bool = True) -> QuestionDecision:
    """A question is allowed only when the field is required for the current
    path, discovery really ran, the EffectiveValue is unresolved / contradicted
    (or needs a required confirmation), and only a human can settle it."""
    if not control.applicable:
        return QuestionDecision(False, None, ("NOT_APPLICABLE",))
    if not control.required:
        return QuestionDecision(False, None, ("OPTIONAL",))
    if not execution_path_requires:
        return QuestionDecision(False, None, ("NOT_REQUIRED_FOR_PATH",))
    if not ev.discovery_ran:
        return QuestionDecision(False, None, ("DISCOVERY_NOT_ATTEMPTED",))
    if ev.state is ValueState.CONTRADICTED:
        return QuestionDecision(True, "CONFLICT", ("EFFECTIVE_VALUE_CONTRADICTED", "AUTHORITY_CANNOT_RESOLVE"))
    if ev.value is None:
        return QuestionDecision(True, "UNKNOWN", ("REQUIRED_FIELD_UNRESOLVED", "DISCOVERY_EXHAUSTED"))
    if control.confirmation_required and ev.confirmation_state is not ConfirmationState.CONFIRMED_BY_USER:
        return QuestionDecision(True, "CONFIRMATION", ("USER_CONFIRMATION_REQUIRED",))
    return QuestionDecision(False, None, ("RESOLVED",))


def _option_rationale(value: str, candidates: Sequence[Candidate]) -> str:
    parts = []
    for c in candidates:
        if _normalize(c.value) == value:
            where = c.location or ", ".join(c.evidence_refs) or "no location"
            parts.append(f"{c.source} ({c.kind.value}) at {where}")
    return "; ".join(parts) or "declared by the user"


def file_clarification(root_or_store: Any, control: FieldControl, ev: EffectiveValue,
                       decision: QuestionDecision, *, context_path: str = "intake workbook",
                       downstream_impact: str = "") -> Optional[Dict[str, Any]]:
    """File the question into the real question queue (idempotent per field).
    Returns None when the gate says nobody should be asked.

    This renders everything into the question text (see
    `KNOWN_TECHNICAL_GAPS["STRUCTURED_CLARIFICATION_CONTEXT_NOT_PERSISTED"]`
    above for the honest, canonical-specific status of a structured
    alternative)."""
    if not decision.ask:
        return None
    store = root_or_store if isinstance(root_or_store, QuestionQueueStore) \
        else QuestionQueueStore(Path(root_or_store))
    key = f"intake:{control.field_id}"
    existing = store.get_question(make_question_id(control.domain, key))
    if existing is not None:
        return existing
    impact = downstream_impact or (
        "consumed by " + ", ".join(control.downstream_consumers) if control.downstream_consumers
        else "the run cannot pass INTAKE_READY until this field is resolved")
    tried = [a.producer for a in ev.attempts]

    conflict_lines: List[str] = []
    if decision.kind == "CONFLICT":
        if len(ev.conflict) > MAX_QUESTION_OPTIONS:
            raise ValueError(f"{len(ev.conflict)} conflicting values for {control.field_id}; the question "
                             f"queue takes at most {MAX_QUESTION_OPTIONS} options -- refusing to truncate")
        options = [{"label": v, "rationale": _option_rationale(v, ev.candidates)} for v, _ in ev.conflict]
        recommendation = options[0]["label"]
        headline = f"sources disagree ({len(options)} different values); which value is correct?"
        why = "the sources disagree and neither source authority nor validation can settle it"
        exact = f"state which value of '{control.field_id}' is correct, or give another value"
        for v, _ in ev.conflict:
            for c in ev.candidates:
                if _normalize(c.value) == v:
                    where = c.location or "no location"
                    refs = ", ".join(c.evidence_refs) or "none"
                    conflict_lines.append(f"  - {v!r} <- {c.source} ({c.kind.value}) at {where} [evidence: {refs}]")
    elif decision.kind == "CONFIRMATION":
        options = [{"label": f"CONFIRM {ev.value}", "rationale": "keep the discovered value"},
                   {"label": "CHANGE the value", "rationale": "answer with the correct value"}]
        recommendation = options[0]["label"]
        headline = f"confirm the discovered value {ev.value!r}?"
        why = "this field is a material decision that must be confirmed by the user"
        exact = f"confirm or replace the value {ev.value!r}"
    else:
        options = [{"label": "PROVIDE_VALUE",
                    "rationale": "answer with the value, or fill the workbook cell and run `dv-harness start`"},
                   {"label": "NOT_APPLICABLE", "rationale": "the field does not apply; say why in the basis"}]
        recommendation = "PROVIDE_VALUE"
        headline = f"required but could not be discovered ({len(tried)} evidence source(s) tried)."
        why = "no evidence source produced a usable value"
        exact = f"provide the value of '{control.field_id}' or declare it not applicable"

    # The question queue does not persist a structured `context` for this module's own
    # use (see KNOWN_TECHNICAL_GAPS above), so everything the answerer needs is rendered
    # into the question text itself.
    lines = [f"Intake field '{control.field_id}': {headline}",
             f"Reason: {', '.join(decision.reasons)}",
             f"Why user authority is required: {why}",
             f"Attempted evidence sources: {', '.join(tried) if tried else 'none registered'}"]
    if conflict_lines:
        lines.append("Conflicting values:")
        lines.extend(conflict_lines)
    lines += [f"Downstream impact: {impact}", f"Exact confirmation needed: {exact}"]
    question = "\n".join(lines)
    ctx = {"blast_radius": "unbounded"}  # tier classification only; not persisted
    return store.add_question(
        domain=control.domain, question=question, context_path=context_path, question_key=key,
        options=options, recommendation=recommendation,
        assumption_if_unanswered=f"The step that needs '{control.field_id}' does not run until it is resolved.",
        context=ctx)
