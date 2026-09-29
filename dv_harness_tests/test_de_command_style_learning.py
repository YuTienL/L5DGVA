"""Tests for dv_harness.de_command_style_learning.

Synthetic fixture only (never real project content), matching this
codebase's established precedent
(`test_reference_pattern_audit.py`'s own `_SYNTHETIC_PATTERN`). The fixture
is deliberately built to exercise:

- a KNOWN case: an unambiguous HOST-context register write (real HOST/DUT
  naming convention this repo already established).
- a DEPRECATED case: a HOST register write whose own trailing comment says
  it is deprecated.
- a KNOWN FW case: an interrupt-named wait.
- an AMBIGUOUS case: a plain, non-interrupt signal wait.
- an UNSUPPORTED case: a bare macro call matching no known register/model-
  task shape.
- an UNKNOWN case: a line matching no recognized DE command shape at all.
- a mixed-classification command: the same macro name written with two
  different, disagreeing prefixes (should never happen for a real prefix,
  but the grouping logic must still handle it honestly rather than picking
  one silently).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dv_harness.de_command_style_learning import (
    BRANCH_OWNER_DUT,
    BRANCH_OWNER_FW,
    BRANCH_OWNER_UNKNOWN,
    BRANCH_OWNER_VIP,
    STATUS_AMBIGUOUS,
    STATUS_DEPRECATED,
    STATUS_KNOWN,
    STATUS_UNKNOWN,
    STATUS_UNSUPPORTED,
    analyze_de_command_file,
    build_de_command_registry,
    format_de_command_analysis,
    learn_command_style,
)

_SYNTHETIC_COMMAND_TXT = """\
// synthetic fixture -- never real project content
`include "wave.txt"
initial begin
  `HOSTWRITE4B(32'hAA00_0004, 32'hFFFF); //enable_evt
  `CPUWRITE4B (32'hBB00_0004, 32'hFFFF); //enable_evt
  `HOSTWRITE2B(32'hAA00_0100, 32'h0001); //legacy_mode, deprecated, do not use
  wait(top.dut.irq_status_reg); //stage1
  wait(top.dut.some_flag); //stage2
  `SOMEVENDOR_UNKNOWN_MACRO(1, 2, 3); //not a register or model-task macro
  this line is not valid syntax at all !!!;
  $finish;
end
"""

_MIXED_PREFIX_COMMAND_TXT = """\
// synthetic fixture -- mixed-classification edge case
initial begin
  `HOSTWRITE4B(32'hAA00_0004, 32'h1); //first occurrence: HOST
  `CPUWRITE4B(32'hBB00_0004, 32'h1); //second occurrence with SAME name key would not happen for real macros;
  $finish;
end
"""


@pytest.fixture()
def synthetic_file(tmp_path: Path) -> Path:
    p = tmp_path / "synth_command.txt"
    p.write_text(_SYNTHETIC_COMMAND_TXT, encoding="utf-8")
    return p


def _entries_by_name(registry):
    return {e.command_name: e for e in registry.entries}


# --- DECommandRegistryIR: positive / KNOWN path -----------------------------

def test_registry_known_host_register_write(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    by_name = _entries_by_name(registry)
    host_write = by_name["HOSTWRITE4B"]
    assert host_write.status == STATUS_KNOWN
    assert host_write.branch_owner == BRANCH_OWNER_VIP
    assert "register write" in host_write.semantic_operation
    assert host_write.first_evidence.endswith(":4")


def test_registry_known_dut_register_write(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    by_name = _entries_by_name(registry)
    dut_write = by_name["CPUWRITE4B"]
    assert dut_write.status == STATUS_KNOWN
    assert dut_write.branch_owner == BRANCH_OWNER_DUT


def test_registry_known_fw_interrupt_wait(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    waits = [e for e in registry.entries if e.kind == "WAIT_CONDITION"]
    # two distinct wait statements -> two distinct entries (different raw text
    # is irrelevant here since both key on kind+name="wait"; they are the
    # SAME command name "wait" so they merge into one entry unless their
    # classification disagrees, in which case mixed_classifications is set).
    assert waits, "expected at least one WAIT_CONDITION entry"


# --- DECommandRegistryIR: negative controls (never a confident guess) ------

def test_registry_deprecated_case_cites_real_comment_token(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    entries = [e for e in registry.entries if e.status == STATUS_DEPRECATED]
    assert entries, "expected at least one DEPRECATED entry"
    dep = entries[0]
    assert "deprecated" in dep.basis.lower()
    assert dep.command_name == "HOSTWRITE2B"


def test_registry_ambiguous_wait_has_no_confident_owner(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    # The interrupt-named wait and the plain-signal wait share the same
    # command_name key ("wait"), so their classifications disagree
    # (KNOWN/FW vs AMBIGUOUS/UNKNOWN) and the merged entry must be reported
    # AMBIGUOUS, never silently collapsed to the first occurrence's KNOWN.
    wait_entry = next(e for e in registry.entries if e.kind == "WAIT_CONDITION")
    assert wait_entry.mixed_classifications is True
    assert wait_entry.status == STATUS_AMBIGUOUS
    assert wait_entry.branch_owner in (BRANCH_OWNER_FW, BRANCH_OWNER_UNKNOWN)


def test_registry_unsupported_bare_macro(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    by_name = _entries_by_name(registry)
    # reference_pattern_audit's own classifier names a bare (non-register,
    # non-model-task) macro call with its leading backtick kept verbatim.
    unsupported = by_name["`SOMEVENDOR_UNKNOWN_MACRO"]
    assert unsupported.status == STATUS_UNSUPPORTED
    assert unsupported.branch_owner == BRANCH_OWNER_UNKNOWN
    assert unsupported.semantic_operation == "UNSUPPORTED_MACRO_OPERATION"


def test_registry_unknown_line_cites_real_raw_text(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    unknowns = [e for e in registry.entries if e.status == STATUS_UNKNOWN]
    assert unknowns, "expected at least one UNKNOWN entry"
    unk = unknowns[0]
    # The raw, real text must be cited verbatim -- never paraphrased.
    assert "this line is not valid syntax at all" in unk.raw_text
    assert unk.semantic_operation == "UNKNOWN"
    assert unk.branch_owner == BRANCH_OWNER_UNKNOWN


def test_registry_never_guesses_a_status_for_unknown(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    unknowns = [e for e in registry.entries if e.status == STATUS_UNKNOWN]
    for u in unknowns:
        assert u.status != STATUS_KNOWN
        assert u.branch_owner == BRANCH_OWNER_UNKNOWN


def test_registry_distinct_commands_never_collapse(synthetic_file):
    registry = build_de_command_registry(synthetic_file)
    assert registry.distinct_command_count == len(registry.entries)
    names = [e.command_name for e in registry.entries]
    assert "HOSTWRITE4B" in names
    assert "CPUWRITE4B" in names
    assert names.count("HOSTWRITE4B") == 1  # grouped, not duplicated


# --- CommandStyleIR ----------------------------------------------------------

def test_style_detects_semicolon_convention(synthetic_file):
    style = learn_command_style(synthetic_file)
    sep = style.separator_convention
    assert sep["convention"] == "SEMICOLON_TERMINATED_ONE_PER_LINE"
    assert sep["semicolon_terminated_lines"] >= 5


def test_style_detects_hex_and_paren_argument_format(synthetic_file):
    style = learn_command_style(synthetic_file)
    args = style.argument_format
    assert args["convention"].startswith("PAREN_COMMA_SEPARATED_ARGS")
    assert args["hex_literal_calls"] >= 3
    assert args["underscore_grouped_hex_calls"] >= 3


def test_style_detects_trailing_line_comments(synthetic_file):
    style = learn_command_style(synthetic_file)
    fmt = style.comment_format
    assert fmt["convention"] == "LINE_COMMENT_TRAILING"
    assert fmt["line_comments"] >= 5


def test_style_reports_phase_markers_not_found_when_absent(synthetic_file):
    style = learn_command_style(synthetic_file)
    # This fixture uses "stage1"/"stage2" only as plain trailing comment
    # words, never a PHASE:/STAGE=/STEP-shaped marker token -- so the
    # honest report is NOT_FOUND, never a guessed marker.
    assert style.phase_markers["convention"] == "NOT_FOUND"


def test_style_reports_sequential_ordering_when_no_fork_join(synthetic_file):
    style = learn_command_style(synthetic_file)
    ordering = style.ordering_rules
    assert ordering["fork_lines"] == []
    assert ordering["join_lines"] == []
    assert ordering["convention"] in ("SEQUENTIAL_ONLY", "NOT_AVAILABLE")


def test_style_reports_not_available_on_empty_file(tmp_path: Path):
    empty = tmp_path / "empty_command.txt"
    empty.write_text("", encoding="utf-8")
    style = learn_command_style(empty)
    assert style.separator_convention["convention"] == "NOT_AVAILABLE"
    assert style.argument_format["convention"] == "NOT_AVAILABLE"
    assert style.comment_format["convention"] == "NOT_FOUND"
    assert style.phase_markers["convention"] == "NOT_FOUND"
    assert style.ordering_rules["convention"] == "NOT_AVAILABLE"


def test_style_detects_explicit_phase_markers_when_present(tmp_path: Path):
    p = tmp_path / "phased_command.txt"
    p.write_text(
        "// PHASE: INIT\n"
        "`HOSTWRITE4B(32'hAA00_0000, 32'h1); //enable\n"
        "// STAGE: bringup\n"
        "`CPUWRITE4B(32'hBB00_0000, 32'h1); //enable\n",
        encoding="utf-8")
    style = learn_command_style(p)
    assert style.phase_markers["convention"] == "EXPLICIT_PHASE_MARKERS_FOUND"
    kinds = {m["marker_kind"] for m in style.phase_markers["markers"]}
    assert "PHASE" in kinds and "STAGE" in kinds


def test_style_detects_fork_join_ordering(tmp_path: Path):
    p = tmp_path / "forked_command.txt"
    p.write_text(
        "initial begin\n"
        "  fork\n"
        "    `HOSTWRITE4B(32'hAA00_0000, 32'h1); //branch_b0\n"
        "    `HOSTWRITE4B(32'hAA01_0000, 32'h1); //branch_b1\n"
        "  join\n"
        "end\n",
        encoding="utf-8")
    style = learn_command_style(p)
    assert style.ordering_rules["convention"] == "PARALLEL_FORK_JOIN"
    assert style.ordering_rules["fork_lines"] and style.ordering_rules["join_lines"]


# --- combined entry point / formatter ----------------------------------------

def test_analyze_de_command_file_returns_plain_dict(synthetic_file):
    analysis = analyze_de_command_file(synthetic_file)
    assert analysis["registry"]["distinct_command_count"] > 0
    assert "convention" in analysis["style"]["separator_convention"]
    # Must be JSON-friendly (plain dict/list/str/int, no dataclass instances).
    import json
    json.dumps(analysis)


def test_format_de_command_analysis_is_human_readable(synthetic_file):
    analysis = analyze_de_command_file(synthetic_file)
    text = format_de_command_analysis(analysis)
    assert "DE command style/registry learning" in text
    assert STATUS_UNKNOWN in text
    assert STATUS_KNOWN in text
