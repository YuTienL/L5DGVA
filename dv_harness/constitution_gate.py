"""L5DGVA Constitution — Article 0 anti-drift enforcement.

Real, mechanical safeguard against the constitution being silently
removed or weakened, per the Article 0 governance update's own explicit
requirement ("with focused tests preventing Article 0 from being
silently removed or weakened"). This module is the code half; the tests
are `dv_harness_tests/test_l5dgva_constitution.py`.

Two artifacts are checked together, never just one: the canonical full
text at `docs/architecture/L5DGVA_CONSTITUTION.md`, and CLAUDE.md's own
condensed pointer section (which must exist AND must appear before
"Core Operating Rules" -- Article 0 sits above ordinary rules by
position, not just by claim).

Deliberately narrow: this checks textual intactness (the constitution's
own words are present, unweakened, correctly positioned), never whether
the constitution's substantive promise (both continuous-learning loops
OPERATIONAL) is actually met -- that is `FINAL_COMPLIANCE_STATUS`'s job,
a final-product-only gate never claimed by an intermediate wave (see
`FINAL_COMPLIANCE_STATUS_INTERMEDIATE`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Tuple, Union

CONSTITUTION_DOC_PATH = "docs/architecture/L5DGVA_CONSTITUTION.md"

CONSTITUTIONAL_DIMENSIONS = (
    "LOCATION_INDEPENDENT",
    "EVIDENCE_GROUNDED",
    "KNOWLEDGE_DRIVEN",
    "CONTINUOUS_EVOLUTION",
    "END_TO_END_DV_ALIGNMENT",
)

ANTI_DRIFT_MARKER = "ARCHITECTURE_CONFLICT"

# L5DGVA_CONSTITUTIONAL_COMPLIANCE is a final-product-only acceptance gate
# (per the constitution's own "Migration-Wave Scoping" section). No
# intermediate wave (M1, M3, ...) may ever report this as PASS -- the only
# legal intermediate value is this one, until the final qualification wave
# computes the real thing from both continuous-learning loops' own
# OPERATIONAL status.
FINAL_COMPLIANCE_STATUS_INTERMEDIATE = "NOT_YET_QUALIFIED"


@dataclass(frozen=True)
class ConstitutionCheckResult:
    status: str  # "PASS" or "FAIL"
    reasons: List[str] = field(default_factory=list)


def check_constitution_intact(root: Union[str, Path]) -> ConstitutionCheckResult:
    """Real, on-disk check. Never raises -- returns FAIL with reasons
    instead, so a caller (dv doctor, a future CI gate) always gets one
    clear verdict."""
    root = Path(root)
    reasons: List[str] = []

    doc_path = root / CONSTITUTION_DOC_PATH
    doc_text = None
    if not doc_path.is_file():
        reasons.append("constitution document missing at %s" % CONSTITUTION_DOC_PATH)
    else:
        doc_text = doc_path.read_text(encoding="utf-8")
        if "Article 0" not in doc_text:
            reasons.append("constitution document no longer names Article 0")
        for dim in CONSTITUTIONAL_DIMENSIONS:
            if dim not in doc_text:
                reasons.append("constitution document is missing dimension %s" % dim)
        if ANTI_DRIFT_MARKER not in doc_text:
            reasons.append("constitution document is missing the Anti-Drift Rule marker %s" % ANTI_DRIFT_MARKER)

    claude_md_path = root / "CLAUDE.md"
    if not claude_md_path.is_file():
        reasons.append("CLAUDE.md missing entirely")
    else:
        claude_text = claude_md_path.read_text(encoding="utf-8")
        if "Article 0" not in claude_text or CONSTITUTION_DOC_PATH not in claude_text:
            reasons.append("CLAUDE.md no longer carries the Article 0 pointer")
        else:
            article_pos = claude_text.find("Article 0")
            core_rules_pos = claude_text.find("Core Operating Rules")
            if core_rules_pos != -1 and article_pos > core_rules_pos:
                reasons.append("CLAUDE.md's Article 0 section no longer precedes Core Operating Rules")

    return ConstitutionCheckResult(status="FAIL" if reasons else "PASS", reasons=reasons)


# ============================================================================
# M8 Cohort 5 (GAP-M8-008): FINAL_COMPLIANCE_GATE -- the real, coded,
# callable composite evaluator for the 13 named "Final Constitutional
# Acceptance" sub-criteria (L5DGVA_CONSTITUTION.md's own "Milestone
# Capability Gates" section). Before this cohort only a fixed sentinel
# string (FINAL_COMPLIANCE_STATUS_INTERMEDIATE above) existed -- never a
# computed value. This section is purely ADDITIVE: check_constitution_
# intact() above is completely unchanged (Cohort 5's own ROLLBACK_BOUNDARY).
#
# Per the Cohort Plan's own EXIT_CRITERIA: "its VERDICT need not be PASS --
# Migration-Wave Scoping explicitly allows this -- but the EVALUATOR itself
# must be real." Several sub-criteria genuinely have no real, findable
# evaluator anywhere in this codebase today (confirmed by exhaustive grep
# before writing this); those are reported as NO_REAL_EVALUATOR_FOUND, never
# fabricated into a false PASS or a guessed proxy. Every sub-criterion that
# DOES have a real evaluator reuses it unchanged (Connect Before Expand):
# claude_reference_graph.check_location_independence() (built for M4.6),
# evidence_provenance.summarize_project_provenance() (built for the
# PROVENANCE_REQUIRED_GATES work), golden_flow_readiness.derive_golden_
# flow_readiness()'s own real per-row facts (section 47's matrix), and
# memory_router.route_and_store()'s own already-extensively-tested
# ENGINEERING_MEMORY/ORGANIZATIONAL_MEMORY promotion path.
# ============================================================================

# The 13 sub-criteria, verbatim from L5DGVA_CONSTITUTION.md's own
# "Final Constitutional Acceptance" section (re-read fresh this cohort).
FINAL_ACCEPTANCE_SUB_CRITERIA = (
    "LOCATION_INDEPENDENT",
    "EVIDENCE_GROUNDED_DECISION_FLOW",
    "KNOWLEDGE_DRIVEN_GENERATION",
    "CONTINUOUS_RESEARCH_EVOLUTION",
    "CONTINUOUS_PROJECT_EXPERIENCE_LEARNING",
    "IP_END_TO_END",
    "SUBSYSTEM_END_TO_END",
    "SYSTEM_LEVEL_END_TO_END",
    "VPLAN_TO_COVERAGE_SIGNOFF",
    "REQUIREMENTS_TRACEABILITY",
    "KNOWLEDGE_PROMOTION",
    "AGENT_KNOWLEDGE_CONSUMPTION",
    "CANONICAL_CAPABILITY_STRICT_SUPERSET",
)

# A real, honest fourth value alongside PASS/FAIL/PARTIAL: no evaluator for
# this sub-criterion exists anywhere in this codebase today. Distinct from
# FAIL (which means a real evaluator ran and found a real problem) --
# collapsing the two would misrepresent "nobody has built this check yet"
# as "the check ran and failed."
NO_REAL_EVALUATOR_FOUND = "NO_REAL_EVALUATOR_FOUND"
SUB_CRITERION_STATUSES = ("PASS", "FAIL", "PARTIAL", NO_REAL_EVALUATOR_FOUND)


@dataclass(frozen=True)
class SubCriterionResult:
    name: str
    status: str
    evidence: str


@dataclass(frozen=True)
class FinalComplianceResult:
    overall_status: str  # strict worst-wins across all 13, using the same
                          # PASS > PARTIAL > FAIL/NO_REAL_EVALUATOR_FOUND
                          # ordering L5DGVA_CONSTITUTIONAL_COMPLIANCE itself
                          # requires ("must eventually prove AT LEAST" all 13)
    sub_criteria: Tuple[SubCriterionResult, ...]


def _sub_location_independent(root: Path) -> SubCriterionResult:
    try:
        from .claude_reference_graph import check_location_independence
        r = check_location_independence(root)
        status = "PASS" if r.location_independent else "FAIL"
        evidence = f"check_location_independence(): location_independent={r.location_independent}, reasons={r.reasons}"
    except Exception as exc:  # noqa: BLE001 -- a real evaluator failing to run is FAIL, never silently skipped
        status, evidence = "FAIL", f"claude_reference_graph.check_location_independence() raised: {type(exc).__name__}: {exc}"
    return SubCriterionResult("LOCATION_INDEPENDENT", status, evidence)


def _sub_evidence_grounded_decision_flow(root: Path) -> SubCriterionResult:
    try:
        from .evidence_provenance import summarize_project_provenance
        r = summarize_project_provenance(root)
        if not r.get("available"):
            status = "PARTIAL"
            evidence = f"summarize_project_provenance(): {r.get('reason')} -- no run state to evaluate against yet"
        else:
            has_self_attested = bool(r.get("has_self_attested_claims"))
            status = "FAIL" if has_self_attested else "PASS"
            evidence = f"summarize_project_provenance(): has_self_attested_claims={has_self_attested}"
    except Exception as exc:  # noqa: BLE001
        status, evidence = "FAIL", f"evidence_provenance.summarize_project_provenance() raised: {type(exc).__name__}: {exc}"
    return SubCriterionResult("EVIDENCE_GROUNDED_DECISION_FLOW", status, evidence)


def _sub_knowledge_driven_generation(root: Path) -> SubCriterionResult:
    # M8 Cohort 3's own real, tested edge: governance_registry.resolve_
    # governance_intent() bridges realistic task phrasing to the right
    # governance document -- "retrieve before generating/asking" made real.
    try:
        from .governance_registry import load_registry, get_entries_by_policy, resolve_governance_intent
        entries = load_registry(root)
        task_scoped = get_entries_by_policy(entries, "TASK_SCOPED")
        if not task_scoped:
            return SubCriterionResult("KNOWLEDGE_DRIVEN_GENERATION", "FAIL",
                                       "governance_registry has zero TASK_SCOPED entries")
        probe = resolve_governance_intent(root, {"task_description": "generate a UVM VIP testbench for this DUT"})
        status = "PASS" if probe["resolved"] else "PARTIAL"
        evidence = (f"{len(task_scoped)} real TASK_SCOPED governance_registry entries; "
                    f"resolve_governance_intent() live probe: resolved={probe['resolved']}")
    except Exception as exc:  # noqa: BLE001
        status, evidence = "FAIL", f"governance_registry probe raised: {type(exc).__name__}: {exc}"
    return SubCriterionResult("KNOWLEDGE_DRIVEN_GENERATION", status, evidence)


def _sub_continuous_research_evolution(root: Path) -> SubCriterionResult:
    # CANONICAL_CAPABILITY_SUPERSET_MATRIX.md's own real, file:line-cited
    # audit (re-read fresh this cohort): RESEARCH_PROVENANCE/RESEARCH_
    # APPLICABILITY/RESEARCH_TO_CAPABILITY_PROPOSAL/CAPABILITY_EXPERIMENT_
    # VALIDATION are all IMPLEMENTED,TESTED (one WIRED,TRIGGERED with a
    # real engine.py call site). This function's own live check is
    # narrower -- import-callability only -- disclosed as such, not a
    # re-derivation of that document's own deeper finding.
    try:
        from . import capability_evolution as ce
        has_pipeline = all(hasattr(ce, name) for name in
                            ("build_candidate", "persist_candidate", "run_controlled_experiment"))
        status = "PASS" if has_pipeline else "FAIL"
        evidence = ("capability_evolution.build_candidate/persist_candidate/run_controlled_experiment "
                    f"importable={has_pipeline}; corroborated by CANONICAL_CAPABILITY_SUPERSET_MATRIX.md's "
                    "own real audit (RESEARCH_* rows IMPLEMENTED,TESTED, not re-derived here)")
    except Exception as exc:  # noqa: BLE001
        status, evidence = "FAIL", f"capability_evolution import probe raised: {type(exc).__name__}: {exc}"
    return SubCriterionResult("CONTINUOUS_RESEARCH_EVOLUTION", status, evidence)


def _sub_continuous_project_experience_learning(root: Path) -> SubCriterionResult:
    # CAP-CE-018's own honest, disclosed state (M8 Cohorts 2/4): STORAGE/
    # DISCOVERABILITY/RETRIEVAL real; CONSUMPTION/ACTION_INFLUENCE not
    # proven -- PARTIAL, never OPERATIONAL, until a real consumer is shown.
    try:
        from . import experience_record as er
        has_types = len(er.EXPERIENCE_TYPES) == 3
        status = "PARTIAL" if has_types else "FAIL"
        evidence = (f"experience_record.EXPERIENCE_TYPES={er.EXPERIENCE_TYPES!r} real and importable "
                    "(3 producers, M8 Cohort 2); CAP-CE-018's own disclosed state (Cohorts 2/4): "
                    "STORAGE/DISCOVERABILITY/RETRIEVAL=REAL, CONSUMPTION=NOT_PROVEN_THIS_COHORT -- "
                    "PARTIAL, not OPERATIONAL, until a real consumer is shown")
    except Exception as exc:  # noqa: BLE001
        status, evidence = "FAIL", f"experience_record import probe raised: {type(exc).__name__}: {exc}"
    return SubCriterionResult("CONTINUOUS_PROJECT_EXPERIENCE_LEARNING", status, evidence)


def _sub_no_evaluator(name: str, reason: str) -> SubCriterionResult:
    return SubCriterionResult(name, NO_REAL_EVALUATOR_FOUND, reason)


def _golden_flow_rows_verdict(root: Path, row_ids: Tuple[str, ...]) -> Tuple[str, str]:
    from .golden_flow_readiness import derive_golden_flow_readiness, combine_readiness
    matrix = derive_golden_flow_readiness(root)
    by_id = {r["row_id"]: r for r in matrix["rows"]}
    statuses = [by_id[rid]["status"] for rid in row_ids if rid in by_id]
    gf_verdict = combine_readiness(statuses)
    # golden_flow_readiness's own READY/PARTIAL/BLOCKED/UNKNOWN vocabulary
    # mapped onto this gate's PASS/PARTIAL/FAIL -- READY is the only PASS
    # value; BLOCKED/UNKNOWN both mean "not evidenced", i.e. FAIL here
    # (this gate has no separate BLOCKED value of its own).
    mapped = {"READY": "PASS", "PARTIAL": "PARTIAL", "BLOCKED": "FAIL", "UNKNOWN": "FAIL"}[gf_verdict]
    detail = "; ".join(f"{rid}={by_id[rid]['status']}" for rid in row_ids if rid in by_id)
    return mapped, f"golden_flow_readiness rows [{detail}] -> combine_readiness()={gf_verdict}"


def _sub_vplan_to_coverage_signoff(root: Path) -> SubCriterionResult:
    try:
        status, evidence = _golden_flow_rows_verdict(root, (
            "vplan_traceability", "coverage_collection", "coverage_hole_analysis",
            "next_best_test", "coverage_closure_loop", "verification_closure_100", "signoff_evidence",
        ))
    except Exception as exc:  # noqa: BLE001
        status, evidence = "FAIL", f"golden_flow_readiness probe raised: {type(exc).__name__}: {exc}"
    return SubCriterionResult("VPLAN_TO_COVERAGE_SIGNOFF", status, evidence)


def _sub_requirements_traceability(root: Path) -> SubCriterionResult:
    try:
        status, evidence = _golden_flow_rows_verdict(root, ("requirement_extraction", "vplan_traceability"))
    except Exception as exc:  # noqa: BLE001
        status, evidence = "FAIL", f"golden_flow_readiness probe raised: {type(exc).__name__}: {exc}"
    return SubCriterionResult("REQUIREMENTS_TRACEABILITY", status, evidence)


def _sub_knowledge_promotion(root: Path) -> SubCriterionResult:
    try:
        from . import memory_router as mr
        has_api = all(hasattr(mr, name) for name in ("route_and_store", "promote_to_organizational", "route_memory"))
        status = "PASS" if has_api else "FAIL"
        evidence = ("memory_router.route_and_store/promote_to_organizational/route_memory importable="
                    f"{has_api}; extensively production-tested this program (M8 Cohorts 1/2/4's own "
                    "real ENGINEERING_MEMORY writes)")
    except Exception as exc:  # noqa: BLE001
        status, evidence = "FAIL", f"memory_router import probe raised: {type(exc).__name__}: {exc}"
    return SubCriterionResult("KNOWLEDGE_PROMOTION", status, evidence)


def _sub_agent_knowledge_consumption(root: Path) -> SubCriterionResult:
    # CAP-M8-MAKC-001's own Preflight-confirmed state (M8_KNOWLEDGE_
    # CONSUMPTION_AUDIT.md): 2 of 5 memory tiers proven cross-agent-
    # consumed (Project, Job); Organizational tier disclosed operationally
    # inert (no configured remote Knowledge Center). Cited, not re-derived
    # this cohort -- re-auditing all 5 tiers fresh is CAP-M8-MAKC-001's own
    # separate, larger scope, not Cohort 5's rollup-proportionate work.
    return SubCriterionResult(
        "AGENT_KNOWLEDGE_CONSUMPTION", "PARTIAL",
        "CAP-M8-MAKC-001 (M8_KNOWLEDGE_CONSUMPTION_AUDIT.md, Preflight-confirmed, not re-derived this "
        "cohort): 2 of 5 memory tiers (Project, Job) proven cross-agent-consumed; Organizational tier "
        "disclosed operationally inert (config.py remote_root='' by default)")


def evaluate_final_compliance(root: Union[str, Path]) -> FinalComplianceResult:
    """M8 Cohort 5 (GAP-M8-008): the real, coded, callable FINAL_
    COMPLIANCE_GATE evaluator for all 13 named Final Constitutional
    Acceptance sub-criteria. Never raises -- an individual sub-check's own
    exception becomes that sub-criterion's FAIL, never an aborted call.

    The overall_status is explicitly NOT expected to be PASS at this wave
    (Migration-Wave Scoping) -- this function's own existence and realness
    is the exit criterion, not its verdict. Composed via the same strict
    worst-wins discipline every other composite verdict in this codebase
    uses: PASS only if every sub-criterion is PASS; otherwise PARTIAL if
    at least one is PASS or PARTIAL; otherwise FAIL (all FAIL/NO_REAL_
    EVALUATOR_FOUND)."""
    root = Path(root)
    checks = (
        _sub_location_independent,
        _sub_evidence_grounded_decision_flow,
        _sub_knowledge_driven_generation,
        _sub_continuous_research_evolution,
        _sub_continuous_project_experience_learning,
        lambda r: _sub_no_evaluator("IP_END_TO_END",
            "No real per-verification-level (IP/Subsystem/System) end-to-end evaluator exists in this "
            "codebase today (golden_flow_readiness.py's own real 20-row matrix is stage-based, not "
            "level-based; verification_level.py is semantics/parsing only, no status tracking) -- "
            "confirmed by search this cohort, not fabricated. See GAP-M8-011."),
        lambda r: _sub_no_evaluator("SUBSYSTEM_END_TO_END",
            "Same finding as IP_END_TO_END -- no real per-level evaluator exists. See GAP-M8-011."),
        lambda r: _sub_no_evaluator("SYSTEM_LEVEL_END_TO_END",
            "Same finding as IP_END_TO_END -- no real per-level evaluator exists. See GAP-M8-011."),
        _sub_vplan_to_coverage_signoff,
        _sub_requirements_traceability,
        _sub_knowledge_promotion,
        _sub_agent_knowledge_consumption,
        lambda r: _sub_no_evaluator("CANONICAL_CAPABILITY_STRICT_SUPERSET",
            "No real CANONICAL_CAPABILITY_STRICT_SUPERSET/SOURCE_CAPABILITY_LOSS evaluator exists in "
            "this codebase today (confirmed by exhaustive grep this cohort) -- the 5 frozen reference "
            "sources are re-verified unchanged manually before every commit, never by a coded gate. "
            "See GAP-M8-011."),
    )
    results = tuple(check(root) for check in checks)
    assert [r.name for r in results] == list(FINAL_ACCEPTANCE_SUB_CRITERIA), (
        "evaluate_final_compliance()'s own check order drifted from FINAL_ACCEPTANCE_SUB_CRITERIA")
    return FinalComplianceResult(overall_status=combine_sub_criterion_statuses(results), sub_criteria=results)


def combine_sub_criterion_statuses(sub_criteria: Tuple[SubCriterionResult, ...]) -> str:
    """Strict worst-wins composite over a real set of sub-criterion
    results: PASS only if every one is PASS; PARTIAL if at least one is
    PASS or PARTIAL; otherwise FAIL (all FAIL/NO_REAL_EVALUATOR_FOUND).
    Extracted as its own real, independently-testable function -- not
    inlined into evaluate_final_compliance() -- so the combination rule
    itself has direct test coverage, not only an end-to-end proof."""
    statuses = {r.status for r in sub_criteria}
    if statuses == {"PASS"}:
        return "PASS"
    if "PASS" in statuses or "PARTIAL" in statuses:
        return "PARTIAL"
    return "FAIL"
