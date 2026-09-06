"""dv_harness/command_error_taxonomy.py -- per-command-dispatch error classifier.

WHAT THESE TESTS ARE FOR. Not "a function returns a string". The things that
can actually go wrong with a classifier like this are:

  1. a message classified into a category its text does not actually support
     (a forced guess) -- tested per category by asserting the SPECIFIC
     `matched_evidence` substring the rule found, not merely that SOME
     category came back;
  2. an unmatchable message silently defaulting to a named category instead
     of the honest `UNCLASSIFIED` -- the Evidence Truth Rule's own concern,
     tested directly with real ambiguous/empty inputs;
  3. the priority order silently changing (e.g. a message carrying both a
     BRANCH_OWNERSHIP_ERROR signal and a plain UNKNOWN_COMMAND phrase landing
     on the wrong one) -- tested by asserting `CLASSIFICATION_ORDER` covers
     every category and by mixed-signal fixtures that pin the documented
     priority;
  4. this module's vocabulary silently colliding with `dv_harness.models.Status`
     or `dv_harness.loop_budget.FailureType` as either grows -- tested by
     actually calling both assertion functions, not by eyeballing the lists;
  5. the `CHECK_FAILURE`/`TASK_ERROR` reuse of `sim_log_analysis` drifting from
     what that module really classifies -- tested against REAL
     `sim_log_analysis.parse_sim_log()`/`classify_signatures()` output, never
     a re-implemented keyword list of this test's own.

Every fixture below is a plausible, hand-written dispatch-failure text (an
exception message or a sim.log excerpt), never a real captured incident this
project does not have -- consistent with this module reading only the text a
caller hands it and inventing no DUT/VIP/timing content of its own.
"""
from __future__ import annotations

import pytest

from dv_harness.command_error_taxonomy import (
    CATEGORIES,
    CLASSIFICATION_ORDER,
    UNCLASSIFIED,
    DispatchFailureClassification,
    assert_disjoint_from_loop_budget_failure_type,
    assert_disjoint_from_verification_verdict_vocabulary,
    classify_dispatch_failure,
)


# ---------------------------------------------------------------------------
# Vocabulary integrity
# ---------------------------------------------------------------------------

def test_classification_order_covers_exactly_the_eleven_categories():
    assert set(CLASSIFICATION_ORDER) == set(CATEGORIES)
    assert len(CATEGORIES) == 11
    assert UNCLASSIFIED not in CATEGORIES


def test_vocabulary_disjoint_from_verification_verdict_vocabulary():
    # Must not raise -- a real drift here would raise AssertionError.
    assert_disjoint_from_verification_verdict_vocabulary()


def test_vocabulary_disjoint_from_loop_budget_failure_type():
    assert_disjoint_from_loop_budget_failure_type()


def test_result_is_a_dataclass_with_the_documented_fields():
    result = classify_dispatch_failure("unknown command 'foo_task' not found")
    assert isinstance(result, DispatchFailureClassification)
    d = result.to_dict()
    assert set(d.keys()) == {"category", "matched_evidence", "rule_id", "matched_line"}


# ---------------------------------------------------------------------------
# Positive path: one clean fixture per category
# ---------------------------------------------------------------------------

def test_unknown_command():
    text = "dispatch error: command 'run_link_train' not found in dispatch table"
    r = classify_dispatch_failure(text)
    assert r.category == "UNKNOWN_COMMAND"
    assert "not found" in r.matched_evidence.lower()


def test_syntax_error():
    text = "command.txt:42: syntax error near 'endtask' -- missing semicolon"
    r = classify_dispatch_failure(text)
    assert r.category == "SYNTAX_ERROR"
    assert "syntax error" in r.matched_evidence.lower()


def test_invalid_argument():
    text = "task usb_port_bringup called with invalid argument: port_id=-1"
    r = classify_dispatch_failure(text)
    assert r.category == "INVALID_ARGUMENT"
    assert "invalid argument" in r.matched_evidence.lower()


def test_precondition_error():
    text = "branch_a0 init aborted: PRECONDITION_NOT_MET, clock domain not released"
    r = classify_dispatch_failure(text)
    assert r.category == "PRECONDITION_ERROR"
    assert r.matched_evidence == "PRECONDITION_NOT_MET"


def test_branch_ownership_error():
    text = (
        "APB write collision: branch_a0 and branch_b0 hold conflicting locks on "
        "the shared bus sequencer; arbitration interleaved the two writes"
    )
    r = classify_dispatch_failure(text)
    assert r.category == "BRANCH_OWNERSHIP_ERROR"
    assert "branch_a0" in r.matched_evidence
    assert "branch_b0" in r.matched_evidence


def test_fw_timeout():
    text = "branch_fw service loop timeout: no interrupt observed within the wait window"
    r = classify_dispatch_failure(text)
    assert r.category == "FW_TIMEOUT"
    assert "branch_fw" in r.matched_evidence
    assert "timeout" in r.matched_evidence


def test_vip_timeout():
    text = "branch_b1 dispatch: svt_usb_agent sequence timed out waiting for a response"
    r = classify_dispatch_failure(text)
    assert r.category == "VIP_TIMEOUT"
    assert "branch_b1" in r.matched_evidence


def test_dut_timeout_via_branch_a():
    text = "branch_a2 dispatch: DUT link training deadlock, no progress observed"
    r = classify_dispatch_failure(text)
    assert r.category == "DUT_TIMEOUT"
    assert "branch_a2" in r.matched_evidence


def test_dut_timeout_via_generic_dut_marker_with_no_branch_label():
    # No branch_a/branch_fw/branch_b token at all -- still attributable via
    # the generic DUT/PHY marker, per the module's documented fallback.
    text = "PHY calibration hang: DUT never asserted cal_done"
    r = classify_dispatch_failure(text)
    assert r.category == "DUT_TIMEOUT"


def test_check_failure_via_scoreboard_mismatch():
    text = "UVM_ERROR: scoreboard mismatch, expected 0xDEAD got 0xBEEF at offset 0x20"
    r = classify_dispatch_failure(text)
    assert r.category == "CHECK_FAILURE"
    assert r.rule_id == "sim_log_analysis:scoreboard_mismatch"
    assert r.matched_line == 1


def test_check_failure_via_assertion():
    text = "UVM_ERROR: assertion failed in apb_no_x_on_addr_a: address bus carries X"
    r = classify_dispatch_failure(text)
    assert r.category == "CHECK_FAILURE"
    assert r.rule_id == "sim_log_analysis:assertion"


def test_environment_error():
    text = "task dispatch aborted: license checkout failed for feature VCS_MX"
    r = classify_dispatch_failure(text)
    assert r.category == "ENVIRONMENT_ERROR"
    assert "license" in r.matched_evidence.lower()


def test_task_error_generic_phrase():
    text = "task branch_b0_seq_body failed: unhandled exception in sequence body"
    r = classify_dispatch_failure(text)
    assert r.category == "TASK_ERROR"
    assert r.rule_id == "task_error_phrase"


def test_task_error_via_sim_log_analysis_bare_uvm_fatal():
    # No scoreboard/assertion/timeout/license/argument/command/precondition/
    # ownership marker present -- just a bare UVM_FATAL the sim-log triage
    # engine classifies as uvm_fatal, which this module routes to TASK_ERROR
    # since section 92-style specificity is absent.
    text = "UVM_FATAL: unrecoverable internal dispatcher state"
    r = classify_dispatch_failure(text)
    assert r.category == "TASK_ERROR"
    assert r.rule_id == "sim_log_analysis:uvm_fatal"


# ---------------------------------------------------------------------------
# Negative controls: the honest UNCLASSIFIED path
# ---------------------------------------------------------------------------

def test_unclassified_on_empty_text():
    r = classify_dispatch_failure("")
    assert r.category == UNCLASSIFIED
    assert r.matched_evidence == ""


def test_unclassified_on_whitespace_only_text():
    r = classify_dispatch_failure("   \n\t  ")
    assert r.category == UNCLASSIFIED


def test_unclassified_on_bare_timeout_with_no_layer_marker():
    # A bare "timeout" with no branch_a/branch_fw/branch_b/VIP/DUT/PHY marker
    # cannot be attributed to FW vs. VIP vs. DUT -- this must NOT be forced
    # into DUT_TIMEOUT (the broadest of the three) as a default guess.
    text = "operation timed out after 30s"
    r = classify_dispatch_failure(text)
    assert r.category == UNCLASSIFIED


def test_unclassified_on_unrelated_benign_text():
    text = "regression nightly summary: 412 tests scheduled for tonight's run"
    r = classify_dispatch_failure(text)
    assert r.category == UNCLASSIFIED


def test_unclassified_on_lone_ownership_keyword_with_only_one_branch_layer():
    # An ownership/lock keyword is present, but only ONE task-layer family is
    # named -- not evidence of a CROSS-layer conflict, so this must not be
    # forced into BRANCH_OWNERSHIP_ERROR.
    text = "branch_a0 acquired the register-access lock for its own init sequence"
    r = classify_dispatch_failure(text)
    assert r.category != "BRANCH_OWNERSHIP_ERROR"


def test_none_text_raises_rather_than_silently_defaulting():
    with pytest.raises(ValueError):
        classify_dispatch_failure(None)


# ---------------------------------------------------------------------------
# Priority ordering: a message carrying two signals lands on the documented
# higher-priority category, not an arbitrary one.
# ---------------------------------------------------------------------------

def test_ownership_error_wins_over_bare_timeout_language():
    text = (
        "branch_fw and branch_b0 both hold conflicting locks on the shared "
        "sequencer; branch_b0's sequence timed out waiting for the bus"
    )
    r = classify_dispatch_failure(text)
    assert r.category == "BRANCH_OWNERSHIP_ERROR"


def test_unknown_command_wins_over_syntax_error_phrasing():
    text = "command 'legacy_reset_seq' not found in dispatch table (syntax error in caller)"
    r = classify_dispatch_failure(text)
    assert r.category == "UNKNOWN_COMMAND"


def test_fw_timeout_wins_over_dut_generic_marker():
    text = "branch_fw timeout waiting on DUT interrupt (PHY link otherwise healthy)"
    r = classify_dispatch_failure(text)
    assert r.category == "FW_TIMEOUT"


def test_precondition_error_wins_over_generic_task_error_phrase():
    text = "task branch_a1_init failed: PRECONDITION_NOT_MET, reset not released"
    r = classify_dispatch_failure(text)
    assert r.category == "PRECONDITION_ERROR"


# ---------------------------------------------------------------------------
# matched_line: real line-location within a multi-line excerpt
# ---------------------------------------------------------------------------

def test_matched_line_points_at_the_real_line_in_a_multi_line_excerpt():
    text = "\n".join([
        "run started at 0 ns",
        "branch_a0: init complete",
        "branch_b0: UVM_ERROR: scoreboard mismatch on transaction 42",
        "run continuing",
    ])
    r = classify_dispatch_failure(text)
    assert r.category == "CHECK_FAILURE"
    assert r.matched_line == 3
