"""Real end-to-end tests for PC-2's platform observability aggregator
(`dv_harness/platform_health.py`, 2026-09-06).

WHAT THESE PROVE, and why they are wiring tests rather than unit tests: the
whole risk in a "platform health + SLO" mechanism is that it looks impressive
while measuring nothing -- a health state derived from a constant, an SLO whose
"events" no producer ever writes, a 100% availability figure computed from an
empty window. So every signal below arrives from the REAL producer that already
existed in this repo, and no test here writes a health verdict or an SLO input
by hand:

  - the EXECUTION_PREFLIGHT_PASS / EXECUTION_PREFLIGHT_BLOCKED events come out
    of the REAL `engine.DVHarness.run_stage()` execution-preflight gate over the
    REAL shipped `main_graph.json`, with only preflight.py's own injected-Runner
    seam mocked (the same seam test_preflight.py / test_execution_preflight_
    wiring.py already use, so no test ever contacts a live license server or
    scheduler);
  - the regression verdicts come out of the REAL evidence write path
    (`regression_reporter._write_reconciliation_evidence_if_configured()`) into
    a real DuckDB file, exactly as test_trend_analysis.py drives it;
  - the connectivity gate statuses come out of a REAL
    `connectivity_check.main()` / `run_connectivity_check()` run against real
    .sv files, a real signal trace and real monitor counts on disk;
  - the DEGRADED triggers come out of the REAL `degradation.force_trigger()`.

The negative controls are what give them power: a healthy farm and a starved
one produce different subsystem states from the SAME code path; a window that
excludes back-dated evidence really reports fewer events than one that includes
it; and a project with no evidence at all reports UNKNOWN rather than HEALTHY.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from dv_harness import connectivity_check as cc
from dv_harness import degradation
from dv_harness import platform_health as ph
from dv_harness import regression_reporter as rr
from dv_harness import lsf_client
from dv_harness.models import Stage
from dv_harness.storage import StateStore

from .test_harness_reliability import (
    REAL_LMSTAT_VCS_STARVED,
    _CountingAdapter,
    _fresh,
)
from .test_preflight import (
    REAL_BQUEUES_VCS_OPEN_ACTIVE,
    REAL_LMSTAT_VCS_HEADER,
    _ScriptedRunner,
    _result as _res,
)
from .test_execution_preflight_wiring import ENV_ALL_SET, REAL_HOSTNAME

ROOT = Path(__file__).resolve().parents[1]

duckdb = pytest.importorskip("duckdb")


# --------------------------------------------------------------------------
# helpers -- every one drives a REAL producer
# --------------------------------------------------------------------------

def _armed_harness():
    """A DVHarness whose Planner -> Execution-Layer preflight gate is armed
    against a pure mock transport, exactly as test_execution_preflight_wiring
    arms it. Caller must shutil.rmtree(tmp)."""
    tmp, h = _fresh()
    h.cfg["preflight"]["license_server"] = "2900@host-a"
    h.cfg["execution_preflight"]["probe_resources"] = True
    h.adapter = _CountingAdapter(ok=True, text="built")
    return tmp, h


def _healthy_runner():
    return _ScriptedRunner([
        _res(stdout=REAL_LMSTAT_VCS_HEADER),        # eda_license  -> PASS
        _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),  # lsf_queue_health -> PASS
        _res(stdout=REAL_HOSTNAME),                 # host_reachability -> PASS
        _res(stdout=ENV_ALL_SET),                   # eda_env_vars -> PASS
    ])


def _starved_runner():
    return _ScriptedRunner([
        _res(stdout=REAL_LMSTAT_VCS_STARVED),       # every VCS license checked out
        _res(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
        _res(stdout=REAL_HOSTNAME),
        _res(stdout=ENV_ALL_SET),
    ])


def _run_real_preflight_gate(h, *, healthy: bool, stage: str = Stage.BUILD.value):
    """One REAL run_stage() pass through engine._execution_preflight_gate(),
    which is what appends the EXECUTION_PREFLIGHT_* event this module reads."""
    h.execution_preflight_runner = _healthy_runner() if healthy else _starved_runner()
    return h.run_stage("goal", stage=stage)


def _subsystem(report: dict, name: str) -> dict:
    for s in report["subsystems"]:
        if s["subsystem"] == name:
            return s
    raise AssertionError(f"{name} missing from report: "
                         f"{[s['subsystem'] for s in report['subsystems']]}")


def _budget(report: dict, slo_id: str) -> dict:
    for b in report["error_budgets"]:
        if b["slo_id"] == slo_id:
            return b
    raise AssertionError(f"{slo_id} missing from {[b['slo_id'] for b in report['error_budgets']]}")


def _store(root):
    from dv_harness.evidence_db import EvidenceStore, default_db_path
    return EvidenceStore(default_db_path(root))


def _record_verdict(root, pattern, passed, *, job_id, git_sha=None):
    """The REAL production evidence write path for one reconciled job -- the
    same one test_trend_analysis.py uses. Never a direct INSERT."""
    state = lsf_client.JobState(
        job_id=job_id, pattern=pattern,
        lsf_status="DONE" if passed else "EXIT",
        sim_status="PASS" if passed else "FAIL", git_sha=git_sha)
    rr._write_reconciliation_evidence_if_configured(root, {job_id: (state, [])})


def _backdate_verdicts(root, day: str, *, where="TRUE"):
    """Back-dates the store clock so a window boundary is testable. The only
    clock manipulation here -- every row's CONTENT still came from the real
    write path above."""
    with _store(root) as store:
        store.query(f"UPDATE regression_verdict_history "
                    f"SET recorded_at = TIMESTAMP '{day} 12:00:00' WHERE {where}")


def _make_rtl_project(tmp_path: Path, rtl_text="module dut(input clk); endmodule\n") -> Path:
    root = tmp_path / "proj"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "dut.sv").write_text(rtl_text, encoding="utf-8")
    (root / ".dv-harness").mkdir(parents=True, exist_ok=True)
    return root


def _write_conn_config(root: Path, **overrides) -> Path:
    cfg = {"rtl_sources": ["rtl/**/*.sv"], "filelists": [], "top_module": "tb_top"}
    cfg.update(overrides)
    p = root / cc.DEFAULT_CONFIG_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return p


def _run_all_passing_connectivity_gates(tmp_path: Path) -> Path:
    """A real `connectivity_check.run_connectivity_check()` in which all three
    gates genuinely PASS, so the aggregator has a positive control.

    Gate 2 and Gate 3 run their REAL logic (`evaluate_zero_time_connectivity()`
    over a real trace file with a toggling clock and a deasserting reset, and
    `evaluate_transaction_activity()` over real monitor counts). Only Gate 1's
    `which`/`subprocess` seam is injected -- connectivity.py's own established
    pattern -- so no fake elaboration tool is ever really invoked."""
    root = _make_rtl_project(tmp_path)
    (root / "sim").mkdir()
    (root / "sim" / "files.f").write_text("rtl/dut.sv\n", encoding="utf-8")
    (root / "sim" / "trace.json").write_text(json.dumps({"samples": {
        "clk": [[0, "0"], [5, "1"], [10, "0"]],
        "rst_n": [[0, "0"], [20, "1"]],
        "data": [[0, "0"], [20, "1"]],
    }}), encoding="utf-8")
    _write_conn_config(root, filelists=["sim/files.f"], top_module="tb_top",
                       signal_trace_path="sim/trace.json",
                       required_nonx_signals=["data"],
                       monitor_transaction_counts={"env.usb_agent.monitor": 42},
                       pattern_completed=True)
    result = cc.run_connectivity_check(
        root, cc.load_config(root / cc.DEFAULT_CONFIG_RELPATH),
        which_fn=lambda n: "/usr/bin/slang" if n == "slang" else None,
        run_fn=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="", stderr=""))
    assert result.exit_code == cc.EXIT_OK, result.status_block
    assert set(result.status_block.values()) == {"PASS"}, result.status_block
    return root


# ===========================================================================
# 1. The refusal to fabricate: the catalog may only carry measurable SLIs
# ===========================================================================


class TestNoFabricatedSLO:

    def test_catalog_and_unmeasurable_list_are_disjoint_and_both_real(self):
        ph.assert_no_unmeasurable_slo()
        ph.assert_slo_catalog_has_producers()
        assert ph.UNMEASURABLE_SLIS, "the refusal list must not be empty"
        for name, why in ph.UNMEASURABLE_SLIS.items():
            assert len(why) > 40, f"{name} must state WHY it cannot be measured"

    def test_adding_an_unmeasurable_slo_to_the_catalog_is_rejected(self):
        """The guard is not decorative: put an uptime SLO in the catalog and
        the assertion really fires."""
        original = ph.SLO_CATALOG
        original_ids = ph.SLO_IDS
        fake = ph.SLODefinition(
            slo_id="harness_uptime", subsystem=ph.SUBSYS_SELF_REPORTING,
            description="x", sli="x", fact_source="x", target_percent=99.9)
        try:
            ph.SLO_CATALOG = original + (fake,)
            ph.SLO_IDS = tuple(s.slo_id for s in ph.SLO_CATALOG)
            with pytest.raises(AssertionError, match="harness_uptime"):
                ph.assert_no_unmeasurable_slo()
            with pytest.raises(AssertionError, match="no counting branch"):
                ph.assert_slo_catalog_has_producers()
        finally:
            ph.SLO_CATALOG = original
            ph.SLO_IDS = original_ids

    def test_every_declared_fact_source_names_a_producer_that_really_exists(self):
        """An SLO's `fact_source` must not be aspirational prose. Both are
        checked against the real source of the module that produces them."""
        engine_src = (ROOT / "dv_harness" / "engine.py").read_text(encoding="utf-8")
        assert f'"event": "{ph.EVENT_PREFLIGHT_PASS}"' in engine_src
        assert f'"event": "{ph.EVENT_PREFLIGHT_BLOCKED}"' in engine_src

        evidence_src = (ROOT / "dv_harness" / "evidence_db.py").read_text(encoding="utf-8")
        assert "CREATE TABLE IF NOT EXISTS regression_verdict_history" in evidence_src

        preflight_src = (ROOT / "dv_harness" / "preflight.py").read_text(encoding="utf-8")
        for name in ph.LICENSE_CHECKS + ph.QUEUE_CHECKS + ph.EXECUTION_ENV_CHECKS:
            assert f'name = "{name}"' in preflight_src, (
                f"platform_health names preflight check {name!r}, which preflight.py "
                f"does not define")

    def test_the_report_authorizes_nothing(self):
        """A health report must observe, never permit. Asserted against this
        module's own source, and against the guard actually working."""
        ph.assert_authorizes_nothing()
        with pytest.raises(AssertionError, match="authorization machinery"):
            ph.assert_authorizes_nothing(ROOT / "dv_harness" / "control_plane.py")


# ===========================================================================
# 2. UNKNOWN is never rendered as healthy
# ===========================================================================


class TestUnknownIsNotHealthy:

    def test_severity_order_puts_unknown_above_healthy(self):
        assert ph.HEALTH_SEVERITY[ph.UNKNOWN] > ph.HEALTH_SEVERITY[ph.HEALTHY]
        assert ph.worst([ph.HEALTHY, ph.UNKNOWN]) == ph.UNKNOWN
        assert ph.worst([ph.HEALTHY, ph.UNKNOWN, ph.DEGRADED]) == ph.DEGRADED
        assert ph.worst([ph.DEGRADED, ph.CRITICAL, ph.UNKNOWN]) == ph.CRITICAL
        assert ph.worst([]) == ph.UNKNOWN, "no subsystems is not a healthy platform"

    def test_a_project_with_no_evidence_reports_unknown_not_healthy(self, tmp_path):
        report = ph.platform_health_report(tmp_path)
        assert report["overall_state"] == ph.UNKNOWN
        assert report["state_counts"][ph.UNKNOWN] >= 5
        # Every UNKNOWN carries a real reason naming what is missing, never a
        # bare state.
        for s in report["subsystems"]:
            if s["state"] == ph.UNKNOWN:
                assert s["reason"] and s["detail"], s
                assert s["fact_source"], s
        text = ph.render_report_text(report)
        assert "UNKNOWN is not a pass" in text

    def test_an_unmeasured_platform_does_not_exit_nonzero_but_is_not_called_healthy(
            self, tmp_path):
        code, report, text = ph.execute(tmp_path)
        assert code == ph.EXIT_OK
        assert report["overall_state"] == ph.UNKNOWN
        assert "OVERALL: UNKNOWN" in text
        assert "HEALTHY" not in text.splitlines()[1]


# ===========================================================================
# 3. Execution-layer subsystems, fed by the REAL engine preflight gate
# ===========================================================================


class TestExecutionSubsystemsFromRealPreflightEvents:

    def test_healthy_farm_run_makes_license_and_queue_healthy(self):
        tmp, h = _armed_harness()
        try:
            _run_real_preflight_gate(h, healthy=True)
            report = ph.platform_health_report(tmp, cfg=h.cfg)

            assert _subsystem(report, ph.SUBSYS_EDA_LICENSE)["state"] == ph.HEALTHY
            assert _subsystem(report, ph.SUBSYS_LSF_QUEUE)["state"] == ph.HEALTHY
            lic = _subsystem(report, ph.SUBSYS_EDA_LICENSE)
            assert lic["observations"]["passed"] == ["eda_license"]
            assert lic["observations"]["preflight_event"] == ph.EVENT_PREFLIGHT_PASS
            # The detail is preflight.py's own parsed evidence, not a label.
            assert "2900@host-a" in lic["observations"]["details"]["eda_license"] or \
                   "available" in lic["observations"]["details"]["eda_license"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_starved_license_run_makes_the_license_subsystem_critical(self):
        """The negative control against the test above: same code path, same
        aggregator, a real BLOCKED preflight verdict -> CRITICAL."""
        tmp, h = _armed_harness()
        try:
            res = _run_real_preflight_gate(h, healthy=False)
            assert res.ok is False and res.raw["preflight"]["blocked_on"] == ["eda_license"]

            report = ph.platform_health_report(tmp, cfg=h.cfg)
            lic = _subsystem(report, ph.SUBSYS_EDA_LICENSE)
            assert lic["state"] == ph.CRITICAL
            assert lic["reason"] == "PREFLIGHT_CHECK_FAILED"
            assert lic["observations"]["failed"] == ["eda_license"]
            # The queue was fine in that same run and must not be smeared.
            assert _subsystem(report, ph.SUBSYS_LSF_QUEUE)["state"] == ph.HEALTHY
            assert report["overall_state"] == ph.CRITICAL
            assert ph.execute(tmp, cfg=h.cfg)[0] == ph.EXIT_UNHEALTHY
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_skipped_checks_are_unknown_never_healthy_and_never_an_alert(self):
        """config.py ships `preflight.workdir` empty, so disk_space/workdir
        genuinely SKIP. A SKIP is missing evidence, not a measured problem: the
        subsystem must be UNKNOWN -- not HEALTHY (which would claim a disk was
        checked) and not DEGRADED (which would alert on the shipped config)."""
        tmp, h = _armed_harness()
        try:
            _run_real_preflight_gate(h, healthy=True)
            report = ph.platform_health_report(tmp, cfg=h.cfg)
            env = _subsystem(report, ph.SUBSYS_EXECUTION_ENV)
            assert env["state"] == ph.UNKNOWN
            assert env["reason"] == "PREFLIGHT_CHECK_SKIPPED"
            assert sorted(env["observations"]["skipped"]) == ["disk_space", "workdir"]
            assert sorted(env["observations"]["passed"]) == ["eda_env_vars",
                                                             "host_reachability"]
            # ...and an unmeasured check must not raise an alert on its own.
            assert ph.execute(tmp, cfg=h.cfg)[0] == ph.EXIT_OK
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_latest_recorded_gate_run_wins_over_an_older_one(self):
        """Two real gate runs, the second one starved: the report describes the
        CURRENT state of the farm, not the first thing it ever saw."""
        tmp, h = _armed_harness()
        try:
            _run_real_preflight_gate(h, healthy=True)
            assert _subsystem(ph.platform_health_report(tmp, cfg=h.cfg),
                              ph.SUBSYS_EDA_LICENSE)["state"] == ph.HEALTHY
            _run_real_preflight_gate(h, healthy=False, stage=Stage.REGRESSION.value)
            assert _subsystem(ph.platform_health_report(tmp, cfg=h.cfg),
                              ph.SUBSYS_EDA_LICENSE)["state"] == ph.CRITICAL
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 4. The preflight error budget, counted off those same real events
# ===========================================================================


class TestExecutionPreflightErrorBudget:

    def test_below_min_events_reports_insufficient_evidence_not_a_rate(self):
        """Two real PASS runs is not a measurement of a 90% objective."""
        tmp, h = _armed_harness()
        try:
            _run_real_preflight_gate(h, healthy=True)
            _run_real_preflight_gate(h, healthy=True, stage=Stage.REGRESSION.value)
            b = _budget(ph.platform_health_report(tmp, cfg=h.cfg),
                        "execution_preflight_pass_rate")
            assert b["status"] == ph.BUDGET_NO_EVIDENCE
            assert b["total_events"] == 2
            assert b["achieved_percent"] is None, "no rate may be claimed from 2 samples"
            assert b["budget_remaining_percent"] is None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_all_passing_runs_meet_the_objective_with_a_full_budget(self):
        tmp, h = _armed_harness()
        try:
            for i in range(6):
                _run_real_preflight_gate(
                    h, healthy=True,
                    stage=Stage.BUILD.value if i % 2 else Stage.REGRESSION.value)
            b = _budget(ph.platform_health_report(tmp, cfg=h.cfg),
                        "execution_preflight_pass_rate")
            assert b["status"] == ph.BUDGET_MEETING
            assert (b["good_events"], b["bad_events"]) == (6, 0)
            assert b["achieved_percent"] == 100.0
            assert b["budget_remaining_percent"] == 100.0
            assert _subsystem(ph.platform_health_report(tmp, cfg=h.cfg),
                              ph.SUBSYS_SLO_COMPLIANCE)["observations"][
                                  "slo_status"]["execution_preflight_pass_rate"] == \
                ph.BUDGET_MEETING
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_real_blocked_runs_spend_the_budget_and_then_breach_it(self):
        """The arithmetic, driven entirely by real recorded gate runs: 5 good +
        1 bad is 83.3% against a 90% objective -> BREACHED, and the
        slo_compliance subsystem says so."""
        tmp, h = _armed_harness()
        try:
            for _ in range(5):
                _run_real_preflight_gate(h, healthy=True)
            _run_real_preflight_gate(h, healthy=False, stage=Stage.REGRESSION.value)

            report = ph.platform_health_report(tmp, cfg=h.cfg)
            b = _budget(report, "execution_preflight_pass_rate")
            assert (b["good_events"], b["bad_events"]) == (5, 1)
            assert b["achieved_percent"] == pytest.approx(83.3333, abs=0.001)
            assert b["status"] == ph.BUDGET_BREACHED
            assert b["budget_remaining_events"] < 0

            slo = _subsystem(report, ph.SUBSYS_SLO_COMPLIANCE)
            assert slo["state"] == ph.CRITICAL
            assert slo["observations"]["breached"] == ["execution_preflight_pass_rate"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_project_config_may_retune_the_objective(self):
        """The same real evidence, judged against a target this project chose:
        5/6 passes a 75% objective it fails at 90%."""
        tmp, h = _armed_harness()
        try:
            for _ in range(5):
                _run_real_preflight_gate(h, healthy=True)
            _run_real_preflight_gate(h, healthy=False, stage=Stage.REGRESSION.value)

            h.cfg.setdefault("platform_health", {}).setdefault("slos", {})[
                "execution_preflight_pass_rate"] = {"target_percent": 75.0,
                                                     "min_events": 5}
            b = _budget(ph.platform_health_report(tmp, cfg=h.cfg),
                        "execution_preflight_pass_rate")
            assert b["target_percent"] == 75.0
            assert b["status"] in (ph.BUDGET_MEETING, ph.BUDGET_AT_RISK)
            assert b["status"] != ph.BUDGET_BREACHED
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 5. The regression pass-rate SLO, off the REAL evidence database
# ===========================================================================


class TestRegressionPassRateSLO:

    def test_real_recorded_verdicts_produce_a_real_pass_rate(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        for i in range(10):
            _record_verdict(root, f"tc_{i}", True, job_id=1000 + i)
        b = _budget(ph.platform_health_report(root), "regression_verdict_pass_rate")
        assert (b["good_events"], b["bad_events"]) == (10, 0)
        assert b["achieved_percent"] == 100.0
        assert b["status"] == ph.BUDGET_MEETING

    def test_real_failing_verdicts_breach_the_95_percent_objective(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        for i in range(8):
            _record_verdict(root, f"tc_{i}", True, job_id=2000 + i)
        for i in range(2):
            _record_verdict(root, f"bad_{i}", False, job_id=2100 + i)
        report = ph.platform_health_report(root)
        b = _budget(report, "regression_verdict_pass_rate")
        assert (b["good_events"], b["bad_events"]) == (8, 2)
        assert b["achieved_percent"] == 80.0
        assert b["status"] == ph.BUDGET_BREACHED
        assert _subsystem(report, ph.SUBSYS_SLO_COMPLIANCE)["observations"][
            "breached"] == ["regression_verdict_pass_rate"]

    def test_the_evidence_store_slo_is_windowed_on_the_store_clock(self, tmp_path):
        """The two recording surfaces are stamped by different clocks
        (`engine.now()` is UTC, DuckDB's `now()` is local). This SLO's window
        must follow the store clock its own rows carry, or a run recorded near
        either midnight would silently fall outside the window it belongs to."""
        root = tmp_path / "proj"
        root.mkdir()
        for i in range(10):
            _record_verdict(root, f"tc_{i}", True, job_id=3500 + i)
        b = _budget(ph.platform_health_report(root), "regression_verdict_pass_rate")
        assert b["window_clock"] == ph.CLOCK_LOCAL_STORE
        assert b["window_end"] == datetime.now().date().isoformat()
        assert b["total_events"] == 10, (
            "a verdict recorded seconds ago must land inside the rolling window")

    def test_the_rolling_window_really_excludes_older_evidence(self, tmp_path):
        """A window that counted everything ever recorded would not be a
        rolling window. Back-date the whole set beyond the window and the SLO
        must fall back to INSUFFICIENT_EVIDENCE rather than keep reporting."""
        root = tmp_path / "proj"
        root.mkdir()
        for i in range(12):
            _record_verdict(root, f"tc_{i}", True, job_id=3000 + i)
        today = datetime.now().date()  # the store clock this SLO is windowed on
        inside = ph.platform_health_report(root, asof=today)
        assert _budget(inside, "regression_verdict_pass_rate")["total_events"] == 12

        old_day = (today - timedelta(days=60)).isoformat()
        _backdate_verdicts(root, old_day)
        outside = ph.platform_health_report(root, asof=today)
        b = _budget(outside, "regression_verdict_pass_rate")
        assert b["total_events"] == 0
        assert b["status"] == ph.BUDGET_NO_EVIDENCE
        assert b["window_start"] == (today - timedelta(days=13)).isoformat()
        assert b["window_end"] == today.isoformat()

        # ...and asking as-of the back-dated day finds them again, which proves
        # the window moved rather than the evidence disappearing.
        asof_then = date.fromisoformat(old_day)
        again = ph.platform_health_report(root, asof=asof_then)
        assert _budget(again, "regression_verdict_pass_rate")["total_events"] == 12

    def test_the_slo_counts_agree_with_trend_analysis_own_daily_rollup(self, tmp_path):
        """No second query path: the SLO's counts must be summable straight out
        of trend_analysis.daily_rollup(), the module that already owns that
        question."""
        from dv_harness import trend_analysis as ta
        root = tmp_path / "proj"
        root.mkdir()
        for i in range(7):
            _record_verdict(root, f"tc_{i}", i % 3 != 0, job_id=4000 + i)
        with _store(root) as store:
            points = ta.daily_rollup(store)
        good = sum(p.verdict_passed for p in points)
        bad = sum(p.verdict_count - p.verdict_passed for p in points)
        b = _budget(ph.platform_health_report(root), "regression_verdict_pass_rate")
        assert (b["good_events"], b["bad_events"]) == (good, bad)


# ===========================================================================
# 6. Regression-quality subsystem, off trend_analysis's own detectors
# ===========================================================================


class TestRegressionQualitySubsystem:

    def test_a_real_pass_then_fail_transition_makes_it_critical(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        _record_verdict(root, "usb_link_tc", True, job_id=5001, git_sha="a" * 40)
        _record_verdict(root, "usb_link_tc", False, job_id=5002, git_sha="b" * 40)
        sub = _subsystem(ph.platform_health_report(root), ph.SUBSYS_REGRESSION_QUALITY)
        assert sub["state"] == ph.CRITICAL
        assert sub["reason"] == "PATTERN_REGRESSION"
        assert sub["observations"]["regressed_patterns"] == ["usb_link_tc"]

    def test_a_steadily_passing_project_is_healthy(self, tmp_path):
        """The positive control: the same aggregator, the same detectors, no
        regression -> HEALTHY, so CRITICAL above is a real discrimination."""
        root = tmp_path / "proj"
        root.mkdir()
        for i in range(4):
            _record_verdict(root, "usb_link_tc", True, job_id=5100 + i)
        sub = _subsystem(ph.platform_health_report(root), ph.SUBSYS_REGRESSION_QUALITY)
        assert sub["state"] == ph.HEALTHY
        assert sub["observations"]["regression_count"] == 0

    def test_no_evidence_database_is_unknown_not_healthy(self, tmp_path):
        sub = _subsystem(ph.platform_health_report(tmp_path), ph.SUBSYS_REGRESSION_QUALITY)
        assert sub["state"] == ph.UNKNOWN
        assert sub["reason"] == "NO_EVIDENCE_DATABASE"


# ===========================================================================
# 7. Connectivity gates, off a REAL connectivity_check run
# ===========================================================================


class TestConnectivityGatesSubsystem:

    def test_a_real_all_passing_gate_run_is_healthy_and_an_rtl_edit_degrades_it(
            self, tmp_path):
        """All three real gates PASS -> HEALTHY. Only Gate 1's `which`/
        `subprocess` seam is injected (connectivity.py's own established
        dependency-injection pattern), so no fake elaborator ever reaches a real
        invocation; Gates 2 and 3 run their real logic over a real trace file
        and real monitor counts on disk."""
        root = _run_all_passing_connectivity_gates(tmp_path)
        sub = _subsystem(ph.platform_health_report(root), ph.SUBSYS_CONNECTIVITY_GATES)
        assert sub["state"] == ph.HEALTHY, sub
        assert sub["observations"]["staleness"]["stale"] is False
        assert set(sub["observations"]["gate_statuses"].values()) == {"PASS"}

        # The RTL moves and nobody re-runs the gates: the recorded verdicts no
        # longer describe what is on disk, so they may not be cited as healthy.
        (root / "rtl" / "dut.sv").write_text(
            "module dut(input clk, input rst_n); endmodule\n", encoding="utf-8")
        stale = _subsystem(ph.platform_health_report(root), ph.SUBSYS_CONNECTIVITY_GATES)
        assert stale["state"] == ph.DEGRADED
        assert stale["reason"] == "STALE_RTL_CHANGED"

    def test_a_gate_with_no_tool_available_is_unknown_not_healthy(self, tmp_path):
        """The realistic case in a repo with no slang/vcs on PATH: Gate 1 is
        NOT_AVAILABLE. That is neither a pass nor a failure, so the subsystem
        must be UNKNOWN even though Gate 3 really PASSed."""
        root = _make_rtl_project(tmp_path)
        _write_conn_config(root, monitor_transaction_counts={"env.usb_agent.monitor": 42},
                           pattern_completed=True)
        assert cc.main(["--project-root", str(root)]) == cc.EXIT_OK
        sub = _subsystem(ph.platform_health_report(root), ph.SUBSYS_CONNECTIVITY_GATES)
        assert sub["state"] == ph.UNKNOWN
        assert sub["reason"] == "GATE_NOT_MEASURED"
        assert sub["observations"]["gate_statuses"]["gate3_transaction_activity"] == "PASS"
        assert sub["observations"]["gate_statuses"]["gate1_elaboration"] == "NOT_AVAILABLE"

    def test_a_real_failing_gate_run_is_critical(self, tmp_path):
        root = _make_rtl_project(tmp_path)
        _write_conn_config(root,
                           monitor_transaction_counts={"env.a.monitor": 7,
                                                        "env.b.monitor": 0},
                           pattern_completed=True)
        assert cc.main(["--project-root", str(root)]) == cc.EXIT_GATE_FAIL
        sub = _subsystem(ph.platform_health_report(root), ph.SUBSYS_CONNECTIVITY_GATES)
        assert sub["state"] == ph.CRITICAL
        assert sub["reason"] == "GATE_FAILED"
        assert "gate3_transaction_activity" in sub["detail"]

    def test_a_pending_gate_is_unknown_never_collapsed_into_pass_or_fail(self, tmp_path):
        """CLAUDE.md's standing rule for this enum, enforced here: PENDING /
        NOT_AVAILABLE are neither a pass nor a failure."""
        root = _make_rtl_project(tmp_path)
        _write_conn_config(root, pattern_completed=False)
        assert cc.main(["--project-root", str(root)]) == cc.EXIT_OK
        sub = _subsystem(ph.platform_health_report(root), ph.SUBSYS_CONNECTIVITY_GATES)
        assert sub["state"] == ph.UNKNOWN
        assert sub["reason"] == "GATE_NOT_MEASURED"
        assert "PENDING" in json.dumps(sub["observations"]["gate_statuses"])


# ===========================================================================
# 8. Degradation triggers, off the REAL degradation state
# ===========================================================================


class TestDegradationBackedSubsystems:

    def test_a_real_adapter_trigger_makes_the_adapter_subsystem_critical(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        before = _subsystem(ph.platform_health_report(root), ph.SUBSYS_AGENT_ADAPTER)
        assert before["state"] == ph.HEALTHY

        degradation.force_trigger(root, degradation.TRIGGER_ADAPTER,
                                  "claude adapter unreachable 3x")
        after = _subsystem(ph.platform_health_report(root), ph.SUBSYS_AGENT_ADAPTER)
        assert after["state"] == ph.CRITICAL
        assert after["reason"] == "ADAPTER_UNAVAILABLE"
        assert "claude adapter unreachable" in after["detail"]

    def test_a_live_license_trigger_outranks_an_older_passing_preflight_run(self):
        """A recorded PASS from an earlier gate run must not out-vote the
        condition the engine is refusing to make judgment calls under RIGHT
        NOW."""
        tmp, h = _armed_harness()
        try:
            _run_real_preflight_gate(h, healthy=True)
            assert _subsystem(ph.platform_health_report(tmp, cfg=h.cfg),
                              ph.SUBSYS_EDA_LICENSE)["state"] == ph.HEALTHY

            degradation.force_trigger(tmp, degradation.TRIGGER_LICENSE,
                                      "0 of 40 VCSRuntime available")
            sub = _subsystem(ph.platform_health_report(tmp, cfg=h.cfg),
                             ph.SUBSYS_EDA_LICENSE)
            assert sub["state"] == ph.CRITICAL
            assert sub["reason"] == "DEGRADATION_TRIGGER_SET"
            assert "0 of 40" in sub["detail"]

            # ...and clearing it really returns the subsystem to the recorded
            # preflight evidence, so the trigger is a live read, not a latch.
            degradation.clear_trigger(tmp, degradation.TRIGGER_LICENSE)
            assert _subsystem(ph.platform_health_report(tmp, cfg=h.cfg),
                              ph.SUBSYS_EDA_LICENSE)["state"] == ph.HEALTHY
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 9. The harness reporting on its own best-effort side channels
# ===========================================================================


class TestSelfReportingSubsystem:

    #: A real `*_FAILED` name this repo genuinely emits. Asserted against the
    #: engine source below so this test can never pass on an invented event.
    REAL_FAILURE_EVENT = "LOOP_TELEMETRY_EMIT_FAILED"

    def test_the_failure_event_name_is_one_the_harness_really_emits(self):
        src = (ROOT / "dv_harness" / "engine.py").read_text(encoding="utf-8")
        assert self.REAL_FAILURE_EVENT in src
        assert self.REAL_FAILURE_EVENT.endswith(ph.SELF_REPORTING_FAILURE_SUFFIX)

    def test_recorded_side_channel_failures_degrade_the_subsystem(self, tmp_path):
        """Written through the REAL single events writer
        (`storage.StateStore.event()`) that every producer in this repo uses --
        no second audit trail is created to test the reader of the first."""
        root = tmp_path / "proj"
        root.mkdir()
        store = StateStore(root)
        from dv_harness.engine import now
        store.event({"ts": now(), "stage": "BUILD", "event": "EXECUTION_PREFLIGHT_PASS"})
        clean = _subsystem(ph.platform_health_report(root), ph.SUBSYS_SELF_REPORTING)
        assert clean["state"] == ph.HEALTHY
        assert clean["observations"]["failure_events"] == 0

        store.event({"ts": now(), "stage": "BUILD", "event": self.REAL_FAILURE_EVENT,
                     "error": "disk full"})
        dirty = _subsystem(ph.platform_health_report(root), ph.SUBSYS_SELF_REPORTING)
        assert dirty["state"] == ph.DEGRADED
        assert dirty["observations"]["failure_events"] == 1
        assert dirty["observations"]["failure_event_names"] == {self.REAL_FAILURE_EVENT: 1}

    def test_events_outside_the_window_are_not_counted(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        store = StateStore(root)
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        store.event({"ts": old, "event": self.REAL_FAILURE_EVENT})
        sub = _subsystem(ph.platform_health_report(root), ph.SUBSYS_SELF_REPORTING)
        assert sub["state"] == ph.UNKNOWN
        assert sub["reason"] == "NO_EVENTS_IN_WINDOW"

    def test_an_unparseable_timestamp_is_dropped_not_counted_at_an_assumed_time(
            self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        store = StateStore(root)
        store.event({"ts": "not-a-timestamp", "event": self.REAL_FAILURE_EVENT})
        sub = _subsystem(ph.platform_health_report(root), ph.SUBSYS_SELF_REPORTING)
        assert sub["observations"]["events_in_window"] == 0


# ===========================================================================
# 10. Read-only, and reachable from the real CLI
# ===========================================================================


class TestReadOnlyAndCli:

    def test_the_report_writes_nothing(self, tmp_path):
        """Observability must not mutate the thing it observes."""
        root = tmp_path / "proj"
        root.mkdir()
        for i in range(3):
            _record_verdict(root, f"tc_{i}", True, job_id=6000 + i)
        StateStore(root).event({"ts": datetime.now(timezone.utc).isoformat(),
                                "event": "EXECUTION_PREFLIGHT_PASS"})

        def snapshot():
            return {str(p.relative_to(root)): p.stat().st_size
                    for p in sorted(root.rglob("*")) if p.is_file()}

        before = snapshot()
        ph.platform_health_report(root)
        ph.platform_health_report(root)
        assert snapshot() == before

    def test_the_real_cli_verb_runs_and_carries_the_exit_code(self, tmp_path):
        """Driven as a real subprocess against the real argparse wiring, so a
        parser/handler mismatch cannot pass this suite."""
        root = tmp_path / "proj"
        root.mkdir()
        proc = subprocess.run(
            [sys.executable, "-m", "dv_harness", "--project-root", str(root), "platform-health",
             "--json"],
            cwd=str(ROOT), capture_output=True, text=True)
        assert proc.returncode == ph.EXIT_OK, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["overall_state"] == ph.UNKNOWN
        assert {s["subsystem"] for s in payload["subsystems"]} == set(ph.SUBSYSTEMS)
        assert set(b["slo_id"] for b in payload["error_budgets"]) == set(ph.SLO_IDS)
        assert payload["unmeasurable_slis"], "the refusal list must reach the CLI output"

        # A real breach really changes the process exit code.
        for i in range(8):
            _record_verdict(root, f"tc_{i}", True, job_id=7000 + i)
        for i in range(4):
            _record_verdict(root, f"bad_{i}", False, job_id=7100 + i)
        proc2 = subprocess.run(
            [sys.executable, "-m", "dv_harness", "--project-root", str(root), "platform-health"],
            cwd=str(ROOT), capture_output=True, text=True)
        assert proc2.returncode == ph.EXIT_UNHEALTHY, proc2.stdout + proc2.stderr
        assert "regression_verdict_pass_rate [BREACHED]" in proc2.stdout

    def test_the_module_entry_point_and_the_cli_agree(self, tmp_path):
        """`python -m dv_harness.platform_health` and `dv-harness
        platform-health` are one implementation, not two."""
        root = tmp_path / "proj"
        root.mkdir()
        a = subprocess.run(
            [sys.executable, "-m", "dv_harness.platform_health", "--root", str(root),
             "--json"], cwd=str(ROOT), capture_output=True, text=True)
        b = subprocess.run(
            [sys.executable, "-m", "dv_harness", "--project-root", str(root), "platform-health",
             "--json"], cwd=str(ROOT), capture_output=True, text=True)
        assert a.returncode == b.returncode == ph.EXIT_OK, a.stderr + b.stderr
        pa, pb = json.loads(a.stdout), json.loads(b.stdout)
        assert pa["overall_state"] == pb["overall_state"]
        assert [s["subsystem"] for s in pa["subsystems"]] == \
               [s["subsystem"] for s in pb["subsystems"]]

    def test_no_second_events_reader_was_introduced(self):
        """The events trail has one parser. platform_health reuses
        loop_telemetry's rather than adding a third beside it and
        dashboard._tail_events()."""
        from dv_harness import loop_telemetry
        assert ph.read_harness_events is loop_telemetry._read_events, (
            "platform_health must reuse loop_telemetry's events.jsonl parser, not "
            "wrap or reimplement it")
        src = (ROOT / "dv_harness" / "platform_health.py").read_text(encoding="utf-8")
        assert "from .loop_telemetry import read_events" in src
        # No second path-join to the trail, and no second parser: the module
        # never builds an events.jsonl path or json.loads() a line of one.
        assert '/ "events.jsonl"' not in src
        assert "json.loads" not in src
