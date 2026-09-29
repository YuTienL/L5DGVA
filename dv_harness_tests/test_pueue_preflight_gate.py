"""Tests for the un-gated farm-submission guard that connects the Execution
Layer (pueue) to the Preflight Agent (2026-09-04 gap closure).

The architecture the harness claims is `Claude -> pueue -> harness task ->
LSF/Slurm`, with `dv_harness/preflight.py`'s license/queue/host/disk/workdir/
env gate standing between the harness task and the farm. Before this guard,
that edge was real for the CLI path (`dv-harness lsf-submit` ->
`lsf_client.bsub_submit_with_preflight()`) but only CONVENTIONAL for pueue:
`pueue_client.add()` accepted any command string, so a bare `bsub -q vcs simv`
task would have submitted a real job with `run_preflight()` never consulted.

These tests prove the edge is now code, in both directions:
  - refusal: a raw `bsub`/`sbatch` task is rejected BEFORE `pueue add` is
    invoked at all (the injected ProcRunner records zero calls),
  - acceptance: the sanctioned `dv-harness lsf-submit ...` task command is
    passed through byte-for-byte, and
  - connection: that SAME accepted string, parsed by the real CLI and run
    through the real `lsf_client.bsub_submit_with_preflight()`, genuinely
    reaches `preflight.run_preflight()` and is BLOCKED before any `bsub`.

Real-subprocess CLI coverage follows test_cli_preflight.py's established
style; no live pueue daemon, license server, or scheduler is required.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dv_harness import lsf_client
from dv_harness import preflight as pf
from dv_harness import pueue_client as pc

ROOT = Path(__file__).resolve().parents[1]

# The real, sanctioned submit-step command shape a pueue chain carries -- the
# one `enqueue_harness_chain()`'s own docstring names. Used by both the
# acceptance test and the end-to-end connection test below, so the two cannot
# drift into testing different strings.
GATED_SUBMIT_TASK = (
    'dv-harness lsf-submit "simv +UVM_TESTNAME=usb_link_up_test" '
    '--queue vcs --run-dir /proj/usb31/run --pattern usb_link_up'
)


def _recording_runner(result):
    """ProcRunner that records every invocation. A guard that fires correctly
    must leave `calls` empty -- proving the refusal happened before pueue was
    reached, not after a task was already enqueued."""
    calls = []

    def runner(argv, env, timeout):
        calls.append(argv)
        return result

    runner.calls = calls
    return runner


def _client(runner):
    return pc.PueueClient(pc.PueueConfig(), runner=runner,
                          daemon_starter=lambda argv, env: None)


# --- command-position detection -------------------------------------------


class TestFindFarmSubmitTokens:
    @pytest.mark.parametrize("command,expected", [
        ("bsub -q vcs simv", ["bsub"]),
        ("sbatch job.sh", ["sbatch"]),
        ("/usr/lsf/bin/bsub -q vcs -n 4 simv", ["bsub"]),
        ("LSF_ENVDIR=/etc/lsf bsub -q vcs simv", ["bsub"]),
        ("cd /proj/run && bsub -q vcs simv", ["bsub"]),
        ("make compile; bsub -q vcs simv", ["bsub"]),
        ("ssh host-a bsub -q vcs simv", ["bsub"]),
        # The load-bearing one: this is the exact pueue step shape this
        # project's own remote transport uses, so a raw bsub hidden inside
        # its quoted payload must still be caught.
        ('python tools/remote/remote_exec.py "bsub -q vcs simv"', ["bsub"]),
        ("$(bsub -q vcs simv)", ["bsub"]),
        ("bsub -q vcs a.sh && sbatch b.sh", ["bsub", "sbatch"]),
    ])
    def test_real_submission_shapes_are_detected(self, command, expected):
        assert pc.find_farm_submit_tokens(command) == expected

    @pytest.mark.parametrize("command", [
        # Mentions the word, does not run it.
        "grep bsub /proj/usb31/run/sim.log",
        "wc -l bsub_history.txt",
        # A differently-named binary that merely starts with the token.
        "./rerun_bsub_failures.sh --tier NIGHTLY",
        "bsubmit --dry-run",
        # The real, gated route and the ordinary local harness steps.
        GATED_SUBMIT_TASK,
        'python tools/remote/remote_exec.py "make compile"',
        "just build vcs /proj/usb31/run lic01@server",
        "dv-harness preflight --remote --queue vcs",
    ])
    def test_non_submission_commands_are_not_flagged(self, command):
        assert pc.find_farm_submit_tokens(command) == []


class TestGatedSubmitMarkers:
    def test_function_marker_is_read_off_the_live_code_object(self):
        """The accepted spelling is derived from the real gated entry point,
        not copy-pasted -- renaming that function changes this marker instead
        of leaving the guard quietly accepting a name nothing answers to."""
        markers = pc.gated_submit_markers()
        assert lsf_client.bsub_submit_with_preflight.__name__ in markers
        assert pc.GATED_SUBMIT_CLI_SUBCOMMAND in markers

    def test_cli_subcommand_marker_is_a_real_dv_harness_subcommand(self):
        """`lsf-submit` must actually exist as the CLI subcommand whose
        handler calls the gated entry point -- otherwise the guard's advertised
        route forward would be a dead string."""
        r = subprocess.run([sys.executable, "-m", "dv_harness.cli", "--help"],
                           cwd=str(ROOT), capture_output=True, text=True,
                           timeout=60, encoding="utf-8")
        assert pc.GATED_SUBMIT_CLI_SUBCOMMAND in r.stdout


# --- refusal: pueue never even sees an un-gated submission ------------------


class TestAddRefusesUngatedSubmission:
    def test_raw_bsub_is_refused_before_pueue_add_runs(self):
        runner = _recording_runner(pc.ProcResult(ok=True, stdout="7\n"))
        with pytest.raises(pc.UngatedFarmSubmissionError) as exc_info:
            _client(runner).add("bsub -q vcs simv")
        assert runner.calls == []  # no `pueue add` was ever invoked
        assert exc_info.value.tokens == ["bsub"]
        assert "preflight" in str(exc_info.value)
        assert pc.GATED_SUBMIT_CLI_SUBCOMMAND in str(exc_info.value)

    def test_raw_sbatch_is_refused(self):
        runner = _recording_runner(pc.ProcResult(ok=True, stdout="7\n"))
        with pytest.raises(pc.UngatedFarmSubmissionError):
            _client(runner).add("sbatch /proj/usb31/run/job.sh")
        assert runner.calls == []

    def test_remote_exec_wrapped_bsub_is_refused(self):
        runner = _recording_runner(pc.ProcResult(ok=True, stdout="7\n"))
        with pytest.raises(pc.UngatedFarmSubmissionError):
            _client(runner).add('python tools/remote/remote_exec.py "bsub -q vcs simv"')
        assert runner.calls == []

    def test_error_is_not_a_pueue_error_subclass(self):
        """A caller catching PueueError ("pueue itself failed") must not
        silently absorb a refused un-gated submission -- the same deliberate
        class separation lsf_client keeps between PreflightBlockedError and
        LsfUnavailableError."""
        assert not issubclass(pc.UngatedFarmSubmissionError, pc.PueueError)

    def test_gated_marker_in_a_different_segment_does_not_launder_a_raw_bsub(self):
        """`dv-harness lsf-submit A && bsub -q vcs B` must NOT pass: the
        marker has to be in the same shell segment as the token it excuses,
        otherwise one gated step would whitelist an un-gated one beside it."""
        runner = _recording_runner(pc.ProcResult(ok=True, stdout="9\n"))
        with pytest.raises(pc.UngatedFarmSubmissionError) as exc_info:
            _client(runner).add(f"{GATED_SUBMIT_TASK} && bsub -q vcs other_simv")
        assert exc_info.value.tokens == ["bsub"]
        assert runner.calls == []

    def test_explicit_override_is_the_only_way_through(self):
        runner = _recording_runner(pc.ProcResult(ok=True, stdout="11\n"))
        task_id = _client(runner).add("bsub -q vcs simv", allow_ungated_farm_submit=True)
        assert task_id == 11
        assert len(runner.calls) == 1


# --- acceptance: the gated route passes through unchanged -------------------


class TestAddAcceptsGatedSubmission:
    def test_lsf_submit_task_is_enqueued_byte_for_byte(self):
        runner = _recording_runner(pc.ProcResult(ok=True, stdout="42\n"))
        task_id = _client(runner).add(GATED_SUBMIT_TASK, label="submit")
        assert task_id == 42
        argv = runner.calls[0]
        assert argv[-1] == GATED_SUBMIT_TASK  # never rewritten by the guard
        assert "--" in argv

    def test_ordinary_local_steps_are_untouched(self):
        runner = _recording_runner(pc.ProcResult(ok=True, stdout="1\n"))
        assert _client(runner).add('python tools/remote/remote_exec.py "make compile"') == 1


# --- chain: all steps are checked before any is enqueued --------------------


class TestChainPreValidation:
    def test_ungated_step_leaves_the_whole_chain_un_enqueued(self):
        runner = _recording_runner(pc.ProcResult(ok=True, stdout="3\n"))
        steps = [("build", 'python tools/remote/remote_exec.py "make compile"'),
                 ("submit", "bsub -q vcs simv")]
        with pytest.raises(pc.UngatedFarmSubmissionError):
            pc.enqueue_harness_chain(_client(runner), steps)
        # The build step must NOT be sitting in pueue half-started.
        assert runner.calls == []

    def test_fully_gated_chain_enqueues_every_step(self):
        results = iter([pc.ProcResult(ok=True, stdout="1\n"),
                        pc.ProcResult(ok=True, stdout="2\n")])
        calls = []

        def runner(argv, env, timeout):
            calls.append(argv)
            return next(results)

        steps = [("build", 'python tools/remote/remote_exec.py "make compile"'),
                 ("submit", GATED_SUBMIT_TASK)]
        enqueued = pc.enqueue_harness_chain(_client(runner), steps)
        assert [e["task_id"] for e in enqueued] == [1, 2]
        assert calls[1][-1] == GATED_SUBMIT_TASK
        assert "-a" in calls[1] and "1" in calls[1]  # real dependency on step 1


# --- the connection itself: accepted task command -> preflight gate ---------


class TestAcceptedTaskCommandReallyReachesPreflight:
    """The point of the guard: the ONE task shape it lets through is the one
    that genuinely runs the Preflight Agent. Testing the guard and the gate in
    isolation would not show that -- these drive the accepted string all the
    way into run_preflight()."""

    def test_accepted_command_names_the_gated_entry_point(self):
        """The accepted task string invokes `dv-harness lsf-submit`, and that
        subcommand's handler is the one call site of
        bsub_submit_with_preflight() -- verified against the real cli source,
        not assumed."""
        src = (ROOT / "dv_harness" / "cli.py").read_text(encoding="utf-8")
        assert f'args.cmd == "{pc.GATED_SUBMIT_CLI_SUBCOMMAND}"' in src
        assert "lsf_client.bsub_submit_with_preflight(" in src
        pc.assert_farm_submission_is_preflight_gated(GATED_SUBMIT_TASK)

    def test_that_entry_point_runs_preflight_first_and_blocks_bsub(self):
        blocked = pf.PreflightResult(
            overall="BLOCKED",
            checks=[pf.CheckOutcome(name="license", status="FAIL",
                                     detail="feature vcs starved: 12/12 in use")],
            blocked_on=["license"],
        )
        with patch("dv_harness.preflight.run_preflight", return_value=blocked) as run_pf, \
             patch("dv_harness.lsf_client.bsub_submit") as bsub:
            with pytest.raises(lsf_client.PreflightBlockedError):
                lsf_client.bsub_submit_with_preflight(
                    "simv +UVM_TESTNAME=usb_link_up_test", queue="vcs",
                    run_dir="/proj/usb31/run")
        run_pf.assert_called_once()
        bsub.assert_not_called()

    def test_real_cli_lsf_submit_blocks_on_this_machine(self):
        """End-to-end, real subprocess: this dev machine has no lmutil/
        bqueues/df, so the accepted task command's own CLI genuinely reports
        PREFLIGHT_BLOCKED and exits non-zero rather than submitting -- the
        real absence exercising the real gate, same convention
        test_cli_preflight.py already uses."""
        tmp = Path(tempfile.mkdtemp())
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp),
             "lsf-submit", "simv +UVM_TESTNAME=usb_link_up_test",
             "--queue", "vcs", "--run-dir", str(tmp)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120, encoding="utf-8")
        assert r.returncode != 0
        out = json.loads(r.stdout.strip() or "{}")
        assert out.get("error") == "PREFLIGHT_BLOCKED"
        assert out["preflight"]["overall"] == "BLOCKED"


# --- CLI surface ------------------------------------------------------------


class TestCliPueueRefusesUngatedSubmission:
    """`dv-harness pueue add`/`chain` must refuse an un-gated submission with
    its own distinct error code and exit status -- and must do so WITHOUT
    needing a live pueued, so the refusal never degrades into
    PUEUED_NOT_AVAILABLE on a machine where pueue is not installed."""

    @staticmethod
    def _run(*args):
        tmp = Path(tempfile.mkdtemp())
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120, encoding="utf-8")
        return r.returncode, json.loads(r.stdout.strip() or "{}")

    def test_chain_with_raw_bsub_submit_step_is_refused(self):
        code, out = self._run("pueue", "chain",
                              "--build", 'python tools/remote/remote_exec.py "make compile"',
                              "--submit", "bsub -q vcs simv")
        assert code == 2
        assert out["error"] == "UNGATED_FARM_SUBMISSION"
        assert out["step"] == "submit"
        assert out["tokens"] == ["bsub"]
        assert out["use_instead"] == f"dv-harness {pc.GATED_SUBMIT_CLI_SUBCOMMAND}"

    def test_add_has_no_bypass_flag(self):
        """The library-level override exists for the guard's known
        false-positive shape; the CLI deliberately exposes no way to reach
        it."""
        r = subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "pueue", "add", "--help"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60, encoding="utf-8")
        assert "allow-ungated" not in r.stdout
        assert "allow_ungated" not in r.stdout
