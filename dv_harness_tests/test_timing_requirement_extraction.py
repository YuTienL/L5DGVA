"""Tests for dv_harness/timing_requirement_extraction.py.

Fixtures live under dv_harness_tests/fixtures/timing_requirement_extraction/
and are synthetic (their own file headers say so, not any real DUT/spec).
The positive-path test proves every explicitly-stated setup/hold/latency
bound is extracted with a real citation; the negative controls prove the
module reports honest NOT_AVAILABLE (or silently drops a line) rather than
fabricating a bound, direction, or subject the text does not literally
state -- and, the property this module is graded on specifically, that a
sentence reporting a MEASURED/OBSERVED value is never extracted as if it
were a documented requirement.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import timing_requirement_extraction as tre

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "timing_requirement_extraction"
DOC_FIXTURE = FIXTURES / "programming_guide.txt"
BLANK_FIXTURE = FIXTURES / "no_timing_requirements.txt"
RTL_FIXTURE = FIXTURES / "dut_io.sv"


# ---------------------------------------------------------------------------
# Positive path: every explicitly-stated bound is extracted with a real
# citation, and the honest per-line skips (TBD, ambiguous direction) are
# proven not to have contributed a fact.
# ---------------------------------------------------------------------------
def test_positive_path_extracts_every_explicit_bound_with_citation():
    report = tre.extract_timing_requirements([str(DOC_FIXTURE)])

    assert report["status"] == "LOADED"
    assert report["reason"] is None
    assert report["source"]["paths"] == [str(DOC_FIXTURE)]
    assert report["source"]["missing"] == []

    tr = report["timing_requirements"]
    assert tr["status"] == "LOADED"
    assert len(tr["requirements"]) == 4

    setup = tr["by_kind"]["SETUP"]
    assert setup["status"] == "LOADED"
    assert len(setup["requirements"]) == 1
    setup_fact = setup["requirements"][0]
    assert setup_fact["comparison"] == ">="
    assert setup_fact["value"] == 5.0
    assert setup_fact["unit"] == "ns"
    assert setup_fact["subject"] == "DATA-CLK"
    assert setup_fact["evidence"] == f"{DOC_FIXTURE}:4"

    hold = tr["by_kind"]["HOLD"]
    assert hold["status"] == "LOADED"
    hold_fact = hold["requirements"][0]
    assert hold_fact["comparison"] == ">="
    assert hold_fact["value"] == 2.0
    assert hold_fact["unit"] == "ns"
    assert hold_fact["subject"] == "DATA-CLK"
    assert hold_fact["evidence"] == f"{DOC_FIXTURE}:5"

    latency = tr["by_kind"]["LATENCY"]
    assert latency["status"] == "LOADED"
    assert len(latency["requirements"]) == 2
    read_lat = next(f for f in latency["requirements"] if f["unit"] == "cycles")
    assert read_lat["comparison"] == "<="
    assert read_lat["value"] == 16.0
    assert read_lat["subject"] is None
    assert read_lat["evidence"] == f"{DOC_FIXTURE}:6"
    write_lat = next(f for f in latency["requirements"] if f["unit"] == "ns")
    assert write_lat["comparison"] == "<="
    assert write_lat["value"] == 20.0
    assert write_lat["evidence"] == f"{DOC_FIXTURE}:7"


# ---------------------------------------------------------------------------
# Negative control 1 (the property this module is graded on specifically):
# a sentence reporting an OBSERVED/MEASURED value is never extracted as a
# documented requirement, even though it uses "setup" and a number+unit.
# ---------------------------------------------------------------------------
def test_measured_or_observed_language_is_never_extracted_as_a_requirement():
    report = tre.extract_timing_requirements([str(DOC_FIXTURE)])
    all_text = [f["text"] for f in report["timing_requirements"]["requirements"]]
    assert not any("observed" in t.lower() or "simulation" in t.lower() for t in all_text)
    assert not any(f["value"] == 6.0 for f in report["timing_requirements"]["requirements"])


# ---------------------------------------------------------------------------
# Negative control 2: a timing keyword with NO number ("is TBD") extracts
# nothing for that line -- never a guessed value.
# ---------------------------------------------------------------------------
def test_keyword_with_no_number_extracts_nothing():
    report = tre.extract_timing_requirements([str(DOC_FIXTURE)])
    setups = report["timing_requirements"]["by_kind"]["SETUP"]["requirements"]
    assert not any(f["subject"] == "CTRL" for f in setups)
    assert len(setups) == 1  # only the DATA-CLK line, never a TBD placeholder


# ---------------------------------------------------------------------------
# Negative control 3: a number+unit with NO explicit min/max/exact
# directional cue ("Latency is 50 ns.") extracts nothing -- an ambiguous
# magnitude is never guessed into a comparison direction.
# ---------------------------------------------------------------------------
def test_number_with_no_directional_cue_extracts_nothing():
    report = tre.extract_timing_requirements([str(DOC_FIXTURE)])
    latencies = report["timing_requirements"]["by_kind"]["LATENCY"]["requirements"]
    assert not any(f["value"] == 50.0 for f in latencies)


# ---------------------------------------------------------------------------
# Negative control 4: a document with no timing language at all reports
# NOT_AVAILABLE at every level, never a fabricated empty-but-LOADED status.
# ---------------------------------------------------------------------------
def test_document_with_no_timing_language_reports_not_available():
    report = tre.extract_timing_requirements([str(BLANK_FIXTURE)])
    assert report["status"] == "NOT_AVAILABLE"
    tr = report["timing_requirements"]
    assert tr["status"] == "NOT_AVAILABLE"
    assert tr["requirements"] == []
    assert "no documented" in tr["reason"]
    for kind in tre.TIMING_REQUIREMENT_KINDS:
        assert tr["by_kind"][kind]["status"] == "NOT_AVAILABLE"
        assert tr["by_kind"][kind]["requirements"] == []
        assert tr["by_kind"][kind]["reason"]


# ---------------------------------------------------------------------------
# Negative control 5: no source files supplied at all, and a missing file --
# both honest NOT_AVAILABLE, never an exception masquerading as "nothing
# found" and never a silently-empty LOADED.
# ---------------------------------------------------------------------------
def test_no_sources_supplied_reports_not_available():
    report = tre.extract_timing_requirements([])
    assert report["status"] == "NOT_AVAILABLE"
    assert report["reason"] == "no source files were supplied"


def test_missing_source_file_reports_not_available_and_lists_it():
    missing_path = str(FIXTURES / "does_not_exist.txt")
    report = tre.extract_timing_requirements([missing_path])
    assert report["status"] == "NOT_AVAILABLE"
    assert missing_path in report["source"]["missing"]


# ---------------------------------------------------------------------------
# Positive path over an RTL comment -- proves extraction is not limited to
# .txt/.md prose, and classify_source() correctly tags the suffix.
# ---------------------------------------------------------------------------
def test_extracts_from_an_rtl_comment_line():
    assert tre.classify_source(RTL_FIXTURE) == "rtl"
    report = tre.extract_timing_requirements([str(RTL_FIXTURE)])
    assert report["status"] == "LOADED"
    hold = report["timing_requirements"]["by_kind"]["HOLD"]["requirements"]
    assert len(hold) == 1
    assert hold[0]["value"] == 1.0
    assert hold[0]["comparison"] == ">="
    assert hold[0]["subject"] == "data-clk"


# ---------------------------------------------------------------------------
# Multiple sources combine cleanly -- facts from both are present, keyed by
# their own real citation.
# ---------------------------------------------------------------------------
def test_multiple_sources_combine():
    report = tre.extract_timing_requirements([str(DOC_FIXTURE), str(RTL_FIXTURE)])
    assert report["status"] == "LOADED"
    assert set(report["source"]["paths"]) == {str(DOC_FIXTURE), str(RTL_FIXTURE)}
    hold = report["timing_requirements"]["by_kind"]["HOLD"]["requirements"]
    assert len(hold) == 2
    evidences = {f["evidence"] for f in hold}
    assert evidences == {f"{DOC_FIXTURE}:5", f"{RTL_FIXTURE}:6"}


# ---------------------------------------------------------------------------
# TimingRequirementFact structurally refuses to be constructed without a
# citation, a real number, a recognized kind, or a recognized comparison --
# the mandated proof that this module cannot be talked into fabricating a
# fact even by a caller building one directly, bypassing the scanner.
# ---------------------------------------------------------------------------
def test_fact_refuses_construction_with_no_citation():
    with pytest.raises(tre.TimingRequirementExtractionError, match="evidence"):
        tre.TimingRequirementFact(
            kind="SETUP", comparison=">=", value=5.0, unit="ns", unit_raw="ns",
            subject=None, text="setup time shall be at least 5 ns", evidence="",
        )


def test_fact_refuses_construction_with_no_text():
    with pytest.raises(tre.TimingRequirementExtractionError, match="text"):
        tre.TimingRequirementFact(
            kind="SETUP", comparison=">=", value=5.0, unit="ns", unit_raw="ns",
            subject=None, text="", evidence="spec.txt:4",
        )


def test_fact_refuses_unrecognized_kind():
    with pytest.raises(tre.TimingRequirementExtractionError, match="kind"):
        tre.TimingRequirementFact(
            kind="THROUGHPUT", comparison=">=", value=5.0, unit="ns", unit_raw="ns",
            subject=None, text="x", evidence="spec.txt:4",
        )


def test_fact_refuses_unrecognized_comparison():
    with pytest.raises(tre.TimingRequirementExtractionError, match="comparison"):
        tre.TimingRequirementFact(
            kind="SETUP", comparison="~=", value=5.0, unit="ns", unit_raw="ns",
            subject=None, text="x", evidence="spec.txt:4",
        )


def test_fact_refuses_missing_value():
    with pytest.raises(tre.TimingRequirementExtractionError, match="value"):
        tre.TimingRequirementFact(
            kind="SETUP", comparison=">=", value=None, unit="ns", unit_raw="ns",
            subject=None, text="x", evidence="spec.txt:4",
        )


def test_fact_refuses_bool_value():
    with pytest.raises(tre.TimingRequirementExtractionError, match="value"):
        tre.TimingRequirementFact(
            kind="SETUP", comparison=">=", value=True, unit="ns", unit_raw="ns",
            subject=None, text="x", evidence="spec.txt:4",
        )


def test_fact_refuses_missing_unit():
    with pytest.raises(tre.TimingRequirementExtractionError, match="unit"):
        tre.TimingRequirementFact(
            kind="SETUP", comparison=">=", value=5.0, unit="", unit_raw="",
            subject=None, text="x", evidence="spec.txt:4",
        )


# ---------------------------------------------------------------------------
# CLI front door, driven as a real subprocess (never imported and called
# in-process, so this proves the `python -m` entry point genuinely works).
# ---------------------------------------------------------------------------
def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "dv_harness.timing_requirement_extraction", *args],
        capture_output=True, text=True,
    )


def test_cli_extract_exits_zero_on_loaded_and_prints_json():
    result = _run_cli("extract", "--sources", str(DOC_FIXTURE), "--json")
    assert result.returncode == 0
    assert '"status": "LOADED"' in result.stdout


def test_cli_extract_exits_nonzero_on_not_available():
    result = _run_cli("extract", "--sources", str(BLANK_FIXTURE))
    assert result.returncode == 2
    assert "NOT_AVAILABLE" in result.stdout


def test_cli_usage_error_exits_two():
    result = _run_cli()
    assert result.returncode == 2
    assert "usage" in result.stderr
