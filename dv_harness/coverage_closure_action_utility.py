"""dv_harness/coverage_closure_action_utility.py -- ranks candidate coverage-closure actions by a
four-factor utility score, over a generic, duck-typed list of candidate actions, strictly under
this project's Evidence Truth Rule.

THE GAP THIS CLOSES. This project has plenty of per-hole coverage ANALYSIS
(`coverage_analysis.classify_coverage_hole()`'s four root causes,
`coverage_analysis.classify_coverage_hole_taxonomy()`'s twelve structural categories) and plenty of
per-project READINESS rollups (`generation_readiness.py`, `golden_flow_readiness.py`,
`subsystem_practicality_score.py`), but nothing RANKS a set of proposed remediation actions against
each other. A coverage-closure effort routinely has more candidate actions (write a new directed
test, relax an over-constrained sequence, add a waiver, escalate as unreachable) than budget to
pursue all of them at once, and nothing in this repo ordered that list by expected value. A
repo-wide grep for `coverage_closure_action`/`closure_action_utility`/`expected_coverage_gain`
before this module was written matched nothing executable.

WHY THE FOUR FACTORS ARE NEVER SELF-MEASURED. `evidence_db.py`'s own `coverage_samples` table (read
before designing this module, per this project's REUSE-OVER-REINVENT rule) is keyed by
`category_name`/`percent`/`bins_total`/`bins_hit` -- a coverage TOOL's own per-category rollup, with
no notion of a candidate ACTION, no requirement-priority field, no risk-coverage field, and no
regression/implementation-cost field. There is no mechanical producer anywhere in this repo for "how
much coverage would writing THIS specific test gain", "how important is the requirement THIS action
serves", "how much of the project's risk surface THIS action covers", or "how expensive is THIS
action to regress/implement" -- all four are judgments a human or an upstream planning agent forms
about a PROPOSED action that has not been taken yet, not facts this harness could measure by running
anything. So, exactly as `requirement_risk_ir.py` established for its own four caller-declared risk
factors (complexity/customer_impact/observability_difficulty/protocol_criticality), every factor
here is accepted only as an explicit caller declaration and reported with status DECLARED --
visibly distinct from a MEASURED value -- never re-derived, never verified, and never defaulted to
a guessed number when absent or invalid (that reports NOT_AVAILABLE instead, exactly like a missing
measurement).

THE UTILITY FORMULA, AND WHAT IT ENCODES.

    utility = expected_coverage_gain * requirement_priority * risk_coverage / cost

All four factors must be real, positive, finite numbers (never a boolean, never zero or negative --
a zero/negative gain, priority, risk_coverage or cost value is not a smaller signal, it is an
invalid declaration, since dividing by a non-positive cost or multiplying by a non-positive benefit
factor would silently invert or destroy the ranking rather than merely shrink it). An action missing
any one of the four factors, or declaring an invalid value for one, is reported UNRANKABLE with the
missing/invalid factor named -- it never receives a fabricated default (a 0, a 1, or the median of
its peers) that would let it participate in ranking on an invented basis.

THE DOCUMENT'S OWN EXPLICIT RULE, ENFORCED AS CODE (this module's central contract): "a
cheap-but-wrong action must never outrank a correct one regardless of cost." This is not a
correctness/risk PENALTY folded into the utility formula (which cost alone could still overcome for
a sufficiently cheap action) -- it is a GATE that runs BEFORE cost, or any other factor, is ever
allowed to influence ranking. Two caller-declared judgments decide the gate, each independent of the
four utility factors above and of each other:

  * `correctness_status` -- one of CONFIRMED_CORRECT / FLAGGED_INCORRECT / UNVERIFIED. An action a
    caller has flagged FLAGGED_INCORRECT is EXCLUDED from ranking entirely -- not scored, not
    penalized, not placed at the bottom of the ranked list where a large enough gain/priority/
    risk_coverage could still, in principle, pull it back up. It is removed from the candidate set
    the utility computation ever runs over.
  * `risk_status` -- one of ACCEPTABLE_RISK / HIGH_RISK / UNVERIFIED. An action flagged HIGH_RISK is
    excluded the identical way. This is a DIFFERENT judgment from the `risk_coverage` UTILITY
    FACTOR above: `risk_coverage` asks "how much risk surface does taking this action address"
    (a benefit, feeding the ranking of actions that pass the gate); `risk_status` asks "is taking
    this specific action itself dangerous" (a gate, deciding which actions are eligible to be
    ranked at all). Conflating the two would let a large declared risk_coverage number buy back an
    action a caller has separately flagged as itself high-risk to pursue.

An action carrying neither flag (the default, UNVERIFIED on both axes, when a caller declares
nothing) is NOT excluded -- exclusion is reserved for an explicit FLAGGED_INCORRECT/HIGH_RISK
declaration, never inferred from silence, per the Evidence Truth Rule's ban on treating absence as a
finding. Only once the gate has removed every flagged action does utility get computed at all for
what remains, and only after that does a genuine utility TIE among the surviving actions get broken
by cost (lower cost first) -- the ordering this module's own function names spell out literally:
`_gate_candidates()` runs, unconditionally, before `_compute_utility()`; cost is read only inside
the latter, and only ever used as a tie-breaker (never a primary sort key) inside the sort that
follows it. The reverse ordering -- deciding eligibility from cost, or letting cost affect anything
before the gate has run -- is not merely undesirable here, it is impossible to express in this
module's call sequence.

FILE-SAFETY / REUSE NOTE. This module imports NOTHING from `dv_harness` -- not `evidence_db.py`
(read, not imported, per the note above), not `requirement_risk_ir.py` (whose DECLARED-factor
disclosure PATTERN this module deliberately follows, but which is outside this batch's own
touch-scope and which this module does not need any executable code from), and none of the ~65
files this batch's other concurrent work owns. A candidate action is accepted as a generic,
duck-typed mapping (`.get`) or attribute-bearing object -- this module reads only the keys/attrs it
documents below and treats every other field as none of its business, the same discipline
`requirement_risk_ir.py`'s own `_lookup()` helper already established (re-implemented here rather
than imported, for the identical isolation reason that module's own file-safety note gives).

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It does not decide whether a flagged-incorrect or
high-risk judgment is itself correct -- arbitrating a caller's own correctness/risk declaration is
not this module's business, any more than `requirement_contract.py` arbitrates which side of a
CONTRADICTORY requirement is right. It does not measure coverage, run a regression, estimate a
requirement's priority, or compute a risk score -- it only accepts, validates the SHAPE of, and
ranks judgments a caller already formed. It writes nothing, approves nothing, and gates no stage.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

#: The four multiplicative utility factors, in the fixed order the formula names them. Callers
#: iterate this, never a hand-rolled list, so a factor can never be silently dropped from a report.
UTILITY_FACTORS: Sequence[str] = (
    "expected_coverage_gain",
    "requirement_priority",
    "risk_coverage",
    "cost",
)

#: The only two honest states a utility factor can be in. DECLARED means a caller supplied a real,
#: valid positive number and this module never re-derives or verifies it -- exactly the disclosure
#: `requirement_risk_ir.py` already established for its own caller-declared factors. NOT_AVAILABLE
#: means the factor was missing or invalid -- never silently defaulted to a guessed number.
FACTOR_STATUSES = ("DECLARED", "NOT_AVAILABLE")

#: Caller-declared correctness judgment about a candidate action itself (distinct from the
#: `risk_coverage` utility factor -- see the module docstring). FLAGGED_INCORRECT gates the action
#: out of ranking entirely, unconditionally of every utility factor.
CORRECTNESS_STATUSES = ("CONFIRMED_CORRECT", "FLAGGED_INCORRECT", "UNVERIFIED")

#: Caller-declared risk judgment about TAKING a candidate action (distinct from `risk_coverage`,
#: which measures the benefit of the risk surface it addresses). HIGH_RISK gates the action out of
#: ranking entirely, unconditionally of every utility factor.
RISK_STATUSES = ("ACCEPTABLE_RISK", "HIGH_RISK", "UNVERIFIED")

#: Overall per-action disposition after gating and utility computation.
#:   RANKED               -- passed the gate; every utility factor was DECLARED; utility computed.
#:   EXCLUDED             -- failed the correctness/risk gate; never scored, never ranked.
#:   UNRANKABLE           -- passed the gate, but at least one utility factor is NOT_AVAILABLE.
ACTION_STATUSES = ("RANKED", "EXCLUDED", "UNRANKABLE")


class CoverageClosureActionUtilityError(ValueError):
    """Raised for a genuinely malformed candidate-action input this module cannot even attempt to
    process (not a missing/invalid factor -- that is reported per-action as NOT_AVAILABLE/
    UNRANKABLE, never raised)."""


@dataclass
class UtilityFactorResult:
    """One utility factor's honest verdict: DECLARED (a real caller-supplied positive number) or
    NOT_AVAILABLE (missing or invalid) -- never blended into a computed number without saying
    which."""
    factor: str
    status: str  # one of FACTOR_STATUSES
    value: Optional[float]  # a positive finite number, or None when status == NOT_AVAILABLE
    evidence: str
    source: str = "caller declaration (not self-measured)"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateActionUtility:
    """One candidate coverage-closure action's full gate + utility record."""
    action_id: str
    status: str  # one of ACTION_STATUSES
    correctness_status: str  # one of CORRECTNESS_STATUSES
    risk_status: str  # one of RISK_STATUSES
    factors: Dict[str, UtilityFactorResult]
    utility_score: Optional[float]
    exclusion_reasons: List[str] = field(default_factory=list)
    missing_factors: List[str] = field(default_factory=list)
    description: Optional[str] = None
    rank: Optional[int] = None  # assigned only for status == "RANKED", 1-based

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "description": self.description,
            "status": self.status,
            "correctness_status": self.correctness_status,
            "risk_status": self.risk_status,
            "factors": {name: r.to_dict() for name, r in self.factors.items()},
            "utility_score": self.utility_score,
            "exclusion_reasons": list(self.exclusion_reasons),
            "missing_factors": list(self.missing_factors),
            "rank": self.rank,
        }


@dataclass
class CoverageClosureRanking:
    """The full result of ranking a set of candidate coverage-closure actions."""
    ranked: List[CandidateActionUtility]
    excluded: List[CandidateActionUtility]
    unrankable: List[CandidateActionUtility]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ranked": [a.to_dict() for a in self.ranked],
            "excluded": [a.to_dict() for a in self.excluded],
            "unrankable": [a.to_dict() for a in self.unrankable],
        }


def _lookup(candidate: Any, key: str) -> Any:
    """Duck-typed read of one field from `candidate`: a Mapping (dict-like, via `.get`) or any
    attribute-bearing object. Never raises on an object that has neither -- returns None, same as a
    missing key. Mirrors `requirement_risk_ir._lookup()`'s exact contract, re-implemented rather
    than imported per this module's own file-safety note."""
    if candidate is None:
        return None
    getter = getattr(candidate, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except TypeError:
            pass
    return getattr(candidate, key, None)


def _resolve_action_id(candidate: Any, index: int) -> str:
    raw = _lookup(candidate, "action_id")
    if raw is None:
        raw = _lookup(candidate, "id")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return f"UNKNOWN-{index}"
    return str(raw)


def _positive_finite_number(raw: Any) -> Optional[float]:
    """A real, positive, finite number -- never a bool (a Python `bool` is an `int` subclass and
    must never silently pass as a numeric factor), never zero or negative (a non-positive gain,
    priority, risk_coverage or cost is an invalid declaration for this multiplicative/divisive
    formula, not merely a small one), never NaN/inf."""
    if raw is None or isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if value != value:  # NaN
        return None
    if value in (float("inf"), float("-inf")):
        return None
    if value <= 0:
        return None
    return value


def declared_utility_factor(candidate: Any, factor_name: str) -> UtilityFactorResult:
    """One caller-DECLARED utility factor. Never self-measures -- only reads whatever
    `candidate[factor_name]` says, validates it is a real positive finite number, and reports
    NOT_AVAILABLE (never a defaulted guess) when it is missing or invalid."""
    raw = _lookup(candidate, factor_name)
    if raw is None:
        return UtilityFactorResult(
            factor=factor_name, status="NOT_AVAILABLE", value=None,
            evidence=f"'{factor_name}' was not declared by the caller for this action",
            source="caller declaration (absent)")

    value = _positive_finite_number(raw)
    if value is None:
        return UtilityFactorResult(
            factor=factor_name, status="NOT_AVAILABLE", value=None,
            evidence=(f"declared {factor_name}={raw!r} is not a valid positive, finite number "
                      "(this multiplicative/divisive formula requires one)"),
            source="caller declaration (invalid value)")

    rationale = _lookup(candidate, f"{factor_name}_rationale")
    evidence = f"caller-declared value {value}"
    if rationale:
        evidence += f" ({rationale})"
    return UtilityFactorResult(factor=factor_name, status="DECLARED", value=value, evidence=evidence)


def _resolve_gate_status(candidate: Any, field_name: str, allowed: Sequence[str]) -> Any:
    """Resolve a caller-declared gate-status field (`correctness_status`/`risk_status`). Absent
    defaults to the honest 'UNVERIFIED' member of `allowed` (never to a value that would gate the
    action either in or out on silence). An explicitly-declared but unrecognized value is reported
    as invalid -- returns None so the caller can distinguish "not declared" (defaulted) from
    "declared something this module does not recognize" (a real caller error)."""
    raw = _lookup(candidate, field_name)
    if raw is None:
        return "UNVERIFIED"
    text = str(raw).strip()
    if text in allowed:
        return text
    return None  # invalid declaration -- distinct from absent


def _gate_candidates(action_id: str, candidate: Any) -> Sequence[Any]:
    """Resolve the two gate judgments for one candidate. Returns
    (correctness_status_or_None, risk_status_or_None, invalid_field_names)."""
    invalid: List[str] = []
    correctness = _resolve_gate_status(candidate, "correctness_status", CORRECTNESS_STATUSES)
    if correctness is None:
        invalid.append("correctness_status")
    risk = _resolve_gate_status(candidate, "risk_status", RISK_STATUSES)
    if risk is None:
        invalid.append("risk_status")
    return correctness, risk, invalid


def _compute_utility(factors: Dict[str, UtilityFactorResult]) -> Sequence[Any]:
    """Compute `utility = gain * priority * risk_coverage / cost` ONLY when every factor is
    DECLARED. Returns (utility_or_None, missing_factor_names) -- never a partial/guessed number."""
    missing = [name for name in UTILITY_FACTORS if factors[name].status != "DECLARED"]
    if missing:
        return None, missing
    gain = factors["expected_coverage_gain"].value
    priority = factors["requirement_priority"].value
    risk_coverage = factors["risk_coverage"].value
    cost = factors["cost"].value
    utility = (gain * priority * risk_coverage) / cost
    return utility, []


def rank_coverage_closure_actions(candidates: Sequence[Any]) -> CoverageClosureRanking:
    """Rank a duck-typed sequence of candidate coverage-closure actions by utility.

    Each candidate may supply (via `.get`/attribute access, everything optional except that a
    missing/invalid utility factor makes that candidate UNRANKABLE):
      - `action_id` / `id`, `description` (labels only)
      - `expected_coverage_gain`, `requirement_priority`, `risk_coverage`, `cost` (each a positive,
        finite number; each accepted only as a caller declaration, reported DECLARED/NOT_AVAILABLE)
      - `<factor>_rationale` (optional evidence text for any of the four factors above)
      - `correctness_status` (CONFIRMED_CORRECT / FLAGGED_INCORRECT / UNVERIFIED; default
        UNVERIFIED) and `risk_status` (ACCEPTABLE_RISK / HIGH_RISK / UNVERIFIED; default
        UNVERIFIED) -- the correctness/risk GATE, resolved and applied BEFORE any utility factor
        (including cost) is ever read for that candidate.

    An empty/None `candidates` sequence raises `CoverageClosureActionUtilityError` -- there is
    nothing to rank, and returning an empty-but-successful ranking would look identical to "every
    candidate was excluded", which is a materially different, citable fact."""
    if not candidates:
        raise CoverageClosureActionUtilityError(
            "rank_coverage_closure_actions: no candidate actions were supplied to rank")

    ranked: List[CandidateActionUtility] = []
    excluded: List[CandidateActionUtility] = []
    unrankable: List[CandidateActionUtility] = []

    for index, candidate in enumerate(candidates):
        action_id = _resolve_action_id(candidate, index)
        description = _lookup(candidate, "description")
        description = str(description) if description else None

        # --- Gate FIRST. Nothing about cost (or any other utility factor) is read yet. ---------
        correctness_status, risk_status, invalid_gate_fields = _gate_candidates(action_id, candidate)

        if invalid_gate_fields:
            record = CandidateActionUtility(
                action_id=action_id, status="UNRANKABLE",
                correctness_status=correctness_status or "UNVERIFIED",
                risk_status=risk_status or "UNVERIFIED",
                factors={}, utility_score=None,
                missing_factors=[f"{name} (invalid declared value)" for name in invalid_gate_fields],
                description=description)
            unrankable.append(record)
            continue

        exclusion_reasons: List[str] = []
        if correctness_status == "FLAGGED_INCORRECT":
            exclusion_reasons.append(
                "correctness_status=FLAGGED_INCORRECT -- excluded from ranking entirely, "
                "regardless of cost or any other factor")
        if risk_status == "HIGH_RISK":
            exclusion_reasons.append(
                "risk_status=HIGH_RISK -- excluded from ranking entirely, "
                "regardless of cost or any other factor")

        if exclusion_reasons:
            # Still resolve and report the four factors for audit transparency -- an excluded
            # action's declared numbers are never hidden, only never used to compute a score.
            factors = {name: declared_utility_factor(candidate, name) for name in UTILITY_FACTORS}
            record = CandidateActionUtility(
                action_id=action_id, status="EXCLUDED",
                correctness_status=correctness_status, risk_status=risk_status,
                factors=factors, utility_score=None,
                exclusion_reasons=exclusion_reasons, description=description)
            excluded.append(record)
            continue

        # --- Gate passed. Only NOW are the utility factors (including cost) read. ---------------
        factors = {name: declared_utility_factor(candidate, name) for name in UTILITY_FACTORS}
        utility, missing = _compute_utility(factors)

        if missing:
            record = CandidateActionUtility(
                action_id=action_id, status="UNRANKABLE",
                correctness_status=correctness_status, risk_status=risk_status,
                factors=factors, utility_score=None, missing_factors=missing,
                description=description)
            unrankable.append(record)
            continue

        record = CandidateActionUtility(
            action_id=action_id, status="RANKED",
            correctness_status=correctness_status, risk_status=risk_status,
            factors=factors, utility_score=utility, description=description)
        ranked.append(record)

    # Sort: utility descending (primary); cost ascending is the ONLY tie-breaker, applied only
    # among actions that already cleared the gate and already have a real utility score --
    # cost never influences which actions reach this sort in the first place. action_id is the
    # final, fully deterministic tie-breaker.
    ranked.sort(key=lambda r: (-r.utility_score, r.factors["cost"].value, r.action_id))
    for position, record in enumerate(ranked, start=1):
        record.rank = position

    excluded.sort(key=lambda r: r.action_id)
    unrankable.sort(key=lambda r: r.action_id)

    return CoverageClosureRanking(ranked=ranked, excluded=excluded, unrankable=unrankable)


def format_ranking_report(ranking: CoverageClosureRanking) -> str:
    """Human-readable rendering of a `CoverageClosureRanking`."""
    lines = [
        f"Coverage-Closure Action Utility Ranking: "
        f"{len(ranking.ranked)} ranked, {len(ranking.excluded)} excluded, "
        f"{len(ranking.unrankable)} unrankable"
    ]
    lines.append("")
    lines.append("RANKED (utility = gain x priority x risk_coverage / cost, all DECLARED):")
    if not ranking.ranked:
        lines.append("  (none)")
    for r in ranking.ranked:
        lines.append(f"  #{r.rank:<3d} {r.action_id:<24s} utility={r.utility_score:.4g}"
                      f"  correctness={r.correctness_status} risk={r.risk_status}")
    lines.append("")
    lines.append("EXCLUDED (correctness/risk gate -- never scored, never merely penalized):")
    if not ranking.excluded:
        lines.append("  (none)")
    for r in ranking.excluded:
        lines.append(f"  {r.action_id:<24s} " + "; ".join(r.exclusion_reasons))
    lines.append("")
    lines.append("UNRANKABLE (missing/invalid declared factor):")
    if not ranking.unrankable:
        lines.append("  (none)")
    for r in ranking.unrankable:
        lines.append(f"  {r.action_id:<24s} missing: " + ", ".join(r.missing_factors))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.coverage_closure_action_utility",
        description="Rank candidate coverage-closure actions by utility = expected_coverage_gain x "
                    "requirement_priority x risk_coverage / cost. Every factor is a caller "
                    "declaration (reported DECLARED, never self-measured). An action whose "
                    "correctness_status=FLAGGED_INCORRECT or risk_status=HIGH_RISK is excluded "
                    "from ranking entirely, before cost or any other factor is considered. "
                    "Reads and reports only -- writes nothing, gates no stage.")
    ap.add_argument("--candidates-file", required=True,
                     help="JSON file holding a list of candidate-action objects.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable ranking.")
    a = ap.parse_args(argv)

    candidates = json.loads(Path(a.candidates_file).read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise CoverageClosureActionUtilityError(
            "--candidates-file must contain a JSON list of candidate-action objects")

    ranking = rank_coverage_closure_actions(candidates)
    if a.json:
        print(json.dumps(ranking.to_dict(), indent=2))
    else:
        print(format_ranking_report(ranking))
    return 0 if not ranking.unrankable else 1


if __name__ == "__main__":
    raise SystemExit(main())
