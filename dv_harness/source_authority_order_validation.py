"""dv_harness/source_authority_order_validation.py -- a standalone, read-only report comparing
`source_authority.py`'s real, fixed 9-level `AUTHORITY_ORDER` against which side a real human has
actually picked, in practice, over this project's own real history of answered Tier-3 conflict
escalations filed by `source_authority.escalate_conflict()` / `question_queue.QuestionQueueStore`.

THE GAP THIS CLOSES. `source_authority.py`'s own module docstring states the 9-level order's whole
point: "which of two already-read sources is TRUE" is decided by a fixed authority order, not by
"which one an agent happened to read last, and not by judgment." `escalate_conflict()` already files
every real mismatch as a Tier-3 blocking question, carrying both sides' evidence and an
AUTHORITY_ORDER-derived `recommendation` -- and a human answering that question is real, cited
ground truth about which side actually turned out to be correct. Nothing in this repo ever compared
the two: whether the fixed order's own recommendation agrees with what humans keep actually deciding
is a real, checkable question this module answers, and only reports -- it never edits
`AUTHORITY_ORDER` itself (that stays a human decision, exactly like every other production-behavior
change in this project).

REUSE OVER REINVENT. This module performs no source-authority arithmetic of its own: `AUTHORITY_ORDER`
is read directly from `source_authority.py` (imported, never re-typed), and every candidate side of a
conflict is identified from the SAME real text `source_authority.SourceClaim.label`/`_option_for()`
already produce for every `escalate_conflict()`-filed question -- `"Trust the {doc_phrase}{qualifier}
(tier {rank}): {claim}"` for the label, `"evidence: {evidence_path}"` for the rationale (see
`source_authority.py`'s own `_option_for()`). A record is recognised as a real source-authority
conflict escalation ONLY when every one of its 2-3 options carries BOTH shapes AND resolves,
unambiguously, to one of the 9 real `AUTHORITY_ORDER` entries -- never from a `domain`/`question_key`
guess, since `escalate_conflict()`'s own `domain` argument is caller-chosen free text with no fixed
value, and multiple detectors in this project already file through it under different domains.

THE EVIDENCE TRUTH RULE, APPLIED TO "WHICH SIDE DID THE HUMAN PICK". A human's real answer
(`QuestionQueueStore.answer_question(answer=..., basis=...)`) is genuinely free text -- proven by this
project's own real test fixture, `store.answer_question(first["id"], answer="the doc is stale; RTL is
right", ...)` -- never constrained to echo an offered option's label verbatim. So this module never
GUESSES which side that text means: it looks for real, literal evidence in the human's own words, in a
fixed, disclosed order of decreasing certainty -- (1) a literal citation of one candidate's own
`evidence_path` (the strongest possible signal: the human named the exact file:line/artifact that
side's evidence lives at); (2) a whole-word, case-insensitive mention of one candidate's own canonical
source id, `doc_phrase`, or one of `AUTHORITY_ORDER`'s own already-registered aliases for that source
(the SAME alias table `source_authority.normalize_source()` uses, never a second one). Two or more
candidates matching at either tier is honestly `AMBIGUOUS` (both sides are cited, or the wording is
genuinely undecidable from this text); no candidate matching is honestly `UNRESOLVED_NO_MATCH`. Neither
is ever collapsed into a guessed pick, and neither counts toward the overall match/mismatch tally --
only a case where BOTH the authority order predicts a real (non-tied) winner AND the human's real
answer resolves to exactly one candidate is `MATCH`/`MISMATCH`-evaluable.

A SAME-TIER TIE PREDICTS NOTHING, HONESTLY. `source_authority.resolve_conflict()` itself already says
"the order cannot break a tie inside one level" for `UNDECIDABLE_SAME_AUTHORITY`; the persisted
question record's own `tier` figure inside each option's label is the coarse `AuthoritySource.rank`
only (never the finer `REGISTER_FILE_SUBORDER` DUT-vs-Global subrank, which the persisted label text
does not carry), so two candidates sharing one rank -- whether a genuine cross-tier tie or a real
tier-4 DUT-vs-Global subordering this module cannot recover from the persisted record -- are reported
as `TIE_NO_AUTHORITY_PREDICTION`, never a fabricated prediction either candidate could satisfy for
free.

WHAT THIS MODULE DOES NOT DO. It never modifies `AUTHORITY_ORDER`, never files or answers a question,
never picks a winner for an open (unanswered) escalation, and never arbitrates a genuine disagreement
between the fixed order and human practice -- a real divergence is reported, per-level and per-pair,
for a human to review; changing `AUTHORITY_ORDER` itself in response is explicitly out of this item's
own scope and would have to go through the same real, human-approved production-behavior-change path
every other weight/threshold proposal in this project already does. There is deliberately no stage
gate and no `dv-harness` CLI verb (`cli.py`/`gates.py` untouched, matching this project's own house
convention for a standalone module built while those two large files are under concurrent edit
pressure) -- the front door is this module's own Python API plus
`python -m dv_harness.source_authority_order_validation`.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import source_authority as _sa
from .models import Status

# ---------------------------------------------------------------------------
# Shape recognition: identify an escalate_conflict()-filed option, from its
# own real text, against the real AUTHORITY_ORDER -- never a domain/key guess.
# ---------------------------------------------------------------------------

#: Matches the "(tier N): <claim>" tail every `SourceClaim.label` carries
#: (`f"Trust the {doc_phrase}{qual} (tier {rank}): {claim}"`). Searched for
#: the literal "(tier " marker rather than a generic paren match, because a
#: real `doc_phrase` can itself contain parentheses (e.g. "register file (DUT
#: then Global)") that must not be mistaken for this one.
_TIER_MARK_RE = re.compile(r"\(tier\s+(\d+)\)\s*:\s*(.*)$", re.DOTALL)

#: Matches the "evidence: <path>" rationale `_option_for()` always writes.
_EVIDENCE_RATIONALE_RE = re.compile(r"^\s*evidence:\s*(.*)$", re.IGNORECASE | re.DOTALL)

CANDIDATE_RESOLUTION_STATUSES = ("RESOLVED", "AMBIGUOUS", "NOT_FOUND")
HUMAN_PICK_STATUSES = (
    "PICKED_BY_EVIDENCE_PATH_CITATION",
    "PICKED_BY_DOC_PHRASE_OR_ALIAS_MENTION",
    "AMBIGUOUS",
    "UNRESOLVED_NO_MATCH",
)
AUTHORITY_PREDICTION_STATUSES = ("PREDICTED", "TIE")
CASE_OUTCOMES = (
    "MATCH",
    "MISMATCH",
    "TIE_NO_AUTHORITY_PREDICTION",
    "HUMAN_PICK_AMBIGUOUS",
    "HUMAN_PICK_UNRESOLVED",
    "PENDING_UNANSWERED",
)
REPORT_STATUSES = ("ORDER_MATCHES_PRACTICE", "ORDER_DIVERGES_FROM_PRACTICE", "NO_EVALUABLE_CASES")


class SourceAuthorityOrderValidationError(Exception):
    """Raised only for a genuinely malformed caller input (e.g. a `root_or_store` this module cannot
    read questions from at all) -- never for an honestly absent/ambiguous/tied case, which is always
    a reported status, per the Evidence Truth Rule."""


def assert_no_verification_verdict_vocabulary() -> None:
    """This module's own vocabulary must share no token with `dv_harness.models.Status` -- the same
    guard several sibling domain-vocabulary modules in this project already apply to themselves. A
    "does the order match practice" report is not a stage verdict, and a future edit that
    accidentally reused e.g. `"PASS"` here would let this module's report be misread as one."""
    verdicts = {s.value for s in Status}
    collision = (
        verdicts & set(CANDIDATE_RESOLUTION_STATUSES)
        | verdicts & set(HUMAN_PICK_STATUSES)
        | verdicts & set(AUTHORITY_PREDICTION_STATUSES)
        | verdicts & set(CASE_OUTCOMES)
        | verdicts & set(REPORT_STATUSES)
    )
    if collision:
        raise SourceAuthorityOrderValidationError(
            f"this module's own vocabulary collides with dv_harness.models.Status: {sorted(collision)!r}"
        )


assert_no_verification_verdict_vocabulary()


def _find_authority_source_for_label(label: str):
    """Identify which real `source_authority.AUTHORITY_ORDER` entry one option `label` names, from
    the label's own literal text -- never guessed. A real `escalate_conflict()`-filed label always has
    the exact form `"Trust the {doc_phrase}{qualifier} (tier {rank}): {claim}"`
    (`SourceClaim.label`), so a label containing BOTH one entry's own `doc_phrase` text AND that SAME
    entry's own `"(tier {rank}):"` marker identifies that entry unambiguously, regardless of a
    tier-4 register-file qualifier appended in between. Returns `(source_or_None, status)`, status one
    of `CANDIDATE_RESOLUTION_STATUSES`."""
    if not isinstance(label, str) or not label.strip().startswith("Trust the "):
        return None, "NOT_FOUND"
    matches = [s for s in _sa.AUTHORITY_ORDER
               if s.doc_phrase in label and f"(tier {s.rank}):" in label]
    if len(matches) == 1:
        return matches[0], "RESOLVED"
    if len(matches) > 1:
        return None, "AMBIGUOUS"
    return None, "NOT_FOUND"


@dataclass
class ConflictCandidate:
    """One real side of a conflict, resolved to a real `AUTHORITY_ORDER` entry from its own persisted
    option text -- never a candidate this module invented."""
    label: str
    rationale: str
    source_id: str
    doc_phrase: str
    rank: int
    evidence_path: str
    claim_text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_conflict_candidates(record: Dict[str, Any]) -> Optional[List[ConflictCandidate]]:
    """Parse `record["options"]` (a real persisted `question_queue` record) into a list of
    `ConflictCandidate`s ONLY when every option is genuinely `escalate_conflict()`-shaped: a real 2-3
    element `options` list, each carrying a `"Trust the ... (tier N): ..."` label that resolves to
    exactly one real `AUTHORITY_ORDER` entry AND an `"evidence: <path>"` rationale with a real,
    non-empty path. Returns `None` -- never a partial/guessed list -- for anything that does not fully
    match this shape, which is the structural test this module uses to recognise a real source-
    authority conflict escalation among a project's questions.json, independent of `domain` (a
    caller-chosen free-text field with no fixed value across this project's real detectors)."""
    options = record.get("options")
    if not isinstance(options, list) or not (2 <= len(options) <= 3):
        return None
    candidates: List[ConflictCandidate] = []
    for opt in options:
        if not isinstance(opt, dict):
            return None
        label = opt.get("label") or ""
        rationale = opt.get("rationale") or ""
        m_ev = _EVIDENCE_RATIONALE_RE.match(rationale)
        if not m_ev:
            return None
        evidence_path = m_ev.group(1).strip()
        if not evidence_path:
            return None
        src, status = _find_authority_source_for_label(label)
        if status != "RESOLVED":
            return None
        m_tier = _TIER_MARK_RE.search(label)
        claim_text = m_tier.group(2).strip() if m_tier else ""
        candidates.append(ConflictCandidate(
            label=label, rationale=rationale, source_id=src.id, doc_phrase=src.doc_phrase,
            rank=src.rank, evidence_path=evidence_path, claim_text=claim_text,
        ))
    return candidates


def is_conflict_escalation_record(record: Dict[str, Any]) -> bool:
    """True iff `record` is a real, recognisable `escalate_conflict()`-filed question -- Tier-3 AND
    option-shaped, per `parse_conflict_candidates()`. Both checks matter: `tier` alone would also
    match a non-conflict Tier-3 escalation (e.g. `build_multiple_choice_question()`'s own N-way
    shape), and option-shape alone (without confirming `tier == TIER3_CANNOT_ASSUME`) would accept a
    record whose options merely happen to look similar."""
    return record.get("tier") == 3 and parse_conflict_candidates(record) is not None


# ---------------------------------------------------------------------------
# Which side did the human actually pick -- from real, literal text only.
# ---------------------------------------------------------------------------

def _candidate_name_tokens(candidate: ConflictCandidate) -> List[str]:
    """The real, already-registered name tokens for `candidate`'s source: its canonical id, its
    `doc_phrase`, and every alias `source_authority.AUTHORITY_ORDER` itself already declares for it --
    the SAME alias table `source_authority.normalize_source()` uses, never a second one built here."""
    src = _sa.authority_source(candidate.source_id)
    return [src.id, src.doc_phrase, *src.aliases]


def _word_boundary_search(token: str, text: str) -> bool:
    if not token:
        return False
    pattern = r"(?<![\w])" + re.escape(token) + r"(?![\w])"
    return re.search(pattern, text, re.IGNORECASE) is not None


@dataclass
class HumanPickResult:
    """The honest result of trying to identify which candidate a human's real free-text answer/basis
    actually names. `status` is one of `HUMAN_PICK_STATUSES`; `picked_source_id` is set ONLY for the
    one resolved status, never for AMBIGUOUS/UNRESOLVED_NO_MATCH."""
    status: str
    picked_source_id: Optional[str]
    matched_evidence: List[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def determine_human_pick(record: Dict[str, Any], candidates: Sequence[ConflictCandidate]) -> HumanPickResult:
    """Identify which of `candidates` the human's real `record["answer"]`/`record["basis"]` text
    actually names -- see this module's own docstring for the fixed, disclosed two-tier matching
    order (a literal `evidence_path` citation first, then a whole-word name/doc_phrase/alias mention).
    Never guesses: two or more candidates matching at either tier is `AMBIGUOUS`; none matching is
    `UNRESOLVED_NO_MATCH`."""
    text = "\n".join(str(p) for p in (record.get("answer"), record.get("basis")) if p)
    if not text.strip():
        return HumanPickResult(
            status="UNRESOLVED_NO_MATCH", picked_source_id=None, matched_evidence=[],
            reason="the answered record carries no real answer/basis text to match against",
        )

    ev_matches = [c for c in candidates if c.evidence_path and c.evidence_path in text]
    if len(ev_matches) == 1:
        c = ev_matches[0]
        return HumanPickResult(
            status="PICKED_BY_EVIDENCE_PATH_CITATION", picked_source_id=c.source_id,
            matched_evidence=[c.evidence_path],
            reason=f"the human's answer/basis text literally cites {c.source_id}'s own evidence "
                   f"path {c.evidence_path!r}, and no other candidate's",
        )
    if len(ev_matches) > 1:
        return HumanPickResult(
            status="AMBIGUOUS", picked_source_id=None,
            matched_evidence=[c.evidence_path for c in ev_matches],
            reason="the answer/basis text cites more than one candidate's evidence path -- refusing "
                   "to guess which side was actually picked",
        )

    phrase_matches: Dict[str, List[str]] = {}
    for c in candidates:
        hits = [t for t in _candidate_name_tokens(c) if _word_boundary_search(t, text)]
        if hits:
            phrase_matches[c.source_id] = hits
    if len(phrase_matches) == 1:
        source_id, hits = next(iter(phrase_matches.items()))
        return HumanPickResult(
            status="PICKED_BY_DOC_PHRASE_OR_ALIAS_MENTION", picked_source_id=source_id,
            matched_evidence=hits,
            reason=f"the answer/basis text mentions {source_id}'s own name/alias {hits!r} and no "
                   f"other candidate's",
        )
    if len(phrase_matches) > 1:
        return HumanPickResult(
            status="AMBIGUOUS", picked_source_id=None,
            matched_evidence=sorted({t for hits in phrase_matches.values() for t in hits}),
            reason=f"the answer/basis text mentions more than one candidate's name/alias: "
                   f"{phrase_matches!r} -- refusing to guess which side was actually picked",
        )

    return HumanPickResult(
        status="UNRESOLVED_NO_MATCH", picked_source_id=None, matched_evidence=[],
        reason="the answer/basis text names neither an evidence path nor a recognizable source "
               "name/alias for any offered candidate",
    )


@dataclass
class AuthorityPrediction:
    """What the real, fixed `AUTHORITY_ORDER` predicts for this conflict: the strictly-highest-
    authority (lowest-rank) candidate, or an honest `TIE` when two or more candidates share the
    lowest rank present -- `source_authority.resolve_conflict()`'s own rule that "the order cannot
    break a tie inside one level", restated here as a refusal to fabricate a prediction."""
    status: str
    predicted_source_id: Optional[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def determine_authority_prediction(candidates: Sequence[ConflictCandidate]) -> AuthorityPrediction:
    min_rank = min(c.rank for c in candidates)
    winners = [c for c in candidates if c.rank == min_rank]
    if len(winners) == 1:
        w = winners[0]
        others = sorted(c.source_id for c in candidates if c is not w)
        return AuthorityPrediction(
            status="PREDICTED", predicted_source_id=w.source_id,
            reason=f"{w.source_id} (tier {w.rank}) strictly outranks {others!r} per AUTHORITY_ORDER",
        )
    tied = sorted(c.source_id for c in winners)
    return AuthorityPrediction(
        status="TIE", predicted_source_id=None,
        reason=f"{tied!r} share the same authority tier ({min_rank}); AUTHORITY_ORDER makes no "
               f"prediction among a same-tier tie",
    )


# ---------------------------------------------------------------------------
# One case per real conflict-escalation question record.
# ---------------------------------------------------------------------------

@dataclass
class ConflictCase:
    question_id: str
    question_key: str
    context_path: str
    question_status: str
    candidates: List[ConflictCandidate]
    authority_prediction: AuthorityPrediction
    human_pick: Optional[HumanPickResult]
    outcome: str
    decided_by: Optional[str]
    decided_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question_key": self.question_key,
            "context_path": self.context_path,
            "question_status": self.question_status,
            "candidates": [c.to_dict() for c in self.candidates],
            "authority_prediction": self.authority_prediction.to_dict(),
            "human_pick": self.human_pick.to_dict() if self.human_pick else None,
            "outcome": self.outcome,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
        }


def build_conflict_case(record: Dict[str, Any]) -> Optional[ConflictCase]:
    """Build one `ConflictCase` from a real persisted question record, or `None` when `record` is not
    a real, recognisable conflict escalation at all (see `is_conflict_escalation_record()`)."""
    candidates = parse_conflict_candidates(record)
    if candidates is None or record.get("tier") != 3:
        return None

    prediction = determine_authority_prediction(candidates)
    status = record.get("status")

    if status != "ANSWERED":
        # A real, still-open (or otherwise self-resolved) escalation -- honestly not yet part of
        # "practice": no human has picked a side yet, so there is nothing here to compare the fixed
        # order's prediction against.
        return ConflictCase(
            question_id=record.get("id"), question_key=record.get("question_key"),
            context_path=record.get("context_path"), question_status=status,
            candidates=candidates, authority_prediction=prediction, human_pick=None,
            outcome="PENDING_UNANSWERED", decided_by=None, decided_at=None,
        )

    human_pick = determine_human_pick(record, candidates)
    if prediction.status == "TIE":
        outcome = "TIE_NO_AUTHORITY_PREDICTION"
    elif human_pick.status == "AMBIGUOUS":
        outcome = "HUMAN_PICK_AMBIGUOUS"
    elif human_pick.status == "UNRESOLVED_NO_MATCH":
        outcome = "HUMAN_PICK_UNRESOLVED"
    else:
        outcome = "MATCH" if human_pick.picked_source_id == prediction.predicted_source_id else "MISMATCH"

    return ConflictCase(
        question_id=record.get("id"), question_key=record.get("question_key"),
        context_path=record.get("context_path"), question_status=status,
        candidates=candidates, authority_prediction=prediction, human_pick=human_pick,
        outcome=outcome, decided_by=record.get("decided_by"), decided_at=record.get("answered_at"),
    )


# ---------------------------------------------------------------------------
# Per-level rollup + the full report.
# ---------------------------------------------------------------------------

@dataclass
class LevelStats:
    """One `AUTHORITY_ORDER` level's real track record across every evaluated (answered, non-tied,
    non-ambiguous) case -- computed, never hand-maintained."""
    rank: int
    id: str
    doc_phrase: str
    times_appeared_as_candidate: int = 0
    times_predicted_winner: int = 0
    times_predicted_winner_confirmed: int = 0
    times_predicted_winner_overridden: int = 0
    times_chosen_by_human_over_higher_authority: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _level_stats(cases: Sequence[ConflictCase]) -> List[LevelStats]:
    stats = {s.id: LevelStats(rank=s.rank, id=s.id, doc_phrase=s.doc_phrase) for s in _sa.AUTHORITY_ORDER}
    for case in cases:
        if case.outcome == "PENDING_UNANSWERED":
            continue
        for c in case.candidates:
            stats[c.source_id].times_appeared_as_candidate += 1
        if case.authority_prediction.status == "PREDICTED":
            pid = case.authority_prediction.predicted_source_id
            stats[pid].times_predicted_winner += 1
            if case.outcome == "MATCH":
                stats[pid].times_predicted_winner_confirmed += 1
            elif case.outcome == "MISMATCH":
                stats[pid].times_predicted_winner_overridden += 1
        if case.outcome == "MISMATCH" and case.human_pick and case.human_pick.picked_source_id:
            stats[case.human_pick.picked_source_id].times_chosen_by_human_over_higher_authority += 1
    return sorted(stats.values(), key=lambda s: s.rank)


def _override_pairs(cases: Sequence[ConflictCase]) -> List[Dict[str, Any]]:
    """Every real `(authority_predicted, human_picked)` reversal, with its real occurrence count --
    the most directly actionable evidence in this report: exactly which lower-authority source keeps
    winning over exactly which higher-authority one, and how often."""
    pairs: Dict[tuple, int] = {}
    for case in cases:
        if case.outcome != "MISMATCH" or not case.human_pick:
            continue
        key = (case.authority_prediction.predicted_source_id, case.human_pick.picked_source_id)
        pairs[key] = pairs.get(key, 0) + 1
    return [
        {"authority_predicted": k[0], "human_picked": k[1], "count": v}
        for k, v in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


@dataclass
class SourceAuthorityOrderValidationReport:
    status: str
    authority_order: List[Dict[str, Any]]
    total_conflict_escalations_found: int
    answered_conflict_escalations: int
    open_pending_conflict_escalations: int
    evaluable_cases: int
    matches: int
    mismatches: int
    match_rate_percent: Optional[float]
    ties_no_authority_prediction: int
    human_pick_ambiguous: int
    human_pick_unresolved: int
    per_level_stats: List[LevelStats]
    override_pairs: List[Dict[str, Any]]
    cases: List[ConflictCase]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "authority_order": self.authority_order,
            "total_conflict_escalations_found": self.total_conflict_escalations_found,
            "answered_conflict_escalations": self.answered_conflict_escalations,
            "open_pending_conflict_escalations": self.open_pending_conflict_escalations,
            "evaluable_cases": self.evaluable_cases,
            "matches": self.matches,
            "mismatches": self.mismatches,
            "match_rate_percent": self.match_rate_percent,
            "ties_no_authority_prediction": self.ties_no_authority_prediction,
            "human_pick_ambiguous": self.human_pick_ambiguous,
            "human_pick_unresolved": self.human_pick_unresolved,
            "per_level_stats": [s.to_dict() for s in self.per_level_stats],
            "override_pairs": self.override_pairs,
            "cases": [c.to_dict() for c in self.cases],
        }


def _resolve_store(root_or_store: Any):
    """Accept either an already-constructed store-like object (anything exposing `list_questions()`
    -- e.g. a real `question_queue.QuestionQueueStore`, or a test double) or a project root path,
    which is turned into a real `QuestionQueueStore` rooted there. Never constructs anything else and
    never writes -- this module only ever calls `list_questions()` on the result."""
    if hasattr(root_or_store, "list_questions"):
        return root_or_store
    try:
        from . import question_queue as _qq
    except ImportError as exc:  # pragma: no cover - question_queue is a real in-package dependency
        raise SourceAuthorityOrderValidationError(
            "dv_harness.question_queue could not be imported"
        ) from exc
    return _qq.QuestionQueueStore(Path(root_or_store))


def build_report(root_or_store: Any) -> SourceAuthorityOrderValidationReport:
    """Build the full report: read every real Tier-3 conflict-escalation question this project's
    question queue holds (answered or still open), build one `ConflictCase` per real one, and roll
    the answered cases up into per-level stats and override pairs. Read-only end to end -- it only
    ever calls `list_questions()` on the resolved store."""
    store = _resolve_store(root_or_store)
    try:
        records = store.list_questions(tier=3)
    except TypeError:
        # A minimal test double may only implement list_questions() with no filter kwargs -- fall
        # back to filtering here rather than requiring every caller to replicate the real store's
        # full keyword-argument surface.
        records = [q for q in store.list_questions() if q.get("tier") == 3]

    cases: List[ConflictCase] = []
    for record in records:
        case = build_conflict_case(record)
        if case is not None:
            cases.append(case)

    answered = [c for c in cases if c.outcome != "PENDING_UNANSWERED"]
    pending = [c for c in cases if c.outcome == "PENDING_UNANSWERED"]
    matches = sum(1 for c in answered if c.outcome == "MATCH")
    mismatches = sum(1 for c in answered if c.outcome == "MISMATCH")
    ties = sum(1 for c in answered if c.outcome == "TIE_NO_AUTHORITY_PREDICTION")
    ambiguous = sum(1 for c in answered if c.outcome == "HUMAN_PICK_AMBIGUOUS")
    unresolved = sum(1 for c in answered if c.outcome == "HUMAN_PICK_UNRESOLVED")
    evaluable = matches + mismatches
    match_rate = round(matches / evaluable * 100.0, 2) if evaluable else None

    if evaluable == 0:
        overall_status = "NO_EVALUABLE_CASES"
    elif mismatches == 0:
        overall_status = "ORDER_MATCHES_PRACTICE"
    else:
        overall_status = "ORDER_DIVERGES_FROM_PRACTICE"

    return SourceAuthorityOrderValidationReport(
        status=overall_status,
        authority_order=_sa.describe_order(),
        total_conflict_escalations_found=len(cases),
        answered_conflict_escalations=len(answered),
        open_pending_conflict_escalations=len(pending),
        evaluable_cases=evaluable,
        matches=matches,
        mismatches=mismatches,
        match_rate_percent=match_rate,
        ties_no_authority_prediction=ties,
        human_pick_ambiguous=ambiguous,
        human_pick_unresolved=unresolved,
        per_level_stats=_level_stats(cases),
        override_pairs=_override_pairs(cases),
        cases=cases,
    )


def format_report(report: SourceAuthorityOrderValidationReport) -> str:
    """Human-readable rendering, reusing `connectivity.render_markdown_table()` -- this repo's one
    parameterized table renderer -- rather than a second hand-rolled table loop."""
    from .connectivity import render_markdown_table

    lines = [
        "Source Authority Order Validation",
        f"  status: {report.status}",
        f"  conflict escalations found: {report.total_conflict_escalations_found} "
        f"(answered: {report.answered_conflict_escalations}, "
        f"still open: {report.open_pending_conflict_escalations})",
        f"  evaluable cases: {report.evaluable_cases}  "
        f"(matches: {report.matches}, mismatches: {report.mismatches}, "
        f"match rate: {report.match_rate_percent if report.match_rate_percent is not None else 'N/A'}%)",
        f"  ties (no authority prediction): {report.ties_no_authority_prediction}  "
        f"human-pick ambiguous: {report.human_pick_ambiguous}  "
        f"human-pick unresolved: {report.human_pick_unresolved}",
        "",
    ]

    lines.append("Per-level track record:")
    lines.append(render_markdown_table(
        [("rank", "Rank"), ("doc_phrase", "Source"), ("times_appeared_as_candidate", "Appeared"),
         ("times_predicted_winner", "Predicted Winner"),
         ("times_predicted_winner_confirmed", "Confirmed"),
         ("times_predicted_winner_overridden", "Overridden"),
         ("times_chosen_by_human_over_higher_authority", "Chosen Over Higher Authority")],
        [s.to_dict() for s in report.per_level_stats],
        empty_note="(no authority levels)",
    ))
    lines.append("")

    lines.append("Real overrides (authority predicted -> human actually picked):")
    lines.append(render_markdown_table(
        [("authority_predicted", "Authority Predicted"), ("human_picked", "Human Picked"),
         ("count", "Count")],
        report.override_pairs,
        empty_note="(no real overrides found -- the order matches practice on every evaluable case)",
    ))
    return "\n".join(lines)


def execute_verb(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.source_authority_order_validation",
        description="Report whether source_authority.py's fixed 9-level AUTHORITY_ORDER actually "
                    "matches which side a human has picked in practice, over this project's real, "
                    "answered Tier-3 conflict escalations. Read-only -- never edits AUTHORITY_ORDER.",
    )
    ap.add_argument("--root", default=".", help="Project root containing .dv-harness/question_queue/.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)

    report = build_report(Path(a.root))
    if a.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))

    if report.status == "ORDER_DIVERGES_FROM_PRACTICE":
        return 1
    if report.status == "NO_EVALUABLE_CASES":
        return 2
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return execute_verb(argv)


if __name__ == "__main__":
    raise SystemExit(main())
