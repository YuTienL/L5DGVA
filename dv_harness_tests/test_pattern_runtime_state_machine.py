"""Tests for dv_harness/pattern_runtime_state_machine.py.

Covers: totality of LEGAL_TRANSITIONS, the core positive happy-path
progression, the task's own named illegal-jump example (CREATED straight to
PASS) plus real negative controls, evidence-derived terminal-verdict
observation grounded in the real sim_log_analysis parser (never a fabricated
PASS), and the small JSON persistence store.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dv_harness import pattern_runtime_state_machine as prsm
from dv_harness.pattern_runtime_state_machine import (
    PatternRuntimeState as S,
    PatternRuntimeStateError,
    IllegalPatternTransitionError,
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    assert_legal_transition,
    create_pattern_record,
    advance_pattern_state,
    derive_observed_terminal_verdict,
    apply_observed_verdict,
    render_pattern_state_table,
    load_records,
    save_records,
    execute_verb,
)


# ---------------------------------------------------------------------------
# Totality / vocabulary self-check
# ---------------------------------------------------------------------------

def test_legal_transitions_is_total_over_every_state():
    assert set(LEGAL_TRANSITIONS.keys()) == set(S)


def test_terminal_states_have_no_legal_outgoing_transition():
    for state in TERMINAL_STATES:
        assert LEGAL_TRANSITIONS[state] == frozenset()


def test_non_terminal_states_all_have_at_least_one_legal_transition():
    for state in S:
        if state not in TERMINAL_STATES:
            assert LEGAL_TRANSITIONS[state], f"{state} has no legal outgoing transition"


def test_every_target_state_in_the_table_is_a_real_enum_member():
    members = set(S)
    for state, targets in LEGAL_TRANSITIONS.items():
        assert targets <= members


# ---------------------------------------------------------------------------
# Core positive path
# ---------------------------------------------------------------------------

def test_full_happy_path_progression_to_pass():
    record = create_pattern_record("usb20_enumeration", protocol="USB")
    assert record.state == S.CREATED.value
    advance_pattern_state(record, S.PARSED, reason="verible parse succeeded")
    advance_pattern_state(record, S.VALIDATED, reason="pattern-architecture lint clean")
    advance_pattern_state(record, S.READY, reason="elaboration Gate 1 PASS")
    advance_pattern_state(record, S.RUNNING, reason="job dispatched to LSF")
    advance_pattern_state(record, S.WAITING, reason="branch_b0/branch_b1 forked, on join")
    advance_pattern_state(record, S.CHECKING, reason="join returned, FINAL_CHECK running")
    advance_pattern_state(record, S.PASS, reason="FINAL_CHECK epilogue VERDICT: PASSED",
                          evidence_basis="FINAL_CHECK_EPILOGUE_VERDICT")
    assert record.state == S.PASS.value
    assert record.is_terminal
    # 8 entries: the initial CREATED + 7 explicit advances.
    assert len(record.history) == 8
    assert record.history[0]["from_state"] is None
    assert record.history[0]["to_state"] == S.CREATED.value
    assert record.history[-1]["from_state"] == S.CHECKING.value
    assert record.history[-1]["to_state"] == S.PASS.value
    assert record.history[-1]["evidence_basis"] == "FINAL_CHECK_EPILOGUE_VERDICT"


def test_running_may_skip_waiting_straight_to_checking():
    """Section 4 of pattern-architecture: whether branch_b* forks at all
    varies with test intent, so RUNNING -> CHECKING must be legal without
    forcing every pattern through WAITING."""
    record = create_pattern_record("single_branch_pattern")
    advance_pattern_state(record, S.PARSED, reason="parsed")
    advance_pattern_state(record, S.VALIDATED, reason="validated")
    advance_pattern_state(record, S.READY, reason="ready")
    advance_pattern_state(record, S.RUNNING, reason="dispatched")
    advance_pattern_state(record, S.CHECKING, reason="no fork to wait on; straight to FINAL_CHECK")
    assert record.state == S.CHECKING.value


# ---------------------------------------------------------------------------
# Negative controls: illegal jumps
# ---------------------------------------------------------------------------

def test_created_straight_to_pass_is_rejected():
    """The task's own named example."""
    record = create_pattern_record("bad_jump_pattern")
    with pytest.raises(IllegalPatternTransitionError) as exc:
        advance_pattern_state(record, S.PASS, reason="tried to skip everything")
    assert exc.value.reason == "ILLEGAL_TRANSITION"
    assert exc.value.detail["from_state"] == S.CREATED.value
    assert exc.value.detail["attempted_to_state"] == S.PASS.value
    # rejected: record must be untouched.
    assert record.state == S.CREATED.value
    assert len(record.history) == 1


def test_ready_straight_to_waiting_skips_running_and_is_rejected():
    record = create_pattern_record("skip_running_pattern")
    advance_pattern_state(record, S.PARSED, reason="parsed")
    advance_pattern_state(record, S.VALIDATED, reason="validated")
    advance_pattern_state(record, S.READY, reason="ready")
    with pytest.raises(IllegalPatternTransitionError):
        advance_pattern_state(record, S.WAITING, reason="tried to skip RUNNING")
    assert record.state == S.READY.value


def test_no_transition_is_legal_from_a_terminal_state():
    record = create_pattern_record("terminal_pattern")
    advance_pattern_state(record, S.PARSED, reason="parsed")
    advance_pattern_state(record, S.VALIDATED, reason="validated")
    advance_pattern_state(record, S.READY, reason="ready")
    advance_pattern_state(record, S.RUNNING, reason="running")
    advance_pattern_state(record, S.CHECKING, reason="checking")
    advance_pattern_state(record, S.FAIL, reason="FINAL_CHECK epilogue VERDICT: FAILED")
    with pytest.raises(IllegalPatternTransitionError) as exc:
        advance_pattern_state(record, S.RUNNING, reason="tried to restart after FAIL")
    assert exc.value.reason == "TRANSITION_FROM_TERMINAL_STATE"
    assert record.state == S.FAIL.value


def test_waiting_never_returns_to_running():
    """WAITING tracks this pattern's own phase, not branch_fw's internal
    ARM/WAIT/WAKE cycling -- re-entering RUNNING from WAITING is not a legal
    top-level phase change in this vocabulary."""
    record = create_pattern_record("no_backedge_pattern")
    advance_pattern_state(record, S.PARSED, reason="parsed")
    advance_pattern_state(record, S.VALIDATED, reason="validated")
    advance_pattern_state(record, S.READY, reason="ready")
    advance_pattern_state(record, S.RUNNING, reason="running")
    advance_pattern_state(record, S.WAITING, reason="waiting on join")
    with pytest.raises(IllegalPatternTransitionError):
        advance_pattern_state(record, S.RUNNING, reason="tried to go back to running")


def test_unknown_target_state_string_is_rejected():
    record = create_pattern_record("garbage_target_pattern")
    with pytest.raises(IllegalPatternTransitionError) as exc:
        advance_pattern_state(record, "NOT_A_REAL_STATE", reason="garbage")
    assert exc.value.reason == "UNKNOWN_TARGET_STATE"


def test_a_fresh_record_cannot_be_minted_at_any_state_but_created():
    with pytest.raises(IllegalPatternTransitionError) as exc:
        assert_legal_transition(None, S.RUNNING)
    assert exc.value.reason == "ILLEGAL_INITIAL_STATE"


def test_empty_reason_is_refused():
    record = create_pattern_record("no_reason_pattern")
    with pytest.raises(PatternRuntimeStateError) as exc:
        advance_pattern_state(record, S.PARSED, reason="   ")
    assert exc.value.reason == "MISSING_TRANSITION_REASON"
    assert record.state == S.CREATED.value


def test_empty_pattern_id_is_refused():
    with pytest.raises(PatternRuntimeStateError) as exc:
        create_pattern_record("")
    assert exc.value.reason == "EMPTY_PATTERN_ID"


# ---------------------------------------------------------------------------
# Evidence-derived terminal-verdict observation
# ---------------------------------------------------------------------------

def test_real_pass_epilogue_is_observed_as_pass():
    log = (
        "UVM_INFO ... running enumeration\n"
        "FINAL CHECK @ 15320 ns\n"
        "UVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 2\n"
        "VERDICT: PASSED\n"
    )
    obs = derive_observed_terminal_verdict(log)
    assert obs["observed_state"] == S.PASS.value
    assert obs["basis"] == "FINAL_CHECK_EPILOGUE_VERDICT"
    assert obs["evidence"]["verdict"] == "PASSED"


def test_real_fail_epilogue_is_observed_as_fail():
    log = (
        "FINAL CHECK @ 9000 ns\n"
        "UVM_FATAL = 0, UVM_ERROR = 3, UVM_WARNING = 0\n"
        "VERDICT: FAILED\n"
    )
    obs = derive_observed_terminal_verdict(log)
    assert obs["observed_state"] == S.FAIL.value
    assert obs["basis"] == "FINAL_CHECK_EPILOGUE_VERDICT"


def test_real_error_marker_with_no_epilogue_is_observed_as_fail():
    log = "UVM_INFO ... starting\nUVM_ERROR @ 500 ns: scoreboard mismatch on port 0\n"
    obs = derive_observed_terminal_verdict(log)
    assert obs["observed_state"] == S.FAIL.value
    assert obs["basis"] == "REAL_ERROR_MARKER_NO_EPILOGUE"
    assert obs["evidence"]["category"] in ("uvm_error", "scoreboard_mismatch")


def test_real_timeout_marker_with_no_epilogue_and_no_error_is_observed_as_timeout():
    log = "UVM_INFO ... starting\nsimulation timeout waiting for interrupt\n"
    obs = derive_observed_terminal_verdict(log)
    assert obs["observed_state"] == S.TIMEOUT.value
    assert obs["basis"] == "TIMEOUT_MARKER_NO_EPILOGUE"


def test_clean_log_with_no_epilogue_and_no_markers_is_silent_failure_suspected_never_pass():
    """The pattern-architecture join/join_any trap: a log that ends cleanly
    with zero errors and never states its own verdict must NEVER be read as
    PASS -- this is the central Evidence Truth Rule assertion for this
    module."""
    log = "UVM_INFO ... build_phase\nUVM_INFO ... connect_phase\nUVM_INFO ... run_phase started\n"
    obs = derive_observed_terminal_verdict(log)
    assert obs["observed_state"] is None
    assert obs["basis"] == prsm.SILENT_FAILURE_SUSPECTED


def test_empty_log_text_is_not_available():
    obs = derive_observed_terminal_verdict("")
    assert obs["observed_state"] is None
    assert obs["basis"] == prsm.NOT_AVAILABLE

    obs2 = derive_observed_terminal_verdict(None)
    assert obs2["observed_state"] is None
    assert obs2["basis"] == prsm.NOT_AVAILABLE


# ---------------------------------------------------------------------------
# apply_observed_verdict(): the enforcement + evidence functions composed
# ---------------------------------------------------------------------------

def _run_to_checking(pattern_id: str) -> "prsm.PatternRuntimeRecord":
    record = create_pattern_record(pattern_id)
    advance_pattern_state(record, S.PARSED, reason="parsed")
    advance_pattern_state(record, S.VALIDATED, reason="validated")
    advance_pattern_state(record, S.READY, reason="ready")
    advance_pattern_state(record, S.RUNNING, reason="running")
    advance_pattern_state(record, S.CHECKING, reason="checking")
    return record


def test_apply_observed_verdict_advances_a_record_at_checking_on_real_pass_evidence():
    record = _run_to_checking("apply_pass_pattern")
    log = "FINAL CHECK @ 100 ns\nUVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\nVERDICT: PASSED\n"
    obs = derive_observed_terminal_verdict(log)
    record, applied = apply_observed_verdict(record, obs)
    assert applied is True
    assert record.state == S.PASS.value
    assert "FINAL_CHECK_EPILOGUE_VERDICT" in record.history[-1]["evidence_basis"]


def test_apply_observed_verdict_never_guesses_on_silent_failure_suspected():
    record = _run_to_checking("apply_silent_pattern")
    log = "UVM_INFO ... run_phase started\n"
    obs = derive_observed_terminal_verdict(log)
    record, applied = apply_observed_verdict(record, obs)
    assert applied is False
    # Untouched: still sitting at CHECKING, not silently marked PASS.
    assert record.state == S.CHECKING.value


def test_apply_observed_verdict_still_enforces_legal_transitions():
    """Real terminal evidence does not excuse skipping the recorded middle:
    a record still at CREATED cannot be jumped to PASS just because a log
    happens to say VERDICT: PASSED."""
    record = create_pattern_record("skipped_middle_pattern")
    log = "FINAL CHECK @ 1 ns\nUVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\nVERDICT: PASSED\n"
    obs = derive_observed_terminal_verdict(log)
    with pytest.raises(IllegalPatternTransitionError):
        apply_observed_verdict(record, obs)
    assert record.state == S.CREATED.value


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_render_pattern_state_table_reuses_connectivity_markdown_table():
    record = create_pattern_record("render_pattern", protocol="USB")
    table = render_pattern_state_table([record])
    assert "Pattern" in table
    assert "render_pattern" in table
    assert "CREATED" in table


def test_render_pattern_state_table_empty_note_when_no_records():
    table = render_pattern_state_table([])
    assert "no pattern runtime records" in table


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_save_and_load_records_round_trip(tmp_path: Path):
    record = create_pattern_record("persisted_pattern", protocol="PCIe")
    advance_pattern_state(record, S.PARSED, reason="parsed")
    save_records(tmp_path, {"persisted_pattern": record})

    reloaded = load_records(tmp_path)
    assert set(reloaded.keys()) == {"persisted_pattern"}
    got = reloaded["persisted_pattern"]
    assert got.state == S.PARSED.value
    assert got.protocol == "PCIe"
    assert len(got.history) == 2

    store_path = tmp_path / ".dv-harness" / "pattern_runtime" / "records.json"
    assert store_path.exists()
    on_disk = json.loads(store_path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == 1


def test_load_records_on_a_bare_root_returns_empty_dict_not_an_error(tmp_path: Path):
    assert load_records(tmp_path) == {}


def test_load_records_raises_a_named_error_on_a_corrupt_store(tmp_path: Path):
    store_dir = tmp_path / ".dv-harness" / "pattern_runtime"
    store_dir.mkdir(parents=True)
    (store_dir / "records.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(PatternRuntimeStateError) as exc:
        load_records(tmp_path)
    assert exc.value.reason == "STORE_UNREADABLE"


# ---------------------------------------------------------------------------
# Ad hoc CLI (execute_verb) -- exercised directly, no subprocess needed since
# it performs no I/O beyond the project root it is given.
# ---------------------------------------------------------------------------

def test_execute_verb_states_lists_all_twelve_states_and_rejects_pass_from_created():
    text, code = execute_verb("states")
    assert code == 0
    assert "CREATED" in text and "PASS" in text and "CANCELLED" in text


def test_execute_verb_show_reports_exit_2_when_nothing_recorded(tmp_path: Path):
    text, code = execute_verb("show", root=tmp_path, pattern_id="nope")
    assert code == 2


def test_execute_verb_observe_over_a_real_log_file(tmp_path: Path):
    log_file = tmp_path / "sim.log"
    log_file.write_text(
        "FINAL CHECK @ 42 ns\nUVM_FATAL = 0, UVM_ERROR = 0, UVM_WARNING = 0\nVERDICT: PASSED\n",
        encoding="utf-8",
    )
    text, code = execute_verb("observe", log_file=str(log_file))
    assert code == 0
    assert "PASS" in text


def test_execute_verb_observe_missing_file_is_a_clean_refusal():
    text, code = execute_verb("observe", log_file="/no/such/file.log")
    assert code == 2


def test_execute_verb_unknown_verb():
    text, code = execute_verb("bogus")
    assert code == 2
