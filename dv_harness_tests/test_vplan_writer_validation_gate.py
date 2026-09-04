"""Tests for tools/vplan/vplan_writer_validation_gate.py -- the gate wired
into dv_harness/gates.py's STAGE_GATES["VPLAN"] alongside spec_coverage_audit
(2026-09-01, vplan-doc-and-wiring-fix). Unlike spec_coverage_audit.py (which
checks a structurally different requirements[] JSON schema and never touches
dv_harness/vplan_writer), this gate calls the real
dv_harness.vplan_writer.build_evidence_context()/validate_items() against
real pattern-dir/dispatcher-file/task-declaration-source evidence on disk --
the same functions and evidence discipline `dv-harness vplan-export` itself
uses.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "vplan" / "vplan_writer_validation_gate.py"


def _make_fake_env(tmp: Path):
    pattern_dir = tmp / "uvm" / "patterns"
    pattern_dir.mkdir(parents=True)
    (pattern_dir / "USB2_bulkin.txt").write_text("bulkin pattern", encoding="utf-8")

    dispatcher_file = tmp / "dv_uvm_pattern_pool.svh"
    dispatcher_file.write_text(
        'case (pattern_name)\n  "USB2_bulkin": run_bulkin();\nendcase\n', encoding="utf-8",
    )

    tests_dir = tmp / "tb" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "usb_bulkin_test.sv").write_text(
        "task automatic usb_bulkin_test();\nendtask\n", encoding="utf-8",
    )
    return pattern_dir, dispatcher_file, tests_dir


def _base_item(**overrides):
    item = {
        "req_id": "USB2-BULK-001", "feature_area": "Bulk Transfers",
        "verification_item": "Bulk IN transfer completes",
        "pattern_name": "USB2_bulkin", "task_name": "usb_bulkin_test",
        "suite": "USB2_sanity", "covered_by": "covered",
        "description": "Directed bulk-in transfer test", "spec_section": "TBD-spec",
        "constraint_items": [], "random_or_directed": "directed", "mode_speed": "HS",
        "instance": "N/A", "checkers_active": ["sb_bulk_data_match"], "notes": "",
        "blocked_on": None, "blocked_reason": None,
    }
    item.update(overrides)
    return item


def _run(payload):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, tmp)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--vplan-validation", tmp.name],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        )
        out = json.loads((r.stdout or "").strip() or "{}")
        return r.returncode, out
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def test_help_smoke():
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=15,
    )
    assert r.returncode == 0
    assert r.stdout.strip()


def test_valid_items_against_real_evidence_pass():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item()],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
        assert out["item_count"] == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_unresolved_pattern_file_fails():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(pattern_name="USB2_nope")],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc != 0
        assert out["status"] == "FAIL"
        assert out["reason"] == "UNRESOLVED_PATTERN_FILE"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_pattern_not_in_dispatcher_fails():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        # A second pattern file exists on disk but was never added to the
        # dispatcher -- real-world case this rule exists to catch.
        (pattern_dir / "USB2_isoc.txt").write_text("isoc pattern", encoding="utf-8")
        rc, out = _run({
            "items": [_base_item(
                req_id="USB2-ISOC-001", pattern_name="USB2_isoc", task_name="usb_bulkin_test",
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc != 0
        assert out["status"] == "FAIL"
        assert out["reason"] == "PATTERN_NOT_IN_DISPATCHER"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_unknown_task_declaration_fails():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(task_name="usb_nonexistent_test")],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc != 0
        assert out["status"] == "FAIL"
        assert out["reason"] == "UNKNOWN_TASK_DECLARATION"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_required_top_level_field_fails_closed():
    rc, out = _run({"items": [_base_item()], "pattern_dir": "somewhere"})
    assert rc == 2
    assert out["status"] == "FAIL"
    assert out["reason"] == "MISSING_REQUIRED_FIELD"
    assert "dispatcher_file" in out["missing"]


def test_empty_items_fails_closed():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 2
        assert out["status"] == "FAIL"
        assert out["reason"] == "MISSING_REQUIRED_FIELD"
        assert "items" in out["missing"]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _add_constraint_declarations(tests_dir: Path):
    """Adds a real SV file declaring `constraint c_bulk_len` under tests_dir,
    evidence for the 4th (constraint-items-exist-in-SV-source, 2026-09-01)
    validation rule."""
    (tests_dir / "constraints.sv").write_text(
        "class usb_bulkin_test extends uvm_test;\n"
        "  constraint c_bulk_len { len inside {[1:512]}; }\n"
        "endclass\n",
        encoding="utf-8",
    )


def test_constraint_items_exist_in_sv_source_passes_when_evidence_supplied():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        _add_constraint_declarations(tests_dir)
        rc, out = _run({
            "items": [_base_item(
                random_or_directed="random", constraint_items=["c_bulk_len"],
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
            "constraint_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_constraint_not_in_sv_source_fails_when_evidence_supplied():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        _add_constraint_declarations(tests_dir)
        rc, out = _run({
            "items": [_base_item(
                random_or_directed="random", constraint_items=["c_totally_made_up"],
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
            "constraint_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 3
        assert out["status"] == "FAIL"
        assert out["reason"] == "CONSTRAINT_NOT_IN_SV_SOURCE"
        assert out["detail"]["constraint_name"] == "c_totally_made_up"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_constraint_rule_skipped_when_no_constraint_evidence_in_payload():
    # No constraint_declaration_sources/known_constraint_names in the
    # payload at all -- an unresolvable-looking constraint name must still
    # PASS, since the 4th rule was never requested (optional, additive).
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(
                random_or_directed="random", constraint_items=["c_anything_goes"],
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_known_constraint_names_bypasses_scanning_in_payload():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(
                random_or_directed="random", constraint_items=["c_custom_only"],
            )],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
            "known_constraint_names": ["c_custom_only"],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_wired_into_vplan_stage_gates():
    from dv_harness.gates import STAGE_GATES
    gate_ids = [g[0] for g in STAGE_GATES["VPLAN"]]
    assert "vplan_writer_validation_gate" in gate_ids
    assert "spec_coverage_audit" in gate_ids


# --- The per-item gap list this gate surfaces (2026-09-04) -------------------
#
# Added with the coverage_gaps payload. Before it, this gate answered only
# "is the plan well-formed" (status/item_count) and its VPLAN stage sibling
# spec_coverage_audit.py answered only an aggregate coverage_percent over a
# different schema -- so the gate pipeline an agent runs at a stage
# transition could never answer "which verification item has no test", even
# though write_vplan_workbook() had always computed exactly that list. These
# drive the REAL gate script as a REAL subprocess, the same way every test
# above does, and assert the list arrives in the JSON gates.py parses into
# GateResult.detail.

def test_gate_reports_which_items_have_no_test_not_only_a_number():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [
                _base_item(),
                _base_item(req_id="USB2-BULK-002", feature_area="Bulk Transfers",
                            verification_item="Bulk IN babble error", covered_by="NOT COVERED",
                            blocked_on="EFFORT", blocked_reason="no error-injection hook yet"),
                _base_item(req_id="USB2-ISO-001", feature_area="Isochronous",
                            verification_item="ISO underrun handling", covered_by="NOT COVERED",
                            blocked_on="INFORMATION", blocked_reason="PHY underrun behavior undocumented"),
                _base_item(req_id="USB2-CTRL-001", feature_area="Control Transfers",
                            verification_item="SETUP stage retry", covered_by="PARTIAL",
                            notes="only the happy path runs today"),
            ],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        assert out["status"] == "PASS"
        gaps = out["coverage_gaps"]

        # Not just a number: every uncovered item is named, individually.
        assert gaps["gap_count"] == 3
        assert [g["req_id"] for g in gaps["gaps_ranked"]] == [
            "USB2-CTRL-001",  # tier 0: PARTIAL
            "USB2-BULK-002",  # tier 1: NOT COVERED / EFFORT
            "USB2-ISO-001",   # tier 2: NOT COVERED / INFORMATION
        ]
        # Each carries the feature it belongs to and a reason a human can act on.
        by_id = {g["req_id"]: g for g in gaps["gaps_ranked"]}
        assert by_id["USB2-ISO-001"]["feature_area"] == "Isochronous"
        assert "PHY underrun behavior undocumented" in by_id["USB2-ISO-001"]["why"]
        assert "no error-injection hook yet" in by_id["USB2-BULK-002"]["why"]
        assert by_id["USB2-CTRL-001"]["blocked_on"] is None

        # The aggregate is still there -- it is now the summary of a list,
        # not the only thing reported.
        assert gaps["total_items"] == 4
        assert gaps["coverage_percent"] == 25.0
        assert gaps["counts_by_state"]["NOT COVERED"] == 2
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_gate_reports_an_empty_gap_list_when_every_item_is_covered():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item()],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        assert out["coverage_gaps"]["gap_count"] == 0
        assert out["coverage_gaps"]["gaps_ranked"] == []
        assert out["coverage_gaps"]["coverage_percent"] == 100.0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_open_gaps_do_not_fail_the_gate():
    """An unclosed vPlan item mid-project is a fact to report, not a
    validation failure -- failing here would only teach people to mark
    items covered to get past the stage."""
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [_base_item(covered_by="NOT COVERED", blocked_on="EFFORT",
                                  blocked_reason="not started")],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0
        assert out["status"] == "PASS"
        assert out["coverage_gaps"]["gap_count"] == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_deferred_items_are_listed_separately_from_open_gaps():
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        rc, out = _run({
            "items": [
                _base_item(),
                _base_item(req_id="USB2-LPM-001", feature_area="Link Power",
                            verification_item="L1 entry/exit", covered_by="DEFERRED",
                            notes="out of scope for this tapeout"),
            ],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert rc == 0, out
        gaps = out["coverage_gaps"]
        assert gaps["gap_count"] == 0
        assert [d["req_id"] for d in gaps["deferred"]] == ["USB2-LPM-001"]
        assert gaps["deferred"][0]["notes"] == "out of scope for this tapeout"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_summarize_coverage_gaps_matches_what_the_workbook_writer_computes():
    """The gate must not be reporting a second, parallel computation -- it is
    the same _rank_gaps() the .xlsx's "Table B -- Gaps ranked" is built from,
    which is what makes the gate's answer and the exported vPlan's answer
    incapable of disagreeing."""
    import openpyxl
    from dv_harness.vplan_writer import (
        build_evidence_context, summarize_coverage_gaps, write_vplan_workbook,
    )
    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        items = [
            _base_item(),
            _base_item(req_id="USB2-BULK-002", verification_item="Bulk IN babble error",
                        covered_by="NOT COVERED", blocked_on="EFFORT",
                        blocked_reason="no error-injection hook yet"),
        ]
        evidence = build_evidence_context(
            pattern_dir=str(pattern_dir), dispatcher_file=str(dispatcher_file),
            task_declaration_sources=[str(tests_dir / "*.sv")],
        )
        out_xlsx = tmp / "vplan.xlsx"
        result = write_vplan_workbook(items, output_path=out_xlsx, evidence=evidence,
                                       protocol="USB2")
        assert summarize_coverage_gaps(items)["gaps_ranked"] == result.gaps_ranked

        # And it is really the list rendered into the workbook a human opens.
        wb = openpyxl.load_workbook(out_xlsx)
        rendered = {str(c.value) for row in wb["coverage_summary"].iter_rows() for c in row}
        assert "USB2-BULK-002" in rendered
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_gap_list_survives_the_real_gates_run_gate_wrapper():
    """The gap list must reach GateResult.detail, not just the script's own
    stdout -- gates.py json-parses that stdout, and detail is what an agent
    at a VPLAN stage transition actually sees."""
    from dv_harness.gates import STAGE_GATES, run_gate

    entry = next(g for g in STAGE_GATES["VPLAN"] if g[0] == "vplan_writer_validation_gate")
    _, script_name, cli_flag = entry

    tmp = Path(tempfile.mkdtemp())
    try:
        pattern_dir, dispatcher_file, tests_dir = _make_fake_env(tmp)
        result = run_gate(ROOT, script_name, cli_flag, {
            "items": [
                _base_item(),
                _base_item(req_id="USB2-ISO-001", feature_area="Isochronous",
                            verification_item="ISO underrun handling", covered_by="NOT COVERED",
                            blocked_on="INFORMATION", blocked_reason="PHY behavior undocumented"),
            ],
            "pattern_dir": str(pattern_dir),
            "dispatcher_file": str(dispatcher_file),
            "task_declaration_sources": [str(tests_dir / "*.sv")],
        })
        assert result.ok is True, result.detail
        gaps = result.detail["coverage_gaps"]
        assert gaps["gap_count"] == 1
        assert gaps["gaps_ranked"][0]["req_id"] == "USB2-ISO-001"
        assert "PHY behavior undocumented" in gaps["gaps_ranked"][0]["why"]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
