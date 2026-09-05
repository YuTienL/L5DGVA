"""Unified loop budget engine + failure taxonomy + circuit breaker
(LOOP_ENGINEERING sections 91 / 92 / 93).

WHAT THESE TESTS ARE FOR. Not "an isolated function returns a value". The five
things that can actually go wrong with this mechanism are:

  1. the taxonomy or the budget table drifting out of agreement with the real
     vocabularies they bridge -- `sim_log_analysis.TRIAGE_CATEGORIES`,
     `preflight`'s own check names, `loop_contract.LoopState` (tested by the
     totality assertions, which FAIL when a member is added on either side
     without a decision here);
  2. a budget claiming a limit nothing enforces, or a `None` limit that reads
     as a bound (tested by requiring every dimension to carry either the real
     config key or the honest reason);
  3. a budget silently resetting -- section 91's one hard rule (tested by
     driving every reset path and asserting the refusal);
  4. the classifier answering from prose rather than evidence, or answering
     differently from the mechanisms it claims to reuse (tested against the
     REAL `preflight.check_license()` outcomes produced from this project's own
     REAL captured `lmstat` output, and against the same boundary-trace rule
     `dashboard._failure_attribution()` recomputes);
  5. none of it being reachable on the real engine path -- the failure mode
     that would make this a vocabulary nobody produces.

(5) is driven end to end against a REAL `DVHarness.loop()` over the REAL shipped
`main_graph.json`, with the REAL `command_migration_integrity_gate.py`
subprocess judging the stage, in an isolated fixture project copy -- the same
fixture `test_loop_contract.py` uses, reused rather than duplicated. The only
stubbed thing is the agent adapter, because the real one dispatches a `claude -p`
subprocess. Nothing here runs a build, a regression or an LSF submission:
COMMAND_PATTERN is an `implementation-route` node with no FAIL edge in the real
graph, so a retry-exhausted `loop()` terminates deterministically instead of
walking on into the rest of the pipeline.

Every behaviour-changing assertion carries its NEGATIVE CONTROL, because a test
that only ever looks at the "on" case proves nothing about whether the default
was left alone: the retry-refusal test asserts three attempts with the flag off
and one with it on, over the identical fixture; the deferral test asserts
PROCEED at the real captured 99/0 license reading and DEFER only once the
reading is genuinely scarce.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import loop_budget as lb
from dv_harness import preflight as pf
from dv_harness import loop_contract as lc
from dv_harness.models import Status
from dv_harness.storage import StateStore

from .controlled_experiment_fixture import (
    FIXTURE_STAGE,
    harness_factory,
    make_fixture_project,
)
from .test_preflight import REAL_LMSTAT_VCS_HEADER


@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def project():
    """An isolated fixture project: the real graph, one real gate script."""
    tmp = Path(tempfile.mkdtemp())
    try:
        yield make_fixture_project(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


BASE_CFG = {"policy": {"max_stage_retries": 2,
                       "inner_react_max_iterations": 3,
                       "inner_react_max_adapter_calls": 2}}


def _write_config(project: Path, loop_budget_block: dict) -> None:
    """Write a REAL `.dv-harness/config.json` the REAL `load_config()` merges,
    so a test's config reaches the engine exactly the way a project's does."""
    from dv_harness.config import DEFAULT_CONFIG
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["loop_budget"] = loop_budget_block
    p = project / ".dv-harness" / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _events(project: Path, name: str) -> list:
    path = project / ".dv-harness" / "events.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("event") == name:
            out.append(e)
    return out


# ==========================================================================
# Section 93: the taxonomy, and its agreement with what it bridges
# ==========================================================================
def test_failure_type_carries_every_section_93_class():
    """Section 93 names ten classes. All ten must exist, spelled exactly as the
    section spells them -- a taxonomy missing a class silently reclassifies it
    as something else."""
    assert set(lb.FAILURE_TYPE_VALUES) == {
        "TRANSIENT", "DETERMINISTIC", "RESOURCE", "LICENSE", "ENVIRONMENT",
        "TEST", "DUT", "VIP", "INFRASTRUCTURE", "UNKNOWN"}


def test_every_failure_type_has_a_decided_retry_meaning():
    lb.assert_retry_policy_total()


def test_unknown_is_retryable_so_the_classifier_never_shortens_an_existing_budget():
    """An unclassified failure must behave exactly as it does today. Refusing
    to retry a failure nobody understood would shrink every existing project's
    retry budget on the strength of this module's ignorance."""
    assert lb.RETRYABLE_FAILURE_TYPES[lb.FailureType.UNKNOWN.value] is True
    assert lb.classify_failure("something nobody wrote a rule for").retryable is True


def test_triage_vocabulary_stays_in_agreement_with_sim_log_analysis():
    """`sim_log_analysis` owns the log triage categories. A category added
    there without a failure-type meaning here fails THIS test rather than
    silently classifying as UNKNOWN."""
    lb.assert_triage_mapping_total()


def test_preflight_check_names_are_the_real_ones():
    """The keys must be `preflight`'s own literal `CheckOutcome.name` values --
    a renamed check must break this mapping loudly, not stop classifying."""
    from dv_harness.preflight import _ALL_CHECKS, PreflightConfig

    class _Never:
        def __call__(self, cmd, timeout=60):
            return pf.CommandResult(ok=False, error="not run")

    real_names = {fn(_Never(), PreflightConfig()).name for fn in _ALL_CHECKS}
    assert set(lb.PREFLIGHT_CHECK_TO_FAILURE_TYPE) == real_names


# ==========================================================================
# Section 93: the classifier, on real evidence
# ==========================================================================
@pytest.mark.parametrize("text,expected,retryable", [
    # Real VCS compile output shape.
    ("Error-[SE] Syntax error\n  Following verilog source has syntax error",
     lb.FailureType.DETERMINISTIC.value, False),
    # Real FlexLM wording.
    ("lmgrd: Users of VCSRuntime: licensed number of users already reached",
     lb.FailureType.LICENSE.value, True),
    # Real farm resource exhaustion.
    ("write failed: No space left on device", lb.FailureType.RESOURCE.value, True),
    # Real LSF termination.
    ("TERM_RUNLIMIT: job killed after reaching LSF run time limit",
     lb.FailureType.INFRASTRUCTURE.value, True),
    # Real transport/API failure.
    ("HTTPSConnectionPool: Connection reset by peer",
     lb.FailureType.TRANSIENT.value, True),
    # Real tcsh unset-variable failure this project has actually hit.
    ("VCS_HOME: Undefined variable.", lb.FailureType.ENVIRONMENT.value, False),
    # Real gates.py verdict token.
    ("MISSING_EVIDENCE: no command_migration_integrity_gate block was submitted",
     lb.FailureType.DETERMINISTIC.value, False),
])
def test_classifier_reads_real_toolchain_text(text, expected, retryable):
    cls = lb.classify_failure(text)
    assert cls.failure_type == expected, cls.rule
    assert cls.retryable is retryable
    assert cls.rule and cls.rule != "no_rule_matched"
    assert cls.evidence["text_sample"].startswith(text[:20])


def test_unmatched_text_is_UNKNOWN_and_says_so():
    """"This harness could not tell" is a real answer and must stay distinct
    from every classified one."""
    cls = lb.classify_failure("the stage did not complete")
    assert cls.failure_type == lb.FailureType.UNKNOWN.value
    assert cls.rule == "no_rule_matched"


def test_a_real_preflight_FAIL_outranks_the_text():
    """A MEASURED resource condition beats an inference from prose. The
    outcome here is produced by the REAL `check_license()` against a real
    captured lmstat transcript with the feature fully checked out."""
    starved = REAL_LMSTAT_VCS_HEADER.replace(
        "Total of 0 licenses in use", "Total of 99 licenses in use")

    class _Runner:
        def __call__(self, cmd, timeout=60):
            return pf.CommandResult(ok=True, exit_code=0, stdout=starved)

    cfg = pf.PreflightConfig(license_server="2900@host-a")
    outcome = pf.check_license(_Runner(), cfg)
    assert outcome.status == "FAIL"

    cls = lb.classify_failure("Error-[SE] Syntax error", preflight_checks=[outcome])
    assert cls.failure_type == lb.FailureType.LICENSE.value
    assert cls.rule == "preflight:eda_license"
    assert cls.evidence["preflight_check"] == "eda_license"


def test_a_real_boundary_trace_attribution_outranks_the_text():
    """DUT-vs-testbench attribution is decided by the same first-differing-
    boundary-stage rule `tools/senior_dv/failure_attribution.py` uses and
    `dashboard._failure_attribution()` recomputes -- never by a log marker."""
    trace = [{"stage": "SEQUENCE", "expected": 1, "observed": 1},
             {"stage": "DUT_INTERNAL", "expected": 1, "observed": 0}]
    cls = lb.classify_failure("UVM_ERROR scoreboard mismatch", boundary_trace=trace)
    assert cls.failure_type == lb.FailureType.DUT.value
    assert cls.rule == "failure_attribution:DUT_BUG"

    tb = [{"stage": "CHECKER", "expected": 1, "observed": 0}]
    assert lb.classify_failure("x", boundary_trace=tb).failure_type == lb.FailureType.TEST.value


def test_an_agreeing_boundary_trace_claims_nothing():
    """A trace whose every stage agrees identifies no defect, so it must not
    override anything -- an all-agreeing trace is evidence of nothing."""
    trace = [{"stage": "DUT_INTERNAL", "expected": 1, "observed": 1}]
    cls = lb.classify_failure("Error-[SE] Syntax error", boundary_trace=trace)
    assert cls.failure_type == lb.FailureType.DETERMINISTIC.value


def test_a_uvm_error_alone_is_TEST_not_DUT():
    """The negative control for the rule above: claiming DUT from a UVM_ERROR
    line would be the unearned conclusion the Evidence Truth Rule forbids."""
    cls = lb.classify_failure("", triage_categories=["uvm_error"])
    assert cls.failure_type == lb.FailureType.TEST.value
    assert cls.rule == "sim_log_triage:uvm_error"


def test_signature_normalization_is_sim_log_analysis_own():
    """Two attempts at the SAME failure must share a signature (times, hex
    addresses and seeds differ every run), and two GENUINELY different failures
    must not -- the second half is what gives the breaker's
    REPEATED_IDENTICAL_FAILURE trigger any detection power."""
    a = lb.classify_failure("UVM_ERROR @ 1200 ns: mismatch at 0xdeadbeef seed=17")
    b = lb.classify_failure("UVM_ERROR @ 9999 ns: mismatch at 0xcafef00d seed=42")
    assert a.signature == b.signature
    c = lb.classify_failure("UVM_ERROR @ 1200 ns: unexpected packet length")
    assert c.signature != a.signature
    # and it really is the shared implementation, not a lookalike
    from dv_harness.sim_log_analysis import normalize_failure_signature
    assert lb.normalize_failure_text("t=1234 abc") == normalize_failure_signature("t=1234 abc")


# ==========================================================================
# Section 91: the unified budget engine
# ==========================================================================
def test_dimensions_are_section_91s_eleven():
    assert set(lb.DIMENSION_NAMES) == {
        "max_iterations", "max_wall_time", "max_lsf_jobs", "max_parallel_jobs",
        "max_retries", "max_failed_experiments", "max_compute",
        "max_license_usage", "max_token_cost", "max_external_calls",
        "max_code_change_scope"}


def test_the_existing_scattered_budgets_are_READ_not_retyped():
    """`max_retries`'s source must quote THIS project's real
    `policy.max_stage_retries`, and `max_external_calls`'s its real
    `inner_react_max_adapter_calls` -- change the config key and the source
    changes with it. Neither becomes a run-wide LIMIT, and that is the point:
    both are PER-NODE / PER-STAGE budgets, and reporting one as a run-wide cap
    would call every second retry-exhausted stage an exhausted run."""
    states = lb.build_dimension_states(
        {"policy": {"max_stage_retries": 7, "inner_react_max_adapter_calls": 9}})
    assert "policy.max_stage_retries (7)" in states["max_retries"].source
    assert states["max_retries"].limit is None
    assert "inner_react_max_adapter_calls (9)" in states["max_external_calls"].source


def test_no_dimension_is_bounded_by_default_and_every_one_says_why():
    """The honest state of this harness today: it enforces NO run-scoped loop
    budget. Every dimension must therefore be `None` AND carry a real reason --
    a `None` with no reason reads to a human as a bound that exists."""
    states = lb.build_dimension_states(BASE_CFG)
    lb.assert_sources_total(states)
    for name, st in states.items():
        assert st.limit is None, f"{name} must not be bounded by default"
        assert "NOT ENFORCED" in st.source or "NOT APPLICABLE" in st.source, name


def test_a_project_declared_limit_wins_and_says_so():
    states = lb.build_dimension_states(
        dict(BASE_CFG, loop_budget={"limits": {"max_wall_time": 3600}}))
    assert states["max_wall_time"].limit == 3600.0
    assert "loop_budget.limits.max_wall_time" in states["max_wall_time"].source


def test_spend_persists_and_reloads(root):
    cfg = dict(BASE_CFG, loop_budget={"limits": {"max_iterations": 3}})
    e = lb.BudgetEngine(root, cfg)
    e.spend("max_iterations", 2, note="two stages")
    assert lb.BudgetEngine(root, cfg).states["max_iterations"].spent == 2.0


def test_exhaustion_is_stamped_once_and_reports_the_loop_contract_state(root):
    cfg = dict(BASE_CFG, loop_budget={"limits": {"max_iterations": 1}})
    e = lb.BudgetEngine(root, cfg)
    d = e.spend("max_iterations", 1)
    assert d.exhausted is True
    assert d.loop_state == lc.LoopState.BUDGET_EXHAUSTED.value
    first_stamp = e.states["max_iterations"].exhausted_at
    e.spend("max_iterations", 1)
    assert e.states["max_iterations"].exhausted_at == first_stamp, (
        "exhausted_at must keep answering 'since when', not restamp every cycle")
    assert len(e.record["exhaustion_log"]) == 1


def test_spending_a_not_enforced_dimension_is_measured_never_exhausted(root):
    e = lb.BudgetEngine(root, BASE_CFG)
    d = e.spend("max_wall_time", 12345.0)
    assert d.spent == 12345.0
    assert d.exhausted is False and d.limit is None
    assert "NOT ENFORCED" in d.reason


def test_an_unknown_dimension_is_refused(root):
    with pytest.raises(lb.BudgetDimensionUnknownError):
        lb.BudgetEngine(root, BASE_CFG).spend("max_vibes", 1)


def test_a_budget_cannot_silently_reset(root):
    """Section 91's one hard rule, enforced: there is no code path in this
    module that zeroes a spend without producing a record naming who and why."""
    cfg = dict(BASE_CFG, loop_budget={"limits": {"max_iterations": 1}})
    e = lb.BudgetEngine(root, cfg)
    e.spend("max_iterations", 1)
    with pytest.raises(lb.BudgetResetRequiresReasonError):
        e.reset("max_iterations", reason="", by="peter")
    with pytest.raises(lb.BudgetResetRequiresReasonError):
        e.reset("max_iterations", reason="need more", by="")
    assert e.states["max_iterations"].spent == 1.0, "a refused reset must change nothing"

    entry = e.reset("max_iterations", reason="second sprint authorized", by="peter")
    assert entry["spent_before"] == 1.0 and entry["was_exhausted"] is True
    assert e.states["max_iterations"].spent == 0.0

    reloaded = lb.BudgetEngine(root, cfg)
    assert len(reloaded.record["resets"]) == 1
    assert reloaded.record["resets"][0]["by"] == "peter"
    assert reloaded.record["exhaustion_log"], (
        "the reset must not erase the record that the budget once ran out")


# ==========================================================================
# Section 93: the circuit breaker
# ==========================================================================
def test_breaker_trips_preserves_and_requires_a_recovery_condition(root):
    e = lb.BudgetEngine(root, BASE_CFG)
    assert e.breaker_open() is False
    assert e.blocking_reason() == ""

    e.trip_breaker("BUDGET_EXHAUSTION", "declared budget ran out",
                   evidence={"stage": "BUILD"})
    opened_at = e.breaker_state()["opened_at"]
    e.trip_breaker("OSCILLATION", "same fingerprint twice")
    assert e.breaker_state()["opened_at"] == opened_at, (
        "re-tripping must not restamp 'since when'")
    assert len(e.breaker_state()["triggers"]) == 2
    assert "CIRCUIT_BREAKER_OPEN" in e.blocking_reason()

    with pytest.raises(lb.BudgetResetRequiresReasonError):
        e.reset_breaker(reason="", by="peter")
    assert e.breaker_open() is True, "a refused recovery must leave the breaker OPEN"

    e.reset_breaker(reason="license pool refilled; farm drained", by="peter")
    assert e.breaker_open() is False
    hist = lb.BudgetEngine(root, BASE_CFG).record["breaker_history"]
    assert hist[0]["recovery_reason"].startswith("license pool refilled")
    assert len(hist[0]["triggers"]) == 2


def test_an_unknown_trigger_is_refused(root):
    with pytest.raises(ValueError):
        lb.BudgetEngine(root, BASE_CFG).trip_breaker("VIBES", "no")


def test_breaker_triggers_are_section_93s():
    assert set(lb.BREAKER_TRIGGERS) >= {
        "BUDGET_EXHAUSTION", "REPEATED_IDENTICAL_FAILURE", "OSCILLATION",
        "NO_PROGRESS", "EVIDENCE_INTEGRITY_FAILURE", "CRITICAL_ENVIRONMENT_FAILURE",
        "UNSAFE_MUTATION", "DESTRUCTIVE_ACTION"}


# ==========================================================================
# Section 92: license-aware pressure and prioritization
# ==========================================================================
def _license_outcome(stdout: str) -> pf.CheckOutcome:
    """A REAL `preflight.check_license()` outcome over real captured lmstat
    text -- never a hand-built CheckOutcome, so the pressure reading is
    computed from what the real check really produces."""
    class _Runner:
        def __call__(self, cmd, timeout=60):
            return pf.CommandResult(ok=True, exit_code=0, stdout=stdout)
    return pf.check_license(_Runner(), pf.PreflightConfig(license_server="2900@host-a"))


def test_the_real_captured_license_reading_is_no_pressure():
    """This project's own real captured `lmstat` transcript reports 99 issued /
    0 in use. That is the negative control for every deferral test below: at a
    real healthy reading, nothing defers."""
    p = lb.pressure_from_checks([_license_outcome(REAL_LMSTAT_VCS_HEADER)])
    assert p.level == lb.PRESSURE_NONE
    assert p.license_headroom == pytest.approx(1.0)


def test_a_scarce_but_not_full_license_pool_is_ELEVATED():
    """The band degradation.py deliberately says nothing about: still PASSing
    (not fully checked out), but nearly gone."""
    scarce = REAL_LMSTAT_VCS_HEADER.replace(
        "Users of VCSRuntime:  (Total of 99 licenses issued;  Total of 0 licenses in use)",
        "Users of VCSRuntime:  (Total of 99 licenses issued;  Total of 95 licenses in use)")
    outcome = _license_outcome(scarce)
    assert outcome.status == "PASS", "still not fully checked out -- degradation would not trip"
    p = lb.pressure_from_checks([outcome], license_pressure_fraction=0.10)
    assert p.level == lb.PRESSURE_ELEVATED
    assert p.license_headroom == pytest.approx(4 / 99.0)


def test_a_fully_checked_out_pool_is_CRITICAL():
    starved = REAL_LMSTAT_VCS_HEADER.replace("Total of 0 licenses in use",
                                             "Total of 99 licenses in use")
    p = lb.pressure_from_checks([_license_outcome(starved)])
    assert p.level == lb.PRESSURE_CRITICAL


def test_nothing_measured_is_UNKNOWN_never_NONE():
    """Section 92: do not invent availability. "Nobody measured" and "measured,
    and there is room" are different facts."""
    skipped = pf.check_license(lambda c, t=60: pf.CommandResult(ok=True),
                               pf.PreflightConfig(require_license_configured=False))
    assert skipped.status == "SKIP"
    assert lb.pressure_from_checks([skipped]).level == lb.PRESSURE_UNKNOWN
    assert lb.pressure_from_checks([]).level == lb.PRESSURE_UNKNOWN
    assert lb.measure_resource_pressure(BASE_CFG).level == lb.PRESSURE_UNKNOWN


def test_measure_resource_pressure_probes_nothing_without_an_injected_runner():
    """It must be structurally impossible for a default call to reach a real
    license server -- the same evidence-based arming rule degradation uses."""
    p = lb.measure_resource_pressure(BASE_CFG)
    assert p.level == lb.PRESSURE_UNKNOWN
    assert "nothing was measured" in p.reason


def test_prioritization_defers_only_scarce_resource_consuming_non_critical_work():
    elevated = lb.ResourcePressure(lb.PRESSURE_ELEVATED, "4/99 left", license_headroom=0.04)
    none = lb.ResourcePressure(lb.PRESSURE_NONE, "plenty", license_headroom=1.0)

    # 1. no measured pressure -> proceed, whatever the stage is
    assert lb.prioritize_stage("BUILD", none,
                               consumes_scarce_resource=True).decision == lb.PRIORITY_PROCEED
    # 2. consumes none of the scarce resource -> proceed
    assert lb.prioritize_stage("IMPLEMENT", elevated,
                               consumes_scarce_resource=False).decision == lb.PRIORITY_PROCEED
    # 3. critical signoff-family work proceeds under pressure, by policy
    d = lb.prioritize_stage("SIGNOFF", elevated, consumes_scarce_resource=True)
    assert d.decision == lb.PRIORITY_PROCEED_CRITICAL and d.deferred is False
    # 4. everything else consuming it defers
    d = lb.prioritize_stage("BUILD", elevated, consumes_scarce_resource=True)
    assert d.decision == lb.PRIORITY_DEFER and d.deferred is True
    assert "4/99 left" in d.reason


def test_unknown_pressure_never_defers():
    """Deferring real work because nothing was measured would be inventing
    scarcity, which is the same error as inventing availability."""
    unknown = lb.ResourcePressure(lb.PRESSURE_UNKNOWN, "nothing measured")
    assert lb.prioritize_stage("BUILD", unknown,
                               consumes_scarce_resource=True).decision == lb.PRIORITY_PROCEED


# ==========================================================================
# The retry decision
# ==========================================================================
def test_retry_decision_defaults_to_the_existing_behaviour():
    """With no opt-in config, a non-retryable classification is RECORDED and
    the existing policy.max_stage_retries budget still decides."""
    cls = lb.classify_failure("Error-[SE] Syntax error")
    d = lb.decide_retry(cls, repeats=3, cfg=BASE_CFG)
    assert d.retry is True and d.enforced is False
    assert "Recorded, not enforced" in d.reason


def test_enforce_retry_policy_stops_a_non_retryable_failure():
    cfg = dict(BASE_CFG, loop_budget={"enforce_retry_policy": True})
    d = lb.decide_retry(lb.classify_failure("Error-[SE] Syntax error"), cfg=cfg)
    assert d.retry is False and d.enforced is True
    assert d.failure_type == lb.FailureType.DETERMINISTIC.value


def test_enforce_retry_policy_still_retries_a_transient_failure():
    """The negative control: enforcement must not stop everything, only the
    failures whose evidence says repeating cannot help."""
    cfg = dict(BASE_CFG, loop_budget={"enforce_retry_policy": True})
    d = lb.decide_retry(lb.classify_failure("Connection reset by peer"), cfg=cfg)
    assert d.retry is True


def test_repeated_identical_failure_threshold_stops_even_a_retryable_type():
    """Section 93's own example. A TRANSIENT failure is normally worth another
    attempt -- an identical one, N times running, is not."""
    cfg = dict(BASE_CFG, loop_budget={"repeated_identical_failure_threshold": 2})
    cls = lb.classify_failure("Connection reset by peer")
    assert lb.decide_retry(cls, repeats=1, cfg=cfg).retry is True
    d = lb.decide_retry(cls, repeats=2, cfg=cfg)
    assert d.retry is False and "REPEATED_IDENTICAL_FAILURE" in d.reason


# ==========================================================================
# The REAL engine path
# ==========================================================================
def _run_real_loop(project: Path):
    """Drive the REAL DVHarness.loop() over the REAL shipped graph until
    COMMAND_PATTERN's retry budget is spent. The gate really runs; the stub
    adapter submits no evidence while the migration manifest is absent."""
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("verify the command pattern migration")
    return h


def test_a_real_loop_records_a_real_classification_and_ledger_spend(project):
    """Default configuration: nothing is enforced, and the run still produces a
    real classification and a real unified ledger entry -- the RECORD-FIRST
    half, on the real path, with no behaviour change."""
    h = _run_real_loop(project)
    ss = h.state.stages[FIXTURE_STAGE]
    assert ss["attempts"] > h.cfg["policy"]["max_stage_retries"], (
        "the loop must actually have spent the retry budget")

    spent = _events(project, "LOOP_BUDGET_SPENT")
    assert spent, "loop() recorded no LOOP_BUDGET_SPENT event"
    ev = spent[-1]
    assert ev["classification"]["failure_type"] in lb.FAILURE_TYPE_VALUES
    assert ev["classification"]["signature"], "the classification must carry its signature"
    assert ev["exhausted"] == [], "nothing is declared, so nothing can be exhausted"
    assert ev["loop_state"] is None

    # the classification is on the stage state too, not only in the event log
    assert ss["failure_type"] in lb.FAILURE_TYPE_VALUES
    assert ss["failure_signature_repeats"] >= 1

    # and a real ledger exists on disk carrying the real spend
    ledger = lb.BudgetEngine(project, h.cfg)
    assert ledger.states["max_retries"].spent >= 1
    assert ledger.states["max_iterations"].spent >= 1
    assert ledger.breaker_open() is False


def test_the_real_failure_here_repeats_identically_across_attempts(project):
    """The signature really is stable across the loop's own real attempts --
    which is what makes REPEATED_IDENTICAL_FAILURE a fact about this run rather
    than a threshold nothing can reach.

    The real fixture failure (the stub agent submits no evidence, the real gate
    rejects the stage) is byte-identical every attempt, so all three attempts
    of the default retry budget collapse onto ONE signature."""
    h = _run_real_loop(project)
    attempts = h.state.stages[FIXTURE_STAGE]["attempts"]
    assert h.state.stages[FIXTURE_STAGE]["failure_signature_repeats"] == attempts, (
        "every real attempt carried the same normalized signature, so the repeat "
        "count must equal the attempt count")
    ev = _events(project, "LOOP_BUDGET_SPENT")[-1]
    assert ev["classification"]["repeats"] == attempts


def test_a_genuinely_different_failure_restarts_the_repeat_count(project):
    """The negative control for the test above: the repeat counter must count
    IDENTICAL failures, not attempts. A different failure on the next attempt
    resets it to 1, or REPEATED_IDENTICAL_FAILURE would fire on any stage that
    simply failed twice for two different reasons."""
    h = harness_factory(project)
    h.state.current_stage = FIXTURE_STAGE
    ss = h.state.stages[FIXTURE_STAGE]
    ss["blocking_reason"] = "Error-[SE] Syntax error in foo.sv"
    h.store.save(h.state)
    assert h._classify_stage_failure(FIXTURE_STAGE)["repeats"] == 1
    assert h._classify_stage_failure(FIXTURE_STAGE)["repeats"] == 2
    ss["blocking_reason"] = "write failed: No space left on device"
    assert h._classify_stage_failure(FIXTURE_STAGE)["repeats"] == 1


def test_a_declared_budget_really_exhausts_and_trips_the_breaker(project):
    """The enforcement half, end to end on the real engine: declare a real
    run-scoped budget, drive a real loop(), and the ledger exhausts, the
    breaker trips, and the NEXT loop() refuses to start any new work."""
    _write_config(project, {"limits": {"max_iterations": 1}})
    h = _run_real_loop(project)

    ev = _events(project, "LOOP_BUDGET_SPENT")[-1]
    assert ev["exhausted"] == ["max_iterations"]
    assert ev["loop_state"] == lc.LoopState.BUDGET_EXHAUSTED.value
    assert ev["breaker"]["state"] == lb.BREAKER_OPEN
    assert ev["breaker"]["triggers"][0]["trigger"] == "BUDGET_EXHAUSTION"

    # STOP NEW ACTIONS: a fresh loop() over the same project blocks immediately.
    h2 = harness_factory(project)
    h2.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h2.state.current_stage = FIXTURE_STAGE
    h2.store.save(h2.state)
    h2.loop("try again")
    assert h2.state.stages[FIXTURE_STAGE]["attempts"] == 0, (
        "an OPEN breaker must stop NEW actions -- no attempt may be spent")
    assert h2.state.overall_status == Status.BLOCKED.value
    blocked = _events(project, "CIRCUIT_BREAKER_BLOCKED")
    assert blocked and blocked[-1]["breaker"]["state"] == lb.BREAKER_OPEN
    assert "CIRCUIT_BREAKER_OPEN" in h2.state.stages[FIXTURE_STAGE]["blocking_reason"]


def test_the_recovery_condition_really_releases_the_loop(project):
    """REQUIRE RECOVERY CONDITION: only a recorded reason+actor reopens the
    loop, and then it really runs again."""
    _write_config(project, {"limits": {"max_iterations": 1}})
    _run_real_loop(project)

    code, payload = lb.execute_verb(project, "breaker-reset", reason="", by="")
    assert code == 1 and payload["error"] == "RECOVERY_REQUIRES_REASON_AND_BY"

    code, payload = lb.execute_verb(project, "breaker-reset",
                                    reason="budget raised for this sprint", by="peter")
    assert code == 0 and payload["breaker"]["state"] == lb.BREAKER_CLOSED
    assert payload["history"][0]["recovery_reason"].startswith("budget raised")

    # the spend itself is still recorded -- closing the breaker is not a reset
    assert lb.BudgetEngine(project, None).states["max_iterations"].spent >= 1

    h = harness_factory(project)
    h.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("try again after the recovery condition")
    assert h.state.stages[FIXTURE_STAGE]["attempts"] >= 1, (
        "a closed breaker must let the loop attempt work again")


def test_human_override_still_outranks_the_breaker(project):
    """The breaker is checked AFTER both Human Override checks, so a takeover
    always wins -- an operator must never have to clear a breaker to take
    control back."""
    from dv_harness.control_plane import ControlPlane

    _write_config(project, {"limits": {"max_iterations": 1}})
    _run_real_loop(project)
    assert lb.BudgetEngine(project, None).breaker_open() is True

    ControlPlane(project).takeover(FIXTURE_STAGE, "operator taking control", "peter")
    h = harness_factory(project)
    h.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("try again")
    ss = h.state.stages[FIXTURE_STAGE]
    assert ss["status"] == Status.WAIT_USER.value
    assert "TAKEOVER" in ss["blocking_reason"]


def test_enforce_retry_policy_shortens_the_real_loop_and_the_default_does_not(project):
    """The behaviour-changing half, with its negative control over the IDENTICAL
    fixture: with enforcement off the real loop spends its full retry budget;
    with it on, the same real failure stops after one attempt and says why."""
    default_h = _run_real_loop(project)
    default_attempts = default_h.state.stages[FIXTURE_STAGE]["attempts"]
    assert default_attempts == default_h.cfg["policy"]["max_stage_retries"] + 1

    second = make_fixture_project(Path(tempfile.mkdtemp()))
    try:
        _write_config(second, {"enforce_retry_policy": True})
        h = _run_real_loop(second)
        ss = h.state.stages[FIXTURE_STAGE]
        assert ss["attempts"] == 1, (
            f"enforcement must stop after the first non-retryable failure, "
            f"got {ss['attempts']} (default path spent {default_attempts})")
        refused = _events(second, "LOOP_RETRY_REFUSED")
        assert refused and refused[-1]["retry"] is False
        assert refused[-1]["failure_type"] == lb.FailureType.DETERMINISTIC.value
        assert "RETRY_REFUSED" in ss["blocking_reason"]
    finally:
        shutil.rmtree(second, ignore_errors=True)


def test_a_repeated_identical_failure_threshold_trips_the_breaker_on_the_real_loop(project):
    """Section 93's own example, on the real engine: the same real gate failure
    on consecutive attempts, counted off the same normalized signature
    `sim_log_analysis` produces."""
    _write_config(project, {"repeated_identical_failure_threshold": 1})
    _run_real_loop(project)
    ev = _events(project, "LOOP_BUDGET_SPENT")[-1]
    assert ev["breaker"]["state"] == lb.BREAKER_OPEN
    assert any(t["trigger"] == "REPEATED_IDENTICAL_FAILURE"
               for t in ev["breaker"]["triggers"])


def test_trip_on_oscillation_uses_loop_contracts_own_detector_on_the_real_loop(project):
    """Opt-in, and computed by `loop_contract.
    detect_oscillation_from_debug_loop_history()` over the SAME
    `debug_loop_history` entries `_record_debug_loop_round()` writes -- one
    definition of an oscillation fingerprint, not two.

    Its own negative control is the first round: ONE retry-exhaustion is one
    fingerprint, which is below the 2-INDEPENDENT-observations threshold, so
    nothing trips until the same node exhausts a second time."""
    _write_config(project, {"trip_on_oscillation": True})
    h = _run_real_loop(project)
    first = _events(project, "LOOP_BUDGET_SPENT")[-1]
    assert first["oscillation"]["oscillating"] is False
    assert lb.BudgetEngine(project, None).breaker_open() is False, (
        "one exhaustion is not an oscillation")

    h.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("second round over the same node")

    second = _events(project, "LOOP_BUDGET_SPENT")[-1]
    assert second["oscillation"]["oscillating"] is True
    assert second["breaker"]["state"] == lb.BREAKER_OPEN
    assert any(t["trigger"] == "OSCILLATION" for t in second["breaker"]["triggers"])

    # and the detector really is the shared one, over the entries the engine wrote
    entries = (h.blackboard.read_debug_loop_history() or {}).get("entries") or []
    assert lc.detect_oscillation_from_debug_loop_history(entries)["oscillating"] is True


def test_oscillation_does_not_trip_by_default(project):
    """The default must leave `loop()`'s existing FAIL-edge routing alone --
    sections 88-90's RESPONSE half is not built, and this must not become it by
    accident."""
    h = _run_real_loop(project)
    h.state.stages[FIXTURE_STAGE]["attempts"] = 0
    h.state.current_stage = FIXTURE_STAGE
    h.store.save(h.state)
    h.loop("second round over the same node")
    entries = (h.blackboard.read_debug_loop_history() or {}).get("entries") or []
    assert lc.detect_oscillation_from_debug_loop_history(entries)["oscillating"] is True, (
        "the run really did oscillate -- so a default that stays CLOSED is a decision, "
        "not an absence of evidence")
    assert lb.BudgetEngine(project, None).breaker_open() is False
    assert "oscillation" not in _events(project, "LOOP_BUDGET_SPENT")[-1]


def test_the_state_file_and_the_cli_agree_about_the_same_project(project):
    """The CLI/status path and the engine's own ledger must not be two
    different answers about the same run."""
    _write_config(project, {"limits": {"max_iterations": 1}})
    _run_real_loop(project)
    code, payload = lb.execute_verb(project, "status")
    assert code == 2, "exit 2 while work is actually stopped"
    assert payload["exhausted"] == ["max_iterations"]
    assert payload["loop_state"] == lc.LoopState.BUDGET_EXHAUSTED.value
    assert payload["breaker"]["state"] == lb.BREAKER_OPEN
    assert payload["dimensions"]["max_retries"]["spent"] >= 1


# ==========================================================================
# Front door
# ==========================================================================
def test_cli_dimensions_reports_every_dimension_with_a_source(root):
    code, payload = lb.execute_verb(root, "dimensions")
    assert code == 0
    assert set(payload["dimensions"]) == set(lb.DIMENSION_NAMES)
    assert set(payload["failure_types"]) == set(lb.FAILURE_TYPE_VALUES)
    assert set(payload["breaker_triggers"]) == set(lb.BREAKER_TRIGGERS)
    for st in payload["dimensions"].values():
        assert st["source"].strip()


def test_cli_status_on_a_clean_project_exits_zero(root):
    code, payload = lb.execute_verb(root, "status")
    assert code == 0
    assert payload["exhausted"] == [] and payload["loop_state"] is None
    assert payload["breaker"]["state"] == lb.BREAKER_CLOSED


def test_cli_classify_requires_text_and_shows_its_rule(root):
    assert lb.execute_verb(root, "classify")[0] == 1
    code, payload = lb.execute_verb(root, "classify", text="No space left on device")
    assert code == 0 and payload["failure_type"] == lb.FailureType.RESOURCE.value


def test_cli_reset_refuses_without_a_reason_and_records_with_one(root):
    cfg = dict(BASE_CFG, loop_budget={"limits": {"max_iterations": 1}})
    lb.BudgetEngine(root, cfg).spend("max_iterations", 1)
    assert lb.execute_verb(root, "reset", cfg=cfg, dimension="max_iterations",
                           reason="", by="peter")[0] == 1
    assert lb.execute_verb(root, "reset", cfg=cfg, dimension="nope",
                           reason="r", by="peter")[1]["error"] == "UNKNOWN_DIMENSION"
    code, payload = lb.execute_verb(root, "reset", cfg=cfg, dimension="max_iterations",
                                    reason="sprint 2 budget approved", by="peter")
    assert code == 0 and payload["reset"]["spent_before"] == 1.0


def test_cli_breaker_reset_refuses_a_breaker_that_is_not_open(root):
    code, payload = lb.execute_verb(root, "breaker-reset", reason="r", by="peter")
    assert code == 1 and payload["error"] == "BREAKER_NOT_OPEN"


def test_unknown_verb_names_the_known_ones(root):
    code, payload = lb.execute_verb(root, "vibes")
    assert code == 1 and "status" in payload["known"]


def test_the_cli_verb_is_registered_and_runs_as_a_real_subprocess(project):
    """The front door really exists -- `dv-harness loop-budget` is a registered
    verb, not just an importable function."""
    import subprocess
    import sys
    out = subprocess.run(
        [sys.executable, "-m", "dv_harness.loop_budget", "dimensions",
         "--project-root", str(project)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]))
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout)
    assert set(payload["dimensions"]) == set(lb.DIMENSION_NAMES)


# ==========================================================================
# The boundary: nothing here weakens a human-approval gate
# ==========================================================================
def test_this_module_touches_no_approval_mechanism():
    """A budget engine that could mint or bypass an approval would be a far
    worse defect than the gap it closes. Asserted against the source, so a
    future edit that reaches for one fails this test."""
    import io
    import tokenize

    path = Path(__file__).resolve().parents[1] / "dv_harness" / "loop_budget.py"
    # CODE only: docstrings and comments legitimately NAME these gates (saying
    # which ones stay untouched is the point of that prose), so scanning the raw
    # text would assert the opposite of what this test means.
    code_tokens = []
    with io.open(path, encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                            tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                continue
            code_tokens.append(tok.string)
    code = " ".join(code_tokens)
    for forbidden in ("ControlPlane", "approve", "can_signoff", "assert_human_approval",
                      "HumanApprovalRequiredError", "ProductionWriteNotAuthorizedError",
                      "answer_question", "save_config"):
        assert forbidden not in code, f"loop_budget.py must not reach for {forbidden}"


def test_the_breaker_authorizes_nothing_it_only_stops(project):
    """Closing the breaker lets the loop attempt work again; it grants no
    permission. The SIGNOFF gate that stood before it still stands."""
    from dv_harness.policy import can_signoff

    _write_config(project, {"limits": {"max_iterations": 1}})
    h = _run_real_loop(project)
    before = can_signoff(h.state, h.cfg)
    lb.execute_verb(project, "breaker-reset", reason="recovered", by="peter")
    after = can_signoff(StateStore(project).load(), h.cfg)
    assert before[0] == after[0], (
        "a breaker recovery must not change what can_signoff() concludes")
