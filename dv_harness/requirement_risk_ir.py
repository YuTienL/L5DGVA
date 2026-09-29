"""dv_harness/requirement_risk_ir.py -- the Requirement Risk IR: a six-factor
risk score (complexity, change_frequency, bug_history, customer_impact,
observability_difficulty, protocol_criticality) for one requirement, built
strictly under this project's Evidence Truth Rule.

THE GAP THIS CLOSES. `requirement_contract.py` (spec section 184) captures a
requirement's fifteen contract fields plus a five-value status vocabulary, but
nothing in this repo turns a requirement's own properties into a RISK number a
downstream prioritizer could sort by. `subsystem_practicality_score.py` and
`subsystem_maturity_gate.py` score a *subsystem*; nothing scores a single
*requirement*. This module is deliberately narrow: it produces one risk
profile per requirement and does nothing else -- it never assigns priority,
never gates generation, never writes to any store.

WHY SIX FACTORS AND NOT MORE. The task names exactly these six, and they split
into two kinds this module keeps visibly separate rather than blending into
one opaque number:

  * MEASURED -- `change_frequency` is the only factor with a real, mechanical
    producer in this repo: `git log --oneline -- <path>` against the
    requirement's own source file, counted the same read-only, degrade-never-
    raise way `trend_analysis._git()` and `change_impact._git()` already do
    (mirrored here, not imported -- see the file-safety note below). A commit
    count is real evidence of how often a requirement's backing artifact
    actually changes.

  * DECLARED -- `complexity`, `customer_impact`, `observability_difficulty`,
    and `protocol_criticality` have NO mechanical producer anywhere in this
    repo (verified by repo-wide grep before this module was written: no
    complexity metric, no customer-impact ledger, no observability-difficulty
    estimator, no protocol-criticality classifier exists). A human or an
    upstream agent may still know these things about a requirement, so this
    module accepts them as an explicit, caller-declared 1-5 value and reports
    them with status DECLARED -- visibly distinct from a MEASURED value, per
    the Evidence Truth Rule's ban on silently treating a claim as evidence.

  * NOT_AVAILABLE -- `bug_history` has no real producer anywhere in this repo
    either (same repo-wide grep: no defect tracker, no bug database, no
    incident log). Unlike the four DECLARED factors, the task specifies this
    one has no legitimate caller-declaration path either -- it is always
    reported NOT_AVAILABLE, never invented and never accepted as a declared
    guess. If a real bug-history producer is ever added to this repo, this
    module should be revisited; until then, guessing a plausible-looking
    number here would be exactly the fabrication CLAUDE.md's Evidence Truth
    Rule forbids.

A requirement whose backing file is not yet known, or whose project is not a
git repository, degrades `change_frequency` to NOT_AVAILABLE too (missing git
binary, git timeout, "not a git repository", nonexistent project root) --
never to a guessed score. The composite score this module reports is the
mean of only the AVAILABLE factors, always paired with how many of the six
factors that mean actually rests on (`available_factor_count`,
`missing_factors`), so a caller can never mistake a partial score for a full
one.

FILE-SAFETY / REUSE NOTE. This module intentionally re-implements the tiny
`_git()` read-only subprocess wrapper rather than importing
`trend_analysis._git()` or `change_impact._git()`: those modules are outside
this batch's touch scope and importing across concurrently-edited modules is
exactly what this batch's isolation rule forbids. The wrapper's contract is
identical on purpose (same return shape, same degrade-never-raise behavior)
so a future consolidation is a mechanical no-op. `requirement_facts` is
accepted as a generic, duck-typed mapping (or attribute-bearing object) --
this module does NOT import `requirement_contract.py` or any other module in
the batch's claimed-files list; it reads whichever of `complexity`,
`change_frequency`'s inputs, `bug_history`, `customer_impact`,
`observability_difficulty`, `protocol_criticality`, `requirement_id`/`id`,
and `<factor>_rationale` keys happen to be present, and treats every other
key as none of its business.

WHAT THIS MODULE DELIBERATELY DOES NOT DO: it does not compute a priority, a
readiness verdict, or a go/no-go gate; it does not write to any store, run
any tool, or approve/reject anything; it never defaults a missing or invalid
declared value to a middle-of-the-scale guess -- a missing or out-of-range
declaration is NOT_AVAILABLE, exactly like a missing measurement.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: Canonical order of the six risk factors this module scores. Fixed and
#: exhaustive -- callers iterate this, never a hand-rolled list, so a factor
#: can never be silently dropped from a report.
RISK_FACTORS: Sequence[str] = (
    "complexity",
    "change_frequency",
    "bug_history",
    "customer_impact",
    "observability_difficulty",
    "protocol_criticality",
)

#: The only three honest states a single factor can be in. MEASURED means a
#: real mechanical producer ran (currently only `change_frequency`).
#: DECLARED means a human/upstream caller supplied the value and this module
#: never re-derives or verifies it. NOT_AVAILABLE means neither happened --
#: never silently defaulted.
FACTOR_STATUSES = ("MEASURED", "DECLARED", "NOT_AVAILABLE")

#: Valid declared/measured risk scale: 1 (lowest risk) .. 5 (highest risk).
RISK_SCALE_MIN = 1
RISK_SCALE_MAX = 5

#: Factors this module measures itself from real evidence. Kept as a set so
#: `assess_requirement_risk()` never has to hardcode the split twice.
MEASURED_FACTORS = frozenset({"change_frequency"})

#: The one factor the task's own explicit rule says can never have a real
#: producer in this repo, and so can never be declared either -- always
#: NOT_AVAILABLE.
NO_PRODUCER_FACTORS = frozenset({"bug_history"})

#: Every other factor is accepted only as an explicit caller declaration.
DECLARED_FACTORS = frozenset(RISK_FACTORS) - MEASURED_FACTORS - NO_PRODUCER_FACTORS


@dataclass
class RiskFactorResult:
    """One factor's honest verdict: never blends MEASURED, DECLARED, and
    NOT_AVAILABLE into a single number without saying which it is."""
    factor: str
    status: str  # one of FACTOR_STATUSES
    score: Optional[int]  # 1-5, or None when status == NOT_AVAILABLE
    evidence: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RequirementRiskProfile:
    """The full six-factor risk profile for one requirement."""
    requirement_id: str
    factors: Dict[str, RiskFactorResult]
    composite_score: Optional[float]
    available_factor_count: int
    missing_factors: List[str]
    coverage: str  # e.g. "4/6"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "factors": {name: r.to_dict() for name, r in self.factors.items()},
            "composite_score": self.composite_score,
            "available_factor_count": self.available_factor_count,
            "missing_factors": list(self.missing_factors),
            "coverage": self.coverage,
        }


def _git(root: Path, args: List[str], timeout: int = 30) -> tuple:
    """Read-only git invocation, mirroring `trend_analysis._git()` /
    `change_impact._git()`'s exact degrade-never-raise contract (missing
    binary -> rc 127, timeout -> rc 124) so a machine without git, or a
    project root that is not a git repository, produces an honest
    NOT_AVAILABLE change_frequency instead of raising out of this module.
    Reimplemented locally rather than imported -- see the module docstring's
    file-safety note."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args],
                               capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        return 127, "", f"git not found on PATH: {e}"
    except subprocess.TimeoutExpired as e:
        return 124, "", f"git timed out: {e}"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _bucket_commit_count(commit_count: int) -> int:
    """Deterministic, documented mapping from a real commit count to the
    1-5 risk scale. Not a fabricated score -- every input is a real count
    from `git log --oneline`, and the thresholds are fixed and disclosed
    here rather than tuned per requirement."""
    if commit_count <= 0:
        return 1
    if commit_count <= 2:
        return 2
    if commit_count <= 5:
        return 3
    if commit_count <= 10:
        return 4
    return 5


def measure_change_frequency(source_file: Optional[str], project_root: Optional[str],
                              timeout: int = 30) -> RiskFactorResult:
    """The one MEASURED factor: count real commits touching `source_file`
    under `project_root` via `git log --oneline -- <path>`. Degrades to
    NOT_AVAILABLE (never a guessed score) whenever the evidence genuinely
    isn't available: no path given, no project root given, the root does
    not exist, git is missing, git times out, or the root is not a git
    repository (or the path has no history in it -- git itself reports
    that as a clean, real "no commits" result, which IS real evidence and
    is reported as commit_count == 0, not NOT_AVAILABLE)."""
    if not source_file or not project_root:
        return RiskFactorResult(
            factor="change_frequency", status="NOT_AVAILABLE", score=None,
            evidence="no source_file/project_root given for change-frequency measurement",
            source="git log --oneline -- <path> (not run: missing inputs)")

    root = Path(project_root)
    if not root.exists():
        return RiskFactorResult(
            factor="change_frequency", status="NOT_AVAILABLE", score=None,
            evidence=f"project_root {root} does not exist",
            source="git log --oneline -- <path> (not run: missing project root)")

    rc, out, err = _git(root, ["log", "--oneline", "--", str(source_file)], timeout=timeout)
    if rc == 127:
        return RiskFactorResult(
            factor="change_frequency", status="NOT_AVAILABLE", score=None,
            evidence="git is not installed / not on PATH",
            source="git log --oneline -- <path> (not run: git missing)")
    if rc == 124:
        return RiskFactorResult(
            factor="change_frequency", status="NOT_AVAILABLE", score=None,
            evidence=f"git log timed out after {timeout}s",
            source="git log --oneline -- <path> (timed out)")
    if rc != 0:
        return RiskFactorResult(
            factor="change_frequency", status="NOT_AVAILABLE", score=None,
            evidence=f"git log failed (not a git repository, or invalid path): {err.strip()}",
            source="git log --oneline -- <path> (git error)")

    commit_count = len([ln for ln in out.splitlines() if ln.strip()])
    score = _bucket_commit_count(commit_count)
    return RiskFactorResult(
        factor="change_frequency", status="MEASURED", score=score,
        evidence=f"{commit_count} commit(s) touching {source_file} (git log --oneline)",
        source=f"git log --oneline -- {source_file}")


def bug_history_factor() -> RiskFactorResult:
    """`bug_history` has no real producer anywhere in this repo (no defect
    tracker, no bug database, no incident log) and, per the task's own
    explicit rule, is never accepted as a caller declaration either --
    always NOT_AVAILABLE, never invented."""
    return RiskFactorResult(
        factor="bug_history", status="NOT_AVAILABLE", score=None,
        evidence=("no bug-tracking or defect-history producer exists anywhere in this "
                  "repo; a bug_history risk score would have to be fabricated, which the "
                  "Evidence Truth Rule forbids"),
        source="no producer in this repo")


def _lookup(requirement_facts: Any, key: str) -> Any:
    """Duck-typed read of one field from `requirement_facts`: a Mapping
    (dict-like, via `.get`) or any attribute-bearing object. Never raises
    on an object that has neither -- returns None, same as a missing key."""
    if requirement_facts is None:
        return None
    getter = getattr(requirement_facts, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except TypeError:
            pass
    return getattr(requirement_facts, key, None)


def declared_factor(requirement_facts: Any, factor_name: str) -> RiskFactorResult:
    """One of the four caller-DECLARED factors (complexity, customer_impact,
    observability_difficulty, protocol_criticality). Never self-measures --
    only reads whatever `requirement_facts[factor_name]` says, validates it
    is a real 1-5 integer, and reports NOT_AVAILABLE (never a defaulted
    guess) when it is missing or invalid."""
    raw = _lookup(requirement_facts, factor_name)
    if raw is None:
        return RiskFactorResult(
            factor=factor_name, status="NOT_AVAILABLE", score=None,
            evidence=f"'{factor_name}' was not declared by the caller for this requirement",
            source="caller declaration (absent)")

    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return RiskFactorResult(
            factor=factor_name, status="NOT_AVAILABLE", score=None,
            evidence=f"declared {factor_name}={raw!r} is not a valid integer risk score",
            source="caller declaration (invalid type)")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return RiskFactorResult(
            factor=factor_name, status="NOT_AVAILABLE", score=None,
            evidence=f"declared {factor_name}={raw!r} is not a valid integer risk score",
            source="caller declaration (invalid type)")

    if not (RISK_SCALE_MIN <= value <= RISK_SCALE_MAX):
        return RiskFactorResult(
            factor=factor_name, status="NOT_AVAILABLE", score=None,
            evidence=(f"declared {factor_name}={value} is outside the valid "
                      f"{RISK_SCALE_MIN}-{RISK_SCALE_MAX} risk scale"),
            source="caller declaration (out of range)")

    rationale = _lookup(requirement_facts, f"{factor_name}_rationale")
    evidence = f"caller-declared value {value}"
    if rationale:
        evidence += f" ({rationale})"
    return RiskFactorResult(
        factor=factor_name, status="DECLARED", score=value, evidence=evidence,
        source="caller declaration (not self-measured)")


def assess_requirement_risk(requirement_facts: Any, *, source_file: Optional[str] = None,
                             project_root: Optional[str] = None,
                             timeout: int = 30) -> RequirementRiskProfile:
    """Build the full six-factor `RequirementRiskProfile` for one
    requirement. `requirement_facts` is a generic, duck-typed
    mapping/object -- this function reads only the keys it names below and
    is agnostic to everything else the caller's requirement record carries.

    `source_file`/`project_root` feed the one MEASURED factor
    (`change_frequency`); everything else comes from
    `requirement_facts["complexity"]`, `["customer_impact"]`,
    `["observability_difficulty"]`, `["protocol_criticality"]` (each with an
    optional `"<factor>_rationale"`), and `["requirement_id"]` /
    `["id"]` for the profile's own label. `bug_history` never reads
    anything -- it is always NOT_AVAILABLE."""
    requirement_id = (_lookup(requirement_facts, "requirement_id")
                       or _lookup(requirement_facts, "id")
                       or "UNKNOWN")

    factors: Dict[str, RiskFactorResult] = {
        "complexity": declared_factor(requirement_facts, "complexity"),
        "change_frequency": measure_change_frequency(source_file, project_root, timeout=timeout),
        "bug_history": bug_history_factor(),
        "customer_impact": declared_factor(requirement_facts, "customer_impact"),
        "observability_difficulty": declared_factor(requirement_facts, "observability_difficulty"),
        "protocol_criticality": declared_factor(requirement_facts, "protocol_criticality"),
    }

    available = [factors[name] for name in RISK_FACTORS if factors[name].status != "NOT_AVAILABLE"]
    missing = [name for name in RISK_FACTORS if factors[name].status == "NOT_AVAILABLE"]
    composite = round(sum(r.score for r in available) / len(available), 2) if available else None

    return RequirementRiskProfile(
        requirement_id=str(requirement_id),
        factors=factors,
        composite_score=composite,
        available_factor_count=len(available),
        missing_factors=missing,
        coverage=f"{len(available)}/{len(RISK_FACTORS)}",
    )


def format_risk_report(profile: RequirementRiskProfile) -> str:
    """Human-readable rendering of a `RequirementRiskProfile`, in the fixed
    `RISK_FACTORS` order."""
    lines = [f"Requirement Risk IR: {profile.requirement_id}",
             f"  coverage: {profile.coverage} factors available, "
             f"composite_score={profile.composite_score}"]
    for name in RISK_FACTORS:
        r = profile.factors[name]
        score_txt = "n/a" if r.score is None else str(r.score)
        lines.append(f"  [{r.status:13s}] {name:26s} score={score_txt}  {r.evidence}")
    if profile.missing_factors:
        lines.append(f"  missing: {', '.join(profile.missing_factors)}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.requirement_risk_ir",
        description="Six-factor requirement risk profile (complexity, change_frequency, "
                    "bug_history, customer_impact, observability_difficulty, "
                    "protocol_criticality). change_frequency is measured from real git "
                    "history; the four declared factors come only from --facts-file; "
                    "bug_history is always NOT_AVAILABLE (no real producer in this repo). "
                    "Reads and reports only -- writes nothing, gates nothing.")
    ap.add_argument("--facts-file", default=None,
                     help="JSON file with requirement facts (requirement_id/id, complexity, "
                          "customer_impact, observability_difficulty, protocol_criticality, "
                          "and optional '<factor>_rationale' keys).")
    ap.add_argument("--source-file", default=None,
                     help="Path (relative to --project-root) whose git history measures "
                          "change_frequency.")
    ap.add_argument("--project-root", default=None,
                     help="Git repository root that --source-file is measured against.")
    ap.add_argument("--json", action="store_true", help="Emit the machine-readable profile.")
    a = ap.parse_args(argv)

    facts: Dict[str, Any] = {}
    if a.facts_file:
        facts = json.loads(Path(a.facts_file).read_text(encoding="utf-8"))

    profile = assess_requirement_risk(facts, source_file=a.source_file,
                                       project_root=a.project_root)
    if a.json:
        print(json.dumps(profile.to_dict(), indent=2))
    else:
        print(format_risk_report(profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
