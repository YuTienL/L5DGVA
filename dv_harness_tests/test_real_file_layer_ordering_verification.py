"""Tests for dv_harness/real_file_layer_ordering_verification.py.

Confirms that block/branch_a*/branch_fw are checked against a real, cited
genesis LINE in a real command.txt-shaped file's own text -- never against a
caller's declared intent -- reusing `pattern_ir_assembly.py`'s ordering
vocabulary and `amba_discovery_report.py`'s canonical branch-label naming
throughout. Includes the required negative controls: an out-of-order real
file, a real file missing one of the three layers entirely, and a file that
only MENTIONS the canonical labels inside a comment (which must never be
read as real evidence) all report an honest, non-CONFIRMED status.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.amba_discovery_report import L5_BRANCH_BLOCK, L5_BRANCH_FW, l5_branch_a
from dv_harness.pattern_ir_assembly import DEFAULT_LAYER_ORDER, LAYER_DUT, LAYER_FW_POLICY, LAYER_GLOBAL
from dv_harness.real_file_layer_ordering_verification import (
    REQUIRED_LAYER_SUBSEQUENCE,
    STATUS_CONFIRMED,
    STATUS_LAYER_NOT_FOUND,
    STATUS_VIOLATION,
    execute_verb,
    extract_layer_genesis_lines,
    render_text,
    verify_actual_layer_order,
    verify_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# The exact real command.txt-shaped fixture text this project's own test
# suite already establishes as "real" for this canonical shape (see
# dv_harness_tests/test_branch_ownership_resolver.py's own
# CANONICAL_PATTERN_TXT) -- reused verbatim rather than re-authored, so this
# module is checked against the identical convention every sibling module in
# this codebase already treats as evidence.
# ---------------------------------------------------------------------------

CANONICAL_PATTERN_TXT = """\
// usb20_enumeration.txt -- canonical block/branch_a*/branch_fw/branch_b* shape
`SOC_GLOBAL_INIT(block)
`USB_FORK_PORT_BRINGUP(branch_a0, branch_a1)
`USB_FORK_FW_SERVICE(branch_fw)
fork
  branch_b0: `USB_HOST_ENUM_SEQ(port=0)
  branch_b1: `USB_HOST_ENUM_SEQ(port=1)
join
`FINAL_CHECK("usb20_enumeration")
"""

# branch_fw launched a second time later -- legal (idempotent, guarded per
# pattern-architecture SKILL.md section 1); only the FIRST genesis line
# should count toward ordering.
CANONICAL_WITH_REPEATED_FW = CANONICAL_PATTERN_TXT + "\n`USB_FORK_FW_SERVICE(branch_fw) // idempotent no-op re-launch\n"

# block AFTER branch_a0's launch -- a real ordering violation.
OUT_OF_ORDER_TXT = """\
`USB_FORK_PORT_BRINGUP(branch_a0)
`SOC_GLOBAL_INIT(block)
`USB_FORK_FW_SERVICE(branch_fw)
"""

# branch_fw genuinely absent from the file (only block + branch_a* exist).
MISSING_FW_TXT = """\
`SOC_GLOBAL_INIT(block)
`USB_FORK_PORT_BRINGUP(branch_a0, branch_a1)
"""

# Every canonical token mentioned, but ONLY inside a comment -- must never
# be read as real evidence of an actual launch site.
COMMENT_ONLY_TXT = """\
// This file will eventually declare block, branch_a0 and branch_fw here.
// See branch_a0 handling and branch_fw service loop notes below.
$display("placeholder, nothing real declared yet");
"""

# A begin:-named-block SV form (a second real structural evidence shape).
NAMED_BLOCK_TXT = """\
initial begin : block
  `GMODEL.GLOBAL_INIT;
end
task branch_a0();
  // per-port DUT+PHY bring-up
endtask
initial begin : branch_fw
  forever @(posedge irq) begin end
end
"""

# block and branch_a0 tied on genuinely different lines, but branch_fw
# genesis line equals branch_a0's own (impossible in practice but exercises
# the strict "<" comparison rather than "<=").
TIED_LINES_TXT = """\
`SOC_GLOBAL_INIT(block)
`USB_FORK_PORT_BRINGUP(branch_a0) `USB_FORK_FW_SERVICE(branch_fw)
"""


# ---------------------------------------------------------------------------
# Vocabulary reuse -- pattern_ir_assembly.py and amba_discovery_report.py,
# never a second spelling.
# ---------------------------------------------------------------------------

def test_required_subsequence_is_the_real_default_layer_order_prefix():
    assert REQUIRED_LAYER_SUBSEQUENCE == (LAYER_GLOBAL, LAYER_DUT, LAYER_FW_POLICY)
    assert tuple(DEFAULT_LAYER_ORDER[:3]) == REQUIRED_LAYER_SUBSEQUENCE


def test_canonical_labels_are_the_real_amba_discovery_report_ones():
    assert L5_BRANCH_BLOCK == "block"
    assert L5_BRANCH_FW == "branch_fw"
    assert l5_branch_a(0) == "branch_a0"
    assert l5_branch_a(7) == "branch_a7"


# ---------------------------------------------------------------------------
# extract_layer_genesis_lines -- structural-evidence extraction, real line
# numbers, comment/string blindness.
# ---------------------------------------------------------------------------

def test_extraction_finds_all_three_real_genesis_lines_in_canonical_fixture():
    genesis = extract_layer_genesis_lines(CANONICAL_PATTERN_TXT)
    assert genesis[LAYER_GLOBAL] == {"line": 2, "token": "block"}
    assert genesis[LAYER_DUT] == {"line": 3, "token": "branch_a0"}
    assert genesis[LAYER_FW_POLICY] == {"line": 4, "token": "branch_fw"}


def test_extraction_never_reads_a_comment_as_real_evidence():
    genesis = extract_layer_genesis_lines(COMMENT_ONLY_TXT)
    assert genesis == {}


def test_extraction_never_reads_a_string_literal_as_real_evidence():
    text = 'x = "block branch_a0 branch_fw all inside one string literal";\n'
    genesis = extract_layer_genesis_lines(text)
    assert genesis == {}


def test_extraction_recognises_named_block_and_task_declaration_forms():
    genesis = extract_layer_genesis_lines(NAMED_BLOCK_TXT)
    assert genesis[LAYER_GLOBAL] == {"line": 1, "token": "block"}
    assert genesis[LAYER_DUT] == {"line": 4, "token": "branch_a0"}
    assert genesis[LAYER_FW_POLICY] == {"line": 7, "token": "branch_fw"}


def test_extraction_only_keeps_the_first_real_occurrence_per_layer():
    genesis = extract_layer_genesis_lines(CANONICAL_WITH_REPEATED_FW)
    # the real re-launch line is well after line 4; genesis must stay at 4.
    assert genesis[LAYER_FW_POLICY]["line"] == 4


def test_extraction_never_matches_a_bare_english_word_block_out_of_position():
    # "block" appears mid-sentence, not as a macro-arg/label/task-name -- no
    # structural evidence, so it must not be extracted.
    text = "$display(\"this is a huge block of prose text\");\n"
    genesis = extract_layer_genesis_lines(text)
    assert LAYER_GLOBAL not in genesis


def test_extraction_ignores_branch_b_and_unrelated_macro_args():
    text = "`USB_HOST_ENUM_SEQ(branch_b0, port=0)\n"
    genesis = extract_layer_genesis_lines(text)
    assert genesis == {}


# ---------------------------------------------------------------------------
# verify_actual_layer_order -- the three-way status vocabulary.
# ---------------------------------------------------------------------------

def test_canonical_real_shaped_file_confirms_in_order():
    result = verify_actual_layer_order(CANONICAL_PATTERN_TXT, path="usb20_enumeration.txt")
    assert result.status == STATUS_CONFIRMED
    assert result.missing_layers == []
    assert result.violations == []
    assert result.path == "usb20_enumeration.txt"


def test_negative_control_out_of_order_real_file_is_a_violation_naming_both_lines():
    result = verify_actual_layer_order(OUT_OF_ORDER_TXT)
    assert result.status == STATUS_VIOLATION
    assert len(result.violations) == 1
    v = result.violations[0]
    assert v["earlier_layer"] == LAYER_GLOBAL
    assert v["later_layer"] == LAYER_DUT
    # block is on line 2, branch_a0's real launch is on line 1 -- cited.
    assert v["earlier_line"] == 2
    assert v["later_line"] == 1


def test_negative_control_missing_layer_is_layer_not_found_never_confirmed():
    result = verify_actual_layer_order(MISSING_FW_TXT)
    assert result.status == STATUS_LAYER_NOT_FOUND
    assert result.missing_layers == [LAYER_FW_POLICY]
    assert result.violations == []


def test_negative_control_comment_only_mentions_report_all_three_missing():
    result = verify_actual_layer_order(COMMENT_ONLY_TXT)
    assert result.status == STATUS_LAYER_NOT_FOUND
    assert set(result.missing_layers) == {LAYER_GLOBAL, LAYER_DUT, LAYER_FW_POLICY}


def test_named_block_forms_also_confirm_in_order():
    result = verify_actual_layer_order(NAMED_BLOCK_TXT)
    assert result.status == STATUS_CONFIRMED


def test_tied_genesis_lines_are_a_violation_not_a_silent_pass():
    result = verify_actual_layer_order(TIED_LINES_TXT)
    assert result.status == STATUS_VIOLATION
    later_violation = [v for v in result.violations if v["later_layer"] == LAYER_FW_POLICY]
    assert later_violation, result.violations


def test_empty_file_reports_all_three_missing():
    result = verify_actual_layer_order("")
    assert result.status == STATUS_LAYER_NOT_FOUND
    assert set(result.missing_layers) == {LAYER_GLOBAL, LAYER_DUT, LAYER_FW_POLICY}


def test_to_dict_round_trips_and_names_required_subsequence():
    result = verify_actual_layer_order(CANONICAL_PATTERN_TXT, path="p.txt")
    d = result.to_dict()
    assert d["status"] == STATUS_CONFIRMED
    assert d["required_layer_subsequence"] == list(REQUIRED_LAYER_SUBSEQUENCE)
    json.dumps(d)  # must be JSON-serialisable


# ---------------------------------------------------------------------------
# verify_file -- real file on disk.
# ---------------------------------------------------------------------------

def test_verify_file_reads_a_real_file_from_disk(tmp_path):
    p = tmp_path / "usb20_enumeration.txt"
    p.write_text(CANONICAL_PATTERN_TXT, encoding="utf-8")
    result = verify_file(p)
    assert result.status == STATUS_CONFIRMED
    assert result.path == str(p)


def test_verify_file_on_a_real_out_of_order_file_on_disk(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text(OUT_OF_ORDER_TXT, encoding="utf-8")
    result = verify_file(p)
    assert result.status == STATUS_VIOLATION


def test_render_text_names_every_layer_line_or_not_found():
    result = verify_actual_layer_order(MISSING_FW_TXT)
    text = render_text(result)
    assert "block:" in text
    assert "branch_fw: NOT_FOUND" in text


# ---------------------------------------------------------------------------
# execute_verb / CLI, both in-process and as a real subprocess.
# ---------------------------------------------------------------------------

def test_execute_verb_confirmed_returns_zero(tmp_path, capsys):
    p = tmp_path / "canonical.txt"
    p.write_text(CANONICAL_PATTERN_TXT, encoding="utf-8")
    rc = execute_verb([str(p), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == STATUS_CONFIRMED


def test_execute_verb_violation_returns_one(tmp_path, capsys):
    p = tmp_path / "bad.txt"
    p.write_text(OUT_OF_ORDER_TXT, encoding="utf-8")
    rc = execute_verb([str(p), "--json"])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == STATUS_VIOLATION


def test_execute_verb_layer_not_found_returns_two(tmp_path, capsys):
    p = tmp_path / "missing.txt"
    p.write_text(MISSING_FW_TXT, encoding="utf-8")
    rc = execute_verb([str(p), "--json"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == STATUS_LAYER_NOT_FOUND


def test_execute_verb_missing_file_returns_two_not_available(tmp_path, capsys):
    rc = execute_verb([str(tmp_path / "nope.txt"), "--json"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "NOT_AVAILABLE"


def test_execute_verb_default_text_output_not_json(tmp_path, capsys):
    p = tmp_path / "canonical.txt"
    p.write_text(CANONICAL_PATTERN_TXT, encoding="utf-8")
    rc = execute_verb([str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status: FILE_ORDER_CONFIRMED" in out


def test_real_cli_subprocess_confirmed(tmp_path):
    p = tmp_path / "canonical.txt"
    p.write_text(CANONICAL_PATTERN_TXT, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.real_file_layer_ordering_verification", str(p), "--json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["status"] == STATUS_CONFIRMED


def test_real_cli_subprocess_violation(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text(OUT_OF_ORDER_TXT, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.real_file_layer_ordering_verification", str(p), "--json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, proc.stderr
    out = json.loads(proc.stdout)
    assert out["status"] == STATUS_VIOLATION


# ---------------------------------------------------------------------------
# Real repo fixture: this project's own hand-authored VIP-conversion file
# (examples/generated_usb_real_evidence_v1/tb/patterns/common/USB2_con_vip.txt)
# never uses the canonical block/branch_a*/branch_fw labels at all (it is a
# pre-canonical, legacy-style single `initial begin` block) -- so this
# module must honestly report LAYER_NOT_FOUND against it, never fabricate a
# confirmed order it cannot actually evidence.
# ---------------------------------------------------------------------------

def test_real_repo_legacy_pattern_file_honestly_reports_layer_not_found():
    real_file = (
        REPO_ROOT
        / "examples"
        / "generated_usb_real_evidence_v1"
        / "tb"
        / "patterns"
        / "common"
        / "USB2_con_vip.txt"
    )
    if not real_file.is_file():
        pytest.skip("real example fixture not present in this checkout")
    result = verify_file(real_file)
    assert result.status == STATUS_LAYER_NOT_FOUND
    assert set(result.missing_layers) == {LAYER_GLOBAL, LAYER_DUT, LAYER_FW_POLICY}
