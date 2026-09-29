"""Tests for dv_harness/vip_config_field_usage_coverage.py -- cross-referencing
vip_capability_extraction.py's VIPConfigIR declared config fields against a real
command.txt/pattern set to report EXERCISED vs. DEAD_OR_UNUSED, name-evidence, cited.

Discipline:
  1. Every absence-of-evidence path (no config records, no command files, every
     command file unreadable) reports the whole thing NOT_AVAILABLE -- never a
     report that fabricates DEAD_OR_UNUSED findings from evidence never gathered.
  2. A real command.txt/pattern statement referencing a field's literal name is
     found and cited (file:line + the real statement text); a field with no such
     reference anywhere is DEAD_OR_UNUSED, with an honest reason naming how many
     real files were checked.
  3. Negative controls give the word-boundary matcher its detection power: a
     substring occurrence inside a longer identifier is never counted, and a
     comment-only mention is never counted either.
  4. Both real CLI entry points are driven as real subprocesses.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import vip_capability_extraction as vce
from dv_harness import vip_config_field_usage_coverage as fuc
from dv_harness import vip_symbol_index as vsi

REPO_ROOT = Path(__file__).resolve().parents[1]
VIP_SRC_ROOT = REPO_ROOT / "examples" / "asset_processing" / "inputs" / "vip_src"
VIP_SRC_BASE = REPO_ROOT / "examples" / "asset_processing" / "inputs"


@pytest.fixture(scope="module")
def demo_config_records():
    """The real svt_demo_cfg VIPConfigIR record (fields: enable_protocol_checks,
    max_burst_length, coverage_enable, interface_name), classified by the real,
    unmodified vip_capability_extraction pipeline over the real synthetic VIP
    fixture this repo already ships."""
    index = vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)
    report = vce.extract_vip_capabilities(index)
    records = fuc.config_records_from_capability_report(report)
    assert [r.class_name for r in records] == ["svt_demo_cfg"]
    return records


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. absence of evidence -> honest NOT_AVAILABLE, never a fabricated verdict
# ---------------------------------------------------------------------------

def test_no_config_records_reports_not_available(tmp_path):
    cmd = _write(tmp_path, "command.txt", "x = 1;\n")
    report = fuc.analyze_config_field_usage([], [cmd])
    assert report.status == fuc.REPORT_NOT_AVAILABLE
    assert report.reason == "NO_VIP_CONFIG_IR_RECORDS_SUPPLIED"
    assert report.classes == []


def test_no_command_files_reports_not_available(demo_config_records):
    report = fuc.analyze_config_field_usage(demo_config_records, [])
    assert report.status == fuc.REPORT_NOT_AVAILABLE
    assert report.reason == "NO_COMMAND_TXT_PATTERN_FILES_SUPPLIED"
    assert report.command_files_scanned == 0


def test_all_unreadable_command_files_reports_not_available(demo_config_records, tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    report = fuc.analyze_config_field_usage(demo_config_records, [missing])
    assert report.status == fuc.REPORT_NOT_AVAILABLE
    assert report.reason == "NO_COMMAND_TXT_PATTERN_FILE_COULD_BE_READ"
    assert report.command_files_scanned == 0
    assert len(report.unreadable_command_files) == 1
    assert report.unreadable_command_files[0]["path"] == str(missing)
    assert "does_not_exist" in report.unreadable_command_files[0]["path"]


def test_a_bad_path_among_good_ones_is_recorded_and_never_sinks_the_scan(demo_config_records, tmp_path):
    missing = tmp_path / "nope.txt"
    good = _write(tmp_path, "good.txt", "max_burst_length = 16;\n")
    report = fuc.analyze_config_field_usage(demo_config_records, [missing, good])
    assert report.status == fuc.REPORT_ANALYZED
    assert report.command_files_scanned == 1
    assert len(report.unreadable_command_files) == 1
    assert report.unreadable_command_files[0]["path"] == str(missing)


# ---------------------------------------------------------------------------
# 2. real EXERCISED / DEAD_OR_UNUSED classification, cited
# ---------------------------------------------------------------------------

def test_exercised_field_is_found_with_a_real_citation_and_unmentioned_fields_stay_dead(
        demo_config_records, tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "max_burst_length = 16;\n")
    report = fuc.analyze_config_field_usage(demo_config_records, [cmd])
    assert report.status == fuc.REPORT_ANALYZED
    assert report.command_files_scanned == 1
    assert report.total_fields == 4
    assert report.total_exercised == 1
    assert report.total_dead_or_unused == 3

    cls = report.classes[0]
    assert cls.class_name == "svt_demo_cfg"
    by_name = {f.field_name: f for f in cls.fields}

    hit = by_name["max_burst_length"]
    assert hit.status == fuc.FIELD_EXERCISED
    assert hit.reason is None
    assert hit.evidence == [{"file": str(cmd), "line": 1, "detail": "max_burst_length = 16;"}]

    for dead_name in ("enable_protocol_checks", "coverage_enable", "interface_name"):
        dead = by_name[dead_name]
        assert dead.status == fuc.FIELD_DEAD_OR_UNUSED
        assert dead.evidence == []
        assert dead.reason is not None
        assert "scanned 1 real command.txt/pattern file" in dead.reason
        assert dead_name in dead.reason
    assert report.dead_or_unused_fields() and all(
        f.status == fuc.FIELD_DEAD_OR_UNUSED for f in report.dead_or_unused_fields())


def test_word_boundary_never_matches_a_substring_inside_a_longer_identifier(
        demo_config_records, tmp_path):
    # "coverage_enabled" genuinely contains "coverage_enable" as a substring,
    # but is a DIFFERENT identifier -- the real field must stay DEAD_OR_UNUSED.
    cmd = _write(tmp_path, "pattern.txt", "coverage_enabled = 1;\n")
    report = fuc.analyze_config_field_usage(demo_config_records, [cmd])
    cls = report.classes[0]
    by_name = {f.field_name: f for f in cls.fields}
    assert by_name["coverage_enable"].status == fuc.FIELD_DEAD_OR_UNUSED
    assert by_name["coverage_enable"].evidence == []


def test_prefixed_identifier_never_matches_either(demo_config_records, tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "x_max_burst_length_cfg = 1;\n")
    report = fuc.analyze_config_field_usage(demo_config_records, [cmd])
    cls = report.classes[0]
    by_name = {f.field_name: f for f in cls.fields}
    assert by_name["max_burst_length"].status == fuc.FIELD_DEAD_OR_UNUSED


def test_comment_only_mention_is_never_counted_as_evidence(demo_config_records, tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "x = 1; // interface_name is set elsewhere\n")
    report = fuc.analyze_config_field_usage(demo_config_records, [cmd])
    cls = report.classes[0]
    by_name = {f.field_name: f for f in cls.fields}
    assert by_name["interface_name"].status == fuc.FIELD_DEAD_OR_UNUSED
    assert by_name["interface_name"].evidence == []


def test_evidence_is_bounded_by_max_evidence(demo_config_records, tmp_path):
    lines = "\n".join(f"max_burst_length = {i};" for i in range(6))
    cmd = _write(tmp_path, "pattern.txt", lines + "\n")
    report = fuc.analyze_config_field_usage(demo_config_records, [cmd], max_evidence=2)
    cls = report.classes[0]
    by_name = {f.field_name: f for f in cls.fields}
    hit = by_name["max_burst_length"]
    assert hit.status == fuc.FIELD_EXERCISED
    assert len(hit.evidence) == 2


def test_multiple_command_files_are_all_scanned(demo_config_records, tmp_path):
    a = _write(tmp_path, "a.txt", "enable_protocol_checks = 1;\n")
    b = _write(tmp_path, "b.txt", "interface_name = \"usb\";\n")
    report = fuc.analyze_config_field_usage(demo_config_records, [a, b])
    assert report.command_files_scanned == 2
    cls = report.classes[0]
    by_name = {f.field_name: f for f in cls.fields}
    assert by_name["enable_protocol_checks"].status == fuc.FIELD_EXERCISED
    assert by_name["enable_protocol_checks"].evidence[0]["file"] == str(a)
    assert by_name["interface_name"].status == fuc.FIELD_EXERCISED
    assert by_name["interface_name"].evidence[0]["file"] == str(b)
    assert by_name["coverage_enable"].status == fuc.FIELD_DEAD_OR_UNUSED
    assert by_name["max_burst_length"].status == fuc.FIELD_DEAD_OR_UNUSED


def test_class_with_no_config_fields_declared_reports_not_available(tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "x = 1;\n")
    fake_record = vce.VIPCapabilityRecord(
        ir_type=vce.IR_VIP_CONFIG, class_name="empty_cfg", file="f.sv", line=1,
        base_class="uvm_object", qualification=vce.INFERRED_FROM_NAMING, basis="NAME_ONLY",
        config_fields=[],
    )
    report = fuc.analyze_config_field_usage([fake_record], [cmd])
    assert report.status == fuc.REPORT_NOT_AVAILABLE
    assert report.reason == "VIP_CONFIG_IR_RECORDS_DECLARE_NO_CONFIG_FIELDS"


def test_malformed_record_with_no_class_name_raises(tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "x = 1;\n")
    with pytest.raises(fuc.VipConfigFieldUsageCoverageError):
        fuc.analyze_config_field_usage([{"config_fields": [{"name": "x"}]}], [cmd])


# ---------------------------------------------------------------------------
# 3. reuse: pulling records out of a real on-disk vip_capability_extraction.json
# ---------------------------------------------------------------------------

def test_config_records_from_capability_report_dict_matches_the_in_memory_report(tmp_path):
    index = vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)
    report = vce.extract_vip_capabilities(index)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    vce.write_capability_extraction_report(report, out_dir)
    data = json.loads((out_dir / vce.CAPABILITY_EXTRACTION_REPORT_NAME).read_text(encoding="utf-8"))
    records = fuc.config_records_from_capability_report_dict(data)
    assert [r["class_name"] for r in records] == ["svt_demo_cfg"]
    assert {f["name"] for f in records[0]["config_fields"]} == {
        "enable_protocol_checks", "max_burst_length", "coverage_enable", "interface_name"}


# ---------------------------------------------------------------------------
# 4. real CLI entry point
# ---------------------------------------------------------------------------

def _write_capability_report(tmp_path):
    index = vsi.build_symbol_index([VIP_SRC_ROOT], "demo", relative_to=VIP_SRC_BASE)
    report = vce.extract_vip_capabilities(index)
    out_dir = tmp_path / "cap_out"
    out_dir.mkdir()
    return vce.write_capability_extraction_report(report, out_dir)


def test_cli_reports_dead_or_unused_findings_exit_1(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    cmd = _write(tmp_path, "pattern.txt", "max_burst_length = 16;\n")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_config_field_usage_coverage",
         "--capability-report", str(cap_path), "--command-file", str(cmd), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ANALYZED"
    assert payload["total_exercised"] == 1
    assert payload["total_dead_or_unused"] == 3


def test_cli_all_fields_exercised_exits_0(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    cmd = _write(tmp_path, "pattern.txt", "\n".join([
        "enable_protocol_checks = 1;",
        "max_burst_length = 16;",
        "coverage_enable = 1;",
        "interface_name = \"usb\";",
    ]) + "\n")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_config_field_usage_coverage",
         "--capability-report", str(cap_path), "--command-file", str(cmd), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["total_dead_or_unused"] == 0


def test_cli_missing_capability_report_exits_2(tmp_path):
    cmd = _write(tmp_path, "pattern.txt", "x = 1;\n")
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_config_field_usage_coverage",
         "--capability-report", str(tmp_path / "nope.json"), "--command-file", str(cmd)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "does not exist" in proc.stdout


def test_cli_no_command_files_exits_2_not_available(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_config_field_usage_coverage",
         "--capability-report", str(cap_path), "--json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "NOT_AVAILABLE"
    assert payload["reason"] == "NO_COMMAND_TXT_PATTERN_FILES_SUPPLIED"


def test_cli_writes_out_dir_artifact(tmp_path):
    cap_path = _write_capability_report(tmp_path)
    cmd = _write(tmp_path, "pattern.txt", "max_burst_length = 16;\n")
    out_dir = tmp_path / "usage_out"
    out_dir.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.vip_config_field_usage_coverage",
         "--capability-report", str(cap_path), "--command-file", str(cmd),
         "--out-dir", str(out_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr
    written = json.loads((out_dir / fuc.CONFIG_FIELD_USAGE_REPORT_NAME).read_text(encoding="utf-8"))
    assert written["total_exercised"] == 1
