"""Unit tests for dv_harness/lsf_client.py.

BUG FIX (2026-08-28, gui-cli-completeness-audit): this module (bsub/bjobs/bkill
subprocess wrappers + agent-reported-vs-live reconciliation) had zero test
coverage anywhere in dv_harness_tests/ despite being a complete, real
implementation -- these tests close that gap. subprocess.run is mocked
throughout so the tests are deterministic and do not require a real LSF farm
(or even real `bsub`/`bjobs`/`bkill` binaries) to be on PATH.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from dv_harness import lsf_client


def _completed(stdout="", stderr="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestBsubSubmit:
    def test_parses_job_id_from_stdout(self):
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout="Job <123456> is submitted to queue <normal>.\n")) as m:
            job_id = lsf_client.bsub_submit("vcs -R sim1", queue="normal", cores=4)
        assert job_id == 123456
        argv = m.call_args.args[0]
        assert argv[:5] == ["bsub", "-q", "normal", "-n", "4"]
        assert argv[-1] == "vcs -R sim1"

    def test_includes_mem_and_run_dir_when_given(self):
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout="Job <1> is submitted.\n")) as m:
            lsf_client.bsub_submit("cmd", queue="q", cores=1, mem_mb=4096, run_dir="/proj/run1")
        argv = m.call_args.args[0]
        assert "-R" in argv and "rusage[mem=4096]" in argv
        assert "-cwd" in argv and "/proj/run1" in argv

    def test_unparseable_output_raises_lsf_unavailable(self):
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout="garbage, no job id here")):
            with pytest.raises(lsf_client.LsfUnavailableError):
                lsf_client.bsub_submit("cmd", queue="q")

    def test_bsub_not_on_path_raises_lsf_unavailable(self):
        with patch("dv_harness.lsf_client.subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(lsf_client.LsfUnavailableError):
                lsf_client.bsub_submit("cmd", queue="q")


class TestBjobsQuery:
    def test_single_job_query_returns_first_record(self):
        payload = json.dumps({"RECORDS": [{"JOBID": "42", "STAT": "RUN"}]})
        with patch("dv_harness.lsf_client.subprocess.run", return_value=_completed(stdout=payload)):
            rec = lsf_client.bjobs_query(42)
        assert rec == {"JOBID": "42", "STAT": "RUN"}

    def test_single_job_query_no_records_returns_placeholder(self):
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout=json.dumps({"RECORDS": []}))):
            rec = lsf_client.bjobs_query(42)
        assert rec == {"JOBID": "42", "STAT": None}

    def test_bjobs_query_many_maps_by_int_job_id(self):
        payload = json.dumps({"RECORDS": [
            {"JOBID": "1", "STAT": "DONE"}, {"JOBID": "2", "STAT": "PEND"},
        ]})
        with patch("dv_harness.lsf_client.subprocess.run", return_value=_completed(stdout=payload)):
            result = lsf_client.bjobs_query_many([1, 2, 3])
        assert result[1] == {"JOBID": "1", "STAT": "DONE"}
        assert result[2] == {"JOBID": "2", "STAT": "PEND"}
        assert result[3] == {}  # no record for job 3 -> empty dict, not KeyError

    def test_bjobs_query_many_empty_input_short_circuits_without_subprocess(self):
        with patch("dv_harness.lsf_client.subprocess.run") as m:
            result = lsf_client.bjobs_query_many([])
        assert result == {}
        m.assert_not_called()

    def test_malformed_json_raises_lsf_unavailable(self):
        with patch("dv_harness.lsf_client.subprocess.run", return_value=_completed(stdout="not json")):
            with pytest.raises(lsf_client.LsfUnavailableError):
                lsf_client.bjobs_query(1)

    @pytest.mark.parametrize("raw,expected", [
        ("PEND", "PEND"), ("PROV", "PEND"), ("WAIT", "PEND"),
        ("RUN", "RUN"), ("DONE", "DONE"), ("EXIT", "EXIT"),
        ("ZOMBI", "UNKNOWN"), (None, "UNKNOWN"), ("", "UNKNOWN"), ("NOT_A_REAL_STAT", "UNKNOWN"),
    ])
    def test_map_bjobs_stat_to_lsf_status(self, raw, expected):
        assert lsf_client.map_bjobs_stat_to_lsf_status(raw) == expected


class TestBkillJob:
    def test_returncode_nonzero_returns_false_without_polling(self):
        with patch("dv_harness.lsf_client.subprocess.run", return_value=_completed(returncode=1)) as m:
            ok = lsf_client.bkill_job(1)
        assert ok is False
        m.assert_called_once()  # bkill only, no bjobs poll after a failed bkill

    def test_no_verify_returns_true_immediately_on_success(self):
        with patch("dv_harness.lsf_client.subprocess.run", return_value=_completed(returncode=0)) as m:
            ok = lsf_client.bkill_job(1, verify=False)
        assert ok is True
        m.assert_called_once()

    def test_verify_polls_bjobs_until_job_leaves_run_pend(self):
        bkill_result = _completed(returncode=0)
        bjobs_result = _completed(stdout=json.dumps({"RECORDS": [{"JOBID": "1", "STAT": "EXIT"}]}))
        with patch("dv_harness.lsf_client.subprocess.run", side_effect=[bkill_result, bjobs_result]):
            with patch("dv_harness.lsf_client.time.sleep"):
                ok = lsf_client.bkill_job(1, verify=True, poll_timeout_s=10)
        assert ok is True

    def test_invalid_job_id_type_raises_valueerror(self):
        with pytest.raises(ValueError):
            lsf_client.bkill_job("not-an-int")
        with pytest.raises(ValueError):
            lsf_client.bkill_job(True)  # bool is technically an int subclass -- must still be rejected


class TestJobStatePersistence:
    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_then_load_round_trips(self):
        state = lsf_client.JobState(job_id=5, pattern="usb_smoke_01", lsf_status="PEND")
        lsf_client.save_job_state(self.tmp, state)
        loaded = lsf_client.load_job_state(self.tmp, 5)
        assert loaded.job_id == 5
        assert loaded.pattern == "usb_smoke_01"
        assert loaded.lsf_status == "PEND"

    def test_load_nonexistent_job_returns_default_state(self):
        loaded = lsf_client.load_job_state(self.tmp, 999)
        assert loaded.job_id == 999
        assert loaded.lsf_status == "UNKNOWN"

    def test_save_sets_fingerprint_and_change_time_on_first_write(self):
        state = lsf_client.JobState(job_id=7, lsf_status="PEND")
        assert state.state_fingerprint is None
        lsf_client.save_job_state(self.tmp, state)
        assert state.state_fingerprint is not None
        assert state.last_change_time is not None

    def test_save_is_idempotent_when_unchanged(self):
        state = lsf_client.JobState(job_id=8, lsf_status="RUN")
        lsf_client.save_job_state(self.tmp, state)
        first_fp = state.state_fingerprint
        first_time = state.last_change_time
        # Re-save an equivalent (but freshly constructed) state -- fingerprint
        # must match and last_change_time must NOT be bumped again.
        state2 = lsf_client.JobState(job_id=8, lsf_status="RUN")
        lsf_client.save_job_state(self.tmp, state2)
        on_disk = json.loads((self.tmp / ".dv-harness" / "lsf" / "jobs" / "8.json").read_text())
        assert on_disk["state_fingerprint"] == first_fp
        assert on_disk["last_change_time"] == first_time


class TestReconcileJob:
    def test_status_mismatch_recorded_as_warn_and_state_updated(self):
        state = lsf_client.JobState(job_id=1, lsf_status="PEND")
        live = {"JOBID": "1", "STAT": "RUN"}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "RUN"
        assert any(d.field == "lsf_status" and d.severity == "WARN" for d in discrepancies)

    def test_done_with_unknown_sim_status_is_critical_analysis_owed(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", sim_status="UNKNOWN")
        live = {"JOBID": "1", "STAT": "DONE"}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        crit = [d for d in discrepancies if d.severity == "CRITICAL"]
        assert len(crit) == 1
        assert crit[0].field == "sim_status"
        assert crit[0].live == "ANALYSIS_OWED"

    def test_mismatched_live_job_id_raises_by_default(self):
        state = lsf_client.JobState(job_id=1, lsf_status="PEND")
        live = {"JOBID": "999", "STAT": "RUN"}
        with pytest.raises(ValueError):
            lsf_client.reconcile_job(state, live)

    def test_matching_state_produces_no_discrepancies(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", sim_status="RUNNING",
                                     sim_log="/proj/run/1/sim.log")
        live = {"JOBID": "1", "STAT": "RUN"}
        _, discrepancies = lsf_client.reconcile_job(state, live)
        assert discrepancies == []

    def test_sim_log_not_containing_job_id_flags_warn(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", sim_log="/proj/run/other/sim.log")
        live = {"JOBID": "1", "STAT": "RUN"}
        _, discrepancies = lsf_client.reconcile_job(state, live)
        assert any(d.field == "sim_log" for d in discrepancies)

    def test_absent_record_retains_already_confirmed_done_status(self):
        # LSF has forgotten this job (aged past its own retention window),
        # but the DONE status was already confirmed by a prior real poll --
        # an absent record now must not destroy that fact.
        state = lsf_client.JobState(job_id=1, lsf_status="DONE", sim_status="PASS")
        live = {"JOBID": "1", "STAT": None}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "DONE"
        info = [d for d in discrepancies if d.severity == "INFO"]
        assert len(info) == 1
        assert info[0].field == "lsf_status"
        assert info[0].reported == "DONE"

    def test_absent_record_retains_already_confirmed_exit_status(self):
        state = lsf_client.JobState(job_id=1, lsf_status="EXIT", sim_status="FAIL")
        live = {"JOBID": "1", "STAT": None}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "EXIT"
        assert any(d.severity == "INFO" and d.field == "lsf_status" for d in discrepancies)

    def test_absent_record_retains_already_confirmed_killed_status(self):
        state = lsf_client.JobState(job_id=1, lsf_status="KILLED", sim_status="UNKNOWN")
        live = {"JOBID": "1", "STAT": None}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "KILLED"
        assert any(d.severity == "INFO" and d.field == "lsf_status" for d in discrepancies)

    def test_absent_record_still_overwrites_a_non_terminal_status(self):
        # This is the ORIGINAL, still-correct behavior: a job that was never
        # confirmed terminal genuinely becomes UNKNOWN when LSF has no
        # record of it at all -- that is real (if disappointing) new
        # information, not a case this fix protects.
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", sim_status="RUNNING")
        live = {"JOBID": "1", "STAT": None}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "UNKNOWN"
        assert any(d.severity == "WARN" and d.field == "lsf_status" for d in discrepancies)

    def test_retained_status_does_not_mark_state_as_changed(self):
        state = lsf_client.JobState(job_id=1, lsf_status="DONE", sim_status="PASS")
        original_fingerprint = state.fingerprint()
        live = {"JOBID": "1", "STAT": None}
        new_state, _ = lsf_client.reconcile_job(state, live)
        # No real change happened, so the fingerprint/change-time machinery
        # must not fire for a job whose recorded status was correctly retained.
        assert new_state.state_fingerprint != original_fingerprint or new_state.state_fingerprint is None
        # (state_fingerprint starts as None on a fresh JobState; the real
        # assertion that matters is that last_change_time stays None, since
        # reconcile_job() only sets it inside the `if changed:` block.)
        assert new_state.last_change_time is None

    def test_present_record_still_compares_normally_when_already_terminal(self):
        # A job recorded as DONE that a live poll ALSO reports as DONE (a
        # real, present record, not an absent one) must go through the
        # normal no-discrepancy path -- this fix only changes behavior for
        # an ABSENT record, never a present one.
        state = lsf_client.JobState(job_id=1, lsf_status="DONE", sim_status="PASS")
        live = {"JOBID": "1", "STAT": "DONE"}
        new_state, discrepancies = lsf_client.reconcile_job(state, live)
        assert new_state.lsf_status == "DONE"
        assert discrepancies == []


class TestReconcileBatch:
    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reconciles_and_persists_each_job(self):
        lsf_client.save_job_state(self.tmp, lsf_client.JobState(job_id=1, lsf_status="PEND"))
        lsf_client.save_job_state(self.tmp, lsf_client.JobState(job_id=2, lsf_status="PEND"))
        payload = json.dumps({"RECORDS": [
            {"JOBID": "1", "STAT": "RUN"}, {"JOBID": "2", "STAT": "DONE"},
        ]})
        with patch("dv_harness.lsf_client.subprocess.run", return_value=_completed(stdout=payload)):
            result = lsf_client.reconcile_batch(self.tmp, [1, 2])
        assert result[1][0].lsf_status == "RUN"
        assert result[2][0].lsf_status == "DONE"
        # persisted to disk, not just returned in-memory
        assert lsf_client.load_job_state(self.tmp, 1).lsf_status == "RUN"
        assert lsf_client.load_job_state(self.tmp, 2).lsf_status == "DONE"

    def test_job_id_mismatch_reports_critical_without_raising(self):
        # A live record whose own claimed JOBID disagrees with the key it was
        # filed under (only reachable via corrupted/adversarial data, not the
        # normal bjobs_query_many keying path -- so patch bjobs_query_many
        # directly rather than subprocess.run to construct that condition).
        lsf_client.save_job_state(self.tmp, lsf_client.JobState(job_id=1, lsf_status="PEND"))
        with patch("dv_harness.lsf_client.bjobs_query_many",
                   return_value={1: {"JOBID": "999", "STAT": "RUN"}}):
            result = lsf_client.reconcile_batch(self.tmp, [1])
        state, discrepancies = result[1]
        assert any(d.severity == "CRITICAL" for d in discrepancies)


class TestLoadEarlyFailPolicy:
    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_policy_file_returns_empty_dict(self):
        assert lsf_client.load_early_fail_policy(self.tmp) == {}

    def test_reads_real_policy_file_contents(self):
        policy_dir = self.tmp.joinpath(*lsf_client.EARLY_FAIL_POLICY_PATH[:-1])
        policy_dir.mkdir(parents=True, exist_ok=True)
        (policy_dir / "early_fail_policy.json").write_text(
            json.dumps({"kill_on_uvm_fatal": True, "uvm_error_threshold": 3}), encoding="utf-8")
        policy = lsf_client.load_early_fail_policy(self.tmp)
        assert policy == {"kill_on_uvm_fatal": True, "uvm_error_threshold": 3}

    def test_malformed_policy_file_returns_empty_dict_not_raise(self):
        policy_dir = self.tmp.joinpath(*lsf_client.EARLY_FAIL_POLICY_PATH[:-1])
        policy_dir.mkdir(parents=True, exist_ok=True)
        (policy_dir / "early_fail_policy.json").write_text("not json", encoding="utf-8")
        assert lsf_client.load_early_fail_policy(self.tmp) == {}


class TestEvaluateAutoKill:
    """Cases exercise exactly the toggles the real .dv-harness/lsf/early_fail_policy.json
    schema defines (uvm_error_threshold, kill_on_uvm_fatal,
    kill_on_uvm_error_above_threshold, kill_on_fatal_assertion,
    kill_on_simulator_crash, kill_on_explicit_fail_marker, allowlist) -- no
    invented policy keys."""

    REAL_POLICY = {
        "uvm_error_threshold": 0,
        "kill_on_uvm_fatal": True,
        "kill_on_uvm_error_above_threshold": True,
        "kill_on_fatal_assertion": True,
        "kill_on_simulator_crash": True,
        "kill_on_explicit_fail_marker": True,
        "kill_on_warning": False,
        "require_exact_job_id": True,
        "require_log_job_match": True,
        "allowlist": [],
        "preserve_other_jobs": True,
        "fix_proposal_required_after_early_fail": True,
    }

    def test_uvm_fatal_triggers_kill(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", uvm_fatal_count=1)
        decision = lsf_client.evaluate_auto_kill(state, self.REAL_POLICY)
        assert decision["should_kill"] is True
        assert "UVM_FATAL" in decision["reason"]

    def test_no_trigger_condition_met_returns_explicit_reason(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN")
        decision = lsf_client.evaluate_auto_kill(state, self.REAL_POLICY)
        assert decision["should_kill"] is False
        assert decision["reason"] == "NO_AUTO_KILL_TRIGGER_CONDITION_MET"

    def test_uvm_error_above_threshold_triggers_kill(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", uvm_error_count=1)
        decision = lsf_client.evaluate_auto_kill(state, self.REAL_POLICY)
        assert decision["should_kill"] is True
        assert "UVM_ERROR_COUNT_ABOVE_THRESHOLD" in decision["reason"]

    def test_uvm_error_at_or_below_threshold_does_not_trigger(self):
        policy = dict(self.REAL_POLICY, uvm_error_threshold=2)
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", uvm_error_count=2)
        decision = lsf_client.evaluate_auto_kill(state, policy)
        assert decision["should_kill"] is False

    def test_fatal_assertion_triggers_kill(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", assertion_failure=True)
        decision = lsf_client.evaluate_auto_kill(state, self.REAL_POLICY)
        assert decision["should_kill"] is True
        assert decision["reason"] == "FATAL_ASSERTION_DETECTED"

    def test_simulator_crash_triggers_kill(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", simulator_crash=True)
        decision = lsf_client.evaluate_auto_kill(state, self.REAL_POLICY)
        assert decision["should_kill"] is True
        assert decision["reason"] == "SIMULATOR_CRASH_DETECTED"

    def test_explicit_fail_marker_triggers_kill(self):
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", terminal_signature="RUN TRUNCATED")
        decision = lsf_client.evaluate_auto_kill(state, self.REAL_POLICY)
        assert decision["should_kill"] is True
        assert "EXPLICIT_FAIL_MARKER" in decision["reason"]

    def test_toggle_disabled_in_policy_suppresses_that_trigger(self):
        policy = dict(self.REAL_POLICY, kill_on_uvm_fatal=False)
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", uvm_fatal_count=5)
        decision = lsf_client.evaluate_auto_kill(state, policy)
        assert decision["should_kill"] is False
        assert decision["reason"] == "NO_AUTO_KILL_TRIGGER_CONDITION_MET"

    def test_allowlisted_pattern_never_killed_even_with_uvm_fatal(self):
        policy = dict(self.REAL_POLICY, allowlist=["usb_known_flaky_01"])
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", pattern="usb_known_flaky_01",
                                     uvm_fatal_count=1)
        decision = lsf_client.evaluate_auto_kill(state, policy)
        assert decision["should_kill"] is False
        assert "ALLOWLISTED" in decision["reason"]

    def test_non_running_job_never_killed_even_with_uvm_fatal(self):
        state = lsf_client.JobState(job_id=1, lsf_status="DONE", uvm_fatal_count=1)
        decision = lsf_client.evaluate_auto_kill(state, self.REAL_POLICY)
        assert decision["should_kill"] is False
        assert "JOB_NOT_RUNNING" in decision["reason"]

    def test_empty_policy_never_kills(self):
        # An unreadable/missing early_fail_policy.json (load_early_fail_policy's
        # {} fallback) must never be treated as "everything enabled".
        state = lsf_client.JobState(job_id=1, lsf_status="RUN", uvm_fatal_count=1,
                                     assertion_failure=True, simulator_crash=True,
                                     uvm_error_count=99, terminal_signature="RUN TRUNCATED")
        decision = lsf_client.evaluate_auto_kill(state, {})
        assert decision["should_kill"] is False
        assert decision["reason"] == "NO_AUTO_KILL_TRIGGER_CONDITION_MET"


class TestDiscoverLiveJobs:
    def test_parses_bjobs_json_output(self):
        raw = json.dumps({
            "RECORDS": [
                {"JOBID": "111", "STAT": "RUN", "QUEUE": "normal",
                 "EXEC_HOST": "host1", "JOB_NAME": "usb2_enum_1",
                 "SUBMIT_TIME": "Sep  1 10:00"},
                {"JOBID": "222", "STAT": "PEND", "QUEUE": "normal",
                 "EXEC_HOST": "", "JOB_NAME": "usb3_gen1_2",
                 "SUBMIT_TIME": "Sep  1 10:05"},
            ]
        })
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout=raw)) as m:
            jobs = lsf_client.discover_live_jobs("vcuser1")
        argv = m.call_args.args[0]
        assert argv[0] == "bjobs"
        assert "-u" in argv and "vcuser1" in argv
        # `-a` is load-bearing: without it bjobs lists only PEND/RUN/
        # SUSPENDED jobs, so a job that finishes between two poll cycles is
        # never observed in a terminal DONE/EXIT state and Part 3's
        # regression-list safety net structurally never fires.
        assert "-a" in argv
        assert jobs == [
            {"job_id": 111, "stat": "RUN", "queue": "normal",
             "exec_host": "host1", "job_name": "usb2_enum_1",
             "submit_time": "Sep  1 10:00"},
            {"job_id": 222, "stat": "PEND", "queue": "normal",
             "exec_host": "", "job_name": "usb3_gen1_2",
             "submit_time": "Sep  1 10:05"},
        ]

    def test_no_jobs_returns_empty_list(self):
        with patch("dv_harness.lsf_client.subprocess.run",
                   return_value=_completed(stdout=json.dumps({"RECORDS": []}))):
            assert lsf_client.discover_live_jobs("vcuser1") == []

    def test_lsf_unavailable_raises(self):
        with patch("dv_harness.lsf_client.subprocess.run",
                   side_effect=FileNotFoundError("no bjobs")):
            with pytest.raises(lsf_client.LsfUnavailableError):
                lsf_client.discover_live_jobs("vcuser1")


class TestRegisterExternalJob:
    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_job_state_matching_bsub_submit_shape(self):
        lsf_client.register_external_job(self.tmp, 999, log_path="/proj/sim/run/foo_1/sim.log",
                                          pattern="foo")
        loaded = lsf_client.load_job_state(self.tmp, 999)
        assert loaded.job_id == 999
        assert loaded.pattern == "foo"
        assert loaded.sim_log == "/proj/sim/run/foo_1/sim.log"
        assert loaded.lsf_status == "UNKNOWN"

    def test_pattern_optional(self):
        lsf_client.register_external_job(self.tmp, 1000, log_path="/proj/sim/run/bar/sim.log")
        loaded = lsf_client.load_job_state(self.tmp, 1000)
        assert loaded.pattern is None

    def test_reconcile_batch_treats_registered_job_like_bsub_submit_job(self):
        lsf_client.register_external_job(self.tmp, 2000, log_path="/proj/sim/run/baz/sim.log",
                                          pattern="baz")
        live = {"JOBID": "2000", "STAT": "DONE", "EXIT_CODE": "0",
                "EXEC_HOST": "host1", "QUEUE": "normal", "RUN_TIME": "10",
                "SUBMIT_TIME": "x", "JOB_NAME": "baz"}
        with patch("dv_harness.lsf_client._run_bjobs",
                   return_value={"RECORDS": [live]}):
            result = lsf_client.reconcile_batch(self.tmp, [2000])
        state, discrepancies = result[2000]
        assert state.lsf_status == "DONE"
        assert any(d.field == "sim_status" and d.severity == "CRITICAL" for d in discrepancies)
