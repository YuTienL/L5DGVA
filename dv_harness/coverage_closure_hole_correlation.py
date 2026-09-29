"""dv_harness/coverage_closure_hole_correlation.py -- cross-hole correlation and multi-hole
action identification for coverage closure, built strictly ON TOP of two existing, unmodified
modules under this project's REUSE-OVER-REINVENT rule:

  * `coverage_analysis.classify_coverage_hole_taxonomy()` -- the real per-hole 12-category
    taxonomy (a hole's own declared register/cross-axes/timing/config/golden-scenario evidence).
  * `coverage_closure_action_utility.rank_coverage_closure_actions()` -- the real
    correctness/risk-gated, four-factor utility ranking over a set of candidate closure actions.

THE GAP THIS CLOSES. Both modules above already answer their own question well: "what STRUCTURAL
category does this ONE hole fall into" and "which candidate ACTION has the highest expected value,
after excluding anything flagged wrong or dangerous". Neither ever compares two holes to each
other, and neither ever asks whether a single proposed action would close more than one of them.
A coverage-closure effort with, say, 40 open holes and 8 candidate actions routinely has several
holes that share a REAL, already-declared root cause -- the same register, the same cross-coverage
axis, the same directed-test pattern, the same missing configuration variant -- and a single
directed test or constraint relaxation addressing that shared cause can close every one of them at
once. A repo-wide grep for `cross_hole`/`hole_correlation`/`multi_hole`/`closes_holes` before this
module was written matched nothing executable anywhere in this repo.

WHAT "CORRELATED" MEANS HERE, AND WHY IT IS NEVER GUESSED. This module never infers a relationship
between two holes from their coverage_id strings, their names, or any other heuristic. Two holes
are correlated ONLY when they share one of four REAL, ALREADY-DECLARED evidence facts -- the exact
same facts `coverage_analysis.py`'s own taxonomy rules already read, reused rather than re-derived:

  * SHARED_REGISTER -- both holes declare the identical `register_name`.
  * SHARED_CROSS_AXIS -- both holes' declared `cross_axes` lists share a member.
  * SHARED_LINKED_PATTERN -- both holes trace, via the project's own real requirements-registry
    linkage (`classify_coverage_hole_taxonomy()`'s own `linked_patterns`, reused verbatim, never
    re-queried), to the identical PATTERN_ID.
  * SHARED_MISSING_CONFIG -- both holes declare `hit_in_configs`/`legal_configs` and are both
    missing coverage in the identical configuration name.

Two holes sharing none of the four are reported as having no correlation -- never assumed related
merely because they were classified into the same 12-category taxonomy value, since two holes can
both be, say, INSUFFICIENT_CONSTRAINT for entirely unrelated reasons.

WHICH ACTION CLOSES WHICH HOLE IS ALWAYS A CALLER DECLARATION, NEVER INFERRED. This module has no
way to know, from a candidate action's free-text `description`, which coverage bins it would
actually close -- inventing that link would be exactly the fabrication the Evidence Truth Rule
forbids. A candidate action may declare a `closes_holes` list of coverage_id strings (the field
name is itself overridable via `closes_holes_field`, for a caller whose own schema spells it
differently); an action declaring none is honestly reported NOT_DECLARED, never assumed to close
zero holes as if that were a measured fact.

THE INTELLIGENCE LAYER: BUNDLE STATUS. For an action declaring two or more real, known holes, every
pairwise combination among them is checked against the real correlation groups above:
`CORRELATED_MULTI_HOLE` (every pair shares real evidence -- a genuine cluster-closing candidate),
`PARTIALLY_CORRELATED_MULTI_HOLE` (some pairs do, some do not), `UNCORRELATED_MULTI_HOLE_BUNDLE`
(none do -- an action claiming to close several holes with no real shared cause between any of
them, worth a second look before trusting the bundle). A declared coverage_id absent from the
supplied hole set is honestly `unknown_hole_ids`, never silently dropped and never treated as
correlated with anything.

THIS MODULE NEVER REORDERS THE UNDERLYING UTILITY RANKING. `rank_coverage_closure_actions()`'s own
rank/utility_score, and -- critically -- its correctness/risk GATE (an action flagged
FLAGGED_INCORRECT or HIGH_RISK is excluded from ranking entirely, before cost or anything else is
considered) are read here verbatim and never recomputed. `high_value_multi_hole_actions` is an
ADDITIONAL, clearly-labelled advisory lens over already-RANKED (i.e. already gate-cleared) actions
only -- a correlated multi-hole bundle whose action was EXCLUDED for being flagged incorrect or
high-risk is never promoted into that list on the strength of how many holes it claims to close.
That is this module's own instance of the project's worst-wins composite-gate rule: a single
UNMET/BLOCKED condition (here, the utility module's own gate) must make the whole recommendation
fail regardless of how attractive another dimension (hole count) makes it look.

FILE-SAFETY / REUSE NOTE. This module imports `coverage_analysis.classify_coverage_hole_taxonomy()`
and `coverage_closure_action_utility`'s public ranking entry point plus its two small private
duck-typed readers (`_lookup`, `_resolve_action_id`) so that an action_id computed here can never
silently diverge from the action_id `rank_coverage_closure_actions()` itself assigned to the exact
same candidate -- re-implementing that resolution separately would risk exactly that drift. Neither
`coverage_analysis.py` nor `coverage_closure_action_utility.py` is edited by this change.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It does not classify a hole (that stays
`classify_coverage_hole_taxonomy()`'s job, called unchanged), it does not rank an action's utility
or apply the correctness/risk gate (that stays `rank_coverage_closure_actions()`'s job, called
unchanged), and it does not decide which action a project should actually pursue -- it only
surfaces, from real declared evidence, which holes are genuinely related and which already-ranked
actions would close more than one of them at once. It writes nothing, approves nothing, and gates
no stage.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .coverage_analysis import classify_coverage_hole_taxonomy
from .coverage_closure_action_utility import (
    ACTION_STATUSES,
    CandidateActionUtility,
    CoverageClosureRanking,
    CoverageClosureActionUtilityError,
    rank_coverage_closure_actions,
    _lookup,
    _resolve_action_id,
)

#: The exact three statuses `coverage_closure_action_utility.py` assigns a candidate, imported
#: rather than re-typed so this module's own gate-respecting logic can never drift from that
#: module's real vocabulary.
RANKED_STATUS, EXCLUDED_STATUS, UNRANKABLE_STATUS = ACTION_STATUSES

#: The four real, declared-evidence-only correlation kinds this module recognizes. Every one
#: reads a field `coverage_analysis.py`'s own taxonomy rules already read for a single hole;
#: this module only asks whether TWO holes agree on one of them.
CORRELATION_SHARED_REGISTER = "SHARED_REGISTER"
CORRELATION_SHARED_CROSS_AXIS = "SHARED_CROSS_AXIS"
CORRELATION_SHARED_LINKED_PATTERN = "SHARED_LINKED_PATTERN"
CORRELATION_SHARED_MISSING_CONFIG = "SHARED_MISSING_CONFIG"

CORRELATION_KINDS: Sequence[str] = (
    CORRELATION_SHARED_REGISTER,
    CORRELATION_SHARED_CROSS_AXIS,
    CORRELATION_SHARED_LINKED_PATTERN,
    CORRELATION_SHARED_MISSING_CONFIG,
)

#: Per-action bundle-status vocabulary -- one of these is assigned to every candidate action
#: this module examines, never a bare bool, so "we could not tell" (NOT_DECLARED / an unknown
#: hole id) stays visibly distinct from a real correlated/uncorrelated finding.
BUNDLE_NOT_DECLARED = "NOT_DECLARED"
BUNDLE_REFERENCES_ONLY_UNKNOWN_HOLES = "REFERENCES_ONLY_UNKNOWN_HOLES"
BUNDLE_SINGLE_HOLE = "SINGLE_HOLE_ACTION"
BUNDLE_CORRELATED = "CORRELATED_MULTI_HOLE"
BUNDLE_PARTIALLY_CORRELATED = "PARTIALLY_CORRELATED_MULTI_HOLE"
BUNDLE_UNCORRELATED = "UNCORRELATED_MULTI_HOLE_BUNDLE"

BUNDLE_STATUSES: Sequence[str] = (
    BUNDLE_NOT_DECLARED,
    BUNDLE_REFERENCES_ONLY_UNKNOWN_HOLES,
    BUNDLE_SINGLE_HOLE,
    BUNDLE_CORRELATED,
    BUNDLE_PARTIALLY_CORRELATED,
    BUNDLE_UNCORRELATED,
)


class CoverageClosureHoleCorrelationError(ValueError):
    """Raised for a genuinely malformed input this module cannot even attempt to process (a
    duplicate/missing coverage_id, a malformed `closes_holes` declaration, or a candidate/ranking
    pair that were not built from the same call) -- never a fabricated best-effort result."""

    def __init__(self, reason: str, detail: dict):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class HoleCorrelationGroup:
    """One real correlation fact shared by two or more holes -- always >= 2 members; a
    would-be group of size 1 is never constructed, since a hole cannot correlate with itself."""
    kind: str
    key: str
    coverage_ids: List[str]
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HoleCorrelationReport:
    """Every supplied hole's own real taxonomy result, plus every real correlation group found
    among them (size >= 2 only)."""
    taxonomy_by_id: Dict[str, dict]
    groups: List[HoleCorrelationGroup]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taxonomy_by_id": self.taxonomy_by_id,
            "groups": [g.to_dict() for g in self.groups],
        }


@dataclass
class ActionHoleImpact:
    """One candidate action's real ranking record (read verbatim, never recomputed) plus its
    real hole-correlation bundle status."""
    action_id: str
    status: str  # the action's real coverage_closure_action_utility.py status, unchanged
    rank: Optional[int]
    utility_score: Optional[float]
    description: Optional[str]
    declared_closes_holes: List[str]
    known_hole_ids: List[str]
    unknown_hole_ids: List[str]
    bundle_status: str  # one of BUNDLE_STATUSES
    correlated_pairs: int
    total_pairs: int
    correlation_evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CoverageClosureIntelligenceReport:
    """The full result: every real hole-correlation group found, every examined action's
    hole-impact record (in the same order the candidates were supplied), and the subset of
    already-utility-RANKED (i.e. already gate-cleared) actions that would close a genuinely
    correlated multi-hole bundle -- an additional advisory view, never a reordering of the
    underlying ranking."""
    hole_correlation_groups: List[HoleCorrelationGroup]
    action_hole_impacts: List[ActionHoleImpact]
    high_value_multi_hole_actions: List[ActionHoleImpact]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hole_correlation_groups": [g.to_dict() for g in self.hole_correlation_groups],
            "action_hole_impacts": [i.to_dict() for i in self.action_hole_impacts],
            "high_value_multi_hole_actions": [i.to_dict() for i in self.high_value_multi_hole_actions],
        }


def _group_key_candidates(hole: dict, taxonomy_result: dict):
    """Yields (kind, key, evidence) tuples for one hole's own REAL declared fields (plus its
    already-computed real `linked_patterns`) -- never inferred from a name or a coverage_id."""
    reg = hole.get("register_name")
    if isinstance(reg, str) and reg.strip():
        norm = reg.strip().upper()
        yield (CORRELATION_SHARED_REGISTER, norm,
               {"source": "hole_declared_field", "field": "register_name",
                "register_name": reg.strip()})

    axes = hole.get("cross_axes")
    if isinstance(axes, list):
        for axis in axes:
            if isinstance(axis, str) and axis.strip():
                name = axis.strip()
                yield (CORRELATION_SHARED_CROSS_AXIS, name,
                       {"source": "hole_declared_field", "field": "cross_axes",
                        "cross_axis": name})

    for pattern in taxonomy_result.get("linked_patterns") or []:
        if isinstance(pattern, str) and pattern.strip():
            name = pattern.strip()
            yield (CORRELATION_SHARED_LINKED_PATTERN, name,
                   {"source": "requirements_registry", "field": "linked_patterns",
                    "linked_pattern": name})

    hit = hole.get("hit_in_configs")
    legal = hole.get("legal_configs")
    if isinstance(hit, list) and isinstance(legal, list) and legal:
        hit_set = {str(c).strip() for c in hit if str(c).strip()}
        legal_set = {str(c).strip() for c in legal if str(c).strip()}
        for cfg_name in sorted(legal_set - hit_set):
            yield (CORRELATION_SHARED_MISSING_CONFIG, cfg_name,
                   {"source": "hole_declared_field", "field": "hit_in_configs/legal_configs",
                    "missing_config": cfg_name})


def correlate_coverage_holes(holes: Sequence[dict], root, *, cfg=None, registry=None,
                              seed_counts=None, db_path=None, history_available=None,
                              head: str = "HEAD", parsed_summary: dict = None) -> HoleCorrelationReport:
    """Classify every supplied hole via `classify_coverage_hole_taxonomy()` (unchanged, called
    once per hole) and find every REAL correlation group (>= 2 members) among them.

    `holes` may be empty -- an empty hole set correlates to nothing, unambiguously, so this never
    raises on it (unlike `rank_coverage_closure_actions()`'s empty-candidates refusal, which
    exists because an empty *ranking* result would look identical to "everything excluded"; an
    empty *correlation* result has no such ambiguity). Every hole MUST declare a non-empty,
    unique `coverage_id` -- a hole with none, or one repeating an earlier hole's id, is a genuine
    input defect this module refuses to silently paper over."""
    taxonomy_by_id: Dict[str, dict] = {}
    group_members: Dict[Tuple[str, str], List[str]] = {}
    group_evidence: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for index, hole in enumerate(holes or []):
        if not isinstance(hole, dict):
            raise CoverageClosureHoleCorrelationError(
                "MALFORMED_HOLE", {"index": index, "hole": hole})
        coverage_id = str(hole.get("coverage_id") or "").strip()
        if not coverage_id:
            raise CoverageClosureHoleCorrelationError(
                "HOLE_MISSING_COVERAGE_ID", {"index": index})
        if coverage_id in taxonomy_by_id:
            raise CoverageClosureHoleCorrelationError(
                "DUPLICATE_COVERAGE_ID", {"coverage_id": coverage_id})

        taxonomy_result = classify_coverage_hole_taxonomy(
            root, hole, cfg=cfg, registry=registry, seed_counts=seed_counts,
            db_path=db_path, history_available=history_available, head=head,
            parsed_summary=parsed_summary)
        taxonomy_by_id[coverage_id] = taxonomy_result

        for kind, key, evidence in _group_key_candidates(hole, taxonomy_result):
            gkey = (kind, key)
            members = group_members.setdefault(gkey, [])
            if coverage_id not in members:
                members.append(coverage_id)
            group_evidence[gkey] = evidence

    groups = [
        HoleCorrelationGroup(kind=kind, key=key, coverage_ids=sorted(members),
                              evidence=dict(group_evidence[(kind, key)]))
        for (kind, key), members in group_members.items()
        if len(members) >= 2
    ]
    groups.sort(key=lambda g: (g.kind, g.key))

    return HoleCorrelationReport(taxonomy_by_id=taxonomy_by_id, groups=groups)


def _correlated_groups_for_pair(a: str, b: str, groups: Sequence[HoleCorrelationGroup]) -> List[HoleCorrelationGroup]:
    return [g for g in groups if a in g.coverage_ids and b in g.coverage_ids]


def build_multi_hole_action_intelligence(
        candidates: Sequence[Any], ranking: CoverageClosureRanking, holes: Sequence[dict], root,
        *, cfg=None, registry=None, seed_counts=None, db_path=None, history_available=None,
        head: str = "HEAD", parsed_summary: dict = None,
        closes_holes_field: str = "closes_holes") -> CoverageClosureIntelligenceReport:
    """The intelligence layer: correlate `holes` (via `correlate_coverage_holes()`, unchanged
    logic) and cross-reference every one of `candidates`' own declared `closes_holes` list
    against those real correlation groups -- WITHOUT ever recomputing `ranking` (which MUST be
    the real `rank_coverage_closure_actions(candidates)` result for this exact same
    `candidates` sequence; a candidate whose resolved action_id is not found anywhere in
    `ranking` raises rather than guessing a status for it)."""
    correlation = correlate_coverage_holes(
        holes, root, cfg=cfg, registry=registry, seed_counts=seed_counts, db_path=db_path,
        history_available=history_available, head=head, parsed_summary=parsed_summary)

    ranking_by_id: Dict[str, CandidateActionUtility] = {}
    for record in (*ranking.ranked, *ranking.excluded, *ranking.unrankable):
        ranking_by_id[record.action_id] = record

    impacts: List[ActionHoleImpact] = []
    for index, candidate in enumerate(candidates or []):
        action_id = _resolve_action_id(candidate, index)
        ranking_record = ranking_by_id.get(action_id)
        if ranking_record is None:
            raise CoverageClosureHoleCorrelationError(
                "ACTION_NOT_IN_RANKING",
                {"action_id": action_id, "index": index,
                 "detail": "`candidates` must be the exact same sequence "
                           "`rank_coverage_closure_actions()` produced `ranking` from"})

        raw_closes = _lookup(candidate, closes_holes_field)
        if raw_closes is None:
            impacts.append(ActionHoleImpact(
                action_id=action_id, status=ranking_record.status, rank=ranking_record.rank,
                utility_score=ranking_record.utility_score, description=ranking_record.description,
                declared_closes_holes=[], known_hole_ids=[], unknown_hole_ids=[],
                bundle_status=BUNDLE_NOT_DECLARED, correlated_pairs=0, total_pairs=0,
                correlation_evidence=[]))
            continue

        if not isinstance(raw_closes, list) or not all(
                isinstance(c, str) and c.strip() for c in raw_closes):
            raise CoverageClosureHoleCorrelationError(
                "INVALID_CLOSES_HOLES_DECLARATION",
                {"action_id": action_id, "field": closes_holes_field, "value": raw_closes})

        declared: List[str] = []
        seen = set()
        for c in raw_closes:
            c = c.strip()
            if c not in seen:
                seen.add(c)
                declared.append(c)

        known = [c for c in declared if c in correlation.taxonomy_by_id]
        unknown = [c for c in declared if c not in correlation.taxonomy_by_id]

        if not known:
            impacts.append(ActionHoleImpact(
                action_id=action_id, status=ranking_record.status, rank=ranking_record.rank,
                utility_score=ranking_record.utility_score, description=ranking_record.description,
                declared_closes_holes=declared, known_hole_ids=[], unknown_hole_ids=unknown,
                bundle_status=BUNDLE_REFERENCES_ONLY_UNKNOWN_HOLES, correlated_pairs=0,
                total_pairs=0, correlation_evidence=[]))
            continue

        if len(known) == 1:
            impacts.append(ActionHoleImpact(
                action_id=action_id, status=ranking_record.status, rank=ranking_record.rank,
                utility_score=ranking_record.utility_score, description=ranking_record.description,
                declared_closes_holes=declared, known_hole_ids=known, unknown_hole_ids=unknown,
                bundle_status=BUNDLE_SINGLE_HOLE, correlated_pairs=0, total_pairs=0,
                correlation_evidence=[]))
            continue

        pairs = list(itertools.combinations(known, 2))
        total_pairs = len(pairs)
        correlated_pairs = 0
        evidence_groups: Dict[Tuple[str, str], HoleCorrelationGroup] = {}
        for a, b in pairs:
            hits = _correlated_groups_for_pair(a, b, correlation.groups)
            if hits:
                correlated_pairs += 1
                for g in hits:
                    evidence_groups[(g.kind, g.key)] = g
        evidence = sorted(evidence_groups.values(), key=lambda g: (g.kind, g.key))

        if correlated_pairs == total_pairs:
            bundle_status = BUNDLE_CORRELATED
        elif correlated_pairs == 0:
            bundle_status = BUNDLE_UNCORRELATED
        else:
            bundle_status = BUNDLE_PARTIALLY_CORRELATED

        impacts.append(ActionHoleImpact(
            action_id=action_id, status=ranking_record.status, rank=ranking_record.rank,
            utility_score=ranking_record.utility_score, description=ranking_record.description,
            declared_closes_holes=declared, known_hole_ids=known, unknown_hole_ids=unknown,
            bundle_status=bundle_status, correlated_pairs=correlated_pairs,
            total_pairs=total_pairs, correlation_evidence=[g.to_dict() for g in evidence]))

    # High-value view: RANKED (i.e. already correctness/risk-gate-cleared, per
    # coverage_closure_action_utility.py's own gate) AND a fully-correlated multi-hole bundle.
    # This never reorders `ranking` itself -- it is a second, clearly-labelled lens over it.
    high_value = [i for i in impacts if i.status == RANKED_STATUS and i.bundle_status == BUNDLE_CORRELATED]
    high_value.sort(key=lambda i: (-(i.correlated_pairs or 0), -(i.utility_score or 0.0), i.action_id))

    return CoverageClosureIntelligenceReport(
        hole_correlation_groups=correlation.groups,
        action_hole_impacts=impacts,
        high_value_multi_hole_actions=high_value,
    )


def format_intelligence_report(report: CoverageClosureIntelligenceReport) -> str:
    """Human-readable rendering of a `CoverageClosureIntelligenceReport`."""
    lines = [
        f"Coverage-Closure Hole Correlation + Multi-Hole Action Intelligence: "
        f"{len(report.hole_correlation_groups)} real correlation group(s), "
        f"{len(report.high_value_multi_hole_actions)} high-value multi-hole action(s)"
    ]
    lines.append("")
    lines.append("HOLE CORRELATION GROUPS (>= 2 holes sharing real declared evidence):")
    if not report.hole_correlation_groups:
        lines.append("  (none)")
    for g in report.hole_correlation_groups:
        lines.append(f"  [{g.kind}] {g.key!r}: {', '.join(g.coverage_ids)}")
    lines.append("")
    lines.append("HIGH-VALUE MULTI-HOLE ACTIONS (RANKED status only -- i.e. already cleared the "
                  "utility module's own correctness/risk gate -- every declared closed-hole pair "
                  "correlated by real evidence; an advisory lens, NEVER a reordering of the "
                  "underlying utility ranking):")
    if not report.high_value_multi_hole_actions:
        lines.append("  (none)")
    for i in report.high_value_multi_hole_actions:
        rank_str = f"#{i.rank}" if i.rank is not None else "#?"
        util_str = f"{i.utility_score:.4g}" if i.utility_score is not None else "n/a"
        lines.append(f"  {rank_str:<4} {i.action_id:<24s} utility={util_str}"
                      f"  closes={i.known_hole_ids}")
    lines.append("")
    lines.append("ALL EXAMINED ACTIONS -- HOLE-IMPACT BREAKDOWN:")
    if not report.action_hole_impacts:
        lines.append("  (none)")
    for i in report.action_hole_impacts:
        extra = f"  unknown={i.unknown_hole_ids}" if i.unknown_hole_ids else ""
        lines.append(f"  {i.action_id:<24s} status={i.status:<10s} bundle={i.bundle_status}"
                      f"  declared={i.declared_closes_holes}{extra}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.coverage_closure_hole_correlation",
        description="Correlate coverage holes by real declared shared evidence (register / "
                    "cross-coverage axis / linked pattern / missing config), then annotate the "
                    "real coverage_closure_action_utility.py utility ranking with which "
                    "already-gate-cleared actions would close a genuinely correlated multi-hole "
                    "bundle. Never re-derives the ranking's own correctness/risk gate or reorders "
                    "it -- reads and reports only.")
    ap.add_argument("--root", default=".",
                     help="Project root, for the requirements-registry/evidence-DB/"
                          "golden-scenario lookups classify_coverage_hole_taxonomy() uses.")
    ap.add_argument("--holes-file", required=True,
                     help="JSON file holding a list of coverage-hole records.")
    ap.add_argument("--candidates-file", required=True,
                     help="JSON file holding a list of candidate coverage-closure actions; each "
                          "candidate MAY declare a 'closes_holes' list of coverage_id strings.")
    ap.add_argument("--closes-holes-field", default="closes_holes")
    ap.add_argument("--parsed-summary-file", default=None,
                     help="Optional real parse_coverage_summary()-shaped JSON file, for the "
                          "CROSS_COVERAGE_ONLY_UNCOVERED taxonomy rule.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable report.")
    a = ap.parse_args(argv)

    holes = json.loads(Path(a.holes_file).read_text(encoding="utf-8"))
    if not isinstance(holes, list):
        raise CoverageClosureHoleCorrelationError(
            "HOLES_FILE_MUST_BE_LIST", {"path": a.holes_file})

    candidates = json.loads(Path(a.candidates_file).read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise CoverageClosureActionUtilityError(
            "--candidates-file must contain a JSON list of candidate-action objects")

    parsed_summary = None
    if a.parsed_summary_file:
        parsed_summary = json.loads(Path(a.parsed_summary_file).read_text(encoding="utf-8"))

    ranking = rank_coverage_closure_actions(candidates)
    report = build_multi_hole_action_intelligence(
        candidates, ranking, holes, a.root, parsed_summary=parsed_summary,
        closes_holes_field=a.closes_holes_field)

    if a.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_intelligence_report(report))
    return 0 if not ranking.unrankable else 1


if __name__ == "__main__":
    raise SystemExit(main())
