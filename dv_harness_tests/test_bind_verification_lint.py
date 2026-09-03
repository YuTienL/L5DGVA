"""Tests for dv_harness/uvm_generator/bind_verification_lint.py -- the
standalone, build-tree-agnostic lint that flags a build-status report
artifact missing Gate 1/2/3 bind-verification status (2026-09-03, Gap #2
closure: mandatory-gate-checkpoint workstream).

Covers: the clean-report case (both markdown and JSON forms, including a
legitimate PENDING Gate 3), each of the three "missing" cases individually,
an unrecognized status-value typo, a malformed-input case that must be
reported as a problem rather than raising, and the file-reading/CLI
entry points against real temp files on disk (the actual "run this against
any build tree's own status/report artifacts" usage this tool is for).
"""
from __future__ import annotations

import json

from dv_harness import connectivity as conn
from dv_harness.uvm_generator import bind_verification_lint as lint


# ===========================================================================
# Markdown extraction / linting
# ===========================================================================

def _clean_markdown_report(gate3_status: str = "PASS") -> str:
    return (
        "# Build Status Report -- usb31_dev_uvm\n\n"
        "First successful compile/elaboration reached.\n\n"
        "## Bind Verification Status\n\n"
        "- Gate 1 (elaboration): NOT_AVAILABLE\n"
        "- Gate 2 (static zero-time connectivity): PASS\n"
        f"- Gate 3 (transaction activity): {gate3_status}\n"
    )


def test_clean_markdown_report_lints_clean():
    problems = lint.lint_status_report_text(_clean_markdown_report(), is_json=False)
    assert problems == []


def test_clean_markdown_report_with_pending_gate3_lints_clean():
    """The TCA-hang shape: Gate 3 legitimately PENDING (no pattern completed
    yet) must NOT be flagged as a problem -- PENDING is a valid, explicit
    status, not a missing one."""
    problems = lint.lint_status_report_text(_clean_markdown_report(gate3_status="PENDING"), is_json=False)
    assert problems == []


def test_markdown_report_missing_gate3_line_entirely_is_flagged():
    """The literal example the gap-closure requirement names: 'Gate 3 status
    missing from this report' must be caught."""
    text = (
        "## Bind Verification Status\n\n"
        "- Gate 1 (elaboration): NOT_AVAILABLE\n"
        "- Gate 2 (static zero-time connectivity): PASS\n"
        # Gate 3 line omitted entirely -- the real defect this tool exists to catch.
    )
    problems = lint.lint_status_report_text(text, is_json=False)
    assert len(problems) == 1
    assert "gate3 transaction activity status missing from this report" in problems[0]


def test_markdown_report_with_no_bind_verification_section_at_all_flags_all_three():
    text = "# Build Status Report\n\nCompile succeeded. Moving on to Step 10.\n"
    problems = lint.lint_status_report_text(text, is_json=False)
    assert len(problems) == 3
    joined = " ".join(problems)
    assert "gate1_elaboration".replace("_", " ") in joined
    assert "gate2_zero_time_connectivity".replace("_", " ") in joined
    assert "gate3_transaction_activity".replace("_", " ") in joined


def test_markdown_report_with_unrecognized_status_value_is_flagged():
    text = (
        "## Bind Verification Status\n\n"
        "- Gate 1 (elaboration): NOT_AVAILABLE\n"
        "- Gate 2 (static zero-time connectivity): PASS\n"
        "- Gate 3 (transaction activity): MAYBE\n"  # typo/invalid value, not a real GateStatus
    )
    problems = lint.lint_status_report_text(text, is_json=False)
    assert len(problems) == 1
    assert "MAYBE" in problems[0]
    assert "not a recognized GateStatus value" in problems[0]


# ===========================================================================
# JSON extraction / linting
# ===========================================================================

def test_clean_flat_json_report_lints_clean():
    payload = json.dumps({
        "gate1_elaboration": "PASS",
        "gate2_zero_time_connectivity": "PASS",
        "gate3_transaction_activity": "PENDING",
    })
    assert lint.lint_status_report_text(payload, is_json=True) == []


def test_clean_nested_json_report_lints_clean():
    payload = json.dumps({
        "build": "usb31_dev_uvm",
        "bind_verification_status": {
            "gate1_elaboration": "NOT_AVAILABLE",
            "gate2_zero_time_connectivity": "FAIL",
            "gate3_transaction_activity": "PENDING",
        },
    })
    assert lint.lint_status_report_text(payload, is_json=True) == []


def test_json_report_missing_gate3_key_is_flagged():
    payload = json.dumps({"gate1_elaboration": "PASS", "gate2_zero_time_connectivity": "PASS"})
    problems = lint.lint_status_report_text(payload, is_json=True)
    assert len(problems) == 1
    assert "gate3" in problems[0]


def test_malformed_json_is_reported_as_a_problem_not_raised():
    problems = lint.lint_status_report_text("{not valid json", is_json=True)
    assert len(problems) == 1
    assert "could not parse report as JSON" in problems[0]


def test_json_report_that_is_not_an_object_is_reported_as_a_problem():
    problems = lint.lint_status_report_text("[1, 2, 3]", is_json=True)
    assert len(problems) == 1
    assert "could not parse report as JSON" in problems[0]


# ===========================================================================
# Real-file / CLI entry points
# ===========================================================================

def test_lint_status_report_file_against_real_markdown_file(tmp_path):
    report_path = tmp_path / "build_status.md"
    report_path.write_text(_clean_markdown_report(), encoding="utf-8")
    assert lint.lint_status_report_file(report_path) == []


def test_lint_status_report_file_against_real_broken_file_flags_it(tmp_path):
    report_path = tmp_path / "build_status.md"
    report_path.write_text("# Build Status Report\n\nNo bind-verification section here.\n", encoding="utf-8")
    problems = lint.lint_status_report_file(report_path)
    assert len(problems) == 3


def test_main_returns_zero_for_clean_report_and_nonzero_for_broken_one(tmp_path, capsys):
    clean_path = tmp_path / "clean.md"
    clean_path.write_text(_clean_markdown_report(), encoding="utf-8")
    assert lint.main([str(clean_path)]) == 0
    out = capsys.readouterr().out
    assert "clean" in out

    broken_path = tmp_path / "broken.md"
    broken_path.write_text("# Report\n\nnothing here\n", encoding="utf-8")
    assert lint.main([str(broken_path)]) == 1
    out = capsys.readouterr().out
    assert "problem" in out


# ===========================================================================
# Round-trip against connectivity.py's own renderer -- proves the lint
# script and the canonical renderer genuinely agree on the same line shape,
# not two independently-guessed formats that happen to coincide today.
# ===========================================================================

def test_lint_accepts_connectivitys_own_rendered_markdown_verbatim():
    md = conn.render_bind_verification_status_markdown(None)  # all NOT_YET_RUN
    problems = lint.lint_status_report_text(md, is_json=False)
    assert problems == []


def test_lint_accepts_connectivitys_own_rendered_markdown_with_real_gate_report():
    report = conn.run_machine_gates(["dut.f"], "chip_top", signal_trace=None, pattern_completed=False)
    md = conn.render_bind_verification_status_markdown(report)
    assert lint.lint_status_report_text(md, is_json=False) == []
