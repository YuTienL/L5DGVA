"""Tests for dv_harness/task_return_model.py -- "no silent command failure":
every dispatched task must resolve to a real, evidence-grounded outcome,
never an assumed one.

The central fixture (`SYNTHETIC_SIM_LOG` below) is a small, clearly-labeled
synthetic sim.log carrying this module's own `TASK_RESULT: <id> => <OUTCOME>`
convention for five tasks (one of each canonical outcome) and deliberately
omitting any TASK_RESULT line at all for a sixth declared task
(`branch_a3_init`) -- the "at least one task with no recorded outcome"
fixture the task spec asks for. Every rule below is then proven either
against that one clean fixture or by a small targeted mutation of it, never
by fabricating a result the parser did not actually derive.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import task_return_model as trm

SYNTHETIC_SIM_LOG = """\
UVM_INFO @ 0 ns: reporter [RNTST] Running test soc_smoke_test...
UVM_INFO @ 100 ns: block [BLOCK_INIT] SoC global init started
TASK_RESULT: block_init => PASS
UVM_INFO @ 200 ns: branch_a0 [PORT_INIT] port 0 DUT+PHY init started
TASK_RESULT: branch_a0_init => PASS
UVM_INFO @ 300 ns: branch_a1 [PORT_INIT] port 1 DUT+PHY init started
TASK_RESULT: branch_a1_init => FAIL
UVM_INFO @ 400 ns: branch_a2 [PORT_INIT] port 2 DUT+PHY init started
TASK_RESULT: branch_a2_init => TIMEOUT
UVM_INFO @ 500 ns: branch_b0 [VIP_SEQ] port 0 VIP scenario dispatched
TASK_RESULT: branch_b0_seq => UNSUPPORTED
UVM_INFO @ 600 ns: branch_b1 [VIP_SEQ] port 1 VIP scenario dispatched
TASK_RESULT: branch_b1_seq => INVALID_ARGUMENT
UVM_INFO @ 700 ns: branch_b2 [VIP_SEQ] port 2 VIP scenario dispatched
TASK_RESULT: branch_b2_seq => ENVIRONMENT_ERROR
UVM_INFO @ 9999 ns: reporter [RNTST] test soc_smoke_test finished
FINAL CHECK @ 10000 ns
UVM_FATAL = 0, UVM_ERROR = 1, UVM_WARNING = 0
VERDICT: FAILED
"""

# branch_a3_init is declared but deliberately has NO TASK_RESULT line
# anywhere above -- the "silent failure suspected" case.
DECLARED_TASKS = [
    {"task_id": "block_init", "layer": "block"},
    {"task_id": "branch_a0_init", "layer": "branch_a0"},
    {"task_id": "branch_a1_init", "layer": "branch_a1"},
    {"task_id": "branch_a2_init", "layer": "branch_a2"},
    {"task_id": "branch_a3_init", "layer": "branch_a3"},
    {"task_id": "branch_b0_seq", "layer": "branch_b0"},
    {"task_id": "branch_b1_seq", "layer": "branch_b1"},
    {"task_id": "branch_b2_seq", "layer": "branch_b2"},
]


@pytest.fixture()
def report():
    return trm.cross_check_task_outcomes(DECLARED_TASKS, SYNTHETIC_SIM_LOG)


# ---------------------------------------------------------------------------
# Core positive path
# ---------------------------------------------------------------------------

def test_all_six_canonical_outcomes_resolve_correctly(report):
    by_id = {t["task_id"]: t for t in report["tasks"]}
    assert by_id["block_init"]["resolved_outcome"] == trm.TASK_RESULT_PASS
    assert by_id["branch_a0_init"]["resolved_outcome"] == trm.TASK_RESULT_PASS
    assert by_id["branch_a1_init"]["resolved_outcome"] == trm.TASK_RESULT_FAIL
    assert by_id["branch_a2_init"]["resolved_outcome"] == trm.TASK_RESULT_TIMEOUT
    assert by_id["branch_b0_seq"]["resolved_outcome"] == trm.TASK_RESULT_UNSUPPORTED
    assert (by_id["branch_b1_seq"]["resolved_outcome"]
            == trm.TASK_RESULT_INVALID_ARGUMENT)
    assert (by_id["branch_b2_seq"]["resolved_outcome"]
            == trm.TASK_RESULT_ENVIRONMENT_ERROR)


def test_each_resolved_task_carries_real_line_evidence(report):
    by_id = {t["task_id"]: t for t in report["tasks"]}
    ev = by_id["branch_a1_init"]["evidence"]
    assert len(ev) == 1
    # the TASK_RESULT line's real 1-indexed line number, independently
    # located in the fixture text rather than hardcoded against a count
    # that would silently go stale if the fixture gained a line above it.
    expected_line_no = next(
        i for i, line in enumerate(SYNTHETIC_SIM_LOG.splitlines(), start=1)
        if "TASK_RESULT: branch_a1_init" in line
    )
    assert ev[0]["line_no"] == expected_line_no
    assert "branch_a1_init" in ev[0]["line_text"]
    assert ev[0]["raw_outcome_token"] == "FAIL"


def test_job_epilogue_is_carried_as_real_supplementary_context(report):
    epilogue = report["job_epilogue"]
    assert epilogue is not None
    assert epilogue["uvm_error"] == 1
    assert epilogue["uvm_fatal"] == 0


def test_summary_counts_match_the_declared_task_list(report):
    assert report["declared_task_count"] == 8
    assert report["counts"][trm.TASK_RESULT_PASS] == 2
    assert report["counts"][trm.TASK_RESULT_FAIL] == 1
    assert report["counts"][trm.TASK_RESULT_TIMEOUT] == 1
    assert report["counts"][trm.TASK_RESULT_UNSUPPORTED] == 1
    assert report["counts"][trm.TASK_RESULT_INVALID_ARGUMENT] == 1
    assert report["counts"][trm.TASK_RESULT_ENVIRONMENT_ERROR] == 1
    assert report["counts"][trm.TASK_RESULT_SILENT_FAILURE_SUSPECTED] == 1


# ---------------------------------------------------------------------------
# The headline case: a task with NO recorded outcome anywhere in the log.
# ---------------------------------------------------------------------------

def test_task_with_no_recorded_outcome_is_flagged_silent_failure_suspected(report):
    by_id = {t["task_id"]: t for t in report["tasks"]}
    missing = by_id["branch_a3_init"]
    assert missing["resolved_outcome"] == trm.TASK_RESULT_SILENT_FAILURE_SUSPECTED
    assert missing["evidence"] == []
    assert "no TASK_RESULT line found" in missing["reason"]
    assert "branch_a3_init" in missing["reason"]


def test_silent_failure_suspected_is_never_read_as_pass_or_fail(report):
    by_id = {t["task_id"]: t for t in report["tasks"]}
    missing = by_id["branch_a3_init"]
    assert missing["resolved_outcome"] != trm.TASK_RESULT_PASS
    assert missing["resolved_outcome"] != trm.TASK_RESULT_FAIL


def test_all_tasks_resolved_is_false_when_any_task_is_silent_failure_suspected(report):
    assert report["silent_failure_suspected_count"] == 1
    assert report["all_tasks_resolved"] is False


def test_all_tasks_resolved_is_true_when_nothing_is_missing():
    tasks = ["block_init", "branch_a0_init"]
    clean_log = (
        "TASK_RESULT: block_init => PASS\n"
        "TASK_RESULT: branch_a0_init => PASS\n"
    )
    r = trm.cross_check_task_outcomes(tasks, clean_log)
    assert r["all_tasks_resolved"] is True
    assert r["silent_failure_suspected_count"] == 0


# ---------------------------------------------------------------------------
# Negative controls: never guess a specific outcome from weak/absent/
# conflicting evidence.
# ---------------------------------------------------------------------------

def test_unrecognized_outcome_token_is_silent_failure_suspected_not_a_guess():
    log = "TASK_RESULT: branch_a0_init => WEIRD_TOKEN_NOBODY_DEFINED\n"
    r = trm.cross_check_task_outcomes(["branch_a0_init"], log)
    t = r["tasks"][0]
    assert t["resolved_outcome"] == trm.TASK_RESULT_SILENT_FAILURE_SUSPECTED
    assert "unrecognized token is not evidence" in t["reason"]
    assert "WEIRD_TOKEN_NOBODY_DEFINED" in t["reason"]


def test_conflicting_outcomes_for_same_task_are_never_resolved_to_either_one():
    log = (
        "TASK_RESULT: branch_a0_init => PASS\n"
        "TASK_RESULT: branch_a0_init => FAIL\n"
    )
    r = trm.cross_check_task_outcomes(["branch_a0_init"], log)
    t = r["tasks"][0]
    assert t["resolved_outcome"] == trm.TASK_RESULT_SILENT_FAILURE_SUSPECTED
    assert "conflicting TASK_RESULT outcomes" in t["reason"]
    assert len(t["evidence"]) == 2


def test_repeated_agreeing_outcomes_resolve_cleanly_not_as_a_conflict():
    log = (
        "TASK_RESULT: branch_a0_init => PASS\n"
        "TASK_RESULT: branch_a0_init => PASSED\n"  # alias spelling, same canonical
    )
    r = trm.cross_check_task_outcomes(["branch_a0_init"], log)
    t = r["tasks"][0]
    assert t["resolved_outcome"] == trm.TASK_RESULT_PASS
    assert len(t["evidence"]) == 2


def test_a_task_id_that_is_a_substring_of_another_never_cross_matches():
    log = (
        "TASK_RESULT: branch_a0_init => PASS\n"
        "TASK_RESULT: branch_a01_init => FAIL\n"
    )
    r = trm.cross_check_task_outcomes(["branch_a0_init"], log)
    t = r["tasks"][0]
    # regex requires the captured task_id to end at a non [A-Za-z0-9_./-]
    # boundary implicitly via greedy matching against the actual token in
    # the log; branch_a0_init's own line must be the only evidence used.
    assert t["resolved_outcome"] == trm.TASK_RESULT_PASS
    assert len(t["evidence"]) == 1


def test_empty_declared_task_list_is_a_hard_input_error():
    with pytest.raises(trm.TaskReturnModelError) as exc_info:
        trm.cross_check_task_outcomes([], "irrelevant log text")
    assert exc_info.value.code == "NO_DECLARED_TASKS"


def test_duplicate_declared_task_id_is_a_hard_input_error():
    with pytest.raises(trm.TaskReturnModelError) as exc_info:
        trm.cross_check_task_outcomes(
            ["branch_a0_init", "branch_a0_init"], "irrelevant log text"
        )
    assert exc_info.value.code == "DUPLICATE_DECLARED_TASK_ID"


def test_declared_task_missing_task_id_is_a_hard_input_error():
    with pytest.raises(trm.TaskReturnModelError) as exc_info:
        trm.cross_check_task_outcomes([{"layer": "block_init"}], "log text")
    assert exc_info.value.code == "DECLARED_TASK_MISSING_TASK_ID"


def test_declared_task_wrong_shape_is_a_hard_input_error():
    with pytest.raises(trm.TaskReturnModelError) as exc_info:
        trm.cross_check_task_outcomes([12345], "log text")
    assert exc_info.value.code == "DECLARED_TASK_INVALID_SHAPE"


# ---------------------------------------------------------------------------
# find_task_result_occurrences() as its own unit
# ---------------------------------------------------------------------------

def test_find_task_result_occurrences_a_task_with_no_line_is_absent_not_empty():
    occ = trm.find_task_result_occurrences("TASK_RESULT: block_init => PASS\n")
    assert "block_init" in occ
    assert "never_mentioned_task" not in occ


def test_find_task_result_occurrences_captures_line_number_and_raw_token():
    log = "line one\nline two\nTASK_RESULT: branch_a0_init => TIMEOUT\n"
    occ = trm.find_task_result_occurrences(log)
    assert occ["branch_a0_init"][0]["line_no"] == 3
    assert occ["branch_a0_init"][0]["raw_outcome_token"] == "TIMEOUT"
    assert occ["branch_a0_init"][0]["canonical_outcome"] == trm.TASK_RESULT_TIMEOUT


# ---------------------------------------------------------------------------
# File wrapper + markdown rendering
# ---------------------------------------------------------------------------

def test_cross_check_task_outcomes_file_reads_a_real_file(tmp_path: Path):
    log_path = tmp_path / "sim.log"
    log_path.write_text(SYNTHETIC_SIM_LOG, encoding="utf-8")
    r = trm.cross_check_task_outcomes_file(DECLARED_TASKS, log_path)
    assert r["declared_task_count"] == 8
    assert r["silent_failure_suspected_count"] == 1


def test_cross_check_task_outcomes_file_tolerates_bad_bytes(tmp_path: Path):
    log_path = tmp_path / "sim.log"
    log_path.write_bytes(
        b"TASK_RESULT: branch_a0_init => PASS\n\xff\xfe garbage bytes\n"
    )
    r = trm.cross_check_task_outcomes_file(["branch_a0_init"], log_path)
    assert r["tasks"][0]["resolved_outcome"] == trm.TASK_RESULT_PASS


def test_render_task_outcome_table_includes_every_task_and_outcome(report):
    md = trm.render_task_outcome_table(report)
    assert "Task ID" in md
    assert "Resolved Outcome" in md
    for task_id in [
        "block_init", "branch_a0_init", "branch_a1_init", "branch_a2_init",
        "branch_a3_init", "branch_b0_seq", "branch_b1_seq", "branch_b2_seq",
    ]:
        assert task_id in md
    assert trm.TASK_RESULT_SILENT_FAILURE_SUSPECTED in md


def test_render_task_outcome_table_empty_report_uses_empty_note():
    empty_report = {"tasks": []}
    md = trm.render_task_outcome_table(empty_report)
    assert "no declared tasks" in md


# ---------------------------------------------------------------------------
# CLI (python -m dv_harness.task_return_model), driven as a real subprocess
# ---------------------------------------------------------------------------

def test_cli_exits_nonzero_when_a_task_is_silent_failure_suspected(tmp_path: Path):
    log_path = tmp_path / "sim.log"
    log_path.write_text(SYNTHETIC_SIM_LOG, encoding="utf-8")
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(json.dumps(DECLARED_TASKS), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.task_return_model",
         "--tasks", str(tasks_path), "--log", str(log_path), "--json"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["silent_failure_suspected_count"] == 1


def test_cli_exits_zero_when_every_task_resolves(tmp_path: Path):
    log_path = tmp_path / "sim.log"
    log_path.write_text("TASK_RESULT: block_init => PASS\n", encoding="utf-8")
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(json.dumps(["block_init"]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.task_return_model",
         "--tasks", str(tasks_path), "--log", str(log_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0
    assert "Task ID" in result.stdout
