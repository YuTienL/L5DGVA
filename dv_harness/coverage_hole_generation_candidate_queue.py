"""dv_harness/coverage_hole_generation_candidate_queue.py -- the DETECTION/RANKING-only
half of L5DGVA V9 Section 205 "Autonomous Hole-Driven Test Generation"
(`CoverageHoleAutoTestGeneration_PASS`), quoted verbatim from the primary source (byte-
identical v9-v23; read directly from
`L5DGVA/L5_DGVA_v23_IMPLEMENTATION_STRICT_Autonomous_Remote_Transport_Recovery.md:3222-3229`):

    "## 205. Autonomous Hole-Driven Test Generation

    When a required hole is caused by missing/insufficient scenario and
    internally resolvable, automatically generate/extend minimum targeted
    test using vPlan + DE seeds + VIP knowledge + design/programming
    evidence.

    Required: `CoverageHoleAutoTestGeneration_PASS = true`"

WHY THE GENERATION ACT ITSELF STAYS A GENUINE, UNDISPUTED BOUNDARY. SS205's own required
boolean is the literal generation ACT ("automatically generate/extend ... test"), running
unattended inside SS207's own eight-step loop (REGRESSION -> COVERAGE MERGE -> VPLAN
TRACEABILITY -> HOLE ANALYSIS -> ROOT CAUSE -> NEXT-BEST ACTION -> TARGETED TEST/REPAIR ->
REGRESSION -> RE-EVALUATE), which names no human checkpoint anywhere in the cycle. An
autonomous step that authors new test/stimulus CONTENT with no human review before it feeds
back into REGRESSION is exactly the unreviewed-AI-content-authorship this repo's own
No-Golden-Reference-Content-Mining rule and Agent-Authored Change Accountability policy
(CLAUDE.md) forbid. This module does not attempt it, and re-confirms
(.dv-harness/l5dgva_audit_result_E.md:44) by direct re-read of both files it names:
`tools/verification_flow/coverage_hole_to_test_generation_gate.py` is a 9-line script that
only VERIFIES a caller's `generated_test_ids`/`closure_owner`/`trace_to_vplan` claim -- it
never emits one -- and `coverage_closure_action_utility.py` ranks caller-declared candidate
ACTIONS by utility, never emits test content either. Both findings hold; neither module is
edited here.

WHAT WAS GENUINELY MISSING, AND IS THE NARROW SLICE THIS MODULE ADDS. `coverage_analysis.
classify_coverage_hole()` already computes, per hole, whether it is "caused by missing/
insufficient scenario and internally resolvable" -- exactly
`coverage_analysis.CLASSES_REQUIRING_TEST_REGENERATION` (MISSING_TEST /
INSUFFICIENT_CONSTRAINT), imported here by identity, never re-typed as a new string --  and
`coverage_closure_action_utility.rank_coverage_closure_actions()` already utility-ranks a
caller-declared candidate-action list. A repo-wide grep (see this module's own test file)
confirms ZERO real callers join them: nothing in this codebase, before this module, took a
SET of coverage holes, decided WHICH are SS205-eligible, and ranked that eligible subset by
closure value. That is exactly, and only, what `build_generation_candidate_queue()` below
does: partition a hole set into SS205-eligible vs not (reusing `classify_coverage_hole()`
unmodified), then utility-rank the eligible subset (reusing `rank_coverage_closure_actions()`
unmodified, its own gate-before-cost / DECLARED-never-measured discipline inherited
verbatim). The output is a ranked GENERATION-CANDIDATE QUEUE -- which coverage holes are
legitimate, internally-resolvable candidates for a human (or a future, SEPARATELY-approved
capability) to author a targeted test against, and in what priority order. It never authors,
drafts, mines, or even outlines test CONTENT.

INELIGIBLE HOLES ARE NAMED, NEVER SILENTLY DROPPED. UNREACHABLE_STIMULUS (needs design-owner
confirmation, not a test -- `coverage_analysis.CLASSES_REQUIRING_HUMAN_ESCALATION`) and
INSUFFICIENT_SEED_ATTEMPTS (needs more seeds, not a new test --
`coverage_analysis.CLASSES_REQUIRING_MORE_SEEDS`) are reported in a separate `not_eligible`
list carrying `classify_coverage_hole()`'s own real verdict -- this module never re-derives,
weakens, or second-guesses that verdict, it only reads the `classification` field already
computed.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It does not compute
`expected_coverage_gain`/`requirement_priority`/`risk_coverage`/`cost` itself -- those stay
caller-DECLARED per `coverage_closure_action_utility.py`'s own existing contract (never
self-measured, reported DECLARED/NOT_AVAILABLE, never defaulted); an eligible hole missing
any of the four is reported UNRANKABLE by the ranker, exactly as it already does for any
other candidate. It does not write `generated_test_ids`/`closure_owner`/`trace_to_vplan` --
`coverage_hole_to_test_generation_gate.py`'s own verification job is untouched and
unduplicated. It does not wire into `engine.py`, `cli.py` or `gates.py` (out of this batch's
scope) -- library-level only, the same shape several sibling CAP-repair modules this wave
used (e.g. `verification_capability_model.py`, `vplan_scope_ownership_gate.py`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .coverage_analysis import (
    CLASSES_REQUIRING_HUMAN_ESCALATION,
    CLASSES_REQUIRING_MORE_SEEDS,
    CLASSES_REQUIRING_TEST_REGENERATION,
    classify_coverage_hole,
)
from .coverage_closure_action_utility import (
    CoverageClosureRanking,
    format_ranking_report,
    rank_coverage_closure_actions,
)

SCHEMA_VERSION = "1.0"

#: The four utility factors a caller may declare directly on a hole record so it can be
#: carried through, unchanged, into the ranker's own candidate shape. Never invented or
#: derived here -- exactly `coverage_closure_action_utility.UTILITY_FACTORS` plus the two
#: gate fields that module already defines; held as a local tuple (not imported by identity)
#: only because the two correctness/risk gate field names are not exported as a single
#: constant there -- the four utility factor NAMES themselves are the same literal strings,
#: cross-checked at import time below so this module cannot silently drift from them.
_CARRIED_HOLE_FIELDS = (
    "expected_coverage_gain", "requirement_priority", "risk_coverage", "cost",
    "expected_coverage_gain_rationale", "requirement_priority_rationale",
    "risk_coverage_rationale", "cost_rationale",
    "correctness_status", "risk_status",
)


class GenerationCandidateQueueError(ValueError):
    """Raised for a genuinely empty/malformed input this module refuses to guess about --
    never for an ordinary "nothing eligible" outcome, which is reported via `not_eligible`."""


@dataclass(frozen=True)
class IneligibleHole:
    """One coverage hole that is NOT an SS205 generation candidate, with the real
    `classify_coverage_hole()` verdict that decided so -- never silently dropped."""
    coverage_id: str
    classification: Optional[str]
    reason: str
    verdict: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coverage_id": self.coverage_id,
            "classification": self.classification,
            "reason": self.reason,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class GenerationCandidateQueue:
    """The full partition + ranking result. `ranking` is a real
    `coverage_closure_action_utility.CoverageClosureRanking` over exactly the SS205-eligible
    subset -- never over ineligible holes, which never reach the ranker at all."""
    ranking: CoverageClosureRanking
    not_eligible: List[IneligibleHole]
    eligible_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "ranking": self.ranking.to_dict(),
            "not_eligible": [h.to_dict() for h in self.not_eligible],
            "eligible_count": self.eligible_count,
        }


def _ineligibility_reason(classification: Optional[str]) -> str:
    if classification in CLASSES_REQUIRING_HUMAN_ESCALATION:
        return ("UNREACHABLE_STIMULUS -- requires design-owner confirmation before any test "
                "can legitimately be authored against it; not a generation candidate")
    if classification in CLASSES_REQUIRING_MORE_SEEDS:
        return ("INSUFFICIENT_SEED_ATTEMPTS -- randomization has not had a fair attempt yet; "
                "the correct next action is more seeds, not a new targeted test")
    if classification is None:
        return "NO_RECOGNISED_ROOT_CAUSE_CLASSIFICATION -- cannot judge SS205 eligibility"
    return f"root cause {classification!r} is not one of CLASSES_REQUIRING_TEST_REGENERATION"


def build_generation_candidate_queue(
    root,
    holes: Sequence[Dict[str, Any]],
    *,
    cfg=None,
    registry=None,
    seed_counts=None,
    db_path=None,
    history_available=None,
) -> GenerationCandidateQueue:
    """Partition `holes` (the same `coverage_hole_regeneration_gate` evidence-block shape
    `coverage_analysis.classify_coverage_hole()` already accepts -- each a dict with at least
    `coverage_id`) into SS205-eligible (MISSING_TEST / INSUFFICIENT_CONSTRAINT, i.e. exactly
    `CLASSES_REQUIRING_TEST_REGENERATION`) and everything else, then utility-rank the eligible
    subset via `rank_coverage_closure_actions()` unmodified. Never generates a test; only
    classifies and orders.

    Each eligible hole becomes ONE candidate-action record for the ranker: `action_id` is its
    `coverage_id`, and any of `_CARRIED_HOLE_FIELDS` the hole record itself declares (still
    caller-DECLARED, never self-measured) are carried through unchanged -- an eligible hole
    missing a utility factor is reported UNRANKABLE by the ranker, exactly as it already does
    for any other candidate.

    Raises `GenerationCandidateQueueError` when `holes` is empty/None, or when NONE of them
    are SS205-eligible -- a caller must be told plainly there was nothing to queue, not shown
    an empty-but-successful ranking that would look identical to "every eligible hole was
    excluded"."""
    if not holes:
        raise GenerationCandidateQueueError(
            "build_generation_candidate_queue: no coverage holes were supplied")

    eligible_candidates: List[Dict[str, Any]] = []
    not_eligible: List[IneligibleHole] = []

    for hole in holes:
        if not isinstance(hole, dict):
            continue
        verdict = classify_coverage_hole(
            root, hole, cfg=cfg, registry=registry, seed_counts=seed_counts,
            db_path=db_path, history_available=history_available)
        classification = verdict.get("classification")
        coverage_id = verdict.get("coverage_id") or "UNKNOWN_COVERAGE_ID"

        if classification in CLASSES_REQUIRING_TEST_REGENERATION:
            candidate: Dict[str, Any] = {
                "action_id": coverage_id,
                "description": (f"Author a targeted test/scenario extension for coverage "
                                 f"hole {coverage_id!r} (root cause {classification})"),
            }
            for name in _CARRIED_HOLE_FIELDS:
                if name in hole:
                    candidate[name] = hole[name]
            eligible_candidates.append(candidate)
        else:
            not_eligible.append(IneligibleHole(
                coverage_id=coverage_id, classification=classification,
                reason=_ineligibility_reason(classification), verdict=verdict))

    if not eligible_candidates:
        raise GenerationCandidateQueueError(
            "build_generation_candidate_queue: no supplied hole is SS205-eligible "
            "(MISSING_TEST/INSUFFICIENT_CONSTRAINT) -- nothing to queue for autonomous-"
            "hole-driven test generation candidacy")

    ranking = rank_coverage_closure_actions(eligible_candidates)
    return GenerationCandidateQueue(
        ranking=ranking, not_eligible=not_eligible, eligible_count=len(eligible_candidates))


def format_candidate_queue_report(queue: GenerationCandidateQueue) -> str:
    """Human-readable rendering: the ranker's own report over the eligible subset, plus the
    named-and-cited ineligible list. Presentation-only -- no new logic beyond formatting."""
    lines = [format_ranking_report(queue.ranking), ""]
    lines.append(f"NOT SS205-ELIGIBLE ({len(queue.not_eligible)}):")
    if not queue.not_eligible:
        lines.append("  (none)")
    for h in queue.not_eligible:
        lines.append(f"  {h.coverage_id:<24s} {h.reason}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.coverage_hole_generation_candidate_queue",
        description="SS205 detection/ranking-only slice: classify which coverage holes are "
                    "internally-resolvable test-generation candidates (coverage_analysis.py, "
                    "unmodified) and utility-rank that eligible subset "
                    "(coverage_closure_action_utility.py, unmodified). Never generates test "
                    "content -- see module docstring for the No-Golden-Reference-Content-"
                    "Mining boundary this stops at.")
    ap.add_argument("--holes-file", required=True,
                     help="JSON file: {\"coverage_holes\": [...]} or a bare JSON list -- the "
                          "same shape as the coverage_hole_regeneration_gate evidence block.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    raw = json.loads(Path(a.holes_file).read_text(encoding="utf-8"))
    holes = raw.get("coverage_holes") if isinstance(raw, dict) else raw
    if not isinstance(holes, list):
        raise GenerationCandidateQueueError(
            "--holes-file must contain a JSON list, or a dict with a 'coverage_holes' list")

    queue = build_generation_candidate_queue(a.root, holes)
    if a.json:
        print(json.dumps(queue.to_dict(), indent=2))
    else:
        print(format_candidate_queue_report(queue))
    return 0 if not queue.ranking.unrankable else 1


if __name__ == "__main__":
    raise SystemExit(main())
