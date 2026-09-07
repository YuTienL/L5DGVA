"""dv_harness/rca_ontology.py -- Root-Cause Ontology + Failure-Signature Normalization.

WHAT THIS ANSWERS. Two related, narrow mechanisms, one module:

1. A fixed ROOT-CAUSE CATEGORY ontology that classifies a CLOSED Engineering-Memory
   `root_cause`/`verified_fix`/`debug_lesson` record's own category -- DUT vs.
   testbench vs. VIP vs. stimulus vs. checker/scoreboard vs. coverage-model vs.
   spec/requirement vs. toolchain vs. configuration vs. flaky vs. accepted-limitation
   -- for CROSS-PROJECT AGGREGATION ("how many closed findings across our projects
   were really DUT RTL defects, vs. VIP defects, vs. flaky tests"). This is
   DELIBERATELY a different, coarser, "who/what is really at fault" axis from the
   two existing taxonomies already in this repo:
     * `command_error_taxonomy.py` classifies why ONE command/task DISPATCH failed
       (a per-dispatch, in-flight-symptom question).
     * `system_failure_taxonomy.py` classifies what KIND of SYSTEM/multi-subsystem
       -composition failure occurred (a per-integration-event, in-flight-symptom
       question).
   Neither ever asks "once this finding was closed and verified, what KIND of
   component actually owned the fix" -- the question this module answers, over a
   RECORD that has already reached closure, not over in-flight failure text.
   `assert_disjoint_from_command_error_taxonomy()` / `assert_disjoint_from_
   system_failure_taxonomy()` / `assert_disjoint_from_verification_verdict_
   vocabulary()` (all run at import) prove the three vocabularies -- and this
   module's own closure-status words -- never collide, the same "state the
   distinction, do not silently assume it" discipline this project's CLAUDE.md
   already applies to every other pair of near-adjacent vocabularies.

2. A CANONICAL failure-signature normalizer. Per the task's own instruction, this
   reuses -- and never re-derives a third/fourth definition of -- "is this the same
   failure": `sim_log_analysis.normalize_failure_signature()` strips the cosmetic
   variance (timestamps, hex addresses, random seeds, large counters) out of a
   record's own free-text fields BEFORE they are folded into a signature, then
   `memory_vault.build_failure_signature()` builds the ONE canonical signature-dict
   shape this project already uses everywhere (engine.py, lsf_client.py,
   loop_budget.py, capability_evolution.py, cross_project_mining.py,
   verification_strategy.py), and `evidence_db.signature_key()` hashes it into the
   SAME stable key those same real callers already group/dedup/accumulate
   `occurrence_count` by. `canonical_signature_for_record()` is the one function
   this module adds: it extracts `build_failure_signature()`'s real fields off a
   root_cause/verified_fix record's own real content, so a caller never has to
   remember to chain the two reused primitives itself.

WHAT "CLOSED" MEANS HERE, REUSED NOT RE-DERIVED. `memory_router.route_memory()`
already decides which `kind` values are root-cause-shaped and verified
(`kind in ("root_cause", "verified_fix", "debug_lesson") and verified`) --
`closure_status()` below calls it directly rather than re-typing that literal
tuple a second time, so a future kind added to `route_memory()`'s own routing
table is picked up here automatically. `memory_router.engineering_admission_gate()`
is the real, already-enforced three-gate bar (evidence, confidence, a reusable
claim) a record must clear to be more than a caller-supplied `verified: True`
label -- `closure_status()` calls that too. A record that fails EITHER check is
honestly `NOT_ROOT_CAUSE_RECORD` / `NOT_YET_CLOSED` and is NEVER categorized for
aggregation: feeding an unverified guess into a cross-project rollup as if it were
reliable root-cause data is exactly the fabrication the Evidence Truth Rule
forbids, and Core Operating Rules already states "Any current root cause must be
revalidated with current evidence" / "Memory is prior knowledge, not current
evidence".

WHAT THIS MODULE DOES NOT DO. It never writes a memory record, never promotes a
tier, never mines a cross-project store (that stays `cross_project_mining.py`'s
job, deliberately not imported here -- this module answers what CATEGORY a single
closed record belongs to and what its canonical signature is; how many PROJECTS'
stores independently confirm one signature is a separate, already-real mechanism).
It runs no build, job, or LSF submission and touches no human-approval gate. It is
a pure function of the record(s) it is given plus the two real reused signature
primitives above -- no file I/O of its own beyond the thin CLI wrapper.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import memory_router
from .sim_log_analysis import normalize_failure_signature
from .memory_vault import build_failure_signature
from .evidence_db import signature_key as _evidence_signature_key
from .human_correction_lesson import has_prior_correction

# ---------------------------------------------------------------------------
# (1) Root-cause CATEGORY ontology.
# ---------------------------------------------------------------------------

#: The eleven named categories, plus the honest fallback (`UNCLASSIFIED`, kept
#: out of this tuple exactly as `command_error_taxonomy.CATEGORIES` and
#: `system_failure_taxonomy.FAILURE_CATEGORIES` keep their own fallback out).
#: Order here is documentation only -- `CLASSIFICATION_ORDER` below is the real,
#: tested priority a record's text is actually checked in.
ROOT_CAUSE_CATEGORIES: Tuple[str, ...] = (
    "KNOWN_LIMITATION_ACCEPTED_RISK",
    "FLAKY_NONDETERMINISTIC_BEHAVIOR",
    "TOOLCHAIN_INFRASTRUCTURE_DEFECT",
    "CONFIGURATION_ERROR",
    "SPEC_REQUIREMENT_DEFECT",
    "COVERAGE_MODEL_DEFECT",
    "CHECKER_SCOREBOARD_DEFECT",
    "STIMULUS_SEQUENCE_DEFECT",
    "VIP_DEFECT_OR_MISCONFIGURATION",
    "TESTBENCH_ENVIRONMENT_DEFECT",
    "DUT_RTL_DEFECT",
)

#: Reported when no rule below matches. Never one of `ROOT_CAUSE_CATEGORIES` --
#: a classifier that could return this AS a named category would make "we
#: could not tell" indistinguishable from a real finding.
UNCLASSIFIED = "UNCLASSIFIED"

#: The real priority order a record's combined text is checked in, most
#: structurally specific / least ambiguous first. KNOWN_LIMITATION and FLAKY
#: are checked first because they are meta-facts about the finding itself
#: (never a component-defect claim, and would be mis-attributed to whatever
#: component happens to be named nearby if checked later). TOOLCHAIN and
#: CONFIGURATION follow -- both are process/environment claims, checked before
#: any component-defect category so a toolchain crash mentioning a component
#: name in passing is never misclassified as that component's defect. SPEC/
#: REQUIREMENT is checked next because a genuine spec ambiguity is a different
#: kind of fault than any implementation defect. The remaining six are
#: component-defect categories, ordered from the most specific/narrow
#: sub-mechanism (coverage model, checker/scoreboard, stimulus/sequence) to
#: the broadest (VIP, testbench, DUT RTL -- checked last because "bug"/
#: "defect" language attached to a bare component name is the least
#: distinguishing signal in the whole vocabulary).
CLASSIFICATION_ORDER: Tuple[str, ...] = (
    "KNOWN_LIMITATION_ACCEPTED_RISK",
    "FLAKY_NONDETERMINISTIC_BEHAVIOR",
    "TOOLCHAIN_INFRASTRUCTURE_DEFECT",
    "CONFIGURATION_ERROR",
    "SPEC_REQUIREMENT_DEFECT",
    "COVERAGE_MODEL_DEFECT",
    "CHECKER_SCOREBOARD_DEFECT",
    "STIMULUS_SEQUENCE_DEFECT",
    "VIP_DEFECT_OR_MISCONFIGURATION",
    "TESTBENCH_ENVIRONMENT_DEFECT",
    "DUT_RTL_DEFECT",
)
assert set(CLASSIFICATION_ORDER) == set(ROOT_CAUSE_CATEGORIES), (
    "CLASSIFICATION_ORDER must name exactly the eleven ROOT_CAUSE_CATEGORIES, "
    "no more and no fewer -- a category missing from this order could never "
    "be reached, and an extra name here would not be a real category."
)

#: Literal, case-insensitive phrases each category is recognised from. A
#: match is never a paraphrase or a guess -- the exact substring matched is
#: always carried on the result (`matched_evidence`) so a human can verify
#: the classification against the record's own real text.
_CATEGORY_PHRASES: Dict[str, Tuple[str, ...]] = {
    "KNOWN_LIMITATION_ACCEPTED_RISK": (
        "known limitation", "accepted risk", "will not fix", "won't fix",
        "wontfix", "documented limitation", "deferred limitation",
        "out of scope for this project",
    ),
    "FLAKY_NONDETERMINISTIC_BEHAVIOR": (
        "flaky test", "flaky failure", "intermittent failure",
        "intermittently fails", "nondeterministic", "non-deterministic",
        "not reproducible every run", "seed-dependent failure",
        "race-dependent test",
    ),
    "TOOLCHAIN_INFRASTRUCTURE_DEFECT": (
        "license server", "lsf queue", "simulator crash", "vcs crash",
        "verdi crash", "tool defect", "toolchain bug", "disk full",
        "out of memory", "compile toolchain", "eda tool bug",
    ),
    "CONFIGURATION_ERROR": (
        "misconfigured", "misconfiguration", "wrong configuration",
        "incorrect build option", "wrong command.txt argument",
        "configuration error", "wrong plusarg", "config error",
    ),
    "SPEC_REQUIREMENT_DEFECT": (
        "specification is ambiguous", "requirement is ambiguous",
        "spec does not define", "conflicting requirement",
        "specification error", "requirement gap", "specification gap",
        "undocumented behavior",
    ),
    "COVERAGE_MODEL_DEFECT": (
        "covergroup bug", "coverpoint error", "cross coverage defect",
        "coverage bin error", "coverage model defect", "coverage model bug",
    ),
    "CHECKER_SCOREBOARD_DEFECT": (
        "scoreboard bug", "scoreboard defect", "checker logic error",
        "reference model bug", "predictor mismatch",
        "comparison logic bug", "checker defect",
    ),
    "STIMULUS_SEQUENCE_DEFECT": (
        "sequence bug", "stimulus generation error",
        "constraint is too loose", "randomization bug",
        "sequence library defect", "sequence defect",
    ),
    "VIP_DEFECT_OR_MISCONFIGURATION": (
        "vip bug", "vip defect", "vip agent misconfigured",
        "vip sequence defect", "vip driver bug", "svt_",
    ),
    "TESTBENCH_ENVIRONMENT_DEFECT": (
        "testbench bug", "testbench defect", "tb defect", "monitor bug",
        "driver bug", "bind statement error", "environment bug",
    ),
    "DUT_RTL_DEFECT": (
        "rtl bug", "dut defect", "hardware bug", "register logic error",
        "fsm bug", "silicon defect", "design defect", "rtl defect",
    ),
}
assert set(_CATEGORY_PHRASES) == set(ROOT_CAUSE_CATEGORIES), (
    "_CATEGORY_PHRASES must carry exactly one phrase list per "
    "ROOT_CAUSE_CATEGORIES entry"
)


def _phrase_regex(phrase: str) -> "re.Pattern":
    escaped = re.escape(phrase)
    prefix = r"\b" if phrase[0].isalnum() else ""
    suffix = r"\b" if phrase[-1].isalnum() else ""
    return re.compile(prefix + escaped + suffix, re.IGNORECASE)


@dataclass
class RootCauseCategoryClassification:
    """One record's category classification result.

    `category` is one of `ROOT_CAUSE_CATEGORIES` or `UNCLASSIFIED` -- never
    anything else. `matched_evidence` is the exact substring of the input
    text the decision was made on (never a paraphrase or a fabricated
    example), empty only for `UNCLASSIFIED`."""
    category: str
    matched_evidence: str = ""
    matched_phrase: str = ""
    #: Populated ONLY by `classify_root_cause_category_checked()` below --
    #: `classify_root_cause_category()` itself never sets this, so every
    #: existing caller of the plain function is completely unaffected by
    #: this field's addition. When set, it is the real, honest
    #: `human_correction_lesson.has_prior_correction()` report for this
    #: exact text -- never a guessed or auto-applied override.
    prior_human_correction: Optional[Dict[str, Any]] = None


def classify_root_cause_category(text: Optional[str]) -> RootCauseCategoryClassification:
    """Classify a real, already-assembled text blob (see `_record_text_blob()`
    below for how one is built off a memory record) into one of
    `ROOT_CAUSE_CATEGORIES`, checked in `CLASSIFICATION_ORDER`. Text matching
    no recognised phrase reports `UNCLASSIFIED` -- never forced into one of
    the eleven named categories."""
    if not text or not str(text).strip():
        return RootCauseCategoryClassification(category=UNCLASSIFIED)
    for category in CLASSIFICATION_ORDER:
        for phrase in _CATEGORY_PHRASES[category]:
            match = _phrase_regex(phrase).search(text)
            if match:
                return RootCauseCategoryClassification(
                    category=category, matched_evidence=match.group(0), matched_phrase=phrase,
                )
    return RootCauseCategoryClassification(category=UNCLASSIFIED)


#: The `mistake_category` this module's own correction-check queries
#: `human_correction_lesson.py` under. A distinct, stable string so a
#: correction filed for THIS module's classification judgment can never be
#: confused with a correction filed elsewhere against the same input text.
CATEGORY_CLASSIFICATION_MISTAKE_CATEGORY = "root_cause_category_classification"


def classify_root_cause_category_checked(
    text: Optional[str], root,
) -> RootCauseCategoryClassification:
    """Additive, opt-in sibling of `classify_root_cause_category()` that
    ALSO checks whether a human has already corrected THIS EXACT text's
    root-cause-category judgment before -- via
    `human_correction_lesson.has_prior_correction()`, reused verbatim, never
    re-derived. `classify_root_cause_category()` itself, its phrase table,
    its priority order and every one of its existing callers are completely
    unchanged; this function only adds the missing check on top of it.

    It never overrides the recomputed classification with the prior
    correction's own free-text `after_claim` -- per `human_correction_lesson.py`'s
    own stated boundary ("it never decides whether the human's correction is
    itself correct"), auto-substituting an unstructured free-text claim for
    a structured category label would be exactly the kind of confident guess
    the Evidence Truth Rule forbids. Instead, a real prior correction is
    surfaced on the result's own `prior_human_correction` field -- the honest
    "has this exact judgment already been corrected once" answer the
    recomputed category was never checked against before -- leaving the
    caller/human free to act on it.

    `root` is required (not optional) so this checked variant can never be
    called by accident with the check silently skipped; a caller that
    genuinely has no project root to check against should call the plain
    `classify_root_cause_category()` instead."""
    result = classify_root_cause_category(text)
    if text and str(text).strip():
        report = has_prior_correction(
            root, before_claim=text, mistake_category=CATEGORY_CLASSIFICATION_MISTAKE_CATEGORY,
        )
        if report.get("found"):
            result.prior_human_correction = report
    return result


def _record_text_blob(record: Dict[str, Any]) -> str:
    """Combine a root_cause/verified_fix/debug_lesson record's own real,
    already-written free-text fields into one blob to classify -- never a
    fabricated summary. Only fields this project's real writers
    (`engine._promote_verified_fix_knowledge()`, a human's `dv-harness memory
    add`) actually populate are read."""
    parts: List[str] = []
    for key in ("title", "root_cause", "fix", "lesson", "note", "provenance"):
        value = record.get(key)
        if value:
            parts.append(str(value))
    symptoms = record.get("symptoms")
    if isinstance(symptoms, list):
        parts.extend(str(s) for s in symptoms if s)
    elif isinstance(symptoms, str) and symptoms.strip():
        parts.append(symptoms)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLOSED-record eligibility -- reused, never re-derived, from
# memory_router.route_memory() / engineering_admission_gate().
# ---------------------------------------------------------------------------

#: This module's own closure-status vocabulary. Deliberately distinct from
#: `models.Status` (checked disjoint below) and from
#: `memory_router.route_memory()`'s destination strings -- this answers
#: "is this record eligible for cross-project root-cause aggregation", a
#: narrower question than "which memory tier does this route to".
NOT_ROOT_CAUSE_RECORD = "NOT_ROOT_CAUSE_RECORD"
NOT_YET_CLOSED = "NOT_YET_CLOSED"
CLOSED_ELIGIBLE = "CLOSED_ELIGIBLE"

CLOSURE_STATUSES: Tuple[str, ...] = (NOT_ROOT_CAUSE_RECORD, NOT_YET_CLOSED, CLOSED_ELIGIBLE)


class RcaOntologyError(ValueError):
    """A caller-usage error -- a record that is not a dict, or a malformed
    aggregation input. Never raised for a record that is simply not (yet)
    closed; that is a normal, expected `NOT_YET_CLOSED` result."""


def closure_status(record: Dict[str, Any], root=None) -> Tuple[str, List[str]]:
    """Is `record` a real, gate-verified CLOSED root_cause/verified_fix/
    debug_lesson record -- reused directly from the two real functions that
    already decide this, never re-derived:

    1. `memory_router.route_memory(record) == "ENGINEERING_MEMORY"` -- the
       SAME kind-is-root-cause-shaped-and-declared-verified check every real
       write path in this project already goes through. A record failing
       this is `NOT_ROOT_CAUSE_RECORD` (wrong kind, or `verified` not True).
    2. `memory_router.engineering_admission_gate(record, root=root)` -- the
       real three-gate bar (evidence, confidence, a reusable claim) that
       turns a caller-supplied `verified: True` label into something this
       project actually trusts. A record failing this is `NOT_YET_CLOSED`,
       carrying the gate's own real reason codes.

    Returns `(status, reasons)` -- `reasons` is empty only for
    `CLOSED_ELIGIBLE`."""
    if not isinstance(record, dict):
        raise RcaOntologyError(f"expected a dict record, got {type(record)!r}")
    if memory_router.route_memory(record) != "ENGINEERING_MEMORY":
        return NOT_ROOT_CAUSE_RECORD, ["KIND_NOT_ROOT_CAUSE_SHAPED_OR_NOT_DECLARED_VERIFIED"]
    admitted, reasons = memory_router.engineering_admission_gate(record, root=root)
    if not admitted:
        return NOT_YET_CLOSED, reasons
    return CLOSED_ELIGIBLE, []


# ---------------------------------------------------------------------------
# (2) Canonical failure-signature normalizer -- reuses
# sim_log_analysis.normalize_failure_signature() + evidence_db.signature_key()
# rather than a third/fourth definition of "same failure".
# ---------------------------------------------------------------------------

@dataclass
class CanonicalFailureSignature:
    signature: Dict[str, Any]
    signature_key: str


def canonical_failure_signature(*, protocol: Optional[str] = None, pattern: Optional[str] = None,
                                  symptom: Optional[str] = None, root_cause_hint: Optional[str] = None,
                                  uvm_error_count: int = 0, uvm_fatal_count: int = 0,
                                  assertion_failure: bool = False, simulator_crash: bool = False,
                                  terminal_signature: Optional[str] = None, lsf_status: Optional[str] = None,
                                  extra_text: Optional[str] = None, vip_agent: Optional[str] = None,
                                  resource: Optional[str] = None,
                                  normalize_text: bool = True) -> CanonicalFailureSignature:
    """The ONE canonical "what does this failure look like, and is it the
    SAME failure as another record" computation this module offers.

    `normalize_text=True` (the default) first runs every free-text field
    through `sim_log_analysis.normalize_failure_signature()` -- the SAME
    normalization `loop_budget.py`'s circuit breaker already keys its
    REPEATED_IDENTICAL_FAILURE trigger on -- so cosmetic variance
    (timestamps, hex addresses, random seeds, large decimal counters
    embedded mid-message) never manufactures two different signature keys
    for the same real failure. The normalized dict is then built by
    `memory_vault.build_failure_signature()` (the ONE canonical shape) and
    hashed by `evidence_db.signature_key()` (the ONE stable key
    `cross_project_mining.py`/`capability_evolution.py`/`loop_budget.py`
    already group/accumulate `occurrence_count` by). Never a third or fourth
    definition of "same failure"."""
    if normalize_text:
        if symptom:
            symptom = normalize_failure_signature(symptom)
        if root_cause_hint:
            root_cause_hint = normalize_failure_signature(root_cause_hint)
        if extra_text:
            extra_text = normalize_failure_signature(extra_text)
    sig = build_failure_signature(
        protocol=protocol, pattern=pattern, symptom=symptom, root_cause_hint=root_cause_hint,
        uvm_error_count=uvm_error_count, uvm_fatal_count=uvm_fatal_count,
        assertion_failure=assertion_failure, simulator_crash=simulator_crash,
        terminal_signature=terminal_signature, lsf_status=lsf_status, extra_text=extra_text,
        vip_agent=vip_agent, resource=resource,
    )
    return CanonicalFailureSignature(signature=sig, signature_key=_evidence_signature_key(sig))


def canonical_signature_for_record(record: Dict[str, Any],
                                     normalize_text: bool = True) -> CanonicalFailureSignature:
    """Extract `canonical_failure_signature()`'s inputs off a real
    root_cause/verified_fix/debug_lesson record's own already-written
    fields -- never guessed, never invented. `symptom` prefers the record's
    first declared `symptoms[0]`, falling back to its own `root_cause` text
    when no symptom was separately recorded (the shape
    `engine._promote_verified_fix_knowledge()` writes: `symptoms` may be
    empty when `root_cause_evidence_gate` supplied no separate symptom
    text)."""
    if not isinstance(record, dict):
        raise RcaOntologyError(f"expected a dict record, got {type(record)!r}")
    symptoms = record.get("symptoms")
    symptom: Optional[str] = None
    if isinstance(symptoms, list) and symptoms:
        symptom = str(symptoms[0])
    elif isinstance(symptoms, str) and symptoms.strip():
        symptom = symptoms
    elif record.get("root_cause"):
        symptom = str(record.get("root_cause"))
    root_cause_hint = str(record["root_cause"]) if record.get("root_cause") else None
    verification = record.get("verification") if isinstance(record.get("verification"), dict) else {}
    return canonical_failure_signature(
        protocol=record.get("protocol"),
        pattern=record.get("pattern") or record.get("test_name"),
        symptom=symptom,
        root_cause_hint=root_cause_hint,
        terminal_signature=record.get("terminal_signature"),
        lsf_status=record.get("lsf_status"),
        vip_agent=record.get("vip_agent"),
        resource=record.get("resource"),
        normalize_text=normalize_text,
    )


# ---------------------------------------------------------------------------
# Cross-project-aggregation-ready assembly: joins closure eligibility, the
# category ontology, and the canonical signature for one or many records.
# Performs no cross-project store lookup itself -- that stays
# cross_project_mining.py's real, separate mechanism.
# ---------------------------------------------------------------------------

@dataclass
class RootCauseAggregationRecord:
    memory_id: Optional[str]
    closure_status: str
    closure_reasons: List[str] = field(default_factory=list)
    category: Optional[str] = None
    matched_evidence: str = ""
    signature_key: Optional[str] = None
    signature: Optional[Dict[str, Any]] = None


def classify_closed_root_cause_record(record: Dict[str, Any], root=None) -> RootCauseAggregationRecord:
    """One record's full assembly: closure eligibility (reused), category
    (this module's own ontology), and canonical signature (reused). A
    record that is not `CLOSED_ELIGIBLE` is returned with `category`/
    `signature_key` both `None` -- never categorized or keyed, per this
    module's own governing rule that an unverified/ungated finding must
    never enter cross-project aggregation as if it were reliable data."""
    memory_id = record.get("memory_id") or record.get("id") if isinstance(record, dict) else None
    status, reasons = closure_status(record, root=root)
    if status != CLOSED_ELIGIBLE:
        return RootCauseAggregationRecord(
            memory_id=memory_id, closure_status=status, closure_reasons=reasons,
        )
    classification = classify_root_cause_category(_record_text_blob(record))
    canonical = canonical_signature_for_record(record)
    return RootCauseAggregationRecord(
        memory_id=memory_id, closure_status=status, closure_reasons=[],
        category=classification.category, matched_evidence=classification.matched_evidence,
        signature_key=canonical.signature_key, signature=canonical.signature,
    )


@dataclass
class RootCauseAggregationReport:
    records: List[RootCauseAggregationRecord]
    category_counts: Dict[str, int]
    signature_groups: Dict[str, List[Optional[str]]]
    excluded_count: int

    def eligible_records(self) -> List[RootCauseAggregationRecord]:
        return [r for r in self.records if r.closure_status == CLOSED_ELIGIBLE]


def aggregate_root_cause_categories(records: Sequence[Dict[str, Any]], root=None) -> RootCauseAggregationReport:
    """Classify a batch of records for cross-project aggregation. Only
    `CLOSED_ELIGIBLE` records contribute to `category_counts` /
    `signature_groups` -- every record is still returned in `records`
    (including the excluded ones, with their real closure reasons), so a
    caller can always see WHY a record did not contribute, never a silently
    shrunk total."""
    if not isinstance(records, (list, tuple)):
        raise RcaOntologyError(f"expected a list/tuple of records, got {type(records)!r}")
    results = [classify_closed_root_cause_record(r, root=root) for r in records]
    category_counts: Dict[str, int] = {}
    signature_groups: Dict[str, List[Optional[str]]] = {}
    excluded = 0
    for r in results:
        if r.closure_status != CLOSED_ELIGIBLE:
            excluded += 1
            continue
        category_counts[r.category] = category_counts.get(r.category, 0) + 1
        signature_groups.setdefault(r.signature_key, []).append(r.memory_id)
    return RootCauseAggregationReport(
        records=results, category_counts=category_counts,
        signature_groups=signature_groups, excluded_count=excluded,
    )


# ---------------------------------------------------------------------------
# Vocabulary-disjointness guards -- run at import, not merely claimed.
# ---------------------------------------------------------------------------

def assert_disjoint_from_command_error_taxonomy() -> None:
    """This module's ROOT_CAUSE_CATEGORIES must share no token with
    `command_error_taxonomy.py`'s per-command-dispatch vocabulary --
    deliberately different questions (see module docstring). The shared
    `UNCLASSIFIED` fallback word is deliberately excluded from this check,
    the same convention `system_failure_taxonomy.py` already applies to its
    own comparison against the same module."""
    from . import command_error_taxonomy as _cet
    collision = set(ROOT_CAUSE_CATEGORIES).intersection(set(_cet.CATEGORIES))
    if collision:
        raise AssertionError(
            f"rca_ontology vocabulary collides with command_error_taxonomy's "
            f"per-command-dispatch vocabulary on {sorted(collision)} -- these are "
            "two deliberately separate questions and must not merge"
        )


def assert_disjoint_from_system_failure_taxonomy() -> None:
    """This module's ROOT_CAUSE_CATEGORIES must share no token with
    `system_failure_taxonomy.py`'s system-integration-failure vocabulary --
    deliberately different questions (see module docstring). The shared
    `UNCLASSIFIED` fallback word is deliberately excluded."""
    from . import system_failure_taxonomy as _sft
    collision = set(ROOT_CAUSE_CATEGORIES).intersection(set(_sft.FAILURE_CATEGORIES))
    if collision:
        raise AssertionError(
            f"rca_ontology vocabulary collides with system_failure_taxonomy's "
            f"system-integration-failure vocabulary on {sorted(collision)} -- these "
            "are two deliberately separate questions and must not merge"
        )


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's category vocabulary AND its closure-status vocabulary
    must share no token with `dv_harness.models.Status`, the harness's
    stage-gate verdict vocabulary -- a root-cause classification, or a
    closure-eligibility status, must never be confusable with a stage
    verdict."""
    from .models import Status

    verdicts = {s.value for s in Status}
    vocabulary = set(ROOT_CAUSE_CATEGORIES) | {UNCLASSIFIED} | set(CLOSURE_STATUSES)
    collision = vocabulary.intersection(verdicts)
    if collision:
        raise AssertionError(
            f"rca_ontology vocabulary collides with models.Status on "
            f"{sorted(collision)} -- a root-cause classification must never be "
            "confusable with a stage-gate verdict"
        )


assert_disjoint_from_command_error_taxonomy()
assert_disjoint_from_system_failure_taxonomy()
assert_no_verification_verdict_vocabulary()


# ---------------------------------------------------------------------------
# Standalone front door -- no dv-harness CLI verb is registered here per this
# batch's own guidance (avoid cli.py/gates.py under heavy concurrent edit).
# ---------------------------------------------------------------------------

def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m dv_harness.rca_ontology categories|classify --records <file.json>
    [--root <dir>]`. `categories` prints the ontology; `classify` reads a JSON
    array of records and prints the aggregation report. Exit 0 = every record
    resolved (whatever its status); 1 = malformed input; 2 = no records given
    at all."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="python -m dv_harness.rca_ontology")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("categories")
    classify_p = sub.add_parser("classify")
    classify_p.add_argument("--records", required=True)
    classify_p.add_argument("--root", default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "categories":
        for cat in ROOT_CAUSE_CATEGORIES:
            print(cat)
        return 0

    records_path = Path(args.records)
    if not records_path.exists():
        print(f"NOT_AVAILABLE: {records_path} does not exist")
        return 2
    try:
        records = json.loads(records_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"MALFORMED_INPUT: {exc}")
        return 1
    if not isinstance(records, list) or not records:
        print("NOT_AVAILABLE: no records to classify")
        return 2

    root = Path(args.root) if args.root else None
    try:
        report = aggregate_root_cause_categories(records, root=root)
    except RcaOntologyError as exc:
        print(f"MALFORMED_INPUT: {exc}")
        return 1

    print(f"eligible={len(report.eligible_records())} excluded={report.excluded_count}")
    for category, count in sorted(report.category_counts.items()):
        print(f"  {category}: {count}")
    for sig_key, ids in sorted(report.signature_groups.items()):
        print(f"  signature {sig_key[:12]}...: {ids}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> None:
    raise SystemExit(execute_verb(argv))


if __name__ == "__main__":
    main()
