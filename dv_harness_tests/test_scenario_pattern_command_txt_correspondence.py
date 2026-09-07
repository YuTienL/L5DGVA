"""Tests for dv_harness/scenario_pattern_command_txt_correspondence.py -- cross-referencing
vip_capability_extraction.py's real VIPScenarioPatternIR declared classes against a real
command.txt/pattern set's real branch_b* (VIP-owned MODEL_TASK_CALL) usages, name-evidence, cited.

Discipline:
  1. Every absence-of-evidence path (no scenario-pattern records, no command files, every command
     file unreadable) reports the whole thing NOT_AVAILABLE -- never a report that fabricates a
     CORRESPONDENCE_NOT_FOUND or NOT_USED_IN_COMMAND_TXT finding from evidence never gathered.
  2. A real command.txt statement whose de_command_style_learning.py-classified primary task
     segment (or a word-boundary argument/text reference) names a real declared class is found and
     cited; a usage naming nothing real is CORRESPONDENCE_NOT_FOUND (a real fabrication-risk
     negative control, the module's central purpose).
  3. A declared class no real branch_b* usage ever names is NOT_USED_IN_COMMAND_TXT, honestly
     distinct from "we never looked".
  4. Both real CLI entry points are driven as real subprocesses.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import de_command_style_learning as dcsl
from dv_harness import scenario_pattern_command_txt_correspondence as spc
from dv_harness import vip_capability_extraction as vce
from dv_harness import vip_symbol_index as vsi

REPO_ROOT = Path(__file__).resolve().parents[1]
VIP_SRC_ROOT = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"
VIP_SRC_BASE = REPO_ROOT / "examples" / "asset_processing" / "inputs"


@pytest.fixture(scope="module")
def demo_scenario_pattern_records():
    """The real svt_demo_base_sequence VIPScenarioPatternIR record, classified by the real,
    unmodified vip_capability_extraction pipeline over the real synthetic VIP fixture this repo
    already ships (the same fixture vip_config_field_usage_coverage.py's own tests reuse)."""
    index = vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)
    report = vce.extract_vip_capabilities(index)
    records = spc.scenario_pattern_records_from_capability_report(report)
    assert [r.class_name for r in records] == ["svt_demo_base_sequence"]
    return records


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _write_capability_report(tmp_path):
    index = vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)
    report = vce.extract_vip_capabilities(index)
    out_dir = tmp_path / "cap_out"
    out_dir.mkdir()
    return vce.write_capability_extraction_report(report, out_dir)


# ---------------------------------------------------------------------------
# 1. absence of evidence -> honest NOT_AVAILABLE, never a fabricated verdict
# ---------------------------------------------------------------------------

def test_no_scenario_pattern_records_reports_not_available(tmp_path):
    cmd = _write(tmp_path, "command.txt", "x = 1;\n")
    report = spc.analyze_scenario_pattern_command_txt_correspondence([], [cmd])
    assert report.status == spc.REPORT_NOT_AVAILABLE
    assert report.reason == "NO_VIP_SCENARIO_PATTERN_IR_RECORDS_SUPPLIED"
    assert report.declared_patterns == []


def test_no_command_files_reports_not_available(demo_scenario_pattern_records):
    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [])
    assert report.status == spc.REPORT_NOT_AVAILABLE
    assert report.reason == "NO_COMMAND_TXT_PATTERN_FILES_SUPPLIED"
    assert report.command_files_scanned == 0


def test_all_unreadable_command_files_reports_not_available(demo_scenario_pattern_records, tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [missing])
    assert report.status == spc.REPORT_NOT_AVAILABLE
    assert report.reason == "NO_COMMAND_TXT_PATTERN_FILE_COULD_BE_READ"
    assert report.command_files_scanned == 0
    assert len(report.unreadable_command_files) == 1
    assert report.unreadable_command_files[0]["path"] == str(missing)


def test_a_bad_path_among_good_ones_is_recorded_and_never_sinks_the_scan(
        demo_scenario_pattern_records, tmp_path):
    missing = tmp_path / "nope.txt"
    good = _write(tmp_path, "good.txt", "x = 1;\n")
    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [missing, good])
    assert report.status == spc.REPORT_ANALYZED
    assert report.command_files_scanned == 1
    assert len(report.unreadable_command_files) == 1
    assert report.unreadable_command_files[0]["path"] == str(missing)


# ---------------------------------------------------------------------------
# 2. real CORRESPONDENCE_CONFIRMED / CORRESPONDENCE_NOT_FOUND classification, cited
# ---------------------------------------------------------------------------

def test_exact_primary_task_segment_match_is_confirmed_and_the_pattern_is_marked_used(
        demo_scenario_pattern_records, tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "`HOST_SEQ.svt_demo_base_sequence();\n")
    # sanity: this really is a real MODEL_TASK_CALL / branch_owner VIP usage before we test
    # this module's own cross-reference logic against it.
    registry = dcsl.build_de_command_registry(cmd)
    assert len(registry.entries) == 1
    entry = registry.entries[0]
    assert entry.kind == dcsl.K_MODEL_TASK_CALL
    assert entry.branch_owner == dcsl.BRANCH_OWNER_VIP
    assert entry.command_name == "`HOST_SEQ.svt_demo_base_sequence"

    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [cmd])
    assert report.status == spc.REPORT_ANALYZED
    assert report.total_branch_b_usages == 1
    assert report.total_confirmed_usages == 1
    assert report.total_unresolved_usages == 0

    usage = report.branch_b_usages[0]
    assert usage.status == spc.USAGE_CORRESPONDENCE_CONFIRMED
    assert usage.matched_class_name == "svt_demo_base_sequence"
    assert usage.match_kind == spc.MATCH_PRIMARY_TASK_SEGMENT_EXACT
    assert usage.reason is None

    pattern = report.declared_patterns[0]
    assert pattern.class_name == "svt_demo_base_sequence"
    assert pattern.status == spc.PATTERN_USED
    assert pattern.reason is None
    assert len(pattern.used_by) == 1
    assert pattern.used_by[0]["command_name"] == "`HOST_SEQ.svt_demo_base_sequence"
    assert pattern.used_by[0]["match_kind"] == spc.MATCH_PRIMARY_TASK_SEGMENT_EXACT


def test_fabricated_sequence_name_is_correspondence_not_found_and_the_real_pattern_stays_unused(
        demo_scenario_pattern_records, tmp_path):
    # A real VIP-branch-shaped command.txt statement (de_command_style_learning.py itself
    # classifies it MODEL_TASK_CALL / branch_owner VIP), but the sequence it names was never
    # classified by vip_capability_extraction.py as a real VIPScenarioPatternIR -- exactly the
    # fabrication-risk case this module exists to catch.
    cmd = _write(tmp_path, "pattern.txt", "`HOST_SEQ.fake_hallucinated_sequence();\n")
    registry = dcsl.build_de_command_registry(cmd)
    entry = registry.entries[0]
    assert entry.kind == dcsl.K_MODEL_TASK_CALL
    assert entry.branch_owner == dcsl.BRANCH_OWNER_VIP

    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [cmd])
    assert report.status == spc.REPORT_ANALYZED
    assert report.total_confirmed_usages == 0
    assert report.total_unresolved_usages == 1

    usage = report.branch_b_usages[0]
    assert usage.status == spc.USAGE_CORRESPONDENCE_NOT_FOUND
    assert usage.matched_class_name is None
    assert usage.reason is not None
    assert "fake_hallucinated_sequence" in usage.reason
    assert usage in report.unresolved_usages()

    pattern = report.declared_patterns[0]
    assert pattern.status == spc.PATTERN_NOT_USED
    assert pattern.reason is not None
    assert "svt_demo_base_sequence" in pattern.reason
    assert pattern in report.unused_patterns()


def test_argument_reference_match_is_confirmed_via_the_weaker_match_kind(
        demo_scenario_pattern_records, tmp_path):
    # The task segment is "run_seq" (not the declared class), but the real class name is passed
    # as an argument -- weaker evidence, still real, cited, and correctly CONFIRMED.
    cmd = _write(tmp_path, "pattern.txt", "`HOST_SEQ.run_seq(svt_demo_base_sequence);\n")
    registry = dcsl.build_de_command_registry(cmd)
    entry = registry.entries[0]
    assert entry.branch_owner == dcsl.BRANCH_OWNER_VIP
    assert spc.extract_primary_task_segment(entry.command_name) == "run_seq"

    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [cmd])
    usage = report.branch_b_usages[0]
    assert usage.status == spc.USAGE_CORRESPONDENCE_CONFIRMED
    assert usage.matched_class_name == "svt_demo_base_sequence"
    assert usage.match_kind == spc.MATCH_TEXT_OR_ARGUMENT_REFERENCE


def test_substring_inside_a_longer_identifier_never_matches(demo_scenario_pattern_records, tmp_path):
    # "svt_demo_base_sequence_v2" genuinely contains "svt_demo_base_sequence" as a substring, but
    # is a DIFFERENT identifier -- word-boundary matching must refuse it.
    cmd = _write(tmp_path, "pattern.txt", "`HOST_SEQ.svt_demo_base_sequence_v2();\n")
    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [cmd])
    usage = report.branch_b_usages[0]
    assert usage.status == spc.USAGE_CORRESPONDENCE_NOT_FOUND


def test_a_non_vip_owned_model_task_call_is_never_treated_as_a_branch_b_usage(
        demo_scenario_pattern_records, tmp_path):
    # A GLOBAL_INIT-shaped model task call -- de_command_style_learning.py itself classifies this
    # branch_owner GLOBAL, never VIP -- must contribute zero branch_b* usages, confirming this
    # module's own real reuse of that module's heuristic rather than a looser scan of its own.
    cmd = _write(tmp_path, "pattern.txt", "`GMODEL.GLOBAL_INIT();\n")
    registry = dcsl.build_de_command_registry(cmd)
    entry = registry.entries[0]
    assert entry.kind == dcsl.K_MODEL_TASK_CALL
    assert entry.branch_owner == dcsl.BRANCH_OWNER_GLOBAL

    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [cmd])
    assert report.status == spc.REPORT_ANALYZED
    assert report.total_branch_b_usages == 0
    assert report.branch_b_usages == []
    # the real declared pattern is still reported, honestly unused (a real scan happened, zero
    # branch_b* usages were found -- distinct from NOT_AVAILABLE, since real files WERE checked).
    pattern = report.declared_patterns[0]
    assert pattern.status == spc.PATTERN_NOT_USED
    # the reason cites the REAL count of branch_b* usages found (zero), not a fabricated claim
    assert "containing 0 real branch_b* (VIP-owned MODEL_TASK_CALL) usage(s)" in pattern.reason


def test_multiple_command_files_are_all_scanned(demo_scenario_pattern_records, tmp_path):
    a = _write(tmp_path, "a.txt", "`HOST_SEQ.svt_demo_base_sequence();\n")
    b = _write(tmp_path, "b.txt", "`HOST_SEQ.fake_seq();\n")
    report = spc.analyze_scenario_pattern_command_txt_correspondence(
        demo_scenario_pattern_records, [a, b])
    assert report.command_files_scanned == 2
    assert report.total_branch_b_usages == 2
    assert report.total_confirmed_usages == 1
    assert report.total_unresolved_usages == 1
    files = {u.source_file for u in report.branch_b_usages}
    assert files == {str(a), str(b)}


def test_class_with_no_class_name_raises(tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "x = 1;\n")
    with pytest.raises(spc.ScenarioPatternCommandTxtCorrespondenceError):
        spc.analyze_scenario_pattern_command_txt_correspondence(
            [{"file": "f.sv", "line": 1}], [cmd])


# ---------------------------------------------------------------------------
# 3. reuse: pulling records out of a real on-disk vip_capability_extraction.json
# ---------------------------------------------------------------------------

def test_scenario_pattern_records_from_capability_report_dict_matches_the_in_memory_report(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    data = json.loads(cap_path.read_text(encoding="utf-8"))
    records = spc.scenario_pattern_records_from_capability_report_dict(data)
    assert [r["class_name"] for r in records] == ["svt_demo_base_sequence"]
    assert records[0]["pattern_kind"] in ("SEQUENCE", "VIRTUAL_SEQUENCE")


# ---------------------------------------------------------------------------
# 4. real CLI entry point
# ---------------------------------------------------------------------------

def test_cli_reports_correspondence_not_found_exit_1(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    cmd = _write(tmp_path, "pattern.txt", "`HOST_SEQ.fake_hallucinated_sequence();\n")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.scenario_pattern_command_txt_correspondence",
         "--capability-report", str(cap_path), "--command-file", str(cmd), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ANALYZED"
    assert payload["total_unresolved_usages"] == 1
    assert payload["total_unused_patterns"] == 1


def test_cli_full_correspondence_exits_0(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    cmd = _write(tmp_path, "pattern.txt", "`HOST_SEQ.svt_demo_base_sequence();\n")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.scenario_pattern_command_txt_correspondence",
         "--capability-report", str(cap_path), "--command-file", str(cmd), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["total_unresolved_usages"] == 0
    assert payload["total_unused_patterns"] == 0


def test_cli_missing_capability_report_exits_2(tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "x = 1;\n")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.scenario_pattern_command_txt_correspondence",
         "--capability-report", str(tmp_path / "nope.json"), "--command-file", str(cmd)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "does not exist" in proc.stdout


def test_cli_no_command_files_exits_2_not_available(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.scenario_pattern_command_txt_correspondence",
         "--capability-report", str(cap_path), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "NOT_AVAILABLE"
    assert payload["reason"] == "NO_COMMAND_TXT_PATTERN_FILES_SUPPLIED"


def test_cli_writes_out_dir_artifact(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    cmd = _write(tmp_path, "pattern.txt", "`HOST_SEQ.svt_demo_base_sequence();\n")
    out_dir = tmp_path / "corr_out"
    out_dir.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.scenario_pattern_command_txt_correspondence",
         "--capability-report", str(cap_path), "--command-file", str(cmd),
         "--out-dir", str(out_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    written = json.loads((out_dir / spc.CORRESPONDENCE_REPORT_NAME).read_text(encoding="utf-8"))
    assert written["total_confirmed_usages"] == 1
