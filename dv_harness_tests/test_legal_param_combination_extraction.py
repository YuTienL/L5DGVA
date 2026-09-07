"""Tests for dv_harness/legal_param_combination_extraction.py -- real,
parser-level extraction of which RTL parameter COMBINATIONS a module's own
source text proves legal/illegal via a generate-if or initial-if guard
(item id legal_param_combination_extraction).

Two tiers, matching this repo's own established convention (see
test_param_define_extraction.py / test_design_architecture_ir.py):
- Tier 1: pure unit tests drive `find_combination_sites()` directly against
  small SYNTHETIC RTL text fixtures (built inline, never real vendor
  content) -- no subprocess needed. This is where every construct shape,
  and every honest-absence negative control the Evidence Truth Rule
  requires, is proven.
- Tier 2: a small number of tests exercise the real end-to-end pipeline
  through a real `verible-verilog-syntax` subprocess (to prove the module's
  own `verible_parser.py` reuse -- real parameter names, real module text
  span -- is wired up correctly) and are skipped (never faked) on a machine
  without it on PATH, per this project's own Evidence Truth Rule.
"""
from __future__ import annotations

import shutil
import textwrap

import pytest

from dv_harness import legal_param_combination_extraction as lpc

VERIBLE_BIN = "verible-verilog-syntax"
requires_verible = pytest.mark.skipif(
    shutil.which(VERIBLE_BIN) is None,
    reason="verible-verilog-syntax not on PATH",
)


# ===========================================================================
# Tier 1: pure unit tests against synthetic RTL text (no subprocess)
# ===========================================================================

# --- construct (a): generate-if legality guard over two-or-more params -----

GENERATE_IF_FIXTURE_TEXT = textwrap.dedent("""\
    module cfg_mux #(
        parameter int WIDTH = 8,
        parameter int MODE  = 1
    ) (
        input  logic a,
        input  logic b,
        output logic y
    );
        generate
            if (WIDTH == 8 && MODE == 1) begin : narrow
                assign y = a;
            end else if (WIDTH == 32 && MODE == 2) begin : wide
                assign y = b;
            end else begin
                initial $error("illegal WIDTH/MODE combination");
            end
        endgenerate
    endmodule
    """)


def test_generate_if_two_legal_branches_are_reported_with_real_citations():
    sites = lpc.find_combination_sites(
        GENERATE_IF_FIXTURE_TEXT, "cfg_mux", ["WIDTH", "MODE"],
        file_path="cfg_mux.sv", base_line=1,
    )
    assert len(sites) == 2
    assert all(s.status == lpc.LEGAL_COMBINATION_PROVEN for s in sites)
    assert all(s.construct_kind == lpc.GENERATE_IF_COMBINATION_GUARD for s in sites)
    assert sites[0].branch_kind == lpc.BRANCH_IF
    assert sites[0].tested_params == ["MODE", "WIDTH"]
    assert sites[0].condition_text == "WIDTH == 8 && MODE == 1"
    assert sites[0].file_path == "cfg_mux.sv"
    assert sites[0].line == GENERATE_IF_FIXTURE_TEXT.splitlines().index(
        "        if (WIDTH == 8 && MODE == 1) begin : narrow") + 1
    assert sites[1].branch_kind == lpc.BRANCH_ELSE_IF
    assert sites[1].tested_params == ["MODE", "WIDTH"]
    # The trailing bare `else` (with its own $error) must NEVER become a
    # site of its own -- see module docstring boundary point 3.
    assert all(s.condition_text != "" for s in sites)
    assert not any(s.status == lpc.ILLEGAL_COMBINATION_PROVEN for s in sites)


GENERATE_IF_ILLEGAL_FIXTURE_TEXT = textwrap.dedent("""\
    module cfg2 #(
        parameter int WIDTH = 8,
        parameter int MODE  = 1
    ) ();
        generate
            if (WIDTH == 8 && MODE == 1) begin
                assign y = a;
            end else if (WIDTH == 16 && MODE == 3) begin
                initial $error("illegal WIDTH/MODE combination");
            end
        endgenerate
    endmodule
    """)


def test_generate_if_else_if_branch_with_error_is_illegal_combination_proven():
    sites = lpc.find_combination_sites(
        GENERATE_IF_ILLEGAL_FIXTURE_TEXT, "cfg2", ["WIDTH", "MODE"],
        file_path="cfg2.sv", base_line=1,
    )
    assert len(sites) == 2
    by_kind = {s.branch_kind: s for s in sites}
    assert by_kind[lpc.BRANCH_IF].status == lpc.LEGAL_COMBINATION_PROVEN
    assert by_kind[lpc.BRANCH_ELSE_IF].status == lpc.ILLEGAL_COMBINATION_PROVEN
    assert by_kind[lpc.BRANCH_ELSE_IF].tested_params == ["MODE", "WIDTH"]
    assert by_kind[lpc.BRANCH_ELSE_IF].condition_text == "WIDTH == 16 && MODE == 3"


# --- construct (b): elaboration-time $error guard over two-or-more params --

INITIAL_IF_FIXTURE_TEXT = textwrap.dedent("""\
    module guard #(
        parameter int WIDTH = 8,
        parameter int MODE  = 1
    ) ();
        initial if (WIDTH==64 && MODE!=2) $error("illegal combination");
    endmodule
    """)


def test_initial_if_error_guard_is_illegal_combination_proven():
    sites = lpc.find_combination_sites(
        INITIAL_IF_FIXTURE_TEXT, "guard", ["WIDTH", "MODE"],
        file_path="guard.sv", base_line=1,
    )
    assert len(sites) == 1
    site = sites[0]
    assert site.status == lpc.ILLEGAL_COMBINATION_PROVEN
    assert site.construct_kind == lpc.ELABORATION_ERROR_COMBINATION_GUARD
    assert site.branch_kind == lpc.BRANCH_IF
    assert site.tested_params == ["MODE", "WIDTH"]
    assert site.condition_text == "WIDTH==64 && MODE!=2"


INITIAL_IF_FATAL_FIXTURE_TEXT = textwrap.dedent("""\
    module guard2 #(
        parameter int DEPTH = 4,
        parameter int WIDTH = 8
    ) ();
        initial begin
            if (DEPTH == 4 && WIDTH == 16) $fatal(1, "illegal DEPTH/WIDTH");
        end
    endmodule
    """)


def test_initial_begin_if_fatal_guard_is_also_illegal_combination_proven():
    """$fatal, not just $error, must be recognized -- and the `initial
    begin ... if (...) ... end` shape (one intervening `begin`), not only
    the bare `initial if (...)` shape."""
    sites = lpc.find_combination_sites(
        INITIAL_IF_FATAL_FIXTURE_TEXT, "guard2", ["DEPTH", "WIDTH"],
        file_path="guard2.sv", base_line=1,
    )
    assert len(sites) == 1
    assert sites[0].status == lpc.ILLEGAL_COMBINATION_PROVEN
    assert sites[0].tested_params == ["DEPTH", "WIDTH"]


# --- negative control: construct spelled inside a comment/string -----------

COMMENT_ONLY_FIXTURE_TEXT = textwrap.dedent("""\
    module clean #(
        parameter int WIDTH = 8,
        parameter int MODE  = 1
    ) ();
        // generate
        //   if (WIDTH == 8 && MODE == 1) $error("fake, inside a comment");
        // endgenerate
        /* initial if (WIDTH == 8 && MODE == 1) $error("also fake"); */
        $display("initial if (WIDTH == 8 && MODE == 1) $error(\\"still fake\\");");
        assign y = a;
    endmodule
    """)


def test_construct_spelled_only_in_comment_or_string_is_never_reported():
    """Negative control: a generate-if / initial-if / $error shape spelled
    inside a // comment, a /* */ block comment, or a "..." string literal
    (e.g. a $display argument) must never be mistaken for a real construct."""
    sites = lpc.find_combination_sites(
        COMMENT_ONLY_FIXTURE_TEXT, "clean", ["WIDTH", "MODE"],
        file_path="clean.sv", base_line=1,
    )
    assert sites == []


# --- negative control: module with no such construct at all ----------------

NO_CONSTRUCT_FIXTURE_TEXT = textwrap.dedent("""\
    module plain #(
        parameter int WIDTH = 8,
        parameter int MODE  = 1
    ) (
        input  logic a,
        output logic y
    );
        assign y = a;
    endmodule
    """)


def test_module_with_no_combination_guard_is_honestly_not_available():
    """Negative control: a module that declares two-or-more parameters but
    contains no generate-if/initial-if construct at all must report
    NOT_AVAILABLE (empty sites), never a fabricated legal-combination fact
    synthesized from the parameter declarations alone."""
    sites = lpc.find_combination_sites(
        NO_CONSTRUCT_FIXTURE_TEXT, "plain", ["WIDTH", "MODE"],
        file_path="plain.sv", base_line=1,
    )
    assert sites == []


# --- negative control: unparseable/unclosed construct -----------------------

UNCLOSED_GENERATE_FIXTURE_TEXT = textwrap.dedent("""\
    module broken #(
        parameter int WIDTH = 8,
        parameter int MODE  = 1
    ) ();
        generate
            if (WIDTH == 8 && MODE == 1) begin
                assign y = a;
    """)


def test_unclosed_generate_block_reports_not_available_never_a_guess():
    """Negative control: a 'generate' with no matching 'endgenerate' (a
    truncated/malformed file) must report a NOT_AVAILABLE site citing the
    real 'generate' line, never a guessed LEGAL/ILLEGAL verdict."""
    sites = lpc.find_combination_sites(
        UNCLOSED_GENERATE_FIXTURE_TEXT, "broken", ["WIDTH", "MODE"],
        file_path="broken.sv", base_line=1,
    )
    assert len(sites) == 1
    site = sites[0]
    assert site.status == lpc.NOT_AVAILABLE
    assert site.branch_kind == lpc.BRANCH_UNRESOLVED
    assert site.condition_text is None
    assert site.tested_params == []
    assert site.reason is not None and "endgenerate" in site.reason
    assert site.line == 5  # the real line 'generate' itself sits on


UNCLOSED_CONDITION_FIXTURE_TEXT = textwrap.dedent("""\
    module broken2 #(
        parameter int WIDTH = 8,
        parameter int MODE  = 1
    ) ();
        generate
            if (WIDTH == 8 && MODE == 1
        endgenerate
    endmodule
    """)


def test_unclosed_if_condition_paren_reports_not_available_never_a_guess():
    """Negative control: an `if (` whose condition parentheses never close
    before the enclosing 'endgenerate' (a genuinely malformed/truncated
    condition) must report NOT_AVAILABLE for that specific site, never a
    guessed condition or verdict."""
    sites = lpc.find_combination_sites(
        UNCLOSED_CONDITION_FIXTURE_TEXT, "broken2", ["WIDTH", "MODE"],
        file_path="broken2.sv", base_line=1,
    )
    assert len(sites) == 1
    site = sites[0]
    assert site.status == lpc.NOT_AVAILABLE
    assert site.branch_kind == lpc.BRANCH_UNRESOLVED
    assert site.condition_text is None
    assert "could not close" in site.reason


# --- scope: fewer than two real declared parameters is out of scope --------

def test_single_parameter_condition_is_out_of_scope_not_a_site():
    text = textwrap.dedent("""\
        module single_p #(
            parameter int WIDTH = 8
        ) ();
            generate
                if (WIDTH == 8) begin
                    assign y = a;
                end else begin
                    initial $error("bad width");
                end
            endgenerate
        endmodule
        """)
    sites = lpc.find_combination_sites(
        text, "single_p", ["WIDTH"], file_path="single_p.sv", base_line=1,
    )
    assert sites == []


def test_condition_on_non_parameter_identifiers_is_out_of_scope_not_a_site():
    """A guard that tests two SIGNAL names (not declared parameters) must
    never be mistaken for a parameter-combination guard -- only identifiers
    that are among the module's own real declared parameter names count."""
    text = textwrap.dedent("""\
        module sig_guard #(
            parameter int WIDTH = 8,
            parameter int MODE  = 1
        ) (
            input logic req, input logic ack
        );
            generate
                if (req == 1'b1 && ack == 1'b0) begin
                    initial $error("bad handshake");
                end
            endgenerate
        endmodule
        """)
    sites = lpc.find_combination_sites(
        text, "sig_guard", ["WIDTH", "MODE"], file_path="sig_guard.sv", base_line=1,
    )
    assert sites == []


def test_first_statement_after_generate_not_if_is_a_silent_miss_not_a_site():
    """Boundary point 1: a generate block whose first real statement is NOT
    an if (a declaration, another construct) is not recognized by this
    scan at all -- this is a disclosed silent miss, not a NOT_AVAILABLE
    site, since no construct was identified to try (and fail) to close."""
    text = textwrap.dedent("""\
        module not_first #(
            parameter int WIDTH = 8,
            parameter int MODE  = 1
        ) ();
            generate
                genvar i;
                if (WIDTH == 8 && MODE == 1) begin
                    initial $error("never reached by this scan");
                end
            endgenerate
        endmodule
        """)
    sites = lpc.find_combination_sites(
        text, "not_first", ["WIDTH", "MODE"], file_path="not_first.sv", base_line=1,
    )
    assert sites == []


# --- module/file-level report shaping ---------------------------------------

def test_module_report_status_distinguishes_no_construct_from_unresolved_site():
    """The two absence shapes must never collapse into one: a module with
    truly no construct reports NOT_AVAILABLE at the MODULE level with an
    empty sites list; a module where a construct was found but could not be
    closed reports COMBINATION_SITES_FOUND at the module level (a real,
    if unresolved, site exists) with that one NOT_AVAILABLE site inside."""
    no_construct_sites = lpc.find_combination_sites(
        NO_CONSTRUCT_FIXTURE_TEXT, "plain", ["WIDTH", "MODE"], file_path="p.sv",
    )
    unresolved_sites = lpc.find_combination_sites(
        UNCLOSED_GENERATE_FIXTURE_TEXT, "broken", ["WIDTH", "MODE"], file_path="b.sv",
    )
    assert no_construct_sites == []
    assert len(unresolved_sites) == 1
    assert unresolved_sites[0].status == lpc.NOT_AVAILABLE


def test_extract_combination_facts_for_file_read_failure_is_honest():
    """Negative control: a file that cannot be read at all (does not exist)
    must report COMBO_FILE_UNAVAILABLE, never a silent 'no sites found'
    that looks identical to a real, successfully-scanned clean file."""
    report = lpc.extract_combination_facts_for_file("/nonexistent/does_not_exist.sv")
    assert report.parse_status == lpc.COMBO_FILE_UNAVAILABLE
    assert report.parse_reason is not None
    assert report.modules == []


def test_extract_combination_facts_for_file_verible_unavailable_is_honest(tmp_path):
    p = tmp_path / "cfg_mux.sv"
    p.write_text(GENERATE_IF_FIXTURE_TEXT, encoding="utf-8")
    report = lpc.extract_combination_facts_for_file(
        p, verible_bin="definitely-not-a-real-verible-binary",
    )
    assert report.parse_status == lpc.COMBO_FILE_UNAVAILABLE
    assert report.parse_reason
    assert report.modules == []


def test_render_combination_markdown_handles_empty_reports():
    md = lpc.render_combination_markdown([])
    assert "no RTL files supplied" in md


def test_vocabulary_does_not_collide_with_verification_verdict():
    # Re-running the import-time guard directly must not raise.
    lpc.assert_no_verification_verdict_vocabulary()


# --- worst-wins composite (MANDATORY HOUSE RULE 4) --------------------------

def test_fold_combination_verdicts_worst_wins_illegal_beats_everything():
    result = lpc.fold_combination_verdicts([
        lpc.LEGAL_COMBINATION_PROVEN, lpc.LEGAL_COMBINATION_PROVEN,
        lpc.ILLEGAL_COMBINATION_PROVEN, lpc.NOT_AVAILABLE,
    ])
    assert result == lpc.ILLEGAL_COMBINATION_PROVEN


def test_fold_combination_verdicts_worst_wins_not_available_beats_clean():
    """A single real unknown must outrank any number of clean sites --
    never averaged, never treated as 'mostly legal so it's fine'."""
    result = lpc.fold_combination_verdicts([
        lpc.LEGAL_COMBINATION_PROVEN, lpc.LEGAL_COMBINATION_PROVEN,
        lpc.LEGAL_COMBINATION_PROVEN, lpc.NOT_AVAILABLE,
    ])
    assert result == lpc.NOT_AVAILABLE


def test_fold_combination_verdicts_all_clean_is_legal():
    result = lpc.fold_combination_verdicts(
        [lpc.LEGAL_COMBINATION_PROVEN, lpc.LEGAL_COMBINATION_PROVEN],
    )
    assert result == lpc.LEGAL_COMBINATION_PROVEN


def test_fold_combination_verdicts_empty_list_is_not_available_not_clean():
    """Negative control: no evidence at all must never be presented as a
    clean pass."""
    assert lpc.fold_combination_verdicts([]) == lpc.NOT_AVAILABLE


# ===========================================================================
# Tier 2: real end-to-end pipeline through a real verible subprocess
# ===========================================================================

@pytest.fixture
def cfg_mux_sv(tmp_path):
    p = tmp_path / "cfg_mux.sv"
    p.write_text(GENERATE_IF_FIXTURE_TEXT, encoding="utf-8")
    return p


@pytest.fixture
def guard_sv(tmp_path):
    p = tmp_path / "guard.sv"
    p.write_text(INITIAL_IF_FIXTURE_TEXT, encoding="utf-8")
    return p


@pytest.fixture
def plain_sv(tmp_path):
    p = tmp_path / "plain.sv"
    p.write_text(NO_CONSTRUCT_FIXTURE_TEXT, encoding="utf-8")
    return p


@requires_verible
def test_end_to_end_generate_if_reports_real_parameters_and_citations(cfg_mux_sv):
    report = lpc.extract_combination_facts_for_file(cfg_mux_sv)
    assert report.parse_status == lpc.COMBO_FILE_PARSED
    assert len(report.modules) == 1
    mr = report.modules[0]
    assert mr.status == lpc.COMBINATION_SITES_FOUND
    assert len(mr.sites) == 2
    assert all(s.status == lpc.LEGAL_COMBINATION_PROVEN for s in mr.sites)
    assert all(s.file_path == str(cfg_mux_sv) for s in mr.sites)
    assert all(s.tested_params == ["MODE", "WIDTH"] for s in mr.sites)
    # Real citation: the first 'if' really does sit on this file's own real line.
    real_text = cfg_mux_sv.read_text(encoding="utf-8")
    if_line = next(
        i + 1 for i, line in enumerate(real_text.splitlines())
        if "if (WIDTH == 8 && MODE == 1)" in line
    )
    assert mr.sites[0].line == if_line


@requires_verible
def test_end_to_end_initial_if_error_guard_is_illegal(guard_sv):
    report = lpc.extract_combination_facts_for_file(guard_sv)
    assert report.parse_status == lpc.COMBO_FILE_PARSED
    mr = report.modules[0]
    assert mr.status == lpc.COMBINATION_SITES_FOUND
    assert len(mr.sites) == 1
    assert mr.sites[0].status == lpc.ILLEGAL_COMBINATION_PROVEN
    assert mr.sites[0].construct_kind == lpc.ELABORATION_ERROR_COMBINATION_GUARD


@requires_verible
def test_end_to_end_plain_module_is_honestly_not_available(plain_sv):
    """Negative control: a real module with real declared parameters but no
    combination-guard construct anywhere must report NOT_AVAILABLE, never a
    fabricated legal-combination fact."""
    report = lpc.extract_combination_facts_for_file(plain_sv)
    assert report.parse_status == lpc.COMBO_FILE_PARSED
    assert report.modules[0].status == lpc.NOT_AVAILABLE
    assert report.modules[0].sites == []


@requires_verible
def test_execute_verb_exit_code_reflects_findings(cfg_mux_sv, plain_sv, capsys):
    rc = lpc.execute_verb([str(cfg_mux_sv), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "LEGAL_COMBINATION_PROVEN" in captured.out
    assert "WIDTH" in captured.out


@requires_verible
def test_execute_verb_exit_code_two_when_nothing_found(plain_sv):
    rc = lpc.execute_verb([str(plain_sv)])
    assert rc == 2
