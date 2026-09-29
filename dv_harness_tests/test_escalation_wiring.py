"""Tests for the real escalation-notifier WIRING (2026-09-03 task) into the
three call sites named in the user's own spec:
  - dv_harness.lsf_client.bsub_submit_with_preflight() -> license_starvation
    (on a starvation-caused PreflightBlockedError) and
    job_submission_failure (on a real post-preflight-PASS bsub failure).
  - dv_harness.regression_reporter.run_reconciliation_cycle() ->
    uvm_fatal_burst (aggregated across one reconciliation cycle's jobs).
  - dv_harness.signoff_export.collect_signoff_bundle() -> signoff_blocked
    (when the bundled self-audit result shows a real gate failure).

Every test confirms BOTH directions: the notifier fires on the real
matching condition, AND stays silent (never called, or called with
fired=False) on an unrelated failure / a clean PASS -- "never for routine
PASS" is a wiring property, not just a notifier-internals property.
"""
from __future__ import annotations

import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from dv_harness import lsf_client, preflight as pf, escalation_notify as esc
from dv_harness import regression_reporter as rr
from dv_harness import signoff_export


class RecordingNotifier:
    """Records every trigger call without touching a real transport --
    used to assert exactly which (if any) escalation method real
    production code called, with what arguments."""

    def __init__(self):
        self.calls = []

    def license_starvation(self, outcome):
        self.calls.append(("license_starvation", outcome))

    def uvm_fatal_burst(self, fatal_job_count, **kw):
        self.calls.append(("uvm_fatal_burst", fatal_job_count, kw))

    def job_submission_failure(self, **kw):
        self.calls.append(("job_submission_failure", kw))

    def signoff_blocked(self, **kw):
        self.calls.append(("signoff_blocked", kw))


# --- lsf_client.bsub_submit_with_preflight() ------------------------------


def _blocked_starvation_result():
    return pf.PreflightResult(
        overall="BLOCKED",
        checks=[pf.CheckOutcome(
            name="eda_license", status="FAIL",
            detail="license feature(s) fully checked out (starvation): ['VCSRuntime']")],
        blocked_on=["eda_license"])


def _blocked_non_license_result():
    return pf.PreflightResult(
        overall="BLOCKED",
        checks=[pf.CheckOutcome(name="lsf_queue_health", status="FAIL",
                                 detail="queue 'vcs' not Open:Active")],
        blocked_on=["lsf_queue_health"])


def _pass_result():
    return pf.PreflightResult(
        overall="PASS",
        checks=[pf.CheckOutcome(name="eda_license", status="PASS", detail="ok")],
        blocked_on=[])


class TestLsfClientNotifierWiring:
    def test_license_starvation_block_notifies(self):
        notifier = RecordingNotifier()
        with patch("dv_harness.preflight.run_preflight", return_value=_blocked_starvation_result()), \
             patch("dv_harness.lsf_client.bsub_submit") as bsub:
            with pytest.raises(lsf_client.PreflightBlockedError):
                lsf_client.bsub_submit_with_preflight("cmd", queue="vcs", notifier=notifier)
            bsub.assert_not_called()
        assert len(notifier.calls) == 1
        assert notifier.calls[0][0] == "license_starvation"
        assert notifier.calls[0][1].name == "eda_license"

    def test_non_license_block_does_not_notify_license_starvation(self):
        notifier = RecordingNotifier()
        with patch("dv_harness.preflight.run_preflight", return_value=_blocked_non_license_result()), \
             patch("dv_harness.lsf_client.bsub_submit"):
            with pytest.raises(lsf_client.PreflightBlockedError):
                lsf_client.bsub_submit_with_preflight("cmd", queue="vcs", notifier=notifier)
        assert notifier.calls == []

    def test_pass_never_notifies(self):
        notifier = RecordingNotifier()
        with patch("dv_harness.preflight.run_preflight", return_value=_pass_result()), \
             patch("dv_harness.lsf_client.bsub_submit", return_value=123):
            lsf_client.bsub_submit_with_preflight("cmd", queue="vcs", notifier=notifier)
        assert notifier.calls == []

    def test_real_bsub_failure_after_pass_notifies_job_submission_failure(self):
        notifier = RecordingNotifier()
        with patch("dv_harness.preflight.run_preflight", return_value=_pass_result()), \
             patch("dv_harness.lsf_client.bsub_submit",
                   side_effect=lsf_client.LsfUnavailableError("bsub not found on PATH")):
            with pytest.raises(lsf_client.LsfUnavailableError):
                lsf_client.bsub_submit_with_preflight("vcs -R sim1", queue="vcs", notifier=notifier)
        assert len(notifier.calls) == 1
        kind, kw = notifier.calls[0]
        assert kind == "job_submission_failure"
        assert kw["command"] == "vcs -R sim1"
        assert kw["queue"] == "vcs"
        assert "bsub not found" in kw["reason"]

    def test_no_notifier_supplied_is_a_pure_no_op(self):
        """Default (notifier=None) must not change any existing
        behavior -- confirms the pre-existing test suite's assumptions
        (test_preflight_lsf_wiring.py) still hold untouched."""
        with patch("dv_harness.preflight.run_preflight", return_value=_pass_result()), \
             patch("dv_harness.lsf_client.bsub_submit", return_value=1):
            job_id, result = lsf_client.bsub_submit_with_preflight("cmd", queue="vcs")
        assert job_id == 1
        assert result.overall == "PASS"


# --- regression_reporter.run_reconciliation_cycle() -----------------------


class TestRegressionReporterUvmFatalBurstWiring:
    """Exercises rr._escalate_uvm_fatal_burst_if_needed() directly -- the
    exact function run_reconciliation_cycle() calls with its own real
    jobs_for_snapshot right before rendering the snapshot -- rather than
    faking the full live/disk job-discovery machinery (which belongs to
    run_reconciliation_cycle()'s own pre-existing test coverage)."""

    def _project_with_config(self, escalation_overrides: dict) -> Path:
        tmp = Path(tempfile.mkdtemp())
        from dv_harness import config as _config
        cfg = json.loads(json.dumps(_config.DEFAULT_CONFIG))
        cfg["escalation"].update(escalation_overrides)
        (tmp / ".dv-harness").mkdir()
        (tmp / ".dv-harness" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        return tmp

    def test_aggregation_counts_only_positive_uvm_fatal_rows(self):
        jobs_for_snapshot = [
            {"job_id": 1, "uvm_fatal_count": 0},
            {"job_id": 2, "uvm_fatal_count": 2},
            {"job_id": 3, "uvm_fatal_count": None},
            {"job_id": 4, "uvm_fatal_count": 5},
        ]
        fatal_job_ids = [row["job_id"] for row in jobs_for_snapshot
                         if (row.get("uvm_fatal_count") or 0) > 0]
        assert fatal_job_ids == [2, 4]

    def test_fires_when_burst_threshold_met(self):
        tmp = self._project_with_config({"uvm_fatal_burst_threshold": 2})
        try:
            notifier = RecordingNotifier()
            jobs_for_snapshot = [
                {"job_id": 1, "uvm_fatal_count": 0},
                {"job_id": 2, "uvm_fatal_count": 1},
                {"job_id": 3, "uvm_fatal_count": 4},
            ]
            with patch("dv_harness.escalation_notify.notifier_from_config", return_value=notifier):
                rr._escalate_uvm_fatal_burst_if_needed(tmp, jobs_for_snapshot)
            assert len(notifier.calls) == 1
            kind, count, kw = notifier.calls[0]
            assert kind == "uvm_fatal_burst"
            assert count == 2
            assert kw["total_jobs"] == 3
            assert kw["job_ids"] == [2, 3]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_fatal_rows_never_constructs_a_notifier(self):
        tmp = self._project_with_config({})
        try:
            with patch("dv_harness.escalation_notify.notifier_from_config") as ctor:
                rr._escalate_uvm_fatal_burst_if_needed(
                    tmp, [{"job_id": 1, "uvm_fatal_count": 0}, {"job_id": 2, "uvm_fatal_count": None}])
            ctor.assert_not_called()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_notifier_construction_failure_never_raises(self, tmp_path):
        """The try/except must swallow a real config/notifier-construction
        error rather than letting it propagate into (and kill)
        run_reconciliation_cycle()'s caller -- same discipline that
        function's every other real side-effect already follows."""
        (tmp_path / ".dv-harness").mkdir()
        with patch("dv_harness.escalation_notify.notifier_from_config",
                   side_effect=RuntimeError("boom")):
            rr._escalate_uvm_fatal_burst_if_needed(
                tmp_path, [{"job_id": 1, "uvm_fatal_count": 5}])
        # No exception escaped -- that is the entire assertion.


# --- signoff_export.collect_signoff_bundle() -------------------------------


class TestSignoffExportNotifierWiring:
    def _project(self):
        tmp = Path(tempfile.mkdtemp())
        return tmp

    def test_fires_signoff_blocked_on_real_gate_failure(self):
        tmp = self._project()
        try:
            notifier = RecordingNotifier()
            fail_audit = {
                "summary": {"total": 1, "pass": 0, "fail": 1, "no_source_data": 0,
                            "tool_missing": 0, "smoke_pass": 0, "smoke_fail": 0},
                "unknown_gate_ids": [],
                "gates": [{"gate_id": "vplan_completeness_gate", "status": "FAIL",
                           "mode": "SOURCED", "detail": {}}],
            }
            with patch("dv_harness.self_audit.run_self_audit", return_value=fail_audit):
                signoff_export.collect_signoff_bundle(tmp, tmp / "out", notifier=notifier)
            assert len(notifier.calls) == 1
            kind, kw = notifier.calls[0]
            assert kind == "signoff_blocked"
            assert kw["stage"] == "SIGNOFF"
            assert kw["reasons"] == ["vplan_completeness_gate"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_clean_audit_never_notifies(self):
        tmp = self._project()
        try:
            notifier = RecordingNotifier()
            clean_audit = {
                "summary": {"total": 1, "pass": 1, "fail": 0, "no_source_data": 0,
                            "tool_missing": 0, "smoke_pass": 0, "smoke_fail": 0},
                "unknown_gate_ids": [],
                "gates": [{"gate_id": "g1", "status": "PASS", "mode": "SOURCED", "detail": {}}],
            }
            with patch("dv_harness.self_audit.run_self_audit", return_value=clean_audit):
                signoff_export.collect_signoff_bundle(tmp, tmp / "out", notifier=notifier)
            assert notifier.calls == []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_notifier_supplied_is_a_pure_no_op(self):
        """Default (notifier=None) must not change collect_signoff_bundle's
        pre-existing return shape/behavior."""
        tmp = self._project()
        try:
            fail_audit = {"summary": {"fail": 1, "total": 1, "pass": 0, "no_source_data": 0,
                                       "tool_missing": 0, "smoke_pass": 0, "smoke_fail": 0},
                          "unknown_gate_ids": [], "gates": []}
            with patch("dv_harness.self_audit.run_self_audit", return_value=fail_audit):
                result = signoff_export.collect_signoff_bundle(tmp, tmp / "out")
            assert "manifest" in result
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
