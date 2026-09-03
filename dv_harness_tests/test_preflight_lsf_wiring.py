"""Tests for lsf_client.bsub_submit_with_preflight() -- the real, GATED
submission entry point wiring dv_harness/preflight.py's gate into the one
real job-submission call site (`dv-harness lsf-submit`).

Confirms the core claim of the 2026-09-03 preflight task: a BLOCKED
PreflightResult genuinely prevents `bsub` from ever being invoked (not
just a logged warning), while a PASS result lets the real bsub_submit()
call through unchanged, and skip_preflight=True is a real, explicit bypass
-- never a silent default.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from dv_harness import lsf_client, preflight as pf


def _blocked_result():
    return pf.PreflightResult(
        overall="BLOCKED",
        checks=[pf.CheckOutcome(name="eda_env_vars", status="FAIL",
                                 detail="required EDA env var(s) not set: ['VCS_HOME']")],
        blocked_on=["eda_env_vars"],
    )


def _pass_result():
    return pf.PreflightResult(
        overall="PASS",
        checks=[pf.CheckOutcome(name="eda_env_vars", status="PASS", detail="all set")],
        blocked_on=[],
    )


class TestBsubSubmitWithPreflight:
    def test_blocked_never_calls_bsub(self):
        with patch("dv_harness.preflight.run_preflight", return_value=_blocked_result()) as run_pf, \
             patch("dv_harness.lsf_client.bsub_submit") as bsub:
            with pytest.raises(lsf_client.PreflightBlockedError) as exc_info:
                lsf_client.bsub_submit_with_preflight("vcs -R sim1", queue="vcs")
            bsub.assert_not_called()
            run_pf.assert_called_once()
        assert exc_info.value.result.overall == "BLOCKED"
        assert exc_info.value.result.blocked_on == ["eda_env_vars"]
        assert "eda_env_vars" in str(exc_info.value)

    def test_pass_calls_bsub_and_returns_job_id_and_result(self):
        with patch("dv_harness.preflight.run_preflight", return_value=_pass_result()), \
             patch("dv_harness.lsf_client.bsub_submit", return_value=987654) as bsub:
            job_id, result = lsf_client.bsub_submit_with_preflight(
                "vcs -R sim1", queue="vcs", cores=4, run_dir="/some/dir")
        bsub.assert_called_once_with(
            "vcs -R sim1", queue="vcs", cores=4, mem_mb=None, run_dir="/some/dir", extra_args=None)
        assert job_id == 987654
        assert result.overall == "PASS"

    def test_skip_preflight_bypasses_gate_entirely(self):
        with patch("dv_harness.preflight.run_preflight") as run_pf, \
             patch("dv_harness.lsf_client.bsub_submit", return_value=42) as bsub:
            job_id, result = lsf_client.bsub_submit_with_preflight(
                "vcs -R sim1", queue="vcs", skip_preflight=True)
        run_pf.assert_not_called()
        bsub.assert_called_once()
        assert job_id == 42
        assert result is None

    def test_default_preflight_cfg_uses_submission_queue_and_run_dir(self):
        captured = {}

        def _fake_run_preflight(cfg, runner=None):
            captured["cfg"] = cfg
            return _pass_result()

        with patch("dv_harness.preflight.run_preflight", side_effect=_fake_run_preflight), \
             patch("dv_harness.lsf_client.bsub_submit", return_value=1):
            lsf_client.bsub_submit_with_preflight("cmd", queue="normal", run_dir="/wd")
        assert captured["cfg"].queue == "normal"
        assert captured["cfg"].workdir == "/wd"

    def test_explicit_preflight_cfg_and_runner_are_passed_through(self):
        cfg = pf.PreflightConfig(queue="vcs", workdir="/x")
        sentinel_runner = object()
        captured = {}

        def _fake_run_preflight(passed_cfg, runner=None):
            captured["cfg"] = passed_cfg
            captured["runner"] = runner
            return _pass_result()

        with patch("dv_harness.preflight.run_preflight", side_effect=_fake_run_preflight), \
             patch("dv_harness.lsf_client.bsub_submit", return_value=1):
            lsf_client.bsub_submit_with_preflight(
                "cmd", queue="vcs", preflight_cfg=cfg, preflight_runner=sentinel_runner)
        assert captured["cfg"] is cfg
        assert captured["runner"] is sentinel_runner

    def test_preflight_blocked_error_is_not_an_lsf_unavailable_error(self):
        """PreflightBlockedError and LsfUnavailableError must stay distinct
        classes -- a caller catching one must never accidentally also
        catch the other and conflate 'LSF is unreachable' with 'the real
        preflight gate refused this job'."""
        assert not issubclass(lsf_client.PreflightBlockedError, lsf_client.LsfUnavailableError)
        assert not issubclass(lsf_client.LsfUnavailableError, lsf_client.PreflightBlockedError)
