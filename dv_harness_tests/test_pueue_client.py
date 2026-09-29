"""Tests for dv_harness/pueue_client.py (2026-09-03 task).

Two tiers, same discipline dv_harness_tests/test_preflight.py already
established for LocalCommandRunner:
  - Unit tests inject a fake ProcRunner/DaemonStarter -- no live pueue
    daemon required, exercise argv-building/JSON-parsing/error-handling.
  - A smaller set of REAL integration tests drive the actual installed
    pueue.exe/pueued.exe (skipped, not failed, if neither is found --
    pueue has no winget/choco package as of this writing, see
    dv_harness/pueue_client.py's own module docstring, so a CI/dev
    machine without the manually-fetched GitHub-release binary must not
    fail this suite). pueue is a local, offline daemon fully owned by
    this dev machine -- unlike the license server/scheduler
    preflight.py talks to, a real call into it from a test is
    legitimate, not a live-external-service violation.
"""
from __future__ import annotations

import json
import shutil

import pytest

from dv_harness import pueue_client as pc


def _fake_runner(script):
    """`script` maps a joined-argv-with-spaces prefix match to a ProcResult.
    Returns a ProcRunner closure that raises AssertionError on an
    unexpected call, so a test never silently gets a wrong/empty result."""
    calls = []

    def runner(argv, env, timeout):
        calls.append((argv, env, timeout))
        for prefix, result in script:
            if argv[1:1 + len(prefix)] == prefix:
                return result
        raise AssertionError(f"unexpected pueue invocation: {argv}")

    runner.calls = calls
    return runner


# --- env sanitization (the core real security finding) --------------------


class TestSanitizeEnv:
    def test_strips_credential_shaped_keys(self):
        env = {"VCPW": "secret123", "PATH": "/usr/bin", "MY_TOKEN": "abc",
               "SSH_ASKPASS": "/bin/askpass", "API_KEY": "xyz",
               "SAFE_VAR": "keep me"}
        out = pc._sanitize_env(env)
        assert "VCPW" not in out
        assert "MY_TOKEN" not in out
        assert "SSH_ASKPASS" not in out
        assert "API_KEY" not in out
        assert out["PATH"] == "/usr/bin"
        assert out["SAFE_VAR"] == "keep me"

    def test_never_mutates_input(self):
        env = {"VCPW": "secret", "PATH": "/x"}
        pc._sanitize_env(env)
        assert "VCPW" in env  # original untouched

    def test_client_env_call_is_always_sanitized(self):
        client = pc.PueueClient(runner=lambda a, e, t: pc.ProcResult(ok=True, stdout="0"))
        env = client._env()
        assert "VCPW" not in env


# --- binary resolution ---------------------------------------------------


class TestResolveBinary:
    def test_uses_path_when_present(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
        assert pc._resolve_binary("pueue") == "/usr/bin/pueue"

    def test_falls_back_to_extra_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        fake_exe = tmp_path / "pueue.exe"
        fake_exe.write_text("stub")
        assert pc._resolve_binary("pueue", extra_dirs=[str(tmp_path)]) == str(fake_exe)

    def test_returns_bare_name_when_nowhere_found(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert pc._resolve_binary("pueue", extra_dirs=[str(tmp_path)]) == "pueue"


# --- add() argv building ---------------------------------------------------


class TestAdd:
    def test_builds_expected_argv_and_parses_task_id(self):
        runner = _fake_runner([
            (["add", "-p", "-l", "build", "-g", "dv_harness", "--", "echo hi"],
             pc.ProcResult(ok=True, stdout="42\n")),
        ])
        client = pc.PueueClient(runner=runner)
        task_id = client.add("echo hi", label="build")
        assert task_id == 42

    def test_after_and_group_and_working_directory_flow_through(self):
        runner = _fake_runner([
            (["add", "-p", "-l", "verify", "-a", "3", "-g", "custom_grp",
              "-w", "/wd", "--", "make lint"],
             pc.ProcResult(ok=True, stdout="7")),
        ])
        client = pc.PueueClient(runner=runner)
        task_id = client.add("make lint", label="verify", after=[3], group="custom_grp",
                              working_directory="/wd")
        assert task_id == 7

    def test_multiple_after_deps(self):
        runner = _fake_runner([
            (["add", "-p", "-a", "1", "-a", "2", "-g", "dv_harness", "--", "cmd"],
             pc.ProcResult(ok=True, stdout="9")),
        ])
        client = pc.PueueClient(runner=runner)
        assert client.add("cmd", after=[1, 2]) == 9

    def test_raises_pueue_error_on_failure(self):
        runner = lambda a, e, t: pc.ProcResult(ok=False, error="BINARY_NOT_FOUND: no pueue")
        client = pc.PueueClient(runner=runner)
        with pytest.raises(pc.PueueError, match="BINARY_NOT_FOUND"):
            client.add("cmd")

    def test_raises_pueue_error_on_unparseable_task_id(self):
        runner = lambda a, e, t: pc.ProcResult(ok=True, stdout="not-a-number")
        client = pc.PueueClient(runner=runner)
        with pytest.raises(pc.PueueError, match="did not return a task id"):
            client.add("cmd")


# --- status/log JSON parsing -----------------------------------------------


class TestStatusAndLog:
    def test_status_parses_json(self):
        payload = {"tasks": {"0": {"status": {"Done": {"result": "Success"}}}}, "groups": {}}
        runner = lambda a, e, t: pc.ProcResult(ok=True, stdout=json.dumps(payload))
        client = pc.PueueClient(runner=runner)
        assert client.status() == payload

    def test_status_with_group_flag(self):
        runner = _fake_runner([
            (["status", "-j", "-g", "dv_harness"], pc.ProcResult(ok=True, stdout='{"tasks":{},"groups":{}}')),
        ])
        client = pc.PueueClient(runner=runner)
        client.status(group="dv_harness")

    def test_status_raises_on_bad_json(self):
        runner = lambda a, e, t: pc.ProcResult(ok=True, stdout="not json")
        client = pc.PueueClient(runner=runner)
        with pytest.raises(pc.PueueError, match="unparseable JSON"):
            client.status()

    def test_status_raises_on_command_failure(self):
        runner = lambda a, e, t: pc.ProcResult(ok=False, error="TIMEOUT: x")
        client = pc.PueueClient(runner=runner)
        with pytest.raises(pc.PueueError, match="TIMEOUT"):
            client.status()

    def test_log_full_flag_and_task_ids(self):
        runner = _fake_runner([
            (["log", "-j", "-f", "1", "2"], pc.ProcResult(ok=True, stdout='{"1":{},"2":{}}')),
        ])
        client = pc.PueueClient(runner=runner)
        result = client.log([1, 2], full=True)
        assert result == {"1": {}, "2": {}}


# --- wait() status-shape parsing (real captured pueue 4.0.4 shapes) --------


class TestWaitStatusParsing:
    def test_status_key_and_result_running(self):
        task = {"status": {"Running": {"start": "..."}}}
        assert pc.PueueClient._status_key_and_result(task) == ("Running", None)

    def test_status_key_and_result_done_success(self):
        task = {"status": {"Done": {"result": "Success"}}}
        assert pc.PueueClient._status_key_and_result(task) == ("Done", "Success")

    def test_status_key_and_result_done_failed(self):
        task = {"status": {"Done": {"result": {"Failed": 7}}}}
        state, result = pc.PueueClient._status_key_and_result(task)
        assert state == "Done"
        assert result == {"Failed": 7}

    def test_wait_polls_until_done_success(self):
        states = iter([
            {"tasks": {"5": {"status": {"Running": {}}}}, "groups": {}},
            {"tasks": {"5": {"status": {"Done": {"result": "Success"}}}}, "groups": {}},
        ])
        client = pc.PueueClient(runner=lambda a, e, t: pc.ProcResult(ok=True))
        client.status = lambda group=None: next(states)  # type: ignore[method-assign]
        result = client.wait(5, poll_interval=0.01, timeout=5)
        assert result == {"task_id": 5, "state": "Done", "result": "Success", "success": True}

    def test_wait_reports_failure_on_nonzero_exit(self):
        client = pc.PueueClient(runner=lambda a, e, t: pc.ProcResult(ok=True))
        client.status = lambda group=None: {  # type: ignore[method-assign]
            "tasks": {"5": {"status": {"Done": {"result": {"Failed": 7}}}}}, "groups": {}}
        result = client.wait(5, poll_interval=0.01, timeout=5)
        assert result["success"] is False
        assert result["result"] == {"Failed": 7}

    def test_wait_raises_on_missing_task(self):
        client = pc.PueueClient(runner=lambda a, e, t: pc.ProcResult(ok=True))
        client.status = lambda group=None: {"tasks": {}, "groups": {}}  # type: ignore[method-assign]
        with pytest.raises(pc.PueueError, match="not found"):
            client.wait(999, poll_interval=0.01, timeout=1)

    def test_wait_times_out_honestly(self):
        client = pc.PueueClient(runner=lambda a, e, t: pc.ProcResult(ok=True))
        client.status = lambda group=None: {  # type: ignore[method-assign]
            "tasks": {"5": {"status": {"Running": {}}}}, "groups": {}}
        result = client.wait(5, poll_interval=0.01, timeout=0.03)
        assert result["success"] is False
        assert result.get("timed_out") is True


# --- ensure_daemon() ---------------------------------------------------


class TestEnsureDaemon:
    def test_already_running_short_circuits(self):
        client = pc.PueueClient(runner=lambda a, e, t: pc.ProcResult(ok=True, stdout="{}"))
        started = {"called": False}
        client._daemon_starter = lambda argv, env: started.__setitem__("called", True)
        assert client.ensure_daemon() is True
        assert started["called"] is False

    def test_starts_daemon_when_not_running(self):
        attempts = {"n": 0}

        def runner(argv, env, timeout):
            attempts["n"] += 1
            # First call (the pre-check) fails; every call after the
            # daemon "starts" succeeds.
            return pc.ProcResult(ok=attempts["n"] > 1, stdout="{}")

        client = pc.PueueClient(runner=runner)
        started = {"called": False}
        client._daemon_starter = lambda argv, env: started.__setitem__("called", True)
        assert client.ensure_daemon(timeout=2) is True
        assert started["called"] is True

    def test_gives_up_honestly_after_timeout(self):
        client = pc.PueueClient(runner=lambda a, e, t: pc.ProcResult(ok=False, error="down"))
        client._daemon_starter = lambda argv, env: None
        assert client.ensure_daemon(timeout=0.05) is False


# --- enqueue_harness_chain() ------------------------------------------


class TestEnqueueHarnessChain:
    def test_chains_dependencies_in_order(self):
        added = []

        class FakeClient:
            def add(self, command, *, label=None, after=None, group=None):
                tid = len(added)
                added.append({"label": label, "command": command, "after": after, "group": group})
                return tid

        result = pc.enqueue_harness_chain(
            FakeClient(),
            [("build", "make compile"), ("verify", "make lint"), ("submit", "dv-harness lsf-submit ...")],
            group="dv_regression")
        assert [r["task_id"] for r in result] == [0, 1, 2]
        assert added[0]["after"] is None
        assert added[1]["after"] == [0]
        assert added[2]["after"] == [1]
        assert all(a["group"] == "dv_regression" for a in added)

    def test_never_fabricates_bsub_command(self):
        """The chain helper must pass every command through byte-for-byte
        -- it must never synthesize its own bsub/sbatch invocation."""
        captured = []

        class FakeClient:
            def add(self, command, *, label=None, after=None, group=None):
                captured.append(command)
                return len(captured) - 1

        submit_cmd = "dv-harness lsf-submit --queue vcs --command 'vcs -R sim1'"
        pc.enqueue_harness_chain(FakeClient(), [("submit", submit_cmd)])
        assert captured == [submit_cmd]


# --- config_from_dict -----------------------------------------------------


class TestConfigFromDict:
    def test_defaults(self):
        cfg = pc.config_from_dict()
        assert cfg.binary == "pueue"
        assert cfg.group == "dv_harness"

    def test_overrides_and_unknown_keys_ignored(self):
        cfg = pc.config_from_dict({"group": "cfg_group", "unknown_key": 1}, binary="custom_pueue")
        assert cfg.group == "cfg_group"
        assert cfg.binary == "custom_pueue"


# --- real integration tests against the actual installed pueue.exe --------

_REAL_PUEUE = pc._resolve_binary("pueue")
_HAS_REAL_PUEUE = shutil.which(_REAL_PUEUE) is not None or (
    __import__("pathlib").Path(_REAL_PUEUE).is_file() if _REAL_PUEUE != "pueue" else False)


@pytest.mark.skipif(not _HAS_REAL_PUEUE, reason="pueue not installed on this machine "
                     "(no winget/choco package exists; see pueue_client.py's module docstring "
                     "for the real GitHub-release install path)")
class TestRealPueueIntegration:
    @pytest.fixture(autouse=True)
    def _daemon(self):
        client = pc.PueueClient()
        assert client.ensure_daemon(timeout=15), "real pueued did not come up"
        yield client
        try:
            client.clean()
        except Exception:
            pass

    def test_real_version(self, _daemon):
        v = _daemon.version()
        assert "pueue" in v.lower()

    def test_real_add_and_wait_success(self, _daemon):
        tid = _daemon.add("echo real_pueue_test", label="real_test_ok")
        result = _daemon.wait(tid, poll_interval=0.2, timeout=15)
        assert result["success"] is True

    def test_real_add_and_wait_failure(self, _daemon):
        tid = _daemon.add("exit 3", label="real_test_fail")
        result = _daemon.wait(tid, poll_interval=0.2, timeout=15)
        assert result["success"] is False
        assert result["result"] == {"Failed": 3}

    def test_real_dependency_chain_success(self, _daemon):
        ids = pc.enqueue_harness_chain(
            _daemon, [("step1", "echo one"), ("step2", "echo two")])
        final = ids[-1]["task_id"]
        result = _daemon.wait(final, poll_interval=0.2, timeout=15)
        assert result["success"] is True

    def test_real_dependency_chain_propagates_failure(self, _daemon):
        ids = pc.enqueue_harness_chain(
            _daemon, [("bad_step", "exit 1"), ("never_runs", "echo should_not_run")])
        final = ids[-1]["task_id"]
        result = _daemon.wait(final, poll_interval=0.2, timeout=15)
        assert result["success"] is False

    def test_real_task_env_is_sanitized(self, _daemon, monkeypatch):
        """The load-bearing security property, exercised against the
        REAL daemon end-to-end: a credential-shaped env var present in
        THIS test process's own environment must never appear in the
        real pueue state this task is added under."""
        monkeypatch.setenv("VCPW", "should_never_persist")
        tid = _daemon.add("echo env_test", label="env_sanitize_test")
        _daemon.wait(tid, poll_interval=0.2, timeout=15)
        log = _daemon.log([tid], full=True)
        raw = json.dumps(log)
        assert "should_never_persist" not in raw
