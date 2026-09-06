"""dv_harness/subsystem_practicality_score.py -- a 10-dimension weighted
maturity ROLLUP over signals this harness already produces.

THE GAP THIS CLOSES
--------------------
This project has at least four real per-domain readiness/quality readers
(`generation_readiness.py`'s twenty capability rows, `golden_flow_readiness.py`'s
twenty stage rows, `loop_convergence.py`'s convergence/plateau/oscillation
classifier, `confidence_calibration.py`'s tier-reliability report, plus
`coverage_analysis.py`'s hole/percent analysis) and no single number that answers
"how practically mature is this subsystem's verification environment, across
all of that, right now". Two people reading the same project's dashboard could
each hand-average a different subset of those signals and report a different
maturity claim. `grep -rni "practicality_score|maturity.*rollup|subsystem.*maturity"
--include=*.py .` matched nothing repo-wide before this module.

This module is the rollup, and it is DELIBERATELY THIN: it computes nothing a
real producer has not already computed. Every one of its 10 dimensions reads
the ALREADY-DERIVED verdict of one existing module (never raw evidence, never
a second parse of a coverage/DUT/VIP file) and maps that verdict onto a 0-100
maturity score through one fixed, documented rule.

THE WEIGHT=0 RULE (the actual point of this module)
----------------------------------------------------
A weighted average that silently treats a dimension nobody could measure as a
0 (an unearned FAIL) or a 100 (an unearned PASS) is fabricated precision --
exactly what the Evidence Truth Rule forbids. So a dimension whose real
producer reports absence (`generation_readiness`/`golden_flow_readiness`'s own
UNKNOWN, `loop_convergence`'s UNKNOWN-with-no-series,
`confidence_calibration`'s NOT_AVAILABLE/INSUFFICIENT_HISTORY, or an unreadable/
absent coverage summary) is marked NOT RESOLVABLE: its declared weight drops to
0 for THIS report, its score stays `None` (never defaulted), and the real
reason the underlying producer gave is carried through verbatim. The overall
score is then a weighted average over only the RESOLVABLE dimensions,
renormalized to their own weight -- and `measured_weight_percent` reports, next
to it and never folded into it, how much of the declared 100% that
renormalization actually covers. A 100/100 score measured over 10% of the
declared weight is not the same claim as a 100/100 measured over all of it, and
this report never lets the two look alike.

WHAT EACH DIMENSION REUSES
---------------------------
  spec_correctness (10%)          -- generation_readiness row 'spec_parsing_requirement_ir'
  dut_discovery (10%)              -- generation_readiness row 'dut_discovery'
  vip_mapping (10%)                -- generation_readiness row 'protocol_vip_mapping'
  uvm_generation_quality (10%)     -- generation_readiness row 'uvm_architecture'
  single_test_proof (10%)          -- golden_flow_readiness row 'single_test_proof'
  regression_reliability (10%)     -- golden_flow_readiness row 'lsf_regression'
  failure_closure (10%)            -- loop_convergence.classify_loop_convergence()'s verdict
  coverage_protocol_closure (15%)  -- coverage_analysis's own categories/holes, read through
                                       the same `dashboard._read_coverage_state()` reader
                                       `golden_flow_readiness.py`'s coverage rows already use
  traceability_evidence_reproducibility (10%) -- confidence_calibration.calibrate()
  usability (5%)                   -- golden_flow_readiness rows 'dashboard' +
                                       'claude_cli_integration', combined through that
                                       module's OWN `combine_readiness()`

Nothing here re-derives a fact any of those five modules already computes; every
dimension's `fact_source` names the real reader it calls, and
`assert_fact_sources_resolvable()` (run at test time) resolves every one of them
through the import system, the same anti-drift check
`generation_readiness.py`/`golden_flow_readiness.py` already run on their own rows.

WHAT THIS MODULE IS NOT
-------------------------
It RUNS no stage, invokes no gate, starts no build/regression/LSF job, and
writes no state or governance record of its own -- every function here is a
read (`derive_subsystem_practicality_score()`, `execute_verb()`,
`render_practicality_matrix()`) over reports that are themselves read-only
rollups. It APPROVES and ARBITRATES nothing: `ControlPlane.approve()`,
`policy.can_signoff()`, `assert_human_approval()`,
`HumanApprovalRequiredError`, `ProductionWriteNotAuthorizedError` and the
PR-only main/master governance are untouched and uncalled from here. There is
deliberately no stage gate: a gate that passed on a maturity SCORE nobody
reviewed would be worse than none.

Disclosed rather than hidden: one rolled-up producer,
`golden_flow_readiness.derive_golden_flow_readiness()`, materializes a default
`.dv-harness/config.json`/`control.json` the first time it runs over a project
that already has `state.json` but no `config.json` yet -- a pre-existing
behavior of that module (its own test suite tolerates it the same way, by
asserting no PRE-EXISTING file is modified rather than that no file ever
appears) which this module inherits rather than introduces, and does not
attempt to fix here per this project's scope-discipline rule.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import subsystem_discovery as sd

SCHEMA_VERSION = "1.0"

#: READY / PARTIAL / BLOCKED / UNKNOWN -- reused verbatim from
#: `subsystem_discovery.py`, the same vocabulary `generation_readiness.py` and
#: `golden_flow_readiness.py` already borrow rather than re-mint.
READY = sd.READY
PARTIAL = sd.PARTIAL
BLOCKED = sd.BLOCKED
UNKNOWN = sd.UNKNOWN

#: Rendered in any cell whose real source supplied nothing.
NONE_CELL = "-"

#: The fixed READY/PARTIAL/BLOCKED -> maturity-score mapping. UNKNOWN is
#: DELIBERATELY absent: it cannot be mapped onto a number honestly (it means
#: "no project evidence", not "bad" or "good"), so a dimension resolving to it
#: is NOT RESOLVABLE rather than scored 0.
STATUS_TO_SCORE: Dict[str, float] = {READY: 100.0, PARTIAL: 50.0, BLOCKED: 0.0}

#: `loop_convergence.py`'s section-88 verdict vocabulary mapped onto the same
#: 0-100 scale. SLOW_CONVERGENCE scores below CONVERGING but well above
#: PLATEAU/NO_PROGRESS -- it IS forward progress, slowly, the same reasoning
#: that module's own `VERDICT_TO_LOOP_STATE` applies. REGRESSION and
#: OSCILLATING both score 0: a loop that is actively undoing its own progress
#: is not a partially-mature failure-closure story, it is a live one. UNKNOWN is
#: deliberately absent for the same reason it is absent from STATUS_TO_SCORE.
CONVERGENCE_VERDICT_TO_SCORE: Dict[str, float] = {
    "CONVERGING": 100.0,
    "SLOW_CONVERGENCE": 70.0,
    "PLATEAU": 25.0,
    "NO_PROGRESS": 25.0,
    "REGRESSION": 0.0,
    "OSCILLATING": 0.0,
}

#: A dimension's declared weight only counts toward `measured_weight_percent`
#: once a real signal was resolvable; below this bar an overall maturity
#: LABEL is refused (INSUFFICIENT_MEASUREMENT) even though the renormalized
#: score is still reported, because a score computed over less than half the
#: declared weight is not a claim about the SUBSYSTEM's practicality, it is
#: mostly a claim about which producers happened to have output on disk.
MIN_MEASURED_WEIGHT_PERCENT_FOR_VERDICT = 50.0

MATURITY_HIGH = "HIGH_MATURITY"
MATURITY_MODERATE = "MODERATE_MATURITY"
MATURITY_LOW = "LOW_MATURITY"
MATURITY_INSUFFICIENT = "INSUFFICIENT_MEASUREMENT"


class SubsystemPracticalityScoreError(ValueError):
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# ===========================================================================
# Dimension declarations
# ===========================================================================

@dataclass(frozen=True)
class DimensionSpec:
    """One of the 10 declared dimensions.

    `fact_source` names the real reader(s) this dimension's resolver calls, so
    `assert_fact_sources_resolvable()` can prove every dimension is backed by
    code that still exists -- the same anti-drift discipline
    `generation_readiness.assert_fact_sources_resolvable()` and
    `golden_flow_readiness.assert_fact_sources_resolvable()` already apply to
    their own rows.
    """
    dimension_id: str
    label: str
    weight_percent: float
    fact_source: Tuple[str, ...]
    basis: str


DIMENSIONS: Tuple[DimensionSpec, ...] = (
    DimensionSpec(
        "spec_correctness", "Spec Correctness", 10.0,
        ("dv_harness.generation_readiness.derive_generation_readiness",),
        "generation_readiness.py row 'spec_parsing_requirement_ir': whether a real "
        "requirement contract set exists and, if it does, its analyzer-derived "
        "COMPLETE/AMBIGUOUS/CONTRADICTORY status."),
    DimensionSpec(
        "dut_discovery", "DUT Discovery", 10.0,
        ("dv_harness.generation_readiness.derive_generation_readiness",),
        "generation_readiness.py row 'dut_discovery': env.manifest.json's own "
        "dut_facts.rtl layer status, a real verible parse of the current RTL."),
    DimensionSpec(
        "vip_mapping", "VIP Mapping", 10.0,
        ("dv_harness.generation_readiness.derive_generation_readiness",),
        "generation_readiness.py row 'protocol_vip_mapping': protocol_capability.py's "
        "real, import-derived capability_status per declared protocol."),
    DimensionSpec(
        "uvm_generation_quality", "UVM Generation Quality", 10.0,
        ("dv_harness.generation_readiness.derive_generation_readiness",),
        "generation_readiness.py row 'uvm_architecture': a working verible parser plus "
        "env.manifest.json's env_topology.component_hierarchy -- whether generated UVM "
        "can be structurally checked and whether a real component tree was captured."),
    DimensionSpec(
        "single_test_proof", "Single-Test Proof", 10.0,
        ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",),
        "golden_flow_readiness.py row 'single_test_proof': the real BUILD+VERIFY stage "
        "pair -- compiled AND one test really passed with a command.txt<->sim.log "
        "semantic check."),
    DimensionSpec(
        "regression_reliability", "Regression Reliability", 10.0,
        ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",),
        "golden_flow_readiness.py row 'lsf_regression': the real per-job dv_analysis_status "
        "GET /api/lsf summarises -- LSF DONE is not DV PASS, so this reads the analysed "
        "verdict, never the scheduler status."),
    DimensionSpec(
        "failure_closure", "Failure Closure", 10.0,
        ("dv_harness.loop_convergence.classify_loop_convergence",),
        "loop_convergence.py's section 88-90 verdict over the real coverage-percent "
        "series and the real debug_loop_history/regression_verdict_history fingerprints -- "
        "CONVERGING/SLOW_CONVERGENCE reads as real closure progress; PLATEAU/NO_PROGRESS/"
        "REGRESSION/OSCILLATING reads as a loop that is not closing."),
    DimensionSpec(
        "coverage_protocol_closure", "Coverage / Protocol Closure", 15.0,
        ("dv_harness.dashboard._read_coverage_state", "dv_harness.coverage_analysis.identify_holes"),
        "coverage_analysis.py's own parsed categories, read through the same "
        "dashboard._read_coverage_state() reader golden_flow_readiness.py's coverage rows "
        "already use -- a bins-weighted percent across every real category, never a "
        "second parse of the summary file."),
    DimensionSpec(
        "traceability_evidence_reproducibility", "Traceability / Evidence / Reproducibility", 10.0,
        ("dv_harness.confidence_calibration.calibrate",),
        "confidence_calibration.py's own calibration report: does this project's real "
        "Memory-record track record hold the CONFIRMED > HIGH > MEDIUM > LOW ordering "
        "this harness acts on."),
    DimensionSpec(
        "usability", "Usability", 5.0,
        ("dv_harness.golden_flow_readiness.derive_golden_flow_readiness",),
        "golden_flow_readiness.py rows 'dashboard' and 'claude_cli_integration', combined "
        "through that module's own combine_readiness() -- whether an operator has a real "
        "working GUI and a real resolvable CLI adapter to interact with this project."),
)

_DECLARED_WEIGHT_TOTAL = sum(d.weight_percent for d in DIMENSIONS)


def _assert_weights_sum_to_100() -> None:
    if abs(_DECLARED_WEIGHT_TOTAL - 100.0) > 1e-9:
        raise SubsystemPracticalityScoreError("DIMENSION_WEIGHTS_DO_NOT_SUM_TO_100", {
            "total": _DECLARED_WEIGHT_TOTAL,
            "weights": {d.dimension_id: d.weight_percent for d in DIMENSIONS}})


def _assert_dimension_ids_unique() -> None:
    ids = [d.dimension_id for d in DIMENSIONS]
    if len(set(ids)) != len(ids):
        raise SubsystemPracticalityScoreError("DUPLICATE_DIMENSION_ID", {"dimension_ids": ids})


_assert_weights_sum_to_100()
_assert_dimension_ids_unique()


def dimension_ids() -> List[str]:
    return [d.dimension_id for d in DIMENSIONS]


def _resolve_dotted(dotted: str):
    """Resolve `pkg.mod.attr` through the import system. Same small pattern
    `generation_readiness._resolve_dotted()` and
    `golden_flow_readiness._resolve_dotted()` already carry, each scoped to its
    own module's error class rather than shared through a public utility --
    a third copy of a ~15-line resolver is the established precedent here, not
    a new one."""
    import importlib
    parts = dotted.split(".")
    obj = None
    rest: List[str] = []
    for cut in range(len(parts), 1, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
        except Exception:
            continue
        rest = parts[cut:]
        break
    else:
        raise SubsystemPracticalityScoreError("FACT_SOURCE_MODULE_UNIMPORTABLE",
                                              {"fact_source": dotted})
    for name in rest:
        if not hasattr(obj, name):
            raise SubsystemPracticalityScoreError("FACT_SOURCE_ATTRIBUTE_MISSING", {
                "fact_source": dotted, "missing_attribute": name})
        obj = getattr(obj, name)
    return obj


def assert_fact_sources_resolvable() -> List[str]:
    """Every dimension's declared `fact_source` still resolves through the
    import system. The anti-drift check that makes this module's reuse claim
    checkable rather than asserted -- run at test time, mirroring
    `generation_readiness.assert_fact_sources_resolvable()`."""
    resolved: List[str] = []
    for spec in DIMENSIONS:
        for dotted in spec.fact_source:
            try:
                _resolve_dotted(dotted)
            except SubsystemPracticalityScoreError as exc:
                raise SubsystemPracticalityScoreError(
                    exc.reason, {**exc.detail, "dimension": spec.dimension_id}) from None
            resolved.append(dotted)
    return resolved


# ===========================================================================
# Gap -> Next-Best-Action catalog, driven through inference.next_best_action
# ===========================================================================

DIMENSION_GAP_ACTION_CATALOG: Dict[str, Any] = {
    "source": "subsystem_practicality_score_dimension",
    "fallback": (
        "no action is registered for dimension '{gap}' -- name the missing real evidence "
        "and the real command that would produce it before treating this dimension as "
        "measurable"
    ),
    "actions": {
        "spec_correctness": (
            "supply a real requirement contract set so generation_readiness.py's "
            "'Spec Parsing / Requirement IR' row has project evidence to read; see that "
            "row's own registered action"),
        "dut_discovery": (
            "run `dv-harness env-manifest generate --rtl-file <f> ...` so dut_facts.rtl "
            "is a real verible parse of the current RTL"),
        "vip_mapping": (
            "close the protocol's capability row via "
            "`python -m dv_harness.protocol_capability --sync` after building a real "
            "protocol-specific model"),
        "uvm_generation_quality": (
            "generate through the real entry point and read the uvm_structural_lint.json "
            "it writes; install a working verible if the lint reports NOT_AVAILABLE"),
        "single_test_proof": (
            "take a subsystem through BUILD and VERIFY to a real gate-validated single-test "
            "PASS -- neither compiling alone nor a claimed pass without a semantic check "
            "counts"),
        "regression_reliability": (
            "run `dv-harness lsf-watch-start` and let a real regression reconcile to a "
            "dv_analysis_status; an LSF DONE with no DV analysis is not evidence"),
        "failure_closure": (
            "populate a real coverage-percent history "
            "(`dashboard.append_coverage_history_sample()`) or a real "
            "regression_verdict_history so loop_convergence.py has a series to classify"),
        "coverage_protocol_closure": (
            "produce a real coverage-summary JSON at "
            ".dv-harness/coverage/summary.json so coverage_analysis.py has categories to "
            "parse"),
        "traceability_evidence_reproducibility": (
            "record real conclusions and real outcomes "
            "(MemoryGC.confirm()/retract()) so confidence_calibration.py has determinate "
            "history to calibrate against"),
        "usability": (
            "confirm the dashboard server starts (dashboard.serve) and the configured "
            "CLI adapter resolves (adapters.cli.ClaudeCLIAdapter._resolve_command)"),
    },
}


def _next_best_actions(root: Path, gaps: List[str]) -> Dict[str, str]:
    if not gaps:
        return {}
    from .inference import next_best_action
    results = next_best_action(None, gaps, root,
                               gap_action_catalog=DIMENSION_GAP_ACTION_CATALOG)
    return {r["gap"]: r["suggested_action"] for r in results}


# ===========================================================================
# Fact gathering -- every read below goes through an already-real reader,
# gathered once per report so no dimension's resolver invokes its module twice
# ===========================================================================

@dataclass
class _Facts:
    root: Path
    gen_matrix: Optional[Dict[str, Any]]
    gen_matrix_error: str
    gen_rows_by_id: Dict[str, Dict[str, Any]]
    gf_matrix: Optional[Dict[str, Any]]
    gf_matrix_error: str
    gf_rows_by_id: Dict[str, Dict[str, Any]]
    loop_report: Optional[Dict[str, Any]]
    loop_report_error: str
    calib_report: Optional[Dict[str, Any]]
    calib_report_error: str
    coverage_state: Optional[Dict[str, Any]]
    coverage_state_error: str


def _gather_facts(root: Path, cfg: Optional[Dict[str, Any]] = None,
                  *, deep: bool = False) -> _Facts:
    root = Path(root)

    gen_matrix = None
    gen_matrix_error = ""
    try:
        from . import generation_readiness as gr
        gen_matrix = gr.derive_generation_readiness(root, cfg, deep=deep)
    except Exception as exc:
        gen_matrix_error = f"generation_readiness failed: {type(exc).__name__}: {exc}"
    gen_rows_by_id = {r["row_id"]: r for r in (gen_matrix or {}).get("rows", [])}

    gf_matrix = None
    gf_matrix_error = ""
    try:
        from . import golden_flow_readiness as gf
        gf_matrix = gf.derive_golden_flow_readiness(root, cfg)
    except Exception as exc:
        gf_matrix_error = f"golden_flow_readiness failed: {type(exc).__name__}: {exc}"
    gf_rows_by_id = {r["row_id"]: r for r in (gf_matrix or {}).get("rows", [])}

    loop_report = None
    loop_report_error = ""
    try:
        from . import loop_convergence as lc
        loop_report = lc.classify_loop_convergence(root, cfg=cfg).to_dict()
    except Exception as exc:
        loop_report_error = f"loop_convergence failed: {type(exc).__name__}: {exc}"

    calib_report = None
    calib_report_error = ""
    try:
        from . import confidence_calibration as cc
        calib_report = cc.calibrate(root, cfg=cfg)
    except Exception as exc:
        calib_report_error = f"confidence_calibration failed: {type(exc).__name__}: {exc}"

    coverage_state = None
    coverage_state_error = ""
    try:
        from .dashboard import _read_coverage_state
        coverage_state = _read_coverage_state(root)
    except Exception as exc:
        coverage_state_error = f"coverage state reader failed: {type(exc).__name__}: {exc}"

    return _Facts(
        root=root,
        gen_matrix=gen_matrix, gen_matrix_error=gen_matrix_error, gen_rows_by_id=gen_rows_by_id,
        gf_matrix=gf_matrix, gf_matrix_error=gf_matrix_error, gf_rows_by_id=gf_rows_by_id,
        loop_report=loop_report, loop_report_error=loop_report_error,
        calib_report=calib_report, calib_report_error=calib_report_error,
        coverage_state=coverage_state, coverage_state_error=coverage_state_error,
    )


# ===========================================================================
# Per-dimension resolvers
# ===========================================================================
#
# Contract, held by every resolver below:
#   * returns {"resolvable", "status", "score", "evidence", "reason"};
#   * `resolvable=False` ALWAYS carries `score=None` -- never a defaulted 0/100;
#   * NEVER raises for a project with nothing on disk -- absence is a verdict,
#     not an error.

def _unresolved(status: str, reason: str, evidence: str = NONE_CELL) -> Dict[str, Any]:
    return {"resolvable": False, "status": status, "score": None,
            "evidence": evidence, "reason": reason}


def _resolved(status: str, score: float, evidence: str) -> Dict[str, Any]:
    return {"resolvable": True, "status": status, "score": score,
            "evidence": evidence, "reason": ""}


def _resolve_from_generation_row(facts: _Facts, row_id: str) -> Dict[str, Any]:
    if facts.gen_matrix is None:
        return _unresolved(UNKNOWN, facts.gen_matrix_error or
                           "generation_readiness matrix unavailable")
    row = facts.gen_rows_by_id.get(row_id)
    if row is None:
        return _unresolved(UNKNOWN, f"generation_readiness carries no row '{row_id}'")
    status = row.get("status")
    if status not in STATUS_TO_SCORE:
        return _unresolved(status or UNKNOWN,
                           row.get("gap") or
                           f"generation_readiness row '{row_id}' is {status}: no project "
                           f"evidence to score",
                           row.get("evidence") or NONE_CELL)
    return _resolved(status, STATUS_TO_SCORE[status], row.get("evidence") or NONE_CELL)


def _resolve_from_golden_flow_row(facts: _Facts, row_id: str) -> Dict[str, Any]:
    if facts.gf_matrix is None:
        return _unresolved(UNKNOWN, facts.gf_matrix_error or
                           "golden_flow_readiness matrix unavailable")
    row = facts.gf_rows_by_id.get(row_id)
    if row is None:
        return _unresolved(UNKNOWN, f"golden_flow_readiness carries no row '{row_id}'")
    status = row.get("status")
    if status not in STATUS_TO_SCORE:
        return _unresolved(status or UNKNOWN,
                           row.get("gap") or
                           f"golden_flow_readiness row '{row_id}' is {status}: no project "
                           f"evidence to score",
                           row.get("evidence") or NONE_CELL)
    return _resolved(status, STATUS_TO_SCORE[status], row.get("evidence") or NONE_CELL)


def _resolve_spec_correctness(facts: _Facts) -> Dict[str, Any]:
    return _resolve_from_generation_row(facts, "spec_parsing_requirement_ir")


def _resolve_dut_discovery(facts: _Facts) -> Dict[str, Any]:
    return _resolve_from_generation_row(facts, "dut_discovery")


def _resolve_vip_mapping(facts: _Facts) -> Dict[str, Any]:
    return _resolve_from_generation_row(facts, "protocol_vip_mapping")


def _resolve_uvm_generation_quality(facts: _Facts) -> Dict[str, Any]:
    return _resolve_from_generation_row(facts, "uvm_architecture")


def _resolve_single_test_proof(facts: _Facts) -> Dict[str, Any]:
    return _resolve_from_golden_flow_row(facts, "single_test_proof")


def _resolve_regression_reliability(facts: _Facts) -> Dict[str, Any]:
    return _resolve_from_golden_flow_row(facts, "lsf_regression")


def _resolve_failure_closure(facts: _Facts) -> Dict[str, Any]:
    report = facts.loop_report
    if report is None:
        return _unresolved(UNKNOWN, facts.loop_report_error or
                           "loop_convergence report unavailable")
    verdict = report.get("verdict")
    if not report.get("available") or verdict not in CONVERGENCE_VERDICT_TO_SCORE:
        return _unresolved(UNKNOWN,
                           report.get("reason") or
                           f"loop_convergence verdict is {verdict}: no usable evidence "
                           f"series")
    score = CONVERGENCE_VERDICT_TO_SCORE[verdict]
    return _resolved(verdict, score,
                     f"loop_convergence verdict={verdict} metric={report.get('metric')}")


def _resolve_coverage_protocol_closure(facts: _Facts) -> Dict[str, Any]:
    cov = facts.coverage_state
    if cov is None:
        return _unresolved(UNKNOWN, facts.coverage_state_error or
                           "coverage state unavailable")
    if not cov.get("available"):
        return _unresolved(UNKNOWN,
                           f"no real coverage summary at {cov.get('summary_path')}")
    if cov.get("error"):
        return _unresolved(UNKNOWN,
                           f"coverage summary is malformed: {cov['error'].get('reason')}")
    cats = cov.get("categories") or []
    if not cats:
        return _unresolved(UNKNOWN, "coverage summary parsed but holds no category")
    total_bins = sum(c["bins_total"] for c in cats)
    hit_bins = sum(c["bins_hit"] for c in cats)
    if total_bins <= 0:
        return _unresolved(UNKNOWN, "every coverage category declares zero bins_total")
    percent = 100.0 * hit_bins / total_bins
    holes = cov.get("holes") or []
    return _resolved(
        "MEASURED", percent,
        f"{len(cats)} categor{'y' if len(cats) == 1 else 'ies'}, weighted "
        f"{percent:.1f}% bins hit ({hit_bins}/{total_bins}), {len(holes)} hole(s) below "
        f"100%")


def _resolve_traceability_evidence_reproducibility(facts: _Facts) -> Dict[str, Any]:
    from . import confidence_calibration as cc
    report = facts.calib_report
    if report is None:
        return _unresolved(UNKNOWN, facts.calib_report_error or
                           "confidence_calibration report unavailable")
    status = report.get("status")
    if status == cc.STATUS_CALIBRATED:
        tiers = report.get("calibratable_tiers") or []
        return _resolved(status, 100.0,
                         f"{len(tiers)} calibratable tier(s); ordering holds and no "
                         f"declared floor is breached")
    if status == cc.STATUS_MISCALIBRATED:
        findings = report.get("findings") or []
        tiers = report.get("calibratable_tiers") or []
        return _resolved(status, 0.0,
                         f"{len(findings)} finding(s) over {len(tiers)} calibratable "
                         f"tier(s)")
    # NOT_AVAILABLE / INSUFFICIENT_HISTORY: a real, honest answer -- nothing to score.
    return _unresolved(status or UNKNOWN,
                       report.get("detail") or report.get("reason") or
                       "confidence_calibration has no determinate history to calibrate")


def _resolve_usability(facts: _Facts) -> Dict[str, Any]:
    if facts.gf_matrix is None:
        return _unresolved(UNKNOWN, facts.gf_matrix_error or
                           "golden_flow_readiness matrix unavailable")
    from . import golden_flow_readiness as gf
    dash = facts.gf_rows_by_id.get("dashboard")
    cli = facts.gf_rows_by_id.get("claude_cli_integration")
    if dash is None or cli is None:
        missing = [n for n, r in (("dashboard", dash), ("claude_cli_integration", cli))
                   if r is None]
        return _unresolved(UNKNOWN,
                           f"golden_flow_readiness carries no row(s): {', '.join(missing)}")
    status = gf.combine_readiness([dash.get("status"), cli.get("status")])
    if status not in STATUS_TO_SCORE:
        gaps = "; ".join(g for g in (dash.get("gap"), cli.get("gap"))
                         if g and g != NONE_CELL)
        return _unresolved(status,
                           gaps or "neither the dashboard nor the CLI adapter row carries "
                                   "usable project evidence")
    evidence = f"dashboard={dash.get('status')}, claude_cli={cli.get('status')}"
    return _resolved(status, STATUS_TO_SCORE[status], evidence)


RESOLVERS: Dict[str, Any] = {
    "spec_correctness": _resolve_spec_correctness,
    "dut_discovery": _resolve_dut_discovery,
    "vip_mapping": _resolve_vip_mapping,
    "uvm_generation_quality": _resolve_uvm_generation_quality,
    "single_test_proof": _resolve_single_test_proof,
    "regression_reliability": _resolve_regression_reliability,
    "failure_closure": _resolve_failure_closure,
    "coverage_protocol_closure": _resolve_coverage_protocol_closure,
    "traceability_evidence_reproducibility": _resolve_traceability_evidence_reproducibility,
    "usability": _resolve_usability,
}


def _assert_every_dimension_has_a_resolver() -> None:
    missing = [d.dimension_id for d in DIMENSIONS if d.dimension_id not in RESOLVERS]
    if missing:
        raise SubsystemPracticalityScoreError("DIMENSION_HAS_NO_RESOLVER",
                                              {"dimension_ids": missing})


_assert_every_dimension_has_a_resolver()


# ===========================================================================
# The rollup
# ===========================================================================

def derive_subsystem_practicality_score(root, cfg: Optional[Dict[str, Any]] = None,
                                        *, deep: bool = False) -> Dict[str, Any]:
    """The 10-dimension weighted maturity rollup for one real project root.

    Read-only and total: every declared dimension appears in the output,
    including dimensions whose real producer reported absence -- "this
    dimension is UNKNOWN" and "this dimension was omitted" must not look
    alike.

    `deep=False` (the default) skips `generation_readiness.py`'s expensive
    SYS-1..SYS-30 cross-subsystem chain, the same default/flag that module
    itself exposes -- a maturity rollup is not on any gate's clock but should
    not need a minute of cross-subsystem analysis just to report a score.
    """
    root = Path(root)
    facts = _gather_facts(root, cfg, deep=deep)

    dims: List[Dict[str, Any]] = []
    for spec in DIMENSIONS:
        try:
            resolved = RESOLVERS[spec.dimension_id](facts)
        except Exception as exc:  # a resolver bug must not delete a mandatory dimension
            resolved = _unresolved(UNKNOWN,
                                   f"resolver raised {type(exc).__name__}: {exc}")
        dims.append({
            "dimension_id": spec.dimension_id,
            "label": spec.label,
            "weight_declared_percent": spec.weight_percent,
            "weight_effective_percent": spec.weight_percent if resolved["resolvable"] else 0.0,
            "resolvable": resolved["resolvable"],
            "status": resolved["status"],
            "score": resolved["score"],
            "evidence": resolved["evidence"] or NONE_CELL,
            "reason": resolved["reason"] or NONE_CELL,
            "fact_source": list(spec.fact_source),
            "basis": spec.basis,
        })

    unresolved_ids = [d["dimension_id"] for d in dims if not d["resolvable"]]
    actions = _next_best_actions(root, unresolved_ids)
    for d in dims:
        d["next_best_action"] = actions.get(d["dimension_id"], NONE_CELL)

    measured_weight_percent = sum(d["weight_effective_percent"] for d in dims)
    if measured_weight_percent > 0:
        overall_score_over_measured = sum(
            d["score"] * d["weight_effective_percent"] for d in dims if d["resolvable"]
        ) / measured_weight_percent
    else:
        overall_score_over_measured = None

    if measured_weight_percent <= 0:
        maturity_status = MATURITY_INSUFFICIENT
    elif measured_weight_percent < MIN_MEASURED_WEIGHT_PERCENT_FOR_VERDICT:
        maturity_status = MATURITY_INSUFFICIENT
    elif overall_score_over_measured >= 80.0:
        maturity_status = MATURITY_HIGH
    elif overall_score_over_measured >= 50.0:
        maturity_status = MATURITY_MODERATE
    else:
        maturity_status = MATURITY_LOW

    blocked_resolvable = [d for d in dims if d["resolvable"] and d["score"] == 0.0]

    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "deep_analysis": deep,
        "dimensions": dims,
        "measured_weight_percent": measured_weight_percent,
        "unmeasured_weight_percent": 100.0 - measured_weight_percent,
        "overall_score_over_measured": overall_score_over_measured,
        "maturity_status": maturity_status,
        "min_measured_weight_percent_for_verdict": MIN_MEASURED_WEIGHT_PERCENT_FOR_VERDICT,
        "blocked_dimension_count": len(blocked_resolvable),
        "unresolved_dimension_count": len(unresolved_ids),
        "rule": (
            "overall_score_over_measured is a weighted average over ONLY the "
            "dimensions with a real, resolvable signal, renormalized to their own "
            "weight -- an unresolvable dimension's weight is 0 for this report, never "
            "defaulted into the score as 0 or 100. measured_weight_percent says how "
            "much of the declared 100% that renormalization actually covers, and is "
            "never folded into the score itself."),
        "authorizes": (
            "nothing. This is a read-only maturity rollup over other read-only "
            "reports; it runs no stage, invokes no gate, starts no build/regression/"
            "LSF job, and approves no promotion or production write."),
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_practicality_matrix(report: Mapping[str, Any]) -> str:
    """The per-dimension table, in the same shared-renderer style
    `generation_readiness.render_generation_matrix()` and
    `golden_flow_readiness.render_golden_flow_matrix()` already use."""
    from .connectivity import render_markdown_table
    columns = (
        ("label", "Dimension"), ("weight_declared_percent", "Weight %"),
        ("status", "Status"), ("score", "Score"), ("evidence", "Evidence"),
        ("reason", "Reason"), ("next_best_action", "Next-Best-Action"),
    )
    keys = [k for k, _ in columns]
    rows = []
    for d in report.get("dimensions") or ():
        row = {k: _cell(d.get(k, NONE_CELL)) for k in keys}
        row["score"] = _cell(f"{d['score']:.1f}" if d.get("score") is not None else NONE_CELL)
        rows.append(row)
    return render_markdown_table(
        list(columns), rows,
        empty_note="(no dimension was produced -- this is a bug: all 10 dimensions are "
                   "mandatory even when every one is unresolvable)")


def format_practicality_report(report: Mapping[str, Any]) -> str:
    """Human-readable form of `derive_subsystem_practicality_score()`'s payload."""
    score = report.get("overall_score_over_measured")
    score_text = f"{score:.1f}/100" if score is not None else "-- (nothing was measurable)"
    out = [
        "# SUBSYSTEM PRACTICALITY SCORE",
        "",
        f"**{report['maturity_status']}** -- {score_text}, measured over "
        f"{report['measured_weight_percent']:.1f}% of the declared 100% weight "
        f"({report['unmeasured_weight_percent']:.1f}% unresolvable).",
        "",
        f"Project root: `{report['root']}`  (generated {report['generated_at']})",
        "",
        render_practicality_matrix(report),
        "",
        report["rule"],
        "",
        f"This score authorizes: {report['authorizes']}",
    ]
    unresolved = [d for d in report.get("dimensions") or () if not d["resolvable"]]
    if unresolved:
        out += ["", "## Unresolvable dimensions (weight=0 for this report)", ""]
        out += [f"- **{d['label']}** ({d['weight_declared_percent']:.0f}% declared) -- "
                f"{d['reason']}" for d in unresolved]
    blocked = [d for d in report.get("dimensions") or ()
              if d["resolvable"] and d["score"] == 0.0]
    if blocked:
        out += ["", "## Blocked / zero-scored dimensions", ""]
        out += [f"- **{d['label']}** -- {d['evidence']}" for d in blocked]
    return "\n".join(out)


# ===========================================================================
# One shared entry point for `python -m dv_harness.subsystem_practicality_score`
# (and any future `dv-harness subsystem-practicality-score` CLI wrapper)
# ===========================================================================

def execute_verb(root, verb: str, *, as_json: bool = False,
                 cfg: Optional[Dict[str, Any]] = None,
                 deep: bool = False) -> Tuple[int, Any]:
    """One implementation shared by `python -m dv_harness.subsystem_practicality_score`
    and any future CLI front door -- the same `execute_verb()` convention
    `confidence_calibration`/`loop_contract`/`loop_budget`/`loop_telemetry` follow.

    Exit codes:
      0 -- clean: at least one dimension was measurable and no measured
           dimension scored 0 (BLOCKED-equivalent).
      1 -- a real finding: at least one dimension WAS resolvable and scored 0
           (a confirmed, not merely unmeasured, problem).
      2 -- nothing to report: no dimension was resolvable at all
           (measured_weight_percent == 0).
    """
    root = Path(root)
    if verb == "dimensions":
        return 0, {
            "dimension_ids": dimension_ids(),
            "weights": {d.dimension_id: d.weight_percent for d in DIMENSIONS},
            "fact_sources": {d.dimension_id: list(d.fact_source) for d in DIMENSIONS},
            "declared_weight_total": _DECLARED_WEIGHT_TOTAL,
        }
    if verb in ("report", "show"):
        report = derive_subsystem_practicality_score(root, cfg=cfg, deep=deep)
        if report["measured_weight_percent"] <= 0:
            code = 2
        elif report["blocked_dimension_count"] > 0:
            code = 1
        else:
            code = 0
        if verb == "show" and not as_json:
            return code, format_practicality_report(report)
        return code, report
    return 1, {"ok": False, "error": "UNKNOWN_VERB", "verb": verb,
               "known": ["dimensions", "report", "show"]}


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI shim
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(
        prog="python -m dv_harness.subsystem_practicality_score",
        description="A 10-dimension weighted maturity rollup over this project's own "
                    "generation_readiness/golden_flow_readiness/loop_convergence/"
                    "coverage_analysis/confidence_calibration reports. Reads only; runs "
                    "no stage.")
    ap.add_argument("verb", nargs="?", default="show",
                    choices=["dimensions", "report", "show"])
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--deep", action="store_true",
                    help="also run generation_readiness.py's expensive SYS-1..SYS-30 "
                         "cross-subsystem chain")
    args = ap.parse_args(argv)
    code, payload = execute_verb(Path(args.project_root), args.verb,
                                 as_json=args.as_json, deep=args.deep)
    print(payload if isinstance(payload, str)
          else _json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
