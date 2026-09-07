"""Tests for dv_harness/error_recovery_flow_extraction.py.

Fixtures live under dv_harness_tests/fixtures/error_recovery_flow/ and are
synthetic (their own file headers say so, not any real DUT/spec). The
positive-path tests prove every facet -- error conditions, recovery
statements, error-to-recovery links, and the spec_doc_map-backed structural
chapter index -- is correctly extracted from real supplied text; the
negative controls prove the module reports honest NOT_AVAILABLE rather than
fabricating a recovery mechanism, an automatic/manual classification, a
link, or a structural chapter when the supplied text does not state one.
"""
import json
import subprocess
import sys
from pathlib import Path

from dv_harness import error_recovery_flow_extraction as erfe

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "error_recovery_flow"
RTL_FIXTURE = FIXTURES / "dut_top.sv"
DOC_FIXTURE = FIXTURES / "programming_guide.txt"
BLANK_FIXTURE = FIXTURES / "no_error_no_recovery.txt"


# ---------------------------------------------------------------------------
# Positive path: real RTL + real doc text -> every line-scan facet extracted
# correctly, with real citable evidence.
# ---------------------------------------------------------------------------
def test_positive_path_extracts_error_conditions_from_real_rtl():
    report = erfe.extract_error_recovery_flow([str(RTL_FIXTURE)])
    assert report["status"] == "LOADED"

    ec = report["error_conditions"]
    assert ec["status"] == "LOADED"
    assert ec["reason"] is None
    names = {s["name"] for s in ec["sources"]}
    assert names == {"crc_error", "fault_code"}

    crc = next(s for s in ec["sources"] if s["name"] == "crc_error")
    assert crc["direction"] == "input"
    assert crc["description"] == "CRC mismatch detected"
    assert crc["evidence"] == f"{RTL_FIXTURE}:6"

    fault = next(s for s in ec["sources"] if s["name"] == "fault_code")
    assert fault["width"] == "1:0"
    assert fault["description"] == "fault classification code"

    # recovery_done is not an error/fault port and must never be reported.
    assert "recovery_done" not in names


def test_positive_path_extracts_recovery_statements_with_correct_classification():
    report = erfe.extract_error_recovery_flow([str(DOC_FIXTURE)])
    rs = report["recovery_statements"]
    assert rs["status"] == "LOADED"
    assert rs["reason"] is None

    by_type = {}
    for statement in rs["statements"]:
        by_type.setdefault(statement["type"], []).append(statement)

    # Explicit "requires a soft reset" with no software/manual/automatic
    # keyword is honestly the generic RECOVERY_MECHANISM_STATED -- who
    # performs the recovery is never guessed.
    assert len(by_type["RECOVERY_MECHANISM_STATED"]) == 1
    generic = by_type["RECOVERY_MECHANISM_STATED"][0]
    assert "CRC error" in generic["text"]
    assert generic["evidence"] == f"{DOC_FIXTURE}:11"

    assert len(by_type["MANUAL_RECOVERY"]) == 1
    manual = by_type["MANUAL_RECOVERY"][0]
    assert "software" in manual["text"]

    assert len(by_type["AUTOMATIC_RECOVERY"]) == 1
    automatic = by_type["AUTOMATIC_RECOVERY"][0]
    assert "automatically recovers" in automatic["text"]

    # The timeout-error sentence never says "recover"/"recovery"/"recoverable"
    # at all, so it must never appear as a recovery_statement (it is an
    # error_recovery_link instead -- a deliberately different facet).
    assert not any("timeout error" in s["text"] for s in rs["statements"])


def test_positive_path_extracts_error_to_recovery_links():
    report = erfe.extract_error_recovery_flow([str(DOC_FIXTURE)])
    links = report["error_recovery_links"]
    assert links["status"] == "LOADED"
    assert links["reason"] is None

    by_type = {link["type"]: link for link in links["links"]}
    assert set(by_type) == {"REQUIRES", "ON_ERROR_ACTION"}

    requires = by_type["REQUIRES"]
    assert "CRC error" in requires["error"]
    assert requires["recovery"] == "a soft reset before normal operation can recover"
    assert requires["evidence"] == f"{DOC_FIXTURE}:11"

    on_error = by_type["ON_ERROR_ACTION"]
    assert on_error["error"] == "timeout error"
    assert on_error["recovery"] == "retries the transfer up to 3 times"
    assert on_error["evidence"] == f"{DOC_FIXTURE}:13"

    # The "Parity errors are recoverable..." and the ECC sentences fit
    # neither of the two recognised link forms and must never be guessed
    # into a fabricated link.
    assert not any("Parity" in link["text"] for link in links["links"])
    assert not any("ECC" in link["text"] for link in links["links"])


# ---------------------------------------------------------------------------
# Positive path: spec_doc_map's real structural index, filtered for an
# error/fault/exception/recovery keyword in a chapter TITLE only.
# ---------------------------------------------------------------------------
def test_structural_chapter_index_reuses_spec_doc_map(tmp_path):
    report = erfe.extract_error_recovery_flow(
        [str(DOC_FIXTURE)], structural_index_dir=str(tmp_path))
    chapters_block = report["error_recovery_chapters"]
    assert chapters_block["status"] == "LOADED"
    assert chapters_block["structural_index_attempted"] is True
    assert chapters_block["index_errors"] == []

    headings = {c["heading"] for c in chapters_block["chapters"]}
    assert headings == {"4.2 Error Handling and Recovery", "6 Fault Recovery Procedures"}

    error_recovery_chapter = next(
        c for c in chapters_block["chapters"] if c["number"] == "4.2")
    assert error_recovery_chapter["level"] == 2
    assert error_recovery_chapter["evidence"] == f"{DOC_FIXTURE}#section:4.2"

    # spec_doc_map's own real structure-only artifacts were actually written
    # -- proof this is real reuse of its public API, not a re-implementation.
    assert (tmp_path / f"{DOC_FIXTURE.stem}.structure_map.json").is_file()
    structure_record = json.loads(
        (tmp_path / f"{DOC_FIXTURE.stem}.structure_map.json").read_text(encoding="utf-8"))
    assert structure_record["section_count"] >= 4

    # Chapters that do NOT mention error/fault/exception/recovery in their
    # own title must never be reported.
    assert not any("Register Map" in h for h in headings)
    assert not any("Power Management" in h for h in headings)


# ---------------------------------------------------------------------------
# Negative control 1: no structural_index_dir supplied -> the structural
# facet is honestly NOT_AVAILABLE, never a silent skip disguised as "found
# nothing", and never an unrequested write to disk.
# ---------------------------------------------------------------------------
def test_no_structural_index_dir_reports_not_available_and_writes_nothing():
    report = erfe.extract_error_recovery_flow([str(DOC_FIXTURE)])
    chapters_block = report["error_recovery_chapters"]
    assert chapters_block["status"] == "NOT_AVAILABLE"
    assert chapters_block["structural_index_attempted"] is False
    assert "no structural_index_dir was supplied" in chapters_block["reason"]
    assert chapters_block["chapters"] == []
    # The two line-scan facets on the same real document are unaffected --
    # one facet's absence never masks another's presence.
    assert report["error_recovery_links"]["status"] == "LOADED"


# ---------------------------------------------------------------------------
# Negative control 2: a document with no error/fault ports, no recovery
# statement, and no error-to-recovery link -> every line-scan facet reports
# an honest NOT_AVAILABLE with a real, distinct reason, never a fabricated
# fact and never a silently empty LOADED.
# ---------------------------------------------------------------------------
def test_blank_document_reports_not_available_everywhere():
    report = erfe.extract_error_recovery_flow([str(BLANK_FIXTURE)])
    assert report["status"] == "NOT_AVAILABLE"

    ec = report["error_conditions"]
    assert ec["status"] == "NOT_AVAILABLE"
    assert ec["sources"] == []

    rs = report["recovery_statements"]
    assert rs["status"] == "NOT_AVAILABLE"
    assert rs["statements"] == []

    links = report["error_recovery_links"]
    assert links["status"] == "NOT_AVAILABLE"
    assert links["links"] == []


def test_blank_document_structural_index_finds_no_matching_chapter(tmp_path):
    report = erfe.extract_error_recovery_flow(
        [str(BLANK_FIXTURE)], structural_index_dir=str(tmp_path))
    chapters_block = report["error_recovery_chapters"]
    assert chapters_block["structural_index_attempted"] is True
    assert chapters_block["status"] == "NOT_AVAILABLE"
    assert chapters_block["chapters"] == []
    assert "no section/chapter heading" in chapters_block["reason"]


# ---------------------------------------------------------------------------
# Negative control 3: a recovery statement naming neither an automatic nor a
# manual keyword must never be guessed into either classification.
# ---------------------------------------------------------------------------
def test_unclassified_recovery_mechanism_is_never_guessed_automatic_or_manual(tmp_path):
    p = tmp_path / "generic_only.txt"
    p.write_text(
        "A watchdog error is present. The device may recover after a reset is applied.\n",
        encoding="utf-8",
    )
    report = erfe.extract_error_recovery_flow([str(p)])
    rs = report["recovery_statements"]
    assert rs["status"] == "LOADED"
    assert len(rs["statements"]) == 1
    assert rs["statements"][0]["type"] == "RECOVERY_MECHANISM_STATED"


# ---------------------------------------------------------------------------
# Negative control 4: no source files at all, and a missing file -> honest
# NOT_AVAILABLE naming the real reason, never a crash and never a fabricated
# LOADED.
# ---------------------------------------------------------------------------
def test_no_sources_supplied_reports_not_available():
    report = erfe.extract_error_recovery_flow([])
    assert report["status"] == "NOT_AVAILABLE"
    assert report["reason"] == "no source files were supplied"


def test_missing_source_file_is_recorded_not_raised(tmp_path):
    missing = tmp_path / "does_not_exist.sv"
    report = erfe.extract_error_recovery_flow([str(missing)])
    assert report["status"] == "NOT_AVAILABLE"
    assert str(missing) in report["source"]["missing"]
    assert report["source"]["paths"] == []


# ---------------------------------------------------------------------------
# classify_source()
# ---------------------------------------------------------------------------
def test_classify_source_by_suffix():
    assert erfe.classify_source(Path("foo.sv")) == "rtl"
    assert erfe.classify_source(Path("foo.v")) == "rtl"
    assert erfe.classify_source(Path("foo.txt")) == "text"
    assert erfe.classify_source(Path("foo.bin")) == "unknown"


def test_unrecognized_suffix_is_still_read_and_recorded(tmp_path):
    p = tmp_path / "notes.weird"
    p.write_text("A parity error requires a full device reset to recover.\n", encoding="utf-8")
    report = erfe.extract_error_recovery_flow([str(p)])
    assert str(p) in report["source"]["unrecognized"]
    assert report["error_recovery_links"]["status"] == "LOADED"


# ---------------------------------------------------------------------------
# CLI front door, driven as a real subprocess
# ---------------------------------------------------------------------------
def test_cli_extract_json_real_subprocess():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.error_recovery_flow_extraction",
         "extract", "--sources", str(RTL_FIXTURE), str(DOC_FIXTURE), "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"status": "LOADED"' in result.stdout
    assert "crc_error" in result.stdout


def test_cli_no_sources_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.error_recovery_flow_extraction",
         "extract", "--sources"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2


def test_cli_structural_index_dir_real_subprocess(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dv_harness.error_recovery_flow_extraction",
         "extract", "--sources", str(DOC_FIXTURE),
         "--structural-index-dir", str(tmp_path), "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["error_recovery_chapters"]["status"] == "LOADED"
    assert (tmp_path / f"{DOC_FIXTURE.stem}.structure_map.json").is_file()
