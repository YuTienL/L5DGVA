"""Tests for dv_harness/runtime_control_commands.py -- CONTROL-command closed
vocabulary enforcement (WAIT/POLL/REPEAT/BOUNDED_LOOP/SYNC/BARRIER) plus the
"no declared iteration limit" unbounded-loop check.

Every test drives the REAL `reference_pattern_audit.extract_command_statements()`
parser over a REAL synthetic command.txt-shaped file written to `tmp_path` --
the same convention `test_reference_pattern_audit.py` already uses for its own
synthetic fixtures. Nothing here re-parses command.txt text of its own; this
file proves the CLASSIFICATION and VOCABULARY rules this module adds on top of
that real parser.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import runtime_control_commands as rcc
from dv_harness.runtime_control_commands import (
    BASIS_EXACT_VOCABULARY_MATCH,
    BASIS_NAME_TOKEN_MATCH,
    BASIS_NATIVE_SV_CONSTRUCT,
    CONTROL_VOCABULARY,
    FINDING_ILLEGAL_CONTROL_COMMAND,
    FINDING_ILLEGAL_UNBOUNDED_LOOP,
    STATUS_CLEAN,
    STATUS_NOT_AVAILABLE,
    STATUS_VIOLATIONS_FOUND,
    analyze_control_commands,
    classify_control_commands,
    render_control_commands_markdown,
)
from dv_harness.reference_pattern_audit import extract_command_statements

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _records_for(tmp_path, text):
    path = _write(tmp_path, "synth_pattern.txt", text)
    statements = extract_command_statements(path)
    return classify_control_commands(statements)


def _by_name(records, name):
    return [r for r in records if r.command_name == name.upper()]


# --------------------------------------------------------------------------
# Core positive path: every legal vocabulary word, correctly used
# --------------------------------------------------------------------------

_CLEAN_PATTERN = """
// synthetic command.txt-shaped fixture -- not a real DE pattern.
`CPUWRITE4B(32'h1272_0020, 32'h1); //not a control command at all
`WAIT(link_up_flag);
`POLL(dsts_reg, 32'h1);
`REPEAT(5);
`BOUNDED_LOOP(3);
`SYNC;
`BARRIER;
"""


def test_clean_pattern_reports_no_findings(tmp_path):
    report = analyze_control_commands(_write(tmp_path, "clean.txt", _CLEAN_PATTERN))
    assert report["status"] == STATUS_CLEAN
    assert report["illegal_control_command_count"] == 0
    assert report["illegal_unbounded_loop_count"] == 0
    # six CONTROL-classified commands; the register write is NOT one of them.
    assert report["control_classified_count"] == 6
    names = {r["command_name"] for r in report["records"]}
    assert names == set(CONTROL_VOCABULARY)
    assert not any(r["findings"] for r in report["records"])


def test_register_write_is_never_classified_as_control(tmp_path):
    records = _records_for(tmp_path, _CLEAN_PATTERN)
    assert not _by_name(records, "CPUWRITE4B")


def test_exact_vocabulary_macro_carries_exact_match_basis(tmp_path):
    records = _records_for(tmp_path, _CLEAN_PATTERN)
    wait_rec = _by_name(records, "WAIT")[0]
    assert wait_rec.classification_basis == BASIS_EXACT_VOCABULARY_MATCH
    assert wait_rec.in_vocabulary is True
    assert wait_rec.findings == []


def test_bounded_loop_and_repeat_record_their_declared_argument(tmp_path):
    records = _records_for(tmp_path, _CLEAN_PATTERN)
    repeat_rec = _by_name(records, "REPEAT")[0]
    bounded_rec = _by_name(records, "BOUNDED_LOOP")[0]
    assert repeat_rec.loop_bound_declared is True
    assert repeat_rec.declared_bound_argument == "5"
    assert bounded_rec.loop_bound_declared is True
    assert bounded_rec.declared_bound_argument == "3"


def test_non_loop_vocabulary_words_carry_no_bound_verdict(tmp_path):
    records = _records_for(tmp_path, _CLEAN_PATTERN)
    for name in ("WAIT", "POLL", "SYNC", "BARRIER"):
        rec = _by_name(records, name)[0]
        assert rec.loop_bound_declared is None, name


# --------------------------------------------------------------------------
# Negative control 1: a control-intended macro OUTSIDE the closed vocabulary
# --------------------------------------------------------------------------

def test_out_of_vocabulary_control_macro_is_flagged_illegal(tmp_path):
    text = "`RETRY_UNTIL_DONE(5);\n"
    records = _records_for(tmp_path, text)
    assert len(records) == 1
    rec = records[0]
    assert rec.command_name == "RETRY_UNTIL_DONE"
    assert rec.classification_basis == BASIS_NAME_TOKEN_MATCH
    assert rec.in_vocabulary is False
    assert FINDING_ILLEGAL_CONTROL_COMMAND in rec.findings


def test_out_of_vocabulary_control_macro_fails_the_report(tmp_path):
    report = analyze_control_commands(_write(tmp_path, "bad_name.txt", "`SPIN_WAIT_FOREVER;\n"))
    assert report["status"] == STATUS_VIOLATIONS_FOUND
    assert report["illegal_control_command_count"] == 1
    assert report["records"][0]["command_name"] == "SPIN_WAIT_FOREVER"


# --------------------------------------------------------------------------
# Negative control 2: BOUNDED_LOOP with no declared iteration limit -- the
# task's own explicit example ("even if the command name is BOUNDED_LOOP")
# --------------------------------------------------------------------------

def test_bounded_loop_with_no_argument_is_unbounded_despite_the_legal_name(tmp_path):
    records = _records_for(tmp_path, "`BOUNDED_LOOP;\n")
    assert len(records) == 1
    rec = records[0]
    assert rec.command_name == "BOUNDED_LOOP"
    assert rec.in_vocabulary is True
    assert FINDING_ILLEGAL_CONTROL_COMMAND not in rec.findings
    assert rec.loop_bound_declared is False
    assert FINDING_ILLEGAL_UNBOUNDED_LOOP in rec.findings


def test_bounded_loop_with_empty_parens_is_also_unbounded(tmp_path):
    records = _records_for(tmp_path, "`BOUNDED_LOOP();\n")
    rec = records[0]
    assert rec.loop_bound_declared is False
    assert FINDING_ILLEGAL_UNBOUNDED_LOOP in rec.findings


def test_repeat_with_no_argument_is_unbounded_even_though_repeat_is_legal(tmp_path):
    records = _records_for(tmp_path, "`REPEAT;\n")
    rec = records[0]
    assert rec.command_name == "REPEAT"
    assert rec.in_vocabulary is True
    assert FINDING_ILLEGAL_CONTROL_COMMAND not in rec.findings
    assert FINDING_ILLEGAL_UNBOUNDED_LOOP in rec.findings


# --------------------------------------------------------------------------
# Negative control 3: native raw SystemVerilog control-flow used directly
# (the actual "unrestricted scripting" this rule exists to catch)
# --------------------------------------------------------------------------

def test_native_while_loop_is_control_classified_and_illegal(tmp_path):
    records = _records_for(tmp_path, "while(link_up_flag);\n")
    assert len(records) == 1
    rec = records[0]
    assert rec.classification_basis == BASIS_NATIVE_SV_CONSTRUCT
    assert rec.command_name == "WHILE"
    assert rec.in_vocabulary is False
    assert FINDING_ILLEGAL_CONTROL_COMMAND in rec.findings
    # "while" has no loop-count concept in this parser's own K_LOOP handling,
    # so it is never subjected to the bound check at all.
    assert rec.loop_bound_declared is None


def test_native_fork_and_join_are_control_classified_and_illegal(tmp_path):
    text = "fork\n  `WAIT(a);\njoin\n"
    records = _records_for(tmp_path, text)
    names = {r.command_name for r in records}
    assert "FORK" in names
    assert "JOIN" in names
    for rec in records:
        if rec.command_name in ("FORK", "JOIN"):
            assert FINDING_ILLEGAL_CONTROL_COMMAND in rec.findings


def test_native_repeat_with_declared_bound_is_legal_and_bounded(tmp_path):
    records = _records_for(tmp_path, "repeat(3);\n")
    rec = records[0]
    assert rec.classification_basis == BASIS_NATIVE_SV_CONSTRUCT
    assert rec.command_name == "REPEAT"
    assert rec.in_vocabulary is True
    assert rec.loop_bound_declared is True
    assert rec.declared_bound_argument == "3"
    assert rec.findings == []


def test_native_repeat_with_no_bound_is_unbounded(tmp_path):
    records = _records_for(tmp_path, "repeat();\n")
    rec = records[0]
    assert rec.command_name == "REPEAT"
    assert rec.in_vocabulary is True
    assert rec.loop_bound_declared is False
    assert FINDING_ILLEGAL_UNBOUNDED_LOOP in rec.findings


# --------------------------------------------------------------------------
# Negative control 4: a real, ordinary command.txt macro that is NOT control
# at all must never appear in the report
# --------------------------------------------------------------------------

def test_ordinary_register_and_model_macros_are_never_classified_control(tmp_path):
    text = (
        "`CPUWRITE4B(32'h1272_0020, 32'h1); //bring-up write\n"
        "`HOSTWRITE4B(32'h161A_0020, 32'h2600);\n"
        "`SMEMMODEL.FILLMEM(\"/dev/x.hex\", 4, 40'h2000_1000, 'd32);\n"
    )
    records = _records_for(tmp_path, text)
    assert records == []


# --------------------------------------------------------------------------
# NOT_AVAILABLE, never a fabricated CLEAN
# --------------------------------------------------------------------------

def test_missing_file_is_not_available_not_clean(tmp_path):
    report = analyze_control_commands(tmp_path / "does_not_exist.txt")
    assert report["status"] == STATUS_NOT_AVAILABLE
    assert "NO_SUCH_FILE" in report["reason"]
    assert report["records"] == []


def test_not_available_report_never_claims_a_count():
    report = analyze_control_commands(Path("Z:/definitely/not/a/real/path.txt"))
    assert report["status"] == STATUS_NOT_AVAILABLE
    assert report["control_classified_count"] == 0


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def test_markdown_render_reports_status_and_command_names(tmp_path):
    report = analyze_control_commands(_write(tmp_path, "clean.txt", _CLEAN_PATTERN))
    text = render_control_commands_markdown(report)
    assert "CLEAN" in text
    assert "WAIT" in text
    assert "BOUNDED_LOOP" in text


def test_markdown_render_of_not_available_names_the_reason(tmp_path):
    report = analyze_control_commands(tmp_path / "missing.txt")
    text = render_control_commands_markdown(report)
    assert "NOT_AVAILABLE" in text
    assert "NO_SUCH_FILE" in text


def test_markdown_render_empty_note_when_no_control_commands(tmp_path):
    report = analyze_control_commands(_write(tmp_path, "none.txt", "`CPUWRITE4B(32'h1000, 32'h1);\n"))
    text = render_control_commands_markdown(report)
    assert "no CONTROL-classified commands found" in text


# --------------------------------------------------------------------------
# The real CLI entry point, driven as a real subprocess
# --------------------------------------------------------------------------

def _run(args):
    return subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)


def test_module_cli_clean_pattern_exits_zero(tmp_path):
    path = _write(tmp_path, "clean.txt", _CLEAN_PATTERN)
    r = _run([sys.executable, "-m", "dv_harness.runtime_control_commands",
              "--command-file", str(path)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CLEAN" in r.stdout


def test_module_cli_illegal_command_exits_one_and_emits_json(tmp_path):
    path = _write(tmp_path, "bad.txt", "`RETRY_UNTIL_DONE(1);\n")
    r = _run([sys.executable, "-m", "dv_harness.runtime_control_commands",
              "--command-file", str(path), "--json"])
    assert r.returncode == 1, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == STATUS_VIOLATIONS_FOUND
    assert payload["records"][0]["command_name"] == "RETRY_UNTIL_DONE"


def test_module_cli_missing_file_exits_two(tmp_path):
    r = _run([sys.executable, "-m", "dv_harness.runtime_control_commands",
              "--command-file", str(tmp_path / "nope.txt")])
    assert r.returncode == 2, r.stdout + r.stderr
