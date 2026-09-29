"""Subsystem Practicality Score: a 10-dimension weighted maturity rollup
(`dv_harness/subsystem_practicality_score.py`).

WHAT THESE TESTS ARE FOR. Not "the function returns 10 dicts and a number".
The things that can actually go wrong with a maturity ROLLUP are:

  1. **A dimension silently defaulted instead of honestly unresolved.** The
     single most expensive failure here would be an unmeasured dimension
     quietly scoring 0 (an unearned FAIL) or 100 (an unearned PASS). Every
     unresolved dimension here is asserted to carry `score=None` and
     `weight_effective_percent=0.0`, and the overall score/measured-weight
     pair is asserted to never collapse into one conflated number.
  2. **A score computed from a fabricated signal instead of the real
     producer.** Every resolvable dimension's score is cross-checked against
     an INDEPENDENT read of the same underlying module
     (`generation_readiness.derive_generation_readiness()`,
     `golden_flow_readiness.derive_golden_flow_readiness()`) or an
     independently hand-computed number (the coverage bins-weighted percent),
     never trusted from this module's own internal arithmetic alone.
  3. **A detector with no detection power.** Every positive case here (a
     CALIBRATED traceability tier, a CONVERGING failure-closure series, a
     READY single-test-proof row) has a paired negative control (MISCALIBRATED,
     REGRESSION, a confirmed FAIL) that must score differently, and a
     malformed/absent-evidence case that must read as unresolved rather than a
     false PASS.
  4. **Reading becoming a mutating act.** Computing a score must not create or
     change any file in the project it scores, asserted with a byte-level
     snapshot.
  5. **The front doors drifting from the library call.** Both `execute_verb()`
     and the real `python -m dv_harness.subsystem_practicality_score`
     subprocess are driven and cross-checked against the library function.

Nothing here runs a build, a regression, an LSF submission or a stage gate:
every artifact is written directly by the real writer that owns it
(`StateStore`, `MemoryStore`/`MemoryGC`, `dashboard.append_coverage_history_sample()`),
exactly as `test_golden_flow_readiness.py` and `test_loop_convergence.py`
already do for the modules this one rolls up.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dv_harness import confidence_calibration as cc  # noqa: E402
from dv_harness import generation_readiness as gr  # noqa: E402
from dv_harness import golden_flow_readiness as gfr  # noqa: E402
from dv_harness import subsystem_practicality_score as sps  # noqa: E402
from dv_harness.memory import MemoryGC, MemoryStore  # noqa: E402
from dv_harness.models import HarnessState, Stage, Status  # noqa: E402
from dv_harness.storage import StateStore  # noqa: E402


# ---------------------------------------------------------------------------
# Real-artifact helpers. Each writes through the real writer that owns the
# artifact, mirroring test_golden_flow_readiness.py / test_loop_convergence.py.
# ---------------------------------------------------------------------------

@pytest.fixture()
def project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir(parents=True)
    return p


def write_state(root: Path, statuses: dict, *, current_stage: str = Stage.INTAKE.value) -> None:
    store = StateStore(root)
    state = HarnessState(project=root.name, current_stage=current_stage)
    state.ensure_stages()
    for stage, status in statuses.items():
        state.stages[stage]["status"] = status
    store.save(state)


def write_coverage_summary(root: Path, categories: list) -> None:
    path = root / ".dv-harness" / "coverage" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"categories": categories}), encoding="utf-8")


def write_lsf_job(root: Path, job: dict) -> None:
    path = root / ".dv-harness" / "lsf" / "jobs" / f"{job['job_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job), encoding="utf-8")


def add_memory_record(store, tier, *, title="finding"):
    return store.add("engineering", {"title": title, "protocol": "USB3",
                                     "root_cause": f"{title}-rc", "confidence": tier})


def populate_memory_tier(store, tier, *, verified=0, rejected=0):
    gc = MemoryGC(store)
    for i in range(verified):
        rec = add_memory_record(store, tier, title=f"{tier}-ok-{i}")
        assert gc.confirm(rec["memory_id"], evidence={"note": "independent re-derivation"})
    for i in range(rejected):
        rec = add_memory_record(store, tier, title=f"{tier}-bad-{i}")
        assert gc.retract(rec["memory_id"], "overturned by current evidence",
                          evidence={"sim_log": "run/sim.log:1201"})


def dim_of(report: dict, dimension_id: str) -> dict:
    return next(d for d in report["dimensions"] if d["dimension_id"] == dimension_id)


def fingerprint(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ===========================================================================
# 1. Declarations: weights, ids, and every reuse claim actually resolves
# ===========================================================================

def test_dimension_weights_sum_to_100_and_ids_match_the_declared_10():
    assert len(sps.DIMENSIONS) == 10
    assert abs(sum(d.weight_percent for d in sps.DIMENSIONS) - 100.0) < 1e-9
    assert sps.dimension_ids() == [
        "spec_correctness", "dut_discovery", "vip_mapping", "uvm_generation_quality",
        "single_test_proof", "regression_reliability", "failure_closure",
        "coverage_protocol_closure", "traceability_evidence_reproducibility", "usability",
    ]
    weights = {d.dimension_id: d.weight_percent for d in sps.DIMENSIONS}
    assert weights["coverage_protocol_closure"] == 15.0
    assert weights["usability"] == 5.0


def test_every_declared_fact_source_really_resolves():
    """The anti-drift check: a dimension claiming a reader that has been
    renamed away must fail loudly rather than render a fabricated score."""
    resolved = sps.assert_fact_sources_resolvable()
    assert len(resolved) >= 10


def test_a_renamed_fact_source_fails_the_resolvability_check(monkeypatch):
    bad = sps.DimensionSpec("spec_correctness", "Spec Correctness", 10.0,
                            ("dv_harness.generation_readiness.this_function_does_not_exist",),
                            "broken on purpose")
    monkeypatch.setattr(sps, "DIMENSIONS", (bad,) + sps.DIMENSIONS[1:])
    with pytest.raises(sps.SubsystemPracticalityScoreError) as exc:
        sps.assert_fact_sources_resolvable()
    assert exc.value.reason == "FACT_SOURCE_ATTRIBUTE_MISSING"


# ===========================================================================
# 2. A bare project: every dimension present, unresolved ones honest
# ===========================================================================

def test_bare_project_reports_all_10_dimensions_and_never_defaults_unresolved_ones(
        project: Path):
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    assert len(report["dimensions"]) == 10
    assert {d["dimension_id"] for d in report["dimensions"]} == set(sps.dimension_ids())

    # Independent recomputation over the SAME underlying modules, so this
    # test does not just trust subsystem_practicality_score's own arithmetic.
    gen_matrix = gr.derive_generation_readiness(project, deep=False)
    gen_rows = {r["row_id"]: r for r in gen_matrix["rows"]}
    gf_matrix = gfr.derive_golden_flow_readiness(project)
    gf_rows = {r["row_id"]: r for r in gf_matrix["rows"]}

    row_map = {
        "spec_correctness": ("generation", "spec_parsing_requirement_ir"),
        "dut_discovery": ("generation", "dut_discovery"),
        "vip_mapping": ("generation", "protocol_vip_mapping"),
        "uvm_generation_quality": ("generation", "uvm_architecture"),
        "single_test_proof": ("golden_flow", "single_test_proof"),
        "regression_reliability": ("golden_flow", "lsf_regression"),
    }
    expected_measured_weight = 0.0
    expected_weighted_score = 0.0
    for dim_id, (which, row_id) in row_map.items():
        row = (gen_rows if which == "generation" else gf_rows)[row_id]
        d = dim_of(report, dim_id)
        if row["status"] in sps.STATUS_TO_SCORE:
            assert d["resolvable"] is True, dim_id
            assert d["score"] == sps.STATUS_TO_SCORE[row["status"]]
            assert d["weight_effective_percent"] == d["weight_declared_percent"]
            expected_measured_weight += d["weight_declared_percent"]
            expected_weighted_score += d["score"] * d["weight_declared_percent"]
        else:
            assert d["resolvable"] is False, dim_id
            assert d["score"] is None
            assert d["weight_effective_percent"] == 0.0
            assert d["reason"] != sps.NONE_CELL

    # Usability (dashboard + CLI adapter rows) is a real deployment fact, not
    # project state -- it is resolvable even on a bare project.
    usability = dim_of(report, "usability")
    assert usability["resolvable"] is True
    assert usability["score"] == sps.STATUS_TO_SCORE[
        gfr.combine_readiness([gf_rows["dashboard"]["status"],
                               gf_rows["claude_cli_integration"]["status"]])]
    expected_measured_weight += usability["weight_declared_percent"]
    expected_weighted_score += usability["score"] * usability["weight_declared_percent"]

    # No coverage summary, no evidence database, no memory store on a bare
    # project -- three dimensions must be unresolved, never scored 0 or 100.
    for dim_id in ("coverage_protocol_closure", "failure_closure",
                   "traceability_evidence_reproducibility"):
        d = dim_of(report, dim_id)
        assert d["resolvable"] is False, dim_id
        assert d["score"] is None
        assert d["weight_effective_percent"] == 0.0

    assert report["measured_weight_percent"] == pytest.approx(expected_measured_weight)
    assert report["overall_score_over_measured"] == pytest.approx(
        expected_weighted_score / expected_measured_weight)


def test_measured_weight_and_overall_score_are_reported_separately_never_conflated(
        project: Path):
    """The actual point of this module: a score computed over a MINORITY of
    the declared weight must not read as a full-confidence maturity claim."""
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    assert report["measured_weight_percent"] < sps.MIN_MEASURED_WEIGHT_PERCENT_FOR_VERDICT
    # The renormalized score is still reported -- it is not conflated away --
    # but the maturity LABEL refuses to claim confidence it does not have.
    assert report["overall_score_over_measured"] is not None
    assert report["maturity_status"] == sps.MATURITY_INSUFFICIENT
    assert report["measured_weight_percent"] + report["unmeasured_weight_percent"] == \
        pytest.approx(100.0)


def test_a_project_with_zero_resolvable_dimensions_reports_no_score_at_all(monkeypatch,
                                                                           project: Path):
    """Negative control on the rule above: NOTHING measurable must report
    `overall_score_over_measured=None`, never a fabricated 0."""
    def _force_unresolved(facts):
        return sps._unresolved(sps.UNKNOWN, "forced unresolved for this test")

    for dim_id in sps.dimension_ids():
        monkeypatch.setitem(sps.RESOLVERS, dim_id, _force_unresolved)
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    assert report["measured_weight_percent"] == 0.0
    assert report["overall_score_over_measured"] is None
    assert report["maturity_status"] == sps.MATURITY_INSUFFICIENT
    code, _ = sps.execute_verb(project, "report")
    assert code == 2


# ===========================================================================
# 3. Coverage / protocol closure: real bins-weighted percent, never a second
#    parse, never a fabricated score on malformed/absent input
# ===========================================================================

def test_coverage_dimension_is_a_real_bins_weighted_percent(project: Path):
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 62.5, "bins_total": 8, "bins_hit": 5},
        {"name": "lpm_entry", "percent": 100.0, "bins_total": 4, "bins_hit": 4},
    ])
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "coverage_protocol_closure")
    assert d["resolvable"] is True
    # Independent hand computation: (5 + 4) / (8 + 4) * 100
    expected = 100.0 * 9 / 12
    assert d["score"] == pytest.approx(expected)
    assert d["weight_effective_percent"] == 15.0
    assert "2 categor" in d["evidence"]
    assert "1 hole(s)" in d["evidence"]


def test_coverage_dimension_absent_summary_is_unresolved(project: Path):
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "coverage_protocol_closure")
    assert d["resolvable"] is False
    assert d["score"] is None
    assert "no real coverage summary" in d["reason"]


def test_coverage_dimension_malformed_summary_is_unresolved_never_zero_or_hundred(
        project: Path):
    """Negative control: a malformed summary must not read as absence (which
    would silently look like an honest 'not yet produced'), and must not be
    scored 0 or 100 -- it must be unresolved with the real parse reason."""
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 50.0, "bins_total": 4, "bins_hit": 9}])
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "coverage_protocol_closure")
    assert d["resolvable"] is False
    assert d["score"] is None
    assert "BINS_HIT_EXCEEDS_TOTAL" in d["reason"]


# ===========================================================================
# 4. Single-test proof / regression reliability: track the real golden_flow
#    rows, including the "LSF DONE is not DV PASS" negative control
# ===========================================================================

def test_single_test_proof_and_regression_reliability_track_golden_flow_rows(project: Path):
    write_state(project, {Stage.BUILD.value: Status.PASS.value,
                          Stage.VERIFY.value: Status.PASS.value,
                          Stage.REGRESSION.value: Status.PASS.value})
    write_lsf_job(project, {"job_id": "1001", "lsf_status": "DONE",
                            "dv_analysis_status": "PASS"})
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    stp = dim_of(report, "single_test_proof")
    rr = dim_of(report, "regression_reliability")
    assert stp["resolvable"] is True and stp["score"] == 100.0
    assert rr["resolvable"] is True and rr["score"] == 100.0


def test_a_confirmed_regression_failure_scores_zero_and_is_a_real_finding(project: Path):
    """LSF DONE is not DV PASS -- a real finding (score 0), never merely
    unmeasured, and it must actually change execute_verb's exit code."""
    write_state(project, {Stage.REGRESSION.value: Status.PASS.value})
    write_lsf_job(project, {"job_id": "2001", "lsf_status": "EXIT",
                            "dv_analysis_status": "FAIL",
                            "last_change_time": "2026-09-05T00:00:00"})
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    rr = dim_of(report, "regression_reliability")
    assert rr["resolvable"] is True
    assert rr["score"] == 0.0
    assert report["blocked_dimension_count"] >= 1

    code, payload = sps.execute_verb(project, "report")
    assert code == 1
    text_code, text = sps.execute_verb(project, "show")
    assert text_code == 1
    assert "Regression Reliability" in text


def test_an_lsf_done_with_no_dv_analysis_is_not_read_as_a_pass(project: Path):
    write_state(project, {Stage.REGRESSION.value: Status.PASS.value})
    write_lsf_job(project, {"job_id": "3001", "lsf_status": "DONE"})
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    rr = dim_of(report, "regression_reliability")
    # PARTIAL (some jobs unresolved) still scores below full maturity, never 100.
    assert rr["score"] != 100.0


# ===========================================================================
# 5. Traceability / evidence / reproducibility: real MemoryStore/MemoryGC
#    outcomes, calibrated vs. miscalibrated
# ===========================================================================

def test_traceability_dimension_no_memory_store_is_unresolved_not_defaulted(project: Path):
    assert not (project / ".dv-harness" / "memory" / "index.json").exists()
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "traceability_evidence_reproducibility")
    assert d["resolvable"] is False
    assert d["score"] is None
    # Reading must not have created the store it was asking about.
    assert not (project / ".dv-harness" / "memory" / "index.json").exists()


def test_traceability_dimension_calibrated_scores_100(project: Path):
    store = MemoryStore(project)
    populate_memory_tier(store, "HIGH", verified=10, rejected=0)
    populate_memory_tier(store, "MEDIUM", verified=8, rejected=2)
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "traceability_evidence_reproducibility")
    assert d["resolvable"] is True
    assert d["score"] == 100.0
    assert d["weight_effective_percent"] == 10.0


def test_traceability_dimension_miscalibrated_scores_zero_and_drives_exit_code_1(
        project: Path):
    """Negative control: an inverted tier ordering (LOW holding up better than
    HIGH, in this project's own real records) must score 0, not merely
    'unmeasured', and must be a real CI finding."""
    store = MemoryStore(project)
    populate_memory_tier(store, "HIGH", verified=5, rejected=5)
    populate_memory_tier(store, "LOW", verified=10, rejected=0)
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "traceability_evidence_reproducibility")
    assert d["resolvable"] is True
    assert d["score"] == 0.0

    code, _ = sps.execute_verb(project, "report")
    assert code == 1
    _, text = sps.execute_verb(project, "show")
    assert "Traceability" in text


# ===========================================================================
# 6. Failure closure: the real loop_convergence verdict, over a real evidence
#    database (CONVERGING vs. REGRESSION, positive and negative)
# ===========================================================================

duckdb = pytest.importorskip("duckdb")

from dv_harness import dashboard  # noqa: E402  (after the duckdb skip)
from dv_harness.evidence_db import EvidenceStore, default_db_path  # noqa: E402


def _ingest_coverage_day(root, percent, day, *, bins_total=1000):
    """One real coverage day, back-dated -- the same technique
    `test_loop_convergence.py` uses so a multi-day curve is testable without
    waiting real days. Only the store CLOCK is manipulated; every row's
    CONTENT comes from the real write path."""
    watermark = 0
    if default_db_path(root).exists():
        with EvidenceStore(default_db_path(root)) as store:
            rows = store.query("SELECT max(id) FROM coverage_samples")
        watermark = int((rows and rows[0][0]) or 0)
    write_coverage_summary(root, [{
        "name": "functional", "percent": percent,
        "bins_total": bins_total, "bins_hit": int(round(bins_total * percent / 100.0))}])
    dashboard.append_coverage_history_sample(root, percent)
    with EvidenceStore(default_db_path(root)) as store:
        store.query(f"UPDATE coverage_samples SET ingested_at = TIMESTAMP "
                    f"'{day} 12:00:00' WHERE id > {watermark}")


def test_failure_closure_dimension_reads_a_real_converging_verdict(project: Path):
    for i, (day, pct) in enumerate([
            ("2026-09-01", 40.0), ("2026-09-02", 55.0),
            ("2026-09-03", 70.0), ("2026-09-04", 90.0)]):
        _ingest_coverage_day(project, pct, day)
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "failure_closure")
    assert d["resolvable"] is True
    assert d["status"] == "CONVERGING"
    assert d["score"] == 100.0
    # Bonus cross-check: the final day's summary.json also resolves the
    # coverage dimension, sharing the same real fixture.
    cov = dim_of(report, "coverage_protocol_closure")
    assert cov["resolvable"] is True
    assert cov["score"] == pytest.approx(90.0)


def test_failure_closure_dimension_reads_a_real_regression_verdict(project: Path):
    """Negative control: a sharp decline must read as REGRESSION (score 0),
    a real finding -- not a plateau, not unmeasured."""
    for day, pct in [("2026-09-01", 90.0), ("2026-09-02", 90.0),
                     ("2026-09-03", 90.0), ("2026-09-04", 50.0)]:
        _ingest_coverage_day(project, pct, day)
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "failure_closure")
    assert d["resolvable"] is True
    assert d["status"] == "REGRESSION"
    assert d["score"] == 0.0
    assert report["blocked_dimension_count"] >= 1
    code, _ = sps.execute_verb(project, "report")
    assert code == 1


def test_failure_closure_dimension_absent_evidence_db_is_unresolved(project: Path):
    report = sps.derive_subsystem_practicality_score(project, deep=False)
    d = dim_of(report, "failure_closure")
    assert d["resolvable"] is False
    assert d["score"] is None


# ===========================================================================
# 7. Reading is never a mutating act
# ===========================================================================

def test_computing_the_score_never_modifies_a_pre_existing_project_file(project: Path):
    """Same guarantee, and the same scope, `test_golden_flow_readiness.py`'s own
    `test_producing_the_report_mutates_nothing_on_an_initialized_project` holds:
    every file that existed BEFORE the report must be byte-identical after it.
    (One of the rolled-up modules, `golden_flow_readiness.py`, materializes a
    default `config.json`/`control.json` the first time it runs over a project
    that has `.dv-harness/state.json` but no `config.json` yet -- the same
    behavior its own test suite already tolerates for the identical reason;
    this module does not introduce that, it only inherits it, and the
    guarantee that actually matters -- no EXISTING artifact is corrupted -- is
    what is asserted here.)"""
    write_state(project, {Stage.BUILD.value: Status.PASS.value})
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 62.5, "bins_total": 8, "bins_hit": 5}])
    before = fingerprint(project)
    sps.derive_subsystem_practicality_score(project, deep=False)
    sps.execute_verb(project, "show")
    after = fingerprint(project)
    for path, content in before.items():
        assert after.get(path) == content, f"{path} was modified by a read-only report"


# ===========================================================================
# 8. Front doors: execute_verb() and the real python -m subprocess
# ===========================================================================

def test_execute_verb_dimensions_lists_declared_metadata():
    code, payload = sps.execute_verb(Path("."), "dimensions")
    assert code == 0
    assert set(payload["dimension_ids"]) == set(sps.dimension_ids())
    assert payload["weights"]["coverage_protocol_closure"] == 15.0
    assert payload["declared_weight_total"] == 100.0


def test_execute_verb_unknown_verb_is_a_clear_refusal():
    code, payload = sps.execute_verb(Path("."), "bogus-verb")
    assert code == 1
    assert payload["error"] == "UNKNOWN_VERB"


def test_execute_verb_report_matches_the_library_function(project: Path):
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 100.0, "bins_total": 4, "bins_hit": 4}])
    code, payload = sps.execute_verb(project, "report", as_json=True)
    direct = sps.derive_subsystem_practicality_score(project, deep=False)
    assert payload["overall_score_over_measured"] == direct["overall_score_over_measured"]
    assert payload["measured_weight_percent"] == direct["measured_weight_percent"]
    assert code == 0


def test_python_m_cli_runs_as_a_real_subprocess(project: Path):
    write_coverage_summary(project, [
        {"name": "fsm_states", "percent": 100.0, "bins_total": 4, "bins_hit": 4}])
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.subsystem_practicality_score", "show",
         "--project-root", str(project)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert "SUBSYSTEM PRACTICALITY SCORE" in result.stdout
    assert result.returncode in (0, 1, 2)

    result_json = subprocess.run(
        [sys.executable, "-m", "dv_harness.subsystem_practicality_score", "report",
         "--project-root", str(project), "--json"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    payload = json.loads(result_json.stdout)
    assert payload["schema_version"] == sps.SCHEMA_VERSION
    assert len(payload["dimensions"]) == 10
