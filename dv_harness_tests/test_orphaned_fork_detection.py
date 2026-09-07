"""Tests for dv_harness/orphaned_fork_detection.py.

All fixture pattern text below is small and synthetic -- built directly in
this file, never mined from any real project's command.txt/pattern content,
matching this repo's own established convention for
`reference_pattern_audit.py`'s own synthetic fixtures
(`test_reference_pattern_audit.py`'s `synthetic_dir`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dv_harness.orphaned_fork_detection import (
    DEFAULT_DISPATCH_PATTERN,
    DEFAULT_WAIT_PATTERN,
    FILE_UNREADABLE,
    FILE_CLEAN,
    FILE_FINDINGS_FOUND,
    FILE_NOT_APPLICABLE,
    REGION_ALL_DISPATCHES_PAIRED,
    REGION_NEVER_CLOSED,
    REGION_NO_DISPATCH_FOUND,
    REGION_ORPHANED_DISPATCH_FOUND,
    TRAP_CITATION,
    analyze_pattern_directory,
    analyze_pattern_file,
    analyze_pattern_text,
    assert_no_verification_verdict_vocabulary,
    find_branch_b_regions,
    main,
    overall_exit_code,
)
from dv_harness import reference_pattern_audit as rpa


# --- vocabulary hygiene --------------------------------------------------------

def test_default_dispatch_and_wait_patterns_match_the_real_documented_macros():
    assert DEFAULT_DISPATCH_PATTERN.match("`FORK_SEQ")
    assert DEFAULT_WAIT_PATTERN.match("`WAIT_SEQ_ALL")
    assert DEFAULT_WAIT_PATTERN.match("`WAIT_SEQ_ALL_OK")
    # RUN_SEQ is deliberately NOT treated as a dispatch (see module docstring:
    # this codebase's own evidence never proves RUN_SEQ is non-blocking).
    assert not DEFAULT_DISPATCH_PATTERN.match("`RUN_SEQ")
    assert not DEFAULT_WAIT_PATTERN.match("`WAIT_SEQ_ONE")


def test_vocabulary_is_disjoint_from_models_status_and_the_guard_has_real_detection_power():
    # Passes today (the guard already ran once at import and did not raise).
    assert_no_verification_verdict_vocabulary()

    # Prove the guard function itself really inspects the vocabulary rather
    # than trivially passing: a deliberately collided vocabulary must raise.
    import dv_harness.orphaned_fork_detection as ofd
    original = ofd.REGION_STATUSES
    try:
        ofd.REGION_STATUSES = ("PASS",)  # a real dv_harness.models.Status token
        with pytest.raises(AssertionError):
            ofd.assert_no_verification_verdict_vocabulary()
    finally:
        ofd.REGION_STATUSES = original


# --- clean pairing ---------------------------------------------------------------

CLEAN_SINGLE = """\
begin : branch_b0
`FORK_SEQ("usb_bulk_in_seq", p_sequencer);
`WAIT_SEQ_ALL;
end
"""


def test_clean_single_dispatch_paired_by_a_following_wait():
    report = analyze_pattern_text(CLEAN_SINGLE, file_name="clean.txt")
    assert report.status == FILE_CLEAN
    assert len(report.regions) == 1
    region = report.regions[0]
    assert region.branch_label == "branch_b0"
    assert region.status == REGION_ALL_DISPATCHES_PAIRED
    assert region.dispatch_count == 1
    assert region.wait_count == 1
    assert region.findings == []


WAIT_ONCE_COVERS_TWO_DISPATCHES = """\
begin : branch_b0
`FORK_SEQ("seq_a", p_sequencer);
`FORK_SEQ("seq_b", p_sequencer);
`WAIT_SEQ_ALL;
end
"""


def test_one_wait_call_legitimately_pairs_with_several_preceding_dispatches():
    """WAIT_SEQ_ALL joins every currently-outstanding sequence -- this must
    never be flagged as a count mismatch (2 dispatches, 1 wait)."""
    report = analyze_pattern_text(WAIT_ONCE_COVERS_TWO_DISPATCHES, file_name="paired.txt")
    assert report.status == FILE_CLEAN
    region = report.regions[0]
    assert region.status == REGION_ALL_DISPATCHES_PAIRED
    assert region.dispatch_count == 2
    assert region.wait_count == 1
    assert region.findings == []


# --- the real trap: an orphaned dispatch ------------------------------------------

ORPHANED_LAST_DISPATCH = """\
begin : branch_b0
`FORK_SEQ("seq_a", p_sequencer);
`FORK_SEQ("seq_b", p_sequencer);
`WAIT_SEQ_ALL;
`FORK_SEQ("seq_c", p_sequencer);
end
"""


def test_dispatch_after_the_last_wait_is_flagged_orphaned():
    """The exact gap the whole-file R7 count check cannot see: >=1 WAIT_SEQ_ALL
    exists in the file, but a later dispatch has nothing after it."""
    report = analyze_pattern_text(ORPHANED_LAST_DISPATCH, file_name="orphan.txt")
    assert report.status == FILE_FINDINGS_FOUND
    region = report.regions[0]
    assert region.status == REGION_ORPHANED_DISPATCH_FOUND
    assert region.dispatch_count == 3
    assert region.wait_count == 1
    assert len(region.findings) == 1
    finding = region.findings[0]
    assert finding.dispatch.line == 5  # the `FORK_SEQ("seq_c", ...) line
    assert "seq_c" not in finding.reason  # cited by macro/line, never by class-name guess
    assert finding.branch_label == "branch_b0"
    assert TRAP_CITATION in finding.trap_citation
    assert "section 3.5" in finding.trap_citation


ZERO_WAIT_AT_ALL = """\
begin : branch_b0
`FORK_SEQ("seq_a", p_sequencer);
`FORK_SEQ("seq_b", p_sequencer);
end
"""


def test_zero_wait_calls_orphans_every_dispatch():
    report = analyze_pattern_text(ZERO_WAIT_AT_ALL, file_name="none.txt")
    region = report.regions[0]
    assert region.status == REGION_ORPHANED_DISPATCH_FOUND
    assert region.wait_count == 0
    assert len(region.findings) == 2
    assert {f.dispatch.line for f in region.findings} == {2, 3}


# --- the trap's own named point: a higher-layer wait cannot substitute -----------

WAIT_OUTSIDE_THE_REGION = """\
begin : branch_b0
`FORK_SEQ("seq_a", p_sequencer);
end
`WAIT_SEQ_ALL;
"""


def test_a_wait_call_after_the_region_has_already_closed_does_not_pair():
    """Section 3.5's own point, made concrete: 'not something the surrounding
    fork/join at a higher layer can substitute for'. The WAIT_SEQ_ALL here is
    real and present in the file, but it sits AFTER branch_b0's own 'end' --
    it must never be read as pairing the dispatch inside that branch."""
    report = analyze_pattern_text(WAIT_OUTSIDE_THE_REGION, file_name="leaked.txt")
    assert report.status == FILE_FINDINGS_FOUND
    region = report.regions[0]
    assert region.status == REGION_ORPHANED_DISPATCH_FOUND
    assert region.wait_count == 0  # the real WAIT_SEQ_ALL exists in the file but not in-region
    assert len(region.findings) == 1


# --- honest absence: nothing to check / cannot be checked ------------------------

NO_DISPATCH_AT_ALL = """\
begin : branch_b0
`WAIT_SEQ_ALL;
end
"""


def test_a_region_with_no_dispatch_is_trivially_clean_never_a_fabricated_finding():
    report = analyze_pattern_text(NO_DISPATCH_AT_ALL, file_name="nodispatch.txt")
    assert report.status == FILE_CLEAN
    region = report.regions[0]
    assert region.status == REGION_NO_DISPATCH_FOUND
    assert region.dispatch_count == 0
    assert region.findings == []


NO_BRANCH_B_AT_ALL = """\
begin : branch_a0
`CPUWRITE4B(32'h1000_0000, 32'hDEAD_BEEF); //some init
end
"""


def test_a_file_with_no_branch_b_region_is_not_applicable_never_clean_by_omission():
    report = analyze_pattern_text(NO_BRANCH_B_AT_ALL, file_name="noregion.txt")
    assert report.status == FILE_NOT_APPLICABLE
    assert report.regions == []
    assert "no 'begin : branch_b" in report.reason


UNCLOSED_REGION = """\
begin : branch_b0
`FORK_SEQ("seq_a", p_sequencer);
`WAIT_SEQ_ALL;
"""


def test_unclosed_region_is_reported_honestly_and_never_gets_a_fabricated_pairing_verdict():
    """The required negative control: this module refuses to compute a
    pairing conclusion it cannot honestly bound -- a WAIT_SEQ_ALL genuinely
    exists in the text, but with no matching 'end'/'join' the module must
    NOT claim ALL_DISPATCHES_PAIRED (or any pairing verdict at all)."""
    report = analyze_pattern_text(UNCLOSED_REGION, file_name="unclosed.txt")
    assert report.status == FILE_FINDINGS_FOUND
    region = report.regions[0]
    assert region.status == REGION_NEVER_CLOSED
    assert region.end_line is None
    assert region.close_kind is None
    # informational counts are still surfaced, but no pairing verdict/findings
    assert region.dispatch_count == 1
    assert region.wait_count == 1
    assert region.findings == []
    assert region.reason is not None and "not evaluated" in region.reason


# --- multiple regions in one file --------------------------------------------------

TWO_REGIONS_ONE_CLEAN_ONE_ORPHANED = """\
begin : branch_b0
`FORK_SEQ("seq_a", p_sequencer);
`WAIT_SEQ_ALL;
end
begin : branch_b1
`FORK_SEQ("seq_b", p_sequencer);
end
"""


def test_multiple_regions_are_each_evaluated_independently():
    report = analyze_pattern_text(TWO_REGIONS_ONE_CLEAN_ONE_ORPHANED, file_name="mixed.txt")
    assert report.status == FILE_FINDINGS_FOUND
    assert len(report.regions) == 2
    by_label = {r.branch_label: r for r in report.regions}
    assert by_label["branch_b0"].status == REGION_ALL_DISPATCHES_PAIRED
    assert by_label["branch_b1"].status == REGION_ORPHANED_DISPATCH_FOUND


LEGACY_BARE_LABEL = """\
begin : branch_b
`FORK_SEQ("seq_a", p_sequencer);
end
"""


def test_legacy_bare_branch_b_label_is_still_scoped_and_checked():
    """Naming CONFORMANCE is branch_ownership_resolver.py's job, not this
    module's -- a legacy (non-0-indexed) label must still be analyzed."""
    report = analyze_pattern_text(LEGACY_BARE_LABEL, file_name="legacy.txt")
    assert report.status == FILE_FINDINGS_FOUND
    region = report.regions[0]
    assert region.branch_label == "branch_b"
    assert region.status == REGION_ORPHANED_DISPATCH_FOUND


# --- override of the default dispatch/wait macro convention ----------------------

CUSTOM_MACRO_NAMES = """\
begin : branch_b0
`MY_DISPATCH("seq_a", p_sequencer);
end
"""


def test_custom_dispatch_and_wait_patterns_are_honored_not_ignored():
    default_report = analyze_pattern_text(CUSTOM_MACRO_NAMES, file_name="custom.txt")
    assert default_report.regions[0].status == REGION_NO_DISPATCH_FOUND  # default pattern sees nothing

    custom_report = analyze_pattern_text(
        CUSTOM_MACRO_NAMES, file_name="custom.txt",
        dispatch_pattern=re.compile(r"^`MY_DISPATCH$"),
        wait_pattern=re.compile(r"^`MY_WAIT$"))
    region = custom_report.regions[0]
    assert region.status == REGION_ORPHANED_DISPATCH_FOUND
    assert region.dispatch_count == 1


# --- file-level I/O ----------------------------------------------------------------

def test_analyze_pattern_file_reports_blocked_on_a_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    report = analyze_pattern_file(missing)
    assert report.status == FILE_UNREADABLE
    assert "does not exist" in report.reason


def test_analyze_pattern_file_real_file_round_trip(tmp_path):
    path = tmp_path / "real_pattern.txt"
    path.write_text(ORPHANED_LAST_DISPATCH, encoding="utf-8")
    report = analyze_pattern_file(path)
    assert report.status == FILE_FINDINGS_FOUND
    assert report.file == str(path)
    assert report.regions[0].findings[0].dispatch.line == 5


def test_find_branch_b_regions_uses_the_real_reused_block_depth(tmp_path):
    """Direct test of the low-level region locator against a REAL parse from
    reference_pattern_audit.extract_command_statements() (no second parser)."""
    path = tmp_path / "regions.txt"
    path.write_text(TWO_REGIONS_ONE_CLEAN_ONE_ORPHANED, encoding="utf-8")
    statements = rpa.extract_command_statements(path)
    regions = find_branch_b_regions(statements)
    assert [r["branch_label"] for r in regions] == ["branch_b0", "branch_b1"]
    assert regions[0]["close_kind"] == "end"
    assert regions[0]["close_index"] is not None


# --- directory-level rollup ---------------------------------------------------------

@pytest.fixture
def synthetic_dir(tmp_path: Path) -> Path:
    d = tmp_path / "synthetic_patterns"
    d.mkdir()
    (d / "clean.txt").write_text(CLEAN_SINGLE, encoding="utf-8")
    (d / "orphan.txt").write_text(ORPHANED_LAST_DISPATCH, encoding="utf-8")
    (d / "noregion.txt").write_text(NO_BRANCH_B_AT_ALL, encoding="utf-8")
    return d


def test_analyze_pattern_directory_end_to_end(synthetic_dir):
    result = analyze_pattern_directory(synthetic_dir)
    assert result["overall_status"] == FILE_FINDINGS_FOUND
    assert result["orphaned_dispatch_count"] == 1
    assert result["unclosed_region_count"] == 0
    assert len(result["files_scanned"]) == 3
    statuses = {Path(r["file"]).name: r["status"] for r in result["reports"]}
    assert statuses["clean.txt"] == FILE_CLEAN
    assert statuses["orphan.txt"] == FILE_FINDINGS_FOUND
    assert statuses["noregion.txt"] == FILE_NOT_APPLICABLE


def test_analyze_pattern_directory_all_not_applicable(tmp_path):
    d = tmp_path / "empty_of_branch_b"
    d.mkdir()
    (d / "a.txt").write_text(NO_BRANCH_B_AT_ALL, encoding="utf-8")
    result = analyze_pattern_directory(d)
    assert result["overall_status"] == FILE_NOT_APPLICABLE


def test_analyze_pattern_directory_no_matching_files_is_not_applicable(tmp_path):
    d = tmp_path / "nothing_here"
    d.mkdir()
    result = analyze_pattern_directory(d)
    assert result["overall_status"] == FILE_NOT_APPLICABLE
    assert result["reports"] == []


# --- CLI ---------------------------------------------------------------------------

def test_cli_file_mode_json_exit_code(tmp_path, capsys):
    path = tmp_path / "orphan.txt"
    path.write_text(ORPHANED_LAST_DISPATCH, encoding="utf-8")
    code = main(["--file", str(path), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload[0]["status"] == FILE_FINDINGS_FOUND
    assert code == 1


def test_cli_file_mode_clean_exit_code(tmp_path, capsys):
    path = tmp_path / "clean.txt"
    path.write_text(CLEAN_SINGLE, encoding="utf-8")
    code = main(["--file", str(path)])
    out = capsys.readouterr().out
    assert "CLEAN" in out
    assert code == 0


def test_cli_file_mode_blocked_exit_code(tmp_path, capsys):
    missing = tmp_path / "nope.txt"
    code = main(["--file", str(missing)])
    assert code == 2


def test_cli_dir_mode_text_output(synthetic_dir, capsys):
    code = main(["--dir", str(synthetic_dir)])
    out = capsys.readouterr().out
    assert "OVERALL: FINDINGS_FOUND" in out
    assert code == 1


def test_overall_exit_code_helper():
    from dv_harness.orphaned_fork_detection import PatternFileReport
    assert overall_exit_code([PatternFileReport(file="a", status=FILE_CLEAN)]) == 0
    assert overall_exit_code([PatternFileReport(file="a", status=FILE_FINDINGS_FOUND)]) == 1
    assert overall_exit_code([PatternFileReport(file="a", status=FILE_UNREADABLE)]) == 2
