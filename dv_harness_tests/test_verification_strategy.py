"""VI-4 -- the Verification Strategy Optimizer (`dv_harness/verification_strategy.py`).

WHAT THESE TESTS ARE FOR. Not "the recommender returns a string". This module's
whole reason to exist is that it must recommend engines this harness CANNOT
run without ever presenting one as something it can do, so the five things that
can actually go wrong are:

  1. **An overstatement.** A row claiming FORMAL/PSS/EMULATION/FPGA_PROTOTYPE is
     executable here, or naming an execution path for one. Driven out both by
     asserting the real derived answer and by FORGING an overstated row and
     proving `assert_no_unexecutable_strategy_claimed_executable()` refuses it.
  2. **Executability that is declared rather than derived.** Proven by
     synthesising a real module at the exact name FORMAL declares and watching
     the row flip to EXECUTABLE_HERE with no code edit -- and by removing
     SIMULATION's real entry point and watching it stop claiming to be
     executable.
  3. **A recommendation with nothing behind it.** Every RECOMMENDED strategy
     this harness cannot execute must name a real act it CAN take; a row that
     does not is refused.
  4. **A detector with no detection power.** Each rule is driven out of REAL
     evidence written through REAL production write paths, and each has a
     negative control: under-sampled bins must SUPPRESS formal rather than
     recommend it, an intermittent failure already closed by a verified_fix
     must not count, one busy day must not read as throughput-bound, and a
     project with no evidence must report NO_SIGNAL rather than a clean bill.
  5. **The report becoming a mutating act.** Recommending must write nothing:
     no question filed, no candidate minted, no memory record, no evidence
     database created or migrated. Proven by a byte-level snapshot of the whole
     project root.

Every coverage/verdict row here is written through the same real functions
`engine.py` and `lsf_client` call (`regression_reporter.
_write_reconciliation_evidence_if_configured()`, `dashboard.
append_coverage_history_sample()`), every memory record through the real
`memory_router.route_and_store()`, and every failure signature through the real
`memory_vault.build_failure_signature()`. Nothing here runs a build, a
regression or an LSF submission, and no human-approval gate is touched.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from dv_harness import verification_strategy as vs

duckdb = pytest.importorskip("duckdb")

from dv_harness import coverage_analysis  # noqa: E402
from dv_harness import dashboard  # noqa: E402
from dv_harness import loop_convergence as lcv  # noqa: E402
from dv_harness import lsf_client  # noqa: E402
from dv_harness import protocol_capability as pc  # noqa: E402
from dv_harness import regression_reporter as rr  # noqa: E402
from dv_harness.evidence_db import EvidenceStore, default_db_path  # noqa: E402
from dv_harness.memory import MemoryStore  # noqa: E402
from dv_harness.memory_router import route_and_store  # noqa: E402
from dv_harness.memory_vault import build_failure_signature  # noqa: E402

REQUIREMENTS_HEADER = ("REQ_ID,SOURCE,SCOPE,VPLAN_ID,SCENARIO_ID,COMMAND_ID,PATTERN_ID,"
                       "CHECKER_ID,COVERAGE_ID,RESULT,STATUS,EVIDENCE")


# --------------------------------------------------------------------------
# Fixtures -- all drive the REAL production write paths
# --------------------------------------------------------------------------
@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        MemoryStore(tmp)  # a real store with a real index.json
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _store(root):
    return EvidenceStore(default_db_path(root))


def _job_state(pattern, passed, *, job_id, git_sha=None, seed=None,
               runtime_seconds=None):
    return lsf_client.JobState(
        job_id=job_id, pattern=pattern,
        lsf_status="DONE" if passed else "EXIT",
        sim_status="PASS" if passed else "FAIL",
        seed=None if seed is None else str(seed),
        runtime_seconds=runtime_seconds,
        git_sha=git_sha)


def _record_verdicts(root, states):
    """The REAL production evidence write path, given the whole cycle's
    reconciled jobs at once -- which is the shape that function actually takes
    from `lsf_client.reconcile_batch()`."""
    rr._write_reconciliation_evidence_if_configured(
        root, {s.job_id: (s, []) for s in states})


def _record_verdict(root, pattern, passed, *, job_id, git_sha=None, seed=None,
                    runtime_seconds=None):
    _record_verdicts(root, [_job_state(pattern, passed, job_id=job_id, git_sha=git_sha,
                                       seed=seed, runtime_seconds=runtime_seconds)])


def _seeded_runs(root, pattern, count, *, first_job_id=1000, runtime_seconds=None):
    """`count` real PASS jobs on distinct seeds -- what makes a coverage bin
    "fairly attempted" as far as coverage_analysis.count_seed_attempts() is
    concerned, because it counts DISTINCT `jobs.seed` values."""
    _record_verdicts(root, [
        _job_state(pattern, True, job_id=first_job_id + i, seed=f"s{i}",
                   git_sha=f"sha{i:04d}", runtime_seconds=runtime_seconds)
        for i in range(count)])


def _runtime_day(root, pattern, day, *, job_ids, hours_each):
    """One real day of MEASURED job runtime: real `JobState`s carrying real
    `runtime_seconds` through the real evidence write path, then only that
    batch's own `jobs` rows back-dated by job_id. Only the store clock is
    manipulated -- every row's CONTENT comes from the real write path, and
    `trend_analysis.daily_rollup()` buckets on `jobs.ingested_at`."""
    _record_verdicts(root, [
        _job_state(pattern, True, job_id=j, seed=f"s{j}", git_sha=f"sha{j}",
                   runtime_seconds=hours_each * 3600.0) for j in job_ids])
    with _store(root) as store:
        store.query(f"UPDATE jobs SET ingested_at = TIMESTAMP '{day} 12:00:00' "
                    f"WHERE job_id IN ({','.join(str(j) for j in job_ids)})")


def _ingest_coverage_day(root, percent, day, *, bins_total=1000):
    """One real coverage day through the REAL function engine.py calls, then
    only that call's own rows back-dated (keyed on the id watermark, so
    back-dating day N never moves day N-1's rows). Only the store clock is
    manipulated; every row's CONTENT comes from the real write path."""
    watermark = 0
    if default_db_path(root).exists():
        with _store(root) as store:
            rows = store.query("SELECT max(id) FROM coverage_samples")
        watermark = int((rows and rows[0][0]) or 0)
    p = Path(root) / ".dv-harness" / "coverage" / "summary.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"categories": [
        {"name": "functional", "percent": percent, "bins_total": bins_total,
         "bins_hit": int(round(bins_total * percent / 100.0))}]}), encoding="utf-8")
    dashboard.append_coverage_history_sample(root, percent)
    with _store(root) as store:
        store.query(f"UPDATE coverage_samples SET ingested_at = TIMESTAMP "
                    f"'{day} 12:00:00' WHERE id > {watermark}")


def _flat_coverage_curve(root, percent=90.0, days=5):
    for i in range(days):
        _ingest_coverage_day(root, percent + (0.1 if i % 2 else 0.0),
                             f"2026-09-{i + 1:02d}")


def _write_registry(root, rows):
    p = Path(root) / ".dv-harness" / "requirements.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(REQUIREMENTS_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _trace(coverage_id, pattern_id):
    return (f"REQ_{coverage_id},spec,block,VP1,SC1,CMD1,{pattern_id},CHK1,"
            f"{coverage_id},,OPEN,")


def _job_failure(root, signature, *, git_sha):
    """One real Job Memory record through the real router, in the shape
    engine._record_debug_attempt_job_memory() writes."""
    routed = route_and_store(root, {
        "kind": "job_failure",
        "scope": "debug",
        "title": "RE_AUDIT attempt did not close",
        "stage": "RE_AUDIT",
        "attempt": 1,
        "status": "PARTIAL",
        "blocking_reason": "GATE_FAIL: root_cause_evidence_gate",
        "failure_signature": signature,
        "protocol": signature.get("protocol"),
        "git_sha": git_sha,
    }, cfg={})
    assert routed["destination"] == "JOB_MEMORY", routed
    return routed


def _verified_fix(root, *, root_cause, symptom, protocol):
    routed = route_and_store(root, {
        "kind": "verified_fix", "verified": True,
        "title": f"Verified fix: {root_cause}", "scope": "engineering",
        "symptoms": [symptom], "root_cause": root_cause,
        "fix": "rtl commit 5e1f00d", "evidence": ["sim.log:9120"],
        "reusable": True,
        "verification": {"targeted_reproducer_passed": True,
                         "broader_regression_passed": True,
                         "new_failures_introduced": False},
        "confidence": "HIGH", "protocol": protocol,
    }, cfg={})
    assert routed["destination"] == "ENGINEERING_MEMORY", routed
    return routed


def _register_subsystems(root, names):
    """The REAL runtime subsystem registry file engine.py's
    _persist_subsystem_registry_entry() writes on a gate-validated SIGNOFF."""
    from dv_harness.environment_mode_router import registry_path
    p = registry_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"subsystems": [
        {"name": n, "environment_manifest": f"{n}/environment_manifest.json",
         "release_sha": f"sha_{n}", "qualification_state": "SIGNOFF_PASS"}
        for n in names]}), encoding="utf-8")


def _snapshot(root: Path):
    """Every file under `root`, by path -> content digest."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _rec(report, strategy):
    return next(r for r in report["recommendations"] if r["strategy"] == strategy)


# ==========================================================================
# 1. The boundary: executability is DERIVED, and never overstated
# ==========================================================================
def test_only_simulation_has_a_real_backend_in_this_repository():
    """The load-bearing fact. If this ever fails because a real formal/PSS/
    emulation backend was built, that is a genuine capability change and the
    module docstring, CLAUDE.md and these tests must be updated together --
    which is exactly what this assertion forces."""
    vs.assert_executability_matches_code()
    rows = {r["strategy"]: r["executability"] for r in vs.executability_rows()}
    assert rows == {
        vs.STRATEGY_SIMULATION: vs.EXECUTABLE_HERE,
        vs.STRATEGY_FORMAL: vs.RECOMMEND_ONLY_NO_BACKEND,
        vs.STRATEGY_PSS: vs.RECOMMEND_ONLY_NO_BACKEND,
        vs.STRATEGY_EMULATION: vs.RECOMMEND_ONLY_NO_BACKEND,
        vs.STRATEGY_FPGA_PROTOTYPE: vs.RECOMMEND_ONLY_NO_BACKEND,
    }


def test_a_strategy_with_no_backend_names_no_execution_path():
    """Naming a hypothetical path is how a recommendation becomes a claim."""
    for row in vs.executability_rows():
        if row["executability"] == vs.RECOMMEND_ONLY_NO_BACKEND:
            assert row["execution_path"] is None
            assert row["absent_note"], row
        else:
            assert row["execution_path"] == list(
                vs._BACKEND_BY_STRATEGY[row["strategy"]].required)


def test_simulations_declared_backend_is_the_real_regression_entry_point():
    """Not a string check: the two entry points must be the callables a real
    regression actually goes through, resolved through the import system."""
    from dv_harness import lsf_client as real_lsf, preflight as real_preflight
    assert callable(real_lsf.bsub_submit_with_preflight)
    assert callable(real_preflight.run_preflight)
    row = vs.derive_executability(vs.STRATEGY_SIMULATION)
    assert row["executability"] == vs.EXECUTABLE_HERE
    assert row["unresolved"] == []


def test_executability_is_derived_not_declared__a_real_backend_flips_the_row(monkeypatch, tmp_path):
    """The proof that nothing here is a typed-in status: create a REAL module
    at the exact name FORMAL declares, with the exact entry point, and the row
    flips to EXECUTABLE_HERE with no edit to verification_strategy.py."""
    pkg = tmp_path / "dv_harness_fake"
    pkg.mkdir()
    (pkg / "formal_client_probe.py").write_text(
        "def prove_property(*a, **k):\n    return None\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(vs, "_BACKEND_BY_STRATEGY", dict(
        vs._BACKEND_BY_STRATEGY,
        FORMAL=vs.StrategyBackend(
            strategy=vs.STRATEGY_FORMAL,
            required=("dv_harness_fake.formal_client_probe:prove_property",),
            what_it_would_run="a proof")))
    row = vs.derive_executability(vs.STRATEGY_FORMAL)
    assert row["executability"] == vs.EXECUTABLE_HERE
    assert row["execution_path"] == ["dv_harness_fake.formal_client_probe:prove_property"]
    # ... and the repo-state assertion now correctly FAILS, forcing the docs to
    # be updated alongside the new capability rather than silently drifting.
    with pytest.raises(vs.StrategyExecutabilityOverstatedError):
        vs.assert_executability_matches_code()


def test_a_module_that_imports_but_lost_its_entry_point_is_not_a_backend(monkeypatch):
    """A module that exists is not a backend -- the callable must resolve too."""
    monkeypatch.setattr(vs, "_BACKEND_BY_STRATEGY", dict(
        vs._BACKEND_BY_STRATEGY,
        SIMULATION=vs.StrategyBackend(
            strategy=vs.STRATEGY_SIMULATION,
            required=("dv_harness.lsf_client:function_that_does_not_exist",),
            what_it_would_run="a regression")))
    row = vs.derive_executability(vs.STRATEGY_SIMULATION)
    assert row["executability"] == vs.RECOMMEND_ONLY_NO_BACKEND
    assert "has no 'function_that_does_not_exist' entry point" in row["basis"]


def test_a_forged_overstated_row_is_refused():
    """The invariant is re-derived from the import system, never trusted from
    the record -- so hand-editing a row to claim executability is caught."""
    forged = vs.StrategyRecommendation(
        strategy=vs.STRATEGY_FORMAL, verdict=vs.VERDICT_RECOMMENDED,
        executability=vs.EXECUTABLE_HERE,
        execution_path=["dv_harness.formal_client:prove_property"],
        executable_next_action="run it")
    with pytest.raises(vs.StrategyExecutabilityOverstatedError) as exc:
        vs.assert_no_unexecutable_strategy_claimed_executable([forged])
    assert "FORMAL" in str(exc.value)


def test_a_recommendation_this_harness_cannot_act_on_at_all_is_refused():
    """"Use formal" with no act this harness can perform reads as a capability
    and is not one."""
    empty = vs.StrategyRecommendation(
        strategy=vs.STRATEGY_EMULATION, verdict=vs.VERDICT_RECOMMENDED,
        executability=vs.RECOMMEND_ONLY_NO_BACKEND, executable_next_action="")
    with pytest.raises(vs.StrategyExecutabilityOverstatedError) as exc:
        vs.assert_no_unexecutable_strategy_claimed_executable([empty])
    assert "executable_next_action" in str(exc.value)


def test_strategy_vocabulary_shares_no_token_with_the_verification_verdicts():
    """A STRATEGY recommendation must never be confusable, by a reader or a log
    grep, with a PASS/FAIL verification result."""
    from dv_harness.models import Status
    vs.assert_no_verification_verdict_vocabulary()
    verdicts = {s.value for s in Status}
    for vocab in (vs.STRATEGIES, vs.STRATEGY_VERDICTS, vs.EXECUTABILITY_VALUES, vs.SCOPES):
        assert not verdicts.intersection(vocab)


def test_every_named_escalator_really_exists():
    """A recommendation whose only actionable content is "call X" is worth
    exactly as much as X being real -- and because this module never TAKES
    these paths, nothing else would catch one being renamed away."""
    vs.assert_named_escalators_resolve()
    from dv_harness import capability_evolution as ce
    from dv_harness.question_queue import QuestionQueueStore
    assert callable(coverage_analysis.escalate_unreachable_holes)
    assert callable(ce.file_repeated_failure_candidate)
    assert callable(QuestionQueueStore.add_question)


def test_a_renamed_escalator_fails_the_check(monkeypatch):
    monkeypatch.setattr(vs, "_ESCALATOR_ENTRY_POINTS",
                        ("dv_harness.coverage_analysis:escalate_nothing_at_all",))
    with pytest.raises(vs.StrategyExecutabilityOverstatedError) as exc:
        vs.assert_named_escalators_resolve()
    assert "escalate_nothing_at_all" in str(exc.value)


def test_a_strategy_token_colliding_with_a_verification_verdict_is_refused(monkeypatch):
    monkeypatch.setattr(vs, "STRATEGY_VERDICTS", vs.STRATEGY_VERDICTS + ("BLOCKED",))
    with pytest.raises(vs.StrategyExecutabilityOverstatedError):
        vs.assert_no_verification_verdict_vocabulary()


# ==========================================================================
# 2. Every strategy is reachable, and no strategy is ever silently dropped
# ==========================================================================
def test_every_strategy_gets_a_row_even_with_no_evidence_at_all(root):
    """An omitted strategy reads as "not applicable"; a NO_SIGNAL strategy
    reads as "we have no evidence". Those must not look the same."""
    report = vs.recommend_strategies(root).to_dict()
    assert [r["strategy"] for r in report["recommendations"]] == list(vs.STRATEGIES)
    for rec in report["recommendations"]:
        assert rec["verdict"] in vs.STRATEGY_VERDICTS
        assert rec["basis"], f"{rec['strategy']} carries no basis"


def test_a_project_with_no_evidence_defaults_to_simulation_and_says_it_is_a_default(root):
    report = vs.recommend_strategies(root).to_dict()
    sim = _rec(report, vs.STRATEGY_SIMULATION)
    assert sim["verdict"] == vs.VERDICT_RECOMMENDED
    assert "R8_NO_SIGNAL_DEFAULT" in sim["rules_fired"]
    assert "a default, not a measurement" in " ".join(sim["basis"])
    assert _rec(report, vs.STRATEGY_FORMAL)["verdict"] != vs.VERDICT_RECOMMENDED
    # And the absence of evidence is REPORTED, not silently treated as clean.
    assert any("NO_COVERAGE_SERIES" in u for u in report["signals"]["unavailable"])


def test_the_goal_text_is_recorded_verbatim_and_never_parsed(root):
    """Free text never silently becomes a verdict -- the same contract
    capability_evolution puts on acceptance_criteria_machine_evaluated."""
    goal = "prove the AXI write-response ordering property exhaustively with formal"
    report = vs.recommend_strategies(root, goal_text=goal).to_dict()
    assert report["goal_text"] == goal
    assert report["goal_text_machine_evaluated"] is False
    # The word "formal" in the goal buys FORMAL nothing.
    assert _rec(report, vs.STRATEGY_FORMAL)["verdict"] != vs.VERDICT_RECOMMENDED


# ==========================================================================
# 3. Coverage-closure difficulty -> simulation vs. formal, from REAL evidence
# ==========================================================================
def _plateau_signals(root, holes):
    """A real PLATEAU convergence report over a real flat coverage curve, with
    the real per-bin plateau investigation attached."""
    convergence = lcv.classify_loop_convergence(root, holes=holes).to_dict()
    assert convergence["verdict"] == lcv.PLATEAU, convergence
    assert convergence["plateau_investigation"] is not None
    return convergence


def test_under_sampled_bins_recommend_more_seeds_and_SUPPRESS_formal(root):
    """The precedence that matters most: a bin randomization has not fairly
    attempted cannot support a structural unreachability claim, so formal is
    SUPPRESSED -- not merely unrecommended. Recommending an engine this harness
    cannot even run, on the strength of bins nobody has run yet, is the most
    expensive possible wrong answer."""
    _write_registry(root, [_trace("COV_LFPS", "PAT_LFPS")])
    _seeded_runs(root, "PAT_LFPS", 3)          # far below the 20-seed minimum
    _flat_coverage_curve(root)
    holes = [{"coverage_id": "COV_LFPS",
              "root_cause_classification": coverage_analysis.ROOT_CAUSE_UNREACHABLE_STIMULUS}]
    convergence = _plateau_signals(root, holes)

    report = vs.recommend_strategies(root, holes=holes, convergence=convergence).to_dict()
    sim, formal = _rec(report, vs.STRATEGY_SIMULATION), _rec(report, vs.STRATEGY_FORMAL)
    assert sim["verdict"] == vs.VERDICT_RECOMMENDED
    assert sim["executable_next_action"] == coverage_analysis.ACTION_ADD_SEEDS
    assert formal["verdict"] == vs.VERDICT_SUPPRESSED
    assert "R1_UNDER_SAMPLED_BINS" in formal["rules_fired"]
    assert report["recommended_strategies"] == [vs.STRATEGY_SIMULATION]


def test_the_same_bin_after_fair_sampling_recommends_formal_and_names_the_real_escalator(root):
    """The detection power: the ONLY difference from the test above is that the
    bin has now really been sampled 20+ distinct seeds through the real
    evidence write path. The recommendation flips to FORMAL -- and, because
    this harness cannot run formal, it names the one act it CAN take."""
    _write_registry(root, [_trace("COV_LFPS", "PAT_LFPS")])
    _seeded_runs(root, "PAT_LFPS", coverage_analysis.DEFAULT_MIN_SEED_ATTEMPTS + 2)
    _flat_coverage_curve(root)
    holes = [{"coverage_id": "COV_LFPS",
              "root_cause_classification": coverage_analysis.ROOT_CAUSE_UNREACHABLE_STIMULUS}]
    convergence = _plateau_signals(root, holes)

    report = vs.recommend_strategies(root, holes=holes, convergence=convergence).to_dict()
    formal = _rec(report, vs.STRATEGY_FORMAL)
    assert formal["verdict"] == vs.VERDICT_RECOMMENDED
    assert formal["executability"] == vs.RECOMMEND_ONLY_NO_BACKEND
    assert formal["execution_path"] is None
    assert vs.ESCALATOR_QUESTION_QUEUE in formal["executable_next_action"]
    assert formal["next_action_owner"] == "designer"
    # More simulation of the same stimulus is NOT the answer for those bins.
    assert _rec(report, vs.STRATEGY_SIMULATION)["verdict"] == vs.VERDICT_NOT_INDICATED


def test_a_stimulus_gap_is_simulation_work_not_an_engine_change(root):
    """A bin no test is even traced to is MISSING_TEST -- writing the test is
    the answer, and this harness can run it."""
    _write_registry(root, [_trace("COV_OTHER", "PAT_OTHER")])
    _seeded_runs(root, "PAT_OTHER", coverage_analysis.DEFAULT_MIN_SEED_ATTEMPTS + 2)
    _flat_coverage_curve(root)
    holes = [{"coverage_id": "COV_UNTRACED"}]  # nothing traced to it at all
    convergence = _plateau_signals(root, holes)

    report = vs.recommend_strategies(root, holes=holes, convergence=convergence).to_dict()
    sim = _rec(report, vs.STRATEGY_SIMULATION)
    assert sim["verdict"] == vs.VERDICT_RECOMMENDED
    assert sim["executability"] == vs.EXECUTABLE_HERE
    assert sim["executable_next_action"] == coverage_analysis.ACTION_GENERATE_TESTCASE
    assert _rec(report, vs.STRATEGY_FORMAL)["verdict"] == vs.VERDICT_NOT_INDICATED


def test_a_healthy_climbing_curve_recommends_no_engine_change(root):
    """Negative control for the whole coverage axis: a converging project must
    not be told to buy a formal tool."""
    _write_registry(root, [_trace("COV_LFPS", "PAT_LFPS")])
    _seeded_runs(root, "PAT_LFPS", coverage_analysis.DEFAULT_MIN_SEED_ATTEMPTS + 2)
    for i, percent in enumerate([10.0, 30.0, 55.0, 80.0]):
        _ingest_coverage_day(root, percent, f"2026-09-{i + 1:02d}")
    convergence = lcv.classify_loop_convergence(root).to_dict()
    assert convergence["verdict"] == lcv.CONVERGING, convergence

    report = vs.recommend_strategies(root, convergence=convergence).to_dict()
    assert report["recommended_strategies"] == [vs.STRATEGY_SIMULATION]
    assert _rec(report, vs.STRATEGY_FORMAL)["verdict"] != vs.VERDICT_RECOMMENDED


# ==========================================================================
# 4. Failure density -> formal, and the verified_fix negative control
# ==========================================================================
SYMPTOM = "AXI write response returns SLVERR after a 4KB-crossing burst"
CAUSE = "the fabric splits the burst but forwards the first response only"


def test_a_signature_recurring_across_independent_runs_recommends_formal(root):
    """Two INDEPENDENT runs (distinct git SHAs) of the same unresolved failure
    signature -- the same bar capability_evolution.REPEAT_FAILURE_MIN_OCCURRENCES
    sets, reused rather than re-defined here."""
    sig = build_failure_signature(protocol="AMBA4", symptom=SYMPTOM, root_cause_hint=CAUSE)
    _job_failure(root, sig, git_sha="aaaa1111")
    _job_failure(root, sig, git_sha="bbbb2222")

    report = vs.recommend_strategies(root).to_dict()
    formal = _rec(report, vs.STRATEGY_FORMAL)
    assert formal["verdict"] == vs.VERDICT_RECOMMENDED
    assert "R4_UNRESOLVED_RECURRING_FAILURE" in formal["rules_fired"]
    assert vs.ESCALATOR_CAPABILITY_CANDIDATE in formal["executable_next_action"]
    assert len(report["signals"]["unresolved_repeated_signatures"]) == 1


def test_three_retries_against_one_commit_are_one_run_and_recommend_nothing(root):
    """Negative control, inherited from capability_evolution._run_identity():
    one stage retrying three times against one commit is one run's
    circumstances, not a repeated pattern."""
    sig = build_failure_signature(protocol="AMBA4", symptom=SYMPTOM, root_cause_hint=CAUSE)
    for _ in range(3):
        _job_failure(root, sig, git_sha="aaaa1111")

    report = vs.recommend_strategies(root).to_dict()
    assert report["signals"]["unresolved_repeated_signatures"] == []
    assert _rec(report, vs.STRATEGY_FORMAL)["verdict"] != vs.VERDICT_RECOMMENDED


def test_a_failure_already_closed_by_a_verified_fix_does_not_recommend_formal(root):
    """Negative control: only a gate-verified verified_fix closes a failure,
    and that decision stays capability_evolution's -- this module imports it
    rather than re-deciding it."""
    sig = build_failure_signature(protocol="AMBA4", symptom=SYMPTOM, root_cause_hint=CAUSE)
    _job_failure(root, sig, git_sha="aaaa1111")
    _job_failure(root, sig, git_sha="bbbb2222")
    _verified_fix(root, root_cause=CAUSE, symptom=SYMPTOM, protocol="AMBA4")

    report = vs.recommend_strategies(root).to_dict()
    assert report["signals"]["unresolved_repeated_signatures"] == []
    assert _rec(report, vs.STRATEGY_FORMAL)["verdict"] != vs.VERDICT_RECOMMENDED


def test_failure_density_comes_from_the_real_evidence_table_read_only(root):
    """The aggregate density is read from the real `failure_signatures` table,
    which the real job-memory write path accumulates occurrence_count on."""
    sig = build_failure_signature(protocol="AMBA4", symptom=SYMPTOM, root_cause_hint=CAUSE)
    with _store(root) as store:
        store.insert_job_memory_record({
            "memory_id": "job:1", "kind": "job_failure", "job_id": 1,
            "pattern": "PAT_A", "failure_signature": sig})
        store.insert_job_memory_record({
            "memory_id": "job:2", "kind": "job_failure", "job_id": 2,
            "pattern": "PAT_A", "failure_signature": sig})
    signals = vs.gather_signals(root)
    assert signals.failure_evidence_available is True
    assert signals.distinct_failure_signatures == 1
    assert signals.total_failure_occurrences == 2


def test_a_missing_evidence_database_reports_unavailable_not_zero_failures(root):
    """"0 failures recorded" from a store that was never written is not a
    measurement of anything -- and a rule would read it as a clean design."""
    assert not default_db_path(root).exists()
    signals = vs.gather_signals(root)
    assert signals.failure_evidence_available is False
    assert signals.distinct_failure_signatures == 0
    assert any("NO_FAILURE_SIGNATURE_EVIDENCE" in u for u in signals.unavailable)
    assert not default_db_path(root).exists(), "gathering signals created a database"


# ==========================================================================
# 5. Throughput -> emulation / prototyping, with its negative control
# ==========================================================================
def test_sustained_measured_simulation_hours_recommend_emulation_and_prototyping(root):
    """Real measured `jobs.runtime_seconds` summed by the real
    trend_analysis.daily_rollup(), over enough days, while coverage is NOT
    converging."""
    _write_registry(root, [_trace("COV_LFPS", "PAT_LFPS")])
    _flat_coverage_curve(root)
    for day in range(3):  # 40h of real measured runtime per day
        _runtime_day(root, "PAT_LFPS", f"2026-09-{day + 1:02d}",
                     job_ids=[5000 + day * 10 + j for j in range(4)], hours_each=10.0)
    convergence = lcv.classify_loop_convergence(root).to_dict()
    report = vs.recommend_strategies(root, convergence=convergence).to_dict()

    assert report["signals"]["mean_runtime_hours_per_day"] >= \
        vs.DEFAULT_THROUGHPUT_BOUND_RUNTIME_HOURS_PER_DAY
    for strategy in (vs.STRATEGY_EMULATION, vs.STRATEGY_FPGA_PROTOTYPE):
        rec = _rec(report, strategy)
        assert rec["verdict"] == vs.VERDICT_RECOMMENDED, rec
        assert rec["executability"] == vs.RECOMMEND_ONLY_NO_BACKEND
        assert vs.ESCALATOR_TOOL_DECISION in rec["executable_next_action"]
        assert rec["next_action_owner"] == "tool-budget owner"


def test_one_busy_day_is_not_a_throughput_signal(root):
    """Negative control: below the minimum days of evidence the honest answer
    is NO_SIGNAL about the SAMPLE, never NOT_INDICATED about the project."""
    _record_verdict(root, "PAT_LFPS", True, job_id=6000, seed="s0",
                    git_sha="sha0", runtime_seconds=200 * 3600.0)
    report = vs.recommend_strategies(root).to_dict()
    assert report["signals"]["runtime_evidence_days"] < vs.DEFAULT_MIN_RUNTIME_DAYS
    rec = _rec(report, vs.STRATEGY_EMULATION)
    assert rec["verdict"] == vs.VERDICT_NO_SIGNAL
    assert "INSUFFICIENT_RUNTIME_EVIDENCE" in " ".join(rec["basis"])


def test_modest_runtime_does_not_recommend_an_emulator(root):
    """Negative control: several days of real but small runtime is measured,
    and measured to be NOT throughput-bound."""
    _flat_coverage_curve(root)
    for day in range(3):
        _runtime_day(root, "PAT_LFPS", f"2026-09-{day + 1:02d}",
                     job_ids=[7000 + day], hours_each=0.1)
    report = vs.recommend_strategies(root).to_dict()
    assert report["signals"]["runtime_evidence_days"] >= vs.DEFAULT_MIN_RUNTIME_DAYS
    assert _rec(report, vs.STRATEGY_EMULATION)["verdict"] == vs.VERDICT_NOT_INDICATED


def test_the_throughput_bound_is_a_project_overridable_threshold(root):
    """It is a heuristic with a stated justification, not a measurement -- so a
    project that knows its own farm can set it."""
    _flat_coverage_curve(root)
    for day in range(3):
        _runtime_day(root, "PAT_LFPS", f"2026-09-{day + 1:02d}",
                     job_ids=[7100 + day], hours_each=1.0)
    cfg = {"verification_strategy": {"throughput_bound_runtime_hours_per_day": 0.5}}
    assert vs.throughput_bound_hours_per_day(cfg) == 0.5
    report = vs.recommend_strategies(root, cfg=cfg).to_dict()
    assert _rec(report, vs.STRATEGY_EMULATION)["verdict"] == vs.VERDICT_RECOMMENDED


# ==========================================================================
# 6. Scope + the real subsystem registry -> PSS
# ==========================================================================
def test_system_scope_over_two_registered_subsystems_recommends_pss(root):
    _register_subsystems(root, ["usb_ss", "amba_fabric"])
    report = vs.recommend_strategies(root, scope=vs.SCOPE_SYSTEM).to_dict()
    pss = _rec(report, vs.STRATEGY_PSS)
    assert pss["verdict"] == vs.VERDICT_RECOMMENDED
    assert pss["executability"] == vs.RECOMMEND_ONLY_NO_BACKEND
    assert vs.ESCALATOR_TOOL_DECISION in pss["executable_next_action"]
    assert report["signals"]["registered_subsystems"] == ["usb_ss", "amba_fabric"]


def test_system_scope_with_one_subsystem_is_not_a_pss_indication(root):
    """Negative control: one subsystem is not a coordination problem."""
    _register_subsystems(root, ["usb_ss"])
    report = vs.recommend_strategies(root, scope=vs.SCOPE_SYSTEM).to_dict()
    assert _rec(report, vs.STRATEGY_PSS)["verdict"] == vs.VERDICT_NOT_INDICATED


def test_scope_is_a_caller_fact_and_is_never_inferred_from_the_goal(root):
    """Two registered subsystems and a goal that says "SoC" still yields
    NO_SIGNAL while scope is UNDECLARED -- this module does not turn prose into
    a verdict."""
    _register_subsystems(root, ["usb_ss", "amba_fabric"])
    report = vs.recommend_strategies(
        root, goal_text="full SoC multi-subsystem boot scenario").to_dict()
    pss = _rec(report, vs.STRATEGY_PSS)
    assert pss["verdict"] == vs.VERDICT_NO_SIGNAL
    assert "caller fact, not a measurement" in " ".join(pss["basis"])


# ==========================================================================
# 7. Protocol capability -- the real per-protocol status, not a guess
# ==========================================================================
def test_a_generic_skeleton_only_protocol_says_build_the_model_before_any_engine(root):
    """Ethernet has no protocol-specific generator anywhere in this repo, so
    "which engine" is the wrong question for it -- and this is read from
    protocol_capability's own code-derived status, not typed in here."""
    cap = pc.capability_for("Ethernet")
    assert cap is not None and pc.derive_status(cap) == pc.STATUS_GENERIC_SKELETON_ONLY
    report = vs.recommend_strategies(root, protocol="Ethernet").to_dict()
    sim = _rec(report, vs.STRATEGY_SIMULATION)
    assert "R7_PROTOCOL_MODEL_CEILING" in sim["rules_fired"]
    assert sim["verdict"] == vs.VERDICT_RECOMMENDED
    assert "protocol model" in sim["executable_next_action"]
    assert report["signals"]["protocol_capability_status"] == pc.STATUS_GENERIC_SKELETON_ONLY


def test_a_partial_protocol_models_unmodelled_layers_are_reported_as_a_caveat(root):
    """PCIe's model explicitly does not model the TLP layer. That is a real
    ceiling and must reach the reader -- but whether THIS goal touches it is
    not machine-evaluated, so it is a caveat, not a verdict."""
    report = vs.recommend_strategies(root, protocol="PCIe").to_dict()
    sim = _rec(report, vs.STRATEGY_SIMULATION)
    basis = " ".join(sim["basis"])
    assert "CAVEAT" in basis and "tlp_layer" in basis
    assert "tlp_layer" in report["signals"]["protocol_unmodelled_layers"]


def test_an_unknown_protocol_is_reported_unavailable_not_silently_ignored(root):
    report = vs.recommend_strategies(root, protocol="NOT_A_PROTOCOL").to_dict()
    assert report["signals"]["protocol_known"] is False
    assert any("UNKNOWN_PROTOCOL" in u for u in report["signals"]["unavailable"])


# ==========================================================================
# 8. Recommending is a pure read, and every gate still stands
# ==========================================================================
def test_recommending_writes_absolutely_nothing(root):
    """Byte-level proof over the whole project root -- no question filed, no
    candidate minted, no memory record, no evidence database created or
    migrated. The module NAMES its escalators and takes none of them, the same
    contract loop_convergence.PlateauInvestigation.escalator has."""
    _write_registry(root, [_trace("COV_LFPS", "PAT_LFPS")])
    _seeded_runs(root, "PAT_LFPS", coverage_analysis.DEFAULT_MIN_SEED_ATTEMPTS + 2)
    _flat_coverage_curve(root)
    _register_subsystems(root, ["usb_ss", "amba_fabric"])
    sig = build_failure_signature(protocol="AMBA4", symptom=SYMPTOM, root_cause_hint=CAUSE)
    _job_failure(root, sig, git_sha="aaaa1111")
    _job_failure(root, sig, git_sha="bbbb2222")
    holes = [{"coverage_id": "COV_LFPS",
              "root_cause_classification": coverage_analysis.ROOT_CAUSE_UNREACHABLE_STIMULUS}]

    before = _snapshot(root)
    report = vs.recommend_strategies(root, holes=holes, scope=vs.SCOPE_SYSTEM,
                                     protocol="USB", goal_text="close LFPS").to_dict()
    after = _snapshot(root)
    assert after == before, "recommend_strategies() mutated the project"
    # ... and it really did have something to say, so this is not a vacuous pass.
    assert vs.STRATEGY_FORMAL in report["recommended_strategies"]


def test_recommend_on_a_bare_root_creates_no_memory_store():
    """Regression for the independent review's finding: the `root` fixture
    above pre-constructs a MemoryStore, which is exactly why
    test_recommending_writes_absolutely_nothing() could not have caught this.
    On a project with NO memory store at all, recommend_strategies() must not
    bring one into existence just by asking about failure-density signals --
    the same guard confidence_calibration.calibrate() and
    cross_project_mining already apply."""
    bare = Path(tempfile.mkdtemp())
    try:
        assert not (bare / ".dv-harness").exists()
        before = _snapshot(bare)
        report = vs.recommend_strategies(bare, holes=[], scope=vs.SCOPE_SYSTEM,
                                         protocol="USB", goal_text="anything").to_dict()
        after = _snapshot(bare)
        assert after == before, "recommend_strategies() created files on a bare root"
        assert not (bare / ".dv-harness" / "memory").exists(), \
            "recommend_strategies() constructed a MemoryStore on a bare root"
        unavailable = (report.get("signals") or {}).get("unavailable") or []
        assert any("NO_JOB_MEMORY_FAILURE_HISTORY" in u for u in unavailable)
    finally:
        shutil.rmtree(bare, ignore_errors=True)


def test_no_question_queue_entry_is_created_by_a_formal_recommendation(root):
    """The escalation is NAMED, never taken -- filing a Tier-3 question is a
    human-facing act and stays one."""
    from dv_harness.question_queue import QuestionQueueStore
    _write_registry(root, [_trace("COV_LFPS", "PAT_LFPS")])
    _seeded_runs(root, "PAT_LFPS", coverage_analysis.DEFAULT_MIN_SEED_ATTEMPTS + 2)
    _flat_coverage_curve(root)
    holes = [{"coverage_id": "COV_LFPS",
              "root_cause_classification": coverage_analysis.ROOT_CAUSE_UNREACHABLE_STIMULUS}]
    report = vs.recommend_strategies(root, holes=holes).to_dict()
    assert _rec(report, vs.STRATEGY_FORMAL)["verdict"] == vs.VERDICT_RECOMMENDED
    assert QuestionQueueStore(root).list_questions() == []


def test_no_capability_candidate_is_filed_by_a_recurring_failure_recommendation(root):
    from dv_harness import capability_evolution as ce
    sig = build_failure_signature(protocol="AMBA4", symptom=SYMPTOM, root_cause_hint=CAUSE)
    _job_failure(root, sig, git_sha="aaaa1111")
    _job_failure(root, sig, git_sha="bbbb2222")
    report = vs.recommend_strategies(root).to_dict()
    assert _rec(report, vs.STRATEGY_FORMAL)["verdict"] == vs.VERDICT_RECOMMENDED
    assert ce.read_candidates(root).get("candidates", []) == []


# ==========================================================================
# 9. The front door
# ==========================================================================
def test_capabilities_verb_prints_the_boundary_and_exits_zero(root):
    code, payload, text = vs.execute_verb(root, "capabilities")
    assert code == 0
    assert {r["strategy"] for r in payload["strategies"]} == set(vs.STRATEGIES)
    assert "EXECUTE simulation only" in text


def test_recommend_exits_2_when_it_names_a_strategy_this_harness_cannot_run(root):
    """A CI-visible "a human has to decide something" signal -- never an
    approval in either direction."""
    _write_registry(root, [_trace("COV_LFPS", "PAT_LFPS")])
    _seeded_runs(root, "PAT_LFPS", coverage_analysis.DEFAULT_MIN_SEED_ATTEMPTS + 2)
    _flat_coverage_curve(root)
    holes_file = Path(root) / "holes.json"
    holes_file.write_text(json.dumps({"holes": [
        {"coverage_id": "COV_LFPS",
         "root_cause_classification": coverage_analysis.ROOT_CAUSE_UNREACHABLE_STIMULUS}]}),
        encoding="utf-8")
    code, payload, text = vs.execute_verb(root, "recommend", holes_path=str(holes_file))
    assert code == 2
    assert vs.STRATEGY_FORMAL in payload["recommended_strategies"]
    assert "RECOMMEND_ONLY_NO_BACKEND" in text


def test_recommend_exits_0_when_only_simulation_is_recommended(root):
    code, payload, _ = vs.execute_verb(root, "recommend")
    assert code == 0
    assert payload["recommended_strategies"] == [vs.STRATEGY_SIMULATION]


def test_a_bad_invocation_is_reported_as_data_and_exits_1(root):
    for kwargs, expected in (
        ({"scope": "GALAXY"}, "UNKNOWN_SCOPE"),
        ({"holes_path": str(Path(root) / "nope.json")}, "HOLES_FILE_NOT_FOUND"),
    ):
        code, payload, _ = vs.execute_verb(root, "recommend", **kwargs)
        assert code == 1 and payload["error"] == expected
    code, payload, _ = vs.execute_verb(root, "optimise")
    assert code == 1 and payload["error"] == "UNKNOWN_VERB"


def test_the_rendered_report_always_carries_the_executability_disclosure(root):
    text = vs.render_strategy_report_text(vs.recommend_strategies(root).to_dict())
    assert vs.REPORT_DISCLOSURE in text
    for strategy in vs.STRATEGIES:
        assert strategy in text


def test_the_cli_front_door_and_the_module_share_one_implementation():
    """Two handlers over one behaviour is the parallel-mechanism defect this
    project forbids, at CLI scale -- so cli.py must call execute_verb()."""
    source = (Path(__file__).resolve().parents[1] / "dv_harness" / "cli.py").read_text(
        encoding="utf-8")
    assert 'sub.add_parser("verification-strategy"' in source
    assert "_vs.execute_verb(" in source
