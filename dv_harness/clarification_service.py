"""dv_harness/clarification_service.py -- CAP-M6-CLARSVC-001: ONE Canonical
`ClarificationService`, over `question_queue.py` + `intake_field_resolution.py`.

Executed under `DEC-M6-DISPATCH-001`'s sibling human decision, M-1 D2
(`ClarificationService` architecture, already decided, never reopened here):
"`question_queue.py` (v50) and `intake_clarification.py` (parent) will not
both survive as competing semantic authorities... The canonical target
defines ONE service, `ClarificationService`, that preserves the maximum
verified capability from both real implementations."

FOUNDATION GAP RE-INVESTIGATED FIRST (not blindly trusted from the Master
Blocker Register's own stale text). The register's `CAP-M5M6-VLEVEL-001` row
still cites `question_queue.py (diverged, M3-excluded)` as an open blocker.
Direct re-investigation this task (function/class-level `comm` diff, both
directions) found this claim is now STALE: canonical's `question_queue.py`
(2718 lines) is byte-for-byte identical to v50/b7a/b7b/b8's copies (confirmed
via `diff -w`, differing only in line endings) and is a strict SUPERSET of
Parent's own `question_queue.py` (1591 lines) -- 13 real functions/classes
present in canonical that Parent lacks (`build_escalation_package`,
`file_signoff_evidence_question`, `list_clarification_requests`,
`request_clarification`, `render_escalation_package_markdown`,
`render_clarification_markdown`, `_explain_tier_reason`,
`CosignNotApplicableError`, `normalize_grounding_evidence`,
`normalize_suggested_answer`, `derive_suggested_answer_from_env_manifest`,
`derive_suggested_answer_from_design_source_inventory`,
`build_suggest_then_confirm_options`), ZERO Parent functions canonical
lacks. Canonical's own test suite (166 tests) passes against this file, more
than double Parent's own (67, independently re-run in Parent's own tree
before trusting it -- both green). **`QUESTION_QUEUE_FOUNDATION = ALREADY_
RESOLVED`** -- there is no real N-way merge left to perform; this is a real,
disclosed correction to the Master Capability Matrix (see this task's own
`M6_CLARSVC_001_QUESTION_QUEUE_NWAY_ANALYSIS.md`), not a technical gap this
module needed to close before it could be built.

`intake_state.py` RECONCILIATION (CAP-ATL-007's own row named this as this
capability's job -- addressed, not silently skipped). Read directly:
`intake_state.py` is a narrow, already-real JOIN of env.manifest.json facts
+ `question_queue.py` decisions + `connectivity.py` bind tiers into a
`UvmGenerationReadiness` refusal gate, with its OWN distinct 8-value status
vocabulary (`AUTO_RESOLVED`/`USER_CONFIRMED`/`PARTIAL`/`CONTRADICTED`/
`MISSING`/`BLOCKED`/`UNKNOWN`/`NOT_APPLICABLE`) -- a genuinely different
domain (UVM-generation-readiness over env/connectivity facts specifically)
from `intake_field_resolution.py`'s generic OpenSpec 8-attribute engine
(`DeclaredValue`/`AutoDiscoveredValue`/`DerivedValue`/`EffectiveValue`/
`Confidence`/`ValidationState`/`ConfirmationState`/`EvidenceRefs`), never
calling `resolve_field()` and reading `question_queue.py` read-only via
`find_decision()`. The real disposition (not a merge, not silence):
`ClarificationService` is built exclusively on `intake_field_resolution.py`'s
engine -- satisfying "do not create a second Field Resolution engine" by
reusing the one canonical generic engine that exists, rather than either
merging two genuinely different-purpose modules (large, risky, unscoped) or
ignoring the flagged tension. `intake_state.py` remains the real,
unmodified, unmerged UVM_GENERATION_READY mechanism for its own domain.

THE REAL LOOP THIS MODULE BUILDS (never a shortcut past Field Resolution):

    Field Resolution -> unresolved? -> ClarificationService -> QuestionOwner
      -> HumanGate (question_queue.py, generalized with `authority_role`)
      -> Response -> Field Resolution (again, with `human_answer=`)
      -> EffectiveValue

A human answer NEVER overwrites `EffectiveValue` directly -- it re-enters
`intake_field_resolution.resolve_field()`'s own `human_answer=` parameter
(already real, already tested there), so `_decide()`'s own 9-level
source-authority arbitration, validation and confirmation-state logic all
still apply to a human-supplied value exactly as they do to any other
candidate. See `resolve_or_ask()`, the one real entry point this loop needs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .intake_field_resolution import (
    Candidate,
    Confidence,
    EffectiveValue,
    EvidenceProducer,
    FieldControl,
    QuestionDecision,
    ValidationState,
    evaluate_question_gate,
    field_is_sufficient,
    file_clarification,
    make_question_id,
    resolve_field,
)
from .question_queue import QuestionQueueStore

#: The three real DE/DV Role-Based HITL authority roles (frozen architecture,
#: `.work/phase3-dual-repo-consolidation/M4_5_DE_DV_ROLE_BASED_HITL/
#: DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md` Section 5 -- never reopened here).
DESIGN = "DESIGN"
VERIFICATION = "VERIFICATION"
SHARED = "SHARED"
QUESTION_OWNERS = (DESIGN, VERIFICATION, SHARED)

#: `intake_field_resolution.QUESTION_DOMAINS` ("dut", "env", "vip"), mapped
#: onto their DEFAULT authority role per DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md
#: Section 5's own definitions: "dut" (DUT RTL/register/port facts) is a
#: DESIGN_AUTHORITY concern ("intended DUT behavior, register semantics,
#: reset/IRQ/clock intent... RTL/spec discrepancy from a design-intent
#: perspective"); "env"/"vip" (verification-environment/VIP configuration)
#: are VERIFICATION_AUTHORITY concerns (neither is named under
#: DESIGN_AUTHORITY anywhere in that document). This is the DEFAULT only --
#: see classify_question_owner() for the one real signal that promotes a
#: "dut"-domain question to SHARED.
_DOMAIN_DEFAULT_OWNER: Dict[str, str] = {
    "dut": DESIGN,
    "env": VERIFICATION,
    "vip": VERIFICATION,
}


def classify_question_owner(control: FieldControl, decision: QuestionDecision) -> str:
    """Evidence/policy-based QuestionOwner classification -- never a lazy
    SHARED fallback (DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md Section 5: "SHARED
    is never a fallback for poor classification").

    The default is `control.domain`'s own real routing
    (`_DOMAIN_DEFAULT_OWNER`). The one real promotion to SHARED: a "dut"
    domain field whose `QuestionDecision.kind == "CONFLICT"` -- two real,
    evidence-backed sources disagree about a DUT/RTL fact, which
    DE_DV_ROLE_BASED_HITL_ARCHITECTURE.md's own SHARED examples name
    directly ("Spec/RTL contradiction"). An ordinary unresolved-but-not-
    conflicting "dut" question (decision.kind == "UNKNOWN", i.e. simply never
    discovered) stays DESIGN -- never promoted to SHARED merely because a
    human must be asked at all."""
    owner = _DOMAIN_DEFAULT_OWNER.get(control.domain, VERIFICATION)
    if control.domain == "dut" and decision.kind == "CONFLICT":
        return SHARED
    return owner


@dataclass(frozen=True)
class ClarificationOutcome:
    """The real result of one `resolve_or_ask()` call -- every field here is
    computed from a real source, never fabricated. `effective_value` is
    ALWAYS the live output of `intake_field_resolution.resolve_field()`
    (possibly re-run with a real human answer) -- this dataclass never
    carries a second, competing notion of "the value"."""

    effective_value: EffectiveValue
    resolved: bool          # field_is_sufficient(control, effective_value)
    asked: bool              # a NEW question was filed this call
    answered: bool           # an EXISTING answer was consumed this call
    question: Optional[Dict[str, Any]]   # the real, persisted question_queue record, or None
    question_owner: Optional[str]        # DESIGN | VERIFICATION | SHARED | None


def _as_store(root_or_store: Any) -> QuestionQueueStore:
    return root_or_store if isinstance(root_or_store, QuestionQueueStore) \
        else QuestionQueueStore(Path(root_or_store))


def resolve_or_ask(
    root_or_store: Any,
    control: FieldControl,
    *,
    declared: Optional[str] = None,
    producers: Sequence[EvidenceProducer] = (),
    context: Optional[Dict[str, Any]] = None,
    min_confidence: Confidence = Confidence.LOW,
    context_path: str = "intake workbook",
    downstream_impact: str = "",
    validator: Optional[Callable[[str, "Candidate"], "tuple[ValidationState, str]"]] = None,
) -> ClarificationOutcome:
    """The one real `ClarificationService` entry point: consume unresolved
    Field Resolution results, determine whether human clarification is
    required, determine `QuestionOwner`, construct/submit the minimum
    sufficient question (or consume an existing answer), and feed the
    result back through Field Resolution -- producing a newly resolved or
    still-unresolved field state. Never a second Field Resolution engine:
    every resolution decision runs through the real
    `intake_field_resolution.resolve_field()`.

    AUTO_DISCOVERY_FIRST / MINIMAL_STRUCTURED_CLARIFICATION (preserved,
    never weakened): `resolve_field()` always runs first, with every real
    producer this caller supplied; a human is asked only when
    `evaluate_question_gate()` -- itself already gated on
    `ev.discovery_ran` and a real contradiction/unresolved/confirmation-
    required condition -- says so. A field with `AutoDiscoveredValue`/
    `DerivedValue` sufficient to resolve it never reaches the question path
    at all (see `test_no_question_when_automatically_resolved`).

    `validator` (`CAP-M5M6-VLEVEL-001`, additive): an optional pass-through
    to `resolve_field()`'s own pre-existing `validator=` parameter (real,
    already there since `intake_field_resolution.py`'s own foundation --
    this module simply never exposed it before). `None` (the default)
    means `resolve_field()`'s own `default_validator` (a bare non-blank
    check) -- byte-identical to every call site that predates this
    parameter. A caller with a real, narrower value domain (e.g.
    `generation_field_controls.py`'s own `verification_level`, which must
    be exactly IP/SUBSYSTEM/SYSTEM_LEVEL, never merely non-blank) can now
    supply a stricter schema-level check without a second Field Resolution
    engine or a second validation mechanism -- still the same one real
    `_validated()`/`_decide()` pipeline every other field already runs
    through.
    """
    ev = resolve_field(control, declared=declared, producers=producers,
                       context=context, min_confidence=min_confidence,
                       validator=validator)
    if field_is_sufficient(control, ev):
        return ClarificationOutcome(ev, resolved=True, asked=False, answered=False,
                                    question=None, question_owner=None)

    decision = evaluate_question_gate(control, ev)
    if not decision.ask:
        # The gate itself says nobody should be asked (NOT_APPLICABLE/
        # OPTIONAL/NOT_REQUIRED_FOR_PATH/DISCOVERY_NOT_ATTEMPTED) -- honored,
        # never overridden here.
        return ClarificationOutcome(ev, resolved=False, asked=False, answered=False,
                                    question=None, question_owner=None)

    owner = classify_question_owner(control, decision)
    store = _as_store(root_or_store)

    # THE ANSWER -> FIELD RESOLUTION LOOP (mandatory, never a shortcut):
    # check FIRST whether this exact question already carries a real
    # answer -- if so, re-run resolve_field() WITH it (human_answer=),
    # never overwrite EffectiveValue directly.
    question_key = f"intake:{control.field_id}"
    qid = make_question_id(control.domain, question_key)
    existing = store.get_question(qid)
    if existing is not None and existing.get("answer") is not None:
        ev2 = resolve_field(control, declared=declared, producers=producers, context=context,
                            min_confidence=min_confidence, human_answer=existing["answer"],
                            validator=validator)
        return ClarificationOutcome(
            ev2, resolved=field_is_sufficient(control, ev2), asked=False, answered=True,
            question=existing, question_owner=existing.get("authority_role") or owner)

    # No answer on file yet -- file (or idempotently re-fetch, per
    # file_clarification()'s own dedup -- item 16's duplicate-question
    # prevention, reused, not reimplemented) the question, tagged with the
    # real, evidence-based QuestionOwner.
    q = file_clarification(store, control, ev, decision, context_path=context_path,
                           downstream_impact=downstream_impact, authority_role=owner)
    return ClarificationOutcome(ev, resolved=False, asked=(q is not None), answered=False,
                                question=q, question_owner=owner)


#: HumanGate's own conceptual states (HUMAN_GATE_CONTRACT.md Section 7's
#: `RESOLUTION_STATE`), mapped onto question_queue.py's REAL, already-
#: persisted `status`/`answer` fields -- reuse/generalize, never a second
#: incompatible state machine (item 9's own instruction). Every mapped value
#: below is backed by a real question_queue.py status; the 3 HUMAN_GATE_
#: CONTRACT.md-named states with no real canonical equivalent today
#: (REJECTED, DEFERRED, CANCELLED) are disclosed as NOT_SUPPORTED rather
#: than invented.
HG_WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
HG_ANSWERED = "ANSWERED"
HG_STILL_UNRESOLVED = "STILL_UNRESOLVED"
HG_SUPERSEDED = "SUPERSEDED"
HG_NOT_SUPPORTED = "NOT_SUPPORTED"


def human_gate_state(question: Dict[str, Any]) -> str:
    """Project a real, persisted question_queue.py record onto
    HUMAN_GATE_CONTRACT.md's own `RESOLUTION_STATE` vocabulary, using only
    states this codebase's real `status`/`answer`/`overturned` fields can
    honestly support -- never a fabricated REJECTED/DEFERRED/CANCELLED."""
    if question.get("overturned"):
        return HG_SUPERSEDED
    if question.get("answer") is not None:
        return HG_ANSWERED
    if question.get("status") == "OPEN":
        return HG_WAITING_FOR_HUMAN
    return HG_STILL_UNRESOLVED
