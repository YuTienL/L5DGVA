"""dv_harness/knowledge_conflict_resolver.py -- resolves a conflict between
TWO MEMORY-TIER RECORDS, not between two document sources.

WHY THIS MODULE EXISTS (2026-09-06 gap, item `knowledge_conflict_resolver`).
`dv_harness/source_authority.py`'s own module docstring already draws the
line this module sits on the other side of: its 9-level `AUTHORITY_ORDER`
and `resolve_conflict()` decide which of two ALREADY-READ DOCUMENT/artifact
sources (simulation result, RTL, register file, controller doc, VIP
example, ...) is true, by a fixed authority order a human wrote down once.
Nothing in this repo answered the DIFFERENT question this item names: two
records already living in this project's own 5-tier MEMORY store (see
`dv_harness/memory.py`'s `MEMORY_LEVELS`) state DIFFERENT claims about the
SAME subject -- concretely, a `kind="verified_fix"`/`"root_cause"` record at
Engineering tier states a root cause a `promote_to_organizational()`-minted
Organizational-tier record for the same protocol does not agree with. A
repo-wide grep for `knowledge_conflict`/`KnowledgeConflict`/
`memory_conflict`/`MEMORY_CONFLICT` before this file was written found
nothing.

WHY MEMORY TIER IS NOT A SECOND AUTHORITY ORDER, AND WHY THIS MODULE MUST
NEVER PICK A WINNER THE WAY `source_authority.resolve_conflict()` DOES.
This project's own Core Operating Rules (CLAUDE.md) state plainly: "Memory
is prior knowledge, not current evidence" and "Any current root cause must
be revalidated with current evidence." `memory_router.
ORGANIZATIONAL_MIN_CONFIRMATIONS`/`promote_to_organizational()`'s three
gates mean Organizational tier certifies that a claim was independently
RE-DERIVED at least twice under a qualitative/confidence/confirmation-count
bar -- it is a statement about how much CORROBORATION a claim has
accumulated, never a statement that the claim is still true today. An
Engineering-tier record can be newer, more specific, or simply correct
where an older Organizational-tier record has gone stale (RTL changed, a
prior fix regressed, a corner case was missed the first two times). So
unlike `AUTHORITY_ORDER`, memory tier carries NO fixed rank a conflict can
be resolved against mechanically: `resolve_memory_conflict()` below never
returns a "which one wins" verdict, only NO_CONFLICT / a genuine
MEMORY_TIER_CONFLICT / NOT_COMPARABLE -- and every MEMORY_TIER_CONFLICT is
mandatory human escalation, exactly like `source_authority.resolve_conflict
()`'s own `UNDECIDABLE_SAME_AUTHORITY` case, applied here to EVERY
disagreement rather than only a same-rank tie (because for memory records,
every pair is effectively a same-rank tie -- there is no rank at all).

REUSE, NOT REINVENT -- THE ESCALATION HALF. `source_authority.
escalate_conflict()` cannot be called directly here: it builds a
`SourceClaim` per side, and `SourceClaim.__post_init__` calls
`normalize_source()`, which RAISES on anything outside the 9
`AUTHORITY_ORDER` ids/aliases -- "engineering_memory tier"/"organizational
_memory tier" are not, and were never meant to be, members of that list
(adding them there would be exactly the mis-identification `source_
authority.py`'s own docstring warns a second, differently-scoped 9/10-item
list has already caused once). What this module reuses instead is the
REAL, SANCTIONED generalization of `escalate_conflict()`'s own question-
queue mechanism for exactly this situation:
`question_queue.build_multiple_choice_question()`, whose own docstring
states it is "the N >= 2 generalization of `source_authority.
escalate_conflict()`'s exactly-2-option shape" and that it "reuses this
module's own `add_question()` / `make_question_key()` exactly as
`escalate_conflict` already does -- there is no second filing mechanism."
`escalate_memory_conflict()` below calls that function directly: same
Q-ID derivation, same Tier-3 (`affects_spec_intent`) classification, same
per-option evidence-path citation and the same idempotent-on-`question_key`
re-filing discipline `escalate_conflict()` uses -- there is exactly one
question-queue escalation code path in this project, in
`question_queue.py`, and this module is a caller of it, not a second one.

WHAT THIS MODULE DOES AND DOES NOT DO. `extract_memory_claim()` turns one
raw MemoryStore record into a `MemoryClaim` -- refusing (never guessing) a
record missing a tier, a `memory_id`, a subject (`protocol`), or a reusable
claim field (`memory_router.ENGINEERING_REUSABLE_CLAIM_FIELDS` -- imported,
not re-typed: "root_cause"/"fix"/"lesson", the same fields that module's own
`engineering_admission_gate()` already requires for a record to be a
"reusable claim" at all). `resolve_memory_conflict()` compares one
Engineering-tier claim against one Organizational-tier claim about the
supposedly-same subject and reports NO_CONFLICT (same claim, normalized),
NOT_COMPARABLE_DIFFERENT_SUBJECT (different subject -- comparing them at all
would be the fabrication this module exists to refuse), or
MEMORY_TIER_CONFLICT (a real, textual disagreement -- mandatory escalation,
never a resolved value). `escalate_memory_conflict()` files that conflict as
a real blocking question via `build_multiple_choice_question()`, or returns
None for a NO_CONFLICT/NOT_COMPARABLE verdict (agreement, or an
apples-to-oranges pair, is not a question). `find_tier_conflicts()` is the
convenience detector: it scans a real `MemoryStore`'s ACTIVE
Engineering/Organizational records and reports every real conflict among
them, skipping (never crashing on) any record this module cannot even
extract a claim from.

This module authors no conclusion, decides no protocol, and picks no
winner. It only detects a genuine, textual, evidence-cited disagreement
between two memory tiers and files it where a human already answers
everything else this project cannot decide mechanically: the real question
queue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .memory import MEMORY_LEVELS, MemoryStore
from .memory_router import ENGINEERING_REUSABLE_CLAIM_FIELDS
from . import question_queue


class KnowledgeConflictResolverError(ValueError):
    """Typed error, same convention as `source_authority.SourceAuthorityError`
    and every other typed error in this package: a short SCREAMING_SNAKE_CASE
    `reason` plus a concrete `detail` dict -- never a silently-dropped claim
    or a silently-guessed field."""

    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


#: The two tiers this item is explicitly scoped to (its own `detail`: "an
#: Engineering-tier record contradicting an Organizational-tier one").
#: `resolve_memory_conflict()` refuses any other tier pairing rather than
#: silently widening scope to a pairing this module was never asked to
#: reason about (e.g. two Engineering-tier records, or Project vs Working).
ENGINEERING_TIER = "engineering"
ORGANIZATIONAL_TIER = "organizational"
assert ENGINEERING_TIER in MEMORY_LEVELS and ORGANIZATIONAL_TIER in MEMORY_LEVELS

#: Both records state the same claim (after whitespace/case normalization)
#: about the same subject -- agreement is not a question.
VERDICT_NO_CONFLICT = "NO_CONFLICT"
#: The two records name different subjects (`protocol`) -- comparing their
#: claims would compare unrelated statements, which is not a conflict at
#: all and must never be reported as one.
VERDICT_NOT_COMPARABLE = "NOT_COMPARABLE_DIFFERENT_SUBJECT"
#: A real, textual disagreement about the same subject. There is
#: deliberately no "RESOLVED" verdict here (contrast
#: `source_authority.VERDICT_RESOLVED`): memory tier carries no fixed
#: authority rank, so every conflict this module finds is mandatory human
#: escalation, never a mechanically-decided winner.
VERDICT_CONFLICT = "MEMORY_TIER_CONFLICT"


@dataclass
class MemoryClaim:
    """One memory record's claim about one subject, WITH the file:line-style
    evidence path a human can actually go check.

    Mirrors `source_authority.SourceClaim`'s own discipline deliberately: a
    claim without a checkable evidence path is not evidence, and the whole
    point of this type is to make the escalation this module exists to build
    carry BOTH sides' evidence paths -- the only reliable way to guarantee
    that is to make an un-cited claim unconstructable, rather than checking
    for it at the far end where it is already too late (see
    `extract_memory_claim()`, the sole constructor)."""
    level: str
    memory_id: str
    subject: str
    claim_field: str
    claim: str
    evidence_path: str
    confidence: str
    status: str
    kind: str
    record: dict = field(default_factory=dict, repr=False)

    @property
    def label(self) -> str:
        """Human-facing one-liner used as a question-queue option label,
        mirroring `SourceClaim.label`'s shape."""
        return (f"Trust the {self.level}-tier memory record {self.memory_id} "
                f"(kind={self.kind or 'unspecified'}, confidence={self.confidence}): "
                f"{self.claim}")

    def to_dict(self) -> dict:
        return {
            "level": self.level, "memory_id": self.memory_id, "subject": self.subject,
            "claim_field": self.claim_field, "claim": self.claim,
            "evidence_path": self.evidence_path, "confidence": self.confidence,
            "status": self.status, "kind": self.kind, "label": self.label,
        }


def extract_memory_claim(record: Dict[str, Any]) -> MemoryClaim:
    """The one constructor for `MemoryClaim`. Raises `KnowledgeConflictResolverError`
    -- never silently defaults or guesses -- on a record missing any of the
    four facts a conflict cannot be reasoned about without: a real MEMORY_LEVELS
    tier, a `memory_id` (so the escalation can cite it), a subject to
    correlate against (`protocol`), and a reusable claim
    (`memory_router.ENGINEERING_REUSABLE_CLAIM_FIELDS`, checked in that
    module's own declared order -- root_cause, then fix, then lesson; the
    first non-empty one found is the claim, exactly the "reusable engineering
    claim" test `memory_router.engineering_admission_gate()` already applies
    one layer up).

    The evidence path is a real, runnable command a human can use to pull the
    full record back up (`python -m dv_harness.memory_cli get <memory_id>`,
    the same verb `dv-harness memory get` already wraps) -- not a guessed
    file:line, since a memory record has no source file of its own; the
    record itself, addressable by its own id, is the evidence."""
    if not isinstance(record, dict):
        raise KnowledgeConflictResolverError("MEMORY_RECORD_MUST_BE_A_DICT", {
            "got": type(record).__name__,
        })
    level = record.get("level")
    if level not in MEMORY_LEVELS:
        raise KnowledgeConflictResolverError("MEMORY_RECORD_MISSING_OR_UNKNOWN_LEVEL", {
            "level": level, "known_levels": list(MEMORY_LEVELS),
        })
    memory_id = record.get("memory_id")
    if not str(memory_id or "").strip():
        raise KnowledgeConflictResolverError("MEMORY_RECORD_MISSING_ID", {
            "level": level,
        })
    subject = record.get("protocol")
    if not str(subject or "").strip():
        raise KnowledgeConflictResolverError("MEMORY_RECORD_MISSING_SUBJECT", {
            "memory_id": memory_id, "level": level,
            "hint": "a subject (the record's own `protocol` field) is required to correlate "
                    "two records as being about the same thing; a record without one cannot "
                    "be compared against another, only reported as unable to be compared.",
        })
    claim_field = None
    claim = None
    for f in ENGINEERING_REUSABLE_CLAIM_FIELDS:
        v = record.get(f)
        if v and str(v).strip():
            claim_field = f
            claim = str(v).strip()
            break
    if claim is None:
        raise KnowledgeConflictResolverError("MEMORY_RECORD_MISSING_CLAIM", {
            "memory_id": memory_id, "level": level,
            "checked_fields": list(ENGINEERING_REUSABLE_CLAIM_FIELDS),
            "hint": "a record carrying none of root_cause/fix/lesson is a note about a run, "
                    "not a reusable engineering claim that can conflict with anything -- see "
                    "memory_router.ENGINEERING_REUSABLE_CLAIM_FIELDS.",
        })
    evidence_path = f"python -m dv_harness.memory_cli get {memory_id}"
    return MemoryClaim(
        level=str(level), memory_id=str(memory_id), subject=str(subject).strip(),
        claim_field=claim_field, claim=claim, evidence_path=evidence_path,
        confidence=str(record.get("confidence") or "UNKNOWN"),
        status=str(record.get("status") or "ACTIVE"),
        kind=str(record.get("kind") or ""),
        record=dict(record),
    )


def _normalize_claim_text(text: str) -> str:
    """Whitespace/case-insensitive comparison only -- the same "collapse
    representation noise, never substance" discipline `spec_vplan_delta.py`
    applies to its own content-field comparison. A claim differing only in
    capitalization or line-wrapping is not a conflict; a claim naming a
    genuinely different root cause is, however similarly worded."""
    return " ".join(str(text or "").split()).strip().lower()


def resolve_memory_conflict(engineering_record: Dict[str, Any],
                             organizational_record: Dict[str, Any]) -> Dict[str, Any]:
    """Apply this module's own discipline (see the module docstring) to one
    Engineering-tier record and one Organizational-tier record.

    Returns a dict with:
      verdict   NO_CONFLICT | NOT_COMPARABLE_DIFFERENT_SUBJECT | MEMORY_TIER_CONFLICT
      claims    both sides' `MemoryClaim.to_dict()`, always present
      subject   the shared subject, when the verdict is NO_CONFLICT/CONFLICT
      rule      the exact reasoning sentence this verdict applied

    Never returns a "winner": there is deliberately no field naming which
    side is correct, unlike `source_authority.resolve_conflict()`'s own
    `winner`/`losers` -- memory tier carries no rank a winner could be
    derived from (see the module docstring). Raises
    `KnowledgeConflictResolverError("WRONG_TIER_PAIR", ...)` if the two
    records are not literally an Engineering-tier record and an
    Organizational-tier record (in either parameter -- this item's own
    scope; a same-tier or other-tier pairing is a different, unbuilt
    question)."""
    eng = extract_memory_claim(engineering_record)
    org = extract_memory_claim(organizational_record)
    if eng.level != ENGINEERING_TIER or org.level != ORGANIZATIONAL_TIER:
        raise KnowledgeConflictResolverError("WRONG_TIER_PAIR", {
            "engineering_record_level": eng.level,
            "organizational_record_level": org.level,
            "hint": "resolve_memory_conflict() is scoped to exactly one Engineering-tier "
                    "record and one Organizational-tier record, per this item's own "
                    "detail -- call it as (engineering_record, organizational_record).",
        })

    base = {"claims": [eng.to_dict(), org.to_dict()]}

    if eng.subject.strip().lower() != org.subject.strip().lower():
        return {
            **base, "verdict": VERDICT_NOT_COMPARABLE,
            "subject_engineering": eng.subject, "subject_organizational": org.subject,
            "rule": (
                f"The Engineering-tier record ({eng.memory_id}) names subject "
                f"{eng.subject!r} and the Organizational-tier record ({org.memory_id}) "
                f"names subject {org.subject!r} -- different subjects, so their claims are "
                "not compared. Reporting a conflict between unrelated claims would be "
                "exactly the fabrication this module exists to refuse."
            ),
        }

    if _normalize_claim_text(eng.claim) == _normalize_claim_text(org.claim):
        return {
            **base, "verdict": VERDICT_NO_CONFLICT, "subject": eng.subject,
            "rule": f"Both records state the same claim for {eng.subject!r}; no conflict.",
        }

    return {
        **base, "verdict": VERDICT_CONFLICT, "subject": eng.subject,
        "rule": (
            f"The Engineering-tier record ({eng.memory_id}) and the Organizational-tier "
            f"record ({org.memory_id}) disagree about {eng.subject!r}. Memory tier is NOT "
            "a source-authority order (Core Operating Rules: \"Memory is prior knowledge, "
            "not current evidence\"; \"Any current root cause must be revalidated with "
            "current evidence\") -- Organizational tier confirms a claim was independently "
            "re-derived at least twice, it does not confirm the claim is still true today, "
            "and the Engineering-tier record may simply be more recent, more specific "
            "evidence. Neither tier may be trusted over the other mechanically; a human "
            "must decide which claim, if either, is still correct."
        ),
    }


def escalate_memory_conflict(store: Union["question_queue.QuestionQueueStore", str, Path],
                              conflict: Dict[str, Any], *, domain: str,
                              context_path: Optional[str] = None,
                              question_key: Optional[str] = None,
                              extra_context: Optional[Dict[str, Any]] = None,
                              now=None) -> Optional[dict]:
    """File one `resolve_memory_conflict()` MEMORY_TIER_CONFLICT into the
    REAL question queue and return the persisted record. Returns None (asks
    nothing) for NO_CONFLICT or NOT_COMPARABLE_DIFFERENT_SUBJECT -- agreement,
    and an apples-to-oranges pair, are not questions.

    `store` accepts a `question_queue.QuestionQueueStore` or a project-root
    path to build one from -- the same convenience
    `source_authority.escalate_conflict()` already offers, reused here so
    both escalation paths in this project accept the same argument shape.

    THE REUSE THIS MODULE EXISTS TO MAKE HONEST: this calls
    `question_queue.build_multiple_choice_question()` -- the N-ary
    generalization of `source_authority.escalate_conflict()`'s own
    question-queue filing (same `add_question()`/`make_question_key()` call,
    same Tier-3 `affects_spec_intent` classification, same idempotent-on-
    `question_key` re-filing discipline) -- rather than hand-rolling a
    second `add_question()` call or a second Q-ID/tier scheme. There is
    exactly one question-queue escalation mechanism in this project; this
    function is a caller of it, precisely as `escalate_conflict()` itself
    is.

    Raises `KnowledgeConflictResolverError("UNKNOWN_CONFLICT_VERDICT", ...)`
    for anything other than the three verdicts `resolve_memory_conflict()`
    can produce."""
    verdict = conflict.get("verdict")
    if verdict in (VERDICT_NO_CONFLICT, VERDICT_NOT_COMPARABLE):
        return None
    if verdict != VERDICT_CONFLICT:
        raise KnowledgeConflictResolverError("UNKNOWN_CONFLICT_VERDICT", {"verdict": verdict})

    if isinstance(store, (str, Path)):
        store = question_queue.QuestionQueueStore(Path(store))

    claims = conflict.get("claims") or []
    if len(claims) != 2:
        raise KnowledgeConflictResolverError("CONFLICT_MUST_CARRY_EXACTLY_TWO_CLAIMS", {
            "claim_count": len(claims),
        })

    candidates = [
        {
            "label": c["label"],
            "evidence_path": c["evidence_path"],
            "rationale": f"{c['level']}-tier {c['claim_field']} claim (status={c['status']})",
        }
        for c in claims
    ]
    subject = conflict.get("subject") or "memory conflict"

    return question_queue.build_multiple_choice_question(
        store,
        domain=domain,
        subject=subject,
        candidates=candidates,
        context_path=context_path or claims[0]["evidence_path"],
        question_key=question_key,
        extra_context=extra_context,
        now=now,
    )


def find_tier_conflicts(memory_store: "MemoryStore") -> List[Dict[str, Any]]:
    """Scan a real `MemoryStore` for every genuine Engineering-vs-
    Organizational conflict among its ACTIVE records: every ACTIVE
    Engineering-tier record paired against every ACTIVE Organizational-tier
    record sharing a `protocol`, kept only when `resolve_memory_conflict()`
    reports `MEMORY_TIER_CONFLICT`.

    A record this module cannot even extract a claim from (missing subject,
    missing claim, ...) is silently EXCLUDED from this scan -- this is a
    detector over the store's real records as they stand, not a validator of
    every record's shape, and one malformed record must never crash a
    whole-store scan looking for real conflicts elsewhere. Returns an empty
    list, honestly, when nothing conflicts (including when the store holds
    no Engineering or no Organizational records at all)."""
    engineering = memory_store.find(ENGINEERING_TIER, status="ACTIVE")
    organizational = memory_store.find(ORGANIZATIONAL_TIER, status="ACTIVE")
    conflicts: List[Dict[str, Any]] = []
    for org_rec in organizational:
        try:
            extract_memory_claim(org_rec)
        except KnowledgeConflictResolverError:
            continue
        for eng_rec in engineering:
            try:
                conflict = resolve_memory_conflict(eng_rec, org_rec)
            except KnowledgeConflictResolverError:
                continue
            if conflict["verdict"] == VERDICT_CONFLICT:
                conflicts.append(conflict)
    return conflicts
