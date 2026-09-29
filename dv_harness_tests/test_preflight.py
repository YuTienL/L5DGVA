"""Unit tests for dv_harness/preflight.py -- the lmstat + scheduler
preflight gate (2026-09-03, highest-priority workstream per the user's own
spec).

Every parser-level test below is fed REAL captured command output --
gathered live 2026-09-03 against this project's real remote DV server
(host-c) over an already-READY persistent relay (see
.work/governance-preflight-report.md for the full real-evidence session):
real `bqueues vcs` (queue Open:Active, 12 RUN), real `lmutil lmstat -a -c
2900@host-a` (the project's real Synopsys license server, discovered via
/eda/sunplus/modulefiles/synopsys/vcs/.common), real `df -Pk` against the
real workdir /home/svcacct/DV/UVM/USB/usb_uvm/sim, and the real tcsh
`$?VAR`-based env-var-presence output showing VCS_HOME/UVM_HOME/VERDI_HOME
genuinely UNSET in that relay's persistent shell. This module itself never
makes a live call to license/scheduler infrastructure in a test -- every
Runner here is a pure, deterministic mock (dv_harness/preflight.py's own
design goal, stated in its module docstring)."""
from __future__ import annotations

from dataclasses import replace

import pytest

from dv_harness import preflight as pf


def _result(stdout="", ok=True, exit_code=0, error=None, stderr=""):
    return pf.CommandResult(ok=ok, exit_code=exit_code, stdout=stdout, stderr=stderr, error=error)


class _ScriptedRunner:
    """A pure-mock Runner: returns the next canned CommandResult for each
    call, in order, and records every (cmd, timeout) it was asked to run."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def __call__(self, cmd, timeout=60):
        self.calls.append((cmd, timeout))
        if not self._results:
            raise AssertionError(f"_ScriptedRunner ran out of canned results at call: {cmd!r}")
        return self._results.pop(0)


# --- real captured fixtures (2026-09-03 live session) -----------------------

REAL_BQUEUES_VCS_OPEN_ACTIVE = (
    "QUEUE_NAME      PRIO STATUS          MAX JL/U JL/P JL/H NJOBS  PEND   RUN  SUSP\n"
    "vcs              30  Open:Active       -    -    -    -    12     0    12     0\n"
)

REAL_LMSTAT_VCS_HEADER = (
    "lmutil - Copyright (c) 1989-2009 Acresso Software Inc. All Rights Reserved.\n"
    "Flexible License Manager status on Thu 9/3/2026 14:19\n"
    "License server status: 2900@host-a\n"
    "    License file(s) on host-a: /home/eda/flexlm/host-a/synopsys/license.dat:\n"
    "     host-a: license server UP (MASTER) v10.8\n"
    "Vendor daemon status (on host-a):\n"
    "   snpslmd: UP v11.19\n"
    "Feature usage info:\n"
    "Users of VCSRuntime:  (Total of 99 licenses issued;  Total of 0 licenses in use)\n"
    "Users of VCSCompiler:  (Total of 99 licenses issued;  Total of 0 licenses in use)\n"
)

REAL_DF_WORKDIR = (
    "Filesystem                               1024-blocks       Used  Available Capacity Mounted on\n"
    "f200.icatchtek.com.tw:/ifs/proj1/svcacct  5368709120 3709058368 1659650752      70% /home/svcacct\n"
)

# Real tcsh output confirming VCS_HOME/UVM_HOME/VERDI_HOME genuinely UNSET
# in the persistent relay's shell (module load was never sourced there).
REAL_ENV_ALL_UNSET = "VCS_HOME_UNSET\nUVM_HOME_UNSET\nVERDI_HOME_UNSET\n"
REAL_ENV_ALL_SET = "VCS_HOME_SET\nUVM_HOME_SET\nVERDI_HOME_SET\n"


class TestLicenseCheck:
    def test_pass_when_server_up_and_features_available(self):
        cfg = pf.PreflightConfig(license_server="2900@host-a", license_features=["VCSRuntime"])
        runner = _ScriptedRunner([_result(stdout=REAL_LMSTAT_VCS_HEADER)])
        outcome = pf.check_license(runner, cfg)
        assert outcome.status == "PASS"
        assert "VCSRuntime" in outcome.detail
        assert runner.calls[0][0] == "lmutil lmstat -a -c 2900@host-a"

    def test_fails_when_no_license_server_configured_by_default(self):
        cfg = pf.PreflightConfig(license_server="")
        outcome = pf.check_license(_ScriptedRunner([]), cfg)
        assert outcome.status == "FAIL"

    def test_skips_when_license_check_explicitly_opted_out(self):
        cfg = pf.PreflightConfig(license_server="", require_license_configured=False)
        outcome = pf.check_license(_ScriptedRunner([]), cfg)
        assert outcome.status == "SKIP"

    def test_fails_when_server_not_up(self):
        cfg = pf.PreflightConfig(license_server="2900@host-a")
        down = "License server status: 2900@host-a\n     host-a: license server DOWN\n"
        outcome = pf.check_license(_ScriptedRunner([_result(stdout=down)]), cfg)
        assert outcome.status == "FAIL"
        assert "not reported UP" in outcome.detail

    def test_fails_on_feature_starvation(self):
        cfg = pf.PreflightConfig(license_server="2900@host-a", license_features=["VCSRuntime"])
        starved = REAL_LMSTAT_VCS_HEADER.replace(
            "Users of VCSRuntime:  (Total of 99 licenses issued;  Total of 0 licenses in use)",
            "Users of VCSRuntime:  (Total of 99 licenses issued;  Total of 99 licenses in use)")
        outcome = pf.check_license(_ScriptedRunner([_result(stdout=starved)]), cfg)
        assert outcome.status == "FAIL"
        assert "starvation" in outcome.detail

    def test_fails_when_required_feature_missing_from_output(self):
        cfg = pf.PreflightConfig(license_server="2900@host-a", license_features=["Verdi"])
        outcome = pf.check_license(_ScriptedRunner([_result(stdout=REAL_LMSTAT_VCS_HEADER)]), cfg)
        assert outcome.status == "FAIL"
        assert "not found" in outcome.detail

    def test_fails_when_lmstat_command_itself_fails(self):
        cfg = pf.PreflightConfig(license_server="2900@host-a")
        outcome = pf.check_license(
            _ScriptedRunner([_result(ok=False, exit_code=None, error="COMMAND_NOT_FOUND: lmutil")]), cfg)
        assert outcome.status == "FAIL"
        assert "lmstat command failed" in outcome.detail


class TestQueueHealthCheck:
    def test_pass_on_real_open_active_vcs_queue(self):
        cfg = pf.PreflightConfig(queue="vcs")
        outcome = pf.check_queue_health(_ScriptedRunner([_result(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE)]), cfg)
        assert outcome.status == "PASS"
        assert "Open:Active" in outcome.detail

    def test_fails_when_queue_closed_or_inactive(self):
        cfg = pf.PreflightConfig(queue="vcs")
        closed = REAL_BQUEUES_VCS_OPEN_ACTIVE.replace("Open:Active", "Closed:Inactive")
        outcome = pf.check_queue_health(_ScriptedRunner([_result(stdout=closed)]), cfg)
        assert outcome.status == "FAIL"

    def test_fails_when_queue_not_found(self):
        cfg = pf.PreflightConfig(queue="nosuchqueue")
        outcome = pf.check_queue_health(_ScriptedRunner([_result(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE)]), cfg)
        assert outcome.status == "FAIL"
        assert "not found" in outcome.detail

    def test_fails_when_bqueues_command_fails(self):
        cfg = pf.PreflightConfig(queue="vcs")
        outcome = pf.check_queue_health(
            _ScriptedRunner([_result(ok=False, exit_code=127, error="COMMAND_NOT_FOUND")]), cfg)
        assert outcome.status == "FAIL"


class TestHostReachability:
    def test_pass_when_hostname_returned(self):
        cfg = pf.PreflightConfig()
        outcome = pf.check_host_reachability(_ScriptedRunner([_result(stdout="host-c\n")]), cfg)
        assert outcome.status == "PASS"
        assert "host-c" in outcome.detail

    def test_fails_on_expected_host_mismatch(self):
        cfg = pf.PreflightConfig(host="host-a")
        outcome = pf.check_host_reachability(_ScriptedRunner([_result(stdout="host-c\n")]), cfg)
        assert outcome.status == "FAIL"

    def test_fails_when_unreachable(self):
        cfg = pf.PreflightConfig()
        outcome = pf.check_host_reachability(
            _ScriptedRunner([_result(ok=False, error="RELAY_NOT_READY")]), cfg)
        assert outcome.status == "FAIL"


class TestDiskSpaceCheck:
    def test_pass_with_real_df_output(self):
        cfg = pf.PreflightConfig(workdir="/home/svcacct/DV/UVM/USB/usb_uvm/sim", min_free_disk_gb=20)
        outcome = pf.check_disk_space(_ScriptedRunner([_result(stdout=REAL_DF_WORKDIR)]), cfg)
        assert outcome.status == "PASS"
        assert "GB free" in outcome.detail

    def test_fails_below_threshold(self):
        cfg = pf.PreflightConfig(workdir="/home/svcacct/DV/UVM/USB/usb_uvm/sim", min_free_disk_gb=999999)
        outcome = pf.check_disk_space(_ScriptedRunner([_result(stdout=REAL_DF_WORKDIR)]), cfg)
        assert outcome.status == "FAIL"

    def test_skips_when_no_workdir_configured(self):
        cfg = pf.PreflightConfig(workdir="")
        outcome = pf.check_disk_space(_ScriptedRunner([]), cfg)
        assert outcome.status == "SKIP"

    def test_fails_on_unparseable_output(self):
        cfg = pf.PreflightConfig(workdir="/x")
        outcome = pf.check_disk_space(_ScriptedRunner([_result(stdout="garbage\n")]), cfg)
        assert outcome.status == "FAIL"


class TestWorkdirCheck:
    def test_pass_when_exists_and_writable(self):
        cfg = pf.PreflightConfig(workdir="/home/svcacct/DV/UVM/USB/usb_uvm/sim")
        outcome = pf.check_workdir(
            _ScriptedRunner([_result(stdout="DIR_EXISTS\nDIR_WRITABLE\n")]), cfg)
        assert outcome.status == "PASS"

    def test_fails_when_missing(self):
        cfg = pf.PreflightConfig(workdir="/no/such/dir")
        outcome = pf.check_workdir(
            _ScriptedRunner([_result(stdout="DIR_MISSING\nDIR_NOT_WRITABLE\n")]), cfg)
        assert outcome.status == "FAIL"
        assert "does not exist" in outcome.detail
        assert "not writable" in outcome.detail

    def test_fails_when_exists_but_not_writable(self):
        cfg = pf.PreflightConfig(workdir="/readonly/dir")
        outcome = pf.check_workdir(
            _ScriptedRunner([_result(stdout="DIR_EXISTS\nDIR_NOT_WRITABLE\n")]), cfg)
        assert outcome.status == "FAIL"
        assert "not writable" in outcome.detail

    def test_skips_when_no_workdir_configured(self):
        cfg = pf.PreflightConfig(workdir="")
        outcome = pf.check_workdir(_ScriptedRunner([]), cfg)
        assert outcome.status == "SKIP"


class TestEnvVarsCheck:
    def test_pass_when_all_set(self):
        cfg = pf.PreflightConfig(required_env_vars=["VCS_HOME", "UVM_HOME", "VERDI_HOME"])
        outcome = pf.check_env_vars(_ScriptedRunner([_result(stdout=REAL_ENV_ALL_SET)]), cfg)
        assert outcome.status == "PASS"

    def test_fails_with_real_unset_evidence(self):
        """Real finding, 2026-09-03: on this project's actual persistent
        relay shell, VCS_HOME/UVM_HOME/VERDI_HOME are genuinely UNSET
        (the module-load EDA setup was never sourced there) -- this is
        exactly the real output the check must correctly turn into a
        blocking FAIL, not a false PASS."""
        cfg = pf.PreflightConfig(required_env_vars=["VCS_HOME", "UVM_HOME", "VERDI_HOME"])
        outcome = pf.check_env_vars(_ScriptedRunner([_result(stdout=REAL_ENV_ALL_UNSET)]), cfg)
        assert outcome.status == "FAIL"
        assert "VCS_HOME" in outcome.detail
        assert "UVM_HOME" in outcome.detail
        assert "VERDI_HOME" in outcome.detail

    def test_fails_when_partially_set(self):
        cfg = pf.PreflightConfig(required_env_vars=["VCS_HOME", "UVM_HOME"])
        outcome = pf.check_env_vars(
            _ScriptedRunner([_result(stdout="VCS_HOME_SET\nUVM_HOME_UNSET\n")]), cfg)
        assert outcome.status == "FAIL"
        # only the genuinely-unset var is reported missing -- VCS_HOME_SET
        # was present so VCS_HOME must not be listed.
        assert "UVM_HOME" in outcome.detail
        assert "'VCS_HOME'" not in outcome.detail

    def test_skips_when_no_required_vars_configured(self):
        cfg = pf.PreflightConfig(required_env_vars=[])
        outcome = pf.check_env_vars(_ScriptedRunner([]), cfg)
        assert outcome.status == "SKIP"

    def test_builds_csh_dollar_question_syntax_not_bare_dollar_var(self):
        """Real finding, 2026-09-03: this project's real remote server's
        login shell is tcsh, where a bare `$VAR` on an unset variable is a
        hard error ('VCS_HOME: Undefined variable.'), not an empty string
        -- confirmed live. The command built for the csh/tcsh branch must
        use `$?VAR`, never `$VAR` alone."""
        cmd = pf._build_env_check_command(["VCS_HOME"], "csh")
        assert "$?VCS_HOME" in cmd
        assert "echo $VCS_HOME" not in cmd

    def test_builds_sh_syntax_without_bare_printenv_env_set_export(self):
        """Real finding, 2026-09-03: the persistent relay's own credential-
        inspection filter (tools/remote/remote_relay.py) denies any bare
        `printenv`/`env`/`set`/`export` command outright (confirmed live:
        `printenv VCS_HOME` -> CREDENTIAL_INSPECTION_DENIED), regardless of
        which variable follows. The sh/bash branch must never emit one of
        those as a bare command."""
        cmd = pf._build_env_check_command(["VCS_HOME"], "sh")
        for banned in ("printenv", "env ", "export ", " set "):
            assert banned not in cmd


class TestConfigFromDict:
    def test_overrides_win_over_dict(self):
        cfg = pf.config_from_dict({"queue": "vcs", "workdir": "/old"}, queue="other", workdir="/new")
        assert cfg.queue == "other"
        assert cfg.workdir == "/new"

    def test_none_overrides_do_not_clobber_dict_value(self):
        cfg = pf.config_from_dict({"queue": "vcs"}, queue=None)
        assert cfg.queue == "vcs"

    def test_unknown_keys_in_dict_are_ignored(self):
        cfg = pf.config_from_dict({"queue": "vcs", "configured_by": "someone"})
        assert cfg.queue == "vcs"
        assert not hasattr(cfg, "configured_by")

    def test_empty_dict_gives_dataclass_defaults(self):
        cfg = pf.config_from_dict(None)
        assert cfg == pf.PreflightConfig()


class TestRunPreflightAggregate:
    def _all_pass_cfg(self):
        return pf.PreflightConfig(
            queue="vcs", workdir="/home/svcacct/DV/UVM/USB/usb_uvm/sim",
            license_server="2900@host-a", license_features=["VCSRuntime"],
            required_env_vars=["VCS_HOME"],
        )

    def test_overall_pass_when_every_check_passes(self):
        cfg = self._all_pass_cfg()
        runner = _ScriptedRunner([
            _result(stdout=REAL_LMSTAT_VCS_HEADER),       # license
            _result(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),  # queue
            _result(stdout="host-c\n"),                     # host
            _result(stdout=REAL_DF_WORKDIR),               # disk
            _result(stdout="DIR_EXISTS\nDIR_WRITABLE\n"),  # workdir
            _result(stdout="VCS_HOME_SET\n"),              # env
        ])
        result = pf.run_preflight(cfg, runner=runner)
        assert result.overall == "PASS"
        assert result.blocked_on == []
        assert len(result.checks) == 6

    def test_overall_blocked_when_env_vars_fail_real_scenario(self):
        """Reproduces this project's REAL live 2026-09-03 state: license,
        queue, host, disk, workdir all real-PASS, but the persistent
        relay's shell never sourced the EDA module load -> env vars
        genuinely UNSET -> the whole gate must BLOCK, not just warn."""
        cfg = self._all_pass_cfg()
        runner = _ScriptedRunner([
            _result(stdout=REAL_LMSTAT_VCS_HEADER),
            _result(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
            _result(stdout="host-c\n"),
            _result(stdout=REAL_DF_WORKDIR),
            _result(stdout="DIR_EXISTS\nDIR_WRITABLE\n"),
            _result(stdout=REAL_ENV_ALL_UNSET),
        ])
        result = pf.run_preflight(cfg, runner=runner)
        assert result.overall == "BLOCKED"
        assert result.blocked_on == ["eda_env_vars"]

    def test_any_single_failure_blocks_the_whole_gate(self):
        cfg = self._all_pass_cfg()
        runner = _ScriptedRunner([
            _result(ok=False, error="server down"),        # license FAILs
            _result(stdout=REAL_BQUEUES_VCS_OPEN_ACTIVE),
            _result(stdout="host-c\n"),
            _result(stdout=REAL_DF_WORKDIR),
            _result(stdout="DIR_EXISTS\nDIR_WRITABLE\n"),
            _result(stdout="VCS_HOME_SET\n"),
        ])
        result = pf.run_preflight(cfg, runner=runner)
        assert result.overall == "BLOCKED"
        assert "eda_license" in result.blocked_on

    def test_to_dict_never_a_bare_boolean(self):
        cfg = self._all_pass_cfg()
        runner = _ScriptedRunner([_result(ok=False, error="x")] * 6)
        result = pf.run_preflight(cfg, runner=runner)
        d = result.to_dict()
        assert isinstance(d["checks"], list)
        assert all({"name", "status", "detail"} <= set(c.keys()) for c in d["checks"])

    def test_default_runner_is_local_subprocess_when_none_injected(self, monkeypatch):
        used = {}

        class _Spy(pf.LocalCommandRunner):
            def __call__(self, cmd, timeout=60):
                used["called"] = True
                return _result(ok=False, error="not on PATH")

        monkeypatch.setattr(pf, "LocalCommandRunner", _Spy)
        cfg = self._all_pass_cfg()
        pf.run_preflight(cfg, runner=None)
        assert used.get("called") is True


class TestRemoteRelayCommandRunner:
    def test_reports_missing_vchost_vchop_without_importing_remote_exec(self, monkeypatch):
        # Explicit "" must mean "no host configured", not silently fall
        # back to this developer machine's own real VCHOST/VCHOP env vars
        # (which ARE set in this session -- see .work/
        # governance-preflight-report.md) -- so the env vars are removed
        # for this one test to isolate the "nothing configured at all"
        # case from this session's real, coincidentally-present relay.
        monkeypatch.delenv("VCHOST", raising=False)
        monkeypatch.delenv("VCHOP", raising=False)
        runner = pf.RemoteRelayCommandRunner(vchost="", vchop="")
        res = runner("hostname")
        assert res.ok is False
        assert res.error == "VC_HOST_HOP_NOT_CONFIGURED"

    def test_reports_relay_not_ready(self, monkeypatch):
        class _FakeRemoteExec:
            @staticmethod
            def read_relay_info(vchost, vchop):
                return None

        monkeypatch.setattr(pf, "_remote_exec_module", lambda: _FakeRemoteExec)
        runner = pf.RemoteRelayCommandRunner(vchost="vchost-b", vchop="host-c")
        res = runner("hostname")
        assert res.ok is False
        assert res.error == "RELAY_NOT_READY"

    def test_success_path_returns_real_stdout(self, monkeypatch):
        class _FakeRemoteExec:
            @staticmethod
            def read_relay_info(vchost, vchop):
                return {"host": "127.0.0.1", "port": 9, "token": "t"}

            @staticmethod
            def send_request(host, port, req, timeout=60):
                assert req["op"] == "run"
                assert req["cmd"] == "hostname"
                return {"ok": True, "exit_code": 0, "stdout": "host-c\n"}

        monkeypatch.setattr(pf, "_remote_exec_module", lambda: _FakeRemoteExec)
        runner = pf.RemoteRelayCommandRunner(vchost="vchost-b", vchop="host-c")
        res = runner("hostname")
        assert res.ok is True
        assert res.stdout == "host-c\n"


class TestLocalCommandRunner:
    def test_runs_real_subprocess_and_reports_command_not_found(self):
        runner = pf.LocalCommandRunner()
        res = runner("this_binary_definitely_does_not_exist_xyz123", timeout=10)
        assert res.ok is False

    def test_runs_real_subprocess_success(self):
        import sys
        runner = pf.LocalCommandRunner()
        res = runner(f'"{sys.executable}" -c "print(1)"', timeout=10)
        assert res.ok is True
        assert "1" in res.stdout
