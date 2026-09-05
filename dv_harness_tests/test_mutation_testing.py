"""Tests for dv_harness/mutation_testing.py -- mutation testing of THIS
repository's own Python test suite (2026-09-06).

These tests exercise the real thing end to end: real `dv_harness/*.py`
modules, mutated for real, run against their real existing test files in
real pytest subprocesses, and asserted to come back KILLED or SURVIVED as
the code under test genuinely deserves. The end-to-end cases are kept
narrow (`line_range` / `max_mutants`) because each mutant costs one full
pytest process -- narrow, not fake: every assertion below is about a mutant
that was actually generated, actually installed and actually run.

Scope reminder, same as the module's own: the subject is this repo's Python
tests. Nothing here is DUT/RTL fault injection.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import mutation_testing as mt

ROOT = Path(__file__).resolve().parents[1]

# One small, real target used by the end-to-end cases. `test_stats_snapshot.py`
# is the fastest self-contained module/test pair in this suite (~0.7s), which
# is what makes a real per-mutant pytest process affordable in a regression
# test at all.
STATS_MODULE = "dv_harness.stats_snapshot"
STATS_SOURCE = (ROOT / "dv_harness" / "stats_snapshot.py").read_text(encoding="utf-8")


def _line_containing(source: str, needle: str) -> int:
    """1-based line number of the single line containing `needle`.

    Located by content rather than hardcoded, so an edit above it in
    stats_snapshot.py cannot silently retarget these tests at a different
    expression.
    """
    hits = [i for i, line in enumerate(source.splitlines(), start=1) if needle in line]
    assert len(hits) == 1, f"expected exactly one line containing {needle!r}, found {hits}"
    return hits[0]


# --- mutant generation ----------------------------------------------------


SYNTHETIC = '''\
def classify(count, ready, forced):
    if count > 3 and ready:
        return True
    if count == 0 or forced:
        return False
    return None
'''


def test_all_four_operators_fire_on_one_synthetic_module():
    mutants = mt.generate_mutants(SYNTHETIC, "synthetic.py")
    fired = {m.operator for m in mutants}
    assert fired == set(mt.MUTATION_OPERATORS), f"missing operators: {set(mt.MUTATION_OPERATORS) - fired}"

    described = {m.describe().split(" at ")[0] + " " + m.original + "->" + m.mutated
                 for m in mutants}
    assert "COMPARISON_SWAP Gt->GtE" in described
    assert "COMPARISON_SWAP Eq->NotEq" in described
    assert "BOOL_OP_SWAP And->Or" in described
    assert "BOOL_OP_SWAP Or->And" in described
    assert "BOUNDARY_SHIFT 3->4" in described
    assert "BOUNDARY_SHIFT 0->1" in described
    assert "BOOL_CONST_FLIP True->False" in described
    assert "BOOL_CONST_FLIP False->True" in described


def test_every_mutant_is_valid_python_and_actually_differs():
    """A mutation harness that emits un-importable source spends its whole
    budget on noise, and one that emits an unchanged source inflates the
    denominator with mutants nothing could ever kill."""
    mutants = mt.generate_mutants(STATS_SOURCE, "stats_snapshot.py")
    assert mutants, "the real module must yield at least one mutant"
    for m in mutants:
        compile(m.source, "<mutant>", "exec")  # raises SyntaxError if malformed
        assert m.source != STATS_SOURCE, f"{m.mutant_id} did not change anything"
    assert len({m.source for m in mutants}) == len(mutants), "duplicate mutant sources"


def test_generation_does_not_leak_one_mutation_into_the_next():
    """Every mutant carries exactly ONE change. The generator mutates a
    shared AST in place and undoes it, so a missed undo would silently
    produce compound mutants -- and a compound mutant's kill says nothing
    about which fault the tests caught."""
    mutants = mt.generate_mutants(SYNTHETIC, "synthetic.py")
    import ast
    baseline = ast.dump(ast.parse(SYNTHETIC))
    for m in mutants:
        dumped = ast.dump(ast.parse(m.source))
        assert dumped != baseline
    # Re-generating from the same source must reproduce the identical set,
    # which it cannot if the tree were left dirty.
    again = mt.generate_mutants(SYNTHETIC, "synthetic.py")
    assert [x.source for x in again] == [x.source for x in mutants]
    assert [x.mutant_id for x in again] == [x.mutant_id for x in mutants]


def test_mutants_are_reported_in_source_order_with_stable_ids():
    mutants = mt.generate_mutants(STATS_SOURCE, "stats_snapshot.py")
    assert [m.lineno for m in mutants] == sorted(m.lineno for m in mutants)
    assert [m.mutant_id for m in mutants] == [f"m{i:03d}" for i in range(1, len(mutants) + 1)]


def test_negative_literal_is_labelled_the_way_the_source_spells_it():
    """`-1` is UnaryOp(USub, Constant(1)); a report saying "1 -> 2" for a
    line that reads `end == -1` is unreviewable."""
    mutants = mt.generate_mutants(STATS_SOURCE, "stats_snapshot.py")
    negatives = [m for m in mutants if m.operator == mt.BOUNDARY_SHIFT and m.original == "-1"]
    assert negatives, "stats_snapshot.py's `end == -1` sentinel must produce a labelled mutant"
    assert negatives[0].mutated == "-2"


def test_operator_filter_and_line_range_narrow_the_generated_set():
    everything = mt.generate_mutants(STATS_SOURCE, "stats_snapshot.py")
    comparisons = mt.generate_mutants(STATS_SOURCE, "stats_snapshot.py",
                                       operators=[mt.COMPARISON_SWAP])
    assert comparisons, "the real module has comparisons to swap"
    assert len(comparisons) < len(everything)
    assert {m.operator for m in comparisons} == {mt.COMPARISON_SWAP}

    target_line = _line_containing(STATS_SOURCE, "end == -1")
    scoped = mt.generate_mutants(STATS_SOURCE, "stats_snapshot.py",
                                  line_range=(target_line, target_line))
    assert scoped, "the sentinel line must be mutable"
    assert {m.lineno for m in scoped} == {target_line}


# --- the safety guards ----------------------------------------------------


def test_refuses_a_module_outside_the_dv_harness_package(tmp_path):
    stray = tmp_path / "stray.py"
    stray.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(mt.UnsafeMutationTargetError, match="not inside"):
        mt.assert_safe_target(ROOT, stray, ROOT / "dv_harness_tests" / "test_stats_snapshot.py")


def test_refuses_a_test_file_outside_the_dv_harness_tests_suite(tmp_path):
    """The "a mutant run can never reach a real build/regression/LSF
    submission" argument rests entirely on the test file living in the suite
    whose conftest.py pins the resource-probe transport off. If this guard
    is ever relaxed, that argument is gone."""
    stray_test = tmp_path / "test_stray.py"
    stray_test.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    with pytest.raises(mt.UnsafeMutationTargetError, match="conftest"):
        mt.assert_safe_target(ROOT, ROOT / "dv_harness" / "stats_snapshot.py", stray_test)


def test_refuses_a_module_that_does_not_exist():
    with pytest.raises(mt.UnsafeMutationTargetError, match="does not exist"):
        mt.assert_safe_target(ROOT, ROOT / "dv_harness" / "no_such_module.py",
                              ROOT / "dv_harness_tests" / "test_stats_snapshot.py")


def test_unregistered_module_needs_an_explicit_test_file():
    with pytest.raises(mt.UnsafeMutationTargetError, match="no default test file"):
        mt.resolve_target(ROOT, "dv_harness.engine")
    module_file, test_file = mt.resolve_target(
        ROOT, "dv_harness.engine", "dv_harness_tests/test_stats_snapshot.py")
    assert module_file == ROOT / "dv_harness" / "engine.py"
    assert test_file == ROOT / "dv_harness_tests" / "test_stats_snapshot.py"


def test_every_default_target_names_a_real_module_and_a_real_test_file():
    """Drift guard: a DEFAULT_TARGETS pair that stops resolving would turn
    the bare `dv-harness mutation-test` into a crash."""
    assert mt.DEFAULT_TARGETS, "the default target set must not be empty"
    for module, test_rel in mt.DEFAULT_TARGETS.items():
        module_file, test_file = mt.resolve_target(ROOT, module)
        mt.assert_safe_target(ROOT, module_file, test_file)
        assert test_file == ROOT / test_rel


def test_short_module_name_is_accepted_and_qualified():
    module_file, _ = mt.resolve_target(ROOT, "stats_snapshot")
    assert module_file == ROOT / "dv_harness" / "stats_snapshot.py"


# --- running mutants for real ---------------------------------------------


def test_one_real_line_yields_one_real_kill_and_one_real_survivor():
    """The core end-to-end proof, on real code and real tests.

    `stats_snapshot.py`'s `if end == -1: return False` sentinel yields
    exactly two mutants, whose outcomes differ for a reason that is provable
    by inspection rather than by hoping:

      * `==` -> `!=` inverts the sentinel, so frontmatter parsing breaks for
        every real agent profile and `test_agent_count_matches_real_glob`
        fails. KILLED.
      * `-1` -> `-2` is an EQUIVALENT mutant: `str.find` returns either -1 or
        a non-negative index and can never return -2, so no observable
        behaviour changes and no test can ever detect it. SURVIVED.

    If the harness's import hook were not actually installing the mutant,
    BOTH would survive; if it were breaking the module, both would be
    killed. Only a real, working mutation run separates them.
    """
    target_line = _line_containing(STATS_SOURCE, "end == -1")
    report = mt.run_mutation_test(ROOT, STATS_MODULE, line_range=(target_line, target_line))

    assert report.baseline == mt.BASELINE_OK, report.baseline_detail
    assert report.generated == 2, [m.describe() for m in report.mutants]
    assert report.executed == 2

    by_change = {(m.original, m.mutated): m for m in report.mutants}
    assert by_change[("Eq", "NotEq")].outcome == mt.MutantOutcome.KILLED.value
    assert by_change[("Eq", "NotEq")].returncode not in (0, None)
    assert by_change[("-1", "-2")].outcome == mt.MutantOutcome.SURVIVED.value
    assert by_change[("-1", "-2")].returncode == 0

    assert report.killed == 1 and report.survived == 1 and report.timeout == 0
    assert report.mutation_score == 0.5
    assert [m.describe() for m in report.survivors] == [by_change[("-1", "-2")].describe()]


def test_a_run_never_writes_to_the_module_it_mutates():
    """Non-negotiable: the mutant lives in a temp file served by an import
    hook, never in the working tree. A crash mid-run must not be able to
    leave a deliberately-broken dv_harness/*.py behind."""
    module_file = ROOT / "dv_harness" / "stats_snapshot.py"
    before_bytes = module_file.read_bytes()
    before_mtime = module_file.stat().st_mtime_ns

    target_line = _line_containing(STATS_SOURCE, "end == -1")
    report = mt.run_mutation_test(ROOT, STATS_MODULE, line_range=(target_line, target_line),
                                   operators=[mt.COMPARISON_SWAP])
    assert report.executed == 1 and report.killed == 1

    assert module_file.read_bytes() == before_bytes
    assert module_file.stat().st_mtime_ns == before_mtime


def test_max_mutants_leaves_the_rest_not_run_instead_of_dropping_them():
    """A cap must shrink the numerator AND stay visible: mutants that were
    never executed are reported NOT_RUN, so `generated` and `executed`
    disagree loudly rather than a partial run reading like a full one."""
    report = mt.run_mutation_test(ROOT, "dv_harness.qualification", max_mutants=1)
    assert report.baseline == mt.BASELINE_OK, report.baseline_detail
    assert report.generated > 1, "test needs a module with more than one mutant"
    assert report.executed == 1
    assert report.not_run == report.generated - 1
    assert report.killed + report.survived + report.timeout == 1
    # qualification.py's comparisons are all directly asserted by
    # test_qualification.py, so the executed one is genuinely killed.
    assert report.killed == 1
    assert report.mutation_score == 1.0


def test_baseline_failure_scores_nothing_and_runs_no_mutant():
    """Killed/survived counts off a red suite are meaningless, so a failing
    baseline must produce no score at all rather than a plausible number.
    Forced here by pointing pytest at a selector that matches no test, which
    real pytest exits non-zero on (exit code 5, no tests collected)."""
    report = mt.run_mutation_test(
        ROOT, STATS_MODULE,
        pytest_args=("-q", "--no-header", "--color=no", "-p", "no:cacheprovider",
                     "-k", "there_is_no_test_with_this_name"))
    assert report.baseline == mt.BASELINE_FAILED
    assert report.baseline_detail, "a failed baseline must say why"
    assert report.mutation_score is None
    assert report.killed == 0 and report.survived == 0
    assert report.generated > 0
    assert report.not_run == report.generated
    assert all(m.outcome == mt.MutantOutcome.NOT_RUN.value for m in report.mutants)


def test_a_hang_is_reported_as_timeout_not_as_a_kill():
    """A mutant that makes the tests hang is not the tests detecting the
    fault. `_run_source_under_tests` signals it with returncode None, which
    `run_mutation_test` buckets as TIMEOUT and excludes from `killed`."""
    module_file = ROOT / "dv_harness" / "stats_snapshot.py"
    rc, detail = mt._run_source_under_tests(
        ROOT, STATS_MODULE, module_file, STATS_SOURCE,
        ROOT / "dv_harness_tests" / "test_stats_snapshot.py",
        timeout=0.001, pytest_args=mt.DEFAULT_PYTEST_ARGS)
    assert rc is None
    assert "did not finish" in detail


def test_report_json_is_serialisable_and_omits_the_mutant_sources():
    """A report carrying one full copy of the module per mutant is unusable
    as CLI output."""
    mutants = mt.generate_mutants(STATS_SOURCE, "stats_snapshot.py")
    report = mt.MutationReport(
        module=STATS_MODULE, module_path="m.py", test_path="t.py",
        baseline=mt.BASELINE_OK, baseline_detail="5 passed",
        generated=len(mutants), executed=0, killed=0, survived=0, timeout=0,
        not_run=len(mutants), mutation_score=None, mutants=mutants)
    payload = json.loads(report.to_json())
    assert payload["summary"]["generated"] == len(mutants)
    assert "NOT DUT/RTL" in payload["scope"]
    for entry in payload["mutants"]:
        assert "source" not in entry
        assert entry["operator"] in mt.MUTATION_OPERATORS


# --- the CLI front door ---------------------------------------------------


def _run_cli(*args):
    return subprocess.run([sys.executable, "-m", "dv_harness", *args],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=300)


def test_cli_list_reports_the_real_mutants_without_running_any():
    result = _run_cli("mutation-test", "--module", "dv_harness.qualification", "--list")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["module"] == "dv_harness.qualification"
    assert payload["generated"] == len(mt.generate_mutants(
        (ROOT / "dv_harness" / "qualification.py").read_text(encoding="utf-8"), "q.py"))
    assert all(m["outcome"] == mt.MutantOutcome.NOT_RUN.value for m in payload["mutants"])


def test_cli_min_score_is_opt_in_and_really_fails_below_the_threshold():
    """Mutation score is a measurement, not a gate -- but a caller that asks
    for a floor must actually get a non-zero exit when the score is under it.
    Run on the ONE provably-equivalent survivor, so the assertion never
    depends on a weak test somebody might later strengthen."""
    target_line = _line_containing(STATS_SOURCE, "end == -1")
    result = _run_cli("mutation-test", "--module", STATS_MODULE,
                      "--lines", f"{target_line}:{target_line}",
                      "--operator", mt.BOUNDARY_SHIFT, "--min-score", "1.0")
    payload = json.loads(result.stdout)
    assert payload["summary"] == {
        "generated": 1, "executed": 1, "killed": 0, "survived": 1,
        "timeout": 0, "not_run": 0, "mutation_score": 0.0,
    }, payload["summary"]
    assert result.returncode == 1, "a score below --min-score must exit non-zero"


def test_cli_rejects_one_test_file_for_several_modules():
    result = _run_cli("mutation-test", "--module", "dv_harness.qualification",
                      "--module", STATS_MODULE, "--test",
                      "dv_harness_tests/test_stats_snapshot.py", "--list")
    assert result.returncode != 0
    assert "exactly one --module" in (result.stdout + result.stderr)
