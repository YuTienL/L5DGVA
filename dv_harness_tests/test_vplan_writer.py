"""Tests for dv_harness/vplan_writer -- writes a real, openable vPlan .xlsx
workbook (verification_plan + coverage_summary sheets) from a protocol-
agnostic list of structured verification-item dicts, validated first
against real pattern-dir/dispatcher-file/task-declaration-source evidence.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from openpyxl import load_workbook

from dv_harness import vplan_writer

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixture helpers: a small, realistic fake USB-shaped environment (pattern
# dir + dispatcher file + task-declaration source) plus a matching set of
# VPlanItem dicts.
# ---------------------------------------------------------------------------

def _make_fake_env(tmp: Path):
    pattern_dir = tmp / "uvm" / "patterns"
    pattern_dir.mkdir(parents=True)
    (pattern_dir / "USB2_bulkin.txt").write_text("bulkin pattern", encoding="utf-8")
    (pattern_dir / "USB2_isoc.txt").write_text("isoc pattern", encoding="utf-8")

    dispatcher_file = tmp / "dv_uvm_pattern_pool.svh"
    dispatcher_file.write_text(
        'case (pattern_name)\n'
        '  "USB2_bulkin": run_bulkin();\n'
        '  "USB2_isoc": run_isoc();\n'
        'endcase\n',
        encoding="utf-8",
    )

    tests_dir = tmp / "tb" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "usb_bulkin_test.sv").write_text(
        "class usb_bulkin_test extends uvm_test;\nendclass\n", encoding="utf-8",
    )
    (tests_dir / "usb_isoc_test.sv").write_text(
        "task automatic usb_isoc_test();\nendtask\n", encoding="utf-8",
    )

    evidence = vplan_writer.build_evidence_context(
        pattern_dir=pattern_dir,
        dispatcher_file=dispatcher_file,
        task_declaration_sources=[str(tests_dir / "*.sv")],
    )
    return evidence


def _base_item(**overrides):
    item = {
        "req_id": "USB2-BULK-001",
        "feature_area": "Bulk Transfers",
        "verification_item": "Bulk IN transfer completes",
        "pattern_name": "USB2_bulkin",
        "task_name": "usb_bulkin_test",
        "suite": "USB2_sanity",
        "covered_by": "covered",
        "description": "Directed bulk-in transfer test",
        "spec_section": "TBD-spec",
        "constraint_items": [],
        "random_or_directed": "directed",
        "mode_speed": "HS",
        "instance": "N/A",
        "checkers_active": ["sb_bulk_data_match"],
        "notes": "",
        "blocked_on": None,
        "blocked_reason": None,
    }
    item.update(overrides)
    return item


def _realistic_items():
    return [
        _base_item(
            req_id="USB2-BULK-001", feature_area="Bulk Transfers",
            verification_item="Bulk IN transfer completes",
            pattern_name="USB2_bulkin", task_name="usb_bulkin_test",
            covered_by="covered", checkers_active=["sb_bulk_data_match"],
        ),
        _base_item(
            req_id="USB2-BULK-002", feature_area="Bulk Transfers",
            verification_item="Bulk OUT transfer with random length",
            pattern_name="USB2_bulkin", task_name="usb_bulkin_test",
            covered_by="PARTIAL", random_or_directed="random",
            constraint_items=["c_bulk_len"], checkers_active=["sb_bulk_data_match"],
            notes="need short-packet variant",
        ),
        _base_item(
            req_id="USB2-ISOC-001", feature_area="Isochronous Transfers",
            verification_item="Isoc transfer with random payload",
            pattern_name="USB2_isoc", task_name="usb_isoc_test",
            covered_by="covered", random_or_directed="random",
            constraint_items=["c_isoc_payload"], checkers_active=["sb_isoc_data_match"],
            mode_speed="FS",
        ),
        _base_item(
            # NOT COVERED is not in the {"N/A","DEFERRED"} exemption, so
            # pattern_name/task_name must still cite a real, dispatcher-listed
            # pattern -- the existing isoc pattern runs but doesn't yet cover
            # this specific feedback-endpoint scenario.
            req_id="USB2-ISOC-002", feature_area="Isochronous Transfers",
            verification_item="Isoc feedback endpoint not yet modeled",
            pattern_name="USB2_isoc", task_name="usb_isoc_test", covered_by="NOT COVERED",
            constraint_items=[], checkers_active=[],
            blocked_on="EFFORT", blocked_reason="no VIP sequence yet for feedback EP",
        ),
        _base_item(
            req_id="USB2-ISOC-003", feature_area="Isochronous Transfers",
            verification_item="Isoc error-injection needs spec clarification",
            pattern_name="USB2_isoc", task_name="usb_isoc_test", covered_by="NOT COVERED",
            constraint_items=[], checkers_active=[],
            blocked_on="INFORMATION", blocked_reason="awaiting spec section from IP owner",
        ),
        _base_item(
            req_id="USB2-OTG-001", feature_area="OTG",
            verification_item="OTG role swap",
            pattern_name=None, task_name=None, covered_by="N/A",
            constraint_items=[], checkers_active=[],
            notes="OTG disabled in this DUT config",
        ),
        _base_item(
            req_id="USB2-BC-001", feature_area="Battery Charging",
            verification_item="BC1.2 detection",
            pattern_name=None, task_name=None, covered_by="DEFERRED",
            constraint_items=[], checkers_active=[],
            notes="postponed to next tapeout",
        ),
    ]


# ---------------------------------------------------------------------------
# Realistic multi-row write -> real, openable workbook
# ---------------------------------------------------------------------------

class TestWriteVplanWorkbook:
    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.evidence = _make_fake_env(self.tmp)

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_real_openable_workbook_with_correct_sheets_and_columns(self):
        items = _realistic_items()
        out_path = self.tmp / "out" / "usb_vplan.xlsx"
        result = vplan_writer.write_vplan_workbook(
            items, output_path=out_path, evidence=self.evidence, protocol="USB",
            known_check_names=frozenset({"sb_bulk_data_match", "sb_isoc_data_match"}),
        )
        assert result.path == out_path
        assert out_path.is_file()
        assert result.row_count == len(items)

        wb = load_workbook(str(out_path))
        assert wb.sheetnames == ["verification_plan", "coverage_summary"]

        ws = wb["verification_plan"]
        header = [ws.cell(row=1, column=c).value for c in range(1, 16)]
        assert header == [
            "ID", "Feature area", "Verification item", "testing pattern name",
            "command.txt task name", "suite", "covered by", "testing pattern description",
            "spec section", "constraint items", "random or directed", "mode/speed",
            "instance", "checkers active", "notes",
        ]

        # Row 2 is the first feature-area banner ("A. Bulk Transfers"), row 3
        # is the first real item row -- verify real cell values, not just shape.
        assert ws.cell(row=2, column=1).value == "A. Bulk Transfers"
        assert ws.cell(row=3, column=1).value == "USB2-BULK-001"
        assert ws.cell(row=3, column=4).value == "USB2_bulkin"
        assert ws.cell(row=3, column=7).value == "covered"
        assert ws.cell(row=3, column=7).fill.start_color.rgb == "00C6EFCE"

        assert ws.auto_filter.ref == "A1:O%d" % ws.max_row
        assert ws.freeze_panes == "F2"

        # Second feature-area banner and its row's constraint-items join.
        found_partial_row = None
        for r in range(1, ws.max_row + 1):
            if ws.cell(row=r, column=1).value == "USB2-BULK-002":
                found_partial_row = r
        assert found_partial_row is not None
        assert ws.cell(row=found_partial_row, column=10).value == "c_bulk_len"
        assert ws.cell(row=found_partial_row, column=7).fill.start_color.rgb == "00FFEB9C"

    def test_coverage_summary_counts_and_ranking(self):
        items = _realistic_items()
        out_path = self.tmp / "usb_vplan.xlsx"
        result = vplan_writer.write_vplan_workbook(
            items, output_path=out_path, evidence=self.evidence, protocol="USB",
        )
        # covered: BULK-001, ISOC-001 = 2; PARTIAL: BULK-002 = 1;
        # NOT COVERED: ISOC-002, ISOC-003 = 2; N/A: OTG-001 = 1; DEFERRED: BC-001 = 1
        assert result.counts_by_state == {
            "covered": 2, "PARTIAL": 1, "NOT COVERED": 2, "N/A": 1, "DEFERRED": 1,
        }
        # CREDITED_STATES = {covered, N/A} -> (2+1)/7
        assert result.coverage_percent == pytest.approx(100.0 * 3 / 7)

        # Gap ranking: tier0 (PARTIAL) first, then tier1 (NOT COVERED/EFFORT),
        # then tier2 (NOT COVERED/INFORMATION).
        assert [g["req_id"] for g in result.gaps_ranked] == [
            "USB2-BULK-002", "USB2-ISOC-002", "USB2-ISOC-003",
        ]
        assert [g["rank"] for g in result.gaps_ranked] == [1, 2, 3]
        assert "PARTIAL" in result.gaps_ranked[0]["why"]
        assert "EFFORT" in result.gaps_ranked[1]["why"]
        assert "INFORMATION" in result.gaps_ranked[2]["why"]

        wb = load_workbook(str(out_path))
        ws = wb["coverage_summary"]
        all_values = [
            ws.cell(row=r, column=c).value
            for r in range(1, ws.max_row + 1) for c in range(1, ws.max_column + 1)
        ]
        assert "Table A — Counts by covered-by state" in all_values
        assert "Table B — Gaps ranked" in all_values
        assert "Table C — Deferred (visible, not ranked)" in all_values
        assert "USB2-BC-001" in all_values  # deferred row visible, not in gaps


# ---------------------------------------------------------------------------
# Validation-refusal cases -- each the correct typed error, never a
# partially-written file.
# ---------------------------------------------------------------------------

class TestValidationRefusals:
    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.evidence = _make_fake_env(self.tmp)

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unresolvable_pattern_name_raises_typed_error(self):
        items = [_base_item(pattern_name="USB2_does_not_exist")]
        with pytest.raises(vplan_writer.UnresolvedPatternFileError) as exc_info:
            vplan_writer.validate_items(items, self.evidence)
        e = exc_info.value
        assert e.reason == "UNRESOLVED_PATTERN_FILE"
        assert e.detail["pattern_name"] == "USB2_does_not_exist"
        assert e.detail["req_id"] == "USB2-BULK-001"

    def test_unresolvable_task_name_raises_typed_error(self):
        items = [_base_item(task_name="usb_task_that_does_not_exist")]
        with pytest.raises(vplan_writer.UnknownTaskDeclarationError) as exc_info:
            vplan_writer.validate_items(items, self.evidence)
        e = exc_info.value
        assert e.reason == "UNKNOWN_TASK_DECLARATION"
        assert e.detail["task_name"] == "usb_task_that_does_not_exist"

    def test_pattern_absent_from_dispatcher_raises_typed_error(self):
        # A real file on disk with no dispatcher entry -- evidence context
        # must be (re)built AFTER the file exists, so pattern_files picks it
        # up while dispatcher_patterns still does not.
        (self.tmp / "uvm" / "patterns" / "USB2_no_dispatcher_entry.txt").write_text("x", encoding="utf-8")
        evidence = vplan_writer.build_evidence_context(
            pattern_dir=Path(self.evidence.pattern_dir), dispatcher_file=Path(self.evidence.dispatcher_file),
            task_declaration_sources=[str(self.tmp / "tb" / "tests" / "*.sv")],
        )
        items = [_base_item(pattern_name="USB2_no_dispatcher_entry")]
        with pytest.raises(vplan_writer.PatternNotInDispatcherError) as exc_info:
            vplan_writer.validate_items(items, evidence)
        e = exc_info.value
        assert e.reason == "PATTERN_NOT_IN_DISPATCHER"
        assert e.detail["pattern_name"] == "USB2_no_dispatcher_entry"

    def test_write_refuses_on_validation_failure_no_file_written(self):
        items = [_base_item(pattern_name="USB2_does_not_exist")]
        out_path = self.tmp / "should_not_exist.xlsx"
        with pytest.raises(vplan_writer.UnresolvedPatternFileError):
            vplan_writer.write_vplan_workbook(
                items, output_path=out_path, evidence=self.evidence, protocol="USB",
            )
        assert not out_path.exists()

    def test_unknown_checker_name_raises_when_known_check_names_supplied(self):
        items = [_base_item(checkers_active=["sb_unknown_check"])]
        with pytest.raises(vplan_writer.UnknownCheckerNameError) as exc_info:
            vplan_writer.validate_items(
                items, self.evidence, known_check_names=frozenset({"sb_bulk_data_match"}),
            )
        assert exc_info.value.reason == "UNKNOWN_CHECKER_NAME"

    def test_unknown_checker_name_skipped_when_known_check_names_omitted(self):
        items = [_base_item(checkers_active=["sb_totally_made_up"])]
        vplan_writer.validate_items(items, self.evidence)  # no raise

    def test_missing_required_field_raises_schema_error(self):
        item = _base_item()
        del item["suite"]
        with pytest.raises(vplan_writer.VPlanSchemaError) as exc_info:
            vplan_writer.validate_items([item], self.evidence)
        assert exc_info.value.reason == "MISSING_REQUIRED_FIELD"
        assert exc_info.value.detail["field"] == "suite"

    def test_duplicate_req_id_raises_schema_error(self):
        items = [_base_item(), _base_item()]
        with pytest.raises(vplan_writer.VPlanSchemaError) as exc_info:
            vplan_writer.validate_items(items, self.evidence)
        assert exc_info.value.reason == "DUPLICATE_REQ_ID"

    def test_invalid_covered_by_state_raises_schema_error(self):
        items = [_base_item(covered_by="MOSTLY_COVERED")]
        with pytest.raises(vplan_writer.VPlanSchemaError) as exc_info:
            vplan_writer.validate_items(items, self.evidence)
        assert exc_info.value.reason == "INVALID_COVERED_BY_STATE"

    def test_random_without_constraints_raises_schema_error(self):
        items = [_base_item(random_or_directed="random", constraint_items=[])]
        with pytest.raises(vplan_writer.VPlanSchemaError) as exc_info:
            vplan_writer.validate_items(items, self.evidence)
        assert exc_info.value.reason == "MISSING_CONSTRAINT_EVIDENCE_FOR_RANDOM_PATTERN"

    def test_not_covered_without_blocked_classification_raises_schema_error(self):
        items = [_base_item(
            covered_by="NOT COVERED",
            checkers_active=[], blocked_on=None, blocked_reason=None,
        )]
        with pytest.raises(vplan_writer.VPlanSchemaError) as exc_info:
            vplan_writer.validate_items(items, self.evidence)
        assert exc_info.value.reason == "MISSING_BLOCKED_CLASSIFICATION"

    def test_missing_pattern_for_covered_state_raises_schema_error(self):
        items = [_base_item(pattern_name=None, task_name=None, covered_by="covered")]
        with pytest.raises(vplan_writer.VPlanSchemaError) as exc_info:
            vplan_writer.validate_items(items, self.evidence)
        assert exc_info.value.reason == "MISSING_PATTERN_OR_TASK_FOR_COVERED_STATE"


# ---------------------------------------------------------------------------
# build_evidence_context edge cases
# ---------------------------------------------------------------------------

class TestBuildEvidenceContext:
    def test_empty_pattern_dir_raises_evidence_source_empty(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            empty_pattern_dir = tmp / "patterns"
            empty_pattern_dir.mkdir()
            dispatcher_file = tmp / "disp.svh"
            dispatcher_file.write_text('"X": foo();', encoding="utf-8")
            with pytest.raises(vplan_writer.EvidenceSourceEmptyError) as exc_info:
                vplan_writer.build_evidence_context(
                    pattern_dir=empty_pattern_dir, dispatcher_file=dispatcher_file,
                    known_task_names=frozenset({"x"}),
                )
            assert exc_info.value.detail["which"] == "pattern_files"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_known_task_names_bypasses_scanning(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            evidence = _make_fake_env(tmp)
            evidence2 = vplan_writer.build_evidence_context(
                pattern_dir=Path(evidence.pattern_dir), dispatcher_file=Path(evidence.dispatcher_file),
                known_task_names=frozenset({"my_task"}),
            )
            assert evidence2.declared_tasks == frozenset({"my_task"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Follow-up sheets: reserved keys raise NotImplementedError, never silently
# omitted.
# ---------------------------------------------------------------------------

class TestReservedSheetKeys:
    def test_mode_speed_matrix_raises_not_implemented(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            evidence = _make_fake_env(tmp)
            items = [_base_item()]
            with pytest.raises(NotImplementedError, match="mode_speed_matrix"):
                vplan_writer.write_vplan_workbook(
                    items, output_path=tmp / "out.xlsx", evidence=evidence, protocol="USB",
                    sheets=("verification_plan", "mode_speed_matrix"),
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI subcommand
# ---------------------------------------------------------------------------

class TestCliVplanExport:
    def _run_cli(self, tmp, items_path, out_path, evidence_tmp):
        return subprocess.run(
            [sys.executable, "-m", "dv_harness.cli", "--project-root", str(tmp), "vplan-export",
             str(items_path), "--out", str(out_path), "--protocol", "USB",
             "--pattern-dir", str(evidence_tmp / "uvm" / "patterns"),
             "--dispatcher-file", str(evidence_tmp / "dv_uvm_pattern_pool.svh"),
             "--task-declaration-source", str(evidence_tmp / "tb" / "tests" / "*.sv")],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30, encoding="utf-8",
        )

    def test_cli_writes_workbook(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            evidence_tmp = tmp / "env"
            evidence_tmp.mkdir()
            _make_fake_env(evidence_tmp)
            items_path = tmp / "items.json"
            items_path.write_text(json.dumps(_realistic_items()), encoding="utf-8")
            out_path = tmp / "out.xlsx"
            r = self._run_cli(tmp, items_path, out_path, evidence_tmp)
            assert r.returncode == 0, r.stdout + r.stderr
            assert out_path.is_file()
            payload = json.loads(r.stdout)
            assert payload["row_count"] == len(_realistic_items())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cli_reports_typed_error_on_validation_failure(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            evidence_tmp = tmp / "env"
            evidence_tmp.mkdir()
            _make_fake_env(evidence_tmp)
            items_path = tmp / "items.json"
            items_path.write_text(json.dumps([_base_item(pattern_name="USB2_nope")]), encoding="utf-8")
            out_path = tmp / "out.xlsx"
            r = self._run_cli(tmp, items_path, out_path, evidence_tmp)
            assert r.returncode != 0
            assert "UnresolvedPatternFileError" in r.stdout
            assert not out_path.exists()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
