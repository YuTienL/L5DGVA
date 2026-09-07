"""Tests for dv_harness.system_command_grammar_ir.

Synthetic fixtures only (never real project content), matching
`test_de_command_style_learning.py`'s own established precedent. Each
fixture is a small, real DE `command.txt`-style file, read through the
REAL `de_command_style_learning.learn_command_style()` reader (never a
hand-built `CommandStyleIR`) so these tests prove the composition against
genuine pattern-detected evidence, not a stand-in.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness.de_command_style_learning import learn_command_style
from dv_harness.system_command_grammar_ir import (
    FACET_NAMES,
    FACET_STATUS_AMBIGUOUS,
    FACET_STATUS_CONFLICTING,
    FACET_STATUS_NOT_AVAILABLE,
    FACET_STATUS_UNIFORM,
    SYSTEM_STATUS_AMBIGUOUS,
    SYSTEM_STATUS_CONFLICTING,
    SYSTEM_STATUS_NOT_AVAILABLE,
    SYSTEM_STATUS_UNIFORM,
    SystemCommandGrammarError,
    build_system_command_grammar_ir,
    format_system_command_grammar,
    learn_system_command_grammar,
    system_command_grammar_to_dict,
)

# --- fixtures -----------------------------------------------------------------

# One-statement-per-line, semicolon-terminated, underscore-grouped hex,
# trailing line comments -- the same real convention
# test_de_command_style_learning.py's own synthetic fixture uses.
_UNIFORM_A = """\
// synthetic fixture -- never real project content
`HOSTWRITE4B(32'hAA00_0004, 32'hFFFF); //enable_evt
`CPUWRITE4B(32'hBB00_0004, 32'hFFFF); //enable_evt
`HOSTWRITE4B(32'hAA00_0008, 32'h0001); //mode_set
$finish;
"""

# A second subsystem written in the identical real style -- same separator,
# same argument format, same comment style, no phase markers, no fork/join.
_UNIFORM_B = """\
// synthetic fixture -- never real project content
`HOSTWRITE4B(32'hCC00_0004, 32'hFFFF); //enable_evt
`CPUWRITE4B(32'hDD00_0004, 32'hFFFF); //enable_evt
$finish;
"""

# A subsystem whose separator convention genuinely differs: several
# statements share one semicolon-terminated line, so the detected
# convention is SEMICOLON_TERMINATED_MULTI_STATEMENT_OR_MULTI_LINE rather
# than ONE_PER_LINE.
_CONFLICTING_SEPARATOR = """\
// synthetic fixture -- never real project content
`HOSTWRITE4B(32'hEE00_0004, 32'hFFFF); `CPUWRITE4B(32'hEE00_0008, 32'h1); //two statements, one line
`HOSTWRITE4B(32'hEE00_000C, 32'h2); `CPUWRITE4B(32'hEE00_0010, 32'h2); //two statements, one line
`HOSTWRITE4B(32'hEE00_0014, 32'h3); `CPUWRITE4B(32'hEE00_0018, 32'h3); //two statements, one line
$finish;
"""

# A subsystem with genuinely no evidence at all for any facet.
_EMPTY = ""

# A subsystem whose comment style is standalone rather than trailing.
_STANDALONE_COMMENTS = """\
// synthetic fixture -- never real project content
// enable_evt
`HOSTWRITE4B(32'hFF00_0004, 32'hFFFF);
// mode_set
`CPUWRITE4B(32'hFF00_0008, 32'h0001);
$finish;
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# --- build_system_command_grammar_ir: UNIFORM path ---------------------------


def test_two_subsystems_with_identical_style_are_uniform(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_b = learn_command_style(_write(tmp_path, "b.txt", _UNIFORM_B))
    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_b": style_b})

    assert ir.system_status == SYSTEM_STATUS_UNIFORM
    assert ir.subsystem_ids == ["subsys_a", "subsys_b"]
    for facet_name in FACET_NAMES:
        facet = ir.facets[facet_name]
        assert facet.status in (FACET_STATUS_UNIFORM, FACET_STATUS_NOT_AVAILABLE)


def test_uniform_separator_facet_reports_the_real_agreed_convention(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_b = learn_command_style(_write(tmp_path, "b.txt", _UNIFORM_B))
    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_b": style_b})

    sep = ir.facets["separator_convention"]
    assert sep.status == FACET_STATUS_UNIFORM
    assert sep.system_convention == "SEMICOLON_TERMINATED_ONE_PER_LINE"
    assert sep.evidenced_subsystems == ["subsys_a", "subsys_b"]
    assert sep.absent_subsystems == []


def test_single_subsystem_system_is_trivially_uniform(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    ir = build_system_command_grammar_ir({"subsys_a": style_a})
    assert ir.system_status == SYSTEM_STATUS_UNIFORM
    assert ir.facets["separator_convention"].system_convention == \
        "SEMICOLON_TERMINATED_ONE_PER_LINE"


# --- CONFLICTING path: genuine disagreement, never picked between -----------


def test_genuinely_different_separator_conventions_are_conflicting(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_c = learn_command_style(_write(tmp_path, "c.txt", _CONFLICTING_SEPARATOR))

    sep_a = style_a.separator_convention["convention"]
    sep_c = style_c.separator_convention["convention"]
    # Sanity: the two real, independently pattern-detected conventions must
    # actually differ, or this test proves nothing.
    assert sep_a == "SEMICOLON_TERMINATED_ONE_PER_LINE"
    assert sep_c == "SEMICOLON_TERMINATED_MULTI_STATEMENT_OR_MULTI_LINE"
    assert sep_a != sep_c

    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_c": style_c})
    sep = ir.facets["separator_convention"]
    assert sep.status == FACET_STATUS_CONFLICTING
    # Never fabricated: no single winner is reported.
    assert sep.system_convention is None
    assert set(sep.distinct_conventions.keys()) == {sep_a, sep_c}
    assert sep.distinct_conventions[sep_a] == ["subsys_a"]
    assert sep.distinct_conventions[sep_c] == ["subsys_c"]
    assert ir.system_status == SYSTEM_STATUS_CONFLICTING


def test_conflicting_facet_never_silently_picks_the_first_alphabetically(tmp_path: Path):
    # subsys_a sorts before subsys_c alphabetically -- verify the module
    # does not silently prefer the alphabetically-first subsystem's
    # convention when they disagree.
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_c = learn_command_style(_write(tmp_path, "c.txt", _CONFLICTING_SEPARATOR))
    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_c": style_c})
    assert ir.facets["separator_convention"].system_convention is None


def test_one_conflicting_facet_fails_the_whole_worst_wins_composite(tmp_path: Path):
    # Every OTHER facet agrees between these two fixtures (both use
    # trailing comments, no phase markers, no fork/join, comma-separated
    # hex args) -- only the separator convention genuinely disagrees. The
    # worst-wins rule must still fail the whole system_status.
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_c = learn_command_style(_write(tmp_path, "c.txt", _CONFLICTING_SEPARATOR))
    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_c": style_c})

    non_separator_facets = [f for f in FACET_NAMES if f != "separator_convention"]
    clean_count = sum(
        1 for f in non_separator_facets
        if ir.facets[f].status in (FACET_STATUS_UNIFORM, FACET_STATUS_NOT_AVAILABLE))
    assert clean_count == len(non_separator_facets), (
        "test fixture assumption broken: expected every facet except the "
        "separator convention to be clean")
    assert ir.system_status == SYSTEM_STATUS_CONFLICTING


# --- AMBIGUOUS path: agreed-but-partial evidence, never read as UNIFORM -----


def test_partial_evidence_is_ambiguous_not_uniform(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_empty = learn_command_style(_write(tmp_path, "empty.txt", _EMPTY))

    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_empty": style_empty})
    sep = ir.facets["separator_convention"]
    assert sep.status == FACET_STATUS_AMBIGUOUS
    # The one real agreed value is still reported (it IS real evidence)...
    assert sep.system_convention == "SEMICOLON_TERMINATED_ONE_PER_LINE"
    # ...but the absence is honestly named, never hidden.
    assert sep.absent_subsystems == ["subsys_empty"]
    assert sep.evidenced_subsystems == ["subsys_a"]
    assert ir.system_status == SYSTEM_STATUS_AMBIGUOUS


def test_ambiguous_never_reads_as_uniform_in_the_composite(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_empty = learn_command_style(_write(tmp_path, "empty.txt", _EMPTY))
    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_empty": style_empty})
    assert ir.system_status != SYSTEM_STATUS_UNIFORM
    assert ir.system_status == SYSTEM_STATUS_AMBIGUOUS


# --- NOT_AVAILABLE path: negative control -- never fabricate an answer -----


def test_no_evidence_anywhere_is_not_available_never_a_guessed_convention(tmp_path: Path):
    style_empty_1 = learn_command_style(_write(tmp_path, "empty1.txt", _EMPTY))
    style_empty_2 = learn_command_style(_write(tmp_path, "empty2.txt", _EMPTY))
    ir = build_system_command_grammar_ir({"s1": style_empty_1, "s2": style_empty_2})

    assert ir.system_status == SYSTEM_STATUS_NOT_AVAILABLE
    for facet_name in FACET_NAMES:
        facet = ir.facets[facet_name]
        assert facet.status == FACET_STATUS_NOT_AVAILABLE
        # The core negative control: no convention is fabricated when no
        # subsystem has any real evidence at all.
        assert facet.system_convention is None
        assert facet.evidenced_subsystems == []


def test_empty_subsystem_map_is_not_available_and_never_crashes():
    ir = build_system_command_grammar_ir({})
    assert ir.system_status == SYSTEM_STATUS_NOT_AVAILABLE
    assert ir.subsystem_ids == []
    assert ir.facets == {}
    assert "no subsystem" in ir.basis.lower()


# --- comment-format facet, exercised independently of the separator one ----


def test_conflicting_comment_style_is_reported_on_its_own_facet(tmp_path: Path):
    style_trailing = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_standalone = learn_command_style(
        _write(tmp_path, "s.txt", _STANDALONE_COMMENTS))

    assert style_trailing.comment_format["convention"] == "LINE_COMMENT_TRAILING"
    assert style_standalone.comment_format["convention"] == "LINE_COMMENT_STANDALONE"

    ir = build_system_command_grammar_ir(
        {"subsys_a": style_trailing, "subsys_s": style_standalone})
    comment = ir.facets["comment_format"]
    assert comment.status == FACET_STATUS_CONFLICTING
    assert comment.system_convention is None


# --- learn_system_command_grammar: real reuse of learn_command_style -------


def test_learn_system_command_grammar_reuses_the_real_reader(tmp_path: Path):
    path_a = _write(tmp_path, "a.txt", _UNIFORM_A)
    path_b = _write(tmp_path, "b.txt", _UNIFORM_B)
    ir = learn_system_command_grammar({"subsys_a": path_a, "subsys_b": path_b})
    assert ir.system_status == SYSTEM_STATUS_UNIFORM
    assert ir.source_files["subsys_a"] == str(path_a)
    assert ir.source_files["subsys_b"] == str(path_b)


# --- accepting an already-serialized (plain dict) style record -------------


def test_build_accepts_plain_dict_style_records(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_b = learn_command_style(_write(tmp_path, "b.txt", _UNIFORM_B))
    from dataclasses import asdict
    plain_a = asdict(style_a)
    plain_b = asdict(style_b)
    ir = build_system_command_grammar_ir({"subsys_a": plain_a, "subsys_b": plain_b})
    assert ir.system_status == SYSTEM_STATUS_UNIFORM
    assert ir.facets["separator_convention"].system_convention == \
        "SEMICOLON_TERMINATED_ONE_PER_LINE"


def test_malformed_style_record_raises_rather_than_silently_skipping():
    with pytest.raises(SystemCommandGrammarError):
        build_system_command_grammar_ir({"bad": object()})


def test_malformed_facet_shape_raises():
    with pytest.raises(SystemCommandGrammarError):
        build_system_command_grammar_ir(
            {"bad": {"separator_convention": "not-a-dict"}})


# --- rendering ----------------------------------------------------------------


def test_to_dict_is_json_friendly(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_c = learn_command_style(_write(tmp_path, "c.txt", _CONFLICTING_SEPARATOR))
    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_c": style_c})
    payload = system_command_grammar_to_dict(ir)
    import json
    json.dumps(payload)  # must not raise
    assert payload["system_status"] == SYSTEM_STATUS_CONFLICTING
    assert payload["facets"]["separator_convention"]["status"] == FACET_STATUS_CONFLICTING


def test_format_is_human_readable_and_names_conflicting_subsystems(tmp_path: Path):
    style_a = learn_command_style(_write(tmp_path, "a.txt", _UNIFORM_A))
    style_c = learn_command_style(_write(tmp_path, "c.txt", _CONFLICTING_SEPARATOR))
    ir = build_system_command_grammar_ir({"subsys_a": style_a, "subsys_c": style_c})
    text = format_system_command_grammar(ir)
    assert "CONFLICTING" in text
    assert "subsys_a" in text and "subsys_c" in text


# --- CLI (standalone python -m front door) ----------------------------------


def test_cli_reports_conflicting_exit_code(tmp_path: Path):
    path_a = _write(tmp_path, "a.txt", _UNIFORM_A)
    path_c = _write(tmp_path, "c.txt", _CONFLICTING_SEPARATOR)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_command_grammar_ir",
         "--subsystem", f"subsys_a={path_a}",
         "--subsystem", f"subsys_c={path_c}", "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stderr
    assert "CONFLICTING" in result.stdout


def test_cli_reports_uniform_exit_code(tmp_path: Path):
    path_a = _write(tmp_path, "a.txt", _UNIFORM_A)
    path_b = _write(tmp_path, "b.txt", _UNIFORM_B)
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_command_grammar_ir",
         "--subsystem", f"subsys_a={path_a}",
         "--subsystem", f"subsys_b={path_b}"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "UNIFORM" in result.stdout


def test_cli_requires_at_least_one_subsystem():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.system_command_grammar_ir"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert result.returncode == 2
