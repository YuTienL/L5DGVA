"""LOOP_ENGINEERING sections 88-90: convergence classification, plateau
detection, oscillation / no-progress detection (`dv_harness/loop_convergence.py`).

WHAT THESE TESTS ARE FOR. Not "the classifier returns a string". The five
things that can actually go wrong with this mechanism are:

  1. **A verdict that cannot be produced.** A seven-value taxonomy is worthless
     if three of the values are unreachable, so every one of section 88's
     verdicts is driven out of a real series, and PLATEAU/OSCILLATING are
     additionally driven out of a REAL evidence database written through the
     REAL production write path (`regression_reporter.
     _write_reconciliation_evidence_if_configured()` and
     `dashboard.append_coverage_history_sample()` -- the exact functions
     `lsf_client` and `engine.py` call).
  2. **A verdict computed from a fabricated series.** A day with no coverage
     evidence must never be read as 0% -- that alone would manufacture a
     REGRESSION out of a quiet day -- and a project with no evidence database
     must report UNKNOWN, never "no plateau".
  3. **A detector with no detection power.** A flat-looking spike-and-crash must
     NOT read as a plateau, an intermittent same-SHA test must NOT read as the
     loop oscillating, and a long green streak must not inflate the fix-revert
     count. Each of those has its own negative control here.
  4. **The bridge to LOOP-1 drifting.** PLATEAU/OSCILLATING must reach a real
     `LoopObservation` over a real `state.json`, along legal section-86 edges,
     and `PLATEAU_NOT_EVALUATED` must survive intact for a project with no
     series -- that distinction is the whole reason it exists.
  5. **The observation becoming a mutating act.** Classifying must escalate
     nothing: no question-queue entry, no ControlPlane approval, no write of
     any kind. The plateau investigation NAMES the real escalator and does not
     take it.

Nothing here runs a build, a regression or an LSF submission: every job/verdict
row is written by handing a synthetic `lsf_client.JobState` to the real
evidence-write function, and every coverage row comes from a synthetic
`summary.json`.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from dv_harness import coverage_analysis
from dv_harness import loop_contract as lc
from dv_harness import loop_convergence as lcv
from dv_harness import trend_analysis as ta
from dv_harness.models import Status

duckdb = pytest.importorskip("duckdb")

from dv_harness import dashboard  # noqa: E402  (after the duckdb skip)
from dv_harness import lsf_client  # noqa: E402
from dv_harness import regression_reporter as rr  # noqa: E402
from dv_harness.evidence_db import EvidenceStore, default_db_path  # noqa: E402

REQUIREMENTS_HEADER = ("REQ_ID,SOURCE,SCOPE,VPLAN_ID,SCENARIO_ID,COMMAND_ID,PATTERN_ID,"
                       "CHECKER_ID,COVERAGE_ID,RESULT,STATUS,EVIDENCE")


# --------------------------------------------------------------------------
# helpers -- all drive the REAL production write paths
# --------------------------------------------------------------------------
@pytest.fixture
def root():
    tmp = Path(tempfile.mkdtemp())
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def series(values):
    """A ProgressPoint series with real, distinct labels."""
    return [lcv.ProgressPoint(label=f"2026-09-{i + 1:02d}", value=float(v))
            for i, v in enumerate(values)]


def _store(root):
    return EvidenceStore(default_db_path(root))


def _record_verdict(root, pattern, passed, *, job_id, git_sha=None, seed=None):
    """The REAL production evidence write path for one job."""
    state = lsf_client.JobState(
        job_id=job_id, pattern=pattern,
        lsf_status="DONE" if passed else "EXIT",
        sim_status="PASS" if passed else "FAIL",
        seed=None if seed is None else str(seed),
        git_sha=git_sha)
    rr._write_reconciliation_evidence_if_configured(root, {job_id: (state, [])})


def _write_coverage_summary(root, percent, *, bins_total=1000):
    p = Path(root) / ".dv-harness" / "coverage" / "summary.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"categories": [
        {"name": "functional", "percent": percent,
         "bins_total": bins_total, "bins_hit": int(round(bins_total * percent / 100.0))}]}),
        encoding="utf-8")


def _ingest_coverage_day(root, percent, day):
    """One real coverage day: the REAL function engine.py's
    `_append_coverage_history_sample()` calls, then ONLY the rows that call
    just inserted back-dated, so a multi-day curve is testable. Keyed on the
    row id watermark rather than on the timestamp, so back-dating day N never
    moves day N-1's rows with it. Only the store clock is manipulated -- every
    row's CONTENT comes from the real write path."""
    watermark = 0
    if default_db_path(root).exists():
        with _store(root) as store:
            rows = store.query("SELECT max(id) FROM coverage_samples")
        watermark = int((rows and rows[0][0]) or 0)
    _write_coverage_summary(root, percent)
    dashboard.append_coverage_history_sample(root, percent)
    with _store(root) as store:
        store.query(f"UPDATE coverage_samples SET ingested_at = TIMESTAMP "
                    f"'{day} 12:00:00' WHERE id > {watermark}")


def _coverage_days(root, day_percent_pairs):
    for day, percent in day_percent_pairs:
        _ingest_coverage_day(root, percent, day)


def _write_registry(root, rows):
    p = Path(root) / ".dv-harness" / "requirements.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(REQUIREMENTS_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


# ==========================================================================
# 1. The vocabulary: total, and every verdict really reachable
# ==========================================================================
def test_every_section_88_verdict_has_a_decided_loop_state_meaning():
    """The same totality technique `assert_status_mapping_total()` uses: a new
    verdict added without deciding what it means for a loop fails here rather
    than falling silently through every caller's `if verdict in (...)`."""
    lcv.assert_verdict_mapping_total()
    assert set(lcv.VERDICT_TO_LOOP_STATE) == set(lcv.CONVERGENCE_VERDICTS)


def test_a_verdict_added_without_a_loop_meaning_fails_the_totality_check(monkeypatch):
    monkeypatch.setattr(lcv, "CONVERGENCE_VERDICTS",
                        lcv.CONVERGENCE_VERDICTS + ("STALLED_FOREVER",))
    with pytest.raises(AssertionError) as exc:
        lcv.assert_verdict_mapping_total()
    assert "STALLED_FOREVER" in str(exc.value)


@pytest.mark.parametrize("name,values,expected", [
    ("steady climb",          [10, 25, 40, 55],              lcv.CONVERGING),
    ("gain inside the band",  [80.0, 80.2, 80.4, 80.7],      lcv.SLOW_CONVERGENCE),
    ("stopped moving",        [90.0, 90.2, 89.9, 90.1, 90.0], lcv.PLATEAU),
    ("spike then crash",      [80, 90, 80.2, 80.1],          lcv.NO_PROGRESS),
    ("coverage went down",    [90, 88, 85, 80],              lcv.REGRESSION),
    ("undone as fast as won", [50, 60, 50, 60],              lcv.OSCILLATING),
    ("one sample",            [50],                          lcv.UNKNOWN),
])
def test_every_section_88_verdict_is_reachable_from_a_real_series(name, values, expected):
    """A seven-value taxonomy in which three values can never be produced is a
    vocabulary, not a classifier."""
    v = lcv.classify_convergence(series(values))
    assert v.verdict == expected, f"{name}: {v.verdict} ({v.reason})"


def test_the_verdict_carries_the_numbers_it_was_computed_from():
    """Show your work: a reader must be able to re-derive the verdict without
    trusting it, exactly as LoopObservation.evidence requires."""
    v = lcv.classify_convergence(series([50, 60, 50, 60]))
    assert v.window_values == [50.0, 60.0, 50.0, 60.0]
    assert v.deltas == [10.0, -10.0, 10.0]
    assert v.net_delta == 10.0
    assert v.significant_reversals == 2
    assert v.thresholds["oscillation_min_reversals"] == \
        lcv.DEFAULT_OSCILLATION_MIN_REVERSALS


# ==========================================================================
# 2. Detection power: the negative controls
# ==========================================================================
def test_this_classifier_and_coverage_analysis_share_one_notion_of_flat():
    """Two modules disagreeing about what counts as flat would let one report
    PLATEAU while the other reported IMPROVING over the identical series."""
    assert lcv.DEFAULT_NOISE_FLOOR_PERCENT == \
        coverage_analysis.FLAT_TREND_TOLERANCE_PERCENT
    values = [90.0, 90.2, 89.9, 90.1]
    trend = coverage_analysis.compute_coverage_trend(
        [{"timestamp": i, "percent": v} for i, v in enumerate(values)])
    assert trend["trend"] == "FLAT"
    assert lcv.classify_convergence(series(values)).verdict in (
        lcv.PLATEAU, lcv.NO_PROGRESS)


def test_a_spike_and_crash_is_not_a_plateau():
    """The plateau run counts ABSOLUTE movement, not gain. Counting a large
    DECLINE as 'did not gain' would let a series whose net is flat only because
    a spike and a crash cancel report a plateau it never had."""
    v = lcv.classify_convergence(series([80, 90, 80.2, 80.1]))
    assert v.verdict == lcv.NO_PROGRESS
    assert v.flat_run_samples == 2 < lcv.DEFAULT_PLATEAU_WINDOW


def test_one_flat_interval_is_a_quiet_day_not_a_plateau():
    """PLATEAU needs 2 consecutive no-movement INTERVALS -- the same
    '2 INDEPENDENT observations' bar the rest of this codebase uses."""
    two_samples = lcv.classify_convergence(series([90.0, 90.1]))
    assert two_samples.verdict == lcv.NO_PROGRESS
    assert two_samples.flat_run_samples == 2
    three_samples = lcv.classify_convergence(series([90.0, 90.1, 90.0]))
    assert three_samples.verdict == lcv.PLATEAU
    assert lcv.DEFAULT_PLATEAU_WINDOW == lc.DEFAULT_OSCILLATION_REPEAT_THRESHOLD + 1


def test_noise_inside_the_tolerance_band_has_no_direction_to_reverse():
    """Counting sub-threshold jitter as direction reversals would make every
    flat series report OSCILLATING."""
    v = lcv.classify_convergence(series([90.0, 90.2, 89.9, 90.1, 90.0]))
    assert v.significant_reversals == 0
    assert v.verdict == lcv.PLATEAU


def test_a_plateau_run_is_counted_over_the_whole_series_not_just_the_window():
    """Truncating the run at the window would cap a long plateau at the window
    size and make a six-day plateau indistinguishable from a fresh one."""
    v = lcv.classify_convergence(series([88.0] * 8))
    assert v.window_used == lcv.DEFAULT_CONVERGENCE_WINDOW
    assert v.flat_run_samples == 8
    assert v.verdict == lcv.PLATEAU


def test_a_single_sample_is_unknown_never_a_guessed_trend():
    """The same floor `compute_coverage_trend()` enforces."""
    v = lcv.classify_convergence(series([77.0]))
    assert v.verdict == lcv.UNKNOWN
    assert v.reason == lcv.INSUFFICIENT_HISTORY
    assert v.loop_state is None


def test_a_day_with_no_coverage_evidence_is_skipped_never_read_as_zero():
    """`DailyPoint.coverage_percent` is None -- never 0 -- for a day with no
    evidence. Reading that None as 0% would manufacture a REGRESSION out of a
    quiet day."""
    class _Day:
        def __init__(self, day, pct):
            self.day, self.coverage_percent = day, pct

    days = [_Day("2026-09-01", 70.0), _Day("2026-09-02", None), _Day("2026-09-03", 85.0)]
    points = lcv.points_from_daily_rollup(days)
    assert [p.value for p in points] == [70.0, 85.0]
    assert lcv.classify_convergence(points).verdict == lcv.CONVERGING


# ==========================================================================
# 3. End to end over a REAL evidence database
# ==========================================================================
def test_a_real_four_day_flat_coverage_curve_classifies_as_plateau(root):
    """Real `dashboard.append_coverage_history_sample()` writes -- the exact
    function engine.py calls on a gate-verified COVERAGE_CLOSURE PASS -- read
    back through `trend_analysis.daily_rollup()`'s own bins-weighted curve."""
    _coverage_days(root, [("2026-09-01", 88.0), ("2026-09-02", 88.1),
                          ("2026-09-03", 88.0), ("2026-09-04", 88.2)])

    report = lcv.classify_loop_convergence(root)
    assert report.available is True
    assert report.verdict == lcv.PLATEAU
    assert report.loop_state == lc.LoopState.PLATEAU.value
    assert report.sources["series_points"] == 4
    assert report.convergence["flat_run_samples"] == 4


def test_a_real_rising_coverage_curve_is_the_positive_control(root):
    """Without this, PLATEAU above could be an artifact of the harness rather
    than a measurement of the series."""
    _coverage_days(root, [("2026-09-01", 40.0), ("2026-09-02", 55.0),
                          ("2026-09-03", 70.0), ("2026-09-04", 85.0)])

    report = lcv.classify_loop_convergence(root)
    assert report.verdict == lcv.CONVERGING
    assert report.loop_state == lc.LoopState.CONVERGING.value
    assert report.convergence["net_delta"] == 45.0


def test_a_project_with_no_evidence_database_reports_unknown_not_no_plateau(root):
    """A detector that never ran and a detector that ran and found nothing are
    different facts. This is the one that matters most: reporting 'no plateau'
    here would be the unearned claim PLATEAU_NOT_EVALUATED exists to prevent."""
    report = lcv.classify_loop_convergence(root)
    assert report.available is False
    assert report.verdict == lcv.UNKNOWN
    assert report.reason == lcv.NO_EVIDENCE_DATABASE
    assert report.loop_state is None


def test_an_evidence_db_with_jobs_but_no_coverage_reports_a_distinct_reason(root):
    """'No database at all' and 'a database with no coverage sample in it' are
    different operator problems with different fixes."""
    _record_verdict(root, "pat_a", True, job_id=1, git_sha="a" * 40)
    report = lcv.classify_loop_convergence(root)
    assert report.available is False
    assert report.reason == lcv.NO_COVERAGE_SAMPLES
    assert report.reason != lcv.NO_EVIDENCE_DATABASE


def test_classification_never_creates_or_migrates_the_evidence_database(root):
    """Read-only, exactly as `trend_analysis.trend_report()` opens it."""
    lcv.classify_loop_convergence(root)
    assert not default_db_path(root).exists()


# ==========================================================================
# 4. Section 90: repeat-fix-revert over the REAL verdict write path
# ==========================================================================
def test_a_pattern_fixed_and_rebroken_twice_is_a_real_oscillation(root):
    """FAIL -> PASS -> FAIL -> PASS -> FAIL across DISTINCT commits: two
    completed fix-revert cycles, a real fix that did not hold, twice."""
    for i, (passed, sha) in enumerate([
            (False, "a" * 40), (True, "b" * 40), (False, "c" * 40),
            (True, "d" * 40), (False, "e" * 40)]):
        _record_verdict(root, "pat_link_up", passed, job_id=100 + i, git_sha=sha)

    with _store(root) as store:
        found = ta.detect_verdict_oscillation(store)
    assert len(found) == 1
    o = found[0]
    assert o.pattern == "pat_link_up"
    assert o.fix_revert_cycles == 2
    assert o.collapsed_verdicts == ["FAIL", "PASS", "FAIL", "PASS", "FAIL"]
    assert o.classification == ta.FIX_REVERT
    assert o.oscillating is True


def test_one_commit_that_both_passed_and_failed_is_a_flaky_test_not_loop_oscillation(root):
    """The negative control that gives this detector its power. Answering an
    intermittent test with 'stop retrying and change strategy' would point the
    loop at the wrong problem entirely."""
    same = "f" * 40
    for i, passed in enumerate([False, True, False, True, False]):
        _record_verdict(root, "pat_flaky", passed, job_id=200 + i, git_sha=same)

    with _store(root) as store:
        o = ta.detect_verdict_oscillation(store)[0]
    assert o.fix_revert_cycles == 2          # the cycles are real
    assert o.classification == ta.FLAKY_SAME_SHA
    assert o.oscillating is False            # ...and they are not loop oscillation
    assert same in o.reason


def test_a_long_green_streak_does_not_inflate_the_cycle_count(root):
    """Consecutive duplicate verdicts are collapsed first: a pattern passing on
    five consecutive nightlies is ONE pass state, not five."""
    seq = [(False, "a" * 40)] + [(True, "b" * 40)] * 5 + [(False, "c" * 40)]
    for i, (passed, sha) in enumerate(seq):
        _record_verdict(root, "pat_streak", passed, job_id=300 + i, git_sha=sha)

    with _store(root) as store:
        o = ta.detect_verdict_oscillation(store)[0]
    assert o.collapsed_verdicts == ["FAIL", "PASS", "FAIL"]
    assert o.fix_revert_cycles == 1
    assert o.oscillating is False     # one cycle is below the 2-observation bar


def test_a_pattern_that_only_ever_regressed_once_is_not_an_oscillation(root):
    """`detect_pattern_regressions()`'s territory, not this one's."""
    for i, (passed, sha) in enumerate([(True, "a" * 40), (False, "b" * 40)]):
        _record_verdict(root, "pat_once", passed, job_id=400 + i, git_sha=sha)
    with _store(root) as store:
        assert ta.detect_verdict_oscillation(store) == []


def test_no_recorded_sha_is_undetermined_but_still_unstable(root):
    """A fix-revert and a flake cannot be told apart with no SHA -- but 'this
    pattern's verdict is not stable across the loop's own iterations' is still
    true and is still a no-progress signal."""
    for i, passed in enumerate([False, True, False, True, False]):
        _record_verdict(root, "pat_nosha", passed, job_id=500 + i)
    with _store(root) as store:
        o = ta.detect_verdict_oscillation(store)[0]
    assert o.classification == ta.UNDETERMINED_NO_SHA
    assert o.oscillating is True
    assert "NO_GIT_SHA_RECORDED" in o.reason


def test_a_fix_revert_fingerprint_overrides_a_climbing_coverage_curve(root):
    """The metric and the fingerprint measure different things: a curve can
    climb steadily while the loop repeatedly re-breaks the same pattern, and
    the fingerprint is the more urgent and more specific fact. Nothing is
    hidden -- the series verdict is still carried in `convergence`."""
    _coverage_days(root, [("2026-09-01", 40.0), ("2026-09-02", 55.0),
                          ("2026-09-03", 70.0), ("2026-09-04", 85.0)])
    for i, (passed, sha) in enumerate([
            (False, "a" * 40), (True, "b" * 40), (False, "c" * 40),
            (True, "d" * 40), (False, "e" * 40)]):
        _record_verdict(root, "pat_link_up", passed, job_id=600 + i, git_sha=sha)

    report = lcv.classify_loop_convergence(root)
    assert report.verdict == lcv.OSCILLATING
    assert report.loop_state == lc.LoopState.OSCILLATING.value
    assert report.convergence["verdict"] == lcv.CONVERGING     # not hidden
    assert "REPEAT_FIX_REVERT:pat_link_up" in report.oscillation["fingerprints"]


def test_the_repeat_failure_fingerprint_is_loop_contracts_own_not_a_second_copy():
    """`detect_oscillation_from_debug_loop_history()` is CALLED, never copied:
    there must be exactly one definition of that fingerprint in this codebase."""
    entries = [{"failing_stage": "BUILD", "target_fail_edge": "BUILD_DEBUG"}] * 2
    findings = lcv.detect_oscillation(debug_loop_entries=entries)
    assert findings.oscillating is True
    assert findings.repeat_failure == \
        lc.detect_oscillation_from_debug_loop_history(entries)
    assert findings.fingerprints == ["REPEAT_FAILURE:BUILD|BUILD_DEBUG"]


def test_either_fingerprint_alone_is_enough(root):
    """Requiring both would mean a project with no regression evidence database
    could never report oscillation at all."""
    only_failure = lcv.detect_oscillation(
        debug_loop_entries=[{"failing_stage": "VERIFY",
                             "target_fail_edge": "FAILURE_RECOVERY"}] * 2)
    assert only_failure.oscillating is True
    only_revert = lcv.detect_oscillation(fix_reverts=[
        ta.VerdictOscillation(pattern="p", fix_revert_cycles=2,
                              collapsed_verdicts=["FAIL", "PASS", "FAIL", "PASS", "FAIL"],
                              distinct_shas=["a", "b"], classification=ta.FIX_REVERT,
                              oscillating=True, min_cycles=2, first_recorded_at=None,
                              last_recorded_at=None, reason="r")])
    assert only_revert.oscillating is True
    assert lcv.detect_oscillation().oscillating is False


# ==========================================================================
# 5. Section 89: the plateau investigation, over the REAL hole classifier
# ==========================================================================
def test_a_plateau_over_under_sampled_bins_is_premature_and_routes_to_seeds(root):
    """Section 89's cheapest branch, and the aggregate form of
    `classify_coverage_hole()`'s own precedence: a plateau declared over bins
    randomization has not fairly attempted is an unfinished run, not a plateau
    -- even when the agent CLAIMED the bin is unreachable."""
    _write_registry(root, [
        "REQ-1,spec,usb_link,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1"])
    for i, seed in enumerate([1, 2, 3]):
        _record_verdict(root, "pat_link_up", True, job_id=700 + i, seed=seed)

    inv = lcv.investigate_plateau(root, [
        {"coverage_id": "COV-LINK", "root_cause_classification": "UNREACHABLE_STIMULUS"}])
    assert inv.recommended_action == coverage_analysis.ACTION_ADD_SEEDS
    assert inv.under_sampled_candidates == ["COV-LINK"]
    assert inv.escalation_required is False
    assert lcv.PLATEAU_PREMATURE_UNDER_SAMPLED in inv.basis


def test_an_adequately_sampled_unreachable_bin_needs_a_human(root):
    """Only the design owner can confirm the RTL cannot produce a condition,
    and generating another testcase provably cannot."""
    _write_registry(root, [
        "REQ-1,spec,usb_link,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1"])
    for i in range(25):
        _record_verdict(root, "pat_link_up", True, job_id=800 + i, seed=i)

    inv = lcv.investigate_plateau(root, [
        {"coverage_id": "COV-LINK", "root_cause_classification": "UNREACHABLE_STIMULUS"}])
    assert inv.recommended_action == coverage_analysis.ACTION_ESCALATE_TO_HUMAN
    assert inv.escalation_required is True
    assert inv.unreachable_candidates == ["COV-LINK"]
    assert inv.escalator == "coverage_analysis.escalate_unreachable_holes()"


def test_a_bin_no_test_targets_is_a_computed_stimulus_gap(root):
    """No pattern traced to the bin at all is exactly MISSING_TEST, and
    `classify_coverage_hole()` computes that conclusion rather than guessing."""
    _write_registry(root, [
        "REQ-1,spec,usb_link,VP-LINK,SC-1,CMD-1,pat_other,CHK-1,COV-OTHER,PASS,OPEN,ev1"])
    inv = lcv.investigate_plateau(root, [{"coverage_id": "COV-ORPHAN"}])
    assert inv.recommended_action == coverage_analysis.ACTION_GENERATE_TESTCASE
    assert inv.stimulus_gap_candidates == ["COV-ORPHAN"]
    assert inv.by_classification == {coverage_analysis.ROOT_CAUSE_MISSING_TEST: 1}


def test_the_investigation_escalates_nothing_and_writes_nothing(root):
    """Reading a loop's state must never be a mutating act. The investigation
    reports which bins would need a human and NAMES the real escalator; it does
    not take that path."""
    from dv_harness.question_queue import QuestionQueueStore

    _write_registry(root, [
        "REQ-1,spec,usb_link,VP-LINK,SC-1,CMD-1,pat_link_up,CHK-1,COV-LINK,PASS,OPEN,ev1"])
    for i in range(25):
        _record_verdict(root, "pat_link_up", True, job_id=900 + i, seed=i)

    inv = lcv.investigate_plateau(root, [
        {"coverage_id": "COV-LINK", "root_cause_classification": "UNREACHABLE_STIMULUS"}])
    assert inv.escalation_required is True
    assert QuestionQueueStore(root).list_questions() == []
    assert not (Path(root) / ".dv-harness" / "question_queue" / "questions.json").exists()


def test_a_waived_hole_is_not_investigated(root):
    inv = lcv.investigate_plateau(root, [{"coverage_id": "COV-W", "waived": True}])
    assert inv.holes_examined == 0
    assert inv.recommended_action == lcv.NO_HOLES_TO_INVESTIGATE


def test_the_investigation_runs_only_on_a_flat_verdict(root):
    """A climbing curve has no plateau to explain; running the investigation
    anyway would attach a remediation to a loop that is working."""
    _coverage_days(root, [("2026-09-01", 40.0), ("2026-09-02", 55.0),
                          ("2026-09-03", 70.0), ("2026-09-04", 85.0)])
    climbing = lcv.classify_loop_convergence(root, holes=[{"coverage_id": "COV-X"}])
    assert climbing.verdict == lcv.CONVERGING
    assert climbing.plateau_investigation is None

    flat_root = Path(tempfile.mkdtemp())
    try:
        _coverage_days(flat_root, [("2026-09-01", 88.0), ("2026-09-02", 88.1),
                                   ("2026-09-03", 88.0), ("2026-09-04", 88.2)])
        flat = lcv.classify_loop_convergence(flat_root, holes=[{"coverage_id": "COV-X"}])
        assert flat.verdict == lcv.PLATEAU
        assert flat.plateau_investigation["holes_examined"] == 1
    finally:
        shutil.rmtree(flat_root, ignore_errors=True)


# ==========================================================================
# 6. The bridge to LOOP-1
# ==========================================================================
class _State:
    """A minimal stand-in for the fields `observe_verification_closure_loop()`
    reads off a real `models.HarnessState`."""
    def __init__(self, stage, status, attempts=1, overall=Status.RUNNING.value):
        self.current_stage = stage
        self.stages = {stage: {"status": status, "attempts": attempts}}
        self.overall_status = overall


def test_plateau_not_evaluated_survives_for_a_project_with_no_series(root):
    """LOOP-1's own guarantee, kept intact. This is a regression guard: the
    whole point of PLATEAU_NOT_EVALUATED is that it must NOT be replaced by a
    cheerful 'no plateau' once a detector exists."""
    state = _State("VERIFY", Status.PASS.value)
    without = lc.observe_verification_closure_loop(state, {"policy": {}})
    assert without.plateau == lc.PLATEAU_NOT_EVALUATED

    empty = lcv.classify_loop_convergence(root).to_dict()
    with_empty = lc.observe_verification_closure_loop(
        state, {"policy": {}}, convergence=empty)
    assert with_empty.plateau == lc.PLATEAU_NOT_EVALUATED
    assert lcv.NO_EVIDENCE_DATABASE in with_empty.note


def test_one_sample_is_not_evaluated_either_even_though_a_series_exists(root):
    """UNKNOWN is not a plateau RESULT: the classifier ran and could not
    conclude. Recording that as the plateau field would present 'we could not
    tell' as a finding -- the same unearned claim, one step later."""
    _coverage_days(root, [("2026-09-01", 88.0)])
    report = lcv.classify_loop_convergence(root).to_dict()
    assert report["available"] is True          # a series really was read
    assert report["verdict"] == lcv.UNKNOWN     # ...and it decides nothing

    obs = lc.observe_verification_closure_loop(
        _State("VERIFY", Status.PASS.value), {"policy": {}}, convergence=report)
    assert obs.plateau == lc.PLATEAU_NOT_EVALUATED
    assert obs.state == lc.LoopState.CONVERGING.value

    code, _ = lc.execute_verb(root, "convergence", cfg={"policy": {}})
    assert code == 2


def test_a_caller_supplied_series_does_not_half_read_the_database(root):
    """Deriving the series from a caller and the fingerprint from a database
    the caller did not ask to be read would make the two halves describe
    different runs."""
    for i, (passed, sha) in enumerate([
            (False, "a" * 40), (True, "b" * 40), (False, "c" * 40),
            (True, "d" * 40), (False, "e" * 40)]):
        _record_verdict(root, "pat_link_up", passed, job_id=1100 + i, git_sha=sha)

    supplied = lcv.classify_loop_convergence(root, points=series([88.0, 88.1, 88.0]))
    assert supplied.verdict == lcv.PLATEAU               # the DB was not consulted
    assert supplied.oscillation["repeat_fix_revert"] == []
    assert supplied.sources["series"] == "caller-supplied"

    with _store(root) as store:
        reverts = ta.detect_verdict_oscillation(store)
    both = lcv.classify_loop_convergence(root, points=series([88.0, 88.1, 88.0]),
                                         fix_reverts=reverts)
    assert both.verdict == lcv.OSCILLATING


def test_a_real_plateau_reaches_a_real_loop_observation(root):
    """The end of the chain: real coverage rows -> real series -> PLATEAU
    verdict -> the section-86 LoopState on a real observation."""
    _coverage_days(root, [("2026-09-01", 88.0), ("2026-09-02", 88.1),
                          ("2026-09-03", 88.0), ("2026-09-04", 88.2)])
    report = lcv.classify_loop_convergence(root).to_dict()

    obs = lc.observe_verification_closure_loop(
        _State("COVERAGE_CLOSURE", Status.PASS.value), {"policy": {}},
        convergence=report)
    assert obs.state == lc.LoopState.PLATEAU.value
    assert obs.plateau == lcv.PLATEAU
    assert obs.evidence["convergence"]["verdict"] == lcv.PLATEAU
    assert "loop_convergence" in obs.derived_from


def test_a_real_oscillation_reaches_a_real_loop_observation(root):
    _coverage_days(root, [("2026-09-01", 50.0), ("2026-09-02", 60.0),
                          ("2026-09-03", 50.0), ("2026-09-04", 60.0)])
    report = lcv.classify_loop_convergence(root).to_dict()
    assert report["verdict"] == lcv.OSCILLATING

    obs = lc.observe_verification_closure_loop(
        _State("COVERAGE_CLOSURE", Status.PASS.value), {"policy": {}},
        convergence=report)
    assert obs.state == lc.LoopState.OSCILLATING.value


def test_the_new_states_are_reached_along_legal_section_86_edges():
    """A verdict that produces an illegal transition would be a state machine
    in name only."""
    for to_state in (lc.LoopState.PLATEAU.value, lc.LoopState.OSCILLATING.value):
        lc.assert_legal_loop_transition(lc.LoopState.CONVERGING.value, to_state)
        lc.assert_legal_loop_transition(lc.LoopState.VERIFYING.value, to_state)


def test_a_plateau_never_overrides_a_failing_stage_or_a_closed_project():
    """RETRY_WAIT/BUDGET_EXHAUSTED already describe a failing stage better, and
    a CLOSED project is finished, not stalled."""
    assert lc.derive_loop_state(Status.FAIL.value, attempts=1, max_attempts=3,
                                plateau=True) is lc.LoopState.RETRY_WAIT
    assert lc.derive_loop_state(Status.FAIL.value, attempts=9, max_attempts=3,
                                plateau=True) is lc.LoopState.BUDGET_EXHAUSTED
    assert lc.derive_loop_state(Status.PASS.value, loop_done=True,
                                plateau=True) is lc.LoopState.SUCCESS
    assert lc.derive_loop_state(Status.CLOSED.value,
                                plateau=True) is lc.LoopState.SUCCESS


def test_a_human_stop_still_outranks_every_convergence_verdict():
    """Human Override is checked first, exactly as `engine.loop()` checks it."""
    assert lc.derive_loop_state(Status.PASS.value, takeover_active=True,
                                plateau=True,
                                progress_oscillating=True) is lc.LoopState.HUMAN_GATE
    assert lc.derive_loop_state(Status.PASS.value, paused=True,
                                plateau=True) is lc.LoopState.STOPPED


def test_undoing_its_own_work_outranks_reaching_a_ceiling():
    """Both can hold at once; they point at different remedies, and the more
    specific one must win."""
    assert lc.derive_loop_state(Status.PASS.value, plateau=True,
                                progress_oscillating=True) is lc.LoopState.OSCILLATING


# ==========================================================================
# 7. The contract is DERIVED from the detector, not hand-typed
# ==========================================================================
def test_the_contract_reports_the_detectors_real_thresholds():
    """LOOP-1 left convergence/plateau all `None` because nothing computed
    them. They are now read from `loop_convergence`'s own constants, so
    changing a threshold changes the contract with it."""
    contract = lc.verification_closure_contract()
    assert contract.convergence.minimum_progress == lcv.DEFAULT_MIN_GAIN_PERCENT
    assert contract.convergence.window == lcv.DEFAULT_CONVERGENCE_WINDOW
    assert contract.plateau.detection_window == lcv.DEFAULT_PLATEAU_WINDOW
    assert contract.plateau.minimum_gain == lcv.DEFAULT_PLATEAU_MIN_GAIN_PERCENT
    lc.validate_contract(contract)
    lc.assert_driver_resolvable(contract)


def test_the_contract_no_longer_claims_no_progress_is_undetected():
    contract = lc.verification_closure_contract()
    assert "loop_convergence" in contract.termination.no_progress
    assert "pattern" in contract.oscillation.fingerprint_fields
    assert "regression_verdict_history" in contract.oscillation.evidence_source


# ==========================================================================
# 8. The front door, and what it must not do
# ==========================================================================
def test_the_convergence_verb_exits_2_when_there_is_no_usable_series(root):
    code, payload = lc.execute_verb(root, "convergence", cfg={"policy": {}})
    assert code == 2
    assert payload["available"] is False
    assert payload["verdict"] == lcv.UNKNOWN


def test_the_convergence_verb_reports_a_real_verdict(root):
    _coverage_days(root, [("2026-09-01", 88.0), ("2026-09-02", 88.1),
                          ("2026-09-03", 88.0), ("2026-09-04", 88.2)])
    code, payload = lc.execute_verb(root, "convergence", cfg={"policy": {}})
    assert code == 0
    assert payload["verdict"] == lcv.PLATEAU
    text = lcv.render_convergence_report_text(payload)
    assert "PLATEAU" in text and "LoopState PLATEAU" in text


def test_an_unknown_verb_lists_convergence_among_the_known_ones(root):
    code, payload = lc.execute_verb(root, "nonsense", cfg={"policy": {}})
    assert code == 1
    assert "convergence" in payload["known"]


def test_observe_all_carries_the_convergence_report(root):
    _coverage_days(root, [("2026-09-01", 88.0), ("2026-09-02", 88.1),
                          ("2026-09-03", 88.0), ("2026-09-04", 88.2)])
    payload = lc.observe_all(root, {"policy": {}})
    assert payload["convergence"]["verdict"] == lcv.PLATEAU
    assert payload["observations"][lc.VERIFICATION_CLOSURE_LOOP]["plateau"] == lcv.PLATEAU


def test_classifying_mints_no_approval_and_leaves_the_control_plane_untouched(root):
    """Not one human-approval gate moved to build this. A convergence verdict
    authorizes nothing."""
    from dv_harness.control_plane import ControlPlane

    _coverage_days(root, [("2026-09-01", 88.0), ("2026-09-02", 88.1),
                          ("2026-09-03", 88.0), ("2026-09-04", 88.2)])
    before = json.dumps(ControlPlane(root).load(), sort_keys=True)
    report = lcv.classify_loop_convergence(root)
    assert report.verdict == lcv.PLATEAU
    assert json.dumps(ControlPlane(root).load(), sort_keys=True) == before
    assert not (Path(root) / ".dv-harness" / "approvals.json").exists()


def test_no_models_status_member_is_ever_a_convergence_verdict():
    """The same vocabulary-collision guarantee `capability_evolution`'s
    `assert_no_verification_verdict_vocabulary()` holds: a convergence verdict
    is not a gate verdict and must never be mistaken for one."""
    collisions = set(lcv.CONVERGENCE_VERDICTS) & {s.value for s in Status}
    assert collisions == set()
