"""dv_harness/l5dgva_gap_queue.py -- aggregation logic for the L5DGVA
all-contract audit's Phase 2 output (per-cluster classifications against
`dv_harness/`, produced by domain-audit passes) into the Phase 3 artifacts
V21 SS622/SS625/SS636 call `ContractImplementationGapQueue` and
`AllContractImplementationClosureMatrix`.

MIGRATED (M5 Capability Pool Closure, Batch 2, from Parent). Real, tested
Parent capability (24/24 tests, independently re-run in Parent's own tree
before trusting). Fully self-contained (stdlib only: `dataclasses`, `enum`)
-- no canonical dependency of any kind. This module is itself the ROOT
dependency this Batch's dependency-graph analysis found blocking
`CAP-POOL-003` (`l5dgva_directive_blackboard_work_queue.py`, via
`l5dgva_workitem_projection.py`/`l5dgva_directive_registry.py`) and
`CAP-POOL-004` (`l5dgva_kc_extraction.py`, directly).

This module takes ClosureRow records (one per audited concept cluster,
already classified with the 12-state runtime-status vocabulary and cited
evidence -- that classification work is semantic/evidence-based and is done
by a human or an LLM audit pass reading real source, never by this module)
and does the mechanical, honestly-checkable part: priority assignment,
coverage-percentage arithmetic, and Markdown rendering.

HONESTY NOTE: `ContractRuntimeCoverage` here is computed strictly from
whatever ClosureRow statuses were actually supplied. It has no floor, no
rounding-up, and no way to reach 100% except by every supplied row actually
being IMPLEMENTED_AND_OPERATIONAL. A caller that wants a specific number
must earn it by classifying rows that way with real evidence, not by
calling a function that produces one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RuntimeStatus(str, Enum):
    IMPLEMENTED_AND_OPERATIONAL = "IMPLEMENTED_AND_OPERATIONAL"
    DOCUMENTED_NOT_IMPLEMENTED = "DOCUMENTED_NOT_IMPLEMENTED"
    IMPLEMENTED_NOT_WIRED = "IMPLEMENTED_NOT_WIRED"
    WIRED_NOT_REACHABLE = "WIRED_NOT_REACHABLE"
    WIRED_NOT_TRIGGERED = "WIRED_NOT_TRIGGERED"
    TRIGGERED_NO_ARTIFACT = "TRIGGERED_NO_ARTIFACT"
    ARTIFACT_NOT_CONSUMED = "ARTIFACT_NOT_CONSUMED"
    CONSUMED_OUTCOME_NOT_VERIFIED = "CONSUMED_OUTCOME_NOT_VERIFIED"
    REGRESSION_MISSING = "REGRESSION_MISSING"
    NOT_PROVEN = "NOT_PROVEN"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE_WITH_EVIDENCE = "NOT_APPLICABLE_WITH_EVIDENCE"


PASSING_STATUSES = frozenset({
    RuntimeStatus.IMPLEMENTED_AND_OPERATIONAL,
    RuntimeStatus.NOT_APPLICABLE_WITH_EVIDENCE,
    RuntimeStatus.WIRED_NOT_TRIGGERED,
})

# POLICY CHANGE (2026-09-18, explicit user decision, project owner):
# this audit program's current scope is IMPLEMENTATION-AND-INTEGRATION
# verification -- does the mechanism exist and is it genuinely reachable
# from a real dispatch path -- not live end-to-end operational proof. A
# WIRED_NOT_TRIGGERED row (mechanism real+tested AND a real, non-mock call
# site exists in the real dispatch path -- confirmed by direct code read,
# never a mock/stub) counts as closed for this audit's own purposes, even
# though it has never yet fired in a real recorded run. This was a
# deliberate, informed choice, not an oversight: WIRED_NOT_REACHABLE stays
# a gap (the wiring itself is broken/dead), and TRIGGERED_NO_ARTIFACT
# onward also stay gaps -- confirmed via eight_engine_runtime_proof_matrix.py/
# engine_maturity_state.py's own live evidence that this repo currently has
# NO producer anywhere for ArtifactIds/ConsumerIds/OutcomeVerified/
# RegressionIds on any engine, so those four rungs are structurally
# unreachable today regardless of whether a real end-to-end scenario (e.g.
# generating a CAN-FD verification environment) is ever run -- moving the
# PASS line past WIRED_NOT_TRIGGERED would require building that missing
# instrumentation first, a separate, larger, not-yet-scoped task.
#
# Statuses that represent a genuinely closed row for coverage-denominator
# purposes under this audit's current scope: either it works, evidence says
# it need not, or it is genuinely implemented and wired into a real dispatch
# path (verification of live triggering/artifact/consumption/outcome is
# explicitly out of this audit's current scope). Every other status is an
# open gap by definition.
GAP_STATUSES = frozenset(s for s in RuntimeStatus if s not in PASSING_STATUSES)


class Priority(str, Enum):
    P0_VERIFICATION_TRUTH = "P0"
    P1_GRAPH_GATE_ENGINE_KNOWLEDGE = "P1"
    P2_DE_REFERENCE_BUILD_DEBUG_COVERAGE = "P2"
    P3_OBSERVABILITY_UX = "P3"


# Domain -> default priority, per the user's own explicit P0-P3 definition:
# P0 verification truth / false signoff; P1 graph/gate/engine/KC/memory/
# Obsidian; P2 DE/reference/build/debug/coverage; P3 observability/UX.
_DOMAIN_DEFAULT_PRIORITY = {
    "A_orchestration_engines": Priority.P1_GRAPH_GATE_ENGINE_KNOWLEDGE,
    "B_kc_memory_obsidian": Priority.P1_GRAPH_GATE_ENGINE_KNOWLEDGE,
    "C_reference_de_architecture": Priority.P2_DE_REFERENCE_BUILD_DEBUG_COVERAGE,
    "D_irq": Priority.P2_DE_REFERENCE_BUILD_DEBUG_COVERAGE,
    "E_evidence_vplan_coverage_signoff": Priority.P0_VERIFICATION_TRUTH,
    "F_contract_as_code_meta": Priority.P0_VERIFICATION_TRUTH,
    "G_foundational_v1": Priority.P1_GRAPH_GATE_ENGINE_KNOWLEDGE,
}

# Within any domain, a row whose notes/cluster text signals it IS a
# signoff/verification-truth claim (rather than an implementation detail of
# that domain) escalates to P0 regardless of domain default -- a false PASS
# in, say, IRQ signoff is a P0 problem even though IRQ itself defaults P2.
_P0_ESCALATION_KEYWORDS = ("signoff", "false pass", "false-pass", "verification complete", "verification truth")


@dataclass
class ClosureRow:
    domain: str
    cluster: str
    requirement_ids: list[str]
    status: RuntimeStatus
    evidence: str
    confidence: str  # "high" | "medium" | "low"
    notes: str = ""

    def priority(self) -> Priority:
        text = f"{self.cluster} {self.notes}".lower()
        if any(kw in text for kw in _P0_ESCALATION_KEYWORDS):
            return Priority.P0_VERIFICATION_TRUTH
        return _DOMAIN_DEFAULT_PRIORITY.get(self.domain, Priority.P2_DE_REFERENCE_BUILD_DEBUG_COVERAGE)

    def is_gap(self) -> bool:
        return self.status in GAP_STATUSES

    def requirement_count(self) -> int:
        return len(self.requirement_ids)


@dataclass
class CoverageMetrics:
    total_requirements: int
    passing_requirements: int
    by_status: dict[str, int] = field(default_factory=dict)

    @property
    def coverage_percent(self) -> float:
        if self.total_requirements == 0:
            return 0.0
        return round(100.0 * self.passing_requirements / self.total_requirements, 2)


def compute_coverage(rows: list[ClosureRow]) -> CoverageMetrics:
    """SS625 ContractRuntimeCoverageMetrics, at requirement granularity (a
    cluster covering 40 requirement_ids counts 40x, not 1x) -- a domain with
    a handful of big unaudited clusters must not look "mostly done" next to
    one with many small audited ones."""
    by_status: dict[str, int] = {}
    total = 0
    passing = 0
    for row in rows:
        n = row.requirement_count()
        total += n
        by_status[row.status.value] = by_status.get(row.status.value, 0) + n
        if row.status in PASSING_STATUSES:
            passing += n
    return CoverageMetrics(total_requirements=total, passing_requirements=passing, by_status=by_status)


def build_gap_queue(rows: list[ClosureRow]) -> dict[Priority, list[ClosureRow]]:
    """SS622 ContractImplementationGapQueue: every gap row, bucketed P0-P3.
    Rows that already pass are not gaps and are not returned here."""
    queue: dict[Priority, list[ClosureRow]] = {p: [] for p in Priority}
    for row in rows:
        if row.is_gap():
            queue[row.priority()].append(row)
    return queue


def rows_from_json(records: list[dict]) -> list[ClosureRow]:
    """Caller-supplied `{domain, cluster, requirement_ids, status, evidence,
    confidence, notes}` dicts (the same shape this module's own docstring
    calls a ClosureRow) -> real `ClosureRow` objects. `status` is matched
    case-insensitively against `RuntimeStatus`; an unrecognized value raises
    rather than silently defaulting to a passing status."""
    out: list[ClosureRow] = []
    for rec in records:
        raw_status = str(rec["status"]).strip().upper()
        try:
            status = RuntimeStatus(raw_status)
        except ValueError as exc:
            raise ValueError(
                f"rows_from_json: unrecognized status {raw_status!r} for cluster "
                f"{rec.get('cluster')!r}; must be one of {[s.value for s in RuntimeStatus]}"
            ) from exc
        out.append(
            ClosureRow(
                domain=rec["domain"],
                cluster=rec["cluster"],
                requirement_ids=list(rec["requirement_ids"]),
                status=status,
                evidence=rec.get("evidence", ""),
                confidence=rec.get("confidence", "medium"),
                notes=rec.get("notes", ""),
            )
        )
    return out


def render_closure_matrix(rows: list[ClosureRow]) -> str:
    """SS636 AllContractImplementationClosureMatrix, one Markdown table row
    per audited concept cluster (not per raw requirement_id -- with ~1050
    exact requirements a per-requirement table would be unreadable; the
    cluster IS the unit of audit here, and its requirement_ids are listed in
    a column so nothing is lost)."""
    coverage = compute_coverage(rows)
    lines = [
        "# AllContractImplementationClosureMatrix",
        "",
        f"ContractRuntimeCoverage = {coverage.coverage_percent}% "
        f"({coverage.passing_requirements}/{coverage.total_requirements} requirements, by status below)",
        "",
        "| Status | Requirement count |",
        "|---|---|",
    ]
    for status in RuntimeStatus:
        n = coverage.by_status.get(status.value, 0)
        if n:
            lines.append(f"| {status.value} | {n} |")
    lines += [
        "",
        "| Domain | Cluster | Priority | Status | RequirementIds | Confidence | Evidence | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        ids = ", ".join(row.requirement_ids[:6]) + (f", … (+{len(row.requirement_ids) - 6} more)" if len(row.requirement_ids) > 6 else "")
        lines.append(
            f"| {row.domain} | {row.cluster} | {row.priority().value} | {row.status.value} | {ids} | {row.confidence} | {row.evidence} | {row.notes} |"
        )
    return "\n".join(lines)


# --- CLI front door -----------------------------------------------------------


def execute_verb(argv: list[str] | None = None) -> int:
    """`python -m dv_harness.l5dgva_gap_queue --rows <file.json> [--markdown]`.
    `<file.json>` is a bare list of, or `{"rows": [...]}` wrapping, the
    `{domain, cluster, requirement_ids, status, evidence, confidence, notes}`
    records `rows_from_json()` accepts. Exit 0 if ContractRuntimeCoverage is
    100%, 1 otherwise -- mirroring system_closure_aggregator.execute_verb()'s
    exit-code convention so both L5DGVA-audit CLI verbs behave the same way
    for a scripted caller."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(prog="l5dgva-gap-queue")
    parser.add_argument("--rows", required=True,
                         help='path to a JSON file: a bare list of ClosureRow-shaped '
                              'records, or {"rows": [...]}')
    parser.add_argument("--markdown", action="store_true",
                         help="render the full closure matrix instead of the JSON summary")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        with open(args.rows, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"NOT_AVAILABLE: could not read --rows file: {exc}", file=sys.stderr)
        return 2

    if isinstance(data, dict) and "rows" in data:
        records = data["rows"]
    elif isinstance(data, list):
        records = data
    else:
        print('NOT_AVAILABLE: --rows file must be a JSON list or {"rows": [...]}', file=sys.stderr)
        return 2

    try:
        rows = rows_from_json(records)
    except (KeyError, ValueError) as exc:
        print(f"NOT_AVAILABLE: {exc}", file=sys.stderr)
        return 2

    if args.markdown:
        print(render_closure_matrix(rows))
        coverage = compute_coverage(rows)
    else:
        coverage = compute_coverage(rows)
        gap_queue = build_gap_queue(rows)
        print(json.dumps({
            "total_requirements": coverage.total_requirements,
            "passing_requirements": coverage.passing_requirements,
            "coverage_percent": coverage.coverage_percent,
            "by_status": coverage.by_status,
            "gap_queue_sizes": {p.value: sum(r.requirement_count() for r in rs) for p, rs in gap_queue.items()},
        }, indent=2))

    return 0 if coverage.coverage_percent >= 100.0 else 1


def main(argv: list[str] | None = None) -> None:
    import sys
    sys.exit(execute_verb(argv))


if __name__ == "__main__":
    main()
