"""Background job/log monitor cadence contract -- self_check_list.md #41.

#41 asks for a background mechanism watching every job and simulation log
that auto-confirms 每隔10分鐘 (every 10 minutes). The mechanism itself was
already real and live-tested (test_regression_reporter.py's
TestWatcherLifecycle, test_cli_lsf_watch.py's real-subprocess round trip);
what nothing enforced was the CADENCE half of the requirement.

Two real defects this file locks shut:

1. Three entry points fan into the same watch loop -- `dv-harness
   lsf-watch-start` (default 5), `python -m dv_harness.regression_reporter
   --watch` (defaulted 30) and `scripts/powershell/DV_REGRESSION_SNAPSHOT.ps1 -Watch`
   (defaulted 30). Two of the three shipped a cadence three times slower
   than #41's ceiling. Nothing tied them together, so nothing caught it.
2. No test pinned ANY default: every existing test passes an explicit
   `--interval-minutes 30`, so the real shipped cadence was untested and a
   silent edit to any default would have gone unnoticed.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import cli, regression_reporter

ROOT = Path(__file__).resolve().parents[1]


class TestSpecCeiling:
    def test_default_interval_is_within_the_spec_ceiling(self):
        assert regression_reporter.DEFAULT_INTERVAL_MINUTES <= \
            regression_reporter.SPEC_MAX_INTERVAL_MINUTES

    def test_spec_ceiling_is_the_ten_minutes_self_check_list_41_asks_for(self):
        assert regression_reporter.SPEC_MAX_INTERVAL_MINUTES == 10

    @pytest.mark.parametrize("minutes", [1, 5, 9, 10])
    def test_intervals_at_or_under_the_ceiling_are_compliant(self, minutes):
        c = regression_reporter.interval_compliance(minutes)
        assert c["compliant"] is True
        assert c["interval_minutes"] == minutes
        assert c["spec_max_interval_minutes"] == 10
        assert "within" in c["message"]

    @pytest.mark.parametrize("minutes", [11, 30, 120])
    def test_intervals_over_the_ceiling_are_reported_non_compliant(self, minutes):
        c = regression_reporter.interval_compliance(minutes)
        assert c["compliant"] is False
        assert "SLOWER" in c["message"]
        assert str(minutes) in c["message"]

    def test_non_compliance_is_advisory_not_a_clamp(self):
        """A deliberately slow watcher stays possible -- interval_compliance()
        reports, it does not silently rewrite the operator's number."""
        assert regression_reporter.interval_compliance(45)["interval_minutes"] == 45

    def test_sub_minute_intervals_are_floored_the_same_way_the_sleep_is(self):
        # main()'s loop sleeps max(1, interval_minutes) * 60; the compliance
        # report must describe that same effective value, not the raw input.
        assert regression_reporter.interval_compliance(0)["interval_minutes"] == 1


class TestEveryEntryPointSharesTheDefault:
    """The three real ways to start the watch loop must agree, and all three
    must sit inside #41's ceiling."""

    def test_ensure_watcher_running_signature_default(self):
        import inspect
        sig = inspect.signature(regression_reporter.ensure_watcher_running)
        assert sig.parameters["interval_minutes"].default == \
            regression_reporter.DEFAULT_INTERVAL_MINUTES

    def test_main_signature_default(self):
        import inspect
        sig = inspect.signature(regression_reporter.main)
        assert sig.parameters["interval_minutes"].default == \
            regression_reporter.DEFAULT_INTERVAL_MINUTES

    def test_cli_lsf_watch_start_default_matches_the_module_constant(self, tmp_path):
        """Drives the REAL `dv-harness lsf-watch-start` argv path with no
        --interval-minutes and captures what actually reaches
        ensure_watcher_running(), so this pins the shipped default rather
        than re-reading the source."""
        from unittest.mock import patch
        seen = {}

        def fake_ensure(root, vcuser, uvm_root_path, interval_minutes=None):
            seen["interval_minutes"] = interval_minutes
            return {"started": True, "pid": 4242}

        argv = ["dv-harness", "--project-root", str(tmp_path),
                "lsf-watch-start", "--vcuser", "vcuser1"]
        with patch.object(sys, "argv", argv), \
             patch("dv_harness.regression_reporter.ensure_watcher_running",
                   side_effect=fake_ensure):
            try:
                cli.main()
            except SystemExit as e:      # some branches exit 0 explicitly
                assert not e.code
        assert seen["interval_minutes"] == regression_reporter.DEFAULT_INTERVAL_MINUTES
        assert seen["interval_minutes"] <= regression_reporter.SPEC_MAX_INTERVAL_MINUTES

    def test_module_argparse_default_matches_the_module_constant(self):
        """`python -m dv_harness.regression_reporter --watch` with no
        --interval-minutes. Asserted through the real module source rather
        than by running the (infinite) watch loop."""
        src = (ROOT / "dv_harness" / "regression_reporter.py").read_text(encoding="utf-8")
        m = re.search(r"ap\.add_argument\('--interval-minutes',\s*type=int,\s*"
                      r"default=([A-Za-z_0-9]+)", src)
        assert m, "module-level --interval-minutes argparse default not found"
        assert m.group(1) == "DEFAULT_INTERVAL_MINUTES"

    def test_powershell_snapshot_script_default_matches_the_module_constant(self):
        src = (ROOT / "scripts" / "powershell" / "DV_REGRESSION_SNAPSHOT.ps1").read_text(encoding="utf-8")
        m = re.search(r"\[int\]\$IntervalMinutes=(\d+)", src)
        assert m, "-IntervalMinutes param default not found"
        assert int(m.group(1)) == regression_reporter.DEFAULT_INTERVAL_MINUTES

    def test_regression_agent_snapshot_policy_is_inside_the_ceiling(self):
        """The fourth cadence declaration, and the only one not read by
        Python: `.claude/agents/regression-agent.md` line 165 tells the
        Regression Agent to report periodically per this file. It shipped
        30 minutes, outside #41's ceiling."""
        import json as _json
        policy = _json.loads(
            (ROOT / ".dv-harness" / "lsf" / "periodic_snapshot_policy.json")
            .read_text(encoding="utf-8"))
        assert policy["default_interval_minutes"] == \
            regression_reporter.DEFAULT_INTERVAL_MINUTES
        assert policy["spec_max_interval_minutes"] == \
            regression_reporter.SPEC_MAX_INTERVAL_MINUTES
        assert policy["default_interval_minutes"] <= \
            policy["spec_max_interval_minutes"]

    def test_periodic_regression_snapshot_skill_states_the_same_cadence(self):
        """The fifth declaration: the CORE skill an agent actually reads
        before producing a snapshot. It said 預設每 30 分鐘 -- a number an
        agent would have followed straight past #41's ceiling."""
        src = (ROOT / ".claude" / "skills" / "CORE" /
               "periodic-regression-snapshot" / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r"預設每\s*(\d+)\s*分鐘", src)
        assert m, "the skill no longer states a default cadence at all"
        assert int(m.group(1)) == regression_reporter.DEFAULT_INTERVAL_MINUTES
        assert str(regression_reporter.SPEC_MAX_INTERVAL_MINUTES) in src


class TestWatchLoopAnnouncesItsCadence:
    def test_watch_mode_logs_its_real_cadence_once(self, tmp_path, capsys):
        from unittest.mock import patch
        calls = []

        def one_then_stop(root, vcuser, uvm_root):
            calls.append(1)
            raise KeyboardInterrupt

        with patch("dv_harness.regression_reporter.run_reconciliation_cycle",
                   side_effect=one_then_stop), \
             patch("dv_harness.regression_reporter.time.sleep"):
            with pytest.raises(KeyboardInterrupt):
                regression_reporter.main(project_root=str(tmp_path), once=False,
                                         interval_minutes=30, vcuser="vcuser1",
                                         uvm_root_path=str(tmp_path / "uvm"))
        out = capsys.readouterr().out
        assert "[watch loop]" in out and "SLOWER" in out and "30min" in out
        assert len(calls) == 1

    def test_single_shot_mode_does_not_print_a_cadence_line(self, tmp_path, capsys):
        regression_reporter.main(project_root=str(tmp_path), once=True)
        assert "self_check_list #41" not in capsys.readouterr().out


class TestCliWarnsOnSlowCadence:
    """Real CLI subprocess: the warning must reach stderr and must NOT
    contaminate stdout, which callers parse as JSON."""

    @staticmethod
    def _start(tmp, minutes):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "lsf-watch-start", "--vcuser", "vcuser1",
             "--uvm-root-path", str(tmp / "uvm"),
             "--interval-minutes", str(minutes)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60,
            encoding="utf-8")

    @staticmethod
    def _kill(tmp):
        subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "lsf-watch-stop"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60,
            encoding="utf-8")

    def test_slow_interval_warns_on_stderr_and_still_starts(self, tmp_path):
        import json
        try:
            r = self._start(tmp_path, 30)
            assert r.returncode == 0
            assert json.loads(r.stdout.strip())["started"] is True
            assert "[warn]" in r.stderr and "SLOWER" in r.stderr
        finally:
            self._kill(tmp_path)

    def test_default_interval_produces_no_warning(self, tmp_path):
        import json
        try:
            r = subprocess.run(
                [sys.executable, "-m", "dv_harness.cli",
                 "--project-root", str(tmp_path), "lsf-watch-start",
                 "--vcuser", "vcuser1", "--uvm-root-path", str(tmp_path / "uvm")],
                cwd=str(ROOT), capture_output=True, text=True, timeout=60,
                encoding="utf-8")
            assert r.returncode == 0
            assert json.loads(r.stdout.strip())["started"] is True
            assert "[warn]" not in r.stderr
        finally:
            self._kill(tmp_path)
