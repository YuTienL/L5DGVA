"""Tests for dv_harness/perf_function_extraction.py.

Fixtures live under dv_harness_tests/fixtures/perf_function_extraction/ and
are synthetic (their own file headers say so, not any real DUT/spec). The
positive-path tests prove every recognised statement shape is correctly
extracted, with a real citation, from real supplied RTL/spec text. The
negative controls prove the module reports honest NOT_AVAILABLE rather than
fabricating a performance-function fact when the supplied text does not
state one -- and that it never evaluates, measures, or estimates a single
performance number itself (that stays amba_performance_calculator.py's
job, per this session's own Performance Verification exclusion).
"""
import ast
import subprocess
import sys
from pathlib import Path

from dv_harness import perf_function_extraction as pfe

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "perf_function_extraction"
RTL_FIXTURE = FIXTURES / "synthetic_dma_engine.v"
SPEC_FIXTURE = FIXTURES / "synthetic_dma_spec.txt"
NO_FACTS_FIXTURE = FIXTURES / "no_perf_facts.txt"
MODULE_PATH = Path(pfe.__file__)


# ---------------------------------------------------------------------------
# Positive path: real RTL comments -> every recognised assignment/verb-first
# statement extracted correctly, each with a real citation.
# ---------------------------------------------------------------------------
def test_rtl_assignment_style_facts_extracted_with_citations():
    report = pfe.extract_performance_function_facts([str(RTL_FIXTURE)])

    assert report["status"] == "LOADED"
    assert report["reason"] is None
    assert report["source"]["paths"] == [str(RTL_FIXTURE)]
    assert report["source"]["missing"] == []

    facts_by_metric = {f["metric"]: f for f in report["facts"] if f["match_rule"] == "ASSIGNMENT"}

    assert "THROUGHPUT" in facts_by_metric
    tp = facts_by_metric["THROUGHPUT"]
    assert tp["formula_expression"] == "(num_beats * DATA_WIDTH_BYTES) / cycles_elapsed"
    assert tp["evidence"] == f"{RTL_FIXTURE}:12"

    assert "BANDWIDTH" in facts_by_metric
    bw = facts_by_metric["BANDWIDTH"]
    assert bw["formula_expression"] == "data_width_bytes * clk_freq_hz"

    assert "IOPS" in facts_by_metric
    iops = facts_by_metric["IOPS"]
    assert iops["formula_expression"] == "requests_completed / elapsed_seconds"


def test_rtl_verb_first_and_metric_first_sentences_extracted():
    report = pfe.extract_performance_function_facts([str(RTL_FIXTURE)])
    by_metric = {f["metric"]: f for f in report["facts"] if f["match_rule"] != "ASSIGNMENT"}

    assert by_metric["LATENCY"]["match_rule"] == "VERB_METRIC"
    assert "number of cycles" in by_metric["LATENCY"]["formula_expression"]

    assert by_metric["UTILIZATION"]["match_rule"] == "METRIC_VERB"
    assert by_metric["UTILIZATION"]["formula_expression"] == "busy_cycles / total_cycles"


def test_rtl_bare_metric_mention_with_no_formula_is_never_a_fact():
    """'// TODO: add a throughput counter here...' mentions the metric but
    has no verb+as/by/via and no assignment -- must never be extracted."""
    report = pfe.extract_performance_function_facts([str(RTL_FIXTURE)])
    texts = [f["statement_text"] for f in report["facts"]]
    assert not any("TODO" in t for t in texts)


def test_assignment_whose_lhs_names_no_metric_is_never_a_fact():
    """'// count = a + b;' is a real assignment but names no performance
    metric -- must never be reported as a performance function fact."""
    report = pfe.extract_performance_function_facts([str(RTL_FIXTURE)])
    texts = [f["statement_text"] for f in report["facts"]]
    assert not any("count = a + b" in t for t in texts)


# ---------------------------------------------------------------------------
# Positive path: real spec prose -> both verb-first and metric-first
# sentence forms extracted.
# ---------------------------------------------------------------------------
def test_spec_prose_facts_extracted_with_citations():
    report = pfe.extract_performance_function_facts([str(SPEC_FIXTURE)])
    assert report["status"] == "LOADED"

    by_metric = {f["metric"]: f for f in report["facts"]}

    assert by_metric["THROUGHPUT"]["match_rule"] == "VERB_METRIC"
    assert by_metric["THROUGHPUT"]["formula_expression"] == (
        "the number of bytes transferred divided by the number of elapsed cycles"
    )

    assert by_metric["BANDWIDTH"]["match_rule"] == "METRIC_VERB"
    assert "product of the data width" in by_metric["BANDWIDTH"]["formula_expression"]

    assert by_metric["LATENCY"]["match_rule"] == "METRIC_VERB"
    assert "request issue" in by_metric["LATENCY"]["formula_expression"]


def test_spec_bare_metric_mention_with_no_verb_is_never_a_fact():
    """"The engine's throughput is a key design consideration..." names the
    metric with no compute/calculate/derive/measure/define verb at all."""
    report = pfe.extract_performance_function_facts([str(SPEC_FIXTURE)])
    texts = [f["statement_text"] for f in report["facts"]]
    assert not any("key design consideration" in t for t in texts)


def test_multiple_sources_combined_in_one_report():
    report = pfe.extract_performance_function_facts([str(RTL_FIXTURE), str(SPEC_FIXTURE)])
    assert report["status"] == "LOADED"
    assert set(report["source"]["paths"]) == {str(RTL_FIXTURE), str(SPEC_FIXTURE)}
    evidence_files = {f["evidence"].rsplit(":", 1)[0] for f in report["facts"]}
    assert evidence_files == {str(RTL_FIXTURE), str(SPEC_FIXTURE)}


# ---------------------------------------------------------------------------
# Negative controls -- REQUIRED: the module refuses to fabricate an answer
# when evidence is absent.
# ---------------------------------------------------------------------------
def test_no_source_paths_reports_not_available():
    report = pfe.extract_performance_function_facts([])
    assert report["status"] == "NOT_AVAILABLE"
    assert "no source files were supplied" in report["reason"]
    assert report["facts"] == []


def test_none_source_paths_reports_not_available():
    report = pfe.extract_performance_function_facts(None)
    assert report["status"] == "NOT_AVAILABLE"
    assert report["facts"] == []


def test_missing_file_reports_not_available_and_names_it():
    missing = str(FIXTURES / "does_not_exist.v")
    report = pfe.extract_performance_function_facts([missing])
    assert report["status"] == "NOT_AVAILABLE"
    assert "does_not_exist.v" in report["reason"]
    assert report["source"]["missing"] == [missing]
    assert report["facts"] == []


def test_sources_read_but_no_perf_statement_found_reports_not_available():
    """The headline negative control: real text was read, but it states no
    documented performance-related function -- the module must NEVER
    invent one from a bare mention or a name alone."""
    report = pfe.extract_performance_function_facts([str(NO_FACTS_FIXTURE)])
    assert report["status"] == "NOT_AVAILABLE"
    assert report["source"]["paths"] == [str(NO_FACTS_FIXTURE)]
    assert report["facts"] == []
    assert "never invented" in report["reason"]


def test_mixed_missing_and_present_sources_still_extracts_the_present_one():
    missing = str(FIXTURES / "does_not_exist.v")
    report = pfe.extract_performance_function_facts([missing, str(RTL_FIXTURE)])
    assert report["status"] == "LOADED"
    assert report["source"]["missing"] == [missing]
    assert report["source"]["paths"] == [str(RTL_FIXTURE)]
    assert report["facts"]


def test_unrecognized_suffix_is_still_read_and_flagged():
    unrecognized = FIXTURES / "no_perf_facts.unknownext"
    unrecognized.write_text((FIXTURES / "no_perf_facts.txt").read_text(encoding="utf-8"),
                             encoding="utf-8")
    try:
        report = pfe.extract_performance_function_facts([str(unrecognized)])
        assert str(unrecognized) in report["source"]["unrecognized"]
        assert str(unrecognized) in report["source"]["paths"]
    finally:
        unrecognized.unlink()


def test_classify_source():
    assert pfe.classify_source("foo.sv") == "rtl"
    assert pfe.classify_source("foo.v") == "rtl"
    assert pfe.classify_source("foo.txt") == "text"
    assert pfe.classify_source("foo.spec") == "text"
    assert pfe.classify_source("foo.bin") == "unknown"


def test_disclosure_field_always_present_and_states_the_boundary():
    for paths in ([], [str(RTL_FIXTURE)]):
        report = pfe.extract_performance_function_facts(paths)
        assert "amba_performance_calculator" in report["disclosure"]
        assert "never" in report["disclosure"].lower()


# ---------------------------------------------------------------------------
# Structural proof: this module NEVER computes/evaluates a real performance
# number -- it only cites text. Proven by AST inspection of its own source,
# not merely asserted in prose.
# ---------------------------------------------------------------------------
def test_module_never_imports_the_arithmetic_or_measurement_modules():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden = {
        "amba_performance_calculator",
        "amba_performance_requirement_checker",
        "amba_performance_classification",
        "amba_performance_readiness_gates",
        "fsdb_report",
        "sim_log_analysis",
    }
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[-1])
            for alias in node.names:
                imported_names.add(alias.name)
    assert not (imported_names & forbidden), imported_names & forbidden


def test_module_never_calls_eval_or_exec():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("eval", "exec")


def test_extracted_formula_is_never_evaluated_it_is_only_cited_text():
    """The extracted formula_expression for a real formula-bearing line is
    the LITERAL source text, never a computed numeric result."""
    report = pfe.extract_performance_function_facts([str(RTL_FIXTURE)])
    tp = next(f for f in report["facts"] if f["metric"] == "THROUGHPUT"
              and f["match_rule"] == "ASSIGNMENT")
    # It is a string containing the real RTL expression text, not a number.
    assert isinstance(tp["formula_expression"], str)
    assert "num_beats" in tp["formula_expression"]
    try:
        float(tp["formula_expression"])
        assert False, "formula_expression must never be a bare evaluated number"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# CLI front door
# ---------------------------------------------------------------------------
def test_execute_verb_json_and_exit_code():
    code = pfe.execute_verb(["extract", "--sources", str(RTL_FIXTURE), "--json"])
    assert code == 0


def test_execute_verb_not_available_exit_code():
    code = pfe.execute_verb(["extract", "--sources", str(NO_FACTS_FIXTURE)])
    assert code == 2


def test_execute_verb_usage_error():
    code = pfe.execute_verb([])
    assert code == 2


def test_cli_subprocess_real_run():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.perf_function_extraction",
         "extract", "--sources", str(RTL_FIXTURE), str(SPEC_FIXTURE), "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert '"status": "LOADED"' in result.stdout
